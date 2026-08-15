"""Business services: serializers, lookups, rating pipeline, consumption
accounting, state-machine side effects, and cascades (PRD §2.7-§2.10, §3).

Pinned rules implemented here:
  - chargeable weight: max(gross, volume/0.006) rounded UP to the next 0.5 kg
  - freight: IATA lowest-applicable-rate over qualifying weight breaks
  - charge lines: each line rounded half-up to 2dp FIRST, then summed
  - spot surcharge: candidate-EXCLUDED pre-assignment utilization snapshot,
    inclusive 85.00 threshold, locked at consolidation, never re-evaluated
  - booking consumption set: attached HWBs in CONSOLIDATED/TENDERED/IN_TRANSIT
    on non-VOID master waybills (DELIVERED/detached/cancelled excluded)
  - MAWB totals set: attached HWBs in CONSOLIDATED/TENDERED only
"""
import uuid
from decimal import Decimal

from db import Rec, store
from errors import (
    ApiError,
    ERR_CLAIM_NOT_FOUND,
    ERR_CUSTOMS_ENTRY_NOT_FOUND,
    ERR_FLIGHT_BOOKING_NOT_FOUND,
    ERR_HOUSE_WAYBILL_NOT_FOUND,
    ERR_MASTER_WAYBILL_NOT_FOUND,
    ERR_SCREENING_RECORD_NOT_FOUND,
    ERR_SHIPPER_NOT_FOUND,
)
from money import (
    DEMERIT_LIMIT,
    SDR_PER_KG,
    SDR_TO_USD,
    SPOT_THRESHOLD_PCT,
    chargeable_weight,
    dec,
    num,
    round2,
)
from timeutil import iso

# HWB states counted toward booking consumption (PRD §2.7).
CONSUMPTION_STATES = ("CONSOLIDATED", "TENDERED", "IN_TRANSIT")
# HWB states counted toward master-waybill totals (scaffold §1.1).
MAWB_TOTAL_STATES = ("CONSOLIDATED", "TENDERED")
# HWB states counted toward the spot-surcharge snapshot (scaffold §1.3).
SPOT_SNAPSHOT_STATES = ("CONSOLIDATED", "TENDERED")
# Claim states that block MAWB close / duplicate filing (PRD §3.4, §3.8).
OPEN_CLAIM_STATES = ("FILED", "UNDER_REVIEW", "COUNTERED", "APPROVED")


def new_id():
    return str(uuid.uuid4())


def touch(rec):
    """Mutation bookkeeping: refresh updated_at and bump version (PRD §2.4)."""
    rec.updated_at = store.now()
    rec.version += 1


def fresh_rec(**kw):
    now = store.issue_ts()
    return Rec(id=new_id(), created_at=now, updated_at=now, version=1,
               seq=store.next_seq(), **kw)


# ---------------------------------------------------------------------------
# Lookup helpers (existence, priority 3: path ids left-to-right, then body ids)
# ---------------------------------------------------------------------------

def get_shipper(sid):
    rec = store.shippers.get(sid)
    if rec is None:
        raise ApiError(ERR_SHIPPER_NOT_FOUND, f"Shipper '{sid}' does not exist.", 404)
    return rec


def get_booking(bid):
    rec = store.bookings.get(bid)
    if rec is None:
        raise ApiError(ERR_FLIGHT_BOOKING_NOT_FOUND, f"Flight booking '{bid}' does not exist.", 404)
    return rec


def get_mawb(mid):
    rec = store.mawbs.get(mid)
    if rec is None:
        raise ApiError(ERR_MASTER_WAYBILL_NOT_FOUND, f"Master waybill '{mid}' does not exist.", 404)
    return rec


def get_hwb(hid):
    rec = store.hwbs.get(hid)
    if rec is None:
        raise ApiError(ERR_HOUSE_WAYBILL_NOT_FOUND, f"House waybill '{hid}' does not exist.", 404)
    return rec


def get_screening(rid):
    rec = store.screenings.get(rid)
    if rec is None:
        raise ApiError(ERR_SCREENING_RECORD_NOT_FOUND, f"Screening record '{rid}' does not exist.", 404)
    return rec


