"""Block risk-heat step-decay: variants, bucket boundaries, and precision."""
import pytest

from test_helpers import (
    TEST_USERS,
    corroborate_report,
    create_active_agreement,
    create_officer,
    file_incident,
    make_officer_headers,
    move_report_to_under_review,
    set_clock,
    setup_group_with_member,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _heat_workspace(api, name, precinct, badge):
    """Group + REGISTERED block + one member + officer + ACTIVE agreement."""
    group, block, member = setup_group_with_member(name, precinct)
    officer = create_officer(badge, "Officer Heat", precinct)
    create_active_agreement(group["id"], officer, scope="FULL")
    return group, block, member, officer


def _corroborate(api, block_id, member, officer, occurred_at, severity,
                 category="TRAFFIC"):
    report = file_incident(block_id, member, category=category,
                           occurred_at=occurred_at, severity=severity)
    move_report_to_under_review(report["id"])
    corroborate_report(report["id"], officer)
    return report


class TestRiskHeatVariants:
    def test_heat_provisional_variant_counts_cleared_reports(self, api):
        """PRD §3.3: "While an `ACTIVE` data-sharing agreement covers the group,
        both corroborated and cleared reports contribute."
        PRD §3.3: "Each report's contribution is its `severity` multiplied by its
        bucket weight, rounded half-up to two decimal places per report, and the
        block's `risk_heat_score` is the sum of those rounded contributions over
        the block's reports in `CORROBORATED` or `CLEARED`."

        Design: Difficulty/dual_variant_calc/block_risk_heat_provisional_vs_corroborated_only
        """
        set_clock("2026-08-15T00:00:00Z")
        group, block, member, officer = _heat_workspace(
            api, "Heat Watch", "PCT2", "B200",
        )
        # 25 days old -> full weight; corroborated then cleared.
        r1 = _corroborate(api, block["id"], member, officer,
                          "2026-07-20T08:00:00Z", 4, "PROPERTY_CRIME")
        validate_success(
            api.clear_incident(r1["id"], make_officer_headers(officer["id"]))
        )
        # 50 days old -> half weight; stays CORROBORATED.
        _corroborate(api, block["id"], member, officer,
                     "2026-06-25T08:00:00Z", 3, "SUSPICIOUS_ACTIVITY")

        block_after = validate_success(api.get_block(block["id"], COORD))
        assert block_after["risk_heat_score"] == pytest.approx(5.5, abs=1e-6), (
            "PROVISIONAL variant: round2(4*1.0)=4.0 from the CLEARED report plus "
            "round2(3*0.5)=1.5 from the CORROBORATED report"
        )

    def test_heat_corroborated_only_variant_after_revocation(self, api):
        """PRD §3.3: "Once no active agreement covers the group — because it was
        revoked or expired — the corroborated-only variant applies: cleared
        reports whose disclosure was revoked contribute zero, while corroborated
        reports continue to contribute."
        PRD §3.5: "Both exits run the same cascade: every incident report of the
        group with `shared_with_liaison` true is re-scoped — the reports remain
        `CORROBORATED` or `CLEARED`, but new liaison reads are denied — roster
        enforcement tightens to the declared `roster_visibility`, and each
        affected block's heat is recomputed under the corroborated-only variant,
        excluding cleared reports whose disclosure has lapsed."

        Design: Difficulty/dual_variant_calc/block_risk_heat_provisional_vs_corroborated_only
        """
        set_clock("2026-08-15T00:00:00Z")
        group, block, member, officer = _heat_workspace(
            api, "Heat Watch", "PCT2", "B200",
        )
        r1 = _corroborate(api, block["id"], member, officer,
                          "2026-07-20T08:00:00Z", 4, "PROPERTY_CRIME")
        validate_success(
            api.clear_incident(r1["id"], make_officer_headers(officer["id"]))
        )
        _corroborate(api, block["id"], member, officer,
                     "2026-06-25T08:00:00Z", 3, "SUSPICIOUS_ACTIVITY")
        assert validate_success(api.get_block(block["id"], COORD))[
            "risk_heat_score"
        ] == pytest.approx(5.5, abs=1e-6)

        # Revoke the group's agreement: heat recomputes corroborated-only.
        agreements, _meta = validate_paginated(
            api.list_data_share_agreements(
                COORD, params={"watch_group_id": group["id"]},
            )
        )
        validate_success(api.revoke_data_share_agreement(agreements[0]["id"], COORD))

        block_after = validate_success(api.get_block(block["id"], COORD))
        assert block_after["risk_heat_score"] == pytest.approx(1.5, abs=1e-6), (
            "CORROBORATED_ONLY variant: the CLEARED report's 4.0 contribution "
            "drops out; the CORROBORATED report's 1.5 remains"
        )


class TestRiskHeatBucketBoundaries:
    def test_bucket_boundary_30_vs_31_days(self, api):
        """PRD §3.3: "A report aged no more than 30 days contributes at full
        weight; more than 30 and no more than 60 days contributes at half weight;
        more than 60 and no more than 90 days contributes at one-quarter weight;
        anything older contributes nothing."

        Design: Difficulty/boundary_precision_check/risk_heat_bucket_boundary_30_vs_31_days
        """
        set_clock("2026-08-31T00:00:00Z")
        group, block, member, officer = _heat_workspace(
            api, "Edge Watch", "PCT11", "B110",
        )
        # Age exactly 30 days -> full weight: contributes 2 * 1.0 = 2.0.
        _corroborate(api, block["id"], member, officer,
                     "2026-08-01T00:00:00Z", 2)
        # Age exactly 31 days -> half weight: contributes 2 * 0.5 = 1.0.
        _corroborate(api, block["id"], member, officer,
                     "2026-07-31T00:00:00Z", 2)

        block_after = validate_success(api.get_block(block["id"], COORD))
        assert block_after["risk_heat_score"] == pytest.approx(3.0, abs=1e-6), (
            "age 30d is inside the <=30 full bucket (2.0); age 31d falls to the "
            "half bucket (1.0); an off-by-one on the edge would give 4.0 or 2.0"
        )

    def test_bucket_boundary_60_vs_61_days(self, api):
        """PRD §3.3: "A report aged no more than 30 days contributes at full
        weight; more than 30 and no more than 60 days contributes at half weight;
        more than 60 and no more than 90 days contributes at one-quarter weight;
        anything older contributes nothing."

        Design: Difficulty/boundary_precision_check/risk_heat_bucket_boundary_30_vs_31_days
        """
        set_clock("2026-09-30T00:00:00Z")
        group, block, member, officer = _heat_workspace(
            api, "Edge Watch", "PCT11", "B110",
        )
        # Age exactly 60 days -> half weight: contributes 2 * 0.5 = 1.0.
        _corroborate(api, block["id"], member, officer,
                     "2026-08-01T00:00:00Z", 2)
        # Age exactly 61 days -> quarter weight: contributes 4 * 0.25 = 1.0.
        _corroborate(api, block["id"], member, officer,
                     "2026-07-31T00:00:00Z", 4)

        block_after = validate_success(api.get_block(block["id"], COORD))
        assert block_after["risk_heat_score"] == pytest.approx(2.0, abs=1e-6), (
            "age 60d is inside the <=60 half bucket (1.0); age 61d falls to the "
            "quarter bucket (1.0)"
        )


class TestRiskHeatPrecision:
    def test_per_term_two_decimal_half_up_rounding(self, api):
        """PRD §3.3: "Each report's contribution is its `severity` multiplied by
        its bucket weight, rounded half-up to two decimal places per report, and
        the block's `risk_heat_score` is the sum of those rounded contributions
        over the block's reports in `CORROBORATED` or `CLEARED`."
        PRD §2.9: "The block risk-heat score uses decimal arithmetic with
        per-term rounding: each incident's contribution is rounded half-up to
        exactly 2 decimal places before the contributions are summed."

        Design: Corner/calculations/block_risk_heat_per_term_rounding_precision
        """
        set_clock("2026-09-30T00:00:00Z")
        group, block, member, officer = _heat_workspace(
            api, "Prec Watch", "C03", "BC03",
        )
        # Age 66 days -> quarter weight: round2(5 * 0.25) = 1.25.
        _corroborate(api, block["id"], member, officer,
                     "2026-07-25T10:00:00Z", 5, "VANDALISM")
        # Age 40 days -> half weight: round2(1 * 0.5) = 0.5.
        _corroborate(api, block["id"], member, officer,
                     "2026-08-20T10:00:00Z", 1, "NOISE")

        block_after = validate_success(api.get_block(block["id"], COORD))
        assert block_after["risk_heat_score"] == pytest.approx(1.75, abs=1e-6), (
            "1.25 + 0.5 exactly — per-term rounding, no trailing-float noise"
        )
