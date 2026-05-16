"""LRE percentages and classification boundaries — PRD §3.8, §2.11.

Covers: dual-variant computation (instructional vs school-day),
classification boundaries (20.00 / 60.00 inclusive), PULL_OUT vs
PUSH_IN exclusion from numerator.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    LRE_A_UPPER_INCLUSIVE,
    LRE_B_UPPER_INCLUSIVE,
    activate_related_service,
    assert_lre_relationship,
    create_related_service_consent_approved,
    get_iep,
    get_lre_summary,
    get_student,
    propose_related_service,
    setup_active_iep,
    setup_active_iep_with_active_service,
    suspend_related_service,
)


class TestLrePercentageDualVariants:
    """PRD §3.8: instructional vs school-day denominator on the same
    numerator."""

    def test_dual_variant_same_numerator_different_denominator(
        self, api,
    ):
        """PRD §3.8: "lre_percentage_instructional is 100 multiplied
        by the pull-out-minutes numerator, divided by the IEP's
        total_instructional_minutes_per_week, rounded half-up to two
        decimal places."
        PRD §3.8: "lre_percentage_school_day is 100 multiplied by the
        same numerator, divided by the IEP's
        total_school_day_minutes_per_week, rounded half-up to two
        decimal places."

        Claim: with 300 PULL_OUT minutes on an IEP with
        instructional=1500 / school_day=1875, instructional_basis
        produces 20.00 and school_day_basis produces 16.00 — same
        numerator, different denominator, different percentage.

        # difficulty: dual_variant_calc/lre_percentage_dual_basis_on_iep
        """
        district, student, _eval, iep, _goal = setup_active_iep(
            total_instructional_minutes_per_week=1500,
            total_school_day_minutes_per_week=1875,
        )
        # Add a 300-minute OT PULL_OUT service, activate it.
        service = propose_related_service(
            district["id"], student["id"], iep["id"],
            service_type="OT", minutes_per_week=300,
            location_setting="PULL_OUT",
        )
        consent = create_related_service_consent_approved(
            district["id"], student["id"], service["id"],
            parent_user_id=student["parent_user_id"],
        )
        activate_related_service(
            district["id"], student["id"], iep["id"], service["id"],
            consent_id=consent["id"],
        )
        summary = get_lre_summary(
            district["id"], student["id"], iep["id"],
        )
        # 100*300/1500 = 20.00; 100*300/1875 = 16.00.
        assert summary["lre_percentage_instructional"] == pytest.approx(
            20.00, abs=0.01,
        )
        assert summary["lre_percentage_school_day"] == pytest.approx(
            16.00, abs=0.01,
        )
        # PRD §3.8 says classification is keyed exclusively to the
        # instructional-basis value; at 20.00 → LRE_A (boundary
        # inclusive).
        assert summary["lre_classification"] == "LRE_A"


class TestLreClassificationBoundaries:
    """PRD §3.8: 20.00 and 60.00 inclusive boundaries."""

    def test_lre_a_at_20_pct_inclusive(self, api):
        """PRD §3.8: "if the percentage is at most 20.00, the
        classification is LRE_A".

        Claim: lre_percentage_instructional == 20.00 exactly →
        LRE_A.
        """
        district, student, _eval, iep, _goal = setup_active_iep(
            total_instructional_minutes_per_week=1500,
            total_school_day_minutes_per_week=1875,
        )
        # 300 PULL_OUT minutes → 100*300/1500 = 20.00 exactly.
        service = propose_related_service(
            district["id"], student["id"], iep["id"],
            service_type="OT", minutes_per_week=300,
            location_setting="PULL_OUT",
        )
        consent = create_related_service_consent_approved(
            district["id"], student["id"], service["id"],
            parent_user_id=student["parent_user_id"],
        )
        activate_related_service(
            district["id"], student["id"], iep["id"], service["id"],
            consent_id=consent["id"],
        )
        s_now = get_student(district["id"], student["id"])
        assert s_now["lre_classification"] == "LRE_A"

    def test_lre_b_at_60_pct_inclusive(self, api):
        """PRD §3.8: "if the percentage is greater than 20.00 and at
        most 60.00, the classification is LRE_B".

        Claim: lre_percentage_instructional == 60.00 exactly → LRE_B.

        # difficulty: boundary_precision_check/lre_classification_inclusive_60_pct_boundary
        """
        district, student, _eval, iep, _goal = setup_active_iep(
            total_instructional_minutes_per_week=1500,
            total_school_day_minutes_per_week=1875,
        )
        # Activate three 300-min PULL_OUT services (different
        # service_types) to reach 900 sped minutes →
        # 100*900/1500 = 60.00.
        for st in ["OT", "PT", "SPEECH"]:
            svc = propose_related_service(
                district["id"], student["id"], iep["id"],
                service_type=st, minutes_per_week=300,
                location_setting="PULL_OUT",
            )
            c = create_related_service_consent_approved(
                district["id"], student["id"], svc["id"],
                parent_user_id=student["parent_user_id"],
            )
            activate_related_service(
                district["id"], student["id"], iep["id"], svc["id"],
                consent_id=c["id"],
            )
        iep_now = get_iep(district["id"], student["id"], iep["id"])
        assert iep_now["lre_percentage_instructional"] == pytest.approx(
            60.00, abs=0.01,
        )
        s_now = get_student(district["id"], student["id"])
        assert s_now["lre_classification"] == "LRE_B"

    def test_lre_c_strictly_above_60_pct(self, api):
        """PRD §3.8: "otherwise the classification is LRE_C".

        Claim: lre_percentage_instructional strictly above 60.00 →
        LRE_C.
        """
        district, student, _eval, iep, _goal = setup_active_iep(
            total_instructional_minutes_per_week=1500,
            total_school_day_minutes_per_week=1875,
        )
        # Activate four services totalling 915 PULL_OUT min →
        # 100*915/1500 = 61.00.
        sizes = [300, 300, 300, 15]
        for i, mpw in enumerate(sizes):
            svc = propose_related_service(
                district["id"], student["id"], iep["id"],
                service_type=["OT", "PT", "SPEECH",
                              "COUNSELING"][i],
                minutes_per_week=mpw,
                location_setting="PULL_OUT",
            )
            c = create_related_service_consent_approved(
                district["id"], student["id"], svc["id"],
                parent_user_id=student["parent_user_id"],
            )
            activate_related_service(
                district["id"], student["id"], iep["id"], svc["id"],
                consent_id=c["id"],
            )
        iep_now = get_iep(district["id"], student["id"], iep["id"])
        assert iep_now["lre_percentage_instructional"] == pytest.approx(
            61.00, abs=0.01,
        )
        s_now = get_student(district["id"], student["id"])
        assert s_now["lre_classification"] == "LRE_C"


class TestLreNumeratorComposition:
    """PRD §3.8."""

    def test_push_in_does_not_contribute_to_numerator(self, api):
        """PRD §3.8: "The numerator for both percentage variants is
        the sum of minutes_per_week over every RelatedService on this
        IEP that is currently in ACTIVE and whose location_setting
        is either PULL_OUT or COMMUNITY (services delivered as
        PUSH_IN happen inside the regular classroom and do not
        contribute)."

        Claim: with one PULL_OUT 200-min service and one PUSH_IN
        200-min service ACTIVE, the LRE numerator is 200, not 400.
        """
        district, student, _eval, iep, _goal = setup_active_iep(
            total_instructional_minutes_per_week=1500,
            total_school_day_minutes_per_week=1875,
        )
        ot = propose_related_service(
            district["id"], student["id"], iep["id"],
            service_type="OT", minutes_per_week=200,
            location_setting="PULL_OUT",
        )
        consent_ot = create_related_service_consent_approved(
            district["id"], student["id"], ot["id"],
            parent_user_id=student["parent_user_id"],
        )
        activate_related_service(
            district["id"], student["id"], iep["id"], ot["id"],
            consent_id=consent_ot["id"],
        )
        pt = propose_related_service(
            district["id"], student["id"], iep["id"],
            service_type="PT", minutes_per_week=200,
            location_setting="PUSH_IN",
        )
        consent_pt = create_related_service_consent_approved(
            district["id"], student["id"], pt["id"],
            parent_user_id=student["parent_user_id"],
        )
        activate_related_service(
            district["id"], student["id"], iep["id"], pt["id"],
            consent_id=consent_pt["id"],
        )
        summary = get_lre_summary(
            district["id"], student["id"], iep["id"],
        )
        # Numerator = 200 (PULL_OUT) only.
        assert summary["total_sped_minutes"] == 200
        # 100*200/1500 = 13.33.
        assert summary["lre_percentage_instructional"] == pytest.approx(
            13.33, abs=0.01,
        )

    def test_school_day_basis_le_instructional_basis(self, api):
        """PRD §3.8: "lre_percentage_school_day is less than or equal
        to lre_percentage_instructional for any identical numerator."

        Claim: invariant holds after activating a service.
        """
        district, student, iep, _service, _consent = (
            setup_active_iep_with_active_service(
                service_type="OT", minutes_per_week=300,
                location_setting="PULL_OUT",
                total_instructional_minutes_per_week=1500,
                total_school_day_minutes_per_week=1875,
            )
        )
        iep_now = get_iep(district["id"], student["id"], iep["id"])
        assert_lre_relationship(iep_now)
