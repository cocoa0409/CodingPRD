"""Tag audit services: vendor risk scoring (strict + weighted variants)."""
from db import store

WEIGHT_HIGH = 50
WEIGHT_MEDIUM = 25
SCORE_CAP = 100


def recompute_vendor_risk(vendor_id):
    """risk_score_strict: 100 if any finding is CONFIRMED_VIOLATION else 0.
    risk_score_weighted: min(100, sum of severity weights over findings in
    OPEN or CONFIRMED_VIOLATION). REMEDIATED/CLOSED contribute nothing.
    Scores are computed fields; recomputation does not bump vendor version."""
    if vendor_id is None:
        return
    vendor = store["vendors"].get(vendor_id)
    if vendor is None:
        return
    findings = [
        f
        for f in store["tracker_findings"].values()
        if f.get("vendor_id") == vendor_id
    ]
    vendor["risk_score_strict"] = (
        100 if any(f.get("status") == "CONFIRMED_VIOLATION" for f in findings) else 0
    )
    weighted = 0
    for f in findings:
        if f.get("status") in ("OPEN", "CONFIRMED_VIOLATION"):
            weighted += WEIGHT_HIGH if f.get("severity") == "HIGH" else WEIGHT_MEDIUM
    vendor["risk_score_weighted"] = min(SCORE_CAP, weighted)


def approved_vendors_of_property(property_id):
    vendors = [
        v
        for v in store["vendors"].values()
        if v.get("property_id") == property_id and v.get("status") == "APPROVED"
    ]
    vendors.sort(key=lambda v: v.get("created_at") or "")
    return vendors
