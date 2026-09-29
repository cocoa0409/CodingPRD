"""Endpoint shapes: the registration round trip, the two action endpoints that
move state through a payload of their own, the computed read, the reverse
traversal link, and the child collections a client walks."""

from test_helpers import (
    ANALYST_HEADERS,
    DEFAULT_CLOCK,
    MANAGER_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    assert_fte_equals,
    assert_gme_summary,
    assert_instant_equals,
    assert_money_equals,
    assert_provider,
    assert_trial_balance_line,
    get_success_data,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import provider_payload, review_decision_payload
from test_helpers.fixtures import (
    CENTER_AG,
    CENTER_ROUTINE,
    accept_wage_submission,
    add_cost_center,
    add_mapped_tb_line,
    add_ucc_data_set,
    add_unmapped_tb_line,
    add_wage_submission,
    new_scenario,
    read_cost_center,
    read_cost_report,
    run_stepdown,
    set_clock,
    setup_resident_with_rotation,
    setup_two_center_report,
    start_wage_review,
    submit_wage_submission,
)


def _report_with_every_collection_populated(api):
    """A two-center report carrying a run, an accepted survey and a UCC data set."""
    scenario = setup_two_center_report(api)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    accept_wage_submission(api, scenario)
    add_ucc_data_set(api, scenario)
    return scenario


def test_a_registered_provider_reads_back_and_filters_by_its_certification_number(api):
    """The id handed back by registration reads back field for field at version 1,
    and the ccn filter picks that one row out of the two on file.

    PRD 2.4: "**`version`** (integer): a monotonically increasing counter that begins at 1 and increments by one on every mutation of the row."

    PRD 2.3: "Providers may be filtered by `ccn`, `cbsa_code` and `teaching_status`."

    Design: Corner/endpoints/provider_crud_round_trip_covers_create_read_and_filtered_list
    """
    set_clock(api)
    other = validate_success(
        api.create_provider(
            {
                "ccn": "450999",
                "name": "Northside Community Hospital",
                "cbsa_code": "26420",
                "teaching_status": "NON_TEACHING",
            },
            SYSTEM_ADMIN_HEADERS,
        ),
        201,
    )

    created = validate_success(
        api.create_provider(provider_payload(), SYSTEM_ADMIN_HEADERS), 201
    )
    assert created["id"] != other["id"]

    fetched = validate_success(api.get_provider(created["id"], ANALYST_HEADERS))

    assert_provider(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["version"] == 1
    assert fetched["ccn"] == "450123"
    assert fetched["name"] == "Mercy General Hospital"
    assert fetched["cbsa_code"] == "19100"
    assert fetched["teaching_status"] == "TEACHING"
    assert fetched["fte_cap"] == 2.00
    assert_money_equals(
        fetched["current_interim_rate_cents"], 900000, "current_interim_rate_cents"
    )

    filtered, filtered_meta = validate_paginated(
        api.list_providers(SYSTEM_ADMIN_HEADERS, {"ccn": "450123"})
    )
    assert filtered_meta["total_count"] == 1
    assert len(filtered) == 1
    assert filtered[0]["id"] == created["id"]

    _all_rows, all_meta = validate_paginated(api.list_providers(SYSTEM_ADMIN_HEADERS))
    assert all_meta["total_count"] == 2


def test_the_mapping_action_moves_the_ledger_amount_into_its_new_home(api):
    """Mapping the suspense line carries its whole 200000000 out of the report's
    unmapped balance and into the routine center in one call.

    PRD 3.3: "An unmapped line can be mapped later through a dedicated mapping action that carries a `cost_center_id` in its payload and advances the line from `UNMAPPED` to `MAPPED`; mapping a line that is already `MAPPED` is an `ERR_INVALID_STATE_TRANSITION`."

    PRD 3.3: "Loading a line and mapping a line both trigger the same rollup, which is pure aggregation over integer cents and needs no rounding."

    Design: Corner/endpoints/map_action_endpoint_moves_a_ledger_line_and_reprices_the_center
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
        api,
        scenario,
        gl_account="6200",
        description="Nursing salaries awaiting mapping",
        amount_cents=200000000,
    )
    before = read_cost_report(api, scenario)
    assert_money_equals(
        before["unmapped_tb_total_cents"], 200000000, "unmapped_tb_total_cents"
    )

    mapped = validate_success(
        api.map_trial_balance_line(
            pending["id"], {"cost_center_id": scenario["cc_routine"]}, scenario["analyst"]
        )
    )

    assert_trial_balance_line(mapped)
    assert mapped["status"] == "MAPPED"
    assert mapped["mapped_cost_center_id"] == scenario["cc_routine"]

    receiver = read_cost_center(api, scenario, scenario["cc_routine"])
    assert_money_equals(
        receiver["direct_cost_cents"], 200000000, "03000 direct_cost_cents"
    )

    after = read_cost_report(api, scenario)
    assert_money_equals(
        after["total_direct_cost_cents"], 300000000, "total_direct_cost_cents"
    )
    assert_money_equals(after["unmapped_tb_total_cents"], 0, "unmapped_tb_total_cents")

    lines, meta = validate_paginated(
        api.list_cost_center_trial_balance_lines(
            scenario["cc_routine"], scenario["analyst"]
        )
    )
    assert meta["total_count"] == 1
    assert lines[0]["id"] == pending["id"]


def test_the_gme_summary_read_reports_the_fte_block_without_advancing_the_report(api):
    """A 365-day period holding one 0.6000 rotation over 184 days reads 110.4000
    FTE-days and 0.30 across every derived count, and the report stays DRAFT.

    PRD 3.6: "The summary read returns `cost_report_id`, `period_days`, `unweighted_fte_days_total`, `unweighted_fte_total`, `capped_unweighted_fte`, `weighted_fte_total`, `rolling_average_fte` and `prior_period_count`, the last being the number of prior settled periods actually found (0, 1 or 2)."

    PRD 3.6: "A provider with no settled history therefore divides by 1 and its rolling average equals its own capped count."

    Design: Corner/endpoints/gme_summary_is_a_computed_read_that_stores_nothing
    """
    scenario = setup_resident_with_rotation(api)

    summary = validate_success(
        api.get_gme_summary(scenario["report_id"], scenario["manager"])
    )

    assert_gme_summary(summary)
    assert summary["cost_report_id"] == scenario["report_id"]
    assert summary["period_days"] == 365
    assert_fte_equals(
        summary["unweighted_fte_days_total"], 110.4000, "unweighted_fte_days_total"
    )
    assert summary["unweighted_fte_total"] == 0.30
    assert summary["capped_unweighted_fte"] == 0.30
    assert summary["weighted_fte_total"] == 0.30
    assert summary["rolling_average_fte"] == 0.30
    assert summary["prior_period_count"] == 0

    rotation = validate_success(
        api.get_rotation_assignment(scenario["base_rotation_id"], scenario["analyst"])
    )
    assert rotation["overlap_days"] == 184
    assert_fte_equals(rotation["fte_days"], 110.4000, "fte_days")

    resident = validate_success(
        api.get_resident(scenario["resident_id"], scenario["analyst"])
    )
    assert_fte_equals(resident["assigned_fte_days"], 110.4000, "assigned_fte_days")

    assert read_cost_report(api, scenario)["status"] == "DRAFT"


def test_a_cost_centers_ledger_link_returns_only_its_own_lines(api):
    """Four lines sit on the report; the link off 00100 returns exactly the two
    mapped to it and neither the other center's line nor the suspense line.

    PRD 3.3: "For each cost center of the report, `direct_cost_cents` becomes the sum of `amount_cents` over the report's trial balance lines whose `mapped_cost_center_id` is that center and whose `status` is `MAPPED`."

    PRD 2.3: "Most list endpoints also accept equality filters drawn from the listed entity's own fields, and those filters are how a client traverses a relationship backwards."

    Design: Corner/endpoints/cost_center_ledger_link_lists_only_the_lines_mapped_to_it
    """
    scenario = new_scenario(api)
    add_cost_center(api, scenario, "cc_ag", {**CENTER_AG, "statistics": {"SQUARE_FEET": 0}})
    add_cost_center(
        api, scenario, "cc_routine", {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}}
    )
    ag_one = add_mapped_tb_line(
        api, scenario, "6000", "Administration salaries", 60000000, "cc_ag"
    )
    ag_two = add_mapped_tb_line(
        api, scenario, "6001", "Administration benefits", 40000000, "cc_ag"
    )
    routine_line = add_mapped_tb_line(
        api, scenario, "6200", "Nursing salaries", 200000000, "cc_routine"
    )
    suspense = add_unmapped_tb_line(
        api, scenario, gl_account="6900", description="Suspense account", amount_cents=5000000
    )

    lines, meta = validate_paginated(
        api.list_cost_center_trial_balance_lines(
            scenario["cc_ag"], scenario["auditor"], {"limit": 10, "offset": 0}
        )
    )

    assert meta["total_count"] == 2
    returned_ids = {line["id"] for line in lines}
    assert returned_ids == {ag_one["id"], ag_two["id"]}
    assert routine_line["id"] not in returned_ids
    assert suspense["id"] not in returned_ids

    _all_lines, all_meta = validate_paginated(
        api.list_report_trial_balance_lines(scenario["report_id"], scenario["analyst"])
    )
    assert all_meta["total_count"] == 4

    assert_money_equals(
        read_cost_center(api, scenario, scenario["cc_ag"])["direct_cost_cents"],
        100000000,
        "00100 direct_cost_cents",
    )


def test_a_change_request_decision_moves_only_the_wage_axis(api):
    """The change-request branch marks the survey and the report's wage axis but
    leaves the report itself in DRAFT with the revision count still at 1.

    PRD 3.5: "`REQUEST_CHANGE` advances the submission to `CHANGE_REQUESTED` with no additional precondition; it sets `review_note`, sets the report's `wage_data_status` to `REVISION_REQUESTED` while leaving the report's `status` untouched, and increments the report's `version`."

    PRD 3.5: "They differ in two respects: the `DRAFT` path additionally requires that at least one survey response exist for the submission, while the `CHANGE_REQUESTED` path does not; and the `CHANGE_REQUESTED` path increments `revision_number` by one, which is why `revision_number` counts submissions after the first rather than submissions in total."

    Design: Corner/endpoints/review_decision_branch_change_requested_leaves_report_status_untouched
    """
    scenario = new_scenario(api)
    add_wage_submission(api, scenario)
    submit_wage_submission(api, scenario)
    start_wage_review(api, scenario)

    decided = validate_success(
        api.record_wage_index_review_decision(
            scenario["submission_id"],
            review_decision_payload(
                decision="REQUEST_CHANGE",
                review_note="Verify contract labor hours against the payroll register",
            ),
            scenario["auditor"],
        )
    )

    assert decided["status"] == "CHANGE_REQUESTED"
    assert (
        decided["review_note"]
        == "Verify contract labor hours against the payroll register"
    )

    resubmitted = validate_success(
        api.submit_wage_index_submission(scenario["submission_id"], scenario["manager"])
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_number"] == 1

    report = read_cost_report(api, scenario)
    assert report["status"] == "DRAFT"


def test_every_child_collection_of_a_report_lists_and_filters(api):
    """One report is walked through each of its collections: the filters narrow as
    declared, and the four legitimately empty lists answer 200 with zero rows.

    PRD 2.3: "A report's cost centers may be narrowed by `center_type`, its trial balance lines and its stepdown runs by `status`, its stepdown runs also by `method`, its workpaper entries by `entry_type`, `status` and `source`, and its wage index submissions and settlements by `status` (settlements additionally by `stage`)."

    PRD 2.3: "The response envelope's `meta` object carries `limit`, `offset`, `total_count` (the number of rows matching the filter before the window is applied) and `has_more` (whether rows remain beyond the current window)."

    Design: Corner/endpoints/every_report_child_collection_is_listable_with_its_declared_filters
    """
    scenario = _report_with_every_collection_populated(api)
    report_id = scenario["report_id"]
    analyst = scenario["analyst"]

    clock = get_success_data(api.get_clock(analyst))
    assert_instant_equals(clock["current_utc"], DEFAULT_CLOCK, "current_utc")

    centers, centers_meta = validate_paginated(
        api.list_report_cost_centers(report_id, analyst, {"center_type": "GENERAL_SERVICE"})
    )
    assert centers_meta["total_count"] == 1
    assert centers[0]["code"] == "00100"

    window, window_meta = validate_paginated(
        api.list_report_trial_balance_lines(
            report_id, analyst, {"status": "MAPPED", "limit": 1, "offset": 1}
        )
    )
    assert len(window) == 1
    assert window_meta["total_count"] == 2
    assert window_meta["limit"] == 1
    assert window_meta["offset"] == 1
    assert window_meta["has_more"] is False

    _runs, runs_meta = validate_paginated(api.list_report_stepdown_runs(report_id, analyst))
    assert runs_meta["total_count"] == 1

    _submissions, submissions_meta = validate_paginated(
        api.list_report_wage_index_submissions(report_id, analyst, {"status": "ACCEPTED"})
    )
    assert submissions_meta["total_count"] == 1

    rn_rows, rn_meta = validate_paginated(
        api.list_occ_mix_responses(scenario["submission_id"], analyst, {"category": "RN"})
    )
    assert rn_meta["total_count"] == 1
    assert_money_equals(rn_rows[0]["category_ahw_cents"], 3500, "category_ahw_cents")

    _ucc, ucc_meta = validate_paginated(api.list_report_ucc_data_sets(report_id, analyst))
    assert ucc_meta["total_count"] == 1

    _entries, entries_meta = validate_paginated(
        api.list_report_workpaper_entries(report_id, analyst)
    )
    assert entries_meta["total_count"] == 0

    _settlements, settlements_meta = validate_paginated(
        api.list_report_settlements(report_id, scenario["manager"])
    )
    assert settlements_meta["total_count"] == 0

    _residents, residents_meta = validate_paginated(
        api.list_provider_residents(scenario["provider_id"], analyst)
    )
    assert residents_meta["total_count"] == 0

    _rotations, rotations_meta = validate_paginated(
        api.list_rotation_assignments(analyst, {"cost_center_id": scenario["cc_routine"]})
    )
    assert rotations_meta["total_count"] == 0

    _appeals, appeals_meta = validate_paginated(
        api.list_appeal_cases(MANAGER_HEADERS, {"cost_report_id": report_id})
    )
    assert appeals_meta["total_count"] == 0

    _requests, requests_meta = validate_paginated(
        api.list_interim_rate_requests(
            MANAGER_HEADERS, {"provider_id": scenario["provider_id"]}
        )
    )
    assert requests_meta["total_count"] == 0
