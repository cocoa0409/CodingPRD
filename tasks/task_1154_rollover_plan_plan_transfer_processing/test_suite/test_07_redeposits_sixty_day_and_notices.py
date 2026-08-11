"""Redeposits: the 60-day window, completion cascades, remaining-shortfall and
account-state gates, and scheduled follow-up notices."""
from test_helpers import (
    ApiErrorId,
    api_client,
    build_issued_indirect_case,
    create_redeposit_payload,
    get_account,
    get_case,
    list_case_tax_forms,
    list_participant_5498s,
    make_account,
    make_operations_headers,
    make_participant,
    make_participant_headers,
    make_plan,
    make_processor_headers,
    set_logical_clock,
    settle_case_documents,
    submit_case,
    approve_case,
    validate_error,
    validate_paginated,
    validate_success,
)

PROC1 = make_processor_headers("proc-1")
PROC2 = make_processor_headers("proc-2")


def _deposit(case_id, account_id, amount, received_date):
    return api_client.create_redeposit(
        create_redeposit_payload(account_id, amount, received_date, rollover_case_id=case_id),
        PROC1,
    )


def test_sixty_day_boundary_day60_deposit_is_timely(api):
    """PRD §3.7: "The **60-day rule** governs indirect rollovers with an
    inclusive upper bound: a redeposit whose `received_date` is on or before
    `rollover_deadline_date` is timely — the deadline day itself counts — while
    a `received_date` of the day after the deadline or later is rejected with
    `ERR_DEPOSIT_PAST_DEADLINE`."
    PRD §3.7: "For indirect cases, `rollover_deadline_date` is computed as
    exactly 60 calendar days after `disbursement_issued_date`."

    Design: Difficulty/boundary_precision_check/sixty_day_boundary_day60_vs_day61
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", receiving_plan_type="IRA")
    case = get_case(bundle["case"]["id"])
    # 2026-06-01 + 60 calendar days == 2026-07-31.
    assert case["rollover_deadline_date"] == "2026-07-31", (
        f"deadline must be 2026-07-31, got {case['rollover_deadline_date']}"
    )

    resp = _deposit(bundle["case"]["id"], bundle["receiving_account"]["id"], 1000000, "2026-07-31")
    deposit = validate_success(resp, expected_status=201)
    assert deposit["status"] == "PENDING_VERIFICATION", "the deadline day itself counts (inclusive)"


def test_sixty_day_boundary_day61_deposit_rejected(api):
    """PRD §3.7: "The **60-day rule** governs indirect rollovers with an
    inclusive upper bound: a redeposit whose `received_date` is on or before
    `rollover_deadline_date` is timely — the deadline day itself counts — while
    a `received_date` of the day after the deadline or later is rejected with
    `ERR_DEPOSIT_PAST_DEADLINE`."
    PRD §3.9: "The deadline gate is evaluated at creation and re-checked at
    credit time: a case-linked deposit's `received_date` must be on or before
    the case's `rollover_deadline_date`"

    Design: Difficulty/boundary_precision_check/sixty_day_boundary_day60_vs_day61
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", receiving_plan_type="IRA")
    case = get_case(bundle["case"]["id"])
    assert case["rollover_deadline_date"] == "2026-07-31"

    resp = _deposit(bundle["case"]["id"], bundle["receiving_account"]["id"], 1000000, "2026-08-01")
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_PAST_DEADLINE, expected_status=422)


