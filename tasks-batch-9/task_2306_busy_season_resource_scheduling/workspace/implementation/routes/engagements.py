"""Engagement lifecycle: creation, reads, the realization analysis and the five
status transitions (schedule, start-fieldwork, report/clear client block, deliver)."""

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

bp = Blueprint("engagements", __name__)

BUSY_SEASON_MIN = 2020
BUSY_SEASON_MAX = 2035


def _require_status(engagement, allowed, detail):
    if engagement["status"] not in allowed:
        raise ApiError("ERR_ENGAGEMENT_INVALID_STATE", detail)


def _require_owner(engagement, user_id):
    if user_id != engagement["engagement_partner_staff_id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "Only the engagement partner of record may perform this action.",
        )


# =============================================================================
# create / read / list
# =============================================================================
@bp.post("/engagements")
def create_engagement():
    authorize(ROLE_SCHEDULING_MANAGER)
    body = validation.json_body()

    # --- 5: body foreign keys in declared field order ----------------------
    client = validation.body_fk(body, "client_id", db.clients, "ERR_CLIENT_NOT_FOUND")
    partner = validation.body_fk(
        body, "engagement_partner_staff_id", db.staff_members, "ERR_STAFF_MEMBER_NOT_FOUND"
    )

    # --- 6: shape ----------------------------------------------------------
    validation.req_string(body, "client_id")
    validation.req_string(body, "engagement_partner_staff_id")
    service_line = validation.req_enum(body, "service_line", validation.SERVICE_LINES)
    busy_season_year = validation.req_integer(
        body, "busy_season_year", BUSY_SEASON_MIN, BUSY_SEASON_MAX
    )
    deadline_date = validation.req_date(body, "deadline_date")
    budget_fee_amount = validation.req_number(
        body, "budget_fee_amount", calc.D("0"), exclusive_min=True
    )

    # --- 15: partner rotation ----------------------------------------------
    limit = calc.partner_rotation_limit_years(client)
    consecutive = calc.consecutive_partner_years(
        client["id"], partner["id"], busy_season_year
    )
    if consecutive > limit:
        raise ApiError(
            "ERR_PARTNER_ROTATION_LIMIT",
            "This partner would serve %d consecutive years against a limit of %d."
            % (consecutive, limit),
        )

    # --- 24: one engagement per (client, partner, year) --------------------
    for existing in db.engagements.values():
        if (
            existing["client_id"] == client["id"]
            and existing["engagement_partner_staff_id"] == partner["id"]
            and existing["busy_season_year"] == busy_season_year
        ):
            raise ApiError(
                "ERR_DUPLICATE_ENGAGEMENT_YEAR",
                "An engagement already exists for this client, partner and busy season year.",
            )

    # --- 43: the partner must be a domestic partner ------------------------
    if partner["level"] != "PARTNER" or partner["service_center"] != "DOMESTIC":
        raise ApiError(
            "ERR_PARTNER_LEVEL_REQUIRED",
            "The engagement partner must be a DOMESTIC staff member of level PARTNER.",
        )

    row = db.new_row()
    row.update(
        {
            "client_id": client["id"],
            "engagement_partner_staff_id": partner["id"],
            "service_line": service_line,
            "busy_season_year": busy_season_year,
            "deadline_date": deadline_date,
            "budget_fee_amount": calc.r2(budget_fee_amount),
            "status": "SETUP",
            "pre_block_status": None,
            "client_block_count": 0,
            "scope_change_count": 0,
        }
    )
    db.engagements[row["id"]] = row
    db.commit()
    return response.object_response(serialize.engagement(row), 201)


@bp.get("/engagements/<engagement_id>")
def read_engagement(engagement_id):
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
        ROLE_INDEPENDENCE_OFFICER,
    )
    row = validation.path_engagement(engagement_id)
    return response.object_response(serialize.engagement(row))


