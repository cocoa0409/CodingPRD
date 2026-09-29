"""The epoch advance: five steps in a pinned order (PRD section 3.9)."""
from flask import Blueprint

import db
from middleware import PERMIT_OFFICER, require_roles
from response import ok_object
from routes.closures import covers_pitch, scope_pitches
from services import domain
from utils import fmt_dt, season_end_utc, sort_created, touch

bp = Blueprint("ops", __name__, url_prefix="/busking")


def _lift_closures(clock):
    """Step 1: lift ACTIVE orders whose ends_at is behind the clock."""
    lifted = 0
    for closure in sort_created(db.all_of("closures")):
        if closure["status"] != "ACTIVE" or not closure["ends_at"] < clock:
            continue
        closure["status"] = "LIFTED"
        touch(closure)
        zone = db.get("zones", closure["zone_id"])
        if zone is not None:
            zone["active_closure_count"] -= 1
            touch(zone)
        for pitch in scope_pitches(closure):
            still_covered = any(
                other["status"] == "ACTIVE" and covers_pitch(other, pitch)
                for other in db.all_of("closures"))
            if not still_covered and pitch["availability_status"] != "OPEN":
                pitch["availability_status"] = "OPEN"
                touch(pitch)
        lifted += 1
    return lifted


def _sweep_invoices(clock):
    """Step 2: PENDING invoices past due_at, plus the renewal lapse edge."""
    swept = 0
    for invoice in sort_created(db.all_of("invoices")):
        if invoice["status"] != "PENDING" or not invoice["due_at"] < clock:
            continue
        invoice["status"] = "PAST_DUE"
        touch(invoice)
        swept += 1
        permit = db.get("permits", invoice["permit_id"])
        if (invoice["invoice_kind"] == "RENEWAL" and permit is not None
                and permit["lifecycle_status"] == "RENEWAL_PENDING"):
            permit["lifecycle_status"] = "ACTIVE"
            permit["next_season_year"] = None
            touch(permit)
    return swept


def _expire_permits(clock):
    """Step 3: permits whose season has ended."""
    expired = 0
    for permit in sort_created(db.all_of("permits")):
        if permit["lifecycle_status"] not in ("ACTIVE", "RENEWAL_PENDING"):
            continue
        if not clock > season_end_utc(permit["season_year"]):
            continue
        was_renewal_pending = permit["lifecycle_status"] == "RENEWAL_PENDING"
        permit["lifecycle_status"] = "EXPIRED"
        if was_renewal_pending:
            for invoice in domain.permit_invoices(permit):
                if invoice["invoice_kind"] == "RENEWAL" and invoice["status"] in ("PENDING", "PAST_DUE"):
                    invoice["status"] = "VOID"
                    touch(invoice)
        domain.cancel_future_bookings(permit, "CANCELLED_BY_EXPIRY")
        domain.forfeit_submitted_entries(permit)
        touch(permit)
        expired += 1
    return expired


def _complete_bookings(clock):
    """Step 4: sessions whose end_at has arrived; minutes are NOT released."""
    completed = 0
    for booking in sort_created(db.all_of("bookings")):
        if booking["status"] not in ("RESERVED", "RELOCATED"):
            continue
        if not booking["end_at"] <= clock:
            continue
        booking["status"] = "COMPLETED"
        touch(booking)
        completed += 1
    return completed


def _rescore_performers():
    """Step 5: recompute both conduct figures and bar-cascade where needed."""
    rescored = 0
    for performer in sort_created(db.all_of("performers")):
        if performer["upheld_complaint_count"] <= 0:
            continue
        domain.rescore_performer(performer)
        rescored += 1
    return rescored


@bp.post("/ops-runs")
def advance_epoch():
    require_roles([PERMIT_OFFICER])
    clock = db.now()
    # The five steps run in this pinned order.
    closures_lifted = _lift_closures(clock)
    invoices_past_due = _sweep_invoices(clock)
    permits_expired = _expire_permits(clock)
    bookings_completed = _complete_bookings(clock)
    performers_rescored = _rescore_performers()
    return ok_object({
        "processed_at": fmt_dt(clock),
        "closures_lifted_count": closures_lifted,
        "invoices_past_due_count": invoices_past_due,
        "permits_expired_count": permits_expired,
        "bookings_completed_count": bookings_completed,
        "performers_rescored_count": performers_rescored,
    })
