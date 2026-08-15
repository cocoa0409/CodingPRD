"""RMA claim branching workflow, per-claim snapshot pricing, and the credit
memo waterfall into invoice balances and installer exposure."""
from test_helpers import (
    TEST_USERS,
    allocate_current_version,
    api_client,
    create_active_installer,
    create_approved_rma,
    create_locked_project,
    create_submitted_rma,
    receive_single_line_lot,
    seed_catalog,
    set_clock,
    setup_pto_billed_project,
    setup_shipped_project,
    ship_allocation,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _credit_memos(project_id):
    return validate_success(
        api_client.list_project_invoices(
            project_id, MANAGER, params={"invoice_kind": "CREDIT_MEMO"}
        ),
        200,
    )


def test_rma_approved_path_credits_and_closes(api):
    """PRD section 3.9: "it sets `qty_approved`, computes the claim's
    `credit_amount_cents` as the approved quantity multiplied by the
    allocation's frozen `unit_cost_cents_at_allocation` — snapshot pricing,
    the price the installer actually paid rather than any current replacement
    cost — and moves the claim to `APPROVED`."
    PRD section 3.9: "Issuing credit creates an invoice with `invoice_kind`
    `CREDIT_MEMO` whose `amount_cents` is the negative of the claim's
    `credit_amount_cents`". Two approved units at the frozen 55000c snapshot
    give a 110000c credit and a -110000c memo; the claim then closes.

    Design: Difficulty/non_linear_state_machine/rma_claim_cyclic_workflow_draft_submit_approve_credit_close
    """
    ctx = setup_shipped_project(module_qty=5, lot_qty=5,
                                progress_payment_pct_bp=10000)
    inst_id = ctx["installer"]["id"]
    claim = create_approved_rma(inst_id, ctx["module"]["id"],
                                ctx["allocation"]["id"], 2)
    assert claim["status"] == "APPROVED"
    assert claim["credit_amount_cents"] == 110000, (
        f"credit must be 2 x 55000 = 110000, got {claim['credit_amount_cents']}"
    )

    validate_success(api_client.issue_rma_credit(claim["id"], OFFICER), 200)
    after_credit = validate_success(api_client.get_rma_claim(claim["id"], MANAGER), 200)
    assert after_credit["status"] == "CREDIT_ISSUED"

    memos = _credit_memos(ctx["project"]["id"])
    assert len(memos) == 1
    assert memos[0]["amount_cents"] == -110000

    closed = validate_success(api_client.close_rma_claim(claim["id"], OFFICER), 200)
    assert closed["status"] == "CLOSED"


def test_rma_rejected_path_has_no_credit_memo(api):
    """PRD section 3.9: "Rejection moves the claim to `REJECTED`, terminal."
    PRD section 3.9: "Issuing credit creates an invoice with `invoice_kind`
    `CREDIT_MEMO` whose `amount_cents` is the negative of the claim's
    `credit_amount_cents`" — only the approved-and-credited branch creates
    one, so the rejected claim leaves no credit memo behind.

    Design: Difficulty/non_linear_state_machine/rma_claim_cyclic_workflow_draft_submit_approve_credit_close
    """
    ctx = setup_shipped_project(module_qty=5, lot_qty=5,
                                progress_payment_pct_bp=10000)
    inst_id = ctx["installer"]["id"]
    claim = create_submitted_rma(inst_id, ctx["module"]["id"],
                                 ctx["allocation"]["id"], 1)
    rejected = validate_success(
        api_client.reject_rma_claim(claim["id"], MANAGER), 200
    )
    assert rejected["status"] == "REJECTED"

    assert _credit_memos(ctx["project"]["id"]) == [], (
        "a rejected claim must not generate a CREDIT_MEMO"
    )


def _rounding_artifact_scenario():
    """One line of 6 units declared at 60609c each under the 10% module
    tariff, zero freight/insurance. Per-line rounding at receipt:
    base 363654, duty round_half_up(36365.4) = 36365, landed 400019, unit
    round_half_up(400019 / 6) = 66670."""
    set_clock()
    catalog = seed_catalog(min_modules=5, max_modules=20)
    installer = create_active_installer(progress_payment_pct_bp=10000)
    project = create_locked_project(
        installer["id"], catalog["module"]["id"], catalog["inverter"]["id"],
        module_qty=6,
    )
    container, line, lot = receive_single_line_lot(
        catalog["module"]["id"], qty_booked=6,
        declared_unit_value_cents=60609,
    )
    return {**catalog, "installer": installer, "project": project,
            "container": container, "line": line, "lot": lot}


def test_per_line_rounding_snapshot_at_receive(api):
    """PRD section 2.5: "Every division performed inside a calculation rounds
    half up to a whole cent, and multi-step calculations round at each
    division step rather than only at the end, so that every intermediate
    figure is itself a whole-cent amount." The landed total 400019c divided
    by 6 received units rounds half up to 66670c — per line at receipt, never
    66669c from truncating or from deferring the division.

    Design: Difficulty/combinatorial_formula/credit_exposure_nested_rounding_then_sum_vs_sum_then_round
    """
    ctx = _rounding_artifact_scenario()
    assert ctx["lot"]["unit_cost_cents_final"] == 66670, (
        f"final unit cost must round half up to 66670, "
        f"got {ctx['lot']['unit_cost_cents_final']}"
    )
    assert ctx["lot"]["qty_on_hand"] == 6


def test_two_rma_credits_zero_out_exposure(api):
    """PRD section 3.9: "it sets `qty_approved`, computes the claim's
    `credit_amount_cents` as the approved quantity multiplied by the
    allocation's frozen `unit_cost_cents_at_allocation`". Each 3-unit claim
    credits 3 x 66670 = 200010; both credits applied against the single
    400020 progress invoice bring its balance to 0.
    PRD section 3.2: "An installer's `credit_exposure_cents` is the sum of
    `balance_due_cents` across that installer's invoices in `OPEN`,
    `PARTIALLY_PAID`, or `PAST_DUE` status, excluding `WRITE_OFF` invoices
    entirely" — a zeroed balance contributes nothing.

    Design: Difficulty/combinatorial_formula/credit_exposure_nested_rounding_then_sum_vs_sum_then_round
    """
    ctx = _rounding_artifact_scenario()
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]
    lot_id = ctx["lot"]["id"]

    alloc1 = allocate_current_version(proj_id, inst_id, lot_id, 3)
    alloc2 = allocate_current_version(proj_id, inst_id, lot_id, 3)
    ship_allocation(alloc1["id"])
    ship_allocation(alloc2["id"])

    invoices = validate_success(
        api_client.list_project_invoices(
            proj_id, MANAGER, params={"invoice_kind": "PROGRESS"}
        ),
        200,
    )
    assert len(invoices) == 1
    invoice = invoices[0]
    # 6 units x 66670 snapshot, billed at 100%.
    assert invoice["amount_cents"] == 400020
    assert invoice["balance_due_cents"] == 400020

    for alloc in (alloc1, alloc2):
        claim = create_approved_rma(inst_id, ctx["module"]["id"],
                                    alloc["id"], 3)
        assert claim["credit_amount_cents"] == 200010
        validate_success(api_client.issue_rma_credit(claim["id"], OFFICER), 200)

    after = validate_success(api_client.get_invoice(invoice["id"], OFFICER), 200)
    assert after["balance_due_cents"] == 0, (
        f"400020 - 200010 - 200010 must zero the balance, "
        f"got {after['balance_due_cents']}"
    )
    installer = validate_success(api_client.get_installer(inst_id, OFFICER), 200)
    assert installer["credit_exposure_cents"] == 0


