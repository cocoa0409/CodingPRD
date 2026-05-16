"""Fee snapshot calculations: sibling discount, scholarship allocation,
final fee derivation.

Tests cover PRD §3.5 (computation order, sibling tiers, scholarship
waterfall) and PRD §3.6 (award lifecycle effects of confirmation
snapshotting).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    confirm_enrollment,
    create_enrollment,
    grant_scholarship,
    re_get_enrollment,
    setup_authorized_child,
    setup_family_with_n_authorized_children,
    setup_family_with_primary_guardian,
    setup_open_session,
    validate_error,
    validate_success,
)


# ===========================================================================
# Sibling discount tiers — N=1, N=2, N=3, N=4
# ===========================================================================
class TestSiblingDiscountTiers:
    def test_n1_zero_percent(self, api):
        """PRD §3.5: "When N equals 1, no sibling discount applies
        (the percentage is zero)."

        Claim: a single confirmed child in a family has
        sibling_discount_cents == 0 and final_fee_cents ==
        list_fee_cents.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(base_weekly_fee_cents=10_000)
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
        )
        enrollment = create_enrollment(child=child, session=session)
        confirmed = confirm_enrollment(enrollment=enrollment)
        assert confirmed["sibling_discount_cents"] == 0
        assert confirmed["list_fee_cents"] == 10_000
        assert confirmed["final_fee_cents"] == 10_000

    def test_n2_ten_percent_with_cascade(self, api):
        """PRD §3.5: "When N equals 2, the per-row percentage is 10
        percent."
        PRD §3.5: "After the about-to-be-confirmed row's own
        sibling_discount_cents is computed, every other already-
        CONFIRMED sibling enrollment in the same (session_id,
        week_index) has its sibling_discount_cents recomputed under
        the new N and its final_fee_cents updated accordingly."

        Claim: confirming the second sibling sets each enrollment's
        sibling_discount_cents to 1000 (10% of 10000) and updates the
        first sibling's final_fee_cents.
        """
        family, guardian, children = (
            setup_family_with_n_authorized_children(n=2)
        )
        session = setup_open_session(base_weekly_fee_cents=10_000)
        # Re-fetch children using the session's reference_date so age
        # math is consistent. setup_family_with_n_authorized_children
        # uses default reference, which is also today.
        e1 = create_enrollment(child=children[0], session=session)
        e2 = create_enrollment(child=children[1], session=session)
        c1_after = confirm_enrollment(enrollment=e1)
        assert c1_after["sibling_discount_cents"] == 0
        c2_after = confirm_enrollment(enrollment=e2)
        # PRD §3.5: 10% of 10000 = 1000.
        assert c2_after["sibling_discount_cents"] == 1000
        assert c2_after["final_fee_cents"] == 9000
        # Cascade — first sibling now sees the new N.
        e1_after = re_get_enrollment(e1["id"])
        assert e1_after["sibling_discount_cents"] == 1000
        assert e1_after["final_fee_cents"] == 9000

    def test_n3_fifteen_percent_all_recomputed(self, api):
        """PRD §3.5: "When N equals 3, the per-row percentage is 15
        percent."

        Claim: with three confirmed siblings each at
        base_weekly_fee_cents=10000, each gets sibling_discount_cents
        = 1500 (15%) and final_fee_cents = 8500.
        """
        family, guardian, children = (
            setup_family_with_n_authorized_children(n=3)
        )
        session = setup_open_session(base_weekly_fee_cents=10_000)
        enrollments = [
            create_enrollment(child=c, session=session) for c in children
        ]
        for e in enrollments:
            confirm_enrollment(enrollment=e)
        # All three siblings now at 15% — check each.
        for e in enrollments:
            after = re_get_enrollment(e["id"])
            assert after["sibling_discount_cents"] == 1500
            assert after["final_fee_cents"] == 8500

    def test_n4_twenty_percent(self, api):
        """PRD §3.5: "When N is 4 or more, the per-row percentage is
        20 percent."

        Claim: with four confirmed siblings each at fee=10000, each
        has sibling_discount_cents=2000 and final_fee_cents=8000.
        """
        family, guardian, children = (
            setup_family_with_n_authorized_children(n=4)
        )
        session = setup_open_session(
            base_weekly_fee_cents=10_000, weekly_capacity=10,
        )
        enrollments = [
            create_enrollment(child=c, session=session) for c in children
        ]
        for e in enrollments:
            confirm_enrollment(enrollment=e)
        for e in enrollments:
            after = re_get_enrollment(e["id"])
            assert after["sibling_discount_cents"] == 2000
            assert after["final_fee_cents"] == 8000


