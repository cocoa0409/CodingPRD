"""Output serialization with computed-field derivation.

Each builder returns the public JSON view of a stored record, recomputing
`source: computed` fields from current state (PRD §2.4, §3.x).
"""
import db
from services import ledger


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
def active_unit_count(catalog_id):
    # Count of this catalog's GarmentUnit children whose status != RETIRED.
    return sum(
        1
        for u in db.garment_units.values()
        if u["catalog_id"] == catalog_id and u["status"] != "RETIRED"
    )


def catalog_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "style_name": c["style_name"],
        "category": c["category"],
        "daily_rate_cents": c["daily_rate_cents"],
        "deposit_cents": c["deposit_cents"],
        "replacement_value_cents": c["replacement_value_cents"],
        "waiver_daily_rate_cents": c["waiver_daily_rate_cents"],
        "cleaning_buffer_days": c["cleaning_buffer_days"],
        "late_fee_daily_rate_cents": c["late_fee_daily_rate_cents"],
        "active_unit_count": active_unit_count(c["id"]),
    }


# ---------------------------------------------------------------------------
# GarmentUnit
# ---------------------------------------------------------------------------
def garment_unit_view(u):
    return {
        "id": u["id"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
        "catalog_id": u["catalog_id"],
        "size_code": u["size_code"],
        "condition_grade": u["condition_grade"],
        "status": u["status"],
        "damage_strike_count": u["damage_strike_count"],
        "available_from_iso": u["available_from_iso"],
    }


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
def open_strike_count(customer_id):
    # Count of this customer's settlements with disposition DAMAGED.
    count = 0
    for s in db.settlements.values():
        res = db.reservations.get(s["reservation_id"])
        if res is None:
            continue
        if res["customer_id"] == customer_id and s["disposition"] == "DAMAGED":
            count += 1
    return count


def customer_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "full_name": c["full_name"],
        "email": c["email"],
        "deposit_held_cents": ledger.deposit_held_for_customer(c["id"]),
        "balance_owed_cents": ledger.balance_owed_for_customer(c["id"]),
        "open_strike_count": open_strike_count(c["id"]),
    }


# ---------------------------------------------------------------------------
# MeasurementProfile
# ---------------------------------------------------------------------------
def measurement_profile_view(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "customer_id": m["customer_id"],
        "chest_cm": m["chest_cm"],
        "waist_cm": m["waist_cm"],
        "inseam_cm": m["inseam_cm"],
        "recommended_size_code": m["recommended_size_code"],
    }


# ---------------------------------------------------------------------------
# Reservation
# ---------------------------------------------------------------------------
def reservation_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "customer_id": r["customer_id"],
        "catalog_id": r["catalog_id"],
        "garment_unit_id": r["garment_unit_id"],
        "party_order_id": r["party_order_id"],
        "requested_size_code": r["requested_size_code"],
        "event_date_iso": r["event_date_iso"],
        "pickup_window_start_iso": r["pickup_window_start_iso"],
        "return_window_end_iso": r["return_window_end_iso"],
        "damage_waiver_opted": r["damage_waiver_opted"],
        "status": r["status"],
        "rental_days": r["rental_days"],
        "quoted_charge_cents": r["quoted_charge_cents"],
    }


# ---------------------------------------------------------------------------
# Alteration
# ---------------------------------------------------------------------------
def alteration_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "reservation_id": a["reservation_id"],
        "kind": a["kind"],
        "fee_cents": a["fee_cents"],
        "status": a["status"],
    }


# ---------------------------------------------------------------------------
# PartyOrder
# ---------------------------------------------------------------------------
CONFIRMED_MEMBER_STATES = {"CONFIRMED", "PICKED_UP", "RETURNED", "OVERDUE", "SETTLED"}


def confirmed_member_count(party_order_id):
    return sum(
        1
        for r in db.reservations.values()
        if r["party_order_id"] == party_order_id
        and r["status"] in CONFIRMED_MEMBER_STATES
    )


def derive_posture(party):
    """Posture is derived; explicit LOCKED/DISSOLVED are sticky, else threshold."""
    explicit = party.get("posture_explicit")
    if explicit in ("LOCKED", "DISSOLVED"):
        return explicit
    count = confirmed_member_count(party["id"])
    if count >= party["required_member_count"]:
        return "READY"
    return "FORMING"


def party_order_view(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "coordinator_customer_id": p["coordinator_customer_id"],
        "event_date_iso": p["event_date_iso"],
        "required_member_count": p["required_member_count"],
        "confirmed_member_count": confirmed_member_count(p["id"]),
        "posture": derive_posture(p),
    }


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
def settlement_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "reservation_id": s["reservation_id"],
        "returned_at_iso": s["returned_at_iso"],
        "disposition": s["disposition"],
        "late_days": s["late_days"],
        "late_fee_cents": s["late_fee_cents"],
        "damage_fee_cents": s["damage_fee_cents"],
        "waiver_credit_cents": s["waiver_credit_cents"],
        "net_charge_cents": s["net_charge_cents"],
        "deposit_refund_cents": s["deposit_refund_cents"],
    }


# ---------------------------------------------------------------------------
# LedgerEntry
# ---------------------------------------------------------------------------
def ledger_entry_view(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "customer_id": e["customer_id"],
        "reservation_id": e["reservation_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
    }


# ---------------------------------------------------------------------------
# FitCheck
# ---------------------------------------------------------------------------
def fit_check_view(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "reservation_id": f["reservation_id"],
        "measurement_profile_id": f["measurement_profile_id"],
        "verdict": f["verdict"],
    }
