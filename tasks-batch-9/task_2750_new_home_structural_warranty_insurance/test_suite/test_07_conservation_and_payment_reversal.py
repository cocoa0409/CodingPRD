"""Compensating movements: what a payment reversal restores, and what it does not.

A reversal is the only compensating movement in the ledger, and it is held to a
strict standard: it must put both conserved quantities back exactly where they
were, without also undoing the consequences that other rows already suffered
while the capacity was gone. These tests measure the same world before the
payment, after the payment and after the reversal, so a reversal implemented as
an approximate adjustment — or as a full rollback — cannot pass.
"""

import pytest

from test_helpers import (
    CANONICAL_PREMIUM_CENTS,
    add_endorsement_term,
    adjudicate_claim,
    assert_claim_money_conserved,
    assert_coverage_capacity_conserved,
    assert_loss_monitor,
    assert_reserve_entry,
    file_claim,
    investigate_claim,
    latest_payment_entry_id,
    pay_claim,
    read_claim,
    read_coverage_term,
    read_loss_monitor,
    read_reserve_entries,
    reverse_payment,
    route_claim,
    set_clock,
    setup_active_policy,
    setup_approved_claim,
    validate_paginated,
)

# A claim of 1,000,000 cents fully substantiated and not designated structural:
# gross 1,000,000, deductible 100,000, provisional net 900,000, betterment at
# 5 percent 45,000, net payable 855,000.
NET_PAYABLE_CENTS = 855_000
PAYMENT_CENTS = 300_000
# 855,000 / 363,894 rounded half up to four decimal places.
LOSS_RATIO_WITH_ONE_CLAIM = 2.3496


# --------------------------------------------------------------------------
# The claim money identity: reserve + paid + released == incurred authorized
# --------------------------------------------------------------------------
def test_payment_and_its_reversal_leave_all_four_claim_money_fields_untouched(api):
    """PRD §2.9: "The claim ledger maintains a hard invariant that must hold
    after **every** request that touches it: a claim's `reserve_cents` plus its
    `paid_cents` plus its `released_cents` always equals its
    `incurred_authorized_cents`."
    PRD §2.9: "A reversal subtracts the reversed amount from `paid_cents` and
    adds it back to `reserve_cents`, again leaving `incurred_authorized_cents`
    untouched — so a payment followed by its reversal is a complete no-op on all
    four fields."
    PRD §3.8: "A payment followed by its reversal is therefore an exact no-op on
    all four claim money fields and on both term capacity fields."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_the_claim_incurred_identity_exactly
    """
    scenario = setup_approved_claim(claimed_amount_cents=1_000_000)
    claim_id = scenario["claim"]["id"]
    term_id = scenario["claim"]["coverage_term_id"]

    before = read_claim(claim_id)
    term_before = read_coverage_term(term_id)
    assert before["net_payable_cents"] == NET_PAYABLE_CENTS, (
        f"expected a net payable of {NET_PAYABLE_CENTS}, "
        f"got {before['net_payable_cents']}"
    )
    assert before["reserve_cents"] == NET_PAYABLE_CENTS
    assert before["paid_cents"] == 0
    assert before["released_cents"] == 0
    assert before["incurred_authorized_cents"] == NET_PAYABLE_CENTS
    assert_claim_money_conserved(before)

    pay_claim(claim_id, PAYMENT_CENTS)
    during = read_claim(claim_id)
    assert during["paid_cents"] == PAYMENT_CENTS
    assert during["reserve_cents"] == NET_PAYABLE_CENTS - PAYMENT_CENTS
    assert during["released_cents"] == 0
    assert during["incurred_authorized_cents"] == NET_PAYABLE_CENTS, (
        "a disbursement leaves incurred_authorized_cents untouched"
    )
    assert during["status"] == "APPROVED", (
        "a part payment does not close the claim, got " f"{during['status']}"
    )
    assert_claim_money_conserved(during)
    term_during = read_coverage_term(term_id)
    assert term_during["consumed_limit_cents"] == PAYMENT_CENTS
    assert term_during["remaining_limit_cents"] == (
        term_before["remaining_limit_cents"] - PAYMENT_CENTS
    )
    assert_coverage_capacity_conserved(term_during)

    reverse_payment(claim_id, latest_payment_entry_id(claim_id))
    after = read_claim(claim_id)
    assert after["paid_cents"] == 0, f"paid must return to 0, got {after['paid_cents']}"
    assert after["reserve_cents"] == NET_PAYABLE_CENTS, (
        f"reserve must return to {NET_PAYABLE_CENTS}, got {after['reserve_cents']}"
    )
    assert after["released_cents"] == 0, (
        "a reversal is not a release, so released_cents must stay at 0, got "
        f"{after['released_cents']}"
    )
    assert after["incurred_authorized_cents"] == NET_PAYABLE_CENTS
    assert_claim_money_conserved(after)
    assert after["status"] == "APPROVED"

    term_after = read_coverage_term(term_id)
    assert term_after["consumed_limit_cents"] == term_before["consumed_limit_cents"]
    assert term_after["remaining_limit_cents"] == term_before["remaining_limit_cents"]
    assert term_after["limit_cents"] == term_before["limit_cents"], (
        "limit_cents is immutable once the term exists"
    )
    assert_coverage_capacity_conserved(term_after)


