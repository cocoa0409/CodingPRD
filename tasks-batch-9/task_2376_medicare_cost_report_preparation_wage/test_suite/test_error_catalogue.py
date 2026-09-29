"""Every catalogued refusal reached through the shortest legitimate path: the
per-entity 404s, the body-foreign-key 404, and the compliance-window, business
and fiscal-viability bands that guard filing, settlement, appeal and rate reset."""

from test_helpers import (
    AUDITOR_HEADERS,
    CANONICAL_OCC_MIX,
    SYSTEM_ADMIN_HEADERS,
    ApiErrorId,
    assert_fte_equals,
    assert_money_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    appeal_case_payload,
    appeal_decision_payload,
    cost_center_payload,
    interim_rate_request_payload,
    review_decision_payload,
    rotation_assignment_payload,
    settlement_payload,
    stepdown_run_payload,
)
from test_helpers.fixtures import (
    CENTER_AG,
    CENTER_ROUTINE,
    accept_wage_submission,
    add_cost_center,
    add_mapped_tb_line,
    add_ucc_data_set,
    add_unmapped_tb_line,
    add_wage_submission,
    create_appeal_case,
    create_cost_report,
    create_other_provider,
    create_provider,
    create_resident,
    create_settlement,
    file_report,
    new_scenario,
    propose_audit_adjustment,
    read_cost_report,
    read_provider,
    role_headers_for,
    run_stepdown,
    set_clock,
    setup_two_center_report,
    start_wage_review,
    submit_wage_submission,
)
from test_helpers.test_users import AUDITOR_ONE_ID

UNRESOLVABLE_IDS = {
    "provider": "00000000-0000-0000-0000-0000000000a1",
    "trial_balance_line": "00000000-0000-0000-0000-0000000000a2",
    "workpaper_entry": "00000000-0000-0000-0000-0000000000a3",
    "stepdown_run": "00000000-0000-0000-0000-0000000000a4",
    "wage_index_submission": "00000000-0000-0000-0000-0000000000a5",
    "occ_mix_response": "00000000-0000-0000-0000-0000000000a6",
    "resident": "00000000-0000-0000-0000-0000000000a7",
    "rotation_assignment": "00000000-0000-0000-0000-0000000000a8",
    "ucc_data_set": "00000000-0000-0000-0000-0000000000a9",
    "settlement": "00000000-0000-0000-0000-0000000000aa",
    "audit_adjustment": "00000000-0000-0000-0000-0000000000ab",
    "appeal_case": "00000000-0000-0000-0000-0000000000ac",
    "interim_rate_request": "00000000-0000-0000-0000-0000000000ad",
}

UNKNOWN_PROVIDER_ID = "00000000-0000-0000-0000-0000000000b1"


def _two_center_report_ready_to_file(api, **kwargs):
    """The two-center report with every filing precondition satisfied."""
    scenario = setup_two_center_report(api, **kwargs)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    accept_wage_submission(api, scenario)
    add_ucc_data_set(api, scenario)
    return scenario


def _two_center_tentative_settlement(api, **kwargs):
    scenario = _two_center_report_ready_to_file(api, **kwargs)
    file_report(api, scenario)
    create_settlement(api, scenario, "TENTATIVE")
    return scenario


def _two_center_final_settlement(api, **kwargs):
    """A FINAL_SETTLED two-center report: 600000 per discharge, 32300000 due."""
    scenario = _two_center_tentative_settlement(api, **kwargs)
    run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")
    create_settlement(api, scenario, "FINAL")
    return scenario


