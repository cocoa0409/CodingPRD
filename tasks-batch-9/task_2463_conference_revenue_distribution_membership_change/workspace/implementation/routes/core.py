"""Logical clock, conference singleton and venue registration."""

from flask import Blueprint

import clock
import response
import serializers
import validation
from db import base_record, db, touch
from errors import ApiError
from middleware import api, authenticate, authorize, current_user_id, raw_body
from services import conference_service

bp = Blueprint("core", __name__)

ALL_ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "Treasurer",
    "Auditor",
    "ComplianceOfficer",
    "ScheduleCoordinator",
    "PlatformAdmin",
    "MemberRepresentative",
)


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc
# ---------------------------------------------------------------------------


@bp.route("/_clock/set_current_utc", methods=["POST"])
@api(("PlatformAdmin",), needs_conference=False)
def set_clock():
    body = raw_body()
    instant = validation.get_instant(body, "to_iso8601")
    clock.set_now(instant)
    return response.single({"current_utc": clock.iso(instant)})


# ---------------------------------------------------------------------------
# POST /conference  |  GET /conference
# ---------------------------------------------------------------------------


@bp.route("/conference", methods=["POST"])
@api(("PlatformAdmin",), needs_conference=False)
def create_conference():
    if db.conference is not None:
        raise ApiError("ERR_CONFERENCE_ALREADY_EXISTS")
    body = raw_body()
    name = validation.get_str(body, "name")
    fiscal_year_start_month = validation.get_int(
        body, "fiscal_year_start_month", required=False, default=7, minimum=1, maximum=12
    )
    current_fiscal_year = validation.get_int(
        body, "current_fiscal_year", required=False, default=2027
    )
    unit_value_cents = validation.get_int(
        body, "unit_value_cents", required=False, default=34000000
    )
    phase_schedule_years = validation.get_int(
        body, "phase_schedule_years", required=False, default=3, minimum=1
    )

    conference = base_record()
    conference.update(
        {
            "name": name,
            "fiscal_year_start_month": fiscal_year_start_month,
            "current_fiscal_year": current_fiscal_year,
            "unit_value_cents": unit_value_cents,
            "phase_schedule_years": phase_schedule_years,
            "governance_status": "FORMING",
            "approved_operating_expense_cents": 0,
            "approved_governance_expense_cents": 0,
            "reserve_target_cents": 0,
            "reserve_balance_cents": 0,
            "reserve_posture": "OPEN",
            "funded_ratio_bps": 10000,
            "escrow_balance_cents": 0,
            "governance_fee_revenue_cents": 0,
            "validated_postseason_unit_count": 0,
        }
    )
    db.conference = conference
    return response.single(serializers.conference(conference), 201)


@bp.route("/conference", methods=["GET"])
@api(ALL_ROLES)
def read_conference():
    return response.single(serializers.conference(db.conference))


# ---------------------------------------------------------------------------
# POST /conference/reserve-transfers
# ---------------------------------------------------------------------------


@bp.route("/conference/reserve-transfers", methods=["POST"])
@api(("Treasurer",))
def reserve_transfer():
    conference = db.conference
    body = raw_body()
    transfer_type = validation.get_enum(
        body, "transfer_type", ("CONTRIBUTION", "WITHDRAWAL")
    )
    amount_cents = validation.get_int(body, "amount_cents")
    expected_version = validation.get_int(
        body, "expected_conference_version", minimum=None
    )
    validation.get_optional_str(body, "memo")

    if expected_version != conference["version"]:
        raise ApiError("ERR_STALE_CONFERENCE_VERSION")

    if transfer_type == "WITHDRAWAL":
        if amount_cents > conference["reserve_balance_cents"]:
            raise ApiError("ERR_RESERVE_INSUFFICIENT")
        conference["reserve_balance_cents"] -= amount_cents
    else:
        conference["reserve_balance_cents"] += amount_cents

    conference_service.derive_reserve_posture(conference)
    touch(conference)
    return response.single(serializers.conference(conference))


# ---------------------------------------------------------------------------
# POST /venues
# ---------------------------------------------------------------------------


@bp.route("/venues", methods=["POST"])
@api(("ScheduleCoordinator", "PlatformAdmin"))
def create_venue():
    body = raw_body()
    name = validation.get_str(body, "name")
    city = validation.get_str(body, "city")
    seating_capacity = validation.get_int(body, "seating_capacity", minimum=1)
    concurrent_event_capacity = validation.get_int(
        body, "concurrent_event_capacity", required=False, default=1, minimum=1
    )

    venue = base_record()
    venue.update(
        {
            "name": name,
            "city": city,
            "seating_capacity": seating_capacity,
            "concurrent_event_capacity": concurrent_event_capacity,
        }
    )
    db.venues[venue["id"]] = venue
    return response.single(serializers.venue(venue), 201)
