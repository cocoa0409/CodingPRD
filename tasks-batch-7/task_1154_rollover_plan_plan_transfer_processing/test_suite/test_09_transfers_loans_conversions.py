"""Plan-to-plan transfers, loan movement and offsets, in-plan Roth conversion
lockdown, and inbound rollover credit with basis tracking."""
from test_helpers import (
    ApiErrorId,
    api_client,
    build_conversion_case,
    build_plan_transfer_acceptance,
    build_rollover_in_acceptance,
    get_account,
    get_case,
    list_case_documents,
    list_participant_5498s,
    make_account,
    make_admin_headers,
    make_loan,
    make_participant,
    make_participant_headers,
    make_plan,
    make_processor_headers,
    settle_case_documents,
    source_rows_by_type,
    submit_case,
    approve_case,
    validate_error,
    validate_paginated,
    validate_success,
)

PROC1 = make_processor_headers("proc-1")
PROC2 = make_processor_headers("proc-2")
ADMIN = make_admin_headers()


def test_transfer_completion_blocked_while_loans_outstanding(api):
    """PRD §3.8: "**Executing a plan-to-plan transfer** first requires that no
    `ACTIVE` loan remains on the source account (else `ERR_LOANS_OUTSTANDING`) —
    loans must be transferred or offset before the money moves."
    PRD §3.4: "while `PLAN_TRANSFER` and `ROLLOVER_IN` cases move directly to
    `ACCEPTANCE_PENDING`, since no disbursement is assembled for them."

    Design: Difficulty/cross_entity_state_dependency/transfer_completion_requires_loans_resolved
    """
    bundle = build_plan_transfer_acceptance(clock="2026-05-01T00:00:00Z")
    assert bundle["case"]["status"] == "ACCEPTANCE_PENDING", (
        f"APPROVE must route PLAN_TRANSFER to ACCEPTANCE_PENDING, got {bundle['case']['status']}"
    )
    # An ACTIVE loan appears on the source account after approval.
    make_loan(bundle["source_account"]["id"], outstanding_balance_cents=250000)

    resp = api_client.execute_transfer(bundle["case"]["id"], PROC2)
    validate_error(resp, ApiErrorId.ERR_LOANS_OUTSTANDING, expected_status=409)


def test_transfer_completion_after_loan_transferred(api):
    """PRD §3.8: "The loan's `account_id` is reassigned across the aggregate
    boundary, its status becomes `TRANSFERRED`, and its
    `outstanding_balance_cents`, `interest_rate_bp`, and `term_months` are
    preserved untouched."
    PRD §3.8: "**Executing a plan-to-plan transfer** first requires that no
    `ACTIVE` loan remains on the source account (else `ERR_LOANS_OUTSTANDING`) —
    loans must be transferred or offset before the money moves."

    Design: Difficulty/cross_entity_state_dependency/transfer_completion_requires_loans_resolved
    """
    bundle = build_plan_transfer_acceptance(clock="2026-05-01T00:00:00Z")
    loan = make_loan(bundle["source_account"]["id"], outstanding_balance_cents=250000)

    moved = validate_success(api_client.transfer_loan(
        loan["id"], {"receiving_account_id": bundle["receiving_account"]["id"]}, PROC1,
    ))
    assert moved["status"] == "TRANSFERRED"
    assert moved["account_id"] == bundle["receiving_account"]["id"], (
        "the loan note is reassigned across the aggregate boundary"
    )
    assert moved["outstanding_balance_cents"] == 250000
    assert moved["interest_rate_bp"] == 500 and moved["term_months"] == 60

    done = validate_success(api_client.execute_transfer(bundle["case"]["id"], PROC2))
    assert done["status"] == "COMPLETED", (
        f"with no ACTIVE loan remaining, the identical call succeeds: {done['status']}"
    )


def test_transfer_mirrors_source_rows_exactly(api):
    """PRD §3.8: "Execution then moves every money-source row book-entry to the
    receiving account, preserving each row's `balance_cents`, `basis_cents`, and
    `vested_pct` per source: basis tracking survives the move, and unvested
    employer money moves too — a transfer is not a distribution, so nothing is
    forfeited. Rows are copied in the pinned source-type order `AFTER_TAX`,
    `EMPLOYER_PRETAX`, `PRE_TAX`, `ROTH`. The source account's balances are
    zeroed and its status becomes `CLOSED`; the receiving account's computed
    totals recompute; no 1099-R is produced, because a transfer is non-taxable;
    and the case completes."

    Design: Difficulty/compensating_invariant/transfer_balance_basis_conservation
    """
    bundle = build_plan_transfer_acceptance(clock="2026-05-01T00:00:00Z")
    done = validate_success(api_client.execute_transfer(bundle["case"]["id"], PROC2))
    assert done["status"] == "COMPLETED"

    recv = source_rows_by_type(bundle["receiving_account"]["id"])
    expected = {
        "AFTER_TAX": (600000, 500000, 100),
        "EMPLOYER_PRETAX": (2000000, 0, 60),
        "PRE_TAX": (8000000, 0, 100),
        "ROTH": (1000000, 800000, 100),
    }
    for source_type, (balance, basis, pct) in expected.items():
        row = recv[source_type]
        assert (row["balance_cents"], row["basis_cents"], row["vested_pct"]) == (balance, basis, pct), (
            f"{source_type} must mirror the source exactly, got {row}"
        )

    src = source_rows_by_type(bundle["source_account"]["id"])
    for row in src.values():
        assert row["balance_cents"] == 0 and row["basis_cents"] == 0, (
            f"source rows must be zeroed, got {row}"
        )
    assert get_account(bundle["source_account"]["id"])["status"] == "CLOSED"