def get_customs_entry(cid):
    rec = store.customs_entries.get(cid)
    if rec is None:
        raise ApiError(ERR_CUSTOMS_ENTRY_NOT_FOUND, f"Customs entry '{cid}' does not exist.", 404)
    return rec


def get_claim(cid):
    rec = store.claims.get(cid)
    if rec is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"Claim '{cid}' does not exist.", 404)
    return rec


# ---------------------------------------------------------------------------
# Logical-clock-driven booking cutoff (PRD §2.9)
# ---------------------------------------------------------------------------

def refresh_booking_cutoff(booking):
    """Lazy cutoff auto-close: OPEN -> CUTOFF_CLOSED once clock >= cutoff_utc."""
    if booking.status == "OPEN" and store.now() >= booking.cutoff_utc:
        booking.status = "CUTOFF_CLOSED"
        touch(booking)


def auto_close_bookings():
    """Eager cutoff auto-close, run when the logical clock is set (PRD §2.9)."""
    for b in store.bookings.values():
        refresh_booking_cutoff(b)


# ---------------------------------------------------------------------------
# Consumption / totals accounting (PRD §2.7, §2.10)
# ---------------------------------------------------------------------------

def _attached_hwbs(mawb):
    return [h for h in store.hwbs.values() if h.mawb_id == mawb.id]


def booking_mawbs(booking):
    return [m for m in store.mawbs.values() if m.booking_id == booking.id]


def consumption_sums(booking, states=CONSUMPTION_STATES, exclude_hwb_id=None):
    w = Decimal(0)
    v = Decimal(0)
    for m in booking_mawbs(booking):
        if m.status == "VOID":
            continue
        for h in _attached_hwbs(m):
            if exclude_hwb_id is not None and h.id == exclude_hwb_id:
                continue
            if h.status in states:
                w += dec(h.chargeable_weight_kg)
                v += dec(h.effective_volume_m3)
    return w, v


def utilization_of(booking, w, v):
    return round2(max(w / dec(booking.booked_weight_kg),
                      v / dec(booking.booked_volume_m3)) * Decimal(100))


def recompute_booking(booking):
    """Recompute consumed_*/utilization_pct; a mutation per PRD §2.4."""
    w, v = consumption_sums(booking)
    booking.consumed_weight_kg = w
    booking.consumed_volume_m3 = v
    booking.utilization_pct = utilization_of(booking, w, v)
    touch(booking)


def recompute_mawb_totals(mawb):
    w = Decimal(0)
    v = Decimal(0)
    f = Decimal(0)
    for h in _attached_hwbs(mawb):
        if h.status in MAWB_TOTAL_STATES:
            w += dec(h.chargeable_weight_kg)
            v += dec(h.effective_volume_m3)
            f += dec(h.total_charge_amount)
    mawb.total_chargeable_weight_kg = w
    mawb.total_volume_m3 = v
    mawb.total_freight_amount = f


def maybe_auto_depart(booking):
    """CUTOFF_CLOSED -> DEPARTED bubble-up (PRD §3.2): fires only when at
    least one non-VOID master waybill reached IN_TRANSIT/ARRIVED/DELIVERED/
    CLOSED and none remain in DRAFT/OPEN_FOR_CONSOLIDATION/TENDERED."""
    if booking.status != "CUTOFF_CLOSED":
        return
    mawbs = booking_mawbs(booking)
    advancing = [m for m in mawbs if m.status in ("IN_TRANSIT", "ARRIVED", "DELIVERED", "CLOSED")]
    pending = [m for m in mawbs if m.status in ("DRAFT", "OPEN_FOR_CONSOLIDATION", "TENDERED")]
    if len(advancing) >= 1 and not pending:
        booking.status = "DEPARTED"
        touch(booking)


# ---------------------------------------------------------------------------
# Rating pipeline (PRD §3.5; scaffold §1.3)
# ---------------------------------------------------------------------------

