"""Session lifecycle: start, complete, dispute cycle, cancel.

PRD §3.5 (sessions), §2.11 (ledger causality).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    add_seconds,
    advance_clock,
    complete_session_payload,
    create_session_payload,
    dispute_session_payload,
    get_authorization,
    get_clinic,
    make_bcba_headers,
    make_rbt_headers,
    schedule_session,
    setup_active_authorization,
    setup_active_treatment_plan,
    setup_basic_environment,
    setup_clinic_with_roster,
    setup_completed_session,
    setup_completed_session_with_billed_units,
    setup_ledger_for_authorization,
    setup_pending_authorization_unapproved,
    start_session,
    validate_error,
    validate_success,
)


class TestSessionStart:

    def test_start_records_actual_start_as_now_ts(self, api):
        """PRD §3.5: "Starting a scheduled session moves it from
        SCHEDULED to IN_PROGRESS and records actual_start as the
        clinic's now_ts."

        Claim: after /start, session.status == IN_PROGRESS and
        actual_start equals the clinic's current now_ts.
        """
        env = setup_basic_environment()
        clinic = env["clinic"]
        rbt = env["rbts"][0]
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        session = schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=planned_start,
            planned_end=add_minutes(planned_start, minutes=60),
        )
        advance_clock(clinic["id"], 3600)
        now_ts_at_start = get_clinic(clinic["id"])["now_ts"]
        started = start_session(
            session["id"], therapist_id=rbt["id"], therapist_role="RBT",
        )
        assert started["status"] == "IN_PROGRESS"
        assert started.get("actual_start") == now_ts_at_start

    def test_start_by_non_owning_therapist_yields_not_therapist_of_record(
        self, api,
    ):
        """PRD §2.1: "When a BCBA or RBT attempts a therapist-specific
        transition on a session or evaluation whose therapist-of-record
        is a different therapist, the response is
        ERR_NOT_THERAPIST_OF_RECORD with HTTP 403."

        Claim: a DIFFERENT RBT cannot start someone else's session.
        """
        env = setup_basic_environment(num_rbts=2)
        clinic = env["clinic"]
        rbt_owner = env["rbts"][0]
        rbt_other = env["rbts"][1]
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        session = schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            therapist_id=rbt_owner["id"],
            session_type="DIRECT_RBT",
            planned_start=planned_start,
            planned_end=add_minutes(planned_start, minutes=60),
        )
        advance_clock(clinic["id"], 3600)
        res = api.start_session(
            session["id"], make_rbt_headers(rbt_other["id"]),
        )
        validate_error(res, "ERR_NOT_THERAPIST_OF_RECORD")

    def test_start_session_when_authorization_not_active_yields_invalid_state(
        self, api,
    ):
        """PRD §3.5: "The acting therapist must be the session's
        therapist_id, and the Authorization must still be ACTIVE".

        Claim: start fails with ERR_INVALID_STATE when the referenced
        Authorization has left ACTIVE (here driven into RENEWED by an
        approved renewal Authorization per PRD §3.4: "Two simultaneous
        approvals … serialize to first-writer-wins on the parent's
        renewed_from_id slot; the parent's renewed_to_id is set to the
        new Authorization's id, and the parent moves from ACTIVE to
        RENEWED").

        PRD §3.5's scheduling rule also requires ACTIVE, so the only
        PRD-faithful way to land a SCHEDULED session under a non-ACTIVE
        Authorization is to transition the parent Authorization out of
        ACTIVE *after* scheduling. Renewal is one such transition that
        does NOT cascade SCHEDULED sessions to CANCELLED (only the
        ACTIVE→EXPIRED transition does, per PRD §3.5).

        # difficulty: cross_entity_state_dependency/session_start_requires_authorization_active
        """
        from test_helpers import (
            add_days, approve_authorization, get_authorization,
            request_authorization,
        )
        env = setup_basic_environment()
        clinic = env["clinic"]
        rbt = env["rbts"][0]
        auth = env["authorization"]
        # Schedule a session while the parent Authorization is ACTIVE.
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        planned_end = add_minutes(planned_start, minutes=60)
        session = schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=auth["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=planned_start,
            planned_end=planned_end,
        )
        # Build a renewal Authorization that points at the parent via
        # renewed_from_id, approve it. Per PRD §3.4 the parent flips
        # ACTIVE → RENEWED in the same operation.
        clinic_state = get_clinic(clinic["id"])
        renewal_start = add_seconds(clinic_state["now_ts"], seconds=60)
        renewal_end = add_days(renewal_start, days=180)
        renewal_auth = request_authorization(
            patient_id=env["patient"]["id"],
            treatment_plan_id=env["plan"]["id"],
            cpt_code=auth["cpt_code"],
            approved_units=auth["approved_units"],
            effective_start=renewal_start,
            effective_end=renewal_end,
            renewed_from_id=auth["id"],
        )
        approve_authorization(renewal_auth["id"])
        # Sanity: parent is now RENEWED (or at least not ACTIVE).
        parent_auth = get_authorization(auth["id"])
        assert parent_auth["status"] != "ACTIVE"
        # Advance clock to the session's planned_start so the start
        # request isn't rejected for "now_ts before planned_start".
        from test_helpers import parse_iso
        delta = int(
            (parse_iso(planned_start)
             - parse_iso(get_clinic(clinic["id"])["now_ts"])
             ).total_seconds()
        )
        if delta > 0:
            advance_clock(clinic["id"], delta)
        # PRD §3.5: the Authorization must still be ACTIVE; expect
        # ERR_INVALID_STATE.
        res = api.start_session(
            session["id"], make_rbt_headers(rbt["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestSessionComplete:

    def test_complete_sets_actual_end_and_billed_units(self, api):
        """PRD §3.5: "On the transition, actual_end is set to now_ts,
        billed_units is computed by dividing the elapsed minutes
        (actual_end minus actual_start) by 15 and rounding up to the
        next whole unit".

        Claim: after /complete with a 60-minute elapsed window,
        billed_units == 4 and actual_end == now_ts.
        """
        env = setup_basic_environment()
        session, final_now_ts = setup_completed_session(
            clinic=env["clinic"], patient=env["patient"],
            authorization=env["authorization"],
            therapist=env["rbts"][0], therapist_role="RBT",
            session_type="DIRECT_RBT",
            duration_minutes=60, progress_rating=4,
        )
        assert session["status"] == "COMPLETED"
        assert session["billed_units"] == 4
        assert session.get("actual_end") == final_now_ts

    @pytest.mark.parametrize("rating", [0, 6, -1, 10])
    def test_complete_progress_rating_out_of_range_rejected(
        self, api, rating,
    ):
        """PRD §3.5: "The body must carry the progress_rating, an
        integer in the inclusive range from 1 to 5."

        Claim: progress_rating outside [1, 5] is rejected.
        """
        env = setup_basic_environment()
        clinic = env["clinic"]
        rbt = env["rbts"][0]
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        session = schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=planned_start,
            planned_end=add_minutes(planned_start, minutes=60),
        )
        advance_clock(clinic["id"], 3600)
        start_session(
            session["id"], therapist_id=rbt["id"], therapist_role="RBT",
        )
        advance_clock(clinic["id"], 60 * 60)
        res = api.complete_session(
            session["id"],
            complete_session_payload(progress_rating=rating),
            make_rbt_headers(rbt["id"]),
        )
        validate_error(res, "ERR_VALIDATION")

    def test_complete_appends_provisional_debit_to_ledger(self, api):
        """PRD §3.5: "a PROVISIONAL_DEBIT is appended to the ledger
        with units_delta equal to the negative of billed_units and
        reason_code of SESSION_COMPLETED".

        Claim: after /complete, the authorization's ledger contains a
        PROVISIONAL_DEBIT row whose units_delta == -billed_units and
        reason_code == SESSION_COMPLETED.
        """
        env = setup_completed_session_with_billed_units(billed_units=4)
        ledger = setup_ledger_for_authorization(env["authorization"]["id"])
        debits = [
            r for r in ledger
            if r["entry_type"] == "PROVISIONAL_DEBIT"
            and r["reason_code"] == "SESSION_COMPLETED"
        ]
        assert len(debits) == 1
        assert debits[0]["units_delta"] == -4

    def test_complete_recomputes_provisional_units_consumed(self, api):
        """PRD §3.5: "the Authorization's provisional_units_consumed is
        recomputed from the ledger".

        Claim: after a 4-unit /complete, the authorization's
        provisional_units_consumed == 4.
        """
        env = setup_completed_session_with_billed_units(billed_units=4)
        auth_after = get_authorization(env["authorization"]["id"])
        assert auth_after["provisional_units_consumed"] == 4


class TestSessionDisputeCycle:

    def test_dispute_appends_provisional_credit(self, api):
        """PRD §3.5: "On COMPLETED -> DISPUTED, the dispute_reason is
        stored on the session and a PROVISIONAL_CREDIT is appended to
        the ledger with units_delta equal to the positive of
        billed_units and reason_code of SESSION_DISPUTED".

        Claim: after /dispute on a 4-unit session, ledger contains a
        PROVISIONAL_CREDIT row with units_delta == +4 and reason_code
        == SESSION_DISPUTED.

        # difficulty: non_linear_state_machine/therapy_session_dispute_cycle
        """
        env = setup_completed_session_with_billed_units(billed_units=4)
        bcba = env["bcba"]
        res = api.dispute_session(
            env["session"]["id"],
            dispute_session_payload(dispute_reason="review_pending"),
            make_bcba_headers(bcba["id"]),
        )
        disputed = validate_success(res)
        assert disputed["status"] == "DISPUTED"
        ledger = setup_ledger_for_authorization(env["authorization"]["id"])
        credits = [
            r for r in ledger
            if r["entry_type"] == "PROVISIONAL_CREDIT"
            and r["reason_code"] == "SESSION_DISPUTED"
        ]
        assert len(credits) == 1
        assert credits[0]["units_delta"] == 4

    def test_dispute_recomputes_provisional_consumed_to_zero(self, api):
        """PRD §3.5: "the Authorization's provisional_units_consumed is
        recomputed."

        Claim: after a 4-unit session is disputed, provisional_units_consumed
        returns to 0 (debit -4 + credit +4 = 0).

        # difficulty: transitive_cascade/session_dispute_depth_2_cascade
        """
        env = setup_completed_session_with_billed_units(billed_units=4)
        bcba = env["bcba"]
        api.dispute_session(
            env["session"]["id"],
            dispute_session_payload(),
            make_bcba_headers(bcba["id"]),
        )
        auth_after = get_authorization(env["authorization"]["id"])
        assert auth_after["provisional_units_consumed"] == 0

    def test_resolve_dispute_returns_session_to_completed_and_redebits(
        self, api,
    ):
        """PRD §3.5: "Resolving the dispute returns the session from
        DISPUTED to COMPLETED and re-debits the units: a
        PROVISIONAL_DEBIT is appended with units_delta equal to the
        negative of billed_units and reason_code of SESSION_COMPLETED,
        and the Authorization's provisional_units_consumed is
        recomputed."

        Claim: after /resolve-dispute, session is COMPLETED and
        provisional_units_consumed returns to its pre-dispute value.

        # difficulty: non_linear_state_machine/therapy_session_dispute_cycle
        """
        env = setup_completed_session_with_billed_units(billed_units=4)
        bcba = env["bcba"]
        api.dispute_session(
            env["session"]["id"],
            dispute_session_payload(),
            make_bcba_headers(bcba["id"]),
        )
        res = api.resolve_session_dispute(
            env["session"]["id"], make_bcba_headers(bcba["id"]),
        )
        resolved = validate_success(res)
        assert resolved["status"] == "COMPLETED"
        auth_after = get_authorization(env["authorization"]["id"])
        assert auth_after["provisional_units_consumed"] == 4

    def test_dispute_cycle_emits_three_ledger_rows(self, api):
        """PRD §2.11: "Several transitions cascade across entities. …
        Denying an adjudicated claim flips each referenced session back
        from BILLED to COMPLETED and appends a PROVISIONAL_CREDIT
        ledger entry".  PRD §3.5: dispute + resolve-dispute each append
        their own ledger row, giving three rows for one complete +
        dispute + resolve.

        Claim: after the cycle, the authorization has exactly 3 ledger
        entries (initial PROVISIONAL_DEBIT + dispute PROVISIONAL_CREDIT
        + resolve PROVISIONAL_DEBIT).
        """
        env = setup_completed_session_with_billed_units(billed_units=4)
        bcba = env["bcba"]
        api.dispute_session(
            env["session"]["id"],
            dispute_session_payload(),
            make_bcba_headers(bcba["id"]),
        )
        api.resolve_session_dispute(
            env["session"]["id"], make_bcba_headers(bcba["id"]),
        )
        ledger = setup_ledger_for_authorization(env["authorization"]["id"])
        assert len(ledger) == 3


class TestSessionCancel:

    def test_cancel_scheduled_session(self, api, clinic_admin_headers):
        """PRD §3.5: "A SCHEDULED session may be cancelled by a
        ClinicAdmin or a BCBA, terminating it in CANCELLED."

        Claim: cancelling a SCHEDULED session yields status CANCELLED.
        """
        env = setup_basic_environment()
        rbt = env["rbts"][0]
        planned_start = add_seconds(env["now_ts"], seconds=3600)
        session = schedule_session(
            patient_id=env["patient"]["id"],
            authorization_id=env["authorization"]["id"],
            therapist_id=rbt["id"],
            session_type="DIRECT_RBT",
            planned_start=planned_start,
            planned_end=add_minutes(planned_start, minutes=60),
        )
        res = api.cancel_session(session["id"], clinic_admin_headers)
        data = validate_success(res)
        assert data["status"] == "CANCELLED"
