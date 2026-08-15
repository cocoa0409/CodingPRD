"""Lead intake gates (source state, monthly budget, referral partner field),
accountability scorecard, performance tier boundaries, and source ROI bases."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_deal_as_leader,
    claim_as,
    create_agent,
    create_deal_as_agent,
    create_lead_source,
    create_partner,
    create_team,
    ctx_routing,
    get_agent,
    get_lead,
    intake_lead,
    lead_payload,
    post_event,
    set_clock,
    validate_error,
    validate_success,
    work_lead,
)

ADMIN = TEST_USERS["team_admin_headers"]


# ─── Source budget boundary (Corner) ─────────────────────────────────────────


def test_source_budget_equality_allowed_excess_rejected(api):
    """PRD §3.3: "Per the fixed order of §2.8, intake from a `PAUSED` source is rejected with `ERR_SOURCE_NOT_ACTIVE` before any budget arithmetic runs, and intake that would push the source over budget — `spent_this_month_cents` plus `cost_per_lead_cents` strictly greater than `monthly_budget_cents`, with exact equality allowed — is rejected with `ERR_SOURCE_BUDGET_EXHAUSTED`."
    PRD §3.3: "Two counters track the current calendar month (per the team's `timezone`): `leads_this_month_count` counts leads created from the source this month, and `spent_this_month_cents` is that count multiplied by `cost_per_lead_cents`, recomputed on every intake."

    Design: Corner/validations/source_budget_equality_allowed_excess_rejected
    """
    team = create_team()
    source = create_lead_source(
        team["id"], cost_per_lead_cents=10000, monthly_budget_cents=20000, auto_route=False
    )
    intake_lead(team["id"], source["id"], "+15125550120", contact_name="One", contact_email="1@x.com")
    second = validate_success(
        api.create_lead(
            lead_payload(team["id"], source["id"], "+15125550121", contact_name="Two", contact_email="2@x.com"),
            ADMIN,
        ),
        201,
    )
    assert second["status"] == "NEW", "10000 + 10000 <= 20000: exact equality is allowed"

    third = api.create_lead(
        lead_payload(team["id"], source["id"], "+15125550122", contact_name="Three", contact_email="3@x.com"),
        ADMIN,
    )
    validate_error(third, ApiErrorId.ERR_SOURCE_BUDGET_EXHAUSTED, expected_status=409)

    after = validate_success(api.get_lead_source(source["id"], ADMIN), 200)
    assert after["spent_this_month_cents"] == 20000
    assert after["leads_this_month_count"] == 2, "A rejected intake never mutates the counters"


# ─── Referral-partner conditional field (Corner) ─────────────────────────────


def test_referral_partner_field_conditional_requirement(api):
    """PRD §3.3: "The `referral_partner_id` field is required exactly when the source's `type` is `REFERRAL_PARTNER` and forbidden for every other source type; either violation is `ERR_REFERRAL_PARTNER_REQUIRED` (HTTP 422)."

    Design: Corner/validations/referral_partner_field_conditional_requirement
    """
    team = create_team()
    referral_src = create_lead_source(
        team["id"], name="Pat Referrals", type="REFERRAL_PARTNER", auto_route=False
    )
    portal_src = create_lead_source(team["id"], name="Zillow", type="PORTAL", auto_route=False)
    partner = create_partner(team["id"], name="Pat", fee_bps=2500)

    missing = api.create_lead(
        lead_payload(team["id"], referral_src["id"], "+15125550124", contact_email="np@x.com"),
        ADMIN,
    )
    validate_error(missing, ApiErrorId.ERR_REFERRAL_PARTNER_REQUIRED, expected_status=422)

    forbidden = api.create_lead(
        lead_payload(
            team["id"], portal_src["id"], "+15125550125",
            contact_email="wp@x.com", referral_partner_id=partner["id"],
        ),
        ADMIN,
    )
    validate_error(forbidden, ApiErrorId.ERR_REFERRAL_PARTNER_REQUIRED, expected_status=422)


# ─── Source ROI empty-cohort guard (Corner) ──────────────────────────────────


def test_source_roi_empty_cohort_null_roi(api):
    """PRD §3.7: "The return `roi_bps` is the attributed commission minus the spend, the difference multiplied by 10000 and divided by the spend using floor division; when the spend is zero, `roi_bps` is null."
    PRD §3.7: "The cohort is every lead whose `source_id` matches and whose `created_at` falls inside the window; `leads_count` is its size, and `spend_cents` is the cohort size multiplied by `cost_per_lead_cents`."

    Design: Corner/calculations/source_roi_empty_cohort_null_roi
    """
    team = create_team()
    source = create_lead_source(team["id"], cost_per_lead_cents=10000, monthly_budget_cents=1_000_000)

    roi = validate_success(api.get_source_roi(source["id"], ADMIN), 200)
    assert roi["leads_count"] == 0
    assert roi["conversions_count"] == 0
    assert roi["spend_cents"] == 0
    assert roi["roi_bps"] is None


# ─── Accountability scorecard (Corner) ───────────────────────────────────────


def test_scorecard_weighted_accountability_score(api):
    """PRD §3.7: "The claim rate `claim_rate_bps` is `trailing_90d_claimed` multiplied by 10000 and divided by `trailing_90d_offered` using floor division, with a zero offered count treated as one."
    PRD §3.7: "The speed score `speed_score_bps` is 10000 when `avg_first_response_seconds` is set and is at most the effective speed window — the active policy's `speed_to_lead_window_seconds` override when set, otherwise the team default; it is 0 when the agent has no recorded responses; otherwise it is the effective window multiplied by 10000 and divided by the average response time, using floor division."
    PRD §3.7: "The conversion rate `conversion_rate_bps` is `trailing_90d_conversions` multiplied by 10000 and divided by `trailing_90d_claimed` using floor division, again with a zero denominator treated as one."
    PRD §3.7: "The composite `accountability_score_bps` is the weighted mean — five parts claim rate, three parts speed score, two parts conversion rate — divided by ten and rounded half up."

    Design: Corner/calculations/scorecard_weighted_accountability_score
    """
    team = create_team()  # default speed window 900s; no ACTIVE policy needed
    agent = create_agent(
        team["id"], "LIC-A",
        activate=False,
        import_stats={
            "trailing_90d_conversions": 2,
            "trailing_90d_claimed": 5,
            "trailing_90d_offered": 10,
            "avg_first_response_seconds": 600,
        },
    )
    card = validate_success(api.get_agent_scorecard(agent["id"], ADMIN), 200)
    assert card["claim_rate_bps"] == 5000, "5*10000/10"
    assert card["speed_score_bps"] == 10000, "600 <= 900 effective (team default) window"
    assert card["conversion_rate_bps"] == 4000, "2*10000/5"
    assert card["accountability_score_bps"] == 6300, (
        "round_half_up((5*5000 + 3*10000 + 2*4000) / 10)"
    )
    assert card["performance_tier"] == "SILVER"


# ─── Performance tier boundaries (Corner) ────────────────────────────────────


def test_tier_boundary_gold_at_exact_thresholds(api):
    """PRD §3.7: "`PLATINUM` requires at least 8 trailing-90-day conversions together with an average first response of at most 300 seconds (five minutes); `GOLD` requires at least 4 conversions together with an average of at most 900 seconds (fifteen minutes); `SILVER` requires at least 1 conversion; anything else is `BRONZE`."
    PRD §3.7: "Both boundary comparisons are inclusive — exactly 4 conversions with an average of exactly 900 seconds earns `GOLD`, and exactly 8 conversions with exactly 300 seconds earns `PLATINUM` — and an agent with no recorded responses, whose `avg_first_response_seconds` is null, cannot reach `GOLD` or `PLATINUM` regardless of conversions."

    Design: Corner/calculations/tier_boundary_gold_at_exact_thresholds
    """
    team = create_team()
    gold = create_agent(
        team["id"], "LIC-G", display_name="Gold G", activate=False,
        import_stats={"trailing_90d_conversions": 4, "avg_first_response_seconds": 900},
    )
    silver = create_agent(
        team["id"], "LIC-S", display_name="Silver S", activate=False,
        import_stats={"trailing_90d_conversions": 4, "avg_first_response_seconds": 901},
    )
    plat = create_agent(
        team["id"], "LIC-P", display_name="Plat P", activate=False,
        import_stats={"trailing_90d_conversions": 8, "avg_first_response_seconds": 300},
    )

    assert get_agent(gold["id"])["performance_tier"] == "GOLD", "4 >= 4 and 900 <= 900"
    assert get_agent(silver["id"])["performance_tier"] == "SILVER", "901 > 900 fails the GOLD gate"
    assert get_agent(plat["id"])["performance_tier"] == "PLATINUM", "8 >= 8 and 300 <= 300"


# ─── Difficulty: state-vs-fiscal priority on intake ──────────────────────────


def _paused_over_budget_source(api):
    """Source cost 10000 / budget 10000 with one lead already taken (budget
    exhausted for the next intake), then PAUSED — both failure conditions hold."""
    team = create_team()
    source = create_lead_source(
        team["id"], cost_per_lead_cents=10000, monthly_budget_cents=10000, auto_route=False
    )
    intake_lead(team["id"], source["id"], "+15125550060", contact_name="First", contact_email="f@x.com")
    return team, source


def test_intake_paused_source_and_exhausted_budget_state_beats_fiscal(api):
    """PRD §2.8: "Because the order is fixed, an intake request against a paused source that is also over budget reports `ERR_SOURCE_NOT_ACTIVE`, and a manual route attempted on a team with no active policy reports `ERR_NO_ACTIVE_POLICY` rather than `ERR_NO_ELIGIBLE_AGENT`."
    PRD §3.3: "Per the fixed order of §2.8, intake from a `PAUSED` source is rejected with `ERR_SOURCE_NOT_ACTIVE` before any budget arithmetic runs, and intake that would push the source over budget — `spent_this_month_cents` plus `cost_per_lead_cents` strictly greater than `monthly_budget_cents`, with exact equality allowed — is rejected with `ERR_SOURCE_BUDGET_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/intake_paused_source_and_exhausted_budget_state_beats_fiscal
    """
    team, source = _paused_over_budget_source(api)
    validate_success(api.pause_lead_source(source["id"], ADMIN), 200)

    res = api.create_lead(
        lead_payload(team["id"], source["id"], "+15125550061", contact_name="Second", contact_email="s@x.com"),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_SOURCE_NOT_ACTIVE, expected_status=409)


def test_intake_over_budget_active_source_reports_fiscal_error(api):
    """PRD §3.3: "Per the fixed order of §2.8, intake from a `PAUSED` source is rejected with `ERR_SOURCE_NOT_ACTIVE` before any budget arithmetic runs, and intake that would push the source over budget — `spent_this_month_cents` plus `cost_per_lead_cents` strictly greater than `monthly_budget_cents`, with exact equality allowed — is rejected with `ERR_SOURCE_BUDGET_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/intake_paused_source_and_exhausted_budget_state_beats_fiscal
    """
    team, source = _paused_over_budget_source(api)  # over budget but still ACTIVE

    res = api.create_lead(
        lead_payload(team["id"], source["id"], "+15125550061", contact_name="Second", contact_email="s@x.com"),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_SOURCE_BUDGET_EXHAUSTED, expected_status=409)


# ─── Difficulty: REALIZED vs PROJECTED source ROI ────────────────────────────


def _roi_setup(api):
    """Two leads (10,000 cents each): lead1's deal approved at 900,000;
    lead2 CLAIMED and HOT (40+30+10 = 80 points)."""
    ctx = ctx_routing(
        source_type="PORTAL",
        auto_route=True,
        cost_per_lead_cents=10000,
        monthly_budget_cents=100_000_000,
        agents=({"display_name": "Closer C", "license_number": "LIC-C", "max_active_leads": 10},),
        with_leader=True,
    )
    agent = ctx["agents"][0]
    leader = ctx["leader"]
    lead1 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550001",
        contact_name="Buyer One", contact_email="b1@x.com",
        expected_close_price_cents=50_000_000,
    )
    work_lead(lead1["id"], agent["id"])
    deal1 = create_deal_as_agent(lead1["id"], agent["id"], 900_000)
    approve_deal_as_leader(deal1["id"], leader["id"])

    set_clock("2026-08-02T00:00:00Z")
    lead2 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550002",
        contact_name="Buyer Two", contact_email="b2@x.com",
        expected_close_price_cents=40_000_000,
    )
    claim_as(lead2["id"], agent["id"])
    post_event(lead2["id"], "SHOWING_ATTENDED", "2026-08-01T06:00:00Z")
    post_event(lead2["id"], "REPLIED", "2026-08-01T06:30:00Z")
    post_event(lead2["id"], "LINK_CLICK", "2026-08-01T07:00:00Z")
    ctx["lead2"] = lead2
    return ctx


def test_source_roi_realized_basis_counts_only_closed_won(api):
    """PRD §3.7: "Under `REALIZED`, `attributed_commission_cents` sums `split_basis_cents` over the cohort's deals in `APPROVED` or `PAID_OUT` status, and `conversions_count` counts those deals."
    PRD §3.7: "The cohort is every lead whose `source_id` matches and whose `created_at` falls inside the window; `leads_count` is its size, and `spend_cents` is the cohort size multiplied by `cost_per_lead_cents`."
    PRD §3.7: "The return `roi_bps` is the attributed commission minus the spend, the difference multiplied by 10000 and divided by the spend using floor division; when the spend is zero, `roi_bps` is null."

    Design: Difficulty/dual_variant_calc/source_roi_realized_vs_projected_on_lead_source
    """
    ctx = _roi_setup(api)
    roi = validate_success(
        api.get_source_roi(ctx["source"]["id"], ADMIN, params={"basis": "REALIZED"}), 200
    )
    assert roi["leads_count"] == 2
    assert roi["conversions_count"] == 1
    assert roi["spend_cents"] == 20000
    assert roi["attributed_commission_cents"] == 900000
    assert roi["roi_bps"] == 440000, "(900000 - 20000) * 10000 / 20000"


def test_source_roi_projected_basis_adds_temperature_weighted_pipeline(api):
    """PRD §3.7: "Under `PROJECTED`, the realized sum is augmented by the open pipeline: each cohort lead in `OFFERED`, `CLAIMED`, `WORKING`, or `UNDER_CONTRACT` contributes its `expected_close_price_cents` scaled by an estimated commission rate of 300 basis points (three percent) and then by its temperature's closing probability — 500 basis points for `COLD`, 2000 for `WARM`, 4500 for `HOT` — with each lead's contribution rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/source_roi_realized_vs_projected_on_lead_source
    """
    ctx = _roi_setup(api)
    lead2 = get_lead(ctx["lead2"]["id"])
    assert lead2["temperature"] == "HOT"
    assert lead2["status"] == "CLAIMED"

    realized = validate_success(
        api.get_source_roi(ctx["source"]["id"], ADMIN, params={"basis": "REALIZED"}), 200
    )
    projected = validate_success(
        api.get_source_roi(ctx["source"]["id"], ADMIN, params={"basis": "PROJECTED"}), 200
    )
    assert projected["attributed_commission_cents"] == 1_440_000, (
        "900000 realized + round_half_up(40000000 * 300/10000 * 4500/10000) = 540000 pipeline"
    )
    assert projected["roi_bps"] == 710000
    assert realized["roi_bps"] != projected["roi_bps"], (
        "The two bases diverge whenever the source has open pipeline"
    )
