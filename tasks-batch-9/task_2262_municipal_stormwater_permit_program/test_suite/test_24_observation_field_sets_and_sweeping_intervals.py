"""Two shape rules that live below the request layer: the observation
discriminator and the sweeping log's half-open intervals."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import IDDE_HEADERS, OPERATIONS_HEADERS

OBSERVED_AT = "2026-08-01T08:00:00Z"


def _post_observation(outfall_id, payload, headers):
    """Send a hand-built observation body so no factory default fills a gap."""
    return api_client.create_observation(outfall_id, payload, headers)


class TestTheObservationTypeDecidesTheFieldSet:
    """Four bodies, each mismatching its own discriminator in a different way."""

    @pytest.fixture
    def outfall(self, active_program):
        """The single ACTIVE outfall of an ACTIVE term, never yet screened."""
        return active_program["outfalls"]["OF-01"]

    def test_01_a_screening_may_not_carry_the_sample_fields(self, outfall):
        """Concentration and volume belong to the other kind of visit.

        PRD: "A `DRY_WEATHER_SCREENING` requires `dry_weather_flow_present` and may carry
        the three indicator readings `indicator_bacteria_mpn`,
        `indicator_surfactant_mg_per_l` and `indicator_ammonia_mg_per_l`, each
        non-negative; it must not carry `pollutant_concentration_mg_per_l` or
        `runoff_volume_kl`." And: "A field set that does not match its
        `observation_type` — a required field missing, or a field belonging to the other
        type present — is refused with `ERR_OBSERVATION_TYPE_FIELDS_INVALID`."

        Design: Corner/validations/observation_field_sets_must_match_the_observation_type_discriminator
        """
        response = _post_observation(
            outfall["id"],
            {
                "observation_type": "DRY_WEATHER_SCREENING",
                "observed_at": OBSERVED_AT,
                "dry_weather_flow_present": True,
                "pollutant_concentration_mg_per_l": 0.30,
                "runoff_volume_kl": 100.00,
            },
            IDDE_HEADERS,
        )

        validate_error(
            response, ApiErrorId.ERR_OBSERVATION_TYPE_FIELDS_INVALID.value, 422
        )

    def test_02_a_screening_without_its_flow_flag_is_incomplete(self, outfall):
        """An indicator reading is optional; the flow observation is not.

        PRD: "A `DRY_WEATHER_SCREENING` requires `dry_weather_flow_present` and may carry
        the three indicator readings `indicator_bacteria_mpn`,
        `indicator_surfactant_mg_per_l` and `indicator_ammonia_mg_per_l`, each
        non-negative; it must not carry `pollutant_concentration_mg_per_l` or
        `runoff_volume_kl`." And: "A field set that does not match its
        `observation_type` — a required field missing, or a field belonging to the other
        type present — is refused with `ERR_OBSERVATION_TYPE_FIELDS_INVALID`."

        Design: Corner/validations/observation_field_sets_must_match_the_observation_type_discriminator
        """
        response = _post_observation(
            outfall["id"],
            {
                "observation_type": "DRY_WEATHER_SCREENING",
                "observed_at": OBSERVED_AT,
                "indicator_bacteria_mpn": 400.0,
            },
            IDDE_HEADERS,
        )

        validate_error(
            response, ApiErrorId.ERR_OBSERVATION_TYPE_FIELDS_INVALID.value, 422
        )

    def test_03_a_sample_without_its_volume_is_incomplete(self, outfall):
        """A concentration alone cannot be turned into a load.

        PRD: "A `WET_WEATHER_SAMPLE` requires both `pollutant_concentration_mg_per_l` and
        `runoff_volume_kl` and must not carry any of the three indicator fields." And: "A
        field set that does not match its `observation_type` — a required field missing,
        or a field belonging to the other type present — is refused with
        `ERR_OBSERVATION_TYPE_FIELDS_INVALID`."

        Design: Corner/validations/observation_field_sets_must_match_the_observation_type_discriminator
        """
        response = _post_observation(
            outfall["id"],
            {
                "observation_type": "WET_WEATHER_SAMPLE",
                "observed_at": OBSERVED_AT,
                "pollutant_concentration_mg_per_l": 0.30,
            },
            OPERATIONS_HEADERS,
        )

        validate_error(
            response, ApiErrorId.ERR_OBSERVATION_TYPE_FIELDS_INVALID.value, 422
        )

    def test_04_a_complete_sample_may_still_not_smuggle_an_indicator(self, outfall):
        """Every required sample field is present, and one foreign field spoils it.

        PRD: "A `WET_WEATHER_SAMPLE` requires both `pollutant_concentration_mg_per_l` and
        `runoff_volume_kl` and must not carry any of the three indicator fields." And: "A
        field set that does not match its `observation_type` — a required field missing,
        or a field belonging to the other type present — is refused with
        `ERR_OBSERVATION_TYPE_FIELDS_INVALID`."

        Design: Corner/validations/observation_field_sets_must_match_the_observation_type_discriminator
        """
        response = _post_observation(
            outfall["id"],
            {
                "observation_type": "WET_WEATHER_SAMPLE",
                "observed_at": OBSERVED_AT,
                "pollutant_concentration_mg_per_l": 0.30,
                "runoff_volume_kl": 100.00,
                "indicator_ammonia_mg_per_l": 0.10,
            },
            OPERATIONS_HEADERS,
        )

        validate_error(
            response, ApiErrorId.ERR_OBSERVATION_TYPE_FIELDS_INVALID.value, 422
        )

    def test_05_none_of_the_four_rejections_touched_the_outfall(self, outfall):
        """The counters read exactly as they did before the four attempts.

        PRD: "Nothing is persisted when a request is rejected — no partial writes, no
        counter increments, no cascades." And: "**Subject and field-set coherence.**
        Polymorphic and type-conditional shape rules evaluate together at this level:
        `ERR_INSPECTION_SUBJECT_MISMATCH`, `ERR_ESC_PLAN_NOT_APPROVED` at inspection
        creation, `ERR_ENFORCEMENT_SUBJECT_INVALID`,
        `ERR_SOURCE_INSPECTION_NOT_FINALIZED` and
        `ERR_OBSERVATION_TYPE_FIELDS_INVALID` (all 422)."

        Design: Corner/validations/observation_field_sets_must_match_the_observation_type_discriminator
        """
        bodies = [
            (
                {
                    "observation_type": "DRY_WEATHER_SCREENING",
                    "observed_at": OBSERVED_AT,
                    "dry_weather_flow_present": True,
                    "pollutant_concentration_mg_per_l": 0.30,
                    "runoff_volume_kl": 100.00,
                },
                IDDE_HEADERS,
            ),
            (
                {
                    "observation_type": "DRY_WEATHER_SCREENING",
                    "observed_at": OBSERVED_AT,
                    "indicator_bacteria_mpn": 400.0,
                },
                IDDE_HEADERS,
            ),
            (
                {
                    "observation_type": "WET_WEATHER_SAMPLE",
                    "observed_at": OBSERVED_AT,
                    "pollutant_concentration_mg_per_l": 0.30,
                },
                OPERATIONS_HEADERS,
            ),
            (
                {
                    "observation_type": "WET_WEATHER_SAMPLE",
                    "observed_at": OBSERVED_AT,
                    "pollutant_concentration_mg_per_l": 0.30,
                    "runoff_volume_kl": 100.00,
                    "indicator_ammonia_mg_per_l": 0.10,
                },
                OPERATIONS_HEADERS,
            ),
        ]
        for body, headers in bodies:
            validate_error(
                _post_observation(outfall["id"], body, headers),
                ApiErrorId.ERR_OBSERVATION_TYPE_FIELDS_INVALID.value,
                422,
            )

        stored = fx.read_outfall(outfall["id"])
        assert stored["screening_count"] == 0, (
            f"no rejected body was counted, got {stored['screening_count']}"
        )
        assert stored["screening_status"] == "NOT_SCREENED", (
            f"the outfall has still never been screened, got {stored['screening_status']}"
        )


class TestTheSweepingLogTouchesButNeverOverlaps:
    """A half-open interval, an overlap and a monthly ceiling, in that order."""

    @pytest.fixture
    def swept_outfall(self, active_program):
        """OF-01 capped at 40.00 lane miles a month, holding two touching runs."""
        outfall = active_program["outfalls"]["OF-01"]
        fx.append_sweeping_run(outfall["id"], "2026-08-01", "2026-08-10", 25.00)
        fx.append_sweeping_run(outfall["id"], "2026-08-10", "2026-08-20", 15.00)
        return outfall

    def test_06_a_run_starting_the_day_the_last_one_ended_is_accepted(
        self, active_program
    ):
        """The interval excludes its end date, so 2026-08-10 is free.

        PRD: "A sweeping run's interval is half-open, running from `run_start_date`
        inclusive to `run_end_date` exclusive, and two runs on the same outfall may not
        overlap. A run starting on the very day a previous run ends is therefore accepted;
        a genuine overlap is refused with `ERR_SWEEPING_RUN_OVERLAP`." And: "Each accepted
        run is appended to the outfall's append-only `sweeping_runs` list as an entry
        holding `run_start_date`, `run_end_date` and `lane_miles_swept`, and raises the
        outfall's `swept_lane_miles_ytd`, which is the sum of `lane_miles_swept` over the
        whole list to 2 decimal places."

        Design: Corner/validations/sweeping_runs_touch_at_the_boundary_but_may_not_overlap_or_exceed_monthly_capacity
        """
        outfall = active_program["outfalls"]["OF-01"]
        fx.append_sweeping_run(outfall["id"], "2026-08-01", "2026-08-10", 25.00)

        validate_success(
            api_client.create_sweeping_run(
                outfall["id"],
                factories.sweeping_run_payload("2026-08-10", "2026-08-20", 15.00),
                OPERATIONS_HEADERS,
            ),
            200,
        )

        stored = fx.read_outfall(outfall["id"])
        assert stored["swept_lane_miles_ytd"] == pytest.approx(40.00, abs=0.01), (
            "25.00 and 15.00 sum to the month's whole capacity, got "
            f"{stored['swept_lane_miles_ytd']}"
        )
        assert len(stored["sweeping_runs"]) == 2, "both runs are on the log"

    def test_07_a_genuine_overlap_answers_before_the_monthly_ceiling(
        self, swept_outfall
    ):
        """Thirty more lane miles breach both rules, and the overlap wins.

        PRD: "A sweeping run's interval is half-open, running from `run_start_date`
        inclusive to `run_end_date` exclusive, and two runs on the same outfall may not
        overlap. A run starting on the very day a previous run ends is therefore accepted;
        a genuine overlap is refused with `ERR_SWEEPING_RUN_OVERLAP`." And:
        "**Sweeping-run overlap.** `ERR_SWEEPING_RUN_OVERLAP` (409)." And: "**Aggregate
        capacity.** `ERR_SWEEPING_CAPACITY_EXCEEDED` (422), evaluated last because each
        individual run is plausible and only the monthly total is not."

        Design: Corner/validations/sweeping_runs_touch_at_the_boundary_but_may_not_overlap_or_exceed_monthly_capacity
        """
        response = api_client.create_sweeping_run(
            swept_outfall["id"],
            factories.sweeping_run_payload("2026-08-19", "2026-08-25", 30.00),
            OPERATIONS_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_SWEEPING_RUN_OVERLAP.value, 409)

        stored = fx.read_outfall(swept_outfall["id"])
        assert stored["swept_lane_miles_ytd"] == pytest.approx(40.00, abs=0.01), (
            "the refused run added nothing, got "
            f"{stored['swept_lane_miles_ytd']}"
        )

    def test_08_a_full_month_refuses_even_a_hundredth_of_a_lane_mile(
        self, swept_outfall
    ):
        """August already holds its 40.00, and the cap is not a tolerance.

        PRD: "Separately, the lane miles attributed to any one calendar month — a run is
        attributed to the month of its `run_start_date` — may not exceed the outfall's
        `sweeping_capacity_lane_miles_per_month`; a run that would push the month's total
        past capacity is refused with `ERR_SWEEPING_CAPACITY_EXCEEDED`, even though the
        individual run looks perfectly plausible on its own."

        Design: Corner/validations/sweeping_runs_touch_at_the_boundary_but_may_not_overlap_or_exceed_monthly_capacity
        """
        response = api_client.create_sweeping_run(
            swept_outfall["id"],
            factories.sweeping_run_payload("2026-08-21", "2026-08-28", 0.01),
            OPERATIONS_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_SWEEPING_CAPACITY_EXCEEDED.value, 422)

    def test_09_the_next_calendar_month_starts_from_zero_again(self, swept_outfall):
        """The ceiling is monthly, attributed by the start date, not annual.

        PRD: "Separately, the lane miles attributed to any one calendar month — a run is
        attributed to the month of its `run_start_date` — may not exceed the outfall's
        `sweeping_capacity_lane_miles_per_month`; a run that would push the month's total
        past capacity is refused with `ERR_SWEEPING_CAPACITY_EXCEEDED`, even though the
        individual run looks perfectly plausible on its own."

        Design: Corner/validations/sweeping_runs_touch_at_the_boundary_but_may_not_overlap_or_exceed_monthly_capacity
        """
        validate_success(
            api_client.create_sweeping_run(
                swept_outfall["id"],
                factories.sweeping_run_payload("2026-09-01", "2026-09-05", 40.00),
                OPERATIONS_HEADERS,
            ),
            200,
        )

        stored = fx.read_outfall(swept_outfall["id"])
        assert stored["swept_lane_miles_ytd"] == pytest.approx(80.00, abs=0.01), (
            "September's 40.00 joins August's 40.00, got "
            f"{stored['swept_lane_miles_ytd']}"
        )

    def test_10_the_log_holds_the_accepted_runs_and_nothing_else(self, swept_outfall):
        """Two refusals between three acceptances leave three entries.

        PRD: "Each accepted run is appended to the outfall's append-only `sweeping_runs`
        list as an entry holding `run_start_date`, `run_end_date` and `lane_miles_swept`,
        and raises the outfall's `swept_lane_miles_ytd`, which is the sum of
        `lane_miles_swept` over the whole list to 2 decimal places." And: "Nothing is
        persisted when a request is rejected — no partial writes, no counter increments,
        no cascades."

        Design: Corner/validations/sweeping_runs_touch_at_the_boundary_but_may_not_overlap_or_exceed_monthly_capacity
        """
        validate_error(
            api_client.create_sweeping_run(
                swept_outfall["id"],
                factories.sweeping_run_payload("2026-08-19", "2026-08-25", 30.00),
                OPERATIONS_HEADERS,
            ),
            ApiErrorId.ERR_SWEEPING_RUN_OVERLAP.value,
            409,
        )
        validate_error(
            api_client.create_sweeping_run(
                swept_outfall["id"],
                factories.sweeping_run_payload("2026-08-21", "2026-08-28", 0.01),
                OPERATIONS_HEADERS,
            ),
            ApiErrorId.ERR_SWEEPING_CAPACITY_EXCEEDED.value,
            422,
        )
        fx.append_sweeping_run(swept_outfall["id"], "2026-09-01", "2026-09-05", 40.00)

        stored = fx.read_outfall(swept_outfall["id"])
        assert len(stored["sweeping_runs"]) == 3, (
            f"only the accepted runs were appended, got {len(stored['sweeping_runs'])}"
        )
        logged = {
            (
                run["run_start_date"],
                run["run_end_date"],
                round(float(run["lane_miles_swept"]), 2),
            )
            for run in stored["sweeping_runs"]
        }
        assert logged == {
            ("2026-08-01", "2026-08-10", 25.00),
            ("2026-08-10", "2026-08-20", 15.00),
            ("2026-09-01", "2026-09-05", 40.00),
        }, f"each entry keeps its own dates and lane miles, got {logged}"
        assert stored["swept_lane_miles_ytd"] == pytest.approx(80.00, abs=0.01), (
            f"the total is the sum of the three, got {stored['swept_lane_miles_ytd']}"
        )
