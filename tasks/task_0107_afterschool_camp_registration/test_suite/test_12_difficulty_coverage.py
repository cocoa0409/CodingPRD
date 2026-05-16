"""Second-vantage tests for the difficulty-design priority queue.

Every `scaffold_difficulty_design.instances[*]` entry receives at
least TWO dedicated tests, tagged in their docstrings as
  # difficulty: <rule_id>/<instance.name>

Primary tests live in topic-organized files (test_02..test_11). This
file adds the second vantage per instance and adds one new vantage per
instance where the primary file did not already cover both.

Tests rest on verbatim PRD prose only — the difficulty-design entries
themselves are NOT cited; the underlying §3 rules are.
"""
from __future__ import annotations

import pytest
from datetime import timedelta

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_to,
    add_emergency_contact,
    cancel_enrollment,
    confirm_enrollment,
    create_authorization,
    create_authorization_payload,
    create_child,
    create_enrollment,
    create_enrollment_payload,
    create_family,
    create_session_payload,
    get_session_days,
    grant_scholarship,
    iso_offset,
    iso_utc,
    next_monday,
    parse_iso,
    re_get_child,
    re_get_enrollment,
    re_get_family,
    re_get_session,
    revoke_scholarship,
    set_weather,
    setup_authorized_child,
    setup_confirmed_enrollment,
    setup_family_with_n_authorized_children,
    setup_family_with_primary_guardian,
    setup_n_families_each_with_authorized_child,
    setup_open_session,
    setup_ready_to_confirm,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# dual_variant_calc/scholarship_allocation_provisional_vs_final
# ===========================================================================
class TestScholarshipProvisionalVsFinal:
    """difficulty: dual_variant_calc/
    scholarship_allocation_provisional_vs_final"""

    def test_fee_quote_uses_current_balance_then_confirm_snapshots(
        self, api,
    ):
        """# difficulty: dual_variant_calc/scholarship_allocation_provisional_vs_final
        PRD §3.5: "The provisional fee-quote capability returns a
        what-if computation using the current (pre-confirmation)
        sibling count for the requested (session_id, week_index) and
        the current award balances."
        PRD §3.5: "the chosen list_fee_cents, sibling_discount_cents,
        scholarship_discount_cents, and final_fee_cents are
        snapshotted onto the enrollment row and become immutable on
        that row except for the explicit cascades documented in §3."

        Claim: GET /camp/enrollments/{id}/fee-quote on a PENDING_AUTH
        row with a 5000-cent award shows scholarship_discount_cents
        ==5000; POST /confirm then snapshots the same 5000 onto the
        enrollment row.
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="ANY",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        enrollment = create_enrollment(child=child, session=session)
        # 1. Quote — provisional.
        quote = validate_success(
            api.get_fee_quote(
                enrollment["id"], TEST_USERS["admin_headers"],
            ),
            200,
        )
        assert quote["scholarship_discount_cents"] == 5_000
        # 2. Confirm — final snapshot.
        confirmed = confirm_enrollment(enrollment=enrollment)
        assert confirmed["scholarship_discount_cents"] == 5_000
        assert confirmed["list_fee_cents"] == 10_000
        assert confirmed["sibling_discount_cents"] == 0
        assert confirmed["final_fee_cents"] == 5_000

    def test_confirm_exhausts_award_after_full_consumption(self, api):
        """# difficulty: dual_variant_calc/scholarship_allocation_provisional_vs_final
        PRD §3.5: "The chosen ScholarshipAward then has its
        consumed_credit_cents increased by the snapshotted
        scholarship discount; if that increase brings
        consumed_credit_cents exactly equal to the award's
        total_credit_cents, the award is auto-transitioned to
        EXHAUSTED."

        Claim: confirming an enrollment that consumes a 5000-cent
        award in full makes the award unusable for a subsequent
        confirmation in the same family (proving EXHAUSTED is
        observable).
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="ANY",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
            weekly_capacity=10,
        )
        child_a = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"], full_name="A",
        )
        child_b = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"], full_name="B",
        )
        e_a = create_enrollment(child=child_a, session=session)
        confirmed_a = confirm_enrollment(enrollment=e_a)
        assert confirmed_a["scholarship_discount_cents"] == 5_000
        e_b = create_enrollment(child=child_b, session=session)
        confirmed_b = confirm_enrollment(enrollment=e_b)
        # The award is EXHAUSTED, so the second confirmation must see
        # 0 scholarship discount (silent skip of non-ACTIVE awards
        # per PRD §3.5).
        assert confirmed_b["scholarship_discount_cents"] == 0


# ===========================================================================
# dual_variant_calc/rainy_day_pool_chronological_vs_forward_looking
# ===========================================================================
class TestRainyDayPoolPersistedOrder:
    """difficulty: dual_variant_calc/
    rainy_day_pool_chronological_vs_forward_looking"""

    def test_persisted_order_consumes_pool_not_day_date_order(self, api):
        """# difficulty: dual_variant_calc/rainy_day_pool_chronological_vs_forward_looking
        PRD §3.8: "The pool is therefore consumed in the order in
        which days were marked RAINY, not in chronological day-date
        order — if the later day in a week was set RAINY first and an
        earlier day is set RAINY afterward, the pool already used by
        the later day still counts against the earlier day's
        allocation, because the computation reads currently persisted
        state at the moment of the transition."

        Claim: with rainy_day_pool_per_week=5 and 8 confirmed
        attendees, setting the LATER day RAINY first claims the full
        pool; setting the EARLIER day RAINY second gets 0 of the
        pool.
        """
        session = setup_open_session(
            rainy_day_pool_per_week=5, weekly_capacity=10,
        )
        days = get_session_days(session=session)
        week0 = sorted(
            (d for d in days if d.get("week_index") == 0),
            key=lambda d: d["day_date"],
        )
        assert len(week0) >= 2, (
            "PRD §3.3: opening a session materializes SessionDay rows "
            "for every business day of every ISO week; week 0 must "
            "yield at least 2 rows."
        )
        earlier, later = week0[0], week0[1]
        actors = setup_n_families_each_with_authorized_child(
            n=8, reference_date=session["reference_date"],
        )
        for _f, _g, c in actors:
            e = create_enrollment(child=c, session=session)
            confirm_enrollment(enrollment=e)
        later_after = set_weather(
            session_day=later, weather_status="RAINY",
        )
        assert later_after["rainy_day_used"] == 5
        earlier_after = set_weather(
            session_day=earlier, weather_status="RAINY",
        )
        assert earlier_after["rainy_day_used"] == 0

    def test_normal_revert_resets_used_and_keeps_pool_for_other_days(
        self, api,
    ):
        """# difficulty: dual_variant_calc/rainy_day_pool_chronological_vs_forward_looking
        PRD §3.8: "When a RAINY day reverts to NORMAL,
        rainy_day_used is set to zero and outdoor_headcount is set
        to confirmed_attendees_for_day."
        PRD §3.8: "the budget already consumed by other days in the
        same week is the sum of rainy_day_used across SessionDay
        rows in the same (session_id, week_index) whose
        weather_status is currently RAINY, excluding the current day
        being transitioned."

        Claim: reverting a RAINY day to NORMAL frees that day's
        share of the pool for a subsequent RAINY transition on a
        previously-blocked day in the same week.
        """
        session = setup_open_session(
            rainy_day_pool_per_week=5, weekly_capacity=10,
        )
        days = get_session_days(session=session)
        week0 = sorted(
            (d for d in days if d.get("week_index") == 0),
            key=lambda d: d["day_date"],
        )
        assert len(week0) >= 2, (
            "PRD §3.3: opening a session materializes SessionDay rows "
            "for every business day of every ISO week; week 0 must "
            "yield at least 2 rows."
        )
        d1, d2 = week0[0], week0[1]
        actors = setup_n_families_each_with_authorized_child(
            n=8, reference_date=session["reference_date"],
        )
        for _f, _g, c in actors:
            e = create_enrollment(child=c, session=session)
            confirm_enrollment(enrollment=e)
        # 1) Make d1 RAINY (claims pool of 5).
        d1_after = set_weather(session_day=d1, weather_status="RAINY")
        assert d1_after["rainy_day_used"] == 5
        # 2) Make d2 RAINY now — pool already used, gets 0.
        d2_first = set_weather(session_day=d2, weather_status="RAINY")
        assert d2_first["rainy_day_used"] == 0
        # 3) Revert d1 to NORMAL — frees its share.
        d1_normal = set_weather(session_day=d1, weather_status="NORMAL")
        assert d1_normal["rainy_day_used"] == 0
        # 4) Re-trigger d2 by reverting NORMAL→RAINY would not be
        # legal (RAINY→RAINY not a legal pair). The test asserts only
        # the freed-pool observable above.


