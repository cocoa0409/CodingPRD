"""Business validations: payment bounds, the partial-then-full payment progression, the
controlled-med witness requirement, the eMAR slot membership check, and the at-most-one-open
agreement rule.

Citations are verbatim from PRD.md §3.5, §3.7, §3.8.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_issued_full_month_statement, setup_resident_with_med_order,
    create_facility, create_resident, create_unit,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
NURSE = TEST_USERS["nurse_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
STAFF = TEST_USERS["staff_headers"]


def test_payment_exceeds_balance_rejected(api):
    """PRD §3.8: "The payment must be greater than zero and at most the remaining balance, which
    is the `total_charge_cents` minus the cumulative `paid_cents`; a payment that is non-positive
    or exceeds the remaining balance is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/payment_exceeds_balance_rejected
    """
    ctx = setup_issued_full_month_statement(period_year=2026, period_month=12)
    stmt = ctx["statement"]
    assert stmt["total_charge_cents"] == 446500
    resp = api.record_payment(stmt["id"], {"amount_cents": 999999999}, BILLING)
    validate_error(resp, "ERR_PAYMENT_EXCEEDS_BALANCE", expected_status=422)
    after = validate_success(api.get_billing_statement(stmt["id"], STAFF), 200)
    assert after["paid_cents"] == 0
    assert after["status"] == "ISSUED"


def test_partial_then_full_payment_transitions(api):
    """PRD §3.8: "When the amount is strictly less than the remaining balance, it is added to
    `paid_cents` and the statement moves to (or remains in) `PARTIALLY_PAID`: an `ISSUED`
    statement advances `ISSUED → PARTIALLY_PAID`"
    PRD §3.8: "When the amount exactly equals the remaining balance, `paid_cents` is set to the
    `total_charge_cents` and the statement advances to `PAID`"

    Design: Corner/validations/partial_then_full_payment_transitions
    """
    ctx = setup_issued_full_month_statement(period_year=2026, period_month=10)
    stmt = ctx["statement"]
    res_id = ctx["resident"]["id"]
    first = validate_success(api.record_payment(stmt["id"], {"amount_cents": 100000}, BILLING), 200)
    assert first["status"] == "PARTIALLY_PAID"
    assert first["paid_cents"] == 100000
    res_mid = validate_success(api.get_resident(res_id, STAFF), 200)
    assert res_mid["open_balance_cents"] == 346500

    second = validate_success(api.record_payment(stmt["id"], {"amount_cents": 346500}, BILLING), 200)
    assert second["status"] == "PAID"
    assert second["paid_cents"] == 446500
    res_end = validate_success(api.get_resident(res_id, STAFF), 200)
    assert res_end["open_balance_cents"] == 0


def test_controlled_med_given_without_witness_rejected(api):
    """PRD §3.7: "When the order is controlled and the recorded outcome is `GIVEN`, a
    `witness_user_id` is required and it must be different from the administering nurse; a missing
    or non-distinct witness is rejected with `ERR_WITNESS_REQUIRED`."

    Design: Corner/validations/controlled_med_given_without_witness_rejected
    """
    ctx = setup_resident_with_med_order(schedule_times=["08:00"], is_controlled=True)
    resp = api.record_administration(ctx["order"]["id"], {"scheduled_time": "08:00", "outcome": "GIVEN"}, NURSE)
    validate_error(resp, "ERR_WITNESS_REQUIRED", expected_status=422)


def test_emar_invalid_slot_rejected(api):
    """PRD §3.7: "The `scheduled_time` must be one of the times listed in the order's
    `schedule_times`; a slot that is not a member of that list is rejected with
    `ERR_INVALID_MED_SLOT`."

    Design: Corner/validations/emar_invalid_slot_rejected
    """
    ctx = setup_resident_with_med_order(schedule_times=["08:00"], is_controlled=False)
    resp = api.record_administration(ctx["order"]["id"], {"scheduled_time": "22:00", "outcome": "GIVEN"}, NURSE)
    validate_error(resp, "ERR_INVALID_MED_SLOT", expected_status=422)


def test_second_open_agreement_rejected(api):
    """PRD §3.5: "A resident may have at most one agreement that is in either `DRAFT` or `ACTIVE`
    status at any time; attempting to draft a second open agreement is rejected with
    `ERR_AGREEMENT_ALREADY_OPEN`."

    Design: Corner/validations/second_open_agreement_rejected
    """
    fac = create_facility()
    unit1 = create_unit(fac["id"], unit_number="330")
    unit2 = create_unit(fac["id"], unit_number="331")
    res = create_resident(fac["id"], full_name="Open Ollie", date_of_birth="1938-01-01")
    get_success_data(api.create_move_in_agreement(
        {"resident_id": res["id"], "unit_id": unit1["id"], "move_in_date": "2026-06-01", "community_fee_cents": 0},
        REGISTRAR))
    resp = api.create_move_in_agreement(
        {"resident_id": res["id"], "unit_id": unit2["id"], "move_in_date": "2026-06-01", "community_fee_cents": 0},
        REGISTRAR)
    validate_error(resp, "ERR_AGREEMENT_ALREADY_OPEN", expected_status=409)
