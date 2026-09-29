"""The cross-cutting layers: both halves of each version token, the one run that
is recorded rather than refused, the variance gate at its exact boundary, and a
derived figure republished when its source finally exists."""

from test_helpers import (
    CANONICAL_UCC_DATA_SET,
    ApiErrorId,
    assert_money_equals,
    assert_ratio_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    interim_rate_decision_payload,
    interim_rate_request_payload,
    stepdown_run_payload,
)
from test_helpers.fixtures import (
    CENTER_AG,
    CENTER_LAUNDRY,
    CENTER_ROUTINE,
    accept_wage_submission,
    add_cost_center,
    add_mapped_tb_line,
    add_ucc_data_set,
    create_settlement,
    file_report,
    new_scenario,
    read_cost_center,
    read_cost_report,
    read_provider,
    run_stepdown,
    setup_two_center_report,
)


def _two_center_final_settlement(api, **kwargs):
    """A FINAL_SETTLED two-center report: 600000 per discharge, rate still 900000."""
    scenario = setup_two_center_report(api, **kwargs)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    accept_wage_submission(api, scenario)
    add_ucc_data_set(api, scenario)
    file_report(api, scenario)
    create_settlement(api, scenario, "TENTATIVE")
    run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")
    create_settlement(api, scenario, "FINAL")
    return scenario


