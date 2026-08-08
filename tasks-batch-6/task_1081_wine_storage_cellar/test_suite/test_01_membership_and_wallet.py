"""Member lifecycle, suspension cascade, and wallet-ledger conservation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    onboard_member, create_locker, assign_locker, create_intake_request,
    setup_active_member_with_locker, setup_bottle_with_finalized_appraisal,
    post_ledger_adjustment, quote_policy,
    create_member_payload, make_cellar_member_headers,
)

MGR = TEST_USERS["cellar_manager_headers"]
AGENT = TEST_USERS["insurance_agent_headers"]


# --------------------------------------------------------------------------- #
# Queue A — non_linear_state_machine / member_active_suspended_active_cycle
# --------------------------------------------------------------------------- #
def test_member_suspend_sets_suspended(api):
    """PRD §3.1: "Suspension takes an `ACTIVE` member to `SUSPENDED` and triggers a
    three-hop cascade resolved within the request."

    Design: Difficulty/non_linear_state_machine/member_active_suspended_active_cycle
    """
    member = onboard_member(api, tier="STANDARD")
    data = validate_success(api.suspend_member(member["id"], MGR))
    assert data["status"] == "SUSPENDED", f"expected SUSPENDED, got {data['status']}"


def test_member_reactivate_returns_to_active_after_cycle(api):
    """PRD §3.1: "Reactivation returns a `SUSPENDED` member to `ACTIVE` and unfreezes
    their lockers: every locker owned by the member that is `FROZEN` transitions back
    to `ASSIGNED`."

    Design: Difficulty/non_linear_state_machine/member_active_suspended_active_cycle
    """
    member = onboard_member(api, tier="STANDARD")
    suspended = validate_success(api.suspend_member(member["id"], MGR))
    assert suspended["status"] == "SUSPENDED"
    reactivated = validate_success(api.reactivate_member(member["id"], MGR))
    assert reactivated["status"] == "ACTIVE", (
        f"member must cycle back to ACTIVE, got {reactivated['status']}"
    )


# --------------------------------------------------------------------------- #
# Queue A — transitive_cascade / member_suspend_freeze_cancel_release_depth3
# --------------------------------------------------------------------------- #
def test_suspend_freezes_locker_and_cancels_intake_request(api):
    """PRD §3.1: "First, every locker owned by the member (matching on `member_id`)
    that is currently `ASSIGNED` transitions to `FROZEN`."
    PRD §3.1: "Second, for each such newly frozen locker, every movement request on it
    that is still `REQUESTED` or `APPROVED` transitions to `CANCELLED`."

    Design: Difficulty/transitive_cascade/member_suspend_freeze_cancel_release_depth3
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="LARGE", climate_zone="RED", capacity=5, tier="RESERVE"
    )
    mr = create_intake_request(api, member["id"], locker["id"], quantity=3)
    validate_success(api.suspend_member(member["id"], MGR))

    lk = validate_success(api.get_locker(locker["id"], MGR))
    assert lk["status"] == "FROZEN", f"locker must be FROZEN, got {lk['status']}"
    mr_after = validate_success(api.get_movement_request(mr["id"], MGR))
    assert mr_after["status"] == "CANCELLED", (
        f"open intake request must be CANCELLED, got {mr_after['status']}"
    )


