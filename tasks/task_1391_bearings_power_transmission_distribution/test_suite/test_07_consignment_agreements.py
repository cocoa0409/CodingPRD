"""Consignment agreement lifecycle: placement, consumption reporting,
suspend/resume, close guards, amendment guards, and identity checks."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_product, create_branch, create_customer, create_branch_stock,
    create_agreement, report_consumption, invoice_consumption,
    get_agreement, get_branch_stock, get_customer, get_consumption,
    make_customer_plant_headers,
    ApiErrorId, TEST_USERS,
)

CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def _setup_agreement_with_invoiced_consumption():
    """Stock 100; agreement consigned 30; consumption qty 10 invoiced."""
    product = create_product(sku="BRG-6210", list_price_cents=4000)
    branch = create_branch(code="TUL-16")
    customer = create_customer(name="Plains Plant")
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=100)
    agreement = create_agreement(customer["id"], branch["id"], product["id"],
                                 consigned_qty=30)
    consumption = report_consumption(agreement["id"], 10, customer["id"])
    consumption = invoice_consumption(consumption["id"])
    return {"product": product, "branch": branch, "customer": customer,
            "stock": stock, "agreement": agreement, "consumption": consumption}


def test_consignment_placement_consumption_credit_stock_sum_invariant(api):
    """PRD §3.5: "Placement requires `available_qty` on the branch's stock
    record for this product to be at least `consigned_qty`
    (`ERR_INSUFFICIENT_AVAILABLE_STOCK`, 409); the shelf `on_hand_qty` then
    decreases by `consigned_qty` as the units physically move to the customer
    site."
    PRD §3.5: "the agreement's `consumed_qty` recomputes excluding `CREDITED`
    consumptions, so `remaining_qty` is restored."

    Design: Difficulty/compensating_invariant/consignment_stock_sum_invariant
    """
    ctx = _setup_agreement_with_invoiced_consumption()
    stock = get_branch_stock(ctx["stock"]["id"])
    agreement = get_agreement(ctx["agreement"]["id"])
    # After placement: 100 - 30 = 70 on the shelf, 30 at the customer plant.
    assert stock["on_hand_qty"] == 70
    # After invoicing 10 consumed: 30 - 10 = 20 remaining.
    assert agreement["remaining_qty"] == 20, (
        f"consumed 10 of 30; expected remaining 20, got {agreement['remaining_qty']}")

    credited = validate_success(
        api.credit_consumption(ctx["consumption"]["id"], MANAGER), 200)
    assert credited["status"] == "CREDITED"
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["remaining_qty"] == 30, (
        f"credit restores remaining; got {agreement['remaining_qty']}")
    assert get_branch_stock(ctx["stock"]["id"])["on_hand_qty"] == 70, (
        "crediting a consumption restores consignment quantity, not shelf stock")


def test_consignment_close_returns_unconsumed_stock_to_shelf(api):
    """PRD §3.5: "Closing requires `ACTIVE` or `SUSPENDED`
    (`ERR_AGREEMENT_NOT_CLOSABLE`, 409) and requires that no consumptions
    remain in `REPORTED` or `DISPUTED` status (`ERR_AGREEMENT_CLOSE_BLOCKED`,
    409); on close the unconsumed `remaining_qty` returns to the branch shelf,
    increasing `on_hand_qty`."

    Design: Difficulty/compensating_invariant/consignment_stock_sum_invariant
    """
    ctx = _setup_agreement_with_invoiced_consumption()
    validate_success(api.credit_consumption(ctx["consumption"]["id"], MANAGER), 200)
    closed = validate_success(
        api.close_agreement(ctx["agreement"]["id"], CONTRACT_ADMIN), 200)
    assert closed["status"] == "CLOSED"
    stock = get_branch_stock(ctx["stock"]["id"])
    assert stock["on_hand_qty"] == 100, (
        f"70 + 30 returned = 100; got {stock['on_hand_qty']}")
    customer = get_customer(ctx["customer"]["id"])
    assert customer["open_receivables_cents"] == 0, (
        "invoice +40000 then credit -40000 nets to zero")


def test_consignment_suspend_blocks_then_resume_allows_consumption(api):
    """PRD §3.5: "The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`,
    409); a suspended agreement blocks new consumption reports."
    PRD §3.5: "resuming requires `SUSPENDED` (`ERR_AGREEMENT_NOT_SUSPENDED`,
    409) and returns to `ACTIVE`."

    Design: Corner/state_machines/consignment_suspend_blocks_then_resume_allows_consumption
    """
    product = create_product(sku="BRG-6015", list_price_cents=1000)
    branch = create_branch(code="SUS-05")
    customer = create_customer(name="Suspend Plant", credit_limit_cents=1000000)
    create_branch_stock(branch["id"], product["id"], on_hand_qty=10)
    agreement = create_agreement(customer["id"], branch["id"], product["id"],
                                 consigned_qty=10)
    validate_success(api.suspend_agreement(agreement["id"], CONTRACT_ADMIN), 200)
    res = api.report_consumption(agreement["id"], {"qty": 1},
                                 make_customer_plant_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, expected_status=409)
    validate_success(api.resume_agreement(agreement["id"], CONTRACT_ADMIN), 200)
    consumption = report_consumption(agreement["id"], 1, customer["id"])
    assert consumption["status"] == "REPORTED"
    assert get_agreement(agreement["id"])["remaining_qty"] == 9


def test_agreement_close_blocked_by_unbilled_consumption(api):
    """PRD §3.5: "Closing requires `ACTIVE` or `SUSPENDED`
    (`ERR_AGREEMENT_NOT_CLOSABLE`, 409) and requires that no consumptions
    remain in `REPORTED` or `DISPUTED` status (`ERR_AGREEMENT_CLOSE_BLOCKED`,
    409); on close the unconsumed `remaining_qty` returns to the branch shelf,
    increasing `on_hand_qty`."

    Design: Corner/state_machines/agreement_close_blocked_by_unbilled_consumption
    """
    product = create_product(sku="BRG-6016", list_price_cents=1000)
    branch = create_branch(code="BLK-06")
    customer = create_customer(name="Block Plant", credit_limit_cents=1000000)
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=10)
    agreement = create_agreement(customer["id"], branch["id"], product["id"],
                                 consigned_qty=5)
    consumption = report_consumption(agreement["id"], 2, customer["id"])

    res = api.close_agreement(agreement["id"], CONTRACT_ADMIN)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_CLOSE_BLOCKED, expected_status=409)

    invoice_consumption(consumption["id"])
    closed = validate_success(api.close_agreement(agreement["id"], CONTRACT_ADMIN), 200)
    assert closed["status"] == "CLOSED"
    # 10 - 5 placed = 5 on shelf; remaining 3 returns on close -> 8.
    assert get_branch_stock(stock["id"])["on_hand_qty"] == 8


def test_dispute_requires_invoiced_consumption(api):
    """PRD §3.5: "A `CustomerPlant` may dispute an `INVOICED` consumption of
    its own account (`ERR_CONSUMPTION_NOT_INVOICED`, 409 if not invoiced;
    `ERR_IDENTITY_MISMATCH` if another customer's), moving it to `DISPUTED`."

    Design: Corner/state_machines/dispute_requires_invoiced_consumption
    """
    product = create_product(sku="BRG-6017", list_price_cents=1000)
    branch = create_branch(code="DSP-07")
    customer = create_customer(name="Dispute Plant", credit_limit_cents=1000000)
    create_branch_stock(branch["id"], product["id"], on_hand_qty=10)
    agreement = create_agreement(customer["id"], branch["id"], product["id"],
                                 consigned_qty=5)
    consumption = report_consumption(agreement["id"], 1, customer["id"])
    res = api.dispute_consumption(
        consumption["id"], make_customer_plant_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_CONSUMPTION_NOT_INVOICED, expected_status=409)
    assert get_consumption(consumption["id"])["status"] == "REPORTED"


def test_consumption_qty_exceeds_remaining(api):
    """PRD §3.5: "The quantity must be at least 1 and no more than the
    agreement's `remaining_qty` (`ERR_CONSUMPTION_EXCEEDS_REMAINING`, 409)."

    Design: Corner/validations/consumption_qty_exceeds_remaining
    """
    product = create_product(sku="BRG-6028", list_price_cents=1000)
    branch = create_branch(code="REM-17")
    customer = create_customer(name="Remaining Plant", credit_limit_cents=1000000)
    create_branch_stock(branch["id"], product["id"], on_hand_qty=5)
    agreement = create_agreement(customer["id"], branch["id"], product["id"],
                                 consigned_qty=5)
    report_consumption(agreement["id"], 3, customer["id"])  # remaining 2

    res = api.report_consumption(agreement["id"], {"qty": 3},
                                 make_customer_plant_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_CONSUMPTION_EXCEEDS_REMAINING,
                   expected_status=409)
    consumption = report_consumption(agreement["id"], 2, customer["id"])
    assert consumption["status"] == "REPORTED"
    assert get_agreement(agreement["id"])["remaining_qty"] == 0


def test_agreement_amend_below_consumed_rejected(api):
    """PRD §3.5: "The new quantity must be at least the current `consumed_qty`
    (`ERR_CONSIGNMENT_QTY_BELOW_CONSUMED`, 409); the shelf `on_hand_qty`
    adjusts by the delta, `remaining_qty` recomputes, and the agreement's
    `version` bumps."

    Design: Corner/validations/agreement_amend_below_consumed_rejected
    """
    product = create_product(sku="BRG-6031", list_price_cents=1000)
    branch = create_branch(code="AMD-19")
    customer = create_customer(name="Amend Plant", credit_limit_cents=1000000)
    create_branch_stock(branch["id"], product["id"], on_hand_qty=20)
    agreement = create_agreement(customer["id"], branch["id"], product["id"],
                                 consigned_qty=10)
    report_consumption(agreement["id"], 4, customer["id"])  # consumed 4
    fresh = get_agreement(agreement["id"])
    res = api.amend_consignment_agreement(
        agreement["id"],
        {"consigned_qty": 3, "expected_agreement_version": fresh["version"]},
        CONTRACT_ADMIN)
    validate_error(res, ApiErrorId.ERR_CONSIGNMENT_QTY_BELOW_CONSUMED,
                   expected_status=409)
    assert get_agreement(agreement["id"])["consigned_qty"] == 10


def test_identity_mismatch_on_foreign_customer_consumption(api):
    """PRD §2.1: "An entity-backed role acting on a resource owned by a
    different entity is rejected with `ERR_IDENTITY_MISMATCH` (HTTP 403) — this
    guards a `CustomerPlant` reporting consumption on another customer's
    agreement".

    Design: Corner/errors/identity_mismatch_on_foreign_customer_consumption
    """
    product = create_product(sku="BRG-6045", list_price_cents=1000)
    branch = create_branch(code="IDM-32")
    customer_a = create_customer(name="Owner Plant", credit_limit_cents=1000000)
    customer_b = create_customer(name="Stranger Plant", credit_limit_cents=1000000)
    create_branch_stock(branch["id"], product["id"], on_hand_qty=10)
    agreement = create_agreement(customer_a["id"], branch["id"], product["id"],
                                 consigned_qty=5)
    res = api.report_consumption(
        agreement["id"], {"qty": 1}, make_customer_plant_headers(customer_b["id"]))
    validate_error(res, ApiErrorId.ERR_IDENTITY_MISMATCH, expected_status=403)
