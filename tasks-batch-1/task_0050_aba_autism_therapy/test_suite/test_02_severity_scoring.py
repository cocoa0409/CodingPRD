"""Diagnostic-evaluation severity scoring: tiered, inclusive lower-bound
thresholds that compute severity_level and recommended_weekly_units at submit."""
from test_helpers import (
    get_success_data,
    create_payer,
    create_bcba,
    create_client,
    TEST_USERS,
    make_bcba_headers,
    factories,
)


def _draft_evaluation(api, assessment_score):
    payer = create_payer(api)
    bcba = create_bcba(api)
    client = create_client(api, insurance_payer_id=payer["id"])
    bcba_h = make_bcba_headers(bcba["id"])
    ev = get_success_data(
        api.create_evaluation(
            factories.create_evaluation_payload(client["id"], bcba["id"],
                                                assessment_score),
            bcba_h,
        )
    )
    return ev, bcba_h


def test_severe_score_computes_severe_and_160_units_on_submit(api):
    """PRD §3.2: "a score of 120 or more yields a `SEVERE` severity with 160
    recommended weekly units (forty hours per week)". PRD §3.2: "Both computed
    fields are written onto the evaluation at submission time."

    Design: Corner/entities/diagnostic_evaluation_severity_computed_input_ignored
    """
    ev, bcba_h = _draft_evaluation(api, 130)
    data = get_success_data(api.submit_evaluation(ev["id"], bcba_h))
    assert data["severity_level"] == "SEVERE", data["severity_level"]
    assert data["recommended_weekly_units"] == 160, data["recommended_weekly_units"]
    assert data["status"] == "SUBMITTED"


def test_score_at_60_is_moderate_inclusive_lower_bound(api):
    """PRD §3.2: "a score of at least 60 but below 120 yields a `MODERATE`
    severity with 100 recommended weekly units (twenty-five hours per week)".

    Design: Corner/entities/diagnostic_severity_moderate_boundary_at_60
    """
    ev, bcba_h = _draft_evaluation(api, 60)
    data = get_success_data(api.submit_evaluation(ev["id"], bcba_h))
    assert data["severity_level"] == "MODERATE", data["severity_level"]
    assert data["recommended_weekly_units"] == 100, data["recommended_weekly_units"]