def test_reversal_is_journalled_as_a_reversal_and_moves_no_incurred_loss(
        api, claims_adjuster_headers):
    """PRD §3.8: "On success a journal row of `entry_type` `PAYMENT_REVERSAL` is
    appended with its `reversed_entry_id` naming the undone payment."
    PRD §3.8: "Every movement — authorisation, disbursement, reversal, release —
    appends one row, and each row records the `claim_id` it belongs to, its
    `entry_type`, the `amount_cents` of the movement as a positive magnitude of
    at least 1, an optional `memo` note explaining it, the
    `recorded_by_user_id` of whoever caused it, and two balance stamps:
    `balance_after_reserve_cents` and `balance_after_paid_cents`, capturing the
    claim's `reserve_cents` and `paid_cents` immediately after the entry was
    applied."
    PRD §3.2: "The numerator, `incurred_loss_cents`, is the sum of
    `reserve_cents` plus `paid_cents` over every claim filed against any policy
    of this builder whose `obligor` is `INSURER`, with **no claim-status filter
    whatsoever** — closed claims count exactly as open ones do."

    Because the identity is restored exactly and nothing is released, the
    builder's incurred loss is the same figure at all three observation points.

    Design: Difficulty/compensating_invariant/payment_reversal_restores_the_claim_incurred_identity_exactly
    """
    scenario = setup_approved_claim(claimed_amount_cents=1_000_000)
    claim_id = scenario["claim"]["id"]
    builder_id = scenario["builder"]["id"]

    monitor_before = read_loss_monitor(builder_id)
    assert_loss_monitor(monitor_before)
    assert monitor_before["earned_premium_cents"] == CANONICAL_PREMIUM_CENTS
    assert monitor_before["incurred_loss_cents"] == NET_PAYABLE_CENTS
    assert monitor_before["loss_ratio"] == pytest.approx(
        LOSS_RATIO_WITH_ONE_CLAIM, abs=1e-9)

    pay_claim(claim_id, PAYMENT_CENTS)
    payment_entry_id = latest_payment_entry_id(claim_id)
    monitor_during = read_loss_monitor(builder_id)
    assert monitor_during["incurred_loss_cents"] == NET_PAYABLE_CENTS, (
        "moving reserve into paid does not change the numerator, got "
        f"{monitor_during['incurred_loss_cents']}"
    )

    reverse_payment(claim_id, payment_entry_id,
                    memo="duplicate disbursement withdrawn")
    reversal_rows = read_reserve_entries(claim_id, entry_type="PAYMENT_REVERSAL")
    assert len(reversal_rows) == 1, (
        f"exactly one reversal row must be appended, got {len(reversal_rows)}"
    )
    reversal_entry = reversal_rows[0]
    assert_reserve_entry(reversal_entry)
    assert reversal_entry["claim_id"] == claim_id
    assert reversal_entry["entry_type"] == "PAYMENT_REVERSAL", (
        f"expected PAYMENT_REVERSAL, got {reversal_entry['entry_type']}"
    )
    assert reversal_entry["amount_cents"] == PAYMENT_CENTS, (
        "a reversal is always full, never partial"
    )
    assert reversal_entry["reversed_entry_id"] == payment_entry_id
    assert reversal_entry["balance_after_reserve_cents"] == NET_PAYABLE_CENTS
    assert reversal_entry["balance_after_paid_cents"] == 0

    entries, meta = validate_paginated(
        api.list_reserve_entries(claims_adjuster_headers,
                                 {"claim_id": claim_id, "limit": 100})
    )
    assert meta["total_count"] == 2, (
        "the journal carries the payment and its reversal and nothing else, got "
        f"{meta['total_count']}"
    )
    assert [entry["entry_type"] for entry in entries] == ["PAYMENT",
                                                          "PAYMENT_REVERSAL"], (
        f"expected the journal oldest first, got {[e['entry_type'] for e in entries]}"
    )
    assert not read_reserve_entries(claim_id, entry_type="RELEASE"), (
        "a reversal must not be journalled as a release"
    )

    monitor_after = read_loss_monitor(builder_id)
    assert monitor_after["incurred_loss_cents"] == NET_PAYABLE_CENTS
    assert monitor_after["loss_ratio"] == pytest.approx(
        LOSS_RATIO_WITH_ONE_CLAIM, abs=1e-9), (
        f"the loss ratio must be unmoved, got {monitor_after['loss_ratio']}"
    )
    assert monitor_after["monitoring_posture"] == monitor_before["monitoring_posture"]


