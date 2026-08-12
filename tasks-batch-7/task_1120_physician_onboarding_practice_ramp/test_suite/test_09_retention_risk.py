"""Retention risk snapshots: TRAILING vs LEADING dual variants and the pinned
per-term rounding order at the CRITICAL band boundary.

Component arithmetic referenced by the assertions (all rates 0..100):
  milestone_risk TRAILING = missed attested / attested; LEADING adds
    unreconciled due months over months due (PRD §3.9).
  panel_risk = shortfall below capacity * fill-curve expectation, per variant.
  sentiment_risk = mean of POSITIVE 0 / NEUTRAL 40 / CONCERN 70 / CRISIS 100.
  schedule_risk = shortfall of weekly_active_minutes below the requirement.
  score = round2(0.35*milestone) + round2(0.25*panel) + round2(0.25*sentiment)
          + round2(0.15*schedule), each term rounded half-up before summing.
"""
from test_helpers import (
    api_client, validate_success,
    TEST_USERS,
    setup_active_guarantee, setup_go_live,
    create_active_template, create_active_mentor, create_mentorship,
    record_check_in, set_clock, report_and_attest, get_case,
    create_snapshot_payload,
)

DIRECTOR = TEST_USERS["onboarding_director_headers"]
PM = TEST_USERS["practice_manager_headers"]
FINANCE = TEST_USERS["finance_analyst_headers"]


def _snap(case_id, variant):
    return validate_success(
        api_client.create_retention_snapshot(create_snapshot_payload(case_id, variant), DIRECTOR),
        201,
    )


def _components(data):
    return {
        "milestone_risk": round(data["milestone_risk"], 2),
        "panel_risk": round(data["panel_risk"], 2),
        "sentiment_risk": round(data["sentiment_risk"], 2),
        "schedule_risk": round(data["schedule_risk"], 2),
        "score": round(data["score"], 2),
    }


def _setup_divergence_scenario():
    """Executed pipeline with 800 weekly minutes, guarantee ACTIVE, months 1-2
    attested (attained then missed), month 3 left PENDING past its window
    (2027-09-15) without a sweep, one NEUTRAL check-in, clock at 2027-09-20."""
    ctx = setup_active_guarantee(full_name="Dr. Bree", panel_capacity=1000)
    case_id = ctx["case"]["id"]
    create_active_template(case_id, weekday=1, start_minute=480, end_minute=960)  # 480
    create_active_template(case_id, weekday=2, start_minute=480, end_minute=800)  # 320
    report_and_attest(case_id, 1, actual_wrvu=120, collections_cents=1200000)
    report_and_attest(case_id, 2, actual_wrvu=100, collections_cents=600000)
    mentor = create_active_mentor()
    assignment = create_mentorship(case_id, mentor["id"])
    record_check_in(assignment["id"], mentor["id"], "D30", "NEUTRAL")
    set_clock("2027-09-20T00:00:00Z")
    return ctx


def test_retention_score_trailing_variant_components(api):
    """PRD §3.9: "The `milestone_risk` differs by variant: `TRAILING` takes the attested months that were missed as a share of all attested months, expressed as a percentage, and is 0 when no month is attested"
    PRD §3.9: "The `panel_risk` compares the census with a ramp expectation: the case's current month offset is the number of months elapsed since `start_month`, never less than 1, and the expected fill is the panel's `capacity` multiplied by the fill-curve point for that month — ten, eighteen, twenty-six, thirty-four, forty-two, fifty, fifty-eight, sixty-five, seventy-one, seventy-seven, eighty-two, and eighty-five percent for months one through twelve — except that `LEADING` uses the following month's curve point, projecting next-month expectations."
    PRD §3.9: "The `sentiment_risk` is the mean, over every check-in recorded on every mentorship assignment of the case regardless of assignment status, of the sentiment mapping — `POSITIVE` scores 0, `NEUTRAL` 40, `CONCERN` 70, `CRISIS` 100 — and defaults to 50 when no check-in has been recorded."
    PRD §3.9: "The `schedule_risk` is the shortfall of the case's `weekly_active_minutes` below its specialty's required weekly minutes, as a percentage of that requirement, never negative."
    PRD §3.9: "The composite `score` weights the components: 0.35 for milestone risk, 0.25 for panel risk, 0.25 for sentiment risk, and 0.15 for schedule risk."
    PRD §3.9: "The `risk_band` maps the score with inclusive lower bounds: at least 75 is `CRITICAL`, at least 50 is `HIGH`, at least 25 is `MODERATE`, and anything lower is `LOW`."

    TRAILING here: milestone 1/2 -> 50.00; panel (260-0)/260 -> 100.00 at month
    offset 3 (1000 * 0.26 expected, census 0); sentiment 40.00 (one NEUTRAL);
    schedule (1200-800)/1200 -> 33.33; score 17.50+25.00+10.00+5.00 = 57.50.

    Design: Difficulty/dual_variant_calc/retention_score_trailing_vs_leading_diverge
    """
    ctx = _setup_divergence_scenario()
    data = _snap(ctx["case"]["id"], "TRAILING")
    comp = _components(data)
    assert comp == {
        "milestone_risk": 50.00, "panel_risk": 100.00,
        "sentiment_risk": 40.00, "schedule_risk": 33.33, "score": 57.50,
    }, f"TRAILING components mismatch: {comp}"
    assert data["risk_band"] == "HIGH"


