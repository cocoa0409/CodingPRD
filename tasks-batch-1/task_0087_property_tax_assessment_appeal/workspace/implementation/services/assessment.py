"""Assessment recompute helpers shared by assessment + exemption flows."""
import db
from services.calc import (
    capped_base_value, exemption_total_and_taxable,
)


def recompute_value(assessment):
    """Recompute capped_base_value + assessed_value from the parcel/roll inputs.

    Used on create and on notice (PRD §3.3). Does NOT mutate version/timestamp;
    callers decide when to bump.
    """
    parcel = db.parcels[assessment["parcel_id"]]
    roll = db.tax_rolls[assessment["tax_roll_id"]]
    base = capped_base_value(
        assessment["market_value"],
        parcel["last_certified_capped_base"],
        roll["growth_cap_pct"],
        assessment["reassessment_event"],
    )
    assessment["capped_base_value"] = base
    assessment["assessed_value"] = base


def recompute_exemptions(assessment):
    """Recompute exemption_total + taxable_value from APPROVED exemptions.

    PRD §3.5: every approved deduction was computed against the same
    assessed_value; sum then clamp the SUM to assessed_value.
    """
    approved = [
        e["claimed_amount"]
        for e in db.exemptions.values()
        if e["assessment_id"] == assessment["id"] and e["status"] == "APPROVED"
    ]
    exemption_total, taxable_value = exemption_total_and_taxable(
        assessment["assessed_value"], approved
    )
    assessment["exemption_total"] = exemption_total
    assessment["taxable_value"] = taxable_value
    return taxable_value
