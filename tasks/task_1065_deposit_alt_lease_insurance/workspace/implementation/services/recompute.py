"""Cascading recompute helpers shared across route handlers (PRD §2.8, §2.9)."""
import lookups
from db import touch
from services import calculations as calc


def recompute_policy_gross(policy):
    claims = lookups.claims_for_policy(policy["id"])
    policy["gross_available_coverage_cents"] = calc.policy_gross_available_coverage(
        policy["coverage_limit_cents"], claims
    )


def recompute_policy_net(policy):
    payouts = lookups.payouts_for_policy(policy["id"])
    policy["net_available_coverage_cents"] = calc.policy_net_available_coverage(
        policy["coverage_limit_cents"], payouts
    )


def recompute_property_total_paid_claims(property_):
    payouts = lookups.payouts_for_property(property_["id"])
    property_["total_paid_claims_cents"] = calc.property_total_paid_claims(payouts)


def touch_policy_after_coverage_change(policy):
    """Coverage-figure recomputation is itself a mutating write on the Policy record."""
    touch(policy)
