"""Independence restrictions, reschedule plans and workload waivers."""

from flask import Blueprint

import db
import response
import validation
from errors import ApiError
from middleware import (
    ROLE_ENGAGEMENT_PARTNER,
    ROLE_ENGAGEMENT_STAFF,
    ROLE_FIRM_ADMIN,
    ROLE_INDEPENDENCE_OFFICER,
    ROLE_SCHEDULING_MANAGER,
    authorize,
)
from routes import common
from services import calc, derive, serialize

bp = Blueprint("compliance", __name__)

MAX_SHIFT_DAYS = 60
MAX_ADDED_HOURS = calc.D("400.00")


# =============================================================================
# IndependenceRestriction
# =============================================================================
@bp.post("/independence-restrictions")
def create_restriction():
    authorize(ROLE_INDEPENDENCE_OFFICER)
    body = validation.json_body()

    client = validation.body_fk(body, "client_id", db.clients, "ERR_CLIENT_NOT_FOUND")
    staff = validation.body_fk(
        body, "staff_member_id", db.staff_members, "ERR_STAFF_MEMBER_NOT_FOUND"
    )

    validation.req_string(body, "client_id")
    validation.req_string(body, "staff_member_id")
    restriction_type = validation.req_enum(
        body, "restriction_type", validation.RESTRICTION_TYPES
    )
    effective_start_date = validation.req_date(body, "effective_start_date")
    effective_end_date = validation.req_date(body, "effective_end_date")

    if effective_end_date < effective_start_date:
        raise ApiError(
            "ERR_INVALID_DATE_RANGE",
            "effective_end_date must be on or after effective_start_date.",
        )

    for existing in db.restrictions.values():
        if (
            existing["status"] == "ACTIVE"
            and existing["client_id"] == client["id"]
            and existing["staff_member_id"] == staff["id"]
        ):
            raise ApiError(
                "ERR_DUPLICATE_RESTRICTION",
                "An active restriction already exists for this client and staff member.",
            )

    row = db.new_row()
    row.update(
        {
            "client_id": client["id"],
            "staff_member_id": staff["id"],
            "restriction_type": restriction_type,
            "effective_start_date": effective_start_date,
            "effective_end_date": effective_end_date,
            "status": "ACTIVE",
            "released_assignment_count": 0,
        }
    )
    db.restrictions[row["id"]] = row

    derive.cascade_restriction(row)

    db.commit()
    return response.object_response(serialize.restriction(row), 201)


@bp.get("/independence-restrictions/<independence_restriction_id>")
def read_restriction(independence_restriction_id):
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_INDEPENDENCE_OFFICER,
    )
    row = validation.path_restriction(independence_restriction_id)
    return response.object_response(serialize.restriction(row))


