"""Individual validation rules: the shape rules on workpaper legs, the two
uniqueness scopes, the structural precondition on the allocation, and the two
bands that decide a malformed fiscal period and an unauthorized registration."""

from test_helpers import (
    ANALYST_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    ApiErrorId,
    assert_cost_center,
    assert_money_equals,
    assert_workpaper_entry,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    adjustment_payload,
    cost_center_payload,
    occ_mix_response_payload,
    reclassification_payload,
    stepdown_run_payload,
    workpaper_leg,
)
from test_helpers.fixtures import (
    CENTER_ROUTINE,
    add_cost_center,
    add_mapped_tb_line,
    create_provider,
    new_scenario,
    read_cost_center,
    read_cost_report,
    run_stepdown,
    set_clock,
    setup_two_center_report,
)

MINIMAL_SURVEY_INPUTS = {
    "total_salaries_cents": 5000000000,
    "total_paid_hours": 2000000.00,
}


def _single_routine_center_report(api):
    """A report holding one ROUTINE center funded with 200000000 and nothing else."""
    scenario = new_scenario(api)
    add_cost_center(
        api,
        scenario,
        "cc_routine",
        {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}},
    )
    add_mapped_tb_line(api, scenario, "6200", "Nursing salaries", 200000000, "cc_routine")
    return scenario


