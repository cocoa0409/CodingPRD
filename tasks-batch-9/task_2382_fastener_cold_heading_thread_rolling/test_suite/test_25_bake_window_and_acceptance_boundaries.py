"""Threshold ticks where the plant's verdict flips.

Two limits are probed at the exact instant and the exact piece count where the
answer changes: the hydrogen-embrittlement relief bake, which may still start at
a delay of exactly 4.000 hours after ``plated_at`` but not one minute later, and
the normal-inspection sampling plan, whose ``acceptance_number`` stops being zero
once ``sample_size`` reaches 20. The logical plant clock is driven so the bake
start lands precisely on the bound, and the lot's ``available_count`` is driven to
400 and 361 pieces so the derived sample size lands precisely on 20 and 19.
"""

from typing import Any, Dict, Optional

import pytest

from test_helpers import (
    ApiErrorId,
    assert_lot_piece_ledger,
    assert_lot_test,
    assert_plating_run,
    assert_versions_incremented,
    expected_normal_sample_size,
    factories,
    fixtures,
    is_iso8601_timestamp,
    round_half_up,
    validate_error,
    validate_paginated,
    validate_success,
)

# A plated CLASS_10_9 part: he_bake_required is true and he_bake_min_minutes 240.
_PLATED_SPEC: Dict[str, Any] = {
    "part_number": "BX-M8-109",
    "strength_class": "CLASS_10_9",
    "qualification_program": "AUTOMOTIVE_PPAP",
    "plating_spec": "ZINC_CLEAR",
    "blank_mass_g": 20.0,
    "thread_timing": "BEFORE_HEAT_TREAT",
    "required_secondary_ops": ["THREAD_ROLL"],
    "min_core_hardness_hv": 304,
    "max_core_hardness_hv": 361,
    "max_decarb_depth_mm": 0.150,
}

# The same part with no finish at all, so the lot is testable straight from
# HEAT_TREATED and no bake ever runs.
_UNPLATED_SPEC: Dict[str, Any] = dict(_PLATED_SPEC, part_number="NP-M8-088", plating_spec="NONE")

_BAKE_TEMP_C = 210.0
_BAKE_DURATION_MIN = 240


def _plated_run(plated_at: str, scheduled_at: Optional[str] = None):
    """A CLASS_10_9 lot with one plating run in ``PLATED``, plated at ``plated_at``."""
    env = fixtures.setup_heat_treated_lot(spec_overrides=dict(_PLATED_SPEC))
    spec = env["spec"]
    assert spec["he_bake_required"] is True, (
        f"A ZINC_CLEAR CLASS_10_9 part needs a relief bake, got "
        f"he_bake_required={spec['he_bake_required']}"
    )
    assert spec["he_bake_min_minutes"] == 240, (
        f"Expected he_bake_min_minutes 240 for CLASS_10_9, got {spec['he_bake_min_minutes']}"
    )
    if scheduled_at is not None:
        fixtures.set_clock(scheduled_at)
    run = fixtures.schedule_plating(env["lot"]["id"])
    run = fixtures.complete_plating(run["id"], at=plated_at)
    assert run["status"] == "PLATED", f"Expected PLATED after completing plating, got {run['status']}"
    return env, run


