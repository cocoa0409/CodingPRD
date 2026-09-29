"""Asbestos screening, retrofit exclusion and the four-hop cascade they run."""

from test_helpers import (
    ADMIN_HEADERS,
    CLAIM_PAID,
    CLAIM_SUBMITTED,
    CLAIM_WITHDRAWN,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_EXCLUDED,
    ELIGIBILITY_PENDING_SCREENING,
    ERR_DUCT_SYSTEM_INVALID_STATE,
    EXCLUSION_ASBESTOS_CONFIRMED,
    EXCLUSION_INACCESSIBLE,
    EXCLUSION_MATERIAL_NOT_SEALABLE,
    INSPECTOR_PASS,
    JOB_ABORTED_EXCLUSION,
    JOB_SCHEDULED,
    MATERIAL_ASBESTOS_WRAP,
    QA_HEADERS,
    REPORT_VOIDED,
    SCREENING_CLEARED,
    SCREENING_CONFIRMED,
    SCREENING_SUSPECT,
    SEAL_STATUS_SEAL_PENDING,
    SEAL_STATUS_SEALING,
    assert_leakage_ledger,
    assert_program_ledger,
    assert_program_ledger_identity,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)


def test_a_confirmed_screening_unwinds_the_run_report_and_claim_beneath_it(api):
    """One screening result reaches four hops down and releases the committed money.

    PRD 3.2: "Hop two, caused by hop one, sweeps every sealing run on that system
    ... into `ABORTED_EXCLUSION`, stamping `abort_reason` as `asbestos confirmed`.
    Hop three, caused by hop two, drives every verification report belonging to one
    of those aborted runs whose status is `DRAFT`, `ISSUED` or
    `CORRECTION_REQUIRED` into `VOIDED`. Hop four, caused by hop three, drives
    every rebate claim referencing one of those voided reports whose status is
    `SUBMITTED`, `APPROVED` or `RETURNED_FOR_CORRECTION` into `WITHDRAWN`, sets
    that claim's `committed` flag to false, and releases its `payable_cents` from
    the program's `committed_rebate_cents`, raising `remaining_budget_cents` by
    the same amount."

    Design: Difficulty/transitive_cascade/asbestos_confirmation_cascade_depth_four
    """
    sc = fx.scenario_submitted_claim(api)
    assert sc.claim["status"] == CLAIM_SUBMITTED
    payable = sc.claim["payable_cents"]
    assert sc.read_project()["eligible_duct_system_count"] == 1

    validate_success(
        api.record_asbestos_screening(
            sc.duct_system_id,
            f.asbestos_screening_payload(
                asbestos_screening_result=SCREENING_CONFIRMED, lab_reference="LAB-2002"
            ),
            QA_HEADERS,
        )
    )

    duct_system = sc.read_duct_system()
    assert duct_system["asbestos_screening_result"] == SCREENING_CONFIRMED
    assert duct_system["eligibility_status"] == ELIGIBILITY_EXCLUDED
    assert duct_system["exclusion_reason"] == EXCLUSION_ASBESTOS_CONFIRMED
    assert duct_system["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert duct_system["active_seal_job_id"] is None
    assert_leakage_ledger(duct_system, 300.00, 300.00, 0.00)
    assert sc.read_project()["eligible_duct_system_count"] == 0

    job = sc.read_seal_job()
    assert job["status"] == JOB_ABORTED_EXCLUSION
    assert job["abort_reason"] == "asbestos confirmed"

    assert sc.read_report()["status"] == REPORT_VOIDED

    claim = sc.read_claim()
    assert claim["status"] == CLAIM_WITHDRAWN
    assert claim["committed"] is False
    assert claim["payable_cents"] == payable, "the frozen amount is retained on the row"

    program = sc.read_program()
    assert_program_ledger(program, 0, 0, 5000000)
    assert_program_ledger_identity(program)


def test_a_confirmed_screening_before_clearance_leaves_the_eligible_counter_alone(api):
    """The counter only falls when the row it terminalises had actually been eligible.

    PRD 3.2: "the project's `eligible_duct_system_count` drops by 1 — but only when
    the previous `eligibility_status` was `ELIGIBLE`"; "A result of `CONFIRMED` ...
    may be recorded from either `PENDING_SCREENING` or `ELIGIBLE`."

    Design: Difficulty/transitive_cascade/asbestos_confirmation_cascade_depth_four
    """
    sc = fx.scenario_base(api)
    duct_system = fx.add_duct_system(sc, clear_screening=False)
    assert duct_system["eligibility_status"] == ELIGIBILITY_PENDING_SCREENING
    assert sc.read_project()["eligible_duct_system_count"] == 0

    confirmed = validate_success(
        api.record_asbestos_screening(
            duct_system["id"],
            f.asbestos_screening_payload(
                asbestos_screening_result=SCREENING_CONFIRMED, lab_reference="LAB-2002"
            ),
            QA_HEADERS,
        )
    )
    assert confirmed["eligibility_status"] == ELIGIBILITY_EXCLUDED
    assert confirmed["exclusion_reason"] == EXCLUSION_ASBESTOS_CONFIRMED
    assert confirmed["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert confirmed["version"] == 2, "every screening bumps the duct system's version by 1"

    project = sc.read_project()
    assert project["duct_system_count"] == 1
    assert project["eligible_duct_system_count"] == 0


def test_withdrawing_a_claim_by_exclusion_restores_the_program_budget_exactly(api):
    """Money released by a withdrawal returns to `remaining_budget_cents` in full.

    PRD 2.11: "Releasing a commitment — because an inspector spot check failed, or
    because a retrofit exclusion withdrew the claim — subtracts `payable_cents`
    from `committed_rebate_cents` and raises `remaining_budget_cents` by the same
    amount, and sets the claim's `committed` flag to false."

    Design: Difficulty/compensating_invariant/claim_withdraw_restores_program_budget_identity
    """
    sc = fx.scenario_submitted_claim(api)
    payable = sc.claim["payable_cents"]
    before = sc.read_program()
    assert_program_ledger(before, payable, 0, 5000000 - payable)

    validate_success(
        api.exclude_duct_system(
            sc.duct_system_id,
            f.exclude_payload(exclusion_reason=EXCLUSION_INACCESSIBLE),
            ADMIN_HEADERS,
        )
    )

    duct_system = sc.read_duct_system()
    assert duct_system["eligibility_status"] == ELIGIBILITY_EXCLUDED
    assert duct_system["exclusion_reason"] == EXCLUSION_INACCESSIBLE
    assert_leakage_ledger(duct_system, 300.00, 300.00, 0.00)

    claim = sc.read_claim()
    assert claim["status"] == CLAIM_WITHDRAWN
    assert claim["committed"] is False
    assert claim["payable_cents"] == payable

    after = sc.read_program()
    assert_program_ledger(after, 0, 0, 5000000)
    assert after["annual_budget_cents"] == 5000000
    assert_program_ledger_identity(after)

    assert sc.read_report()["status"] == REPORT_VOIDED
    assert sc.read_seal_job()["status"] == JOB_ABORTED_EXCLUSION


def test_an_exclusion_after_payment_leaves_the_paid_money_where_it_is(api):
    """Hop four reaches only claims still holding a commitment, never a paid one.

    PRD 3.2 hop four covers "every rebate claim referencing one of those voided
    reports whose status is `SUBMITTED`, `APPROVED` or
    `RETURNED_FOR_CORRECTION`"; PRD 3.8: payment "moves the claim to the terminal
    `PAID` status, sets `committed` false, subtracts `payable_cents` from the
    program's `committed_rebate_cents` and adds it to `paid_rebate_cents` — so
    `remaining_budget_cents` does not move".

    Design: Difficulty/compensating_invariant/claim_withdraw_restores_program_budget_identity
    """
    sc = fx.scenario_submitted_claim(api)
    payable = sc.claim["payable_cents"]
    approved = fx.record_spot_check(sc)
    assert approved["inspector_outcome"] == INSPECTOR_PASS
    paid = validate_success(api.pay_rebate_claim(sc.claim_id, f.pay_payload(), ADMIN_HEADERS))
    assert paid["status"] == CLAIM_PAID
    assert_program_ledger(sc.read_program(), 0, payable, 5000000 - payable)

    validate_success(
        api.exclude_duct_system(
            sc.duct_system_id,
            f.exclude_payload(exclusion_reason=EXCLUSION_INACCESSIBLE),
            ADMIN_HEADERS,
        )
    )

    assert sc.read_report()["status"] == REPORT_VOIDED
    assert sc.read_seal_job()["status"] == JOB_ABORTED_EXCLUSION
    claim = sc.read_claim()
    assert claim["status"] == CLAIM_PAID, "a paid claim is not reached by hop four"
    assert claim["payment_reference"] == "ACH-90211"

    program = sc.read_program()
    assert_program_ledger(program, 0, payable, 5000000 - payable)
    assert_program_ledger_identity(program)


def test_a_suspect_screening_stamps_the_result_but_holds_the_eligibility(api):
    """`SUSPECT` is a self-loop: it records the lab report and changes nothing else.

    PRD 3.2: "A result of `SUSPECT` stamps the result and the reference but leaves
    `eligibility_status` at `PENDING_SCREENING`, so the system stays unsealable
    until a re-screen either clears or confirms it. Every screening bumps the duct
    system's `version` by 1."

    Design: Corner/state_machines/suspect_screening_keeps_duct_system_in_pending_screening
    """
    sc = fx.scenario_base(api)
    duct_system = fx.add_duct_system(sc, clear_screening=False)

    suspect = validate_success(
        api.record_asbestos_screening(
            duct_system["id"],
            f.asbestos_screening_payload(
                asbestos_screening_result=SCREENING_SUSPECT, lab_reference="LAB-1001"
            ),
            QA_HEADERS,
        )
    )
    assert suspect["asbestos_screening_result"] == SCREENING_SUSPECT
    assert suspect["lab_reference"] == "LAB-1001"
    assert suspect["eligibility_status"] == ELIGIBILITY_PENDING_SCREENING
    assert suspect["exclusion_reason"] is None
    assert suspect["version"] == 2
    assert sc.read_project()["eligible_duct_system_count"] == 0

    cleared = validate_success(
        api.record_asbestos_screening(
            duct_system["id"],
            f.asbestos_screening_payload(
                asbestos_screening_result=SCREENING_CLEARED, lab_reference="LAB-1002"
            ),
            QA_HEADERS,
        )
    )
    assert cleared["asbestos_screening_result"] == SCREENING_CLEARED
    assert cleared["lab_reference"] == "LAB-1002"
    assert cleared["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert cleared["version"] == 3
    assert sc.read_project()["eligible_duct_system_count"] == 1


def test_excluded_is_terminal_for_both_screening_and_exclusion(api):
    """A structurally disqualified system refuses every further eligibility write.

    PRD 3.2: "A result of `CLEARED` on a system that nonetheless fails one of those
    two structural tests does the opposite: `eligibility_status` goes straight to
    `EXCLUDED`, with `exclusion_reason` recorded as ... `MATERIAL_NOT_SEALABLE`
    when the disqualifier was a `duct_material` of `ASBESTOS_WRAP`"; "Screening —
    or excluding — a system whose `eligibility_status` already reads `EXCLUDED` is
    rejected with `ERR_DUCT_SYSTEM_INVALID_STATE`, because `EXCLUDED` is terminal
    on that dimension."

    Design: Corner/state_machines/excluding_an_already_excluded_duct_system_returns_duct_system_invalid_state
    """
    sc = fx.scenario_base(api)
    duct_system = validate_success(
        api.create_duct_system(
            sc.project_id,
            f.duct_system_payload(duct_material=MATERIAL_ASBESTOS_WRAP),
            ADMIN_HEADERS,
        ),
        201,
    )
    excluded = validate_success(
        api.record_asbestos_screening(
            duct_system["id"], f.asbestos_screening_payload(), QA_HEADERS
        )
    )
    assert excluded["eligibility_status"] == ELIGIBILITY_EXCLUDED
    assert excluded["exclusion_reason"] == EXCLUSION_MATERIAL_NOT_SEALABLE
    assert excluded["seal_status"] == SEAL_STATUS_SEAL_PENDING

    validate_error(
        api.record_asbestos_screening(
            duct_system["id"],
            f.asbestos_screening_payload(lab_reference="LAB-9999"),
            QA_HEADERS,
        ),
        ERR_DUCT_SYSTEM_INVALID_STATE,
        409,
    )
    validate_error(
        api.exclude_duct_system(
            duct_system["id"],
            f.exclude_payload(exclusion_reason=EXCLUSION_INACCESSIBLE),
            ADMIN_HEADERS,
        ),
        ERR_DUCT_SYSTEM_INVALID_STATE,
        409,
    )

    after = validate_success(api.get_duct_system(duct_system["id"], ADMIN_HEADERS))
    assert after["exclusion_reason"] == EXCLUSION_MATERIAL_NOT_SEALABLE
    assert after["lab_reference"] == "LAB-1001"
    assert sc.read_project()["eligible_duct_system_count"] == 0


def test_eligibility_and_seal_progress_are_two_independent_dimensions(api):
    """One row carries both dimensions and they move on their own schedules.

    PRD 2.10: "A duct system carries **two independent state dimensions on the same
    row**. `eligibility_status` tracks retrofit eligibility and moves through
    `PENDING_SCREENING`, `ELIGIBLE` and the terminal `EXCLUDED`. `seal_status`
    tracks sealing progress and moves through `SEAL_PENDING`, `SEALING`, `SEALED`
    and `VERIFIED`. The two advance separately".

    Design: Corner/state_machines/duct_system_eligibility_and_seal_dimensions_advance_independently
    """
    sc = fx.scenario_ready_to_inject(api)
    before = sc.read_duct_system()
    assert before["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert before["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert before["active_seal_job_id"] is None

    job = fx.schedule_seal_job(sc)
    assert job["status"] == JOB_SCHEDULED
    scheduled_view = sc.read_duct_system()
    assert scheduled_view["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert scheduled_view["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert scheduled_view["active_seal_job_id"] == job["id"]

    fx.mask_all_registers(sc)
    fx.begin_injection(sc)

    injecting_view = sc.read_duct_system()
    assert injecting_view["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert injecting_view["seal_status"] == SEAL_STATUS_SEALING
    assert injecting_view["active_seal_job_id"] == job["id"]
    assert_leakage_ledger(injecting_view, 300.00, 300.00, 0.00)
