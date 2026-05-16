"""Cascading side effects from session cancel, authorization revoke,
and clock-driven expiry.

Tests cover:
- PRD §3.3: Session OPEN→CANCELLED cancels every non-terminal
  Enrollment + cascades scholarship refund + sibling recompute.
- PRD §3.2: Authorization ACTIVE→REVOKED cascades CONFIRMED →
  CANCELLED on future-week enrollments, refunds scholarship, recomputes
  siblings, promotes waitlist.
- PRD §2.7 + §3.2: Clock advance sweeps expired authorizations and
  re-projects child statuses.
- PRD §3.1: Family soft-delete blocked when CONFIRMED future
  enrollments exist (ERR_FAMILY_HAS_FUTURE_ENROLLMENTS).
"""
from __future__ import annotations

import pytest
from datetime import timedelta

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    confirm_enrollment,
    create_authorization,
    create_authorization_payload,
    create_child,
    create_enrollment,
    grant_scholarship,
    iso_offset,
    iso_utc,
    parse_iso,
    re_get_child,
    re_get_enrollment,
    re_get_session,
    setup_authorized_child,
    setup_confirmed_enrollment,
    setup_family_with_primary_guardian,
    setup_open_session,
    validate_error,
)


# ===========================================================================
# Session OPEN → CANCELLED cascade
# ===========================================================================
class TestSessionCancelCascade:
    def test_session_cancel_cancels_confirmed_enrollment(self, api):
        """PRD §3.3: "From OPEN, cancellation... cascades: every
        Enrollment on this session in a non-terminal state
        (PENDING_AUTH, CONFIRMED, or WAITLISTED) is moved to
        CANCELLED."

        Claim: cancelling a session whose enrollment is CONFIRMED
        moves that enrollment to CANCELLED.
        """
        family, guardian, child, session, confirmed = (
            setup_confirmed_enrollment()
        )
        assert confirmed["status"] == "CONFIRMED"
        api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        after = re_get_enrollment(confirmed["id"])
        assert after["status"] == "CANCELLED"

    def test_session_cancel_refunds_scholarship_credit(self, api):
        """PRD §3.3: "For each cancelled enrollment that had been
        CONFIRMED, the system additionally recomputes
        ScholarshipAward.consumed_credit_cents for the award that
        the enrollment had consumed".

        Claim: after a session cancel cascades a CONFIRMED enrollment
        that consumed 5000 cents of scholarship credit, a new family
        enrollment in a fresh session can again consume the full
        5000 (proving the credit was refunded to the award).
        """
        family, guardian = setup_family_with_primary_guardian()
        grant_scholarship(
            family=family, total_credit_cents=5_000,
            granted_for_kind="ANY",
        )
        # Session 1: confirm an enrollment that exhausts the award.
        session1 = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session1["reference_date"],
        )
        e1 = create_enrollment(child=child, session=session1)
        c1 = confirm_enrollment(enrollment=e1)
        assert c1["scholarship_discount_cents"] == 5_000
        # Cancel session 1 — must refund the scholarship.
        api.cancel_session(session1["id"], TEST_USERS["admin_headers"])
        # Session 2: a new enrollment must again be able to consume 5000.
        session2 = setup_open_session(
            kind="AFTERSCHOOL", base_weekly_fee_cents=10_000,
        )
        child2 = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session2["reference_date"],
            full_name="Refunded Child",
        )
        e2 = create_enrollment(child=child2, session=session2)
        c2 = confirm_enrollment(enrollment=e2)
        assert c2["scholarship_discount_cents"] == 5_000, (
            "after session-cancel refund the award must be ACTIVE "
            "again so a fresh confirm fully consumes 5000"
        )


