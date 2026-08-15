"""Closeout documents (singularity, revisions, decisions) and training sessions."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_doc,
    assert_training_session,
    begin_punch,
    create_closeout_document_payload,
    create_training_session_payload,
    get_session,
    get_trade,
    make_subcontractor_headers,
    new_project,
    new_trade,
    schedule_training,
    set_clock,
    setup_closeout_project,
    setup_substantially_complete_project,
    submit_doc,
    validate_error,
    validate_success,
)

PM = TEST_USERS["gc_pm_headers"]
INSP = TEST_USERS["gc_inspector_headers"]
OWNER = TEST_USERS["owner_rep_headers"]


class TestDocumentSingularity:

    def test_doc_already_pending_returns_error(self):
        """PRD §3.5: "Two singularity rules apply per trade and document type: at most one document may sit pending — that is, in `SUBMITTED` — at a time, with a second rejected as `ERR_DOC_ALREADY_PENDING`; and once a document of that type has been `APPROVED`, the pair is satisfied and further submissions are rejected with `ERR_DOC_TYPE_ALREADY_SATISFIED`."

        Design: Corner/validations/doc_already_pending_returns_error
        """
        project = new_project(name="Proj")
        trade = new_trade(project["id"])
        begin_punch(project["id"])
        sub = make_subcontractor_headers(trade["id"])
        first = api_client.create_closeout_document(
            create_closeout_document_payload(
                project["id"], trade["id"], doc_type="OM_MANUAL", file_ref="om-v1",
            ),
            sub,
        )
        validate_success(first, 201)
        second = api_client.create_closeout_document(
            create_closeout_document_payload(
                project["id"], trade["id"], doc_type="OM_MANUAL", file_ref="om-v2",
            ),
            sub,
        )
        validate_error(second, ApiErrorId.ERR_DOC_ALREADY_PENDING)

    def test_doc_type_already_satisfied_returns_error(self):
        """PRD §3.5: "Two singularity rules apply per trade and document type: at most one document may sit pending — that is, in `SUBMITTED` — at a time, with a second rejected as `ERR_DOC_ALREADY_PENDING`; and once a document of that type has been `APPROVED`, the pair is satisfied and further submissions are rejected with `ERR_DOC_TYPE_ALREADY_SATISFIED`."

        Design: Corner/validations/doc_type_already_satisfied_returns_error
        """
        ctx = setup_closeout_project(name="Proj")
        project, trade = ctx["project"], ctx["trade"]
        doc = submit_doc(project["id"], trade["id"], "OM_MANUAL", "om-v1")
        approve_doc(doc["id"])
        resp = api_client.create_closeout_document(
            create_closeout_document_payload(
                project["id"], trade["id"], doc_type="OM_MANUAL", file_ref="om-v2",
            ),
            make_subcontractor_headers(trade["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOC_TYPE_ALREADY_SATISFIED)


class TestDocumentRevisionLoop:

    def test_doc_revision_increments_on_resubmission(self):
        """PRD §3.5: "Each accepted submission is numbered by the server: its `revision` is the count of prior documents for the same trade and document type, plus one."
        PRD §3.5: "Rejection requires a `rejection_reason` (`ERR_INVALID_REQUEST` without one) and moves the document to `REJECTED`; the revision loop then runs through a brand-new document for the same trade and type, numbered one higher."

        Design: Corner/validations/doc_revision_increments_on_resubmission
        """
        ctx = setup_closeout_project(name="Proj")
        project, trade = ctx["project"], ctx["trade"]
        first = submit_doc(project["id"], trade["id"], "OM_MANUAL", "om-v1")
        assert first["revision"] == 1
        rejected = validate_success(api_client.reject_closeout_document(
            first["id"], {"rejection_reason": "missing diagrams"}, PM,
        ), 200)
        assert rejected["status"] == "REJECTED"

        second = submit_doc(project["id"], trade["id"], "OM_MANUAL", "om-v2")
        assert second["revision"] == 2
        assert second["status"] == "SUBMITTED"

    def test_doc_approve_from_rejected_returns_invalid_state(self):
        """PRD §3.5: "`APPROVED` and `REJECTED` are both terminal for the document itself."
        PRD §2.10: "8. State-machine and project-phase validity (`ERR_INVALID_STATE`, or `ERR_PROJECT_NOT_CLOSED` for warranty reporting against a project that is not closed)."

        Design: Corner/state_machines/doc_approve_from_rejected_returns_invalid_state
        """
        ctx = setup_closeout_project(name="Proj")
        project, trade = ctx["project"], ctx["trade"]
        doc = submit_doc(project["id"], trade["id"], "OM_MANUAL", "om-v1")
        validate_success(api_client.reject_closeout_document(
            doc["id"], {"rejection_reason": "missing wiring diagrams"}, PM,
        ), 200)
        resp = api_client.approve_closeout_document(doc["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        still = validate_success(api_client.get_closeout_document(doc["id"], PM), 200)
        assert still["status"] == "REJECTED"

    def test_doc_approve_immediately_visible_on_trade(self):
        """PRD §3.5: "Approval moves the document from `SUBMITTED` to `APPROVED`, flips the trade's corresponding flag — `om_doc_approved`, `warranty_doc_approved`, or `asbuilt_doc_approved` according to `doc_type` — and recomputes `closeout_ready`."

        Design: Corner/consistency_model/doc_approve_immediately_visible_on_trade
        """
        ctx = setup_closeout_project(name="Proj")
        project, trade = ctx["project"], ctx["trade"]
        assert get_trade(trade["id"])["om_doc_approved"] is False
        doc = submit_doc(project["id"], trade["id"], "OM_MANUAL", "om-v1")
        approved = validate_success(api_client.approve_closeout_document(doc["id"], PM), 200)
        assert approved["status"] == "APPROVED"
        assert get_trade(trade["id"])["om_doc_approved"] is True


class TestTrainingConduct:

    def test_session_conduct_before_start_returns_error(self):
        """PRD §3.5: "Conducting the session is possible once the logical clock has reached its `scheduled_start` — earlier attempts fail with `ERR_SESSION_NOT_STARTED` — and requires an `attendee_count` of at least one (`ERR_NO_ATTENDEES` otherwise)."

        Design: Corner/validations/session_conduct_before_start_returns_error
        """
        ctx = setup_substantially_complete_project(name="Proj")
        session = schedule_training(ctx["project"]["id"], ctx["trade"]["id"],
                                    location_room="TR-1",
                                    scheduled_start="2026-08-10T09:00:00Z",
                                    scheduled_end="2026-08-10T10:00:00Z")
        # Clock is still pinned at the SC instant (2026-08-03T10:00:00Z).
        resp = api_client.conduct_training_session(session["id"], {"attendee_count": 3}, PM)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_STARTED)
        after = get_session(session["id"])
        assert after["status"] == "SCHEDULED"
        assert after["attendee_count"] is None

    def test_conduct_zero_attendees_boundary(self):
        """PRD §3.5: "Conducting the session is possible once the logical clock has reached its `scheduled_start` — earlier attempts fail with `ERR_SESSION_NOT_STARTED` — and requires an `attendee_count` of at least one (`ERR_NO_ATTENDEES` otherwise)."

        Design: Corner/validations/conduct_zero_attendees_boundary
        """
        ctx = setup_substantially_complete_project(name="Proj")
        session = schedule_training(ctx["project"]["id"], ctx["trade"]["id"],
                                    location_room="TR-1",
                                    scheduled_start="2026-08-04T09:00:00Z",
                                    scheduled_end="2026-08-04T10:00:00Z")
        set_clock("2026-08-04T09:00:00Z")
        zero = api_client.conduct_training_session(session["id"], {"attendee_count": 0}, PM)
        validate_error(zero, ApiErrorId.ERR_NO_ATTENDEES)

        one = validate_success(api_client.conduct_training_session(
            session["id"], {"attendee_count": 1}, PM,
        ), 200)
        assert one["status"] == "CONDUCTED"
        assert one["attendee_count"] == 1


class TestSessionReschedule:

    def _session_in_sc_project(self, room):
        ctx = setup_substantially_complete_project(name="Proj")
        session = schedule_training(ctx["project"]["id"], ctx["trade"]["id"],
                                    location_room=room,
                                    scheduled_start="2026-08-10T09:00:00Z",
                                    scheduled_end="2026-08-10T10:00:00Z")
        return ctx, session

    def test_third_reschedule_returns_limit_error(self):
        """PRD §3.5: "The cap is hard: `reschedule_count` must still be below two, so a session already rescheduled twice rejects a third attempt with `ERR_RESCHEDULE_LIMIT`."
        PRD §3.5: "A successful reschedule replaces the window, increases `reschedule_count` by one, and increments the session's `version`."

        Design: Corner/validations/third_reschedule_returns_limit_error
        """
        ctx, session = self._session_in_sc_project("TR-9")
        v = session["version"]
        first = validate_success(api_client.reschedule_training_session(
            session["id"],
            {"scheduled_start": "2026-08-11T09:00:00Z", "scheduled_end": "2026-08-11T10:00:00Z",
             "expected_training_session_version": v},
            PM,
        ), 200)
        assert first["reschedule_count"] == 1
        second = validate_success(api_client.reschedule_training_session(
            session["id"],
            {"scheduled_start": "2026-08-12T09:00:00Z", "scheduled_end": "2026-08-12T10:00:00Z",
             "expected_training_session_version": first["version"]},
            PM,
        ), 200)
        assert second["reschedule_count"] == 2

        third = api_client.reschedule_training_session(
            session["id"],
            {"scheduled_start": "2026-08-13T09:00:00Z", "scheduled_end": "2026-08-13T10:00:00Z",
             "expected_training_session_version": second["version"]},
            PM,
        )
        validate_error(third, ApiErrorId.ERR_RESCHEDULE_LIMIT)
        after = get_session(session["id"])
        assert after["scheduled_start"].startswith("2026-08-12T09:00:00")

    def test_session_reschedule_stale_version_returns_412(self):
        """PRD §2.7: "Second, rescheduling a training session requires `expected_training_session_version` matching the session's current `version`. A reschedule leaves the session in `SCHEDULED`, so a later request carrying a stale version would observe a state identical to the one it expects and would otherwise apply cleanly on top of an unseen reschedule; the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/session_reschedule_stale_version_returns_412
        """
        ctx, session = self._session_in_sc_project("TR-7")
        v = session["version"]
        moved = validate_success(api_client.reschedule_training_session(
            session["id"],
            {"scheduled_start": "2026-08-11T09:00:00Z", "scheduled_end": "2026-08-11T10:00:00Z",
             "expected_training_session_version": v},
            PM,
        ), 200)
        assert moved["version"] == v + 1

        stale = api_client.reschedule_training_session(
            session["id"],
            {"scheduled_start": "2026-08-12T09:00:00Z", "scheduled_end": "2026-08-12T10:00:00Z",
             "expected_training_session_version": v},
            PM,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert get_session(session["id"])["scheduled_start"].startswith("2026-08-11T09:00:00")


class TestRoomTurnoverBuffer:

    def _project_with_first_session(self):
        ctx = setup_substantially_complete_project(name="Proj O2")
        session = schedule_training(ctx["project"]["id"], ctx["trade"]["id"],
                                    location_room="TR-1",
                                    scheduled_start="2026-08-10T09:00:00Z",
                                    scheduled_end="2026-08-10T10:00:00Z")
        return ctx, session

    def test_adjacent_session_rejected_thirty_minutes_accepted(self):
        """PRD §3.5: "Rooms turn over slowly: a 30-minute buffer must separate any two sessions booked into the same `location_room`, so one session's end and the next session's start must stand at least thirty minutes apart, with outright overlap forbidden; a violation is rejected with `ERR_SESSION_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/session_room_thirty_minute_turnover_buffer
        """
        ctx, _ = self._project_with_first_session()
        # Adjacency (start exactly at the prior end) violates the 30-minute buffer.
        adjacent = api_client.create_training_session(
            create_training_session_payload(
                ctx["project"]["id"], ctx["trade"]["id"], system_name="BMS",
                location_room="TR-1",
                scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T11:00:00Z",
            ),
            PM,
        )
        validate_error(adjacent, ApiErrorId.ERR_SESSION_ROOM_CONFLICT)

        # Exactly 30 minutes after the prior end clears the buffer.
        cleared = api_client.create_training_session(
            create_training_session_payload(
                ctx["project"]["id"], ctx["trade"]["id"], system_name="BMS",
                location_room="TR-1",
                scheduled_start="2026-08-10T10:30:00Z", scheduled_end="2026-08-10T11:30:00Z",
            ),
            PM,
        )
        session = validate_success(cleared, 201)
        assert_training_session(session)
        assert session["status"] == "SCHEDULED"

    def test_same_window_different_room_allowed(self):
        """PRD §3.5: "Rooms turn over slowly: a 30-minute buffer must separate any two sessions booked into the same `location_room`, so one session's end and the next session's start must stand at least thirty minutes apart, with outright overlap forbidden; a violation is rejected with `ERR_SESSION_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/session_room_thirty_minute_turnover_buffer
        """
        ctx, _ = self._project_with_first_session()
        other_room = api_client.create_training_session(
            create_training_session_payload(
                ctx["project"]["id"], ctx["trade"]["id"], system_name="BMS",
                location_room="TR-2",
                scheduled_start="2026-08-10T09:00:00Z", scheduled_end="2026-08-10T10:00:00Z",
            ),
            PM,
        )
        session = validate_success(other_room, 201)
        assert session["status"] == "SCHEDULED"
