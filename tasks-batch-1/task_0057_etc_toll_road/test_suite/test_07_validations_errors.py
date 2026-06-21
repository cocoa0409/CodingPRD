"""Business-rule validations and error catalogue corners."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_account, create_vehicle, create_transponder, create_plaza, credit_account,
    bind_transponder, record_transponder_read, record_plate_read, price,
    create_interop_agency, create_hov_window_payload, create_transponder_binding_payload,
    setup_plate_violation,
    api_client, TEST_USERS, make_account_holder_headers,
)

OP = TEST_USERS["toll_operator_headers"]
CLERK = TEST_USERS["interop_clerk_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def test_duplicate_transponder_serial_rejected(api):
    """PRD §3.3: "The serial must be unique across all transponders in the system; a
    duplicate is rejected with `ERR_DUPLICATE_SERIAL` (HTTP 409)."

    Design: Corner/validations/duplicate_transponder_serial_rejected
    """
    account = create_account(holder_name="Du")
    create_transponder(account["id"], "TP-DUP")
    res = api.create_transponder({"account_id": account["id"], "serial": "TP-DUP"}, OP)
    validate_error(res, "ERR_DUPLICATE_SERIAL", expected_status=409)


def test_invalid_occupancy_zero_rejected(api):
    """PRD §3.5: "`declared_occupants`, the number of people in the vehicle, which must
    be at least 1; a value below 1 is rejected with `ERR_INVALID_OCCUPANCY` (HTTP 422)."

    Design: Corner/validations/invalid_occupancy_zero_rejected
    """
    account = create_account(holder_name="Oc")
    vehicle = create_vehicle(account["id"], plate_number="OC1", hov_capable=True)
    res = api.create_hov_window(create_hov_window_payload(
        vehicle["id"], "2026-03-05T07:00:00Z", "2026-03-05T09:00:00Z", 0),
        make_account_holder_headers(account["id"]))
    validate_error(res, "ERR_INVALID_OCCUPANCY", expected_status=422)


def test_interop_agency_inactive_rejected_at_post(api):
    """PRD §3.9: "Interop posting is only accepted when the referenced agency's `active`
    flag is true; a posting against an inactive agency is rejected with
    `ERR_INTEROP_AGENCY_INACTIVE` (HTTP 409)."

    Design: Corner/validations/interop_agency_inactive_rejected_at_post
    """
    agency = create_interop_agency(name="Old", state_code="PA", active=False)
    account = create_account(holder_name="In")
    create_vehicle(account["id"], plate_number="IN1")
    plaza = create_plaza(name="Pin", state_code="PA", base_rate_cents=400)
    res = api.create_toll_transaction({
        "plaza_id": plaza["id"], "read_method": "PLATE", "read_at": "2026-03-06T08:00:00Z",
        "is_peak": False, "declared_axles": 2, "plate_number": "IN1", "plate_state_code": "NY",
        "interop_agency_id": agency["id"]}, CLERK)
    validate_error(res, "ERR_INTEROP_AGENCY_INACTIVE")


def test_close_account_with_balance_rejected(api):
    """PRD §3.2: "An operator may close an account only from `SUSPENDED`, and only when
    both `balance_cents` is exactly 0 and `outstanding_fines_cents` is exactly 0; a close
    attempt that violates either condition is rejected with `ERR_BALANCE_NONZERO`
    (HTTP 409)."

    Design: Corner/validations/close_account_with_balance_rejected
    """
    account = create_account(holder_name="Cb")
    credit_account(account["id"], 500)
    api.suspend_account(account["id"], OP)
    res = api.close_account(account["id"], OP)
    validate_error(res, "ERR_BALANCE_NONZERO")


def test_violation_not_eligible_transponder_read(api):
    """PRD §3.8: "A violation may be opened only on a transaction that is `PRICED`, still
    `UNSETTLED`, and was a `PLATE` read; an attempt against any transaction not meeting
    all three conditions is rejected with `ERR_NOT_VIOLATION_ELIGIBLE` (HTTP 409)."

    Design: Corner/validations/violation_not_eligible_transponder_read
    """
    account = create_account(holder_name="Ne")
    credit_account(account["id"], 5000)
    vehicle = create_vehicle(account["id"], plate_number="NE1")
    transponder = create_transponder(account["id"], "TP-NE")
    bind_transponder(account["id"], transponder["id"], vehicle["id"], vehicle["version"])
    plaza = create_plaza(base_rate_cents=400)
    txn = record_transponder_read(plaza["id"], transponder["id"], "2026-03-07T03:00:00Z",
                                  is_peak=False)
    price(txn["id"])  # transponder read auto-settles
    res = api.create_violation({"toll_transaction_id": txn["id"]}, OP)
    validate_error(res, "ERR_NOT_VIOLATION_ELIGIBLE")


def test_unresolved_plate_read_price_rejected(api):
    """PRD §3.6: "It first requires that `account_id` is resolved; pricing a transaction
    whose account and vehicle could not be resolved is rejected with
    `ERR_UNRESOLVED_READ` (HTTP 409)."

    Design: Corner/validations/unresolved_plate_read_price_rejected
    """
    plaza = create_plaza(name="Pun", base_rate_cents=400)
    txn = record_plate_read(plaza["id"], "GHOST", "NY", "2026-03-08T08:00:00Z",
                            is_peak=False, declared_axles=2)
    res = api.price_toll_transaction(txn["id"], OP)
    validate_error(res, "ERR_UNRESOLVED_READ")


def test_insufficient_balance_on_violation_pay(api):
    """PRD §3.8: "provided the account's `balance_cents` is greater than or equal to
    `fine_total_cents`; an underfunded payment is rejected with
    `ERR_INSUFFICIENT_BALANCE` (HTTP 402)."

    Design: Corner/errors/insufficient_balance_on_violation_pay
    """
    account, vehicle, plaza, txn, viol = setup_plate_violation(plate_number="IB1")
    # zero balance, fine_total = 3250
    res = api.pay_violation(viol["id"], make_account_holder_headers(account["id"]))
    validate_error(res, "ERR_INSUFFICIENT_BALANCE", expected_status=402)


def test_validation_bad_enum_read_method(api):
    """PRD §2.9: "the structural body check — valid JSON, required fields present, enum
    values legal, numeric constraints satisfied, else `ERR_VALIDATION` (422)."
    PRD §3.6: "a `read_method` of either `TRANSPONDER` or `PLATE`".

    Design: Corner/errors/validation_bad_enum_read_method
    """
    plaza = create_plaza(name="Pbe", base_rate_cents=400)
    res = api.create_toll_transaction({
        "plaza_id": plaza["id"], "read_method": "SATELLITE",
        "read_at": "2026-03-12T08:00:00Z", "is_peak": False}, OP)
    validate_error(res, "ERR_VALIDATION", expected_status=422)