@bp.get("/independence-restrictions")
def list_restrictions():
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_INDEPENDENCE_OFFICER,
    )
    client_id = common.q("client_id")
    staff_member_id = common.q("staff_member_id")
    status = common.q("status")
    restriction_type = common.q("restriction_type")
    rows = db.by_seq(list(db.restrictions.values()))
    if client_id is not None:
        rows = [r for r in rows if r["client_id"] == client_id]
    if staff_member_id is not None:
        rows = [r for r in rows if r["staff_member_id"] == staff_member_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if restriction_type is not None:
        rows = [r for r in rows if r["restriction_type"] == restriction_type]
    return common.page(rows, serialize.restriction)


@bp.post("/independence-restrictions/<independence_restriction_id>/lift")
def lift_restriction(independence_restriction_id):
    authorize(ROLE_INDEPENDENCE_OFFICER)
    row = validation.path_restriction(independence_restriction_id)

    if row["status"] != "ACTIVE":
        raise ApiError(
            "ERR_RESTRICTION_INVALID_STATE", "Only an ACTIVE restriction may be lifted."
        )

    row["status"] = "LIFTED"
    db.mark(row)
    db.commit()
    return response.object_response(serialize.restriction(row))


# =============================================================================
# ReschedulePlan
# =============================================================================
@bp.post("/reschedule-plans")
def create_plan():
    authorize(ROLE_SCHEDULING_MANAGER)
    body = validation.json_body()

    engagement = validation.body_fk(
        body, "engagement_id", db.engagements, "ERR_ENGAGEMENT_NOT_FOUND"
    )

    validation.req_string(body, "engagement_id")
    trigger_reason = validation.req_enum(body, "trigger_reason", validation.TRIGGER_REASONS)
    shift_days = validation.req_integer(body, "shift_days", 0, MAX_SHIFT_DAYS)
    added_hours = validation.opt_number(
        body, "added_hours", calc.D("0"), MAX_ADDED_HOURS, default=calc.ZERO
    )

    row = db.new_row()
    row.update(
        {
            "engagement_id": engagement["id"],
            "trigger_reason": trigger_reason,
            "shift_days": shift_days,
            "added_hours": calc.r2(added_hours),
            "status": "DRAFT",
            "target_phase_id": None,
            "simulated_at_engagement_version": None,
            "projected_unstaffed_hours": None,
            "projected_dropped_assignment_count": None,
            "projected_cap_breach_count": None,
            "projected_realization_pct": None,
        }
    )
    db.reschedule_plans[row["id"]] = row
    db.commit()
    return response.object_response(serialize.reschedule_plan(row), 201)


@bp.get("/reschedule-plans/<reschedule_plan_id>")
def read_plan(reschedule_plan_id):
    authorize(ROLE_FIRM_ADMIN, ROLE_SCHEDULING_MANAGER, ROLE_ENGAGEMENT_PARTNER)
    row = validation.path_plan(reschedule_plan_id)
    return response.object_response(serialize.reschedule_plan(row))


@bp.get("/reschedule-plans")
def list_plans():
    authorize(ROLE_FIRM_ADMIN, ROLE_SCHEDULING_MANAGER, ROLE_ENGAGEMENT_PARTNER)
    engagement_id = common.q("engagement_id")
    target_phase_id = common.q("target_phase_id")
    status = common.q("status")
    rows = db.by_seq(list(db.reschedule_plans.values()))
    if engagement_id is not None:
        rows = [r for r in rows if r["engagement_id"] == engagement_id]
    if target_phase_id is not None:
        rows = [r for r in rows if r["target_phase_id"] == target_phase_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.page(rows, serialize.reschedule_plan)


@bp.post("/reschedule-plans/<reschedule_plan_id>/simulate")
def simulate_plan(reschedule_plan_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    plan = validation.path_plan(reschedule_plan_id)

    if plan["status"] not in ("DRAFT", "SIMULATED"):
        raise ApiError(
            "ERR_PLAN_INVALID_STATE", "Only a DRAFT or SIMULATED plan may be simulated."
        )

    engagement = db.engagements.get(plan["engagement_id"])
    if engagement is None or engagement["status"] not in (
        "SCHEDULED",
        "IN_FIELDWORK",
        "CLIENT_BLOCKED",
    ):
        raise ApiError(
            "ERR_PLAN_INVALID_STATE",
            "The owning engagement must be SCHEDULED, IN_FIELDWORK or CLIENT_BLOCKED.",
        )

    projection = calc.reschedule_projection(plan, engagement)
    plan.update(projection)
    plan["simulated_at_engagement_version"] = engagement["version"]
    plan["status"] = "SIMULATED"
    db.mark(plan)
    db.commit()
    return response.object_response(serialize.reschedule_plan(plan))


@bp.post("/reschedule-plans/<reschedule_plan_id>/apply")
def apply_plan(reschedule_plan_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    plan = validation.path_plan(reschedule_plan_id)
    body = validation.json_body()
    expected_engagement_version = validation.req_integer(
        body, "expected_engagement_version", 1
    )

    if plan["status"] != "SIMULATED":
        raise ApiError("ERR_PLAN_INVALID_STATE", "Only a SIMULATED plan may be applied.")

    engagement = db.engagements.get(plan["engagement_id"])
    if engagement is None:
        raise ApiError("ERR_ENGAGEMENT_NOT_FOUND", "The plan's engagement no longer exists.")

    if calc.simulation_stale(plan):
        raise ApiError(
            "ERR_SIMULATION_STALE",
            "The engagement moved since the projection was computed; re-simulate first.",
        )

    if expected_engagement_version != engagement["version"]:
        raise ApiError(
            "ERR_STALE_ENGAGEMENT_VERSION",
            "expected_engagement_version %d does not match the engagement version %d."
            % (expected_engagement_version, engagement["version"]),
        )

    plan["status"] = "APPLIED"
    db.mark(plan)
    db.mark(engagement)
    derive.apply_reschedule(plan, engagement)

    db.commit()
    return response.object_response(serialize.reschedule_plan(plan))


# =============================================================================
# WorkloadWaiver
# =============================================================================
@bp.post("/workload-waivers")
def create_waiver():
    user_id, _role = authorize(ROLE_ENGAGEMENT_STAFF)
    body = validation.json_body()

    staff = validation.body_fk(
        body, "staff_member_id", db.staff_members, "ERR_STAFF_MEMBER_NOT_FOUND"
    )
    engagement = validation.body_fk(
        body, "engagement_id", db.engagements, "ERR_ENGAGEMENT_NOT_FOUND"
    )

    validation.req_string(body, "staff_member_id")
    validation.req_string(body, "engagement_id")
    week_start_date = validation.req_date(body, "week_start_date")
    extra_hours = validation.req_number(
        body, "extra_hours_allowance", calc.D("0.25"), calc.D("10.00")
    )
    justification_note = validation.opt_string(body, "justification_note", 1, 500)

    validation.require_monday("week_start_date", week_start_date)

    if user_id != staff["id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "A staff member may only request an allowance for themselves.",
        )

    for existing in db.waivers.values():
        if (
            existing["staff_member_id"] == staff["id"]
            and existing["week_start_date"] == week_start_date
            and existing["status"] in ("REQUESTED", "APPROVED")
        ):
            raise ApiError(
                "ERR_DUPLICATE_WAIVER",
                "A live allowance already exists for this staff member and ISO week.",
            )

    row = db.new_row()
    row.update(
        {
            "staff_member_id": staff["id"],
            "engagement_id": engagement["id"],
            "week_start_date": week_start_date,
            "extra_hours_allowance": calc.r2(extra_hours),
            "status": "REQUESTED",
            "approved_by_user_id": None,
            "expiry_reason": None,
            "justification_note": justification_note,
        }
    )
    db.waivers[row["id"]] = row
    db.commit()
    return response.object_response(serialize.waiver(row), 201)


@bp.get("/workload-waivers/<workload_waiver_id>")
def read_waiver(workload_waiver_id):
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
    )
    row = validation.path_waiver(workload_waiver_id)
    return response.object_response(serialize.waiver(row))


@bp.get("/workload-waivers")
def list_waivers():
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
    )
    staff_member_id = common.q("staff_member_id")
    engagement_id = common.q("engagement_id")
    status = common.q("status")
    week_start_date = common.q_date("week_start_date")
    if common.has_invalid(week_start_date):
        return common.empty_page()
    rows = db.by_seq(list(db.waivers.values()))
    if staff_member_id is not None:
        rows = [r for r in rows if r["staff_member_id"] == staff_member_id]
    if engagement_id is not None:
        rows = [r for r in rows if r["engagement_id"] == engagement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if week_start_date is not None:
        rows = [r for r in rows if r["week_start_date"] == week_start_date]
    return common.page(rows, serialize.waiver)


def _decide_waiver(waiver_id, user_id, approving):
    waiver = validation.path_waiver(waiver_id)
    engagement = db.engagements.get(waiver["engagement_id"])

    # --- 10: only the engagement partner of record decides -----------------
    if engagement is None or user_id != engagement["engagement_partner_staff_id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "Only the engagement partner named by the allowance may decide it.",
        )

    # --- 11: state ----------------------------------------------------------
    if waiver["status"] != "REQUESTED":
        raise ApiError(
            "ERR_WAIVER_INVALID_STATE", "Only a REQUESTED allowance may be decided."
        )
    if approving and engagement["status"] == "DELIVERED":
        raise ApiError(
            "ERR_WAIVER_INVALID_STATE",
            "A delivered engagement cannot justify a new overtime allowance.",
        )

    # --- 16: segregation of duties -----------------------------------------
    if user_id == waiver["staff_member_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The beneficiary of an allowance may never decide it.",
        )

    waiver["status"] = "APPROVED" if approving else "DENIED"
    waiver["approved_by_user_id"] = user_id
    db.mark(waiver)
    db.commit()
    return response.object_response(serialize.waiver(waiver))


@bp.post("/workload-waivers/<workload_waiver_id>/approve")
def approve_waiver(workload_waiver_id):
    user_id, _role = authorize(ROLE_ENGAGEMENT_PARTNER)
    return _decide_waiver(workload_waiver_id, user_id, True)


@bp.post("/workload-waivers/<workload_waiver_id>/deny")
def deny_waiver(workload_waiver_id):
    user_id, _role = authorize(ROLE_ENGAGEMENT_PARTNER)
    return _decide_waiver(workload_waiver_id, user_id, False)