def test_redeposit_referential_error_beats_fiscal_error(api):
    """PRD §2.9: "6. **Cross-reference consistency** — linked resources must
    belong to the same participant and the referenced plans
    (`ERR_ACCOUNT_PARTICIPANT_MISMATCH`, `ERR_SAME_PLAN_TRANSFER`,
    `ERR_ACCOUNT_ALREADY_EXISTS`)."
    PRD §2.9: "9. **Amount checks, last** — only after every other gate has
    passed are magnitudes validated (`ERR_AMOUNT_EXCEEDS_VESTED`,
    `ERR_DEPOSIT_EXCEEDS_REMAINING`, and `ERR_VALIDATION` for non-positive
    amounts or malformed fields)."
    PRD §3.9: "The receiving account must belong to the same participant as the
    linked case or loan (else `ERR_ACCOUNT_PARTICIPANT_MISMATCH`), and the
    amount must not exceed the remaining shortfall — the case's gross minus its
    `credited_total_cents`, or the loan's outstanding balance minus its
    `offset_repaid_cents` — else `ERR_DEPOSIT_EXCEEDS_REMAINING`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_redeposit
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z")
    ira_plan = make_plan(name="IRA Plan", plan_type="IRA")
    other = make_participant(
        full_name="Pat Two", date_of_birth="1965-03-10", separation_date="2026-03-01"
    )
    foreign_account = make_account(other["id"], ira_plan["id"], [])

    # Dual failure: another participant's account AND amount over the remaining
    # shortfall (20,000,000 > 10,800,000). Referential (priority 6) wins.
    resp = _deposit(bundle["case"]["id"], foreign_account["id"], 20000000, "2026-07-01")
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_PARTICIPANT_MISMATCH, expected_status=422)


def test_redeposit_referential_rejection_persists_nothing(api):
    """PRD §2.9: "When a request fails several rules at once, the API answers
    with exactly one error, and which error it is must be deterministic."
    PRD §3.9: "The receiving account must belong to the same participant as the
    linked case or loan (else `ERR_ACCOUNT_PARTICIPANT_MISMATCH`), and the
    amount must not exceed the remaining shortfall — the case's gross minus its
    `credited_total_cents`, or the loan's outstanding balance minus its
    `offset_repaid_cents` — else `ERR_DEPOSIT_EXCEEDS_REMAINING`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_redeposit
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", receiving_plan_type="IRA")
    case_id = bundle["case"]["id"]
    ira_plan = bundle["receiving_plan"]
    other = make_participant(
        full_name="Pat Two", date_of_birth="1965-03-10", separation_date="2026-03-01"
    )
    foreign_account = make_account(other["id"], ira_plan["id"], [])

    resp = _deposit(case_id, foreign_account["id"], 20000000, "2026-07-01")
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_PARTICIPANT_MISMATCH, expected_status=422)

    resp = api_client.list_case_redeposits(case_id, PROC1)
    _rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 0, "the rejected request must not persist a redeposit"

    # Control: with the referential failure removed, the lone fiscal failure
    # surfaces its own error.
    resp = _deposit(case_id, bundle["receiving_account"]["id"], 20000000, "2026-07-01")
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_EXCEEDS_REMAINING, expected_status=422)


def _setup_closed_receiving_account_scenario():
    """A2 (Plan B, PRE_TAX 100,000) is fully transferred into A1 (Plan A,
    PRE_TAX 8,000,000), so A2 auto-CLOSED; then a partial (500,000) INDIRECT
    case out of A1 is approved and issued. Returns (participant, a1, a2,
    case_y)."""
    plan_a = make_plan(name="Plan A", clock="2026-06-01T00:00:00Z")
    plan_b = make_plan(name="Plan B")
    participant = make_participant()
    a1 = make_account(participant["id"], plan_a["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 8000000, "basis_cents": 0, "vested_pct": 100},
    ])
    a2 = make_account(participant["id"], plan_b["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 100000, "basis_cents": 0, "vested_pct": 100},
    ])
    p_headers = make_participant_headers(participant["id"])
    resp = api_client.create_rollover_case(
        {"case_type": "PLAN_TRANSFER", "source_account_id": a2["id"],
         "receiving_plan_id": plan_a["id"], "receiving_account_id": a1["id"]},
        p_headers,
    )
    case_t = validate_success(resp, expected_status=201)
    submit_case(case_t["id"], participant["id"])
    settle_case_documents(case_t["id"], participant["id"])
    approve_case(case_t["id"])
    validate_success(api_client.execute_transfer(case_t["id"], PROC2))

    resp = api_client.create_rollover_case(
        {"case_type": "INDIRECT_ROLLOVER_OUT", "source_account_id": a1["id"],
         "receiving_institution_name": "External IRA Trust",
         "requested_amount_cents": 500000, "withholding_acknowledged": True},
        p_headers,
    )
    case_y = validate_success(resp, expected_status=201)
    submit_case(case_y["id"], participant["id"])
    settle_case_documents(case_y["id"], participant["id"])
    approve_case(case_y["id"])
    resp = api_client.assemble_disbursement(case_y["id"], {"method": "CHECK"}, PROC2)
    disb = validate_success(resp)
    validate_success(api_client.issue_disbursement(disb["id"], PROC2))
    return participant, a1, a2, case_y


