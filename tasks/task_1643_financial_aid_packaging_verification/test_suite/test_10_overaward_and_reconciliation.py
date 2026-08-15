"""Over-award detection/resolution and year-end reconciliation: plan
validation and application, exact rollback restoration, the acceptance gate,
the close guard, the fund-close cascade, and variance arithmetic
(PRD §2.7, §3.8, §3.9)."""
from test_helpers import (
    SSN_SELECTED_B,
    TEST_USERS,
    ApiErrorId,
    accept_lines,
    assert_overaward_case,
    get_package,
    get_success_data,
    lines_by_fund,
    resolution_plan_step,
    setup_notified_package,
    setup_overaward_case,
    setup_reconciling_year,
    setup_reconciliation_with_posted,
    validate_error,
    validate_paginated,
    validate_success,
    create_external_aid_payload,
)

OFFICER = TEST_USERS["aid_officer_headers"]
DIRECTOR = TEST_USERS["aid_director_headers"]

PELL_PLUS_INST = [
    {"fund_code": "PELL", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 739500, "pool_budget_cents": 0, "packaging_rank": 1,
     "requires_verification_complete": False},
    {"fund_code": "INST_GRANT", "category": "INSTITUTIONAL", "need_based": True,
     "annual_cap_cents": 500000, "pool_budget_cents": 800000,
     "packaging_rank": 2, "requires_verification_complete": False},
]


class TestOverawardPlanApplyRollback:
    def test_plan_application_reduces_total_accepted(self, api):
        """PRD §3.8: "A valid plan is applied in array order: each step reduces the target line's `accepted_cents`, dropping the line from `ACCEPTED` to `PARTIALLY_ACCEPTED` when a positive remainder survives, and to `DECLINED` only when the reduction exactly equals the accepted amount and no disbursement has posted against the line; package totals and each affected fund's reserved pool are recomputed as the plan proceeds, firing `EXHAUSTED` → `ACTIVE` transitions where warranted. After the plan is applied, the case auto-transitions `RESOLVING` → `RESOLVED` once the recomputed total aid — the package's `total_accepted_cents` plus counted external aid — is at or below `coa_used_cents`."

        Design: Difficulty/compensating_invariant/overaward_plan_apply_rollback_restores_total_accepted
        """
        env = setup_overaward_case(ssn=SSN_SELECTED_B)
        case = env["case"]
        assert_overaward_case(case)
        # 739_500 + 350_000 + 500_000 accepted + 900_000 external - 2_400_000 COA.
        assert case["overage_cents"] == 89500
        assert case["status"] == "OPEN"

        inst_line = env["lines_by_code"]["INST_GRANT"]
        resp = api.begin_overaward_resolution(
            case["id"], [resolution_plan_step(inst_line["id"], 89500)],
            OFFICER)
        validate_success(resp)

        package = get_package(env["package"]["id"])
        # 1_589_500 - 89_500 = 1_500_000; total aid 2_400_000 == COA.
        assert package["total_accepted_cents"] == 1500000
        line = get_success_data(api.get_award_line(inst_line["id"], OFFICER))
        assert line["accepted_cents"] == 410500
        assert line["status"] == "PARTIALLY_ACCEPTED"
        resolved = get_success_data(api.get_overaward_case(case["id"], OFFICER))
        assert resolved["status"] == "RESOLVED"

    def test_rollback_restores_total_accepted_exactly(self, api):
        """PRD §3.8: "The rollback reverts every plan step, restoring each line's `accepted_cents`, and recomputes package and fund aggregates such that the package's `total_accepted_cents` returns to exactly its pre-plan value."
        PRD §3.8: "A rollback from `RESOLVING` — or from `RESOLVED`, reopening a resolved case any time before verification — returns the case to `OPEN`, but only while no `POSTED` disbursement exists on any line the plan modified."

        Design: Difficulty/compensating_invariant/overaward_plan_apply_rollback_restores_total_accepted
        """
        env = setup_overaward_case(ssn=SSN_SELECTED_B)
        case = env["case"]
        assert get_package(env["package"]["id"])["total_accepted_cents"] == 1589500

        inst_line = env["lines_by_code"]["INST_GRANT"]
        validate_success(api.begin_overaward_resolution(
            case["id"], [resolution_plan_step(inst_line["id"], 89500)],
            OFFICER))
        assert get_package(env["package"]["id"])["total_accepted_cents"] == 1500000

        rolled_back = validate_success(
            api.rollback_overaward_case(case["id"], OFFICER))
        assert rolled_back["status"] == "OPEN"

        package = get_package(env["package"]["id"])
        assert package["total_accepted_cents"] == 1589500
        line = get_success_data(api.get_award_line(inst_line["id"], OFFICER))
        assert line["accepted_cents"] == 500000
        assert line["status"] == "ACCEPTED"

    def test_plan_summing_below_overage_rejected(self, api):
        """PRD §3.8: "The plan is validated as a whole — it must be non-empty, every referenced line must belong to a package of the same student and aid year, each `reduce_by_cents` must be strictly positive and no more than its target line's `accepted_cents`, and the steps must sum to at least the `overage_cents`; any violation fails with `ERR_OVERAWARD_PLAN_INVALID` (422)."

        Design: Corner/validations/overaward_plan_invalid_sum_below_overage
        """
        env = setup_overaward_case(ssn=SSN_SELECTED_B)
        case = env["case"]
        assert case["overage_cents"] == 89500

        inst_line = env["lines_by_code"]["INST_GRANT"]
        # 80_000 < 89_500 overage: the plan under-cures the over-award.
        resp = api.begin_overaward_resolution(
            case["id"], [resolution_plan_step(inst_line["id"], 80000)],
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_OVERAWARD_PLAN_INVALID)
        current = get_success_data(api.get_overaward_case(case["id"], OFFICER))
        assert current["status"] == "OPEN"


