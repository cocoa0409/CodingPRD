"""Insurance policies and Tow-Assist contracts — PRD §3.2.

Covers policy lifecycle (ACTIVE → CANCELLED, ACTIVE → EXPIRED via
ops-sweep cascade), tow contract creation (BASIC/PREMIUM tow counts),
and dependency-blocked policy cancellation.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to_iso,
    approve_reservation,
    assert_insurance_policy,
    assert_tow_assist_contract,
    cancel_policy,
    create_active_policy,
    create_boater,
    create_marina,
    create_tow_contract,
    create_vessel,
    get_policy,
    make_boater_headers,
    run_ops,
    setup_approved_reservation,
    setup_draft_reservation,
    validate_error,
)


# ===========================================================================
# InsurancePolicy create + ACTIVE on create — PRD §3.2
# ===========================================================================
class TestInsurancePolicyCreate:

    def test_new_policy_is_active(self, api, dock_master_headers):
        """PRD §3.2: "New policies enter `ACTIVE`.\""""
        marina = create_marina()
        boater = create_boater(marina["id"])
        policy = create_active_policy(marina["id"], boater)
        assert policy["status"] == "ACTIVE", (
            f"New policy.status must be ACTIVE, got {policy['status']!r}"
        )
        assert_insurance_policy(policy)


# ===========================================================================
# Policy expiry cascade via ops/run — PRD §3.2 / §2.7
# ===========================================================================
class TestPolicyExpiryCascade:

    def test_policy_expires_after_clock_past_expiration(
        self, api, dock_master_headers,
    ):
        """PRD §3.2: "The ops sweep transitions any `ACTIVE` policy
        whose `expiration_date` has been reached or passed by the
        marina clock to `EXPIRED`..."

        Claim: clock advances past expiration_date, run ops, policy
        transitions ACTIVE → EXPIRED."""
        marina = create_marina()
        boater = create_boater(marina["id"])
        policy = create_active_policy(
            marina["id"], boater,
            effective_date="2024-01-01T00:00:00.000Z",
            expiration_date="2024-06-01T00:00:00.000Z",
        )
        advance_clock_to_iso(marina["id"], "2024-06-02T00:00:00.000Z")
        run_ops(marina["id"])
        refreshed = get_policy(marina["id"], policy["id"])
        assert refreshed["status"] == "EXPIRED", (
            f"After ops/run with clock past expiration_date, policy "
            f"must be EXPIRED, got {refreshed['status']!r}"
        )


# ===========================================================================
# Policy cancel — PRD §3.2
# ===========================================================================
class TestPolicyCancel:

    def test_cancel_active_policy_without_dependencies(
        self, api, dock_master_headers,
    ):
        """PRD §3.2: "A boater may also cancel an `ACTIVE` policy
        explicitly, transitioning it to `CANCELLED`..."

        Claim: cancel an ACTIVE policy with no APPROVED/CHECKED_IN
        reservation referencing it → CANCELLED."""
        marina = create_marina()
        boater = create_boater(marina["id"])
        policy = create_active_policy(marina["id"], boater)
        result = cancel_policy(marina["id"], boater, policy["id"])
        assert result["status"] == "CANCELLED", (
            f"After cancel, policy.status must be CANCELLED, got "
            f"{result['status']!r}"
        )

    def test_cancel_policy_blocked_by_approved_reservation(
        self, api, dock_master_headers,
    ):
        """PRD §3.2: "this cancellation is rejected with
        `ERR_HAS_DEPENDENCIES` if any reservation referencing the
        policy is currently in `APPROVED` or `CHECKED_IN`."

        Claim: attempting to cancel a policy that is referenced by an
        APPROVED reservation → ERR_HAS_DEPENDENCIES."""
        scenario = setup_approved_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
            liveaboard=False,
            slip_liveaboard_allowed=False,
        )
        h = make_boater_headers(scenario["boater"]["id"])
        resp = api.cancel_policy(
            scenario["marina"]["id"], scenario["policy"]["id"], h,
        )
        validate_error(resp, ApiErrorId.ERR_HAS_DEPENDENCIES.value)


# ===========================================================================
# TowAssistContract — PRD §3.2 / §3.8
# ===========================================================================
class TestTowContractCreate:

    def test_basic_contract_starts_with_two_tows(
        self, api, dock_master_headers,
    ):
        """PRD §3.2: "its `tows_remaining` counter starts at 2 for
        `BASIC`..."

        Claim: BASIC contract has tows_remaining == 2 on creation."""
        marina = create_marina()
        boater = create_boater(marina["id"])
        contract = create_tow_contract(marina["id"], boater, tier="BASIC")
        assert contract["tier"] == "BASIC"
        assert contract["tows_remaining"] == 2, (
            f"BASIC contract.tows_remaining must start at 2, got "
            f"{contract['tows_remaining']!r}"
        )
        assert_tow_assist_contract(contract)

    def test_premium_contract_starts_with_sentinel_negative_one(
        self, api, dock_master_headers,
    ):
        """PRD §3.2: "...or at -1 for `PREMIUM`, where -1 is a sentinel
        meaning unlimited."

        Claim: PREMIUM contract has tows_remaining == -1 on creation."""
        marina = create_marina()
        boater = create_boater(marina["id"])
        contract = create_tow_contract(marina["id"], boater, tier="PREMIUM")
        assert contract["tier"] == "PREMIUM"
        assert contract["tows_remaining"] == -1, (
            f"PREMIUM contract.tows_remaining must start at -1, got "
            f"{contract['tows_remaining']!r}"
        )

    def test_new_contract_is_active(self, api, dock_master_headers):
        """PRD §3.2: "A new contract is created in `ACTIVE` status..."."""
        marina = create_marina()
        boater = create_boater(marina["id"])
        contract = create_tow_contract(marina["id"], boater, tier="BASIC")
        assert contract["status"] == "ACTIVE", (
            f"New TowAssistContract.status must be ACTIVE, got "
            f"{contract['status']!r}"
        )
