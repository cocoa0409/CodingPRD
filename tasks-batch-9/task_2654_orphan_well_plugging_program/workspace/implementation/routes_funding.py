"""Funding sources, the commitment waterfall and federal reporting (PRD 3.9)."""
from flask import Blueprint

import calc
import validate as v
from auth import (AWARD_AUTHORITY, DETERMINATION_REVIEWER, FUNDING_OFFICER,
                  PROCUREMENT_OFFICER, PROGRAM_ADMIN, endpoint, sod, user_id)
from envelope import array_response, filter_value, object_response, paginated
from errors import ApiError
from lookup import (collect, get_allocation, get_funding_source,
                    get_grant_report, get_job, get_operator, get_well)
from store import clock, db, new_row, touch

bp = Blueprint("funding", __name__)

KINDS = ("STATE_FUND", "FEDERAL_GRANT", "FORFEITED_BOND")
CATEGORIES = ("PLUGGING", "RECLAMATION", "ADMIN")
ALLOCATION_ACTIONS = ("DISBURSE", "DEOBLIGATE")
SUBMISSION_ACTIONS = ("SUBMIT", "ACCEPT", "REJECT")
DISBURSABLE_JOB_STATUSES = ("FIELD_REPORTED", "PLUGGED", "RECLAIMED")

SOURCE_READERS = (PROGRAM_ADMIN, FUNDING_OFFICER, PROCUREMENT_OFFICER,
                  AWARD_AUTHORITY, DETERMINATION_REVIEWER)
ALLOCATION_READERS = (PROGRAM_ADMIN, FUNDING_OFFICER, AWARD_AUTHORITY,
                      DETERMINATION_REVIEWER)
REPORT_READERS = (PROGRAM_ADMIN, FUNDING_OFFICER, AWARD_AUTHORITY)


def source_expired(source):
    return ApiError(
        "ERR_FUNDING_SOURCE_EXPIRED",
        "Funding source %s is expired." % source["id"],
    )


def _is_expired(source):
    return source["status"] == "EXPIRED" or source["expires_at"] <= clock()


@bp.route("/funding-sources", methods=["POST"])
@endpoint((FUNDING_OFFICER, PROGRAM_ADMIN))
def create_source():
    data = v.body()

    # Step 6: body reference existence.
    if isinstance(data.get("bond_operator_id"), str) and data["bond_operator_id"]:
        get_operator(data["bond_operator_id"])

    kind = v.enum_field(data, "kind", KINDS)
    name = v.str_field(data, "name")
    authorized_cents = v.int_field(data, "authorized_cents", exclusive_minimum=0)
    expires_at = v.datetime_field(data, "expires_at")
    categories = v.enum_array_field(data, "allowable_cost_categories", CATEGORIES)

    if kind == "FEDERAL_GRANT":
        match_pct = v.int_field(data, "federal_match_required_pct",
                                minimum=0, maximum=100)
    else:
        if data.get("federal_match_required_pct") is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "federal_match_required_pct applies only to FEDERAL_GRANT sources.",
            )
        match_pct = None

    if kind == "FORFEITED_BOND":
        bond_operator_id = v.str_field(data, "bond_operator_id")
    else:
        if data.get("bond_operator_id") is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "bond_operator_id applies only to FORFEITED_BOND sources.",
            )
        bond_operator_id = None

    row = new_row()
    row.update({
        "kind": kind,
        "name": name,
        "authorized_cents": authorized_cents,
        "committed_cents": 0,
        "disbursed_cents": 0,
        "expires_at": expires_at,
        "federal_match_required_pct": match_pct,
        "allowable_cost_categories": categories,
        "bond_operator_id": bond_operator_id,
        "status": "ACTIVE",
        "reporting_required": kind == "FEDERAL_GRANT",
    })
    db.funding_sources[row["id"]] = row
    return object_response(row, 201)


@bp.route("/funding-sources/<source_id>", methods=["GET"])
@endpoint(SOURCE_READERS)
def fetch_source(source_id):
    return object_response(get_funding_source(source_id))


