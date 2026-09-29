"""Territory exposure posture and the conservation of insured value (PRD 2.7)."""

from db import db, touch
from util import D, rhu4
from services.constants import CLOSED_RATIO, RESTRICTED_RATIO


def policies_in_zone(zone_id):
    rows = []
    for policy in db.policies.values():
        prop = db.properties.get(policy["property_id"])
        if prop is not None and prop["cat_zone_id"] == zone_id:
            rows.append(policy)
    return rows


def aggregate_for_zone(zone_id):
    """Sum of exposure_value_cents over BOUND / IN_FORCE policies only."""
    total = 0
    for policy in policies_in_zone(zone_id):
        if policy["coverage_status"] in ("BOUND", "IN_FORCE"):
            total += policy["exposure_value_cents"]
    return total


def derive_status(ratio):
    if ratio >= CLOSED_RATIO:
        return "CLOSED"
    if ratio >= RESTRICTED_RATIO:
        return "RESTRICTED"
    return "OPEN"


def recompute(zone, bump_version=True):
    """Recompute aggregate, ratio and status; a recomputation is a mutation."""
    total = aggregate_for_zone(zone["id"])
    ratio = rhu4(D(total) / D(zone["exposure_cap_cents"]))
    zone["aggregate_insured_value_cents"] = total
    zone["concentration_ratio"] = ratio
    zone["status"] = derive_status(ratio)
    if bump_version:
        touch(zone)
    return zone


def zone_of_property(prop):
    return db.cat_zones.get(prop["cat_zone_id"]) if prop else None


def zone_of_policy(policy):
    prop = db.properties.get(policy["property_id"])
    return zone_of_property(prop)