def test_transfer_conserves_aggregate_balances_and_produces_no_tax_form(api):
    """PRD §3.8: "Execution then moves every money-source row book-entry to the
    receiving account, preserving each row's `balance_cents`, `basis_cents`, and
    `vested_pct` per source: basis tracking survives the move, and unvested
    employer money moves too — a transfer is not a distribution, so nothing is
    forfeited."
    PRD §3.8: "no 1099-R is produced, because a transfer is non-taxable; and the
    case completes."

    Design: Difficulty/compensating_invariant/transfer_balance_basis_conservation
    """
    bundle = build_plan_transfer_acceptance(clock="2026-05-01T00:00:00Z")
    validate_success(api_client.execute_transfer(bundle["case"]["id"], PROC2))

    src = get_account(bundle["source_account"]["id"])
    recv = get_account(bundle["receiving_account"]["id"])
    assert src["total_balance_cents"] + recv["total_balance_cents"] == 11600000, (
        "aggregate balance is conserved across source and receiving accounts"
    )
    assert src["basis_cents"] + recv["basis_cents"] == 1300000, (
        "aggregate basis is conserved across source and receiving accounts"
    )
    assert recv["vested_balance_cents"] == 10800000

    resp = api_client.list_tax_forms(
        make_processor_headers("proc-1"), params={"rollover_case_id": bundle["case"]["id"]}
    )
    _forms, meta = validate_paginated(resp)
    assert meta["total_count"] == 0, "a non-taxable transfer produces no tax form"


def test_loan_offset_standard_window_and_1099r(api):
    """PRD §3.8: "The offset is a *qualified plan loan offset* —
    `offset_qualified` true — when, at offset time, the participant's
    `employment_status` is `SEPARATED` or `RETIRED`, or the holding plan's
    `status` is `TERMINATED`; otherwise it is a standard offset. The deadline
    variant follows: a standard offset sets `offset_rollover_deadline` to 60
    calendar days after the offset date, inclusive, mirroring the
    indirect-rollover rule, while a qualified plan loan offset sets it to
    October 15 of the year following the offset's tax year"
    PRD §3.8: "Offset is a taxable event and immediately drafts a 1099-R:
    `gross_distribution_cents` and `taxable_amount_cents` both equal to the
    loan's `outstanding_balance_cents`, `federal_withholding_cents` zero, and
    `distribution_code` `CODE_7` when the participant's `age_months` at offset
    is at least 714, else `CODE_1`."

    Design: Difficulty/dual_variant_calc/loan_offset_qualified_vs_standard_window
    """
    plan = make_plan(clock="2026-06-01T00:00:00Z")
    participant = make_participant(
        full_name="Stan Dard", date_of_birth="1970-01-01", employment_status="ACTIVE",
        marital_status="SINGLE", separation_date=None,
    )
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 1000000, "basis_cents": 0, "vested_pct": 100},
    ])
    loan = make_loan(account["id"], outstanding_balance_cents=250000)

    offset = validate_success(api_client.offset_loan(loan["id"], PROC1))
    assert offset["status"] == "OFFSET"
    assert offset["offset_qualified"] is False, "ACTIVE employment in an ACTIVE plan is not qualified"
    # 2026-06-01 + 60 calendar days == 2026-07-31.
    assert offset["offset_rollover_deadline"] == "2026-07-31", (
        f"standard variant deadline must be 2026-07-31, got {offset['offset_rollover_deadline']}"
    )

    resp = api_client.list_tax_forms(
        make_processor_headers("proc-1"), params={"loan_id": loan["id"]}
    )
    forms, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    form = forms[0]
    assert form["gross_distribution_cents"] == 250000
    assert form["taxable_amount_cents"] == 250000
    assert form["federal_withholding_cents"] == 0
    # age_months at offset: 677 < 714 -> CODE_1.
    assert form["distribution_code"] == "CODE_1"


