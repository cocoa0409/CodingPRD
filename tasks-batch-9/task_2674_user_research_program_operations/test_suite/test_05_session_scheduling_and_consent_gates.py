"""Booking a session: the consent gate that stands in front of it, the scope
vector that decides what may be recorded afterwards, and the half-open
thirty-minute buffer that protects a participant's calendar."""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    RESEARCHER_HEADERS,
    RESEARCHER_USER_ID,
    RESEARCH_LEAD_HEADERS,
    RESEARCH_LEAD_USER_ID,
    ApiErrorId,
    assert_consent_record,
    assert_recruitment,
    assert_research_artifact,
    complete_session,
    create_artifact_payload,
    grant_consent,
    invite,
    read_artifact,
    read_recruitment,
    schedule,
    schedule_payload,
    screen,
    set_clock,
    setup_fielding_study,
    setup_two_fielding_studies_sharing_pool,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
SESSION_START = "2026-08-05T14:00:00Z"
SESSION_END = "2026-08-05T15:00:00Z"


def _instant(value):
    """Parse an ISO-8601 instant so two spellings of the same moment compare equal."""
    assert isinstance(value, str) and value, f"Expected an ISO-8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _screened_in_without_consent(api):
    """One INTERVIEW study in the field with a single participant screened in and
    no consent record for that (participant, study) pair yet."""
    set_clock(CLOCK_START, api)
    ctx = setup_fielding_study(
        api, method="INTERVIEW", participant_count=1, target_participant_count=1
    )
    recruitment = invite(ctx["study"]["id"], ctx["participants"][0]["id"], api)
    ctx["recruitment"] = screen(recruitment["id"], api)
    assert ctx["recruitment"]["status"] == "SCREENED_IN", (
        f"Expected SCREENED_IN, got {ctx['recruitment']['status']} before the booking under test"
    )
    return ctx


def _booked_session_under_transcript_only_consent(api):
    """The same chain carried through a transcript-only consent grant, a booked
    session and a completed session, which is where artifacts become registrable."""
    ctx = _screened_in_without_consent(api)
    ctx["consent"] = grant_consent(
        ctx["participants"][0]["id"],
        ctx["study"]["id"],
        api,
        scopes=["TRANSCRIPT"],
        retention_days=120,
    )
    ctx["recruitment"] = schedule(
        ctx["recruitment"]["id"], SESSION_START, SESSION_END, api,
        moderator_user_id=RESEARCHER_USER_ID,
    )
    ctx["recruitment"] = complete_session(ctx["recruitment"]["id"], api)
    return ctx


