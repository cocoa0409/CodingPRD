"""Entity-shape assertions, arithmetic oracles and reconciliation checkers.

The oracle helpers re-implement the PRD's pinned formulas so tests can assert
against an independently computed figure instead of restating a magic number.
"""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import (
    CHANNEL_WEIGHTS,
    CHARGEBACK_TIER_RATES,
    CHARGEBACK_TOP_TIER_RATE,
    REPEAT_WEIGHT_BASE,
    REPEAT_WEIGHT_CAP,
    REPEAT_WEIGHT_MAX_PRIORS_COUNTED,
    REPEAT_WEIGHT_STEP,
    RUNG_BY_RANK,
    RUNG_RANKS,
    SCORE_DELTA_PER_UNIT,
    SEVERITY_TIERS,
    SEVERITY_TIER_TOP_POINTS,
    STANDING_PROBATION_THRESHOLD,
    STANDING_SUSPENDED_THRESHOLD,
)


# --------------------------------------------------------------------------- #
# Rounding primitives (PRD 2.5)
# --------------------------------------------------------------------------- #
def round_half_up(value, places=0):
    """Round half up: a value exactly halfway rounds away from zero."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


def floor_to_int(value):
    """Truncate downward to a whole number."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_FLOOR))


# --------------------------------------------------------------------------- #
# Common properties (PRD 2.4)
# --------------------------------------------------------------------------- #
def assert_common_fields(entity, expected_version=None):
    """Every row carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_freshly_created(entity):
    """A newly created row has version 1 and updated_at equal to created_at."""
    assert_common_fields(entity, expected_version=1)
    assert entity["updated_at"] == entity["created_at"]


def parse_instant(value):
    """Parse an ISO 8601 UTC instant, tolerating any fractional-digit count."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def same_instant(actual, expected):
    """True when two ISO 8601 UTC strings denote the same moment."""
    return parse_instant(actual) == parse_instant(expected)