def _newest_plating_run(api, production_lot_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """The lot's newest plating run; the listing is newest first."""
    items, _ = validate_paginated(api.list_lot_plating_runs(production_lot_id, headers))
    assert items, f"Expected at least one plating run on lot {production_lot_id}"
    return items[0]


def _heat_treated_unplated_lot(pieces_out: int) -> Dict[str, Any]:
    """An unplated lot in ``HEAT_TREATED`` holding exactly ``pieces_out`` pieces."""
    env = fixtures.setup_heat_treated_lot(
        unplated=True,
        planned_pieces=500,
        headed_count=480,
        heading_scrap_count=20,
        ops=[
            {
                "op_type": "THREAD_ROLL",
                "sequence_no": 1,
                "pieces_out": pieces_out,
                "machine_code": "TR-1",
            }
        ],
        spec_overrides=dict(_UNPLATED_SPEC),
    )
    lot = env["lot"]
    assert lot["process_state"] == "HEAT_TREATED", (
        f"Expected HEAT_TREATED before testing, got {lot['process_state']}"
    )
    assert lot["available_count"] == pieces_out, (
        f"Expected available_count {pieces_out}, got {lot['available_count']} before sampling"
    )
    return env


# ---------------------------------------------------------------------------
# The four-hour relief bake window
# ---------------------------------------------------------------------------
class TestReliefBakeDelayBoundary:
    """The inclusive four-hour bound on ``bake_delay_hours``."""

    def test_bake_started_at_exactly_four_hours_after_plating_is_accepted(
        self, api, heat_treat_headers
    ):
        """A bake begun 4.000 hours after plating still opens: the bound is inclusive.

        PRD: "The bake must start promptly: `bake_delay_hours` is the elapsed time from `plated_at` to now, expressed in hours — the elapsed seconds divided by three thousand six hundred — rounded half up to three decimal places, and it must be at most 4.0 hours; the bound is inclusive, so a delay of exactly 4.000 hours still passes, while anything longer is refused with `ERR_HE_BAKE_WINDOW_MISSED`."

        PRD: "On success the run moves `PLATED → BAKING`, `bake_started_at` is stamped from the logical clock, `bake_delay_hours` and both bake parameters are recorded, and the run's `version` increments by 1."

        Design: Difficulty/boundary_precision_check/relief_bake_delay_exactly_four_hours_passes_one_minute_later_fails
        """
        env, plated = _plated_run("2026-09-02T02:00:00Z")

        fixtures.set_clock("2026-09-02T06:00:00Z")
        run = validate_success(
            api.start_bake(
                plated["id"],
                factories.start_bake_payload(
                    bake_temp_c=_BAKE_TEMP_C, bake_duration_min=_BAKE_DURATION_MIN
                ),
                heat_treat_headers,
            )
        )

        assert run["status"] == "BAKING", (
            f"Expected BAKING at a delay of exactly 4.000 hours, got {run['status']}"
        )
        assert run["bake_delay_hours"] == pytest.approx(4.000, abs=0.001), (
            f"Expected bake_delay_hours 4.000, got {run['bake_delay_hours']}"
        )
        assert run["bake_temp_c"] == pytest.approx(_BAKE_TEMP_C, abs=0.001), (
            f"Expected bake_temp_c {_BAKE_TEMP_C}, got {run['bake_temp_c']}"
        )
        assert run["bake_duration_min"] == _BAKE_DURATION_MIN, (
            f"Expected bake_duration_min {_BAKE_DURATION_MIN}, got {run['bake_duration_min']}"
        )
        assert is_iso8601_timestamp(run["bake_started_at"]), (
            f"bake_started_at must be an ISO 8601 stamp, got {run['bake_started_at']!r}"
        )
        assert run["bake_started_at"].startswith("2026-09-02T06:00:00"), (
            f"Expected bake_started_at at the logical clock 2026-09-02T06:00:00Z, "
            f"got {run['bake_started_at']}"
        )
        assert_versions_incremented(plated, run)
        assert_plating_run(run)

        lot = fixtures.read_lot(env["lot"]["id"])
        assert lot["process_state"] == "PLATED", (
            f"Starting the bake leaves the lot at PLATED, got {lot['process_state']}"
        )

    def test_bake_started_one_minute_past_four_hours_is_refused(
        self, api, heat_treat_headers
    ):
        """One minute later the delay computes past 4.0 hours and the bake is refused.

        PRD: "The bake must start promptly: `bake_delay_hours` is the elapsed time from `plated_at` to now, expressed in hours — the elapsed seconds divided by three thousand six hundred — rounded half up to three decimal places, and it must be at most 4.0 hours; the bound is inclusive, so a delay of exactly 4.000 hours still passes, while anything longer is refused with `ERR_HE_BAKE_WINDOW_MISSED`."

        PRD: "On success the run moves `PLATED → BAKING`, `bake_started_at` is stamped from the logical clock, `bake_delay_hours` and both bake parameters are recorded, and the run's `version` increments by 1."

        Design: Difficulty/boundary_precision_check/relief_bake_delay_exactly_four_hours_passes_one_minute_later_fails
        """
        env, plated = _plated_run("2026-09-02T02:00:00Z")

        fixtures.set_clock("2026-09-02T06:01:00Z")
        validate_error(
            api.start_bake(
                plated["id"],
                factories.start_bake_payload(
                    bake_temp_c=_BAKE_TEMP_C, bake_duration_min=_BAKE_DURATION_MIN
                ),
                heat_treat_headers,
            ),
            ApiErrorId.ERR_HE_BAKE_WINDOW_MISSED.value,
        )

        run = _newest_plating_run(api, env["lot"]["id"], heat_treat_headers)
        assert run["id"] == plated["id"], "The newest plating run is the one the bake was refused on"
        assert run["status"] == "PLATED", (
            f"A refused bake leaves the run at PLATED, got {run['status']}"
        )
        assert run["bake_started_at"] is None, (
            f"A refused bake stamps no bake_started_at, got {run['bake_started_at']!r}"
        )
        assert run["bake_delay_hours"] is None, (
            f"A refused bake records no bake_delay_hours, got {run['bake_delay_hours']!r}"
        )
        assert run["version"] == plated["version"], (
            f"A refused bake mutates nothing, so version stays {plated['version']}, "
            f"got {run['version']}"
        )

        lot = fixtures.read_lot(env["lot"]["id"])
        assert lot["process_state"] == "PLATED", (
            f"A refused bake leaves the lot at PLATED, got {lot['process_state']}"
        )
        assert lot["disposition"] == "IN_PROCESS", (
            f"A refused bake places no hold, got disposition {lot['disposition']}"
        )

    def test_bake_delay_is_measured_from_plated_at_not_from_scheduling(
        self, api, heat_treat_headers
    ):
        """The relief clock starts at ``plated_at``, so a run scheduled six hours earlier still passes.

        PRD: "The run moves `SCHEDULED → PLATED` and stamps `plated_at` from the logical clock, which starts the embrittlement relief clock ticking."

        PRD: "The bake must start promptly: `bake_delay_hours` is the elapsed time from `plated_at` to now, expressed in hours — the elapsed seconds divided by three thousand six hundred — rounded half up to three decimal places, and it must be at most 4.0 hours; the bound is inclusive, so a delay of exactly 4.000 hours still passes, while anything longer is refused with `ERR_HE_BAKE_WINDOW_MISSED`."

        Design: Difficulty/boundary_precision_check/relief_bake_delay_exactly_four_hours_passes_one_minute_later_fails
        """
        env, plated = _plated_run(
            "2026-09-02T04:00:00Z", scheduled_at="2026-09-02T02:00:00Z"
        )
        assert plated["created_at"].startswith("2026-09-02T02:00:00"), (
            f"Expected the run scheduled at 2026-09-02T02:00:00Z, got {plated['created_at']}"
        )
        assert plated["plated_at"].startswith("2026-09-02T04:00:00"), (
            f"Expected plated_at 2026-09-02T04:00:00Z, got {plated['plated_at']}"
        )

        fixtures.set_clock("2026-09-02T08:00:00Z")
        run = validate_success(
            api.start_bake(
                plated["id"],
                factories.start_bake_payload(
                    bake_temp_c=_BAKE_TEMP_C, bake_duration_min=_BAKE_DURATION_MIN
                ),
                heat_treat_headers,
            )
        )

        assert run["bake_delay_hours"] == pytest.approx(4.000, abs=0.001), (
            "Six hours after scheduling but exactly four after plating, bake_delay_hours "
            f"must be 4.000, got {run['bake_delay_hours']}"
        )
        assert run["status"] == "BAKING", (
            f"Expected BAKING for a delay of exactly 4.000 hours from plated_at, got {run['status']}"
        )
        assert run["bake_started_at"].startswith("2026-09-02T08:00:00"), (
            f"Expected bake_started_at 2026-09-02T08:00:00Z, got {run['bake_started_at']}"
        )


# ---------------------------------------------------------------------------
# The acceptance number under normal inspection
# ---------------------------------------------------------------------------
class TestNormalSamplingAcceptanceBoundary:
    """``acceptance_number`` is 1 once ``sample_size`` reaches 20, and 0 below it."""

    def test_four_hundred_pieces_give_sample_twenty_and_tolerate_one_failure(
        self, api, inspector_headers
    ):
        """400 available pieces sample 20, so the acceptance number is 1 and one failure ACCEPTs.

        PRD: "Under **normal inspection**, `sample_size` is the greater of 8 and the square root of the lot's `available_count` raised upward to the next whole piece, and `acceptance_number` is 1 when that `sample_size` is at least 20 and 0 otherwise — so a single failure is tolerated on any lot holding 400 or more available pieces, and a lot holding fewer than 8 available pieces cannot be sampled at all."

        PRD: "The verdict is a straight comparison against the frozen plan: `ACCEPT` when `total_failures` is at most `acceptance_number`, and `REJECT` when it is greater."

        PRD: "On `ACCEPT` the test moves `PENDING → ACCEPT`, the lot's `achieved_strength_class` is derived, `risk_score_final` is computed, and the lot moves `TESTING → TESTED`."

        Design: Difficulty/boundary_precision_check/sampling_acceptance_number_flips_at_sample_size_twenty
        """
        env = _heat_treated_unplated_lot(400)
        lot_id = env["lot"]["id"]

        lot_test = validate_success(
            api.create_lot_test(factories.create_lot_test_payload(lot_id), inspector_headers),
            201,
        )
        assert lot_test["severity"] == "NORMAL", (
            f"Expected NORMAL severity on a low-risk first test, got {lot_test['severity']}"
        )
        assert lot_test["sample_size"] == 20, (
            f"Expected sample_size 20 for 400 available pieces, got {lot_test['sample_size']}"
        )
        assert lot_test["sample_size"] == expected_normal_sample_size(400), (
            "sample_size must be max(8, ceil(sqrt(available_count)))"
        )
        assert lot_test["acceptance_number"] == 1, (
            f"A sample size of 20 tolerates one failure, got acceptance_number "
            f"{lot_test['acceptance_number']}"
        )

        lot_testing = fixtures.read_lot(lot_id)
        assert lot_testing["process_state"] == "TESTING", (
            f"Expected TESTING once the test is open, got {lot_testing['process_state']}"
        )
        assert lot_testing["destructive_test_count"] == 20, (
            f"The destroyed sample is 20 pieces, got {lot_testing['destructive_test_count']}"
        )
        assert lot_testing["available_count"] == 380, (
            f"Expected 380 available pieces after sampling 20, got {lot_testing['available_count']}"
        )
        assert_lot_piece_ledger(lot_testing)
        pre_test = lot_testing["risk_score_pre_test"]
        assert pre_test is not None, "risk_score_pre_test is computed when an unplated lot is tested"
        assert pre_test < 40.0, (
            f"A risk score under 40.0 is what keeps severity NORMAL, got {pre_test}"
        )

        closed = validate_success(
            api.record_lot_test_results(
                lot_test["id"],
                factories.lot_test_results_payload(
                    proof_load_failures=1,
                    tensile_failures=0,
                    min_measured_core_hardness_hv=322.0,
                ),
                inspector_headers,
            )
        )
        assert closed["total_failures"] == 1, (
            f"Expected total_failures 1, got {closed['total_failures']}"
        )
        assert closed["result"] == "ACCEPT", (
            f"One failure against acceptance_number 1 must ACCEPT, got {closed['result']}"
        )
        assert_lot_test(closed)

        lot_after = fixtures.read_lot(lot_id)
        assert lot_after["process_state"] == "TESTED", (
            f"An accepted test moves the lot to TESTED, got {lot_after['process_state']}"
        )
        assert lot_after["disposition"] == "IN_PROCESS", (
            f"An accepted test places no hold, got disposition {lot_after['disposition']}"
        )
        assert lot_after["achieved_strength_class"] == "CLASS_10_9", (
            "322 HV sits inside the specified CLASS_10_9 band 304-361, got "
            f"{lot_after['achieved_strength_class']}"
        )
        assert lot_after["risk_score_final"] == pytest.approx(
            round_half_up(pre_test + 12.5, 2), abs=0.001
        ), (
            f"Expected risk_score_final {round_half_up(pre_test + 12.5, 2)} for one failure, "
            f"got {lot_after['risk_score_final']}"
        )

    def test_three_hundred_sixty_one_pieces_give_sample_nineteen_and_reject_one_failure(
        self, api, inspector_headers
    ):
        """361 available pieces sample 19, so the acceptance number is 0 and one failure REJECTs.

        PRD: "Under **normal inspection**, `sample_size` is the greater of 8 and the square root of the lot's `available_count` raised upward to the next whole piece, and `acceptance_number` is 1 when that `sample_size` is at least 20 and 0 otherwise — so a single failure is tolerated on any lot holding 400 or more available pieces, and a lot holding fewer than 8 available pieces cannot be sampled at all."

        PRD: "The test's `destructive` flag defaults to true and the create payload offers no way to change it, so the sample is consumed: when `destructive` is true, the lot's `destructive_test_count` grows by `sample_size` and its `available_count` shrinks by the same amount, keeping the piece ledger balanced."

        PRD: "On `REJECT` the test moves `PENDING → REJECT`, `risk_score_final` is still computed, the lot's `disposition` moves to `HOLD` with `hold_source` of `TEST_REJECT`, and the lot's `process_state` stays at `TESTING` — which is exactly why a certificate drafted after a retest can still be pointing at the first, rejected test."

        Design: Difficulty/boundary_precision_check/sampling_acceptance_number_flips_at_sample_size_twenty
        """
        env = _heat_treated_unplated_lot(361)
        lot_id = env["lot"]["id"]

        lot_test = validate_success(
            api.create_lot_test(factories.create_lot_test_payload(lot_id), inspector_headers),
            201,
        )
        assert lot_test["severity"] == "NORMAL", (
            f"Expected NORMAL severity on a low-risk first test, got {lot_test['severity']}"
        )
        assert lot_test["sample_size"] == 19, (
            f"Expected sample_size 19 for 361 available pieces, got {lot_test['sample_size']}"
        )
        assert lot_test["sample_size"] == expected_normal_sample_size(361), (
            "sample_size must be max(8, ceil(sqrt(available_count)))"
        )
        assert lot_test["acceptance_number"] == 0, (
            f"A sample size of 19 tolerates no failure, got acceptance_number "
            f"{lot_test['acceptance_number']}"
        )

        lot_testing = fixtures.read_lot(lot_id)
        assert lot_testing["destructive_test_count"] == 19, (
            f"The destroyed sample is 19 pieces, got {lot_testing['destructive_test_count']}"
        )
        assert lot_testing["available_count"] == 342, (
            f"Expected 342 available pieces after sampling 19, got {lot_testing['available_count']}"
        )
        assert_lot_piece_ledger(lot_testing)
        pre_test = lot_testing["risk_score_pre_test"]
        assert pre_test is not None, "risk_score_pre_test is computed when an unplated lot is tested"
        assert pre_test < 40.0, (
            f"A risk score under 40.0 is what keeps severity NORMAL, got {pre_test}"
        )

        closed = validate_success(
            api.record_lot_test_results(
                lot_test["id"],
                factories.lot_test_results_payload(
                    proof_load_failures=1,
                    tensile_failures=0,
                    min_measured_core_hardness_hv=322.0,
                ),
                inspector_headers,
            )
        )
        assert closed["total_failures"] == 1, (
            f"Expected total_failures 1, got {closed['total_failures']}"
        )
        assert closed["result"] == "REJECT", (
            f"One failure against acceptance_number 0 must REJECT, got {closed['result']}"
        )
        assert_lot_test(closed)

        lot_after = fixtures.read_lot(lot_id)
        assert lot_after["disposition"] == "HOLD", (
            f"A rejected test holds the lot, got disposition {lot_after['disposition']}"
        )
        assert lot_after["hold_source"] == "TEST_REJECT", (
            f"Expected hold_source TEST_REJECT, got {lot_after['hold_source']}"
        )
        assert lot_after["process_state"] == "TESTING", (
            f"A rejected test leaves process_state at TESTING, got {lot_after['process_state']}"
        )
        assert lot_after["risk_score_final"] == pytest.approx(
            round_half_up(pre_test + 12.5, 2), abs=0.001
        ), (
            f"Expected risk_score_final {round_half_up(pre_test + 12.5, 2)} for one failure, "
            f"got {lot_after['risk_score_final']}"
        )

    def test_acceptance_number_one_tolerates_exactly_one_failure_and_no_more(
        self, api, inspector_headers
    ):
        """At the same sample size of 20, a second failure tips the verdict to REJECT.

        PRD: "Under **normal inspection**, `sample_size` is the greater of 8 and the square root of the lot's `available_count` raised upward to the next whole piece, and `acceptance_number` is 1 when that `sample_size` is at least 20 and 0 otherwise — so a single failure is tolerated on any lot holding 400 or more available pieces, and a lot holding fewer than 8 available pieces cannot be sampled at all."

        PRD: "The verdict is a straight comparison against the frozen plan: `ACCEPT` when `total_failures` is at most `acceptance_number`, and `REJECT` when it is greater."

        PRD: "On `REJECT` the test moves `PENDING → REJECT`, `risk_score_final` is still computed, the lot's `disposition` moves to `HOLD` with `hold_source` of `TEST_REJECT`, and the lot's `process_state` stays at `TESTING` — which is exactly why a certificate drafted after a retest can still be pointing at the first, rejected test."

        Design: Difficulty/boundary_precision_check/sampling_acceptance_number_flips_at_sample_size_twenty
        """
        env = _heat_treated_unplated_lot(400)
        lot_id = env["lot"]["id"]

        lot_test = validate_success(
            api.create_lot_test(factories.create_lot_test_payload(lot_id), inspector_headers),
            201,
        )
        assert lot_test["sample_size"] == 20, (
            f"Expected sample_size 20 for 400 available pieces, got {lot_test['sample_size']}"
        )
        assert lot_test["acceptance_number"] == 1, (
            f"Expected acceptance_number 1 at a sample size of 20, got "
            f"{lot_test['acceptance_number']}"
        )

        pre_test = fixtures.read_lot(lot_id)["risk_score_pre_test"]
        assert pre_test is not None, "risk_score_pre_test is computed when an unplated lot is tested"

        closed = validate_success(
            api.record_lot_test_results(
                lot_test["id"],
                factories.lot_test_results_payload(
                    proof_load_failures=1,
                    tensile_failures=1,
                    min_measured_core_hardness_hv=322.0,
                ),
                inspector_headers,
            )
        )
        assert closed["total_failures"] == 2, (
            f"Expected total_failures 2, got {closed['total_failures']}"
        )
        assert closed["result"] == "REJECT", (
            f"Two failures exceed acceptance_number 1 and must REJECT, got {closed['result']}"
        )
        assert_lot_test(closed)

        lot_after = fixtures.read_lot(lot_id)
        assert lot_after["disposition"] == "HOLD", (
            f"A rejected test holds the lot, got disposition {lot_after['disposition']}"
        )
        assert lot_after["hold_source"] == "TEST_REJECT", (
            f"Expected hold_source TEST_REJECT, got {lot_after['hold_source']}"
        )
        assert lot_after["process_state"] == "TESTING", (
            f"A rejected test leaves process_state at TESTING, got {lot_after['process_state']}"
        )
        assert lot_after["risk_score_final"] == pytest.approx(
            round_half_up(pre_test + 25.0, 2), abs=0.001
        ), (
            f"Expected risk_score_final {round_half_up(pre_test + 25.0, 2)} for two failures, "
            f"got {lot_after['risk_score_final']}"
        )