@bp.get("/engagements")
def list_engagements():
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_INDEPENDENCE_OFFICER,
    )
    client_id = common.q("client_id")
    partner_id = common.q("engagement_partner_staff_id")
    status = common.q("status")
    band = common.q("schedule_risk_band")
    rows = db.by_seq(list(db.engagements.values()))
    if client_id is not None:
        rows = [r for r in rows if r["client_id"] == client_id]
    if partner_id is not None:
        rows = [r for r in rows if r["engagement_partner_staff_id"] == partner_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if band is not None:
        rows = [r for r in rows if calc.schedule_risk_band(r) == band]
    return common.page(rows, serialize.engagement)


@bp.get("/engagements/<engagement_id>/realization")
def read_realization(engagement_id):
    authorize(ROLE_FIRM_ADMIN, ROLE_SCHEDULING_MANAGER, ROLE_ENGAGEMENT_PARTNER)
    engagement = validation.path_engagement(engagement_id)
    figures = calc.realization(engagement)
    return response.object_response(
        {
            "engagement_id": engagement["id"],
            "budget_fee_amount": serialize.num(engagement["budget_fee_amount"]),
            "committed_hours_total": serialize.num(figures["committed_hours_total"]),
            "logged_hours_total": serialize.num(figures["logged_hours_total"]),
            "standard_value_provisional": serialize.num(figures["standard_value_provisional"]),
            "realization_pct_provisional": serialize.num(figures["realization_pct_provisional"]),
            "standard_value_final": serialize.num(figures["standard_value_final"]),
            "realization_pct_final": serialize.num(figures["realization_pct_final"]),
            "onshore_standard_value": serialize.num(figures["onshore_standard_value"]),
            "offshore_standard_value": serialize.num(figures["offshore_standard_value"]),
        }
    )


# =============================================================================
# transitions
# =============================================================================
@bp.post("/engagements/<engagement_id>/schedule")
def schedule_engagement(engagement_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    engagement = validation.path_engagement(engagement_id)

    phases = calc.phases_of_engagement(engagement["id"])
    if engagement["status"] != "SETUP":
        _require_status(engagement, ("SETUP",), "Only a SETUP engagement may be scheduled.")
    if not phases:
        raise ApiError(
            "ERR_ENGAGEMENT_INVALID_STATE",
            "The engagement carries no phase and cannot be scheduled.",
        )
    if any(p["staffing_status"] not in ("PARTIALLY_STAFFED", "FULLY_STAFFED") for p in phases):
        raise ApiError(
            "ERR_ENGAGEMENT_INVALID_STATE",
            "Every phase must be at least partially staffed before scheduling.",
        )

    engagement["status"] = "SCHEDULED"
    db.mark(engagement)
    db.commit()
    return response.object_response(serialize.engagement(engagement))


@bp.post("/engagements/<engagement_id>/start-fieldwork")
def start_fieldwork(engagement_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    engagement = validation.path_engagement(engagement_id)

    _require_status(
        engagement, ("SCHEDULED",), "Only a SCHEDULED engagement may enter fieldwork."
    )
    if calc.staffing_completion_pct(engagement) < calc.D("50.00"):
        raise ApiError(
            "ERR_ENGAGEMENT_INVALID_STATE",
            "Staffing completion must reach 50.00 percent before fieldwork starts.",
        )

    engagement["status"] = "IN_FIELDWORK"
    db.mark(engagement)
    db.commit()
    return response.object_response(serialize.engagement(engagement))


@bp.post("/engagements/<engagement_id>/report-client-block")
def report_client_block(engagement_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    engagement = validation.path_engagement(engagement_id)
    body = validation.json_body()
    validation.req_string(body, "reason_note", 1, 500)
    validation.opt_date(body, "blocked_until_date")

    _require_status(
        engagement,
        ("SCHEDULED", "IN_FIELDWORK"),
        "Only a SCHEDULED or IN_FIELDWORK engagement may be reported as client-blocked.",
    )

    engagement["pre_block_status"] = engagement["status"]
    engagement["status"] = "CLIENT_BLOCKED"
    engagement["client_block_count"] = engagement["client_block_count"] + 1
    db.mark(engagement)

    derive.cascade_client_block(engagement)

    db.commit()
    return response.object_response(serialize.engagement(engagement))


@bp.post("/engagements/<engagement_id>/clear-client-block")
def clear_client_block(engagement_id):
    user_id, _role = authorize(ROLE_ENGAGEMENT_PARTNER)
    engagement = validation.path_engagement(engagement_id)

    _require_owner(engagement, user_id)
    _require_status(
        engagement, ("CLIENT_BLOCKED",), "Only a CLIENT_BLOCKED engagement may be cleared."
    )

    restored = engagement["pre_block_status"]
    if restored not in ("SCHEDULED", "IN_FIELDWORK"):
        raise ApiError(
            "ERR_ENGAGEMENT_INVALID_STATE",
            "The engagement carries no restorable pre-block status.",
        )

    engagement["status"] = restored
    engagement["pre_block_status"] = None
    db.mark(engagement)
    db.commit()
    return response.object_response(serialize.engagement(engagement))


@bp.post("/engagements/<engagement_id>/deliver")
def deliver_engagement(engagement_id):
    user_id, _role = authorize(ROLE_ENGAGEMENT_PARTNER)
    engagement = validation.path_engagement(engagement_id)

    _require_owner(engagement, user_id)
    _require_status(
        engagement, ("IN_FIELDWORK",), "Only an IN_FIELDWORK engagement may be delivered."
    )

    phases = calc.phases_of_engagement(engagement["id"])
    if any(p["staffing_status"] != "COMPLETE" for p in phases):
        raise ApiError(
            "ERR_ENGAGEMENT_INVALID_STATE",
            "Every phase must be COMPLETE before the engagement is delivered.",
        )

    engagement["status"] = "DELIVERED"
    db.mark(engagement)

    for waiver in derive.waivers_of(engagement_id=engagement["id"], status="APPROVED"):
        derive.expire_waiver(waiver, "ENGAGEMENT_BLOCKED")

    db.commit()
    return response.object_response(serialize.engagement(engagement))
