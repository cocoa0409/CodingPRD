"""Fee schedule band endpoints (PRD 3.2)."""

from flask import Blueprint, request

import db
from db import FEE_SCHEDULE_STATUSES, ROLE_TYPES, TERMINAL_FEE_SCHEDULE, serialize, store, touch
from errors import fail
from middleware import (
    AGENCY_PRINCIPAL,
    BILLING_ADMINISTRATOR,
    CLIENT,
    COMPLIANCE_OFFICER,
    PLACEMENT_CONSULTANT,
    authenticate,
)
from response import created_response, list_response, object_response
from services import calc, domain
from validation import (
    apply_filters,
    body_of,
    check_date,
    check_enum,
    check_int,
    interval_fail,
    list_params,
    require_present,
)

bp = Blueprint("fee_schedules", __name__)


@bp.post("/fee-schedules")
def create_fee_schedule():
    authenticate({AGENCY_PRINCIPAL})
    body = body_of(request)

    require_present(
        body, "role_type", "comp_band_floor_cents", "fee_percent_bps",
        "guarantee_window_days", "effective_from",
    )
    role_type = check_enum(body, "role_type", ROLE_TYPES)
    comp_band_floor_cents = check_int(body, "comp_band_floor_cents", minimum=0)
    comp_band_ceiling_cents = check_int(body, "comp_band_ceiling_cents", minimum=0, required=False)
    fee_percent_bps = check_int(body, "fee_percent_bps", minimum=1, maximum=10000)
    guarantee_window_days = check_int(body, "guarantee_window_days", minimum=1, maximum=365)
    effective_from = check_date(body, "effective_from")

    # A non-null ceiling at or below the floor is a mis-ordered interval.
    if comp_band_ceiling_cents is not None and comp_band_ceiling_cents <= comp_band_floor_cents:
        interval_fail("comp_band_ceiling_cents must be greater than comp_band_floor_cents")

    # Overlap is examined only among ACTIVE bands sharing the role_type and the
    # same effective_from; ranges are half-open so a touching pair is legal.
    for other in store.fee_schedules.values():
        if other["status"] != "ACTIVE":
            continue
        if other["role_type"] != role_type:
            continue
        if other["effective_from"] != body["effective_from"]:
            continue
        if calc.bands_overlap(
            comp_band_floor_cents, comp_band_ceiling_cents,
            other["comp_band_floor_cents"], other["comp_band_ceiling_cents"],
        ):
            fail("ERR_FEE_BAND_OVERLAP")

    row = {
        "role_type": role_type,
        "comp_band_floor_cents": comp_band_floor_cents,
        "comp_band_ceiling_cents": comp_band_ceiling_cents,
        "fee_percent_bps": fee_percent_bps,
        "guarantee_window_days": guarantee_window_days,
        "effective_from": body["effective_from"],
        "status": "ACTIVE",
    }
    db.stamp_new(row)
    store.fee_schedules[row["id"]] = row
    return created_response(serialize(row))


@bp.get("/fee-schedules/<schedule_id>")
def get_fee_schedule(schedule_id):
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, BILLING_ADMINISTRATOR,
        COMPLIANCE_OFFICER, CLIENT,
    })
    row = domain.resolve("fee_schedules", schedule_id)
    return object_response(serialize(row))


@bp.get("/fee-schedules")
def list_fee_schedules():
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, BILLING_ADMINISTRATOR,
        COMPLIANCE_OFFICER, CLIENT,
    })
    limit, offset, filters = list_params(
        request,
        enum_filters={"role_type": ROLE_TYPES, "status": FEE_SCHEDULE_STATUSES},
    )
    rows = apply_filters(list(store.fee_schedules.values()), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


@bp.post("/fee-schedules/<schedule_id>/retire")
def retire_fee_schedule(schedule_id):
    authenticate({AGENCY_PRINCIPAL})
    body_of(request)
    row = domain.resolve("fee_schedules", schedule_id)
    domain.guard_terminal(row["status"], TERMINAL_FEE_SCHEDULE)
    row["status"] = "RETIRED"
    touch(row)
    return object_response(serialize(row))
