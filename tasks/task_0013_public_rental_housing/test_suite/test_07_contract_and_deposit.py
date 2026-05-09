"""Contract lifecycle: deposit verification, signing, handover, and the chain that
cascades through to ACTIVE / OCCUPIED.

Covers PRD §3.5 (confirmation, contract auto-create, pay-deposit, sign, handover) and
PRD §2.7 (deposit rounding), and supports SCAFFOLD_DIFFICULTY_DESIGN instances:
- confirm_to_contract_to_handover_chain (transitive_cascade)
- contract_state_vs_fiscal_deposit (priority_pair_validation_conflict)
- monthly_effective_rent_round_per_line_then_sum (combinatorial_formula mode b)

# difficulty: transitive_cascade/confirm_to_contract_to_handover_chain
# difficulty: priority_pair_validation_conflict/contract_state_vs_fiscal_deposit
# difficulty: combinatorial_formula/monthly_effective_rent_round_per_line_then_sum
"""

import pytest

from test_helpers import (
    OFFICER_HEADERS,
    advance_clock_by,
    api_client as api,
    create_confirmed_allocation,
    create_program,
    create_sign_payload,
    emit_payment_deposit_for,
    make_applicant_headers,
    setup_contract_active,
    setup_contract_signed,
    setup_two_bedroom_active_contract_for_rent_split,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# Difficulty: transitive_cascade/confirm_to_contract_to_handover_chain
# ──────────────────────────────────────────────────────────


def test_confirm_creates_contract_in_draft_with_correct_deposit_amount():
    """PRD §3.5: "On success, the allocation transitions from PUBLISHED to CONFIRMED,
    confirmation_period is set to the current current_period_index, a Contract is
    auto-created in DRAFT status with application_id and housing_unit_id denormalized
    from the parent allocation and deposit_amount_cents computed as the unit's
    monthly_base_rent_cents multiplied by two".

    # difficulty: transitive_cascade/confirm_to_contract_to_handover_chain
    """
    program = create_program(notice_period_length=1)
    allocation, contract, application, unit, applicant_id = create_confirmed_allocation(
        program["id"],
        notice_period_length=1,
        unit_overrides={"monthly_base_rent_cents": 50_000},
    )
    assert allocation["status"] == "CONFIRMED"
    assert contract["status"] == "DRAFT"
    # PRD §2.7: deposit = monthly_base_rent_cents * 2 (half-up; integer*2 stays integer).
    assert contract["deposit_amount_cents"] == 100_000
    assert contract["application_id"] == application["id"]
    assert contract["housing_unit_id"] == unit["id"]


def test_full_chain_confirm_to_handover_cascades_application_and_unit():
    """PRD §3.5: "On success, handover_recorded is set to true and the contract
    transitions from SIGNED to ACTIVE; the cascade transitions the application from
    ALLOCATED to OCCUPIED, transitions the housing unit from RESERVED to OCCUPIED".

    # difficulty: transitive_cascade/confirm_to_contract_to_handover_chain
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, _ = setup_contract_active(
        program["id"], notice_period_length=1
    )
    assert contract["status"] == "ACTIVE"
    assert contract["handover_recorded"] is True
    assert application["status"] == "OCCUPIED"
    assert unit["status"] == "OCCUPIED"


# ──────────────────────────────────────────────────────────
# Pay deposit (PRD §3.5)
# ──────────────────────────────────────────────────────────


def test_pay_deposit_rejects_when_amount_does_not_match():
    """PRD §3.5: "the latest PAYMENT_DEPOSIT event for this contract to carry a
    payload.amount_cents exactly equal to the contract's deposit_amount_cents —
    otherwise the request is rejected with ERR_DEPOSIT_AMOUNT_MISMATCH at HTTP 402".
    """
    program = create_program(notice_period_length=1)
    allocation, contract, application, unit, applicant_id = create_confirmed_allocation(
        program["id"],
        notice_period_length=1,
        unit_overrides={"monthly_base_rent_cents": 50_000},
    )
    # Emit a payment for the wrong amount.
    emit_payment_deposit_for(
        program["id"], contract["id"], contract["deposit_amount_cents"] - 1
    )
    res = api.pay_deposit(
        program["id"], contract["id"], make_applicant_headers(applicant_id)
    )
    validate_error(res, "ERR_DEPOSIT_AMOUNT_MISMATCH")


def test_pay_deposit_succeeds_when_amount_matches_and_sets_flag():
    """PRD §3.5: "On success the contract transitions from DRAFT to DEPOSIT_PAID and
    deposit_paid is set to true".
    """
    program = create_program(notice_period_length=1)
    allocation, contract, application, unit, applicant_id = create_confirmed_allocation(
        program["id"],
        notice_period_length=1,
        unit_overrides={"monthly_base_rent_cents": 50_000},
    )
    emit_payment_deposit_for(program["id"], contract["id"], contract["deposit_amount_cents"])
    res = api.pay_deposit(
        program["id"], contract["id"], make_applicant_headers(applicant_id)
    )
    contract_after = validate_success(res)
    assert contract_after["status"] == "DEPOSIT_PAID"
    assert contract_after["deposit_paid"] is True


# ──────────────────────────────────────────────────────────
# Difficulty: priority_pair_validation_conflict/contract_state_vs_fiscal_deposit
# PRD §2.9 explicitly orders: state precedes business_fiscal — so when both fail at
# /pay-deposit, the state error wins.
# ──────────────────────────────────────────────────────────


def test_pay_deposit_state_error_wins_over_amount_mismatch():
    """PRD §2.9: "Validation across every endpoint runs in a fixed priority order so
    that a higher-priority failure is not masked by a lower-priority one. ... then
    state-machine preconditions on the target entity (priorities 5–8, the typed
    ERR_*_NOT_* family); and finally the domain-specific business checks of priorities
    9 through 26".

    Contract is already DEPOSIT_PAID (state error) AND latest PAYMENT_DEPOSIT amount
    differs from deposit_amount_cents (fiscal error). State wins:
    ERR_CONTRACT_NOT_IN_DRAFT.

    # difficulty: priority_pair_validation_conflict/contract_state_vs_fiscal_deposit
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_signed(
        program["id"], notice_period_length=1
    )
    # contract is now SIGNED (past DEPOSIT_PAID); definitely not DRAFT.
    # Latest PAYMENT_DEPOSIT is the matching one, so emit a wrong one to manufacture
    # the fiscal error.
    emit_payment_deposit_for(
        program["id"], contract["id"], contract["deposit_amount_cents"] + 1
    )
    res = api.pay_deposit(
        program["id"], contract["id"], make_applicant_headers(applicant_id)
    )
    validate_error(res, "ERR_CONTRACT_NOT_IN_DRAFT")


def test_pay_deposit_state_error_wins_when_contract_signed_and_amount_off():
    """Second instance for difficulty coverage with a different mismatched amount
    direction.

    PRD §2.9: state precondition errors (priorities 5–8) precede business_fiscal errors
    (priorities 9–26).

    # difficulty: priority_pair_validation_conflict/contract_state_vs_fiscal_deposit
    """
    program = create_program(notice_period_length=1)
    application, allocation, contract, unit, applicant_id = setup_contract_signed(
        program["id"], notice_period_length=1
    )
    # Mismatch in the OTHER direction.
    emit_payment_deposit_for(
        program["id"], contract["id"], max(0, contract["deposit_amount_cents"] - 5_000)
    )
    res = api.pay_deposit(
        program["id"], contract["id"], make_applicant_headers(applicant_id)
    )
    validate_error(res, "ERR_CONTRACT_NOT_IN_DRAFT")


# ──────────────────────────────────────────────────────────
# Sign (PRD §3.5)
# ──────────────────────────────────────────────────────────


def test_sign_rejects_invalid_lease_term_when_end_not_after_start():
    """PRD §3.5: "lease_end_period must be strictly greater than lease_start_period and
    lease_start_period must be at least the parent allocation's confirmation_period;
    either failure is reported as ERR_INVALID_LEASE_TERM".
    """
    program = create_program(notice_period_length=1)
    allocation, contract, application, unit, applicant_id = create_confirmed_allocation(
        program["id"], notice_period_length=1
    )
    emit_payment_deposit_for(program["id"], contract["id"], contract["deposit_amount_cents"])
    headers = make_applicant_headers(applicant_id)
    contract = validate_success(api.pay_deposit(program["id"], contract["id"], headers))
    cp = allocation["confirmation_period"]
    res = api.sign_contract(
        program["id"],
        contract["id"],
        create_sign_payload(cp, cp),  # end == start, must be strictly greater
        headers,
    )
    validate_error(res, "ERR_INVALID_LEASE_TERM")


def test_sign_rejects_when_lease_start_before_confirmation_period():
    """PRD §3.5: "lease_start_period must be at least the parent allocation's
    confirmation_period; either failure is reported as ERR_INVALID_LEASE_TERM".
    """
    program = create_program(notice_period_length=1)
    allocation, contract, application, unit, applicant_id = create_confirmed_allocation(
        program["id"], notice_period_length=1
    )
    emit_payment_deposit_for(program["id"], contract["id"], contract["deposit_amount_cents"])
    headers = make_applicant_headers(applicant_id)
    contract = validate_success(api.pay_deposit(program["id"], contract["id"], headers))
    cp = allocation["confirmation_period"]
    res = api.sign_contract(
        program["id"],
        contract["id"],
        create_sign_payload(cp - 1, cp + 5),  # start < confirmation_period
        headers,
    )
    validate_error(res, "ERR_INVALID_LEASE_TERM")


def test_sign_rejects_empty_signature_blob():
    """PRD §3.5: "the signature_blob must be non-empty (else ERR_INVALID_REQUEST)"."""
    program = create_program(notice_period_length=1)
    allocation, contract, application, unit, applicant_id = create_confirmed_allocation(
        program["id"], notice_period_length=1
    )
    emit_payment_deposit_for(program["id"], contract["id"], contract["deposit_amount_cents"])
    headers = make_applicant_headers(applicant_id)
    contract = validate_success(api.pay_deposit(program["id"], contract["id"], headers))
    cp = allocation["confirmation_period"]
    res = api.sign_contract(
        program["id"],
        contract["id"],
        create_sign_payload(cp, cp + 5, signature_blob=""),
        headers,
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_handover_rejects_before_lease_start():
    """PRD §3.5: "the program's current_period_index to be at least the contract's
    lease_start_period (else ERR_LEASE_NOT_STARTED)".
    """
    program = create_program(notice_period_length=1)
    allocation, contract, application, unit, applicant_id = create_confirmed_allocation(
        program["id"], notice_period_length=1
    )
    emit_payment_deposit_for(program["id"], contract["id"], contract["deposit_amount_cents"])
    headers = make_applicant_headers(applicant_id)
    contract = validate_success(api.pay_deposit(program["id"], contract["id"], headers))
    cp = allocation["confirmation_period"]
    # Sign with a future lease_start_period, then attempt handover before reaching it.
    contract = validate_success(
        api.sign_contract(
            program["id"],
            contract["id"],
            create_sign_payload(cp + 5, cp + 20),
            headers,
        )
    )
    res = api.handover_contract(program["id"], contract["id"], OFFICER_HEADERS)
    validate_error(res, "ERR_LEASE_NOT_STARTED")


# ──────────────────────────────────────────────────────────
# Difficulty: combinatorial_formula/monthly_effective_rent_round_per_line_then_sum
# ──────────────────────────────────────────────────────────


def test_two_bedroom_per_room_round_then_sum_99999():
    """PRD §2.7: "Two specific places require rounding ... per-room rent shares (each
    per-room amount rounded half-up to integer cents before summation, never after).
    The order of operations on per-room rent shares is fixed and load-bearing: round
    each per-room amount first, then sum the rounded amounts. Summing first and
    rounding the total once is incorrect and will produce a different number when the
    fractional cents collectively exceed half a cent".

    PRD §3.6: TWO_BEDROOM split = 40/30/30 of monthly_base_rent_cents.

    With base=99999:
    - Living room = round_half_up(99999 * 0.40) = round_half_up(39999.6) = 40000
    - Bedroom 1   = round_half_up(99999 * 0.30) = round_half_up(29999.7) = 30000
    - Bedroom 2   = round_half_up(99999 * 0.30) = round_half_up(29999.7) = 30000
    Sum (round-then-sum) = 40000 + 30000 + 30000 = 100000.
    Sum-then-round of 99999*1.0 = 99999, the WRONG variant.

    # difficulty: combinatorial_formula/monthly_effective_rent_round_per_line_then_sum
    """
    program = create_program(notice_period_length=1)
    application, contract, unit, _ = setup_two_bedroom_active_contract_for_rent_split(
        program["id"], monthly_base_rent_cents=99999
    )
    assert contract["monthly_effective_rent_cents"] == 100_000, (
        "PRD §2.7 round-per-line then sum requires the result to be 100000, not the "
        f"sum-then-round 99999. Got {contract.get('monthly_effective_rent_cents')}"
    )


def test_two_bedroom_per_room_round_then_sum_with_different_base_rent():
    """Second instance for difficulty coverage with a different base rent that exposes
    the same round-per-line ordering.

    PRD §2.7: "round each per-room amount first, then sum the rounded amounts".

    With base=10001 (TWO_BEDROOM 40/30/30):
    - Living room = round_half_up(10001 * 0.40) = round_half_up(4000.4) = 4000
    - Bedroom 1   = round_half_up(10001 * 0.30) = round_half_up(3000.3) = 3000
    - Bedroom 2   = round_half_up(10001 * 0.30) = round_half_up(3000.3) = 3000
    Sum = 10000. The sum-then-round-once variant would yield 10001.

    # difficulty: combinatorial_formula/monthly_effective_rent_round_per_line_then_sum
    """
    program = create_program(notice_period_length=1)
    application, contract, unit, _ = setup_two_bedroom_active_contract_for_rent_split(
        program["id"], monthly_base_rent_cents=10001
    )
    assert contract["monthly_effective_rent_cents"] == 10_000


def test_deposit_amount_is_two_months_base_rent():
    """PRD §3.5: "deposit_amount_cents computed as the unit's monthly_base_rent_cents
    multiplied by two (rounded half-up to integer cents — since monthly_base_rent_cents
    is already integer cents this is just twice the base rent)".
    """
    program = create_program(notice_period_length=1)
    _, contract, _, _, _ = create_confirmed_allocation(
        program["id"],
        notice_period_length=1,
        unit_overrides={"monthly_base_rent_cents": 75_000},
    )
    assert contract["deposit_amount_cents"] == 150_000
