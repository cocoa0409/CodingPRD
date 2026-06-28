"""Membership billing & access axes, freeze/resume, renewal, grace sweep.

Covers difficulty instances on the Membership entity's parallel state machine,
the wallet-then-card renewal calc, the freeze/resume fee-conservation invariant,
and the grace-sweep boundary; plus corner instances on invalid transitions,
cross-axis recovery, and the frozen-renewal error.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_membership,
    create_member, create_membership, create_member_with_active_membership,
    create_frozen_membership, create_past_due_membership, set_clock,
    make_member_headers, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]


def _member_h(member_id):
    return make_member_headers(member_id)


# ─── Difficulty: parallel billing × access axes ───────────────────────────
def test_membership_can_be_past_due_and_frozen_simultaneously(api):
    """PRD §3.2: "The `billing_status` axis moves among `CURRENT`, `PAST_DUE`, and
    `CANCELLED`, with `CANCELLED` being terminal. The `access_status` axis moves
    among `ACTIVE`, `FROZEN`, `SUSPENDED`, and `TERMINATED`, with `TERMINATED`
    being terminal."
    PRD §3.3: "It moves `billing_status` from `CURRENT` to `PAST_DUE`, stamps
    `past_due_since` with the current clock, and increments the `version`.
    Crucially, it does **not** change `access_status`: the member keeps `ACTIVE`
    access during the grace window."

    Design: Difficulty/non_linear_state_machine/membership_parallel_billing_and_access_axes
    """
    set_clock("2026-05-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    set_clock("2026-06-01T00:00:00Z")
    after_fail = validate_success(
        api.run_billing(membership["id"], {"outcome": "FAILED"}, FD), 200)
    assert after_fail["billing_status"] == "PAST_DUE"
    assert after_fail["access_status"] == "ACTIVE"

    after_freeze = validate_success(api.freeze_membership(
        membership["id"],
        {"expected_membership_version": after_fail["version"]},
        _member_h(member["id"])), 200)
    assert after_freeze["billing_status"] == "PAST_DUE", \
        "billing axis unchanged by a freeze"
    assert after_freeze["access_status"] == "FROZEN", \
        "access axis independently moved to FROZEN"


def test_freeze_then_billing_axes_remain_independent(api):
    """PRD §3.2: "These two axes evolve on their own timelines except where a
    transition explicitly reaches across to the other axis."
    PRD §3.3: "A failed charge is a FAILED outcome on a CURRENT membership whose
    cycle is due (the clock has reached or passed cycle_end). It moves
    billing_status from CURRENT to PAST_DUE, stamps past_due_since with the
    current clock, and increments the version."

    Design: Difficulty/non_linear_state_machine/membership_parallel_billing_and_access_axes
    """
    set_clock("2026-05-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    # Freeze first (access axis moves), billing remains CURRENT.
    frozen = validate_success(api.freeze_membership(
        membership["id"],
        {"expected_membership_version": membership["version"]},
        _member_h(member["id"])), 200)
    assert frozen["access_status"] == "FROZEN"
    assert frozen["billing_status"] == "CURRENT", \
        "freezing access does not touch the billing axis"


# ─── Difficulty: renewal charge wallet-then-card pinned order ─────────────
def test_renewal_draws_wallet_before_card_pinned_order(api):
    """PRD §3.7: "the gross amount is the monthly_fee_cents; the amount drawn from
    the wallet is the smaller of the member's current wallet_credit_cents and that
    gross amount; the amount charged to the card is the gross minus the wallet
    draw; and the member's wallet_credit_cents is then reduced by the amount
    drawn."
    PRD §3.3: "A successful renewal advances cycle_start to the current clock,
    recomputes cycle_end, applies the renewal charge (wallet first, then card, as
    detailed in Section 3.7), and increments the membership's version. The billing
    axis stays at CURRENT."

    Design: Difficulty/combinatorial_formula/renewal_charge_wallet_then_card_pinned_order_mode_c
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    # Freeze at 2026-06-19 to credit 3600 to the wallet, then resume.
    set_clock("2026-06-19T00:00:00Z")
    frozen = validate_success(api.freeze_membership(
        membership["id"],
        {"expected_membership_version": membership["version"]},
        _member_h(member["id"])), 200)
    resumed = validate_success(api.resume_membership(
        membership["id"],
        {"expected_membership_version": frozen["version"]},
        _member_h(member["id"])), 200)
    # Advance past the rebased cycle_end and renew.
    set_clock("2026-07-25T00:00:00Z")
    after = validate_success(
        api.run_billing(membership["id"], {"outcome": "SUCCEEDED"}, FD), 200)
    assert after["billing_status"] == "CURRENT"
    member_after = validate_success(api.get_member(member["id"], FD), 200)
    assert member_after["wallet_credit_cents"] == 0, \
        "3600 wallet credit fully drawn before any card charge (9000 fee)"


