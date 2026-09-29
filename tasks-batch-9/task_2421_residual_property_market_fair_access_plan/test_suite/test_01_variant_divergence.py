"""Two calculations that run the same ladder twice with different inputs.

The annual premium ladder is walked once at submission on producer-reported
inputs and again at bind on inspector-observed inputs; the assessment waterfall
is walked once on statewide market share and again on written-premium share.
Both pairs must diverge on the very same underlying facts.
"""

from test_helpers.api_client import FairPlanApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_field_equals,
    assert_pct,
    assert_ratio,
    find_one,
)
from test_helpers.constants import (
    APP_STATUS_BOUND,
    BASIS_MARKET_SHARE,
    BASIS_PREMIUM_VOLUME,
    EVENT_STATUS_ALLOCATED,
)
from test_helpers.fixtures import (
    Foundations,
    allocate_event,
    bind,
    build_bindable_application,
    create_event,
    create_member_insurers,
    create_zone,
    pin_clock,
    read_allocations,
    read_event,
    read_member,
)

# The one risk both premium variants are computed for: a 54,000,000-cent FRAME
# owner-occupied dwelling in a HURRICANE territory, rated off an approved filing
# of 900 cents per thousand against a surveyed voluntary average of 800.
QUOTED_ANNUAL_PREMIUM_CENTS = 546_750
VOLUNTARY_EQUIVALENT_PREMIUM_CENTS = 486_000
VOLUNTARY_MARKET_COMPARISON_PCT = "0.1250"
BASE_PREMIUM_CENTS = 607_500
BOUND_ANNUAL_PREMIUM_CENTS = 577_125
OBSERVED_CONDITION_SCORE = 72

# The one loss both allocation bases are computed for.
TRIGGER_LOSS_CENTS = 150_000_001
RESERVE_BALANCE_CENTS = 50_000_000
ASSESSABLE_AMOUNT_CENTS = 100_000_001


def _allocation_for(client: FairPlanApiClient, event_id: str, member_id: str) -> dict:
    return find_one(read_allocations(client, event_id), "member_insurer_id", member_id)


def _two_bases_on_the_same_loss(client: FairPlanApiClient):
    """Allocate one identical loss twice, once per basis, over the same carriers."""
    pin_clock(client)
    members = create_member_insurers(client)
    zone = create_zone(client)
    market_share_event = allocate_event(
        client,
        create_event(
            client,
            zone["id"],
            TRIGGER_LOSS_CENTS,
            RESERVE_BALANCE_CENTS,
            BASIS_MARKET_SHARE,
        ),
    )
    premium_volume_event = allocate_event(
        client,
        create_event(
            client,
            zone["id"],
            TRIGGER_LOSS_CENTS,
            RESERVE_BALANCE_CENTS,
            BASIS_PREMIUM_VOLUME,
        ),
    )
    return members, market_share_event, premium_volume_event


# ---------------------------------------------------------------------------
# The premium ladder, quoted then bound
# ---------------------------------------------------------------------------


def test_provisional_quote_rates_on_the_producer_reported_condition_score(
    foundations: Foundations,
) -> None:
    """Submission pins a quote keyed on the reported score of 88, a ten percent cut.

    PRD: "`PROVISIONAL_QUOTE`, written to an application's `quoted_annual_premium_cents` at submission, rates on the property's producer-reported `condition_score`, treats the cleared-major count as zero so no improvement credit can exist, and uses the submission clock date as the rate reference date."

    PRD: "From the rating condition score, choose a signed adjustment percentage: a reduction of ten percent when the score is at least 85; a reduction of five percent when the score is at least 70 but below 85; no adjustment at all when the score is at least 50 but below 70; and a surcharge of fifteen percent when the score is below 50."

    Design: Difficulty/dual_variant_calc/premium_provisional_quote_versus_bound_final_divergence
    """
    chain = build_bindable_application(foundations.client, foundations)

    application = chain.application
    assert_cents(
        application["quoted_annual_premium_cents"],
        QUOTED_ANNUAL_PREMIUM_CENTS,
        "quoted_annual_premium_cents",
    )
    assert_field_equals(application, "quote_rate_filing_id", foundations.filing_id)