def test_redeposit_credit_into_closed_account_rejected(api):
    """PRD §3.9: "Crediting a redeposit requires it to still be
    `PENDING_VERIFICATION` (else `ERR_REDEPOSIT_INVALID_STATE`) and the
    receiving account to be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`)"
    PRD §3.2: "An account is `ACTIVE` on creation and auto-transitions to
    `CLOSED` the moment its `total_balance_cents` reaches zero on a case
    terminal transition (`COMPLETED` or `INCOMPLETE`) or on execution of a
    plan-to-plan transfer"

    Design: Difficulty/cross_entity_state_dependency/redeposit_credit_requires_active_account
    """
    _participant, _a1, a2, case_y = _setup_closed_receiving_account_scenario()
    assert get_account(a2["id"])["status"] == "CLOSED", (
        "A2 auto-closes when its full balance transfers out"
    )

    # Recording the redeposit against the CLOSED account is allowed (creation
    # is not gated on account state); the credit transition is.
    deposit = validate_success(_deposit(case_y["id"], a2["id"], 100000, "2026-06-15"), expected_status=201)
    assert deposit["status"] == "PENDING_VERIFICATION"
    resp = api_client.credit_redeposit(deposit["id"], PROC2)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, expected_status=409)


def test_redeposit_credit_into_active_account_succeeds_after_closed_rejection(api):
    """PRD §3.9: "Crediting a redeposit requires it to still be
    `PENDING_VERIFICATION` (else `ERR_REDEPOSIT_INVALID_STATE`) and the
    receiving account to be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`), and
    re-checks the same deadline gate. The credit cascades by linkage. For a
    case-linked deposit, the case's `credited_total_cents` — always the sum of
    `amount_cents` over the case's `CREDITED` redeposits only, excluding
    `PENDING_VERIFICATION` and `REJECTED` rows — grows by the deposit amount"

    Design: Difficulty/cross_entity_state_dependency/redeposit_credit_requires_active_account
    """
    _participant, a1, a2, case_y = _setup_closed_receiving_account_scenario()

    rejected_target = validate_success(_deposit(case_y["id"], a2["id"], 100000, "2026-06-15"), expected_status=201)
    resp = api_client.credit_redeposit(rejected_target["id"], PROC2)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, expected_status=409)
    assert get_case(case_y["id"])["credited_total_cents"] == 0, (
        "a credit rejected on account state must not grow credited_total_cents"
    )

    # The same amount into the ACTIVE account credits normally.
    ok = validate_success(_deposit(case_y["id"], a1["id"], 100000, "2026-06-15"), expected_status=201)
    credited = validate_success(api_client.credit_redeposit(ok["id"], PROC2))
    assert credited["status"] == "CREDITED"
    assert get_case(case_y["id"])["credited_total_cents"] == 100000


