"""Single requests whose effects travel three and four hops deep.

Each chain here is strictly sequential: every hop exists only because the hop
before it happened, so an assertion on the last record in the chain is an
assertion that the whole chain fired in order.
"""

from typing import Tuple

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_date_equals,
    assert_field_equals,
    assert_instant_equals,
    assert_ratio,
    find_one,
)
from test_helpers.constants import (
    ALLOCATION_STATUS_PAID,
    APP_STATUS_APPROVED_TO_BIND,
    BASIS_MARKET_SHARE,
    CANCEL_REASON_TAKEOUT_ELECTION,
    CONSTRUCTION_MASONRY,
    COVERAGE_STATUS_TAKEN_OUT,
    DEPOP_STATUS_ELECTED_TAKEOUT,
    ELECTION_ACCEPT,
    EVENT_STATUS_SETTLED,
    INSPECTION_RESULT_PASS,
    INSPECTION_RESULT_PASS_WITH_CONDITIONS,
    OFFER_STATUS_ACCEPTED,
    REQUIREMENT_STATUS_CLEARED,
    ZONE_STATUS_OPEN,
    ZONE_STATUS_RESTRICTED,
)
from test_helpers.fixtures import (
    ApplicationChain,
    Foundations,
    bind_exposure,
    build_inspection_pending_application,
    build_invoiced_event,
    complete_inspection,
    create_offer,
    elect_offer,
    pay_allocation,
    pin_clock,
    read_allocations,
    read_event,
    read_inspection,
    read_member,
    read_producer,
    read_requirements,
    read_zone,
)
from test_helpers.test_users import inspector_headers

ELECTION_CLOCK = "2026-10-15T00:00:00Z"
ELECTION_DATE = "2026-10-15"
TAKEN_OUT_ANNUAL_PREMIUM_CENTS = 688_500
TAKEN_OUT_COMMISSION_CREDITED_CENTS = 68_850
UNEARNED_PREMIUM_CENTS = 605_503
COMMISSION_RETURNED_CENTS = 60_550
RESIDUAL_YTD_COMMISSION_CENTS = 8_300

ASSESSABLE_AMOUNT_CENTS = 10_000_000
FIRST_CARRIER_GROSS_CENTS = 3_000_000
FIRST_CARRIER_CREDIT_CENTS = 500_000
FIRST_CARRIER_NET_CENTS = 2_500_000
SECOND_CARRIER_NET_CENTS = 3_000_000
THIRD_CARRIER_NET_CENTS = 4_000_000

CLEARED_AT = "2026-09-01T00:00:00Z"
REQUIREMENT_DUE_AT = "2026-10-16T00:00:00Z"
BIND_DEADLINE_AT = "2026-10-01T00:00:00Z"


def _restricted_zone_policy(foundations: Foundations) -> ApplicationChain:
    """An in-force 85,000,000 masonry policy that leaves the zone RESTRICTED."""
    return bind_exposure(
        foundations.client,
        foundations,
        dwelling_limit_cents=85_000_000,
        address_line="1 Shore Rd",
        construction_type=CONSTRUCTION_MASONRY,
        condition_score=88,
        observed_condition_score=88,
        replacement_cost_cents=100_000_000,
    )


def _accepted_takeout(foundations: Foundations) -> Tuple[ApplicationChain, dict]:
    """Carrier One takes the risk out on day forty-four of the term."""
    chain = _restricted_zone_policy(foundations)
    offer = create_offer(chain, member_index=0, offered_premium_cents=700_000)
    pin_clock(foundations.client, ELECTION_CLOCK)
    accepted = elect_offer(chain, offer["id"], ELECTION_ACCEPT)
    return chain, accepted


def _settled_assessment(foundations: Foundations) -> Tuple[dict, list]:
    """After the take-out, one invoiced event is paid off carrier by carrier."""
    client = foundations.client
    _chain, _accepted = _accepted_takeout(foundations)
    event = build_invoiced_event(
        client, foundations.zone_id, 60_000_000, 50_000_000, BASIS_MARKET_SHARE
    )
    allocations = read_allocations(client, event["id"])
    ordered = [
        find_one(allocations, "member_insurer_id", member["id"])
        for member in foundations.members
    ]
    for allocation in ordered[:-1]:
        pay_allocation(client, allocation)
    pay_allocation(client, ordered[-1])
    return event, ordered


def _requirement_awaiting_clearance(
    foundations: Foundations,
) -> Tuple[ApplicationChain, dict]:
    """One MAJOR requirement with the producer's evidence already filed."""
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
    return chain, requirement


