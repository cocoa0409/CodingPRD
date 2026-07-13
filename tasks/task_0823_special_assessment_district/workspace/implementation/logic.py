"""State-machine side effects, cascades, lazy promotions."""
import store
from store import (
    DB, now, make, touch, ser,
    parcels_of_district, installments_of_parcel, installments_of_bond,
    liens_of_parcel, bonds_of_district,
)
import calc
from util import add_days


# ---------------------------------------------------------------------------
# Lazy promotions (no version bump — automatic clock-driven derivation)
# ---------------------------------------------------------------------------
def promote_all():
    clock = now()
    for inst in DB["installments"].values():
        if inst["status"] == "SCHEDULED" and inst.get("due_date") and clock >= inst["due_date"]:
            inst["status"] = "DUE"
    for q in DB["quotes"].values():
        if q["status"] == "QUOTED" and clock > q["valid_until"]:
            q["status"] = "EXPIRED"


# ---------------------------------------------------------------------------
# Lien helpers
# ---------------------------------------------------------------------------
def record_lien(parcel, lien_type, amount_cents):
    return make("liens", {
        "parcel_id": parcel["id"],
        "lien_type": lien_type,
        "amount_cents": amount_cents,
        "recorded_date": now(),
        "status": "RECORDED",
    })


def unreleased_assessment_lien(parcel_id):
    for l in liens_of_parcel(parcel_id):
        if l["lien_type"] == "ASSESSMENT" and l["status"] == "RECORDED":
            return l
    return None


# ---------------------------------------------------------------------------
# Amortization installment generation
# ---------------------------------------------------------------------------
def generate_installments(parcel, bond, p0):
    schedule = calc.amortize(
        p0, bond["coupon_rate_bps"], bond["term_years"],
        bond["admin_fee_bps"], bond["issuance_date"],
    )
    created = []
    for row in schedule:
        inst = make("installments", {
            "parcel_id": parcel["id"],
            "bond_id": bond["id"],
            "installment_year": row["installment_year"],
            "due_date": row["due_date"],
            "principal_cents": row["principal_cents"],
            "interest_cents": row["interest_cents"],
            "admin_fee_cents": row["admin_fee_cents"],
            "penalty_cents": 0,
            "redemption_interest_cents": 0,
            "amount_due_cents": row["amount_due_cents"],
            "status": "SCHEDULED",
        })
        created.append(inst)
    return created


def cancel_scheduled_installments(parcel, bond_id=None):
    for inst in installments_of_parcel(parcel["id"]):
        if bond_id is not None and inst["bond_id"] != bond_id:
            continue
        if inst["status"] == "SCHEDULED":
            inst["status"] = "CANCELLED"
            touch(inst)


# ---------------------------------------------------------------------------
# Parcel payoff cascade
# ---------------------------------------------------------------------------
def parcel_paid_off(parcel):
    if parcel["status"] != "ACTIVE":
        return
    parcel["status"] = "PAID_OFF"
    touch(parcel)
    for lien in liens_of_parcel(parcel["id"]):
        if lien["status"] == "RECORDED":
            lien["status"] = "RELEASED"
            touch(lien)
    for inst in installments_of_parcel(parcel["id"]):
        if inst["status"] in ("SCHEDULED", "DUE"):
            inst["status"] = "CANCELLED"
            touch(inst)


def debit_parcel_principal(parcel, amount):
    parcel["remaining_principal_cents"] -= amount
    if parcel["remaining_principal_cents"] < 0:
        parcel["remaining_principal_cents"] = 0
    touch(parcel)
    if parcel["remaining_principal_cents"] == 0:
        parcel_paid_off(parcel)


# ---------------------------------------------------------------------------
# Bond reconciliation
# ---------------------------------------------------------------------------
def maybe_call_bonds(district_id):
    for b in bonds_of_district(district_id):
        if b["status"] != "ISSUED":
            continue
        relevant = [p for p in parcels_of_district(district_id)
                    if p["status"] in ("ACTIVE", "PAID_OFF", "IN_FORECLOSURE")]
        if relevant and all(p["remaining_principal_cents"] == 0 for p in relevant):
            b["status"] = "CALLED"
            touch(b)


def maybe_retire_bond(bond):
    if bond["status"] != "ISSUED":
        return
    insts = installments_of_bond(bond["id"])
    if any(i["status"] in ("SCHEDULED", "DUE", "DELINQUENT") for i in insts):
        return
    if any(i["status"] == "PAID" for i in insts):
        bond["status"] = "RETIRED"
        touch(bond)
