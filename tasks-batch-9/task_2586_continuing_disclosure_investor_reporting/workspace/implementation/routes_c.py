"""Listed-event notices and the repository submission surface."""
from flask import Blueprint, g

import calc
import domain
from core import (ALL_ROLES, DB, Obj, ROLE_COMPLIANCE_REVIEWER,
                  ROLE_DISCLOSURE_OFFICER, ROLE_DISSEMINATION_AGENT, body,
                  bump, clock_stamp, endpoint, fail, fk, listing, must_get,
                  new_row, touch, undertaking_for_issue, vdate, venum, vint,
                  vstr)
from routes_a import guard_notice_occurrence

bp = Blueprint("routes_c", __name__)

EVENT_TYPES = ("PRINCIPAL_PAYMENT_DELINQUENCY", "RATING_CHANGE", "DEFEASANCE",
               "BOND_CALL", "UNSCHEDULED_DRAW_ON_RESERVE", "TRUSTEE_SUBSTITUTION",
               "FINANCIAL_OBLIGATION_INCURRENCE", "MERGER_OR_SALE")
FILING_TYPES = ("ANNUAL_REPORT", "MATERIAL_EVENT_NOTICE", "FAILURE_TO_FILE_NOTICE",
                "VOLUNTARY_FINANCIAL_OBLIGATION")
LIVE_FILING_STATUSES = ("DRAFT", "SUBMITTED", "CONFIRMED")

SUBJECT_FIELD = {
    "ANNUAL_REPORT": "cycle_id",
    "FAILURE_TO_FILE_NOTICE": "cycle_id",
    "MATERIAL_EVENT_NOTICE": "material_event_id",
    "VOLUNTARY_FINANCIAL_OBLIGATION": "direct_placement_id",
}
FILEABLE_SUBJECT_STATUS = {
    "ANNUAL_REPORT": ("READY_TO_FILE",),
    "FAILURE_TO_FILE_NOTICE": ("DELINQUENT",),
    "MATERIAL_EVENT_NOTICE": ("MATERIAL",),
    "VOLUNTARY_FINANCIAL_OBLIGATION": ("DISCLOSURE_REQUIRED",),
}
DISCHARGED_SUBJECT_STATUS = {
    "ANNUAL_REPORT": ("FILED_TIMELY", "FILED_LATE"),
    "FAILURE_TO_FILE_NOTICE": ("FILED_TIMELY", "FILED_LATE"),
    "MATERIAL_EVENT_NOTICE": ("FILED_TIMELY", "FILED_LATE"),
    "VOLUNTARY_FINANCIAL_OBLIGATION": ("DISCLOSED",),
}


# ------------------------------------------------------ material event notices
@bp.post("/disclosure/material-event-notices")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def create_notice():
    data = body()
    issue = fk("bond_issues", data, "issue_id")
    placement = fk("placements", data, "financial_obligation_ref")
    if issue is None:
        fail("ERR_INVALID_REQUEST", "issue_id is required")
    event_type = venum(data, "event_type", EVENT_TYPES)
    occurrence_date = vdate(data, "occurrence_date")
    if issue["status"] != "OUTSTANDING":
        fail("ERR_ISSUE_NOT_OUTSTANDING", "the issue is not OUTSTANDING")
    guard_notice_occurrence(issue["id"], event_type, occurrence_date)
    notice = domain.create_notice(
        issue["id"], event_type, occurrence_date, g.user_id,
        financial_obligation_ref=placement["id"] if placement else None)
    domain.recompute_open_material_event_count(issue)
    domain.recompute_open_obligation_count(undertaking_for_issue(issue["id"]))
    return Obj(notice, 201)


@bp.get("/disclosure/material-event-notices/<row_id>")
@endpoint(ALL_ROLES)
def get_notice(row_id):
    return Obj(must_get("notices", row_id))


