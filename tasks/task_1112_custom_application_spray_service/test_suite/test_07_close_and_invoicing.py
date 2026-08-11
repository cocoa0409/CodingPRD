"""Work-order closing gates and the invoice settlement ledger."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_neighbor_customer, create_rinsate_record_payload,
    create_drift_complaint_payload, certify_record,
    completed_environment, certified_environment,
    make_applicator_headers, make_grower_headers,
    EXPECTED, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def _dispose_all(env, volume=24.0):
    validate_success(api_client.create_rinsate_record(
        create_rinsate_record_payload(env["work_order"]["id"],
                                      "CONTAINMENT_DISPOSAL", volume,
                                      manifest_no="MAN-9"),
        make_applicator_headers(env["applicator"]["id"])), 201)


def test_close_gate_progression_record_then_invoice(api):
    """PRD §3.7: "Three conditions must all hold: the ApplicationRecord for the
    work order is `CERTIFIED` (else `ERR_RECORD_NOT_CERTIFIED`), the
    `rinsate_balance_gal` has been disposed down to exactly zero (else
    `ERR_RINSATE_BALANCE_OPEN`), and the work order's invoice is settled —
    `PAID` or `VOIDED` (else `ERR_INVOICE_UNSETTLED`)."
    PRD §2.9: state preconditions (category 6, surfacing
    `ERR_RECORD_NOT_CERTIFIED`) are evaluated before domain constraints
    (category 9, surfacing `ERR_RINSATE_BALANCE_OPEN` / `ERR_INVOICE_UNSETTLED`).

    Design: Corner/validations/close_gate_progression
    """
    env = completed_environment()
    wo_id = env["work_order"]["id"]

    # Record SUBMITTED (and rinsate open, invoice DRAFT): the state gate wins.
    res1 = api_client.close_work_order(wo_id, DISPATCHER)
    validate_error(res1, "ERR_RECORD_NOT_CERTIFIED", expected_status=409)

    # Rinsate disposed; still SUBMITTED record + DRAFT invoice: state gate again.
    _dispose_all(env)
    res2 = api_client.close_work_order(wo_id, DISPATCHER)
    validate_error(res2, "ERR_RECORD_NOT_CERTIFIED", expected_status=409)

    # Record certified; only the invoice gate remains.
    certify_record(env["record"]["id"])
    res3 = api_client.close_work_order(wo_id, DISPATCHER)
    validate_error(res3, "ERR_INVOICE_UNSETTLED", expected_status=409)

    validate_success(api_client.issue_invoice(env["invoice"]["id"], ADMIN), 200)
    validate_success(api_client.pay_invoice(
        env["invoice"]["id"], make_grower_headers(env["customer"]["id"])), 200)
    closed = validate_success(api_client.close_work_order(wo_id, DISPATCHER), 200)
    assert closed["status"] == "CLOSED"


def test_close_gate_rinsate_balance_open(api):
    """PRD §3.7: "the `rinsate_balance_gal` has been disposed down to exactly
    zero (else `ERR_RINSATE_BALANCE_OPEN`)"

    Design: Corner/validations/close_gate_progression
    """
    env = certified_environment()
    wo_id = env["work_order"]["id"]
    validate_success(api_client.issue_invoice(env["invoice"]["id"], ADMIN), 200)
    validate_success(api_client.pay_invoice(
        env["invoice"]["id"], make_grower_headers(env["customer"]["id"])), 200)

    # Record CERTIFIED and invoice PAID; only the rinsate gate can fail.
    res = api_client.close_work_order(wo_id, DISPATCHER)
    validate_error(res, "ERR_RINSATE_BALANCE_OPEN", expected_status=409)

    _dispose_all(env)
    closed = validate_success(api_client.close_work_order(wo_id, DISPATCHER), 200)
    assert closed["status"] == "CLOSED"


def test_invoice_issue_blocked_by_open_complaint(api):
    """PRD §3.9: "no complaint on the work order may be `FILED` or
    `INVESTIGATING` (else `ERR_COMPLAINT_HOLD`)"

    Design: Corner/validations/invoice_issue_blocked_by_open_complaint
    """
    env = certified_environment(num_products=1)
    neighbor = create_neighbor_customer()
    validate_success(api_client.create_drift_complaint(
        create_drift_complaint_payload(env["work_order"]["id"],
                                       description="drift reported"),
        make_grower_headers(neighbor["id"])), 201)

    res = api_client.issue_invoice(env["invoice"]["id"], ADMIN)
    validate_error(res, "ERR_COMPLAINT_HOLD", expected_status=409)
    invoice = get_success_data(api.get_invoice(env["invoice"]["id"], ADMIN))
    assert invoice["status"] == "DRAFT", "held issue leaves the invoice DRAFT"


def test_invoice_issue_before_certification_rejected(api):
    """PRD §3.9: "the work order's application record must be `CERTIFIED` so
    that `final_amount_cents` exists (else `ERR_RECORD_NOT_CERTIFIED`)"

    Design: Corner/validations/invoice_issue_before_certification_rejected
    """
    env = completed_environment(num_products=1)
    res = api_client.issue_invoice(env["invoice"]["id"], ADMIN)
    validate_error(res, "ERR_RECORD_NOT_CERTIFIED", expected_status=409)


def test_grower_cannot_pay_others_invoice(api):
    """PRD §3.9: "Only the invoice's own grower may pay: the caller's
    `X-User-ID` must equal the `customer_id` of the work order behind the
    invoice, else `ERR_FORBIDDEN`."

    Design: Corner/rbac/grower_cannot_pay_others_invoice
    """
    env = certified_environment(num_products=1)
    neighbor = create_neighbor_customer()
    validate_success(api_client.issue_invoice(env["invoice"]["id"], ADMIN), 200)

    res = api_client.pay_invoice(env["invoice"]["id"], make_grower_headers(neighbor["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
    invoice = get_success_data(api.get_invoice(env["invoice"]["id"], ADMIN))
    assert invoice["status"] == "ISSUED", "rejected payment leaves the invoice ISSUED"


def test_outstanding_reconciles_on_pay(api):
    """PRD §2.10: "Issuing an invoice debits the balance by its
    `final_amount_cents`; paying an issued invoice credits it back"
    PRD §2.10: "at any moment it equals the sum of `final_amount_cents` over
    that customer's invoices currently in `ISSUED` status."

    Design: Corner/cross_cutting_complexity_layers/outstanding_reconciles_on_pay
    """
    env = certified_environment(num_products=1)
    invoice = env["invoice"]
    assert invoice["final_amount_cents"] == EXPECTED["SINGLE_PRODUCT_100AC"], \
        f"expected final 945000 (120000 service + 825000 product), got {invoice['final_amount_cents']}"

    validate_success(api_client.issue_invoice(invoice["id"], ADMIN), 200)
    customer = get_success_data(api.get_customer(env["customer"]["id"], ADMIN))
    assert customer["outstanding_cents"] == EXPECTED["SINGLE_PRODUCT_100AC"]

    paid = validate_success(api_client.pay_invoice(
        invoice["id"], make_grower_headers(env["customer"]["id"])), 200)
    assert paid["status"] == "PAID"
    customer = get_success_data(api.get_customer(env["customer"]["id"], ADMIN))
    assert customer["outstanding_cents"] == 0, "pay returns the balance to zero"


def test_outstanding_credit_issue_void_neutral(api):
    """PRD §2.10: "Issuing an invoice debits the balance by its
    `final_amount_cents`; paying an issued invoice credits it back; voiding an
    issued invoice credits it back as well."

    Design: Difficulty/compensating_invariant/outstanding_credit_issue_void_neutral
    """
    env = certified_environment(actual_rates={"p1": 1.6, "p2": 0.4})
    invoice = env["invoice"]
    assert invoice["final_amount_cents"] == EXPECTED["FINAL_100AC_P1_1_6"]
    customer = get_success_data(api.get_customer(env["customer"]["id"], ADMIN))
    assert customer["outstanding_cents"] == 0

    issued = validate_success(api_client.issue_invoice(invoice["id"], ADMIN), 200)
    assert issued["status"] == "ISSUED"
    customer = get_success_data(api.get_customer(env["customer"]["id"], ADMIN))
    assert customer["outstanding_cents"] == EXPECTED["FINAL_100AC_P1_1_6"]

    voided = validate_success(api_client.void_invoice(invoice["id"], ADMIN), 200)
    assert voided["status"] == "VOIDED"
    customer = get_success_data(api.get_customer(env["customer"]["id"], ADMIN))
    assert customer["outstanding_cents"] == 0, \
        "issue + void leaves the conserved outstanding balance unchanged"


def test_void_draft_invoice_has_no_balance_effect(api):
    """PRD §3.9: "A `DRAFT` invoice moves to the terminal `VOIDED` state with
    no balance effect at all — it never debited anything."
    PRD §2.10: "Voiding a `DRAFT` invoice changes nothing, because a draft was
    never part of the sum."

    Design: Difficulty/compensating_invariant/outstanding_credit_issue_void_neutral
    """
    env = completed_environment()
    voided = validate_success(api_client.void_invoice(env["invoice"]["id"], ADMIN), 200)
    assert voided["status"] == "VOIDED"
    customer = get_success_data(api.get_customer(env["customer"]["id"], ADMIN))
    assert customer["outstanding_cents"] == 0