# ===========================================================================
# Sibling discount rounding — PRD §3.5 + §2.10 per-line round_half_up
# ===========================================================================
class TestSiblingDiscountRounding:
    def test_per_line_round_half_up_three_siblings_10003(self, api):
        """PRD §3.5: "The dollar discount for each affected
        enrollment is list_fee_cents multiplied by the per-row
        percentage, then rounded half-up to whole cents independently
        for each line item before the family-level summation."
        PRD §2.10: "round half-up to the nearest whole cent per line
        item, independently, before any family-level summation; the
        implementation must never sum un-rounded per-line discounts
        and then round the sum."

        Claim: with base_weekly_fee_cents=10003 and N=3 siblings
        (15%), per-line raw = 1500.45 → per-line rounded = 1500,
        family-level sibling discount = 4500 (not 4501).
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
        family_total_discount = 0
        for e in enrollments:
            after = re_get_enrollment(e["id"])
            # PRD §3.5: 15% of 10003 = 1500.45 → half-up rounded = 1500.
            assert after["sibling_discount_cents"] == 1500, (
                f"per-line round_half_up of 1500.45 must yield 1500, "
                f"got {after['sibling_discount_cents']}"
            )
            assert after["final_fee_cents"] == 10_003 - 1500
            family_total_discount += after["sibling_discount_cents"]
        # PRD §2.10: per-line then sum → 4500, NOT 4501 (sum-then-round).
        assert family_total_discount == 4500, (
            f"family-level sibling discount must be 4500 (per-line), "
            f"got {family_total_discount}"
        )


# ===========================================================================
# Scholarship waterfall — kind match, ANY-fallback, exhaust, refund
# ===========================================================================
class TestScholarshipAllocation:
    def test_any_kind_award_applies_to_afterschool_session(self, api):
        """PRD §3.6: "granted_for_kind selecting which session kind it
        may be applied against: AFTERSCHOOL only, SUMMER_CAMP only, or
        ANY (both)."
        PRD §3.5: "The amount allocated is the smaller of that
        award's remaining credit and the net payable amount, where
        the net payable amount is list_fee_cents minus the
        already-computed sibling_discount_cents."

        Claim: an ANY-kind award fully covers a 5000-cent net
        payable on an AFTERSCHOOL session.
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
        enrollment = create_enrollment(child=child, session=session)
        confirmed = confirm_enrollment(enrollment=enrollment)
        # net_payable = 10000 - 0 = 10000; award has 5000.
        # min(5000, 10000) = 5000.
        assert confirmed["scholarship_discount_cents"] == 5_000
        assert confirmed["scholarship_award_id"] == award["id"]
        # final = 10000 - 0 - 5000 = 5000.
        assert confirmed["final_fee_cents"] == 5_000

    def test_summer_camp_only_award_does_not_apply_to_afterschool(self, api):
        """PRD §3.5: "The system first filters to awards that are
        currently ACTIVE and whose granted_for_kind matches the
        parent session's kind exactly or is ANY."
        PRD §3.5: "Awards that are not ACTIVE (i.e., EXHAUSTED or
        REVOKED), or whose granted_for_kind is incompatible with the
        session's kind, are skipped silently when they would otherwise
        be considered."

        Claim: a SUMMER_CAMP-only award is silently skipped on an
        AFTERSCHOOL enrollment confirmation, leaving
        scholarship_discount_cents==0.
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
        enrollment = create_enrollment(child=child, session=session)
        confirmed = confirm_enrollment(enrollment=enrollment)
        assert confirmed["scholarship_discount_cents"] == 0
        assert confirmed.get("scholarship_award_id") in (None, "")

    def test_exhaust_award_when_consumed_equals_total(self, api):
        """PRD §3.5: "The chosen ScholarshipAward then has its
        consumed_credit_cents increased by the snapshotted
        scholarship discount; if that increase brings
        consumed_credit_cents exactly equal to the award's
        total_credit_cents, the award is auto-transitioned to
        EXHAUSTED."

        Claim: confirming an enrollment that consumes the full
        award balance moves the award to EXHAUSTED. Verified by
        attempting a second confirmation against the same award and
        observing zero scholarship_discount applied (since the award
        is no longer ACTIVE).
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
        # First child confirms — consumes the full 5000.
        child1 = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            full_name="First Sibling",
        )
        e1 = create_enrollment(child=child1, session=session)
        c1 = confirm_enrollment(enrollment=e1)
        assert c1["scholarship_discount_cents"] == 5_000
        # Second sibling confirms — award is EXHAUSTED, so no discount.
        child2 = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            full_name="Second Sibling",
        )
        e2 = create_enrollment(child=child2, session=session)
        c2 = confirm_enrollment(enrollment=e2)
        assert c2["scholarship_discount_cents"] == 0, (
            "EXHAUSTED award must yield zero discount on next confirm"
        )

    def test_scholarship_refund_on_cancellation(self, api):
        """PRD §3.4: "Cancelling a CONFIRMED row... the snapshotted
        scholarship_discount_cents is refunded back to the consumed
        ScholarshipAward (its consumed_credit_cents is decreased by
        exactly that amount, and if that award had reached EXHAUSTED
        and now has remaining credit, it transitions back to
        ACTIVE)."

        Claim: cancelling a CONFIRMED enrollment that consumed the
        full award returns the award to ACTIVE with consumed=0. Verified
        by confirming a second enrollment for the same family afterwards
        and observing the discount fires again (only possible if the
        award has been restored to ACTIVE).
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="ANY",
        )
        session = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child1 = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            full_name="A",
        )
        e1 = create_enrollment(child=child1, session=session)
        c1 = confirm_enrollment(enrollment=e1)
        assert c1["scholarship_discount_cents"] == 5_000
        # Cancel — refunds to the award.
        api.cancel_enrollment(e1["id"], TEST_USERS["admin_headers"])
        # New sibling confirms — award is ACTIVE again so discount fires.
        child2 = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            full_name="B",
        )
        e2 = create_enrollment(child=child2, session=session)
        c2 = confirm_enrollment(enrollment=e2)
        assert c2["scholarship_discount_cents"] == 5_000, (
            "after refund, award must be ACTIVE again so a fresh "
            "confirm fully consumes it"
        )


# ===========================================================================
# Fee-quote (provisional) vs confirm-snapshot (final)
# ===========================================================================
class TestFeeQuote:
    def test_fee_quote_does_not_snapshot(self, api):
        """PRD §3.5: "The provisional fee-quote capability returns a
        what-if computation using the current (pre-confirmation)
        sibling count for the requested (session_id, week_index) and
        the current award balances. The quote returns the same shape
        of figures — list_fee_cents, sibling_discount_cents,
        scholarship_discount_cents, final_fee_cents, and
        scholarship_award_id of the award the allocation would
        currently choose — but it explicitly does not snapshot
        anything onto the enrollment row."

        Claim: GET /camp/enrollments/{id}/fee-quote returns the
        expected shape AND the underlying enrollment remains in
        PENDING_AUTH afterwards (the row is not mutated).
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
        res = api.get_fee_quote(
            enrollment["id"], TEST_USERS["admin_headers"],
        )
        quote = validate_success(res, 200)
        for k in (
            "list_fee_cents", "sibling_discount_cents",
            "scholarship_discount_cents", "final_fee_cents",
            "scholarship_award_id",
        ):
            assert k in quote, f"fee-quote must include {k}"
        # Verify the underlying enrollment was not mutated.
        unchanged = re_get_enrollment(enrollment["id"])
        assert unchanged["status"] == "PENDING_AUTH"
