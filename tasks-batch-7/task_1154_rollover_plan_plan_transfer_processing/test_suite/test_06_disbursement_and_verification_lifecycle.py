"""Disbursement issuance lifecycle (return/reissue, cancel compensation,
freeze-window gating, validation priority) and verification terminal states."""
from test_helpers import (
    ApiErrorId,
    api_client,
    build_approved_indirect_case,
    build_issued_indirect_case,
    get_account,
    get_case,
    make_admin_headers,
    make_participant_headers,
    make_processor_headers,
    source_rows_by_type,
    open_verification,
    complete_verification,
    set_logical_clock,
    make_account,
    make_participant,
    make_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

PROC2 = make_processor_headers("proc-2")


def test_disbursement_return_reissue_cycle_statuses(api):
    """PRD §3.7: "An issued disbursement may be marked `RETURNED` (a bounced
    check, a rejected wire) while it is `ISSUED` — otherwise
    `ERR_DISBURSEMENT_INVALID_STATE`. A `RETURNED` disbursement may be reissued,
    returning to `ISSUED` with `issued_date` refreshed to the current clock
    date, provided the owning case is `DISBURSED` or `AWAITING_REDEPOSIT` (else
    `ERR_CASE_INVALID_STATE`)"

    Design: Difficulty/non_linear_state_machine/disbursement_return_reissue_cycle
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", method="CHECK")
    disb = bundle["disbursement"]
    assert disb["status"] == "ISSUED"

    set_logical_clock("2026-06-10T00:00:00Z")
    returned = validate_success(api_client.return_disbursement(disb["id"], PROC2))
    assert returned["status"] == "RETURNED", f"ISSUED -> RETURNED, got {returned['status']}"

    reissued = validate_success(api_client.reissue_disbursement(disb["id"], PROC2))
    assert reissued["status"] == "ISSUED", f"RETURNED -> ISSUED, got {reissued['status']}"
    assert reissued["issued_date"] == "2026-06-10", (
        f"reissue refreshes issued_date to the clock date, got {reissued['issued_date']}"
    )
    case = get_case(bundle["case"]["id"])
    assert case["status"] == "AWAITING_REDEPOSIT", (
        f"case stays AWAITING_REDEPOSIT throughout the cycle, got {case['status']}"
    )


def test_disbursement_reissue_does_not_restart_sixty_day_deadline(api):
    """PRD §3.7: "crucially, for indirect cases the 60-day deadline does **not**
    restart — `rollover_deadline_date` remains anchored to the first issuance."
    PRD §3.7: "The case's `disbursement_issued_date` is set to the clock date —
    the basis of the 60-day deadline — and never overwritten."

    Design: Difficulty/non_linear_state_machine/disbursement_return_reissue_cycle
    """
    bundle = build_issued_indirect_case(clock="2026-06-01T00:00:00Z", method="CHECK")
    case_id = bundle["case"]["id"]
    case = get_case(case_id)
    assert case["disbursement_issued_date"] == "2026-06-01"
    # 2026-06-01 + 60 calendar days == 2026-07-31.
    assert case["rollover_deadline_date"] == "2026-07-31", (
        f"deadline anchored at first issuance + 60 days, got {case['rollover_deadline_date']}"
    )

    set_logical_clock("2026-06-10T00:00:00Z")
    validate_success(api_client.return_disbursement(bundle["disbursement"]["id"], PROC2))
    validate_success(api_client.reissue_disbursement(bundle["disbursement"]["id"], PROC2))

    case = get_case(case_id)
    assert case["disbursement_issued_date"] == "2026-06-01", (
        "first-issuance anchor must never be overwritten by reissue"
    )
    assert case["rollover_deadline_date"] == "2026-07-31", (
        f"60-day clock must not restart on reissue, got {case['rollover_deadline_date']}"
    )


def test_disbursement_cancel_restores_sources_exactly(api):
    """PRD §3.7: "a disbursement in `PENDING` or `RETURNED` may be cancelled,
    transitioning to the terminal `CANCELLED` status with full compensation:
    every money-source row of the source account is credited back by exactly its
    issue-time allocation, so source balances return precisely to their
    pre-issue values."
    PRD §3.6: "for which the invariant `gross_cents` equals `withholding_cents`
    plus `net_cents` always holds"

    Design: Difficulty/compensating_invariant/disbursement_cancel_restores_exactly
    """
    bundle = build_approved_indirect_case(
        requested_amount_cents=1000000, clock="2026-05-01T00:00:00Z"
    )
    resp = api_client.assemble_disbursement(bundle["case"]["id"], {"method": "ACH"}, PROC2)
    disb = validate_success(resp)
    # Snapshot decomposition identity: 1,000,000 == 175,926 + 824,074.
    assert disb["gross_cents"] == 1000000
    assert disb["withholding_cents"] == 175926
    assert disb["net_cents"] == 824074
    assert disb["gross_cents"] == disb["withholding_cents"] + disb["net_cents"]

    cancelled = validate_success(api_client.cancel_disbursement(disb["id"], PROC2))
    assert cancelled["status"] == "CANCELLED"

    rows = source_rows_by_type(bundle["account"]["id"])
    assert rows["PRE_TAX"]["balance_cents"] == 8000000 and rows["PRE_TAX"]["basis_cents"] == 0
    assert rows["EMPLOYER_PRETAX"]["balance_cents"] == 2000000
    assert rows["EMPLOYER_PRETAX"]["vested_pct"] == 60
    assert rows["ROTH"]["balance_cents"] == 1000000 and rows["ROTH"]["basis_cents"] == 800000
    assert rows["AFTER_TAX"]["balance_cents"] == 600000 and rows["AFTER_TAX"]["basis_cents"] == 500000


def test_disbursement_cancel_leaves_case_eligible_and_totals_restored(api):
    """PRD §3.7: "a disbursement in `PENDING` or `RETURNED` may be cancelled,
    transitioning to the terminal `CANCELLED` status with full compensation:
    every money-source row of the source account is credited back by exactly its
    issue-time allocation, so source balances return precisely to their
    pre-issue values."
    PRD §3.6: "no non-`CANCELLED` disbursement may already exist for the case
    (else `ERR_DISBURSEMENT_ALREADY_EXISTS`)" (a cancelled disbursement
    therefore does not block the ELIGIBLE case).

    Design: Difficulty/compensating_invariant/disbursement_cancel_restores_exactly
    """
    bundle = build_approved_indirect_case(
        requested_amount_cents=1000000, clock="2026-05-01T00:00:00Z"
    )
    resp = api_client.assemble_disbursement(bundle["case"]["id"], {"method": "ACH"}, PROC2)
    disb = validate_success(resp)
    validate_success(api_client.cancel_disbursement(disb["id"], PROC2))

    case = get_case(bundle["case"]["id"])
    assert case["status"] == "ELIGIBLE", (
        f"the case must remain ELIGIBLE after its disbursement is cancelled, got {case['status']}"
    )
    account = get_account(bundle["account"]["id"])
    assert account["vested_balance_cents"] == 10800000, (
        f"vested restored to 10800000, got {account['vested_balance_cents']}"
    )
    assert account["total_balance_cents"] == 11600000, (
        f"total restored to 11600000, got {account['total_balance_cents']}"
    )


def test_state_error_beats_freeze_window_on_cancelled_disbursement(api):
    """PRD §2.9: "When a request fails several rules at once, the API answers
    with exactly one error, and which error it is must be deterministic. The
    system therefore evaluates validations in a fixed priority order, from
    broadest to most specific:"
    PRD §2.9: "4. **State** — the target must be in a state that permits the
    operation (`ERR_CASE_INVALID_STATE`, `ERR_PLAN_FROZEN`, `ERR_PLAN_TERMINATED`,
    `ERR_PLAN_NOT_FROZEN`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_DOCUMENT_INVALID_STATE`,
    `ERR_DISBURSEMENT_INVALID_STATE`, `ERR_REDEPOSIT_INVALID_STATE`,
    `ERR_VERIFICATION_INVALID_STATE`, `ERR_TAX_FORM_INVALID_STATE`,
    `ERR_LOAN_INVALID_STATE`)."
    PRD §2.9: "7. **Temporal gates** — deadlines and freeze windows
    (`ERR_DEPOSIT_PAST_DEADLINE`, `ERR_DISBURSEMENT_IN_FREEZE_WINDOW`,
    `ERR_FREEZE_WINDOW_OVERLAP`, `ERR_WINDOW_RANGE_INVALID`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_disbursement_issue
    """
    bundle = build_approved_indirect_case(
        requested_amount_cents=1000000, clock="2026-05-01T00:00:00Z"
    )
    resp = api_client.assemble_disbursement(bundle["case"]["id"], {"method": "ACH"}, PROC2)
    disb = validate_success(resp)
    validate_success(api_client.cancel_disbursement(disb["id"], PROC2))
    # Freeze window over the source plan; the clock lands inside it. The request
    # violates BOTH the state gate (disbursement CANCELLED) and the temporal gate.
    # PRD §4: adding a new, distinct resource to a collection returns 201.
    validate_success(api_client.create_freeze_window(
        bundle["plan"]["id"],
        {"start_date": "2026-06-10", "end_date": "2026-06-20", "reason": "recordkeeper conversion blackout"},
        make_admin_headers(),
    ), expected_status=201)
    set_logical_clock("2026-06-15T00:00:00Z")

    resp = api_client.issue_disbursement(disb["id"], PROC2)
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_INVALID_STATE, expected_status=409)

    # No side effects leaked from the rejected issuance.
    account = get_account(bundle["account"]["id"])
    assert account["vested_balance_cents"] == 10800000, (
        f"balances stay restored after the rejected issue, got {account['vested_balance_cents']}"
    )


def test_state_error_beats_freeze_window_on_issued_disbursement(api):
    """PRD §2.9: "When a request fails several rules at once, the API answers
    with exactly one error, and which error it is must be deterministic. The
    system therefore evaluates validations in a fixed priority order, from
    broadest to most specific:"
    PRD §3.7: "A `PENDING` disbursement becomes `ISSUED` when a
    `RolloverProcessor` issues it, provided the disbursement is `PENDING` (else
    `ERR_DISBURSEMENT_INVALID_STATE`), the owning case is `ELIGIBLE` (else
    `ERR_CASE_INVALID_STATE` — notably, a case `SUSPENDED` by a plan freeze
    blocks issuance), and the issue date read from the logical clock does not
    fall inside any freeze window of the source plan under the closed-interval
    rule of §2.10 (else `ERR_DISBURSEMENT_IN_FREEZE_WINDOW`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_disbursement_issue
    """
    bundle = build_approved_indirect_case(
        requested_amount_cents=1000000, clock="2026-05-01T00:00:00Z"
    )
    resp = api_client.assemble_disbursement(bundle["case"]["id"], {"method": "ACH"}, PROC2)
    disb = validate_success(resp)
    # Issue while outside any freeze window; then move the clock inside one.
    validate_success(api_client.issue_disbursement(disb["id"], PROC2))
    # PRD §4: adding a new, distinct resource to a collection returns 201.
    validate_success(api_client.create_freeze_window(
        bundle["plan"]["id"],
        {"start_date": "2026-06-10", "end_date": "2026-06-20", "reason": "blackout"},
        make_admin_headers(),
    ), expected_status=201)
    set_logical_clock("2026-06-15T00:00:00Z")

    # Dual failure: disbursement no longer PENDING AND clock inside the window.
    resp = api_client.issue_disbursement(disb["id"], PROC2)
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_INVALID_STATE, expected_status=409)


def test_disbursement_issue_inside_freeze_window_rejected(api):
    """PRD §3.7: "the issue date read from the logical clock does not fall
    inside any freeze window of the source plan under the closed-interval rule
    of §2.10 (else `ERR_DISBURSEMENT_IN_FREEZE_WINDOW`)"
    PRD §2.10: "the window is a *closed interval*: both the start date and the
    end date are inside the blackout."
    PRD §3.7: "Issuance stamps the disbursement's `issued_date` with the clock
    date"

    Design: Corner/validations/disbursement_issue_inside_freeze_window_rejected
    """
    bundle = build_approved_indirect_case(
        balances=[{"source_type": "PRE_TAX", "balance_cents": 500000,
                   "basis_cents": 0, "vested_pct": 100}],
        clock="2026-05-01T00:00:00Z",
    )
    # PRD §4: adding a new, distinct resource to a collection returns 201.
    validate_success(api_client.create_freeze_window(
        bundle["plan"]["id"],
        {"start_date": "2026-06-10", "end_date": "2026-06-20", "reason": "blackout"},
        make_admin_headers(),
    ), expected_status=201)
    resp = api_client.assemble_disbursement(bundle["case"]["id"], {"method": "ACH"}, PROC2)
    disb = validate_success(resp)

    # 2026-06-10 is the window's inclusive first day.
    set_logical_clock("2026-06-10T00:00:00Z")
    resp = api_client.issue_disbursement(disb["id"], PROC2)
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_IN_FREEZE_WINDOW, expected_status=422)

    # The day after the inclusive end is outside the blackout.
    set_logical_clock("2026-06-21T00:00:00Z")
    issued = validate_success(api_client.issue_disbursement(disb["id"], PROC2))
    assert issued["status"] == "ISSUED"
    assert issued["issued_date"] == "2026-06-21", (
        f"issued_date stamps the clock date, got {issued['issued_date']}"
    )


def test_verification_terminal_lockdown(api):
    """PRD §3.5: "The verification is born `PENDING` and completes when a
    processor records an `outcome` of `VERIFIED` or `FAILED` — completing a
    verification that is no longer `PENDING` is rejected with
    `ERR_VERIFICATION_INVALID_STATE`. A `VERIFIED` completion stamps
    `verified_at` with the logical clock; `FAILED` stamps nothing. Both outcomes
    are terminal."

    Design: Corner/state_machines/verification_terminal_lockdown
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    resp = api_client.create_rollover_case(
        {
            "case_type": "DIRECT_ROLLOVER_OUT",
            "source_account_id": account["id"],
            "receiving_institution_name": "External IRA Trust",
        },
        make_participant_headers(participant["id"]),
    )
    case = validate_success(resp, expected_status=201)
    ver = open_verification(case["id"], "OUTBOUND", method="IRS_FORM_LOOKUP")

    completed = complete_verification(ver["id"], "VERIFIED")
    assert completed["status"] == "VERIFIED"
    assert completed.get("verified_at"), "VERIFIED completion stamps verified_at"

    resp = api_client.complete_verification(
        ver["id"], {"outcome": "FAILED"}, make_processor_headers("proc-1")
    )
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_INVALID_STATE, expected_status=409)

    resp = api_client.list_case_verifications(case["id"], make_processor_headers("proc-1"))
    vers, _ = validate_paginated(resp)
    assert vers[0]["status"] == "VERIFIED", "terminal VERIFIED state is unchanged"