class TestOverawardAcceptanceGate:
    def test_accept_blocked_while_overaward_case_open(self, api):
        """PRD §3.6: "Acceptance is also gated by rung 16: if an over-award case for the student and year is `OPEN` or `RESOLVING` and the offered-total-based detection still exceeds the cost snapshot, the acceptance is rejected with `ERR_OVERAWARD_UNRESOLVED`."
        PRD §3.8: "while the package is `DRAFT`, `PACKAGED`, `NOTIFIED`, or `REVISION_REQUESTED`, the counted figure is `total_offered_cents`; once it is `PARTIALLY_ACCEPTED`, `ACCEPTED`, or `LOCKED`, the counted figure is `total_accepted_cents`."
        PRD §3.8: "When the overage is strictly positive and no case for the student and year is already `OPEN` or `RESOLVING`, an OverawardCase is created in `OPEN` recording `detected_total_aid_cents` and `overage_cents`; when the overage is zero or negative, an existing `OPEN` case is left alone — there is no automatic close, only the manual rollback path."

        Design: Corner/errors/error_overaward_unresolved_accept_blocked
        """
        env = setup_notified_package(ssn=SSN_SELECTED_B,
                                     fund_specs=PELL_PLUS_INST)
        by_code = lines_by_fund(env["lines"], env["funds"])
        # Package NOTIFIED with offered 739_500 + 500_000 = 1_239_500.
        assert env["package"]["total_offered_cents"] == 1239500

        get_success_data(api.create_external_aid(
            create_external_aid_payload(env["student"]["id"],
                                        env["aid_year"]["id"],
                                        source_name="Big Scholarship",
                                        amount_cents=1500000), OFFICER))
        cases, _meta = validate_paginated(
            api.list_student_overaward_cases(env["student"]["id"], OFFICER))
        assert len(cases) == 1
        # Offered-based detection: 1_239_500 + 1_500_000 - 2_400_000.
        assert cases[0]["overage_cents"] == 339500
        assert cases[0]["status"] == "OPEN"

        resp = accept_lines(env["package"]["id"], env["student"]["id"],
                            [(by_code["PELL"]["id"], 739500),
                             (by_code["INST_GRANT"]["id"], 500000)])
        validate_error(resp, ApiErrorId.ERR_OVERAWARD_UNRESOLVED)
        assert get_package(env["package"]["id"])["status"] == "NOTIFIED"