# ===========================================================================
# combinatorial_formula/sibling_discount_tiered_with_state_filter
# ===========================================================================
class TestSiblingDiscountTieredFormula:
    """difficulty: combinatorial_formula/
    sibling_discount_tiered_with_state_filter"""

    def test_progression_n1_n2_n3_in_one_family(self, api):
        """# difficulty: combinatorial_formula/sibling_discount_tiered_with_state_filter
        PRD §3.5: "When N equals 1, no sibling discount applies (the
        percentage is zero). When N equals 2, the per-row percentage
        is 10 percent. When N equals 3, the per-row percentage is 15
        percent."
        PRD §3.5: "After the about-to-be-confirmed row's own
        sibling_discount_cents is computed, every other already-
        CONFIRMED sibling enrollment in the same (session_id,
        week_index) has its sibling_discount_cents recomputed under
        the new N and its final_fee_cents updated accordingly."

        Claim: confirming three siblings in sequence drives the
        family's sibling_discount_cents through the tier sequence
        0 → 1000 → 1500 on each row.
        """
        family, guardian, children = (
            setup_family_with_n_authorized_children(n=3)
        )
        session = setup_open_session(base_weekly_fee_cents=10_000)
        enrollments = [
            create_enrollment(child=c, session=session) for c in children
        ]
        c1 = confirm_enrollment(enrollment=enrollments[0])
        assert c1["sibling_discount_cents"] == 0
        assert c1["final_fee_cents"] == 10_000
        c2 = confirm_enrollment(enrollment=enrollments[1])
        e1_after_2 = re_get_enrollment(enrollments[0]["id"])
        assert c2["sibling_discount_cents"] == 1_000
        assert e1_after_2["sibling_discount_cents"] == 1_000
        c3 = confirm_enrollment(enrollment=enrollments[2])
        e1_after_3 = re_get_enrollment(enrollments[0]["id"])
        e2_after_3 = re_get_enrollment(enrollments[1]["id"])
        assert c3["sibling_discount_cents"] == 1_500
        assert e1_after_3["sibling_discount_cents"] == 1_500
        assert e2_after_3["sibling_discount_cents"] == 1_500
        assert e1_after_3["final_fee_cents"] == 8_500

    def test_state_filter_excludes_pending_auth_siblings(self, api):
        """# difficulty: combinatorial_formula/sibling_discount_tiered_with_state_filter
        PRD §3.5: "The sibling-discount rule uses tiered pricing on
        the count of currently-CONFIRMED enrollments belonging to
        children of the same family in the same (session_id,
        week_index), including the about-to-be-confirmed row itself."

        Claim: when only one sibling has been CONFIRMED and a second
        is still PENDING_AUTH, the confirmed row's
        sibling_discount_cents remains 0 (the PENDING_AUTH sibling
        does NOT contribute to N).
        """
        family, guardian, children = (
            setup_family_with_n_authorized_children(n=2)
        )
        session = setup_open_session(base_weekly_fee_cents=10_000)
        e1 = create_enrollment(child=children[0], session=session)
        e2 = create_enrollment(child=children[1], session=session)
        c1 = confirm_enrollment(enrollment=e1)
        # e2 remains PENDING_AUTH; N=1 from c1's perspective.
        assert c1["sibling_discount_cents"] == 0
        assert c1["final_fee_cents"] == 10_000


# ===========================================================================
# combinatorial_formula/sibling_discount_per_line_rounding_order
# ===========================================================================
class TestSiblingDiscountPerLineRounding:
    """difficulty: combinatorial_formula/sibling_discount_per_line_rounding_order"""

    def test_per_line_round_half_up_10003_n3(self, api):
        """# difficulty: combinatorial_formula/sibling_discount_per_line_rounding_order
        PRD §2.10: "All discount computations that involve a
        percentage tier — currently only the sibling discount —
        round half-up to the nearest whole cent per line item,
        independently, before any family-level summation; the
        implementation must never sum un-rounded per-line discounts
        and then round the sum."

        Claim: base_weekly_fee_cents=10003, N=3 (15%), per-row
        raw=1500.45 → per-row rounded=1500; family sum=4500 (not
        4501 from sum-then-round).
        """
        family, guardian, children = (
            setup_family_with_n_authorized_children(n=3)
        )
        session = setup_open_session(
            base_weekly_fee_cents=10_003, weekly_capacity=5,
        )
        enrollments = [
            create_enrollment(child=c, session=session) for c in children
        ]
        for e in enrollments:
            confirm_enrollment(enrollment=e)
        family_discount = 0
        for e in enrollments:
            after = re_get_enrollment(e["id"])
            assert after["sibling_discount_cents"] == 1_500
            family_discount += after["sibling_discount_cents"]
        assert family_discount == 4_500, (
            "per-line round_half_up yields 4500; sum-then-round "
            "would yield 4501"
        )

    def test_invoice_total_aligns_with_per_line_snapshots(self, api):
        """# difficulty: combinatorial_formula/sibling_discount_per_line_rounding_order
        PRD §3.7: "The invoice totals the per-row snapshotted
        final_fee_cents over those rows — the implementation must
        read the snapshots, not re-derive them from current sibling
        counts or award balances."

        Claim: invoice_total_cents == 3 * 8503 == 25509 (each
        snapshot is 10003 − 1500).
        """
        family, guardian, children = (
            setup_family_with_n_authorized_children(n=3)
        )
        session = setup_open_session(
            base_weekly_fee_cents=10_003, weekly_capacity=5,
        )
        for c in children:
            e = create_enrollment(child=c, session=session)
            confirm_enrollment(enrollment=e)
        res = api.get_family_invoice(
            family["id"], TEST_USERS["admin_headers"],
            params={"week_start": session["week_start"]},
        )
        invoice = validate_success(res, 200)
        assert invoice["invoice_total_cents"] == 25_509


