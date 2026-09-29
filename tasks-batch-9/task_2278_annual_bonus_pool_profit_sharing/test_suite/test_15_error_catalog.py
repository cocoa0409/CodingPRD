"""Catalogued refusals: the header gate, the fixed pool and the two governance ceilings."""

from test_helpers import (
    CC_ADJUDICATOR,
    PA,
    PLAN_ADMIN_USER,
    ApiErrorId,
    BonusPlanScenario,
    adjustment_decision_payload,
    assert_pct,
    bonus_plan_payload,
    build_allocated_scenario,
    build_funded_scenario,
    build_user_headers,
    make_committee_headers,
    propose_allocation_payload,
    retract_allocation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

_NO_ROLE_HEADERS = {"X-User-ID": PLAN_ADMIN_USER, "Content-Type": "application/json"}
_UNKNOWN_ROLE_HEADERS = build_user_headers("pc_1", "PayrollClerk")


class TestHeaderGate:
    def test_a_missing_role_and_an_undeclared_role_are_both_unauthenticated(self, api):
        """PRD §2.1: "If either header is absent or empty, or if `X-User-Role` names
        anything other than one of the six roles below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)." And PRD §2.10: "1. **Headers.** Both headers
        present and non-empty, and `X-User-Role` naming one of the six roles — otherwise
        `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/auth_headers_missing_or_unknown_role_rejected
        """
        scenario = BonusPlanScenario()
        scenario.add_unit("K1", name="Unit K1")
        scenario.create_plan(plan_name="FY26 Auth Probe Plan")

        # Both payloads would create a perfectly legal plan with correct headers.
        headerless = api.create_bonus_plan(
            bonus_plan_payload(plan_name="FY26 Headerless Plan"), _NO_ROLE_HEADERS
        )
        error = validate_error(
            headerless, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value

        unknown_role = api.create_bonus_plan(
            bonus_plan_payload(plan_name="FY26 Unknown Role Plan"),
            _UNKNOWN_ROLE_HEADERS,
        )
        error = validate_error(
            unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value

        rows, meta = validate_paginated(api.list_bonus_plans(PA))
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert rows[0]["plan_name"] == "FY26 Auth Probe Plan"


class TestFixedPoolCeiling:
    def test_a_within_band_proposal_is_still_refused_by_the_pool(self, api):
        """PRD §3.5: "The **pool money check** is the last gate to run." And PRD §3.5: "The
        pool's `allocated_cents`, evaluated after this award's previous proposed amount has
        been removed and the new one added, must not exceed the pool's frozen
        `funded_cents`; if it would, the request is refused with `ERR_POOL_FUNDS_EXCEEDED`."
        And PRD §3.5: "For a non-zero amount, that ratio must be at least the
        `guideline_min_ratio` and at most the `guideline_max_ratio` of the job-level target
        row for the award's level; a ratio outside the band is `ERR_GUIDELINE_RATIO_BREACH`."

        Design: Corner/errors/pool_funds_exceeded_by_a_within_guideline_proposal_rejected
        """
        scenario = build_funded_scenario(
            units=("K2",), plan_overrides={"plan_name": "FY26 Funds Exceeded Plan"}
        )
        assert scenario.refresh_pool("K2")["funded_cents"] == 4000000

        # 5,000,000 over a 4,000,000 target is a ratio of 1.2500, inside [0.25, 2.00].
        response = api.propose_allocation(
            scenario.award_id("ada"),
            propose_allocation_payload(
                5000000,
                scenario.pool_version("K2"),
                allocation_rationale="stretch award well above the pool",
            ),
            scenario.manager_headers("K2"),
        )
        error = validate_error(
            response, ApiErrorId.ERR_POOL_FUNDS_EXCEEDED.value, expected_status=422
        )
        assert error["error_id"] != ApiErrorId.ERR_GUIDELINE_RATIO_BREACH.value

        award = scenario.refresh_award("ada")
        assert award["allocation_status"] == "UNALLOCATED"
        assert award["proposed_allocation_cents"] == 0
        assert award["final_award_cents"] == 0

        pool = scenario.refresh_pool("K2")
        assert pool["allocated_cents"] == 0
        assert pool["available_cents"] == 4000000
        assert pool["calibration_status"] == "FUNDED"
        assert scenario.refresh_plan()["funded_pool_cents"] == 4000000


class TestRetractionAfterCalibrationSubmission:
    def test_the_pool_has_left_the_money_moving_states(self, api):
        """PRD §3.5: "It requires the acting manager to own the award's business unit, the
        plan to be in `ALLOCATION_OPEN` (`ERR_PLAN_NOT_IN_ALLOCATION`), the pool to be in
        `FUNDED` or `ALLOCATING` (`ERR_POOL_NOT_ALLOCATING`), the award to be in `PROPOSED`
        (`ERR_AWARD_STATE_INVALID`), and a matching `expected_pool_version`." And PRD §3.7:
        "When a manager considers their unit's distribution finished, they submit it for
        calibration, moving the pool's `calibration_status` from `ALLOCATING` to
        `CALIBRATION_SUBMITTED`; the submission may carry a revised `scorecard_narrative`."

        Design: Corner/errors/retraction_after_calibration_submission_rejected
        """
        scenario = build_allocated_scenario(
            units=("K3",),
            plan_overrides={"plan_name": "FY26 Retraction Window Plan"},
        )
        submitted = scenario.submit_calibration("K3")
        assert submitted["calibration_status"] == "CALIBRATION_SUBMITTED"

        response = api.retract_allocation(
            scenario.award_id("ada"),
            retract_allocation_payload(
                scenario.pool_version("K3"),
                retraction_reason="manager wants to redo the split",
            ),
            scenario.manager_headers("K3"),
        )
        error = validate_error(
            response, ApiErrorId.ERR_POOL_NOT_ALLOCATING.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_AWARD_STATE_INVALID.value
        assert error["error_id"] != ApiErrorId.ERR_PLAN_NOT_IN_ALLOCATION.value

        award = scenario.refresh_award("ada")
        assert award["allocation_status"] == "PROPOSED"
        assert award["proposed_allocation_cents"] == 4000000
        assert award["retraction_count"] == 0

        pool = scenario.refresh_pool("K3")
        assert pool["calibration_status"] == "CALIBRATION_SUBMITTED"
        assert pool["allocated_cents"] == 4000000
        assert pool["available_cents"] == 0
        assert_pct(pool["utilization_pct"], 100.00)
        assert pool["distribution_status"] == "WITHIN_GUIDELINES"
        assert scenario.refresh_plan()["status"] == "ALLOCATION_OPEN"


class TestTheTwoGovernanceCeilings:
    def test_the_per_award_cap_outranks_the_plan_wide_budget(self, api):
        """PRD §3.6: "The absolute value of `adjustment_cents` must not exceed the frozen
        `per_award_cap_cents` — exactly equal to the cap is allowed — or the decision is
        refused with `ERR_ADJUSTMENT_EXCEEDS_PER_AWARD_LIMIT`." And PRD §3.6: "The plan's
        `discretionary_used_cents` plus the absolute value of `adjustment_cents` must not
        exceed `discretionary_budget_cents`, or the decision is refused with
        `ERR_DISCRETIONARY_BUDGET_EXCEEDED`." And PRD §2.10: "**Fiscal checks**, last, in
        this order: the frozen per-award adjustment cap
        (`ERR_ADJUSTMENT_EXCEEDS_PER_AWARD_LIMIT`), the pool's remaining money
        (`ERR_POOL_FUNDS_EXCEEDED`) and the plan's discretionary budget
        (`ERR_DISCRETIONARY_BUDGET_EXCEEDED`)."

        Design: Corner/errors/adjustment_cap_and_budget_limits_rejected
        """
        scenario = build_allocated_scenario(
            units=("K4",),
            plan_overrides={"plan_name": "FY26 Adjustment Limits Plan"},
        )
        assert scenario.refresh_plan()["discretionary_budget_cents"] == 400000

        over_cap = scenario.file_adjustment(
            "ada",
            1200000,
            justification="retention of a critical engineer",
            documentation_ref="MEMO-K4-01",
        )
        over_budget = scenario.file_adjustment(
            "ada",
            500000,
            justification="market correction for the same engineer",
            documentation_ref="MEMO-K4-02",
        )
        assert over_cap["per_award_cap_cents"] == 1000000
        assert over_budget["per_award_cap_cents"] == 1000000

        # 1,200,000 breaks the 1,000,000 cap and the 400,000 budget; the cap answers.
        response = api.decide_discretionary_adjustment(
            over_cap["id"],
            adjustment_decision_payload(
                "APPROVE", decision_note="committee approves the retention case"
            ),
            make_committee_headers(CC_ADJUDICATOR),
        )
        error = validate_error(
            response,
            ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_PER_AWARD_LIMIT.value,
            expected_status=422,
        )
        assert error["error_id"] != ApiErrorId.ERR_DISCRETIONARY_BUDGET_EXCEEDED.value

        response = api.decide_discretionary_adjustment(
            over_budget["id"],
            adjustment_decision_payload(
                "APPROVE", decision_note="committee approves the market case"
            ),
            make_committee_headers(CC_ADJUDICATOR),
        )
        validate_error(
            response,
            ApiErrorId.ERR_DISCRETIONARY_BUDGET_EXCEEDED.value,
            expected_status=422,
        )

        for adjustment_id in (over_cap["id"], over_budget["id"]):
            stored = validate_success(
                api.get_discretionary_adjustment(adjustment_id, PA)
            )
            assert stored["status"] == "PENDING_APPROVAL"
            assert stored["per_award_cap_cents"] == 1000000

        plan = scenario.refresh_plan()
        assert plan["discretionary_budget_cents"] == 400000
        assert plan["discretionary_used_cents"] == 0

        award = scenario.refresh_award("ada")
        assert award["adjustment_total_cents"] == 0
        assert award["final_award_cents"] == 4000000

        pool = scenario.refresh_pool("K4")
        assert pool["allocated_cents"] == 4000000
        assert pool["distribution_status"] == "WITHIN_GUIDELINES"
