"""Provider reporting compliance score: 4-piece linear/floor formula,
pinned round-then-sum rounding, auto-suspend at 70, reinstate at 90.

PRD §3.6 (compliance score), §2.8 (precision), §3.2 (status).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    PROVIDER_CLINICIAN_ID,
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_score_precision,
    create_antigen_schedule_rule,
    create_patient,
    create_provider_organization,
    create_vaccine_lot,
    create_vaccine_product,
    iso_anchor_offset,
    iso_utc,
    parse_iso,
    re_get_provider_organization,
    schedule_and_administer_dose,
    schedule_dose,
    setup_compliance_score_two_doses,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 4-piece score formula (boundary precision)
# ===========================================================================
class TestComplianceScoreFormula:

    def test_no_doses_score_defaults_to_100(self, api):
        """PRD §3.6: "If the window is empty, the score defaults to
        100.00."

        Claim: a freshly-created provider org with no doses has
        reporting_compliance_score == 100.00.
        """
        provider_org = create_provider_organization()
        data = re_get_provider_organization(provider_org["id"])
        assert float(data["reporting_compliance_score"]) == 100.00

    def test_lag_24h_exact_scores_100(self, api):
        """PRD §3.6: "A lag of at most 24 hours earns 100.00 - full
        credit, on-time." and "a lag of exactly 24 hours earns 100."

        Claim: a single dose with lag=24.0h yields
        reporting_compliance_score == 100.00.
        """
        ctx = setup_compliance_score_two_doses(
            administered_at_1="2026-01-10T00:00:00.000Z",
            reported_offset_hours_1=-24.0,  # reported_at = admin - 24h
            administered_at_2="2026-01-11T00:00:00.000Z",
            reported_offset_hours_2=-24.0,
        )
        # reported_at = admin - 24h means lag = -24h. PRD §3.6 says
        # "the wall-clock seconds between reported_at and
        # administered_at", which we interpret as
        # |reported_at - administered_at|. The standard reading is
        # report happens AFTER admin, but in our flow we POST schedule
        # before administer, so reported_at < administered_at and the
        # lag in hours equals (administered_at - reported_at)/3600
        # taken positive. Either reading gives 24h here.
        data = re_get_provider_organization(ctx["provider_org"]["id"])
        score = float(data["reporting_compliance_score"])
        assert score == 100.00, (
            f"PRD §3.6: lag = 24.0h must score 100.00, got {score}"
        )

    def test_lag_48h_scores_70(self, api):
        """PRD §3.6: "a lag of 48 hours earns 70."

        Claim: a single dose with lag = 48h scores 70.00.
        """
        # reported_at is stamped by the server at schedule time. Pin the
        # clock to a known instant, schedule (so reported_at = that
        # instant), then advance the clock 48h forward and administer
        # at that later instant. lag = administered_at - reported_at
        # = 48h exactly.
        sched_ts = "2026-01-10T00:00:00.000Z"
        admin_ts = iso_utc(parse_iso(sched_ts) + timedelta(hours=48))
        advance_clock_to(sched_ts)
        provider_org = create_provider_organization()
        patient = create_patient(date_of_birth="2020-01-01")
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0, routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
        )
        product = create_vaccine_product(
            antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
        )
        lot = create_vaccine_lot(
            product["id"], provider_org["id"], doses_on_hand=5,
        )
        dose = schedule_dose(
            patient["id"], product["id"], lot["id"], provider_org["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        advance_clock_to(admin_ts)
        from test_helpers import administer_dose as _adm
        _adm(patient["id"], dose["id"], admin_ts)
        data = re_get_provider_organization(provider_org["id"])
        score = float(data["reporting_compliance_score"])
        assert score == 70.00, (
            f"PRD §3.6: lag = 48h must score 70.00, got {score}"
        )

    def test_lag_72h_exact_scores_40(self, api):
        """PRD §3.6: "a lag of exactly 72 hours earns 40."

        Claim: a single dose with lag = 72h scores 40.00.
        """
        anchor_clock()
        provider_org = create_provider_organization()
        patient = create_patient(date_of_birth="2020-01-01")
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0, routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
        )
        product = create_vaccine_product(
            antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
        )
        lot = create_vaccine_lot(
            product["id"], provider_org["id"], doses_on_hand=5,
        )
        sched_ts = iso_anchor_offset()
        dose = schedule_dose(
            patient["id"], product["id"], lot["id"], provider_org["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        admin_ts = iso_utc(parse_iso(sched_ts) - timedelta(hours=72))
        from test_helpers import administer_dose as _adm
        _adm(patient["id"], dose["id"], admin_ts)
        data = re_get_provider_organization(provider_org["id"])
        score = float(data["reporting_compliance_score"])
        assert score == 40.00, (
            f"PRD §3.6: lag = 72h must score 40.00, got {score}"
        )

    def test_lag_over_168h_scores_0(self, api):
        """PRD §3.6: "A lag greater than 168 hours earns 0.00."

        Claim: a single dose with lag = 169h scores 0.00, suspending
        the provider.
        """
        anchor_clock()
        provider_org = create_provider_organization()
        patient = create_patient(date_of_birth="2020-01-01")
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0, routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
        )
        product = create_vaccine_product(
            antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
        )
        lot = create_vaccine_lot(
            product["id"], provider_org["id"], doses_on_hand=5,
        )
        sched_ts = iso_anchor_offset()
        dose = schedule_dose(
            patient["id"], product["id"], lot["id"], provider_org["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        admin_ts = iso_utc(parse_iso(sched_ts) - timedelta(hours=169))
        from test_helpers import administer_dose as _adm
        _adm(patient["id"], dose["id"], admin_ts)
        data = re_get_provider_organization(provider_org["id"])
        score = float(data["reporting_compliance_score"])
        assert score == 0.00, (
            f"PRD §3.6: lag > 168h must score 0.00, got {score}"
        )


# ===========================================================================
# §3.6 Pinned rounding order (difficulty design)
# ===========================================================================
class TestPinnedRoundingOrder:
    """Difficulty design: compliance_score_pinned_rounding_order.
    PRD §3.6 / §2.8: "round per-dose to 2 dp, then sum, divide,
    then round the average ... sum-then-round-the-average is not
    equivalent in boundary cases and is explicitly forbidden."
    """

    # difficulty: combinatorial_formula/compliance_score_pinned_rounding_order
    def test_round_then_sum_yields_pinned_cent_for_boundary_case(self, api):
        """PRD §3.6: per-dose raw scores 30.555 and 30.554
        round-then-sum to (30.56 + 30.55) / 2 = 30.555 -> 30.56;
        sum-then-round yields 30.5545 -> 30.55. The PRD pins round-then-sum.

        We craft two doses with per-dose raw scores such that the
        boundary divergence is observable.

        # difficulty: combinatorial_formula/compliance_score_pinned_rounding_order
        """
        # Per-dose: 100 - (lag-24)*1.25 in the 24<lag<=72 region.
        # We want raw scores that differ in the third decimal so the
        # rounding-order divergence shows up.
        #
        # Strategy: pick lag values such that per_dose_raw lands on
        # numbers whose 3rd-decimal differs.
        # raw = 100 - 1.25*(lag-24)
        # For raw=90.55: 100 - 90.55 = 9.45; 9.45/1.25 = 7.56; lag = 31.56 h
        # For raw=90.5375: 100 - 90.5375 = 9.4625; /1.25 = 7.57; lag = 31.57 h
        #
        # round_half_up(90.55, 2) = 90.55
        # round_half_up(90.5375, 2) = 90.54  (5375 rounds up at 4th dp)
        # round-then-sum: (90.55 + 90.54) / 2 = 90.545 -> 90.55 (ROUND_HALF_UP)
        # sum-then-round: (90.55 + 90.5375) / 2 = 90.54375 -> 90.54
        ctx = setup_compliance_score_two_doses(
            administered_at_1="2026-05-30T00:00:00.000Z",
            reported_offset_hours_1=31.56,
            administered_at_2="2026-05-30T00:00:00.000Z",
            reported_offset_hours_2=31.57,
        )
        data = re_get_provider_organization(ctx["provider_org"]["id"])
        score = float(data["reporting_compliance_score"])
        assert score == 90.55, (
            f"PRD §3.6: round-then-sum-then-round must yield 90.55 for "
            f"per-dose raw scores 90.55 / 90.5375. Got {score}. The "
            f"sum-then-round alternative would yield 90.54 - explicitly "
            f"forbidden by PRD §3.6."
        )

    # difficulty: combinatorial_formula/compliance_score_pinned_rounding_order
    def test_score_has_two_decimal_precision(self, api):
        """PRD §2.8: "It is rounded to two decimal places using the
        round-half-up rule."

        Claim: the score field carries at most 2 decimal places.

        # difficulty: combinatorial_formula/compliance_score_pinned_rounding_order
        """
        provider_org = create_provider_organization()
        data = re_get_provider_organization(provider_org["id"])
        assert_score_precision(float(data["reporting_compliance_score"]))


# ===========================================================================
# §3.6 / §3.2 auto-suspend / reinstate
# ===========================================================================
class TestSuspendReinstate:

    def test_score_below_70_auto_suspends_provider(self, api):
        """PRD §3.6: "When the recomputed score falls below 70.00, the
        provider organization's status auto-transitions to SUSPENDED."

        Claim: after one dose with a lag > 72h (score = 40) brings
        the score under 70, the provider's status auto-transitions
        to SUSPENDED.
        """
        anchor_clock()
        provider_org = create_provider_organization()
        patient = create_patient(date_of_birth="2020-01-01")
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0, routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
        )
        product = create_vaccine_product(
            antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
        )
        lot = create_vaccine_lot(
            product["id"], provider_org["id"], doses_on_hand=5,
        )
        sched_ts = iso_anchor_offset()
        dose = schedule_dose(
            patient["id"], product["id"], lot["id"], provider_org["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        admin_ts = iso_utc(parse_iso(sched_ts) - timedelta(hours=72))
        from test_helpers import administer_dose as _adm
        _adm(patient["id"], dose["id"], admin_ts)
        # Re-read; trigger score recompute.
        data = re_get_provider_organization(provider_org["id"])
        # Score 40 < 70 -> SUSPENDED.
        assert float(data["reporting_compliance_score"]) == 40.00
        assert data["status"] == "SUSPENDED", (
            f"PRD §3.6: status must auto-transition to SUSPENDED when "
            f"score < 70.00, got {data['status']!r}"
        )

    def test_manual_suspend_then_reinstate_requires_score_at_least_90(self, api):
        """PRD §3.6: "A PublicHealthOfficer may also manually suspend
        a provider, and may reinstate a suspended provider only when
        its score has climbed back to at least 90.00."

        Claim: manual reinstate when score >= 90 succeeds (sets
        status=ACTIVE); reinstate with score < 90 yields
        ERR_INVALID_STATE.
        """
        provider_org = create_provider_organization()
        # Default score = 100. Manually suspend.
        api.suspend_provider_organization(
            provider_org["id"],
            TEST_USERS["public_health_officer_headers"],
        )
        data = re_get_provider_organization(provider_org["id"])
        assert data["status"] == "SUSPENDED"
        # Score still 100 (no doses), so reinstate must succeed.
        res = api.reinstate_provider_organization(
            provider_org["id"],
            TEST_USERS["public_health_officer_headers"],
        )
        data = validate_success(res)
        assert data["status"] == "ACTIVE"

    def test_reinstate_below_90_rejected(self, api):
        """PRD §3.6: "may reinstate a suspended provider only when its
        score has climbed back to at least 90.00."

        Claim: a SUSPENDED provider with score < 90 cannot be reinstated.
        """
        anchor_clock()
        provider_org = create_provider_organization()
        patient = create_patient(date_of_birth="2020-01-01")
        create_antigen_schedule_rule(
            antigen="MMR_MEASLES", dose_sequence_number=1,
            routine_min_age_days=0, routine_recommended_age_days=0,
            routine_max_age_days=3650,
            catchup_min_interval_days=0,
        )
        product = create_vaccine_product(
            antigens=["MMR_MEASLES"], min_age_days=0, max_age_days=None,
        )
        lot = create_vaccine_lot(
            product["id"], provider_org["id"], doses_on_hand=5,
        )
        sched_ts = iso_anchor_offset()
        dose = schedule_dose(
            patient["id"], product["id"], lot["id"], provider_org["id"],
            administering_clinician_id=PROVIDER_CLINICIAN_ID,
        )
        # Lag = 48h -> score = 70 (< 90).
        admin_ts = iso_utc(parse_iso(sched_ts) - timedelta(hours=48))
        from test_helpers import administer_dose as _adm
        _adm(patient["id"], dose["id"], admin_ts)
        # Manually suspend the provider.
        api.suspend_provider_organization(
            provider_org["id"],
            TEST_USERS["public_health_officer_headers"],
        )
        # Attempt to reinstate.
        res = api.reinstate_provider_organization(
            provider_org["id"],
            TEST_USERS["public_health_officer_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