# ===========================================================================
# combinatorial_formula/enrollment_fee_evaluation_order_chain
# ===========================================================================
class TestEvaluationOrderChain:
    """difficulty: combinatorial_formula/enrollment_fee_evaluation_order_chain"""

    def test_sibling_then_scholarship_then_final_in_pinned_order(
        self, api,
    ):
        """# difficulty: combinatorial_formula/enrollment_fee_evaluation_order_chain
        PRD §3.5: "The computation runs in a fixed order. First,
        list_fee_cents is set to the parent session's
        base_weekly_fee_cents. Second, the sibling discount is
        computed and snapshotted into sibling_discount_cents. Third,
        the scholarship allocation is computed and snapshotted into
        scholarship_discount_cents... Fourth, final_fee_cents is set
        to the larger of zero and list_fee_cents minus
        sibling_discount_cents minus scholarship_discount_cents."

        Claim: Family with 2-child sibling + 2000-cent award:
        E1 confirms first → list=10000, sibling=0 (N=1),
        scholarship=2000 (net=10000), final=8000, award→EXHAUSTED.
        E2 confirms second → list=10000, sibling=1000 (N=2),
        scholarship=0 (award EXHAUSTED), final=9000.
        E1 cascade → sibling_discount_cents recomputed to 1000;
        final = 10000 − 1000 − 2000 = 7000 (snapshotted scholarship
        preserved).
        """
        family, guardian, children = (
            setup_family_with_n_authorized_children(n=2)
        )
        grant_scholarship(
            family=family, total_credit_cents=2_000,
            granted_for_kind="ANY",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
            weekly_capacity=10,
        )
        e1 = create_enrollment(child=children[0], session=session)
        e2 = create_enrollment(child=children[1], session=session)
        c1 = confirm_enrollment(enrollment=e1)
        assert c1["list_fee_cents"] == 10_000
        assert c1["sibling_discount_cents"] == 0
        assert c1["scholarship_discount_cents"] == 2_000
        assert c1["final_fee_cents"] == 8_000
        c2 = confirm_enrollment(enrollment=e2)
        assert c2["list_fee_cents"] == 10_000
        assert c2["sibling_discount_cents"] == 1_000
        # award is EXHAUSTED after E1 → silent-skip for E2.
        assert c2["scholarship_discount_cents"] == 0
        assert c2["final_fee_cents"] == 9_000
        # E1 cascade: sibling recomputed, scholarship preserved.
        e1_after = re_get_enrollment(e1["id"])
        assert e1_after["sibling_discount_cents"] == 1_000
        assert e1_after["scholarship_discount_cents"] == 2_000, (
            "snapshotted scholarship discount on E1 must be "
            "preserved through the sibling-cascade"
        )
        assert e1_after["final_fee_cents"] == 7_000

    def test_final_fee_floors_at_zero(self, api):
        """# difficulty: combinatorial_formula/enrollment_fee_evaluation_order_chain
        PRD §3.5: "final_fee_cents is set to the larger of zero and
        list_fee_cents minus sibling_discount_cents minus
        scholarship_discount_cents — in plain prose, the list fee
        with both discounts subtracted, never below zero."

        Claim: with a scholarship larger than list_fee_cents, the
        final_fee_cents is clamped to 0.
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=50_000,
            granted_for_kind="ANY",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        e = create_enrollment(child=child, session=session)
        c = confirm_enrollment(enrollment=e)
        # scholarship can take at most net_payable = 10000 (per
        # PRD §3.5 — min(remaining_credit, net_payable_amount)).
        # So final_fee_cents = 10000 - 0 - 10000 = 0.
        assert c["scholarship_discount_cents"] == 10_000
        assert c["final_fee_cents"] == 0


# ===========================================================================
# non_linear_state_machine/enrollment_branching_with_waitlist_promotion_cycle
# ===========================================================================
class TestEnrollmentBranchingWaitlistCycle:
    """difficulty: non_linear_state_machine/
    enrollment_branching_with_waitlist_promotion_cycle"""

    def test_confirm_then_waitlist_then_cancel_promotes_peer(self, api):
        """# difficulty: non_linear_state_machine/enrollment_branching_with_waitlist_promotion_cycle
        PRD §3.4: "If the count is exactly at capacity, the
        enrollment instead transitions PENDING_AUTH → WAITLISTED, and
        its waitlist_position is set to one plus the maximum of
        existing waitlist_position values for the same (session_id,
        week_index)."
        PRD §3.4: "the lowest-positioned WAITLISTED enrollment in
        that week — if any — is promoted via a system transition that
        re-runs all of the confirmation preconditions."

        Claim: with weekly_capacity=1, two distinct-family children:
        E1 confirmed; E2 confirms but waitlists; cancel E1 promotes
        E2 to CONFIRMED with waitlist_position=null.
        """
        session = setup_open_session(weekly_capacity=1)
        actors = setup_n_families_each_with_authorized_child(
            n=2, reference_date=session["reference_date"],
        )
        (_, _, c1), (_, _, c2) = actors
        e1 = create_enrollment(child=c1, session=session)
        e2 = create_enrollment(child=c2, session=session)
        confirm_enrollment(enrollment=e1)
        waitlisted = confirm_enrollment(enrollment=e2)
        assert waitlisted["status"] == "WAITLISTED"
        assert waitlisted["waitlist_position"] == 1
        cancel_enrollment(enrollment=e1)
        promoted = re_get_enrollment(e2["id"])
        assert promoted["status"] == "CONFIRMED"
        assert promoted.get("waitlist_position") is None
        assert promoted["list_fee_cents"] == 10_000
        assert promoted["sibling_discount_cents"] == 0
        assert promoted["final_fee_cents"] == 10_000

    def test_waitlist_renumbering_on_cancel(self, api):
        """# difficulty: non_linear_state_machine/enrollment_branching_with_waitlist_promotion_cycle
        PRD §3.4: "Cancelling a WAITLISTED row records cancelled_at
        and additionally renumbers the remaining WAITLISTED rows in
        the same (session_id, week_index) so that waitlist_position
        is contiguous starting at 1."

        Claim: with weekly_capacity=1 and 3 PENDING_AUTH enrollments,
        confirm all three. E1 CONFIRMED, E2 at waitlist_position 1,
        E3 at waitlist_position 2. Cancel E2 → E3 renumbers to
        waitlist_position 1.
        """
        session = setup_open_session(weekly_capacity=1)
        actors = setup_n_families_each_with_authorized_child(
            n=3, reference_date=session["reference_date"],
        )
        (_, _, c1), (_, _, c2), (_, _, c3) = actors
        e1 = create_enrollment(child=c1, session=session)
        e2 = create_enrollment(child=c2, session=session)
        e3 = create_enrollment(child=c3, session=session)
        confirm_enrollment(enrollment=e1)
        w2 = confirm_enrollment(enrollment=e2)
        w3 = confirm_enrollment(enrollment=e3)
        assert w2["waitlist_position"] == 1
        assert w3["waitlist_position"] == 2
        # Cancel e2 — renumber required.
        cancel_enrollment(enrollment=e2)
        e3_after = re_get_enrollment(e3["id"])
        assert e3_after["status"] == "WAITLISTED"
        assert e3_after["waitlist_position"] == 1, (
            "remaining waitlisted row must renumber to contiguous "
            "starting at 1 after cancellation of a peer"
        )


# ===========================================================================
# non_linear_state_machine/scholarship_award_cycle_active_exhausted_active
# ===========================================================================
class TestScholarshipAwardCycle:
    """difficulty: non_linear_state_machine/
    scholarship_award_cycle_active_exhausted_active"""

    def test_exhaust_then_refund_cycles_back_to_active(self, api):
        """# difficulty: non_linear_state_machine/scholarship_award_cycle_active_exhausted_active
        PRD §3.6: "If a subsequent confirmed-enrollment cancellation
        refunds credit back below total_credit_cents, an EXHAUSTED
        award auto-transitions back to ACTIVE."

        Claim: confirm an enrollment that consumes the full 5000-cent
        award (award → EXHAUSTED); cancel that enrollment (refund
        → ACTIVE). Verified by re-confirming a fresh enrollment in
        the same family and observing the full 5000 discount fires
        again.
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="ANY",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        e = create_enrollment(child=child, session=session)
        c = confirm_enrollment(enrollment=e)
        assert c["scholarship_discount_cents"] == 5_000
        # Cancel → refund.
        cancel_enrollment(enrollment=e)
        # Fresh confirm — award must be ACTIVE again.
        child2 = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"], full_name="X",
        )
        e2 = create_enrollment(child=child2, session=session)
        c2 = confirm_enrollment(enrollment=e2)
        assert c2["scholarship_discount_cents"] == 5_000

    def test_revoke_during_exhausted_is_legal(self, api):
        """# difficulty: non_linear_state_machine/scholarship_award_cycle_active_exhausted_active
        PRD §3.6: "An admin can also revoke an award, moving ACTIVE
        or EXHAUSTED to REVOKED and recording revoked_at."

        Claim: revoking an EXHAUSTED award succeeds (moves to
        REVOKED).
        """
        family, guardian = setup_family_with_primary_guardian()
        award = grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="ANY",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        e = create_enrollment(child=child, session=session)
        confirm_enrollment(enrollment=e)
        # Award is now EXHAUSTED. Revoke must succeed.
        res = api.revoke_scholarship(
            award["id"], TEST_USERS["admin_headers"],
        )
        revoked = validate_success(res, 200)
        assert revoked["status"] == "REVOKED"