@bp.get("/disclosure/material-event-notices")
@endpoint(ALL_ROLES)
def list_notices():
    return listing(DB.notices.values(),
                   {"issue_id": "issue_id",
                    "financial_obligation_ref": "financial_obligation_ref",
                    "filed_filing_id": "filed_filing_id",
                    "status": "status",
                    "event_type": "event_type"})


@bp.post("/disclosure/material-event-notices/<row_id>/determine")
@endpoint([ROLE_COMPLIANCE_REVIEWER])
def determine_notice(row_id):
    notice = must_get("notices", row_id)
    data = body()
    determination = venum(data, "determination", ("MATERIAL", "NOT_MATERIAL"))
    note = vstr(data, "determination_note", required=False, max_len=500)
    if notice["status"] != "DETERMINATION_PENDING":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a DETERMINATION_PENDING notice may be determined")
    if determination == "NOT_MATERIAL" and notice["per_se_material"]:
        fail("ERR_PER_SE_EVENT_IS_MATERIAL",
             "a per-se listed event can never be determined immaterial")
    touch(notice)
    notice["status"] = "MATERIAL" if determination == "MATERIAL" else "NOT_MATERIAL"
    notice["determined_by_user_id"] = g.user_id
    notice["determined_at"] = clock_stamp()
    if note is not None:
        notice["determination_note"] = note
    issue = DB.bond_issues.get(notice["issue_id"])
    domain.recompute_open_material_event_count(issue)
    domain.recompute_open_obligation_count(undertaking_for_issue(notice["issue_id"]))
    return Obj(notice)


# ------------------------------------------------------------------- filings
SUBJECT_TABLE = {"cycle_id": "cycles",
                 "material_event_id": "notices",
                 "direct_placement_id": "placements"}


def _subject_row(filing):
    field = SUBJECT_FIELD[filing["filing_type"]]
    row_id = filing[field]
    return DB.__dict__[SUBJECT_TABLE[field]].get(row_id) if row_id else None


def _subject_issue_id(field, subject):
    if subject is None:
        return None
    if field == "cycle_id":
        undertaking = DB.undertakings.get(subject["undertaking_id"])
        return undertaking["issue_id"] if undertaking else None
    return subject["issue_id"]


def _subject_undertaking(filing):
    subject = _subject_row(filing)
    if subject is None:
        return None
    if SUBJECT_FIELD[filing["filing_type"]] == "cycle_id":
        return DB.undertakings.get(subject["undertaking_id"])
    return undertaking_for_issue(subject["issue_id"])


