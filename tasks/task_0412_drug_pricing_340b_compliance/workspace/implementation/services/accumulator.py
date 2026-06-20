"""Split-billing accumulator: accrual, replenishment crystallisation, and the
emitted B340B purchase order. PRD §3.6, scaffold §1.3 accumulator_replenishment."""
from db import db, base_record, touch
from services.pricing import effective_ceiling


def find_accumulator(covered_entity_id, drug_product_id):
    for acc in db.accumulators.all():
        if (
            acc["covered_entity_id"] == covered_entity_id
            and acc["drug_product_id"] == drug_product_id
        ):
            return acc
    return None


def _create_b340b_po(acc, packages, unit_price_paid_cents, quarter):
    """Emit a B340B purchase order for a crystallised replenishment."""
    po = base_record(full_meta=True)
    po.update(
        {
            "covered_entity_id": acc["covered_entity_id"],
            "drug_product_id": acc["drug_product_id"],
            "accumulator_id": acc["id"],
            "channel": "B340B",
            "packages_ordered": packages,
            "quarter": quarter,
            "unit_price_paid_cents": unit_price_paid_cents,
        }
    )
    db.purchase_orders.put(po)
    return po


def run_replenishment(acc, triggering_dispense_id, ceiling_unit_price, quarter):
    """Crystallise whole packages from accrued_units. Mutates acc (touch) and
    emits a B340B PurchaseOrder when a package boundary is crossed.

    Inclusive boundary: accrued_units >= package_size triggers. Returns True
    if a sweep crystallised packages.
    """
    drug = db.drug_products.get(acc["drug_product_id"])
    package_size = drug["package_size_units"]

    if acc["accrued_units"] >= package_size:
        packages = acc["accrued_units"] // package_size
        acc["accrued_units"] = acc["accrued_units"] - packages * package_size
        acc["replenished_packages_total"] += packages
        acc["last_replenish_dispense_id"] = triggering_dispense_id
        touch(acc)
        _create_b340b_po(acc, packages, ceiling_unit_price, quarter)
        return True
    return False


def accrue_and_replenish(acc, quantity_units, triggering_dispense_id, ceiling_unit_price, quarter):
    """Add quantity to accrued_units (a mutation) then run the replenishment
    sweep. Used by 340B dispense creation and reinstatement."""
    acc["accrued_units"] += quantity_units
    touch(acc)
    run_replenishment(acc, triggering_dispense_id, ceiling_unit_price, quarter)


def debit(acc, quantity_units):
    """Compensate a reversal: reduce accrued_units (no crystallisation). PRD §3.7."""
    acc["accrued_units"] -= quantity_units
    touch(acc)
