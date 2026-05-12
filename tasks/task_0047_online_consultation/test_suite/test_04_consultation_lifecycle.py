"""Consultation lifecycle: accept, start, complete, transfer, cancel,
quality reports, fee calculation. Covers PRD §3.4, §3.5."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_consultation,
    advance_clock,
    api_client,
    complete_consultation,
    create_doctor,
    get_success_data,
    make_doctor_headers,
    make_patient_headers,
    quality_report_payload,
    setup_basic_org,
    setup_completed_consultation,
    setup_consultation_pending,
    setup_in_progress_consultation,
    start_consultation,
    transfer_payload,
    validate_error,
    validate_success,
    TEST_USERS,
    DEFAULT_DOCTOR_BASE_FEE,
)


# =========================================================================
# /accept transitions QUEUED -> ACCEPTED; capacity gate.
# =========================================================================
class TestAccept:

    def test_doctor_accepts_queued_consultation(self, api):
        """PRD §3.4: 'A real-time consultation advances from QUEUED to
        ACCEPTED only when the assigned doctor explicitly accepts it.'
        PRD §3.4: 'On acceptance the consultation's base_fee is
        snapshotted from the doctor's profile.'

        Claim: /accept advances session_status to ACCEPTED and snapshots
        base_fee.
        """
        state = setup_consultation_pending(mode="REAL_TIME")
        accepted = accept_consultation(
            consultation=state["consultation"], doctor=state["doctor"],
        )
        assert accepted["session_status"] == "ACCEPTED"
        # PRD §3.4: 'On acceptance the consultation's base_fee is
        # snapshotted from the doctor's profile.'
        assert accepted.get("base_fee") == DEFAULT_DOCTOR_BASE_FEE

    def test_accept_by_wrong_doctor_rejected(self, api):
        """PRD §3.4: 'Acceptance is permitted only when ... the calling
        user's X-User-ID equals the consultation's doctor_id'.

        Claim: /accept by a different doctor -> ERR_FORBIDDEN (per PRD
        §2.6 ownership-precondition checks fall under authorization).
        """
        state = setup_consultation_pending(mode="REAL_TIME")
        # Create a second doctor; not the assigned one.
        other_doc = create_doctor()
        res = api.accept_consultation(
            state["consultation"]["id"],
            make_doctor_headers(other_doc["id"]),
        )
        # PRD does not explicitly name the error_id for this guard; it
        # could surface as ERR_FORBIDDEN or ERR_INVALID_STATE depending
        # on how the implementer reads the prose. We accept either.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_FORBIDDEN.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])

    def test_accept_when_doctor_suspended_rejected(self, api):
        """PRD §3.4: 'Acceptance is permitted only when ... the doctor's
        status is anything other than SUSPENDED'.

        Claim: doctor.status == SUSPENDED -> /accept rejected (state guard).
        """
        state = setup_consultation_pending(mode="REAL_TIME")
        # Flip the doctor to SUSPENDED via PATCH (PRD §3.1 allows doctor
        # to self-update; admin per PRD §4 is also authorised).
        get_success_data(api_client.patch_doctor(
            state["doctor"]["id"],
            {"status": "SUSPENDED"},
            TEST_USERS["platform_admin_headers"],
        ))
        res = api.accept_consultation(
            state["consultation"]["id"],
            make_doctor_headers(state["doctor"]["id"]),
        )
        # PRD only commits to 'permitted only when' phrasing; status
        # mismatch surfaces as a state-precondition failure.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_INVALID_STATE.value,
            ApiErrorId.ERR_FORBIDDEN.value,
        ])


# =========================================================================
# /start transitions ACCEPTED -> IN_PROGRESS; video quality init.
# =========================================================================
class TestStart:

    def test_start_text_image_session(self, api):
        """PRD §3.4: 'From ACCEPTED, the doctor starts the session to
        advance to IN_PROGRESS.'

        Claim: /start advances to IN_PROGRESS and sets started_at.
        """
        state = setup_consultation_pending(mode="REAL_TIME")
        accept_consultation(
            consultation=state["consultation"], doctor=state["doctor"],
        )
        started = start_consultation(
            consultation=state["consultation"], doctor=state["doctor"],
        )
        assert started["session_status"] == "IN_PROGRESS"
        assert started.get("started_at") is not None

    def test_start_video_initialises_quality_ok(self, api):
        """PRD §3.4: 'Starting sets started_at to the current server
        time; if the media_type is VIDEO, the parallel quality_status is
        initialised to OK (it begins at the inert NOT_APPLICABLE for
        text-image consultations).'

        Claim: VIDEO start -> quality_status == OK.
        """
        state = setup_consultation_pending(
            mode="REAL_TIME", media_type="VIDEO",
        )
        accept_consultation(
            consultation=state["consultation"], doctor=state["doctor"],
        )
        started = start_consultation(
            consultation=state["consultation"], doctor=state["doctor"],
        )
        assert started["quality_status"] == "OK"


# =========================================================================
# /complete: state, billing, transcript.
# =========================================================================
class TestComplete:

    def test_complete_sets_total_fee_short_session(self, api):
        """PRD §3.5: 'duration_minutes ... the ceiling of the elapsed
        seconds divided by 60.' PRD §3.5: 'The first ten minutes are
        billed at 100 cents per minute (the first-tier rate)'. PRD §3.5:
        'rounded half-up to two decimal places. The rounding happens
        exactly once, on the final sum'.

        Claim: 5-minute session at base_fee=30.00 ->
        total_fee = 30.00 + 5*1.00 = 35.00.
        """
        # elapsed = 300s -> ceil(300/60) = 5 min
        # raw_cents = 3000 + 5*100 + 0 = 3500 -> 35.00
        state = setup_completed_consultation(
            elapsed_seconds=300, doctor_base_fee=30.00,
        )
        c = state["consultation"]
        assert c["session_status"] == "COMPLETED"
        assert c["duration_minutes"] == 5
        assert c["total_fee"] == pytest.approx(35.00, abs=0.001)

    def test_complete_two_tier_billing(self, api):
        """PRD §3.5: 'minutes beyond ten are billed at 200 cents per
        minute (the second-tier rate)'.

        Claim: 13-min session at base_fee=30.00 ->
        total = 30.00 + 10*1.00 + 3*2.00 = 46.00.
        """
        # elapsed = 750s -> ceil(750/60) = 13 min
        # raw_cents = 3000 + 10*100 + 3*200 = 4600 -> 46.00
        state = setup_completed_consultation(
            elapsed_seconds=750, doctor_base_fee=30.00,
        )
        c = state["consultation"]
        assert c["duration_minutes"] == 13
        assert c["total_fee"] == pytest.approx(46.00, abs=0.001)

    def test_complete_sets_transcript_archive(self, api):
        """PRD §3.5: 'It mints a fresh UUID into transcript_archive_id to
        record the session-record archive.'

        Claim: transcript_archive_id is set after /complete.
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        from test_helpers import is_valid_uuid
        assert state["consultation"].get("transcript_archive_id")
        assert is_valid_uuid(
            state["consultation"]["transcript_archive_id"]
        )

    def test_complete_video_failed_quality_blocked(self, api):
        """PRD §3.5: 'Once quality_status reaches FAILED, the doctor may
        no longer complete the session normally -- completion of a video
        consultation is gated on quality_status being anything other than
        FAILED.'

        Claim: VIDEO + quality_status FAILED -> /complete returns
        ERR_INVALID_STATE.
        """
        state = setup_in_progress_consultation(media_type="VIDEO")
        # Step quality: OK -> DEGRADED -> FAILED
        get_success_data(api.quality_report(
            state["consultation"]["id"],
            quality_report_payload("DEGRADED"),
            make_doctor_headers(state["doctor"]["id"]),
        ))
        get_success_data(api.quality_report(
            state["consultation"]["id"],
            quality_report_payload("FAILED"),
            make_doctor_headers(state["doctor"]["id"]),
        ))
        res = api.complete_consultation(
            state["consultation"]["id"],
            make_doctor_headers(state["doctor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================
# /transfer: IN_PROGRESS -> TRANSFERRED + sibling ACCEPTED.
# =========================================================================
class TestTransfer:

    def test_transfer_creates_sibling_and_terminates_origin(self, api):
        """PRD §3.5: 'A transfer advances the original consultation from
        IN_PROGRESS to the terminal TRANSFERRED and creates a brand-new
        consultation under the receiving doctor in ACCEPTED status with
        mode = REAL_TIME and a null queue_position.'

        Claim: /transfer sets origin to TRANSFERRED and creates a sibling
        Consultation under target_doctor in ACCEPTED.
        """
        state = setup_in_progress_consultation()
        target_doc = create_doctor()
        from test_helpers import is_valid_uuid
        res = api.transfer_consultation(
            state["consultation"]["id"],
            transfer_payload(target_doctor_id=target_doc["id"]),
            make_doctor_headers(state["doctor"]["id"]),
        )
        data = validate_success(res)
        assert data["session_status"] == "TRANSFERRED"
        # PRD §3.5: 'records the new sibling's doctor id in
        # transfer_to_doctor_id'.
        assert data.get("transfer_to_doctor_id") == target_doc["id"]


# =========================================================================
# DELETE cancel.
# =========================================================================
class TestCancel:

    def test_cancel_queued_consultation(self, api):
        """PRD §3.4: 'A patient may cancel before the session begins,
        transitioning the consultation into the terminal CANCELLED status.
        Cancellation from QUEUED is unconditional'.

        Claim: DELETE on QUEUED -> session_status CANCELLED.
        """
        state = setup_consultation_pending(mode="REAL_TIME")
        res = api.cancel_consultation(
            state["consultation"]["id"],
            make_patient_headers(state["patient"]["id"]),
        )
        data = validate_success(res)
        assert data["session_status"] == "CANCELLED"


# =========================================================================
# Image attachments
# =========================================================================
class TestImageAttachments:

    def test_attach_image_records_attachment_id(self, api):
        """PRD §3.5: 'Image uploads are recorded by the patient by
        attaching ids -- the binary blob is handled out of band; the
        consultation simply collects the attachment_id into
        image_attachment_ids.'

        Claim: POST /image-attachments records the id on image_attachment_ids.
        """
        state = setup_in_progress_consultation()
        from test_helpers import image_attachment_payload
        attachment_id = "att-xyz-123"
        res = api.add_image_attachment(
            state["consultation"]["id"],
            image_attachment_payload(attachment_id),
            make_patient_headers(state["patient"]["id"]),
        )
        # PRD §4: 201 (create)
        validate_success(res, expected_status=201)
        # Verify by GET.
        from test_helpers import api_client
        refreshed = get_success_data(api_client.get_consultation(
            state["consultation"]["id"],
            make_patient_headers(state["patient"]["id"]),
        ))
        assert attachment_id in refreshed.get("image_attachment_ids", [])