@bp.route("/funding-sources", methods=["GET"])
@endpoint(SOURCE_READERS)
def list_sources():
    kind = filter_value("kind")
    status = filter_value("status")
    bond_operator_id = filter_value("bond_operator_id")

    def keep(row):
        if kind is not None and row["kind"] != kind:
            return False
        if status is not None and row["status"] != status:
            return False
        if (bond_operator_id is not None
                and row["bond_operator_id"] != bond_operator_id):
            return False
        return True

    return paginated(collect(db.funding_sources, keep))


@bp.route("/plugging-jobs/<job_id>/funding-commitments", methods=["POST"])
@endpoint((FUNDING_OFFICER,), needs_user_id=True)
def commit_funding(job_id):
    job = get_job(job_id)
    data = v.body()

    override_id = None
    if data.get("override_source_id") is not None:
        # Step 6: body reference existence, then schema.
        if isinstance(data["override_source_id"], str) and data["override_source_id"]:
            get_funding_source(data["override_source_id"])
        override_id = v.str_field(data, "override_source_id")

    well = get_well(job["well_id"])
    needed = job["plugging_cost_estimate_cents"]

    if override_id is not None:
        source = get_funding_source(override_id)
        # Step 8 (priority 45): expiry outranks the remaining eligibility tests.
        if _is_expired(source):
            raise source_expired(source)
        if (source["kind"] == "FORFEITED_BOND"
                and source.get("bond_operator_id") != well["operator_id"]):
            raise ApiError(
                "ERR_FORFEITED_BOND_OPERATOR_MISMATCH",
                "That forfeited bond belongs to another operator.",
            )
        pool = [source] if calc.source_eligible(source, well["operator_id"]) else []
    else:
        pool = calc.waterfall_order([
            s for s in db.funding_sources.values()
            if calc.source_eligible(s, well["operator_id"])
        ])

    plan, remaining, federal_capped = calc.run_waterfall(pool, needed)

    if remaining > 0:
        # Nothing is persisted on either failure; the match error outranks.
        if federal_capped:
            raise ApiError(
                "ERR_FEDERAL_MATCH_INSUFFICIENT",
                "A federal grant was throttled by its match entitlement; "
                "%d cents remain uncovered." % remaining,
            )
        raise ApiError(
            "ERR_FUNDING_SHORTFALL",
            "Eligible funding authority is short by %d cents." % remaining,
        )

    created = []
    for entry in plan:
        source = entry["source"]
        allocation = new_row()
        allocation.update({
            "job_id": job["id"],
            "source_id": source["id"],
            "allocated_cents": entry["allocated_cents"],
            "disbursed_cents": 0,
            "waterfall_rank": entry["waterfall_rank"],
            "status": "COMMITTED",
            "committed_by_user_id": user_id(),
            "disbursed_by_user_id": None,
            "disbursed_at": None,
            "deobligated_at": None,
        })
        db.allocations[allocation["id"]] = allocation
        created.append(allocation)

        source["committed_cents"] = calc.source_committed_cents(source["id"])
        calc.refresh_source_availability(source)
        touch(source)

    job["funded_cents"] = calc.job_funded_cents(job["id"])
    touch(job)

    return array_response(created, 201)


@bp.route("/funding-allocations/<allocation_id>", methods=["GET"])
@endpoint(ALLOCATION_READERS)
def fetch_allocation(allocation_id):
    return object_response(get_allocation(allocation_id))


@bp.route("/funding-allocations", methods=["GET"])
@endpoint(ALLOCATION_READERS)
def list_allocations():
    job_id = filter_value("job_id")
    source_id = filter_value("source_id")
    status = filter_value("status")

    def keep(row):
        if job_id is not None and row["job_id"] != job_id:
            return False
        if source_id is not None and row["source_id"] != source_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(
        collect(db.allocations, keep, sort_key=lambda r: r["waterfall_rank"])
    )