def test_retention_score_leading_variant_diverges(api):
    """PRD §3.9: "`LEADING` instead divides the missed attested months plus the unreconciled months already due by the months due — the term months whose reporting window has closed by the logical clock — and is 0 when no month is due."
    PRD §3.9: "Because `TRAILING` uses only attested history and the current month's fill expectation while `LEADING` counts unreconciled elapsed months as missed and projects the next month's fill, identical underlying data yields a different score under the two variants."
    PRD §3.9: "Persisting a snapshot updates the case's `latest_risk_score` and `latest_risk_band` — both null until the first snapshot exists — sets `at_risk` true exactly when the new band is `HIGH` or `CRITICAL`, and increments the case's `version`."

    LEADING here on identical stored data: milestone (1 missed attested + 1
    unreconciled due) / 3 due -> 66.67; panel expectation projects month 4
    (1000 * 0.34 = 340, census 0) -> 100.00; sentiment 40.00; schedule 33.33;
    score 23.33+25.00+10.00+5.00 = 63.33.

    Design: Difficulty/dual_variant_calc/retention_score_trailing_vs_leading_diverge
    """
    ctx = _setup_divergence_scenario()
    case_id = ctx["case"]["id"]
    trailing = _snap(case_id, "TRAILING")
    leading = _snap(case_id, "LEADING")

    comp = _components(leading)
    assert comp == {
        "milestone_risk": 66.67, "panel_risk": 100.00,
        "sentiment_risk": 40.00, "schedule_risk": 33.33, "score": 63.33,
    }, f"LEADING components mismatch: {comp}"
    assert leading["risk_band"] == "HIGH"
    assert round(leading["score"], 2) != round(trailing["score"], 2), (
        "the two variants must diverge for identical stored data"
    )

    case = get_case(case_id)
    assert round(case["latest_risk_score"], 2) == 63.33
    assert case["latest_risk_band"] == "HIGH"
    assert case["at_risk"] is True


def _setup_rounding_scenario():
    """Go-live with capacity 2000 and 1224 weekly minutes; census 11; months
    1-3 attested with exactly one miss; templates then retired down to 24
    weekly minutes (freezing the panel); one CRISIS check-in; clock stays in
    June 2027 so the current month offset is 1."""
    ctx = setup_go_live(
        full_name="Dr. Dee", panel_capacity=2000, clock_after_ready="2027-06-05T00:00:00Z"
    )
    case_id = ctx["case"]["id"]
    # Fourth block brings the total to 1224 so the three retires leave exactly 24.
    create_active_template(case_id, weekday=4, start_minute=480, end_minute=504)
    validate_success(
        api_client.adjust_panel_census(ctx["panel"]["id"], {"delta": 11}, PM), 200
    )
    validate_success(
        api_client.activate_income_guarantee(ctx["guarantee"]["id"], FINANCE), 200
    )
    report_and_attest(case_id, 1, actual_wrvu=120, collections_cents=1200000)  # attained
    report_and_attest(case_id, 2, actual_wrvu=160, collections_cents=800000)   # attained
    report_and_attest(case_id, 3, actual_wrvu=100, collections_cents=900000)   # missed
    for template in ctx["templates"]:
        validate_success(api_client.retire_schedule_template(template["id"], PM), 200)
    mentor = create_active_mentor()
    assignment = create_mentorship(case_id, mentor["id"])
    record_check_in(assignment["id"], mentor["id"], "D30", "CRISIS")
    return ctx


def test_retention_score_per_term_rounding_order_pinned_components(api):
    """PRD §2.11: "Retention-risk component values are rounded to exactly 2 decimal places, round half-up, before weighting, and each weighted term is likewise rounded to 2 decimal places half-up before the terms are summed; summing raw terms and rounding once at the end is explicitly not the contract."
    PRD §3.9: "The composite `score` weights the components: 0.35 for milestone risk, 0.25 for panel risk, 0.25 for sentiment risk, and 0.15 for schedule risk."

    Here: milestone 1 missed of 3 attested -> 33.33; panel expected 200 (2000 *
    0.10 at month offset 1) with census 11 -> 94.50; sentiment 100.00 (one
    CRISIS); schedule (1200-24)/1200 -> 98.00. Pinned per-term rounding:
    11.67 + 23.63 + 25.00 + 14.70 = 75.00 (the sum-raw-then-round alternative
    would be 74.99).

    Design: Difficulty/combinatorial_formula/retention_score_per_term_rounding_order_pinned
    """
    ctx = _setup_rounding_scenario()
    data = _snap(ctx["case"]["id"], "TRAILING")
    comp = _components(data)
    assert comp == {
        "milestone_risk": 33.33, "panel_risk": 94.50,
        "sentiment_risk": 100.00, "schedule_risk": 98.00, "score": 75.00,
    }, f"per-term rounded components mismatch: {comp}"


def test_retention_score_per_term_rounding_order_pinned_band(api):
    """PRD §3.9: "The `risk_band` maps the score with inclusive lower bounds: at least 75 is `CRITICAL`, at least 50 is `HIGH`, at least 25 is `MODERATE`, and anything lower is `LOW`."
    PRD §3.9: "Persisting a snapshot updates the case's `latest_risk_score` and `latest_risk_band` — both null until the first snapshot exists — sets `at_risk` true exactly when the new band is `HIGH` or `CRITICAL`, and increments the case's `version`."

    Design: Difficulty/combinatorial_formula/retention_score_per_term_rounding_order_pinned
    """
    ctx = _setup_rounding_scenario()
    data = _snap(ctx["case"]["id"], "TRAILING")
    assert round(data["score"], 2) == 75.00
    assert data["risk_band"] == "CRITICAL", "75.00 meets the inclusive lower bound of CRITICAL"

    case = get_case(ctx["case"]["id"])
    assert round(case["latest_risk_score"], 2) == 75.00
    assert case["latest_risk_band"] == "CRITICAL"
    assert case["at_risk"] is True