def test_deposit_exceeds_remaining_rejected_equality_completes(api):
    """PRD §3.9: "the amount must not exceed the remaining shortfall — the
    case's gross minus its `credited_total_cents`, or the loan's outstanding
    balance minus its `offset_repaid_cents` — else `ERR_DEPOSIT_EXCEEDS_REMAINING`."
    PRD §3.9: "When the credit lifts `credited_total_cents` to at least the
    case's `gross_cents` — equality completes — the case moves
    `AWAITING_REDEPOSIT → COMPLETED`"

    Design: Corner/validations/deposit_exceeds_remaining_rejected
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", receiving_plan_type="IRA")
    case_id = bundle["case"]["id"]
    a2 = bundle["receiving_account"]["id"]
    first = validate_success(_deposit(case_id, a2, 8900000, "2026-06-20"), expected_status=201)
    validate_success(api_client.credit_redeposit(first["id"], PROC2))

    # Remaining shortfall is 10,800,000 - 8,900,000 = 1,900,000.
    resp = _deposit(case_id, a2, 2000000, "2026-07-01")
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_EXCEEDS_REMAINING, expected_status=422)

    exact = validate_success(_deposit(case_id, a2, 1900000, "2026-07-01"), expected_status=201)
    credited = validate_success(api_client.credit_redeposit(exact["id"], PROC2))
    assert credited["status"] == "CREDITED"
    case = get_case(case_id)
    assert case["status"] == "COMPLETED", (
        f"equality completes the case, got {case['status']}"
    )


def test_redeposit_double_credit_rejected(api):
    """PRD §3.9: "Crediting a redeposit requires it to still be
    `PENDING_VERIFICATION` (else `ERR_REDEPOSIT_INVALID_STATE`)"
    PRD §3.9: "For a case-linked deposit, the case's `credited_total_cents` —
    always the sum of `amount_cents` over the case's `CREDITED` redeposits only,
    excluding `PENDING_VERIFICATION` and `REJECTED` rows — grows by the deposit
    amount"

    Design: Corner/state_machines/redeposit_double_credit_rejected
    """
    bundle = build_issued_indirect_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-06-01T00:00:00Z",
        receiving_plan_type="IRA",
    )
    case_id = bundle["case"]["id"]
    # Gross 500,000, taxable 500,000, withholding 100,000, net 400,000.
    deposit = validate_success(
        _deposit(case_id, bundle["receiving_account"]["id"], 400000, "2026-07-01"),
        expected_status=201,
    )
    credited = validate_success(api_client.credit_redeposit(deposit["id"], PROC2))
    assert credited["status"] == "CREDITED"

    resp = api_client.credit_redeposit(deposit["id"], PROC2)
    validate_error(resp, ApiErrorId.ERR_REDEPOSIT_INVALID_STATE, expected_status=409)

    case = get_case(case_id)
    assert case["credited_total_cents"] == 400000, (
        f"no double count after the rejected second credit, got {case['credited_total_cents']}"
    )


def test_redeposit_completion_cascade_case_and_notices(api):
    """PRD §3.9: "When the credit lifts `credited_total_cents` to at least the
    case's `gross_cents` — equality completes — the case moves
    `AWAITING_REDEPOSIT → COMPLETED` with its own cascades: every
    still-`SCHEDULED` follow-up notice flips to `SKIPPED`, and the 1099-R
    recomputes to its *corrected* variant (§3.10)."

    Design: Difficulty/transitive_cascade/redeposit_completion_cascade
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", receiving_plan_type="IRA")
    case_id = bundle["case"]["id"]
    deposit = validate_success(
        _deposit(case_id, bundle["receiving_account"]["id"], 10800000, "2026-07-01"),
        expected_status=201,
    )
    validate_success(api_client.credit_redeposit(deposit["id"], PROC2))

    case = get_case(case_id)
    assert case["status"] == "COMPLETED", f"case must complete, got {case['status']}"
    assert case["credited_total_cents"] == 10800000

    resp = api_client.list_case_notices(case_id, PROC1)
    notices, meta = validate_paginated(resp)
    assert meta["total_count"] == 3
    assert all(n["status"] == "SKIPPED" for n in notices), (
        f"every still-SCHEDULED notice flips to SKIPPED, got {[n['status'] for n in notices]}"
    )