def active_agreement(shipper_id, origin_code, destination_code):
    """The agreement whose half-open [valid_from, valid_to) window contains
    the logical clock, or None. Overlap prevention keeps this unambiguous."""
    now = store.now()
    for a in store.rate_agreements.values():
        if (a.shipper_id == shipper_id and a.origin_code == origin_code
                and a.destination_code == destination_code
                and a.valid_from_utc <= now < a.valid_to_utc):
            return a
    return None


def rate_freight(agreement, cw):
    """IATA lowest-applicable-rate: over tiers with min_weight_kg <= cw, take
    min(max(min_charge, rate*cw)); no qualifying tier -> min_charge floor."""
    applicable = [t for t in agreement.weight_breaks if t["min_weight_kg"] <= cw]
    if not applicable:
        return dec(agreement.min_charge_amount)
    candidates = []
    for t in applicable:
        line = t["rate_per_kg"] * cw
        floor = dec(agreement.min_charge_amount)
        candidates.append(line if line > floor else floor)
    return min(candidates)


def apply_rating(hwb, agreement, volume, spot_applied):
    """(Re-)rate a waybill from the given volume basis. Lines round half-up
    to 2dp FIRST, then sum (pinned order, PRD §2.8)."""
    cw = chargeable_weight(dec(hwb.gross_weight_kg), dec(volume))
    freight = round2(rate_freight(agreement, cw))
    fuel = round2(freight * dec(agreement.fuel_surcharge_pct))
    security = dec(agreement.security_fee_amount)
    spot = round2(freight * dec(agreement.spot_surcharge_pct)) if spot_applied else Decimal(0)
    hwb.chargeable_weight_kg = cw
    hwb.freight_amount = freight
    hwb.fuel_surcharge_amount = fuel
    hwb.security_fee_amount = security
    hwb.spot_surcharge_amount = spot
    hwb.total_charge_amount = freight + fuel + security + spot


def spot_surcharge_applied(booking, candidate_hwb_id):
    """Pre-assignment utilization snapshot EXCLUDING the candidate; the
    85.00 threshold is inclusive (scaffold §1.3 spot_surcharge_determination)."""
    w, v = consumption_sums(booking, states=SPOT_SNAPSHOT_STATES,
                            exclude_hwb_id=candidate_hwb_id)
    return utilization_of(booking, w, v) >= SPOT_THRESHOLD_PCT


def liability_limit(hwb, claimed_amount):
    """PRD §3.7: STANDARD caps at round2(22 SDR * 1.35 * gross kg);
    DECLARED_VALUE caps at the declared value. Both min with claimed."""
    if hwb.declared_value_surcharge_paid:
        return "DECLARED_VALUE", min(claimed_amount, dec(hwb.declared_value_amount))
    cap = round2(SDR_PER_KG * SDR_TO_USD * dec(hwb.gross_weight_kg))
    return "STANDARD", min(claimed_amount, cap)


# ---------------------------------------------------------------------------
# Cascades (PRD §2.10)
# ---------------------------------------------------------------------------

def detach_hwb(hwb):
    """CONSOLIDATED/TENDERED -> CLEARED, detached and zeroed (void cascade and
    manual deconsolidation share these field-level effects)."""
    hwb.mawb_id = None
    hwb.status = "CLEARED"
    hwb.chargeable_weight_kg = Decimal(0)
    hwb.weight_basis = "UNRATED"
    hwb.freight_amount = Decimal(0)
    hwb.fuel_surcharge_amount = Decimal(0)
    hwb.security_fee_amount = Decimal(0)
    hwb.spot_surcharge_amount = Decimal(0)
    hwb.spot_surcharge_applied = False
    hwb.total_charge_amount = Decimal(0)
    hwb.rate_agreement_id = None
    touch(hwb)


def void_mawb(mawb):
    """MAWB -> VOID with the detach cascade; totals zeroed (PRD §2.10 link 2)."""
    mawb.status = "VOID"
    for h in _attached_hwbs(mawb):
        if h.status in ("CONSOLIDATED", "TENDERED"):
            detach_hwb(h)
    mawb.total_chargeable_weight_kg = Decimal(0)
    mawb.total_volume_m3 = Decimal(0)
    mawb.total_freight_amount = Decimal(0)
    touch(mawb)


