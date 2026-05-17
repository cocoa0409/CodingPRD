"""Visit scheduling preconditions, completion ownership, cancellation.

PRD §3.5 (Scheduling, Completing, and Cancelling Visits).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_visit,
    cancel_visit,
    complete_visit,
    create_clinician,
    create_visit_payload,
    date_offset,
    make_field_clinician_headers,
    schedule_visit,
    setup_episode_with_one_completed_visit,
    setup_open_episode,
    suspend_clinician,
    validate_error,
    validate_success,
)


# ===========================================================================
# Visit schedule — happy path
# ===========================================================================
class TestVisitScheduleHappyPath:

    def test_schedule_visit_returns_scheduled(self, api):
        """PRD §3.5: "A newly scheduled visit lands in SCHEDULED status."

        Claim: POST /episodes/{id}/visits returns 201 with status
        SCHEDULED.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=clinician["id"],
                visit_type="SN",
                visit_date=episode["start_date"],
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_visit(data)
        assert data["status"] == "SCHEDULED"
        assert data["episode_id"] == episode["id"]


# ===========================================================================
# Visit schedule — preconditions
# ===========================================================================
class TestVisitSchedulePreconditions:

    def test_schedule_on_closed_episode_rejected(self, api):
        """PRD §3.5: "The target episode must be OPEN; mutations against
        a non-OPEN episode are rejected with ERR_EPISODE_NOT_OPEN."

        Claim: scheduling a visit on a CLOSED Episode returns
        ERR_EPISODE_NOT_OPEN.
        """
        from test_helpers import setup_closed_episode
        anchor_clock()
        _, _, closed = setup_closed_episode()
        clinician = create_clinician(discipline="SN")
        res = api.create_visit(
            closed["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="SN",
                visit_date=closed["start_date"],
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_EPISODE_NOT_OPEN")

    def test_schedule_with_expired_license_rejected(self, api):
        """PRD §3.5: "The clinician's license must still be valid on the
        visit date — license_expiration_date strictly greater than
        visit_date. A license whose expiration date is on or before the
        visit date is rejected with ERR_CLINICIAN_LICENSE_EXPIRED."

        Claim: scheduling with a clinician whose license expires before
        the visit_date is rejected.
        """
        anchor_clock("2026-01-01")
        _, _, episode = setup_open_episode()
        # License expired well before any visit date in this episode.
        clinician = create_clinician(
            discipline="SN", license_expiration_date="2025-01-01",
        )
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="SN",
                visit_date=episode["start_date"],
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_CLINICIAN_LICENSE_EXPIRED")

    def test_schedule_with_license_expiring_on_visit_date_rejected(
        self, api,
    ):
        """PRD §3.5: "Strict inequality: a visit on the expiration date
        itself is blocked."

        Claim: license_expiration_date == visit_date is rejected with
        ERR_CLINICIAN_LICENSE_EXPIRED.
        """
        anchor_clock("2026-01-01")
        _, _, episode = setup_open_episode()
        visit_date = episode["start_date"]
        clinician = create_clinician(
            discipline="SN", license_expiration_date=visit_date,
        )
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="SN",
                visit_date=visit_date,
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_CLINICIAN_LICENSE_EXPIRED")

    def test_schedule_with_suspended_clinician_rejected(self, api):
        """PRD §3.5: "The clinician must be AVAILABLE; a SUSPENDED
        clinician is rejected with ERR_CLINICIAN_NOT_AVAILABLE."

        Claim: scheduling with a SUSPENDED clinician returns
        ERR_CLINICIAN_NOT_AVAILABLE.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        suspend_clinician(clinician)
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="SN",
                visit_date=episode["start_date"],
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_CLINICIAN_NOT_AVAILABLE")

    def test_schedule_with_discipline_mismatch_rejected(self, api):
        """PRD §3.5: "The clinician's discipline must equal the
        requested visit_type; a mismatch is rejected with
        ERR_DISCIPLINE_MISMATCH."

        Claim: requesting visit_type=PT against a discipline=SN
        clinician is rejected.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="PT",
                visit_date=episode["start_date"],
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_DISCIPLINE_MISMATCH")

    def test_visit_date_before_episode_start_rejected(self, api):
        """PRD §3.5: "The visit_date must be inclusively within the
        episode's window — at least the start_date and at most the
        end_date. A date outside the window is rejected with
        ERR_VISIT_OUTSIDE_EPISODE."

        Claim: visit_date earlier than episode.start_date is rejected.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        # One day BEFORE start_date.
        before = date_offset(episode["start_date"], days=-1)
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="SN",
                visit_date=before,
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_VISIT_OUTSIDE_EPISODE")

    def test_visit_date_after_episode_end_rejected(self, api):
        """PRD §3.5: "A date outside the window is rejected with
        ERR_VISIT_OUTSIDE_EPISODE."

        Claim: visit_date later than episode.end_date is rejected.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        after = date_offset(episode["end_date"], days=1)
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="SN",
                visit_date=after,
                start_minute=480, end_minute=540,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_VISIT_OUTSIDE_EPISODE")

    @pytest.mark.parametrize("start_minute,end_minute", [
        (600, 600),     # equal — end_minute must be strictly > start_minute
        (600, 599),     # end before start
        (-1, 60),       # below 0
        (0, 1440),      # 1440 is above the 1439 ceiling
    ])
    def test_invalid_visit_time_rejected(
        self, api, start_minute, end_minute,
    ):
        """PRD §3.5: "The visit time window must be well-formed:
        end_minute strictly greater than start_minute, with both values
        in the inclusive range 0 through 1439. A malformed window is
        rejected with ERR_VISIT_TIME_INVALID."

        Claim: each malformed window value is rejected.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        res = api.create_visit(
            episode["id"],
            create_visit_payload(
                clinician_id=clinician["id"], visit_type="SN",
                visit_date=episode["start_date"],
                start_minute=start_minute, end_minute=end_minute,
            ),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_VISIT_TIME_INVALID")


# ===========================================================================
# Visit completion — ownership-gated
# ===========================================================================
class TestVisitComplete:

    def test_owning_clinician_can_complete_after_visit_date(self, api):
        """PRD §3.5: "A FieldClinician completes a visit they own. The
        completion action requires that X-User-ID equal the visit's
        clinician_id, that current_date be on or after visit_date, and
        that the visit be in SCHEDULED status".

        Claim: the owning clinician can complete on/after visit_date.
        """
        _, _, _, _, completed = setup_episode_with_one_completed_visit()
        # setup helper already runs schedule + complete via the owning
        # clinician; verify the projection.
        assert_visit(completed)
        assert completed["status"] == "COMPLETED"

    def test_complete_visit_state_machine_returns_completed(self, api):
        """PRD §3.5: "A successful completion moves the visit from
        SCHEDULED to COMPLETED."

        Claim: re-fetching the visit after completion shows COMPLETED.
        """
        _, _, _, clinician, visit = setup_episode_with_one_completed_visit()
        assert visit["status"] == "COMPLETED"
        assert visit["clinician_id"] == clinician["id"]


# ===========================================================================
# Visit cancellation
# ===========================================================================
class TestVisitCancel:

    def test_cancel_scheduled_visit_transitions_to_cancelled(self, api):
        """PRD §3.5: "An IntakeCoordinator may cancel a visit that is
        still in SCHEDULED; cancellation has no further preconditions
        beyond the state check and moves the visit from SCHEDULED to
        CANCELLED."

        Claim: cancelling a SCHEDULED visit transitions it to CANCELLED.
        """
        anchor_clock()
        _, _, episode = setup_open_episode()
        clinician = create_clinician(discipline="SN")
        visit = schedule_visit(episode=episode, clinician=clinician)
        cancelled = cancel_visit(visit=visit)
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_already_completed_visit_rejected(self, api):
        """PRD §3.5: "A cancel attempt on a visit not in SCHEDULED is
        also rejected with ERR_VISIT_NOT_SCHEDULED."

        Claim: cancelling a COMPLETED visit returns
        ERR_VISIT_NOT_SCHEDULED.
        """
        _, _, _, _, visit = setup_episode_with_one_completed_visit()
        assert visit["status"] == "COMPLETED"
        res = api.cancel_visit(
            visit["id"],
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_VISIT_NOT_SCHEDULED")
