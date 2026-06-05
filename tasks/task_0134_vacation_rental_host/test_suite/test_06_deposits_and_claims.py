"""Security deposits and damage claims: the approve waterfall cascade, the
dispute cycle, the approve-then-deny conservation invariant, the waterfall cap,
the zero-amount guard, and the cross-entity claim-blocks-payout gate.

Covers difficulty rules transitive_cascade (claim approve half),
non_linear_state_machine (dispute cycle half), compensating_invariant (deposit
conservation half), cross_entity_state_dependency (payout-release-blocked half),
plus corner calculations / validations claim instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_host_headers, make_guest_headers, admin_headers,
    setup_filed_claim, setup_under_review_claim, setup_approved_claim,
    setup_in_stay_booking, set_clock, file_claim,
)


# ==========================================================================
# Difficulty: transitive_cascade (claim approve three-hop)
# ==========================================================================
def test_claim_approve_debits_and_settles_deposit(api):
    """PRD §3.7: "The deposit's `held_cents` is then set to its `authorized_cents`
    minus the total of all approved amounts including this one — equivalently,
    the deposit is debited by this claim's `approved_cents`. If no other
    non-terminal claim remains on the deposit after this approval, the deposit
    moves to `SETTLED`."

    Design: Difficulty/transitive_cascade/claim_approve_three_hop_cascade
    """
    ctx = setup_under_review_claim(amount_cents=6000, deposit_cents=10000)
    host, claim, deposit = ctx["host"], ctx["claim"], ctx["deposit"]
    resp = api.approve_claim(claim["id"], headers=admin_headers())
    after = validate_success(resp)
    assert after["approved_cents"] == 6000, \
        f"approved_cents should be 6000, got {after['approved_cents']}"
    dep = validate_success(api.get_security_deposit(deposit["id"], headers=make_host_headers(host["id"])))
    assert dep["held_cents"] == 4000, f"10000-6000=4000 held_cents, got {dep['held_cents']}"
    assert dep["status"] == "SETTLED", f"deposit should SETTLE, got {dep['status']}"


def test_claim_approve_status_transition(api):
    """PRD §3.7: "From `UNDER_REVIEW` the admin may approve or deny."
    PRD §3.7: "The claim moves to `APPROVED` and its `version` increments."

    Second test of the approve cascade: pins the claim's own terminal status.

    Design: Difficulty/transitive_cascade/claim_approve_three_hop_cascade
    """
    ctx = setup_under_review_claim(amount_cents=6000, deposit_cents=10000)
    claim = ctx["claim"]
    resp = api.approve_claim(claim["id"], headers=admin_headers())
    after = validate_success(resp)
    assert after["status"] == "APPROVED", f"claim should be APPROVED, got {after['status']}"


# ==========================================================================
# Difficulty: non_linear_state_machine (dispute cycle)
# ==========================================================================
def test_dispute_cycle_under_review_to_disputed(api):
    """PRD §3.7: "A guest may dispute a claim. Disputing a claim that is
    `UNDER_REVIEW` moves it to `DISPUTED`."

    Design: Difficulty/non_linear_state_machine/damage_claim_dispute_cycle
    """
    ctx = setup_under_review_claim(amount_cents=5000, deposit_cents=10000)
    guest, claim = ctx["guest"], ctx["claim"]
    resp = api.dispute_claim(claim["id"], headers=make_guest_headers(guest["id"]))
    after = validate_success(resp)
    assert after["status"] == "DISPUTED", f"claim should be DISPUTED, got {after['status']}"


def test_dispute_cycle_disputed_back_to_under_review(api):
    """PRD §3.7: "From `DISPUTED`, the admin reviews the claim again, returning it
    to `UNDER_REVIEW`."

    Second test of the dispute cycle: the return hop back into review.

    Design: Difficulty/non_linear_state_machine/damage_claim_dispute_cycle
    """
    ctx = setup_under_review_claim(amount_cents=5000, deposit_cents=10000)
    guest, claim = ctx["guest"], ctx["claim"]
    api.dispute_claim(claim["id"], headers=make_guest_headers(guest["id"]))
    resp = api.review_claim(claim["id"], headers=admin_headers())
    after = validate_success(resp)
    assert after["status"] == "UNDER_REVIEW", \
        f"re-reviewed disputed claim should be UNDER_REVIEW, got {after['status']}"


# ==========================================================================
# Difficulty: compensating_invariant (approve-then-deny conserves balance)
# ==========================================================================
def test_approve_debits_then_deny_restores_balance(api):
    """PRD §3.7: "When the admin denies a claim from `UNDER_REVIEW`, if the claim
    had previously been approved (its `approved_cents` is greater than zero, the
    situation that arises after an approve-then-dispute cycle), the deposit's
    `held_cents` is increased by that `approved_cents` to restore the earlier
    debit so the deposit balance is conserved; the claim's `approved_cents` is
    then reset to 0."

    Design: Difficulty/compensating_invariant/claim_approve_then_deny_conserves_deposit_balance
    """
    ctx = setup_approved_claim(amount_cents=6000, deposit_cents=10000)
    host, guest, claim, deposit = ctx["host"], ctx["guest"], ctx["claim"], ctx["deposit"]
    # After approve, held_cents debited 10000 -> 4000.
    assert deposit["held_cents"] == 4000, \
        f"post-approve held_cents should be 4000, got {deposit['held_cents']}"
    # Guest disputes the APPROVED claim, admin re-reviews, then denies.
    api.dispute_claim(claim["id"], headers=make_guest_headers(guest["id"]))
    api.review_claim(claim["id"], headers=admin_headers())
    api.deny_claim(claim["id"], headers=admin_headers())
    dep = validate_success(api.get_security_deposit(deposit["id"], headers=make_host_headers(host["id"])))
    assert dep["held_cents"] == 10000, \
        f"deny should restore held_cents to 10000 (== authorized), got {dep['held_cents']}"


def test_deny_resets_approved_cents_to_zero(api):
    """PRD §3.7: "the claim's `approved_cents` is then reset to 0."
    PRD §3.7: "The claim moves to the terminal `DENIED` and its `version`
    increments."

    Second test of the conservation invariant: the denied claim's own residue.

    Design: Difficulty/compensating_invariant/claim_approve_then_deny_conserves_deposit_balance
    """
    ctx = setup_approved_claim(amount_cents=6000, deposit_cents=10000)
    guest, claim = ctx["guest"], ctx["claim"]
    api.dispute_claim(claim["id"], headers=make_guest_headers(guest["id"]))
    api.review_claim(claim["id"], headers=admin_headers())
    resp = api.deny_claim(claim["id"], headers=admin_headers())
    after = validate_success(resp)
    assert after["status"] == "DENIED", f"claim should be DENIED, got {after['status']}"
    assert after["approved_cents"] == 0, \
        f"denied claim approved_cents should reset to 0, got {after['approved_cents']}"


# ==========================================================================
# Difficulty: cross_entity_state_dependency (payout release blocked by claim)
# ==========================================================================
def test_payout_release_blocked_by_open_claim(api):
    """PRD §3.8: "And a cross-entity gate applies — if any damage claim on the
    booking's deposit is in `FILED`, `UNDER_REVIEW`, or `DISPUTED`, the release
    is blocked with `ERR_CLAIM_BLOCKS_PAYOUT` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/payout_release_blocked_by_open_claim
    """
    # Build a due payout (clock past release_after) with an UNDER_REVIEW claim.
    ctx = setup_under_review_claim(
        amount_cents=5000, deposit_cents=10000,
        in_stay_clock="2026-07-10T12:00:00Z", claim_clock="2026-07-11T00:00:00Z")
    host, booking = ctx["host"], ctx["booking"]
    # Complete the stay (after check_out) so the payout is otherwise due.
    set_clock("2026-07-15T00:00:00Z")
    api.complete_booking(booking["id"], headers=make_host_headers(host["id"]))
    payout = ctx["payout"]
    resp = api.release_payout(payout["id"], headers=admin_headers())
    validate_error(resp, ApiErrorId.ERR_CLAIM_BLOCKS_PAYOUT.value)
    pay = validate_success(api.get_payout(payout["id"], headers=make_host_headers(host["id"])))
    assert pay["status"] == "SCHEDULED", f"blocked payout should stay SCHEDULED, got {pay['status']}"


def test_payout_release_blocked_status_unchanged_for_filed_claim(api):
    """PRD §3.8: "if any damage claim on the booking's deposit is in `FILED`,
    `UNDER_REVIEW`, or `DISPUTED`, the release is blocked with
    `ERR_CLAIM_BLOCKS_PAYOUT` (HTTP 409)."

    Second test of the cross-entity gate: the FILED-claim branch (not yet
    reviewed) blocks release just the same.

    Design: Difficulty/cross_entity_state_dependency/payout_release_blocked_by_open_claim
    """
    ctx = setup_filed_claim(
        amount_cents=5000, deposit_cents=10000,
        in_stay_clock="2026-07-10T12:00:00Z", claim_clock="2026-07-11T00:00:00Z")
    host, booking, payout = ctx["host"], ctx["booking"], ctx["payout"]
    set_clock("2026-07-15T00:00:00Z")
    api.complete_booking(booking["id"], headers=make_host_headers(host["id"]))
    resp = api.release_payout(payout["id"], headers=admin_headers())
    validate_error(resp, ApiErrorId.ERR_CLAIM_BLOCKS_PAYOUT.value)


# ==========================================================================
# Corner: validations / claim amount
# ==========================================================================
def test_claim_zero_amount_rejected(api):
    """PRD §3.7: "The `amount_cents` must be strictly greater than zero and the
    deposit's `authorized_cents` must be strictly greater than zero; otherwise
    the filing is rejected with `ERR_INVALID_CLAIM_AMOUNT` (HTTP 422)."

    Design: Corner/validations/claim_zero_amount_rejected
    """
    ctx = setup_in_stay_booking(
        listing_overrides={"security_deposit_cents": 10000, "payout_delay_days": 1},
        check_in_clock="2026-07-10T12:00:00Z")
    host, deposit = ctx["host"], ctx["deposit"]
    set_clock("2026-07-11T00:00:00Z")
    from test_helpers import create_claim_payload
    resp = api.file_claim(
        deposit["id"], create_claim_payload(deposit["id"], 0, reason="Nothing"),
        headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_AMOUNT.value)
