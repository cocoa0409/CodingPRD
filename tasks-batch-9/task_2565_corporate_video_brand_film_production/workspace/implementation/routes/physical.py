"""Locations, shoot days, call sheets, wrap/cancel and equipment (PRD 3.4, 3.5, 3.6, 3.7)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import derive
import workflow
from auth import authenticate
from envelope import respond_created, respond_list, respond_object
from errors import ApiError
from lookups import find_location, find_project, find_shoot_day
from store import clock_now, db, iso, new_row, parse_instant, touch
from validation import (field_date, field_identifier, field_instant, field_integer,
                        field_string, json_body, paginate, pagination, require_interval)

bp = Blueprint("physical", __name__)


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------
@bp.get("/locations/<location_id>")
def read_location(location_id):
    authenticate(("ProductionCoordinator", "LineProducer", "ComplianceOfficer"))
    location = find_location(location_id)
    return respond_object(derive.location_out(location))


@bp.post("/locations")
def create_location():
    authenticate(("ProductionCoordinator", "LineProducer"))
    body = json_body()
    name = field_string(body, "name", 1, 120)
    address = field_string(body, "address", 1, 200)
    stage_count = field_integer(body, "stage_count", 1, 12)
    daily_fee_cents = field_integer(body, "daily_fee_cents", minimum=0)
    insurance_minimum_cents = field_integer(body, "insurance_minimum_cents", minimum=0)
    permit_authority = field_string(body, "permit_authority", 1, 120)
    row = new_row(
        name=name,
        address=address,
        stage_count=stage_count,
        daily_fee_cents=daily_fee_cents,
        insurance_minimum_cents=insurance_minimum_cents,
        permit_authority=permit_authority,
    )
    db["locations"][row["id"]] = row
    return respond_created(derive.location_out(row))


# --------------------------------------------------------------------------
# Shoot days
# --------------------------------------------------------------------------
def _day_sort_key(row):
    return (row["call_time"], row["created_at"], row["_seq"])


@bp.get("/shoot-days/<shoot_day_id>")
def read_shoot_day(shoot_day_id):
    authenticate(("ProductionCoordinator", "LineProducer", "ComplianceOfficer", "CrewMember"))
    shoot_day = find_shoot_day(shoot_day_id)
    return respond_object(derive.shoot_day_out(shoot_day))


@bp.get("/shoot-days")
def list_shoot_days():
    authenticate(("ProductionCoordinator", "LineProducer", "ComplianceOfficer"))
    limit, offset = pagination()
    rows = list(db["shoot_days"].values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    location_id = request.args.get("location_id")
    if location_id is not None:
        rows = [r for r in rows if r["location_id"] == location_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=_day_sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_list([derive.shoot_day_out(r) for r in page], limit, offset, total)


@bp.get("/shoot-days/<shoot_day_id>/equipment-reservations")
def list_day_reservations(shoot_day_id):
    authenticate(("ProductionCoordinator", "LineProducer"))
    limit, offset = pagination()
    shoot_day = find_shoot_day(shoot_day_id)
    rows = derive.shoot_day_reservations(shoot_day["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return respond_list([derive.equipment_reservation_out(r) for r in page], limit, offset, total)


@bp.post("/shoot-days")
def create_shoot_day():
    authenticate(("ProductionCoordinator",))
    body = json_body()
    project_id = field_identifier(body, "project_id")
    location_id = field_identifier(body, "location_id")
    shoot_date = field_date(body, "shoot_date")
    call_time = field_instant(body, "call_time")
    wrap_time = field_instant(body, "wrap_time")
    require_interval(call_time, wrap_time, "call_time", "wrap_time")
    if shoot_date != call_time.strftime("%Y-%m-%d"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "shoot_date must equal the UTC date part of call_time.")

    project = find_project(project_id)
    location = find_location(location_id)
    if project["status"] not in ("SCOPED", "IN_PRODUCTION"):
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "Shoot days may not be scheduled while the project is %s."
                       % project["status"])

    # Half-open overlap: a day that wraps exactly when the next is called does
    # not consume a second stage (PRD 3.4).
    occupied = 0
    for other in derive.location_shoot_days(location["id"]):
        if other["status"] not in ("PLANNED", "CONFIRMED"):
            continue
        other_call = parse_instant(other["call_time"])
        other_wrap = parse_instant(other["wrap_time"])
        if call_time < other_wrap and other_call < wrap_time:
            occupied += 1
    if occupied >= location["stage_count"]:
        raise ApiError("ERR_LOCATION_CAPACITY_EXCEEDED",
                       "All %d stages at this location are occupied for the requested window."
                       % location["stage_count"])

    row = new_row(
        project_id=project["id"],
        location_id=location["id"],
        shoot_date=shoot_date,
        call_time=iso(call_time),
        wrap_time=iso(wrap_time),
        status="PLANNED",
        call_sheet_status="DRAFT",
        call_sheet_published_at=None,
        cancellation_reason=None,
    )
    db["shoot_days"][row["id"]] = row
    return respond_created(derive.shoot_day_out(row))


def _require_permit_and_coi(shoot_day):
    """Priority 29 then priority 30: a day lacking both reports the permit error."""
    if not derive.permit_ok(shoot_day):
        raise ApiError("ERR_PERMIT_WINDOW_MISMATCH",
                       "No ISSUED, unexpired FILM_PERMIT covers this shoot day's window.")
    if not derive.coi_ok(shoot_day):
        raise ApiError("ERR_INSUFFICIENT_COI_COVERAGE",
                       "No ISSUED, unexpired LIABILITY_COI with sufficient coverage covers "
                       "this shoot day's window.")


@bp.post("/shoot-days/<shoot_day_id>/confirm")
def confirm_shoot_day(shoot_day_id):
    authenticate(("ProductionCoordinator",))
    json_body(required=False)
    shoot_day = find_shoot_day(shoot_day_id)
    project = derive.project_of_shoot_day(shoot_day)
    if project["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "Shoot-day confirmation requires the project to be IN_PRODUCTION.")
    if shoot_day["status"] != "PLANNED":
        raise ApiError("ERR_SHOOT_DAY_STATE_INVALID",
                       "Confirmation requires the shoot day to be PLANNED.")
    _require_permit_and_coi(shoot_day)
    # No crew or equipment sweep: every child keeps the status it already had.
    shoot_day["status"] = "CONFIRMED"
    touch(shoot_day)
    return respond_object(derive.shoot_day_out(shoot_day))


@bp.post("/shoot-days/<shoot_day_id>/publish-call-sheet")
def publish_call_sheet(shoot_day_id):
    authenticate(("ProductionCoordinator",))
    json_body(required=False)
    shoot_day = find_shoot_day(shoot_day_id)
    if shoot_day["status"] != "CONFIRMED":
        raise ApiError("ERR_SHOOT_DAY_STATE_INVALID",
                       "Call-sheet publication requires the shoot day to be CONFIRMED.")
    _require_permit_and_coi(shoot_day)
    if derive.compliance_posture(shoot_day) == "BLOCKED":
        raise ApiError("ERR_COMPLIANCE_POSTURE_BLOCKED",
                       "The day's live compliance posture is BLOCKED.")
    confirmed = derive.confirmed_crew_count(shoot_day["id"])
    if confirmed < calc.MIN_CONFIRMED_CREW_FOR_CALL_SHEET:
        raise ApiError("ERR_MIN_CREW_NOT_MET",
                       "Only %d crew bookings are confirmed; %d are required."
                       % (confirmed, calc.MIN_CONFIRMED_CREW_FOR_CALL_SHEET))
    call_time = parse_instant(shoot_day["call_time"])
    deadline = call_time - timedelta(hours=calc.CALL_SHEET_LEAD_HOURS)
    if clock_now() > deadline:
        raise ApiError("ERR_CALL_SHEET_WINDOW_CLOSED",
                       "The call sheet may only be published at or before %s." % iso(deadline))
    shoot_day["call_sheet_status"] = "PUBLISHED"
    shoot_day["call_sheet_published_at"] = iso(clock_now())
    touch(shoot_day)
    return respond_object(derive.shoot_day_out(shoot_day))


@bp.post("/shoot-days/<shoot_day_id>/cancel")
def cancel_shoot_day(shoot_day_id):
    authenticate(("ProductionCoordinator", "LineProducer"))
    body = json_body()
    cancellation_reason = field_string(body, "cancellation_reason", 1, None)
    shoot_day = find_shoot_day(shoot_day_id)
    if shoot_day["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_SHOOT_DAY_STATE_INVALID",
                       "Cancellation requires the shoot day to be PLANNED or CONFIRMED.")
    project = derive.project_of_shoot_day(shoot_day)
    watch = workflow.LedgerWatch(project)
    shoot_day["status"] = "CANCELLED"
    shoot_day["cancellation_reason"] = cancellation_reason
    touch(shoot_day)
    workflow.cascade_shoot_day_cancel(shoot_day)
    watch.finish()
    workflow.bubble_project_into_post(project)
    return respond_object(derive.shoot_day_out(shoot_day))


@bp.post("/shoot-days/<shoot_day_id>/wrap")
def wrap_shoot_day(shoot_day_id):
    authenticate(("ProductionCoordinator",))
    json_body(required=False)
    shoot_day = find_shoot_day(shoot_day_id)
    if shoot_day["status"] != "CONFIRMED":
        raise ApiError("ERR_SHOOT_DAY_STATE_INVALID",
                       "Wrap requires the shoot day to be CONFIRMED.")
    wrap_time = parse_instant(shoot_day["wrap_time"])
    if clock_now() < wrap_time:
        raise ApiError("ERR_SHOOT_DAY_STATE_INVALID",
                       "Wrap requires the logical clock to have reached %s."
                       % shoot_day["wrap_time"])
    if derive.compliance_posture(shoot_day) == "BLOCKED":
        raise ApiError("ERR_COMPLIANCE_POSTURE_BLOCKED",
                       "The day's live compliance posture is BLOCKED.")
    project = derive.project_of_shoot_day(shoot_day)
    watch = workflow.LedgerWatch(project)
    shoot_day["status"] = "WRAPPED"
    touch(shoot_day)
    workflow.cascade_shoot_day_wrap(shoot_day)
    watch.finish()
    workflow.bubble_project_into_post(project)
    return respond_object(derive.shoot_day_out(shoot_day))


# --------------------------------------------------------------------------
# Equipment reservations
# --------------------------------------------------------------------------
@bp.post("/equipment-reservations")
def create_reservation():
    authenticate(("ProductionCoordinator",))
    body = json_body()
    shoot_day_id = field_identifier(body, "shoot_day_id")
    vendor_name = field_string(body, "vendor_name", 1, 120)
    kit_label = field_string(body, "kit_label", 1, 120)
    unit_count = field_integer(body, "unit_count", 1, 50)
    daily_rate_cents = field_integer(body, "daily_rate_cents", minimum=1)
    pickup_at = field_instant(body, "pickup_at")
    return_at = field_instant(body, "return_at")
    require_interval(pickup_at, return_at, "pickup_at", "return_at")

    shoot_day = find_shoot_day(shoot_day_id)
    if shoot_day["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_SHOOT_DAY_STATE_INVALID",
                       "Equipment may only be reserved against a PLANNED or CONFIRMED day.")
    call_time = parse_instant(shoot_day["call_time"])
    wrap_time = parse_instant(shoot_day["wrap_time"])
    earliest = call_time - timedelta(hours=calc.PREP_WINDOW_HOURS)
    latest = wrap_time + timedelta(hours=calc.RETURN_WINDOW_HOURS)
    if pickup_at < earliest or return_at > latest:
        raise ApiError("ERR_EQUIPMENT_WINDOW_OUT_OF_RANGE",
                       "The rental must sit within %s and %s." % (iso(earliest), iso(latest)))

    money = calc.equipment_reservation_cost(pickup_at, return_at, unit_count, daily_rate_cents)
    project = derive.project_of_shoot_day(shoot_day)
    workflow.enforce_allowance(project, money["total_cost_cents"])

    watch = workflow.LedgerWatch(project)
    row = new_row(
        shoot_day_id=shoot_day["id"],
        vendor_name=vendor_name,
        kit_label=kit_label,
        unit_count=unit_count,
        daily_rate_cents=daily_rate_cents,
        pickup_at=iso(pickup_at),
        return_at=iso(return_at),
        rental_days=money["rental_days"],
        total_cost_cents=money["total_cost_cents"],
        status="RESERVED",
    )
    db["equipment_reservations"][row["id"]] = row
    watch.finish()
    return respond_created(derive.equipment_reservation_out(row))
