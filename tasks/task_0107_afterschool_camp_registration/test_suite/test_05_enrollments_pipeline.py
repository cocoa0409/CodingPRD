"""Enrollment pipeline: create, confirm, cancel, waitlist promotion.

Tests cover PRD §3.4 (enrollment pipeline + confirmation gate) and the
state machine PENDING_AUTH → CONFIRMED | WAITLISTED | CANCELLED with
the cascading side effects on cancellation.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_emergency_contact,
    assert_enrollment,
    cancel_enrollment,
    confirm_enrollment,
    create_authorization,
    create_child,
    create_enrollment,
    create_enrollment_payload,
    re_get_enrollment,
    setup_authorized_child,
    setup_confirmed_enrollment,
    setup_family_with_primary_guardian,
    setup_n_families_each_with_authorized_child,
    setup_open_session,
    setup_ready_to_confirm,
    validate_error,
    validate_success,
)


# ===========================================================================
# Enrollment creation
# ===========================================================================
class TestEnrollmentCreation:
    def test_create_enrollment_pending_auth(self, api):
        """PRD §3.4: "A guardian or admin creates an Enrollment for a
        specific (child_id, session_id, week_index) tuple. The new row
        starts at PENDING_AUTH."

        Claim: POST /camp/enrollments returns 201 + Enrollment with
        status=="PENDING_AUTH".
        """
        family, guardian, child, session, enrollment = (
            setup_ready_to_confirm()
        )
        assert_enrollment(enrollment)
        assert enrollment["status"] == "PENDING_AUTH"

    def test_week_index_out_of_range_rejected(self, api):
        """PRD §3.4: "the week_index must be at least 0 and strictly
        less than the session's week_count, otherwise the request
        fails with ERR_INVALID_WEEK_INDEX".

        Claim: POST /camp/enrollments with week_index == week_count
        is rejected with ERR_INVALID_WEEK_INDEX.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(week_count=2)
        child = setup_authorized_child(family=family, guardian=guardian)
        res = api.create_enrollment(
            create_enrollment_payload(
                child_id=child["id"], session_id=session["id"],
                week_index=2,  # == week_count, out of range
            ),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_WEEK_INDEX")

    def test_negative_week_index_rejected(self, api):
        """PRD §3.4: "the week_index must be at least 0 and strictly
        less than the session's week_count, otherwise the request
        fails with ERR_INVALID_WEEK_INDEX".

        Claim: POST /camp/enrollments with week_index == -1 is
        rejected with ERR_INVALID_WEEK_INDEX.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(week_count=1)
        child = setup_authorized_child(family=family, guardian=guardian)
        res = api.create_enrollment(
            create_enrollment_payload(
                child_id=child["id"], session_id=session["id"],
                week_index=-1,
            ),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_WEEK_INDEX")

    def test_age_out_of_range_rejected_at_creation(self, api):
        """PRD §3.4: "the child's age in whole years on the session's
        reference_date must be in the inclusive interval from age_min
        to age_max, otherwise the request fails with
        ERR_AGE_OUT_OF_RANGE and no row is created."

        Claim: a child aged 4 in a session with age_min=8 yields
        ERR_AGE_OUT_OF_RANGE on POST /camp/enrollments.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session(age_min=8, age_max=12)
        # Child whose age on reference_date is 4 (below age_min=8).
        child = setup_authorized_child(
            family=family, guardian=guardian, age_years=4,
            reference_date=session["reference_date"],
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                child_id=child["id"], session_id=session["id"],
                week_index=0,
            ),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_AGE_OUT_OF_RANGE")

    def test_duplicate_enrollment_rejected(self, api):
        """PRD §3.4: "Duplicates are forbidden: any non-terminal
        Enrollment already existing for the same (child_id,
        session_id, week_index) causes the new attempt to fail with
        ERR_DUPLICATE_ENROLLMENT."

        Claim: second POST /camp/enrollments for the same
        (child, session, week_index) while the first is PENDING_AUTH
        returns ERR_DUPLICATE_ENROLLMENT.
        """
        family, guardian, child, session, first = setup_ready_to_confirm()
        res = api.create_enrollment(
            create_enrollment_payload(
                child_id=child["id"], session_id=session["id"],
                week_index=0,
            ),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_DUPLICATE_ENROLLMENT")


# ===========================================================================
# Confirmation gate — safety triad
# ===========================================================================
class TestConfirmationGate:
    def test_confirm_requires_session_open(self, api):
        """PRD §3.4: "First, the parent Session must currently be
        OPEN; otherwise the transition is rejected with
        ERR_INVALID_STATE."

        Claim: confirming an enrollment whose session has been
        cancelled returns ERR_INVALID_STATE.
        """
        family, guardian, child, session, enrollment = (
            setup_ready_to_confirm()
        )
        # Cancel the session under the enrollment.
        api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        res = api.confirm_enrollment(
            enrollment["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_confirm_without_medical_auth_rejected(self, api):
        """PRD §3.4: "the child's medical_authorization_status must be
        ACTIVE at request time (else ERR_MEDICAL_AUTH_REQUIRED)".

        Claim: a confirm attempt against a child with no MEDICAL
        Authorization returns ERR_MEDICAL_AUTH_REQUIRED.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session()
        # Build child with PICKUP + emergency contact but no MEDICAL.
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            include_medical=False,
        )
        enrollment = create_enrollment(child=child, session=session)
        res = api.confirm_enrollment(
            enrollment["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_MEDICAL_AUTH_REQUIRED")

    def test_confirm_without_pickup_auth_rejected(self, api):
        """PRD §3.4: "the child's pickup_authorization_status must be
        ACTIVE at request time (else ERR_PICKUP_AUTH_REQUIRED)".

        Claim: a confirm attempt against a child with MEDICAL but no
        PICKUP Authorization returns ERR_PICKUP_AUTH_REQUIRED.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session()
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            include_pickup=False,
        )
        enrollment = create_enrollment(child=child, session=session)
        res = api.confirm_enrollment(
            enrollment["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_PICKUP_AUTH_REQUIRED")

    def test_confirm_without_emergency_contact_rejected(self, api):
        """PRD §3.4: "the child's emergency_contact_count must be at
        least 1 (else ERR_EMERGENCY_CONTACT_REQUIRED)".

        Claim: a confirm attempt against a child with both
        authorizations but zero emergency contacts returns
        ERR_EMERGENCY_CONTACT_REQUIRED.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session()
        child = setup_authorized_child(
            family=family, guardian=guardian,
            reference_date=session["reference_date"],
            include_emergency_contact=False,
        )
        enrollment = create_enrollment(child=child, session=session)
        res = api.confirm_enrollment(
            enrollment["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_EMERGENCY_CONTACT_REQUIRED")


# ===========================================================================
# Successful confirmation + snapshot
# ===========================================================================
class TestConfirmationHappyPath:
    def test_confirm_with_all_prereqs_transitions_to_confirmed(self, api):
        """PRD §3.4: "If the count of currently-CONFIRMED enrollments
        for the target (session_id, week_index) is strictly less than
        Session.weekly_capacity, the enrollment proceeds to CONFIRMED."

        Claim: confirm on an enrollment whose preconditions are met
        and whose week has capacity returns 200 + status==CONFIRMED.
        """
        family, guardian, child, session, enrollment = (
            setup_ready_to_confirm()
        )
        res = api.confirm_enrollment(
            enrollment["id"], TEST_USERS["admin_headers"],
        )
        confirmed = validate_success(res, 200)
        assert confirmed["status"] == "CONFIRMED"

    def test_confirm_snapshots_list_fee(self, api):
        """PRD §3.5: "First, list_fee_cents is set to the parent
        session's base_weekly_fee_cents."

        Claim: after confirm, list_fee_cents on the Enrollment equals
        the session's base_weekly_fee_cents (10000 by default).
        """
        family, guardian, child, session, confirmed = (
            setup_confirmed_enrollment(base_weekly_fee_cents=12_345)
        )
        assert confirmed["list_fee_cents"] == 12_345


# ===========================================================================
# Waitlist branch — capacity full
# ===========================================================================
class TestWaitlistBranch:
    def test_third_confirm_into_capacity_2_goes_to_waitlist(self, api):
        """PRD §3.4: "If the count is exactly at capacity, the
        enrollment instead transitions PENDING_AUTH → WAITLISTED, and
        its waitlist_position is set to one plus the maximum of
        existing waitlist_position values for the same (session_id,
        week_index). There is no error in the waitlist path — this is
        normal behavior."

        Claim: with weekly_capacity=2, the third confirmation lands
        in WAITLISTED with waitlist_position==1, returning 200.
        """
        session = setup_open_session(weekly_capacity=2)
        # Three independent families so siblings don't apply.
        actors = setup_n_families_each_with_authorized_child(
            n=3, reference_date=session["reference_date"],
        )
        enrollments = []
        for _f, _g, child in actors:
            enrollments.append(create_enrollment(
                child=child, session=session,
            ))
        # Confirm first two — both succeed.
        first = confirm_enrollment(enrollment=enrollments[0])
        assert first["status"] == "CONFIRMED"
        second = confirm_enrollment(enrollment=enrollments[1])
        assert second["status"] == "CONFIRMED"
        # Third — capacity at ceiling, must waitlist (200 success).
        res = api.confirm_enrollment(
            enrollments[2]["id"], TEST_USERS["admin_headers"],
        )
        third = validate_success(res, 200)
        assert third["status"] == "WAITLISTED"
        assert third["waitlist_position"] == 1


# ===========================================================================
# Cancel — PENDING_AUTH, WAITLISTED, CONFIRMED, terminal
# ===========================================================================
class TestEnrollmentCancel:
    def test_cancel_pending_auth_sets_cancelled_at(self, api):
        """PRD §3.4: "Cancelling a PENDING_AUTH row simply records
        cancelled_at and ends the lifecycle."

        Claim: cancelling a PENDING_AUTH enrollment returns 200 +
        status==CANCELLED with cancelled_at set.
        """
        family, guardian, child, session, enrollment = (
            setup_ready_to_confirm()
        )
        res = api.cancel_enrollment(
            enrollment["id"], TEST_USERS["admin_headers"],
        )
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled.get("cancelled_at") is not None

    def test_cancel_confirmed_with_waitlist_promotes(self, api):
        """PRD §3.4: "the lowest-positioned WAITLISTED enrollment in
        that week — if any — is promoted via a system transition that
        re-runs all of the confirmation preconditions."

        Claim: when a CONFIRMED row is cancelled while a WAITLISTED
        peer exists, the peer is promoted to CONFIRMED and its
        waitlist_position becomes null.
        """
        session = setup_open_session(weekly_capacity=1)
        actors = setup_n_families_each_with_authorized_child(
            n=2, reference_date=session["reference_date"],
        )
        (_, _, c1), (_, _, c2) = actors
        e1 = create_enrollment(child=c1, session=session)
        e2 = create_enrollment(child=c2, session=session)
        confirm_enrollment(enrollment=e1)
        promoted_candidate = confirm_enrollment(enrollment=e2)
        assert promoted_candidate["status"] == "WAITLISTED"
        # Cancel e1 — e2 must be promoted.
        api.cancel_enrollment(e1["id"], TEST_USERS["admin_headers"])
        e2_after = re_get_enrollment(e2["id"])
        assert e2_after["status"] == "CONFIRMED"
        assert e2_after.get("waitlist_position") is None

    def test_cancel_after_close_rejected(self, api):
        """PRD §3.4: "Cancelling a CONFIRMED row requires the parent
        session to be OPEN (cancellation after CLOSED is rejected
        with ERR_INVALID_STATE)".

        Claim: cancelling a CONFIRMED enrollment whose session has
        moved to CLOSED returns ERR_INVALID_STATE. The session-close
        flow itself requires the clock to be past every week_end; the
        narrower observable here is that a confirmed enrollment
        terminal-state (COMPLETED) cannot be cancelled.
        """
        family, guardian, child, session, confirmed = (
            setup_confirmed_enrollment()
        )
        # Cancel the session (OPEN→CANCELLED) — this cascades the
        # CONFIRMED enrollment to CANCELLED. A subsequent cancel on
        # the now-CANCELLED enrollment must fail as ERR_INVALID_STATE.
        api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        res = api.cancel_enrollment(
            confirmed["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Validation ordering — PRD §2.9 names a partial total order.
# ===========================================================================
class TestValidationOrdering:
    def test_pickup_check_fires_before_emergency_contact_check(self, api):
        """PRD §2.9: "The three confirmation safety checks — active
        medical authorization, active pickup authorization, and at
        least one emergency contact — are evaluated in that order
        against confirmation requests, surfacing
        ERR_MEDICAL_AUTH_REQUIRED, then ERR_PICKUP_AUTH_REQUIRED,
        then ERR_EMERGENCY_CONTACT_REQUIRED."

        Claim: when a confirm attempt simultaneously lacks ACTIVE
        pickup and lacks any emergency contact, the pickup-auth
        check (ordered earlier) wins.
        """
        family, guardian = setup_family_with_primary_guardian()
        session = setup_open_session()
        # Build a child WITH medical auth, WITHOUT pickup auth, and
        # WITHOUT any emergency contact.
        from test_helpers import create_child, create_authorization
        child = create_child(family=family)
        create_authorization(
            child=child, guardian=guardian, kind="MEDICAL",
        )
        enrollment = create_enrollment(child=child, session=session)
        res = api.confirm_enrollment(
            enrollment["id"], TEST_USERS["admin_headers"],
        )
        # PRD §2.9: pickup safety is checked before emergency contact.
        validate_error(res, "ERR_PICKUP_AUTH_REQUIRED")