def test_reclassification_legs_that_do_not_net_to_zero_are_refused(api):
    """Legs of -5000000 and +4000000 leave 1000000 unaccounted for, so the entry is
    refused and neither center's reclassified column moves.

    PRD 3.3: "A `RECLASSIFICATION` must have at least two legs and its leg amounts must sum to exactly zero — it moves cost, it never creates or destroys it — and an entry that has fewer than two legs or whose legs do not net to zero is rejected with `ERR_RECLASS_NOT_BALANCED`."

    Design: Corner/validations/unbalanced_reclassification_legs_are_rejected
    """
    scenario = setup_two_center_report(api)

    response = api.create_workpaper_entry(
        scenario["report_id"],
        reclassification_payload(
            [
                workpaper_leg(scenario["cc_ag"], -5000000),
                workpaper_leg(scenario["cc_routine"], 4000000),
            ],
            code="A-6-1",
            description="Move dietary overhead",
        ),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_RECLASS_NOT_BALANCED.value, 422)

    entries, meta = validate_paginated(
        api.list_report_workpaper_entries(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert entries == []

    allocator = read_cost_center(api, scenario, scenario["cc_ag"])
    assert_money_equals(
        allocator["reclassified_amount_cents"], 0, "00100 reclassified_amount_cents"
    )
    assert_money_equals(
        allocator["post_reclass_direct_cost_cents"],
        100000000,
        "00100 post_reclass_direct_cost_cents",
    )

    receiver = read_cost_center(api, scenario, scenario["cc_routine"])
    assert_money_equals(
        receiver["reclassified_amount_cents"], 0, "03000 reclassified_amount_cents"
    )


def test_balanced_legs_shift_the_post_reclass_pool_and_stale_the_allocation(api):
    """Legs of -5000000 and +5000000 net to zero, so the entry stands and moves the
    pool to 95000000 / 205000000 while demoting the standing run.

    PRD 3.3: "On that basis each cost center's `reclassified_amount_cents` is the signed sum of leg amounts targeting it across the report's `ACTIVE` entries of type `RECLASSIFICATION`, and its `adjustment_amount_cents` is the signed sum of leg amounts targeting it across the report's `ACTIVE` entries of type `ADJUSTMENT`."

    PRD 3.3: "Both creating and reversing an entry additionally demote every `COMPLETED` stepdown run of the report to `STALE` with `stale_reason` `WORKPAPER_ENTRY_CHANGED`, set the report's `allocation_status` to `STALE`, and increment the report's `version`."

    Design: Corner/validations/balanced_reclassification_passes_and_shifts_post_reclass_cost
    """
    scenario = setup_two_center_report(api)
    run = run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    assert run["status"] == "COMPLETED"

    entry = validate_success(
        api.create_workpaper_entry(
            scenario["report_id"],
            reclassification_payload(
                [
                    workpaper_leg(scenario["cc_ag"], -5000000),
                    workpaper_leg(scenario["cc_routine"], 5000000),
                ],
                code="A-6-1",
                description="Move dietary overhead",
            ),
            scenario["analyst"],
        ),
        201,
    )

    assert_workpaper_entry(entry)
    assert entry["status"] == "ACTIVE"
    assert entry["entry_type"] == "RECLASSIFICATION"
    assert entry["source"] == "MANUAL"
    assert entry["is_non_allowable"] is False

    allocator = read_cost_center(api, scenario, scenario["cc_ag"])
    assert_money_equals(
        allocator["reclassified_amount_cents"],
        -5000000,
        "00100 reclassified_amount_cents",
    )
    assert_money_equals(
        allocator["post_reclass_direct_cost_cents"],
        95000000,
        "00100 post_reclass_direct_cost_cents",
    )

    receiver = read_cost_center(api, scenario, scenario["cc_routine"])
    assert_money_equals(
        receiver["reclassified_amount_cents"], 5000000, "03000 reclassified_amount_cents"
    )
    assert_money_equals(
        receiver["post_reclass_direct_cost_cents"],
        205000000,
        "03000 post_reclass_direct_cost_cents",
    )

    reread_run = validate_success(
        api.get_stepdown_run(run["id"], scenario["analyst"])
    )
    assert reread_run["status"] == "STALE"
    assert reread_run["stale_reason"] == "WORKPAPER_ENTRY_CHANGED"

    assert read_cost_report(api, scenario)["allocation_status"] == "STALE"


def test_a_non_allowable_adjustment_may_not_add_cost(api):
    """Marking an A-8 entry non-allowable forces every leg strictly negative, so a
    +1000000 leg is refused even though adjustments skip the net-zero test.

    PRD 3.3: "When it is set to true, every leg's `amount_cents` must be strictly less than zero; a non-negative leg amount on such an entry is rejected with `ERR_NON_ALLOWABLE_MUST_BE_NEGATIVE`."

    PRD 3.3: "An `ADJUSTMENT` must have exactly one leg and is exempt from the net-zero test entirely, because adding or removing cost is the whole point of an A-8 adjustment."

    Design: Corner/validations/non_allowable_adjustment_with_a_positive_leg_is_rejected
    """
    scenario = _single_routine_center_report(api)

    response = api.create_workpaper_entry(
        scenario["report_id"],
        adjustment_payload(
            [workpaper_leg(scenario["cc_routine"], 1000000)],
            code="A-8-2",
            description="Remove non-allowable advertising",
            is_non_allowable=True,
        ),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_NON_ALLOWABLE_MUST_BE_NEGATIVE.value, 422)

    center = read_cost_center(api, scenario, scenario["cc_routine"])
    assert_cost_center(center)
    assert_money_equals(
        center["adjustment_amount_cents"], 0, "adjustment_amount_cents"
    )
    assert_money_equals(
        center["post_adjustment_cost_cents"], 200000000, "post_adjustment_cost_cents"
    )

    entries, meta = validate_paginated(
        api.list_report_workpaper_entries(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert entries == []


def test_a_worksheet_code_may_not_be_reused_within_one_report(api):
    """A second 03000 under the same report is refused even with a different name,
    type and statistic, and only the original center survives.

    PRD 3.2: "A center is created with a worksheet line `code` (exactly five characters, digits only, and unique within the report — a reused code is rejected with `ERR_COST_CENTER_CODE_DUPLICATE`), a human-readable `name`, and a `center_type` of `GENERAL_SERVICE`, `ANCILLARY`, `ROUTINE` or `NONREIMBURSABLE`."

    Design: Corner/validations/duplicate_cost_center_code_in_the_same_report_is_rejected
    """
    scenario = new_scenario(api)
    add_cost_center(
        api,
        scenario,
        "cc_routine",
        {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}},
    )

    response = api.create_cost_center(
        scenario["report_id"],
        cost_center_payload(
            code="03000",
            name="Adults and Pediatrics duplicate",
            center_type="ANCILLARY",
            statistics={"SQUARE_FEET": 500},
        ),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_COST_CENTER_CODE_DUPLICATE.value, 422)

    centers, meta = validate_paginated(
        api.list_report_cost_centers(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 1
    assert len(centers) == 1
    assert centers[0]["id"] == scenario["cc_routine"]


def test_an_allocation_needs_a_general_service_center_to_step_down_from(api):
    """With a fully mapped ledger but no overhead center there is nothing to
    allocate, so the structural refusal wins and no run row is kept.

    PRD 3.4: "The report must contain at least one `GENERAL_SERVICE` cost center and at least one cost center whose `center_type` is `ROUTINE` or `ANCILLARY`, else the request is rejected with `ERR_STEPDOWN_STRUCTURE_INCOMPLETE`."

    Design: Corner/validations/stepdown_run_without_a_general_service_center_is_rejected
    """
    scenario = _single_routine_center_report(api)
    report = read_cost_report(api, scenario)
    assert_money_equals(report["unmapped_tb_total_cents"], 0, "unmapped_tb_total_cents")

    response = api.create_stepdown_run(
        scenario["report_id"],
        stepdown_run_payload(report["version"], method="SINGLE_APPORTIONMENT"),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_STEPDOWN_STRUCTURE_INCOMPLETE.value, 422)

    after = read_cost_report(api, scenario)
    assert_money_equals(after["unmapped_tb_total_cents"], 0, "unmapped_tb_total_cents")
    assert after["allocation_status"] == "NOT_RUN"

    runs, meta = validate_paginated(
        api.list_report_stepdown_runs(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert runs == []


def test_a_nursing_category_may_be_surveyed_only_once(api):
    """A second RN row on the same survey is refused, so the staffed-category count
    stays at 1 and the reported hours stay at the first row's 1200000.00.

    PRD 3.5: "The `category` is one of `RN`, `LPN`, `NURSE_AIDE`, `MEDICAL_ASSISTANT` or `NURSE_PRACTITIONER` and must be unique within the submission identified by `wage_index_submission_id`; a repeat category is rejected with `ERR_OCC_MIX_CATEGORY_DUPLICATE`."

    Design: Corner/validations/duplicate_occupational_mix_category_is_rejected
    """
    scenario = new_scenario(api)
    submission = validate_success(
        api.create_wage_index_submission(
            scenario["report_id"], dict(MINIMAL_SURVEY_INPUTS), scenario["analyst"]
        ),
        201,
    )
    validate_success(
        api.create_occ_mix_response(
            submission["id"],
            occ_mix_response_payload(
                category="RN",
                reported_hours=1200000.00,
                reported_salaries_cents=4200000000,
            ),
            scenario["analyst"],
        ),
        201,
    )

    response = api.create_occ_mix_response(
        submission["id"],
        occ_mix_response_payload(
            category="RN", reported_hours=100000.00, reported_salaries_cents=350000000
        ),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_OCC_MIX_CATEGORY_DUPLICATE.value, 422)

    reread = validate_success(
        api.get_wage_index_submission(submission["id"], scenario["analyst"])
    )
    assert reread["occ_mix_category_count"] == 1
    assert reread["reported_hours_total"] == 1200000.00

    responses, meta = validate_paginated(
        api.list_occ_mix_responses(submission["id"], scenario["analyst"])
    )
    assert meta["total_count"] == 1
    assert len(responses) == 1


def test_a_report_carries_at_most_one_live_wage_index_submission(api):
    """A DRAFT survey already occupies the report's single live slot, so the second
    creation is refused and the first one's figures are untouched.

    PRD 3.5: "At most one submission with a `status` other than `REJECTED` may exist per report, and a second one is rejected with `ERR_DUPLICATE_CHILD_RECORD`."

    Design: Corner/validations/a_second_live_wage_index_submission_is_rejected
    """
    scenario = new_scenario(api)
    first = validate_success(
        api.create_wage_index_submission(
            scenario["report_id"], dict(MINIMAL_SURVEY_INPUTS), scenario["analyst"]
        ),
        201,
    )
    assert first["status"] == "DRAFT"

    response = api.create_wage_index_submission(
        scenario["report_id"],
        {"total_salaries_cents": 6000000000, "total_paid_hours": 2400000.00},
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_CHILD_RECORD.value, 422)

    submissions, meta = validate_paginated(
        api.list_report_wage_index_submissions(
            scenario["report_id"], scenario["analyst"]
        )
    )
    assert meta["total_count"] == 1
    assert len(submissions) == 1

    reread = validate_success(
        api.get_wage_index_submission(first["id"], scenario["analyst"])
    )
    assert_money_equals(
        reread["total_salaries_cents"], 5000000000, "total_salaries_cents"
    )
    assert reread["total_paid_hours"] == 2000000.00


def test_a_period_that_ends_before_it_begins_fails_on_the_fiscal_band(api):
    """Both dates parse cleanly, so the refusal is the fiscal viability band's 422
    rather than a schema complaint, and no report is opened.

    PRD 3.1: "The period must be well formed — the begin date strictly earlier than the end date, and the span from begin to end no shorter than 1 day and no longer than 366 days — and a period that fails either test is rejected with `ERR_FISCAL_PERIOD_INVALID`."

    Design: Corner/validations/fiscal_period_ending_before_it_begins_is_rejected
    """
    set_clock(api)
    provider = create_provider(api)

    response = api.create_cost_report(
        {
            "provider_id": provider["id"],
            "fiscal_year_begin": "2026-06-30",
            "fiscal_year_end": "2025-07-01",
        },
        SYSTEM_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_FISCAL_PERIOD_INVALID.value, 422)

    reports, meta = validate_paginated(
        api.list_cost_reports(SYSTEM_ADMIN_HEADERS, {"provider_id": provider["id"]})
    )
    assert meta["total_count"] == 0
    assert reports == []


def test_an_unpermitted_role_is_refused_before_the_body_is_inspected(api):
    """Registration belongs to the operator alone, so an analyst's attempt is a 403
    even with the required certification number missing from the body.

    PRD 2.10: "**Authorization by role** — the caller's role appears in the endpoint's permitted set, else `ERR_FORBIDDEN_ROLE` (403)."

    PRD 2.10: "All validation on a request is evaluated in a strict ascending priority order, and **the first violated rule decides the response; nothing is written**."

    Design: Corner/validations/provider_create_by_an_analyst_returns_forbidden_before_the_schema_check
    """
    set_clock(api)

    response = api.create_provider(
        {"name": "Mercy General Hospital", "cbsa_code": "19100"}, ANALYST_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    providers, meta = validate_paginated(api.list_providers(SYSTEM_ADMIN_HEADERS))
    assert meta["total_count"] == 0
    assert providers == []
