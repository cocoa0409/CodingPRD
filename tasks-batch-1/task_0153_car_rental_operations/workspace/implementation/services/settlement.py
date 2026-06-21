"""Agreement settlement: ledger emission and final_total_cents (PRD §3.5, §3.7).

Provisional pass (at PICKED_UP): emit the date-driven lines only
  BASE_RENTAL, ADDONS, YOUNG_DRIVER, ONE_WAY_DROP, LOYALTY_DISCOUNT.
Final pass (at CLOSE / WRITE_OFF): keep the provisional rows and ADD the
  usage-driven rows MILEAGE_OVERAGE, FUEL, DAMAGE, then re-sum.
"""
import db
import util
from services import calc


def _emit(agreement_id, kind, amount_cents, memo):
    entry = util.stamp_audit(
        {
            "agreement_id": agreement_id,
            "kind": kind,
            "amount_cents": amount_cents,
            "memo": memo,
        }
    )
    db.ledger_entries[entry["id"]] = entry
    return entry


def ledger_for(agreement_id):
    return [e for e in db.ledger_entries.values() if e["agreement_id"] == agreement_id]


def recompute_final_total(agreement):
    total = sum(e["amount_cents"] for e in ledger_for(agreement["id"]))
    agreement["final_total_cents"] = total
    return total


def emit_provisional(agreement, reservation):
    """Date-driven ledger lines at pickup; amounts equal the quote components."""
    c = calc.quote_components(reservation)
    aid = agreement["id"]
    _emit(aid, "BASE_RENTAL", c["base"], "Base rental")
    _emit(aid, "ADDONS", c["addons"], "Add-ons (LDW/PAI)")
    _emit(aid, "YOUNG_DRIVER", c["young"], "Young-driver surcharge")
    _emit(aid, "ONE_WAY_DROP", c["drop"], "One-way drop fee")
    # Loyalty discount is a credit -> negative amount.
    _emit(aid, "LOYALTY_DISCOUNT", -c["discount"], "Loyalty discount")
    recompute_final_total(agreement)


def emit_final_usage(agreement, reservation, vehicle):
    """Usage-driven lines added on close/write-off, then re-sum."""
    vclass = db.vehicle_classes[reservation["class_id"]]
    aid = agreement["id"]

    miles_driven = agreement["odometer_in"] - agreement["odometer_out"]
    included_total = vclass["included_miles_per_day"] * reservation["rental_days"]
    overage_miles = max(0, miles_driven - included_total)
    mileage_overage = overage_miles * vclass["overage_per_mile_cents"]
    _emit(aid, "MILEAGE_OVERAGE", mileage_overage, "Mileage overage")

    missing_eighths = max(0, agreement["fuel_out_eighths"] - agreement["fuel_in_eighths"])
    fuel_charge = missing_eighths * calc.FUEL_PER_EIGHTH_CENTS
    _emit(aid, "FUEL", fuel_charge, "Fuel charge")

    # Damage = sum of member_liability_cents over FILED/RESOLVED incidents.
    damage = 0
    for inc in db.incidents.values():
        if inc["agreement_id"] == aid and inc["status"] in ("FILED", "RESOLVED"):
            damage += inc["member_liability_cents"]
    _emit(aid, "DAMAGE", damage, "Damage charge")

    recompute_final_total(agreement)
