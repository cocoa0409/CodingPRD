"""Progress/PTO billing variants, parallel payment and fulfillment
dimensions, and payment post/reverse invariants."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_container_line,
    allocate_current_version,
    api_client,
    approve_permit_for_project,
    book_container,
    create_active_installer,
    create_locked_project,
    get_lot,
    receive_container,
    seed_catalog,
    set_clock,
    setup_paid_in_full_project,
    setup_shipped_project,
    ship_allocation,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_installer_rep_headers

MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _two_product_shipped_project():
    """Module 10 x 50000c declared (10% duty) plus inverter 1 x 250000c
    declared (5% duty) on one container with freight 50000c and insurance
    10000c; installer at 80% progress. Final unit costs: module 59000c,
    inverter 282500c; allocated value 872500c."""
    set_clock()
    catalog = seed_catalog(min_modules=10, max_modules=20)
    installer = create_active_installer(credit_limit_cents=10000000,
                                        progress_payment_pct_bp=8000)
    project = create_locked_project(
        installer["id"], catalog["module"]["id"], catalog["inverter"]["id"],
        module_qty=10, inverter_qty=1,
    )
    container = book_container(freight_cost_cents=50000,
                               insurance_cost_cents=10000)
    line_mod = add_container_line(container["id"], catalog["module"]["id"],
                                  10, 50000)
    line_inv = add_container_line(container["id"], catalog["inverter"]["id"],
                                  1, 250000)
    receive_container(container["id"], [
        {"container_line_id": line_mod["id"], "qty_received": 10,
         "qty_damaged": 0},
        {"container_line_id": line_inv["id"], "qty_received": 1,
         "qty_damaged": 0},
    ])
    inst_id = installer["id"]
    alloc_mod = allocate_current_version(project["id"], inst_id,
                                         line_mod["inventory_lot_id"], 10)
    alloc_inv = allocate_current_version(project["id"], inst_id,
                                         line_inv["inventory_lot_id"], 1)
    ship_allocation(alloc_mod["id"])
    ship_allocation(alloc_inv["id"])
    invoices = validate_success(
        api_client.list_project_invoices(
            project["id"], MANAGER, params={"invoice_kind": "PROGRESS"}
        ),
        200,
    )
    assert len(invoices) == 1
    return {
        **catalog, "installer": installer, "project": project,
        "alloc_mod": alloc_mod, "alloc_inv": alloc_inv,
        "progress_invoice": invoices[0],
    }


def test_progress_invoice_amount_at_ship(api):
    """PRD section 3.7: "The invoice's `amount_cents` is the project's
    `allocated_value_cents` at issue time — computed from shipped
    allocations' frozen `unit_cost_cents_at_allocation` values, each of which
    reflects the lot's final unit cost when set and its provisional cost
    otherwise — multiplied by the installer's `progress_payment_pct_bp` and
    divided by ten thousand, rounded half up to a whole cent."
    Allocated value is 10 x 59000 + 1 x 282500 = 872500; the progress invoice
    at 8000 bp is 698000.

    Design: Difficulty/dual_variant_calc/progress_vs_pto_invoice_split_reconciles_to_avc
    """
    ctx = _two_product_shipped_project()
    project = validate_success(
        api_client.get_project(ctx["project"]["id"], MANAGER), 200
    )
    assert project["allocated_value_cents"] == 872500
    assert project["payment_status"] == "PROGRESS_BILLED"
    assert project["fulfillment_status"] == "SHIPPED"

    invoice = ctx["progress_invoice"]
    assert invoice["invoice_kind"] == "PROGRESS"
    assert invoice["amount_cents"] == 698000, (
        f"PROGRESS amount must be 80% of 872500 = 698000, "
        f"got {invoice['amount_cents']}"
    )


def test_pto_invoice_is_remainder_reconciling_to_avc(api):
    """PRD section 3.7: "The PTO amount is the remainder — the project's
    `allocated_value_cents` minus the progress invoice amount — not a second
    percentage computation, so the two invoices sum exactly to the allocated
    value and any rounding residue lands on the PTO invoice."
    872500 - 698000 = 174500, and 698000 + 174500 = 872500 exactly.

    Design: Difficulty/dual_variant_calc/progress_vs_pto_invoice_split_reconciles_to_avc
    """
    ctx = _two_product_shipped_project()
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]

    approve_permit_for_project(proj_id, inst_id)
    validate_success(api_client.invoice_pto(proj_id, MANAGER), 200)

    pto_invoices = validate_success(
        api_client.list_project_invoices(proj_id, MANAGER,
                                         params={"invoice_kind": "PTO"}),
        200,
    )
    assert len(pto_invoices) == 1
    pto = pto_invoices[0]
    progress = validate_success(
        api_client.get_invoice(ctx["progress_invoice"]["id"], MANAGER), 200
    )
    assert pto["amount_cents"] == 174500, (
        f"PTO amount must be the remainder 872500 - 698000 = 174500, "
        f"got {pto['amount_cents']}"
    )
    assert progress["amount_cents"] + pto["amount_cents"] == 872500

    project = validate_success(api_client.get_project(proj_id, MANAGER), 200)
    assert project["payment_status"] == "PTO_BILLED"


def test_paid_in_full_while_fulfillment_still_shipped(api):
    """PRD section 3.7: "from `PTO_BILLED` it advances to `PAID_IN_FULL` when
    the posted payments across all of the project's invoices equal
    `invoiced_value_cents` and that invoiced value is greater than zero."
    The payment dimension can close while fulfillment remains SHIPPED — the
    two dimensions evolve independently. Here 10 modules land at 55000c each
    (allocated value 550000), so at 50% the PROGRESS and PTO invoices are
    275000 each.

    Design: Difficulty/non_linear_state_machine/project_parallel_payment_and_fulfillment_dimensions
    """
    ctx = setup_paid_in_full_project(module_qty=10, lot_qty=10,
                                     progress_payment_pct_bp=5000)
    project = ctx["project"]
    assert project["payment_status"] == "PAID_IN_FULL", (
        f"both invoices fully paid must advance payment_status, "
        f"got {project['payment_status']}"
    )
    assert project["fulfillment_status"] == "SHIPPED", (
        f"fulfillment is independent of payment, got "
        f"{project['fulfillment_status']}"
    )
    assert project["allocated_value_cents"] == 550000
    assert project["paid_value_cents"] == 550000


def test_complete_after_both_dimensions_aligned(api):
    """PRD section 3.8: "It requires `fulfillment_status` `SHIPPED`,
    `payment_status` `PAID_IN_FULL` — failing with `ERR_UNPAID_BALANCE` while
    any balance stands — and an `APPROVED` permit package, failing with
    `ERR_PERMIT_NOT_APPROVED` otherwise. On success the project's
    `fulfillment_status` moves `SHIPPED` → `COMPLETE`, terminal."

    Design: Difficulty/non_linear_state_machine/project_parallel_payment_and_fulfillment_dimensions
    """
    ctx = setup_paid_in_full_project(module_qty=10, lot_qty=10,
                                     progress_payment_pct_bp=5000)
    proj_id = ctx["project"]["id"]
    completed = validate_success(
        api_client.complete_project(
            proj_id, make_installer_rep_headers(ctx["installer"]["id"])
        ),
        200,
    )
    assert completed["fulfillment_status"] == "COMPLETE"
    assert completed["payment_status"] == "PAID_IN_FULL"


def test_payment_then_reverse_restores_balance(api):
    """PRD section 3.7: "The first partial payment moves the invoice `OPEN` →
    `PARTIALLY_PAID`" and "A reversal stamps `reversed_at`, moves the payment
    to `REVERSED`, terminal, adds its amount back to the invoice's
    `balance_due_cents`, reverts an invoice that had been `PAID` to
    `PARTIALLY_PAID` or `OPEN` according to the remaining balance, and
    recomputes the installer's `credit_exposure_cents`, the project's
    `paid_value_cents`, and the project's `payment_status`."

    Design: Difficulty/compensating_invariant/payment_post_then_reverse_preserves_invoice_balance
    """
    ctx = setup_shipped_project(module_qty=5, lot_qty=5,
                                progress_payment_pct_bp=10000)
    invoice = ctx["progress_invoice"]
    assert invoice["amount_cents"] == 275000
    assert invoice["balance_due_cents"] == 275000

    payment = validate_success(
        api_client.post_payment(invoice["id"], {"amount_cents": 100000},
                                OFFICER),
        201,
    )
    assert payment["status"] == "POSTED"

    during = validate_success(api_client.get_invoice(invoice["id"], OFFICER), 200)
    assert during["balance_due_cents"] == 175000
    assert during["status"] == "PARTIALLY_PAID"

    reversed_payment = validate_success(
        api_client.reverse_payment(payment["id"], OFFICER), 200
    )
    assert reversed_payment["status"] == "REVERSED"
    assert reversed_payment["reversed_at"] is not None

    after = validate_success(api_client.get_invoice(invoice["id"], OFFICER), 200)
    assert after["balance_due_cents"] == 275000, (
        f"reversal must restore the balance to 275000, "
        f"got {after['balance_due_cents']}"
    )


def test_partial_payments_then_reverse_one_restores_balance(api):
    """PRD section 3.7: "A posted payment stamps `posted_at`, holds status
    `POSTED`, and reduces the invoice's `balance_due_cents` by its amount."
    PRD section 3.7: "A reversal stamps `reversed_at`, moves the payment to
    `REVERSED`, terminal, adds its amount back to the invoice's
    `balance_due_cents`, reverts an invoice that had been `PAID` to
    `PARTIALLY_PAID` or `OPEN` according to the remaining balance, and
    recomputes the installer's `credit_exposure_cents`, the project's
    `paid_value_cents`, and the project's `payment_status`." Two partial
    payments (100000 + 75000) take the 275000 balance to 100000; reversing
    the second returns it to 175000 and the installer's exposure tracks the
    balance exactly.

    Design: Difficulty/compensating_invariant/payment_post_then_reverse_preserves_invoice_balance
    """
    ctx = setup_shipped_project(module_qty=5, lot_qty=5,
                                progress_payment_pct_bp=10000)
    inst_id = ctx["installer"]["id"]
    invoice = ctx["progress_invoice"]

    validate_success(
        api_client.post_payment(invoice["id"], {"amount_cents": 100000},
                                OFFICER),
        201,
    )
    second = validate_success(
        api_client.post_payment(invoice["id"], {"amount_cents": 75000},
                                OFFICER),
        201,
    )
    mid = validate_success(api_client.get_invoice(invoice["id"], OFFICER), 200)
    assert mid["balance_due_cents"] == 100000

    installer = validate_success(api_client.get_installer(inst_id, OFFICER), 200)
    assert installer["credit_exposure_cents"] == 100000

    validate_success(api_client.reverse_payment(second["id"], OFFICER), 200)
    after = validate_success(api_client.get_invoice(invoice["id"], OFFICER), 200)
    assert after["balance_due_cents"] == 175000

    installer = validate_success(api_client.get_installer(inst_id, OFFICER), 200)
    assert installer["credit_exposure_cents"] == 175000


def test_payment_to_nonexistent_invoice_returns_not_found(api):
    """PRD section 2.6: "The request is rejected immediately with a `404 Not
    Found` for the first identifier that does not resolve to an existing
    resource, before any later identifier — and before any business rule — is
    examined." Existence precedes every state and fiscal rule.

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_state_payment_to_nonexistent_invoice
    """
    resp = api_client.post_payment(
        NON_EXISTENT_UUID, {"amount_cents": 1000}, OFFICER
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)


def test_existence_precedes_payment_amount_validation(api):
    """PRD section 2.6: "The request is rejected immediately with a `404 Not
    Found` for the first identifier that does not resolve to an existing
    resource, before any later identifier — and before any business rule — is
    examined." Even a structurally invalid amount (0) on a non-existent
    invoice reports the not-found error, not the amount error.

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_state_payment_to_nonexistent_invoice
    """
    resp = api_client.post_payment(
        NON_EXISTENT_UUID, {"amount_cents": 0}, OFFICER
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)


def test_payment_exceeds_invoice_balance(api):
    """PRD section 3.7: "The amount must be greater than zero and no more than
    the invoice's current `balance_due_cents` at post time, failing with
    `ERR_INVALID_PAYMENT_AMOUNT` otherwise".

    Design: Corner/validations/payment_exceeds_invoice_balance
    """
    ctx = setup_shipped_project(module_qty=5, lot_qty=5,
                                progress_payment_pct_bp=10000)
    invoice = ctx["progress_invoice"]
    assert invoice["balance_due_cents"] == 275000

    resp = api_client.post_payment(
        invoice["id"], {"amount_cents": 999999999}, OFFICER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PAYMENT_AMOUNT)

    resp_zero = api_client.post_payment(
        invoice["id"], {"amount_cents": 0}, OFFICER
    )
    validate_error(resp_zero, ApiErrorId.ERR_INVALID_PAYMENT_AMOUNT)