def test_redeposit_completion_cascade_tax_forms(api):
    """PRD §3.10: "The **corrected** variant applies once the 60-day outcome is
    known — whether the case completed or the sweep marked it `INCOMPLETE`:
    credited dollars are applied to the taxable portion first, so the corrected
    taxable is the original `taxable_cents` minus the smaller of
    `credited_total_cents` and `taxable_cents`."
    PRD §3.10: "**FORM_5498** is aggregated: one `DRAFT` per (`participant_id`,
    `tax_year`), its `rollover_contribution_cents` accumulating the sum of every
    `CREDITED` redeposit amount and every `ROLLOVER_IN` posted credit received
    in that tax year, and its `fair_market_value_cents` snapshotting the
    receiving account's `total_balance_cents` at the latest credit."

    Design: Difficulty/transitive_cascade/redeposit_completion_cascade
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", receiving_plan_type="IRA")
    case_id = bundle["case"]["id"]
    deposit = validate_success(
        _deposit(case_id, bundle["receiving_account"]["id"], 10800000, "2026-07-01"),
        expected_status=201,
    )
    validate_success(api_client.credit_redeposit(deposit["id"], PROC2))

    forms, meta = list_case_tax_forms(case_id, form_type="FORM_1099_R")
    assert meta["total_count"] == 1
    # corrected taxable = 9,500,000 - min(10,800,000, 9,500,000) = 0.
    assert forms[0]["taxable_amount_cents"] == 0, (
        f"corrected variant must zero the taxable amount, got {forms[0]['taxable_amount_cents']}"
    )

    f5498, meta5498 = list_participant_5498s(bundle["participant"]["id"])
    assert meta5498["total_count"] == 1
    assert f5498[0]["rollover_contribution_cents"] == 10800000
    assert f5498[0]["tax_year"] == 2026
    assert f5498[0]["fair_market_value_cents"] == 10800000, (
        "fair market value snapshots the receiving account's total at credit time"
    )


def test_scheduled_notice_sweep_timing(api):
    """PRD §3.7: "And three **FollowUpNotice** rows are created for an indirect
    case, in `SCHEDULED` status: `notice_seq` 1 scheduled 30 days after the
    issue date, `notice_seq` 2 at 45 days, and `notice_seq` 3 at 55 days, each
    carrying its `scheduled_date`."
    PRD §3.11: "First, it dispatches due follow-up notices: every `SCHEDULED`
    notice whose `scheduled_date` has been reached by the clock date and whose
    owning case still stands at `AWAITING_REDEPOSIT` transitions to `SENT`,
    recording `days_remaining` — the count of days from the send date to the
    case's `rollover_deadline_date` — and `outstanding_cents`, the case's
    `gross_cents` minus its `credited_total_cents` at send time."

    Design: Corner/complexity_layers/scheduled_notice_sweep_timing
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", receiving_plan_type="IRA")
    case_id = bundle["case"]["id"]
    ops = make_operations_headers()

    # Notices are due 2026-07-01 / 2026-07-16 / 2026-07-26; deadline 2026-07-31.
    set_logical_clock("2026-07-05T00:00:00Z")
    sweep1 = validate_success(api_client.run_daily_sweep(ops))
    assert sweep1["notices_sent"] == 1, f"only notice 1 is due, got {sweep1}"

    resp = api_client.list_case_notices(case_id, PROC1)
    notices, _ = validate_paginated(resp)
    by_seq = {n["notice_seq"]: n for n in notices}
    assert by_seq[1]["status"] == "SENT"
    assert by_seq[1]["days_remaining"] == 26, (
        f"2026-07-31 minus 2026-07-05 is 26 days, got {by_seq[1]['days_remaining']}"
    )
    assert by_seq[1]["outstanding_cents"] == 10800000
    assert by_seq[2]["status"] == "SCHEDULED"
    assert by_seq[3]["status"] == "SCHEDULED"

    set_logical_clock("2026-07-30T00:00:00Z")
    sweep2 = validate_success(api_client.run_daily_sweep(ops))
    assert sweep2["notices_sent"] == 2, f"notices 2 and 3 are now due, got {sweep2}"

    resp = api_client.list_case_notices(case_id, PROC1)
    notices, _ = validate_paginated(resp)
    by_seq = {n["notice_seq"]: n for n in notices}
    assert by_seq[3]["status"] == "SENT"
    assert by_seq[3]["days_remaining"] == 1, (
        f"2026-07-31 minus 2026-07-30 is 1 day, got {by_seq[3]['days_remaining']}"
    )

    case = get_case(case_id)
    assert case["status"] == "AWAITING_REDEPOSIT", (
        "the deadline has not passed at sweep time, so the case still awaits redeposit"
    )
