"""Risk-questionnaire scoring and model-band assignment.

Queue A: combinatorial_formula/risk_score_single_round_then_clamp_order_pinned.
Queue B (calculations): model_band_overlap_picks_narrowest_band,
no_model_for_score_returns_error.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_account_payload,
    create_questionnaire_payload,
    set_clock,
    create_model,
)

ADVISOR = TEST_USERS["advisor_headers"]


def _score(api, account_id, **inputs):
    return get_success_data(
        api.create_questionnaire(
            create_questionnaire_payload(account_id=account_id, **inputs), ADVISOR
        )
    )


def test_risk_score_sum_then_round_to_82(api):
    """PRD §3.2: "The four terms are combined into a single raw value as one expression — all four terms first, then a single rounding — because rounding each term individually would drift the result; the raw value is rounded half up to an integer and then clamped to lie between 0 and 100 inclusive, producing `risk_score`."

    Design: Difficulty/combinatorial_formula/risk_score_single_round_then_clamp_order_pinned
    """
    set_clock("2026-03-01T00:00:00.000Z")
    create_model(name="band70", min_risk_score=70, max_risk_score=100)
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="round@x.com"), ADVISOR)
    )
    # raw = 35 + 31.5 + 16 - 1 = 81.5 -> round_half_up -> 82
    q = _score(api, acct["id"], horizon_years=30, loss_tolerance=9, liquidity_need=1, income_band=8)
    assert q["risk_score"] == 82
    assert q["status"] == "SCORED"


def test_risk_score_single_rounding_uses_half_up_to_83(api):
    """PRD §3.2: "The four terms are combined into a single raw value as one expression — all four terms first, then a single rounding — because rounding each term individually would drift the result; the raw value is rounded half up to an integer and then clamped to lie between 0 and 100 inclusive, producing `risk_score`."

    Design: Difficulty/combinatorial_formula/risk_score_single_round_then_clamp_order_pinned
    """
    set_clock("2026-03-02T00:00:00.000Z")
    create_model(name="band70b", min_risk_score=70, max_risk_score=100)
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="round2@x.com"), ADVISOR)
    )
    # raw = 35 + 31.5 + 16 - 0 = 82.5 -> round_half_up -> 83 (not 82)
    q = _score(api, acct["id"], horizon_years=30, loss_tolerance=9, liquidity_need=0, income_band=8)
    assert q["risk_score"] == 83
    assert q["status"] == "SCORED"


def test_model_band_overlap_picks_narrowest_band(api):
    """PRD §3.2: "When two active models both contain the score, the platform picks the one with the smaller band width — that is, the smaller value of `max_risk_score` minus `min_risk_score` — and breaks any remaining tie by choosing the model created earliest (`created_at` ascending)."

    Design: Corner/calculations/model_band_overlap_picks_narrowest_band
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(name="Wide", min_risk_score=70, max_risk_score=100)
    narrow = create_model(name="Narrow", min_risk_score=80, max_risk_score=90)
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="band@x.com"), ADVISOR)
    )
    q = _score(api, acct["id"], horizon_years=30, loss_tolerance=9, liquidity_need=1, income_band=8)
    assert q["risk_score"] == 82
    assert q["assigned_model_portfolio_id"] == narrow["id"]


def test_no_active_model_for_score_returns_error(api):
    """PRD §3.2: "If no active model's band contains the score, the submission is rejected with `ERR_NO_MODEL_FOR_SCORE`."

    Design: Corner/calculations/no_model_for_score_returns_error
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(
        name="LowOnly",
        min_risk_score=0,
        max_risk_score=40,
        targets=[{"asset_class": "BOND", "target_pct": 100}],
    )
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="nomodel@x.com"), ADVISOR)
    )
    # Score 82 falls outside the only active band [0,40].
    res = api.create_questionnaire(
        create_questionnaire_payload(
            account_id=acct["id"], horizon_years=30, loss_tolerance=9, liquidity_need=1, income_band=8
        ),
        ADVISOR,
    )
    validate_error(res, ApiErrorId.ERR_NO_MODEL_FOR_SCORE.value)