@bp.post("/disclosure/filings")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def create_filing():
    data = body()
    issue = fk("bond_issues", data, "issue_id")
    cycle = fk("cycles", data, "cycle_id")
    notice = fk("notices", data, "material_event_id")
    placement = fk("placements", data, "direct_placement_id")
    target = fk("filings", data, "supersedes_filing_id")
    if issue is None:
        fail("ERR_INVALID_REQUEST", "issue_id is required")
    filing_type = venum(data, "filing_type", FILING_TYPES)
    expected_version = vint(data, "expected_issue_version", minimum=0)
    correction_reason = vstr(data, "correction_reason", required=False, max_len=500)
    # rule 7 — optimistic concurrency on the parent issue
    if expected_version != issue["version"]:
        fail("ERR_ISSUE_VERSION_STALE",
             "expected_issue_version %s does not match the issue's current version %s"
             % (expected_version, issue["version"]))
    # rule 9 — issue gate
    if issue["status"] != "OUTSTANDING":
        fail("ERR_ISSUE_NOT_OUTSTANDING", "the issue is not OUTSTANDING")
    # rule 28 — subject exclusivity, type agreement, issue match, subject state
    supplied = [(field, row) for field, row in (("cycle_id", cycle),
                                                ("material_event_id", notice),
                                                ("direct_placement_id", placement))
                if row is not None]
    if len(supplied) != 1:
        fail("ERR_FILING_SUBJECT_MISMATCH",
             "exactly one of cycle_id, material_event_id or direct_placement_id "
             "must be supplied")
    subject_field, subject = supplied[0]
    if subject_field != SUBJECT_FIELD[filing_type]:
        fail("ERR_FILING_SUBJECT_MISMATCH",
             "%s takes %s" % (filing_type, SUBJECT_FIELD[filing_type]))
    if _subject_issue_id(subject_field, subject) != issue["id"]:
        fail("ERR_FILING_SUBJECT_MISMATCH",
             "issue_id does not match the subject's owning issue")
    correcting = target is not None
    allowed = (DISCHARGED_SUBJECT_STATUS if correcting
               else FILEABLE_SUBJECT_STATUS)[filing_type]
    if subject["status"] not in allowed:
        fail("ERR_FILING_SUBJECT_MISMATCH",
             "the subject is in status %s; expected one of %s"
             % (subject["status"], ", ".join(allowed)))
    # rule 29 — one live filing per four-field subject tuple
    tuple_fields = (filing_type,
                    cycle["id"] if cycle else None,
                    notice["id"] if notice else None,
                    placement["id"] if placement else None)
    for existing in DB.filings.values():
        if existing["status"] not in LIVE_FILING_STATUSES:
            continue
        if (existing["filing_type"], existing["cycle_id"],
                existing["material_event_id"],
                existing["direct_placement_id"]) != tuple_fields:
            continue
        if correcting and existing["id"] == target["id"] \
                and existing["status"] == "CONFIRMED":
            continue
        fail("ERR_SUBJECT_ALREADY_FILED",
             "a live filing already carries this subject")
    # rule 30 — supersede-target validity
    if correcting:
        if target["status"] != "CONFIRMED" \
                or target["superseded_by_filing_id"] is not None \
                or target[subject_field] != subject["id"]:
            fail("ERR_SUPERSEDE_TARGET_INVALID",
                 "the supersede target must be a CONFIRMED filing of the same "
                 "subject that is not already superseded")
    # rule 33 — a correcting draft must carry a correction reason
    if correcting and (correction_reason is None or correction_reason.strip() == ""):
        fail("ERR_CORRECTION_REASON_REQUIRED",
             "a correcting filing requires a non-empty correction_reason")
    row = new_row({
        "issue_id": issue["id"],
        "filing_type": filing_type,
        "cycle_id": cycle["id"] if cycle else None,
        "material_event_id": notice["id"] if notice else None,
        "direct_placement_id": placement["id"] if placement else None,
        "status": "DRAFT",
        "submission_attempt_count": 0,
        "submitted_at": None,
        "submitted_by_user_id": None,
        "submitting_engagement_id": None,
        "repository_receipt_id": None,
        "repository_confirmed_at": None,
        "rejection_reason": None,
        "supersedes_filing_id": target["id"] if target else None,
        "superseded_by_filing_id": None,
        "correction_reason": correction_reason,
    })
    DB.filings[row["id"]] = row
    bump(issue)  # the draft is guarded on the parent issue
    return Obj(row, 201)


@bp.get("/disclosure/filings/<row_id>")
@endpoint(ALL_ROLES)
def get_filing(row_id):
    return Obj(must_get("filings", row_id))


@bp.get("/disclosure/filings")
@endpoint(ALL_ROLES)
def list_filings():
    return listing(DB.filings.values(),
                   {"issue_id": "issue_id",
                    "cycle_id": "cycle_id",
                    "material_event_id": "material_event_id",
                    "direct_placement_id": "direct_placement_id",
                    "supersedes_filing_id": "supersedes_filing_id",
                    "superseded_by_filing_id": "superseded_by_filing_id",
                    "submitting_engagement_id": "submitting_engagement_id",
                    "filing_type": "filing_type",
                    "status": "status"})


