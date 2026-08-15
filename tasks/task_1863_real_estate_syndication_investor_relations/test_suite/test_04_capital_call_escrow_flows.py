"""Capital-call pro-rata allocation, escrow receipt/release flows, and the
release cascade into subscriptions and offering totals."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    contribution_for,
    fund_contribution,
    get_capital_call,
    get_contribution,
    get_offering,
    get_subscription,
    issue_capital_call,
    make_investor_headers,
    receive_escrow_payload,
    setup_funded_offering,
    setup_offering_with_approved_subscriptions,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_operator_headers"]


class TestProrataLargestRemainder:
    def test_prorata_rounding_largest_remainder_positive_diff(self, api):
        """PRD §3.4: "The rounding discipline is pinned — every line is first
        rounded half-up to a whole cent individually, and then, if the rounded
        lines do not sum exactly to `total_call_cents`, the difference (which
        can never exceed one cent per eligible subscription in either
        direction) is allocated to the single line with the largest
        `amount_due_cents`, ties broken by the earliest subscription
        `created_at`. This largest-remainder adjustment guarantees the
        contributions sum exactly to the call amount."
        Call of 100,001c over commitments 33,333/33,333/33,334 rounds per-line
        to 33,333+33,333+33,334=100,000, then +1c lands on the largest line.

        Design: Difficulty/combinatorial_formula/capital_call_prorata_largest_remainder_rounding
        """
        ctx = setup_offering_with_approved_subscriptions([33_333, 33_333, 33_334])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        call, contribs = issue_capital_call(syn_id, off_id, 100_001)
        assert call["status"] == "ISSUED"

        sub_a, sub_b, sub_c = ctx["subs"]
        due_a = contribution_for(contribs, sub_a["id"])["amount_due_cents"]
        due_b = contribution_for(contribs, sub_b["id"])["amount_due_cents"]
        due_c = contribution_for(contribs, sub_c["id"])["amount_due_cents"]
        assert due_a == 33_333, f"A due {due_a} != 33333"
        assert due_b == 33_333, f"B due {due_b} != 33333"
        assert due_c == 33_335, (
            f"largest-remainder +1c must land on the largest line (C): "
            f"got {due_c}")
        assert due_a + due_b + due_c == 100_001, (
            "contributions must sum exactly to total_call_cents")

    def test_prorata_rounding_largest_remainder_negative_diff(self, api):
        """PRD §3.4: "if the rounded lines do not sum exactly to
        `total_call_cents`, the difference (which can never exceed one cent per
        eligible subscription in either direction) is allocated to the single
        line with the largest `amount_due_cents`". Call of 100,002c over
        commitments 33,333/33,333/33,334 rounds per-line to
        33,334+33,334+33,335=100,003, so -1c lands on the largest line.

        Design: Difficulty/combinatorial_formula/capital_call_prorata_largest_remainder_rounding
        """
        ctx = setup_offering_with_approved_subscriptions([33_333, 33_333, 33_334])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        call, contribs = issue_capital_call(syn_id, off_id, 100_002)
        assert call["status"] == "ISSUED"

        sub_a, sub_b, sub_c = ctx["subs"]
        due_a = contribution_for(contribs, sub_a["id"])["amount_due_cents"]
        due_b = contribution_for(contribs, sub_b["id"])["amount_due_cents"]
        due_c = contribution_for(contribs, sub_c["id"])["amount_due_cents"]
        assert due_a == 33_334, f"A due {due_a} != 33334"
        assert due_b == 33_334, f"B due {due_b} != 33334"
        assert due_c == 33_334, (
            f"largest-remainder -1c must land on the largest line (C): "
            f"got {due_c}")
        assert due_a + due_b + due_c == 100_002


class TestCapitalCallBubbling:
    def test_partial_then_full_funding_bubbles_call_status(self, api):
        """PRD §3.4: "As soon as at least one contribution on an `ISSUED` call
        has reached `ESCROW_RECEIVED` while at least one sibling remains
        `PENDING` or received-but-not-yet-released, the call itself moves from
        `ISSUED` to `PARTIALLY_FUNDED`." PRD §3.4: "When the last outstanding
        contribution on a call releases, the call bubbles up to
        `FULLY_FUNDED`."

        Design: Difficulty/non_linear_state_machine/capital_call_partial_full_funded_bubbling
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000, 5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub_a, sub_b = ctx["subs"]
        inv_a, inv_b = ctx["investors"]
        call, contribs = issue_capital_call(syn_id, off_id, 10_000_000)
        contrib_a = contribution_for(contribs, sub_a["id"])
        contrib_b = contribution_for(contribs, sub_b["id"])
        assert call["status"] == "ISSUED"

        # First receipt: one ESCROW_RECEIVED, sibling PENDING.
        validate_success(api.receive_escrow(
            syn_id, off_id, call["id"], contrib_a["id"],
            receive_escrow_payload(5_000_000), make_investor_headers(inv_a["id"])))
        call_now = get_capital_call(syn_id, off_id, call["id"])
        assert call_now["status"] == "PARTIALLY_FUNDED", (
            f"after first receipt call must be PARTIALLY_FUNDED, "
            f"got {call_now['status']}")

        # First release with sibling still PENDING: still PARTIALLY_FUNDED.
        validate_success(api.release_escrow(syn_id, off_id, call["id"],
                                            contrib_a["id"], SPONSOR))
        call_now = get_capital_call(syn_id, off_id, call["id"])
        assert call_now["status"] == "PARTIALLY_FUNDED", (
            f"with one contribution still PENDING the call must remain "
            f"PARTIALLY_FUNDED, got {call_now['status']}")

        # Second release: the last outstanding contribution -> FULLY_FUNDED.
        validate_success(api.receive_escrow(
            syn_id, off_id, call["id"], contrib_b["id"],
            receive_escrow_payload(5_000_000), make_investor_headers(inv_b["id"])))
        validate_success(api.release_escrow(syn_id, off_id, call["id"],
                                            contrib_b["id"], SPONSOR))
        call_now = get_capital_call(syn_id, off_id, call["id"])
        assert call_now["status"] == "FULLY_FUNDED"
        assert call_now["escrow_released_cents"] == 10_000_000

    def test_partial_receipt_marks_call_partially_funded(self, api):
        """PRD §3.4: "A valid receipt adds `amount_cents` into
        `amount_received_cents`, stamps `received_at`, and moves the
        contribution from `PENDING` to `ESCROW_RECEIVED` once any money has
        landed." With a sibling still PENDING, that first partial receipt
        already moves the call to PARTIALLY_FUNDED (PRD §3.4, same quote as
        above), and releasing the final outstanding contribution bubbles the
        call to FULLY_FUNDED.

        Design: Difficulty/non_linear_state_machine/capital_call_partial_full_funded_bubbling
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000, 5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub_a, sub_b = ctx["subs"]
        inv_a, inv_b = ctx["investors"]
        call, contribs = issue_capital_call(syn_id, off_id, 10_000_000)
        contrib_a = contribution_for(contribs, sub_a["id"])
        contrib_b = contribution_for(contribs, sub_b["id"])

        # Partial wire of 2,000,000 against a 5,000,000 due.
        validate_success(api.receive_escrow(
            syn_id, off_id, call["id"], contrib_a["id"],
            receive_escrow_payload(2_000_000), make_investor_headers(inv_a["id"])))
        contrib_a_now = get_contribution(syn_id, off_id, call["id"],
                                         contrib_a["id"])
        assert contrib_a_now["status"] == "ESCROW_RECEIVED"
        assert contrib_a_now["amount_received_cents"] == 2_000_000
        assert get_capital_call(syn_id, off_id, call["id"])["status"] == \
            "PARTIALLY_FUNDED"

        # Complete A, release A, then fund B fully: call reaches FULLY_FUNDED.
        validate_success(api.receive_escrow(
            syn_id, off_id, call["id"], contrib_a["id"],
            receive_escrow_payload(3_000_000), make_investor_headers(inv_a["id"])))
        validate_success(api.release_escrow(syn_id, off_id, call["id"],
                                            contrib_a["id"], SPONSOR))
        fund_contribution(syn_id, off_id, call["id"], contrib_b, inv_b)
        call_now = get_capital_call(syn_id, off_id, call["id"])
        assert call_now["status"] == "FULLY_FUNDED"
        assert call_now["escrow_released_cents"] == 10_000_000


class TestReleaseEscrowCascade:
    def test_release_escrow_cascades_to_offering_totals(self, api):
        """PRD §3.4: "Release moves the contribution to `RELEASED` and cascades
        in three directions: the call's `escrow_released_cents` grows by the
        released amount; the subscription's `funded_cents` grows by the same
        amount and, if the subscription was still `AWAITING_FUNDING`, it
        transitions to `FUNDED` with `funded_at` stamped at that moment; and
        the offering's `total_funded_cents` is recomputed as the sum of
        `funded_cents` across all `FUNDED` subscriptions."

        Design: Difficulty/transitive_cascade/release_escrow_cascade_to_offering_totals
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub, inv = ctx["subs"][0], ctx["investors"][0]
        call, contribs = issue_capital_call(syn_id, off_id, 5_000_000)
        contrib = contribution_for(contribs, sub["id"])
        assert get_offering(syn_id, off_id)["total_funded_cents"] == 0

        validate_success(api.receive_escrow(
            syn_id, off_id, call["id"], contrib["id"],
            receive_escrow_payload(5_000_000), make_investor_headers(inv["id"])))
        released = validate_success(api.release_escrow(
            syn_id, off_id, call["id"], contrib["id"], SPONSOR))
        assert released["status"] == "RELEASED"

        sub_now = get_subscription(syn_id, off_id, sub["id"])
        assert sub_now["status"] == "FUNDED"
        assert sub_now["funded_cents"] == 5_000_000
        assert sub_now["funded_at"], "funded_at must be stamped on first release"
        off_now = get_offering(syn_id, off_id)
        assert off_now["total_funded_cents"] == 5_000_000
        call_now = get_capital_call(syn_id, off_id, call["id"])
        assert call_now["escrow_released_cents"] == 5_000_000

    def test_second_release_recomputes_total_funded(self, api):
        """PRD §3.4: "the offering's `total_funded_cents` is recomputed as the
        sum of `funded_cents` across all `FUNDED` subscriptions." Releasing a
        second subscription's escrow grows the aggregate from the first
        subscription's funded amount to the sum of both.

        Design: Difficulty/transitive_cascade/release_escrow_cascade_to_offering_totals
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000, 5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub_a, sub_b = ctx["subs"]
        inv_a, inv_b = ctx["investors"]
        call, contribs = issue_capital_call(syn_id, off_id, 10_000_000)
        contrib_a = contribution_for(contribs, sub_a["id"])
        contrib_b = contribution_for(contribs, sub_b["id"])

        fund_contribution(syn_id, off_id, call["id"], contrib_a, inv_a)
        assert get_offering(syn_id, off_id)["total_funded_cents"] == 5_000_000
        assert get_subscription(syn_id, off_id, sub_a["id"])["status"] == "FUNDED"
        assert get_subscription(syn_id, off_id, sub_b["id"])["status"] == \
            "AWAITING_FUNDING"

        fund_contribution(syn_id, off_id, call["id"], contrib_b, inv_b)
        assert get_offering(syn_id, off_id)["total_funded_cents"] == 10_000_000
        assert get_subscription(syn_id, off_id, sub_b["id"])["status"] == "FUNDED"


class TestContributionReleaseBubbleUp:
    def test_contribution_release_bubble_up_side_effect(self, api):
        """PRD §3.4: "Release moves the contribution to `RELEASED` and cascades
        in three directions: the call's `escrow_released_cents` grows by the
        released amount; the subscription's `funded_cents` grows by the same
        amount and, if the subscription was still `AWAITING_FUNDING`, it
        transitions to `FUNDED` with `funded_at` stamped at that moment; and
        the offering's `total_funded_cents` is recomputed as the sum of
        `funded_cents` across all `FUNDED` subscriptions. When the last
        outstanding contribution on a call releases, the call bubbles up to
        `FULLY_FUNDED`."

        Design: Corner/state_machines/contribution_release_bubble_up_side_effect
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub, inv = ctx["subs"][0], ctx["investors"][0]
        call, contribs = issue_capital_call(syn_id, off_id, 5_000_000)
        contrib = contribution_for(contribs, sub["id"])
        fund_contribution(syn_id, off_id, call["id"], contrib, inv)

        contrib_now = get_contribution(syn_id, off_id, call["id"], contrib["id"])
        assert contrib_now["status"] == "RELEASED"
        sub_now = get_subscription(syn_id, off_id, sub["id"])
        assert sub_now["status"] == "FUNDED"
        assert sub_now["funded_at"], "funded_at must be set after first release"
        assert get_capital_call(syn_id, off_id, call["id"])["status"] == \
            "FULLY_FUNDED"
