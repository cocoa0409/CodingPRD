"""Multi-hop cascades and conserved-quantity (compensating) invariants.

Translates Difficulty/transitive_cascade and Difficulty/compensating_invariant.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_active_placement, setup_issued_invoice_one_timesheet,
    drive_submission_to_offer_extended, create_placement, start_placement, end_placement,
    create_skill, create_client, create_open_job_order, create_candidate,
    make_account_manager_headers, make_recruiter_headers, make_client_headers,
)

AM = make_account_manager_headers()
RECRUITER = make_recruiter_headers()


def test_placement_fills_order_and_rejects_sibling_submissions(api):
    """PRD 3.4: "The submission advances from `OFFER_EXTENDED` to `PLACED`."
    PRD 3.4: "The candidate, if currently `AVAILABLE`, transitions to `ON_ASSIGNMENT`."
    PRD 3.4: "If this brings `filled_count` to equal `openings`, the order transitions from
    `OPEN` to `FILLED`, and that transition in turn sweeps every still-open submission on the
    order — those whose status is `SUBMITTED`, `CLIENT_REVIEW`, `INTERVIEWING`, or
    `OFFER_EXTENDED` — to `REJECTED` with `rejection_reason` set to the literal `ORDER_FILLED`."

    Depth-3 cascade on a 1-opening order: place candidate A (OFFER_EXTENDED) while sibling
    B sits at CLIENT_REVIEW. A -> PLACED, candidate A -> ON_ASSIGNMENT, order -> FILLED with
    filled_count 1, sibling B -> REJECTED with rejection_reason ORDER_FILLED.

    Design: Difficulty/transitive_cascade/place_fills_order_rejects_siblings
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    job_order, _jo_v = create_open_job_order(cl["id"], openings=1)
    cand_a = create_candidate(full_name="Cand A", skill_codes=["JAVA"])
    cand_b = create_candidate(full_name="Cand B", skill_codes=["JAVA"])

    # Sibling B: submit then advance to CLIENT_REVIEW (Recruiter op), then leave it there.
    sub_b = get_success_data(api.create_submission(
        {"job_order_id": job_order["id"], "candidate_id": cand_b["id"], "submitted_pay_rate_cents": 8000},
        RECRUITER))
    get_success_data(api.patch_submission(sub_b["id"], {"target_status": "CLIENT_REVIEW"}, RECRUITER))

    # Candidate A: drive to OFFER_EXTENDED.
    sub_a, _iv = drive_submission_to_offer_extended(job_order, cand_a, cl)

    # Re-read the order to obtain its current version for the OCC field.
    jo_now = validate_success(api.get_job_order(job_order["id"], RECRUITER))

    placement = get_success_data(api.create_placement(
        {"submission_id": sub_a["id"], "start_date": "2026-06-15T00:00:00Z",
         "end_date": "2026-12-15T00:00:00Z", "expected_job_order_version": jo_now["version"],
         "standard_weekly_hours": 40}, RECRUITER))

    placed_sub = validate_success(api.get_submission(sub_a["id"], RECRUITER))
    assert placed_sub["status"] == "PLACED", f"submission A status {placed_sub['status']}"

    cand_a_after = validate_success(api.get_candidate(cand_a["id"], RECRUITER))
    assert cand_a_after["status"] == "ON_ASSIGNMENT", f"candidate A status {cand_a_after['status']}"

    jo_after = validate_success(api.get_job_order(job_order["id"], RECRUITER))
    assert jo_after["status"] == "FILLED", f"job order status {jo_after['status']}"
    assert jo_after["filled_count"] == 1, f"filled_count {jo_after['filled_count']}"

    sib_after = validate_success(api.get_submission(sub_b["id"], RECRUITER))
    assert sib_after["status"] == "REJECTED", f"sibling B status {sib_after['status']}"
    assert sib_after["rejection_reason"] == "ORDER_FILLED", (
        f"sibling B rejection_reason {sib_after['rejection_reason']!r}"
    )


