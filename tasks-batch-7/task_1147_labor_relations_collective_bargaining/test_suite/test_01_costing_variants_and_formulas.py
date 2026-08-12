"""Costing scenario variant and formula tests (difficulty rules 1-2, corner calculations)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_agreement_payload,
    create_costing_scenario_payload,
    create_employer_proposal_on_table,
    create_proposal_payload,
    create_reviewed_scenario,
    create_union,
    create_draft_agreement,
    get_agreement_version,
    get_success_data,
    make_union_representative_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["lr_admin_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
NEG2 = TEST_USERS["negotiator_2_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / scenario_costing_provisional_vs_final_divergence
# ---------------------------------------------------------------------------

def _setup_provisional_then_final(api):
    union = create_union(name="Union A")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA 2026",
        effective_date="2026-06-01T00:00:00Z",
        expiration_date="2029-05-31T00:00:00Z",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=1_000_000_000_000,
        deadline_mode="BUSINESS",
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"],
        union["id"],
        title="GWI 4%",
        proposal_type="ECONOMIC",
        wage_increase_pct=0.04,
        affected_headcount=100,
        includes_benefits=True,
        one_time_cost_cents=120000,
        recurring_annual_cost_cents=6000000,
    )
    prov = get_success_data(
        api.create_costing_scenario(
            create_costing_scenario_payload(
                agreement_id=agreement["id"],
                name="prov",
                scenario_mode="PROVISIONAL",
                term_years=3,
                proposal_ids=[proposal["id"]],
            ),
            NEG1,
        )
    )
    prov = get_success_data(
        api.transition_costing_scenario(prov["id"], {"to_status": "COMPUTED"}, NEG1)
    )
    est_after_prov = get_success_data(api.get_proposal(proposal["id"], NEG1))[
        "estimated_year1_cost_cents"
    ]
    fin = get_success_data(
        api.create_costing_scenario(
            create_costing_scenario_payload(
                agreement_id=agreement["id"],
                name="final",
                scenario_mode="FINAL",
                term_years=3,
                proposal_ids=[proposal["id"]],
            ),
            NEG1,
        )
    )
    fin = get_success_data(
        api.transition_costing_scenario(fin["id"], {"to_status": "COMPUTED"}, NEG1)
    )
    est_after_final = get_success_data(api.get_proposal(proposal["id"], NEG1))[
        "estimated_year1_cost_cents"
    ]
    return prov, fin, est_after_prov, est_after_final


def test_provisional_vs_final_scenario_totals(api):
    """PRD §3.5: "The basis is the agreement's `fte_projected` when the scenario
    mode is `PROVISIONAL`, or the agreement's `headcount_baseline` when the mode
    is `FINAL`." and "under `PROVISIONAL` it is the proposal's
    `one_time_cost_cents` divided by `term_years`, rounded half-up to whole
    cents; under `FINAL` it is the full `one_time_cost_cents` charged to year 1
    and 0 in every later year."

    Design: Difficulty/dual_variant_calc/scenario_costing_provisional_vs_final_divergence
    """
    prov, fin, _, _ = _setup_provisional_then_final(api)
    assert prov["year_breakdown_cents"] == [78523840, 81423194, 84438521], (
        f"PROVISIONAL breakdown mismatch: {prov['year_breakdown_cents']}"
    )
    assert prov["reserve_cents"] == 12219278
    assert prov["total_cost_cents"] == 256604833
    assert fin["year_breakdown_cents"] == [66523200, 68819328, 71332101], (
        f"FINAL breakdown mismatch: {fin['year_breakdown_cents']}"
    )
    assert fin["reserve_cents"] == 10333731
    assert fin["total_cost_cents"] == 217008360


def test_proposal_estimate_overwritten_by_later_variant(api):
    """PRD §3.5: "Each proposal's `estimated_year1_cost_cents` is overwritten
    with its year-1 line under this scenario's variant."

    Design: Difficulty/dual_variant_calc/scenario_costing_provisional_vs_final_divergence
    """
    _, _, est_after_prov, est_after_final = _setup_provisional_then_final(api)
    assert est_after_prov == 78523840, (
        f"PROVISIONAL year-1 estimate mismatch: {est_after_prov}"
    )
    assert est_after_final == 66523200, (
        f"FINAL year-1 estimate (later variant overwrites) mismatch: {est_after_final}"
    )


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / scenario_costing_tiered_conditional_mode_a
# ---------------------------------------------------------------------------

def _setup_tier_mid_scenario(api):
    union = create_union(name="Union C")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA C",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=1_000_000_000_000,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"],
        union["id"],
        title="GWI 3% partial",
        proposal_type="ECONOMIC",
        wage_increase_pct=0.03,
        affected_headcount=60,
        includes_benefits=False,
        one_time_cost_cents=90000,
        recurring_annual_cost_cents=1200000,
    )
    scenario = get_success_data(
        api.create_costing_scenario(
            create_costing_scenario_payload(
                agreement_id=agreement["id"],
                name="tier-prov",
                scenario_mode="PROVISIONAL",
                term_years=3,
                proposal_ids=[proposal["id"]],
            ),
            NEG1,
        )
    )
    return get_success_data(
        api.transition_costing_scenario(scenario["id"], {"to_status": "COMPUTED"}, NEG1)
    )


def test_tier_mid_multiplier_full_breakdown(api):
    """PRD §3.5: "the tiered multiplier is 1.10 when `r` is at least 0.80, 1.05
    when `r` is at least 0.50 but less than 0.80, and 1.00 when `r` is less
    than 0.50. The wage line is multiplied by the tier multiplier and rounded
    half-up to whole cents."

    Design: Difficulty/combinatorial_formula/scenario_costing_tiered_conditional_mode_a
    """
    scenario = _setup_tier_mid_scenario(api)
    assert scenario["year_breakdown_cents"] == [40542000, 41721360, 42936101]
    assert scenario["subtotal_cents"] == 125199461
    assert scenario["reserve_cents"] == 6259973
    assert scenario["total_cost_cents"] == 131459434


def test_tier_mid_multiplier_year1_line(api):
    """PRD §3.5: "The coverage ratio `r` is the proposal's `affected_headcount`
    (or 0 when null) divided by the basis; the tiered multiplier is 1.10 when
    `r` is at least 0.80, 1.05 when `r` is at least 0.50 but less than 0.80,
    and 1.00 when `r` is less than 0.50." (Coverage ratio 60/120 == 0.50 is
    "at least 0.50" and selects 1.05, visible in the year-1 line.)

    Design: Difficulty/combinatorial_formula/scenario_costing_tiered_conditional_mode_a
    """
    scenario = _setup_tier_mid_scenario(api)
    # basis = fte_projected 120; base_payroll = 120*5000*2080 = 1248000000
    # wage_y1 = 1248000000*0.03 = 37440000; cap 187200000 no-op; no benefits
    # r = 60/120 = 0.50 -> mult 1.05 -> round(37440000*1.05) = 39312000
    # one_time share = round(90000/3) = 30000; recurring 1200000
    # year-1 line = 39312000 + 1200000 + 30000 = 40542000
    assert scenario["year_breakdown_cents"][0] == 40542000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / retro_payout_line_then_sum_mode_b
# ---------------------------------------------------------------------------

def _setup_vote_for_retro(api, ballot_close_at="2026-07-01T00:00:00Z"):
    """Agreement effective 2026-03-01 (in the past at tally), proposal with
    recurring 100 cents, LOCKED FINAL scenario, ACCEPTED package, OPEN vote."""
    from test_helpers import (
        create_locked_scenario,
        create_ratification_vote_payload,
    )

    union = create_union(name="Union D")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA D",
        effective_date="2026-03-01T00:00:00Z",
        expiration_date="2029-05-31T00:00:00Z",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=1_000_000_000_000,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"],
        union["id"],
        title="Shift allowance",
        proposal_type="ECONOMIC",
        recurring_annual_cost_cents=100,
    )
    create_locked_scenario(
        agreement["id"], [proposal["id"]], scenario_mode="FINAL", term_years=3
    )
    get_success_data(
        api.transition_proposal(
            proposal["id"], {"to_status": "ACCEPTED"}, make_union_representative_headers(union["id"])
        )
    )
    vote = get_success_data(
        api.create_ratification_vote(
            create_ratification_vote_payload(
                agreement_id=agreement["id"],
                eligible_voter_count=10,
                ballot_close_at=ballot_close_at,
            ),
            CHIEF,
        )
    )
    get_success_data(api.transition_ratification_vote(vote["id"], {"to_status": "OPEN"}, CHIEF))
    return union, agreement, proposal, vote


def test_retro_payout_round_monthly_line_first(api):
    """PRD §3.7: "the monthly line is the proposal's `recurring_annual_cost_cents`
    divided by 12, rounded half-up to whole cents — this monthly rounding is
    pinned and happens before any multiplication. The payout for that proposal
    is the monthly line multiplied by the retro period count."
    (round_half_up(100/12) = 8 monthly, then * 4 retro periods = 32; the
    alternative sum-then-round order would yield round_half_up(100*4/12) = 33.)

    Design: Difficulty/combinatorial_formula/retro_payout_line_then_sum_mode_b
    """
    union, _, _, vote = _setup_vote_for_retro(api)
    get_success_data(api.set_clock("2026-07-15T00:00:00Z", ADMIN))
    result = get_success_data(
        api.tally_vote(
            vote["id"],
            {"votes_for": 4, "votes_against": 1},
            make_union_representative_headers(union["id"]),
        )
    )
    assert result["status"] == "RATIFIED"
    assert result["retro_payout_cents"] == 32, (
        f"retro_payout_cents must be 32 under line-then-multiply order; got "
        f"{result['retro_payout_cents']} (33 would mean sum-then-round)"
    )


def test_retro_payout_period_count_floor(api):
    """PRD §3.7: "The retro period count is the number of whole 30-day periods
    between the agreement's `effective_date` and the tally date — computed as
    the floor of the day difference divided by 30, and 0 when the
    `effective_date` is not in the past."
    (2026-03-01 -> 2026-07-15 is 136 days; floor(136/30) = 4 periods.)

    Design: Difficulty/combinatorial_formula/retro_payout_line_then_sum_mode_b
    """
    union, _, _, vote = _setup_vote_for_retro(api)
    get_success_data(api.set_clock("2026-07-15T00:00:00Z", ADMIN))
    result = get_success_data(
        api.tally_vote(
            vote["id"],
            {"votes_for": 4, "votes_against": 1},
            make_union_representative_headers(union["id"]),
        )
    )
    # 4 whole 30-day periods * round_half_up(100/12)=8 = 32
    assert result["votes_for"] == 4
    assert result["votes_against"] == 1
    assert result["retro_payout_cents"] == 8 * 4


# ---------------------------------------------------------------------------
# Corner: calculations / costing_compute_rejects_non_economic_member
# ---------------------------------------------------------------------------

def test_compute_rejects_non_economic_member(api):
    """PRD §3.5: "Compute first validates that every id in `proposal_ids`
    resolves to a proposal whose `agreement_id` equals the scenario's, whose
    `proposal_type` is `ECONOMIC`, and whose status is `ON_TABLE` or `ACCEPTED`
    — any miss is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/calculations/costing_compute_rejects_non_economic_member
    """
    union = create_union(name="Union CO")
    agreement = create_draft_agreement(union["id"], title="CBA CO")
    proposal = create_employer_proposal_on_table(
        agreement["id"], union["id"], title="Language tweak", proposal_type="NON_ECONOMIC"
    )
    scenario = get_success_data(
        api.create_costing_scenario(
            create_costing_scenario_payload(
                agreement_id=agreement["id"],
                name="badset",
                scenario_mode="FINAL",
                term_years=3,
                proposal_ids=[proposal["id"]],
            ),
            NEG1,
        )
    )
    resp = api.transition_costing_scenario(scenario["id"], {"to_status": "COMPUTED"}, NEG1)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    after = get_success_data(api.get_costing_scenario(scenario["id"], NEG1))
    assert after["status"] == "DRAFT", "failed compute must leave the scenario DRAFT"


# ---------------------------------------------------------------------------
# Corner: calculations / costing_wage_drift_cap_applies
# ---------------------------------------------------------------------------

def test_wage_drift_cap_binds_before_benefits(api):
    """PRD §3.5: "then is capped at 15 percent of the base payroll — that is, if
    the uncapped wage line exceeds the base payroll times 0.15, the wage line
    is set to the base payroll times 0.15 — before any benefits loading."
    (0.20 wage proposal on base payroll 100*5000*2080 = 1040000000 caps to
    156000000; 1.10 coverage tier then yields year-1 line 171600000.)

    Design: Corner/calculations/costing_wage_drift_cap_applies
    """
    union = create_union(name="Union CP")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA CP",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=1_000_000_000_000,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"],
        union["id"],
        title="GWI 20%",
        proposal_type="ECONOMIC",
        wage_increase_pct=0.20,
        affected_headcount=100,
        includes_benefits=False,
    )
    scenario = get_success_data(
        api.create_costing_scenario(
            create_costing_scenario_payload(
                agreement_id=agreement["id"],
                name="cap",
                scenario_mode="FINAL",
                term_years=3,
                proposal_ids=[proposal["id"]],
            ),
            NEG1,
        )
    )
    scenario = get_success_data(
        api.transition_costing_scenario(scenario["id"], {"to_status": "COMPUTED"}, NEG1)
    )
    assert scenario["year_breakdown_cents"] == [171600000, 205920000, 247104000]
    assert scenario["subtotal_cents"] == 624624000
    assert scenario["reserve_cents"] == 31231200
    assert scenario["total_cost_cents"] == 655855200
