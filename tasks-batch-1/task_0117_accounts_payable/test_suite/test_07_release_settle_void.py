"""Release / settle / void / return and OCC on release (PRD §2.9, §3.6, §3.7).
Difficulty instances (settle cascade, segregation-beats-stale, payment-return and
payment-remove conservation, empty-batch boundary) get >=2 tests each.
"""
from test_helpers import (
    validate_success, validate_error,
    create_gl_account, create_vendor, create_approval_route,
    create_lined_invoice, code_invoice,
    setup_approved_non_po_invoice, setup_scheduled_payment,
    setup_released_batch, setup_settled_batch, setup_approved_three_way_invoice,
    open_batch, add_payment, release_batch, current_batch_version,
    api_client,
    TEST_USERS,
    make_clerk_headers, make_approver_headers, make_manager_headers,
)

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
APPROVER = TEST_USERS["approver_headers"]


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / occ_correct_version_release_succeeds
# ---------------------------------------------------------------------------
def test_occ_correct_version_release_succeeds(api):
    """PRD §2.9: "If that value does not equal the batch's current `version`, the
    release is rejected with `ERR_STALE_BATCH_VERSION`".
    PRD §3.6: "On release the batch records `released_by`, freezes its
    `total_disbursed_cents`, moves to `RELEASED`, bubbles every member invoice from
    `SCHEDULED` to `PAID`".

    Design: Corner/cross_cutting_layers/occ_correct_version_release_succeeds
    """
    vendor, invoice, batch, payment = setup_scheduled_payment(
        amount_cents=50000, clerk_id="CLERK1", approver_id="APV1", manager_id="MGR1")
    mgr = make_manager_headers("MGR1")
    bv = current_batch_version(batch["id"], mgr)
    resp = api.release_batch(batch["id"], {"expected_paymentbatch_version": bv}, mgr)
    data = validate_success(resp, 200)
    assert data["status"] == "RELEASED"
    inv_after = validate_success(api.get_invoice(invoice["id"], mgr), 200)
    assert inv_after["status"] == "PAID"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / occ_stale_version_release_rejected