# ===========================================================================
# Authorization revoke cascade
# ===========================================================================
class TestAuthorizationRevokeCascade:
    def test_revoke_medical_cancels_future_confirmed_enrollment(self, api):
        """PRD §3.2: "Revocation has a substantial downstream effect
        when the child has any CONFIRMED enrollment in a future or
        current week — i.e., the session-week window Session.week_start
        plus seven days times the enrollment's week_index is strictly
        after the current clock — and the revocation causes the
        child's medical_authorization_status or
        pickup_authorization_status to drop below ACTIVE. In that case,
        each such enrollment is moved from CONFIRMED to CANCELLED
        (cascade), cancelled_at is set to the current clock".

        Claim: revoking the only ACTIVE MEDICAL auth on a child with
        a CONFIRMED future enrollment moves that enrollment to
        CANCELLED.
        """
        family, guardian, child, session, confirmed = (
            setup_confirmed_enrollment()
        )
        # Locate the medical authorization on this child.
        from prd_bench_local_runner.testing import get_success_data
        # We created an authorization in setup_authorized_child; re-read
        # the child to confirm medical is ACTIVE.
        assert re_get_child(child["id"])[
            "medical_authorization_status"
        ] == "ACTIVE"
        # Create a fresh MEDICAL auth to know its id, then revoke it
        # plus any auto-created one by re-projection. To keep the test
        # tight, list and revoke all ACTIVE MEDICAL auths for the
        # child via direct revoke endpoints. The implementation must
        # surface auth rows somewhere; the simplest deterministic
        # approach is: create a known second medical auth, then revoke
        # the first one (which we don't know the id of). The PRD does
        # not promise a list-authorizations endpoint, so instead we
        # build a fresh family + child + ONE known medical auth and
        # use that id directly.
        family2, guardian2 = setup_family_with_primary_guardian()
        session2 = setup_open_session(
            base_weekly_fee_cents=10_000,
        )
        child2 = create_child(family=family2)
        from test_helpers import add_emergency_contact
        add_emergency_contact(child=child2, priority=1)
        med_auth = create_authorization(
            child=child2, guardian=guardian2, kind="MEDICAL",
        )
        create_authorization(
            child=child2, guardian=guardian2, kind="PICKUP",
        )
        e = create_enrollment(child=child2, session=session2)
        c = confirm_enrollment(enrollment=e)
        assert c["status"] == "CONFIRMED"
        # Revoke the medical auth — must cascade-cancel the enrollment.
        api.revoke_authorization(
            med_auth["id"], TEST_USERS["admin_headers"],
        )
        e_after = re_get_enrollment(e["id"])
        assert e_after["status"] == "CANCELLED"
        assert e_after.get("cancelled_at") is not None


# ===========================================================================
# Clock advance — Authorization ACTIVE → EXPIRED
# ===========================================================================
class TestClockAdvanceExpirySweep:
    def test_clock_advance_expires_authorization(self, api):
        """PRD §2.7: "The clock is advanced by an admin-only
        test-driving capability that takes an iso_timestamp and
        atomically (a) sweeps every Authorization with status ACTIVE
        whose expires_at is at or before the new instant into the
        EXPIRED state, and (b) re-projects medical_authorization_status
        and pickup_authorization_status onto every affected Child per
        the projection rules in §2.8."

        Claim: an Authorization with expires_at == new clock instant
        is swept to EXPIRED, and the child's projected status flips.
        """
        family, guardian = setup_family_with_primary_guardian()
        child = create_child(family=family)
        # Use an expires_at that is in the near future so we can step
        # the clock past it.
        from test_helpers import add_emergency_contact
        add_emergency_contact(child=child, priority=1)
        expires = iso_offset(hours=1)
        med = create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
            effective_offset_minutes=-60, expires_at=expires,
        )
        # Sanity: child is currently ACTIVE.
        assert re_get_child(child["id"])[
            "medical_authorization_status"
        ] == "ACTIVE"
        # Advance the clock to expires_at exactly.
        advance_clock_to(expires)
        # PRD §2.8 + §2.7: at t == expires_at the auth flips to EXPIRED.
        refreshed = re_get_child(child["id"])
        assert refreshed["medical_authorization_status"] == "EXPIRED"


# ===========================================================================
# Family soft-delete blocking
# ===========================================================================
class TestFamilySoftDeleteBlocking:
    def test_delete_family_blocked_with_future_confirmed_enrollment(
        self, api,
    ):
        """PRD §3.1: "Soft-delete is refused with
        ERR_FAMILY_HAS_FUTURE_ENROLLMENTS whenever any Enrollment
        belonging to this family is currently CONFIRMED against a
        session week whose calendar window (Session.week_start plus
        seven days multiplied by Enrollment.week_index) is strictly
        after the logical clock; the family must first cancel or
        wait out those enrollments."

        Claim: DELETE on a family with a CONFIRMED future enrollment
        returns ERR_FAMILY_HAS_FUTURE_ENROLLMENTS.
        """
        family, guardian, child, session, confirmed = (
            setup_confirmed_enrollment()
        )
        # The setup uses next-Monday week_start, so the week is in the
        # future relative to the clock.
        res = api.delete_family(family["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_FAMILY_HAS_FUTURE_ENROLLMENTS")