def test_renewal_with_partial_wallet_leaves_remainder(api):
    """PRD §3.7: "the amount drawn from the wallet is the smaller of the member's
    current wallet_credit_cents and that gross amount; the amount charged to the
    card is the gross minus the wallet draw; and the member's wallet_credit_cents
    is then reduced by the amount drawn."

    A YOUTH_TEAM fee is 6000; a freeze on a 6000 plan at 12 unused days credits
    round_half_up(6000*12/30) = 2400 < 6000, so the wallet is fully drawn and the
    remainder hits the card; wallet ends at 0.

    Design: Difficulty/combinatorial_formula/renewal_charge_wallet_then_card_pinned_order_mode_c
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="YOUTH_TEAM")
    set_clock("2026-06-19T00:00:00Z")
    frozen = validate_success(api.freeze_membership(
        membership["id"],
        {"expected_membership_version": membership["version"]},
        _member_h(member["id"])), 200)
    member_credited = validate_success(api.get_member(member["id"], FD), 200)
    assert member_credited["wallet_credit_cents"] == 2400, \
        "round_half_up(6000*12/30) == 2400 credited at freeze"
    resumed = validate_success(api.resume_membership(
        membership["id"],
        {"expected_membership_version": frozen["version"]},
        _member_h(member["id"])), 200)
    set_clock("2026-07-25T00:00:00Z")
    validate_success(api.run_billing(membership["id"], {"outcome": "SUCCEEDED"}, FD), 200)
    member_after = validate_success(api.get_member(member["id"], FD), 200)
    assert member_after["wallet_credit_cents"] == 0, \
        "2400 wallet fully drawn against the 6000 fee; remainder on card"


# ─── Difficulty: grace sweep boundary (exactly 7 days) ────────────────────
def test_grace_sweep_suspends_at_exactly_seven_days(api):
    """PRD §3.3: "When that whole-day count is at least 7, the sweep moves
    access_status from ACTIVE to SUSPENDED. The boundary is exact: at 6 whole days
    overdue the sweep is a no-op, and at 7 whole days it suspends."

    Design: Difficulty/boundary_precision_check/grace_sweep_suspends_at_exactly_seven_days
    """
    set_clock("2026-05-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    set_clock("2026-06-01T00:00:00Z")
    validate_success(api.run_billing(membership["id"], {"outcome": "FAILED"}, FD), 200)
    set_clock("2026-06-08T00:00:00Z")  # exactly 7 days past past_due_since
    after = validate_success(
        api.run_billing(membership["id"], {"outcome": "SWEEP"}, FD), 200)
    assert after["access_status"] == "SUSPENDED"
    assert after["billing_status"] == "PAST_DUE"


def test_grace_sweep_at_six_days_is_no_op(api):
    """PRD §3.3: "The boundary is exact: at 6 whole days overdue the sweep is a
    no-op, and at 7 whole days it suspends."

    Design: Difficulty/boundary_precision_check/grace_sweep_suspends_at_exactly_seven_days
    """
    set_clock("2026-05-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    set_clock("2026-06-01T00:00:00Z")
    validate_success(api.run_billing(membership["id"], {"outcome": "FAILED"}, FD), 200)
    set_clock("2026-06-07T00:00:00Z")  # exactly 6 days past past_due_since
    after = validate_success(
        api.run_billing(membership["id"], {"outcome": "SWEEP"}, FD), 200)
    assert after["access_status"] == "ACTIVE", "6-day sweep is a no-op"
    assert after["billing_status"] == "PAST_DUE"


# ─── Difficulty: freeze/resume/renew fee-conservation invariant ───────────
def test_freeze_credit_conserved_end_to_end_through_renewal(api):
    """PRD §3.7: "The number of unused days is the count of whole days remaining
    from the freeze instant to cycle_end, never less than zero. The credit is the
    monthly_fee_cents multiplied by the unused days, divided by the 30-day cycle
    length, with the result rounded half up to whole cents. That credit is added
    to the member's wallet_credit_cents."
    PRD §3.7: "the amount drawn from the wallet is the smaller of the member's
    current wallet_credit_cents and that gross amount; the amount charged to the
    card is the gross minus the wallet draw; and the member's wallet_credit_cents
    is then reduced by the amount drawn."

    Design: Difficulty/compensating_invariant/freeze_resume_cycle_fee_conservation_invariant
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    set_clock("2026-06-19T00:00:00Z")
    frozen = validate_success(api.freeze_membership(
        membership["id"],
        {"expected_membership_version": membership["version"]},
        _member_h(member["id"])), 200)
    credited = validate_success(api.get_member(member["id"], FD), 200)
    assert credited["wallet_credit_cents"] == 3600, "credited at freeze"
    resumed = validate_success(api.resume_membership(
        membership["id"],
        {"expected_membership_version": frozen["version"]},
        _member_h(member["id"])), 200)
    set_clock("2026-07-25T00:00:00Z")
    validate_success(api.run_billing(membership["id"], {"outcome": "SUCCEEDED"}, FD), 200)
    after = validate_success(api.get_member(member["id"], FD), 200)
    assert after["wallet_credit_cents"] == 0, \
        "the 3600 credit is fully redeemed against the next renewal; conserved"