def test_placement_copies_job_order_and_candidate_from_submission(api):
    """PRD 3.4: "The placement copies several fields from its sources: its `job_order_id` and
    `candidate_id` are copied from the submission, its `placement_type` is copied from the job
    order's `employment_type`, its `bill_rate_cents` is copied from the job order, and its
    `pay_rate_cents` is copied from the submission's `submitted_pay_rate_cents`."

    The placed candidate A's placement carries the order's id, the candidate's id, TEMP type, and
    the copied bill/pay rates — the first hop of the fill cascade.

    Design: Difficulty/transitive_cascade/place_fills_order_rejects_siblings
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    job_order, _jo_v = create_open_job_order(cl["id"], openings=1, bill_rate_cents=12000)
    cand = create_candidate(full_name="Cara Dev", skill_codes=["JAVA"])
    sub, _iv = drive_submission_to_offer_extended(job_order, cand, cl, submitted_pay_rate_cents=8000)
    jo_now = validate_success(api.get_job_order(job_order["id"], RECRUITER))
    placement = get_success_data(api.create_placement(
        {"submission_id": sub["id"], "start_date": "2026-06-15T00:00:00Z",
         "end_date": "2026-12-15T00:00:00Z", "expected_job_order_version": jo_now["version"],
         "standard_weekly_hours": 40}, RECRUITER))
    assert placement["job_order_id"] == job_order["id"], f"job_order_id {placement['job_order_id']!r}"
    assert placement["candidate_id"] == cand["id"], f"candidate_id {placement['candidate_id']!r}"
    assert placement["placement_type"] == "TEMP", f"placement_type {placement['placement_type']}"
    assert placement["bill_rate_cents"] == 12000, f"bill_rate_cents {placement['bill_rate_cents']}"
    assert placement["pay_rate_cents"] == 8000, f"pay_rate_cents {placement['pay_rate_cents']}"


def test_invoice_issue_sweeps_timesheet_and_increments_balance(api):
    """PRD 3.8: "each timesheet referenced by the invoice's line items transitions from
    `APPROVED` to `INVOICED` and has its `invoice_id` set to this invoice; and the client's
    `outstanding_balance_cents` is increased by the invoice's `total_cents`."

    A single 40h timesheet (total 487200) is swept to INVOICED with invoice_id set, and the
    client's outstanding_balance_cents becomes 487200.

    Design: Difficulty/transitive_cascade/invoice_issue_sweeps_timesheet_and_balance
    """
    scen = setup_issued_invoice_one_timesheet(hours=40)
    ts = validate_success(api.get_timesheet(scen["timesheet"]["id"], scen["recruiter"]))
    assert ts["status"] == "INVOICED", f"timesheet status {ts['status']}"
    assert ts["invoice_id"] == scen["invoice"]["id"], (
        f"timesheet invoice_id {ts['invoice_id']!r} should be {scen['invoice']['id']!r}"
    )
    invoice = validate_success(api.get_invoice(scen["invoice"]["id"], AM))
    assert invoice["total_cents"] == 487200, f"invoice total {invoice['total_cents']}"
    client = validate_success(api.get_client(scen["client"]["id"], scen["recruiter"]))
    assert client["outstanding_balance_cents"] == 487200, (
        f"outstanding_balance_cents {client['outstanding_balance_cents']}"
    )


def test_invoice_issue_does_not_change_placement_actual_margin(api):
    """PRD 3.6: "Because the margin is counted once at approval, a later sweep onto an invoice does
    not add it again."
    PRD 3.8: "Because each approved timesheet's margin was counted into the placement's
    `actual_margin_cents` at approval time, neither issuing nor voiding an invoice changes that figure."

    A 40h timesheet (margin 160000) is approved (actual_margin 160000), then billed and the invoice
    issued; the placement's actual_margin_cents stays 160000 after the issue sweep.

    Design: Difficulty/transitive_cascade/invoice_issue_sweeps_timesheet_and_balance
    """
    scen = setup_issued_invoice_one_timesheet(hours=40)
    placement = validate_success(api.get_placement(scen["placement"]["id"], scen["recruiter"]))
    assert placement["actual_margin_cents"] == 160000, (
        f"actual_margin_cents should stay 160000 across the issue sweep, got {placement['actual_margin_cents']}"
    )


def test_place_then_end_conserves_filled_count_and_reopens(api):
    """PRD 3.4: "The order's `filled_count` is increased by one."
    PRD 3.5: "the job order's `filled_count` is decreased by one, and if that drops it below
    `openings` while the order is `FILLED`, the order automatically returns from `FILLED` to
    `OPEN` so the seat can be refilled."
    PRD 3.5: "if they now have no remaining placements whose `assignment_status` is `ACTIVE`,
    the candidate transitions from `ON_ASSIGNMENT` back to `AVAILABLE`."

    After place + start + end on a 1-opening order: filled_count back to 0, order back to OPEN,
    candidate back to AVAILABLE (no drift).

    Design: Difficulty/compensating_invariant/placement_end_conserves_filled_count
    """
    scen = setup_active_placement(job_order_overrides={"openings": 1})
    end_placement(scen["placement"]["id"])
    jo_after = validate_success(api.get_job_order(scen["job_order"]["id"], RECRUITER))
    assert jo_after["filled_count"] == 0, f"filled_count {jo_after['filled_count']}"
    assert jo_after["status"] == "OPEN", f"job order status {jo_after['status']}"
    cand_after = validate_success(api.get_candidate(scen["candidate"]["id"], RECRUITER))
    assert cand_after["status"] == "AVAILABLE", f"candidate status {cand_after['status']}"


def test_end_on_unfilled_order_conserves_filled_count_without_reopen(api):
    """PRD 3.4: "The order's `filled_count` is increased by one."
    PRD 3.5: "the job order's `filled_count` is decreased by one, and if that drops it below
    `openings` while the order is `FILLED`, the order automatically returns from `FILLED` to `OPEN`."

    On a 2-opening order, one ACTIVE placement leaves filled_count 1 (order still OPEN, never
    FILLED). Ending it returns filled_count to 0 while the order remains OPEN — the conservation
    invariant holds and no spurious FILLED->OPEN reopen occurs.

    Design: Difficulty/compensating_invariant/placement_end_conserves_filled_count
    """
    scen = setup_active_placement(job_order_overrides={"openings": 2})
    jo_active = validate_success(api.get_job_order(scen["job_order"]["id"], RECRUITER))
    assert jo_active["filled_count"] == 1, f"filled_count {jo_active['filled_count']}"
    assert jo_active["status"] == "OPEN", f"status {jo_active['status']}"
    end_placement(scen["placement"]["id"])
    jo_after = validate_success(api.get_job_order(scen["job_order"]["id"], RECRUITER))
    assert jo_after["filled_count"] == 0, f"filled_count after end {jo_after['filled_count']}"
    assert jo_after["status"] == "OPEN", f"status after end {jo_after['status']}"


def test_issue_then_void_conserves_outstanding_balance_and_uninvoices(api):
    """PRD 3.8: "Voiding is a compensating reversal of the issue: the client's
    `outstanding_balance_cents` is decreased by the invoice's `total_cents`, leaving the balance
    equal to the sum of the remaining issued invoices' totals; and every timesheet the invoice
    referenced reverts from `INVOICED` back to `APPROVED` with its `invoice_id` cleared, so it
    becomes re-billable."

    After issue + void of the only invoice: outstanding_balance back to 0, invoice VOID, the
    timesheet APPROVED again with invoice_id cleared (no drift).

    Design: Difficulty/compensating_invariant/invoice_void_conserves_outstanding_balance
    """
    scen = setup_issued_invoice_one_timesheet(hours=40)
    get_success_data(api.patch_invoice(scen["invoice"]["id"], {"target_status": "VOID"}, AM))
    client = validate_success(api.get_client(scen["client"]["id"], scen["recruiter"]))
    assert client["outstanding_balance_cents"] == 0, (
        f"outstanding_balance_cents should be 0 after issue+void, got {client['outstanding_balance_cents']}"
    )
    invoice = validate_success(api.get_invoice(scen["invoice"]["id"], AM))
    assert invoice["status"] == "VOID", f"invoice status {invoice['status']}"
    ts = validate_success(api.get_timesheet(scen["timesheet"]["id"], scen["recruiter"]))
    assert ts["status"] == "APPROVED", f"timesheet status {ts['status']}"
    assert not ts.get("invoice_id"), f"timesheet invoice_id should be cleared, got {ts.get('invoice_id')!r}"


def test_invoice_void_does_not_change_placement_actual_margin(api):
    """PRD 3.8: "Because each approved timesheet's margin was counted into the placement's
    `actual_margin_cents` at approval time, neither issuing nor voiding an invoice changes that figure."

    A 40h timesheet (margin 160000) is approved, billed, issued, then the invoice is voided; the
    placement's actual_margin_cents stays 160000 throughout the compensating reversal.

    Design: Difficulty/compensating_invariant/invoice_void_conserves_outstanding_balance
    """
    scen = setup_issued_invoice_one_timesheet(hours=40)
    get_success_data(api.patch_invoice(scen["invoice"]["id"], {"target_status": "VOID"}, AM))
    placement = validate_success(api.get_placement(scen["placement"]["id"], scen["recruiter"]))
    assert placement["actual_margin_cents"] == 160000, (
        f"actual_margin_cents should stay 160000 across issue+void, got {placement['actual_margin_cents']}"
    )
