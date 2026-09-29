"""Formulas whose answer depends on how several inputs are combined.

Three shapes are exercised: a surcharge clamped between a floor and a ceiling
while six other inputs feed the same premium, a waterfall whose per-member
rounding order decides the sign of the reconciliation figure, and two
adjustments that are both percentages of one pinned intermediate total.
"""

from typing import Tuple

from test_helpers import factories as f
from test_helpers.api_client import FairPlanApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_field_equals,
    assert_pct,
    assert_ratio,
    find_one,
)
from test_helpers.constants import (
    BASIS_MARKET_SHARE,
    CONSTRUCTION_MASONRY,
    EVENT_STATUS_ALLOCATED,
    INSPECTION_RESULT_PASS_WITH_CONDITIONS,
    MEMBER_STATUS_RUNOFF,
    MEMBER_STATUS_WITHDRAWN,
    ZONE_STATUS_CLOSED,
    ZONE_STATUS_RESTRICTED,
)
from test_helpers.fixtures import (
    ApplicationChain,
    Foundations,
    allocate_event,
    bind,
    bind_exposure,
    build_bindable_application,
    build_inspection_pending_application,
    complete_inspection,
    create_event,
    create_member_insurers,
    create_zone,
    pin_clock,
    read_allocations,
    read_inspection,
    read_member,
    read_producer,
    read_requirements,
    read_zone,
)
from test_helpers.test_users import admin_headers, inspector_headers

FIRST_POLICY_ANNUAL_PREMIUM_CENTS = 688_500
SECOND_POLICY_BASE_PREMIUM_CENTS = 135_000
SECOND_POLICY_SURCHARGE_CENTS = 15_188
SECOND_POLICY_ANNUAL_PREMIUM_CENTS = 135_169
SECOND_POLICY_VOLUNTARY_EQUIVALENT_CENTS = 120_150

ASSESSABLE_AMOUNT_CENTS = 100_000_001

CREDITED_ANNUAL_PREMIUM_CENTS = 552_825
CREDITED_COMMISSION_CENTS = 55_283


def _zone_at_eighty_five_percent(
    foundations: Foundations,
) -> Tuple[ApplicationChain, ApplicationChain]:
    """Fill 85% of the cap with one policy, then stage a second one behind it."""
    client = foundations.client
    first = bind_exposure(
        client,
        foundations,
        dwelling_limit_cents=85_000_000,
        address_line="1 Shore Rd",
        construction_type=CONSTRUCTION_MASONRY,
        condition_score=88,
        observed_condition_score=88,
        replacement_cost_cents=100_000_000,
    )
    second = build_bindable_application(
        client,
        foundations,
        observed_condition_score=88,
        applicant_overrides={"full_name": "Bo Owner", "email": "bo@example.com"},
        property_overrides={
            "address_line": "2 Shore Rd",
            "construction_type": CONSTRUCTION_MASONRY,
            "roof_age_years": 4,
            "replacement_cost_cents": 20_000_000,
            "condition_score": 88,
        },
        application_overrides={"requested_dwelling_limit_cents": 15_000_000},
    )
    return first, second


def _two_eligible_carriers_and_one_draft_event(client: FairPlanApiClient):
    """Withdraw the largest carrier so two equal-weight carriers remain."""
    pin_clock(client)
    members = create_member_insurers(client)
    zone = create_zone(client)
    event = create_event(
        client, zone["id"], 150_000_001, 50_000_000, BASIS_MARKET_SHARE
    )
    for status in (MEMBER_STATUS_RUNOFF, MEMBER_STATUS_WITHDRAWN):
        response = client.update_member_insurer(
            members[2]["id"], f.member_status_payload(status), admin_headers()
        )
        assert response.status_code == 200, response.text
    return members, event


def _cleared_major_requirement(foundations: Foundations) -> ApplicationChain:
    """One MAJOR requirement raised, evidenced and cleared, back to bindable."""
    client = foundations.client
    chain = build_inspection_pending_application(client, foundations)
    complete_inspection(
        chain,
        observed_condition_score=72,
        result=INSPECTION_RESULT_PASS_WITH_CONDITIONS,
        requirements=[f.requirement_spec()],
    )
    requirement = read_requirements(client, chain.inspection_id)[0]
    evidence = client.submit_requirement_evidence(
        requirement["id"], f.requirement_evidence_payload(), chain.producer_headers
    )
    assert evidence.status_code == 200, evidence.text
    clearance = client.clear_requirement(
        requirement["id"], f.requirement_clearance_payload(), inspector_headers()
    )
    assert clearance.status_code == 200, clearance.text
    chain.refresh_application()
    return chain


# ---------------------------------------------------------------------------
# A clamped surcharge with six other inputs
# ---------------------------------------------------------------------------


