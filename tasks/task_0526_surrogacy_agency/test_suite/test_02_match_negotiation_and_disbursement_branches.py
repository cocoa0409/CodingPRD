"""Non-linear state-machine shapes: the match negotiation cycle
(PROPOSED -> COUNTERED -> PROPOSED with offer_round climbing) and the
disbursement branching fork (REQUESTED -> {APPROVED, REJECTED}, APPROVED ->
REJECTED with divergent escrow side-effects).

Covers difficulty queue rule non_linear_state_machine.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    create_approved_disbursement,
    create_requested_disbursement,
)
from test_helpers import factories as f

CM = TEST_USERS["case_manager_headers"]


def test_match_negotiation_cycle_reproposes_and_bumps_offer_round(api):
    """PRD §3.3: "From `COUNTERED`, a re-propose moves back to `PROPOSED`; it
    requires the match to be in `COUNTERED` and `expected_match_version` to
    match, and it increments `offer_round` by 1, sets `proposed_carrier_comp_cents`
    to the re-proposed amount, and increments the match `version`."

    Design: Difficulty/non_linear_state_machine/match_negotiation_cycle_proposed_countered_proposed
    """
    ip = get_success_data(api.create_intended_parent(f.create_intended_parent_payload(), CM))
    car = get_success_data(api.create_carrier(f.create_carrier_payload(), CM))
    match = get_success_data(api.create_match(
        f.create_match_payload(ip["id"], car["id"], proposed_carrier_comp_cents=4_000_000), CM))
    countered = validate_success(api.counter_match(
        match["id"], {"proposed_carrier_comp_cents": 4_500_000,
                      "expected_match_version": match["version"]}, CM))
    assert countered["status"] == "COUNTERED"

    reproposed = validate_success(api.re_propose_match(
        match["id"], {"proposed_carrier_comp_cents": 4_300_000,
                      "expected_match_version": countered["version"]}, CM))
    assert reproposed["status"] == "PROPOSED"
    assert reproposed["offer_round"] == 1
    assert reproposed["proposed_carrier_comp_cents"] == 4_300_000


def test_match_counter_sets_proposed_comp_and_status(api):
    """PRD §3.3: "A `CaseManager` may counter a proposal, moving `PROPOSED` to
    `COUNTERED`; this requires the match to be in `PROPOSED` and
    `expected_match_version` to equal the match's current `version`, and it sets
    `proposed_carrier_comp_cents` to the countered amount and increments the
    match `version`."

    Design: Difficulty/non_linear_state_machine/match_negotiation_cycle_proposed_countered_proposed
    """
    ip = get_success_data(api.create_intended_parent(f.create_intended_parent_payload(), CM))
    car = get_success_data(api.create_carrier(f.create_carrier_payload(), CM))
    match = get_success_data(api.create_match(
        f.create_match_payload(ip["id"], car["id"], proposed_carrier_comp_cents=4_000_000), CM))
    countered = validate_success(api.counter_match(
        match["id"], {"proposed_carrier_comp_cents": 4_500_000,
                      "expected_match_version": match["version"]}, CM))
    assert countered["status"] == "COUNTERED"
    assert countered["proposed_carrier_comp_cents"] == 4_500_000
    assert countered["offer_round"] == 0


def test_reject_approved_disbursement_returns_reservation(api):
    """PRD §3.8: "Rejecting an `APPROVED` disbursement also moves it to
    `REJECTED` but first releases its reservation: it subtracts `amount_cents`
    from the account's `reserved_cents`, recomputes `available_cents`, and
    increments the escrow and disbursement `version` counters — returning the
    previously reserved funds to available."

    Design: Difficulty/non_linear_state_machine/disbursement_branch_reject_from_approved_returns_reservation
    """
    ctx = create_approved_disbursement(deposit_cents=6_000_000, schedule_amount_cents=1_000_000)
    jr_id = ctx["journey"]["id"]
    disb = validate_success(api.reject_disbursement(jr_id, ctx["disbursement"]["id"], CM))
    assert disb["status"] == "REJECTED"

    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], TEST_USERS["finance_officer_headers"]))
    assert escrow["reserved_cents"] == 0
    assert escrow["available_cents"] == 6_000_000


def test_reject_requested_disbursement_has_no_escrow_effect(api):
    """PRD §3.8: "Rejecting a `REQUESTED` disbursement moves it to the terminal
    `REJECTED` with no escrow effect."

    Design: Difficulty/non_linear_state_machine/disbursement_branch_reject_from_approved_returns_reservation
    """
    ctx = create_requested_disbursement(deposit_cents=6_000_000, schedule_amount_cents=1_000_000)
    jr_id = ctx["journey"]["id"]
    disb = validate_success(api.reject_disbursement(jr_id, ctx["disbursement"]["id"], CM))
    assert disb["status"] == "REJECTED"

    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], TEST_USERS["finance_officer_headers"]))
    assert escrow["reserved_cents"] == 0
    assert escrow["available_cents"] == 6_000_000
    assert escrow["deposited_cents"] == 6_000_000
