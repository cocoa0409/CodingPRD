"""Pricing calculations: quote_provisional, quote_final, compute_recall_fee.

All money is integer cents; round-half-up is applied exactly once at the
final step of each chain (no intermediate rounding).
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import db

SCALE_BASIS_POINTS = 10000

_RECALL_RATE_CENTS = {
    'HOT': 500,       # $5/GB
    'WARM': 1000,     # $10/GB
    'COLD': 2000,     # $20/GB
    'GLACIER': 4000,  # $40/GB
}
MIN_RECALL_FEE_CENTS = 1000  # $10 floor
_GIB = 1024 * 1024 * 1024

_DEFAULT_RULE = {
    'multiplier_bp': 10000,
    'sla_hours': 24,
    'surcharge_breach_cents': 0,
    'included_revision_rounds': 0,
    'per_round_cents': 0,
}


def rule_for_tier(tier):
    for r in db.rush_tier_rules.values():
        if r['tier'] == tier:
            return r
    return None


def _rule_or_default(tier):
    return rule_for_tier(tier) or _DEFAULT_RULE


def _base_cents(project, engineer_rate_cents):
    hours = Decimal(project['scheduled_duration_minutes']) / Decimal(60)
    return hours * Decimal(engineer_rate_cents)


def _rush_multiplier(rule):
    return Decimal(rule['multiplier_bp']) / Decimal(SCALE_BASIS_POINTS)


def quote_provisional(project, engineer):
    """Booking-time quote: session base * rush multiplier; no revision billing."""
    rule = _rule_or_default(project['rush_tier'])
    base = _base_cents(project, engineer['hourly_rate_cents'])
    provisional = base * _rush_multiplier(rule)
    return int(provisional.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def quote_final(project):
    """Approval-time quote: current engineer rate, extra rounds, breach surcharges."""
    rule = _rule_or_default(project['rush_tier'])
    engineer = db.engineers.get(project.get('assigned_engineer_id') or '')
    rate = engineer['hourly_rate_cents'] if engineer else 0
    base = _base_cents(project, rate)
    rush_applied = base * _rush_multiplier(rule)
    extra_rounds = max(0, project['revision_round_count'] - rule['included_revision_rounds'])
    extra_rounds_cents = extra_rounds * rule['per_round_cents']
    breach_count = sum(
        1 for r in db.revision_rounds.values()
        if r['project_id'] == project['id'] and r['status'] == 'EXPIRED'
    )
    breach_cents = breach_count * rule['surcharge_breach_cents']
    final = rush_applied + Decimal(extra_rounds_cents) + Decimal(breach_cents)
    return int(final.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def compute_recall_fee(bundle):
    size_gb = math.ceil(bundle['archive_size_bytes'] / _GIB) if bundle['archive_size_bytes'] > 0 else 0
    fee = size_gb * _RECALL_RATE_CENTS[bundle['storage_class']]
    return max(fee, MIN_RECALL_FEE_CENTS)
