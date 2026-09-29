"""The two health-score variants over one identical observation window."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assert_deployment_state, assert_health_score
from test_helpers.test_users import RELIABILITY_1
from test_helpers.fixtures import (
    build_stack,
    close_window,
    record_window,
    set_clock,
)


def test_recording_a_window_publishes_the_provisional_variant(api):
    """A recorded observation window reports the provisional variant.

    PRD 3.5: "Recording a window computes the composite health score under the
    PROVISIONAL variant" and "mirrors the PROVISIONAL score into the
    deployment's health_score_provisional". The worked example pins 10,000
    predictions, 2,000 labelled, 1,700 correct, an observed positive rate of
    0.32 and an observed p95 of 240 ms against baselines 0.82 / 0.30 / 200 to a
    PROVISIONAL score of 86.08.

    Design: Difficulty/dual_variant_calc/health_score_provisional_vs_final_on_monitoring_window
    """
    stack = build_stack(api, ramps=1)
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )

    assert_health_score(window, health_score=86.08, variant="PROVISIONAL")
    assert_health_score(window, baseline_delta_pct=4.08)

    deployment = get_success_data(api.get_deployment(stack.deployment_id, RELIABILITY_1))
    assert deployment["health_score_provisional"] == 86.08


def test_closing_the_window_republishes_it_under_the_final_variant(api):
    """Closing the same window swaps in the final variant's denominator.

    PRD 3.5: "Closing a PERFORMANCE window recomputes the composite health
    score under the FINAL variant, mirrors it into the deployment's
    health_score_final". The FINAL accuracy proxy divides by every served
    prediction with the unlabelled remainder imputed at 0.60, which turns the
    same stored inputs into 77.08 and a baseline delta of -4.92.

    Design: Difficulty/dual_variant_calc/health_score_provisional_vs_final_on_monitoring_window
    """
    stack = build_stack(api, ramps=1)
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )
    set_clock(api, "2026-08-04T00:00:00Z")
    closed = close_window(api, window["id"])

    assert closed["status"] == "CLOSED"
    assert_health_score(closed, health_score=77.08, variant="FINAL")
    assert_health_score(closed, baseline_delta_pct=-4.92)
    assert round(86.08 - closed["health_score"], 2) == 9.00

    deployment = get_success_data(api.get_deployment(stack.deployment_id, RELIABILITY_1))
    assert deployment["health_score_final"] == 77.08
    assert deployment["health_score_provisional"] == 86.08
    assert_deployment_state(deployment, health_state="HEALTHY")


def test_final_variant_read_over_an_open_window_is_not_persisted(api):
    """The on-demand FINAL read leaves the stored window untouched.

    PRD 3.5: "score_variant selects which variant to report ... A FINAL score
    over a window that is still OPEN is computed on demand and is not
    persisted." So the health read answers 77.08 for FINAL and 86.08 for
    PROVISIONAL while the window row itself still reports 86.08.

    Design: Difficulty/dual_variant_calc/health_score_provisional_vs_final_on_monitoring_window
    """
    stack = build_stack(api, ramps=1)
    window = record_window(
        api,
        stack.deployment_id,
        stack.version_id,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )

    provisional = get_success_data(
        api.get_deployment_health(
            stack.deployment_id, RELIABILITY_1, {"score_variant": "PROVISIONAL"}
        )
    )
    assert_health_score(provisional, health_score=86.08)

    final = get_success_data(
        api.get_deployment_health(
            stack.deployment_id, RELIABILITY_1, {"score_variant": "FINAL"}
        )
    )
    assert_health_score(final, health_score=77.08)

    stored = validate_success(api.get_monitoring_window(window["id"], RELIABILITY_1))
    assert stored["status"] == "OPEN"
    assert_health_score(stored, health_score=86.08, variant="PROVISIONAL")