def test_loan_offset_qualified_window_differs(api):
    """PRD §3.8: "The offset is a *qualified plan loan offset* —
    `offset_qualified` true — when, at offset time, the participant's
    `employment_status` is `SEPARATED` or `RETIRED`, or the holding plan's
    `status` is `TERMINATED`; otherwise it is a standard offset. The deadline
    variant follows: a standard offset sets `offset_rollover_deadline` to 60
    calendar days after the offset date, inclusive, mirroring the
    indirect-rollover rule, while a qualified plan loan offset sets it to
    October 15 of the year following the offset's tax year — the participant's
    filing deadline including extensions — a materially later deadline for the
    same outstanding balance."

    Design: Difficulty/dual_variant_calc/loan_offset_qualified_vs_standard_window
    """
    plan = make_plan(clock="2026-06-01T00:00:00Z")
    participant = make_participant(full_name="Que Alified")  # SEPARATED, dob 1960-06-15
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 1000000, "basis_cents": 0, "vested_pct": 100},
    ])
    loan = make_loan(account["id"], outstanding_balance_cents=250000)

    offset = validate_success(api_client.offset_loan(loan["id"], PROC1))
    assert offset["status"] == "OFFSET"
    assert offset["offset_qualified"] is True, "SEPARATED participant makes the offset qualified"
    # Qualified variant: October 15 of the year after the offset's tax year.
    assert offset["offset_rollover_deadline"] == "2027-10-15", (
        f"qualified variant deadline must be 2027-10-15, got {offset['offset_rollover_deadline']}"
    )

    resp = api_client.list_tax_forms(
        make_processor_headers("proc-1"), params={"loan_id": loan["id"]}
    )
    forms, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    # age_months at offset >= 714 -> CODE_7.
    assert forms[0]["distribution_code"] == "CODE_7"


def test_loan_bearing_transfer_capability_rejected(api):
    """PRD §3.3: "a `PLAN_TRANSFER` requires the receiving plan's
    `accepts_incoming_transfers`, a `ROLLOVER_IN` requires
    `accepts_incoming_rollovers`, a conversion requires
    `allows_in_plan_roth_conversion`, the presence of after-tax basis in scope
    requires the receiving plan's `accepts_after_tax_basis`, and a loan-bearing
    transfer requires `accepts_loan_transfers` — any failure answered with
    `ERR_PLAN_CAPABILITY_REJECTED`."

    Design: Corner/validations/loan_bearing_transfer_capability_rejected
    """
    plan_a = make_plan(name="Plan A", clock="2026-05-01T00:00:00Z")
    plan_b = make_plan(name="Plan Bnoloan", accepts_loan_transfers=False)
    participant = make_participant()
    a1 = make_account(participant["id"], plan_a["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    a1b = make_account(participant["id"], plan_b["id"], [])
    loan = make_loan(a1["id"], outstanding_balance_cents=100000, term_months=36)
    p_headers = make_participant_headers(participant["id"])
    resp = api_client.create_rollover_case(
        {"case_type": "PLAN_TRANSFER", "source_account_id": a1["id"],
         "receiving_plan_id": plan_b["id"], "receiving_account_id": a1b["id"]},
        p_headers,
    )
    case = validate_success(resp, expected_status=201)

    resp = api_client.submit_case(case["id"], p_headers)
    validate_error(resp, ApiErrorId.ERR_PLAN_CAPABILITY_REJECTED, expected_status=422)

    # Once the loan leaves ACTIVE (offset), the transfer is no longer
    # loan-bearing and the capability gate passes.
    validate_success(api_client.offset_loan(loan["id"], PROC1))
    submitted = validate_success(api_client.submit_case(case["id"], p_headers))
    assert submitted["status"] == "DOCS_PENDING", (
        f"submit must succeed after the loan is offset, got {submitted['status']}"
    )


def test_loan_transfer_rejected_by_receiving_plan(api):
    """PRD §3.8: "the receiving account's plan must have
    `accepts_loan_transfers` set and be `ACTIVE` itself (else
    `ERR_LOAN_NOT_TRANSFERRABLE`)"

    Design: Corner/validations/loan_transfer_rejected_by_receiving_plan
    """
    bundle = build_plan_transfer_acceptance(
        source_balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                          "basis_cents": 0, "vested_pct": 100}],
        receiving_plan_flags={"accepts_loan_transfers": False},
        clock="2026-05-01T00:00:00Z",
    )
    # The case had no loans at submit time, so its capability gate passed; the
    # loan appears afterwards.
    loan = make_loan(bundle["source_account"]["id"], outstanding_balance_cents=100000, term_months=36)

    resp = api_client.transfer_loan(
        loan["id"], {"receiving_account_id": bundle["receiving_account"]["id"]}, PROC1
    )
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_TRANSFERRABLE, expected_status=422)

    still = validate_success(api_client.get_loan(loan["id"], PROC1))
    assert still["status"] == "ACTIVE"
    assert still["account_id"] == bundle["source_account"]["id"], "rejected transfer must not move the note"


