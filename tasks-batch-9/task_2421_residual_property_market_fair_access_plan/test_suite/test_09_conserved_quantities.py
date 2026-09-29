"""Aggregates driven up and then compensated back to their starting value.

Three different conserved quantities are exercised: money on an agent's ledger,
exposure and derived posture on a territory, and assessment liability spread
across three carriers at once. In each case the reversal must undo every derived
field it touched, not merely the headline total.
"""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_date_equals,
    assert_field_equals,
    assert_ratio,
    find_one,
)
from test_helpers.constants import (
    ALLOCATION_STATUS_ABATED,
    ALLOCATION_STATUS_PENDING,
    BASIS_MARKET_SHARE,
    CANCEL_REASON_PLAN_INITIATED,
    CLOCK_BASE_DATE,
    CONSTRUCTION_MASONRY,
    COVERAGE_STATUS_CANCELLED,
    EVENT_STATUS_CANCELLED,
    ZONE_STATUS_OPEN,
    ZONE_STATUS_RESTRICTED,
)
from test_helpers.api_client import FairPlanApiClient
from test_helpers.fixtures import (
    ApplicationChain,
    Foundations,
    bind_exposure,
    build_allocated_event,
    build_in_force_policy,
    cancel_policy,
    create_member_insurers,
    create_zone,
    pin_clock,
    read_allocations,
    read_event,
    read_member,
    read_producer,
    read_zone,
)
from test_helpers.test_users import admin_headers

TERM_ANNUAL_PREMIUM_CENTS = 577_125
COMMISSION_CREDITED_CENTS = 57_713
DAY_ZERO_UNEARNED_PREMIUM_CENTS = 577_125
DAY_ZERO_FEE_CENTS = 17_314
DAY_ZERO_REFUND_CENTS = 559_811

RESTRICTING_LIMIT_CENTS = 85_000_000
RESTRICTING_ANNUAL_PREMIUM_CENTS = 688_500
HARDENED_CONDITION_SCORE = 88

TRIGGER_LOSS_CENTS = 200_000_001
RESERVE_BALANCE_CENTS = 100_000_000
ASSESSABLE_AMOUNT_CENTS = 100_000_001
FIRST_SHARE_CENTS = 30_000_000
SECOND_SHARE_CENTS = 30_000_000
THIRD_SHARE_CENTS = 40_000_001
CANCELLATION_REASON = "loss estimate revised below reserves"


def _in_force_policy_with_a_credited_ledger(
    foundations: Foundations,
) -> ApplicationChain:
    """One bind has credited the agent's only commission; nothing else has."""
    chain = build_in_force_policy(foundations.client, foundations)
    producer = read_producer(foundations.client, foundations.producer_id)
    assert_cents(
        producer["ytd_commission_cents"],
        COMMISSION_CREDITED_CENTS,
        "ytd_commission_cents",
    )
    return chain


def _territory_pushed_to_the_restricted_rung(
    foundations: Foundations,
) -> ApplicationChain:
    """An 85,000,000 bind lifts the territory from OPEN to exactly RESTRICTED."""
    chain = bind_exposure(
        foundations.client,
        foundations,
        dwelling_limit_cents=RESTRICTING_LIMIT_CENTS,
        address_line="1 Shore Rd",
        construction_type=CONSTRUCTION_MASONRY,
        observed_condition_score=HARDENED_CONDITION_SCORE,
    )
    zone = read_zone(foundations.client, foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"],
        RESTRICTING_LIMIT_CENTS,
        "aggregate_insured_value_cents",
    )
    assert_ratio(zone["concentration_ratio"], "0.8500", "concentration_ratio")
    assert_field_equals(zone, "status", ZONE_STATUS_RESTRICTED)
    return chain


