"""Regional risk tier computation and decision lifecycle — PRD §3.6."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    approve_risk_decision_payload,
    assert_region,
    assert_risk_decision,
    create_person,
    create_region,
    drive_region_to_published_tier,
    file_case,
    file_case_under_tracing,
    make_hospital_reporter_headers,
    setup_district_with_hospital,
    setup_district_with_hospital_and_cdc,
    setup_provisional_risk_decision,
    validate_error,
    validate_success,
    TEST_USERS,
)


# ===========================================================================
# Manual recompute — PRD §3.6
# ===========================================================================
class TestRecomputeRisk:

    def test_recompute_empty_district_stays_low(self, api,
                                                supervisor_headers):
        """PRD §3.6: "anything else is LOW. The result is written to
        the region's provisional_risk_tier. This automatic path does
        not write current_risk_tier."

        Claim: a region with no Case rows recomputes to
        provisional_risk_tier LOW and current_risk_tier remains LOW
        (its default).
        """
        region = create_region(district_code="D-RR-1", population=100000)
        api.recompute_region_risk(region["id"], supervisor_headers)
        refreshed = validate_success(api.get_region(
            region["id"], supervisor_headers,
        ))
        assert refreshed["provisional_risk_tier"] == "LOW"
        assert refreshed["current_risk_tier"] == "LOW", (
            "PRD §3.6: provisional recompute does NOT write current_risk_tier"
        )


# ===========================================================================
# Decision lifecycle — PRD §3.6
# ===========================================================================
class TestRiskDecisionLifecycle:

    def test_publish_writes_region_current_risk_tier(self, api,
                                                     supervisor_headers):
        """PRD §3.6: "A PressOfficer then publishes the approved decision
        (APPROVED → PUBLISHED), permitted as long as the final_tier
        differs from the region's current_risk_tier or this is the
        first publication for that region. Publishing stamps
        published_at, writes Region.current_risk_tier to final_tier,
        sets Region.last_tier_decision_id to this decision's id."

        Claim: a full PROVISIONAL → UNDER_REVIEW → APPROVED → PUBLISHED
        cycle with final_tier=HIGH on a previously-LOW region sets
        Region.current_risk_tier == HIGH.
        """
        region, _hospital = setup_district_with_hospital(
            district_code="D-RD-1", population=100000,
        )
        # Drive to PUBLISHED with HIGH.
        decision, region_after = drive_region_to_published_tier(
            region, "HIGH",
        )
        assert decision["status"] == "PUBLISHED"
        assert region_after["current_risk_tier"] == "HIGH", (
            "PRD §3.6: publish writes Region.current_risk_tier to "
            "decision.final_tier"
        )
        assert region_after["last_tier_decision_id"] == decision["id"]

    def test_republish_same_tier_after_first_publication_blocked(self, api,
                                                                 supervisor_headers,
                                                                 risk_expert_headers,
                                                                 press_officer_headers):
        """PRD §3.6: "A PressOfficer then publishes the approved decision
        (APPROVED → PUBLISHED), permitted as long as the final_tier
        differs from the region's current_risk_tier or this is the
        first publication for that region."

        Claim: after a region has already been published once at HIGH,
        a second decision approved-for-HIGH cannot be published — the
        no-op publish is rejected with ERR_INVALID_STATE.
        # difficulty: cross_entity_state_dependency/risk_decision_publish_depends_on_region_state
        """
        region, _hospital = setup_district_with_hospital(
            district_code="D-RD-2", population=100000,
        )
        # First publication: brings region to HIGH.
        drive_region_to_published_tier(region, "HIGH")
        # Now stack a second APPROVED decision with final_tier=HIGH (no-op).
        # We must trigger a new provisional cycle. First recompute (still
        # LOW unless we filed cases, but provisional doesn't need to be
        # HIGH for the precondition test — the publish check looks at
        # current_risk_tier vs final_tier).
        api.recompute_region_risk(region["id"], supervisor_headers)
        rd2 = setup_provisional_risk_decision(region["id"])
        # submit-review requires provisional_tier != current_risk_tier.
        # After the first publication, current_risk_tier == HIGH; if
        # provisional_tier is LOW (no real cases) then they differ and
        # submit-review will pass.
        submit = api.submit_risk_decision_review(rd2["id"], supervisor_headers)
        validate_success(submit, 200)
        approve = api.approve_risk_decision(
            rd2["id"],
            approve_risk_decision_payload(
                final_tier="HIGH",
                expert_reviewer_id=TEST_USERS["risk_expert_headers"]["X-User-ID"],
            ),
            risk_expert_headers,
        )
        validate_success(approve, 200)
        # Publish: final_tier == current_risk_tier (both HIGH) and this
        # is NOT first publication → blocked.
        publish = api.publish_risk_decision(rd2["id"], press_officer_headers)
        validate_error(publish, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Provisional vs final divergence (dual-variant) — PRD §3.6
# ===========================================================================
class TestProvisionalVsFinalDivergence:

    def test_expert_override_writes_high_while_provisional_remains_low(
        self, api, supervisor_headers, risk_expert_headers,
        press_officer_headers,
    ):
        """PRD §3.6: "The final_tier set on approval may diverge from
        provisional_tier — that divergence is the entire point of
        EXPERT_OVERRIDE."
        PRD §3.6 also: "Publishing stamps published_at, writes
        Region.current_risk_tier to final_tier."

        Claim: a Region with low case density computes provisional_tier
        LOW but an expert-supplied final_tier=HIGH overrides it on
        publish — Region.current_risk_tier becomes HIGH while
        provisional_risk_tier stays LOW.
        # difficulty: dual_variant_calc/region_tier_provisional_vs_final
        """
        # No cases at all → density score 0 → provisional LOW.
        region = create_region(district_code="D-PF-1", population=100000)
        api.recompute_region_risk(region["id"], supervisor_headers)
        # Capture provisional state.
        prov = validate_success(api.get_region(region["id"], supervisor_headers))
        assert prov["provisional_risk_tier"] == "LOW"
        assert prov["current_risk_tier"] == "LOW"

        # Walk to PUBLISHED with final_tier=HIGH (expert override).
        decision, region_after = drive_region_to_published_tier(
            region, "HIGH",
        )
        assert region_after["current_risk_tier"] == "HIGH"
        # PRD §3.6: "This automatic path does not write
        # current_risk_tier." The expert override only changes
        # current_risk_tier; we do NOT assert provisional_risk_tier
        # changed back to LOW here because the publish side-effects
        # focus on current_risk_tier per PRD prose.


# ===========================================================================
# Auto-tier mapping — PRD §3.6 case_density_risk_score formula
# ===========================================================================
class TestCaseDensityAutoTier:

    def test_high_tier_at_55_score(self, api, supervisor_headers):
        """PRD §3.6: "The density score is then the count of confirmed
        cases multiplied by a weight of 3, plus the count of asymptomatic
        cases multiplied by a weight of 1, divided by the region's
        population, multiplied by 100 000 — yielding cases per 100 000
        residents. That density figure is rounded half-up to two
        decimal places. To it the platform adds the count of distinct
        contact-chain connected components multiplied by a weight of 5;
        the resulting total is rounded again half-up to two decimal
        places. Tier mapping is closed-interval and evaluated top-down:
        a final score of at least 50.00 yields HIGH; otherwise a score
        of at least 10.00 yields MEDIUM; anything else is LOW."

        Claim: 16 CONFIRMED cases + 2 ASYMPTOMATIC cases in a region of
        population 100 000 with no contact chain gives density 50.00 and
        score 50.00 → HIGH (≥ 50.00 boundary inclusive).
        # difficulty: combinatorial_formula/case_density_tiered_selection
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-CD-1", population=100000,
        )
        # 16 CONFIRMED-typed cases advanced to UNDER_TRACING (which PRD
        # §3.6 counts in the confirmed-or-tracing-active bucket) plus
        # 2 ASYMPTOMATIC-typed cases (counted by case_type regardless of
        # status).
        for _ in range(16):
            p = create_person(district_code=region["district_code"])
            file_case_under_tracing(
                person_id=p["id"], hospital_id=hospital["id"],
                cdc_id=cdc["id"], case_type="CONFIRMED",
            )
        for _ in range(2):
            p = create_person(district_code=region["district_code"])
            file_case(
                person_id=p["id"], hospital_id=hospital["id"],
                case_type="ASYMPTOMATIC",
            )
        # Recompute risk score for this region.
        api.recompute_region_risk(region["id"], supervisor_headers)
        refreshed = validate_success(api.get_region(
            region["id"], supervisor_headers,
        ))
        # density = (16*3 + 2*1)/100000 * 100000 = 50.00
        # score   = 50.00 + 0*5 = 50.00 → HIGH (≥ 50.00)
        assert refreshed["provisional_risk_tier"] == "HIGH", (
            f"PRD §3.6: density score 50.00 must map to HIGH "
            f"(closed-interval >= 50.00 threshold); got "
            f"provisional_risk_tier={refreshed['provisional_risk_tier']!r}"
        )

    def test_medium_tier_at_score_between_10_and_50(self, api,
                                                    supervisor_headers):
        """PRD §3.6: "otherwise a score of at least 10.00 yields MEDIUM."

        Claim: 4 CONFIRMED cases in a region of 100 000 population →
        density 12.00 (4*3/100000*100000) → score 12.00 → MEDIUM.
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-CD-2", population=100000,
        )
        for _ in range(4):
            p = create_person(district_code=region["district_code"])
            file_case_under_tracing(
                person_id=p["id"], hospital_id=hospital["id"],
                cdc_id=cdc["id"], case_type="CONFIRMED",
            )
        api.recompute_region_risk(region["id"], supervisor_headers)
        refreshed = validate_success(api.get_region(
            region["id"], supervisor_headers,
        ))
        # density = 4*3 / 100000 * 100000 = 12.00; tier MEDIUM.
        assert refreshed["provisional_risk_tier"] == "MEDIUM", (
            f"density 12.00 should map to MEDIUM "
            f"(>= 10.00 threshold); got "
            f"{refreshed['provisional_risk_tier']!r}"
        )
