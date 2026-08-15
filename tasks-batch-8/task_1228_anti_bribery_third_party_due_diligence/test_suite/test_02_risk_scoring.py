"""Risk scoring: provisional vs final variants, tier boundaries, sanction override."""
import pytest

from test_helpers import (
    admin_headers,
    create_draft_third_party,
    disposition_check,
    get_check_ids,
    get_third_party,
    issue_questionnaire,
    officer_headers,
    setup_risk_basis,
    setup_third_party_in_state,
    sponsor_headers,
    submit_questionnaire,
    submit_third_party,
    validate_success,
)


class TestProvisionalVsFinalVariants:
    """Both variants over identical base inputs: provisional 73/HIGH at submit,
    final 100/CRITICAL once the accepted questionnaire (+10) and the confirmed
    PEP hit (+20) are folded in and the sum is clamped."""

    def _setup_br_third_party_with_pep_hit(self, api):
        """BR (cpi 30 -> norm 70), CONSULTING/DIRECT, PEP hit confirmed, other
        checks CLEAR, questionnaire submitted with government_ownership_pct=25."""
        setup_risk_basis("BR", 30)
        tp = create_draft_third_party("BR", "CONSULTING", "DIRECT",
                                      legal_name="BR Consulting Ltd")
        submitted = submit_third_party(tp["id"])
        pep_id, am_id, san_id = get_check_ids(tp["id"])
        disposition_check(pep_id, "POTENTIAL_HIT",
                          match_detail="beneficial owner is a sitting mayor")
        disposition_check(pep_id, "HIT_CONFIRMED")
        disposition_check(am_id, "CLEAR")
        disposition_check(san_id, "CLEAR")
        q = issue_questionnaire(tp["id"])
        submit_questionnaire(q["id"], government_ownership_pct=25)
        return tp["id"], submitted, q["id"]

    def test_provisional_variant_scores_73_high(self, api):
        """PRD §3.2: "Multiply `country_norm` by `w_country`, the industry score
        by `w_industry`, and the touchpoint score by `w_touchpoint`; sum the
        three products; divide by 100; and round half-up to an integer between 0
        and 100."
        PRD §3.1: "Its three tier thresholds, `tier_medium_min`, `tier_high_min`,
        and `tier_critical_min`, are inclusive lower bounds: a score at or above
        `tier_critical_min` maps to `CRITICAL`; otherwise a score at or above
        `tier_high_min` maps to `HIGH`; otherwise a score at or above
        `tier_medium_min` maps to `MEDIUM`; anything lower is `LOW`."

        Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_final_on_third_party
        """
        _, submitted, _ = self._setup_br_third_party_with_pep_hit(api)
        # (50*70 + 30*60 + 20*100) / 100 = 73 — base-only weighted formula.
        assert submitted["risk_score_provisional"] == 73, (
            f"provisional must be 73, got {submitted['risk_score_provisional']}"
        )
        assert submitted["risk_tier"] == "HIGH"

    def test_final_variant_clamps_to_100_critical(self, api):
        """PRD §3.4: "The questionnaire modifier is 10 when
        `government_ownership_pct` is above zero, plus 15 when
        `has_facilitation_payments` is true, plus 5 when `uses_sub_agents` is
        true. The screening modifier sums 20 for each confirmed `PEP` hit and 10
        for each confirmed `ADVERSE_MEDIA` hit across the party's checks. The sum
        is clamped to the 0-to-100 band."
        PRD §3.4: "For identical base inputs the two variants therefore differ
        whenever any modifier is non-zero — a provisional 73 can become a final
        100."
        PRD §3.3: "the `PEP` and `ADVERSE_MEDIA` increments are reserved for the
        final variant described in §3.4"

        Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_final_on_third_party
        """
        tp_id, _, q_id = self._setup_br_third_party_with_pep_hit(api)
        accept_resp = api.accept_questionnaire(q_id, officer_headers())
        validate_success(accept_resp, 200)

        tp = get_third_party(tp_id)
        # 73 + 10 (gov ownership) + 20 (confirmed PEP) = 103, clamped to 100.
        assert tp["risk_score_final"] == 100, (
            f"final must clamp to 100, got {tp['risk_score_final']}"
        )
        assert tp["risk_tier"] == "CRITICAL"
        assert tp["risk_score_provisional"] == 73, (
            "the final variant must not overwrite the provisional field"
        )