def cancel_booking_cascade(booking):
    """Three-link cascade (PRD §2.10): MAWB void -> HWB detach -> recompute."""
    booking.status = "CANCELLED"
    for m in booking_mawbs(booking):
        if m.status in ("DRAFT", "OPEN_FOR_CONSOLIDATION", "TENDERED"):
            void_mawb(m)
    recompute_booking(booking)


def bubble_screening(hwb):
    """Screening bubble-up (PRD §3.3): judged on the LATEST record per
    required type (created_at ordering, creation sequence tie-break)."""
    if hwb.status != "SCREENING":
        return
    required = ["SECURITY"] + (["DANGEROUS_GOODS"] if hwb.dg_flag else [])
    records = [r for r in store.screenings.values() if r.hwb_id == hwb.id]

    def latest_of(t):
        rs = [r for r in records if r.screening_type == t]
        if not rs:
            return None
        return max(rs, key=lambda r: (r.created_at, r.seq))

    latest = [latest_of(t) for t in required]
    if any(r is not None and r.result == "REJECTED" for r in latest):
        hwb.status = "SCREENING_REJECTED"
        touch(hwb)
        # Demerit cascade: increment; inclusive >= 3 suspends a KNOWN shipper.
        shipper = store.shippers.get(hwb.shipper_id)
        if shipper is not None:
            shipper.screening_rejection_count += 1
            if (shipper.screening_rejection_count >= DEMERIT_LIMIT
                    and shipper.known_shipper_status == "KNOWN"):
                shipper.known_shipper_status = "SUSPENDED"
            touch(shipper)
    elif all(r is not None and r.result == "CLEARED" for r in latest):
        hwb.status = "CLEARED"
        touch(hwb)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def shipper_json(s):
    return {
        "id": s.id,
        "name": s.name,
        "account_code": s.account_code,
        "known_shipper_status": s.known_shipper_status,
        "screening_rejection_count": s.screening_rejection_count,
        "created_at": iso(s.created_at),
        "updated_at": iso(s.updated_at),
        "version": s.version,
    }


def booking_json(b):
    return {
        "id": b.id,
        "airline_code": b.airline_code,
        "flight_number": b.flight_number,
        "origin_code": b.origin_code,
        "destination_code": b.destination_code,
        "scheduled_departure_utc": iso(b.scheduled_departure_utc),
        "cutoff_utc": iso(b.cutoff_utc),
        "booked_weight_kg": num(b.booked_weight_kg),
        "booked_volume_m3": num(b.booked_volume_m3),
        "consumed_weight_kg": num(b.consumed_weight_kg),
        "consumed_volume_m3": num(b.consumed_volume_m3),
        "utilization_pct": num(b.utilization_pct),
        "status": b.status,
        "created_at": iso(b.created_at),
        "updated_at": iso(b.updated_at),
        "version": b.version,
    }


def mawb_json(m):
    return {
        "id": m.id,
        "booking_id": m.booking_id,
        "mawb_number": m.mawb_number,
        "total_chargeable_weight_kg": num(m.total_chargeable_weight_kg),
        "total_volume_m3": num(m.total_volume_m3),
        "total_freight_amount": num(m.total_freight_amount),
        "tender_window_start_utc": iso(m.tender_window_start_utc),
        "tender_window_end_utc": iso(m.tender_window_end_utc),
        "status": m.status,
        "created_at": iso(m.created_at),
        "updated_at": iso(m.updated_at),
        "version": m.version,
    }