# --------------------------------------------------------------------------
# The capacity identity: restoring a term without resurrecting its casualties
# --------------------------------------------------------------------------
ENDORSEMENT_LIMIT_CENTS = 2_000_000
HALF_LIMIT_CENTS = 1_000_000
EXHAUSTION_CLAIM_INSTANT = "2028-09-15T00:00:00Z"
# Two claims of 3,000,000 cents each: gross 3,000,000, deductible 100,000,
# provisional net 2,900,000, betterment at 8 percent 232,000, and step 7 caps
# the result at the term's whole remaining capacity of 2,000,000.
EXHAUSTION_NET_PAYABLE_CENTS = 2_000_000
# After both disbursements: the suspended sibling contributes 0 + 1,000,000 and
# the paying claim 1,000,000 + 1,000,000; 3,000,000 / 363,894 to four places.
INCURRED_LOSS_AFTER_EXHAUSTION_CENTS = 3_000_000
LOSS_RATIO_AFTER_EXHAUSTION = 8.2442
INCURRED_LOSS_BEFORE_ANY_PAYMENT_CENTS = 4_000_000


def _exhausted_endorsement_world():
    """One ACTIVE home carrying a workmanship endorsement term of 2,000,000
    cents, two claims approved against that one term, and two disbursements of
    1,000,000 cents that together drive its capacity to exactly zero.

    The second disbursement exhausts the term and the cascade therefore
    suspends the first claim, which is the sibling a later reversal must not
    bring back.
    """
    scenario = setup_active_policy()
    policy_id = scenario["policy"]["id"]
    owner_id = scenario["homeowner"]["id"]
    endorsement = add_endorsement_term(
        policy_id, coverage_type="WORKMANSHIP", start_date="2028-09-01",
        end_date="2030-08-31", limit_cents=ENDORSEMENT_LIMIT_CENTS,
        deductible_cents=100_000,
    )
    set_clock(EXHAUSTION_CLAIM_INSTANT)

    claims = []
    for description in ("Cabinet run out of plumb along the north wall",
                        "Trim separation throughout the upper hallway"):
        claim = file_claim(
            policy_id, owner_id, coverage_type="WORKMANSHIP",
            defect_category="WORKMANSHIP_DEFECT",
            claimed_amount_cents=3_000_000, damage_description=description,
        )
        investigate_claim(claim["id"], 1.00)
        route_claim(claim["id"])
        adjudicate_claim(claim["id"], "APPROVE")
        claims.append(read_claim(claim["id"]))

    sibling, paying = claims
    for claim in claims:
        assert claim["coverage_term_id"] == endorsement["id"], (
            "both claims must resolve to the endorsement term"
        )
        assert claim["net_payable_cents"] == EXHAUSTION_NET_PAYABLE_CENTS, (
            f"expected a net payable of {EXHAUSTION_NET_PAYABLE_CENTS}, "
            f"got {claim['net_payable_cents']}"
        )

    monitor = read_loss_monitor(scenario["builder"]["id"])
    assert monitor["incurred_loss_cents"] == INCURRED_LOSS_BEFORE_ANY_PAYMENT_CENTS, (
        "both reserves must be standing before any money moves, got "
        f"{monitor['incurred_loss_cents']}"
    )

    pay_claim(sibling["id"], HALF_LIMIT_CENTS)
    pay_claim(paying["id"], HALF_LIMIT_CENTS)
    return {
        "builder_id": scenario["builder"]["id"],
        "endorsement_id": endorsement["id"],
        "sibling_id": sibling["id"],
        "paying_id": paying["id"],
    }