def assert_same_instant(actual, expected, label="timestamp"):
    """Compare two instants by moment rather than by string spelling."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert same_instant(actual, expected), f"{label} is {actual}, expected {expected}"


def assert_envelope_meta(response, expected_response_type):
    body = response.json()
    assert body["response_type"] == expected_response_type
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    return body


# --------------------------------------------------------------------------- #
# Entity-shape assertions
# --------------------------------------------------------------------------- #
def assert_pricing_policy_shape(policy):
    for field in (
        "policy_code",
        "revision_number",
        "status",
        "effective_from",
        "shipping_counts_as_advertised",
        "auto_coupon_counts_as_advertised",
        "promo_code_counts_as_advertised",
        "max_discount_attribution_pct",
        "non_negotiation_ack_required",
        "cure_window_days",
        "suspension_points_threshold",
        "termination_points_threshold",
        "suspension_cooling_off_days",
        "legal_review_notes",
        "reviewed_by_user_id",
        "published_by_user_id",
        "superseded_by_policy_id",
        "withdrawn_reason",
    ):
        assert field in policy, f"policy is missing {field}"
    assert_common_fields(policy)


def assert_product_shape(product):
    for field in (
        "sku",
        "name",
        "msrp_cents",
        "standard_map_floor_cents",
        "lifecycle_status",
        "clearance_discount_pct",
        "serialization_enabled",
        "governing_policy_id",
        "open_exception_count",
    ):
        assert field in product, f"product is missing {field}"
    assert_common_fields(product)


def assert_reseller_shape(reseller):
    for field in (
        "legal_name",
        "contact_email",
        "primary_channel",
        "authorization_status",
        "supply_status",
        "hold_reason",
        "violation_points_total",
        "review_required",
        "sourcing_distributor_id",
        "suspension_ends_at",
        "last_suspension_ended_at",
        "terminated_at",
    ):
        assert field in reseller, f"reseller is missing {field}"
    assert_common_fields(reseller)


def assert_distributor_shape(distributor):
    for field in (
        "legal_name",
        "annual_chargeback_cap_cents",
        "standing",
        "diversion_score",
        "chargeback_balance_cents",
        "shipped_units_total",
        "probation_entered_at",
    ):
        assert field in distributor, f"distributor is missing {field}"
    assert_common_fields(distributor)


def assert_agreement_shape(agreement):
    for field in (
        "reseller_id",
        "policy_id",
        "status",
        "permitted_channels",
        "quality_obligations",
        "term_ends_at",
        "price_terms_included",
        "non_negotiation_acknowledged",
        "sent_at",
        "countersigned_at",
        "countersigned_by_user_id",
        "activated_at",
        "closed_reason",
    ):
        assert field in agreement, f"agreement is missing {field}"
    assert_common_fields(agreement)


def assert_observation_shape(observation):
    for field in (
        "product_id",
        "channel",
        "marketplace_name",
        "seller_display_name",
        "listing_url",
        "listed_price_cents",
        "shipping_cents",
        "auto_coupon_cents",
        "promo_code_cents",
        "is_bundle",
        "bundle_total_price_cents",
        "bundle_components",
        "matched_reseller_id",
        "observed_at",
        "evidence_hash",
        "evidence_captured_by_user_id",
        "allocated_component_price_cents",
        "effective_advertised_price_cents",
        "effective_map_floor_cents",
        "deviation_cents",
        "deviation_pct",
        "evaluation_status",
        "unauthorized_seller_confirmed",
    ):
        assert field in observation, f"observation is missing {field}"
    assert_common_fields(observation)


def assert_violation_shape(violation):
    for field in (
        "observation_id",
        "reseller_id",
        "cited_policy_id",
        "status",
        "provisional_floor_cents",
        "provisional_points",
        "assessed_floor_cents",
        "assessed_points",
        "cure_deadline_at",
        "dispute_rounds",
        "resolution_reason",
    ):
        assert field in violation, f"violation is missing {field}"
    assert_common_fields(violation)


def assert_notice_shape(notice):
    for field in (
        "violation_id",
        "reseller_id",
        "rung",
        "status",
        "issued_by_user_id",
        "cumulative_points_at_issue",
        "assessed_points",
        "suspension_starts_at",
        "suspension_ends_at",
        "delivery_channel",
        "acknowledged_at",
        "closed_reason",
    ):
        assert field in notice, f"notice is missing {field}"
    assert_common_fields(notice)


def assert_exception_shape(exception):
    for field in (
        "product_id",
        "exception_type",
        "channel_scope",
        "starts_at",
        "ends_at",
        "override_floor_cents",
        "status",
        "retroactive",
        "requested_by_user_id",
        "approved_by_user_id",
        "decision_reason",
        "voided_violation_count",
    ):
        assert field in exception, f"exception is missing {field}"
    assert_common_fields(exception)


def assert_serial_unit_shape(unit):
    for field in (
        "serial_number",
        "product_id",
        "lot_code",
        "shipped_distributor_id",
        "downstream_reseller_id",
        "status",
        "shipped_downstream_at",
        "traced_at",
    ):
        assert field in unit, f"serial unit is missing {field}"
    assert_common_fields(unit)


def assert_test_purchase_shape(purchase):
    for field in (
        "observation_id",
        "ordered_at",
        "purchase_price_cents",
        "purchaser_user_id",
        "status",
        "captured_serial_number",
        "traced_serial_unit_id",
        "outcome_reason",
    ):
        assert field in purchase, f"test purchase is missing {field}"
    assert_common_fields(purchase)


def assert_chargeback_shape(chargeback):
    for field in (
        "distributor_id",
        "test_purchase_id",
        "diverted_units",
        "tier_rate_cents_per_unit",
        "amount_cents",
        "score_delta_applied",
        "status",
        "dispute_rounds",
        "decision_reason",
    ):
        assert field in chargeback, f"chargeback is missing {field}"
    assert_common_fields(chargeback)


# --------------------------------------------------------------------------- #
# Advertised-price arithmetic oracles (PRD 3.5)
# --------------------------------------------------------------------------- #
def allocate_bundle(bundle_total_price_cents, components):
    """Allocate a bundle price across components, residual to the last.

    Components are ordered by msrp_cents descending, ties broken by sku
    ascending; every share but the last is rounded half up, and the last takes
    the residual.  Returns a dict keyed by sku.
    """
    total_msrp = sum(c["msrp_cents"] for c in components)
    ordered = sorted(components, key=lambda c: (-c["msrp_cents"], c["sku"]))
    shares = {}
    running = 0
    for component in ordered[:-1]:
        share = round_half_up(
            Decimal(bundle_total_price_cents) * Decimal(component["msrp_cents"]) / Decimal(total_msrp)
        )
        shares[component["sku"]] = share
        running += share
    shares[ordered[-1]["sku"]] = bundle_total_price_cents - running
    return shares


def effective_advertised_price(
    base_cents,
    shipping_cents=0,
    auto_coupon_cents=0,
    promo_code_cents=0,
    shipping_counts=False,
    auto_coupon_counts=True,
    promo_code_counts=False,
    max_discount_attribution_pct=0.40,
):
    """Gross price minus the smaller of the largest qualifying discount and the cap."""
    gross = base_cents + (shipping_cents if shipping_counts else 0)
    candidates = []
    if auto_coupon_counts:
        candidates.append(auto_coupon_cents)
    if promo_code_counts:
        candidates.append(promo_code_cents)
    candidate = max(candidates) if candidates else 0
    cap = floor_to_int(Decimal(gross) * Decimal(str(max_discount_attribution_pct)))
    return gross - min(candidate, cap)


def deviation_cents(floor_cents, price_cents):
    """Floor minus effective advertised price, floored at 0."""
    return max(0, floor_cents - price_cents)


def deviation_pct(floor_cents, deviation):
    """Deviation over the floor, rounded half up to four decimal places."""
    if deviation == 0:
        return 0
    return round_half_up(Decimal(deviation) / Decimal(floor_cents), 4)


def base_points_for_fraction(fraction):
    """Read base points off the four inclusive severity tiers."""
    for upper, points in SEVERITY_TIERS:
        if Decimal(str(fraction)) <= Decimal(str(upper)):
            return points
    return SEVERITY_TIER_TOP_POINTS


def repeat_weight(prior_noticed_count):
    """1.00 plus a quarter per prior noticed violation, at most four counted."""
    counted = min(prior_noticed_count, REPEAT_WEIGHT_MAX_PRIORS_COUNTED)
    weight = REPEAT_WEIGHT_BASE + REPEAT_WEIGHT_STEP * counted
    return min(weight, REPEAT_WEIGHT_CAP)


def violation_points(floor_cents, price_cents, channel, prior_noticed_count=0):
    """The full points chain, rounded half up once at the very end."""
    deviation = deviation_cents(floor_cents, price_cents)
    if deviation == 0:
        return 0
    fraction = deviation_pct(floor_cents, deviation)
    base = base_points_for_fraction(fraction)
    product = (
        Decimal(base)
        * Decimal(str(CHANNEL_WEIGHTS[channel]))
        * Decimal(str(repeat_weight(prior_noticed_count)))
    )
    return round_half_up(product)


# --------------------------------------------------------------------------- #
# Ladder oracles (PRD 3.7)
# --------------------------------------------------------------------------- #
def points_justified_rung(cumulative_points, suspension_threshold, termination_threshold):
    if cumulative_points >= termination_threshold:
        return "TERMINATION"
    if cumulative_points >= suspension_threshold:
        return "SUSPENSION"
    return "WARNING"


def issued_rung(cumulative_points, suspension_threshold, termination_threshold, highest_served_rank):
    """Whichever of the points-justified rung and the ceiling ranks lower."""
    justified = points_justified_rung(
        cumulative_points, suspension_threshold, termination_threshold
    )
    ceiling_rank = min(highest_served_rank + 1, 3)
    return RUNG_BY_RANK[min(RUNG_RANKS[justified], ceiling_rank)]


# --------------------------------------------------------------------------- #
# Chargeback oracles (PRD 3.9)
# --------------------------------------------------------------------------- #
def tier_rate_for_score(diversion_score):
    """Per-unit rate read off the three tiers, lower bounds inclusive."""
    for upper, rate in CHARGEBACK_TIER_RATES:
        if Decimal(str(diversion_score)) < Decimal(str(upper)):
            return rate
    return CHARGEBACK_TOP_TIER_RATE


def score_delta(diverted_units):
    return float(Decimal(str(SCORE_DELTA_PER_UNIT)) * Decimal(diverted_units))


def standing_for_score(diversion_score):
    score = Decimal(str(diversion_score))
    if score >= Decimal(str(STANDING_SUSPENDED_THRESHOLD)):
        return "SUSPENDED"
    if score >= Decimal(str(STANDING_PROBATION_THRESHOLD)):
        return "PROBATION"
    return "GOOD"


def clearance_override_floor(standard_map_floor_cents, clearance_discount_pct):
    """Standard floor times one minus the clearance fraction, rounded half up."""
    return round_half_up(
        Decimal(standard_map_floor_cents) * (Decimal(1) - Decimal(str(clearance_discount_pct)))
    )


def override_floor_lower_bound(standard_map_floor_cents):
    """Half the standard floor, truncated downward: no cut deeper than half."""
    return floor_to_int(Decimal(standard_map_floor_cents) * Decimal("0.50"))


# --------------------------------------------------------------------------- #
# Reconciliation invariants (PRD 2.11)
# --------------------------------------------------------------------------- #
LEDGER_CONTRIBUTING_VIOLATION_STATUSES = {
    "NOTICED",
    "DISPUTED",
    "CURED",
    "ESCALATED",
    "CLOSED_MOOT",
}
LEDGER_CONTRIBUTING_CHARGEBACK_STATUSES = {"ASSESSED", "DISPUTED", "UPHELD"}


def assert_reseller_points_reconcile(client, reseller_id, headers):
    """The stored points total equals the sum over contributing violations."""
    reseller = validate_success(client.get_reseller(reseller_id, headers))
    rows, _ = validate_paginated(
        client.list_violations(headers, params={"reseller_id": reseller_id, "limit": 100})
    )
    expected = sum(
        row["assessed_points"]
        for row in rows
        if row["assessed_points"] is not None
        and row["status"] in LEDGER_CONTRIBUTING_VIOLATION_STATUSES
    )
    assert reseller["violation_points_total"] == expected, (
        f"points ledger {reseller['violation_points_total']} != contributor sum {expected}"
    )
    return reseller


def assert_distributor_ledgers_reconcile(client, distributor_id, headers):
    """Balance and diversion score both equal their contributor sums."""
    distributor = validate_success(client.get_distributor(distributor_id, headers))
    rows, _ = validate_paginated(
        client.list_chargebacks(headers, params={"distributor_id": distributor_id, "limit": 100})
    )
    contributing = [
        row for row in rows if row["status"] in LEDGER_CONTRIBUTING_CHARGEBACK_STATUSES
    ]
    expected_balance = sum(row["amount_cents"] for row in contributing)
    expected_score = float(
        sum(Decimal(str(row["score_delta_applied"])) for row in contributing)
    )
    assert distributor["chargeback_balance_cents"] == expected_balance
    assert distributor["diversion_score"] == expected_score
    assert distributor["standing"] == standing_for_score(distributor["diversion_score"])
    return distributor


def assert_open_exception_count_reconciles(client, product_id, headers):
    """A product's open_exception_count equals its APPROVED exception count."""
    product = validate_success(client.get_product(product_id, headers))
    rows, _ = validate_paginated(
        client.list_exceptions(headers, params={"product_id": product_id, "limit": 100})
    )
    expected = len([row for row in rows if row["status"] == "APPROVED"])
    assert product["open_exception_count"] == expected
    return product


