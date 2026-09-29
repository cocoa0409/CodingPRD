"""Corner queue - section cross_cutting_complexity_layers, part D: the dual wind-down bases."""
from test_helpers import (
    COMMITTEE_ID,
    approve_plan,
    calibrate,
    corridor,
    draft_plan,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    post_observation,
    read_respondent,
    score_respondent,
    submit_plan,
    validate_success,
)
from test_helpers.fixtures import RM

_OBSERVATIONS = (
    ("2026-04", 999.00),
    ("2026-05", 50000.00),
    ("2026-06", 300000.00),
    ("2026-07", 100000.00),
)


def _respondent_with_history(name, swift_bic):
    """Identical respondent, identical calibrated corridor, identical four observations."""
    respondent = licensed_respondent(
        "DE", legal_name=name, swift_bic=swift_bic,
        expected_monthly_volume_usd=100000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    assert score_respondent(rid, "ONBOARDING_PROVISIONAL")["risk_rating"] == "LOW"
    profile = open_profile(
        rid, [corridor("DE", 100000.00, 100)],
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-12-31T23:59:59Z",
    )
    calibrated = calibrate(profile["id"])
    assert calibrated["corridor_thresholds"][0]["usd_threshold"] == 149500.00
    assert calibrated["corridor_thresholds"][0]["count_threshold"] == 150
    assert calibrated["aggregate_usd_threshold"] == 164450.00
    assert calibrated["hold_threshold_usd"] == 16445.00
    for period_month, aggregate_usd in _OBSERVATIONS:
        post_observation(
            profile["id"], period_month, "DE", aggregate_usd=aggregate_usd, txn_count=100
        )
    return rid


def test_the_two_wind_down_bases_diverge_on_byte_identical_respondents(api):
    """Two respondents built from byte-identical data differ only in cap_basis, so the whole
    delta is attributable to the variant: the declared basis ignores what flowed while the
    chronological basis drops the oldest of four months and caps one of the three it keeps.

    Design: Corner/cross_cutting_complexity_layers/the_two_wind_down_bases_diverge_on_byte_identical_respondents
    """
    new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )
    rid_a = _respondent_with_history("A Bank AG", "ABNKDEFF")
    rid_b = _respondent_with_history("B Bank AG", "BBNKDEFF")

    plan_a = draft_plan(
        rid_a, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=0,
    )
    plan_b = draft_plan(
        rid_b, RM, termination_reason="COMMERCIAL", cap_basis="CHRONOLOGICAL_ACTUAL",
        original_obligation_cents=0,
    )
    assert plan_a["notice_period_days"] == 90
    assert plan_b["notice_period_days"] == 90
    assert submit_plan(plan_a["id"])["state"] == "PENDING_APPROVAL"
    assert submit_plan(plan_b["id"])["state"] == "PENDING_APPROVAL"

    approved_a = approve_plan(plan_a["id"])
    assert approved_a["state"] == "APPROVED"
    assert approved_a["cap_basis"] == "FORWARD_PROJECTED"
    assert approved_a["notice_period_days"] == 90
    assert approved_a["wind_down_cap_usd"] == 180000.00
    assert approved_a["approved_by_user_id"] == COMMITTEE_ID

    approved_b = approve_plan(plan_b["id"])
    assert approved_b["state"] == "APPROVED"
    assert approved_b["cap_basis"] == "CHRONOLOGICAL_ACTUAL"
    assert approved_b["notice_period_days"] == 90
    assert approved_b["wind_down_cap_usd"] == 213337.49
    assert approved_b["approved_by_user_id"] == COMMITTEE_ID

    delta = round(approved_b["wind_down_cap_usd"] - approved_a["wind_down_cap_usd"], 2)
    assert delta == 33337.49
    assert approved_b["wind_down_cap_usd"] != 160452.68

    for rid in (rid_a, rid_b):
        exiting = read_respondent(rid)
        assert exiting["dd_state"] == "EXITING"
        assert exiting["payment_posture"] == "WIND_DOWN_ONLY"
    assert validate_success(api.get_closure_plan(plan_a["id"], RM))["state"] == "APPROVED"