def test_reversal_restores_the_exhausted_term_and_reopens_it(api):
    """PRD §2.9: "A parallel but distinct invariant governs coverage capacity: a
    coverage term's `remaining_limit_cents` plus its `consumed_limit_cents`
    always equals its `limit_cents`."
    PRD §3.8: "The reversed amount is subtracted from the claim's `paid_cents`
    and added back to its `reserve_cents`, leaving `incurred_authorized_cents`
    untouched; and the term is restored, with the amount subtracted from
    `consumed_limit_cents` and added back to `remaining_limit_cents`."
    PRD §3.8: "A reversal that lifts a term's `remaining_limit_cents` above 0
    also transitions that term `LIMIT_EXHAUSTED → OPEN`, advancing the term's
    `version` by 1 — capacity is genuinely available again."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_coverage_term_capacity_without_resurrecting_the_suspended_sibling
    """
    world = _exhausted_endorsement_world()

    term_before = read_coverage_term(world["endorsement_id"])
    assert term_before["status"] == "LIMIT_EXHAUSTED", (
        f"the two disbursements must exhaust the term, got {term_before['status']}"
    )
    assert term_before["consumed_limit_cents"] == ENDORSEMENT_LIMIT_CENTS
    assert term_before["remaining_limit_cents"] == 0
    assert_coverage_capacity_conserved(term_before)

    reverse_payment(world["paying_id"],
                    latest_payment_entry_id(world["paying_id"]),
                    memo="disbursement issued against the wrong claim")

    term_after = read_coverage_term(world["endorsement_id"])
    assert term_after["consumed_limit_cents"] == HALF_LIMIT_CENTS, (
        f"expected {HALF_LIMIT_CENTS} still consumed, "
        f"got {term_after['consumed_limit_cents']}"
    )
    assert term_after["remaining_limit_cents"] == HALF_LIMIT_CENTS, (
        f"expected {HALF_LIMIT_CENTS} available again, "
        f"got {term_after['remaining_limit_cents']}"
    )
    assert term_after["limit_cents"] == ENDORSEMENT_LIMIT_CENTS
    assert_coverage_capacity_conserved(term_after)
    assert term_after["status"] == "OPEN", (
        f"a term with capacity again must reopen, got {term_after['status']}"
    )
    assert term_after["version"] == term_before["version"] + 1, (
        "reopening the term advances its version by exactly 1"
    )

    paying = read_claim(world["paying_id"])
    assert paying["paid_cents"] == 0
    assert paying["reserve_cents"] == EXHAUSTION_NET_PAYABLE_CENTS
    assert paying["released_cents"] == 0
    assert paying["incurred_authorized_cents"] == EXHAUSTION_NET_PAYABLE_CENTS
    assert_claim_money_conserved(paying)
    assert paying["status"] == "APPROVED", (
        f"the reversed claim stays authorised, got {paying['status']}"
    )


