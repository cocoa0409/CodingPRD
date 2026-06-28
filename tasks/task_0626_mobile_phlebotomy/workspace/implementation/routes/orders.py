"""Lab orders: create, list, get, book appointment, cancel, results (PRD 3.3, 3.4, 3.11)."""
from flask import Blueprint, request, g

import common
import errors
import serializers
from clock import parse_iso
from db import db, stamp_common, touch
from middleware import require_roles
from services import billing, cascade

bp = Blueprint("orders", __name__)


# ---------------------------------------------------------------------------
# Create / list / get
# ---------------------------------------------------------------------------
@bp.post("/lab-orders")
@require_roles("OrderingProvider")
def create_order():
    body = common.get_body()

    patient_full_name = common.require_str(body, "patient_full_name")
    patient_territory_code = common.require_str(body, "patient_territory_code")
    panel_code = common.require_str(body, "panel_code")
    lab_partner_id = common.require_str(body, "lab_partner_id")
    billing_mode = common.require_enum(body, "billing_mode", {"INSURANCE", "SELF_PAY"})
    priority = common.optional_enum(body, "priority", {"ROUTINE", "STAT"}, "ROUTINE")
    insurance_member_id = common.optional_str(body, "insurance_member_id")

    # Priority 4: referenced foreign keys in the body exist (panel_code, lab_partner_id).
    panel = common.find_panel_by_code(panel_code)
    if panel is None:
        errors.fail(errors.ERR_PANEL_NOT_FOUND, "Test panel not found.")
    partner = db.lab_partners.get(lab_partner_id)
    if partner is None:
        errors.fail(errors.ERR_LAB_PARTNER_NOT_FOUND, "Lab partner not found.")

    # Priority 5: INSURANCE order requires insurance_member_id.
    if billing_mode == "INSURANCE" and (insurance_member_id is None or not insurance_member_id.strip()):
        errors.fail(errors.ERR_INVALID_REQUEST, "INSURANCE order requires insurance_member_id.")

    # Priority 8 (business referential): panel ACTIVE and accepted by the partner.
    if panel["status"] != "ACTIVE" or panel["panel_code"] not in partner["accepted_panel_codes"]:
        errors.fail(errors.ERR_PANEL_NOT_ACCEPTED_BY_PARTNER,
                    "Ordered panel is RETIRED or not in the partner's accepted_panel_codes.")

    rec = {
        "ordering_provider_id": g.user_id,
        "patient_full_name": patient_full_name,
        "patient_territory_code": patient_territory_code,
        "panel_code": panel_code,
        "lab_partner_id": lab_partner_id,
        "priority": priority,
        "billing_mode": billing_mode,
        "insurance_member_id": insurance_member_id,
        "appointment_id": None,
        "specimens_required_count": panel["required_tube_count"],
        "specimens_accessioned_count": 0,
        "redraw_count": 0,
        "total_due_cents": 0,
        "status": "ORDERED",
    }
    # Provisional estimate (redraw_count == 0).
    rec["total_due_cents"] = billing.order_total_due_estimate(rec, panel, partner)
    stamp_common(rec)
    db.lab_orders[rec["id"]] = rec

    # PRD 3.3: a companion DRAFT invoice is created for the order at creation time.
    _create_draft_invoice(rec)

    return common.object_response_201(serializers.lab_order(rec))


def _create_draft_invoice(order):
    inv = {
        "lab_order_id": order["id"],
        "billing_mode": order["billing_mode"],
        "lab_fee_cents": 0,
        "convenience_fee_cents": 0,
        "redraw_waiver_cents": 0,
        "total_cents": 0,
        "status": "DRAFT",
    }
    stamp_common(inv)
    db.invoices[inv["id"]] = inv
    return inv


@bp.get("/lab-orders")
@require_roles("OrderingProvider", "Dispatcher", "LabOps", "BillingAgent")
def list_orders():
    limit, offset = common.get_pagination()
    items = list(db.lab_orders.values())
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    lab_partner_id = request.args.get("lab_partner_id")
    if lab_partner_id is not None:
        items = [o for o in items if o["lab_partner_id"] == lab_partner_id]
    appointment_id = request.args.get("appointment_id")
    if appointment_id is not None:
        items = [o for o in items if o["appointment_id"] == appointment_id]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.lab_order(o) for o in page], limit, offset, total)


