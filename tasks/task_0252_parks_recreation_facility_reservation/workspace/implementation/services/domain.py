"""Core domain logic: permit lifecycle, refunds, league roll-up/cascade.

Centralises the side-effect-heavy transitions so routes stay thin. Money is
integer cents; temporal checks use the logical clock.
"""
from datetime import timedelta

from clock import now as clock_now
from db import db, stamp_create, touch
import errors
from services import calculations as calc


# ---------------------------------------------------------------------------
# Pricing / prime overlap at apply time
# ---------------------------------------------------------------------------
def compute_apply_pricing(facility, patron, start_at, end_at):
    """Return (is_prime_requested, pricing_residency, quoted_fee_cents)."""
    _, prime_h, nonprime_h = calc.prime_overlap_hours(
        start_at, end_at, facility["prime_start_hour"], facility["prime_end_hour"]
    )
    is_prime = prime_h > 0
    tier = calc.resolve_residency(patron)
    quoted = calc.provisional_quote_fee(facility, tier, prime_h, nonprime_h)
    return is_prime, tier, quoted


def compute_final_fee(facility, patron, start_at, end_at):
    """Chronological final fee re-resolving residency at grant moment."""
    _, prime_h, nonprime_h = calc.prime_overlap_hours(
        start_at, end_at, facility["prime_start_hour"], facility["prime_end_hour"]
    )
    tier = calc.resolve_residency(patron)
    return calc.final_grant_fee(facility, tier, prime_h, nonprime_h)


# ---------------------------------------------------------------------------
# Double-booking detection (buffer-expanded overlap against GRANTED permits)
# ---------------------------------------------------------------------------
def _intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def has_buffer_conflict(facility, permit, exclude_id=None):
    """True if some GRANTED permit on the facility, widened by buffer_minutes on
    both sides, overlaps this permit's [start_at, end_at)."""
    buffer = timedelta(minutes=facility.get("buffer_minutes", 0))
    p_start, p_end = permit["start_at"], permit["end_at"]
    for other in db.permits.values():
        if other["id"] == permit["id"] or other["id"] == exclude_id:
            continue
        if other["facility_id"] != facility["id"]:
            continue
        if other["status"] != "GRANTED":
            continue
        if _intervals_overlap(other["start_at"] - buffer, other["end_at"] + buffer, p_start, p_end):
            return True
    return False


def slot_has_granted(facility_id, slot_start, slot_end):
    """True if a GRANTED permit already occupies [slot_start, slot_end) (lottery
    draw double-booking check — no buffer per PRD §3.9)."""
    for other in db.permits.values():
        if other["facility_id"] != facility_id:
            continue
        if other["status"] != "GRANTED":
            continue
        if _intervals_overlap(other["start_at"], other["end_at"], slot_start, slot_end):
            return True
    return False


# ---------------------------------------------------------------------------
# COI / payment grant gates
# ---------------------------------------------------------------------------
def check_coi_for_grant(facility, permit):
    """Raise ERR_COI_REQUIRED / ERR_COI_INSUFFICIENT per PRD §3.5 when the
    facility requires a COI."""
    if not facility.get("requires_coi"):
        return
    coi_id = permit.get("coi_id")
    coi = db.insurance_certificates.get(coi_id) if coi_id else None
    if coi is None or coi["status"] != "ACTIVE":
        raise errors.err(errors.ERR_COI_REQUIRED,
                         "Facility requires an ACTIVE certificate of insurance at grant")
    if (coi["coverage_amount_cents"] < facility["min_coi_coverage_cents"]
            or coi["expiry_date"] <= permit["start_at"]):
        raise errors.err(errors.ERR_COI_INSUFFICIENT,
                         "Presented COI coverage below minimum or expired before start")


def check_payment_for_grant(facility, permit, final_fee_cents):
    """Raise ERR_PAYMENT_REQUIRED unless a CAPTURED payment covers fee+deposit."""
    required = final_fee_cents + facility["deposit_cents"]
    for pay in db.payments.values():
        if pay["permit_id"] != permit["id"]:
            continue
        if pay["status"] != "CAPTURED":
            continue
        if pay["fee_component_cents"] + pay["deposit_component_cents"] >= required:
            return
    raise errors.err(errors.ERR_PAYMENT_REQUIRED,
                     "A CAPTURED payment covering final fee + deposit is required to grant")


