"""Patrol planning, execution, and segregation-of-duties (PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    FIELD_OPERATOR_ID,
    OM_ENGINEER_ID,
    create_patrol_plan,
    create_patrol_plan_payload,
    log_zone_payload,
    make_field_operator_headers,
    make_om_engineer_headers,
    reject_patrol_payload,
    schedule_patrol,
    schedule_patrol_payload,
    setup_station_with_inverters,
    setup_submitted_patrol,
    validate_error,
    validate_success,
)


class TestPatrolScheduleAndStart:
    """PRD §3.4 schedule + start lifecycle."""

    def test_schedule_produces_scheduled_record(self, api, om_headers):
        """PRD §3.4: "Scheduling a patrol on an active plan accepts a
        scheduled_for instant and produces a PatrolRecord carrying the
        parent patrol_plan_id, the station_id denormalized from the
        plan, state = SCHEDULED, an empty zone_progress, and
        completed_zone_count = 0."

        Claim: schedule returns a PatrolRecord with state=SCHEDULED
        and completed_zone_count=0.
        """
        station, _supp, _invs = setup_station_with_inverters(inverter_count=1)
        plan = create_patrol_plan(station["id"])
        resp = api.schedule_patrol(
            plan["id"], schedule_patrol_payload(), om_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["state"] == "SCHEDULED"
        assert data["completed_zone_count"] == 0
        assert data["patrol_plan_id"] == plan["id"]

    def test_start_records_actor_id(self, api):
        """PRD §3.4: "A FieldOperator starts the patrol; the
        operator's X-User-ID is recorded as the record's actor_id and
        the state moves to IN_PROGRESS."

        Claim: starting the patrol persists actor_id from the caller's
        X-User-ID and transitions to IN_PROGRESS.
        """
        station, _supp, _invs = setup_station_with_inverters(inverter_count=1)
        plan = create_patrol_plan(station["id"])
        record = schedule_patrol(plan["id"])
        operator_headers = make_field_operator_headers("operator-alpha")
        resp = api.start_patrol(record["id"], operator_headers)
        data = validate_success(resp)
        assert data["state"] == "IN_PROGRESS"
        assert data["actor_id"] == "operator-alpha"


class TestPatrolSubmissionGate:
    """PRD §3.4: completed_zone_count must equal len(zone_route)."""

    def test_submit_before_all_zones_logged_fails(self, api):
        """PRD §3.4: "Submission is permitted only when
        completed_zone_count equals the length of the plan's
        zone_route — every zone in the route must be fully logged —
        and moves the record from IN_PROGRESS to SUBMITTED."

        Claim: submitting before all zones are logged is rejected
        with ERR_INVALID_STATE.
        """
        station, _supp, _invs = setup_station_with_inverters(inverter_count=1)
        plan = create_patrol_plan(
            station["id"], zone_route=["Z1", "Z2"],
        )
        record = schedule_patrol(plan["id"])
        op_headers = make_field_operator_headers("op-1")
        api.start_patrol(record["id"], op_headers)
        # Log only ONE of two zones.
        api.log_patrol_zone(
            record["id"], "Z1",
            log_zone_payload(),
            op_headers,
        )
        resp = api.submit_patrol(record["id"], op_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestPatrolSoD:
    """PRD §3.4 segregation-of-duties gate on verify/reject."""

    def test_verify_by_same_actor_rejected(self, api):
        """PRD §3.4: "Both are performed by an O&MEngineer, and both
        compare the verifier's X-User-ID to the record's actor_id;
        the two MUST differ, or the request is rejected with
        ERR_SOD_VIOLATION (HTTP 403)."

        Claim: when the verifier's X-User-ID equals the record's
        actor_id, verify is rejected with ERR_SOD_VIOLATION.

        We pass the operator id under the O&MEngineer role to drive
        the equality.
        """
        operator_id = "op-conflicting"
        station, plan, submitted = setup_submitted_patrol(
            operator_id=operator_id,
        )
        # Verifier role = O&MEngineer, but using the same X-User-ID.
        same_id_om_headers = make_om_engineer_headers(operator_id)
        resp = api.verify_patrol(submitted["id"], same_id_om_headers)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)

    def test_reject_by_same_actor_rejected(self, api):
        """PRD §3.4: "The segregation-of-duties check applies to both
        verification and rejection — an operator cannot reject their
        own submission to avoid being verified."

        Claim: reject by the same X-User-ID as actor_id →
        ERR_SOD_VIOLATION.
        """
        operator_id = "op-conflicting-2"
        station, plan, submitted = setup_submitted_patrol(
            operator_id=operator_id,
        )
        same_id_om_headers = make_om_engineer_headers(operator_id)
        resp = api.reject_patrol(
            submitted["id"], reject_patrol_payload(notes="bad"),
            same_id_om_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)

    def test_verify_by_distinct_actor_succeeds(self, api):
        """PRD §3.4: "Verification moves the record from SUBMITTED to
        VERIFIED..."

        Claim: verify by a different X-User-ID succeeds; record
        state moves to VERIFIED.
        """
        operator_id = "op-verify-distinct"
        station, plan, submitted = setup_submitted_patrol(
            operator_id=operator_id,
        )
        # Distinct verifier — uses the shared O&MEngineer constant.
        from test_helpers import TEST_USERS
        verifier_headers = TEST_USERS["om_engineer_headers"]
        # Sanity: the verifier's id must differ from actor_id.
        assert verifier_headers["X-User-ID"] != operator_id
        resp = api.verify_patrol(submitted["id"], verifier_headers)
        data = validate_success(resp)
        assert data["state"] == "VERIFIED"


class TestPatrolKindAndCadence:
    """PRD §3.4: cadence_days required for PERIODIC, must be null for
    SPECIAL_POST_STORM."""

    def test_periodic_without_cadence_rejected(self, api, om_headers):
        """PRD §3.4: "a cadence_days integer between 1 and 180 that is
        required when kind is PERIODIC and must be null when kind is
        SPECIAL_POST_STORM."

        Claim: kind=PERIODIC and cadence_days=None → ERR_VALIDATION.
        """
        station, _supp, _invs = setup_station_with_inverters(inverter_count=1)
        payload = create_patrol_plan_payload(kind="PERIODIC")
        payload["cadence_days"] = None  # force null on PERIODIC
        resp = api.create_patrol_plan(station["id"], payload, om_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
