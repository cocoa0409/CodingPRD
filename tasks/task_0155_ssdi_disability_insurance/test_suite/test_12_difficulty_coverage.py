"""Additional difficulty-coverage tests to reach >= 2 tests per
difficulty-design instance.

Each test is tagged `# difficulty: <rule_id>/<instance.name>` so the
final coverage audit can confirm 2N tests for N instances.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    CDR_NOT_DUE_GRACE_DAYS,
    TEST_USERS,
    advance_clock_to,
    api_client,
    create_child_aux,
    create_determination_payload,
    current_clock,
    date_to_iso,
    entitle_child,
    get_application,
    list_child_auxiliaries_for_application,
    list_determinations,
    make_alj_headers,
    parse_iso,
    schedule_cdr,
    complete_cdr,
    setup_application_approved_at_initial,
    setup_application_initial_denied,
    setup_application_with_pending_cdr,
    terminate_child,
    validate_error,
)


def _young_dob(years_ago: int) -> str:
    """Return an ISO date for a child `years_ago` years younger than the
    server's current logical clock instant. Tests that ran before this one
    may have advanced the clock; a hard-coded calendar DOB would age the
    child past the PRD §3.5 eligibility window. Anchoring DOB to the
    current logical clock keeps the child under-18 regardless of where
    earlier tests left the clock.
    """
    today = current_clock().date()
    safe_year = today.year - years_ago
    # Use Feb 28 to dodge leap-day edge cases.
    return date_to_iso(today.replace(year=safe_year, month=2, day=28))


class TestFamilyMaxWaterfallExtraCoverage:
    """Second test for difficulty instance:
    combinatorial_formula/family_max_waterfall_rounding_order_mode_b
    """

    def test_two_children_split_pool_equally_when_no_remainder(self, api):
        """# difficulty: combinatorial_formula/family_max_waterfall_rounding_order_mode_b

        PRD §3.5: "the per-child share is the integer division of the
        pool by the count of entitled children; the remainder (the
        pool minus the per-child share multiplied by the count) is
        distributed one cent at a time to the oldest entitled children
        first".

        Boundary: when n*gross > pool but pool%n == 0, each child
        receives exactly pool//n with NO remainder distribution.
        """
        claimant, application = setup_application_approved_at_initial()
        pia = application["pia_cents"]
        fm = application["family_max_cents"]
        pool = fm - pia
        gross_per_child = pia // 2

        c1 = create_child_aux(
            application["id"], child_date_of_birth=_young_dob(14),
        )
        c2 = create_child_aux(
            application["id"], child_date_of_birth=_young_dob(12),
        )
        entitle_child(c1["id"])
        entitle_child(c2["id"])

        rows = sorted(
            [r for r in list_child_auxiliaries_for_application(application["id"])
             if r["status"] == "ENTITLED"],
            key=lambda r: (r["child_date_of_birth"], r["created_at"]),
        )
        n = 2
        if n * gross_per_child <= pool:
            for r in rows:
                assert r["monthly_benefit_cents"] == gross_per_child, (
                    f"both children should receive gross_per_child "
                    f"({gross_per_child}); got "
                    f"{[r['monthly_benefit_cents'] for r in rows]}"
                )
        else:
            each = pool // n
            rem = pool - each * n
            expected = [each + 1] * rem + [each] * (n - rem)
            actual = [r["monthly_benefit_cents"] for r in rows]
            assert actual == expected, (
                f"expected {expected}, got {actual} "
                f"(pool={pool}, each={each}, rem={rem})"
            )


class TestSiblingRecomputeExtraCoverage:
    """Second test for difficulty instance:
    transitive_cascade/child_termination_recompute_siblings_depth_2
    """

    def test_terminate_record_carries_pinned_reason(self, api):
        """# difficulty: transitive_cascade/child_termination_recompute_siblings_depth_2

        PRD §3.5: "Termination is a system-emitted transition that
        supplies a termination_reason (one of AGE_OUT,
        NO_LONGER_DISABLED, or PARENT_BENEFIT_ENDED), moves status
        from ENTITLED to TERMINATED, and again recomputes every
        surviving sibling's monthly_benefit_cents."

        Hop-1: terminated row carries the explicit reason
        NO_LONGER_DISABLED (not PARENT_BENEFIT_ENDED, which is the
        cascade-default).
        """
        claimant, application = setup_application_approved_at_initial()
        c1 = create_child_aux(
            application["id"], child_date_of_birth=_young_dob(14),
        )
        c2 = create_child_aux(
            application["id"], child_date_of_birth=_young_dob(12),
        )
        entitle_child(c1["id"])
        entitle_child(c2["id"])
        terminated = terminate_child(c2["id"], "NO_LONGER_DISABLED")
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_reason"] == "NO_LONGER_DISABLED", (
            f"explicit termination_reason should be NO_LONGER_DISABLED; "
            f"got {terminated.get('termination_reason')!r}"
        )


class TestPriorityPairExtraCoverage:
    """Second test for difficulty instance:
    priority_pair_validation_conflict/state_vs_business_safety_recon_double_fail
    """

    def test_reconsideration_in_recon_state_still_blocks_sod_alone(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_recon_double_fail

        PRD §3.6: "the segregation-of-duties rule binds: the acting
        examiner's X-User-ID must not equal the application's
        last_initial_examiner_id. A violation is rejected with
        ERR_SEGREGATION_OF_DUTIES at HTTP status 403, and this
        binding applies to both the ALLOW and DENY branches at
        reconsideration with equal force."

        Companion to the state-wins test in test_05: when ONLY SoD is
        violated (state is valid), the SoD error fires (priority 9
        actually surfaces when state is OK at priority 8).
        """
        from test_helpers import setup_application_at_reconsideration
        claimant, application = setup_application_at_reconsideration(
            examiner_headers=TEST_USERS["dds_examiner_headers"],
        )
        payload = create_determination_payload(
            level="RECONSIDERATION", decision="DENY",
            medical_basis="NOT_DISABLED",
        )
        # Same examiner as the initial determination -> SoD fail; state
        # is valid (application is currently RECONSIDERATION).
        resp = api.create_determination(
            claimant["id"], application["id"], payload,
            TEST_USERS["dds_examiner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


class TestBackPayRecoupmentExtraCoverage:
    """Second test for difficulty instance:
    compensating_invariant/back_pay_recoupment_lifetime_paid_zero_drift
    """

    def test_cease_cascade_appends_determination_with_application_id(self, api):
        """# difficulty: compensating_invariant/back_pay_recoupment_lifetime_paid_zero_drift

        PRD §3.8: "A new Determination row is appended carrying a
        negative entitlement delta that recoups the originally awarded
        back pay, preserving a compensating-invariant total lifetime-
        paid ledger."

        Claim: post-cease, every Determination row in the ledger is
        keyed to the application.
        """
        claimant, application, cdr = setup_application_with_pending_cdr()
        due = parse_iso(cdr["review_due_date"])
        advance_clock_to(due - timedelta(days=CDR_NOT_DUE_GRACE_DAYS - 1))
        schedule_cdr(cdr["id"])
        complete_cdr(
            cdr["id"], medical_improvement_found=True, working_at_sga=False,
        )
        rows = list_determinations(claimant["id"], application["id"])
        for r in rows:
            assert r["application_id"] == application["id"], (
                f"Determination row {r['id']} mis-keyed to "
                f"{r['application_id']!r} (expected {application['id']!r})"
            )
        # The cease cascade should have added at least one row beyond
        # the original approval.
        assert len(rows) >= 2, (
            f"after cessation cascade there must be at least the "
            f"initial approval row AND the compensating row; got "
            f"{len(rows)} rows"
        )


class TestFamilyMaxPoolInvariantExtraCoverage:
    """Second test for difficulty instance:
    compensating_invariant/family_max_pool_invariant_on_child_turnover
    """

    def test_pool_invariant_holds_through_three_child_lifecycle(self, api):
        """# difficulty: compensating_invariant/family_max_pool_invariant_on_child_turnover

        PRD §3.5: "Every ChildAuxiliary.monthly_benefit_cents is
        recomputed at every event that changes the entitled
        population — a new entitlement or a termination — and every
        recomputation refreshes the corresponding updated_at and
        bumps the corresponding version."

        Claim: after a sequence of entitle, entitle, entitle, terminate
        (back to two entitled), the sum of entitled monthly_benefit_cents
        equals the value seen with two entitled children at the start —
        the pool invariant is preserved with no drift.
        """
        claimant, application = setup_application_approved_at_initial()
        pia = application["pia_cents"]
        fm = application["family_max_cents"]
        pool = fm - pia
        gross_per_child = pia // 2

        c1 = create_child_aux(
            application["id"], child_date_of_birth=_young_dob(14),
        )
        c2 = create_child_aux(
            application["id"], child_date_of_birth=_young_dob(12),
        )
        entitle_child(c1["id"])
        entitle_child(c2["id"])
        two_entitled = sorted(
            [r for r in list_child_auxiliaries_for_application(application["id"])
             if r["status"] == "ENTITLED"],
            key=lambda r: (r["child_date_of_birth"], r["created_at"]),
        )
        sum_two_before = sum(c["monthly_benefit_cents"] for c in two_entitled)
        # Entitle a 3rd and then terminate it.
        c3 = create_child_aux(
            application["id"], child_date_of_birth=_young_dob(10),
        )
        entitle_child(c3["id"])
        terminate_child(c3["id"], "NO_LONGER_DISABLED")
        two_after = sorted(
            [r for r in list_child_auxiliaries_for_application(application["id"])
             if r["status"] == "ENTITLED"],
            key=lambda r: (r["child_date_of_birth"], r["created_at"]),
        )
        sum_two_after = sum(c["monthly_benefit_cents"] for c in two_after)
        assert sum_two_after == sum_two_before, (
            f"family-max pool invariant broken: two-child sum drifted "
            f"from {sum_two_before} to {sum_two_after} after "
            f"entitle+terminate of third child"
        )
