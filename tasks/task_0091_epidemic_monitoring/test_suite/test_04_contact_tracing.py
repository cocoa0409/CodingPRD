"""Contact events and tracing-task lifecycle — PRD §3.3."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    accept_tracing_task,
    advance_clock,
    api_client,
    assert_contact_event,
    assert_tracing_task,
    complete_tracing_task,
    create_contact_event_payload,
    create_person,
    dispatch_tracing_task,
    file_case,
    iso_utc,
    make_cdc_dispatcher_headers,
    make_cdc_tracer_headers,
    make_hospital_reporter_headers,
    setup_district_with_hospital_and_cdc,
    validate_error,
    validate_success,
)


# ===========================================================================
# ContactEvent ingestion — PRD §3.3
# ===========================================================================
class TestContactEventIngestion:

    def test_self_contact_rejected(self, api):
        """PRD §3.3: "source_person_id must differ from
        target_person_id, rejected with ERR_SELF_CONTACT."

        Claim: a ContactEvent where source == target → ERR_SELF_CONTACT.
        """
        region, hospital, _cdc = setup_district_with_hospital_and_cdc(
            district_code="D-CT-1",
        )
        person = create_person(district_code=region["district_code"])
        payload = create_contact_event_payload(
            source_person_id=person["id"],
            target_person_id=person["id"],
            event_type="HOUSEHOLD",
        )
        resp = api.create_contact_event(
            payload, make_hospital_reporter_headers(hospital["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_CONTACT.value)

    def test_future_event_time_rejected(self, api):
        """PRD §3.3: "event_time cannot be in the future, rejected with
        ERR_EVENT_TIME_INVALID."

        Claim: a ContactEvent with event_time strictly in the future →
        ERR_EVENT_TIME_INVALID.
        """
        region, hospital, _cdc = setup_district_with_hospital_and_cdc(
            district_code="D-CT-2",
        )
        src = create_person(district_code=region["district_code"])
        tgt = create_person(district_code=region["district_code"])
        future = iso_utc(datetime.now(timezone.utc) + timedelta(days=2))
        payload = create_contact_event_payload(
            source_person_id=src["id"],
            target_person_id=tgt["id"],
            event_type="HOUSEHOLD",
            event_time=future,
        )
        resp = api.create_contact_event(
            payload, make_hospital_reporter_headers(hospital["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_TIME_INVALID.value)

    def test_household_close_distance_long_duration_classified_close(self, api):
        """PRD §3.3: "The base weight is read from a per-channel table:
        a HOUSEHOLD contact weighs 10 points, a COWORKER contact 6, a
        VENUE contact 4, and a TRANSIT contact 2. Proximity multiplies
        the weight by one if distance_meters is at most 1.5, and by
        one-half otherwise. Duration multiplies by the smaller of two
        quantities — the number of minutes divided by 60, and a cap of
        4. The raw edge weight is the product of base weight, proximity
        factor, and duration factor. The edge's tier is set to CLOSE
        when this raw weight is at least 5.0, and SUB_CLOSE otherwise."

        Claim: HOUSEHOLD (base 10) × proximity 1.0 (distance 1.0 ≤ 1.5)
        × duration 1.0 (60 min/60) = 10.0 ≥ 5.0 → tier == CLOSE.
        """
        region, hospital, _cdc = setup_district_with_hospital_and_cdc(
            district_code="D-CT-3",
        )
        src = create_person(district_code=region["district_code"])
        tgt = create_person(district_code=region["district_code"])
        payload = create_contact_event_payload(
            source_person_id=src["id"],
            target_person_id=tgt["id"],
            event_type="HOUSEHOLD",
            duration_minutes=60,
            distance_meters=1.0,
        )
        resp = api.create_contact_event(
            payload, make_hospital_reporter_headers(hospital["id"]),
        )
        event = validate_success(resp, 201)
        assert_contact_event(event)
        assert event["tier"] == "CLOSE", (
            f"HOUSEHOLD raw weight = 10*1*1 = 10.0 ≥ 5.0; expected tier=CLOSE, "
            f"got tier={event['tier']}"
        )

    def test_transit_far_short_classified_sub_close(self, api):
        """PRD §3.3: "Proximity multiplies the weight by one if
        distance_meters is at most 1.5, and by one-half otherwise. ...
        The edge's tier is set to CLOSE when this raw weight is at
        least 5.0, and SUB_CLOSE otherwise."

        Claim: TRANSIT (base 2) × proximity 0.5 (distance > 1.5) ×
        duration 0.5 (30 min/60) = 0.5 < 5.0 → tier == SUB_CLOSE.
        """
        region, hospital, _cdc = setup_district_with_hospital_and_cdc(
            district_code="D-CT-4",
        )
        src = create_person(district_code=region["district_code"])
        tgt = create_person(district_code=region["district_code"])
        payload = create_contact_event_payload(
            source_person_id=src["id"],
            target_person_id=tgt["id"],
            event_type="TRANSIT",
            duration_minutes=30,
            distance_meters=3.0,
        )
        resp = api.create_contact_event(
            payload, make_hospital_reporter_headers(hospital["id"]),
        )
        event = validate_success(resp, 201)
        assert_contact_event(event)
        assert event["tier"] == "SUB_CLOSE", (
            f"TRANSIT raw weight = 2*0.5*0.5 = 0.5 < 5.0; expected "
            f"tier=SUB_CLOSE, got tier={event['tier']}"
        )


# ===========================================================================
# Tracing task lifecycle — PRD §3.3
# ===========================================================================
class TestTracingTaskLifecycle:

    def test_dispatch_transitions_case_to_under_tracing(self, api):
        """PRD §3.3: "Creating the tracing task ... transitions the
        underlying case from REPORTED to UNDER_TRACING, and appends an
        audit row."

        Claim: POST /epi/tracing-tasks moves Case.status from REPORTED
        to UNDER_TRACING and the new TracingTask is in DISPATCHED.
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-TT-1",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        task = dispatch_tracing_task(case_id=case["id"], cdc_id=cdc["id"])
        assert_tracing_task(task)
        assert task["status"] == "DISPATCHED"
        assert task["case_id"] == case["id"]
        assert task["assigned_cdc_id"] == cdc["id"]
        # Case advanced by side-effect.
        updated = validate_success(
            api.get_case(case["id"], make_hospital_reporter_headers(hospital["id"])),
        )
        assert updated["status"] == "UNDER_TRACING", (
            "PRD §3.3: case must move REPORTED -> UNDER_TRACING on dispatch"
        )

    def test_dispatch_for_suspected_case_rejected(self, api):
        """PRD §3.3: "this is permitted only when the source case is in
        REPORTED status with case_type in CONFIRMED or ASYMPTOMATIC
        (suspected cases trace only after a positive test moves them
        along the case lifecycle)."

        Claim: POST /epi/tracing-tasks for a SUSPECTED case is rejected
        with ERR_INVALID_STATE.
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-TT-2",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="SUSPECTED",
        )
        payload = {"case_id": case["id"], "assigned_cdc_id": cdc["id"]}
        resp = api.create_tracing_task(
            payload, make_cdc_dispatcher_headers(cdc["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_accept_dispatched_moves_to_in_progress(self, api):
        """PRD §3.3: "A field tracer accepts the task (DISPATCHED →
        IN_PROGRESS)."

        Claim: POST /epi/tracing-tasks/{id}/accept moves DISPATCHED →
        IN_PROGRESS.
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-TT-3",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        task = dispatch_tracing_task(case_id=case["id"], cdc_id=cdc["id"])
        accepted = accept_tracing_task(task["id"], cdc["id"])
        assert accepted["status"] == "IN_PROGRESS"

    def test_complete_with_zero_contacts_allowed(self, api):
        """PRD §3.3: "When the contact list is finalized —
        discovered_contact_count may be zero — the tracer marks the
        task complete (IN_PROGRESS → COMPLETED)."

        Claim: POST /epi/tracing-tasks/{id}/complete succeeds when no
        contact events were ingested; discovered_contact_count == 0.
        # difficulty: boundary_precision_check/tracing_complete_with_zero_contacts
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-TT-4",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        task = dispatch_tracing_task(case_id=case["id"], cdc_id=cdc["id"])
        accept_tracing_task(task["id"], cdc["id"])
        completed = complete_tracing_task(task["id"], cdc["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["discovered_contact_count"] == 0


# ===========================================================================
# SLA severity — PRD §3.3
# ===========================================================================
class TestSlaSeverity:

    def test_get_tracing_task_returns_persisted_fields(self, api):
        """PRD §3.3: "Each tracing task also exposes a computed SLA
        severity on read."

        Claim: GET /epi/tracing-tasks/{id} succeeds and returns the
        persisted task fields (id, status, case_id, assigned_cdc_id,
        due_at, dispatched_at). We do NOT assert a specific field name
        for SLA severity because the PRD does not pin the JSON key —
        only that it is "exposed on read."
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-SLA-1",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        task = dispatch_tracing_task(case_id=case["id"], cdc_id=cdc["id"])
        get_resp = api.get_tracing_task(
            task["id"], make_cdc_tracer_headers(cdc["id"]),
        )
        body = validate_success(get_resp, 200)
        assert body["id"] == task["id"]
        assert body["status"] == "DISPATCHED"
        assert body["case_id"] == case["id"]