__all__ = [
    "round_half_up",
    "floor_to_int",
    "assert_common_fields",
    "assert_freshly_created",
    "assert_envelope_meta",
    "parse_instant",
    "same_instant",
    "assert_same_instant",
    "assert_pricing_policy_shape",
    "assert_product_shape",
    "assert_reseller_shape",
    "assert_distributor_shape",
    "assert_agreement_shape",
    "assert_observation_shape",
    "assert_violation_shape",
    "assert_notice_shape",
    "assert_exception_shape",
    "assert_serial_unit_shape",
    "assert_test_purchase_shape",
    "assert_chargeback_shape",
    "allocate_bundle",
    "effective_advertised_price",
    "deviation_cents",
    "deviation_pct",
    "base_points_for_fraction",
    "repeat_weight",
    "violation_points",
    "points_justified_rung",
    "issued_rung",
    "tier_rate_for_score",
    "score_delta",
    "standing_for_score",
    "clearance_override_floor",
    "override_floor_lower_bound",
    "assert_reseller_points_reconcile",
    "assert_distributor_ledgers_reconcile",
    "assert_open_exception_count_reconciles",
    "LEDGER_CONTRIBUTING_VIOLATION_STATUSES",
    "LEDGER_CONTRIBUTING_CHARGEBACK_STATUSES",
]