class TestSchedulingIsGatedOnConsentAndItsScopes:
    def test_booking_is_refused_until_a_granted_consent_record_is_on_file(self, api):
        """A screened-in candidate cannot be booked before consent exists, and the same
        request succeeds once a GRANTED record covers that participant and study.

        PRD 3.5: "Booking a session carries a screened-in candidate `SCREENED_IN → SCHEDULED`."

        PRD 3.5: "First, consent must already be on file: a `ConsentRecord` in `status`
        `GRANTED` must exist for this recruitment's participant and this recruitment's
        study, else the booking is refused with `ERR_CONSENT_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/session_scheduling_gated_on_participant_consent_and_scope
        """
        ctx = _screened_in_without_consent(api)
        recruitment_id = ctx["recruitment"]["id"]

        refused = api.schedule_recruitment(
            recruitment_id,
            schedule_payload(SESSION_START, SESSION_END, RESEARCHER_USER_ID),
            RESEARCHER_HEADERS,
        )
        validate_error(refused, ApiErrorId.CONSENT_MISSING.value)

        untouched = read_recruitment(recruitment_id, api)
        assert untouched["status"] == "SCREENED_IN", (
            f"Expected SCREENED_IN, got {untouched['status']} after a booking refused for missing consent"
        )
        assert untouched["scheduled_start"] is None, (
            f"Expected scheduled_start to stay unset, got {untouched['scheduled_start']}"
        )
        assert untouched["scheduled_end"] is None, (
            f"Expected scheduled_end to stay unset, got {untouched['scheduled_end']}"
        )
        assert untouched["reschedule_count"] == 0, (
            f"Expected reschedule_count 0, got {untouched['reschedule_count']} after a refused booking"
        )

        grant_consent(
            ctx["participants"][0]["id"],
            ctx["study"]["id"],
            api,
            scopes=["TRANSCRIPT"],
            retention_days=120,
        )

        booked = validate_success(
            api.schedule_recruitment(
                recruitment_id,
                schedule_payload(SESSION_START, SESSION_END, RESEARCHER_USER_ID),
                RESEARCHER_HEADERS,
            )
        )
        assert_recruitment(booked)
        assert booked["status"] == "SCHEDULED", (
            f"Expected SCHEDULED, got {booked['status']} once consent was on file"
        )
        assert booked["reschedule_count"] == 0, (
            f"Expected reschedule_count 0 on a first booking, got {booked['reschedule_count']}"
        )
        assert _instant(booked["scheduled_start"]) == _instant(SESSION_START), (
            f"Expected scheduled_start {SESSION_START}, got {booked['scheduled_start']}"
        )
        assert _instant(booked["scheduled_end"]) == _instant(SESSION_END), (
            f"Expected scheduled_end {SESSION_END}, got {booked['scheduled_end']}"
        )

    def test_the_granted_scope_vector_refuses_a_recording_and_admits_a_transcript(self, api):
        """One transcript-only consent record is enough to book the session yet still
        refuses a RECORDING artifact while permitting a TRANSCRIPT one.

        PRD 3.6: "Each artifact type demands a matching consent scope — a `RECORDING`
        needs the `RECORDING` scope, a `TRANSCRIPT` needs the `TRANSCRIPT` scope, and a
        `PII_NOTE` needs the `PII_QUOTE` scope. The platform looks for a `GRANTED` consent
        record whose `participant_id` and `study_id` match those of the recruitment and
        whose `scopes` include the required scope; if there is none, registration is
        refused with `ERR_CONSENT_SCOPE_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/session_scheduling_gated_on_participant_consent_and_scope
        """
        ctx = _booked_session_under_transcript_only_consent(api)
        recruitment_id = ctx["recruitment"]["id"]

        assert ctx["consent"]["status"] == "GRANTED", (
            f"Expected GRANTED, got {ctx['consent']['status']} for the consent record under test"
        )
        assert ctx["consent"]["scopes"] == ["TRANSCRIPT"], (
            f"Expected scopes ['TRANSCRIPT'], got {ctx['consent']['scopes']}"
        )

        refused = api.create_artifact(
            recruitment_id,
            create_artifact_payload("RECORDING", contains_pii=True),
            RESEARCHER_HEADERS,
        )
        validate_error(refused, ApiErrorId.CONSENT_SCOPE_MISSING.value)

        admitted = validate_success(
            api.create_artifact(
                recruitment_id,
                create_artifact_payload("TRANSCRIPT", contains_pii=False),
                RESEARCHER_HEADERS,
            ),
            expected_status=201,
        )
        assert_research_artifact(admitted)
        assert admitted["artifact_type"] == "TRANSCRIPT", (
            f"Expected TRANSCRIPT, got {admitted['artifact_type']}"
        )
        assert admitted["lifecycle_state"] == "RETAINED", (
            f"Expected RETAINED, got {admitted['lifecycle_state']} on a freshly registered artifact"
        )

        rows, _meta = validate_paginated(
            api.list_recruitment_artifacts(recruitment_id, RESEARCHER_HEADERS)
        )
        assert len(rows) == 1, (
            f"Expected exactly 1 artifact, got {len(rows)}; the refused RECORDING write must leave nothing behind"
        )
        assert rows[0]["id"] == admitted["id"], (
            f"Expected the surviving row to be the TRANSCRIPT artifact {admitted['id']}, got {rows[0]['id']}"
        )

    def test_a_transcript_artifact_inherits_the_consent_records_retention_horizon(self, api):
        """A transcript-only grant of 120 days is honoured in full because the transcript
        cap is 365, and the artifact copies that horizon verbatim.

        PRD 3.6: "Each scope carries its own maximum: a `RECORDING` may be kept at most
        180 days, a `TRANSCRIPT` at most 365 days, and a `PII_QUOTE` at most 90 days. Take
        the smallest maximum across every scope the record grants, take the smaller of that
        figure and the requested `retention_days`, and add that many whole days to
        `granted_at` to obtain `retention_until`, preserving the millisecond component of
        the instant exactly."

        PRD 3.6: "When one is found, the artifact inherits that record's `retention_until`
        verbatim and opens in `lifecycle_state` `RETAINED` with `purged_at` and
        `purge_reason` null."

        Design: Difficulty/cross_entity_state_dependency/session_scheduling_gated_on_participant_consent_and_scope
        """
        ctx = _booked_session_under_transcript_only_consent(api)
        consent = ctx["consent"]
        assert_consent_record(consent)

        expected_horizon = _instant(CLOCK_START) + timedelta(days=120)
        assert _instant(consent["granted_at"]) == _instant(CLOCK_START), (
            f"Expected granted_at {CLOCK_START}, got {consent['granted_at']}"
        )
        assert _instant(consent["retention_until"]) == expected_horizon, (
            f"Expected retention_until {expected_horizon.isoformat()}, got {consent['retention_until']}"
        )

        artifact = validate_success(
            api.create_artifact(
                ctx["recruitment"]["id"],
                create_artifact_payload("TRANSCRIPT", contains_pii=False),
                RESEARCHER_HEADERS,
            ),
            expected_status=201,
        )
        assert _instant(artifact["retention_until"]) == _instant(consent["retention_until"]), (
            f"Expected the artifact to inherit {consent['retention_until']}, got {artifact['retention_until']}"
        )

        stored = read_artifact(artifact["id"], api)
        assert stored["lifecycle_state"] == "RETAINED", (
            f"Expected RETAINED, got {stored['lifecycle_state']}"
        )
        assert stored["purged_at"] is None, (
            f"Expected purged_at null on a retained artifact, got {stored['purged_at']}"
        )
        assert stored.get("purge_reason") is None, (
            f"Expected purge_reason null on a retained artifact, got {stored.get('purge_reason')}"
        )


