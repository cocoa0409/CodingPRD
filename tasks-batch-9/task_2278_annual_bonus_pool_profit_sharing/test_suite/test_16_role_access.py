"""Who may act: exclusive operations, entity-backed ownership, duties splits, shared writes."""

from test_helpers import (
    CC_CERTIFIER,
    CC_LOCKER,
    FC,
    HR,
    PA,
    ApiErrorId,
    assert_ratio,
    build_allocated_scenario,
    build_calibration_review_scenario,
    build_funded_scenario,
    build_locked_scenario,
    build_targets_set_scenario,
    clock_payload,
    decision_payload,
    discretionary_adjustment_payload,
    dispute_payload,
    make_committee_headers,
    propose_allocation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

_TWO_L5 = (
    {
        "label": "ada",
        "employee_code": "E981",
        "full_name": "Ada Long",
        "job_level": "L5",
        "base_salary_cents": 20000000,
        "hire_date": "2025-03-01",
    },
    {
        "label": "bea",
        "employee_code": "E982",
        "full_name": "Bea Short",
        "job_level": "L5",
        "base_salary_cents": 20000000,
        "hire_date": "2025-03-01",
    },
)


class TestCommitteeExclusiveOperations:
    def test_finance_cannot_certify_and_the_plan_admin_cannot_mint_the_money(self, api):
        """PRD §2.1: "If the headers are well formed but the named role is not among the
        roles authorized for the endpoint in §4, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)." And PRD §2.10: "2. **Role authorization.** The acting
        role appears in the endpoint's authorized roles — otherwise `ERR_UNAUTHORIZED`." And
        PRD §3.4:
        "Certification finally records the acting `X-User-ID` in `certified_by_user_id`."

        Design: Corner/rbac/committee_only_operations_attempted_by_other_roles_rejected
        """
        scenario = build_targets_set_scenario(
            units=("K5",), plan_overrides={"plan_name": "FY26 Role Boundary Plan"}
        )
        scenario.submit_for_certification()

        finance_certifies = api.decide_plan_certification(
            scenario.plan_id,
            decision_payload("CERTIFY", decision_note="finance tries to certify"),
            FC,
        )
        validate_error(
            finance_certifies, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403
        )

        # An authorized actor would earn a state error here; the role check comes first.
        admin_funds = api.fund_pool(scenario.plan_id, PA)
        error = validate_error(
            admin_funds, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403
        )
        assert error["error_id"] != ApiErrorId.ERR_PLAN_STATE_INVALID.value

        plan = scenario.refresh_plan()
        assert plan["status"] == "PENDING_CERTIFICATION"
        assert plan["certified_by_user_id"] is None

        certified = validate_success(
            api.decide_plan_certification(
                scenario.plan_id,
                decision_payload("CERTIFY", decision_note="committee certifies"),
                make_committee_headers(CC_CERTIFIER),
            )
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == CC_CERTIFIER
        assert certified["funded_pool_cents"] == 0
        assert_ratio(certified["funding_multiplier"], 1.0000)


class TestManagerOwnership:
    def test_a_neighbouring_manager_cannot_spend_or_close_this_pool(self, api):
        """PRD §2.1: "Concretely, scorecard and calibration submissions require `X-User-ID`
        to equal the pool's `business_unit_id`, and allocation writes require `X-User-ID` to
        equal the award's `business_unit_id`." And PRD §2.1: "A mismatch is rejected with
        `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/manager_of_another_unit_cannot_touch_this_pool_rejected
        """
        scenario = build_funded_scenario(
            units=("K6", "K7"),
            pooled_units=("K6",),
            plan_overrides={"plan_name": "FY26 Manager Isolation Plan"},
        )
        pool_version = scenario.pool_version("K6")
        intruder = scenario.manager_headers("K7")

        outsider_allocates = api.propose_allocation(
            scenario.award_id("ada"),
            propose_allocation_payload(
                4000000,
                pool_version,
                allocation_rationale="outsider tries to spend this pool",
            ),
            intruder,
        )
        error = validate_error(
            outsider_allocates,
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP.value,
            expected_status=403,
        )
        # BusinessUnitManager is an authorized role for this endpoint.
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value

        outsider_closes = api.submit_calibration(scenario.pool_id("K6"), intruder)
        validate_error(
            outsider_closes,
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP.value,
            expected_status=403,
        )

        assert scenario.refresh_award("ada")["allocation_status"] == "UNALLOCATED"
        pool = scenario.refresh_pool("K6")
        assert pool["allocated_cents"] == 0
        assert pool["calibration_status"] == "FUNDED"

        owner_allocates = validate_success(
            api.propose_allocation(
                scenario.award_id("ada"),
                propose_allocation_payload(
                    4000000,
                    pool_version,
                    allocation_rationale="owning manager allocates at target",
                ),
                scenario.manager_headers("K6"),
            )
        )
        assert owner_allocates["allocation_status"] == "PROPOSED"
        assert owner_allocates["proposed_allocation_cents"] == 4000000

        pool = scenario.refresh_pool("K6")
        assert pool["calibration_status"] == "ALLOCATING"
        assert pool["available_cents"] == 0


class TestEmployeeOwnership:
    def test_an_employee_may_only_contest_their_own_number(self, api):
        """PRD §2.1: "Filing a dispute requires `X-User-ID` to equal both the disputed
        award's `participant_id` and the `participant_id` supplied in the request body, and
        any other combination is rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`." And PRD
        §3.10: "The filing `participant_id` must match both the award's `participant_id` and
        the acting `X-User-ID` (`ERR_FORBIDDEN_RESOURCE_OWNERSHIP`), and the dispute, the
        award and the plan must all belong to the same plan (`ERR_PLAN_SCOPE_MISMATCH`)." And
        PRD §3.10: "A new dispute is `OPEN`."

        Design: Corner/rbac/employee_cannot_dispute_another_participants_award_rejected
        """
        scenario = build_locked_scenario(
            units=("K8",),
            plan_overrides={"plan_name": "FY26 Dispute Ownership Plan"},
            participants=_TWO_L5,
        )
        assert scenario.refresh_plan()["locked_total_cents"] == 8000000
        bea = scenario.employee_headers("bea")

        # A coherent filing on a LOCKED plan, wrong only in who is acting.
        foreign = api.create_dispute(
            dispute_payload(
                scenario.plan_id,
                scenario.award_id("ada"),
                scenario.participant_id("ada"),
                dispute_reason="Bea contests Ada's award",
                claimed_amount_cents=5000000,
            ),
            bea,
        )
        error = validate_error(
            foreign,
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP.value,
            expected_status=403,
        )
        assert error["error_id"] != ApiErrorId.ERR_DISPUTE_NOT_ALLOWED_YET.value
        assert error["error_id"] != ApiErrorId.ERR_PLAN_SCOPE_MISMATCH.value

        own = validate_success(
            api.create_dispute(
                dispute_payload(
                    scenario.plan_id,
                    scenario.award_id("bea"),
                    scenario.participant_id("bea"),
                    dispute_reason="Bea contests her own award",
                    claimed_amount_cents=5000000,
                ),
                bea,
            ),
            expected_status=201,
        )
        assert own["status"] == "OPEN"

        rows, meta = validate_paginated(
            api.list_disputes(PA, params={"plan_id": scenario.plan_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["award_id"] == scenario.award_id("bea")
        assert rows[0]["participant_id"] == scenario.participant_id("bea")

        assert scenario.refresh_award("ada")["payment_status"] == "PENDING"
        assert scenario.refresh_award("bea")["payment_status"] == "PENDING"


class TestSegregationOfDuties:
    def test_the_certifier_cannot_also_freeze_the_money(self, api):
        """PRD §3.7: "Three conditions guard it, in ladder order: the acting `X-User-ID`
        must differ from the plan's `certified_by_user_id`, so that the member who certified
        the performance figures is not the member who freezes the money
        (`ERR_SEGREGATION_OF_DUTIES`); the plan's `governance_posture` must be `COMPLIANT`,
        which means no pool may be left over-allocated or under-utilized
        (`ERR_GOVERNANCE_POSTURE_BREACHED`); and every pool of the plan must be in
        `CALIBRATED`, not merely submitted (`ERR_POOL_CALIBRATION_PENDING`)." And PRD §3.7:
        "The plan's `locked_total_cents` is the sum of `final_award_cents` over the awards
        now in `LOCKED`, and `locked_by_user_id` records the acting member."

        Design: Corner/rbac/certifying_committee_member_cannot_lock_the_plan_rejected
        """
        scenario = build_calibration_review_scenario(
            units=("K9",),
            plan_overrides={"plan_name": "FY26 Duties Split Plan"},
            certifier=CC_CERTIFIER,
        )
        assert scenario.refresh_plan()["governance_posture"] == "COMPLIANT"

        same_member = api.lock_plan(
            scenario.plan_id, make_committee_headers(CC_CERTIFIER)
        )
        error = validate_error(
            same_member,
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            expected_status=403,
        )
        assert error["error_id"] != ApiErrorId.ERR_GOVERNANCE_POSTURE_BREACHED.value
        assert error["error_id"] != ApiErrorId.ERR_POOL_CALIBRATION_PENDING.value

        plan = scenario.refresh_plan()
        assert plan["status"] == "CALIBRATION_REVIEW"
        assert plan["locked_total_cents"] == 0
        assert plan["locked_by_user_id"] is None

        locked = validate_success(
            api.lock_plan(scenario.plan_id, make_committee_headers(CC_LOCKER))
        )
        assert locked["status"] == "LOCKED"
        assert locked["locked_by_user_id"] == CC_LOCKER
        assert locked["certified_by_user_id"] == CC_CERTIFIER
        assert locked["locked_total_cents"] == 4000000
        assert locked["governance_posture"] == "COMPLIANT"

        assert scenario.refresh_award("ada")["allocation_status"] == "LOCKED"
        assert scenario.refresh_pool("K9")["calibration_status"] == "LOCKED"


class TestSharedOperations:
    def test_both_declared_roles_may_file_an_adjustment_and_drive_the_clock(self, api):
        """PRD §3.6: "For these, a `PlanAdmin` or an `HRBusinessPartner` files a
        **discretionary adjustment** against one award, drawn not on the unit's pool but on
        the plan-level discretionary budget reserved at funding time." And PRD §3.6: "The new
        row stores `submitted_by_user_id` as the acting `X-User-ID`, sets `status` to
        `PENDING_APPROVAL`, leaves `decided_by_user_id` and `decision_note` null, and moves
        no money at all." And PRD §2.4: "A test-driving capability, restricted to `PlanAdmin`
        and `FinanceController`, sets the clock to a supplied `current_utc` instant, after
        which every subsequent request reads the new value."

        Design: Corner/rbac/shared_operations_accept_both_declared_roles
        """
        scenario = build_allocated_scenario(
            units=("L1",), plan_overrides={"plan_name": "FY26 Shared Operations Plan"}
        )

        by_admin = validate_success(
            api.create_discretionary_adjustment(
                discretionary_adjustment_payload(
                    scenario.plan_id,
                    scenario.award_id("ada"),
                    50000,
                    scenario.plan_version(),
                    justification="plan admin files a small uplift",
                ),
                PA,
            ),
            expected_status=201,
        )
        by_hr = validate_success(
            api.create_discretionary_adjustment(
                discretionary_adjustment_payload(
                    scenario.plan_id,
                    scenario.award_id("ada"),
                    50000,
                    scenario.plan_version(),
                    justification="hrbp files a second small uplift",
                ),
                HR,
            ),
            expected_status=201,
        )
        for adjustment in (by_admin, by_hr):
            assert adjustment["status"] == "PENDING_APPROVAL"
            assert adjustment["per_award_cap_cents"] == 1000000
            assert adjustment["decided_by_user_id"] is None

        validate_success(api.set_clock(clock_payload("2026-09-30T00:00:00Z"), FC))
        validate_success(api.set_clock(clock_payload("2026-10-01T00:00:00Z"), PA))

        _, meta = validate_paginated(
            api.list_discretionary_adjustments(
                HR, params={"plan_id": scenario.plan_id}
            )
        )
        assert meta["total_count"] == 2

        assert scenario.refresh_plan()["discretionary_used_cents"] == 0
        award = scenario.refresh_award("ada")
        assert award["adjustment_total_cents"] == 0
        assert award["final_award_cents"] == 4000000
