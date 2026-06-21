"""Calculation rules (PRD §3.4, §3.7, §3.8, §3.10; SCAFFOLD §1.3).

All money is in integer cents. Divisions use floor / ceil on integers; no
float is ever used for money.
"""
import math

from db import db

# chaperone_ratio_requirement constants (SCAFFOLD §1.3)
RATIO_BY_BAND = {"ELEMENTARY": 8, "MIDDLE": 12, "HIGH": 15}
WATER_EXTRA = 1

# chaperone_window_overlap travel buffer (seconds)
TRAVEL_BUFFER = 3600


# --- aggregation helpers over append-only ledgers -------------------------

def slip_net_paid(slip_id):
    """Sum of amount_cents over this slip's FeeTransactions (PRD §2.8)."""
    return sum(
        f["amount_cents"]
        for f in db.fee_transactions.values()
        if f["slip_id"] == slip_id
    )


def trip_collected_fees(trip_id):
    """Sum of amount_cents over this trip's FeeTransactions (PRD §2.8)."""
    return sum(
        f["amount_cents"]
        for f in db.fee_transactions.values()
        if f["trip_id"] == trip_id
    )


def vehicle_seats_reserved(vehicle_id):
    """Sum of seat_count over this vehicle's CONFIRMED bookings (PRD §2.9)."""
    return sum(
        b["seat_count"]
        for b in db.transport_bookings.values()
        if b["vehicle_id"] == vehicle_id and b["status"] == "CONFIRMED"
    )


def pool_granted_cents(pool_id):
    """Sum of award_cents over this pool's ACTIVE grants (PRD §2.9)."""
    return sum(
        g["award_cents"]
        for g in db.scholarship_grants.values()
        if g["pool_id"] == pool_id and g["status"] == "ACTIVE"
    )


def slip_scholarship_award(slip_id):
    """Sum of award_cents over this slip's ACTIVE grants (PRD §3.7)."""
    return sum(
        g["award_cents"]
        for g in db.scholarship_grants.values()
        if g["slip_id"] == slip_id and g["status"] == "ACTIVE"
    )


# --- chaperone ratio requirement (PRD §3.4) --------------------------------

def signed_slips_of_trip(trip_id):
    return [
        s for s in db.permission_slips.values()
        if s["trip_id"] == trip_id and s["signature_status"] == "SIGNED"
    ]


def required_chaperones(trip):
    """S/base ratio (ceil) + N dedicated 1:1 + water surcharge (PRD §3.4)."""
    signed = signed_slips_of_trip(trip["id"])
    s = len(signed)
    base_ratio = RATIO_BY_BAND[trip["grade_band"]]
    general = math.ceil(s / base_ratio) if s > 0 else 0
    n = 0
    for slip in signed:
        student = db.students.get(slip["student_id"])
        if student and student.get("special_needs"):
            n += 1
    surcharge = WATER_EXTRA if trip["has_water_activity"] else 0
    return general + n + surcharge


# --- slip fee due (PRD §3.7) -----------------------------------------------

def provisional_transport_share(trip):
    """ceil(transport_cost_cents / max(signed_count, 1)) (PRD §3.7)."""
    denom = max(trip["signed_count"], 1)
    return math.ceil(trip["transport_cost_cents"] / denom)


def compute_fee_due(trip, slip, transport_share):
    """gross - effective_scholarship (PRD §3.7).

    gross = base_fee_cents + transport_share
    waivable = gross - deposit_cents (never < 0)
    effective_scholarship = min(scholarship, waivable)
    fee_due = gross - effective_scholarship
    """
    gross = trip["base_fee_cents"] + transport_share
    scholarship = slip_scholarship_award(slip["id"])
    waivable = max(gross - trip["deposit_cents"], 0)
    effective_scholarship = min(scholarship, waivable)
    return gross - effective_scholarship


def recompute_provisional_fee(trip, slip):
    share = provisional_transport_share(trip)
    slip["fee_due_cents"] = compute_fee_due(trip, slip, share)


# --- per-student cost allocation at lock (PRD §3.8) ------------------------

def allocate_final_transport(trip, confirmed_slips):
    """Waterfall allocation: floor-then-sweep remainder (PRD §3.8).

    Returns dict slip_id -> transport_share, and the representative base_share.
    Confirmed slips are ordered by (signed_at ASC, created_at ASC).
    """
    c = len(confirmed_slips)
    transport_cost = trip["transport_cost_cents"]
    base_share = transport_cost // c
    remainder = transport_cost - base_share * c

    ordered = sorted(
        confirmed_slips,
        key=lambda s: (s["signed_at"], s["created_at"], s["_seq"]),
    )
    shares = {}
    for i, slip in enumerate(ordered):
        if i < remainder:
            shares[slip["id"]] = base_share + 1
        else:
            shares[slip["id"]] = base_share
    return shares, base_share


# --- voluntary withdrawal refund (PRD §3.10) -------------------------------

def voluntary_withdrawal_refund(trip, slip, transport_share):
    """refund = max(net_paid - deposit - committed transport_share, 0)."""
    paid = slip_net_paid(slip["id"])
    forfeit = trip["deposit_cents"] + transport_share
    return max(paid - forfeit, 0)
