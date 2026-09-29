"""Exact-boundary arithmetic: a listing that lands precisely on the floor, and a
ledger that lands precisely on a ladder threshold. One cent and one point either
side of each boundary changes the outcome, so both sides are measured.
"""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import BCM_HEADERS, api_client
from test_helpers.assertions import (
    assert_same_instant,
    deviation_pct,
    effective_advertised_price,
    floor_to_int,
    violation_points,
)
from test_helpers.fixtures import (
    bootstrap_authorized_channel,
    capture_observation,
    create_detected_violation,
    evaluate_observation,
    issue_notice,
    pin_clock,
    read_compliance_summary,
    read_reseller,
    read_violation,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_10 = "2026-08-10T00:00:00Z"
OBSERVED_AUG_05 = "2026-08-05T00:00:00Z"

SHIPPING_CENTS = 700
AUTO_COUPON_CENTS = 2000
PROMO_CODE_CENTS = 1500


# --------------------------------------------------------------------------- #
# Instance 1 — the effective advertised price landing exactly on the floor
# --------------------------------------------------------------------------- #
def _setup_retailer_channel():
    """A retailer-site reseller under a 10000-cent floor at the default definition."""
    pin_clock(CLOCK_AUG_01)
    world = bootstrap_authorized_channel(
        product_overrides={"msrp_cents": 15000, "standard_map_floor_cents": 10000},
        reseller_overrides={"primary_channel": "RETAILER_SITE"},
        agreement_overrides={"permitted_channels": ["RETAILER_SITE"]},
    )
    pin_clock(CLOCK_AUG_10)
    return world


def _capture_priced_listing(world, listed_price_cents, suffix):
    """Capture one listing carrying all three discount fields at once."""
    return capture_observation(
        world["product"]["id"],
        channel="RETAILER_SITE",
        listed_price_cents=listed_price_cents,
        observed_at=OBSERVED_AUG_05,
        matched_reseller_id=world["reseller"]["id"],
        shipping_cents=SHIPPING_CENTS,
        auto_coupon_cents=AUTO_COUPON_CENTS,
        promo_code_cents=PROMO_CODE_CENTS,
        listing_url=f"https://retailer.example/boundary-{suffix}",
    )


def test_only_the_largest_qualifying_discount_is_credited_and_shipping_is_excluded():
    """The default definition counts the auto-coupon alone and ignores the rest.

    PRD: "Only the **single largest** qualifying amount is a candidate for attribution;
    qualifying discounts are never added together, so a listing with a qualifying
    auto-coupon of 500 cents and a qualifying promo code of 800 cents offers a candidate
    of 800 cents, not 1300."

    Design: Difficulty/boundary_precision_check/effective_advertised_price_exactly_at_floor_is_compliant
    """
    world = _setup_retailer_channel()
    observation = _capture_priced_listing(world, 12000, "at-floor")
    evaluation = evaluate_observation(observation["id"])

    # Shipping is excluded from the gross price, the promo code does not qualify, and
    # the 2000-cent auto-coupon sits well under the 4800-cent attribution cap.
    assert floor_to_int(12000 * 0.40) == 4800
    expected = effective_advertised_price(
        12000,
        shipping_cents=SHIPPING_CENTS,
        auto_coupon_cents=AUTO_COUPON_CENTS,
        promo_code_cents=PROMO_CODE_CENTS,
    )
    assert expected == 10000
    assert evaluation["effective_advertised_price_cents"] == 10000
    assert evaluation["effective_map_floor_cents"] == 10000
    assert evaluation["floor_source"] == "STANDARD"


def test_a_price_resting_exactly_on_the_floor_is_compliant_and_scores_no_points():
    """Equality with the floor is compliance, not a one-cent breach.

    PRD: "When the effective advertised price is greater than or equal to the resolved
    floor, the observation moves `CAPTURED → EVALUATED_COMPLIANT`. It stores
    `allocated_component_price_cents` (bundles only), `effective_advertised_price_cents`
    and `effective_map_floor_cents`, sets both `deviation_cents` and `deviation_pct` to
    0, advances its own `version`, and creates no violation."

    Design: Difficulty/boundary_precision_check/effective_advertised_price_exactly_at_floor_is_compliant
    """
    world = _setup_retailer_channel()
    observation = _capture_priced_listing(world, 12000, "at-floor")
    evaluation = evaluate_observation(observation["id"])

    assert evaluation["evaluation_status"] == "EVALUATED_COMPLIANT"
    assert evaluation["deviation_cents"] == 0
    assert evaluation["deviation_pct"] == 0
    assert evaluation["violation_id"] is None

    rows, meta = validate_paginated(
        api_client.list_violations(
            BCM_HEADERS, params={"reseller_id": world["reseller"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 0


def test_one_cent_below_the_floor_is_a_breach_worth_the_lowest_severity_tier():
    """A single cent of deviation crosses the boundary and earns one point.

    PRD: "`deviation_cents` itself is defined as the resolved floor minus the effective
    advertised price, floored at 0 so it is never negative, and `deviation_pct` is
    `deviation_cents` divided by the resolved floor, rounded half up to four decimal
    places."

    Design: Difficulty/boundary_precision_check/effective_advertised_price_exactly_at_floor_is_compliant
    """
    world = _setup_retailer_channel()
    observation = _capture_priced_listing(world, 11999, "one-cent-under")
    evaluation = evaluate_observation(observation["id"])

    # The attribution cap moves with the gross price but stays above the coupon.
    assert floor_to_int(11999 * 0.40) == 4799
    assert evaluation["effective_advertised_price_cents"] == 9999
    assert evaluation["evaluation_status"] == "EVALUATED_BREACH"
    assert evaluation["deviation_cents"] == 1
    assert evaluation["deviation_pct"] == deviation_pct(10000, 1) == 0.0001
    assert evaluation["provisional_points"] == violation_points(10000, 9999, "RETAILER_SITE", 0) == 1

    violation = read_violation(evaluation["violation_id"])
    assert violation["status"] == "DETECTED"
    assert violation["provisional_points"] == 1

    # Points only enter the ledger when a notice is issued.
    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 0


# --------------------------------------------------------------------------- #
# Instance 2 — the ledger landing exactly on the suspension threshold
# --------------------------------------------------------------------------- #
SUSPENSION_STARTS = "2026-08-15T00:00:00Z"
SUSPENSION_ENDS = "2026-08-25T00:00:00Z"


def _setup_ledger_at_exactly_six():
    """One point then five more, so the ledger lands exactly on the threshold of six."""
    pin_clock(CLOCK_AUG_01)
    world = bootstrap_authorized_channel(
        policy_overrides={
            "cure_window_days": 10,
            "suspension_points_threshold": 6,
            "termination_points_threshold": 12,
            "suspension_cooling_off_days": 14,
        },
        product_overrides={"msrp_cents": 15000, "standard_map_floor_cents": 10000},
        reseller_overrides={"primary_channel": "RETAILER_SITE"},
        agreement_overrides={"permitted_channels": ["RETAILER_SITE"]},
    )
    pin_clock(CLOCK_AUG_10)
    first_violation, _obs, _eval = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=9900,
        channel="RETAILER_SITE",
        observed_at=OBSERVED_AUG_05,
        listing_url="https://retailer.example/threshold-1",
    )
    first_notice = issue_notice(world["reseller"]["id"], first_violation["id"])
    second_violation, _obs2, _eval2 = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=8000,
        channel="RETAILER_SITE",
        observed_at=OBSERVED_AUG_05,
        listing_url="https://retailer.example/threshold-2",
    )
    world.update(
        {
            "first_violation": first_violation,
            "first_notice": first_notice,
            "second_violation": second_violation,
        }
    )
    return world


def _issue_suspension(world):
    return issue_notice(
        world["reseller"]["id"],
        world["second_violation"]["id"],
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
    )


def test_the_repeat_weight_lands_the_second_notice_exactly_on_the_threshold():
    """One prior notice weights the second breach to exactly five points.

    PRD: "Finally, multiply base points by channel weight by repeat weight and round the
    product half up to a whole number of points — **once, at the end**."

    Design: Difficulty/boundary_precision_check/ladder_rung_at_exact_suspension_points_threshold
    """
    world = _setup_ledger_at_exactly_six()
    assert world["first_notice"]["rung"] == "WARNING"
    assert world["first_notice"]["assessed_points"] == 1
    assert world["first_notice"]["cumulative_points_at_issue"] == 1

    second = _issue_suspension(world)
    assert second["assessed_points"] == violation_points(10000, 8000, "RETAILER_SITE", 1) == 5
    assert second["cumulative_points_at_issue"] == 6


def test_a_ledger_exactly_at_the_threshold_installs_the_suspension_rung():
    """The threshold comparison is at-or-above, so equality suspends.

    PRD: "Compare that figure against the cited policy's two thresholds, with both
    boundaries inclusive at the lower bound: the points-justified rung is `WARNING` when
    the cumulative figure is strictly below `suspension_points_threshold`, `SUSPENSION`
    when it is at or above `suspension_points_threshold` but strictly below
    `termination_points_threshold`, and `TERMINATION` when it is at or above
    `termination_points_threshold`."

    Design: Difficulty/boundary_precision_check/ladder_rung_at_exact_suspension_points_threshold
    """
    world = _setup_ledger_at_exactly_six()
    second = _issue_suspension(world)

    assert second["rung"] == "SUSPENSION"
    assert_same_instant(
        second["suspension_starts_at"], SUSPENSION_STARTS, "suspension_starts_at"
    )
    assert_same_instant(second["suspension_ends_at"], SUSPENSION_ENDS, "suspension_ends_at")

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 6
    assert reseller["authorization_status"] == "SUSPENDED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "SUSPENSION"
    assert_same_instant(reseller["suspension_ends_at"], SUSPENSION_ENDS, "suspension_ends_at")

    violation = read_violation(world["second_violation"]["id"])
    assert violation["status"] == "NOTICED"
    assert violation["assessed_floor_cents"] == 10000
    assert_same_instant(violation["cure_deadline_at"], "2026-08-20T00:00:00Z", "cure_deadline_at")


def test_the_gap_to_suspension_floors_at_zero_the_moment_it_is_reached():
    """Reaching the threshold exactly leaves a gap of zero, not a negative number.

    PRD: "the two gaps `points_to_suspension` and `points_to_termination`, each being
    the reseller's own governing thresholds minus the current total, floored at zero
    when the threshold has already been passed."

    Design: Difficulty/boundary_precision_check/ladder_rung_at_exact_suspension_points_threshold
    """
    world = _setup_ledger_at_exactly_six()

    before = read_compliance_summary(world["reseller"]["id"])
    assert before["violation_points_total"] == 1
    assert before["points_to_suspension"] == 5
    assert before["points_to_termination"] == 11
    assert before["highest_issued_rung"] == "WARNING"
    # One point justifies no more than a warning, and the ceiling would allow one rung
    # more than the warning already served.
    assert before["next_rung"] == "WARNING"

    _issue_suspension(world)

    after = read_compliance_summary(world["reseller"]["id"])
    assert after["violation_points_total"] == 6
    assert after["summed_assessed_points"] == 6
    assert after["contributing_violation_count"] == 2
    assert after["points_to_suspension"] == 0
    assert after["points_to_termination"] == 6
    assert after["highest_issued_rung"] == "SUSPENSION"
    # Six points is short of the twelve termination demands, so the next notice would
    # suspend again rather than terminate.
    assert after["next_rung"] == "SUSPENSION"