# ---------------------------------------------------------------------------
# Refund creation
# ---------------------------------------------------------------------------
def _captured_payment_for(permit_id):
    for pay in db.payments.values():
        if pay["permit_id"] == permit_id and pay["status"] == "CAPTURED":
            return pay
    return None


def create_refund(permit, fee_refund, deposit_refund, refund_destination):
    payment = _captured_payment_for(permit["id"])
    total = fee_refund + deposit_refund
    rec = {
        "permit_id": permit["id"],
        "payment_id": payment["id"] if payment else None,
        "refund_destination": refund_destination,
        "fee_refund_cents": fee_refund,
        "deposit_refund_cents": deposit_refund,
        "total_refund_cents": total,
    }
    stamp_create(rec)
    db.refunds[rec["id"]] = rec
    if refund_destination == "CREDIT":
        patron = db.patrons.get(permit["patron_id"])
        if patron is not None:
            patron["wallet_credit_cents"] += total
            touch(patron)
    return rec


# ---------------------------------------------------------------------------
# League roll-up
# ---------------------------------------------------------------------------
def recompute_league(league_id):
    """Recompute league counts + status from child permit states. Treated as a
    mutation of the league (touch). Does not touch CANCELLED leagues."""
    league = db.league_series.get(league_id)
    if league is None or league["status"] == "CANCELLED":
        return
    children = [p for p in db.permits.values() if p.get("league_id") == league_id]
    granted = sum(1 for p in children if p["status"] == "GRANTED")
    conflicted = sum(1 for p in children if p["status"] in ("WAITLISTED", "DENIED"))
    occurrences = league["occurrences"]

    if granted == occurrences:
        new_status = "GRANTED"
    elif granted > 0 and conflicted > 0:
        new_status = "PARTIALLY_GRANTED"
    elif granted > 0 and granted < occurrences:
        # some granted, none conflicted yet -> remains PENDING per scaffold
        # bubble-up rule (PARTIALLY_GRANTED needs a conflict). Keep PENDING.
        new_status = "PENDING"
    else:
        new_status = "PENDING"

    changed = (league["granted_occurrence_count"] != granted
               or league["conflicted_occurrence_count"] != conflicted
               or league["status"] != new_status)
    league["granted_occurrence_count"] = granted
    league["conflicted_occurrence_count"] = conflicted
    league["status"] = new_status
    if changed:
        touch(league)


# ---------------------------------------------------------------------------
# Facility counters
# ---------------------------------------------------------------------------
def facility_grant_inc(facility):
    facility["granted_permit_count"] += 1
    touch(facility)


def facility_grant_dec(facility):
    facility["granted_permit_count"] -= 1
    touch(facility)


# ---------------------------------------------------------------------------
# Permit cancel (used directly and by league cascade)
# ---------------------------------------------------------------------------
def cancel_permit(permit, refund_destination):
    """Execute APPLIED->CANCELLED or GRANTED->CANCELLED side effects.

    Caller must have validated state and (for direct cancel) the temporal guard.
    """
    facility = db.facilities[permit["facility_id"]]
    was_granted = permit["status"] == "GRANTED"

    if was_granted:
        now = clock_now()
        lead = calc.lead_hours(permit["start_at"], now)
        permit["cancelled_lead_hours"] = float(lead)
        fee_refund, deposit_refund, total = calc.cancellation_refund(
            permit["final_fee_cents"] or 0, permit["deposit_held_cents"], lead
        )
        create_refund(permit, fee_refund, deposit_refund, refund_destination or "ORIGINAL")
        permit["refunded_cents"] = total
        permit["status"] = "CANCELLED"
        touch(permit)
        facility_grant_dec(facility)
    else:
        # APPLIED -> CANCELLED: full reversal of any AUTHORIZED payment; nothing
        # was captured into a fee, refunded_cents stays 0.
        for pay in db.payments.values():
            if pay["permit_id"] == permit["id"] and pay["status"] == "AUTHORIZED":
                pay["status"] = "VOIDED"
                touch(pay)
        permit["status"] = "CANCELLED"
        touch(permit)

    if permit.get("league_id"):
        recompute_league(permit["league_id"])
    return permit