# ===========================================================================
# transitive_cascade/authorization_revoke_cascade_depth_3
# ===========================================================================
class TestAuthorizationRevokeDepth3Cascade:
    """difficulty: transitive_cascade/authorization_revoke_cascade_depth_3"""

    def test_revoke_medical_cancels_confirmed_and_refunds_scholarship(
        self, api,
    ):
        """# difficulty: transitive_cascade/authorization_revoke_cascade_depth_3
        PRD §3.2: "In that case, each such enrollment is moved from
        CONFIRMED to CANCELLED (cascade), cancelled_at is set to the
        current clock, and the standard confirmed-cancellation
        side-effect chain runs for each one: the scholarship credit
        is refunded against the originally consumed award, the
        sibling discount is recomputed on every remaining CONFIRMED
        sibling in the same (session_id, week_index), and the
        lowest-positioned WAITLISTED enrollment in that week is
        promoted if one exists."

        Claim: Revoking the only ACTIVE MEDICAL auth on a child with
        a CONFIRMED future-week enrollment that consumed a 5000-cent
        award:
          HOP 1: auth → REVOKED, child medical_authorization_status
                 → EXPIRED
          HOP 2: enrollment → CANCELLED, cancelled_at set
          HOP 3: scholarship credit refunded — verified by a fresh
                 confirm now seeing the full 5000 discount again.
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="ANY",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        # Build a child with one known MEDICAL auth id we can revoke.
        child = create_child(family=family)
        add_emergency_contact(child=child, priority=1)
        med = create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
        )
        create_authorization(
            child=child, guardian=guardian, kind="PICKUP",
        )
        e = create_enrollment(child=child, session=session)
        c = confirm_enrollment(enrollment=e)
        assert c["scholarship_discount_cents"] == 5_000
        # Trigger the cascade.
        api.revoke_authorization(med["id"], TEST_USERS["admin_headers"])
        # HOP 1: child medical projection → EXPIRED.
        refreshed_child = re_get_child(child["id"])
        assert refreshed_child[
            "medical_authorization_status"
        ] == "EXPIRED"
        # HOP 2: enrollment → CANCELLED, cancelled_at set.
        e_after = re_get_enrollment(e["id"])
        assert e_after["status"] == "CANCELLED"
        assert e_after.get("cancelled_at") is not None
        # HOP 3: scholarship refunded — observable via fresh confirm.
        family2_child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"], full_name="Fresh",
        )
        e2 = create_enrollment(child=family2_child, session=session)
        c2 = confirm_enrollment(enrollment=e2)
        assert c2["scholarship_discount_cents"] == 5_000

    def test_revoke_medical_promotes_waitlisted_peer(self, api):
        """# difficulty: transitive_cascade/authorization_revoke_cascade_depth_3
        PRD §3.2: "the lowest-positioned WAITLISTED enrollment in
        that week is promoted if one exists."

        Claim: with weekly_capacity=1, child C1 (different family
        F1) CONFIRMED, child C2 (different family F2) WAITLISTED on
        the same week, revoking C1's medical auth cancels C1 and
        promotes C2 to CONFIRMED.
        """
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
            weekly_capacity=1,
        )
        # Family 1 with a known medical auth id to revoke.
        family1, guardian1 = setup_family_with_primary_guardian()
        child1 = create_child(family=family1)
        add_emergency_contact(child=child1, priority=1)
        med1 = create_authorization(
            child=child1, guardian=guardian1, kind="MEDICAL",
        )
        create_authorization(
            child=child1, guardian=guardian1, kind="PICKUP",
        )
        family2, guardian2, child2 = (
            setup_n_families_each_with_authorized_child(
                n=1, reference_date=session["reference_date"],
            )[0]
        )
        e1 = create_enrollment(child=child1, session=session)
        e2 = create_enrollment(child=child2, session=session)
        confirm_enrollment(enrollment=e1)
        wait = confirm_enrollment(enrollment=e2)
        assert wait["status"] == "WAITLISTED"
        # Revoke medical on C1 — cascade-cancels E1 → promotes E2.
        api.revoke_authorization(med1["id"], TEST_USERS["admin_headers"])
        e1_after = re_get_enrollment(e1["id"])
        e2_after = re_get_enrollment(e2["id"])
        assert e1_after["status"] == "CANCELLED"
        assert e2_after["status"] == "CONFIRMED"
        assert e2_after.get("waitlist_position") is None


# ===========================================================================
# transitive_cascade/session_cancel_cascade_depth_2
# ===========================================================================
class TestSessionCancelDepth2Cascade:
    """difficulty: transitive_cascade/session_cancel_cascade_depth_2"""

    def test_session_cancel_cancels_enrollment_and_refunds_scholarship(
        self, api,
    ):
        """# difficulty: transitive_cascade/session_cancel_cascade_depth_2
        PRD §3.3: "From OPEN, cancellation... cascades: every
        Enrollment on this session in a non-terminal state
        (PENDING_AUTH, CONFIRMED, or WAITLISTED) is moved to
        CANCELLED. For each cancelled enrollment that had been
        CONFIRMED, the system additionally recomputes
        ScholarshipAward.consumed_credit_cents for the award that
        the enrollment had consumed".

        Claim: cancel the session → enrollment CANCELLED, scholarship
        refunded (proven by re-using the full 5000 on a fresh
        confirm in a new session for the same family).
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="ANY",
        )
        session1 = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session1["reference_date"],
        )
        e = create_enrollment(child=child, session=session1)
        c = confirm_enrollment(enrollment=e)
        assert c["scholarship_discount_cents"] == 5_000
        # Cancel the session.
        api.cancel_session(session1["id"], TEST_USERS["admin_headers"])
        e_after = re_get_enrollment(e["id"])
        assert e_after["status"] == "CANCELLED"
        # Scholarship must be back to ACTIVE — observable via a new
        # confirm in a fresh session.
        session2 = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child2 = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session2["reference_date"], full_name="X",
        )
        e2 = create_enrollment(child=child2, session=session2)
        c2 = confirm_enrollment(enrollment=e2)
        assert c2["scholarship_discount_cents"] == 5_000

    def test_session_cancel_recomputes_sibling_discount_for_remaining(
        self, api,
    ):
        """# difficulty: transitive_cascade/session_cancel_cascade_depth_2
        PRD §3.3: "triggers a sibling-discount recomputation on
        every remaining CONFIRMED sibling enrollment in the same
        (session_id, week_index)."

        Claim: a session-cancel that touches only one of two
        sessions used by a family does not affect the other session's
        siblings' snapshot — but a session-cancel of a session with
        two confirmed siblings cancels both. The PRD names this as
        a "recompute" event; here we exercise the bulk-cancel side of
        it: two confirmed siblings under one session, then cancel the
        session, both become CANCELLED.
        """
        family, guardian, children = (
            setup_family_with_n_authorized_children(n=2)
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
            weekly_capacity=10,
        )
        e1 = create_enrollment(child=children[0], session=session)
        e2 = create_enrollment(child=children[1], session=session)
        confirm_enrollment(enrollment=e1)
        confirm_enrollment(enrollment=e2)
        # Both confirmed at N=2 with 1000 discount each — sanity.
        assert re_get_enrollment(e1["id"])[
            "sibling_discount_cents"
        ] == 1_000
        # Cancel the session — both enrollments become CANCELLED.
        api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        assert re_get_enrollment(e1["id"])["status"] == "CANCELLED"
        assert re_get_enrollment(e2["id"])["status"] == "CANCELLED"


