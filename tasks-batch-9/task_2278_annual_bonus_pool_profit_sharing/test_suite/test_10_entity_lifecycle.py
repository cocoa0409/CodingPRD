"""Creation, retrieval, defaults, computed and system fields, and immutability."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid
from test_helpers import (
    FC,
    HR,
    NON_EXISTENT_UUID,
    PA,
    ApiErrorId,
    assert_bonus_plan,
    assert_eligibility_event,
    assert_participant,
    assert_pct,
    assert_ratio,
    bonus_plan_payload,
    bu_pool_payload,
    business_unit_payload,
    company_metric_payload,
    job_level_target_payload,
    metric_actual_payload,
    participant_payload,
    transfer_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

_ZEROED_MONEY_FIELDS = (
    "total_target_cents",
    "funded_pool_cents",
    "aggregate_rounding_delta_cents",
    "discretionary_budget_cents",
    "discretionary_used_cents",
    "accrued_base_cents",
    "accrued_total_cents",
    "locked_total_cents",
    "paid_total_cents",
    "forfeited_total_cents",
    "dispute_adjustment_cents",
    "settlement_burden_cents",
    "true_up_cents",
    "over_allocated_pool_count",
    "under_utilized_pool_count",
)


class TestBonusPlanCreation:
    def test_a_plan_created_from_the_required_inputs_alone_starts_zeroed(self, api):
        """PRD §3.1: "On creation, `status` is `DRAFT`, `governance_posture` is
        `COMPLIANT`, and every achievement, multiplier and money field is initialised to
        zero: `company_achievement_pct`, `bu_weighted_achievement_pct` and
        `blended_achievement_pct` at 0.00, `funding_multiplier` at 0.0000, and
        `total_target_cents`, `funded_pool_cents`, `aggregate_rounding_delta_cents`,
        `discretionary_budget_cents`, `discretionary_used_cents`, `accrued_base_cents`,
        `accrued_total_cents`, `locked_total_cents`, `paid_total_cents`,
        `forfeited_total_cents`, `dispute_adjustment_cents`, `settlement_burden_cents`,
        `true_up_cents`, `over_allocated_pool_count` and `under_utilized_pool_count` all
        at 0."

        Design: Corner/entities/bonus_plan_creation_returns_declared_defaults_and_a_zeroed_ledger
        """
        validate_success(
            api.create_business_unit(business_unit_payload(unit_code="UNIT-A1"), PA),
            expected_status=201,
        )

        response = api.create_bonus_plan(
            bonus_plan_payload(plan_name="FY26 Creation Plan"), PA
        )
        plan = validate_success(response, expected_status=201)
        assert response.json()["response_type"] == "object"

        assert plan["status"] == "DRAFT"
        assert plan["governance_posture"] == "COMPLIANT"
        assert_pct(plan["discretionary_budget_pct"], 10.00)
        assert plan["termination_treatment_policy"] == "STRICT_PAYMENT_DATE"
        assert_pct(plan["company_achievement_pct"], 0.00)
        assert_pct(plan["bu_weighted_achievement_pct"], 0.00)
        assert_pct(plan["blended_achievement_pct"], 0.00)
        assert_ratio(plan["funding_multiplier"], 0.0000)
        for field in _ZEROED_MONEY_FIELDS:
            assert plan[field] == 0, f"{field} must start at 0"
        assert plan["certified_by_user_id"] is None
        assert plan["locked_by_user_id"] is None
        assert plan["version"] == 1
        assert_bonus_plan(plan)

    def test_the_stored_plan_reads_back_field_for_field_to_a_finance_controller(
        self, api
    ):
        """PRD §3.1: "`discretionary_budget_pct`, the share of the funded pool held back
        for discretionary exceptions, lies between 0 and 25 with two decimals and defaults
        to 10.00." And: "`termination_treatment_policy` selects which payout variant runs
        at execution and is either `STRICT_PAYMENT_DATE` or `GOOD_LEAVER_PRORATION`,
        defaulting to `STRICT_PAYMENT_DATE`."

        Design: Corner/entities/bonus_plan_retrieval_returns_the_stored_record
        """
        created = validate_success(
            api.create_bonus_plan(
                bonus_plan_payload(
                    plan_name="FY26 Retrieval Plan",
                    company_weight_pct=40.00,
                    business_unit_weight_pct=40.00,
                    individual_weight_pct=20.00,
                    discretionary_budget_pct=12.50,
                    termination_treatment_policy="GOOD_LEAVER_PRORATION",
                ),
                PA,
            ),
            expected_status=201,
        )

        plan = validate_success(api.get_bonus_plan(created["id"], FC))

        assert plan["plan_year"] == 2026
        assert plan["plan_name"] == "FY26 Retrieval Plan"
        assert_pct(plan["company_weight_pct"], 40.00)
        assert_pct(plan["business_unit_weight_pct"], 40.00)
        assert_pct(plan["individual_weight_pct"], 20.00)
        assert_pct(plan["discretionary_budget_pct"], 12.50)
        assert plan["termination_treatment_policy"] == "GOOD_LEAVER_PRORATION"
        assert plan["payment_date"] == "2027-03-15"
        assert plan["status"] == "DRAFT"

    def test_three_plans_paginate_and_filter_on_their_own_total_count(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        in the envelope's `meta` object, where `total_count` is the number of records
        matching the filters before pagination is applied." And: "Unless a collection says
        otherwise, records are returned sorted by `created_at` ascending."

        Design: Corner/entities/bonus_plans_listing_paginates_with_total_count_and_has_more
        """
        for plan_name in ("FY26 Plan One", "FY26 Plan Two"):
            validate_success(
                api.create_bonus_plan(bonus_plan_payload(plan_name=plan_name), PA),
                expected_status=201,
            )
        third = validate_success(
            api.create_bonus_plan(
                bonus_plan_payload(
                    plan_name="FY27 Plan One",
                    plan_year=2027,
                    plan_period_start="2027-01-01",
                    plan_period_end="2028-01-01",
                    payment_date="2028-03-15",
                ),
                PA,
            ),
            expected_status=201,
        )

        first_page, meta = validate_paginated(
            api.list_bonus_plans(PA, params={"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        second_page, meta = validate_paginated(
            api.list_bonus_plans(PA, params={"limit": 2, "offset": 2})
        )
        assert [row["id"] for row in second_page] == [third["id"]]
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["offset"] == 2

        filtered, meta = validate_paginated(
            api.list_bonus_plans(PA, params={"plan_year": 2027})
        )
        assert [row["id"] for row in filtered] == [third["id"]]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

    def test_the_missing_payment_date_wins_over_the_broken_weight_sum(self, api):
        """PRD §2.10: "The ladder below is total: every check has a distinct position, and
        a request that fails more than one check returns the error of the
        highest-positioned (earliest) check it fails."

        Design: Corner/entities/bonus_plan_creation_missing_payment_date_rejected
        """
        validate_success(
            api.create_business_unit(business_unit_payload(unit_code="UNIT-A2"), PA),
            expected_status=201,
        )

        response = api.create_bonus_plan(
            {
                "plan_year": 2026,
                "plan_name": "FY26 Missing Date",
                "plan_period_start": "2026-01-01",
                "plan_period_end": "2027-01-01",
                "company_weight_pct": 40.00,
                "business_unit_weight_pct": 30.00,
                "individual_weight_pct": 20.00,
            },
            PA,
        )
        error = validate_error(
            response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )
        assert error["error_id"] != ApiErrorId.ERR_PLAN_WEIGHTS_INVALID.value

        _, meta = validate_paginated(api.list_bonus_plans(PA))
        assert meta["total_count"] == 0

    def test_a_third_termination_policy_value_is_refused_as_malformed(self, api):
        """PRD §2.10: "**Request shape.** Every required input field present, every enum
        value inside its declared set, every date a valid ISO 8601 `YYYY-MM-DD` calendar
        date, every cents field an integer, pagination inside its band, and every
        conditionally-required field present: `leave_end_date` for a `LEAVE` event,
        `termination_reason` for a `TERMINATION` event, `new_job_level` together with
        `new_base_salary_cents` and `new_business_unit_id` for a `TRANSFER` event, and
        `adjusted_amount_cents` for a dispute resolution of `ADJUST`. Any failure is
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/bonus_plan_invalid_enum_termination_policy_rejected
        """
        validate_success(
            api.create_business_unit(business_unit_payload(unit_code="UNIT-A5"), PA),
            expected_status=201,
        )

        response = api.create_bonus_plan(
            bonus_plan_payload(
                plan_name="FY26 Bad Enum", termination_treatment_policy="PAY_EVERYONE"
            ),
            PA,
        )
        validate_error(
            response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )

        _, meta = validate_paginated(api.list_bonus_plans(PA))
        assert meta["total_count"] == 0


class TestDeclaredDefaultsAndServerOwnedFields:
    def test_the_three_optional_inputs_settle_on_their_declared_defaults(self, api):
        """PRD §3.2: "A `LEAVE` carries `leave_end_date`, the last day of leave
        **inclusive** — so the occupied interval runs from `effective_date` through
        `leave_end_date` — plus the `paid_leave` flag, which defaults to false." And PRD
        §3.2: "A new participant is `ACTIVE`: `employment_status` is `ACTIVE`,
        `termination_date` and `termination_reason` are null, and the derived trio
        `current_job_level`, `current_base_salary_cents` and `current_business_unit_id` is
        seeded from the supplied `job_level`, `base_salary_cents` and `business_unit_id`."

        Design: Corner/entities/optional_inputs_take_their_declared_defaults
        """
        unit = validate_success(
            api.create_business_unit(business_unit_payload(unit_code="UNIT-A3"), PA),
            expected_status=201,
        )
        plan = validate_success(
            api.create_bonus_plan(
                bonus_plan_payload(plan_name="FY26 Defaults Plan"), PA
            ),
            expected_status=201,
        )
        assert_pct(plan["discretionary_budget_pct"], 10.00)
        assert plan["termination_treatment_policy"] == "STRICT_PAYMENT_DATE"

        validate_success(
            api.create_job_level_target(
                job_level_target_payload(
                    plan["id"], job_level="L3", target_bonus_pct=10.00
                ),
                PA,
            ),
            expected_status=201,
        )
        participant = validate_success(
            api.create_participant(
                participant_payload(
                    plan["id"],
                    unit["id"],
                    employee_code="E501",
                    full_name="Dee Fault",
                    job_level="L3",
                    base_salary_cents=10000000,
                    hire_date="2025-01-01",
                ),
                PA,
            ),
            expected_status=201,
        )
        assert participant["employment_status"] == "ACTIVE"
        assert participant["termination_date"] is None
        assert participant["termination_reason"] is None

        # The paid_leave flag is left out of the body entirely.
        event = validate_success(
            api.create_eligibility_event(
                {
                    "participant_id": participant["id"],
                    "event_type": "LEAVE",
                    "effective_date": "2026-02-01",
                    "leave_end_date": "2026-02-28",
                    "note": "leave filed without the paid flag",
                },
                HR,
            ),
            expected_status=201,
        )
        assert event["paid_leave"] is False
        assert event["superseded"] is False
        assert event["leave_end_date"] == "2026-02-28"

    def test_the_metric_achievement_is_scored_by_the_curve_not_by_the_client(self, api):
        """PRD §3.4: "An actual that is at least `threshold_value` but below
        `target_value` scores 50.00 plus half of the fraction of the way it has travelled
        from `threshold_value` to `target_value`, expressed in percentage points — that
        is, 50 plus the difference between `actual_value` and `threshold_value`, divided
        by the difference between `target_value` and `threshold_value`, multiplied by 50."

        Design: Corner/entities/metric_achievement_pct_is_computed_with_client_input_ignored
        """
        plan = validate_success(
            api.create_bonus_plan(
                bonus_plan_payload(plan_name="FY26 Computed Field Plan"), PA
            ),
            expected_status=201,
        )
        metric = validate_success(
            api.create_company_metric(company_metric_payload(plan["id"]), PA),
            expected_status=201,
        )
        assert metric["status"] == "DRAFT"
        assert_pct(metric["achievement_pct"], 0.00)

        filed = validate_success(
            api.file_metric_actual(
                metric["id"],
                metric_actual_payload(
                    950, source_note="audited half-way result", achievement_pct=999.99
                ),
                PA,
            )
        )

        assert_pct(filed["achievement_pct"], 75.00)
        assert filed["actual_value"] == 950
        assert filed["status"] == "ACTUAL_ENTERED"
        assert filed["source_note"] == "audited half-way result"

    def test_the_participant_system_fields_ignore_everything_the_client_sent(self, api):
        """PRD §2.4: "Every resource is addressed by an `id` that the server mints as a
        UUID with no type prefix; clients never supply it." And PRD §3.2: "A new
        participant is `ACTIVE`: `employment_status` is `ACTIVE`, `termination_date` and
        `termination_reason` are null, and the derived trio `current_job_level`,
        `current_base_salary_cents` and `current_business_unit_id` is seeded from the
        supplied `job_level`, `base_salary_cents` and `business_unit_id`."

        Design: Corner/entities/participant_system_fields_are_server_generated_with_input_ignored
        """
        unit = validate_success(
            api.create_business_unit(business_unit_payload(unit_code="UNIT-A4"), PA),
            expected_status=201,
        )
        plan = validate_success(
            api.create_bonus_plan(
                bonus_plan_payload(plan_name="FY26 System Fields Plan"), PA
            ),
            expected_status=201,
        )
        validate_success(
            api.create_job_level_target(
                job_level_target_payload(
                    plan["id"], job_level="L3", target_bonus_pct=10.00
                ),
                PA,
            ),
            expected_status=201,
        )

        client_id = "00000000-0000-0000-0000-00000000dead"
        participant = validate_success(
            api.create_participant(
                participant_payload(
                    plan["id"],
                    unit["id"],
                    employee_code="E502",
                    full_name="Sys Field",
                    job_level="L3",
                    base_salary_cents=10000000,
                    hire_date="2025-01-01",
                    id=client_id,
                    employment_status="TERMINATED",
                    termination_date="2026-01-31",
                    version=99,
                ),
                PA,
            ),
            expected_status=201,
        )

        assert participant["id"] != client_id
        assert is_valid_uuid(participant["id"])
        assert participant["employment_status"] == "ACTIVE"
        assert participant["termination_date"] is None
        assert participant["termination_reason"] is None
        assert participant["version"] == 1
        assert is_iso8601_timestamp(participant["created_at"])
        assert is_iso8601_timestamp(participant["updated_at"])
        assert participant["current_job_level"] == "L3"
        assert participant["current_base_salary_cents"] == 10000000
        assert participant["current_business_unit_id"] == unit["id"]
        assert_participant(participant)

    def test_a_degenerate_and_a_reversed_guideline_band_are_both_refused(self, api):
        """PRD §3.1: "Both lie between 0 and 5 with two decimals, `guideline_max_ratio`
        must be strictly greater than `guideline_min_ratio`, and a band that fails either
        condition is rejected with `ERR_GUIDELINE_BAND_INVALID`."

        Design: Corner/entities/job_level_target_guideline_band_type_constraint_rejected
        """
        plan = validate_success(
            api.create_bonus_plan(bonus_plan_payload(plan_name="FY26 Band Plan"), PA),
            expected_status=201,
        )

        for minimum, maximum in ((1.00, 1.00), (2.00, 0.25)):
            response = api.create_job_level_target(
                job_level_target_payload(
                    plan["id"],
                    job_level="L3",
                    target_bonus_pct=10.00,
                    guideline_min_ratio=minimum,
                    guideline_max_ratio=maximum,
                ),
                PA,
            )
            validate_error(
                response,
                ApiErrorId.ERR_GUIDELINE_BAND_INVALID.value,
                expected_status=422,
            )

        target = validate_success(
            api.create_job_level_target(
                job_level_target_payload(
                    plan["id"],
                    job_level="L3",
                    target_bonus_pct=10.00,
                    guideline_min_ratio=0.25,
                    guideline_max_ratio=2.00,
                ),
                PA,
            ),
            expected_status=201,
        )
        assert target["guideline_min_ratio"] == 0.25
        assert target["guideline_max_ratio"] == 2.00

        _, meta = validate_paginated(
            api.list_job_level_targets(PA, params={"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 1


class TestAppendOnlyAndParentRelationships:
    def test_a_mistaken_transfer_is_corrected_by_appending_a_superseding_event(
        self, api
    ):
        """PRD §2.4: "Eligibility events are an append-only record: an event is never
        edited, and a mistake is corrected by appending a new event that names the
        mistaken one." And PRD §3.2: "A new event may name a previous one in
        `supersedes_event_id`; the named event's `superseded` flag becomes true and that
        event is thereafter excluded entirely from every proration input set, including
        all of its leave days."

        Design: Corner/entities/eligibility_event_is_append_only_and_superseded_instead_of_edited
        """
        unit = validate_success(
            api.create_business_unit(business_unit_payload(unit_code="UNIT-A6"), PA),
            expected_status=201,
        )
        plan = validate_success(
            api.create_bonus_plan(
                bonus_plan_payload(plan_name="FY26 Append Only Plan"), PA
            ),
            expected_status=201,
        )
        for job_level, pct in (("L3", 10.00), ("L5", 20.00)):
            validate_success(
                api.create_job_level_target(
                    job_level_target_payload(
                        plan["id"], job_level=job_level, target_bonus_pct=pct
                    ),
                    PA,
                ),
                expected_status=201,
            )
        participant = validate_success(
            api.create_participant(
                participant_payload(
                    plan["id"],
                    unit["id"],
                    employee_code="E503",
                    full_name="App Endonly",
                    job_level="L3",
                    base_salary_cents=10000000,
                    hire_date="2025-01-01",
                ),
                PA,
            ),
            expected_status=201,
        )
        first = validate_success(
            api.create_eligibility_event(
                transfer_event_payload(
                    participant["id"],
                    "2026-07-01",
                    "L5",
                    19000000,
                    unit["id"],
                    note="wrong salary keyed",
                ),
                HR,
            ),
            expected_status=201,
        )

        correction = validate_success(
            api.create_eligibility_event(
                transfer_event_payload(
                    participant["id"],
                    "2026-07-01",
                    "L5",
                    20000000,
                    unit["id"],
                    supersedes_event_id=first["id"],
                    note="correction of the keying error",
                ),
                HR,
            ),
            expected_status=201,
        )

        stored_first = validate_success(api.get_eligibility_event(first["id"], HR))
        assert stored_first["superseded"] is True
        # The original row is not edited in place.
        assert stored_first["new_base_salary_cents"] == 19000000
        assert correction["superseded"] is False
        assert correction["supersedes_event_id"] == first["id"]
        assert_eligibility_event(stored_first)
        assert_eligibility_event(correction)

        _, meta = validate_paginated(
            api.list_eligibility_events(
                HR, params={"participant_id": participant["id"]}
            )
        )
        assert meta["total_count"] == 2

        live, meta = validate_paginated(
            api.list_eligibility_events(
                HR, params={"participant_id": participant["id"], "superseded": "false"}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in live] == [correction["id"]]

    def test_each_unknown_body_reference_returns_the_not_found_of_its_own_entity(
        self, api
    ):
        """PRD §2.9: "Each unresolved reference raises its own not-found error —
        `ERR_PLAN_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_BUSINESS_UNIT_NOT_FOUND`,
        `ERR_POOL_NOT_FOUND`, `ERR_AWARD_NOT_FOUND` and `ERR_EVENT_NOT_FOUND`
        respectively."

        Design: Corner/entities/participant_with_unknown_parent_ids_returns_not_found
        """
        unit = validate_success(
            api.create_business_unit(business_unit_payload(unit_code="UNIT-A7"), PA),
            expected_status=201,
        )
        plan = validate_success(
            api.create_bonus_plan(bonus_plan_payload(plan_name="FY26 Parent FK Plan"), PA),
            expected_status=201,
        )
        validate_success(
            api.create_job_level_target(
                job_level_target_payload(
                    plan["id"], job_level="L3", target_bonus_pct=10.00
                ),
                PA,
            ),
            expected_status=201,
        )

        unknown_plan = api.create_participant(
            participant_payload(
                NON_EXISTENT_UUID,
                unit["id"],
                employee_code="E504",
                full_name="No Plan",
                job_level="L3",
                base_salary_cents=10000000,
                hire_date="2025-01-01",
            ),
            PA,
        )
        validate_error(
            unknown_plan, ApiErrorId.ERR_PLAN_NOT_FOUND.value, expected_status=404
        )

        unknown_unit = api.create_participant(
            participant_payload(
                plan["id"],
                NON_EXISTENT_UUID,
                employee_code="E505",
                full_name="No Unit",
                job_level="L3",
                base_salary_cents=10000000,
                hire_date="2025-01-01",
            ),
            PA,
        )
        validate_error(
            unknown_unit,
            ApiErrorId.ERR_BUSINESS_UNIT_NOT_FOUND.value,
            expected_status=404,
        )

        _, meta = validate_paginated(
            api.list_participants(PA, params={"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 0

    def test_each_unknown_path_identifier_returns_its_own_not_found_error(self, api):
        """PRD §2.9: "The identifiers in use are `{planId}` for a bonus plan
        (`ERR_PLAN_NOT_FOUND`), `{metricId}` for a company metric
        (`ERR_METRIC_NOT_FOUND`), `{unitId}` for a business unit
        (`ERR_BUSINESS_UNIT_NOT_FOUND`), `{targetId}` for a job-level target row
        (`ERR_JOB_LEVEL_TARGET_NOT_FOUND`), `{participantId}` for a participant
        (`ERR_PARTICIPANT_NOT_FOUND`), `{eventId}` for an eligibility event
        (`ERR_EVENT_NOT_FOUND`), `{poolId}` for a business-unit pool
        (`ERR_POOL_NOT_FOUND`), `{awardId}` for a participant award
        (`ERR_AWARD_NOT_FOUND`), `{adjustmentId}` for a discretionary adjustment
        (`ERR_ADJUSTMENT_NOT_FOUND`), `{periodId}` for an accrual period
        (`ERR_ACCRUAL_PERIOD_NOT_FOUND`), `{payoutRunId}` for a payout run
        (`ERR_PAYOUT_RUN_NOT_FOUND`) and `{disputeId}` for a dispute
        (`ERR_DISPUTE_NOT_FOUND`)."

        Design: Corner/entities/unknown_ids_return_each_resources_own_not_found_error
        """
        validate_success(
            api.create_bonus_plan(
                bonus_plan_payload(plan_name="FY26 Not Found Probe"), PA
            ),
            expected_status=201,
        )

        reads = (
            (api.get_bonus_plan, ApiErrorId.ERR_PLAN_NOT_FOUND),
            (api.get_company_metric, ApiErrorId.ERR_METRIC_NOT_FOUND),
            (api.get_business_unit, ApiErrorId.ERR_BUSINESS_UNIT_NOT_FOUND),
            (api.get_job_level_target, ApiErrorId.ERR_JOB_LEVEL_TARGET_NOT_FOUND),
            (api.get_participant, ApiErrorId.ERR_PARTICIPANT_NOT_FOUND),
            (api.get_eligibility_event, ApiErrorId.ERR_EVENT_NOT_FOUND),
            (api.get_bu_pool, ApiErrorId.ERR_POOL_NOT_FOUND),
            (api.get_participant_award, ApiErrorId.ERR_AWARD_NOT_FOUND),
            (api.get_discretionary_adjustment, ApiErrorId.ERR_ADJUSTMENT_NOT_FOUND),
            (api.get_accrual_period, ApiErrorId.ERR_ACCRUAL_PERIOD_NOT_FOUND),
            (api.get_payout_run, ApiErrorId.ERR_PAYOUT_RUN_NOT_FOUND),
            (api.get_dispute, ApiErrorId.ERR_DISPUTE_NOT_FOUND),
        )
        for read, error_id in reads:
            validate_error(
                read(NON_EXISTENT_UUID, PA), error_id.value, expected_status=404
            )

    def test_a_second_pool_for_the_same_pair_is_duplicate_while_another_plan_is_free(
        self, api
    ):
        """PRD §3.1: "Each business unit that will spend money in a plan needs a
        **business-unit pool**, created by a `PlanAdmin` with the pool's `plan_id` and
        `business_unit_id`; at most one pool may exist per plan-and-unit pair, and a
        second is `ERR_DUPLICATE_RESOURCE`." And PRD §3.1: "A new pool starts with
        `calibration_status` `DRAFT` and `distribution_status` `NO_ELIGIBLE_PARTICIPANTS`,
        with `eligible_target_cents`, `eligible_headcount`, `funded_cents`,
        `allocated_cents`, `available_cents`, `min_utilization_cents`,
        `top_tier_award_count`, `max_top_tier_count` and `calibration_returned_count` at
        0, `utilization_pct` at 0.00, and `scorecard_certified_by_user_id` null."

        Design: Corner/entities/second_pool_for_the_same_plan_and_unit_is_rejected_as_duplicate
        """
        unit = validate_success(
            api.create_business_unit(business_unit_payload(unit_code="UNIT-A8"), PA),
            expected_status=201,
        )
        plan_a = validate_success(
            api.create_bonus_plan(
                bonus_plan_payload(plan_name="FY26 Duplicate Pool Plan A"), PA
            ),
            expected_status=201,
        )
        plan_b = validate_success(
            api.create_bonus_plan(
                bonus_plan_payload(
                    plan_name="FY27 Duplicate Pool Plan B",
                    plan_year=2027,
                    plan_period_start="2027-01-01",
                    plan_period_end="2028-01-01",
                    payment_date="2028-03-15",
                ),
                PA,
            ),
            expected_status=201,
        )
        pool_a = validate_success(
            api.create_bu_pool(bu_pool_payload(plan_a["id"], unit["id"]), PA),
            expected_status=201,
        )

        duplicate = api.create_bu_pool(bu_pool_payload(plan_a["id"], unit["id"]), PA)
        validate_error(
            duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, expected_status=409
        )

        pool_b = validate_success(
            api.create_bu_pool(bu_pool_payload(plan_b["id"], unit["id"]), PA),
            expected_status=201,
        )
        assert pool_b["plan_id"] == plan_b["id"]

        rows, meta = validate_paginated(
            api.list_bu_pools(PA, params={"plan_id": plan_a["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [pool_a["id"]]

        assert pool_a["calibration_status"] == "DRAFT"
        assert pool_a["distribution_status"] == "NO_ELIGIBLE_PARTICIPANTS"
        for field in (
            "eligible_target_cents",
            "eligible_headcount",
            "funded_cents",
            "allocated_cents",
            "available_cents",
            "min_utilization_cents",
            "top_tier_award_count",
            "max_top_tier_count",
            "calibration_returned_count",
        ):
            assert pool_a[field] == 0, f"a new pool starts with {field} at 0"
        assert_pct(pool_a["utilization_pct"], 0.00)
        assert pool_a["scorecard_certified_by_user_id"] is None