def test_reversal_does_not_resurrect_the_sibling_suspended_for_no_limit(api):
    """PRD §3.8: "But **claims already moved to `SUSPENDED_NO_LIMIT` are not
    resurrected**: that state is terminal, and the compensating transition on
    the term does not reach back into it."
    PRD §3.8: "Every *other* claim bound to that same coverage term whose
    `status` is `UNDER_INVESTIGATION`, `BUILDER_OBLIGATION_NOTICE`,
    `INSURER_ADJUDICATION` or `APPROVED` transitions to the terminal
    `SUSPENDED_NO_LIMIT`; on each such claim the whole of its `reserve_cents` is
    added to its `released_cents` and its `reserve_cents` is set to 0, leaving
    its `incurred_authorized_cents` unchanged, and a journal row of `entry_type`
    `RELEASE` for the released amount is appended to that claim's journal when
    the released amount is at least 1 cent."
    PRD §3.2: "A claim's `released_cents` never enters the numerator, which is
    why releasing a reserve lowers a builder's incurred loss."

    The asymmetry: the term's capacity comes back, but the sibling's released
    reserve does not, so the builder's incurred loss stays where the cascade
    left it instead of returning to its pre-payment figure.

    Design: Difficulty/compensating_invariant/payment_reversal_restores_coverage_term_capacity_without_resurrecting_the_suspended_sibling
    """
    world = _exhausted_endorsement_world()

    sibling_before = read_claim(world["sibling_id"])
    assert sibling_before["status"] == "SUSPENDED_NO_LIMIT", (
        "the cascade must have suspended the sibling, got "
        f"{sibling_before['status']}"
    )
    assert sibling_before["reserve_cents"] == 0
    assert sibling_before["released_cents"] == HALF_LIMIT_CENTS
    assert sibling_before["paid_cents"] == HALF_LIMIT_CENTS
    assert sibling_before["incurred_authorized_cents"] == EXHAUSTION_NET_PAYABLE_CENTS
    assert_claim_money_conserved(sibling_before)

    reverse_payment(world["paying_id"],
                    latest_payment_entry_id(world["paying_id"]),
                    memo="disbursement issued against the wrong claim")

    sibling_after = read_claim(world["sibling_id"])
    assert sibling_after["status"] == "SUSPENDED_NO_LIMIT", (
        f"SUSPENDED_NO_LIMIT is terminal, got {sibling_after['status']}"
    )
    assert sibling_after["reserve_cents"] == 0, (
        "the released reserve must not be handed back, got "
        f"{sibling_after['reserve_cents']}"
    )
    assert sibling_after["released_cents"] == HALF_LIMIT_CENTS
    assert sibling_after["paid_cents"] == HALF_LIMIT_CENTS
    assert sibling_after["incurred_authorized_cents"] == EXHAUSTION_NET_PAYABLE_CENTS
    assert sibling_after["version"] == sibling_before["version"], (
        "the reversal must not touch the sibling at all"
    )
    assert_claim_money_conserved(sibling_after)

    monitor = read_loss_monitor(world["builder_id"])
    assert_loss_monitor(monitor)
    assert monitor["earned_premium_cents"] == CANONICAL_PREMIUM_CENTS
    assert monitor["incurred_loss_cents"] == INCURRED_LOSS_AFTER_EXHAUSTION_CENTS, (
        "the sibling's released reserve stays out of the numerator, got "
        f"{monitor['incurred_loss_cents']}"
    )
    assert monitor["incurred_loss_cents"] != INCURRED_LOSS_BEFORE_ANY_PAYMENT_CENTS, (
        "a reversal must not restore the pre-payment incurred loss"
    )
    assert monitor["loss_ratio"] == pytest.approx(
        LOSS_RATIO_AFTER_EXHAUSTION, abs=1e-9), (
        f"expected {LOSS_RATIO_AFTER_EXHAUSTION}, got {monitor['loss_ratio']}"
    )
    assert monitor["open_claim_count"] == 1, (
        "the suspended sibling is terminal and no longer counts as open, got "
        f"{monitor['open_claim_count']}"
    )
