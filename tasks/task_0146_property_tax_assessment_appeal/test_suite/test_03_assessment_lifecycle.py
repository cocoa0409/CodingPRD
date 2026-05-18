"""Assessment lifecycle and capped-value computation (PRD §3.2).

Covers DRAFT → ISSUED (with capped-value branches), ISSUED →
UNDER_APPEAL, UNDER_APPEAL → ISSUED (cycle), ISSUED → FINALIZED via
clock, UNDER_APPEAL → FINALIZED via last appeal decided, plus
ERR_DUPLICATE_ROLL_YEAR.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    GROWTH_CAP,
    add_days_iso,
    advance_clock_to,
    assert_assessment,
    create_assessment,
    create_owner,
    create_property,
    file_appeal,
    get_assessment,
    issue_assessment,
    setup_issued_assessment,
    setup_owner_and_property,
    transfer_property_owner,
    validate_error,
    validate_success,
)


# ===========================================================================
# DRAFT → ISSUED and the capped-value computation — PRD §3.2
# ===========================================================================
class TestCappedValueOnIssue:

    def test_first_roll_resets_to_market(self, api):
        """PRD §3.2: 'If prior_capped_value equals zero (which is true
        on the property's first roll) ... then capped_value is set
        equal to market_value_at_roll and cap_reset_applied is True.'

        Claim: a property's very first Assessment sets
        capped_value=market_value_at_roll and cap_reset_applied=True.
        """
        owner, prop = setup_owner_and_property(market_value=500_000.00)
        draft = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=600_000.00,
        )
        issued = issue_assessment(
            property_id=prop["id"], assessment_id=draft["id"],
        )
        assert_assessment(issued)
        assert issued["status"] == "ISSUED"
        assert issued["capped_value"] == pytest.approx(
            600_000.00, abs=0.01,
        ), (
            f"First-roll capped_value must equal market_value_at_roll, "
            f"got {issued['capped_value']}"
        )
        assert issued["cap_reset_applied"] is True

    def test_growth_cap_dominates_when_market_grew_more_than_2pct(self, api):
        """PRD §3.2: 'the server first computes a ceiling equal to
        prior_capped_value multiplied by 1.02 (one plus the system
        growth-cap constant GROWTH_CAP, which is 2 percent — the
        Prop-13-style annual growth cap), then rounded half up to two
        decimal places. The capped_value is then the smaller of
        market_value_at_roll and that ceiling.'

        Claim: when market_value_at_roll > prior_capped_value * 1.02,
        capped_value = ceiling (here 500000*1.02 = 510000.00) and
        cap_reset_applied is False.

        # difficulty: dual_variant_calc/capped_value_growth_vs_reset_on_property
        """
        # Use roll years strictly in the past relative to wall-clock
        # "today" so that the property's ownership_change_date (set at
        # creation = current server time) does NOT fall inside either
        # roll year and therefore does NOT trigger the §3.2 reset
        # branch ("ownership_change_date ... falls on or after midnight
        # UTC on January 1 of the Assessment's roll_year and on or
        # before 23:59:59 UTC on December 31 of that same year").
        owner, prop = setup_owner_and_property(market_value=500_000.00)
        # First roll establishes prior_capped_value=500000.
        d1 = create_assessment(
            property_id=prop["id"], roll_year=2010,
            market_value_at_roll=500_000.00,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=d1["id"],
        )
        # Second roll: market grows 20% — growth cap should clamp at
        # 510000. PRD §3.2 says prior_assessment_id resolves to the
        # most recent Assessment with strictly lesser roll_year, which
        # is the 2010 roll; its capped_value (500000) is read directly.
        d2 = create_assessment(
            property_id=prop["id"], roll_year=2011,
            market_value_at_roll=600_000.00,
        )
        issued2 = issue_assessment(
            property_id=prop["id"], assessment_id=d2["id"],
        )
        assert issued2["status"] == "ISSUED"
        # 500000 * 1.02 = 510000.00.
        assert issued2["capped_value"] == pytest.approx(
            510_000.00, abs=0.01,
        ), (
            f"growth_capped variant: capped_value must be 510000.00, "
            f"got {issued2['capped_value']}"
        )
        assert issued2["cap_reset_applied"] is False

    def test_market_below_ceiling_caps_at_market(self, api):
        """PRD §3.2: 'The capped_value is then the smaller of
        market_value_at_roll and that ceiling.'

        Claim: when market_value_at_roll < ceiling, capped_value =
        market_value_at_roll and cap_reset_applied is False.
        """
        # Use roll years strictly in the past so the property's
        # ownership_change_date does NOT fall inside the second roll
        # year (which would trigger the §3.2 reset branch).
        owner, prop = setup_owner_and_property(market_value=500_000.00)
        d1 = create_assessment(
            property_id=prop["id"], roll_year=2010,
            market_value_at_roll=500_000.00,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=d1["id"],
        )
        # Market grew only $1, so capped_value = 500_001 < 510_000.
        d2 = create_assessment(
            property_id=prop["id"], roll_year=2011,
            market_value_at_roll=500_001.00,
        )
        issued2 = issue_assessment(
            property_id=prop["id"], assessment_id=d2["id"],
        )
        assert issued2["capped_value"] == pytest.approx(
            500_001.00, abs=0.01,
        )
        assert issued2["cap_reset_applied"] is False

    def test_ownership_change_inside_roll_year_resets_to_market(self, api):
        """PRD §3.2: 'or if ownership_change_date is not null and
        falls on or after midnight UTC on January 1 of the
        Assessment's roll_year and on or before 23:59:59 UTC on
        December 31 of that same year, then capped_value is set equal
        to market_value_at_roll and cap_reset_applied is True. The
        growth cap is bypassed in this branch.'

        Claim: ownership transferred inside the 2026 roll year forces
        the 2026 Assessment to reset_to_market.

        # difficulty: dual_variant_calc/capped_value_growth_vs_reset_on_property
        """
        # 1st roll establishes prior_capped_value.
        owner1, prop = setup_owner_and_property(market_value=500_000.00)
        d1 = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=500_000.00,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=d1["id"],
        )
        asmt_iss = get_assessment(prop["id"], d1["id"])
        advance_clock_to(
            add_days_iso(asmt_iss["appeal_window_closes_at"], 1),
        )
        # Transfer ownership AFTER advancing into 2026 — establishes
        # ownership_change_date inside roll_year=2026.
        advance_clock_to("2026-03-01T00:00:00.000Z")
        owner2 = create_owner()
        # Refresh property version.
        from test_helpers import api_client, TEST_USERS
        prop_resp = api_client.get_property(
            prop["id"], TEST_USERS["assessor_headers"],
        )
        prop_data = validate_success(prop_resp)
        transfer_property_owner(
            property_id=prop["id"], new_owner_id=owner2["id"],
            version=prop_data["version"],
        )
        # New roll for 2026 with elevated market — should RESET to
        # market because ownership_change_date falls inside roll_year.
        d2 = create_assessment(
            property_id=prop["id"], roll_year=2026,
            market_value_at_roll=600_000.00,
        )
        issued2 = issue_assessment(
            property_id=prop["id"], assessment_id=d2["id"],
        )
        assert issued2["capped_value"] == pytest.approx(
            600_000.00, abs=0.01,
        ), (
            f"reset_to_market variant: capped_value=market_value_at_roll, "
            f"got {issued2['capped_value']}"
        )
        assert issued2["cap_reset_applied"] is True


# ===========================================================================
# Duplicate roll year — PRD §3.2
# ===========================================================================
class TestDuplicateRollYear:

    def test_second_issue_for_same_roll_year_rejected(self, api):
        """PRD §3.2: 'at most one Assessment per property may exist in
        any of ISSUED, UNDER_APPEAL, or FINALIZED status for the same
        roll year, and any attempt to issue a second triggers
        ERR_DUPLICATE_ROLL_YEAR.'

        Claim: creating + issuing a second Assessment for the same
        (property_id, roll_year) is rejected with
        ERR_DUPLICATE_ROLL_YEAR on the second issue.
        """
        owner, prop = setup_owner_and_property()
        d1 = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=500_000.00,
        )
        issue_assessment(
            property_id=prop["id"], assessment_id=d1["id"],
        )
        # Second draft for the same year + try to issue.
        d2 = create_assessment(
            property_id=prop["id"], roll_year=2025,
            market_value_at_roll=520_000.00,
        )
        from test_helpers import api_client, TEST_USERS
        resp = api_client.issue_assessment(
            prop["id"], d2["id"], TEST_USERS["assessor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ROLL_YEAR.value)


# ===========================================================================
# Cycle: ISSUED → UNDER_APPEAL → ISSUED → UNDER_APPEAL → ISSUED — PRD §3.2,
# §3.5
# ===========================================================================
class TestAssessmentCycle:

    def test_assessment_cycles_through_under_appeal_and_back(self, api):
        """PRD §3.2: 'If an Owner files an Appeal against the
        Assessment before the appeal window closes, the Assessment
        automatically transitions ISSUED → UNDER_APPEAL.' PRD §3.5:
        'If no remaining Appeal on the Assessment is in FILED,
        SCHEDULED, or HEARD, the Assessment reverts UNDER_APPEAL →
        ISSUED and is once again appeal-eligible'.

        Claim: file → withdraw → file → withdraw cycles the Assessment
        ISSUED → UNDER_APPEAL → ISSUED → UNDER_APPEAL → ISSUED.

        # difficulty: non_linear_state_machine/assessment_appeal_cycle
        """
        from test_helpers import withdraw_appeal
        owner, prop, assessment = setup_issued_assessment()
        # File first Appeal.
        a1 = file_appeal(
            owner=owner, property_id=prop["id"],
            assessment_id=assessment["id"], claimed_value=100_000.00,
        )
        s1 = get_assessment(prop["id"], assessment["id"])
        assert s1["status"] == "UNDER_APPEAL", (
            f"Assessment must be UNDER_APPEAL after first Appeal filed, "
            f"got {s1['status']}"
        )
        # Withdraw A1 — last open Appeal, Assessment reverts.
        withdraw_appeal(
            owner=owner, property_id=prop["id"], appeal_id=a1["id"],
        )
        s2 = get_assessment(prop["id"], assessment["id"])
        assert s2["status"] == "ISSUED", (
            f"Assessment must revert UNDER_APPEAL → ISSUED after the "
            f"last open Appeal is withdrawn, got {s2['status']}"
        )
        # File a 2nd Appeal.
        a2 = file_appeal(
            owner=owner, property_id=prop["id"],
            assessment_id=assessment["id"], claimed_value=120_000.00,
        )
        s3 = get_assessment(prop["id"], assessment["id"])
        assert s3["status"] == "UNDER_APPEAL"
        # Withdraw A2 — back to ISSUED.
        withdraw_appeal(
            owner=owner, property_id=prop["id"], appeal_id=a2["id"],
        )
        s4 = get_assessment(prop["id"], assessment["id"])
        assert s4["status"] == "ISSUED"


# ===========================================================================
# Auto-FINALIZE via clock — PRD §3.2
# ===========================================================================
class TestAutoFinalizeOnAppealWindowClose:

    def test_clock_past_window_auto_finalizes_with_no_appeal(self, api):
        """PRD §3.2: 'If, instead, the logical clock advances past
        appeal_window_closes_at without any Appeal having been filed,
        the Assessment automatically transitions ISSUED → FINALIZED
        (recording finalized_at), and a TaxBill is auto-created in
        PENDING status with taxable_value and base_tax_amount already
        computed.'

        Claim: clock advanced past appeal_window_closes_at flips
        Assessment from ISSUED to FINALIZED (no appeal filed).
        """
        owner, prop, asmt = setup_issued_assessment()
        advance_clock_to(
            add_days_iso(asmt["appeal_window_closes_at"], 1),
        )
        refreshed = get_assessment(prop["id"], asmt["id"])
        assert refreshed["status"] == "FINALIZED", (
            f"Assessment must auto-FINALIZE after clock advances past "
            f"appeal_window_closes_at with no Appeal filed; got "
            f"{refreshed['status']}"
        )