def test_first_policy_carries_no_surcharge_and_drives_the_ratio_to_the_rung(
    foundations: Foundations,
) -> None:
    """The opening bind reads a ratio of zero, so its surcharge is zero.

    PRD: "Read the territory's `concentration_ratio` **before** this policy's own exposure is added to the territory. Subtract 0.60 from it; if the result is negative, treat it as zero. Multiply what remains by 0.45. If that product exceeds 0.25, use 0.25 instead — the surcharge is capped at a quarter of the base premium. Multiply `base_premium_cents` by the resulting surcharge percentage and round half up to whole cents; that is `cat_surcharge_cents`."

    PRD: "The territory's derived `status` is then read off a three-rung ladder: the status is `CLOSED` when the concentration ratio is at least 1.0000, otherwise `RESTRICTED` when the ratio is at least 0.8500, otherwise `OPEN`."

    Design: Difficulty/combinatorial_formula/premium_clamped_cat_surcharge_over_five_inputs
    """
    first, _second = _zone_at_eighty_five_percent(foundations)

    assert_cents(first.policy["cat_surcharge_cents"], 0, "cat_surcharge_cents")
    assert_cents(
        first.policy["annual_premium_cents"],
        FIRST_POLICY_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )

    zone = read_zone(foundations.client, foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"], 85_000_000, "aggregate_insured_value_cents"
    )
    assert_ratio(zone["concentration_ratio"], "0.8500", "concentration_ratio")
    assert_field_equals(zone, "status", ZONE_STATUS_RESTRICTED)


def test_second_policy_surcharge_is_clamped_by_the_min_and_max_bounds(
    foundations: Foundations,
) -> None:
    """At a 0.8500 ratio the surcharge is 0.1125 of base: 15188 cents, not the cap.

    PRD: "Multiply the selected rate by that figure, then by the construction factor for the property's `construction_type` (1.25 for `FRAME`, 1.00 for `MASONRY`, 1.60 for `MOBILE`), then by the occupancy factor for its `occupancy` (1.00 for `OWNER_OCCUPIED`, 1.15 for `TENANT_OCCUPIED`, 1.45 for `VACANT`), then by the package factor for the `peril_package` (1.00 for `BASIC_FIRE_EO`, 1.35 for `EXTENDED_WIND`)."

    PRD: "**Pre-credit premium.** Add `base_premium_cents` and `cat_surcharge_cents`. Both of the next two adjustments are keyed on **this** pre-credit figure and never on a running total, which is what makes the otherwise circular-looking dependency between them well defined."

    Design: Difficulty/combinatorial_formula/premium_clamped_cat_surcharge_over_five_inputs
    """
    _first, second = _zone_at_eighty_five_percent(foundations)

    policy = bind(second)

    assert_cents(
        policy["base_premium_cents"],
        SECOND_POLICY_BASE_PREMIUM_CENTS,
        "base_premium_cents",
    )
    assert_cents(
        policy["cat_surcharge_cents"],
        SECOND_POLICY_SURCHARGE_CENTS,
        "cat_surcharge_cents",
    )
    assert_cents(
        policy["annual_premium_cents"],
        SECOND_POLICY_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )


def test_clamped_surcharge_also_shows_in_the_quote_and_closes_the_territory(
    foundations: Foundations,
) -> None:
    """The quote carries the same clamped surcharge, and the bind fills the cap.

    PRD: "The plan's live exposure in a territory is the derived field `aggregate_insured_value_cents`: the sum of `exposure_value_cents` over every policy attributed to that territory whose `coverage_status` is either `BOUND` or `IN_FORCE`."

    PRD: "Both thresholds are inclusive, so a ratio of exactly 0.8500 is `RESTRICTED` and a ratio of exactly 1.0000 is `CLOSED`."

    Design: Difficulty/combinatorial_formula/premium_clamped_cat_surcharge_over_five_inputs
    """
    _first, second = _zone_at_eighty_five_percent(foundations)

    assert_cents(
        second.application["quoted_annual_premium_cents"],
        SECOND_POLICY_ANNUAL_PREMIUM_CENTS,
        "quoted_annual_premium_cents",
    )
    assert_cents(
        second.application["voluntary_equivalent_premium_cents"],
        SECOND_POLICY_VOLUNTARY_EQUIVALENT_CENTS,
        "voluntary_equivalent_premium_cents",
    )
    assert_ratio(
        second.application["voluntary_market_comparison_pct"],
        "0.1250",
        "voluntary_market_comparison_pct",
    )

    bind(second)

    zone = read_zone(foundations.client, foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"],
        100_000_000,
        "aggregate_insured_value_cents",
    )
    assert_ratio(zone["concentration_ratio"], "1.0000", "concentration_ratio")
    assert_field_equals(zone, "status", ZONE_STATUS_CLOSED)


# ---------------------------------------------------------------------------
# Rounding order inside the allocation waterfall
# ---------------------------------------------------------------------------