def _participant_with_one_booked_session(api):
    """One participant holding a recruitment in each of two fielding studies of the same
    pool, with the first already booked for 14:00-15:00 on 2026-08-05."""
    set_clock(CLOCK_START, api)
    ctx = setup_two_fielding_studies_sharing_pool(
        api, participant_count=1, method="INTERVIEW"
    )
    participant_id = ctx["participants"][0]["id"]
    study_a, study_b = ctx["studies"][0], ctx["studies"][1]
    for study in (study_a, study_b):
        grant_consent(
            participant_id,
            study["id"],
            api,
            scopes=["RECORDING", "TRANSCRIPT"],
            retention_days=90,
        )
    recruitment_a = screen(invite(study_a["id"], participant_id, api)["id"], api)
    recruitment_b = screen(invite(study_b["id"], participant_id, api)["id"], api)
    recruitment_a = schedule(
        recruitment_a["id"], SESSION_START, SESSION_END, api,
        moderator_user_id=RESEARCH_LEAD_USER_ID,
    )
    assert recruitment_a["status"] == "SCHEDULED", (
        f"Expected the first session to be SCHEDULED, got {recruitment_a['status']}"
    )
    ctx["participant_id"] = participant_id
    ctx["recruitment_a"] = recruitment_a
    ctx["recruitment_b"] = recruitment_b
    return ctx