def test_voluntary_equivalent_substitutes_the_surveyed_average_rate(
    foundations: Foundations,
) -> None:
    """The same ladder on the surveyed rate gives 486000 and a 0.1250 comparison.

    PRD: "`VOLUNTARY_EQUIVALENT`, written to `voluntary_equivalent_premium_cents` at submission, is identical to `PROVISIONAL_QUOTE` except that step 1 reads the pinned filing's `voluntary_market_avg_rate_per_1000_cents` instead of its filed rate."

    PRD: "`voluntary_market_comparison_pct` is then the quoted plan premium minus the voluntary-equivalent premium, divided by that voluntary-equivalent premium, rounded half up to four decimal places."

    Design: Difficulty/dual_variant_calc/premium_provisional_quote_versus_bound_final_divergence
    """
    chain = build_bindable_application(foundations.client, foundations)

    application = chain.application
    assert_cents(
        application["voluntary_equivalent_premium_cents"],
        VOLUNTARY_EQUIVALENT_PREMIUM_CENTS,
        "voluntary_equivalent_premium_cents",
    )
    assert_ratio(
        application["voluntary_market_comparison_pct"],
        VOLUNTARY_MARKET_COMPARISON_PCT,
        "voluntary_market_comparison_pct",
    )


def test_bound_final_rates_on_the_observed_score_and_diverges_from_the_quote(
    foundations: Foundations,
) -> None:
    """The observed 72 drops the tier to a five percent cut: 577125, not 546750.

    PRD: "`BOUND_FINAL`, written to a policy's `annual_premium_cents` at bind, rates on the chosen inspection's `observed_condition_score` — which may differ from the producer-reported figure and therefore move the condition tier — applies the improvement credit from that inspection's `cleared_major_count`, and uses the bind clock date as the rate reference date."

    PRD: "Binding therefore mutates four records. The new policy is created; the producer's `ytd_commission_cents` rises by the commission credited and the producer's `version` increments; the territory's `aggregate_insured_value_cents` rises by the policy's `exposure_value_cents`, its `concentration_ratio` is recomputed, its `status` is re-derived and its `version` increments by one; and the application moves `APPROVED_TO_BIND → BOUND` with its `version` incremented by one."

    Design: Difficulty/dual_variant_calc/premium_provisional_quote_versus_bound_final_divergence
    """
    chain = build_bindable_application(foundations.client, foundations)
    quoted = chain.application["quoted_annual_premium_cents"]

    policy = bind(chain)

    assert_cents(policy["base_premium_cents"], BASE_PREMIUM_CENTS, "base_premium_cents")
    assert_cents(policy["cat_surcharge_cents"], 0, "cat_surcharge_cents")
    assert_cents(
        policy["annual_premium_cents"],
        BOUND_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )
    assert_field_equals(policy, "condition_score_at_bind", OBSERVED_CONDITION_SCORE)
    assert policy["annual_premium_cents"] != quoted, (
        "the bound premium must diverge from the provisional quote"
    )
    assert_field_equals(chain.refresh_application(), "status", APP_STATUS_BOUND)


# ---------------------------------------------------------------------------
# The assessment waterfall, on each basis
# ---------------------------------------------------------------------------


