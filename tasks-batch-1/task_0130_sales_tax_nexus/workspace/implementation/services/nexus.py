"""Nexus posture recomputation (PRD §2.5, calculations.nexus_status).

The posture is derived from the profile's own accumulators and its
jurisdiction's thresholds. REGISTERED is sticky and never reverts.
"""
import db


def find_profile(seller_id, jurisdiction_id):
    """Return the NexusProfile for (seller, jurisdiction) or None."""
    for p in db.nexus_profiles.values():
        if p["seller_id"] == seller_id and p["jurisdiction_id"] == jurisdiction_id:
            return p
    return None


def recompute_status(profile):
    """Recompute and set nexus_status in place per §2.5. Returns the status."""
    j = db.tax_jurisdictions.get(profile["jurisdiction_id"])
    if j is None:
        return profile["nexus_status"]

    sales_threshold = j["economic_nexus_sales_threshold"]
    count_threshold = j["economic_nexus_txn_threshold"]

    # Sales test: inclusive >=. Held at 2 dp, compared exactly.
    sales_met = profile["cumulative_taxable_sales"] >= sales_threshold
    # Count test: only when the threshold is > 0 (0 disables the test).
    count_met = count_threshold > 0 and profile["cumulative_txn_count"] >= count_threshold
    threshold_crossed = sales_met or count_met

    if profile["nexus_status"] == "REGISTERED":
        profile["nexus_status"] = "REGISTERED"  # sticky
    elif threshold_crossed:
        profile["nexus_status"] = "THRESHOLD_MET"
    else:
        profile["nexus_status"] = "NO_NEXUS"
    return profile["nexus_status"]