# Two adds: capture version after first add, second add bumps it -> stale.
# ---------------------------------------------------------------------------
def test_occ_stale_version_release_rejected(api):
    """PRD §2.9: "the release request must include `expected_paymentbatch_version` as a
    required field carrying the `version` the client last observed for that batch. If
    that value does not equal the batch's current `version`, the release is rejected
    with `ERR_STALE_BATCH_VERSION` and an HTTP status of 412".

    Design: Corner/cross_cutting_layers/occ_stale_version_release_rejected
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Stale", payment_method="ACH")
    create_approval_route(min_amount_cents=0, max_amount_cents=1_000_000_000, required_levels=1)
    inv_ids = []
    clerk = make_clerk_headers("CLERK1")
    approver = make_approver_headers("APV1")
    for n in ("ST-A", "ST-B"):
        inv = create_lined_invoice(vendor["id"], 50000, invoice_number=n,
                                   invoice_date="2026-05-01", clerk_headers=clerk)
        code_invoice(inv["id"], headers=clerk)
        validate_success(api_client.submit_invoice_for_approval(inv["id"], clerk), 200)
        step = validate_success(api_client.list_invoice_approval_steps(inv["id"], MGR), 200)[0]
        validate_success(api_client.approve_step(step["id"], approver), 200)
        inv_ids.append(inv["id"])
    mgr = make_manager_headers("MGR1")
    batch = open_batch(payment_method="ACH", run_date="2026-05-10", headers=mgr)
    add_payment(batch["id"], inv_ids[0], headers=mgr)
    stale_version = current_batch_version(batch["id"], mgr)  # captured before 2nd add
    add_payment(batch["id"], inv_ids[1], headers=mgr)        # bumps version
    resp = api.release_batch(batch["id"], {"expected_paymentbatch_version": stale_version}, mgr)
    validate_error(resp, "ERR_STALE_BATCH_VERSION", 412)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / release_empty_batch_zero_count_rejected
# (>=2 tests.)
# ---------------------------------------------------------------------------
def test_release_empty_batch_rejected(api):
    """PRD §3.6: "requires the batch to hold at least one payment (an empty batch is
    rejected with `ERR_BATCH_EMPTY`)".

    Design: Difficulty/boundary_precision_check/release_empty_batch_zero_count_rejected
    """
    batch = open_batch(payment_method="ACH", run_date="2026-05-10")
    bv = current_batch_version(batch["id"])
    resp = api.release_batch(batch["id"], {"expected_paymentbatch_version": bv}, MGR)
    validate_error(resp, "ERR_BATCH_EMPTY", 409)


def test_release_succeeds_once_batch_has_one_payment(api):
    """PRD §3.6: "requires the batch to hold at least one payment (an empty batch is
    rejected with `ERR_BATCH_EMPTY`)".

    Design: Difficulty/boundary_precision_check/release_empty_batch_zero_count_rejected
    """
    # Boundary complement: exactly one payment (count 1) releases cleanly.
    vendor, invoice, batch, payment = setup_scheduled_payment(amount_cents=50000)
    bv = current_batch_version(batch["id"])
    resp = api.release_batch(batch["id"], {"expected_paymentbatch_version": bv}, MGR)
    data = validate_success(resp, 200)
    assert data["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / segregation_beats_stale_version_on_release
# Releaser U1 also coded the member invoice AND version is stale -> SEGREGATION wins.
# (>=2 tests.)
# ---------------------------------------------------------------------------
def _setup_self_coded_scheduled_batch():
    """U1 (clerk) codes; U2 approves; U1 (manager) opens batch and adds. Returns batch."""
    create_gl_account()
    vendor = create_vendor(legal_name="Acme", payment_method="ACH")
    create_approval_route(min_amount_cents=0, max_amount_cents=1_000_000_000, required_levels=1)
    clerk_u1 = make_clerk_headers("U1")
    inv = create_lined_invoice(vendor["id"], 50000, invoice_number="NP-SOD",
                               invoice_date="2026-05-01", clerk_headers=clerk_u1)
    code_invoice(inv["id"], headers=clerk_u1)
    validate_success(api_client.submit_invoice_for_approval(inv["id"], clerk_u1), 200)
    step = validate_success(api_client.list_invoice_approval_steps(inv["id"], MGR), 200)[0]
    validate_success(api_client.approve_step(step["id"], make_approver_headers("U2")), 200)
    mgr_u1 = make_manager_headers("U1")
    batch = open_batch(payment_method="ACH", run_date="2026-05-10", headers=mgr_u1)
    add_payment(batch["id"], inv["id"], headers=mgr_u1)
    return inv, batch


def test_segregation_of_duties_blocks_self_releaser(api):
    """PRD §3.6: "enforces segregation of duties: the releasing operator's `X-User-ID`
    must not equal the `coded_by` or `approved_by` of any member invoice, and a
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_stale_version_on_release
    """
    inv, batch = _setup_self_coded_scheduled_batch()
    bv = current_batch_version(batch["id"], make_manager_headers("U1"))
    resp = api.release_batch(batch["id"], {"expected_paymentbatch_version": bv},
                             make_manager_headers("U1"))
    validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", 403)


# DELETED: test_segregation_outranks_stale_version_on_release — ERROR PRECEDENCE
# SILENCE (STEP 1b). The test made the releaser both the coder (SoD violation)
# AND passed a stale version (0), asserting ERR_SEGREGATION_OF_DUTIES wins over
# ERR_STALE_BATCH_VERSION. Both are post-state Section-3 business rules; PRD §2.4
# orders auth/existence/validation/state vs business rules but does NOT rank
# business rules amongst themselves. The only ordering signal in the PRD prose is
# §3.6's textual sequence, which lists the OCC version check FIRST ("It requires
# the supplied expected_paymentbatch_version to match ... requires ... at least
# one payment ... and enforces segregation of duties"). A faithful PRD-only
# implementer therefore returns ERR_STALE_BATCH_VERSION, the opposite of the
# assertion. The PRD does not uniquely determine SoD-over-OCC. (SoD alone is still
# covered by test_segregation_of_duties_blocks_self_releaser; OCC-stale alone by
# test_occ_stale_version_release_rejected.) Scaffold rule that drove generation:
# validations priority 9 (SoD) vs priority 18 (OCC), a scaffold priority table
# that contradicts the PRD prose order.


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / settle_cascade_payment_then_vendor_ytd_depth3
# settle -> payment SETTLED -> vendor ytd recomputed. 1099 vendor, invoice 50000.
# (>=2 tests.)
# ---------------------------------------------------------------------------
def test_settle_cascades_payment_to_settled(api):
    """PRD §3.6: "**Settling** cascades each member payment's `settlement_status` from
    `PENDING` to `SETTLED` ... then moves the batch to `SETTLED`."

    Design: Difficulty/transitive_cascade/settle_cascade_payment_then_vendor_ytd_depth3
    """
    vendor, invoice, batch, payment = setup_released_batch(
        amount_cents=50000, run_date="2026-05-10",
        vendor_overrides={"legal_name": "Reportable", "payment_method": "ACH",
                          "is_1099": True, "tax_id": "12-3456789"})
    resp = api.settle_batch(batch["id"], MGR)
    data = validate_success(resp, 200)
    assert data["status"] == "SETTLED"
    pay_after = validate_success(api.get_payment(payment["id"], MGR), 200)
    assert pay_after["settlement_status"] == "SETTLED"


def test_settle_recomputes_vendor_ytd_1099(api):
    """PRD §3.6: "for each settled payment recomputes the recipient vendor's
    `ytd_1099_paid_cents` by adding the payment's net amount".

    Design: Difficulty/transitive_cascade/settle_cascade_payment_then_vendor_ytd_depth3
    """
    vendor, invoice, batch, payment = setup_released_batch(
        amount_cents=50000, run_date="2026-05-10",
        vendor_overrides={"legal_name": "Reportable", "payment_method": "ACH",
                          "is_1099": True, "tax_id": "12-3456789"})
    validate_success(api.settle_batch(batch["id"], MGR), 200)
    vendor_after = validate_success(api.get_vendor(vendor["id"], MGR), 200)
    assert vendor_after["ytd_1099_paid_cents"] == 50000


# ---------------------------------------------------------------------------
# Corner: state_machines / void_released_batch_reverts_invoices_to_approved
# ---------------------------------------------------------------------------
def test_void_released_batch_reverts_invoices_to_approved(api):
    """PRD §3.6: "**Voiding** is the compensating reverse of a release that has not yet
    settled: it cascades every member invoice from `PAID` back to `APPROVED`, deletes
    all member payments, drives the batch's `total_disbursed_cents` to 0, moves the
    batch to `VOID`".

    Design: Corner/state_machines/void_released_batch_reverts_invoices_to_approved
    """
    vendor, invoice, batch, payment = setup_released_batch(amount_cents=50000,
                                                           run_date="2026-05-20")
    resp = api.void_batch(batch["id"], MGR)
    data = validate_success(resp, 200)
    assert data["status"] == "VOID"
    assert data["total_disbursed_cents"] == 0
    inv_after = validate_success(api.get_invoice(invoice["id"], MGR), 200)
    assert inv_after["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / payment_return_conserves_vendor_ytd_1099
# settle (+50000) then return (-50000) -> ytd back to 0. (>=2 tests.)
# ---------------------------------------------------------------------------
def test_return_settled_payment_marks_returned(api):
    """PRD §3.6: "Returning is permitted only when the payment's `settlement_status` is
    `SETTLED` and its parent batch is `SETTLED`; it moves the payment's
    `settlement_status` to `RETURNED`, reverses the paid invoice from `PAID` back to
    `APPROVED`".

    Design: Difficulty/compensating_invariant/payment_return_conserves_vendor_ytd_1099
    """
    vendor, invoice, batch, payment = setup_settled_batch(
        amount_cents=50000, run_date="2026-06-30",
        vendor_overrides={"legal_name": "Reportable", "payment_method": "ACH",
                          "is_1099": True, "tax_id": "99-9999999"})
    resp = api.return_payment(payment["id"], MGR)
    data = validate_success(resp, 200)
    assert data["settlement_status"] == "RETURNED"
    inv_after = validate_success(api.get_invoice(invoice["id"], MGR), 200)
    assert inv_after["status"] == "APPROVED"


def test_return_conserves_vendor_ytd_1099(api):
    """PRD §3.6: "subtracts the payment's net amount from the vendor's
    `ytd_1099_paid_cents` to keep the year-to-date figure conserved".

    Design: Difficulty/compensating_invariant/payment_return_conserves_vendor_ytd_1099
    """
    vendor, invoice, batch, payment = setup_settled_batch(
        amount_cents=50000, run_date="2026-06-30",
        vendor_overrides={"legal_name": "Reportable", "payment_method": "ACH",
                          "is_1099": True, "tax_id": "99-9999999"})
    # After settle ytd is 50000; after return it must return to 0 (conserved).
    vendor_settled = validate_success(api.get_vendor(vendor["id"], MGR), 200)
    assert vendor_settled["ytd_1099_paid_cents"] == 50000
    validate_success(api.return_payment(payment["id"], MGR), 200)
    vendor_after = validate_success(api.get_vendor(vendor["id"], MGR), 200)
    assert vendor_after["ytd_1099_paid_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / payment_remove_conserves_po_matched_amount
# Schedule then DELETE -> invoice APPROVED, PO matched unchanged. (>=2 tests.)
# THREE_WAY invoice 100000, ordered 200000, received 100000 -> MATCHED, PO matched 100000.
# ---------------------------------------------------------------------------
def test_remove_payment_reverts_invoice_to_approved(api):
    """PRD §3.6: "Before release, the manager may remove a payment from a `BUILDING`
    batch. Removal deletes the payment, reverts its invoice from `SCHEDULED` back to
    `APPROVED`, recomputes the batch's `total_disbursed_cents`, increments the batch's
    `version` by one, and appends an `UNSCHEDULED` audit event."

    Design: Difficulty/compensating_invariant/payment_remove_conserves_po_matched_amount
    """
    vendor, po, invoice = setup_approved_three_way_invoice(
        ordered_amount_cents=200000, received_amount_cents=100000, invoice_amount_cents=100000)
    batch = open_batch(payment_method="ACH", run_date="2026-05-20")
    payment = add_payment(batch["id"], invoice["id"])
    resp = api.delete_payment(payment["id"], MGR)
    validate_success(resp, 200)
    inv_after = validate_success(api.get_invoice(invoice["id"], MGR), 200)
    assert inv_after["status"] == "APPROVED"


def test_remove_payment_conserves_po_matched_amount(api):
    """PRD §2.6: "A purchase order's `matched_amount_cents` is the sum of
    `total_amount_cents` over that PO's invoices whose status is one of `MATCHED`,
    `APPROVED`, `SCHEDULED`, or `PAID`".

    Design: Difficulty/compensating_invariant/payment_remove_conserves_po_matched_amount
    """
    vendor, po, invoice = setup_approved_three_way_invoice(
        ordered_amount_cents=200000, received_amount_cents=100000, invoice_amount_cents=100000)
    batch = open_batch(payment_method="ACH", run_date="2026-05-20")
    payment = add_payment(batch["id"], invoice["id"])
    validate_success(api.delete_payment(payment["id"], MGR), 200)
    po_after = validate_success(api.get_purchase_order(po["id"], MGR), 200)
    # APPROVED is still in the matched set, so the ledger debit is untouched.
    assert po_after["matched_amount_cents"] == 100000
    assert po_after["status"] == "OPEN"