def _allocated_liability_across_three_carriers(client: FairPlanApiClient) -> tuple:
    """Three carriers each carrying their share of a 100,000,001 assessment."""
    pin_clock(client)
    members = create_member_insurers(client)
    zone = create_zone(client)
    event = build_allocated_event(
        client,
        zone["id"],
        TRIGGER_LOSS_CENTS,
        RESERVE_BALANCE_CENTS,
        BASIS_MARKET_SHARE,
    )
    assert_cents(
        event["assessable_amount_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "assessable_amount_cents",
    )
    assert_cents(
        read_member(client, members[2]["id"])["cumulative_assessed_cents"],
        THIRD_SHARE_CENTS,
        "cumulative_assessed_cents",
    )
    return members, event


# ---------------------------------------------------------------------------
# Money on the producer's ledger
# ---------------------------------------------------------------------------


def test_day_zero_cancellation_returns_the_whole_commission(
    roomy_foundations: Foundations,
) -> None:
    """The claw-back is the full credit, so the conserved ledger lands back on zero.

    PRD: "On early termination the same unearned fraction used by the refund calculation is applied to the amount originally credited: multiply the policy's `commission_credited_cents` by that unearned fraction, round half up to whole cents, and write the result to `commission_returned_cents`."

    PRD: "Cancelled and taken-out policies stay in that sum with their returned amounts, which is exactly what keeps the identity exact."

    Design: Difficulty/compensating_invariant/producer_commission_ledger_returns_to_zero_after_day_zero_cancellation
    """
    chain = _in_force_policy_with_a_credited_ledger(roomy_foundations)

    policy = cancel_policy(chain, CANCEL_REASON_PLAN_INITIATED, CLOCK_BASE_DATE)

    assert_cents(
        policy["commission_credited_cents"],
        COMMISSION_CREDITED_CENTS,
        "commission_credited_cents",
    )
    assert_cents(
        policy["commission_returned_cents"],
        COMMISSION_CREDITED_CENTS,
        "commission_returned_cents",
    )
    producer = read_producer(roomy_foundations.client, roomy_foundations.producer_id)
    assert_cents(producer["ytd_commission_cents"], 0, "ytd_commission_cents")


def test_day_zero_cancellation_refunds_the_whole_term_less_the_fee(
    roomy_foundations: Foundations,
) -> None:
    """Cancelling on the effective date leaves the unearned fraction at one.

    PRD: "Subtract that count from three hundred sixty-five, treat a negative result as zero, and divide by three hundred sixty-five; that quotient is the unearned fraction, and it equals one when the cancellation date is the effective date itself."

    PRD: "The fee is then chosen from `unearned_premium_cents` — never from the refund it is subtracted from."

    Design: Difficulty/compensating_invariant/producer_commission_ledger_returns_to_zero_after_day_zero_cancellation
    """
    chain = _in_force_policy_with_a_credited_ledger(roomy_foundations)

    policy = cancel_policy(chain, CANCEL_REASON_PLAN_INITIATED, CLOCK_BASE_DATE)

    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_CANCELLED)
    assert_field_equals(policy, "cancel_reason", CANCEL_REASON_PLAN_INITIATED)
    assert_date_equals(policy["cancellation_date"], CLOCK_BASE_DATE, "cancellation_date")
    assert_cents(
        policy["annual_premium_cents"],
        TERM_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )
    assert_cents(
        policy["unearned_premium_cents"],
        DAY_ZERO_UNEARNED_PREMIUM_CENTS,
        "unearned_premium_cents",
    )
    assert_cents(
        policy["cancellation_fee_cents"], DAY_ZERO_FEE_CENTS, "cancellation_fee_cents"
    )
    assert_cents(policy["refund_cents"], DAY_ZERO_REFUND_CENTS, "refund_cents")


# ---------------------------------------------------------------------------
# Exposure and derived posture on the territory
# ---------------------------------------------------------------------------


def test_cancellation_walks_the_territory_ladder_back_down_to_open(
    foundations: Foundations,
) -> None:
    """Releasing the exposure must restore the aggregate, the ratio and the posture.

    PRD: "Any operation that adds a policy to the `BOUND`-or-`IN_FORCE` set, and any operation that removes one from it, recomputes the aggregate, recomputes the ratio, re-derives the status, and increments the territory's `version` by one."

    PRD: "A territory that had climbed to `CLOSED` therefore descends back through `RESTRICTED` to `OPEN` as cancellations, expirations and take-outs release exposure."

    Design: Difficulty/compensating_invariant/zone_exposure_aggregate_returns_to_zero_and_status_reverts_to_open
    """
    chain = _territory_pushed_to_the_restricted_rung(foundations)

    cancel_policy(chain, CANCEL_REASON_PLAN_INITIATED, CLOCK_BASE_DATE)

    zone = read_zone(foundations.client, foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"], 0, "aggregate_insured_value_cents"
    )
    assert_ratio(zone["concentration_ratio"], "0.0000", "concentration_ratio")
    assert_field_equals(zone, "status", ZONE_STATUS_OPEN)


