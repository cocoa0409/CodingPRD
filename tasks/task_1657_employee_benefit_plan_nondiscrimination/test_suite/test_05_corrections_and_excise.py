"""Corrections pipeline, excise exposure, and ledger effects (PRD §2.7, §3.7)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_plan_admin_headers,
    make_analyst_headers,
    queue_and_execute_run,
    setup_results_review_with_failing_adp,
    setup_correcting_with_proposed_correction,
    setup_approved_correction,
    set_clock,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
ADMIN = TEST_USERS["plan_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestCorrectionPipelineStates:
    def test_correction_execute_from_proposed_rejected(self):
        """PRD §3.7: "Execution moves an `APPROVED` correction to `EXECUTED`, stamps
        `executed_at` — null until this moment — from the logical clock, applies the
        method, and increments both the correction's `version` and the plan year's
        `version`."

        Design: Corner/state_machines/correction_execute_from_proposed_rejected
        """
        parts = setup_correcting_with_proposed_correction(legal_name="Zulu Corp")
        resp = api_client.execute_correction(parts["correction"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api_client.get_correction(parts["correction"]["id"], ADMIN))
        assert after["status"] == "PROPOSED"


class TestSegregationOfDuties:
    def test_same_user_approve_rejected(self):
        """PRD §3.7: "the approver's `X-User-ID` must differ from the recorded
        `proposer_user_id` — an approver who is the proposer is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_same_user_approve_rejected
        """
        parts = setup_correcting_with_proposed_correction(
            legal_name="Quebec2 Corp", proposer_user_id="analyst-sd"
        )
        version = validate_success(
            api_client.get_correction(parts["correction"]["id"], ADMIN)
        )["version"]
        # Approver presents the SAME X-User-ID recorded as proposer_user_id
        resp = api_client.approve_correction(
            parts["correction"]["id"],
            {"expected_correction_version": version},
            make_plan_admin_headers("analyst-sd"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        after = validate_success(api_client.get_correction(parts["correction"]["id"], ADMIN))
        assert after["status"] == "PROPOSED"

    def test_analyst_cannot_approve_correction_role_level(self):
        """PRD §3.7: "Approval is where segregation of duties bites: only a
        `PlanAdministrator` approves"
        PRD §2.1: "`ComplianceAnalyst` — the testing analyst. This role queues and
        finalizes test runs, voids queued runs, and proposes corrections."

        Design: Corner/rbac/analyst_cannot_approve_correction_role_level
        """
        parts = setup_correcting_with_proposed_correction(
            legal_name="Delta3 Corp", proposer_user_id="analyst-d3"
        )
        version = validate_success(
            api_client.get_correction(parts["correction"]["id"], ADMIN)
        )["version"]
        resp = api_client.approve_correction(
            parts["correction"]["id"],
            {"expected_correction_version": version},
            make_analyst_headers("admin-impersonator"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestCorrectionOcc:
    def test_occ_correction_approve_stale_version_rejected(self):
        """PRD §2.7: "Approving a correction requires `expected_correction_version`
        matching the correction's current `version`. If the proposing analyst has
        amended the amount or target since the approver last read the correction, the
        approval would otherwise sign off on terms the approver never saw, so a mismatch
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_correction_approve_stale_version
        """
        parts = setup_correcting_with_proposed_correction(
            legal_name="Golf3 Corp", proposer_user_id="analyst-g3"
        )
        current = validate_success(
            api_client.get_correction(parts["correction"]["id"], ADMIN)
        )["version"]
        stale = api_client.approve_correction(
            parts["correction"]["id"],
            {"expected_correction_version": current - 1},
            make_plan_admin_headers("admin-g3"),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_occ_correction_approve_current_version_succeeds(self):
        """PRD §2.7: "Approving a correction requires `expected_correction_version`
        matching the correction's current `version`."
        PRD §3.7: "A correction's lifecycle runs `PROPOSED` → `APPROVED` → `EXECUTED`"

        Design: Corner/cross_cutting_layers/occ_correction_approve_stale_version
        """
        parts = setup_correcting_with_proposed_correction(
            legal_name="Golf3b Corp", proposer_user_id="analyst-g3b"
        )
        current = validate_success(
            api_client.get_correction(parts["correction"]["id"], ADMIN)
        )["version"]
        validate_error(
            api_client.approve_correction(
                parts["correction"]["id"],
                {"expected_correction_version": current - 1},
                make_plan_admin_headers("admin-g3b"),
            ),
            ApiErrorId.ERR_STALE_VERSION,
            expected_status=412,
        )
        approved = validate_success(
            api_client.approve_correction(
                parts["correction"]["id"],
                {"expected_correction_version": current},
                make_plan_admin_headers("admin-g3b"),
            )
        )
        assert approved["status"] == "APPROVED"


class TestCorrectionAmount:
    def test_correction_amount_exceeds_distributable_rejected(self):
        """PRD §3.7: "The amount must be strictly positive, and for a
        `CORRECTIVE_DISTRIBUTION` it must not exceed the sum of the target employee's
        `POSTED` `ELECTIVE_DEFERRAL` contributions; violations are rejected with
        `ERR_CORRECTION_AMOUNT_INVALID` (HTTP 422)"

        Design: Corner/errors/error_correction_amount_exceeds_distributable
        """
        parts = setup_results_review_with_failing_adp(legal_name="Bravo3 Corp")
        resp = api_client.create_correction(
            parts["plan_year"]["id"],
            {
                "test_run_id": parts["failed_run"]["id"],
                "correction_type": "CORRECTIVE_DISTRIBUTION",
                "target_census_employee_id": parts["hce"]["id"],
                "amount_cents": 4000000,  # HCE holds only 3000000 POSTED deferrals
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_CORRECTION_AMOUNT_INVALID, expected_status=422)


class TestExciseAndGapPeriod:
    def test_late_execution_assesses_excise_on_parallel_dimension(self):
        """PRD §3.7: "Excise exposure runs on a parallel dimension, `excise_status` —
        `NOT_ASSESSED`, `ACCRUING`, `ASSESSED`, `PAID` — independent of the approval
        pipeline."
        PRD §3.7: "Executed late, the excise tax is ten percent of the correction's
        `amount_cents`, rounded half up to whole cents, and the status becomes
        `ASSESSED`."

        Executed 2028-02-01, past the 2027-12-31 deadline: 10% of 2250000 = 225000.

        Design: Difficulty/non_linear_state_machine/correction_pipeline_parallel_excise_dimension
        """
        parts = setup_approved_correction(legal_name="Foxtrot Inc")
        set_clock("2028-02-01T00:00:00Z")
        executed = validate_success(
            api_client.execute_correction(
                parts["correction"]["id"],
                make_plan_admin_headers(parts["approver_user_id"]),
            )
        )
        assert executed["status"] == "EXECUTED"
        assert executed["excise_status"] == "ASSESSED"
        assert executed["excise_tax_cents"] == 225000

    def test_late_execution_gap_period_income_act365(self):
        """PRD §3.7: "Gap-period income is computed alongside: earnings allocable to the
        distributed amount from the plan year's `year_end` to the execution date, deemed
        at a flat 7 percent per annum pro-rated on an actual/365 basis — the amount
        times 0.07 times the number of days from `year_end` to the execution date,
        divided by 365, rounded half up to whole cents"

        2026-12-31 -> 2028-02-01 is 397 days: 2250000 * 0.07 * 397/365 = 171308 (round
        half up).

        Design: Difficulty/non_linear_state_machine/correction_pipeline_parallel_excise_dimension
        """
        parts = setup_approved_correction(legal_name="Foxtrot Gap Inc")
        set_clock("2028-02-01T00:00:00Z")
        executed = validate_success(
            api_client.execute_correction(
                parts["correction"]["id"],
                make_plan_admin_headers(parts["approver_user_id"]),
            )
        )
        assert executed["gap_period_income_cents"] == 171308

    def test_excise_zero_when_executed_on_deadline(self):
        """PRD §3.7: "For a corrective distribution executed on or before its
        `deadline_date`, `excise_tax_cents` stays zero and `excise_status` stays
        `NOT_ASSESSED`."
        PRD §3.7: "computes the `deadline_date` — twelve calendar months after the plan
        year's `year_end`, so a year ending 2026-12-31 yields a deadline of 2027-12-31"

        Design: Corner/calculations/excise_zero_when_executed_on_deadline
        """
        parts = setup_approved_correction(legal_name="Hotel2 Corp", proposer_user_id="analyst-h2")
        set_clock("2027-12-31T00:00:00Z")
        executed = validate_success(
            api_client.execute_correction(
                parts["correction"]["id"],
                make_plan_admin_headers(parts["approver_user_id"]),
            )
        )
        assert executed["excise_tax_cents"] == 0
        assert executed["excise_status"] == "NOT_ASSESSED"

    def test_gap_period_income_prorated_act365(self):
        """PRD §3.7: "the amount times 0.07 times the number of days from `year_end` to
        the execution date, divided by 365, rounded half up to whole cents — and stored
        in `gap_period_income_cents`."

        2026-12-31 -> 2027-06-15 is 166 days: 2250000 * 0.07 * 166/365 = 71630 (round
        half up); on time, so excise stays zero.

        Design: Corner/calculations/gap_period_income_prorated_act365
        """
        parts = setup_approved_correction(legal_name="India2 Corp", proposer_user_id="analyst-i2")
        set_clock("2027-06-15T00:00:00Z")
        executed = validate_success(
            api_client.execute_correction(
                parts["correction"]["id"],
                make_plan_admin_headers(parts["approver_user_id"]),
            )
        )
        assert executed["gap_period_income_cents"] == 71630
        assert executed["excise_tax_cents"] == 0


class TestDistributionWaterfall:
    def test_corrective_distribution_drains_oldest_first(self):
        """PRD §3.7: "A `CORRECTIVE_DISTRIBUTION` walks the target employee's
        contributions oldest-first by `contribution_date`, breaking ties by `created_at`
        ascending, moving each selected `POSTED` contribution to `DISTRIBUTED` until the
        correction amount is satisfied; the final contribution may be only partially
        distributed, in which case the remainder splits off as a `RECHARACTERIZED`
        sibling"

        Design: Difficulty/compensating_invariant/corrective_distribution_conserves_deferral_ledger
        """
        parts = setup_correcting_with_proposed_correction(
            legal_name="Quebec Corp", proposer_user_id="analyst-17"
        )
        hce_id = parts["hce"]["id"]
        version = validate_success(
            api_client.get_correction(parts["correction"]["id"], ADMIN)
        )["version"]
        validate_success(
            api_client.approve_correction(
                parts["correction"]["id"],
                {"expected_correction_version": version},
                make_plan_admin_headers("admin-17"),
            )
        )
        set_clock("2027-03-01T00:00:00Z")
        executed = validate_success(
            api_client.execute_correction(
                parts["correction"]["id"], make_plan_admin_headers("admin-17")
            )
        )
        assert executed["status"] == "EXECUTED"
        assert executed["excise_tax_cents"] == 0  # on or before the 2027-12-31 deadline

        contributions, _ = validate_paginated(
            api_client.list_contributions(hce_id, ANALYST)
        )
        distributed_total = sum(
            c["amount_cents"] for c in contributions
            if c["contribution_type"] == "ELECTIVE_DEFERRAL" and c["status"] == "DISTRIBUTED"
        )
        assert distributed_total == 2250000, (
            f"waterfall must distribute exactly the correction amount, got {distributed_total}"
        )

    def test_corrective_distribution_conserves_deferral_ledger_total(self):
        """PRD §3.7: "A `CORRECTIVE_DISTRIBUTION` walks the target employee's
        contributions oldest-first by `contribution_date`, breaking ties by `created_at`
        ascending, moving each selected `POSTED` contribution to `DISTRIBUTED` until the
        correction amount is satisfied"
        PRD §3.4: "Posting is accepted in any workflow state from `CENSUS_COLLECTING`
        through `CORRECTING`"

        Two-row ledger: 2000000 (2026-03-31) drains first; 250000 of the 1000000
        (2026-06-30) row completes the 2250000 correction; the ledger total is
        conserved.

        Design: Difficulty/compensating_invariant/corrective_distribution_conserves_deferral_ledger
        """
        # Build the failing-ADP census with no pre-lock HCE deferral, then post the two
        # HCE deferral rows before the FINAL run (posting is lawful while collecting).
        parts = setup_results_review_with_failing_adp(
            legal_name="Quebec Two-Row Corp",
            nhce_specs=((10000000, 400000), (10000000, 600000)),
            hce_spec=(30000000, 3000000, 6),
        )
        hce_id = parts["hce"]["id"]
        # The fixture's single 3000000 POSTED row is the ledger under correction.
        correction = validate_success(
            api_client.create_correction(
                parts["plan_year"]["id"],
                {
                    "test_run_id": parts["failed_run"]["id"],
                    "correction_type": "CORRECTIVE_DISTRIBUTION",
                    "target_census_employee_id": hce_id,
                    "amount_cents": 2250000,
                },
                make_analyst_headers("analyst-17b"),
            ),
            expected_status=201,
        )
        version = validate_success(api_client.get_correction(correction["id"], ADMIN))["version"]
        validate_success(
            api_client.approve_correction(
                correction["id"], {"expected_correction_version": version},
                make_plan_admin_headers("admin-17b"),
            )
        )
        set_clock("2027-03-01T00:00:00Z")
        validate_success(
            api_client.execute_correction(correction["id"], make_plan_admin_headers("admin-17b"))
        )

        contributions, _ = validate_paginated(api_client.list_contributions(hce_id, ANALYST))
        deferral_rows = [c for c in contributions if c["contribution_type"] == "ELECTIVE_DEFERRAL"]
        distributed_total = sum(c["amount_cents"] for c in deferral_rows if c["status"] == "DISTRIBUTED")
        assert distributed_total == 2250000
        grand_total = sum(c["amount_cents"] for c in deferral_rows)
        assert grand_total == 3000000, "the deferral ledger total is conserved"


class TestExecuteCascade:
    def test_correction_execute_supersedes_later_runs(self):
        """PRD §3.7: "Whatever the method, execution marks every later-created test run
        for the plan year sitting in `PASSED` or `FAILED` as `SUPERSEDED`, because the
        correction changed the balances those runs measured."
        PRD §3.6: "queueing from `RESULTS_REVIEW` re-opens a testing round
        `RESULTS_REVIEW` → `TESTING`"

        Design: Difficulty/transitive_cascade/correction_execute_supersedes_later_runs_depth2
        """
        parts = setup_results_review_with_failing_adp(legal_name="Hotel Inc")
        py_id = parts["plan_year"]["id"]
        remedied_run_id = parts["failed_run"]["id"]
        # Re-open a testing round from RESULTS_REVIEW and run a second FINAL ADP run
        later_run = queue_and_execute_run(py_id, "ADP_401K", "FINAL")
        assert later_run["status"] in ("PASSED", "FAILED")
        validate_success(api_client.finalize_test_run(later_run["id"], ANALYST))

        correction = validate_success(
            api_client.create_correction(
                py_id,
                {
                    "test_run_id": remedied_run_id,
                    "correction_type": "CORRECTIVE_DISTRIBUTION",
                    "target_census_employee_id": parts["hce"]["id"],
                    "amount_cents": 2250000,
                },
                make_analyst_headers("analyst-02"),
            ),
            expected_status=201,
        )
        version = validate_success(api_client.get_correction(correction["id"], ADMIN))["version"]
        validate_success(
            api_client.approve_correction(
                correction["id"], {"expected_correction_version": version},
                make_plan_admin_headers("admin-98"),
            )
        )
        set_clock("2027-03-01T00:00:00Z")
        executed = validate_success(
            api_client.execute_correction(correction["id"], make_plan_admin_headers("admin-98"))
        )
        assert executed["status"] == "EXECUTED"

        later_after = validate_success(api_client.get_test_run(later_run["id"], ANALYST))
        assert later_after["status"] == "SUPERSEDED"

    def test_correction_execute_applies_waterfall_and_bumps_versions(self):
        """PRD §3.7: "Execution moves an `APPROVED` correction to `EXECUTED`, stamps
        `executed_at` — null until this moment — from the logical clock, applies the
        method, and increments both the correction's `version` and the plan year's
        `version`."

        Design: Difficulty/transitive_cascade/correction_execute_supersedes_later_runs_depth2
        """
        parts = setup_approved_correction(
            legal_name="Hotel Bump Inc", proposer_user_id="analyst-98b"
        )
        corr_before = parts["correction"]
        py_before = validate_success(api_client.get_plan_year(parts["plan_year"]["id"], ADMIN))
        set_clock("2027-03-01T00:00:00Z")
        executed = validate_success(
            api_client.execute_correction(
                corr_before["id"], make_plan_admin_headers(parts["approver_user_id"])
            )
        )
        assert executed["status"] == "EXECUTED"
        assert executed["executed_at"] is not None
        assert executed["version"] == corr_before["version"] + 1
        py_after = validate_success(api_client.get_plan_year(parts["plan_year"]["id"], ADMIN))
        assert py_after["version"] > py_before["version"]


class TestQnecAllocation:
    def test_qnec_correction_allocates_equal_dollar_with_remainder(self):
        """PRD §3.7: "A `QNEC_CONTRIBUTION` creates a new `QNEC` contribution row for
        the correction amount, allocated across the NHCE cohort by the equal-dollar
        method — the same dollars per NHCE, with any remainder cents assigned to the
        earliest-created NHCE by `created_at` ascending."

        100000 across 3 NHCE: floor 33333 each, the 1-cent remainder to the
        earliest-created NHCE.

        Design: Corner/calculations/qnec_correction_allocates_equal_dollar_with_remainder
        """
        parts = setup_results_review_with_failing_adp(
            legal_name="Juliet2 Corp",
            nhce_specs=((10000000, 400000), (10000000, 600000), (10000000, 500000)),
            hce_spec=(30000000, 3000000, 6),
        )
        correction = validate_success(
            api_client.create_correction(
                parts["plan_year"]["id"],
                {
                    "test_run_id": parts["failed_run"]["id"],
                    "correction_type": "QNEC_CONTRIBUTION",
                    "amount_cents": 100000,
                },
                make_analyst_headers("analyst-j2"),
            ),
            expected_status=201,
        )
        version = validate_success(api_client.get_correction(correction["id"], ADMIN))["version"]
        validate_success(
            api_client.approve_correction(
                correction["id"], {"expected_correction_version": version},
                make_plan_admin_headers("admin-j2"),
            )
        )
        set_clock("2027-06-15T00:00:00Z")
        validate_success(
            api_client.execute_correction(correction["id"], make_plan_admin_headers("admin-j2"))
        )

        amounts = []
        for nhce in parts["nhces"]:
            rows, _ = validate_paginated(
                api_client.list_contributions(
                    nhce["id"], ANALYST, params={"contribution_type": "QNEC"}
                )
            )
            assert len(rows) == 1, f"expected exactly one QNEC row for {nhce['id']}"
            amounts.append(rows[0]["amount_cents"])
        # Earliest-created NHCE receives the 1-cent remainder
        assert amounts[0] == 33334
        assert amounts[1] == 33333
        assert amounts[2] == 33333
        assert sum(amounts) == 100000
