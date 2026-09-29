"""Read-after-write agreement across the intake monitoring cascade."""
import pytest

from test_helpers import (
    CLINICAL_STAFF,
    create_community,
    create_resident,
    read_resident,
    record_observation,
    reviews_for,
    set_clock,
)


def test_one_observation_settles_every_metric_and_the_review_before_it_answers(api):
    """The second observation's own write is enough: the resident read taken straight afterwards
    already carries the current weight, both trend variants, the seven-day mean and the score, the
    opened review snapshots that same score, and an immediate second read drifts nowhere.

    PRD: "**Hop 2** evaluates the plan-of-care trigger, and it runs only after the weight variants,
    the intake average and the risk score have been written."

    Design: Corner/consistency_model/intake_observation_response_and_reads_agree_immediately
    """
    set_clock("2026-08-02T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Greta Halvorsen", baseline_weight_kg=78.0
    )
    record_observation(resident["id"], "2026-08-02", "LUNCH", 60, weight_kg=80.0)
    set_clock("2026-08-20T08:00:00Z")

    second = record_observation(resident["id"], "2026-08-20", "LUNCH", 80, weight_kg=76.0)

    assert second["weight_kg"] == pytest.approx(76.0, abs=0.01)
    assert second["recorded_by_user_id"] == CLINICAL_STAFF["X-User-ID"]

    monitored = read_resident(resident["id"])
    assert monitored["current_weight_kg"] == pytest.approx(76.0, abs=0.01)
    assert monitored["rolling_30d_weight_change_pct"] == pytest.approx(-5.00, abs=0.01)
    assert monitored["baseline_weight_change_pct"] == pytest.approx(-2.56, abs=0.01)
    assert monitored["avg_intake_pct_7d"] == pytest.approx(80.00, abs=0.01)
    assert monitored["intake_risk_score"] == pytest.approx(30.00, abs=0.01)

    reviews = reviews_for(resident["id"], status="OPEN")
    assert len(reviews) == 1
    assert reviews[0]["trigger_observation_id"] == second["id"]
    assert reviews[0]["trigger_reason"] == "WEIGHT_LOSS_30D"
    assert reviews[0]["risk_score_at_open"] == pytest.approx(
        monitored["intake_risk_score"], abs=0.01
    )

    again = read_resident(resident["id"])
    assert again["rolling_30d_weight_change_pct"] == pytest.approx(
        monitored["rolling_30d_weight_change_pct"], abs=0.01
    )
    assert again["intake_risk_score"] == pytest.approx(
        monitored["intake_risk_score"], abs=0.01
    )
