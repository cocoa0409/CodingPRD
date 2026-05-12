"""Service record check-in, finish, and patient completion confirmation.

Covers PRD §3.4 (on-site execution).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_SCHEDULED_START_ISO,
    accept_dispatch,
    add_minutes,
    advance_sr_to_in_progress,
    api_client,
    assert_service_record,
    checklist_item,
    confirm_completion,
    create_certified_nurse,
    create_service_record_payload,
    finish_service_record,
    get_success_data,
    make_nurse_headers,
    make_patient_headers,
    offset_lat_km,
    offset_lng_km,
    perform_checkin,
    setup_basic_dispatched_order,
    setup_in_progress_order,
    validate_error,
    validate_success,
)


class TestCheckinGeofence:

    def test_checkin_within_geofence_succeeds(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'the great-circle distance between the check-in
        coordinates and the order's service_address coordinates must be
        no greater than the check-in geofence radius of 0.5 kilometres'.

        Claim: check-in exactly at service coordinates -> success.
        """
        setup = setup_basic_dispatched_order(
            nurse_specialty="ELDERLY_CARE",
        )
        accept_dispatch(setup["dispatch"], setup["nurse_id"])
        res = api.create_service_record(
            setup["order"]["id"],
            create_service_record_payload(
                checkin_at=DEFAULT_SCHEDULED_START_ISO,
                checkin_lat=setup["order"]["service_lat"],
                checkin_lng=setup["order"]["service_lng"],
                face_verification_passed=True,
                checklist_items=[checklist_item("vitals", done=True)],
                evidence_urls=["https://e.example/1.jpg"],
            ),
            make_nurse_headers(setup["nurse_id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_service_record(data)

    def test_checkin_outside_geofence_rejected(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'the great-circle distance between the check-in
        coordinates and the order's service_address coordinates must be
        no greater than the check-in geofence radius of 0.5 kilometres,
        otherwise ERR_CHECKIN_OUT_OF_RANGE'.

        Claim: check-in at 1km from service address -> 422
        ERR_CHECKIN_OUT_OF_RANGE.
        """
        setup = setup_basic_dispatched_order(
            nurse_specialty="ELDERLY_CARE",
        )
        accept_dispatch(setup["dispatch"], setup["nurse_id"])
        far_lat = offset_lat_km(setup["order"]["service_lat"], 1.0)
        res = api.create_service_record(
            setup["order"]["id"],
            create_service_record_payload(
                checkin_at=DEFAULT_SCHEDULED_START_ISO,
                checkin_lat=far_lat,
                checkin_lng=setup["order"]["service_lng"],
                face_verification_passed=True,
                evidence_urls=["https://e.example/1.jpg"],
            ),
            make_nurse_headers(setup["nurse_id"]),
        )
        validate_error(res, ApiErrorId.ERR_CHECKIN_OUT_OF_RANGE.value)


class TestCheckinFaceVerification:

    def test_checkin_face_verification_failed(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'face_verification_passed must be true, otherwise
        ERR_FACE_VERIFICATION_FAILED'.

        Claim: face_verification_passed=False at check-in -> 422
        ERR_FACE_VERIFICATION_FAILED.
        """
        setup = setup_basic_dispatched_order(
            nurse_specialty="ELDERLY_CARE",
        )
        accept_dispatch(setup["dispatch"], setup["nurse_id"])
        res = api.create_service_record(
            setup["order"]["id"],
            create_service_record_payload(
                checkin_at=DEFAULT_SCHEDULED_START_ISO,
                checkin_lat=setup["order"]["service_lat"],
                checkin_lng=setup["order"]["service_lng"],
                face_verification_passed=False,
                evidence_urls=["https://e.example/1.jpg"],
            ),
            make_nurse_headers(setup["nurse_id"]),
        )
        validate_error(res, ApiErrorId.ERR_FACE_VERIFICATION_FAILED.value)


class TestServiceRecordTransitions:

    def test_checkin_advances_order_to_in_progress(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'A successful check-in creates the ServiceRecord
        with status STARTED, advances the order from DISPATCHED to
        IN_PROGRESS'."""
        setup = setup_basic_dispatched_order(
            nurse_specialty="ELDERLY_CARE",
        )
        accept_dispatch(setup["dispatch"], setup["nurse_id"])
        record = perform_checkin(
            setup["order"]["id"], setup["nurse_id"],
            checkin_at=DEFAULT_SCHEDULED_START_ISO,
            checkin_lat=setup["order"]["service_lat"],
            checkin_lng=setup["order"]["service_lng"],
        )
        assert record["status"] == "STARTED"
        order_after = get_success_data(api.get_order(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        ))
        assert order_after["status"] == "IN_PROGRESS"


class TestFinishCompletionGates:

    def test_finish_blocked_when_checklist_incomplete(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'three completion gates fire: every entry in
        checklist_items must have done set to true, the evidence_urls
        array must contain at least one entry, and every abnormal event
        with severity HIGH must carry a non-empty description note.
        Failure of any gate yields ERR_CHECKLIST_INCOMPLETE.'

        Claim: at least one checklist item with done=false -> 422
        ERR_CHECKLIST_INCOMPLETE on /finish.
        """
        setup = setup_basic_dispatched_order(
            nurse_specialty="ELDERLY_CARE",
        )
        accept_dispatch(setup["dispatch"], setup["nurse_id"])
        perform_checkin(
            setup["order"]["id"], setup["nurse_id"],
            checkin_at=DEFAULT_SCHEDULED_START_ISO,
            checkin_lat=setup["order"]["service_lat"],
            checkin_lng=setup["order"]["service_lng"],
            checklist_items=[
                checklist_item("vitals", done=True),
                checklist_item("dressing", done=False),
            ],
            evidence_urls=["https://e.example/1.jpg"],
        )
        # PRD §3.4: 'The first append after check-in advances the record
        # from STARTED to IN_PROGRESS.'  /finish requires IN_PROGRESS.
        advance_sr_to_in_progress(
            setup["order"]["id"], setup["nurse_id"],
        )
        res = api.finish_service_record(
            setup["order"]["id"],
            make_nurse_headers(setup["nurse_id"]),
        )
        validate_error(res, ApiErrorId.ERR_CHECKLIST_INCOMPLETE.value)

    def test_finish_blocked_when_no_evidence_urls(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'every entry in checklist_items must have done set
        to true, the evidence_urls array must contain at least one
        entry, and every abnormal event with severity HIGH must carry a
        non-empty description note. Failure of any gate yields
        ERR_CHECKLIST_INCOMPLETE.'
        """
        setup = setup_basic_dispatched_order(
            nurse_specialty="ELDERLY_CARE",
        )
        accept_dispatch(setup["dispatch"], setup["nurse_id"])
        perform_checkin(
            setup["order"]["id"], setup["nurse_id"],
            checkin_at=DEFAULT_SCHEDULED_START_ISO,
            checkin_lat=setup["order"]["service_lat"],
            checkin_lng=setup["order"]["service_lng"],
            checklist_items=[checklist_item("vitals", done=True)],
            evidence_urls=[],  # explicit empty
        )
        # PRD §3.4: 'The first append after check-in advances the record
        # from STARTED to IN_PROGRESS.'  /finish requires IN_PROGRESS.
        advance_sr_to_in_progress(
            setup["order"]["id"], setup["nurse_id"],
        )
        res = api.finish_service_record(
            setup["order"]["id"],
            make_nurse_headers(setup["nurse_id"]),
        )
        validate_error(res, ApiErrorId.ERR_CHECKLIST_INCOMPLETE.value)

    def test_finish_advances_to_awaiting_patient_confirm(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'On success, the server stamps completed_at with the
        current instant and the record advances from IN_PROGRESS to
        AWAITING_PATIENT_CONFIRM.'"""
        setup = setup_in_progress_order(
            nurse_specialty="ELDERLY_CARE",
        )
        res = api.finish_service_record(
            setup["order"]["id"],
            make_nurse_headers(setup["nurse_id"]),
        )
        data = validate_success(res)
        assert data["status"] == "AWAITING_PATIENT_CONFIRM"


class TestPatientCompletion:

    def test_confirm_completion_advances_order_and_creates_settlement(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'On success the order advances from IN_PROGRESS to
        COMPLETED, the service record advances from
        AWAITING_PATIENT_CONFIRM to COMPLETED, the final settlement is
        computed and a Settlement row is created with status FINALIZED,
        the payment is captured (payment_status advances from
        AUTHORIZED to CAPTURED)'.
        """
        setup = setup_in_progress_order(nurse_specialty="ELDERLY_CARE")
        finish_service_record(setup["order"]["id"], setup["nurse_id"])
        res = api.confirm_completion(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        data = validate_success(res)
        assert data["status"] == "COMPLETED"
        assert data["payment_status"] == "CAPTURED"
        # Settlement should now exist.
        sres = api.get_settlement(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        settlement = get_success_data(sres)
        assert settlement["status"] == "FINALIZED"
