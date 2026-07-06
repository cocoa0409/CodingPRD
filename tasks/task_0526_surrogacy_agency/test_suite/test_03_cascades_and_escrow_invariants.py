"""Transitive cascade chains (match-void depth-3, journey-terminate depth-2) and
compensating-action escrow invariants (reject-approved conserves deposited;
release conserves reserved+disbursed).

Covers difficulty queue rules transitive_cascade and compensating_invariant.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    make_finance_officer_headers,
    create_active_journey,
    create_approved_disbursement,
)

CM = TEST_USERS["case_manager_headers"]
FO = TEST_USERS["finance_officer_headers"]


def test_match_void_cascades_to_contract_void_then_escrow_freeze(api):
    """PRD §3.4: "voiding a match, from any of its non-terminal states, first
    transitions the match's linked contract to `VOID` if such a contract exists
    and is not already `VOID` (hop one), which in turn freezes the open escrow
    account of the linked journey (hop two)."

    Design: Difficulty/transitive_cascade/match_void_cascades_contract_void_then_escrow_freeze_depth3
    """
    ctx = create_active_journey()
    match_id = ctx["match"]["id"]
    voided = validate_success(api.void_match(match_id, CM))
    assert voided["status"] == "VOID"

    contract = validate_success(api.get_contract(ctx["contract"]["id"], CM))
    assert contract["status"] == "VOID"
    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], FO))
    assert escrow["status"] == "FROZEN"


def test_journey_terminate_freezes_linked_escrow(api):
    """PRD §3.5: "A journey may be terminated from either `ACTIVE` or `ON_HOLD`,
    moving it to the terminal `TERMINATED`; termination freezes the linked
    escrow account if it is open."

    Design: Difficulty/transitive_cascade/journey_terminate_freezes_escrow_depth2
    """
    ctx = create_active_journey()
    jr = validate_success(api.terminate_journey(ctx["journey"]["id"], CM))
    assert jr["status"] == "TERMINATED"
    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], FO))
    assert escrow["status"] == "FROZEN"


def test_journey_terminate_from_on_hold_freezes_escrow(api):
    """PRD §3.5: "A journey may be terminated from either `ACTIVE` or `ON_HOLD`,
    moving it to the terminal `TERMINATED`; termination freezes the linked
    escrow account if it is open."

    Design: Difficulty/transitive_cascade/journey_terminate_freezes_escrow_depth2
    """
    ctx = create_active_journey()
    jr_id = ctx["journey"]["id"]
    get_success_data(api.hold_journey(jr_id, CM))
    jr = validate_success(api.terminate_journey(jr_id, CM))
    assert jr["status"] == "TERMINATED"
    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], FO))
    assert escrow["status"] == "FROZEN"


# ==========================================================================
# Compensating-action escrow invariants
# ==========================================================================
def test_reject_approved_disbursement_conserves_deposited_total(api):
    """PRD §3.8: "Rejecting an `APPROVED` disbursement also moves it to
    `REJECTED` but first releases its reservation: it subtracts `amount_cents`
    from the account's `reserved_cents`, recomputes `available_cents` ...
    returning the previously reserved funds to available." PRD §3.8 (approval):
    "adds `amount_cents` to the account's `reserved_cents`, recomputes
    `available_cents` (reserving reduces available funds but leaves
    `deposited_cents` untouched)".

    Design: Difficulty/compensating_invariant/reject_approved_disbursement_conserves_escrow_total
    """
    ctx = create_approved_disbursement(deposit_cents=6_000_000, schedule_amount_cents=1_000_000)
    jr_id = ctx["journey"]["id"]
    # Pre-reject: reservation held.
    assert ctx["escrow"]["reserved_cents"] == 1_000_000
    assert ctx["escrow"]["available_cents"] == 5_000_000

    validate_success(api.reject_disbursement(jr_id, ctx["disbursement"]["id"], CM))
    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], FO))
    assert escrow["deposited_cents"] == 6_000_000
    assert escrow["reserved_cents"] == 0
    assert escrow["disbursed_cents"] == 0
    assert escrow["available_cents"] == 6_000_000


def test_release_disbursement_conserves_reserved_plus_disbursed(api):
    """PRD §3.8: "On release the system moves `amount_cents` from `reserved_cents`
    into `disbursed_cents`, recomputes `available_cents`, and increments both the
    escrow and disbursement `version` counters; `reserved_cents` decreases and
    `disbursed_cents` increases by the same amount while `deposited_cents` is
    unchanged."

    Design: Difficulty/compensating_invariant/release_disbursement_conserves_reserved_plus_disbursed
    """
    ctx = create_approved_disbursement(deposit_cents=6_000_000, schedule_amount_cents=1_000_000,
                                       approver_user_id="cm-approver-rel")
    jr_id = ctx["journey"]["id"]
    releaser = make_finance_officer_headers("fo-releaser-rel")
    disb = validate_success(api.release_disbursement(jr_id, ctx["disbursement"]["id"], releaser))
    assert disb["status"] == "RELEASED"

    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], FO))
    assert escrow["reserved_cents"] == 0
    assert escrow["disbursed_cents"] == 1_000_000
    assert escrow["deposited_cents"] == 6_000_000
    assert escrow["available_cents"] == 5_000_000


def test_disbursement_approval_reserves_funds(api):
    """PRD §3.8: "On approval the system records the acting `CaseManager`'s
    `X-User-ID` as `approved_by_user_id`, adds `amount_cents` to the account's
    `reserved_cents`, recomputes `available_cents` (reserving reduces available
    funds but leaves `deposited_cents` untouched)".

    Design: Difficulty/compensating_invariant/release_disbursement_conserves_reserved_plus_disbursed
    """
    ctx = create_approved_disbursement(deposit_cents=6_000_000, schedule_amount_cents=1_000_000)
    escrow = ctx["escrow"]
    assert escrow["reserved_cents"] == 1_000_000
    assert escrow["disbursed_cents"] == 0
    assert escrow["deposited_cents"] == 6_000_000
    assert escrow["available_cents"] == 5_000_000