def test_suspend_recomputes_reservation_release_depth3(api):
    """PRD §3.1: "Third, for each intake request thus cancelled, the locker's
    `reserved_bottles` is recomputed so the cancelled request no longer counts, which
    raises the locker's `free_bottles`."

    Design: Difficulty/transitive_cascade/member_suspend_freeze_cancel_release_depth3
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="LARGE", climate_zone="RED", capacity=5, tier="RESERVE"
    )
    create_intake_request(api, member["id"], locker["id"], quantity=3)
    validate_success(api.suspend_member(member["id"], MGR))

    lk = validate_success(api.get_locker(locker["id"], MGR))
    assert lk["reserved_bottles"] == 0, f"reserved must drop to 0, got {lk['reserved_bottles']}"
    assert lk["free_bottles"] == 5, f"free must rise to 5, got {lk['free_bottles']}"


# --------------------------------------------------------------------------- #
# Queue A — compensating_invariant / intake_reservation_conserved
# --------------------------------------------------------------------------- #
def test_intake_reservation_lowers_free_bottles(api):
    """PRD §3.3: "When the request is an intake, its reserved units are immediately
    reflected in the locker's `reserved_bottles`, and an intake whose reservation would
    drive the locker's `free_bottles` below zero is refused with
    `ERR_LOCKER_CAPACITY_EXCEEDED`."

    Design: Difficulty/compensating_invariant/intake_reservation_conserved
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="LARGE", climate_zone="RED", capacity=5, tier="RESERVE"
    )
    create_intake_request(api, member["id"], locker["id"], quantity=3)
    lk = validate_success(api.get_locker(locker["id"], MGR))
    assert lk["reserved_bottles"] == 3, f"reserved should be 3, got {lk['reserved_bottles']}"
    assert lk["free_bottles"] == 2, f"free should be 2, got {lk['free_bottles']}"