# ---------------------------------------------------------------------------
# Acceptance of a take-out offer, four hops
# ---------------------------------------------------------------------------


def test_acceptance_grants_the_credit_and_ends_coverage_on_both_dimensions(
    foundations: Foundations,
) -> None:
    """Hop one stamps the offer, hop two flips both policy dimensions.

    PRD: "`ACCEPT` moves the offer `OUTSTANDING → ACCEPTED`, writing `elected_at` to the current logical clock and `credit_units_granted` to 1, and incrementing the offer's `version`."

    PRD: "On the next hop the offering carrier's `takeout_credit_count` rises by the granted credit units and the carrier's `version` increments by one — this is how a carrier earns the depopulation credits it can later offset against an assessment."

    Design: Difficulty/transitive_cascade/takeout_acceptance_cascades_four_hops_to_zone_reopening
    """
    _chain, accepted = _accepted_takeout(foundations)

    assert_field_equals(accepted, "status", OFFER_STATUS_ACCEPTED)
    assert_instant_equals(accepted["elected_at"], ELECTION_CLOCK, "elected_at")
    assert_field_equals(accepted, "credit_units_granted", 1)
    assert_field_equals(
        read_member(foundations.client, foundations.members[0]["id"]),
        "takeout_credit_count",
        1,
    )


def test_acceptance_refunds_pro_rata_with_no_fee_and_claws_commission_back(
    foundations: Foundations,
) -> None:
    """Forty-four days in force leaves 605503 unearned and 60550 clawed back.

    PRD: "On the coverage branch of the same request the policy moves `IN_FORCE → TAKEN_OUT` and `OFFER_OUTSTANDING → ELECTED_TAKEOUT`, with `cancel_reason` written to `TAKEOUT_ELECTION`, `cancellation_date` written to the current clock date, `unearned_premium_cents` computed under the `PRO_RATA` variant, `cancellation_fee_cents` forced to 0 and `refund_cents` therefore equal to the full unearned premium."

    PRD: "Under the `PRO_RATA` variant — which applies when `cancel_reason` is `PLAN_INITIATED` or `TAKEOUT_ELECTION` — the policy's `annual_premium_cents` is multiplied by the unearned fraction and rounded half up to whole cents to give `unearned_premium_cents`."

    PRD: "On early termination the same unearned fraction used by the refund calculation is applied to the amount originally credited: multiply the policy's `commission_credited_cents` by that unearned fraction, round half up to whole cents, and write the result to `commission_returned_cents`."

    Design: Difficulty/transitive_cascade/takeout_acceptance_cascades_four_hops_to_zone_reopening
    """
    chain, _accepted = _accepted_takeout(foundations)

    policy = chain.refresh_policy()
    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_TAKEN_OUT)
    assert_field_equals(policy, "depopulation_status", DEPOP_STATUS_ELECTED_TAKEOUT)
    assert_field_equals(policy, "cancel_reason", CANCEL_REASON_TAKEOUT_ELECTION)
    assert_date_equals(policy["cancellation_date"], ELECTION_DATE, "cancellation_date")
    assert_cents(
        policy["annual_premium_cents"],
        TAKEN_OUT_ANNUAL_PREMIUM_CENTS,
        "annual_premium_cents",
    )
    assert_cents(
        policy["unearned_premium_cents"], UNEARNED_PREMIUM_CENTS, "unearned_premium_cents"
    )
    assert_cents(policy["cancellation_fee_cents"], 0, "cancellation_fee_cents")
    assert_cents(policy["refund_cents"], UNEARNED_PREMIUM_CENTS, "refund_cents")
    assert_cents(
        policy["commission_credited_cents"],
        TAKEN_OUT_COMMISSION_CREDITED_CENTS,
        "commission_credited_cents",
    )
    assert_cents(
        policy["commission_returned_cents"],
        COMMISSION_RETURNED_CENTS,
        "commission_returned_cents",
    )
    assert_cents(
        read_producer(foundations.client, foundations.producer_id)[
            "ytd_commission_cents"
        ],
        RESIDUAL_YTD_COMMISSION_CENTS,
        "ytd_commission_cents",
    )