def test_a_run_built_on_a_superseded_report_version_is_refused(api):
    """A statistic revision moved the report on between the read and the run, so the
    token no longer matches and not even an audit row is left behind.

    PRD 2.8: "If that value does not equal the report's current `version`, the request is rejected with `ERR_STALE_COST_REPORT_VERSION` and HTTP 412, and nothing is written."

    PRD 3.2: "Every revision demotes each `COMPLETED` stepdown run of the report to `STALE` with `stale_reason` `COST_CENTER_INPUT_CHANGED`, sets the report's `allocation_status` to `STALE`, and increments the report's `version`."

    Design: Corner/cross-cutting complexity layers/stale_expected_cost_report_version_is_rejected
    """
    scenario = setup_two_center_report(api)
    observed_version = read_cost_report(api, scenario)["version"]
    validate_success(
        api.update_cost_center(
            scenario["cc_routine"],
            {"statistics": {"SQUARE_FEET": 3500}},
            scenario["analyst"],
        )
    )

    response = api.create_stepdown_run(
        scenario["report_id"],
        stepdown_run_payload(observed_version, "SINGLE_APPORTIONMENT"),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_STALE_COST_REPORT_VERSION.value, 412)

    runs, meta = validate_paginated(
        api.list_report_stepdown_runs(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert runs == []

    report = read_cost_report(api, scenario)
    assert report["allocation_status"] == "NOT_RUN"
    assert_money_equals(
        report["total_allowable_cost_cents"], 0, "total_allowable_cost_cents"
    )
    assert report["version"] == observed_version + 1


def test_a_run_built_on_the_current_report_version_goes_through(api):
    """With no intervening write the same token is still current, so the run
    completes and the write moves the report on by exactly one.

    PRD 2.4: "**`version`** (integer): a monotonically increasing counter that begins at 1 and increments by one on every mutation of the row."

    PRD 3.4: "The report's `total_allowable_cost_cents` is then the sum of `allocated_total_cost_cents` over the cost centers whose `center_type` is `ROUTINE` or `ANCILLARY` only — nonreimbursable centers do receive allocations, and are deliberately excluded from this total."

    Design: Corner/cross-cutting complexity layers/current_expected_cost_report_version_is_accepted_and_bumps_the_version
    """
    scenario = setup_two_center_report(api)
    observed_version = read_cost_report(api, scenario)["version"]

    run = validate_success(
        api.create_stepdown_run(
            scenario["report_id"],
            stepdown_run_payload(observed_version, "SINGLE_APPORTIONMENT"),
            scenario["analyst"],
        ),
        201,
    )

    assert run["status"] == "COMPLETED"
    assert_money_equals(run["total_allocated_cents"], 100000000, "total_allocated_cents")
    assert_money_equals(
        run["residual_unallocated_cents"], 0, "residual_unallocated_cents"
    )

    assert_money_equals(
        read_cost_center(api, scenario, scenario["cc_routine"])[
            "allocated_total_cost_cents"
        ],
        300000000,
        "03000 allocated_total_cost_cents",
    )

    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["total_allowable_cost_cents"], 300000000, "total_allowable_cost_cents"
    )
    assert report["allocation_status"] == "CURRENT"
    assert report["version"] == observed_version + 1


def test_a_rate_request_built_on_a_superseded_provider_version_is_refused(api):
    """Approving the first request repriced the provider, so the second request's
    stale token answers on concurrency before period or variance is examined.

    PRD 2.8: "If that value does not equal the provider's current `version`, the request is rejected with `ERR_STALE_PROVIDER_VERSION` and HTTP 412."

    PRD 2.10: "8. **Concurrency** — `expected_cost_report_version` equals the report's `version` on a stepdown run creation, else `ERR_STALE_COST_REPORT_VERSION` (412); and `expected_provider_version` equals the provider's `version` on an interim rate request creation, else `ERR_STALE_PROVIDER_VERSION` (412)."

    PRD 3.9: "Creating a request increments the provider's `version`."

    PRD 3.9: "`APPROVE` advances the request to the terminal `APPROVED` state; it requires the basis report's `status` to be `FINAL_SETTLED` (`ERR_BASIS_REPORT_NOT_FINAL_SETTLED`), sets `decision_note`, writes `approved_rate_cents` onto the provider as its new `current_interim_rate_cents`, increments the provider's `approved_interim_period_count` by one, and increments the provider's `version`."

    Design: Corner/cross-cutting complexity layers/stale_expected_provider_version_is_rejected
    """
    scenario = _two_center_final_settlement(api)
    observed_version = read_provider(api, scenario)["version"]

    first = validate_success(
        api.create_interim_rate_request(
            interim_rate_request_payload(
                scenario["provider_id"],
                scenario["report_id"],
                observed_version,
                trend_factor=0.3500,
                effective_to="2027-03-31",
            ),
            scenario["manager"],
        ),
        201,
    )
    validate_success(
        api.decide_interim_rate_request(
            first["id"],
            interim_rate_decision_payload(
                decision="APPROVE", decision_note="Rate reduction accepted"
            ),
            scenario["auditor"],
        )
    )

    response = api.create_interim_rate_request(
        interim_rate_request_payload(
            scenario["provider_id"],
            scenario["report_id"],
            observed_version,
            projected_discharges=400,
            trend_factor=0.3500,
            effective_from="2027-01-01",
            effective_to="2027-06-30",
        ),
        scenario["manager"],
    )

    validate_error(response, ApiErrorId.ERR_STALE_PROVIDER_VERSION.value, 412)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_INTERIM_PERIOD_OVERLAP.value
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_INTERIM_VARIANCE_BELOW_THRESHOLD.value
    )

    reread_first = validate_success(
        api.get_interim_rate_request(first["id"], scenario["manager"])
    )
    assert reread_first["status"] == "APPROVED"

    provider = read_provider(api, scenario)
    assert_money_equals(
        provider["current_interim_rate_cents"], 810000, "current_interim_rate_cents"
    )
    assert provider["version"] == observed_version + 2

    requests, meta = validate_paginated(
        api.list_interim_rate_requests(
            scenario["manager"], {"provider_id": scenario["provider_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert len(requests) == 1


def test_a_duplicate_allocation_order_is_recorded_as_a_failed_run(api):
    """The collision a revision permits is not a validation error: the attempt is
    stored as a FAILED run and none of the completion effects fire.

    PRD 3.4: "There is exactly one way for a run to be created and *not* succeed: if two or more `GENERAL_SERVICE` centers of the report share the same `stepdown_order` — the transient collision that revision permits — the run resolves to `FAILED` with `failure_reason` set to the string `DUPLICATE_STEPDOWN_ORDER`, is returned with HTTP 201 as the audit record of the attempt, leaves the report's `allocation_status` untouched, and still increments the report's `version`."

    PRD 3.4: "A `FAILED` run writes no allocation lines and touches no cost center."

    PRD 3.2: "Swapping orders 1 and 2 must pass through a moment where two general service centers both hold the same `stepdown_order`, so revision does **not** enforce `stepdown_order` uniqueness and never raises `ERR_STEPDOWN_ORDER_CONFLICT`."

    Design: Corner/cross-cutting complexity layers/a_failed_stepdown_run_leaves_the_previous_allocation_untouched
    """
    scenario = new_scenario(api)
    add_cost_center(api, scenario, "cc_ag", {**CENTER_AG, "statistics": {"SQUARE_FEET": 0}})
    add_cost_center(
        api,
        scenario,
        "cc_maint",
        {
            **CENTER_LAUNDRY,
            "code": "00200",
            "name": "Maintenance and Repairs",
            "allocation_basis": "SQUARE_FEET",
            "stepdown_order": 2,
            "statistics": {"SQUARE_FEET": 0},
        },
    )
    add_cost_center(
        api, scenario, "cc_routine", {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}}
    )
    add_mapped_tb_line(
        api, scenario, "6000", "Administration salaries", 100000000, "cc_ag"
    )
    add_mapped_tb_line(api, scenario, "6100", "Plant maintenance", 50000000, "cc_maint")
    add_mapped_tb_line(api, scenario, "6200", "Nursing salaries", 200000000, "cc_routine")
    first_run = run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    assert first_run["status"] == "COMPLETED"

    validate_success(
        api.update_cost_center(
            scenario["cc_maint"], {"stepdown_order": 1}, scenario["analyst"]
        )
    )
    current_version = read_cost_report(api, scenario)["version"]

    failed = validate_success(
        api.create_stepdown_run(
            scenario["report_id"],
            stepdown_run_payload(current_version, "SINGLE_APPORTIONMENT"),
            scenario["analyst"],
        ),
        201,
    )

    assert failed["status"] == "FAILED"
    assert failed["failure_reason"] == "DUPLICATE_STEPDOWN_ORDER"
    assert_money_equals(failed["total_allocated_cents"], 0, "total_allocated_cents")
    assert failed["allocation_lines"] == []

    reread_first = validate_success(
        api.get_stepdown_run(first_run["id"], scenario["analyst"])
    )
    assert reread_first["status"] == "STALE"
    assert reread_first["stale_reason"] == "COST_CENTER_INPUT_CHANGED"

    report = read_cost_report(api, scenario)
    assert report["allocation_status"] == "STALE"
    assert_money_equals(
        report["total_allowable_cost_cents"], 350000000, "total_allowable_cost_cents"
    )
    assert_money_equals(
        report["total_direct_cost_cents"], 350000000, "total_direct_cost_cents"
    )


def test_a_swing_of_exactly_ten_percent_clears_the_gate(api):
    """600000 trended by 0.3500 projects 810000 against 900000, a variance of exactly
    0.1000, and the gate refuses only what falls below it.

    PRD 3.9: "Third, the eligibility gate is applied to that pre-cap variance: a `variance_ratio` below 0.1000 — a swing of less than ten percent — is not worth a rate change and the request is rejected with `ERR_INTERIM_VARIANCE_BELOW_THRESHOLD`."

    PRD 3.9: "Fourth, and only after the gate, the cap is applied: the rate ceiling is the provider's `current_interim_rate_cents` multiplied by 1.10 — a hundred and ten percent of the standing rate — rounded down to a whole cent, and `approved_rate_cents` is the lesser of the uncapped projection and that ceiling."

    PRD 3.9: "Fifth, `adjustment_amount_cents` is the difference between `approved_rate_cents` and the provider's `current_interim_rate_cents` at request time, multiplied by `projected_discharges`."

    PRD 3.9: "Creating a request increments the provider's `version`."

    Design: Corner/cross-cutting complexity layers/interim_rate_variance_exactly_at_the_threshold_is_accepted
    """
    scenario = _two_center_final_settlement(api)
    observed_version = read_provider(api, scenario)["version"]

    request = validate_success(
        api.create_interim_rate_request(
            interim_rate_request_payload(
                scenario["provider_id"],
                scenario["report_id"],
                observed_version,
                trend_factor=0.3500,
                effective_to="2027-03-31",
            ),
            scenario["manager"],
        ),
        201,
    )

    assert request["variance_ratio"] == 0.1000
    assert_money_equals(
        request["projected_cost_per_discharge_cents"],
        810000,
        "projected_cost_per_discharge_cents",
    )
    assert_money_equals(request["approved_rate_cents"], 810000, "approved_rate_cents")
    assert_money_equals(
        request["adjustment_amount_cents"], -45000000, "adjustment_amount_cents"
    )
    assert request["status"] == "PENDING"

    provider = read_provider(api, scenario)
    assert_money_equals(
        provider["current_interim_rate_cents"], 900000, "current_interim_rate_cents"
    )
    assert provider["version"] == observed_version + 1


def test_the_care_figures_are_republished_when_a_ratio_finally_exists(api):
    """Compiled before any allocation, the data set carries only its bad-debt term;
    completing the run republishes the charity term with no second write.

    PRD 3.7: "The data set's own `cost_to_charge_ratio` is a snapshot of the report's `cost_to_charge_ratio` taken at the moment of the compilation, held to six decimal places, and it reads 0.000000 until a stepdown run has completed."

    PRD 3.7: "`uncompensated_care_cost_cents` is the sum of two separately rounded terms: `charity_care_charges_cents` multiplied by that snapshot ratio, rounded half up to a whole cent, plus `non_medicare_bad_debt_cents` multiplied by 0.65 — sixty-five percent of non-Medicare bad debt is allowable — rounded half up to a whole cent."

    PRD 3.7: "The compilation runs at creation, on an explicit recompute, and as link three of the completed-stepdown cascade."

    Design: Corner/cross-cutting complexity layers/uncompensated_care_figures_are_reconciled_when_the_cost_to_charge_ratio_appears
    """
    scenario = setup_two_center_report(api)

    at_create = validate_success(
        api.create_ucc_data_set(
            scenario["report_id"], dict(CANONICAL_UCC_DATA_SET), scenario["analyst"]
        ),
        201,
    )
    assert_ratio_equals(
        at_create["cost_to_charge_ratio"], 0.000000, "cost_to_charge_ratio at create"
    )
    assert_money_equals(
        at_create["uncompensated_care_cost_cents"],
        6500000,
        "uncompensated_care_cost_cents at create",
    )
    assert_money_equals(
        at_create["ucc_payment_cents"], 1300000, "ucc_payment_cents at create"
    )

    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")

    reread = validate_success(
        api.get_ucc_data_set(at_create["id"], scenario["analyst"])
    )
    assert_ratio_equals(
        reread["cost_to_charge_ratio"], 0.750000, "cost_to_charge_ratio"
    )
    assert_money_equals(
        reread["uncompensated_care_cost_cents"],
        36500000,
        "uncompensated_care_cost_cents",
    )
    assert_money_equals(reread["ucc_payment_cents"], 7300000, "ucc_payment_cents")
    assert reread["dsh_patient_percentage"] == 0.1500
    assert reread["dsh_eligible"] is True
    assert reread["recompute_required"] is False

    assert_ratio_equals(
        read_cost_report(api, scenario)["cost_to_charge_ratio"],
        0.750000,
        "report cost_to_charge_ratio",
    )
