"""ChildAuxiliary entitlement, termination, and family-max waterfall.

Covers PRD §3.5 (child_aux_calc + family_max_calc waterfall). Difficulty-
design coverage for rule 4 (child_termination_recompute_siblings_depth_2),
rule 7 (child_auxiliary_entitle_requires_parent_application_approved),
and rule 9 (family_max_pool_invariant_on_child_turnover).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_child_auxiliary,
    assert_pool_invariant,
    create_child_aux,
    create_child_auxiliary_payload,
    date_to_iso,
    entitle_child,
    get_application,
    list_child_auxiliaries_for_application,
    setup_application_approved_at_initial,
    setup_application_at_initial_review,
    setup_insured_claimant,
    terminate_child,
    utcnow,
    validate_error,
    validate_success,
)


class TestChildAuxiliaryCreation:

    def test_child_aux_creation_in_pending_status(self, api):
        """PRD §3.5: "A ChildAuxiliary is created by either the
        claimant or a DDS examiner in PENDING status".
        """
        claimant, application = setup_application_approved_at_initial()
        resp = api.create_child_auxiliary(
            create_child_auxiliary_payload(
                application_id=application["id"],
                child_date_of_birth="2015-01-15",
            ),
            TEST_USERS["dds_examiner_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_child_auxiliary(data)
        assert data["status"] == "PENDING"


class TestEntitlementGate:
    """Difficulty design rule 7: child_auxiliary_entitle_requires_parent_application_approved."""

    def test_entitle_before_parent_approved_returns_child_ineligible(self, api):
        """# difficulty: cross_entity_state_dependency/child_auxiliary_entitle_requires_parent_application_approved

        PRD §3.5: "Entitlement is a system-emitted transition that
        fires when the parent Application reaches APPROVED or
        ALJ_APPROVED; the precondition is that the parent
        application's status is in APPROVED or ALJ_APPROVED (otherwise
        ERR_PARENT_NOT_APPROVED, surfaced through the existence/state
        error family) and that the child is under 18 at entitlement,
        ... (otherwise ERR_CHILD_INELIGIBLE at HTTP status 422)."

        The parent-not-approved precondition is explicitly distinct
        from the age-eligibility precondition: PRD names them with
        two different identifiers and routes the parent gate "through
        the existence/state error family", whose catalog entry is
        ERR_INVALID_STATE (the catalogue has no ERR_PARENT_NOT_APPROVED).
        """
        # Parent application in INITIAL_REVIEW — not APPROVED.
        claimant, application, _ = setup_application_at_initial_review()
        child = create_child_aux(
            application["id"], child_date_of_birth="2015-01-15",
        )
        resp = api.entitle_child_auxiliary(
            child["id"], TEST_USERS["dds_examiner_headers"],
        )
        # Parent gate fires via the state-family route per PRD prose.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_entitle_after_parent_approved_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/child_auxiliary_entitle_requires_parent_application_approved

        PRD §3.5: "Entitlement is a system-emitted transition that
        fires when the parent Application reaches APPROVED or
        ALJ_APPROVED".

        Claim: same child entitle call succeeds once the parent reaches
        APPROVED.
        """
        claimant, application = setup_application_approved_at_initial()
        child = create_child_aux(
            application["id"], child_date_of_birth="2015-01-15",
        )
        data = entitle_child(child["id"])
        assert data["status"] == "ENTITLED"

    def test_entitle_child_over_18_not_student_not_disabled_rejected(self, api):
        """PRD §3.5: "the child is under 18 at entitlement, or is
        between 18 and 19 with is_full_time_student true, or has
        is_disabled_before_22 true (otherwise ERR_CHILD_INELIGIBLE at
        HTTP status 422)".
        """
        claimant, application = setup_application_approved_at_initial()
        # Child is currently 25 years old, not a student, not
        # disabled_before_22.
        adult_dob = date_to_iso(utcnow().date() - timedelta(days=365 * 25))
        child = create_child_aux(
            application["id"],
            child_date_of_birth=adult_dob,
            is_full_time_student=False,
            is_disabled_before_22=False,
        )
        resp = api.entitle_child_auxiliary(
            child["id"], TEST_USERS["dds_examiner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CHILD_INELIGIBLE.value)


class TestFamilyMaxWaterfall:
    """Difficulty design rule 2 (mode_b) and rule 9."""

    def _entitled_benefits(self, application_id: str):
        rows = list_child_auxiliaries_for_application(application_id)
        return sorted(
            [r for r in rows if r["status"] == "ENTITLED"],
            key=lambda r: (r["child_date_of_birth"], r["created_at"]),
        )

    def test_single_child_receives_per_child_gross(self, api):
        """PRD §3.5: "The per-child gross is the floor of half of
        pia_cents. If the count of entitled children multiplied by
        that gross is at most the pool, each child receives the
        gross."
        """
        claimant, application = setup_application_approved_at_initial()
        pia = application["pia_cents"]
        fm = application["family_max_cents"]
        pool = fm - pia
        gross_per_child = pia // 2
        child = create_child_aux(
            application["id"], child_date_of_birth="2015-01-15",
        )
        child = entitle_child(child["id"])
        # PRD: if 1 * gross <= pool, child receives gross.
        if gross_per_child <= pool:
            assert child["monthly_benefit_cents"] == gross_per_child, (
                f"single child: expected {gross_per_child}, got "
                f"{child['monthly_benefit_cents']} (pia={pia}, pool={pool})"
            )
        else:
            assert child["monthly_benefit_cents"] == pool, (
                f"single child capped at pool {pool}, got "
                f"{child['monthly_benefit_cents']}"
            )

    def test_family_max_pool_invariant_across_turnover(self, api):
        """# difficulty: compensating_invariant/family_max_pool_invariant_on_child_turnover

        PRD §3.5: "The worker always receives the full pia_cents. The
        remaining pool — family_max_cents minus pia_cents — is
        distributed across the children whose ChildAuxiliary.status is
        ENTITLED."
        PRD §3.5: "Every ChildAuxiliary.monthly_benefit_cents is
        recomputed at every event that changes the entitled
        population — a new entitlement or a termination".

        Claim: sum of entitled child benefits stays bounded by the
        pool at each entitle/terminate event.
        """
        claimant, application = setup_application_approved_at_initial()
        pia = application["pia_cents"]
        fm = application["family_max_cents"]
        pool = fm - pia
        gross_per_child = pia // 2

        # Entitle 2 children
        c1 = create_child_aux(
            application["id"], child_date_of_birth="2010-01-01",
        )
        c2 = create_child_aux(
            application["id"], child_date_of_birth="2012-06-15",
        )
        entitle_child(c1["id"])
        entitle_child(c2["id"])
        entitled = self._entitled_benefits(application["id"])
        total_after_2 = sum(c["monthly_benefit_cents"] for c in entitled)
        expected_total_2 = min(2 * gross_per_child, pool)
        assert total_after_2 == expected_total_2, (
            f"after 2 children: total={total_after_2}, "
            f"expected min(2*{gross_per_child}, {pool}) = {expected_total_2}"
        )

        # Entitle a 3rd child
        c3 = create_child_aux(
            application["id"], child_date_of_birth="2014-09-20",
        )
        entitle_child(c3["id"])
        entitled = self._entitled_benefits(application["id"])
        total_after_3 = sum(c["monthly_benefit_cents"] for c in entitled)
        expected_total_3 = min(3 * gross_per_child, pool)
        assert total_after_3 == expected_total_3, (
            f"after 3 children: total={total_after_3}, "
            f"expected min(3*{gross_per_child}, {pool}) = {expected_total_3}"
        )

        # Terminate the third child — siblings should be recomputed.
        terminate_child(c3["id"], "NO_LONGER_DISABLED")
        entitled = self._entitled_benefits(application["id"])
        total_after_term = sum(c["monthly_benefit_cents"] for c in entitled)
        expected_total_after_term = min(2 * gross_per_child, pool)
        assert total_after_term == expected_total_after_term, (
            f"after termination of 3rd: total={total_after_term}, "
            f"expected {expected_total_after_term}"
        )

    def test_remainder_distributed_to_oldest_children(self, api):
        """# difficulty: combinatorial_formula/family_max_waterfall_rounding_order_mode_b

        PRD §3.5: "Otherwise the per-child share is the integer
        division of the pool by the count of entitled children; the
        remainder (the pool minus the per-child share multiplied by
        the count) is distributed one cent at a time to the oldest
        entitled children first, ordering by child_date_of_birth
        ascending with ties broken by created_at ascending. Each of
        the first (remainder) children receives one more cent than the
        others."

        Claim: when remainder > 0, the oldest children receive
        share+1, others share.
        """
        claimant, application = setup_application_approved_at_initial()
        pia = application["pia_cents"]
        fm = application["family_max_cents"]
        pool = fm - pia
        gross_per_child = pia // 2

        # Create three children oldest-first. If 3*gross > pool, the
        # waterfall splits pool/3 with remainder going to the oldest two.
        oldest = create_child_aux(
            application["id"], child_date_of_birth="2010-01-01",
        )
        middle = create_child_aux(
            application["id"], child_date_of_birth="2012-06-15",
        )
        youngest = create_child_aux(
            application["id"], child_date_of_birth="2014-09-20",
        )
        for c in (oldest, middle, youngest):
            entitle_child(c["id"])

        entitled = self._entitled_benefits(application["id"])
        # entitled sorted by date_of_birth ASC ties broken by created_at
        n = 3
        if n * gross_per_child > pool:
            each = pool // n
            rem = pool - each * n
            # Oldest `rem` children receive each+1, the rest each.
            expected = [each + 1] * rem + [each] * (n - rem)
            actual = [c["monthly_benefit_cents"] for c in entitled]
            assert actual == expected, (
                f"waterfall: expected {expected}, got {actual} "
                f"(pool={pool}, each={each}, rem={rem})"
            )
        else:
            # No remainder split needed; everyone gets gross_per_child.
            for c in entitled:
                assert c["monthly_benefit_cents"] == gross_per_child


class TestSiblingRecomputeOnTerminate:
    """Difficulty design rule 4: child_termination_recompute_siblings_depth_2."""

    def test_terminate_recomputes_siblings(self, api):
        """# difficulty: transitive_cascade/child_termination_recompute_siblings_depth_2

        PRD §3.5: "Every ChildAuxiliary.monthly_benefit_cents is
        recomputed at every event that changes the entitled
        population — a new entitlement or a termination".

        Depth-2 cascade: hop 1 mutates the terminated child; hop 2
        recomputes surviving siblings.
        """
        claimant, application = setup_application_approved_at_initial()
        pia = application["pia_cents"]
        fm = application["family_max_cents"]
        pool = fm - pia
        gross_per_child = pia // 2

        c1 = create_child_aux(
            application["id"], child_date_of_birth="2010-01-01",
        )
        c2 = create_child_aux(
            application["id"], child_date_of_birth="2012-06-15",
        )
        c3 = create_child_aux(
            application["id"], child_date_of_birth="2014-09-20",
        )
        for c in (c1, c2, c3):
            entitle_child(c["id"])
        # Terminate the youngest.
        terminate_child(c3["id"], "NO_LONGER_DISABLED")
        # Surviving children should have monthly_benefit_cents
        # recomputed.
        entitled = sorted(
            [r for r in list_child_auxiliaries_for_application(application["id"])
             if r["status"] == "ENTITLED"],
            key=lambda r: (r["child_date_of_birth"], r["created_at"]),
        )
        assert len(entitled) == 2
        n = 2
        if n * gross_per_child <= pool:
            for c in entitled:
                assert c["monthly_benefit_cents"] == gross_per_child
        else:
            each = pool // n
            rem = pool - each * n
            expected = [each + 1] * rem + [each] * (n - rem)
            actual = [c["monthly_benefit_cents"] for c in entitled]
            assert actual == expected
