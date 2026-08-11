"""Coming back: returns, the one shared condition rubric, cleaning and retirement."""

from test_helpers import (
    ADMIN,
    BILLING,
    GRADER,
    LOGISTICS,
    PLANNER,
    VENDOR,
    WAREHOUSE,
    ApiErrorId,
    assert_condition_assessment,
    assert_processing_job,
    allocate_unit,
    api_client,
    create_box,
    create_open_cycle,
    create_return_shipment,
    create_style,
    create_unit,
    confirm_grade,
    find_charge,
    find_processing_job,
    find_rental_assessment,
    get_assessment,
    get_box_item,
    get_cycle,
    get_job,
    get_style,
    get_submission,
    get_unit,
    grade_returned_unit,
    grade_trade_in_item,
    list_jobs,
    make_grader_headers,
    make_member_headers,
    make_planner_headers,
    mint_label,
    open_trade_in_assessment,
    pack_box,
    set_clock,
    setup_basic_delivered_scenario,
    setup_plan_and_member,
    setup_received_trade_in,
    setup_returned_items,
    ship_box,
    start_item_return,
    submit_grade,
    depart_shipment,
    receive_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestGradingBench:
    def test_an_assessment_with_no_target_at_all_is_refused(self, api):
        """PRD §3.6: "A `GradingTechnician` opens a grading record by naming a
        `pipeline` of `RENTAL` or `TRADE_IN` together with exactly one target:
        `unit_id` for a rental unit, or `trade_in_item_id` for a trade-in
        garment. Supplying both, supplying neither, or supplying the one that
        contradicts the declared pipeline is refused with
        `ERR_ASSESSMENT_TARGET_MISMATCH` (HTTP 422)"

        Design: Corner/entities/corner_condition_assessment_with_both_targets_is_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_condition_assessment({"pipeline": "RENTAL"},
                                               make_grader_headers("grader-90"))
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_TARGET_MISMATCH.value, 422)

    def test_the_confirmer_must_differ_from_the_most_recent_grader(self, api):
        """PRD §2.1: "The operator confirming a `ConditionAssessment` must
        present an `X-User-ID` different from the `graded_by_user_id` already
        stored on that assessment; presenting the same identifier is refused
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §2.6 rung 5: "On grade confirmation, the acting `X-User-ID` differs
        from the assessment's `graded_by_user_id`. Otherwise
        `ERR_SEGREGATION_OF_DUTIES` (403). Applies to
        `POST /kidswear/condition-assessments/{assessment_id}/confirm` only."

        Design: Corner/errors/corner_err_grader_cannot_confirm_their_own_assessment
        """
        _, member = setup_plan_and_member(member={"child_size_code": "6"})
        intake = setup_received_trade_in(member, 3, "STANDARD", "6")
        first_item = intake["items"][0]
        assessment = open_trade_in_assessment(first_item["id"], "shared-op-1")
        submit_grade(assessment["id"], "B", grader_id="shared-op-1")

        resp = api.confirm_assessment(assessment["id"], make_planner_headers("shared-op-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        after = get_assessment(assessment["id"])
        assert after["status"] == "SUBMITTED"
        assert after["confirmed_by_user_id"] is None
        assert validate_success(
            api.get_trade_in_item(first_item["id"], ADMIN)
        )["grading_status"] == "PENDING"

    def test_a_grading_technician_may_not_confirm_a_grade_at_all(self, api):
        """PRD §2.1: "If the acting role is a declared role but is not one of the
        roles listed for the endpoint in §4, the request is refused with
        `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §3.6: "Confirmation is a `MerchandisePlanner` action, permitted from
        `SUBMITTED` and equally from `DISPUTED` — confirming a disputed record
        upholds the dispute at whatever grade currently stands, and the side
        effects of the two edges are identical."

        Design: Corner/rbac/corner_rbac_grading_technician_cannot_confirm_a_grade
        """
        _, member = setup_plan_and_member(member={"child_size_code": "6"})
        intake = setup_received_trade_in(member, 3, "STANDARD", "6")
        assessment = open_trade_in_assessment(intake["items"][0]["id"], "grader-r3")
        submit_grade(assessment["id"], "B", grader_id="grader-r3")

        resp = api.confirm_assessment(assessment["id"], make_grader_headers("grader-other"))
        error = validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value, 403)
        assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
        assert get_assessment(assessment["id"])["status"] == "SUBMITTED"

    def test_the_dispute_and_regrade_loop_terminates_at_two_attempts(self, api):
        """PRD §3.6: "This is a genuine loop and it is capped: both disputing and
        regrading require `regrade_count` to be strictly below
        `REGRADE_MAX_ATTEMPTS`, which is 2, and an attempt at or above the cap
        is refused with `ERR_RETRY_CAP_REACHED`."
        PRD §3.6: "A disputed record may be **regraded** by a technician with a
        replacement `grade`, moving it `DISPUTED → SUBMITTED`, replacing the
        stored grade, incrementing `regrade_count` by 1, and rewriting
        `graded_by_user_id` with the regrading technician's identifier."
        PRD §3.9: "The first grade submitted against any garment in the batch
        moves the submission `RECEIVED → GRADING`."

        Design: Corner/state_machines/corner_sm_assessment_regrade_loop_is_capped_and_rejected_on_third_dispute
        """
        _, member = setup_plan_and_member(member={"child_size_code": "6"})
        intake = setup_received_trade_in(member, 3, "STANDARD", "6")
        assessment = open_trade_in_assessment(intake["items"][0]["id"], "grader-08")
        submit_grade(assessment["id"], "C", grader_id="grader-08")

        member_headers = make_member_headers(member["id"])
        validate_success(api.dispute_assessment(assessment["id"],
                                                {"dispute_reason": "member says grade B"},
                                                member_headers))
        validate_success(api.regrade_assessment(assessment["id"], {"grade": "B"},
                                                make_grader_headers("grader-08")))
        validate_success(api.dispute_assessment(assessment["id"],
                                                {"dispute_reason": "member says grade A"},
                                                member_headers))
        validate_success(api.regrade_assessment(assessment["id"], {"grade": "A"},
                                                make_grader_headers("grader-08")))

        resp = api.dispute_assessment(assessment["id"],
                                      {"dispute_reason": "third attempt"}, member_headers)
        validate_error(resp, ApiErrorId.ERR_RETRY_CAP_REACHED.value, 409)

        after = get_assessment(assessment["id"])
        assert_condition_assessment(after)
        assert after["regrade_count"] == 2
        assert after["status"] == "SUBMITTED"
        assert after["grade"] == "A"
        assert get_submission(intake["submission"]["id"])["status"] == "GRADING"


class TestCleaningRouting:
    def test_a_processing_job_is_discoverable_only_from_its_assessment(self, api):
        """PRD §3.6: "The job is created `QUEUED` with `attempt_count` and
        `cost_cents` at 0, `post_repair_grade` null, and its `assessment_id` and
        `unit_id` copied from the confirmed record."
        PRD §3.6: "The confirmed grade selects a `route` through
        `GRADE_ROUTE_MAP`: an `A` or a `B` routes to `STANDARD_LAUNDER`, a `C`
        routes to `STAIN_TREATMENT`, a `D` routes to `REPAIR`, and a `RETIRE`
        routes to `RETIRE`."

        Design: Corner/endpoints/corner_ep_processing_jobs_are_discoverable_from_their_assessment
        """
        scenario = setup_basic_delivered_scenario(
            member={"protection_enrolled": False},
            style={"sku": "SKU-E5-5", "name": "Job Tee", "size_code": "5"},
        )
        item = scenario["items"][0]
        unit = scenario["units"][0]
        setup_returned_items(scenario["member"], [item["id"]])
        assessment = find_rental_assessment(unit["id"])
        submit_grade(assessment["id"], "A")
        confirm_grade(assessment["id"])

        rows, meta = validate_paginated(api.list_processing_jobs(
            VENDOR, {"assessment_id": assessment["id"], "limit": 100, "offset": 0}))
        assert meta["total_count"] == 1
        job = rows[0]
        assert_processing_job(job)
        assert job["assessment_id"] == assessment["id"]
        assert job["unit_id"] == unit["id"]
        assert job["route"] == "STANDARD_LAUNDER"
        assert job["status"] == "QUEUED"
        assert job["cost_cents"] == 0

    def test_the_rework_loop_adds_half_the_route_base_cost(self, api):
        """PRD §3.6: "A `CleaningVendor` starts a job, moving it `QUEUED →
        IN_PROGRESS`, which requires the unit to be in `PROCESSING` and
        increments `attempt_count` by 1, setting `cost_cents` to the route's
        base cost."
        PRD §3.6: "Each rework increments `attempt_count` again and **adds**
        `REWORK_COST_MULTIPLIER` — 0.50, that is half — of the route's base cost
        to `cost_cents`, rounded half up."
        PRD §3.6: "`CLEAN_COST_STANDARD_LAUNDER_CENTS` is 320,
        `CLEAN_COST_STAIN_TREATMENT_CENTS` is 900, `CLEAN_COST_REPAIR_CENTS` is
        2400, and `CLEAN_COST_RETIRE_CENTS` is 0"
        PRD §3.6: "`DAMAGE_FEE_BY_GRADE_CENTS` gives 0 for `A`, 0 for `B`, 1500
        for `C` and 4000 for `D`, while a `RETIRE` grade instead charges the
        style's `retail_price_cents` multiplied by 0.55 and rounded half up."

        Design: Corner/state_machines/corner_sm_processing_rework_loop_accrues_half_the_base_cost
        """
        scenario = setup_basic_delivered_scenario(
            member={"protection_enrolled": False},
            style={"sku": "SKU-SM9-5", "name": "SM Nine Tee", "size_code": "5"},
        )
        item, unit = scenario["items"][0], scenario["units"][0]
        setup_returned_items(scenario["member"], [item["id"]])
        grade_returned_unit(unit["id"], "C", ["STAIN"])
        job = find_processing_job(unit["id"])
        validate_success(api.start_processing_job(job["id"], VENDOR))
        validate_success(api.fail_processing_job(job["id"], VENDOR))

        validate_success(api.start_processing_job(job["id"], VENDOR))

        after = get_job(job["id"])
        assert after["route"] == "STAIN_TREATMENT"
        assert after["status"] == "IN_PROGRESS"
        assert after["attempt_count"] == 2
        assert after["cost_cents"] == 1350
        assert get_unit(unit["id"])["state"] == "PROCESSING"
        after_item = get_box_item(item["id"])
        assert after_item["damage_fee_cents"] == 1500
        assert after_item["settlement_status"] == "SETTLED"

    def test_a_retire_routed_job_can_never_be_started(self, api):
        """PRD §3.6: "A `QUEUED` job whose `route` is `RETIRE` may be scrapped,
        retiring its unit with `retired_reason` `GRADE_RETIRE`; that is the
        **only** path a `RETIRE`-routed job may ever take, because such a job
        can never be started and never be passed."
        PRD §3.6: "`PASSED` and `SCRAPPED` are the job's terminal states, and any
        job or assessment transition attempted from an undeclared from-state is
        refused with `ERR_ASSESSMENT_INVALID_STATE`."

        Design: Corner/state_machines/corner_sm_retire_route_job_cannot_be_started
        """
        scenario = setup_basic_delivered_scenario(
            member={"protection_enrolled": False},
            style={"sku": "SKU-SM16-5", "name": "SM Sixteen Tee", "size_code": "5",
                   "retail_price_cents": 2000},
        )
        item, unit = scenario["items"][0], scenario["units"][0]
        setup_returned_items(scenario["member"], [item["id"]])
        grade_returned_unit(unit["id"], "RETIRE", ["TEAR"])
        job = find_processing_job(unit["id"])

        resp = api.start_processing_job(job["id"], VENDOR)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE.value, 409)

        after = get_job(job["id"])
        assert after["route"] == "RETIRE"
        assert after["status"] == "QUEUED"
        assert after["attempt_count"] == 0
        assert get_box_item(item["id"])["damage_fee_cents"] == 1100
        assert get_unit(unit["id"])["state"] == "PROCESSING"

    def test_a_cleaning_vendor_may_not_scrap_a_failed_job(self, api):
        """PRD §2.1: "If the acting role is a declared role but is not one of the
        roles listed for the endpoint in §4, the request is refused with
        `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §3.6: "Scrapping is the `MerchandisePlanner`'s counterpart and has
        two edges. A `FAILED` job may be scrapped, retiring its unit with
        `retired_reason` `REWORK_FAILED`."

        Design: Corner/rbac/corner_rbac_cleaning_vendor_cannot_scrap_a_job
        """
        scenario = setup_basic_delivered_scenario(
            member={"protection_enrolled": False},
            style={"sku": "SKU-R4-5", "name": "Scrap Tee", "size_code": "5"},
        )
        item, unit = scenario["items"][0], scenario["units"][0]
        setup_returned_items(scenario["member"], [item["id"]])
        grade_returned_unit(unit["id"], "C")
        job = find_processing_job(unit["id"])
        validate_success(api.start_processing_job(job["id"], VENDOR))
        validate_success(api.fail_processing_job(job["id"], VENDOR))

        resp = api.scrap_processing_job(job["id"], VENDOR)
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value, 403)

        assert get_job(job["id"])["status"] == "FAILED"
        assert get_unit(unit["id"])["state"] == "PROCESSING"

    def test_a_repair_claiming_three_ordinals_of_uplift_is_refused(self, api):
        """PRD §3.6: "Otherwise the job supplies a `post_repair_grade` of `A`,
        `B`, `C` or `D`, and the uplift — the assessment grade's ordinal minus
        the `post_repair_grade`'s ordinal — must be at most
        `REPAIR_UPLIFT_MAX_STEPS`, which is 2; an uplift beyond that, or a
        `post_repair_grade` supplied on a route that is not `REPAIR`, is refused
        with `ERR_REPAIR_UPLIFT_EXCEEDED` (HTTP 422)."
        PRD §3.6: "`GRADE_LADDER` runs `A`, `B`, `C`, `D`, `RETIRE`, and the
        ordinals under `GRADE_ORDINALS` are 0 for `A`, 1 for `B`, 2 for `C`, 3
        for `D` and 4 for `RETIRE`."
        PRD §3.6: "Passing a job moves it `IN_PROGRESS → PASSED` ... The unit's
        `current_grade` is then recomputed."  The refused pass therefore leaves
        the unit on the grade it was acquired with — PRD §3.3: "Every acquired
        unit begins with ... `current_grade` `A` when none is supplied".

        Design: Corner/calculations/corner_calc_repair_uplift_beyond_two_ordinals_is_rejected
        """
        scenario = setup_basic_delivered_scenario(
            member={"protection_enrolled": False},
            style={"sku": "SKU-K15-5", "name": "Repair Tee", "size_code": "5"},
        )
        item, unit = scenario["items"][0], scenario["units"][0]
        setup_returned_items(scenario["member"], [item["id"]])
        grade_returned_unit(unit["id"], "D", ["TEAR"])
        job = find_processing_job(unit["id"])
        validate_success(api.start_processing_job(job["id"], VENDOR))

        resp = api.pass_processing_job(job["id"], VENDOR, {"post_repair_grade": "A"})
        validate_error(resp, ApiErrorId.ERR_REPAIR_UPLIFT_EXCEEDED.value, 422)

        after = get_job(job["id"])
        assert after["route"] == "REPAIR"
        assert after["status"] == "IN_PROGRESS"
        assert after["cost_cents"] == 2400
        assert get_unit(unit["id"])["current_grade"] == "A"
        assert get_box_item(item["id"])["damage_fee_cents"] == 4000

    def test_a_unit_reaching_the_wear_cap_retires_instead_of_restocking(self, api):
        """PRD §3.6: "After the cost has accrued, retirement eligibility is
        re-evaluated: a unit is `retirement_eligible` when its
        `cycles_completed` has reached `UNIT_MAX_CYCLES`, 8, **or** its
        `cumulative_cleaning_cost_cents` has reached
        `UNIT_MAX_CLEANING_COST_CENTS`, 6000, **or** its `current_grade` is
        `RETIRE`."
        PRD §3.6: "A passed job on a unit that *is* eligible moves it
        `PROCESSING → RETIRED` and writes `retired_reason` by a fixed
        precedence: `CYCLE_CAP` when the wear count has reached 8; otherwise
        `COST_CAP` when the cleaning spend has reached 6000; otherwise
        `GRADE_RETIRE`."
        PRD §3.5: "A `RETURN` receipt advances `RETURNING` items to `RECEIVED`,
        moves their units `INBOUND → PROCESSING`, increments each unit's
        `cycles_completed` by 1, and opens a `DRAFT` condition assessment of
        `pipeline` `RENTAL` per unit."

        Design: Corner/calculations/corner_calc_unit_retires_when_the_cycle_counter_reaches_its_cap
        """
        scenario = setup_basic_delivered_scenario(
            member={"protection_enrolled": False},
            style={"sku": "SKU-K18-5", "name": "Retiring Tee", "size_code": "5"},
            unit={"acquired_at": "2025-05-01T00:00:00Z", "current_grade": "A",
                  "cycles_completed": 7},
        )
        item, unit = scenario["items"][0], scenario["units"][0]
        setup_returned_items(scenario["member"], [item["id"]])
        grade_returned_unit(unit["id"], "A")
        job = find_processing_job(unit["id"])
        validate_success(api.start_processing_job(job["id"], VENDOR))

        validate_success(api.pass_processing_job(job["id"], VENDOR))

        after = get_unit(unit["id"])
        assert after["cycles_completed"] == 8
        assert after["retirement_eligible"] is True
        assert after["state"] == "RETIRED"
        assert after["retired_reason"] == "CYCLE_CAP"
        assert after["cumulative_cleaning_cost_cents"] == 320
        assert get_job(job["id"])["status"] == "PASSED"
        assert get_style(scenario["style"]["id"])["units_ever_acquired"] == 1


class TestLateAccrual:
    def _return_four_days_late(self, late_fee_mode, sku):
        scenario = setup_basic_delivered_scenario(
            plan={"late_fee_mode": late_fee_mode},
            style={"sku": sku, "name": "Late Tee", "size_code": "5"},
        )
        set_clock("2026-06-09T00:00:00Z")
        ret = create_return_shipment(scenario["member"]["id"], item_count=1)
        start_item_return(scenario["member"]["id"], scenario["items"][0]["id"],
                          ret["shipment"]["id"])
        return scenario, ret

    def test_a_per_day_plan_accrues_one_hundred_and_fifty_cents_a_day(self, api):
        """PRD §3.2: "The number of late days is the whole number of days between
        `grace_ends_at` and the effective instant, counted only when that instant
        is strictly after `grace_ends_at`, with **any partial day rounded up to
        a whole day**; the effective instant is the return-start instant for an
        item that has already started returning, and otherwise the current
        logical clock."
        PRD §3.2: "Under the `PER_DAY` variant the fee is
        `LATE_FEE_PER_UNIT_PER_DAY_CENTS`, 150 cents, for each late day, capped
        at `LATE_FEE_CAP_PER_UNIT_CENTS`, 4500 cents per unit — the cap binds at
        thirty late days."
        PRD §3.2: "The cycle's `late_fee_cents` is the sum of the per-item fees,
        taken over the cycle's items whose `fulfillment_status` is `SHIPPED`,
        `WITH_MEMBER`, `RETURNING`, `RECEIVED` or `LOST`, walked in ascending
        `slot_index` order; each per-item fee is rounded to the cent first and
        the rounded amounts are then added."

        Design: Corner/calculations/corner_calc_late_fee_per_day_accrual_value
        """
        scenario, _ = self._return_four_days_late("PER_DAY", "SKU-K7-5")
        item = get_box_item(scenario["items"][0]["id"])
        assert item["days_late"] == 4
        assert item["fulfillment_status"] == "RETURNING"
        assert get_unit(scenario["units"][0]["id"])["state"] == "INBOUND"

        validate_success(api.close_swap_window(scenario["cycle"]["id"], ADMIN))
        validate_success(api.assess_late(scenario["cycle"]["id"], BILLING))
        assert get_cycle(scenario["cycle"]["id"])["late_fee_cents"] == 600

    def test_the_flat_tier_variant_charges_a_step_on_identical_input(self, api):
        """PRD §3.2: "Under the `FLAT_TIER` variant the fee is a step function:
        zero when there are no late days, `LATE_FEE_FLAT_TIER_1_CENTS` of 500
        cents while the late days are at most `LATE_FEE_TIER_1_MAX_DAYS`, which
        is 3, `LATE_FEE_FLAT_TIER_2_CENTS` of 2000 cents while they are at most
        `LATE_FEE_TIER_2_MAX_DAYS`, which is 10, and
        `LATE_FEE_FLAT_TIER_3_CENTS` of 4500 cents beyond that."
        PRD §3.2: "The two variants disagree on identical input by construction:
        four days late costs 2000 cents under `FLAT_TIER` but 600 cents under
        `PER_DAY`."

        Design: Corner/calculations/corner_calc_late_fee_flat_tier_diverges_from_per_day
        """
        scenario, _ = self._return_four_days_late("FLAT_TIER", "SKU-K8-5")
        assert get_box_item(scenario["items"][0]["id"])["days_late"] == 4

        validate_success(api.close_swap_window(scenario["cycle"]["id"], ADMIN))
        validate_success(api.assess_late(scenario["cycle"]["id"], BILLING))
        assert get_cycle(scenario["cycle"]["id"])["late_fee_cents"] == 2000


class TestDamageWaiver:
    def _waiver_scenario(self, sku):
        return setup_basic_delivered_scenario(
            plan={"tier": "PLUS", "slots_per_box": 1, "swaps_per_cycle": 1,
                  "monthly_fee_cents": 11500, "protection_available": True,
                  "discount_pct": 0.05},
            member={"child_size_code": "7", "protection_enrolled": True,
                    "auto_apply_credit": False},
            style={"sku": sku, "name": "Waiver Jacket", "size_code": "7",
                   "retail_price_cents": 9000, "season": "AW",
                   "category": "OUTERWEAR"},
            unit={"acquired_at": "2026-01-01T00:00:00Z", "current_grade": "A",
                  "cycles_completed": 0},
        )

    def test_the_discount_scaled_cap_absorbs_a_grade_d_damage_fee_entirely(self, api):
        """PRD §3.6: "The waiver's effective cap for the cycle is
        `PROTECTION_WAIVER_CAP_PER_CYCLE_CENTS`, 5000 cents, scaled by the ratio
        of the cycle's own `protection_fee_cents` to the undiscounted 900-cent
        protection fee, rounded half up; the remaining cap is that effective cap
        less the cycle's `protection_waiver_used_cents`, floored at zero."
        PRD §3.6: "The coupling is deliberate and it costs the household money: a
        10 percent discount that reduces the protection fee to 810 cents also
        shrinks a 5000-cent waiver cap to 4500 cents."
        PRD §3.6: "the item moves `OPEN → WAIVED` exactly when the member is
        enrolled, the grade ordinal is at most 3, the gross fee is strictly
        greater than zero, and the gross fee is less than or equal to the
        remaining cap — that is, when the waiver absorbs the fee **entirely**,
        in which case `damage_fee_cents` is 0 and **no** `DAMAGE_FEE` charge
        entry is created."

        Design: Difficulty/combinatorial_formula/damage_waiver_nested_min_over_grade_enrolment_and_scaled_cap
        """
        scenario = self._waiver_scenario("SKU-WV-7")
        item, unit = scenario["items"][0], scenario["units"][0]
        setup_returned_items(scenario["member"], [item["id"]])
        grade_returned_unit(unit["id"], "D", ["TEAR"])

        assert get_cycle(scenario["cycle"]["id"])["protection_fee_cents"] == 810
        after_item = get_box_item(item["id"])
        assert after_item["assessed_grade"] == "D"
        assert after_item["damage_fee_cents"] == 0
        assert after_item["settlement_status"] == "WAIVED"

    def test_the_cycle_records_the_waiver_headroom_it_consumed(self, api):
        """PRD §3.6: "The item's `damage_fee_cents` is the gross fee less the
        waived amount, and the cycle's `protection_waiver_used_cents` grows by
        the waived amount."
        PRD §3.6: "`DAMAGE_FEE_BY_GRADE_CENTS` gives 0 for `A`, 0 for `B`, 1500
        for `C` and 4000 for `D`, while a `RETIRE` grade instead charges the
        style's `retail_price_cents` multiplied by 0.55 and rounded half up."

        Design: Difficulty/combinatorial_formula/damage_waiver_nested_min_over_grade_enrolment_and_scaled_cap
        """
        scenario = self._waiver_scenario("SKU-WV-7B")
        item, unit = scenario["items"][0], scenario["units"][0]
        setup_returned_items(scenario["member"], [item["id"]])
        grade_returned_unit(unit["id"], "D", ["TEAR"])

        after_cycle = get_cycle(scenario["cycle"]["id"])
        assert after_cycle["protection_waiver_used_cents"] == 4000
        assert after_cycle["damage_fee_cents"] == 0

    def test_a_waived_protection_charge_removes_the_waiver_entirely(self, api):
        """PRD §2.6 rung 62: "The damage waiver may be drawn on only while the
        cycle's `PROTECTION_FEE` charge exists and its `status` is `ASSESSED`,
        `PARTIALLY_SETTLED` or `SETTLED`. If that charge has been `WAIVED`, the
        member paid nothing for protection, so confirming an assessment that
        would draw on the waiver is refused with `ERR_WAIVER_NOT_AVAILABLE`
        (409)."
        PRD §3.6: "confirming an assessment that would draw on the waiver while
        the cycle's `PROTECTION_FEE` charge has itself been waived is refused
        with `ERR_WAIVER_NOT_AVAILABLE`."

        Design: Corner/errors/corner_err_waiver_unavailable_after_the_protection_charge_is_waived
        """
        plan, member = setup_plan_and_member(
            plan={"monthly_fee_cents": 5000, "protection_available": True,
                  "discount_pct": 0},
            member={"protection_enrolled": True, "auto_apply_credit": False},
        )
        style = create_style(sku="SKU-XWV-5", name="Waiver Gone Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        protection_charge = find_charge(member["id"], "PROTECTION_FEE")
        validate_success(api.waive_charge_entry(protection_charge["id"],
                                                {"waive_reason": "service recovery"}, BILLING))

        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        pack_box(box["id"])
        outbound = mint_label(member["id"], "OUTBOUND")
        shipment = ship_box(box["id"], outbound["id"])
        depart_shipment(shipment["id"])
        receive_shipment(shipment["id"])
        setup_returned_items(member, [item["id"]])
        assessment = find_rental_assessment(unit["id"])
        submit_grade(assessment["id"], "C", ["STAIN"], grader_id="grader-wv")

        resp = api.confirm_assessment(assessment["id"], make_planner_headers("planner-wv"))
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_AVAILABLE.value, 409)

        assert validate_success(
            api.get_charge_entry(protection_charge["id"], BILLING)
        )["status"] == "WAIVED"
        assert get_assessment(assessment["id"])["status"] == "SUBMITTED"
        after_item = get_box_item(item["id"])
        assert after_item["settlement_status"] == "OPEN"
        assert after_item["damage_fee_cents"] == 0


class TestCirculationLoop:
    def _loop_scenario(self, sku):
        plan, member = setup_plan_and_member(
            plan={"slots_per_box": 1, "swaps_per_cycle": 1},
            member={"auto_apply_credit": False},
        )
        style = create_style(sku=sku, name="Loop Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z",
                           current_grade="A", cycles_completed=0)
        first_cycle = create_open_cycle(member["id"])
        box = create_box(first_cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        pack_box(box["id"])
        outbound = mint_label(member["id"], "OUTBOUND")
        shipment = ship_box(box["id"], outbound["id"])
        depart_shipment(shipment["id"])
        receive_shipment(shipment["id"])
        setup_returned_items(member, [item["id"]])
        grade_returned_unit(unit["id"], "A")
        job = find_processing_job(unit["id"])
        validate_success(api_client.start_processing_job(job["id"], VENDOR))
        second_cycle = create_open_cycle(member["id"])
        second_box = create_box(second_cycle["id"])
        return {"member": member, "style": style, "unit": unit, "job": job,
                "second_box": second_box}

    def test_a_passed_job_restocks_the_unit_so_it_can_be_allocated_again(self, api):
        """PRD §3.3: "The circulation loop is the heart of Pipeline R and it is
        **re-entrant**: `IN_STOCK → RESERVED → OUT → INBOUND → PROCESSING →
        IN_STOCK`, traversed once per wear cycle by the same unit."
        PRD §3.6: "A passed job on a unit that is not eligible returns it
        `PROCESSING → IN_STOCK` and it re-enters circulation."
        PRD §3.3: "Allocation moves the chosen unit `IN_STOCK → RESERVED`,
        creates a `BoxItem` with `fulfillment_status` `ALLOCATED` and
        `settlement_status` `OPEN`"

        Design: Difficulty/non_linear_state_machine/garment_unit_completes_circulation_loop_and_re_enters_it
        """
        world = self._loop_scenario("SKU-LOOP-5")
        validate_success(api.pass_processing_job(world["job"]["id"], VENDOR))
        assert get_unit(world["unit"]["id"])["state"] == "IN_STOCK"

        second_item = validate_success(
            api.allocate_into_box(world["second_box"]["id"],
                                  {"unit_id": world["unit"]["id"]}, WAREHOUSE),
            201,
        )
        assert second_item["fulfillment_status"] == "ALLOCATED"
        assert get_unit(world["unit"]["id"])["state"] == "RESERVED"

    def test_one_full_loop_leaves_a_wear_ledger_of_exactly_one_cycle(self, api):
        """PRD §3.6: "The unit's `cumulative_cleaning_cost_cents` becomes the sum
        of `cost_cents` over that unit's jobs whose `status` is `PASSED` or
        `SCRAPPED`, walked in ascending `created_at` order."
        PRD §3.6: "a unit is `retirement_eligible` when its `cycles_completed`
        has reached `UNIT_MAX_CYCLES`, 8, **or** its
        `cumulative_cleaning_cost_cents` has reached
        `UNIT_MAX_CLEANING_COST_CENTS`, 6000, **or** its `current_grade` is
        `RETIRE`."
        PRD §3.6: "If the job's route is not `REPAIR`, or the job supplies no
        `post_repair_grade`, the effective grade is simply the confirmed
        assessment grade."

        Design: Difficulty/non_linear_state_machine/garment_unit_completes_circulation_loop_and_re_enters_it
        """
        world = self._loop_scenario("SKU-LOOP-5B")
        validate_success(api.pass_processing_job(world["job"]["id"], VENDOR))
        validate_success(api.allocate_into_box(world["second_box"]["id"],
                                               {"unit_id": world["unit"]["id"]},
                                               WAREHOUSE), 201)

        after = get_unit(world["unit"]["id"])
        assert after["cycles_completed"] == 1
        assert after["cumulative_cleaning_cost_cents"] == 320
        assert after["current_grade"] == "A"
        assert after["retirement_eligible"] is False
        assert get_style(world["style"]["id"])["units_ever_acquired"] == 1


class TestParallelAxes:
    def _received_but_unconfirmed(self, sku):
        scenario = setup_basic_delivered_scenario(
            member={"protection_enrolled": False, "auto_apply_credit": False},
            style={"sku": sku, "name": "Axes Dress", "size_code": "5",
                   "retail_price_cents": 4000, "category": "DRESS"},
        )
        item, unit = scenario["items"][0], scenario["units"][0]
        setup_returned_items(scenario["member"], [item["id"]])
        assessment = find_rental_assessment(unit["id"])
        submit_grade(assessment["id"], "A", grader_id="grader-05")
        scenario["assessment"] = assessment
        return scenario

    def test_a_received_item_is_still_open_on_the_money_axis(self, api):
        """PRD §3.5: "A `RETURN` receipt advances `RETURNING` items to
        `RECEIVED`, moves their units `INBOUND → PROCESSING`, increments each
        unit's `cycles_completed` by 1, and opens a `DRAFT` condition assessment
        of `pipeline` `RENTAL` per unit."
        PRD §3.3: "creates a `BoxItem` with `fulfillment_status` `ALLOCATED` and
        `settlement_status` `OPEN`"

        Design: Difficulty/non_linear_state_machine/box_item_fulfillment_and_settlement_axes_advance_independently
        """
        scenario = self._received_but_unconfirmed("SKU-AX-5")
        mid = get_box_item(scenario["items"][0]["id"])
        assert mid["fulfillment_status"] == "RECEIVED"
        assert mid["settlement_status"] == "OPEN"

    def test_grade_confirmation_advances_only_the_settlement_axis(self, api):
        """PRD §3.6: "For a `RENTAL` record, confirmation writes `assessed_grade`
        onto the returned box item, creates a processing job, and advances the
        item's settlement axis."
        PRD §3.6: "In every other case the item moves `OPEN → SETTLED`,
        `assessed_grade` is written, `damage_fee_cents` is computed as above —
        which may still be a *partially* waived amount when the gross fee
        exceeded the remaining cap — and a charge ledger entry of `charge_type`
        `DAMAGE_FEE` is created whenever the resulting `damage_fee_cents` is
        greater than zero."

        Design: Difficulty/non_linear_state_machine/box_item_fulfillment_and_settlement_axes_advance_independently
        """
        scenario = self._received_but_unconfirmed("SKU-AX-5B")
        confirm_grade(scenario["assessment"]["id"], planner_id="planner-05")

        after = get_box_item(scenario["items"][0]["id"])
        assert after["fulfillment_status"] == "RECEIVED"
        assert after["settlement_status"] == "SETTLED"
        assert after["assessed_grade"] == "A"
        assert after["damage_fee_cents"] == 0
        assert get_unit(scenario["units"][0]["id"])["state"] == "PROCESSING"
