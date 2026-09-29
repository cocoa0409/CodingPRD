"""Money calculations: the premium floor, a tier boundary and the short-rate refund.

Each test pins every rating input, drives one bind or one cancellation, and
asserts the persisted legs of the computation together with the ledgers the
computation feeds — the producer's year-to-date commission and the territory's
exposure aggregate.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_date_equals,
    assert_field_equals,
    assert_ratio,
)
from test_helpers.constants import (
    CANCEL_REASON_POLICYHOLDER_REQUEST,
    CLOCK_BASE_DATE,
    CONSTRUCTION_MASONRY,
    COVERAGE_STATUS_CANCELLED,
    ZONE_STATUS_OPEN,
)
from test_helpers.fixtures import (
    ApplicationChain,
    add_three_declinations,
    bind,
    build_bindable_application,
    build_in_force_policy,
    complete_inspection,
    create_property,
    order_inspection,
    pin_clock,
    read_producer,
    read_zone,
    review_eligibility,
    submit,
)
from test_helpers.test_users import binder_headers


def test_minimum_annual_premium_floor_replaces_the_rated_premium(roomy_foundations):
    """A tiny masonry risk rates below the floor, so the floor is what is charged.

    PRD: "Take the pre-credit premium, add the signed condition adjustment, and
    subtract the improvement credit. If the result is below 35,000 cents — three
    hundred fifty dollars, the plan's minimum annual premium — use 35,000 cents
    instead. The outcome is `annual_premium_cents`."

    PRD: "The catastrophe concentration surcharge is never commissionable, so
    commissionable premium is the policy's `annual_premium_cents` less its
    `cat_surcharge_cents`. Multiply that by the producer's `commission_rate_bps`,
    divide by 10,000, and round half up to whole cents; the result is written to
    the policy's `commission_credited_cents`."

    Design: Corner/calculations/minimum_annual_premium_floor_replaces_the_rated_premium
    """
    client = roomy_foundations.client
    chain = build_bindable_application(
        client,
        roomy_foundations,
        observed_condition_score=88,
        property_overrides={
            "address_line": "9 Cabin Ln",
            "construction_type": CONSTRUCTION_MASONRY,
            "roof_age_years": 4,
            "replacement_cost_cents": 5_000_000,
            "condition_score": 88,
        },
        application_overrides={"requested_dwelling_limit_cents": 3_000_000},
    )

    response = client.bind_policy(
        f.bind_payload(chain.application_id, CLOCK_BASE_DATE), binder_headers()
    )

    policy = validate_success(response, 201)
    assert_cents(policy["base_premium_cents"], 27_000, "base_premium_cents")
    assert_cents(policy["cat_surcharge_cents"], 0, "cat_surcharge_cents")
    assert_cents(policy["annual_premium_cents"], 35_000, "annual_premium_cents")
    assert_cents(policy["dwelling_limit_cents"], 3_000_000, "dwelling_limit_cents")
    assert_cents(policy["exposure_value_cents"], 3_000_000, "exposure_value_cents")
    assert_cents(
        policy["commission_credited_cents"], 3_500, "commission_credited_cents"
    )
    producer = read_producer(client, roomy_foundations.producer_id)
    assert_cents(producer["ytd_commission_cents"], 3_500, "ytd_commission_cents")


def test_condition_adjustment_tier_boundary_at_score_seventy(roomy_foundations):
    """A score of exactly seventy earns the five percent cut; sixty-nine earns none.

    PRD: "From the rating condition score, choose a signed adjustment percentage: a
    reduction of ten percent when the score is at least 85; a reduction of five
    percent when the score is at least 70 but below 85; no adjustment at all when
    the score is at least 50 but below 70; and a surcharge of fifteen percent when
    the score is below 50. Multiply the pre-credit premium by that signed
    percentage and round half up to whole cents, keeping the sign."

    PRD: "`BOUND_FINAL`, written to a policy's `annual_premium_cents` at bind, rates on
    the chosen inspection's `observed_condition_score` — which may differ from the
    producer-reported figure and therefore move the condition tier — applies the
    improvement credit from that inspection's `cleared_major_count`, and uses the
    bind clock date as the rate reference date."

    PRD: "A producer's `ytd_commission_cents` is a conserved quantity recomputed after
    every credit and every return: it is the sum, over **all** policies whose
    `producer_id` is that producer, of `commission_credited_cents` minus
    `commission_returned_cents`."

    Design: Corner/calculations/condition_adjustment_tier_boundary_at_score_seventy
    """
    client = roomy_foundations.client
    chain_a = build_bindable_application(
        client, roomy_foundations, observed_condition_score=70
    )
    property_b = create_property(client, roomy_foundations, address_line="3 Shore Rd")
    application_b = validate_success(
        client.create_application(
            f.application_payload(
                property_id=property_b["id"], applicant_id=chain_a.applicant_id
            ),
            roomy_foundations.producer_headers,
        ),
        201,
    )
    chain_b = ApplicationChain(
        client=client,
        foundations=roomy_foundations,
        applicant=chain_a.applicant,
        property=property_b,
        application=application_b,
    )
    add_three_declinations(chain_b)
    submit(chain_b)
    review_eligibility(chain_b)
    order_inspection(chain_b)
    complete_inspection(chain_b, observed_condition_score=69)

    policy_a = bind(chain_a, effective_date=CLOCK_BASE_DATE)
    policy_b = bind(chain_b, effective_date=CLOCK_BASE_DATE)

    assert_field_equals(policy_a, "condition_score_at_bind", 70)
    assert_cents(policy_a["base_premium_cents"], 607_500, "A base_premium_cents")
    assert_cents(policy_a["cat_surcharge_cents"], 0, "A cat_surcharge_cents")
    assert_cents(policy_a["annual_premium_cents"], 577_125, "A annual_premium_cents")
    assert_field_equals(policy_b, "condition_score_at_bind", 69)
    assert_cents(policy_b["base_premium_cents"], 607_500, "B base_premium_cents")
    assert_cents(policy_b["annual_premium_cents"], 607_500, "B annual_premium_cents")
    assert_cents(
        policy_a["commission_credited_cents"], 57_713, "A commission_credited_cents"
    )
    assert_cents(
        policy_b["commission_credited_cents"], 60_750, "B commission_credited_cents"
    )
    producer = read_producer(client, roomy_foundations.producer_id)
    assert_cents(producer["ytd_commission_cents"], 118_463, "ytd_commission_cents")
    zone = read_zone(client, roomy_foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"],
        108_000_000,
        "aggregate_insured_value_cents",
    )
    assert_ratio(zone["concentration_ratio"], "0.1200", "concentration_ratio")
    assert_field_equals(zone, "status", ZONE_STATUS_OPEN)


def test_short_rate_cancellation_shrinks_unearned_premium_before_the_fee_tier(
    roomy_foundations,
):
    """The short-rate factor lands before the fee tier, shrinking both amounts.

    PRD: "Count the whole days from the policy's `effective_date` to its
    `cancellation_date`; that is the days in force. Subtract that count from three
    hundred sixty-five, treat a negative result as zero, and divide by three
    hundred sixty-five; that quotient is the unearned fraction, and it equals one
    when the cancellation date is the effective date itself."

    PRD: "Under the `SHORT_RATE` variant — which applies when `cancel_reason` is
    `POLICYHOLDER_REQUEST` — the same product is additionally multiplied by 0.90
    before rounding, so a policyholder-requested cancellation yields a smaller
    unearned premium and may therefore also fall into a lower fee tier."

    PRD: "The fee is then chosen from `unearned_premium_cents` — never from the refund
    it is subtracted from."

    PRD: "On early termination the same unearned fraction used by the refund
    calculation is applied to the amount originally credited: multiply the
    policy's `commission_credited_cents` by that unearned fraction, round half up
    to whole cents, and write the result to `commission_returned_cents`."

    Design: Corner/calculations/short_rate_cancellation_shrinks_unearned_premium_before_the_fee_tier
    """
    client = roomy_foundations.client
    chain = build_in_force_policy(
        client, roomy_foundations, effective_date=CLOCK_BASE_DATE
    )
    assert_cents(chain.policy["annual_premium_cents"], 577_125, "annual_premium_cents")
    pin_clock(client, "2026-12-01T00:00:00Z")

    response = client.cancel_policy(
        chain.policy_id,
        f.cancellation_payload(
            cancel_reason=CANCEL_REASON_POLICYHOLDER_REQUEST, cancel_date="2026-12-01"
        ),
        binder_headers(),
    )

    cancelled = validate_success(response, 200)
    assert_field_equals(cancelled, "coverage_status", COVERAGE_STATUS_CANCELLED)
    assert_field_equals(
        cancelled, "cancel_reason", CANCEL_REASON_POLICYHOLDER_REQUEST
    )
    assert_date_equals(cancelled["cancellation_date"], "2026-12-01", "cancellation_date")
    assert_cents(cancelled["unearned_premium_cents"], 389_915, "unearned_premium_cents")
    assert_cents(cancelled["cancellation_fee_cents"], 11_697, "cancellation_fee_cents")
    assert_cents(cancelled["refund_cents"], 378_218, "refund_cents")
    assert_cents(
        cancelled["commission_returned_cents"], 43_324, "commission_returned_cents"
    )
    producer = read_producer(client, roomy_foundations.producer_id)
    assert_cents(producer["ytd_commission_cents"], 14_389, "ytd_commission_cents")
    zone = read_zone(client, roomy_foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"], 0, "aggregate_insured_value_cents"
    )