class TestSanctionedOverrideBranch:
    """Flipping a country's sanctions flag overrides the weighted arithmetic."""

    def _setup_ir_third_party_in_screening(self, api):
        basis = setup_risk_basis("IR", 36, sanctioned=False)
        tp = create_draft_third_party("IR", "CONSULTING", "DIRECT",
                                      legal_name="IR Consulting")
        submitted = submit_third_party(tp["id"])
        return basis["country"]["id"], tp["id"], submitted

    def test_sanctioned_flip_forces_score_100_critical(self, api, admin_headers):
        """PRD §3.1: "Flipping `sanctioned` to true is graver still — every
        non-terminal third party in that country is forced to a score of 100 and
        the `CRITICAL` tier, and the system raises a `SYSTEM`-sourced red flag of
        `CRITICAL` severity on each, which auto-escalates exactly as a confirmed
        sanctions hit would: the flag moves to `UNDER_ENHANCED_REVIEW`, an
        escalation case opens in `ENHANCED_DD` with a null
        `escalated_by_user_id`, and the third party itself drops from `APPROVED`
        to `SUSPENDED` or, if still mid-onboarding, from `SCREENING` or
        `DD_REVIEW` to `ENHANCED_REVIEW`."

        Design: Difficulty/combinatorial_formula/risk_score_weighted_override_branch
        """
        profile_id, tp_id, submitted = self._setup_ir_third_party_in_screening(api)
        # (50*64 + 30*60 + 20*100) / 100 = 70 -> HIGH before the flip.
        assert submitted["risk_score_provisional"] == 70
        assert submitted["risk_tier"] == "HIGH"

        resp = api.update_country_profile(profile_id, {"sanctioned": True}, admin_headers)
        validate_success(resp, 200)

        tp = get_third_party(tp_id)
        assert tp["risk_score_provisional"] == 100, (
            "sanctioned override ignores the weighted arithmetic"
        )
        assert tp["risk_tier"] == "CRITICAL"
        assert tp["onboarding_status"] == "ENHANCED_REVIEW", (
            "SCREENING party is pushed into ENHANCED_REVIEW by the auto-escalation"
        )

    def test_sanctioned_flip_raises_system_critical_flag_and_case(self, api, admin_headers):
        """PRD §3.1: "Flipping `sanctioned` to true is graver still — every
        non-terminal third party in that country is forced to a score of 100 and
        the `CRITICAL` tier, and the system raises a `SYSTEM`-sourced red flag of
        `CRITICAL` severity on each, which auto-escalates exactly as a confirmed
        sanctions hit would: the flag moves to `UNDER_ENHANCED_REVIEW`, an
        escalation case opens in `ENHANCED_DD` with a null
        `escalated_by_user_id`, and the third party itself drops from `APPROVED`
        to `SUSPENDED` or, if still mid-onboarding, from `SCREENING` or
        `DD_REVIEW` to `ENHANCED_REVIEW`."

        Design: Difficulty/combinatorial_formula/risk_score_weighted_override_branch
        """
        profile_id, tp_id, _ = self._setup_ir_third_party_in_screening(api)
        resp = api.update_country_profile(profile_id, {"sanctioned": True}, admin_headers)
        validate_success(resp, 200)

        flags_resp = api.list_red_flags(tp_id, officer_headers())
        flags = validate_success(flags_resp, 200)
        assert len(flags) == 1
        flag = flags[0]
        assert flag["source_type"] == "SYSTEM"
        assert flag["severity"] == "CRITICAL"
        assert flag["flag_status"] == "UNDER_ENHANCED_REVIEW"

        cases_resp = api.list_escalation_cases(tp_id, officer_headers())
        cases = validate_success(cases_resp, 200)
        assert len(cases) == 1
        assert cases[0]["case_status"] == "ENHANCED_DD"
        assert cases[0]["escalated_by_user_id"] is None