def _two_open_invoices_with_rma():
    """50% progress terms over 5 modules at 55000c: allocated value 275000,
    PROGRESS invoice 137500 (older), PTO invoice 137500 (newer). An approved
    3-unit RMA claim carries credit 3 x 55000 = 165000."""
    ctx = setup_pto_billed_project(module_qty=5, lot_qty=5,
                                   progress_payment_pct_bp=5000)
    inst_id = ctx["installer"]["id"]
    claim = create_approved_rma(inst_id, ctx["module"]["id"],
                                ctx["allocation"]["id"], 3)
    ctx["rma_claim"] = claim
    return ctx


def test_issue_credit_applies_oldest_first(api):
    """PRD section 3.9: "Issuing credit creates an invoice with
    `invoice_kind` `CREDIT_MEMO` whose `amount_cents` is the negative of the
    claim's `credit_amount_cents`, then applies that credit against the
    installer's open invoices — those in `OPEN`, `PARTIALLY_PAID`, or
    `PAST_DUE` — oldest first, ordered by `invoice_date` ascending and then
    `created_at` ascending, reducing each target invoice's
    `balance_due_cents` but never below zero; any residual credit remains
    standing as a negative-balance invoice." The 165000c credit zeroes the
    137500c PROGRESS invoice and leaves 110000c on the PTO invoice.
    PRD section 3.2: exposure is the sum of open balances, so it recomputes
    to 110000.

    Design: Difficulty/transitive_cascade/rma_approval_cascades_to_credit_memo_to_invoice_balance_to_installer_exposure
    """
    ctx = _two_open_invoices_with_rma()
    proj_id = ctx["project"]["id"]
    inst_id = ctx["installer"]["id"]
    assert ctx["progress_invoice"]["amount_cents"] == 137500

    validate_success(api_client.issue_rma_credit(ctx["rma_claim"]["id"], OFFICER), 200)

    progress = validate_success(
        api_client.get_invoice(ctx["progress_invoice"]["id"], OFFICER), 200
    )
    pto_list = validate_success(
        api_client.list_project_invoices(proj_id, OFFICER,
                                         params={"invoice_kind": "PTO"}),
        200,
    )
    assert len(pto_list) == 1
    assert progress["balance_due_cents"] == 0, (
        "oldest invoice absorbs the credit first, floored at zero"
    )
    assert pto_list[0]["balance_due_cents"] == 110000, (
        f"residual 27500 reduces the PTO balance to 110000, "
        f"got {pto_list[0]['balance_due_cents']}"
    )

    memos = _credit_memos(proj_id)
    assert len(memos) == 1
    assert memos[0]["amount_cents"] == -165000

    installer = validate_success(api_client.get_installer(inst_id, OFFICER), 200)
    assert installer["credit_exposure_cents"] == 110000


def test_issue_credit_does_not_adjust_allocated_value(api):
    """PRD section 3.9: "The claim moves to `CREDIT_ISSUED`, the installer's
    `credit_exposure_cents` recomputes, and the project's
    `allocated_value_cents` is deliberately *not* adjusted: the units have
    already shipped, so this is a credit, not a return to stock."

    Design: Difficulty/transitive_cascade/rma_approval_cascades_to_credit_memo_to_invoice_balance_to_installer_exposure
    """
    ctx = _two_open_invoices_with_rma()
    proj_id = ctx["project"]["id"]

    validate_success(api_client.issue_rma_credit(ctx["rma_claim"]["id"], OFFICER), 200)

    claim = validate_success(
        api_client.get_rma_claim(ctx["rma_claim"]["id"], MANAGER), 200
    )
    assert claim["status"] == "CREDIT_ISSUED"
    assert claim["credit_amount_cents"] == 165000

    project = validate_success(api_client.get_project(proj_id, MANAGER), 200)
    assert project["allocated_value_cents"] == 275000, (
        f"credit issuance must not touch allocated_value_cents, "
        f"got {project['allocated_value_cents']}"
    )