@bp.get("/lab-orders/<rid>")
@require_roles("OrderingProvider", "Dispatcher", "Phlebotomist", "LabOps", "BillingAgent")
def get_order(rid):
    rec = common.find_order(rid)
    return common.object_response(serializers.lab_order(rec))


# ---------------------------------------------------------------------------
# Book / re-book appointment (PRD 3.4, 2.8)
# ---------------------------------------------------------------------------
@bp.post("/lab-orders/<order_id>/appointments")
@require_roles("Dispatcher")
def book_appointment(order_id):
    order = common.find_order(order_id)  # path existence
    body = common.get_body()

    # Priority 4: route_day_id foreign key exists.
    route_day_id = common.require_str(body, "route_day_id")
    route_day = db.route_days.get(route_day_id)
    if route_day is None:
        errors.fail(errors.ERR_ROUTE_DAY_NOT_FOUND, "Route day not found.")

    # Priority 5: body well-formed (windows, version present).
    window_start_raw = common.require_str(body, "window_start_utc")
    window_end_raw = common.require_str(body, "window_end_utc")
    window_start = parse_iso(window_start_raw)
    window_end = parse_iso(window_end_raw)
    if window_start is None or window_end is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "window_start_utc and window_end_utc must be ISO 8601.")
    if not (window_end > window_start):
        errors.fail(errors.ERR_INVALID_REQUEST, "window_end_utc must be strictly after window_start_utc.")
    expected_version = common.require_int_nonneg(body, "expected_route_day_version")

    # Priority 6: OCC version check runs before route-day business preconditions.
    if expected_version != route_day["version"]:
        errors.fail(errors.ERR_ROUTE_DAY_VERSION_STALE,
                    "expected_route_day_version does not match the route day's current version.")

    # Priority 7: order state legality.
    if order["status"] not in ("ORDERED", "REDRAW_REQUIRED"):
        errors.fail(errors.ERR_ORDER_NOT_SCHEDULABLE, "Order is not in a schedulable state.")

    # Route-day business preconditions (PRD 3.4 sequence).
    if route_day["status"] != "OPEN":
        errors.fail(errors.ERR_ROUTE_DAY_CLOSED, "Route day is CLOSED.")
    if route_day["territory_code"] != order["patient_territory_code"]:
        errors.fail(errors.ERR_TERRITORY_MISMATCH, "Route day territory does not match the order's patient territory.")
    if route_day["booked_stop_count"] >= route_day["stop_capacity"]:
        errors.fail(errors.ERR_ROUTE_DAY_FULL, "Route day is at capacity.")

    # Window must lie within the shift [shift_start, shift_end] (closed) and not
    # overlap another booked window (half-open semantics).
    _check_window(route_day, window_start, window_end)

    # Side effects: create appointment, denormalize phlebotomist, update order/route day.
    appt = {
        "lab_order_id": order["id"],
        "route_day_id": route_day["id"],
        "phlebotomist_id": route_day["phlebotomist_id"],
        "window_start_utc": window_start_raw,
        "window_end_utc": window_end_raw,
        "status": "SCHEDULED",
    }
    stamp_common(appt)
    db.appointments[appt["id"]] = appt

    order["appointment_id"] = appt["id"]
    order["status"] = "SCHEDULED"
    touch(order)

    route_day["booked_stop_count"] = cascade.recompute_booked_stop_count(route_day)
    touch(route_day)

    return common.object_response_201(serializers.appointment(appt))


def _check_window(route_day, window_start, window_end):
    shift_start = parse_iso(route_day["shift_start_utc"])
    shift_end = parse_iso(route_day["shift_end_utc"])
    # Half-open [window_start, window_end) must lie within closed [shift_start, shift_end].
    if window_start < shift_start or window_end > shift_end:
        errors.fail(errors.ERR_APPOINTMENT_WINDOW_CONFLICT, "Window falls outside the route day's shift.")

    # No overlap with another booked appointment's half-open window on the same
    # route day. Back-to-back stops allowed (A.end == B.start is not a conflict).
    for a in db.appointments.values():
        if a["route_day_id"] != route_day["id"]:
            continue
        if a["status"] not in cascade.LIVE_APPT_STATUSES:
            continue
        a_start = parse_iso(a["window_start_utc"])
        a_end = parse_iso(a["window_end_utc"])
        # Half-open overlap: window_start < a_end AND a_start < window_end.
        if window_start < a_end and a_start < window_end:
            errors.fail(errors.ERR_APPOINTMENT_WINDOW_CONFLICT,
                        "Window overlaps another booked appointment.")


