"""Path-resolution helpers (PRD §2.6: validate path ids strictly left to right).

The first identifier in a path that does not resolve to an existing resource
causes ERR_NOT_FOUND before any deeper identifier is examined.
"""
from db import db
from errors import err


def get_policy(policy_id):
    policy = db.policies.get(policy_id)
    if policy is None:
        raise err("ERR_NOT_FOUND", "policy not found")
    return policy


def get_child(collection, child_id, policy_id, what):
    """Resolve a child resource and confirm it belongs to the given policy."""
    child = collection.get(child_id)
    if child is None or child.get("policy_id") != policy_id:
        raise err("ERR_NOT_FOUND", "%s not found" % what)
    return child


def get_coverage(policy_id, coverage_id):
    return get_child(db.coverages, coverage_id, policy_id, "coverage")


def get_claim(policy_id, claim_id):
    return get_child(db.claims, claim_id, policy_id, "claim")


def get_certificate(policy_id, certificate_id):
    return get_child(db.certificates, certificate_id, policy_id, "certificate")


def get_endorsement(policy_id, endorsement_id):
    return get_child(db.endorsements, endorsement_id, policy_id, "endorsement")


def get_vendor(vendor_id):
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise err("ERR_NOT_FOUND", "vendor not found")
    return vendor


def get_product(product_id):
    product = db.coverage_products.get(product_id)
    if product is None:
        raise err("ERR_NOT_FOUND", "coverage product not found")
    return product


def get_peril(event_id):
    peril = db.force_majeure_events.get(event_id)
    if peril is None:
        raise err("ERR_NOT_FOUND", "force-majeure event not found")
    return peril


def total_attendance(policy_id):
    """Sum of expected_attendance over ALL EventProfiles on the policy."""
    return sum(
        ep["expected_attendance"]
        for ep in db.event_profiles.values()
        if ep["policy_id"] == policy_id
    )


def children_by_policy(collection, policy_id):
    return [c for c in collection.values() if c["policy_id"] == policy_id]
