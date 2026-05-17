"""Therapy session scheduling: temporal constraints, CPT alignment,
fiscal capacity, overlap rules, parent-training buffer.

PRD §3.5 (session creation), §2.12 (interval semantics).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    add_minutes,
    add_seconds,
    advance_clock,
    create_session_payload,
    get_clinic,
    schedule_session,
    setup_basic_environment,
    setup_environment_with_two_authorizations,
    validate_error,
    validate_success,
)


class TestSessionDuration:

    @pytest.mark.parametrize("minutes", [14, 481, 0, 1000])
    def test_session_length_out_of_range_rejected(
        self, api, clinic_admin_headers, minutes,
    ):
        """PRD §3.5: "its length in minutes — planned_end minus
        planned_start measured in whole minutes — must be in the
        inclusive range from 15 to 480 minutes".

        Claim: planned interval shorter than 15 or longer than 480
        minutes is rejected.
        """
        env = setup_basic_environment()
        rbt = env["rbts"][0]
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        planned_end = add_minutes(planned_start, minutes=minutes)
        res = api.create_session(
            env["patient"]["id"],
            create_session_payload(
                authorization_id=env["authorization"]["id"],
                therapist_id=rbt["id"],
                session_type="DIRECT_RBT",
                planned_start=planned_start,
                planned_end=planned_end,
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_VALIDATION")


class TestCptCodeAlignment:

    def test_direct_rbt_session_against_supervision_auth_rejected(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.5: "The Authorization must be ACTIVE, and its cpt_code
        must align with the session type: DIRECT_RBT requires 97153,
        BCBA_SUPERVISION requires 97155, PARENT_TRAINING requires
        97156. A mismatch is rejected with ERR_CPT_CODE_MISMATCH."

        Claim: a DIRECT_RBT session under a 97155 authorization is
        rejected with ERR_CPT_CODE_MISMATCH.
        """
        env = setup_environment_with_two_authorizations(
            cpt_codes=("97153", "97155"),
        )
        rbt = env["rbts"][0]
        # Use the second auth (97155) for a DIRECT_RBT session.
        bcba_auth = env["authorizations"][1]
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        planned_end = add_minutes(planned_start, minutes=60)
        res = api.create_session(
            env["patient"]["id"],
            create_session_payload(
                authorization_id=bcba_auth["id"],
                therapist_id=rbt["id"],
                session_type="DIRECT_RBT",
                planned_start=planned_start,
                planned_end=planned_end,
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_CPT_CODE_MISMATCH")


class TestSessionInsideAuthorizationWindow:

    def test_session_outside_authorization_window_rejected(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.5: "The planned interval must fit inside the
        Authorization's window … A violation of any of these is
        rejected with ERR_SESSION_OUTSIDE_AUTH_WINDOW."

        Claim: a session whose planned_end is after the authorization's
        effective_end is rejected with ERR_SESSION_OUTSIDE_AUTH_WINDOW.
        """
        env = setup_basic_environment()
        rbt = env["rbts"][0]
        # Schedule a session whose planned_start is past effective_end.
        planned_start = add_days(
            env["authorization"]["effective_end"], days=1,
        )
        planned_end = add_minutes(planned_start, minutes=60)
        res = api.create_session(
            env["patient"]["id"],
            create_session_payload(
                authorization_id=env["authorization"]["id"],
                therapist_id=rbt["id"],
                session_type="DIRECT_RBT",
                planned_start=planned_start,
                planned_end=planned_end,
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_SESSION_OUTSIDE_AUTH_WINDOW")

    def test_session_in_past_rejected(self, api, clinic_admin_headers):
        """PRD §3.5: "planned_start must not be in the past relative to
        the clinic's now_ts. A violation of any of these is rejected
        with ERR_SESSION_OUTSIDE_AUTH_WINDOW."

        Claim: a session whose planned_start is before now_ts is
        rejected with ERR_SESSION_OUTSIDE_AUTH_WINDOW.
        """
        env = setup_basic_environment()
        rbt = env["rbts"][0]
        # planned_start is 1 minute BEFORE now_ts -- but must still be
        # >= effective_start; use now_ts - 1 minute, which is inside
        # the window (window started a day ago).
        planned_start = add_minutes(env["now_ts"], minutes=-60)
        planned_end = add_minutes(planned_start, minutes=60)
        res = api.create_session(
            env["patient"]["id"],
            create_session_payload(
                authorization_id=env["authorization"]["id"],
                therapist_id=rbt["id"],
                session_type="DIRECT_RBT",
                planned_start=planned_start,
                planned_end=planned_end,
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_SESSION_OUTSIDE_AUTH_WINDOW")


class TestFiscalCapacity:

    def test_session_planned_units_exceeding_balance_rejected(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.5: "The session's planned_units must also be at most
        the Authorization's current provisional balance — at-most is
        inclusive, so the case where planned_units equals the remaining
        balance passes; only a strict excess is rejected with
        ERR_AUTH_UNITS_EXHAUSTED."

        Claim: a session whose planned_units strictly exceeds the
        remaining balance is rejected with ERR_AUTH_UNITS_EXHAUSTED.
        """
        # Build an environment with approved_units = 4 (1 hour quota).
        env = setup_basic_environment(approved_units=4)
        rbt = env["rbts"][0]
        # Now plan a 2-hour (8 unit) session — strictly > 4.
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        planned_end = add_minutes(planned_start, minutes=120)
        res = api.create_session(
            env["patient"]["id"],
            create_session_payload(
                authorization_id=env["authorization"]["id"],
                therapist_id=rbt["id"],
                session_type="DIRECT_RBT",
                planned_start=planned_start,
                planned_end=planned_end,
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_AUTH_UNITS_EXHAUSTED")

    def test_session_planned_units_equal_balance_accepted(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.5: "the case where planned_units equals the remaining
        balance passes; only a strict excess is rejected".

        Claim: a session whose planned_units == remaining balance is
        accepted.
        """
        env = setup_basic_environment(approved_units=4)
        rbt = env["rbts"][0]
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        # 60 minutes == 4 units exactly.
        planned_end = add_minutes(planned_start, minutes=60)
        res = api.create_session(
            env["patient"]["id"],
            create_session_payload(
                authorization_id=env["authorization"]["id"],
                therapist_id=rbt["id"],
                session_type="DIRECT_RBT",
                planned_start=planned_start,
                planned_end=planned_end,
            ),
            clinic_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["planned_units"] == 4


class TestTherapistOverlap:

    def test_overlapping_session_for_same_therapist_rejected(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.5: "For the same therapist_id, no two sessions in any
        of the statuses SCHEDULED, IN_PROGRESS, COMPLETED, BILLED, or
        DISPUTED may share any wall-clock minute. The conflict check
        uses half-open intervals: two sessions whose intervals merely
        touch at the boundary are permitted, but any positive overlap
        is rejected with ERR_SESSION_THERAPIST_OVERLAP."

        Claim: a second session that positively overlaps the first
        (same therapist) is rejected with ERR_SESSION_THERAPIST_OVERLAP.

        # difficulty: resource_temporal_overlap/therapist_half_open_interval_overlap
        """
        env = setup_basic_environment()
        rbt = env["rbts"][0]
        first_start = add_seconds(env["now_ts"], seconds=3600)
        first_end = add_minutes(first_start, minutes=60)
        schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=first_start,
            planned_end=first_end,
        )
        # Overlap: starts 30 mins into the first.
        overlap_start = add_minutes(first_start, minutes=30)
        overlap_end = add_minutes(overlap_start, minutes=60)
        res = api.create_session(
            env["patient"]["id"],
            create_session_payload(
                authorization_id=env["authorization"]["id"],
                therapist_id=rbt["id"],
                session_type="DIRECT_RBT",
                planned_start=overlap_start,
                planned_end=overlap_end,
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_SESSION_THERAPIST_OVERLAP")

    def test_touching_boundary_for_same_therapist_allowed(self, api):
        """PRD §3.5: "two sessions whose intervals merely touch at the
        boundary are permitted, but any positive overlap is rejected
        with ERR_SESSION_THERAPIST_OVERLAP."

        Claim: a second session that starts exactly when the first ends
        (same therapist) is accepted.

        # difficulty: resource_temporal_overlap/therapist_half_open_interval_overlap
        """
        env = setup_basic_environment()
        rbt = env["rbts"][0]
        first_start = add_seconds(env["now_ts"], seconds=3600)
        first_end = add_minutes(first_start, minutes=60)
        schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=first_start,
            planned_end=first_end,
        )
        # Touch at boundary.
        second = schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=first_end,
            planned_end=add_minutes(first_end, minutes=60),
        )
        assert second["status"] == "SCHEDULED"


class TestParentTrainingBuffer:

    def test_parent_training_touching_other_session_rejected(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.5: "Parent-training sessions impose an additional
        restriction on the patient — the planned interval expanded by
        15 minutes on each side must not collide with any other session
        of the same patient in those same statuses; this buffer rule
        treats touching as a conflict, and a violation is rejected with
        ERR_PARENT_TRAINING_BUFFER."

        Claim: a PARENT_TRAINING session touching another session at
        the boundary is rejected with ERR_PARENT_TRAINING_BUFFER.

        # difficulty: resource_temporal_overlap/parent_training_closed_buffered_overlap
        """
        env = setup_environment_with_two_authorizations(
            cpt_codes=("97153", "97156"),
        )
        rbt = env["rbts"][0]
        bcba = env["bcbas"][0]
        rbt_auth = env["authorizations"][0]
        parent_auth = env["authorizations"][1]
        first_start = add_seconds(env["now_ts"], seconds=3600)
        first_end = add_minutes(first_start, minutes=60)
        schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=rbt_auth["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=first_start,
            planned_end=first_end,
        )
        # PARENT_TRAINING touching at the boundary — must be rejected.
        res = api.create_session(
            env["patient"]["id"],
            create_session_payload(
                authorization_id=parent_auth["id"],
                therapist_id=bcba["id"],
                session_type="PARENT_TRAINING",
                planned_start=first_end,
                planned_end=add_minutes(first_end, minutes=45),
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_PARENT_TRAINING_BUFFER")

    def test_parent_training_16_minutes_after_other_session_allowed(
        self, api,
    ):
        """PRD §3.5: parent-training buffer is "15 minutes on each
        side"; once the gap is at least 15 minutes the buffer rule no
        longer collides.

        Claim: a PARENT_TRAINING session 16 minutes after the previous
        session's end is accepted.

        # difficulty: resource_temporal_overlap/parent_training_closed_buffered_overlap
        """
        env = setup_environment_with_two_authorizations(
            cpt_codes=("97153", "97156"),
        )
        rbt = env["rbts"][0]
        bcba = env["bcbas"][0]
        rbt_auth = env["authorizations"][0]
        parent_auth = env["authorizations"][1]
        first_start = add_seconds(env["now_ts"], seconds=3600)
        first_end = add_minutes(first_start, minutes=60)
        schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=rbt_auth["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=first_start,
            planned_end=first_end,
        )
        gap_start = add_minutes(first_end, minutes=16)
        second = schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=parent_auth["id"],
            therapist_id=bcba["id"],
            session_type="PARENT_TRAINING",
            planned_start=gap_start,
            planned_end=add_minutes(gap_start, minutes=45),
        )
        assert second["status"] == "SCHEDULED"


class TestSupervisionSessionRequiresEligibleRbt:

    def test_supervision_without_rbt_history_rejected(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.5: "When the session type is BCBA_SUPERVISION, the
        supervising_therapist_id must resolve to an ACTIVE RBT
        therapist of the same clinic who has at least one session in
        COMPLETED or BILLED with the same patient in the trailing 30
        days; otherwise the request is rejected with
        ERR_NO_RBT_TO_SUPERVISE."

        Claim: a BCBA_SUPERVISION session whose supervising_therapist_id
        has no qualifying recent RBT session is rejected with
        ERR_NO_RBT_TO_SUPERVISE.

        # difficulty: priority_pair_validation_conflict/referential_vs_fiscal_on_session_create
        """
        # Pure 97155 (supervision) environment + RBT with no history.
        env = setup_basic_environment(cpt_code="97155", num_rbts=1)
        rbt = env["rbts"][0]
        bcba = env["bcbas"][0]
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        res = api.create_session(
            env["patient"]["id"],
            create_session_payload(
                authorization_id=env["authorization"]["id"],
                therapist_id=bcba["id"],
                session_type="BCBA_SUPERVISION",
                planned_start=planned_start,
                planned_end=add_minutes(planned_start, minutes=60),
                supervising_therapist_id=rbt["id"],
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_NO_RBT_TO_SUPERVISE")