def test_each_single_resource_read_answers_with_its_own_not_found_code(api):
    """Thirteen unresolvable identifiers produce thirteen distinct 404 codes, one
    named for each entity rather than a single shared generic.

    PRD 2.10: "The per-entity 404 codes are `ERR_PROVIDER_NOT_FOUND`, `ERR_COST_REPORT_NOT_FOUND`, `ERR_COST_CENTER_NOT_FOUND`, `ERR_TRIAL_BALANCE_LINE_NOT_FOUND`, `ERR_WORKPAPER_ENTRY_NOT_FOUND`, `ERR_STEPDOWN_RUN_NOT_FOUND`, `ERR_WAGE_INDEX_SUBMISSION_NOT_FOUND`, `ERR_OCC_MIX_RESPONSE_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_ROTATION_ASSIGNMENT_NOT_FOUND`, `ERR_UCC_DATA_SET_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_AUDIT_ADJUSTMENT_NOT_FOUND`, `ERR_APPEAL_CASE_NOT_FOUND` and `ERR_INTERIM_RATE_REQUEST_NOT_FOUND`."

    Design: Corner/errors/every_entity_read_maps_its_own_not_found_error_id
    """
    set_clock(api)

    validate_error(
        api.get_provider(UNRESOLVABLE_IDS["provider"], AUDITOR_HEADERS),
        ApiErrorId.ERR_PROVIDER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_trial_balance_line(
            UNRESOLVABLE_IDS["trial_balance_line"], AUDITOR_HEADERS
        ),
        ApiErrorId.ERR_TRIAL_BALANCE_LINE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_workpaper_entry(UNRESOLVABLE_IDS["workpaper_entry"], AUDITOR_HEADERS),
        ApiErrorId.ERR_WORKPAPER_ENTRY_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_stepdown_run(UNRESOLVABLE_IDS["stepdown_run"], AUDITOR_HEADERS),
        ApiErrorId.ERR_STEPDOWN_RUN_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_wage_index_submission(
            UNRESOLVABLE_IDS["wage_index_submission"], AUDITOR_HEADERS
        ),
        ApiErrorId.ERR_WAGE_INDEX_SUBMISSION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_occ_mix_response(UNRESOLVABLE_IDS["occ_mix_response"], AUDITOR_HEADERS),
        ApiErrorId.ERR_OCC_MIX_RESPONSE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_resident(UNRESOLVABLE_IDS["resident"], AUDITOR_HEADERS),
        ApiErrorId.ERR_RESIDENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_rotation_assignment(
            UNRESOLVABLE_IDS["rotation_assignment"], AUDITOR_HEADERS
        ),
        ApiErrorId.ERR_ROTATION_ASSIGNMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_ucc_data_set(UNRESOLVABLE_IDS["ucc_data_set"], AUDITOR_HEADERS),
        ApiErrorId.ERR_UCC_DATA_SET_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_settlement(UNRESOLVABLE_IDS["settlement"], AUDITOR_HEADERS),
        ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_audit_adjustment(UNRESOLVABLE_IDS["audit_adjustment"], AUDITOR_HEADERS),
        ApiErrorId.ERR_AUDIT_ADJUSTMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_appeal_case(UNRESOLVABLE_IDS["appeal_case"], AUDITOR_HEADERS),
        ApiErrorId.ERR_APPEAL_CASE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_interim_rate_request(
            UNRESOLVABLE_IDS["interim_rate_request"], AUDITOR_HEADERS
        ),
        ApiErrorId.ERR_INTERIM_RATE_REQUEST_NOT_FOUND.value,
        404,
    )


def test_an_unresolvable_provider_in_the_body_is_a_referenced_entity_failure(api):
    """The provider identifier travels in the body, not the path, so the refusal is
    the generic body-foreign-key 404 and no report is opened.

    PRD 2.10: "A foreign key supplied in a request *body* that does not resolve produces the generic `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404) instead; this applies when opening a cost report, mapping a trial balance line, creating a workpaper entry, creating a rotation assignment, proposing an audit adjustment, opening an appeal case, and creating an interim rate request."

    Design: Corner/errors/cost_report_for_an_unknown_provider_is_not_found
    """
    set_clock(api)

    response = api.create_cost_report(
        {
            "provider_id": UNKNOWN_PROVIDER_ID,
            "fiscal_year_begin": "2025-07-01",
            "fiscal_year_end": "2026-06-30",
        },
        SYSTEM_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value, 404)

    reports, meta = validate_paginated(api.list_cost_reports(SYSTEM_ADMIN_HEADERS))
    assert meta["total_count"] == 0
    assert reports == []