class TestTierBoundaryPrecision:
    """Inclusive >= tier thresholds: score 69 is MEDIUM, score 70 is HIGH."""

    def _submit(self, api, country, cpi, industry, touchpoint, name):
        setup_risk_basis(country, cpi)
        tp = create_draft_third_party(country, industry, touchpoint, legal_name=name)
        return submit_third_party(tp["id"])

    def test_score_69_maps_medium(self, api):
        """PRD §3.1: "Its three tier thresholds, `tier_medium_min`,
        `tier_high_min`, and `tier_critical_min`, are inclusive lower bounds: a
        score at or above `tier_critical_min` maps to `CRITICAL`; otherwise a
        score at or above `tier_high_min` maps to `HIGH`; otherwise a score at or
        above `tier_medium_min` maps to `MEDIUM`; anything lower is `LOW`."
        PRD §3.2: "Multiply `country_norm` by `w_country`, the industry score by
        `w_industry`, and the touchpoint score by `w_touchpoint`; sum the three
        products; divide by 100; and round half-up to an integer between 0 and
        100."

        Design: Difficulty/boundary_precision_check/risk_tier_boundary_69_medium_vs_70_high
        """
        # VE cpi 44 -> norm 56; CONSTRUCTION 70; DIRECT 100:
        # (50*56 + 30*70 + 20*100) / 100 = 69 — one below the HIGH boundary.
        submitted = self._submit(api, "VE", 44, "CONSTRUCTION", "DIRECT", "VE Builders")
        assert submitted["risk_score_provisional"] == 69
        assert submitted["risk_tier"] == "MEDIUM"

    def test_score_70_maps_high(self, api):
        """PRD §3.1: "Its three tier thresholds, `tier_medium_min`,
        `tier_high_min`, and `tier_critical_min`, are inclusive lower bounds: a
        score at or above `tier_critical_min` maps to `CRITICAL`; otherwise a
        score at or above `tier_high_min` maps to `HIGH`; otherwise a score at or
        above `tier_medium_min` maps to `MEDIUM`; anything lower is `LOW`."
        PRD §3.2: "Multiply `country_norm` by `w_country`, the industry score by
        `w_industry`, and the touchpoint score by `w_touchpoint`; sum the three
        products; divide by 100; and round half-up to an integer between 0 and
        100."

        Design: Difficulty/boundary_precision_check/risk_tier_boundary_69_medium_vs_70_high
        """
        # CU cpi 36 -> norm 64; CONSULTING 60; DIRECT 100:
        # (50*64 + 30*60 + 20*100) / 100 = 70 — exactly on the inclusive boundary.
        submitted = self._submit(api, "CU", 36, "CONSULTING", "DIRECT", "CU Advisors")
        assert submitted["risk_score_provisional"] == 70
        assert submitted["risk_tier"] == "HIGH"


class TestSubmitSideEffectsInline:
    def test_submit_creates_three_screening_checks_inline(self, api, officer_headers):
        """PRD §3.2: "A successful submit computes `risk_score_provisional` and
        the first `risk_tier`, auto-creates three screening checks — one `PEP`,
        one `ADVERSE_MEDIA`, one `SANCTIONS`, created in that order and each
        `QUEUED`, so the created-at-ascending list of a party's checks reads in
        the same order — and increments the third party's `version` by one."

        Design: Corner/state_machines/submit_creates_three_screening_checks_inline
        """
        ctx = setup_third_party_in_state("DRAFT", "CH", 80, "TECHNOLOGY", "NONE")
        tp_id = ctx["third_party"]["id"]

        resp = api.submit_third_party(tp_id, sponsor_headers())
        data = validate_success(resp, 200)
        # CH cpi 80 -> norm 20; TECHNOLOGY 20; NONE 0: (50*20 + 30*20 + 0)/100 = 16.
        assert data["onboarding_status"] == "SCREENING"
        assert data["risk_score_provisional"] == 16
        assert data["risk_tier"] == "LOW"

        checks_resp = api.list_screening_checks(tp_id, officer_headers)
        checks = validate_success(checks_resp, 200)
        assert [c["check_type"] for c in checks] == ["PEP", "ADVERSE_MEDIA", "SANCTIONS"]
        assert all(c["check_status"] == "QUEUED" for c in checks)

    def test_mutation_visible_in_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.2: "Submitting the third party moves `onboarding_status` from
        `DRAFT` to `SCREENING`."

        Design: Corner/consistency_model/mutation_visible_in_same_response
        """
        ctx = setup_third_party_in_state("DRAFT", "CH", 80, "TECHNOLOGY", "NONE")
        tp_id = ctx["third_party"]["id"]

        resp = api.submit_third_party(tp_id, sponsor_headers())
        data = validate_success(resp, 200)
        # No follow-up GET is needed: the mutation response itself carries it.
        assert data["onboarding_status"] == "SCREENING"
        assert data["risk_score_provisional"] == 16
        assert data["risk_tier"] == "LOW"
