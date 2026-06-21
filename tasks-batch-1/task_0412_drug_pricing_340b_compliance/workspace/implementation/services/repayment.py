"""Repayment assessment calculation. PRD §3.9, scaffold §1.3 repayment_assessment."""
from db import db
from services.pricing import effective_published_ceiling


def assess_finding_repayment(finding):
    """AUDIT_FINDING variant: per-unit benefit = max(0, wac - published ceiling),
    times assessed_units. Returns assessed_cents."""
    dispense = db.dispenses.get(finding["prescription_dispense_id"])
    drug = db.drug_products.get(dispense["drug_product_id"])
    published = effective_published_ceiling(dispense["drug_product_id"], dispense["quarter"])
    ceiling = published["ceiling_price_per_unit_cents"] if published is not None else 0
    per_unit_benefit = max(0, drug["wac_price_per_unit_cents"] - ceiling)
    return per_unit_benefit * finding["assessed_units"]