# ------------------------------------------- the repository submission surface
def _engagement_for_submit(filing):
    """Rule 6, submit arm: X-User-ID resolves to an engagement of the
    undertaking that owns the filing's subject."""
    engagement = DB.engagements.get(g.user_id)
    undertaking = _subject_undertaking(filing)
    if engagement is None or undertaking is None \
            or engagement["undertaking_id"] != undertaking["id"]:
        fail("ERR_AGENT_NOT_ENGAGED",
             "the acting agent is not engaged on this undertaking")
    return engagement


def _engagement_for_answer(filing):
    """Rule 6, confirm/reject/resubmit arm: X-User-ID is the submitting agent."""
    engagement = DB.engagements.get(g.user_id)
    if engagement is None or filing["submitting_engagement_id"] != engagement["id"]:
        fail("ERR_AGENT_NOT_ENGAGED",
             "only the agent that submitted this filing may carry the "
             "repository's answer back")
    return engagement


def _require_active_engagement(engagement):
    if engagement["status"] != "ACTIVE":
        fail("ERR_ENGAGEMENT_NOT_ACTIVE", "the engagement is not ACTIVE")


def _require_attempt_headroom(filing):
    if filing["submission_attempt_count"] + 1 > calc.MAX_SUBMISSION_ATTEMPTS:
        fail("ERR_SUBMISSION_ATTEMPTS_EXHAUSTED",
             "at most %d submissions are permitted on one filing"
             % calc.MAX_SUBMISSION_ATTEMPTS)


def _drive_subject_into_progress(filing):
    if filing["supersedes_filing_id"] is not None:
        return  # a correction leaves the already-discharged subject alone
    subject = _subject_row(filing)
    if subject is None:
        return
    if filing["filing_type"] == "ANNUAL_REPORT" and subject["status"] == "READY_TO_FILE":
        touch(subject)
        subject["status"] = "FILING_IN_PROGRESS"
    elif filing["filing_type"] == "MATERIAL_EVENT_NOTICE" \
            and subject["status"] == "MATERIAL":
        touch(subject)
        subject["status"] = "FILING_IN_PROGRESS"


def _record_submission(filing, engagement):
    touch(filing)
    filing["status"] = "SUBMITTED"
    filing["submitted_at"] = clock_stamp()
    filing["submitted_by_user_id"] = g.user_id
    filing["submitting_engagement_id"] = engagement["id"]
    filing["submission_attempt_count"] += 1
    filing["rejection_reason"] = None
    _drive_subject_into_progress(filing)
    undertaking = _subject_undertaking(filing)
    domain.recompute_open_obligation_count(undertaking)
    domain.recompute_open_material_event_count(DB.bond_issues.get(filing["issue_id"]))