def test_an_allocation_order_on_a_receiving_center_is_refused(api):
    """The order/basis pair belongs to overhead pools alone, so a ROUTINE center
    carrying stepdown_order 2 is refused and no center is stored.

    PRD 3.2: "At creation, a `GENERAL_SERVICE` center must supply an `allocation_basis` other than `NONE` and a `stepdown_order` that no other general service center of the report already holds, and a center of any other type must supply neither field; every violation of that shape — a missing basis, a missing order, a duplicate order, or either field present on a non-general-service center — is rejected with `ERR_STEPDOWN_ORDER_CONFLICT`."

    Design: Corner/errors/stepdown_order_on_a_routine_cost_center_is_rejected
    """
    scenario = new_scenario(api)

    response = api.create_cost_center(
        scenario["report_id"],
        cost_center_payload(stepdown_order=2, statistics={"SQUARE_FEET": 3000}),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_STEPDOWN_ORDER_CONFLICT.value, 422)

    centers, meta = validate_paginated(
        api.list_report_cost_centers(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert centers == []


def test_a_rotation_missing_the_fiscal_year_entirely_is_refused(api):
    """A 2027 rotation intersects the 2025-07-01..2026-06-30 period on no day at
    all, so it is refused and no FTE day is counted anywhere.

    PRD 3.6: "And the rotation must actually intersect the cost report's fiscal year, meaning its computed `overlap_days` must be strictly greater than zero, else `ERR_ROTATION_OUTSIDE_FISCAL_YEAR`."

    Design: Corner/errors/rotation_entirely_outside_the_fiscal_year_is_rejected
    """
    scenario = new_scenario(api)
    add_cost_center(
        api, scenario, "cc_routine", {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}}
    )
    resident = create_resident(api, scenario)

    response = api.create_rotation_assignment(
        resident["id"],
        rotation_assignment_payload(
            scenario["cc_routine"],
            start_date="2027-01-01",
            end_date="2027-02-01",
            fte_fraction=0.5000,
        ),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_ROTATION_OUTSIDE_FISCAL_YEAR.value, 409)

    reread = validate_success(api.get_resident(resident["id"], scenario["analyst"]))
    assert_fte_equals(reread["assigned_fte_days"], 0.0000, "assigned_fte_days")

    report = read_cost_report(api, scenario)
    assert_fte_equals(
        report["unweighted_fte_days_total"], 0.0000, "unweighted_fte_days_total"
    )

    rotations, meta = validate_paginated(
        api.list_rotation_assignments(
            scenario["analyst"], {"resident_id": resident["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rotations == []


def test_acceptance_needs_three_staffed_categories(api):
    """Two staffed categories clear submission and review start but not the accept
    decision, so the survey stays under review with no weighted wage.

    PRD 3.5: "`ACCEPT` advances the submission to `ACCEPTED`, and requires both that `occ_mix_category_count` be at least 3 — fewer than three staffed categories is rejected with `ERR_OCC_MIX_INCOMPLETE` — and that `reported_hours_total` not exceed `total_paid_hours`; it sets `review_note`, sets the report's `wage_data_status` to `VERIFIED`, and increments the report's `version`."

    PRD 3.5: "When `occ_mix_category_count` is fewer than 3, `occ_mix_adjusted_ahw_cents` is null and no weighting is attempted."

    Design: Corner/errors/accepting_a_submission_with_two_categories_is_rejected
    """
    scenario = new_scenario(api)
    add_wage_submission(api, scenario, occ_mix=CANONICAL_OCC_MIX[:2])
    submit_wage_submission(api, scenario)
    start_wage_review(api, scenario)

    response = api.record_wage_index_review_decision(
        scenario["submission_id"],
        review_decision_payload(decision="ACCEPT", review_note="Desk review complete"),
        scenario["auditor"],
    )

    validate_error(response, ApiErrorId.ERR_OCC_MIX_INCOMPLETE.value, 422)

    submission = validate_success(
        api.get_wage_index_submission(scenario["submission_id"], scenario["analyst"])
    )
    assert submission["occ_mix_category_count"] == 2
    assert submission["status"] == "UNDER_REVIEW"
    assert submission["occ_mix_adjusted_ahw_cents"] is None

    assert read_cost_report(api, scenario)["wage_data_status"] == "UNDER_REVIEW"


def test_a_projection_needs_a_finally_settled_basis_period(api):
    """A DRAFT basis report has never had its cost per discharge stamped, so the
    rate request is refused and nothing is stored.

    PRD 3.9: "The basis report's `status` must be `FINAL_SETTLED`, so that its `allowable_cost_per_discharge_cents` has actually been stamped, else `ERR_BASIS_REPORT_NOT_FINAL_SETTLED`."

    Design: Corner/errors/interim_rate_request_on_a_draft_basis_report_is_rejected
    """
    scenario = new_scenario(api)
    provider = read_provider(api, scenario)

    response = api.create_interim_rate_request(
        interim_rate_request_payload(
            scenario["provider_id"],
            scenario["report_id"],
            provider["version"],
            trend_factor=0.3000,
            effective_to="2027-03-31",
        ),
        scenario["manager"],
    )

    validate_error(response, ApiErrorId.ERR_BASIS_REPORT_NOT_FINAL_SETTLED.value, 422)

    report = read_cost_report(api, scenario)
    assert report["status"] == "DRAFT"
    assert_money_equals(
        report["allowable_cost_per_discharge_cents"],
        0,
        "allowable_cost_per_discharge_cents",
    )

    requests, meta = validate_paginated(
        api.list_interim_rate_requests(
            scenario["manager"], {"provider_id": scenario["provider_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert requests == []


def test_a_projection_may_not_be_built_on_another_hospitals_period(api):
    """The basis report belongs to the second hospital, so the ownership band fires
    ahead of the settlement-status band that the same report also fails.

    PRD 3.9: "The basis report must belong to the named provider, else `ERR_BASIS_REPORT_FOREIGN_TO_PROVIDER`."

    Design: Corner/errors/interim_rate_request_naming_another_providers_basis_report_is_rejected
    """
    set_clock(api)
    provider = create_provider(api)
    other_provider = create_other_provider(api)
    foreign_report = create_cost_report(api, other_provider["id"])
    manager = role_headers_for(provider["id"])["manager"]

    response = api.create_interim_rate_request(
        interim_rate_request_payload(
            provider["id"],
            foreign_report["id"],
            provider["version"],
            trend_factor=0.3000,
            effective_to="2027-03-31",
        ),
        manager,
    )

    validate_error(response, ApiErrorId.ERR_BASIS_REPORT_FOREIGN_TO_PROVIDER.value, 422)

    requests, meta = validate_paginated(
        api.list_interim_rate_requests(manager, {"provider_id": provider["id"]})
    )
    assert meta["total_count"] == 0
    assert requests == []

    assert validate_success(api.get_provider(provider["id"], manager))["version"] == 1


def test_the_accounting_tree_freezes_once_the_report_is_filed(api):
    """FILED is not an editable status, so a new cost center is refused and the
    report keeps exactly the two centers it was filed with.

    PRD 2.6: "The report's accounting children may only be created, mapped, revised, reversed or voided while `status` is `DRAFT` or `REOPENED`; in any other status the attempt is rejected with `ERR_COST_REPORT_NOT_EDITABLE` (HTTP 409)."

    PRD 2.6: "This gate guards eleven operations: creating a cost center, revising a cost center, loading a trial balance line, mapping a trial balance line, creating a workpaper entry, reversing a workpaper entry, creating a rotation assignment, voiding a rotation assignment, opening a wage index submission, correcting a wage index submission's hours and salary figures, and creating the uncompensated care data set."

    Design: Corner/errors/adding_a_cost_center_to_a_filed_report_is_rejected
    """
    scenario = _two_center_report_ready_to_file(api)
    file_report(api, scenario)

    response = api.create_cost_center(
        scenario["report_id"],
        cost_center_payload(
            code="04000",
            name="Intensive Care Unit",
            center_type="ROUTINE",
            statistics={"SQUARE_FEET": 800},
        ),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_COST_REPORT_NOT_EDITABLE.value, 409)

    assert read_cost_report(api, scenario)["status"] == "FILED"

    centers, meta = validate_paginated(
        api.list_report_cost_centers(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 2
    assert len(centers) == 2


def test_filing_needs_an_uncompensated_care_data_set(api):
    """Three of the four readiness conditions are met; the missing care data set
    alone blocks the filing and the report stays unstamped.

    PRD 3.1: "And exactly one uncompensated care data set must exist for the report, else `ERR_UCC_DATA_MISSING`."

    Design: Corner/errors/filing_without_an_uncompensated_care_data_set_is_rejected
    """
    scenario = setup_two_center_report(api)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    accept_wage_submission(api, scenario)

    response = api.file_cost_report(scenario["report_id"], scenario["manager"])

    validate_error(response, ApiErrorId.ERR_UCC_DATA_MISSING.value, 422)

    report = read_cost_report(api, scenario)
    assert report["status"] == "DRAFT"
    assert report["filed_at"] is None
    assert report["wage_data_status"] == "VERIFIED"
    assert report["allocation_status"] == "CURRENT"

    data_sets, meta = validate_paginated(
        api.list_report_ucc_data_sets(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert data_sets == []


def test_an_open_audit_exception_blocks_the_final_settlement(api):
    """The double-pass basis is in place and current, but the unresolved exception
    holds the report at the tentative stage.

    PRD 3.8: "The `TENTATIVE_SETTLED` path to `FINAL_SETTLED` demands three further things: that a settlement with `stage` `TENTATIVE` and `status` `ISSUED` exist; that the report's `COMPLETED` stepdown run have `method` `DOUBLE_APPORTIONMENT`, since a single-pass allocation is not an acceptable basis for a final settlement and a request made against one is rejected with `ERR_FINAL_REQUIRES_DOUBLE_APPORTIONMENT`; and that no audit adjustment of the tentative settlement remain in `PROPOSED`, `ACCEPTED_BY_PROVIDER` or `PROTESTED`, else `ERR_AUDIT_ADJUSTMENT_UNRESOLVED`."

    Design: Corner/errors/final_settlement_with_an_open_audit_exception_is_rejected
    """
    scenario = _two_center_tentative_settlement(api)
    adjustment = propose_audit_adjustment(api, scenario, target_key="cc_routine")
    run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")

    response = api.create_settlement(
        scenario["report_id"], settlement_payload("FINAL"), scenario["auditor"]
    )

    validate_error(response, ApiErrorId.ERR_AUDIT_ADJUSTMENT_UNRESOLVED.value, 422)

    reread = validate_success(
        api.get_audit_adjustment(adjustment["id"], scenario["auditor"])
    )
    assert reread["status"] == "PROPOSED"
    assert reread["proposed_by_user_id"] == AUDITOR_ONE_ID

    report = read_cost_report(api, scenario)
    assert report["status"] == "TENTATIVE_SETTLED"
    assert report["allocation_status"] == "CURRENT"

    finals, meta = validate_paginated(
        api.list_report_settlements(
            scenario["report_id"], scenario["auditor"], {"stage": "FINAL"}
        )
    )
    assert meta["total_count"] == 0
    assert finals == []


def test_a_board_appeal_below_the_statutory_floor_is_refused(api):
    """500000 cents is under the ten-thousand-dollar floor, and because the floor
    is a business rule the answer is a 422 rather than a schema complaint.

    PRD 3.9: "That minimum is a business rule and not a schema bound, so a board appeal naming 500,000 cents is a 422 on `ERR_PRRB_AMOUNT_BELOW_MINIMUM`, never a 400."

    Design: Corner/errors/prrb_appeal_below_the_statutory_minimum_is_rejected
    """
    scenario = _two_center_final_settlement(api)
    final_settlement = scenario["final_settlement"]

    response = api.create_appeal_case(
        scenario["report_id"],
        appeal_case_payload(
            final_settlement["id"],
            kind="PRRB_APPEAL",
            issue_description="Disagree with the agency-labor disallowance",
            amount_at_issue_cents=500000,
        ),
        scenario["manager"],
    )

    validate_error(response, ApiErrorId.ERR_PRRB_AMOUNT_BELOW_MINIMUM.value, 422)

    reread = validate_success(
        api.get_settlement(final_settlement["id"], scenario["auditor"])
    )
    assert reread["stage"] == "FINAL"
    assert_money_equals(
        reread["amount_due_provider_cents"], 32300000, "amount_due_provider_cents"
    )

    assert read_cost_report(api, scenario)["status"] == "FINAL_SETTLED"

    cases, meta = validate_paginated(
        api.list_appeal_cases(
            scenario["manager"], {"cost_report_id": scenario["report_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert cases == []


def test_a_board_appeal_filed_after_one_hundred_eighty_days_is_refused(api):
    """The clock stands 212 days past the final settlement, so the window band
    refuses an otherwise fully qualified appeal.

    PRD 3.9: "A board appeal carries two extra requirements: it must be opened within 180 days of the final settlement's `issued_at`, else `ERR_APPEAL_WINDOW_EXPIRED`, and its `amount_at_issue_cents` must be at least 1,000,000 cents — ten thousand dollars in controversy — else `ERR_PRRB_AMOUNT_BELOW_MINIMUM`."

    Design: Corner/errors/prrb_appeal_filed_after_the_one_hundred_eighty_day_window_is_rejected
    """
    scenario = _two_center_final_settlement(api)
    final_settlement = scenario["final_settlement"]
    set_clock(api, "2027-03-01T00:00:00Z")

    response = api.create_appeal_case(
        scenario["report_id"],
        appeal_case_payload(
            final_settlement["id"],
            kind="PRRB_APPEAL",
            issue_description="Disagree with the agency-labor disallowance",
            amount_at_issue_cents=5000000,
        ),
        scenario["manager"],
    )

    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED.value, 422)

    reread = validate_success(
        api.get_settlement(final_settlement["id"], scenario["auditor"])
    )
    assert reread["stage"] == "FINAL"
    assert read_cost_report(api, scenario)["status"] == "FINAL_SETTLED"

    cases, meta = validate_paginated(
        api.list_appeal_cases(
            scenario["manager"], {"cost_report_id": scenario["report_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert cases == []


def test_a_reopening_granted_past_three_years_is_refused(api):
    """Recording the reopening request is always allowed, but granting it once the
    three-year window has closed is not, and the case stays requested.

    PRD 3.9: "From `REQUESTED` on a case of `kind` `REOPENING`, `GRANT` advances the case to `GRANTED`; it requires that the referenced settlement have `stage` `FINAL` and `status` either `ISSUED` or `APPEALED`, and that the logical clock's date fall on or before three years after that settlement's `issued_at` date, else `ERR_REOPENING_WINDOW_EXPIRED`."

    Design: Corner/errors/reopening_granted_after_three_years_is_rejected
    """
    scenario = _two_center_final_settlement(api)
    case = create_appeal_case(
        api,
        scenario,
        settlement_id=scenario["final_settlement_id"],
        kind="REOPENING",
        issue_description="Reopening sought for the corrected square footage",
        amount_at_issue_cents=2500000,
    )
    assert case["status"] == "REQUESTED"
    set_clock(api, "2029-09-01T00:00:00Z")

    response = api.decide_appeal_case(
        case["id"],
        appeal_decision_payload(
            outcome="GRANT",
            decision_note="Reopening granted for the statistic correction",
        ),
        scenario["auditor"],
    )

    validate_error(response, ApiErrorId.ERR_REOPENING_WINDOW_EXPIRED.value, 422)

    reread = validate_success(api.get_appeal_case(case["id"], scenario["manager"]))
    assert reread["status"] == "REQUESTED"
    assert reread["decided_at"] is None

    report = read_cost_report(api, scenario)
    assert report["status"] == "FINAL_SETTLED"
    assert report["allocation_status"] == "CURRENT"


def test_a_stale_allocation_blocks_the_filing(api):
    """Revising a receiving center's statistic after the run demotes the allocation,
    and the filing is refused on freshness alone.

    PRD 3.1: "Its `allocation_status` must be `CURRENT`, else `ERR_ALLOCATION_NOT_CURRENT`."

    PRD 3.2: "Every revision demotes each `COMPLETED` stepdown run of the report to `STALE` with `stale_reason` `COST_CENTER_INPUT_CHANGED`, sets the report's `allocation_status` to `STALE`, and increments the report's `version`."

    Design: Corner/errors/filing_with_a_stale_allocation_is_rejected
    """
    scenario = _two_center_report_ready_to_file(api)
    validate_success(
        api.update_cost_center(
            scenario["cc_routine"],
            {"statistics": {"SQUARE_FEET": 3500}},
            scenario["analyst"],
        )
    )

    response = api.file_cost_report(scenario["report_id"], scenario["manager"])

    validate_error(response, ApiErrorId.ERR_ALLOCATION_NOT_CURRENT.value, 422)

    report = read_cost_report(api, scenario)
    assert report["allocation_status"] == "STALE"
    assert_money_equals(report["unmapped_tb_total_cents"], 0, "unmapped_tb_total_cents")
    assert report["wage_data_status"] == "VERIFIED"
    assert report["status"] == "DRAFT"
    assert report["filed_at"] is None


def test_a_rate_reset_needs_a_standing_rate_to_measure_against(api):
    """With the standing rate at 0 there is no denominator for the variance, so the
    request is refused before any arithmetic is attempted.

    PRD 3.9: "And the provider's `current_interim_rate_cents` must be strictly greater than zero, since a variance cannot be measured against a rate of zero, else `ERR_NO_CURRENT_INTERIM_RATE`."

    Design: Corner/errors/interim_rate_request_for_a_provider_with_no_current_rate_is_rejected
    """
    scenario = _two_center_final_settlement(
        api, provider_overrides={"current_interim_rate_cents": 0}
    )
    provider = read_provider(api, scenario)
    assert_money_equals(
        provider["current_interim_rate_cents"], 0, "current_interim_rate_cents"
    )

    response = api.create_interim_rate_request(
        interim_rate_request_payload(
            scenario["provider_id"],
            scenario["report_id"],
            provider["version"],
            trend_factor=0.3000,
            effective_to="2027-03-31",
        ),
        scenario["manager"],
    )

    validate_error(response, ApiErrorId.ERR_NO_CURRENT_INTERIM_RATE.value, 422)

    reread = read_provider(api, scenario)
    assert_money_equals(
        reread["current_interim_rate_cents"], 0, "current_interim_rate_cents"
    )
    assert reread["version"] == 1

    report = read_cost_report(api, scenario)
    assert report["status"] == "FINAL_SETTLED"
    assert_money_equals(
        report["allowable_cost_per_discharge_cents"],
        600000,
        "allowable_cost_per_discharge_cents",
    )

    requests, meta = validate_paginated(
        api.list_interim_rate_requests(
            scenario["manager"], {"provider_id": scenario["provider_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert requests == []


def test_a_swing_of_under_ten_percent_is_not_worth_a_rate_change(api):
    """600000 trended by 0.4000 projects 840000 against a standing 900000, a 0.0667
    swing that falls inside the band, so the request is refused unstored.

    PRD 3.9: "Third, the eligibility gate is applied to that pre-cap variance: a `variance_ratio` below 0.1000 — a swing of less than ten percent — is not worth a rate change and the request is rejected with `ERR_INTERIM_VARIANCE_BELOW_THRESHOLD`."

    PRD 3.9: "First, `projected_cost_per_discharge_cents` is the basis report's `allowable_cost_per_discharge_cents` multiplied by one plus `trend_factor`, rounded half up to a whole cent — this is the *uncapped* projection."

    Design: Corner/errors/interim_rate_request_inside_the_variance_band_is_rejected
    """
    scenario = _two_center_final_settlement(api)
    provider = read_provider(api, scenario)
    assert_money_equals(
        provider["current_interim_rate_cents"], 900000, "current_interim_rate_cents"
    )
    assert_money_equals(
        read_cost_report(api, scenario)["allowable_cost_per_discharge_cents"],
        600000,
        "allowable_cost_per_discharge_cents",
    )

    response = api.create_interim_rate_request(
        interim_rate_request_payload(
            scenario["provider_id"],
            scenario["report_id"],
            provider["version"],
            trend_factor=0.4000,
            effective_to="2027-03-31",
        ),
        scenario["manager"],
    )

    validate_error(
        response, ApiErrorId.ERR_INTERIM_VARIANCE_BELOW_THRESHOLD.value, 422
    )

    reread = read_provider(api, scenario)
    assert_money_equals(
        reread["current_interim_rate_cents"], 900000, "current_interim_rate_cents"
    )
    assert reread["version"] == 1

    requests, meta = validate_paginated(
        api.list_interim_rate_requests(
            scenario["manager"], {"provider_id": scenario["provider_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert requests == []


def test_an_appeal_may_not_name_a_sibling_reports_settlement(api):
    """The settlement hangs off the settled period, so opening a case on the earlier
    report of the same hospital trips the cross-parent check.

    PRD 3.9: "The named settlement must belong to the same cost report as the case, else `ERR_SETTLEMENT_FOREIGN_TO_REPORT`, and must have `stage` `FINAL`, else `ERR_SETTLEMENT_STAGE_INVALID`."

    Design: Corner/errors/appeal_case_naming_another_reports_settlement_is_rejected
    """
    scenario = _two_center_final_settlement(api)
    prior_report = create_cost_report(
        api,
        scenario["provider_id"],
        fiscal_year_begin="2024-07-01",
        fiscal_year_end="2025-06-30",
    )

    response = api.create_appeal_case(
        prior_report["id"],
        appeal_case_payload(
            scenario["final_settlement_id"],
            kind="REOPENING",
            issue_description="Wage index occupational mix hours misclassified",
            amount_at_issue_cents=2500000,
        ),
        scenario["manager"],
    )

    validate_error(response, ApiErrorId.ERR_SETTLEMENT_FOREIGN_TO_REPORT.value, 422)

    cases, meta = validate_paginated(
        api.list_appeal_cases(scenario["manager"], {"cost_report_id": prior_report["id"]})
    )
    assert meta["total_count"] == 0
    assert cases == []

    reread = validate_success(
        api.get_cost_report(prior_report["id"], scenario["manager"])
    )
    assert reread["status"] == "DRAFT"


def test_an_unassigned_ledger_dollar_blocks_the_allocation(api):
    """The overhead and receiving centers are both present, so the refusal is the
    outstanding 200000000 of unmapped ledger rather than the structure.

    PRD 3.4: "And the report's `unmapped_tb_total_cents` must be exactly 0, else `ERR_UNMAPPED_TRIAL_BALANCE`."

    PRD 3.3: "That last figure is the gate on both filing and stepdown: while any ledger dollar remains unassigned to a cost center, neither operation may proceed, and both reject with `ERR_UNMAPPED_TRIAL_BALANCE`."

    Design: Corner/errors/stepdown_run_with_an_unmapped_ledger_line_is_rejected
    """
    scenario = new_scenario(api)
    add_cost_center(api, scenario, "cc_ag", {**CENTER_AG, "statistics": {"SQUARE_FEET": 0}})
    add_cost_center(
        api, scenario, "cc_routine", {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}}
    )
    add_mapped_tb_line(
        api, scenario, "6000", "Administration salaries", 100000000, "cc_ag"
    )
    pending = add_unmapped_tb_line(
        api, scenario, gl_account="6200", description="Nursing salaries", amount_cents=200000000
    )
    before = read_cost_report(api, scenario)

    response = api.create_stepdown_run(
        scenario["report_id"],
        stepdown_run_payload(before["version"], method="SINGLE_APPORTIONMENT"),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_UNMAPPED_TRIAL_BALANCE.value, 422)

    reread_line = validate_success(
        api.get_trial_balance_line(pending["id"], scenario["analyst"])
    )
    assert reread_line["status"] == "UNMAPPED"

    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["unmapped_tb_total_cents"], 200000000, "unmapped_tb_total_cents"
    )
    assert_money_equals(
        report["total_direct_cost_cents"], 100000000, "total_direct_cost_cents"
    )
    assert report["allocation_status"] == "NOT_RUN"

    runs, meta = validate_paginated(
        api.list_report_stepdown_runs(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert runs == []