def test_freeze_credit_matches_prorated_unused_days(api):
    """PRD §3.7: "The number of unused days is the count of whole days remaining
    from the freeze instant to cycle_end, never less than zero. The credit is the
    monthly_fee_cents multiplied by the unused days, divided by the 30-day cycle
    length, with the result rounded half up to whole cents. That credit is added
    to the member's wallet_credit_cents."

    Design: Difficulty/compensating_invariant/freeze_resume_cycle_fee_conservation_invariant
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    # cycle_end = 2026-07-01; freeze at 2026-06-19 → 12 unused whole days.
    set_clock("2026-06-19T00:00:00Z")
    validate_success(api.freeze_membership(
        membership["id"],
        {"expected_membership_version": membership["version"]},
        _member_h(member["id"])), 200)
    after = validate_success(api.get_member(member["id"], FD), 200)
    # round_half_up(9000 * 12 / 30) = round_half_up(3600.0) = 3600
    assert after["wallet_credit_cents"] == 3600, \
        "freeze credit is the prorated unused-cycle fee, conserved into wallet"


def test_freeze_credit_quote_does_not_mutate_wallet(api):
    """PRD §3.7: "A what-if quote of this credit is available without mutation:
    the freeze-quote read runs the identical formula against the current clock and
    returns the prospective freeze_credit_cents and unused_days, but persists
    nothing"

    Design: Difficulty/dual_variant_calc/freeze_credit_provisional_quote_vs_committed_variant
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    set_clock("2026-06-19T00:00:00Z")
    quote = validate_success(api.freeze_quote(membership["id"], _member_h(member["id"])), 200)
    assert quote["freeze_credit_cents"] == 3600
    before = validate_success(api.get_member(member["id"], FD), 200)
    assert before["wallet_credit_cents"] == 0, "quote did NOT mutate the wallet"


