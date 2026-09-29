"""RefreshCycle endpoints (PRD 3.2)."""

from flask import Blueprint

import calc
import clock
import db
import domain
import guards
import response

bp = Blueprint("refresh_cycles", __name__)

READ_ROLES = ("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")


@bp.route("/compliance/refresh-cycles", methods=["POST"])
def create_cycle():
    guards.authorize("PlanSponsorAdmin", "ComplianceOfficer")
    body = guards.read_body()
    plan_year_id = guards.field(body, "plan_year_id", "string")
    period_month = guards.field(body, "period_month", "month")
    period_start = guards.field(body, "period_start", "date")
    period_end = guards.field(body, "period_end", "date")
    plan_year = guards.fetch("plan_year", plan_year_id)
    guards.not_frozen(plan_year)
    # Ladder step 19 — closed period, inside the plan year.
    guards.require(
        period_end >= period_start
        and plan_year["start_date"] <= period_start
        and period_end <= plan_year["end_date"],
        "ERR_INVALID_INTERVAL",
        "period_end must be >= period_start and the period must lie inside the plan year.",
    )
    # Ladder step 20 — closed-interval overlap with a sibling cycle.
    for sibling in db.refresh_cycles_of_plan_year(plan_year_id):
        if period_start <= sibling["period_end"] and sibling["period_start"] <= period_end:
            raise_overlap(sibling)
    record = db.common_fields()
    record.update({
        "plan_year_id": plan_year_id,
        "period_month": period_month,
        "period_start": period_start,
        "period_end": period_end,
        "deadline_at": clock.iso(calc.refresh_deadline(period_end)),
        "status": "PENDING",
        "certified_at": None,
        "certified_by_user_id": None,
        "on_time": None,
        "certification_note": None,
    })
    db.refresh_cycles[record["id"]] = record
    return response.created_response(response.public(record))


def raise_overlap(sibling):
    guards.require(
        False,
        "ERR_REFRESH_PERIOD_OVERLAP",
        "The period overlaps refresh cycle %s (%s..%s); periods are closed intervals."
        % (sibling["id"], sibling["period_start"], sibling["period_end"]),
    )


@bp.route("/compliance/refresh-cycles/<row_id>", methods=["GET"])
def get_cycle(row_id):
    guards.authorize(*READ_ROLES)
    return response.object_response(
        response.public(guards.fetch("refresh_cycle", row_id))
    )


@bp.route("/compliance/refresh-cycles", methods=["GET"])
def list_cycles():
    guards.authorize(*READ_ROLES)
    limit, offset = guards.pagination()
    guards.filter_fk("plan_year", "plan_year_id")
    rows = guards.apply_filters(db.ordered(db.refresh_cycles), [
        ("plan_year_id", "plan_year_id", None),
        ("status", "status", None),
        ("period_month", "period_month", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


@bp.route("/compliance/refresh-cycles/<row_id>/certify", methods=["POST"])
def certify_cycle(row_id):
    user_id, _role = guards.authorize("ComplianceOfficer")
    cycle = guards.fetch("refresh_cycle", row_id)
    body = guards.read_body()
    note = guards.field(body, "certification_note", "string", required=False)
    plan_year = db.plan_years.get(cycle["plan_year_id"])
    guards.not_frozen(plan_year)
    guards.state_is(cycle["status"], "PENDING")
    guards.require(
        plan_year is not None and plan_year["lifecycle_status"] == "ACTIVE",
        "ERR_INVALID_STATE_TRANSITION",
        "The plan year must be ACTIVE to certify a refresh cycle.",
    )
    # Ladder step 15 — both required file types PUBLISHED for the period month.
    published = set()
    for mrf in db.mrfs.values():
        if (
            mrf["plan_year_id"] == cycle["plan_year_id"]
            and mrf["posting_month"] == cycle["period_month"]
            and mrf["status"] == "PUBLISHED"
        ):
            published.add(mrf["file_type"])
    guards.require(
        all(file_type in published for file_type in calc.REQUIRED_FILE_TYPES),
        "ERR_MRF_NOT_PUBLISHED",
        "Both IN_NETWORK_RATES and ALLOWED_AMOUNTS must be PUBLISHED for %s."
        % cycle["period_month"],
    )
    on_time = clock.now() <= clock.parse_datetime(cycle["deadline_at"])
    with db.txn(cycle):
        cycle["status"] = "CERTIFIED" if on_time else "LATE_CERTIFIED"
        cycle["certified_at"] = clock.now_iso()
        cycle["certified_by_user_id"] = user_id
        cycle["on_time"] = on_time
        cycle["certification_note"] = note
    if not on_time and plan_year is not None:
        with db.txn(plan_year):
            domain.recompute_posture(plan_year)
    return response.object_response(response.public(cycle))