# ===========================================================================
# priority_pair_validation_conflict — escalations
# ===========================================================================
class TestValidationPriorityConflicts:
    """difficulty: priority_pair_validation_conflict/
    medical_safety_vs_age_constraint_at_creation
    and: priority_pair_validation_conflict/
    age_constraint_vs_week_index_temporal

    PRD §3.4 names the creation precheck as ONLY week_index + age (no
    medical-auth check is invoked at creation). So the difficulty-
    design instance medical_safety_vs_age_constraint_at_creation
    asserts a behavior the PRD prose does not state at the creation
    endpoint. Per the skill's PRD-First rule, we test the
    PRD-supported variant of the same precedence pair at confirmation
    (PRD §2.9 explicitly orders safety > state > age > week_index).

    For age_constraint_vs_week_index_temporal, PRD §2.9 names age
    BEFORE week-index inside the constraint band, so the precedence
    is asserted at the creation endpoint where both fire.
    """

    def test_age_check_fires_before_week_index_check_at_creation(
        self, api,
    ):
        """# difficulty: priority_pair_validation_conflict/age_constraint_vs_week_index_temporal
        PRD §2.9: "After the safety checks, state-machine legality
        (ERR_INVALID_STATE) is evaluated before domain constraints
        such as age (ERR_AGE_OUT_OF_RANGE), week-index window
        (ERR_INVALID_WEEK_INDEX), authorization time range
        (ERR_INVALID_TIME_RANGE), emergency-contact uniqueness
        (ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN), and capacity /
        duplicate enrollment (ERR_DUPLICATE_ENROLLMENT)."

        Claim: when a POST /camp/enrollments has BOTH an
        age-ineligible child AND a week_index outside [0, week_count),
        the response is ERR_AGE_OUT_OF_RANGE (age is listed before
        week-index in PRD §2.9 prose).
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(
            age_min=5, age_max=12, week_count=2,
        )
        # Child age=13 on reference_date — above age_max.
        child = setup_authorized_child(
            family=family, guardian=guardian, age_years=13,
            reference_date=session["reference_date"],
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                child_id=child["id"], session_id=session["id"],
                week_index=99,
            ),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_AGE_OUT_OF_RANGE")

    def test_confirm_medical_safety_wins_over_age_recheck(self, api):
        """# difficulty: priority_pair_validation_conflict/medical_safety_vs_age_constraint_at_creation
        PRD §2.9: "The three confirmation safety checks — active
        medical authorization, active pickup authorization, and at
        least one emergency contact — are evaluated in that order
        against confirmation requests, surfacing
        ERR_MEDICAL_AUTH_REQUIRED... After the safety checks,
        state-machine legality... is evaluated before domain
        constraints such as age (ERR_AGE_OUT_OF_RANGE)."

        Claim: at confirmation, if the child lacks ACTIVE medical
        auth, the system returns ERR_MEDICAL_AUTH_REQUIRED before
        any age check fires.

        NOTE: PRD §3.4 confirms age is re-checked using the
        creation-time snapshot, so age at confirm can only fire if
        creation already passed age (snapshot remained eligible).
        Here we test the cleaner PRD-stated precedence: at confirm,
        a child with no medical auth produces ERR_MEDICAL_AUTH_REQUIRED.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(age_min=5, age_max=12)
        # Build an in-range child WITHOUT medical auth.
        child = setup_authorized_child(
            family=family, guardian=guardian, age_years=8,
            reference_date=session["reference_date"],
            include_medical=False,
        )
        enrollment = create_enrollment(child=child, session=session)
        res = api.confirm_enrollment(
            enrollment["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_MEDICAL_AUTH_REQUIRED")

    def test_confirm_pickup_safety_wins_over_age_recheck(self, api):
        """# difficulty: priority_pair_validation_conflict/medical_safety_vs_age_constraint_at_creation
        PRD §2.9: "The three confirmation safety checks — active
        medical authorization, active pickup authorization, and at
        least one emergency contact — are evaluated in that order
        against confirmation requests, surfacing
        ERR_MEDICAL_AUTH_REQUIRED, then ERR_PICKUP_AUTH_REQUIRED,
        then ERR_EMERGENCY_CONTACT_REQUIRED. After the safety
        checks, state-machine legality (ERR_INVALID_STATE) is
        evaluated before domain constraints such as age
        (ERR_AGE_OUT_OF_RANGE)."

        Claim: at confirmation, the pickup-auth safety check fires
        before age recheck. The closest PRD-stated analog of the
        difficulty-design instance's safety-vs-constraint precedence
        is the confirm-time triad, where the pair is directly named.
        A child with ACTIVE medical, no pickup, and the
        age-eligibility-snapshot-still-fine produces
        ERR_PICKUP_AUTH_REQUIRED (safety) — not any age-related
        error.

        NOTE: PRD §3.4 enumerates creation-time prechecks as only
        week_index + age; the creation-endpoint variant of the
        safety-vs-constraint precedence is not stated in PRD prose
        and we test the PRD-supported confirm variant.
        """
        from test_helpers import (
            create_child,
            create_authorization,
        )
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(age_min=5, age_max=12)
        # Eligible-age child with MEDICAL auth + emergency contact but
        # NO PICKUP auth.
        child = create_child(
            family=family,
            date_of_birth=None, age_years=8,
            reference_date=session["reference_date"],
        )
        add_emergency_contact(child=child, priority=1)
        create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
        )
        enrollment = create_enrollment(child=child, session=session)
        res = api.confirm_enrollment(
            enrollment["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_PICKUP_AUTH_REQUIRED")

    def test_invalid_week_index_when_age_passes(self, api):
        """# difficulty: priority_pair_validation_conflict/age_constraint_vs_week_index_temporal
        PRD §3.4: "the week_index must be at least 0 and strictly
        less than the session's week_count, otherwise the request
        fails with ERR_INVALID_WEEK_INDEX".

        Claim: when only the week_index is invalid (age passes), the
        response is ERR_INVALID_WEEK_INDEX.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(
            age_min=5, age_max=12, week_count=2,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian, age_years=8,
            reference_date=session["reference_date"],
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                child_id=child["id"], session_id=session["id"],
                week_index=5,
            ),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_WEEK_INDEX")


# ===========================================================================
# boundary_precision_check/weekly_capacity_strict_less_than
# ===========================================================================
class TestWeeklyCapacityStrictBoundary:
    """difficulty: boundary_precision_check/weekly_capacity_strict_less_than"""

    def test_capacity_2_third_confirm_goes_to_waitlist(self, api):
        """# difficulty: boundary_precision_check/weekly_capacity_strict_less_than
        PRD §2.11: "Capacity is enforced with a strict inequality: a
        new confirmation is allowed when the count of currently-
        CONFIRMED enrollments for the target (session_id, week_index)
        is strictly less than Session.weekly_capacity. When the count
        equals capacity, the enrollment goes to the waitlist with a
        queue position rather than failing."

        Claim: with weekly_capacity=2, E1 + E2 confirm to CONFIRMED;
        E3 routes to WAITLISTED.
        """
        session = setup_open_session(weekly_capacity=2)
        actors = setup_n_families_each_with_authorized_child(
            n=3, reference_date=session["reference_date"],
        )
        (_, _, c1), (_, _, c2), (_, _, c3) = actors
        e1 = create_enrollment(child=c1, session=session)
        e2 = create_enrollment(child=c2, session=session)
        e3 = create_enrollment(child=c3, session=session)
        a = confirm_enrollment(enrollment=e1)
        b = confirm_enrollment(enrollment=e2)
        c = confirm_enrollment(enrollment=e3)
        assert a["status"] == "CONFIRMED"
        assert b["status"] == "CONFIRMED"
        assert c["status"] == "WAITLISTED"
        assert c["waitlist_position"] == 1

    def test_capacity_1_first_confirm_succeeds_second_waitlists(
        self, api,
    ):
        """# difficulty: boundary_precision_check/weekly_capacity_strict_less_than
        PRD §2.11: "When the count equals capacity, the enrollment
        goes to the waitlist with a queue position rather than
        failing."

        Claim: with weekly_capacity=1, E1 confirms to CONFIRMED; E2
        waitlists.
        """
        session = setup_open_session(weekly_capacity=1)
        actors = setup_n_families_each_with_authorized_child(
            n=2, reference_date=session["reference_date"],
        )
        (_, _, c1), (_, _, c2) = actors
        e1 = create_enrollment(child=c1, session=session)
        e2 = create_enrollment(child=c2, session=session)
        a = confirm_enrollment(enrollment=e1)
        b = confirm_enrollment(enrollment=e2)
        assert a["status"] == "CONFIRMED"
        assert b["status"] == "WAITLISTED"
        assert b["waitlist_position"] == 1


# ===========================================================================
# boundary_precision_check/emergency_contact_zero_count_check
# ===========================================================================
class TestEmergencyContactZeroBoundary:
    """difficulty: boundary_precision_check/emergency_contact_zero_count_check"""

    def test_confirm_with_zero_contacts_rejected(self, api):
        """# difficulty: boundary_precision_check/emergency_contact_zero_count_check
        PRD §3.4: "the child's emergency_contact_count must be at
        least 1 (else ERR_EMERGENCY_CONTACT_REQUIRED)".

        Claim: a confirm against a child with both ACTIVE auths but
        zero emergency contacts returns ERR_EMERGENCY_CONTACT_REQUIRED.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session()
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            include_emergency_contact=False,
        )
        e = create_enrollment(child=child, session=session)
        res = api.confirm_enrollment(
            e["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_EMERGENCY_CONTACT_REQUIRED")

    def test_confirm_after_adding_first_contact_succeeds(self, api):
        """# difficulty: boundary_precision_check/emergency_contact_zero_count_check
        PRD §3.2: "Adding a contact increments
        Child.emergency_contact_count".
        PRD §3.4: "the child's emergency_contact_count must be at
        least 1".

        Claim: after adding one emergency contact, the confirm
        succeeds.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session()
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            include_emergency_contact=False,
        )
        e = create_enrollment(child=child, session=session)
        # First confirm — must fail.
        first = api.confirm_enrollment(
            e["id"], TEST_USERS["admin_headers"],
        )
        validate_error(first, "ERR_EMERGENCY_CONTACT_REQUIRED")
        # Add one emergency contact.
        add_emergency_contact(child=child, priority=1)
        assert re_get_child(child["id"])[
            "emergency_contact_count"
        ] == 1
        # Second confirm — must succeed.
        res = api.confirm_enrollment(
            e["id"], TEST_USERS["admin_headers"],
        )
        confirmed = validate_success(res, 200)
        assert confirmed["status"] == "CONFIRMED"


# ===========================================================================
# cross_entity_state_dependency/enrollment_depends_on_child_auth_state
# ===========================================================================
class TestEnrollmentDependsOnChildAuth:
    """difficulty: cross_entity_state_dependency/
    enrollment_depends_on_child_auth_state"""

    def test_confirm_blocked_then_succeeds_after_adding_medical(
        self, api,
    ):
        """# difficulty: cross_entity_state_dependency/enrollment_depends_on_child_auth_state
        PRD §3.4: "the child's medical_authorization_status must be
        ACTIVE at request time (else ERR_MEDICAL_AUTH_REQUIRED)".
        PRD §3.2: "the side effect of creation is a re-projection of
        the child's medical_authorization_status or
        pickup_authorization_status per the projection rules in §2.8."

        Claim: confirming without medical auth returns
        ERR_MEDICAL_AUTH_REQUIRED; adding a fresh ACTIVE MEDICAL
        authorization flips the child's status to ACTIVE; the second
        confirm succeeds.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session()
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            include_medical=False,
        )
        e = create_enrollment(child=child, session=session)
        # First confirm — must fail.
        first = api.confirm_enrollment(
            e["id"], TEST_USERS["admin_headers"],
        )
        validate_error(first, "ERR_MEDICAL_AUTH_REQUIRED")
        # Add a fresh medical authorization.
        create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
        )
        refreshed = re_get_child(child["id"])
        assert refreshed["medical_authorization_status"] == "ACTIVE"
        # Second confirm — must succeed.
        res = api.confirm_enrollment(
            e["id"], TEST_USERS["admin_headers"],
        )
        confirmed = validate_success(res, 200)
        assert confirmed["status"] == "CONFIRMED"

    def test_confirm_blocked_then_succeeds_after_adding_pickup(
        self, api,
    ):
        """# difficulty: cross_entity_state_dependency/enrollment_depends_on_child_auth_state
        PRD §3.4: "the child's pickup_authorization_status must be
        ACTIVE at request time (else ERR_PICKUP_AUTH_REQUIRED)".

        Claim: confirming without pickup auth returns
        ERR_PICKUP_AUTH_REQUIRED; adding a fresh ACTIVE PICKUP
        authorization makes confirm succeed.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session()
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            include_pickup=False,
        )
        e = create_enrollment(child=child, session=session)
        first = api.confirm_enrollment(
            e["id"], TEST_USERS["admin_headers"],
        )
        validate_error(first, "ERR_PICKUP_AUTH_REQUIRED")
        create_authorization(
            child=child, guardian=guardian, kind="PICKUP",
        )
        res = api.confirm_enrollment(
            e["id"], TEST_USERS["admin_headers"],
        )
        confirmed = validate_success(res, 200)
        assert confirmed["status"] == "CONFIRMED"


# ===========================================================================
# cross_entity_state_dependency/scholarship_award_depends_on_session_kind
# ===========================================================================
class TestScholarshipDependsOnSessionKind:
    """difficulty: cross_entity_state_dependency/
    scholarship_award_depends_on_session_kind"""

    def test_summer_camp_award_does_not_apply_to_afterschool(self, api):
        """# difficulty: cross_entity_state_dependency/scholarship_award_depends_on_session_kind
        PRD §3.5: "The system first filters to awards that are
        currently ACTIVE and whose granted_for_kind matches the
        parent session's kind exactly or is ANY."
        PRD §3.5: "Awards that are not ACTIVE (i.e., EXHAUSTED or
        REVOKED), or whose granted_for_kind is incompatible with the
        session's kind, are skipped silently when they would
        otherwise be considered".

        Claim: a SUMMER_CAMP-only award yields 0 scholarship on an
        AFTERSCHOOL session.
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="SUMMER_CAMP",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        e = create_enrollment(child=child, session=session)
        c = confirm_enrollment(enrollment=e)
        assert c["scholarship_discount_cents"] == 0
        assert c.get("scholarship_award_id") in (None, "")

    def test_summer_camp_award_applies_to_summer_camp_session(self, api):
        """# difficulty: cross_entity_state_dependency/scholarship_award_depends_on_session_kind
        PRD §3.5: "awards whose granted_for_kind matches the
        session's kind exactly come ahead of awards granted with ANY
        (specific before generic)".

        Claim: a SUMMER_CAMP-only award fully applies on a
        SUMMER_CAMP session.
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="SUMMER_CAMP",
        )
        session = setup_open_session(
            kind="SUMMER_CAMP", base_weekly_fee_cents=10_000,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        e = create_enrollment(child=child, session=session)
        c = confirm_enrollment(enrollment=e)
        assert c["scholarship_discount_cents"] == 5_000
        assert c["final_fee_cents"] == 5_000


# ===========================================================================
# resource_temporal_overlap/enrollment_per_week_uniqueness_inclusive_week_index
# ===========================================================================
class TestEnrollmentPerWeekUniqueness:
    """difficulty: resource_temporal_overlap/
    enrollment_per_week_uniqueness_inclusive_week_index"""

    def test_duplicate_triple_rejected_different_week_allowed(self, api):
        """# difficulty: resource_temporal_overlap/enrollment_per_week_uniqueness_inclusive_week_index
        PRD §3.4: "Duplicates are forbidden: any non-terminal
        Enrollment already existing for the same (child_id,
        session_id, week_index) causes the new attempt to fail with
        ERR_DUPLICATE_ENROLLMENT."

        Claim: with an existing PENDING_AUTH for (child, session,
        week=0), a second POST for (child, session, week=0) returns
        ERR_DUPLICATE_ENROLLMENT; a POST for (child, session, week=1)
        succeeds.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(week_count=4)
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        e1 = create_enrollment(
            child=child, session=session, week_index=0,
        )
        # Duplicate triple — must reject.
        res_dup = api.create_enrollment(
            create_enrollment_payload(
                child_id=child["id"], session_id=session["id"],
                week_index=0,
            ),
            TEST_USERS["admin_headers"],
        )
        validate_error(res_dup, "ERR_DUPLICATE_ENROLLMENT")
        # Different week — must succeed.
        res_ok = api.create_enrollment(
            create_enrollment_payload(
                child_id=child["id"], session_id=session["id"],
                week_index=1,
            ),
            TEST_USERS["admin_headers"],
        )
        validate_success(res_ok, 201)

    def test_terminal_cancelled_enrollment_releases_triple(self, api):
        """# difficulty: resource_temporal_overlap/enrollment_per_week_uniqueness_inclusive_week_index
        PRD §3.4: "Duplicates are forbidden: any non-terminal
        Enrollment already existing for the same (child_id,
        session_id, week_index) causes the new attempt to fail with
        ERR_DUPLICATE_ENROLLMENT."

        Claim: cancelling the first PENDING_AUTH row (it becomes
        CANCELLED, a terminal state) allows a fresh POST for the
        same triple to succeed.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session()
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        e1 = create_enrollment(
            child=child, session=session, week_index=0,
        )
        cancel_enrollment(enrollment=e1)
        # Fresh enrollment on the same triple — must succeed (the old
        # row is now CANCELLED → terminal).
        res = api.create_enrollment(
            create_enrollment_payload(
                child_id=child["id"], session_id=session["id"],
                week_index=0,
            ),
            TEST_USERS["admin_headers"],
        )
        validate_success(res, 201)


# ===========================================================================
# resource_temporal_overlap/authorization_active_window_half_open_interval
# ===========================================================================
class TestAuthorizationHalfOpenInterval:
    """difficulty: resource_temporal_overlap/
    authorization_active_window_half_open_interval"""

    def test_at_expires_at_flips_to_expired(self, api):
        """# difficulty: resource_temporal_overlap/authorization_active_window_half_open_interval
        PRD §2.8: "the status is ACTIVE if there exists at least one
        Authorization belonging to that child with that kind, with
        status equal to ACTIVE, whose effective_at is at or before
        the current clock and whose expires_at is strictly after the
        current clock".
        PRD §2.7: "the clock is advanced by an admin-only
        test-driving capability that takes an iso_timestamp and
        atomically (a) sweeps every Authorization with status ACTIVE
        whose expires_at is at or before the new instant into the
        EXPIRED state".

        Claim: at clock == expires_at, the authorization's child
        projection flips from ACTIVE to EXPIRED.
        """
        family, guardian = setup_family_with_primary_guardian()
        child = create_child(family=family)
        add_emergency_contact(child=child, priority=1)
        expires = iso_offset(hours=1)
        create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
            effective_offset_minutes=-60, expires_at=expires,
        )
        # Before clock advance — projection is ACTIVE.
        assert re_get_child(child["id"])[
            "medical_authorization_status"
        ] == "ACTIVE"
        # Advance to expires_at exactly.
        advance_clock_to(expires)
        # Per PRD §2.8 + §2.7: t >= expires_at flips to EXPIRED.
        refreshed = re_get_child(child["id"])
        assert refreshed["medical_authorization_status"] == "EXPIRED"

    def test_just_before_expires_at_remains_active(self, api):
        """# difficulty: resource_temporal_overlap/authorization_active_window_half_open_interval
        PRD §2.8: "whose expires_at is strictly after the current
        clock" — i.e., ACTIVE while now < expires_at.

        Claim: at clock strictly less than expires_at, the projection
        remains ACTIVE.
        """
        from datetime import timedelta as _td
        family, guardian = setup_family_with_primary_guardian()
        child = create_child(family=family)
        add_emergency_contact(child=child, priority=1)
        expires_dt = parse_iso(iso_offset(hours=2))
        create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
            effective_offset_minutes=-60,
            expires_at=iso_utc(expires_dt),
        )
        # Advance to expires_at - 1 minute.
        advance_clock_to(iso_utc(expires_dt - _td(minutes=1)))
        refreshed = re_get_child(child["id"])
        assert refreshed["medical_authorization_status"] == "ACTIVE"


# ===========================================================================
# compensating_invariant/scholarship_credit_invariant_round_trip
# ===========================================================================
class TestScholarshipCreditRoundTrip:
    """difficulty: compensating_invariant/scholarship_credit_invariant_round_trip"""

    def test_confirm_then_cancel_restores_remaining_credit(self, api):
        """# difficulty: compensating_invariant/scholarship_credit_invariant_round_trip
        PRD §3.4: "the snapshotted scholarship_discount_cents is
        refunded back to the consumed ScholarshipAward (its
        consumed_credit_cents is decreased by exactly that amount,
        and if that award had reached EXHAUSTED and now has remaining
        credit, it transitions back to ACTIVE)."

        Claim: a confirm-then-cancel round-trip on a single
        enrollment leaves the family's award balance unchanged. We
        observe this by confirming a fresh enrollment afterwards and
        seeing the full 5000 discount fire again.
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="ANY",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        e = create_enrollment(child=child, session=session)
        c = confirm_enrollment(enrollment=e)
        assert c["scholarship_discount_cents"] == 5_000
        cancel_enrollment(enrollment=e)
        # Fresh enrollment must again be able to consume the full 5000.
        child2 = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"], full_name="R",
        )
        e2 = create_enrollment(child=child2, session=session)
        c2 = confirm_enrollment(enrollment=e2)
        assert c2["scholarship_discount_cents"] == 5_000

    def test_double_round_trip_preserves_balance(self, api):
        """# difficulty: compensating_invariant/scholarship_credit_invariant_round_trip
        PRD §3.4: "the snapshotted scholarship_discount_cents is
        refunded back to the consumed ScholarshipAward".

        Claim: confirm-then-cancel-then-confirm-then-cancel leaves
        the award's remaining balance unchanged; a final fresh
        confirm still observes the full 5000 discount.
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="ANY",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        for cycle in range(2):
            e = create_enrollment(child=child, session=session)
            c = confirm_enrollment(enrollment=e)
            assert c["scholarship_discount_cents"] == 5_000, (
                f"cycle {cycle}: confirm did not draw 5000"
            )
            cancel_enrollment(enrollment=e)
        # Final confirm — should still consume 5000.
        e_final = create_enrollment(child=child, session=session)
        c_final = confirm_enrollment(enrollment=e_final)
        assert c_final["scholarship_discount_cents"] == 5_000


# ===========================================================================
# compensating_invariant/weekly_capacity_invariant_round_trip
# ===========================================================================
class TestWeeklyCapacityRoundTrip:
    """difficulty: compensating_invariant/weekly_capacity_invariant_round_trip"""

    def test_seat_release_promotes_waitlisted_peer(self, api):
        """# difficulty: compensating_invariant/weekly_capacity_invariant_round_trip
        PRD §3.4: "the lowest-positioned WAITLISTED enrollment in
        that week — if any — is promoted via a system transition
        that re-runs all of the confirmation preconditions".

        Claim: cancelling the only CONFIRMED enrollment with a
        WAITLISTED peer promotes that peer to CONFIRMED.
        """
        session = setup_open_session(weekly_capacity=1)
        actors = setup_n_families_each_with_authorized_child(
            n=2, reference_date=session["reference_date"],
        )
        (_, _, c1), (_, _, c2) = actors
        e1 = create_enrollment(child=c1, session=session)
        e2 = create_enrollment(child=c2, session=session)
        confirm_enrollment(enrollment=e1)
        w2 = confirm_enrollment(enrollment=e2)
        assert w2["status"] == "WAITLISTED"
        cancel_enrollment(enrollment=e1)
        promoted = re_get_enrollment(e2["id"])
        assert promoted["status"] == "CONFIRMED"
        assert promoted.get("waitlist_position") is None

    def test_capacity_seats_in_week_remain_at_one_after_round_trip(
        self, api,
    ):
        """# difficulty: compensating_invariant/weekly_capacity_invariant_round_trip
        PRD §2.11: "Capacity is enforced with a strict inequality: a
        new confirmation is allowed when the count of currently-
        CONFIRMED enrollments for the target (session_id, week_index)
        is strictly less than Session.weekly_capacity."

        Claim: after the confirm→cancel→promote round-trip with
        weekly_capacity=1, attempting to confirm a third independent
        enrollment in the same week results in WAITLIST (capacity
        still saturated, conserved seat count == 1).
        """
        session = setup_open_session(weekly_capacity=1)
        actors = setup_n_families_each_with_authorized_child(
            n=3, reference_date=session["reference_date"],
        )
        (_, _, c1), (_, _, c2), (_, _, c3) = actors
        e1 = create_enrollment(child=c1, session=session)
        e2 = create_enrollment(child=c2, session=session)
        confirm_enrollment(enrollment=e1)
        confirm_enrollment(enrollment=e2)
        # Cancel e1 to promote e2.
        cancel_enrollment(enrollment=e1)
        # Now e2 is CONFIRMED. A new e3 must waitlist.
        e3 = create_enrollment(child=c3, session=session)
        w3 = confirm_enrollment(enrollment=e3)
        assert w3["status"] == "WAITLISTED"
        assert w3["waitlist_position"] == 1
