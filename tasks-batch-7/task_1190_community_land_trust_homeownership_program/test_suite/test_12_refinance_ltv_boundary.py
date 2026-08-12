"""Refinance LTV boundary — inclusive max_ltv and max_cash_out."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_program_payload,
    create_refinance_request_payload,
    get_success_data,
    make_household_headers,
    setup_active_lease,
    setup_program,
    validate_error,
)


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _submit_and_push_to_lender(prog_id: str, unit_id: str, lease_id: str, household_id: str, **overrides):
    hh_headers = make_household_headers(household_id)
    refi = get_success_data(
        api_client.create_refinance_request(
            prog_id,
            unit_id,
            lease_id,
            create_refinance_request_payload(**overrides),
            hh_headers,
        )
    )
    get_success_data(
        api_client.submit_refi_to_lender(
            prog_id, unit_id, lease_id, refi["id"], hh_headers
        )
    )
    return refi


def test_ltv_at_max_boundary_approves():
    """PRD §3.8: "...requires `computed_ltv` to be at most `max_refi_ltv_pct`
    (boundary inclusive) and `requested_cash_out_cents` to be at most
    `max_equity_withdrawal_cents` (boundary inclusive) — violations of either
    are rejected with `ERR_REFINANCE_LIMIT_EXCEEDED`..."

    Design: Difficulty/boundary_precision_check/refinance_ltv_zero_appraisal_and_max_cashout_boundary
    """
    prog = setup_program(
        name="P-RF1", max_refi_ltv_pct=0.95, max_equity_withdrawal_cents=100_000
    )
    _, unit, hh, lease = setup_active_lease(prog["id"])

    # ltv = 19_000_000 / 20_000_000 = 0.9500 — exactly at max_refi_ltv_pct.
    # cash_out = 100_000 — exactly at max_equity_withdrawal_cents.
    refi = _submit_and_push_to_lender(
        prog["id"],
        unit["id"],
        lease["id"],
        hh["id"],
        requested_loan_cents=19_000_000,
        requested_cash_out_cents=100_000,
        appraised_value_cents=20_000_000,
    )
    assert refi["computed_ltv"] == pytest.approx(0.9500, abs=1e-9)

    approved = get_success_data(
        api_client.approve_refinance(
            prog["id"], unit["id"], lease["id"], refi["id"], _lm()
        )
    )
    assert approved["status"] == "APPROVED"


def test_ltv_above_max_boundary_rejected_with_limit_exceeded():
    """PRD §3.8: "...requires `computed_ltv` to be at most `max_refi_ltv_pct`
    (boundary inclusive) and `requested_cash_out_cents` to be at most
    `max_equity_withdrawal_cents` (boundary inclusive) — violations of either
    are rejected with `ERR_REFINANCE_LIMIT_EXCEEDED`..."

    Design: Difficulty/boundary_precision_check/refinance_ltv_zero_appraisal_and_max_cashout_boundary
    """
    prog = setup_program(
        name="P-RF2", max_refi_ltv_pct=0.95, max_equity_withdrawal_cents=100_000
    )
    _, unit, hh, lease = setup_active_lease(prog["id"])

    # ltv = 19_002_000 / 20_000_000 = 0.9501 — just above max.
    refi = _submit_and_push_to_lender(
        prog["id"],
        unit["id"],
        lease["id"],
        hh["id"],
        requested_loan_cents=19_002_000,
        requested_cash_out_cents=100_000,
        appraised_value_cents=20_000_000,
    )
    assert refi["computed_ltv"] == pytest.approx(0.9501, abs=1e-9)

    resp = api_client.approve_refinance(
        prog["id"], unit["id"], lease["id"], refi["id"], _lm()
    )
    validate_error(resp, ApiErrorId.ERR_REFINANCE_LIMIT_EXCEEDED.value)


def test_cash_out_above_max_rejected():
    """PRD §3.8: "...violations of either are rejected with
    `ERR_REFINANCE_LIMIT_EXCEEDED`..."

    Design: Difficulty/boundary_precision_check/refinance_ltv_zero_appraisal_and_max_cashout_boundary
    """
    prog = setup_program(
        name="P-RF3", max_refi_ltv_pct=0.95, max_equity_withdrawal_cents=100_000
    )
    _, unit, hh, lease = setup_active_lease(prog["id"])

    # LTV at boundary but cash-out exceeds cap by 1 cent.
    refi = _submit_and_push_to_lender(
        prog["id"],
        unit["id"],
        lease["id"],
        hh["id"],
        requested_loan_cents=19_000_000,
        requested_cash_out_cents=100_001,
        appraised_value_cents=20_000_000,
    )

    resp = api_client.approve_refinance(
        prog["id"], unit["id"], lease["id"], refi["id"], _lm()
    )
    validate_error(resp, ApiErrorId.ERR_REFINANCE_LIMIT_EXCEEDED.value)
