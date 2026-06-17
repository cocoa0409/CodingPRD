"""Shared booking gate checks and slot debit/credit (PRD §3.3, §3.5, §2.11).

The validation priority order (PRD §2.11) for the booking-family endpoints, after
auth/existence/ownership/state/OCC have already been checked by the route, is:
  7  height          ERR_HEIGHT_REQUIREMENT_NOT_MET
  8  accessibility    ERR_ACCESSIBILITY_BLOCKED
  9  temporal window  ERR_WINDOW_NOT_REDEEMABLE
  10 peak gate        ERR_PEAK_GATE_BLOCKED
  11 VQ ceiling       ERR_VQ_LIMIT_REACHED
  13 window exhausted ERR_WINDOW_EXHAUSTED
"""
import db
import domain
import errors


def check_height(guest, ride):
    if guest["height_cm"] < ride["min_height_cm"]:
        errors.err(errors.ERR_HEIGHT_REQUIREMENT_NOT_MET,
                   "Guest height below ride minimum")


def check_accessibility(guest, ride):
    if guest["uses_wheelchair"] and ride["wheelchair_transfer_required"]:
        errors.err(errors.ERR_ACCESSIBILITY_BLOCKED,
                   "Guest cannot transfer for this ride")


def check_window_not_elapsed(window, park):
    """For a VIRTUAL_QUEUE booking: window_end_utc must be strictly after current_utc."""
    now = domain.park_now(park)
    end = domain.parse_dt(window["window_end_utc"], "window_end_utc")
    if now is not None and now >= end:
        errors.err(errors.ERR_WINDOW_NOT_REDEEMABLE, "Return window has already elapsed")


def check_peak_gate(park, guest):
    if park["day_phase"] == "PEAK":
        if not domain.guest_has_active_multipass(park["id"], guest["id"]):
            errors.err(errors.ERR_PEAK_GATE_BLOCKED,
                       "Peak phase requires an active MULTI_PASS hold")


def check_vq_ceiling(guest):
    if domain.active_vq_reservation_count(guest["id"]) >= domain.VQ_MAX_PER_GUEST:
        errors.err(errors.ERR_VQ_LIMIT_REACHED,
                   "Guest at the per-guest virtual-queue ceiling")


def check_window_capacity(window):
    if window["reserved_count"] >= window["slot_capacity"]:
        errors.err(errors.ERR_WINDOW_EXHAUSTED, "Return window is exhausted")


def create_vq_reservation(ride, guest, window, park, party_id=None):
    """Create a HELD VIRTUAL_QUEUE reservation and debit slot counters.

    Caller is responsible for having run the priority-ordered gates. This routine
    performs the side effects of a successful create (PRD §3.3):
      - reservation created HELD
      - window.reserved_count += 1, ride.booked_slot_count += 1
      - window EXHAUSTED bubble-up
      - ReturnWindow.version advanced (counter change = mutation)
      - posted_wait recomputed
    """
    res = db.stamp_new({
        "ride_id": ride["id"],
        "guest_id": guest["id"],
        "return_window_id": window["id"],
        "party_id": party_id,
        "queue_type": "VIRTUAL_QUEUE",
        "reservation_status": "HELD",
        "redistributed_from_window_id": None,
    })
    db.reservations[res["id"]] = res

    window["reserved_count"] += 1
    db.touch(window)
    domain.maybe_exhaust_window(window)

    ride["booked_slot_count"] += 1
    domain.recompute_posted_wait(ride)
    db.touch(ride)

    # The slot debit is a same-request mutation of this reservation too (PRD §2.4/§2.6:
    # a derived-counter change is a mutation of the owning resource). The created VQ
    # reservation and its ReturnWindow advance their version in lockstep, so the
    # reservation's response version equals the window's new version — this is what a
    # subsequent booking on the same window echoes as expected_return_window_id_version.
    res["version"] = window["version"]
    res["updated_at"] = window["updated_at"]
    return res


def create_single_rider_reservation(ride, guest, window, party_id=None):
    """SINGLE_RIDER consumes no slot; leaves reserved_count/window status untouched."""
    res = db.stamp_new({
        "ride_id": ride["id"],
        "guest_id": guest["id"],
        "return_window_id": window["id"],
        "party_id": party_id,
        "queue_type": "SINGLE_RIDER",
        "reservation_status": "HELD",
        "redistributed_from_window_id": None,
    })
    db.reservations[res["id"]] = res
    return res