def test_intake_cancel_restores_free_bottles_conserved(api):
    """PRD §2.8: "A locker tracks three counts that must always sum to its capacity:
    `occupied_bottles`, `reserved_bottles`, and `free_bottles`, where `free_bottles`
    equals `capacity_bottles` minus `occupied_bottles` minus `reserved_bottles`."
    PRD §3.3: "Cancellation moves a request that is `REQUESTED` or `APPROVED` to
    `CANCELLED`, and again, if it was an intake, the reservation is released and
    `free_bottles` rises."

    Design: Difficulty/compensating_invariant/intake_reservation_conserved
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="LARGE", climate_zone="RED", capacity=5, tier="RESERVE"
    )
    mr = create_intake_request(api, member["id"], locker["id"], quantity=3)
    validate_success(api.cancel_movement_request(mr["id"], make_cellar_member_headers(member["id"])))
    lk = validate_success(api.get_locker(locker["id"], MGR))
    assert lk["reserved_bottles"] == 0, f"reserved should return to 0, got {lk['reserved_bottles']}"
    assert lk["free_bottles"] == 5, f"free should return to 5, got {lk['free_bottles']}"


# --------------------------------------------------------------------------- #
# Queue A — compensating_invariant / wallet_ledger_conserved
# --------------------------------------------------------------------------- #
def test_bind_policy_debits_wallet(api):
    """PRD §3.6: "On a successful bind, a `DEBIT` ledger entry for the `premium_cents`
    is posted to the member (lowering the wallet balance) and the policy's `bound_at`
    is stamped from the current logical clock."

    Design: Difficulty/compensating_invariant/wallet_ledger_conserved
    """
    member, locker, bottle = setup_bottle_with_finalized_appraisal(
        api, method="MARKET_COMPARABLE", base_value_cents=700, provenance_status="DOCUMENTED",
        size_tier="SMALL", climate_zone="WHITE", capacity=2, tier="PREMIUM",
    )
    policy = quote_policy(api, member["id"], [bottle["id"]], coverage_tier="FULL")
    assert policy["premium_cents"] == 11, f"premium should be 11, got {policy['premium_cents']}"
    validate_success(api.bind_insurance_policy(policy["id"], AGENT))
    m = validate_success(api.get_member(member["id"], MGR))
    assert m["wallet_balance_cents"] == -11, (
        f"wallet must be -11 after debit, got {m['wallet_balance_cents']}"
    )


def test_cancel_bound_policy_credits_wallet_back_to_zero(api):
    """PRD §2.8: "Because the ledger is append-only, a debit followed by an equal
    compensating credit leaves the wallet balance unchanged."
    PRD §3.6: "if the policy had been bound, a compensating `CREDIT` ledger entry for
    the same `premium_cents` is posted, returning the wallet to its pre-bind value."

    Design: Difficulty/compensating_invariant/wallet_ledger_conserved
    """
    member, locker, bottle = setup_bottle_with_finalized_appraisal(
        api, method="MARKET_COMPARABLE", base_value_cents=700, provenance_status="DOCUMENTED",
        size_tier="SMALL", climate_zone="WHITE", capacity=2, tier="PREMIUM",
    )
    policy = quote_policy(api, member["id"], [bottle["id"]], coverage_tier="FULL")
    validate_success(api.bind_insurance_policy(policy["id"], AGENT))
    m_bound = validate_success(api.get_member(member["id"], MGR))
    assert m_bound["wallet_balance_cents"] == -11
    validate_success(api.cancel_insurance_policy(policy["id"], AGENT))
    m_after = validate_success(api.get_member(member["id"], MGR))
    assert m_after["wallet_balance_cents"] == 0, (
        f"wallet must return to 0 after compensating credit, got {m_after['wallet_balance_cents']}"
    )


# --------------------------------------------------------------------------- #
# Queue B — entities / member_create_returns_pending_zero_wallet
# --------------------------------------------------------------------------- #
def test_member_create_returns_pending_zero_wallet(api):
    """PRD §3.1: "A newly onboarded member begins life in `PENDING` status with a
    `wallet_balance_cents` of 0."

    Design: Corner/entities/member_create_returns_pending_zero_wallet
    """
    payload = create_member_payload(membership_tier="STANDARD")
    data = validate_success(api.create_member(payload, MGR), expected_status=201)
    assert data["status"] == "PENDING", f"new member must be PENDING, got {data['status']}"
    assert data["wallet_balance_cents"] == 0, (
        f"new member wallet must be 0, got {data['wallet_balance_cents']}"
    )


# --------------------------------------------------------------------------- #
# Queue B — state_machines / activate_already_active_returns_invalid_state
# --------------------------------------------------------------------------- #
def test_activate_already_active_returns_invalid_state(api):
    """PRD §3.1: "each requires the member to be in the state from which that transition
    departs, and a member that is not in the departing state is refused with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_returns_invalid_state
    """
    member = onboard_member(api, tier="STANDARD")  # already ACTIVE
    validate_error(api.activate_member(member["id"], MGR), ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# Queue B — errors / close_member_with_negative_wallet_returns_outstanding_balance
# --------------------------------------------------------------------------- #
def test_close_member_with_negative_wallet_returns_outstanding_balance(api):
    """PRD §3.1: "The member's `wallet_balance_cents` must be at least 0 — a member who
    still owes the facility, whose balance is below zero, is refused with
    `ERR_OUTSTANDING_BALANCE`."

    Design: Corner/errors/close_member_with_negative_wallet_returns_outstanding_balance
    """
    member = onboard_member(api, tier="STANDARD")
    post_ledger_adjustment(api, member["id"], "DEBIT", 5000, reason="late fee")
    validate_error(api.close_member(member["id"], MGR), ApiErrorId.ERR_OUTSTANDING_BALANCE.value)


# --------------------------------------------------------------------------- #
# Queue B — errors / close_member_holding_locker_returns_has_active_lockers
# --------------------------------------------------------------------------- #
def test_close_member_holding_locker_returns_has_active_lockers(api):
    """PRD §3.1: "The member may not still hold any locker in `ASSIGNED`, `FROZEN`, or
    `MAINTENANCE`; if one exists, the close is refused with
    `ERR_MEMBER_HAS_ACTIVE_LOCKERS`."

    Design: Corner/errors/close_member_holding_locker_returns_has_active_lockers
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="SMALL", climate_zone="RED", capacity=2, tier="RESERVE"
    )
    validate_error(
        api.close_member(member["id"], MGR), ApiErrorId.ERR_MEMBER_HAS_ACTIVE_LOCKERS.value
    )