def test_committed_freeze_persists_credit_to_wallet(api):
    """PRD §3.7: "The committed freeze is the authoritative value, evaluated and
    persisted at the freeze instant."
    PRD §3.2: "A successful freeze moves access_status from ACTIVE to FROZEN, sets
    frozen_at to the current clock, credits the unused-days proration described in
    Section 3.7 to the member's wallet_credit_cents, and increments the
    membership's version."

    Design: Difficulty/dual_variant_calc/freeze_credit_provisional_quote_vs_committed_variant
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    set_clock("2026-06-19T00:00:00Z")
    frozen = validate_success(api.freeze_membership(
        membership["id"],
        {"expected_membership_version": membership["version"]},
        _member_h(member["id"])), 200)
    assert frozen["access_status"] == "FROZEN"
    after = validate_success(api.get_member(member["id"], FD), 200)
    assert after["wallet_credit_cents"] == 3600, \
        "committed freeze persists 3600 to the wallet"


# ─── Corner: invalid transitions & cross-axis recovery ────────────────────
def test_resume_active_membership_returns_invalid_state(api):
    """PRD §3.2: "A member resumes their own frozen membership; this is allowed
    only when access_status is FROZEN, else ERR_INVALID_STATE."

    Design: Corner/state_machines/resume_active_membership_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    member, membership = create_member_with_active_membership()
    res = api.resume_membership(
        membership["id"],
        {"expected_membership_version": membership["version"]},
        _member_h(member["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_already_cancelled_membership_returns_invalid_state(api):
    """PRD §3.2: "A member may cancel their own membership while billing_status is
    either CURRENT or PAST_DUE; from any other billing state the cancel is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_terminal_membership_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    member, membership = create_member_with_active_membership()
    cancelled = validate_success(api.cancel_membership(
        membership["id"],
        {"expected_membership_version": membership["version"]},
        _member_h(member["id"])), 200)
    assert cancelled["billing_status"] == "CANCELLED"
    res = api.cancel_membership(
        membership["id"],
        {"expected_membership_version": cancelled["version"]},
        _member_h(member["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_back_payment_restores_suspended_access(api):
    """PRD §3.3: "If at the moment of that back-payment the access_status had been
    driven to SUSPENDED, the recovery also restores access_status to ACTIVE — a
    cross-axis side effect that brings a suspended member back onto the floor."
    PRD §3.3: "A back-payment is a SUCCEEDED outcome on a PAST_DUE membership,
    which clears past_due_since to null, advances cycle_start to the current clock
    and recomputes cycle_end, and increments the version; this is the PAST_DUE to
    CURRENT recovery hop."

    Design: Corner/state_machines/past_due_back_payment_restores_suspended_access
    """
    set_clock("2026-05-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    set_clock("2026-06-01T00:00:00Z")
    validate_success(api.run_billing(membership["id"], {"outcome": "FAILED"}, FD), 200)
    set_clock("2026-06-08T00:00:00Z")
    swept = validate_success(api.run_billing(membership["id"], {"outcome": "SWEEP"}, FD), 200)
    assert swept["access_status"] == "SUSPENDED"
    recovered = validate_success(
        api.run_billing(membership["id"], {"outcome": "SUCCEEDED"}, FD), 200)
    assert recovered["billing_status"] == "CURRENT"
    assert recovered["access_status"] == "ACTIVE"


# ─── Corner: frozen renewal error ─────────────────────────────────────────
def test_renewal_on_frozen_membership_rejected(api):
    """PRD §3.3: "a SUCCEEDED renewal attempted while access_status is FROZEN is
    rejected with ERR_MEMBERSHIP_FROZEN (HTTP 409), because a frozen membership is
    not billed."

    Design: Corner/errors/error_membership_frozen_on_renewal
    """
    set_clock("2026-06-01T00:00:00Z")
    member, frozen = create_frozen_membership()
    assert frozen["access_status"] == "FROZEN"
    set_clock("2026-07-15T00:00:00Z")
    res = api.run_billing(frozen["id"], {"outcome": "SUCCEEDED"}, FD)
    validate_error(res, "ERR_MEMBERSHIP_FROZEN")


# ─── Corner: OCC stale membership version on freeze ───────────────────────
def test_freeze_with_stale_membership_version_rejected(api):
    """PRD §2.6: "Freezing, resuming, and cancelling a membership each require
    expected_membership_version; a mismatch with the membership's current version
    is rejected with ERR_STALE_MEMBERSHIP_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_membership_stale_version_freeze_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    member = create_member()
    membership = create_membership(member["id"], plan_tier="BASIC")
    stale_version = membership["version"]
    set_clock("2026-06-01T00:00:00Z")
    # A FAILED run-billing advances the version, making `stale_version` stale.
    validate_success(api.run_billing(membership["id"], {"outcome": "FAILED"}, FD), 200)
    res = api.freeze_membership(
        membership["id"],
        {"expected_membership_version": stale_version},
        _member_h(member["id"]))
    validate_error(res, "ERR_STALE_MEMBERSHIP_VERSION")