class TestAidYearClose:
    def test_close_rejected_until_latest_run_balanced(self, api):
        """PRD §3.9: "Closing the year is the last act: the director may move the aid year from `RECONCILING` to `CLOSED` only when its latest reconciliation run — the one with the highest `run_seq` — is `BALANCED`."
        PRD §2.7 (rung 5): "the target entity's state machine permits the requested transition from its current state — otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/guarded_transition_close_requires_balanced_run
        """
        env = setup_reconciling_year(federal_reported_cents=1000)
        # No disbursements posted: internal 0, variance 1_000 != 0.
        assert env["run"]["status"] == "VARIANCE_FOUND"

        resp = api.close_aid_year(env["aid_year"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        aid_year = get_success_data(api.get_aid_year(env["aid_year"]["id"],
                                                     DIRECTOR))
        assert aid_year["status"] == "RECONCILING"

    def test_close_cascades_funds_to_closed(self, api):
        """PRD §3.9: "The close cascades every FundType under the aid year, whether `ACTIVE` or `EXHAUSTED`, to `CLOSED`, and increments the aid year's `version`."
        PRD §3.9: "A variance of exactly zero auto-transitions the run to `BALANCED`; any non-zero variance routes it to `VARIANCE_FOUND`."

        Design: Corner/state_machines/side_effect_execution_fund_close_cascade
        """
        env = setup_reconciling_year(federal_reported_cents=0)
        # Federal 0 == internal 0 -> BALANCED.
        assert env["run"]["status"] == "BALANCED"

        closed = validate_success(api.close_aid_year(env["aid_year"]["id"],
                                                     DIRECTOR))
        assert closed["status"] == "CLOSED"
        fund = get_success_data(api.get_fund_type(env["funds"]["PELL"]["id"],
                                                  DIRECTOR))
        assert fund["status"] == "CLOSED"


class TestReconciliationVariance:
    def test_variance_computation_and_net_zero_adjustments(self, api):
        """PRD §3.9: "Comparing then snapshots `internal_posted_cents` — the sum of `disbursed_cents` over every disbursement in `POSTED` status whose award line's package belongs to this aid year, taken at compare time — and computes `variance_cents` as `federal_reported_cents` minus `internal_posted_cents`. A variance of exactly zero auto-transitions the run to `BALANCED`; any non-zero variance routes it to `VARIANCE_FOUND`."
        PRD §2.7 (rung 18): "the sum of `adjust_cents` over all of a run's adjustment rows plus `internal_posted_cents` must equal `federal_reported_cents` — otherwise `ERR_VARIANCE_NOT_ZEROED` (422)."

        Design: Corner/calculations/reconciliation_variance_and_adjustment_constants
        """
        env = setup_reconciliation_with_posted(posted_cents=100000,
                                               federal_reported_cents=99800)
        run = env["run"]
        assert run["internal_posted_cents"] == 100000
        # 99_800 - 100_000 = -200.
        assert run["variance_cents"] == -200
        assert run["status"] == "VARIANCE_FOUND"

        line_id = env["line"]["id"]
        # -100 would leave a -100 residual: rejected, and the run stays put.
        resp = api.create_reconciliation_adjustment(
            run["id"],
            {"award_line_id": line_id, "adjust_cents": -100,
             "reason_code": "DATA_ENTRY_ERROR"},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_VARIANCE_NOT_ZEROED)
        current = get_success_data(api.get_reconciliation_run(run["id"],
                                                              DIRECTOR))
        assert current["status"] == "VARIANCE_FOUND"

        # -200 exactly zeroes the variance: 100_000 + (-200) == 99_800.
        created = validate_success(api.create_reconciliation_adjustment(
            run["id"],
            {"award_line_id": line_id, "adjust_cents": -200,
             "reason_code": "FEDERAL_UNDERREPORT"},
            DIRECTOR), 201)
        assert created["adjust_cents"] == -200
        adjusted = get_success_data(api.get_reconciliation_run(run["id"],
                                                               DIRECTOR))
        assert adjusted["status"] == "ADJUSTED"