@bp.route("/funding-allocations/<allocation_id>/transitions", methods=["POST"])
@endpoint((FUNDING_OFFICER,), needs_user_id=True)
def advance_allocation(allocation_id):
    allocation = get_allocation(allocation_id)
    data = v.body()

    # Step 4 (priority 14): the SoD gate precedes schema validation.
    if (data.get("action") == "DISBURSE"
            and allocation["committed_by_user_id"] == user_id()):
        raise sod("The committing officer may not disburse this allocation.")

    action = v.enum_field(data, "action", ALLOCATION_ACTIONS)
    invoice_cents = None
    if action == "DISBURSE":
        invoice_cents = v.int_field(data, "invoice_cents", minimum=0)

    if allocation["status"] != "COMMITTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "An allocation in %s cannot be %sd." % (allocation["status"],
                                                    action.lower()),
        )

    job = get_job(allocation["job_id"])
    source = get_funding_source(allocation["source_id"])

    if action == "DISBURSE":
        if job["status"] not in DISBURSABLE_JOB_STATUSES:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The job must be field-reported before it is paid for.",
            )
        if source["status"] == "EXPIRED":
            raise source_expired(source)
        if invoice_cents > allocation["allocated_cents"]:
            raise ApiError(
                "ERR_DISBURSEMENT_EXCEEDS_ALLOCATION",
                "The invoice exceeds the allocated %d cents."
                % allocation["allocated_cents"],
            )

        allocation["disbursed_cents"] = invoice_cents
        allocation["status"] = "DISBURSED"
        allocation["disbursed_at"] = clock()
        allocation["disbursed_by_user_id"] = user_id()
        touch(allocation)

        source["disbursed_cents"] = calc.source_disbursed_cents(source["id"])
        touch(source)
        return object_response(allocation)

    # action DEOBLIGATE
    if job["status"] in ("PLUGGED", "RECLAIMED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Money cannot be pulled back off accepted work.",
        )

    allocation["status"] = "DEOBLIGATED"
    allocation["deobligated_at"] = clock()
    touch(allocation)

    source["committed_cents"] = calc.source_committed_cents(source["id"])
    calc.refresh_source_availability(source)
    touch(source)

    job["funded_cents"] = calc.job_funded_cents(job["id"])
    touch(job)

    return object_response(allocation)


@bp.route("/funding-sources/<source_id>/grant-reports", methods=["POST"])
@endpoint((FUNDING_OFFICER,))
def create_grant_report(source_id):
    source = get_funding_source(source_id)
    data = v.body()
    period_start = v.date_field(data, "period_start")
    period_end = v.date_field(data, "period_end")

    if period_end < period_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "period_end may not precede period_start.")
    if not source["reporting_required"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Only FEDERAL_GRANT sources are reportable.")

    # Step 8 (priority 45).
    if _is_expired(source):
        raise source_expired(source)

    row = new_row()
    row.update({
        "source_id": source["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "DUE",
        "revision_round": 0,
        "submitted_by_user_id": None,
        "reviewer_note": None,
    })
    calc.apply_report_figures(row)
    db.grant_reports[row["id"]] = row
    return object_response(row, 201)


@bp.route("/funding-sources/<source_id>/grant-reports", methods=["GET"])
@endpoint(REPORT_READERS)
def list_grant_reports(source_id):
    get_funding_source(source_id)
    status = filter_value("status")

    def keep(row):
        if row["source_id"] != source_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(
        collect(db.grant_reports, keep, sort_key=lambda r: r["period_start"])
    )


@bp.route("/grant-reports/<report_id>", methods=["GET"])
@endpoint(REPORT_READERS)
def fetch_grant_report(report_id):
    return object_response(get_grant_report(report_id))


@bp.route("/grant-reports/<report_id>/submission", methods=["POST"])
@endpoint((FUNDING_OFFICER, AWARD_AUTHORITY), needs_user_id=True)
def advance_grant_report(report_id):
    report = get_grant_report(report_id)
    data = v.body()
    action = v.enum_field(data, "action", SUBMISSION_ACTIONS)
    reviewer_note = None
    if data.get("reviewer_note") is not None:
        reviewer_note = v.str_field(data, "reviewer_note")

    if action == "SUBMIT":
        if report["status"] not in ("DUE", "REJECTED"):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "A report in %s cannot be submitted." % report["status"],
            )
        if report["status"] == "REJECTED":
            report["revision_round"] += 1
        calc.apply_report_figures(report)
        report["status"] = "SUBMITTED"
        report["submitted_by_user_id"] = user_id()
        touch(report)
        return object_response(report)

    if report["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A report in %s is not awaiting review." % report["status"],
        )

    report["status"] = "ACCEPTED" if action == "ACCEPT" else "REJECTED"
    report["reviewer_note"] = reviewer_note
    touch(report)
    return object_response(report)
