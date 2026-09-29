"""The interim rate projection: variance measured before the cap, and the
thirty-day buffer between requested periods."""

from test_helpers import (
    ApiErrorId,
    assert_money_equals,
    assert_ratio_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import interim_rate_request_payload
from test_helpers.fixtures import (
    accept_wage_submission,
    add_ucc_data_set,
    create_interim_rate_request,
    create_settlement,
    file_report,
    read_cost_report,
    read_provider,
    run_stepdown,
    setup_interim_rate_basis,
    setup_two_center_report,
)


def test_variance_is_measured_on_the_uncapped_projection(api):
    """The stored variance is 0.1975, computed from the 1077714 projection rather
    than from the capped rate that is actually approved.

    PRD 3.9: "Computing `variance_ratio` from `approved_rate_cents` instead — that is, after the cap — would collapse every capped request to exactly ten percent, changing both the stored variance and which requests pass the gate."

    Design: Difficulty/combinatorial_formula/interim_rate_variance_measured_before_cap_is_applied
    """
    scenario = setup_interim_rate_basis(api)
    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["allowable_cost_per_discharge_cents"],
        898095,
        "allowable_cost_per_discharge_cents",
    )

    request = create_interim_rate_request(
        api,
        scenario,
        projected_discharges=500,
        trend_factor=0.2000,
        effective_from="2026-10-01",
        effective_to="2027-09-30",
    )

    assert_money_equals(
        request["projected_cost_per_discharge_cents"],
        1077714,
        "projected_cost_per_discharge_cents",
    )
    assert_ratio_equals(request["variance_ratio"], 0.1975, "variance_ratio", places=4)
    assert request["variance_ratio"] != 0.1000


def test_the_ten_percent_ceiling_binds_below_the_projection(api):
    """The approved rate is floored at 990000 by the 1.10 ceiling, and the
    adjustment follows from that capped figure.

    PRD 3.9: "Fourth, and only after the gate, the cap is applied: the rate ceiling is the provider's `current_interim_rate_cents` multiplied by 1.10 — a hundred and ten percent of the standing rate — rounded down to a whole cent, and `approved_rate_cents` is the lesser of the uncapped projection and that ceiling."

    Design: Difficulty/combinatorial_formula/interim_rate_variance_measured_before_cap_is_applied
    """
    scenario = setup_interim_rate_basis(api)

    request = create_interim_rate_request(
        api,
        scenario,
        projected_discharges=500,
        trend_factor=0.2000,
        effective_from="2026-10-01",
        effective_to="2027-09-30",
    )

    assert_money_equals(request["approved_rate_cents"], 990000, "approved_rate_cents")
    assert_money_equals(
        request["adjustment_amount_cents"], 45000000, "adjustment_amount_cents"
    )
    assert request["status"] == "PENDING"

    provider = read_provider(api, scenario)
    assert_money_equals(
        provider["current_interim_rate_cents"], 900000, "current_interim_rate_cents"
    )


def _final_settled_basis_at_five_thousand_dollars(api):
    """A two-center report settled off a double apportionment run, 600000 per
    discharge, against a standing rate of 500000 cents."""
    scenario = setup_two_center_report(
        api,
        provider_overrides={"current_interim_rate_cents": 500000},
        report_overrides={"apportionment_method": "DOUBLE_APPORTIONMENT"},
    )
    run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")
    add_ucc_data_set(api, scenario)
    accept_wage_submission(api, scenario)
    file_report(api, scenario)
    create_settlement(api, scenario, "TENTATIVE")
    create_settlement(api, scenario, "FINAL")
    return scenario


def test_a_period_one_day_after_the_incumbent_violates_the_buffer(api):
    """Requesting 2027-10-01 through 2028-09-30 is rejected even though that
    closed interval does not intersect the standing one.

    PRD 3.9: "The requested closed interval must not come within 30 days of the closed interval of any of that provider's existing interim rate requests whose `status` is neither `DENIED` nor `SUPERSEDED`; boundaries are inclusive on both ends, and a violation is rejected with `ERR_INTERIM_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/interim_rate_periods_need_a_thirty_day_gap_on_inclusive_bounds
    """
    scenario = _final_settled_basis_at_five_thousand_dollars(api)
    first = create_interim_rate_request(
        api,
        scenario,
        projected_discharges=500,
        trend_factor=0.1000,
        effective_from="2026-10-01",
        effective_to="2027-09-30",
    )
    provider_version = read_provider(api, scenario)["version"]

    response = api.create_interim_rate_request(
        interim_rate_request_payload(
            scenario["provider_id"],
            scenario["report_id"],
            provider_version,
            projected_discharges=500,
            trend_factor=0.1000,
            effective_from="2027-10-01",
            effective_to="2028-09-30",
        ),
        scenario["manager"],
    )

    validate_error(response, ApiErrorId.ERR_INTERIM_PERIOD_OVERLAP.value, 409)

    unchanged = validate_success(
        api.get_interim_rate_request(first["id"], scenario["manager"])
    )
    assert unchanged["status"] == "PENDING"
    assert read_provider(api, scenario)["version"] == provider_version


def test_a_period_thirty_two_days_later_clears_the_buffer_and_supersedes(api):
    """Starting 2027-11-01 is accepted, and accepting it moves the standing
    pending request to SUPERSEDED without touching the provider's rate.

    PRD 3.9: "A new request begins at `status` `PENDING` with `decision_note` null, and it supersedes the provider's outstanding work: any prior request of the same provider still in `PENDING` is moved to the terminal `SUPERSEDED` state with its `decision_note` set to the string `SUPERSEDED_BY_NEWER_REQUEST`, and the provider's `current_interim_rate_cents` is not touched by that superseding."

    Design: Difficulty/resource_temporal_overlap/interim_rate_periods_need_a_thirty_day_gap_on_inclusive_bounds
    """
    scenario = _final_settled_basis_at_five_thousand_dollars(api)
    first = create_interim_rate_request(
        api,
        scenario,
        projected_discharges=500,
        trend_factor=0.1000,
        effective_from="2026-10-01",
        effective_to="2027-09-30",
    )

    second = create_interim_rate_request(
        api,
        scenario,
        projected_discharges=500,
        trend_factor=0.1000,
        effective_from="2027-11-01",
        effective_to="2028-10-31",
    )

    assert second["status"] == "PENDING"
    assert second["effective_from"] == "2027-11-01"
    assert second["effective_to"] == "2028-10-31"
    assert_money_equals(
        second["projected_cost_per_discharge_cents"],
        660000,
        "projected_cost_per_discharge_cents",
    )
    assert_money_equals(second["approved_rate_cents"], 550000, "approved_rate_cents")

    superseded = validate_success(
        api.get_interim_rate_request(first["id"], scenario["manager"])
    )
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["decision_note"] == "SUPERSEDED_BY_NEWER_REQUEST"

    requests, meta = validate_paginated(
        api.list_interim_rate_requests(
            scenario["manager"], {"provider_id": scenario["provider_id"]}
        )
    )
    assert meta["total_count"] == 2
    assert len(requests) == 2

    report = read_cost_report(api, scenario)
    assert_money_equals(
        report["allowable_cost_per_discharge_cents"],
        600000,
        "allowable_cost_per_discharge_cents",
    )
    provider = read_provider(api, scenario)
    assert_money_equals(
        provider["current_interim_rate_cents"], 500000, "current_interim_rate_cents"
    )