# ---------------------------------------------------------------------------
# Reverse-reachability list endpoints
# ---------------------------------------------------------------------------
@bp.get("/lab-orders/<order_id>/appointments")
@require_roles("OrderingProvider", "Dispatcher", "Phlebotomist", "LabOps")
def list_order_appointments(order_id):
    common.find_order(order_id)
    limit, offset = common.get_pagination()
    items = [a for a in db.appointments.values() if a["lab_order_id"] == order_id]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.appointment(a) for a in page], limit, offset, total)


@bp.get("/lab-orders/<order_id>/specimens")
@require_roles("OrderingProvider", "Dispatcher", "Phlebotomist", "LabOps")
def list_order_specimens(order_id):
    common.find_order(order_id)
    limit, offset = common.get_pagination()
    items = [s for s in db.specimens.values() if s["lab_order_id"] == order_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.specimen(s) for s in page], limit, offset, total)


@bp.get("/lab-orders/<order_id>/results")
@require_roles("OrderingProvider", "LabOps", "BillingAgent")
def list_order_results(order_id):
    common.find_order(order_id)
    limit, offset = common.get_pagination()
    items = [r for r in db.lab_results.values() if r["lab_order_id"] == order_id]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.lab_result(r) for r in page], limit, offset, total)


@bp.get("/lab-orders/<order_id>/invoices")
@require_roles("OrderingProvider", "BillingAgent")
def list_order_invoices(order_id):
    common.find_order(order_id)
    limit, offset = common.get_pagination()
    items = [i for i in db.invoices.values() if i["lab_order_id"] == order_id]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.invoice(i) for i in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Results (PRD 3.11) — DRAW_COMPLETED -> RESULTED
# ---------------------------------------------------------------------------
@bp.post("/lab-orders/<order_id>/results")
@require_roles("LabOps")
def post_results(order_id):
    order = common.find_order(order_id)
    body = common.get_body()
    result_value = common.require_str(body, "result_value")

    # Priority 7: state legality.
    if order["status"] != "DRAW_COMPLETED":
        errors.fail(errors.ERR_ORDER_NOT_RESULTABLE, "Order is not in DRAW_COMPLETED.")
    # Business constraint: all specimens accessioned.
    if order["specimens_accessioned_count"] != order["specimens_required_count"]:
        errors.fail(errors.ERR_SPECIMENS_NOT_ACCESSIONED,
                    "specimens_accessioned_count does not equal specimens_required_count.")

    result = {
        "lab_order_id": order["id"],
        "lab_partner_id": order["lab_partner_id"],
        "result_value": result_value,
        "released_to_provider": False,
        "released_to_portal": False,
        "status": "PENDING_RELEASE",
    }
    stamp_common(result)
    db.lab_results[result["id"]] = result

    order["status"] = "RESULTED"
    touch(order)

    return common.object_response_201(serializers.lab_result(result))


# ---------------------------------------------------------------------------
# Cancel (PRD 3.3) — compensation
# ---------------------------------------------------------------------------
@bp.post("/lab-orders/<order_id>/cancel")
@require_roles("OrderingProvider")
def cancel_order(order_id):
    order = common.find_order(order_id)

    if order["status"] not in ("ORDERED", "SCHEDULED", "REDRAW_REQUIRED"):
        errors.fail(errors.ERR_ORDER_NOT_CANCELLABLE, "Order is not in a cancellable state.")

    # Compensate any active appointment: cancel it and free the route-day slot.
    appt = db.appointments.get(order["appointment_id"]) if order["appointment_id"] else None
    if appt is not None and appt["status"] in cascade.LIVE_APPT_STATUSES:
        appt["status"] = "CANCELLED"
        touch(appt)
        cascade.decrement_route_day_for_appointment(appt)

    order["status"] = "CANCELLED"
    touch(order)

    return common.object_response(serializers.lab_order(order))