@bp.post("/disclosure/filings/<row_id>/submit")
@endpoint([ROLE_DISSEMINATION_AGENT])
def submit_filing(row_id):
    filing = must_get("filings", row_id)
    engagement = _engagement_for_submit(filing)
    if filing["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "only a DRAFT filing may be submitted")
    _require_active_engagement(engagement)
    _require_attempt_headroom(filing)
    _record_submission(filing, engagement)
    return Obj(filing)


@bp.post("/disclosure/filings/<row_id>/resubmit")
@endpoint([ROLE_DISSEMINATION_AGENT])
def resubmit_filing(row_id):
    filing = must_get("filings", row_id)
    data = body()
    correction_reason = vstr(data, "correction_reason", max_len=500)
    engagement = _engagement_for_answer(filing)
    if filing["status"] != "REJECTED":
        fail("ERR_INVALID_STATE_TRANSITION", "only a REJECTED filing may be resubmitted")
    _require_active_engagement(engagement)
    _require_attempt_headroom(filing)
    _record_submission(filing, engagement)
    filing["correction_reason"] = correction_reason
    return Obj(filing)


@bp.post("/disclosure/filings/<row_id>/reject")
@endpoint([ROLE_DISSEMINATION_AGENT])
def reject_filing(row_id):
    filing = must_get("filings", row_id)
    data = body()
    rejection_reason = vstr(data, "rejection_reason", max_len=500)
    engagement = _engagement_for_answer(filing)
    if filing["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION", "only a SUBMITTED filing may be rejected")
    _require_active_engagement(engagement)
    touch(filing)
    filing["status"] = "REJECTED"
    filing["rejection_reason"] = rejection_reason
    # compensating transition: the subject returns to its fileable state
    if filing["supersedes_filing_id"] is None:
        subject = _subject_row(filing)
        if subject is not None and subject["status"] == "FILING_IN_PROGRESS":
            touch(subject)
            subject["status"] = ("READY_TO_FILE"
                                 if filing["filing_type"] == "ANNUAL_REPORT"
                                 else "MATERIAL")
    undertaking = _subject_undertaking(filing)
    domain.recompute_open_obligation_count(undertaking)
    domain.recompute_open_material_event_count(DB.bond_issues.get(filing["issue_id"]))
    return Obj(filing)


@bp.post("/disclosure/filings/<row_id>/confirm")
@endpoint([ROLE_DISSEMINATION_AGENT])
def confirm_filing(row_id):
    filing = must_get("filings", row_id)
    data = body()
    receipt_id = vstr(data, "repository_receipt_id", max_len=64)
    engagement = _engagement_for_answer(filing)
    if filing["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION", "only a SUBMITTED filing may be confirmed")
    _require_active_engagement(engagement)
    for other in DB.filings.values():
        if other["id"] != filing["id"] \
                and other["repository_receipt_id"] == receipt_id:
            fail("ERR_RECEIPT_ID_DUPLICATE",
                 "repository_receipt_id must be unique across every filing")
    touch(filing)
    filing["status"] = "CONFIRMED"
    filing["repository_receipt_id"] = receipt_id
    filing["repository_confirmed_at"] = clock_stamp()

    correcting = filing["supersedes_filing_id"] is not None
    subject = _subject_row(filing)
    undertaking = _subject_undertaking(filing)
    filing_type = filing["filing_type"]

    if correcting:
        # the target leaves CONFIRMED as this filing enters it, so the billable
        # count re-derived below is unchanged and a correction is never re-billed
        target = DB.filings.get(filing["supersedes_filing_id"])
        if target is not None:
            touch(target)
            target["status"] = "SUPERSEDED"
            target["superseded_by_filing_id"] = filing["id"]
        if subject is not None and "filed_filing_id" in subject:
            touch(subject)
            subject["filed_filing_id"] = filing["id"]
    else:
        # hop 1 — discharge the subject
        if filing_type == "ANNUAL_REPORT":
            timely = domain.assess_cycle_timeliness(subject, undertaking, filing)
            # hop 2 — only a FILED_LATE cycle mints a failure event
            domain.settle_cycle_failure_events(subject, not timely)
        elif filing_type == "MATERIAL_EVENT_NOTICE":
            domain.assess_notice_timeliness(subject, filing)
            linked = DB.placements.get(subject["financial_obligation_ref"]) \
                if subject["financial_obligation_ref"] else None
            if linked is not None and linked["status"] == "DISCLOSURE_REQUIRED":
                touch(linked)
                linked["status"] = "DISCLOSED"
        elif filing_type == "VOLUNTARY_FINANCIAL_OBLIGATION":
            if subject is not None and subject["status"] == "DISCLOSURE_REQUIRED":
                touch(subject)
                subject["status"] = "DISCLOSED"

    # hop 3 — counters, then the risk-score pass
    domain.recompute_counters(undertaking)
    domain.run_risk_pass(undertaking)
    # hop 4 — billable filing count, then the invoice total at the fresh posture
    domain.recompute_undertaking_invoices(undertaking)
    # hop 5 — the five-year lookback for statements sharing the program code
    domain.rerun_program_lookbacks(domain.program_code_of_undertaking(undertaking))
    # closing bookkeeping
    domain.recompute_open_obligation_count(undertaking)
    domain.recompute_open_material_event_count(DB.bond_issues.get(filing["issue_id"]))
    return Obj(filing)
