"""Renewal options, the performance bonus and the exposure read."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_exposure_summary,
    assert_renewal_option,
    build_deal,
    create_renewal_option_payload,
    make_brand_rep_headers,
    open_renewal_option,
    read_engagement,
    setup_completed_engagement,
    setup_exposure_scenario,
    set_clock,
    terminate_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["talent_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def test_bonus_tier_is_picked_from_the_base_value_before_the_bonus(api):
    """PRD 3.10: "Step three picks `bonus_tier` from the pair of figures produced so
    far, taking the **first** matching rule: `TIER_1` when `approval_rate` is at least
    1.0000 and `base_value_cents` is at least thirty thousand dollars expressed as
    3,000,000 cents; otherwise `TIER_2` when `approval_rate` is at least 0.8000 and
    `base_value_cents` is at least fifteen thousand dollars expressed as 1,500,000
    cents; otherwise `TIER_3` when `approval_rate` is at least 0.5000; otherwise
    `NONE`."
    PRD 3.10: "Step five computes `total_engagement_value_cents` as `base_value_cents`
    plus `bonus_cents`; this figure is reported only and must never be fed back into
    the tier selection of step three, even in the case where adding the bonus would
    push the value across a higher tier's floor."

    Design: Difficulty/combinatorial_formula/renewal_bonus_tier_pinned_before_total_value
    """
    deal = setup_completed_engagement(
        athlete_overrides={"full_name": "Dana Osei", "sport": "TRACK"},
        brand_overrides={
            "name": "Kite Footwear", "category": "FOOTWEAR",
            "legal_entity_name": "Kite Footwear LLC",
        },
        opportunity_overrides={
            "exclusivity_category": "FOOTWEAR", "exclusivity_months": 6,
            "territory": "DOMESTIC", "usage_rights_tier": "SOCIAL_ONLY",
        },
        term_sheet_overrides={
            "fee_cents": 2_780_000, "usage_rights_tier": "SOCIAL_ONLY",
            "territory": "DOMESTIC", "morals_clause_tier": "TIER_C",
            "exclusivity_months": 6, "appearance_days": 0,
        },
        signed_by_reference="CS-2026-0002",
    )
    assert deal["engagement"]["binding_fee_cents"] == 2_900_000

    response = api.create_renewal_option(
        create_renewal_option_payload(deal["engagement_id"], "2026-12-01", 1_600_000),
        AGENT,
    )
    option = validate_success(response, 201)
    assert_renewal_option(option)

    assert option["base_value_cents"] == 2_900_000
    assert option["bonus_tier"] == "TIER_2"
    assert option["bonus_cents"] == 203_000
    assert option["total_engagement_value_cents"] == 3_103_000
    assert option["bonus_cents"] != 348_000, (
        "re-feeding the 3103000 total into tier selection would wrongly pay TIER_1"
    )


def test_renewal_fee_applies_the_tier_uplift_and_the_market_escalator(api):
    """PRD 3.10: "Step two computes `approval_rate` as the engagement's
    `approved_deliverable_count` divided by its `required_deliverable_count`, rounded
    half up to four decimal places."
    PRD 3.10: "Step six builds the renewal multiplier by starting at 1.00, adding 0.10
    when `bonus_tier` is `TIER_1` or 0.05 when it is `TIER_2` and nothing for `TIER_3`
    or `NONE`, and then adding a market escalator drawn from the athlete's
    `market_tier` — 0.03 for `GLOBAL`, 0.015 for `NATIONAL` and nothing for
    `REGIONAL`. `renewal_fee_cents` is the supplied `proposed_base_fee_cents`
    multiplied by that multiplier, rounded half up to whole cents exactly once."
    PRD 3.10: "The option opens in `OPEN` with `decided_at` null, and an engagement's
    options can be listed and filtered by `status`."

    Design: Difficulty/combinatorial_formula/renewal_bonus_tier_pinned_before_total_value
    """
    deal = setup_completed_engagement(
        athlete_overrides={"full_name": "Dana Osei", "sport": "TRACK"},
        brand_overrides={
            "name": "Kite Footwear", "category": "FOOTWEAR",
            "legal_entity_name": "Kite Footwear LLC",
        },
        opportunity_overrides={
            "exclusivity_category": "FOOTWEAR", "exclusivity_months": 6,
            "territory": "DOMESTIC", "usage_rights_tier": "SOCIAL_ONLY",
        },
        term_sheet_overrides={
            "fee_cents": 2_780_000, "usage_rights_tier": "SOCIAL_ONLY",
            "territory": "DOMESTIC", "morals_clause_tier": "TIER_C",
            "exclusivity_months": 6, "appearance_days": 0,
        },
        signed_by_reference="CS-2026-0002",
    )

    option = open_renewal_option(deal["engagement_id"], "2026-12-01", 1_600_000)

    assert option["approval_rate"] == pytest.approx(1.0)
    assert option["renewal_fee_cents"] == 1_728_000
    assert option["status"] == "OPEN"

    rows, _meta = validate_paginated(
        api.list_engagement_renewal_options(deal["engagement_id"], AGENT)
    )
    assert len(rows) == 1
    assert rows[0]["id"] == option["id"]


def test_bonus_tier_one_is_selected_at_the_exact_value_floor(api):
    """PRD 3.10: "Step three picks `bonus_tier` from the pair of figures produced so
    far, taking the **first** matching rule: `TIER_1` when `approval_rate` is at least
    1.0000 and `base_value_cents` is at least thirty thousand dollars expressed as
    3,000,000 cents; otherwise `TIER_2` when `approval_rate` is at least 0.8000 and
    `base_value_cents` is at least fifteen thousand dollars expressed as 1,500,000
    cents; otherwise `TIER_3` when `approval_rate` is at least 0.5000; otherwise
    `NONE`."
    PRD 3.10: "Step four computes `bonus_cents` as `base_value_cents` multiplied by
    the tier's bonus percentage — twelve percent for `TIER_1`, seven percent for
    `TIER_2`, three percent for `TIER_3` and zero for `NONE` — rounded half up to
    whole cents exactly once."

    Design: Corner/cross_cutting_complexity_layers/bonus_tier_1_selected_at_exact_value_floor
    """
    deal = setup_completed_engagement(
        opportunity_overrides={
            "exclusivity_months": 6, "territory": "DOMESTIC",
            "usage_rights_tier": "SOCIAL_ONLY",
        },
        term_sheet_overrides={
            "fee_cents": 2_880_000, "usage_rights_tier": "SOCIAL_ONLY",
            "territory": "DOMESTIC", "morals_clause_tier": "TIER_C",
            "exclusivity_months": 6, "appearance_days": 0,
        },
        signed_by_reference="CS-C-0002",
    )
    assert deal["engagement"]["binding_fee_cents"] == 3_000_000

    option = open_renewal_option(deal["engagement_id"], "2026-12-01", 1_600_000)

    assert option["base_value_cents"] == 3_000_000
    assert option["bonus_tier"] == "TIER_1"
    assert option["bonus_cents"] == 360_000
    assert option["total_engagement_value_cents"] == 3_360_000
    assert option["renewal_fee_cents"] == 1_808_000


def test_bonus_tier_is_none_when_nothing_was_approved(api):
    """PRD 3.10: "Step three picks `bonus_tier` from the pair of figures produced so
    far, taking the **first** matching rule: `TIER_1` when `approval_rate` is at least
    1.0000 and `base_value_cents` is at least thirty thousand dollars expressed as
    3,000,000 cents; otherwise `TIER_2` when `approval_rate` is at least 0.8000 and
    `base_value_cents` is at least fifteen thousand dollars expressed as 1,500,000
    cents; otherwise `TIER_3` when `approval_rate` is at least 0.5000; otherwise
    `NONE`."
    PRD 3.10: "A renewal option may only be opened against an engagement whose
    `contract_status` is `COMPLETED` or `TERMINATED` and whose `binding_fee_cents` is
    not null; opening one against an engagement still `PENDING_COUNTERSIGN` or
    `ACTIVE` is refused with `ERR_ENGAGEMENT_NOT_ACTIVE`."

    Design: Corner/calculations/renewal_bonus_tier_none_when_approval_rate_below_half
    """
    deal = build_deal(
        stage="active",
        opportunity_overrides={"proposed_fee_cents": 200_000, "planned_posts": 2},
        signed_by_reference="CS-C-0002",
    )
    terminate_engagement(deal["engagement_id"], reason_code="BRAND_WITHDRAWAL")

    option = open_renewal_option(deal["engagement_id"], "2026-12-01", 1_600_000)

    assert option["base_value_cents"] == 2_621_400
    assert option["approval_rate"] == pytest.approx(0.0)
    assert option["bonus_tier"] == "NONE"
    assert option["bonus_cents"] == 0
    assert option["total_engagement_value_cents"] == 2_621_400
    assert option["renewal_fee_cents"] == 1_648_000

    rows, _meta = validate_paginated(
        api.list_engagement_renewal_options(deal["engagement_id"], AGENT, params={"status": "OPEN"})
    )
    assert len(rows) == 1


def test_decision_past_the_deadline_lapses_the_option(api):
    """PRD 3.10: "Like offer expiry, the deadline is enforced lazily: a decision
    arriving when the clock's date is already past `option_deadline_date` moves the
    option `OPEN → LAPSED` and the call is refused with `ERR_RENEWAL_WINDOW_CLOSED`;
    the same error answers a decision on an option that is no longer `OPEN`."
    PRD 3.10: "Exercising moves the option `OPEN → EXERCISED`, stamps `decided_at`,
    and appends a `BONUS` ledger entry whose `amount_cents` is the positive
    `bonus_cents`; because that entry was appended, the engagement's
    `accrued_fee_cents` rises by that amount."

    Design: Corner/state_machines/renewal_decide_after_deadline_lapses_option
    """
    deal = setup_completed_engagement(signed_by_reference="CS-C-0002")
    option = open_renewal_option(deal["engagement_id"], "2026-10-01", 1_600_000)
    assert option["bonus_tier"] == "TIER_2"
    assert option["bonus_cents"] == 183_498

    set_clock("2026-10-02T00:00:00Z")

    response = api.decide_renewal_option(
        option["id"], {"decision": "EXERCISE"}, make_brand_rep_headers(deal["brand_id"])
    )
    validate_error(response, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value, 409)

    rows, _meta = validate_paginated(
        api.list_engagement_renewal_options(deal["engagement_id"], AGENT)
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "LAPSED"

    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], TEST_USERS["finance_manager_headers"])
    )
    assert entries == [], "a lapsed option never accrues its bonus"


# ── The two exposure variants ────────────────────────────────────────────────

def test_roster_snapshot_counts_only_committed_rows(api):
    """PRD 3.10: "Two variants of that read exist, selected by the `variant` query
    parameter, which defaults to `ROSTER_SNAPSHOT` when omitted. `ROSTER_SNAPSHOT`
    counts only committed rows: `category_load` counts exclusivity grants whose
    `status` is `ACTIVE`, and `morals_exposure` sums the morals weight over
    engagements whose `contract_status` is `ACTIVE`."
    PRD 3.10: "It is the `ROSTER_SNAPSHOT` figure — and only that one — which is
    denormalised onto the athlete as `exposure_risk_snapshot_score`."

    Design: Difficulty/dual_variant_calc/roster_snapshot_vs_pipeline_projected_exposure_risk
    """
    scenario = setup_exposure_scenario()

    summary = validate_success(
        api.get_exposure_summary(
            scenario["athlete_id"], OFFICER, params={"variant": "ROSTER_SNAPSHOT"}
        ),
        200,
    )
    assert_exposure_summary(summary, scenario["athlete_id"])

    assert summary["variant"] == "ROSTER_SNAPSHOT"
    assert summary["category_load"] == 1
    assert summary["morals_exposure"] == 2
    assert summary["noncompliance_hits"] == 0
    assert summary["score"] == 28

    athlete = validate_success(api.get_athlete(scenario["athlete_id"], AGENT))
    assert athlete["exposure_risk_snapshot_score"] == 28


def test_pipeline_projected_adds_the_submitted_term_sheets_morals_weight(api):
    """PRD 3.10: "`PIPELINE_PROJECTED` counts the same committed rows plus everything
    in flight: `category_load` additionally counts grants whose `status` is `PENDING`,
    and `morals_exposure` additionally adds a morals weight for every engagement whose
    `contract_status` is `PENDING_COUNTERSIGN` and for every term sheet whose `status`
    is `SUBMITTED` or `COUNTERED` and whose opportunity names this athlete, using that
    term sheet's *current* `morals_clause_tier`."
    PRD 3.10: "`morals_exposure` sums a morals weight over the athlete's engagements,
    weighting a `TIER_A` morals clause as 3, `TIER_B` as 2 and `TIER_C` as 1."

    Design: Difficulty/dual_variant_calc/roster_snapshot_vs_pipeline_projected_exposure_risk
    """
    scenario = setup_exposure_scenario()

    snapshot = validate_success(
        api.get_exposure_summary(
            scenario["athlete_id"], OFFICER, params={"variant": "ROSTER_SNAPSHOT"}
        ),
        200,
    )
    projected = validate_success(
        api.get_exposure_summary(
            scenario["athlete_id"], OFFICER, params={"variant": "PIPELINE_PROJECTED"}
        ),
        200,
    )
    assert_exposure_summary(projected, scenario["athlete_id"])

    assert projected["variant"] == "PIPELINE_PROJECTED"
    assert projected["category_load"] == 1
    assert projected["morals_exposure"] == 5
    assert projected["noncompliance_hits"] == 0
    assert projected["score"] == 52

    assert snapshot["morals_exposure"] == 2
    assert snapshot["category_load"] == projected["category_load"] == 1


def test_exposure_read_defaults_to_the_roster_snapshot_variant(api):
    """PRD 3.10: "Two variants of that read exist, selected by the `variant` query
    parameter, which defaults to `ROSTER_SNAPSHOT` when omitted."
    PRD 3.10: "The read answers with the `athlete_id`, the `variant` applied, and four
    figures: `category_load`, `morals_exposure`, `noncompliance_hits` and the combined
    `score`."

    Design: Corner/endpoints/exposure_summary_defaults_to_roster_snapshot_when_variant_omitted
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")

    response = api.get_exposure_summary(deal["athlete_id"], AGENT)
    summary = validate_success(response, 200)
    assert response.json()["response_type"] == "object"
    assert_exposure_summary(summary, deal["athlete_id"])

    assert summary["variant"] == "ROSTER_SNAPSHOT"
    assert summary["score"] == 28
    assert summary["category_load"] == 1
    assert summary["morals_exposure"] == 2
    assert summary["noncompliance_hits"] == 0

    assert read_engagement(deal["engagement_id"])["contract_status"] == "ACTIVE"