class TestParticipantSessionBufferIsHalfOpenOnBothSides:
    @pytest.mark.parametrize(
        "requested_start,requested_end,gap_minutes",
        [
            ("2026-08-05T15:15:00Z", "2026-08-05T16:15:00Z", 15),
            ("2026-08-05T15:29:00Z", "2026-08-05T16:29:00Z", 29),
        ],
    )
    def test_a_second_session_inside_the_trailing_buffer_is_refused(
        self, api, requested_start, requested_end, gap_minutes
    ):
        """A second session starting fewer than thirty minutes after a booked one has a
        padded window that still reaches back into the booked interval.

        PRD 3.5: "Third, the participant must be free: no *other* recruitment of the same
        participant that is currently `SCHEDULED` may occupy an interval intersecting the
        requested window widened by **thirty minutes on each side**, evaluated as a
        half-open interval from thirty minutes before `scheduled_start` up to thirty
        minutes after `scheduled_end`; a clash is refused with
        `ERR_PARTICIPANT_SESSION_CONFLICT`. Two sessions exactly thirty minutes apart
        therefore do not clash, whereas twenty-nine minutes apart do."

        Design: Difficulty/resource_temporal_overlap/participant_session_buffer_is_half_open_on_both_sides
        """
        ctx = _participant_with_one_booked_session(api)
        recruitment_b_id = ctx["recruitment_b"]["id"]

        refused = api.schedule_recruitment(
            recruitment_b_id,
            schedule_payload(requested_start, requested_end, RESEARCH_LEAD_USER_ID),
            RESEARCH_LEAD_HEADERS,
        )
        validate_error(refused, ApiErrorId.PARTICIPANT_SESSION_CONFLICT.value)

        untouched = read_recruitment(recruitment_b_id, api)
        assert untouched["status"] == "SCREENED_IN", (
            f"Expected SCREENED_IN, got {untouched['status']} after a clash {gap_minutes} minutes after the booked session"
        )
        assert untouched["scheduled_start"] is None, (
            f"Expected scheduled_start to stay unset, got {untouched['scheduled_start']}"
        )
        assert untouched["scheduled_end"] is None, (
            f"Expected scheduled_end to stay unset, got {untouched['scheduled_end']}"
        )
        assert untouched["reschedule_count"] == 0, (
            f"Expected reschedule_count 0 after a refused booking, got {untouched['reschedule_count']}"
        )

    def test_a_second_session_exactly_thirty_minutes_after_the_first_is_allowed(self, api):
        """Thirty minutes after the booked end, the padded window opens exactly where the
        booked interval closes, so the half-open comparison finds no intersection.

        PRD 3.5: "Third, the participant must be free: no *other* recruitment of the same
        participant that is currently `SCHEDULED` may occupy an interval intersecting the
        requested window widened by **thirty minutes on each side**, evaluated as a
        half-open interval from thirty minutes before `scheduled_start` up to thirty
        minutes after `scheduled_end`; a clash is refused with
        `ERR_PARTICIPANT_SESSION_CONFLICT`. Two sessions exactly thirty minutes apart
        therefore do not clash, whereas twenty-nine minutes apart do."

        PRD 3.5: "On success the two instants and the `moderator_user_id` are stored, the
        recruitment keeps the `guide_version_pinned` it received at invitation, and the
        study's `recruitment_status` is recomputed — which may take it
        `RECRUITING → QUOTA_MET`."

        Design: Difficulty/resource_temporal_overlap/participant_session_buffer_is_half_open_on_both_sides
        """
        ctx = _participant_with_one_booked_session(api)
        recruitment_b_id = ctx["recruitment_b"]["id"]
        requested_start = "2026-08-05T15:30:00Z"
        requested_end = "2026-08-05T16:30:00Z"

        booked = validate_success(
            api.schedule_recruitment(
                recruitment_b_id,
                schedule_payload(requested_start, requested_end, RESEARCH_LEAD_USER_ID),
                RESEARCH_LEAD_HEADERS,
            )
        )
        assert_recruitment(booked)
        assert booked["status"] == "SCHEDULED", (
            f"Expected SCHEDULED, got {booked['status']} for a session exactly thirty minutes after the booked one"
        )
        assert _instant(booked["scheduled_start"]) == _instant(requested_start), (
            f"Expected scheduled_start {requested_start}, got {booked['scheduled_start']}"
        )
        assert _instant(booked["scheduled_end"]) == _instant(requested_end), (
            f"Expected scheduled_end {requested_end}, got {booked['scheduled_end']}"
        )
        assert booked["moderator_user_id"] == RESEARCH_LEAD_USER_ID, (
            f"Expected moderator {RESEARCH_LEAD_USER_ID}, got {booked['moderator_user_id']}"
        )
        assert booked["reschedule_count"] == 0, (
            f"Expected reschedule_count 0 on a first booking, got {booked['reschedule_count']}"
        )

        first = read_recruitment(ctx["recruitment_a"]["id"], api)
        assert first["status"] == "SCHEDULED", (
            f"Expected the earlier session to stay SCHEDULED, got {first['status']}"
        )
        assert _instant(first["scheduled_start"]) == _instant(SESSION_START), (
            f"Expected the earlier session to keep {SESSION_START}, got {first['scheduled_start']}"
        )
        assert _instant(first["scheduled_end"]) == _instant(SESSION_END), (
            f"Expected the earlier session to keep {SESSION_END}, got {first['scheduled_end']}"
        )
        assert first["reschedule_count"] == 0, (
            f"Expected the earlier session's reschedule_count to stay 0, got {first['reschedule_count']}"
        )

        rows, _meta = validate_paginated(
            api.list_recruitments(
                RESEARCHER_HEADERS, params={"participant_id": ctx["participant_id"]}
            )
        )
        assert len(rows) == 2, (
            f"Expected exactly 2 recruitments for this participant, got {len(rows)}"
        )
        assert [row["status"] for row in rows] == ["SCHEDULED", "SCHEDULED"], (
            f"Expected both recruitments SCHEDULED, got {[row['status'] for row in rows]}"
        )

    def test_a_session_ending_exactly_thirty_minutes_before_the_first_is_allowed(self, api):
        """The buffer is padded onto the leading side too, and it is half-open there as
        well: a window whose padded end lands exactly on the booked start is admitted.

        PRD 3.5: "Third, the participant must be free: no *other* recruitment of the same
        participant that is currently `SCHEDULED` may occupy an interval intersecting the
        requested window widened by **thirty minutes on each side**, evaluated as a
        half-open interval from thirty minutes before `scheduled_start` up to thirty
        minutes after `scheduled_end`; a clash is refused with
        `ERR_PARTICIPANT_SESSION_CONFLICT`. Two sessions exactly thirty minutes apart
        therefore do not clash, whereas twenty-nine minutes apart do."

        Design: Difficulty/resource_temporal_overlap/participant_session_buffer_is_half_open_on_both_sides
        """
        ctx = _participant_with_one_booked_session(api)
        recruitment_b_id = ctx["recruitment_b"]["id"]

        clashing = api.schedule_recruitment(
            recruitment_b_id,
            schedule_payload(
                "2026-08-05T12:31:00Z", "2026-08-05T13:31:00Z", RESEARCH_LEAD_USER_ID
            ),
            RESEARCH_LEAD_HEADERS,
        )
        validate_error(clashing, ApiErrorId.PARTICIPANT_SESSION_CONFLICT.value)

        booked = validate_success(
            api.schedule_recruitment(
                recruitment_b_id,
                schedule_payload(
                    "2026-08-05T12:30:00Z", "2026-08-05T13:30:00Z", RESEARCH_LEAD_USER_ID
                ),
                RESEARCH_LEAD_HEADERS,
            )
        )
        assert booked["status"] == "SCHEDULED", (
            f"Expected SCHEDULED, got {booked['status']} for a session ending exactly thirty minutes before the booked one"
        )
        assert _instant(booked["scheduled_end"]) == _instant("2026-08-05T13:30:00Z"), (
            f"Expected scheduled_end 2026-08-05T13:30:00Z, got {booked['scheduled_end']}"
        )
        assert booked["reschedule_count"] == 0, (
            f"Expected reschedule_count 0 on a first booking, got {booked['reschedule_count']}"
        )