def test_acceptance_releases_the_exposure_and_reopens_the_territory(
    foundations: Foundations,
) -> None:
    """Hops three and four empty the territory and walk RESTRICTED back to OPEN.

    PRD: "On a third hop the territory's `aggregate_insured_value_cents` drops by the policy's `exposure_value_cents` and its `concentration_ratio` is recomputed; on a fourth hop its `status` is re-derived from the new ratio and its `version` increments by one."

    PRD: "The territory's derived `status` is then read off a three-rung ladder: the status is `CLOSED` when the concentration ratio is at least 1.0000, otherwise `RESTRICTED` when the ratio is at least 0.8500, otherwise `OPEN`."

    Design: Difficulty/transitive_cascade/takeout_acceptance_cascades_four_hops_to_zone_reopening
    """
    client = foundations.client
    chain = _restricted_zone_policy(foundations)

    before = read_zone(client, foundations.zone_id)
    assert_cents(
        before["aggregate_insured_value_cents"],
        85_000_000,
        "aggregate_insured_value_cents",
    )
    assert_field_equals(before, "status", ZONE_STATUS_RESTRICTED)

    offer = create_offer(chain, member_index=0, offered_premium_cents=700_000)
    pin_clock(client, ELECTION_CLOCK)
    elect_offer(chain, offer["id"], ELECTION_ACCEPT)

    after = read_zone(client, foundations.zone_id)
    assert_cents(
        after["aggregate_insured_value_cents"], 0, "aggregate_insured_value_cents"
    )
    assert_ratio(after["concentration_ratio"], "0.0000", "concentration_ratio")
    assert_field_equals(after, "status", ZONE_STATUS_OPEN)


# ---------------------------------------------------------------------------
# Payment of the last pending allocation, three hops
# ---------------------------------------------------------------------------


