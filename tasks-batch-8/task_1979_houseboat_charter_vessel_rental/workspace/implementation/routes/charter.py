"""Itinerary, orientation, checkout, return, settle (PRD §3.5–§3.8)."""

from flask import Blueprint

import common
import db
import errors
import response
from middleware import require_roles
from routes.bookings import ALL_ROLES, check_booking_owner, load_booking
from services import booking_ops, settlement

bp = Blueprint("charter", __name__)


# ---------------------------------------------------------------------------
# Itinerary
# ---------------------------------------------------------------------------

@bp.put("/bookings/<bid>/itinerary")
@require_roles("Renter")
def put_itinerary(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    body = common.json_body()
    waypoints_raw = body.get("waypoints")

    # Priority 4: each referenced zone_id must exist.
    if isinstance(waypoints_raw, list):
        for wp in waypoints_raw:
            if isinstance(wp, dict):
                zid = wp.get("zone_id")
                if isinstance(zid, str) and db.get("geo_zones", zid) is None:
                    errors.err(errors.ERR_NOT_FOUND, f"GeoZone {zid} does not exist")

    # Priority 5: body well-formedness.
    waypoints_raw = common.as_list(common.req_field(body, "waypoints"), "waypoints")
    waypoints = []
    for wp in waypoints_raw:
        if not isinstance(wp, dict):
            errors.err(errors.ERR_INVALID_REQUEST, "Each waypoint must be an object")
        zid = common.as_str(common.req_field(wp, "zone_id"), "zone_id")
        night = common.parse_date(common.req_field(wp, "night_date"), "night_date")
        waypoints.append({"zone_id": zid, "night_date": night})

    # Priority 7: state gate.
    if booking["status"] not in ("HELD", "CONFIRMED"):
        errors.err(
            errors.ERR_INVALID_STATE,
            f"Itinerary cannot be submitted on a booking in state {booking['status']}",
        )

    vessel = db.get("vessels", booking["vessel_id"])

    # Business checks in their fixed order: waypoint range, zone size-class,
    # zone capacity (strict <, evaluated against other bookings only).
    for wp in waypoints:
        if not (booking["start_date"] <= wp["night_date"] < booking["end_date"]):
            errors.err(
                errors.ERR_ITINERARY_WAYPOINT_OUT_OF_RANGE,
                f"night_date {wp['night_date'].isoformat()} is not a night of the booking",
            )
    for wp in waypoints:
        zone = db.get("geo_zones", wp["zone_id"])
        if vessel["size_class"] not in zone["allowed_size_classes"]:
            errors.err(
                errors.ERR_ZONE_SIZE_CLASS_FORBIDDEN,
                f"Zone {zone['zone_code']} does not allow {vessel['size_class']}",
            )
    for wp in waypoints:
        zone = db.get("geo_zones", wp["zone_id"])
        occupancy = booking_ops.zone_night_occupancy(
            wp["zone_id"], wp["night_date"], exclude_booking_id=booking["id"]
        )
        if occupancy >= zone["max_vessels_per_night"]:
            errors.err(
                errors.ERR_ZONE_CAPACITY_EXCEEDED,
                f"Zone {zone['zone_code']} is at capacity on {wp['night_date'].isoformat()}",
            )

    # Valid: supersede any prior APPROVED itinerary, create the replacement
    # already APPROVED.
    for it in db.all_of("itineraries"):
        if it["booking_id"] == booking["id"] and it["status"] == "APPROVED":
            it["status"] = "SUPERSEDED"
            db.touch(it)

    rec = db.base_record()
    rec.update({
        "booking_id": booking["id"],
        "waypoints": waypoints,
        "status": "APPROVED",
    })
    db.insert("itineraries", rec)
    return response.ok(common.itinerary_out(rec), status=201)


@bp.get("/bookings/<bid>/itinerary")
@require_roles(*ALL_ROLES)
def list_itineraries(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    itineraries = [i for i in db.all_of("itineraries") if i["booking_id"] == bid]
    page, total, limit, offset = common.paginate(itineraries)
    return response.list_ok(
        [common.itinerary_out(i) for i in page], total, limit, offset
    )


# ---------------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------------

@bp.post("/bookings/<bid>/orientation/sign-item")
@require_roles("Renter")
def sign_orientation_item(bid, user_id, role):
    booking = load_booking(bid)
    check_booking_owner(booking, user_id, role)
    body = common.json_body()
    item_code = common.as_str(common.req_field(body, "item_code"), "item_code")

    item = None
    for it in booking["orientation_items"]:
        if it["item_code"] == item_code:
            item = it
            break
    if item is None:
        errors.err(
            errors.ERR_INVALID_REQUEST,
            f"Unknown orientation item_code {item_code} on this booking",
        )
    if booking["orientation_status"] != "IN_PROGRESS":
        errors.err(
            errors.ERR_INVALID_STATE,
            f"Orientation in state {booking['orientation_status']} cannot be signed",
        )

    item["signed"] = True
    if all(it["signed"] for it in booking["orientation_items"]):
        booking["orientation_status"] = "COMPLETED"
    db.touch(booking)
    return response.ok(common.booking_out(booking))


@bp.post("/bookings/<bid>/orientation/countersign")
@require_roles("DockStaff")
def countersign_orientation(bid, user_id, role):
    booking = load_booking(bid)
    body = common.json_body()
    approved = common.as_bool(common.req_field(body, "approved"), "approved")
    item_code = common.opt_field(body, "item_code")

    item = None
    if not approved:
        if item_code is None:
            errors.err(
                errors.ERR_INVALID_REQUEST,
                "item_code is required when approved is false",
            )
        common.as_str(item_code, "item_code")
        for it in booking["orientation_items"]:
            if it["item_code"] == item_code:
                item = it
                break
        if item is None:
            errors.err(
                errors.ERR_INVALID_REQUEST,
                f"Unknown orientation item_code {item_code} on this booking",
            )

    if booking["orientation_status"] != "COMPLETED":
        errors.err(
            errors.ERR_INVALID_STATE,
            f"Orientation in state {booking['orientation_status']} cannot be countersigned",
        )

    if approved:
        booking["orientation_status"] = "COUNTERSIGNED"
    else:
        item["signed"] = False
        booking["orientation_status"] = "IN_PROGRESS"
    db.touch(booking)
    return response.ok(common.booking_out(booking))


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

@bp.post("/bookings/<bid>/checkout")
@require_roles("DockStaff")
def checkout_booking(bid, user_id, role):
    booking = load_booking(bid)
    body = common.json_body()
    fuel_gauge = common.as_int(
        common.req_field(body, "fuel_gauge_percent"), "fuel_gauge_percent"
    )
    pump_out = common.as_bool(common.req_field(body, "pump_out_done"), "pump_out_done")

    if booking["status"] != "CONFIRMED":
        errors.err(
            errors.ERR_INVALID_STATE,
            f"Booking in state {booking['status']} cannot be checked out",
        )
    today = db.current_date()
    if not (booking["start_date"] <= today < booking["end_date"]):
        errors.err(
            errors.ERR_INVALID_STATE,
            "Checkout is only possible within the stay window",
        )

    # Business gates, mandated order: weather hold first.
    itinerary = settlement.approved_itinerary(booking["id"])
    if itinerary is not None:
        zones = {w["zone_id"] for w in itinerary["waypoints"]}
        now = db.get_clock()
        for a in db.all_of("weather_advisories"):
            if a["status"] != "ACTIVE":
                continue
            if a["window_start"] <= now < a["window_end"] and zones.intersection(
                a["zone_ids"]
            ):
                errors.err(
                    errors.ERR_WEATHER_HOLD_ACTIVE,
                    "An active weather advisory covers the itinerary zones",
                )
    if itinerary is None:
        errors.err(errors.ERR_ITINERARY_REQUIRED, "Checkout requires an APPROVED itinerary")
    if booking["orientation_status"] != "COUNTERSIGNED":
        errors.err(
            errors.ERR_ORIENTATION_NOT_COUNTERSIGNED,
            "Checkout requires a COUNTERSIGNED orientation",
        )
    for t in db.all_of("cleaning_turns"):
        if t["status"] != "IN_PROGRESS":
            continue
        other = db.get("bookings", t["booking_id"])
        if other is not None and other["vessel_id"] == booking["vessel_id"]:
            errors.err(
                errors.ERR_CLEANING_TURN_INCOMPLETE,
                "A cleaning turn is in progress on this vessel",
            )
    if booking["deposit_status"] != "HELD":
        errors.err(errors.ERR_INVALID_STATE, "Deposit dimension is out of order")
    if fuel_gauge < 0 or fuel_gauge > 100:
        errors.err(
            errors.ERR_FUEL_GAUGE_INVALID, "fuel_gauge_percent must be within [0, 100]"
        )

    vessel = db.get("vessels", booking["vessel_id"])
    booking["checkout_fuel_gauge_percent"] = fuel_gauge
    booking["checkout_pump_out_done"] = pump_out
    booking["status"] = "CHECKED_OUT"
    booking["settlement_status"] = "PROVISIONAL"
    booking["provisional_estimate_cents"] = settlement.provisional_estimate(vessel)
    db.touch(booking)
    return response.ok(common.booking_out(booking))


# ---------------------------------------------------------------------------
# Return
# ---------------------------------------------------------------------------

@bp.post("/bookings/<bid>/return")
@require_roles("DockStaff")
def return_booking(bid, user_id, role):
    booking = load_booking(bid)
    body = common.json_body()
    fuel_gauge = common.as_int(
        common.req_field(body, "fuel_gauge_percent"), "fuel_gauge_percent"
    )
    pump_out = common.as_bool(common.req_field(body, "pump_out_done"), "pump_out_done")
    actual_return_at = common.parse_datetime(
        common.req_field(body, "actual_return_at"), "actual_return_at"
    )
    start_dt = settlement._dt_of_date(booking["start_date"])
    if actual_return_at < start_dt:
        errors.err(
            errors.ERR_INVALID_REQUEST,
            "actual_return_at must not precede the booking start",
        )

    if booking["status"] not in ("CHECKED_OUT", "INTERRUPTED"):
        errors.err(
            errors.ERR_INVALID_STATE,
            f"Booking in state {booking['status']} cannot be returned",
        )
    if fuel_gauge < 0 or fuel_gauge > 100:
        errors.err(
            errors.ERR_FUEL_GAUGE_INVALID, "fuel_gauge_percent must be within [0, 100]"
        )

    booking["return_fuel_gauge_percent"] = fuel_gauge
    booking["return_pump_out_done"] = pump_out
    booking["actual_return_at"] = actual_return_at
    booking["status"] = "RETURNED"
    for t in db.all_of("cleaning_turns"):
        if t["booking_id"] == booking["id"] and t["status"] == "SCHEDULED":
            t["status"] = "IN_PROGRESS"
            db.touch(t)
    db.touch(booking)
    return response.ok(common.booking_out(booking))


# ---------------------------------------------------------------------------
# Settle
# ---------------------------------------------------------------------------

@bp.post("/bookings/<bid>/settle")
@require_roles("DockStaff")
def settle_booking(bid, user_id, role):
    booking = load_booking(bid)
    if booking["status"] != "RETURNED":
        errors.err(
            errors.ERR_INVALID_STATE,
            f"Booking in state {booking['status']} cannot be settled",
        )
    turn = None
    for t in db.all_of("cleaning_turns"):
        if t["booking_id"] == booking["id"]:
            turn = t
            break
    if turn is None or turn["status"] != "COMPLETED":
        errors.err(
            errors.ERR_CLEANING_TURN_INCOMPLETE,
            "The booking's cleaning turn is not COMPLETED",
        )

    vessel = db.get("vessels", booking["vessel_id"])
    operational = settlement.final_operational_lines(booking, vessel)

    incident_lines = [
        c
        for c in booking_ops.charges_of(booking["id"])
        if c["status"] == "POSTED"
        and c["line_type"] in ("DAMAGE", "GROUNDING_LIABILITY", "MECHANICAL_REFUND")
    ]

    # Pinned rounding order: each line already rounded; net is the plain sum.
    net = sum(amount for _, amount in operational)
    net += sum(c["amount_cents"] for c in incident_lines)

    # Non-zero operational lines are posted (the cleaning fee is always
    # non-zero, hence always posted); zero-amount lines never are.
    for line_type, amount in operational:
        booking_ops.post_charge(
            booking["id"], line_type, amount, "POSTED", note="final settlement"
        )

    # Deposit waterfall.
    held = booking["deposit_held_cents"]
    if net >= 0:
        applied = min(net, held)
        released = held - applied
    else:
        applied = 0
        released = held
        booking["refund_issued_cents"] += -net
    booking["deposit_applied_cents"] = applied
    booking["deposit_released_cents"] = released

    # Ledger hygiene: positive lines consumed by the deposit ->
    # APPLIED_TO_DEPOSIT; negative refund lines -> REFUNDED.
    all_lines = booking_ops.charges_of(booking["id"])
    if applied > 0:
        for c in all_lines:
            if c["status"] == "POSTED" and c["amount_cents"] > 0:
                c["status"] = "APPLIED_TO_DEPOSIT"
                db.touch(c)
    for c in all_lines:
        if c["status"] == "POSTED" and c["amount_cents"] < 0:
            c["status"] = "REFUNDED"
            db.touch(c)

    if applied == 0:
        booking["deposit_status"] = "RELEASED"
    elif applied == held:
        booking["deposit_status"] = "FULLY_APPLIED"
    else:
        booking["deposit_status"] = "PARTIALLY_APPLIED"

    booking["final_settlement_cents"] = net
    booking["settlement_status"] = "FINALIZED"
    booking["status"] = "CLOSED"
    db.touch(booking)
    return response.ok(common.booking_out(booking))