def test_per_member_rounding_first_produces_a_negative_remainder(
    client: FairPlanApiClient,
) -> None:
    """Two 50000000.5 raw shares round up first, so the remainder is minus one.

    PRD: "**Each member's raw share is rounded half up to whole cents first**, and only then is the residue reconciled — summing raw shares and rounding once at the end is explicitly not the rule."

    PRD: "The reconciliation figure, `remainder_cents`, is `assessable_amount_cents` minus the sum of the per-member rounded shares, and it may be negative."

    Design: Difficulty/combinatorial_formula/allocation_round_each_share_then_absorb_negative_remainder
    """
    members, event = _two_eligible_carriers_and_one_draft_event(client)

    allocated = allocate_event(client, event)

    assert_field_equals(allocated, "status", EVENT_STATUS_ALLOCATED)
    assert_cents(allocated["remainder_cents"], -1, "remainder_cents")
    assert_cents(
        allocated["allocated_total_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "allocated_total_cents",
    )

    allocations = read_allocations(client, event["id"])
    first = find_one(allocations, "member_insurer_id", members[0]["id"])
    second = find_one(allocations, "member_insurer_id", members[1]["id"])
    assert_cents(first["gross_share_cents"], 50_000_000, "gross_share_cents")
    assert_cents(second["gross_share_cents"], 50_000_001, "gross_share_cents")
    assert_pct(first["basis_weight_pct"], "30.00", "basis_weight_pct")


def test_withdrawn_carrier_is_excluded_from_the_eligible_member_set(
    client: FairPlanApiClient,
) -> None:
    """The withdrawn carrier gets no row at all and no running liability.

    PRD: "The eligible members are those whose membership `status` is `ACTIVE` or `RUNOFF`; `WITHDRAWN` carriers are excluded."

    PRD: "Moving `RUNOFF → WITHDRAWN` requires the carrier to currently be `RUNOFF`; from that point forward the carrier is excluded from the eligible member set, and any new declination record naming it is created with `verified` set to false."

    Design: Difficulty/combinatorial_formula/allocation_round_each_share_then_absorb_negative_remainder
    """
    members, event = _two_eligible_carriers_and_one_draft_event(client)

    allocate_event(client, event)

    allocations = read_allocations(client, event["id"])
    assert_count(allocations, 2, "allocations on the event")
    withdrawn_id = members[2]["id"]
    assert not [
        row for row in allocations if row["member_insurer_id"] == withdrawn_id
    ], "a withdrawn carrier must not receive an allocation"
    assert_cents(
        read_member(client, withdrawn_id)["cumulative_assessed_cents"],
        0,
        "cumulative_assessed_cents",
    )


# ---------------------------------------------------------------------------
# Two adjustments keyed on one pinned intermediate total
# ---------------------------------------------------------------------------


def test_condition_and_improvement_adjustments_both_key_on_the_pre_credit_total(
    foundations: Foundations,
) -> None:
    """607500 less 30375 less 24300 is 552825; chaining would give 554040.

    PRD: "**Improvement credit.** Multiply four percent by the chosen inspection's `cleared_major_count`; if the result exceeds eight percent, use eight percent instead — so clearing two or more major requirements reaches the cap. Multiply the pre-credit premium by that credit percentage and round half up to whole cents."

    PRD: "**Floor.** Take the pre-credit premium, add the signed condition adjustment, and subtract the improvement credit."

    Design: Difficulty/combinatorial_formula/premium_condition_and_improvement_both_keyed_on_pre_credit_total
    """
    chain = _cleared_major_requirement(foundations)

    inspection = read_inspection(foundations.client, chain.inspection_id)
    assert_field_equals(inspection, "cleared_major_count", 1)
    assert_field_equals(inspection, "open_requirement_count", 0)

    policy = bind(chain)

    assert_cents(policy["base_premium_cents"], 607_500, "base_premium_cents")
    assert_cents(policy["cat_surcharge_cents"], 0, "cat_surcharge_cents")
    assert_cents(
        policy["annual_premium_cents"],
        CREDITED_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )
    assert_field_equals(policy, "condition_score_at_bind", 72)


def test_commission_is_credited_on_the_improvement_credited_premium(
    foundations: Foundations,
) -> None:
    """Ten percent of 552825 rounds half up to 55283, and the ledger agrees.

    PRD: "The catastrophe concentration surcharge is never commissionable, so commissionable premium is the policy's `annual_premium_cents` less its `cat_surcharge_cents`. Multiply that by the producer's `commission_rate_bps`, divide by 10,000, and round half up to whole cents; the result is written to the policy's `commission_credited_cents`."

    PRD: "A producer's `ytd_commission_cents` is a conserved quantity recomputed after every credit and every return: it is the sum, over **all** policies whose `producer_id` is that producer, of `commission_credited_cents` minus `commission_returned_cents`."

    Design: Difficulty/combinatorial_formula/premium_condition_and_improvement_both_keyed_on_pre_credit_total
    """
    chain = _cleared_major_requirement(foundations)

    policy = bind(chain)

    assert_cents(
        policy["commission_credited_cents"],
        CREDITED_COMMISSION_CENTS,
        "commission_credited_cents",
    )
    producer = read_producer(foundations.client, foundations.producer_id)
    assert_cents(
        producer["ytd_commission_cents"],
        CREDITED_COMMISSION_CENTS,
        "ytd_commission_cents",
    )