def test_released_policy_keeps_the_exposure_it_carried(
    foundations: Foundations,
) -> None:
    """The cancelled policy retains its own legs while the territory is restored.

    PRD: "A cancellation therefore writes `cancel_reason`, `cancellation_date`, `unearned_premium_cents`, `cancellation_fee_cents` and `refund_cents`; writes `commission_returned_cents` and decrements the producer's `ytd_commission_cents` by the same amount; then, on a second hop, releases the policy's `exposure_value_cents` from the territory's `aggregate_insured_value_cents` and recomputes `concentration_ratio`; then, on a third hop, re-derives the territory's `status` from the fallen ratio — walking back down from `CLOSED` through `RESTRICTED` to `OPEN` as headroom returns — and increments the territory's `version` by one."

    PRD: "From that sum the plan derives `concentration_ratio`, the aggregate insured value divided by the exposure cap, rounded half up to four decimals."

    Design: Difficulty/compensating_invariant/zone_exposure_aggregate_returns_to_zero_and_status_reverts_to_open
    """
    chain = _territory_pushed_to_the_restricted_rung(foundations)

    policy = cancel_policy(chain, CANCEL_REASON_PLAN_INITIATED, CLOCK_BASE_DATE)

    assert_cents(
        policy["exposure_value_cents"], RESTRICTING_LIMIT_CENTS, "exposure_value_cents"
    )
    assert_cents(
        policy["annual_premium_cents"],
        RESTRICTING_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )
    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_CANCELLED)


# ---------------------------------------------------------------------------
# Assessment liability across three carriers
# ---------------------------------------------------------------------------


def test_event_cancellation_abates_every_pending_allocation(
    client: FairPlanApiClient,
) -> None:
    """The rows survive with their amounts, but the event's total is forced to zero.

    PRD: "From `ALLOCATED` it additionally moves every allocation whose `status` is `PENDING` to `ABATED`, decreases each affected member's `cumulative_assessed_cents` by that allocation's `net_due_cents` — restoring the pre-event value — increments each affected member's `version` by one, and writes `allocated_total_cents` back to 0 alongside the reason."

    PRD: "An administrator may cancel an assessment from `DRAFT`, `ALLOCATED` or `INVOICED`, supplying a `reason` that is stored as `cancellation_reason`."

    Design: Difficulty/compensating_invariant/member_assessment_liability_reverts_to_zero_when_event_is_cancelled
    """
    members, event = _allocated_liability_across_three_carriers(client)

    response = client.cancel_assessment(
        event["id"],
        f.assessment_cancellation_payload(CANCELLATION_REASON),
        admin_headers(),
    )
    assert response.status_code == 200, response.text

    cancelled = read_event(client, event["id"])
    assert_field_equals(cancelled, "status", EVENT_STATUS_CANCELLED)
    assert_cents(
        cancelled["assessable_amount_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "assessable_amount_cents",
    )
    assert_cents(cancelled["allocated_total_cents"], 0, "allocated_total_cents")
    assert_field_equals(cancelled, "cancellation_reason", CANCELLATION_REASON)

    allocations = read_allocations(client, event["id"])
    assert_count(
        [row for row in allocations if row["status"] == ALLOCATION_STATUS_ABATED],
        3,
        "abated allocations",
    )
    assert_count(
        [row for row in allocations if row["status"] == ALLOCATION_STATUS_PENDING],
        0,
        "pending allocations",
    )
    assert_cents(
        find_one(allocations, "member_insurer_id", members[2]["id"])[
            "gross_share_cents"
        ],
        THIRD_SHARE_CENTS,
        "gross_share_cents",
    )


def test_event_cancellation_clears_all_three_carriers_liability(
    client: FairPlanApiClient,
) -> None:
    """Every carrier's cumulative figure returns to its pre-event value of zero.

    PRD: "A member's `cumulative_assessed_cents` is always the sum of `net_due_cents` over that member's allocations whose `status` is `PENDING` or `PAID`, and an event's `allocated_total_cents` is the sum of `gross_share_cents` over its allocations whose `status` is not `ABATED` — a figure that must equal `assessable_amount_cents` for as long as the event sits in `ALLOCATED`, `INVOICED` or `SETTLED`."

    PRD: "Whenever an allocation moves `PENDING → ABATED`, the owning member's `cumulative_assessed_cents` falls by that allocation's `net_due_cents` and the allocation's `version` increments by one."

    Design: Difficulty/compensating_invariant/member_assessment_liability_reverts_to_zero_when_event_is_cancelled
    """
    members, event = _allocated_liability_across_three_carriers(client)
    allocations = read_allocations(client, event["id"])
    assert_cents(
        find_one(allocations, "member_insurer_id", members[0]["id"])[
            "gross_share_cents"
        ],
        FIRST_SHARE_CENTS,
        "gross_share_cents",
    )
    assert_cents(
        find_one(allocations, "member_insurer_id", members[1]["id"])[
            "gross_share_cents"
        ],
        SECOND_SHARE_CENTS,
        "gross_share_cents",
    )

    response = client.cancel_assessment(
        event["id"],
        f.assessment_cancellation_payload(CANCELLATION_REASON),
        admin_headers(),
    )
    assert response.status_code == 200, response.text

    for member in members:
        record = read_member(client, member["id"])
        assert_cents(
            record["cumulative_assessed_cents"], 0, "cumulative_assessed_cents"
        )
        assert_field_equals(record, "takeout_credit_count", 0)
