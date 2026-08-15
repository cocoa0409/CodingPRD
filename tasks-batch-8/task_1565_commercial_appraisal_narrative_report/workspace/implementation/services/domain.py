from datetime import timedelta

from db import store, new_rec, touch, add_years
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE
from services import calc

REPORT_NONTERMINAL_STATES = (
    "DRAFTING",
    "INTERNAL_REVIEW",
    "REVIEWED",
    "CLIENT_REVIEW",
    "REVISION_REQUESTED",
    "FINAL",
    "SIGNED",
    "SUSPENDED",
)


def _get(coll, rid, label):
    rec = coll.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{label} not found")
    return rec


def get_client(rid):
    return _get(store.clients, rid, "Client")


def get_appraiser(rid):
    return _get(store.appraisers, rid, "Appraiser")


def get_engagement(rid):
    return _get(store.engagements, rid, "Engagement")


def get_submission(rid):
    return _get(store.submissions, rid, "DataSubmission")


def get_approach(rid):
    return _get(store.approaches, rid, "ValuationApproach")


def get_comparable(rid):
    return _get(store.comparables, rid, "ComparableSale")


def get_report(rid):
    return _get(store.reports, rid, "Report")


def get_revision_request(rid):
    return _get(store.revision_requests, rid, "RevisionRequest")


def get_retention_record(rid):
    return _get(store.retention_records, rid, "RetentionRecord")


def engagement_of(rec):
    return store.engagements[rec["engagement_id"]]


def engagement_of_report(report):
    return store.engagements[report["engagement_id"]]


def retention_of_engagement(engagement_id):
    for rec in store.retention_records.values():
        if rec["engagement_id"] == engagement_id:
            return rec
    return None


def reports_of(engagement_id):
    return [r for r in store.reports.values() if r["engagement_id"] == engagement_id]


def supersede_reports(engagement_id):
    for r in reports_of(engagement_id):
        if r["status"] in REPORT_NONTERMINAL_STATES:
            r["status"] = "SUPERSEDED"
            touch(r)


def create_report_version(eng):
    existing = reports_of(eng["id"])
    superseded = [r for r in existing if r["status"] in REPORT_NONTERMINAL_STATES]
    supersedes_id = None
    if superseded:
        supersedes_id = max(superseded, key=lambda r: r["report_version_no"])["id"]
    for r in superseded:
        r["status"] = "SUPERSEDED"
        touch(r)
    version_no = max([r["report_version_no"] for r in existing], default=0) + 1
    report = new_rec(
        {
            "engagement_id": eng["id"],
            "report_version_no": version_no,
            "supersedes_report_id": supersedes_id,
            "value_conclusion_cents": None,
            "review_cycle_count": 0,
            "signer_appraiser_id": None,
            "pre_hold_status": None,
            "issued_to_client_at": None,
            "signed_at": None,
            "delivered_at": None,
            "status": "DRAFTING",
        }
    )
    store.reports[report["id"]] = report
    touch(eng)
    return report


def complete_engagement(eng):
    """Delivery cascade: engagement -> COMPLETED; client billed and tier
    recomputed; RetentionRecord created; workfile submissions LOCKED."""
    eng["status"] = "COMPLETED"
    touch(eng)
    client = store.clients[eng["client_id"]]
    client["total_billed_cents"] += eng["final_fee_cents"]
    client["volume_discount_tier"] = calc.volume_discount_tier(
        client["total_billed_cents"]
    )
    touch(client)
    completed_date = store.clock.replace(hour=0, minute=0, second=0, microsecond=0)
    base = add_years(completed_date, 5)
    rec = new_rec(
        {
            "engagement_id": eng["id"],
            "completed_date": completed_date,
            "base_retain_until_date": base,
            "litigation_hold_placed_at": None,
            "litigation_released_at": None,
            "litigation_matter_reference": None,
            "retain_until_date": base,
            "status": "ACTIVE",
        }
    )
    store.retention_records[rec["id"]] = rec
    for sub in store.submissions.values():
        if sub["engagement_id"] == eng["id"] and sub["status"] in (
            "SUBMITTED",
            "ACCEPTED",
        ):
            sub["status"] = "LOCKED"
            touch(sub)
    return rec


def place_litigation_hold(eng, matter_reference):
    if eng["status"] == "IN_PROGRESS":
        eng["status"] = "LITIGATION_HOLD"
        eng["litigation_matter_reference"] = matter_reference
        touch(eng)
        for r in reports_of(eng["id"]):
            if r["status"] in REPORT_NONTERMINAL_STATES and r["status"] != "SUSPENDED":
                r["pre_hold_status"] = r["status"]
                r["status"] = "SUSPENDED"
                touch(r)
                for rr in store.revision_requests.values():
                    if rr["report_id"] == r["id"] and rr["status"] == "OPEN":
                        rr["status"] = "ESCALATED"
                        touch(rr)
    elif eng["status"] == "COMPLETED":
        rec = retention_of_engagement(eng["id"])
        if rec is None or rec["status"] != "ACTIVE":
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Retention record is not in a state that accepts a litigation hold",
            )
        rec["status"] = "LITIGATION_HOLD"
        rec["litigation_hold_placed_at"] = store.clock
        rec["litigation_matter_reference"] = matter_reference
        rec["retain_until_date"] = None
        touch(rec)
    else:
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Engagement is not in a state that accepts a litigation hold",
        )


def release_litigation_hold(eng):
    if eng["status"] == "LITIGATION_HOLD":
        eng["status"] = "IN_PROGRESS"
        eng["litigation_matter_reference"] = None
        touch(eng)
        for r in reports_of(eng["id"]):
            if r["status"] == "SUSPENDED":
                r["status"] = r["pre_hold_status"]
                r["pre_hold_status"] = None
                touch(r)
    elif eng["status"] == "COMPLETED":
        rec = retention_of_engagement(eng["id"])
        if rec is None or rec["status"] != "LITIGATION_HOLD":
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Retention record is not under a litigation hold",
            )
        rec["status"] = "ACTIVE"
        rec["litigation_released_at"] = store.clock
        released_date = store.clock.replace(hour=0, minute=0, second=0, microsecond=0)
        rec["retain_until_date"] = max(
            rec["base_retain_until_date"], add_years(released_date, 2)
        )
        touch(rec)
    else:
        raise ApiError(
            ERR_INVALID_STATE, 409, "Engagement is not under a litigation hold"
        )


def author_has_overlap(eng):
    """Half-open [accepted_at, due_date) window overlap against the author's
    other active engagements (IN_PROGRESS or LITIGATION_HOLD)."""
    new_start = store.clock
    new_end = new_start + timedelta(days=eng["requested_turnaround_days"])
    for other in store.engagements.values():
        if other["id"] == eng["id"]:
            continue
        if other["author_appraiser_id"] != eng["author_appraiser_id"]:
            continue
        if other["status"] not in ("IN_PROGRESS", "LITIGATION_HOLD"):
            continue
        if other["accepted_at"] < new_end and new_start < other["due_date"]:
            return True
    return False