def test_loan_double_offset_rejected(api):
    """PRD §3.8: "Alternatively, a processor may *offset* an `ACTIVE` loan (else
    `ERR_LOAN_INVALID_STATE`): the loan becomes `OFFSET`, `offset_at` is stamped
    with the logical clock, and the offset window is computed."
    PRD §3.8: "Offset is a taxable event and immediately drafts a 1099-R"

    Design: Corner/state_machines/loan_double_offset_rejected
    """
    plan = make_plan(clock="2026-06-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 1000000, "basis_cents": 0, "vested_pct": 100},
    ])
    loan = make_loan(account["id"], outstanding_balance_cents=250000)

    first = validate_success(api_client.offset_loan(loan["id"], PROC1))
    assert first["status"] == "OFFSET"

    resp = api_client.offset_loan(loan["id"], PROC1)
    validate_error(resp, ApiErrorId.ERR_LOAN_INVALID_STATE, expected_status=409)

    resp = api_client.list_tax_forms(PROC1, params={"loan_id": loan["id"]})
    _forms, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, "the rejected second offset must not draft a second 1099-R"


def test_case_cancel_from_completed_rejected(api):
    """PRD §3.4: "A participant may abandon a case by cancelling it, but only
    from the pre-disbursement states `DRAFT`, `DOCS_PENDING`, or
    `ELIGIBILITY_REVIEW`; any other status — including every terminal state —
    rejects the cancellation with `ERR_CASE_INVALID_STATE`."
    PRD §4: "Execute the irrevocable in-plan Roth conversion" (the executed
    conversion leaves no cancel path).

    Design: Corner/state_machines/case_cancel_from_completed_rejected
    """
    bundle = build_conversion_case(approve=True)
    case_id = bundle["case"]["id"]
    assert bundle["case"]["status"] == "ELIGIBLE"

    # Execute the conversion as a different processor than the approver.
    resp = api_client.execute_conversion(case_id, PROC2)
    validate_success(resp)

    resp = api_client.cancel_case(case_id, make_participant_headers(bundle["participant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, expected_status=409)


def test_rollover_in_post_credit_basis_tracking(api):
    """PRD §3.8: "The processor posts the inbound breakdown — `pre_tax_cents`,
    `roth_cents`, `roth_basis_cents`, and `after_tax_basis_cents` — and the
    receiving account's money-source rows are credited accordingly:
    `pre_tax_cents` into the `PRE_TAX` source, `roth_cents` into the `ROTH`
    source with `roth_basis_cents` as its tax-paid basis, and
    `after_tax_basis_cents` into the `AFTER_TAX` source as basis. A `DRAFT` 5498
    for the credit's tax year is created or updated (§3.10), and the case
    completes."
    PRD §3.4: "6. `SOURCE_PLAN_STATEMENT`, required for `ROLLOVER_IN` cases."

    Design: Corner/endpoints/rollover_in_post_credit_basis_tracking
    """
    bundle = build_rollover_in_acceptance(clock="2026-05-01T00:00:00Z")
    case = bundle["case"]
    docs = list_case_documents(case["id"])
    assert [d["doc_type"] for d in docs] == ["SOURCE_PLAN_STATEMENT"], (
        f"ROLLOVER_IN requires exactly the SOURCE_PLAN_STATEMENT, got {[d['doc_type'] for d in docs]}"
    )
    assert case["status"] == "ACCEPTANCE_PENDING"

    done = validate_success(api_client.post_credit(
        case["id"],
        {"pre_tax_cents": 400000, "roth_cents": 100000,
         "roth_basis_cents": 90000, "after_tax_basis_cents": 50000},
        PROC2,
    ))
    assert done["status"] == "COMPLETED"

    rows = source_rows_by_type(bundle["receiving_account"]["id"])
    assert (rows["PRE_TAX"]["balance_cents"], rows["PRE_TAX"]["basis_cents"]) == (400000, 0)
    assert (rows["ROTH"]["balance_cents"], rows["ROTH"]["basis_cents"]) == (100000, 90000), (
        "Roth tax-paid basis travels through the rollover"
    )
    assert (rows["AFTER_TAX"]["balance_cents"], rows["AFTER_TAX"]["basis_cents"]) == (50000, 50000)

    f5498, meta = list_participant_5498s(bundle["participant"]["id"])
    assert meta["total_count"] == 1
    assert f5498[0]["rollover_contribution_cents"] == 550000
    assert f5498[0]["tax_year"] == 2026
    assert f5498[0]["fair_market_value_cents"] == 550000
