"""ContractorBooking half-open intervals and occupant counting (PRD 3.5)."""

import calc
import domain
import guards
import repo
import validation as v
from errors import ApiError
from middleware import ANY_ROLE, FRANCHISEE_OWNER
from routing import route

OPEN_LIFE_SAFETY_STATUSES = ("SCOPED", "DEFERRED_PENDING_EXTENSION", "IN_PROGRESS")


@route("/pip/contractor-bookings", ["POST"], (FRANCHISEE_OWNER,))
def create_booking():
    body = v.body_json()
    contractor = guards.resolve_body_fk(body, "contractor_id", "contractors")
    phase = guards.resolve_body_fk(body, "phase_id", "phases")

    v.require(
        body, "contractor_id", "phase_id", "start_datetime", "end_datetime", "crew_size"
    )
    start_raw = v.get_str(body, "start_datetime", min_len=1)
    end_raw = v.get_str(body, "end_datetime", min_len=1)
    crew_size = v.get_int(body, "crew_size", minimum=1)

    start = calc.parse_datetime(start_raw)
    end = calc.parse_datetime(end_raw)
    if start is None or end is None or end <= start:
        raise ApiError(
            "ERR_INVALID_DATE_RANGE",
            "end_datetime must be a valid instant strictly later than start_datetime",
        )

    plan = repo.find("plans", phase["plan_id"])

    # band 6 — the brand-vetting rule, in both of its arms.
    needs_vetting = contractor["trade"] == "FIRE_PROTECTION"
    if not needs_vetting and plan is not None:
        for item in domain.plan_items(plan["id"]):
            if (
                item["category"] == "LIFE_SAFETY"
                and item["status"] in OPEN_LIFE_SAFETY_STATUSES
            ):
                needs_vetting = True
                break
    if needs_vetting and not contractor["brand_approved"]:
        raise ApiError(
            "ERR_CONTRACTOR_NOT_BRAND_APPROVED",
            "this booking requires a brand-approved contractor",
        )

    # band 7 — occupant counting on strict overlap, no buffer.
    occupants = 0
    for other in domain.bookings_of_contractor(contractor["id"]):
        if other["status"] != "BOOKED":
            continue
        other_start = calc.parse_datetime(other["start_datetime"])
        other_end = calc.parse_datetime(other["end_datetime"])
        if other_start is None or other_end is None:
            continue
        if start < other_end and other_start < end:
            occupants += 1
    if occupants >= contractor["max_concurrent_bookings"]:
        raise ApiError(
            "ERR_CONTRACTOR_DOUBLE_BOOKED",
            "the contractor already has %d concurrent bookings on that interval"
            % occupants,
        )

    phase_start = calc.day_start(calc.parse_date(phase["start_date"]))
    phase_end = calc.day_start(
        calc.add_days(calc.parse_date(phase["end_date"]), 1)
    )
    if start < phase_start or end > phase_end:
        raise ApiError(
            "ERR_BOOKING_OUTSIDE_PHASE_WINDOW",
            "the booking interval must sit inside the phase's closure window",
        )

    # band 8
    if plan is not None:
        guards.require_owner(domain.property_of_plan(plan))

    row = repo.new_row(
        {
            "contractor_id": contractor["id"],
            "phase_id": phase["id"],
            "start_datetime": start_raw,
            "end_datetime": end_raw,
            "crew_size": crew_size,
            "status": "BOOKED",
        }
    )
    repo.insert("bookings", row)
    return repo.single(row, 201)


@route("/pip/contractor-bookings/<row_id>", ["GET"], ANY_ROLE)
def get_booking(row_id):
    return repo.single(repo.must_find("bookings", row_id))


@route("/pip/contractor-bookings", ["GET"], ANY_ROLE)
def list_bookings():
    limit, offset = v.pagination()
    rows = repo.rows("bookings")
    for field in ("contractor_id", "phase_id", "status"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)
