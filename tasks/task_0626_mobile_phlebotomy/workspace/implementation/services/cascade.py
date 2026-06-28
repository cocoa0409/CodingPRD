"""Cross-entity cascades and derived-count reconciliation (PRD 2.5, 3.9).

Each automatic, server-initiated transition is itself a mutation: it bumps the
affected entity's version and refreshes updated_at (PRD 2.5).
"""
from db import db, touch
from services import billing

SUSPENSION_THRESHOLD = 3  # PRD 3.9 / scaffold phlebotomist_redraw_strike

LIVE_APPT_STATUSES = {"SCHEDULED", "DISPATCHED", "ARRIVED", "DRAW_COMPLETED"}


def recompute_booked_stop_count(route_day):
    """booked_stop_count = count of appts on this route day in the four live statuses."""
    count = 0
    for a in db.appointments.values():
        if a["route_day_id"] == route_day["id"] and a["status"] in LIVE_APPT_STATUSES:
            count += 1
    return count


def recompute_accessioned_count(order):
    """specimens_accessioned_count = count of order's specimens in ACCESSIONED."""
    count = 0
    for s in db.specimens.values():
        if s["lab_order_id"] == order["id"] and s["status"] == "ACCESSIONED":
            count += 1
    return count


def decrement_route_day_for_appointment(appointment):
    """Free the appointment's route-day slot: booked_stop_count -= 1, version += 1.

    PRD 2.5: a route day's booked_stop_count falls by one on each cancellation or
    redraw-driven appointment cancellation; that touch bumps the route day version.
    """
    route_day = db.route_days.get(appointment["route_day_id"])
    if route_day is None:
        return
    route_day["booked_stop_count"] = recompute_booked_stop_count(route_day)
    touch(route_day)


def restamp_order_total(order):
    """Recompute LabOrder.total_due_cents via the forward-looking estimate."""
    panel = _panel_by_code(order["panel_code"])
    partner = db.lab_partners.get(order["lab_partner_id"])
    if panel is None or partner is None:
        return
    order["total_due_cents"] = billing.order_total_due_estimate(order, panel, partner)


def _panel_by_code(panel_code):
    for p in db.test_panels.values():
        if p["panel_code"] == panel_code:
            return p
    return None


def redraw_cascade(order):
    """PRD 3.9: QNS rejection on a DRAW_COMPLETED order drives the redraw cascade.

    Ordered compensating effects:
      1. order.status -> REDRAW_REQUIRED
      2. order.redraw_count += 1
      3. order.total_due_cents recomputed (now reflects accrued redraw)
      4. order.specimens_accessioned_count recomputed (excludes QNS_REJECTED)
      5. owning appointment -> CANCELLED; route day booked_stop_count -= 1, version += 1
      6. phlebotomist strike: redraw_strike_count += 1; SUSPENDED at threshold
    """
    order["status"] = "REDRAW_REQUIRED"
    order["redraw_count"] += 1
    restamp_order_total(order)
    order["specimens_accessioned_count"] = recompute_accessioned_count(order)
    touch(order)

    appt = db.appointments.get(order["appointment_id"]) if order["appointment_id"] else None
    if appt is not None and appt["status"] in LIVE_APPT_STATUSES:
        appt["status"] = "CANCELLED"
        touch(appt)
        decrement_route_day_for_appointment(appt)
        _strike_phlebotomist(appt["phlebotomist_id"])


def _strike_phlebotomist(phlebotomist_id):
    """PRD 3.9 / phlebotomist_redraw_strike: +1 strike; SUSPENDED at threshold 3."""
    phleb = db.phlebotomists.get(phlebotomist_id)
    if phleb is None:
        return
    phleb["redraw_strike_count"] += 1
    if phleb["redraw_strike_count"] >= SUSPENSION_THRESHOLD:
        phleb["status"] = "SUSPENDED"
    else:
        phleb["status"] = "AVAILABLE"
    touch(phleb)


def maybe_deliver_manifest(manifest):
    """PRD 3.8: if every specimen on the manifest is ACCESSIONED or QNS_REJECTED,
    the manifest bubbles up from IN_TRANSIT to DELIVERED."""
    if manifest["status"] != "IN_TRANSIT":
        return
    specimens = [s for s in db.specimens.values()
                 if s["courier_manifest_id"] == manifest["id"]]
    if not specimens:
        return
    if all(s["status"] in ("ACCESSIONED", "QNS_REJECTED") for s in specimens):
        manifest["status"] = "DELIVERED"
        touch(manifest)


def recompute_manifest_specimen_count(manifest):
    """specimen_count = count of this manifest's specimens in MANIFESTED or ACCESSIONED."""
    count = 0
    for s in db.specimens.values():
        if s["courier_manifest_id"] == manifest["id"] and s["status"] in ("MANIFESTED", "ACCESSIONED"):
            count += 1
    return count