def test_final_payment_bubbles_the_event_to_settled(
    foundations: Foundations,
) -> None:
    """With no PENDING sibling left, the parent event settles on the same request.

    PRD: "A successful payment moves the allocation `PENDING → PAID`, writes `paid_at` to the current logical clock and increments the allocation's `version` by one."

    PRD: "On a second hop, if no allocation on the event remains in `PENDING`, the event moves `INVOICED → SETTLED` and its `version` increments by one."

    Design: Difficulty/transitive_cascade/final_allocation_payment_cascades_three_hops_to_credit_release
    """
    event, ordered = _settled_assessment(foundations)
    client = foundations.client

    settled = read_event(client, event["id"])
    assert_field_equals(settled, "status", EVENT_STATUS_SETTLED)
    assert_cents(
        settled["assessable_amount_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "assessable_amount_cents",
    )
    assert_cents(
        settled["allocated_total_cents"],
        ASSESSABLE_AMOUNT_CENTS,
        "allocated_total_cents",
    )
    assert_cents(settled["remainder_cents"], 0, "remainder_cents")

    last = find_one(
        read_allocations(client, event["id"]),
        "member_insurer_id",
        ordered[-1]["member_insurer_id"],
    )
    assert_field_equals(last, "status", ALLOCATION_STATUS_PAID)
    assert_cents(last["net_due_cents"], THIRD_CARRIER_NET_CENTS, "net_due_cents")


def test_settlement_releases_the_credit_the_first_carrier_had_consumed(
    foundations: Foundations,
) -> None:
    """The credit earned by the take-out is only spent when the event settles.

    PRD: "On a third hop, triggered by that settlement, **every** allocation on the event has its `credits_consumed` deducted from its own member's `takeout_credit_count`, with each such member's `version` incremented by one — this is the moment the depopulation credits earned back in §3.8 are actually spent."

    PRD: "The number of whole credits actually spent, `credits_consumed`, is `takeout_credit_applied_cents` divided by 500,000 and rounded **down** to a whole number; those credits are not deducted from the member yet — that happens only when the event settles."

    Design: Difficulty/transitive_cascade/final_allocation_payment_cascades_three_hops_to_credit_release
    """
    _event, _ordered = _settled_assessment(foundations)
    client = foundations.client

    first_carrier = read_member(client, foundations.members[0]["id"])
    assert_field_equals(first_carrier, "takeout_credit_count", 0)
    assert_cents(
        first_carrier["cumulative_assessed_cents"],
        FIRST_CARRIER_NET_CENTS,
        "cumulative_assessed_cents",
    )
    assert_cents(
        read_member(client, foundations.members[2]["id"])["cumulative_assessed_cents"],
        THIRD_CARRIER_NET_CENTS,
        "cumulative_assessed_cents",
    )


def test_credit_offset_reduces_only_the_holding_carriers_net_due(
    foundations: Foundations,
) -> None:
    """One held credit takes 500000 off a 3000000 gross share, leaving 2500000.

    PRD: "The offset written to `takeout_credit_applied_cents` is the smaller of two figures: fifty percent of that member's `gross_share_cents`, rounded half up to whole cents, and the member's `takeout_credit_count` multiplied by 500,000 cents."

    PRD: "A credit unit is worth five thousand dollars — 500,000 cents — and a member holds `takeout_credit_count` of them."

    Design: Difficulty/transitive_cascade/final_allocation_payment_cascades_three_hops_to_credit_release
    """
    _event, ordered = _settled_assessment(foundations)

    holder, second, third = ordered
    assert_cents(
        holder["gross_share_cents"], FIRST_CARRIER_GROSS_CENTS, "gross_share_cents"
    )
    assert_cents(
        holder["takeout_credit_applied_cents"],
        FIRST_CARRIER_CREDIT_CENTS,
        "takeout_credit_applied_cents",
    )
    assert_cents(holder["net_due_cents"], FIRST_CARRIER_NET_CENTS, "net_due_cents")
    assert_field_equals(holder, "credits_consumed", 1)
    assert_cents(second["net_due_cents"], SECOND_CARRIER_NET_CENTS, "net_due_cents")
    assert_field_equals(second, "credits_consumed", 0)
    assert_cents(third["net_due_cents"], THIRD_CARRIER_NET_CENTS, "net_due_cents")


# ---------------------------------------------------------------------------
# Clearance of the last open requirement, three hops
# ---------------------------------------------------------------------------


def test_clearance_rederives_the_counters_and_authorises_the_bind(
    foundations: Foundations,
) -> None:
    """Zeroing the open count flips the result to PASS and opens the bind window.

    PRD: "It writes `cleared_at` to the current logical clock and increments the requirement's `version`; then, on a second hop, it decrements the parent inspection's `open_requirement_count` by one and — only when the requirement's `severity` is `MAJOR` — increments the parent's `cleared_major_count` by one, incrementing the inspection's `version`; then, on a third hop, if `open_requirement_count` has reached zero, the inspection's `result` flips `PASS_WITH_CONDITIONS → PASS` and the application cascades `IMPROVEMENTS_REQUIRED → APPROVED_TO_BIND` with `approved_to_bind_at` set to the current logical clock and `bind_deadline_at` set thirty days later."

    PRD: "`cleared_major_count` is the number of child requirements whose `severity` is `MAJOR` and whose `status` is `CLEARED`, and it is the input to the improvement credit in the premium ladder."

    Design: Difficulty/transitive_cascade/requirement_clearance_cascades_three_hops_to_bind_authorization
    """
    client = foundations.client
    chain, requirement = _requirement_awaiting_clearance(foundations)

    clearance = client.clear_requirement(
        requirement["id"], f.requirement_clearance_payload(), inspector_headers()
    )
    assert clearance.status_code == 200, clearance.text

    inspection = read_inspection(client, chain.inspection_id)
    assert_field_equals(inspection, "open_requirement_count", 0)
    assert_field_equals(inspection, "cleared_major_count", 1)
    assert_field_equals(inspection, "result", INSPECTION_RESULT_PASS)

    application = chain.refresh_application()
    assert_field_equals(application, "status", APP_STATUS_APPROVED_TO_BIND)
    assert_instant_equals(
        application["approved_to_bind_at"], CLEARED_AT, "approved_to_bind_at"
    )
    assert_instant_equals(
        application["bind_deadline_at"], BIND_DEADLINE_AT, "bind_deadline_at"
    )


def test_clearance_stamps_the_requirement_without_moving_its_due_date(
    foundations: Foundations,
) -> None:
    """The cleared requirement keeps the forty-five day deadline it was raised with.

    PRD: "The producer who owns the application submits remediation evidence, supplying an `evidence_reference`; the requirement's `status` must be `OPEN`, moving it `OPEN → EVIDENCE_SUBMITTED`, and the parent inspection's `open_requirement_count` is deliberately left unchanged."

    PRD: "Its `evidence_reference`, `cleared_at` and `waiver_reason` are null until the corresponding step writes them."

    Design: Difficulty/transitive_cascade/requirement_clearance_cascades_three_hops_to_bind_authorization
    """
    client = foundations.client
    chain, requirement = _requirement_awaiting_clearance(foundations)
    assert_field_equals(
        read_inspection(client, chain.inspection_id), "open_requirement_count", 1
    )

    clearance = client.clear_requirement(
        requirement["id"], f.requirement_clearance_payload(), inspector_headers()
    )
    assert clearance.status_code == 200, clearance.text

    cleared = read_requirements(client, chain.inspection_id)[0]
    assert_field_equals(cleared, "status", REQUIREMENT_STATUS_CLEARED)
    assert_instant_equals(cleared["cleared_at"], CLEARED_AT, "cleared_at")
    assert_instant_equals(cleared["due_at"], REQUIREMENT_DUE_AT, "due_at")
    assert_field_equals(cleared, "evidence_reference", "ROOF-1")