def hwb_json(h):
    return {
        "id": h.id,
        "shipper_id": h.shipper_id,
        "mawb_id": h.mawb_id,
        "hwb_number": h.hwb_number,
        "origin_code": h.origin_code,
        "destination_code": h.destination_code,
        "pieces": h.pieces,
        "gross_weight_kg": num(h.gross_weight_kg),
        "declared_volume_m3": num(h.declared_volume_m3),
        "measured_volume_m3": (None if h.measured_volume_m3 is None else num(h.measured_volume_m3)),
        "effective_volume_m3": num(h.effective_volume_m3),
        "chargeable_weight_kg": num(h.chargeable_weight_kg),
        "weight_basis": h.weight_basis,
        "dg_flag": h.dg_flag,
        "declared_value_amount": num(h.declared_value_amount),
        "declared_value_surcharge_paid": h.declared_value_surcharge_paid,
        "freight_amount": num(h.freight_amount),
        "fuel_surcharge_amount": num(h.fuel_surcharge_amount),
        "security_fee_amount": num(h.security_fee_amount),
        "spot_surcharge_amount": num(h.spot_surcharge_amount),
        "spot_surcharge_applied": h.spot_surcharge_applied,
        "total_charge_amount": num(h.total_charge_amount),
        "rate_agreement_id": h.rate_agreement_id,
        "submitted_by_user_id": h.submitted_by_user_id,
        "delivered_at_utc": iso(h.delivered_at_utc),
        "status": h.status,
        "created_at": iso(h.created_at),
        "updated_at": iso(h.updated_at),
        "version": h.version,
    }


def screening_json(r):
    return {
        "id": r.id,
        "hwb_id": r.hwb_id,
        "screening_type": r.screening_type,
        "result": r.result,
        "rejection_reason": r.rejection_reason,
        "resolved_by_user_id": r.resolved_by_user_id,
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
        "version": r.version,
    }


def customs_entry_json(c):
    return {
        "id": c.id,
        "hwb_id": c.hwb_id,
        "entry_type": c.entry_type,
        "broker_reference": c.broker_reference,
        "rejection_reason": c.rejection_reason,
        "status": c.status,
        "created_at": iso(c.created_at),
        "updated_at": iso(c.updated_at),
        "version": c.version,
    }


def rate_agreement_json(a):
    return {
        "id": a.id,
        "shipper_id": a.shipper_id,
        "origin_code": a.origin_code,
        "destination_code": a.destination_code,
        "weight_breaks": [
            {"min_weight_kg": num(t["min_weight_kg"]), "rate_per_kg": num(t["rate_per_kg"])}
            for t in a.weight_breaks
        ],
        "min_charge_amount": num(a.min_charge_amount),
        "fuel_surcharge_pct": num(a.fuel_surcharge_pct),
        "security_fee_amount": num(a.security_fee_amount),
        "spot_surcharge_pct": num(a.spot_surcharge_pct),
        "valid_from_utc": iso(a.valid_from_utc),
        "valid_to_utc": iso(a.valid_to_utc),
        "created_at": iso(a.created_at),
        "updated_at": iso(a.updated_at),
        "version": a.version,
    }


def milestone_json(e):
    # Append-only audit entry: id + created_at only, no updated_at/version.
    return {
        "id": e.id,
        "mawb_id": e.mawb_id,
        "event_code": e.event_code,
        "event_time_utc": iso(e.event_time_utc),
        "exception_code": e.exception_code,
        "note": e.note,
        "out_of_order": e.out_of_order,
        "created_at": iso(e.created_at),
    }


def claim_json(c):
    return {
        "id": c.id,
        "hwb_id": c.hwb_id,
        "claim_type": c.claim_type,
        "claimed_amount": num(c.claimed_amount),
        "liability_basis": c.liability_basis,
        "liability_limit_amount": num(c.liability_limit_amount),
        "approved_amount": (None if c.approved_amount is None else num(c.approved_amount)),
        "counter_amount": (None if c.counter_amount is None else num(c.counter_amount)),
        "review_round_count": c.review_round_count,
        "status": c.status,
        "created_at": iso(c.created_at),
        "updated_at": iso(c.updated_at),
        "version": c.version,
    }


def paginate(items, limit, offset):
    """Slice a created_at-ascending sorted list per PRD §2.3."""
    total = len(items)
    return items[offset:offset + limit], total


def sorted_by_created(records):
    return sorted(records, key=lambda r: (r.created_at, r.seq))
