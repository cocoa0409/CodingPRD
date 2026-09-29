"""Inclusive thresholds, exact allowance equality and empty candidate sets."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error
from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    make_energy_manager_headers,
    make_store_manager_headers,
)

PRODUCE_CASE = {
    "case_code": "CASE-BP1-01",
    "case_type": "MEDIUM_TEMP",
    "product_class": "PRODUCE",
    "alarm_high_f": 41.0,
    "alarm_low_f": 28.0,
    "product_value_usd": 4800.00,
}


def _armed_produce_case(api):
    """A MARINE store with one armed case whose high alarm sits at 41.0."""
    ctx = fx.setup_case_on_commissioned_store(
        api,
        clock="2026-08-01T12:00:00Z",
        store_overrides={
            "code": "STR-BP1", "climate_zone": "MARINE", "floor_area_sqft": 105000,
        },
        case_overrides=PRODUCE_CASE,
    )
    return ctx


class TestReadingExactlyAtAlarmHigh:
    def test_the_high_alarm_bound_is_inclusive(self, api):
        """40.9 leaves the case clean while 41.0 counts as a breach.

        The PRD states: "A reading **breaches** when its `temp_f` is at or above
        the case's `alarm_high_f`, or at or below the case's `alarm_low_f`; both
        bounds are inclusive, so a reading of exactly 41.0 against a high alarm of
        41.0 breaches, and a reading of 27.9 against a low alarm of 28.0 breaches
        on the cold side."

        Design: Difficulty/boundary_precision_check/reading_exactly_at_alarm_high_breaches
        """
        ctx = _armed_produce_case(api)
        assert ctx["case"]["monitoring_state"] == "ARMED"
        assert ctx["case"]["consecutive_breach_count"] == 0

        below = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 40.9, "2026-08-01T04:00:00Z"
        )
        at_bound = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 41.0, "2026-08-01T04:15:00Z"
        )

        assert below["consecutive_breach_count"] == 0
        assert below["monitoring_state"] == "ARMED"
        assert below["excursion_id"] is None
        assert at_bound["consecutive_breach_count"] == 1
        assert at_bound["monitoring_state"] == "ARMED"
        assert at_bound["excursion_id"] is None

    def test_a_single_clean_reading_restarts_the_breach_run(self, api):
        """The run must reach two consecutive breaches all over again.

        The PRD states: "A non-breaching reading resets `consecutive_breach_count`
        to zero — but it does *not* close an excursion that is already open; only
        explicit food-safety closure does that. When `consecutive_breach_count`
        reaches two and the case has no excursion in a non-closed state, the second
        consecutive breach opens one".

        Design: Difficulty/boundary_precision_check/reading_exactly_at_alarm_high_breaches
        """
        ctx = _armed_produce_case(api)
        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 40.9, "2026-08-01T04:00:00Z")
        fx.post_reading(api, ctx["case_id"], ctx["store_id"], 41.0, "2026-08-01T04:15:00Z")

        reset = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 40.9, "2026-08-01T04:30:00Z"
        )
        first_of_run = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 41.0, "2026-08-01T04:45:00Z"
        )
        opening = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 41.0, "2026-08-01T05:00:00Z"
        )

        assert reset["consecutive_breach_count"] == 0
        assert reset["monitoring_state"] == "ARMED"
        assert first_of_run["consecutive_breach_count"] == 1
        assert first_of_run["monitoring_state"] == "ARMED"
        assert opening["consecutive_breach_count"] == 2
        assert opening["monitoring_state"] == "ALARM"
        assert opening["exposure_minutes"] == 15
        assert opening["peak_temp_f"] == pytest.approx(41.0, abs=0.05)
        assert opening["store_energy_posture"] == "CONSTRAINED"

    def test_the_excursion_dates_from_the_second_run_not_the_first_breach(self, api):
        """first_breach_iso is the first breach of the current run only.

        The PRD states: "a `TempExcursion` is created in `OPEN` with `case_id`
        pointing at the case, `first_breach_iso` set to the reading instant of the
        **first** breach of the current run rather than the reading that crossed
        the count, `last_breach_iso` set to the current reading instant, and
        `product_value_usd` copied from the case as it stands at that moment".

        Design: Difficulty/boundary_precision_check/reading_exactly_at_alarm_high_breaches
        """
        ctx = _armed_produce_case(api)
        for temp, iso in [
            (40.9, "2026-08-01T04:00:00Z"),
            (41.0, "2026-08-01T04:15:00Z"),
            (40.9, "2026-08-01T04:30:00Z"),
            (41.0, "2026-08-01T04:45:00Z"),
        ]:
            fx.post_reading(api, ctx["case_id"], ctx["store_id"], temp, iso)
        opening = fx.post_reading(
            api, ctx["case_id"], ctx["store_id"], 41.0, "2026-08-01T05:00:00Z"
        )

        excursion = fx.read_excursion(api, opening["excursion_id"])
        rows, meta = fx.list_excursions(api, ctx["case_id"])
        case = get_success_data(api.get_refrigeration_case(ctx["case_id"], fx.MANAGER))

        assert excursion["first_breach_iso"].startswith("2026-08-01T04:45:00")
        assert excursion["last_breach_iso"].startswith("2026-08-01T05:00:00")
        assert excursion["state"] == "OPEN"
        assert excursion["product_value_usd"] == pytest.approx(4800.00, abs=0.01)
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert case["last_reading_temp_f"] == pytest.approx(41.0, abs=0.05)


BP2_STORE = {
    "code": "STR-BP2",
    "climate_zone": "HOT_DRY",
    "store_format": "NEIGHBORHOOD",
    "floor_area_sqft": 38000,
    "override_budget_kwh_month": 500.0,
}

OVERRIDE_A = {
    "zone": "SALES_FLOOR",
    "override_type": "SCHEDULE_EXTEND",
    "start_iso": "2026-08-12T00:00:00Z",
    "end_iso": "2026-08-12T08:00:00Z",
    "zone_load_kw": 37.5,
    "requested_reason": "remodel night work",
}

OVERRIDE_B = {
    "zone": "PARKING",
    "override_type": "SCHEDULE_EXTEND",
    "start_iso": "2026-08-12T00:00:00Z",
    "end_iso": "2026-08-12T08:00:00Z",
    "zone_load_kw": 25.0,
    "requested_reason": "lot restriping",
}

OVERRIDE_C = {
    "zone": "BACKROOM",
    "override_type": "OCCUPANCY_DISABLE",
    "start_iso": "2026-08-12T00:00:00Z",
    "end_iso": "2026-08-12T02:00:00Z",
    "zone_load_kw": 40.0,
    "requested_reason": "receiving surge",
}


def _store_charged_to_exactly_its_allowance(api):
    """Two overrides on distinct zones bring override_kwh_used_month to 500.00."""
    ctx = fx.setup_commissioned_store(api, **BP2_STORE)
    ctx["override_a"] = fx.create_override(api, ctx["store_id"], **OVERRIDE_A)
    ctx["used_after_a"] = fx.read_store(api, ctx["store_id"])["override_kwh_used_month"]
    ctx["override_b"] = fx.create_override(api, ctx["store_id"], **OVERRIDE_B)
    ctx["used_after_b"] = fx.read_store(api, ctx["store_id"])["override_kwh_used_month"]
    return ctx


class TestOverrideBudgetExactlyAtAllowance:
    def test_the_charge_landing_exactly_on_the_allowance_is_admitted(self, api):
        """300.00 plus 200.00 reaches 500.00 and is still accepted.

        The PRD states: "A creation request is admitted only when the store's
        current `override_kwh_used_month` plus the new `projected_kwh`, rounded half
        up to two decimal places, is less than or equal to
        `override_budget_kwh_month`; equality is admitted."

        Design: Difficulty/boundary_precision_check/override_budget_exactly_at_allowance_admitted
        """
        ctx = _store_charged_to_exactly_its_allowance(api)

        assert ctx["store"]["override_kwh_used_month"] == pytest.approx(0.00, abs=0.01)
        assert ctx["override_a"]["projected_kwh"] == pytest.approx(300.00, abs=0.01)
        assert ctx["used_after_a"] == pytest.approx(300.00, abs=0.01)
        assert ctx["override_b"]["projected_kwh"] == pytest.approx(200.00, abs=0.01)
        assert ctx["used_after_b"] == pytest.approx(500.00, abs=0.01)

    def test_the_next_request_is_refused_once_the_allowance_is_full(self, api):
        """580.00 against a 500.0 allowance is refused.

        The PRD states: "A store with a 500.00 kWh allowance that has already
        committed 300.00 kWh admits a further 200.00 kWh exactly, and then refuses
        an 80.00 kWh request — until one of the earlier overrides is revoked, at
        which point the freed kilowatt-hours make room."

        Design: Difficulty/boundary_precision_check/override_budget_exactly_at_allowance_admitted
        """
        ctx = _store_charged_to_exactly_its_allowance(api)

        response = api.create_lighting_override(
            ctx["store_id"],
            f.create_lighting_override_payload(**OVERRIDE_C),
            make_store_manager_headers(ctx["store_id"]),
        )

        validate_error(response, ApiErrorId.ERR_OVERRIDE_BUDGET_EXCEEDED.value, 422)
        assert fx.read_store(api, ctx["store_id"])[
            "override_kwh_used_month"
        ] == pytest.approx(500.00, abs=0.01)

    def test_a_user_revocation_frees_exactly_the_revoked_projection(self, api):
        """The running total is recomputed from surviving rows, not counted up.

        The PRD states: "Only `REVOKED` rows drop out of the sum, which is precisely
        how a revocation releases budget."

        Design: Difficulty/boundary_precision_check/override_budget_exactly_at_allowance_admitted
        """
        ctx = _store_charged_to_exactly_its_allowance(api)
        manager = make_store_manager_headers(ctx["store_id"])
        api.create_lighting_override(
            ctx["store_id"], f.create_lighting_override_payload(**OVERRIDE_C), manager
        )

        revoked = get_success_data(
            api.revoke_lighting_override(
                ctx["override_b"]["id"], make_energy_manager_headers("u_manager_bp2")
            )
        )
        used_after_revoke = fx.read_store(api, ctx["store_id"])["override_kwh_used_month"]
        retried = get_success_data(
            api.create_lighting_override(
                ctx["store_id"], f.create_lighting_override_payload(**OVERRIDE_C), manager
            )
        )
        rows, meta = fx.list_overrides(api, ctx["store_id"])

        assert revoked["state"] == "REVOKED"
        assert revoked["revoke_source"] == "USER"
        assert revoked["revoked_by_user_id"] == "u_manager_bp2"
        assert used_after_revoke == pytest.approx(300.00, abs=0.01)
        assert retried["projected_kwh"] == pytest.approx(80.00, abs=0.01)
        assert fx.read_store(api, ctx["store_id"])[
            "override_kwh_used_month"
        ] == pytest.approx(380.00, abs=0.01)
        assert meta["total_count"] == 3
        assert [row["state"] for row in rows].count("REVOKED") == 1


INELIGIBLE_INTERVALS = [
    # Off-peak, so it never enters the candidate pool.
    f.demand_interval("2026-08-04T02:00:00Z", 1600.0, False),
    # On-peak but flagged as an event day.
    f.demand_interval("2026-08-03T14:00:00Z", 1500.0, True, is_dr_event_day=True),
    # On-peak and clean, but it starts after the curtailment start.
    f.demand_interval("2026-08-05T16:00:00Z", 1400.0, True),
]

BP3_EVENT = {
    "program_code": "CPP-2026",
    "curtailment_start_iso": "2026-08-05T14:00:00Z",
    "curtailment_end_iso": "2026-08-05T15:00:00Z",
    "target_reduction_kw": 100.0,
}


def _event_with_no_eligible_baseline_intervals(api):
    """An EXPRESS store whose account holds three deliberately ineligible intervals."""
    ctx = fx.setup_commissioned_store(
        api, code="STR-BP3", store_format="EXPRESS", floor_area_sqft=15000,
    )
    account = fx.create_account(
        api, ctx["store_id"], utility_name="Midland Power",
        rate_schedule_code="TOU-GS1", rate_family="TOU_DEMAND",
        demand_charge_per_kw=12.00, rate_on_peak=0.1400, rate_off_peak=0.0790,
    )
    fx.ingest_intervals(api, account["id"], INELIGIBLE_INTERVALS)
    event = fx.create_event(api, account["id"], **BP3_EVENT)
    ctx["account_id"] = account["id"]
    ctx["event"] = event
    ctx["event_id"] = event["id"]
    return ctx


class TestBaselineEmptyCandidateSetRejectsNotify:
    def test_an_empty_candidate_pool_refuses_notification(self, api):
        """Zero eligible intervals is an error, and the event does not move.

        The PRD states: "When the candidate pool is empty the notification is
        refused with `ERR_BASELINE_DATA_INSUFFICIENT` (HTTP 422), the event stays
        `SCHEDULED` and `baseline_kw` stays null; one or two candidates is not an
        error, merely a thinner average."

        Design: Difficulty/boundary_precision_check/baseline_empty_candidate_set_rejects_notify
        """
        ctx = _event_with_no_eligible_baseline_intervals(api)
        assert ctx["event"]["event_state"] == "SCHEDULED"
        assert ctx["event"]["baseline_kw"] is None

        response = api.notify_demand_response_event(ctx["event_id"], fx.MANAGER)

        validate_error(response, ApiErrorId.ERR_BASELINE_DATA_INSUFFICIENT.value, 422)
        events, _ = fx.list_events(api, ctx["account_id"])
        event = fx.find_row(events, ctx["event_id"])
        assert event["event_state"] == "SCHEDULED"
        assert event["baseline_kw"] is None

    def test_one_eligible_interval_is_enough_and_averages_alone(self, api):
        """A single surviving candidate becomes the whole baseline.

        The PRD states: "`baseline_kw` is then the sum of the kept intervals'
        `kw_demand` divided by the number of kept intervals, with the division
        performed once on the exact sum and the result rounded half up to two
        decimal places."

        Design: Difficulty/boundary_precision_check/baseline_empty_candidate_set_rejects_notify
        """
        ctx = _event_with_no_eligible_baseline_intervals(api)
        api.notify_demand_response_event(ctx["event_id"], fx.MANAGER)

        fx.ingest_intervals(
            api, ctx["account_id"],
            [f.demand_interval("2026-08-04T14:00:00Z", 1290.5, True)],
        )
        notified = fx.notify_event(api, ctx["event_id"])

        assert notified["event_state"] == "NOTIFIED"
        assert notified["baseline_kw"] == pytest.approx(1290.5, abs=0.01)
        assert notified["notified_at_iso"].startswith("2026-08-01T00:00:00")

    def test_the_three_ineligible_intervals_never_enter_the_average(self, api):
        """None of the higher-demand rows can raise the baseline.

        The PRD states: "The candidate pool is every demand interval of the event's
        account whose `is_on_peak` is true, whose `is_dr_event_day` is false, and
        whose `interval_start_iso` is strictly before the event's
        `curtailment_start_iso` — event days are excluded precisely because they are
        already depressed by curtailment."

        Design: Difficulty/boundary_precision_check/baseline_empty_candidate_set_rejects_notify
        """
        ctx = _event_with_no_eligible_baseline_intervals(api)
        fx.ingest_intervals(
            api, ctx["account_id"],
            [f.demand_interval("2026-08-04T14:00:00Z", 1290.5, True)],
        )

        notified = fx.notify_event(api, ctx["event_id"])

        # Averaging all four rows would give 1447.63; averaging the top three of
        # them would give 1500.00 and pulling in the post-start row 1345.25.
        assert notified["baseline_kw"] == pytest.approx(1290.5, abs=0.01)
        assert notified["baseline_kw"] != pytest.approx(1447.63, abs=0.01)
        assert notified["baseline_kw"] != pytest.approx(1345.25, abs=0.01)