def test_market_share_basis_weights_and_absorbs_on_statewide_share(
    client: FairPlanApiClient,
) -> None:
    """On MARKET_SHARE the 40.00-weight carrier absorbs the one-cent remainder.

    PRD: "Each eligible member's weight is its `market_share_pct` when the event's `allocation_basis` is `MARKET_SHARE`, and its `written_premium_share_pct` when the basis is `PREMIUM_VOLUME`; that weight is snapshotted onto the resulting allocation as `basis_weight_pct`."

    PRD: "It is absorbed entirely by one member: the eligible member with the greatest weight, with a tie on equal weight broken in favour of the earliest `created_at` among those members."

    Design: Difficulty/dual_variant_calc/allocation_market_share_versus_premium_volume_divergence
    """
    members, market_share_event, _premium_volume_event = _two_bases_on_the_same_loss(
        client
    )

    assert_field_equals(market_share_event, "status", EVENT_STATUS_ALLOCATED)
    assert_cents(
        market_share_event["assessable_amount_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "assessable_amount_cents",
    )
    assert_cents(
        market_share_event["allocated_total_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "allocated_total_cents",
    )

    largest = _allocation_for(client, market_share_event["id"], members[2]["id"])
    assert_pct(largest["basis_weight_pct"], "40.00", "basis_weight_pct")
    assert_cents(largest["gross_share_cents"], 40_000_001, "gross_share_cents")

    smaller = _allocation_for(client, market_share_event["id"], members[0]["id"])
    assert_cents(smaller["gross_share_cents"], 30_000_000, "gross_share_cents")


def test_premium_volume_basis_reweights_the_identical_loss(
    client: FairPlanApiClient,
) -> None:
    """The same 100000001 loss charges the same carrier 80000001 on premium share.

    PRD: "Under `MARKET_SHARE` a carrier with a small statewide share but a large premium book is assessed less than it would be under `PREMIUM_VOLUME` for the identical event, and because the absorber is chosen by weight, both the per-member shares **and** the identity of the remainder absorber can differ between the two bases on the same event."

    PRD: "**Each member's raw share is rounded half up to whole cents first**, and only then is the residue reconciled — summing raw shares and rounding once at the end is explicitly not the rule."

    Design: Difficulty/dual_variant_calc/allocation_market_share_versus_premium_volume_divergence
    """
    members, market_share_event, premium_volume_event = _two_bases_on_the_same_loss(
        client
    )

    assert_cents(
        premium_volume_event["assessable_amount_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "assessable_amount_cents",
    )
    assert_cents(
        premium_volume_event["allocated_total_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "allocated_total_cents",
    )

    largest = _allocation_for(client, premium_volume_event["id"], members[2]["id"])
    assert_pct(largest["basis_weight_pct"], "80.00", "basis_weight_pct")
    assert_cents(largest["gross_share_cents"], 80_000_001, "gross_share_cents")

    smaller = _allocation_for(client, premium_volume_event["id"], members[0]["id"])
    assert_cents(smaller["gross_share_cents"], 10_000_000, "gross_share_cents")

    market_share_largest = _allocation_for(
        client, market_share_event["id"], members[2]["id"]
    )
    assert (
        market_share_largest["gross_share_cents"] != largest["gross_share_cents"]
    ), "the two bases must charge the same carrier different amounts"


def test_cumulative_assessed_accumulates_across_both_bases(
    client: FairPlanApiClient,
) -> None:
    """The carrier's running liability is the sum of both pending allocations.

    PRD: "A member's `cumulative_assessed_cents` is always the sum of `net_due_cents` over that member's allocations whose `status` is `PENDING` or `PAID`, and an event's `allocated_total_cents` is the sum of `gross_share_cents` over its allocations whose `status` is not `ABATED` — a figure that must equal `assessable_amount_cents` for as long as the event sits in `ALLOCATED`, `INVOICED` or `SETTLED`."

    Design: Difficulty/dual_variant_calc/allocation_market_share_versus_premium_volume_divergence
    """
    members, market_share_event, premium_volume_event = _two_bases_on_the_same_loss(
        client
    )

    reread = read_member(client, members[2]["id"])
    assert_cents(
        reread["cumulative_assessed_cents"], 120_000_002, "cumulative_assessed_cents"
    )
    assert_cents(
        read_event(client, market_share_event["id"])["allocated_total_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "allocated_total_cents",
    )
    assert_cents(
        read_event(client, premium_volume_event["id"])["allocated_total_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "allocated_total_cents",
    )
