"""Cross-entity state gates on the EAS Compliance API.

Each test here exercises a write whose legality lives on a *different* row than
the one being written: a monitoring-assignment create gated on its device's
status, a filing gated on its station's derived posture, and a device
decommission gated on the status of its child assignments.

Every test builds its own plan / station / device / assignment graph, because
the harness restarts the server before each test and the logical clock starts
at its 2026-08-01T00:00:00Z default.
"""

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    OFFICER,
    ApiErrorId,
    add_silence_padding_assignments,
    api_client,
    assert_score_and_posture,
    assert_summary_inputs,
    create_active_plan,
    evaluate_readiness,
    filing_record_payload,
    flag_silence,
    get_success_data,
    monitoring_assignment_payload,
    readiness_check_payload,
    register_device,
    register_station,
    schedule_test_event,
    set_clock,
    setup_logged_test_event,
    setup_station,
    station_summary,
    station_version,
    test_event_version as current_event_version,
    validate_error,
    validate_paginated,
    validate_success,
)

# The review instant at which an assignment last heard from at
# 2026-08-01T00:00:00Z is eight days stale.
SUSPENDING_REVIEW_AT = "2026-08-13T00:00:00Z"


# ---------------------------------------------------------------------------
# Local setup built out of the shared primitives
# ---------------------------------------------------------------------------
def _plan_station_and_registered_device():
    """Active PEP plan + station + one device left in REGISTERED."""
    plan = create_active_plan(required_source_types=("PEP",))
    station = register_station(plan["id"])
    device = register_device(station["id"])
    return plan, station, device


def _attempt_pep_assignment(station_id, device_id):
    """Raw POST /monitoring-assignments response, version read immediately before."""
    payload = monitoring_assignment_payload(
        station_id, device_id, station_version(station_id), source_type="PEP"
    )
    return api_client.create_monitoring_assignment(payload, ENGINEER)


def _assignment_count(station_id):
    rows, meta = validate_paginated(
        api_client.list_monitoring_assignments(ADMIN, params={"station_id": station_id})
    )
    return meta["total_count"], rows


def _station_suspended_with_a_logged_test_event():
    """A station driven to SUSPENDED_FILINGS purely by the silence sweep, carrying a
    LOGGED test event whose filing deadline has not yet passed."""
    ctx = setup_station(required_source_types=("PEP",))
    ctx["padding_assignments"] = add_silence_padding_assignments(
        ctx, ("SATELLITE", "LP1", "LP2")
    )
    ctx = setup_logged_test_event(ctx)
    ctx["log_review"] = flag_silence(ctx, SUSPENDING_REVIEW_AT)
    return ctx


class TestAssignmentCreateGatedOnDeviceReadiness:
    def test_assignment_create_rejected_while_the_device_is_only_registered(self):
        """PRD §3.3: "The referenced unit must currently be in `READY`, otherwise the create is rejected with `ERR_DEVICE_NOT_READY`, and the unit's `station_id` must equal the `station_id` in the payload, otherwise `ERR_DEVICE_STATION_MISMATCH`."
        PRD §3.2: "A newly registered unit sits in `REGISTERED` with `readiness_check_passed` false and `last_readiness_check_at` null."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_requires_the_referenced_device_to_be_ready
        """
        _plan, station, device = _plan_station_and_registered_device()
        assert device["status"] == "REGISTERED"
        assert device["readiness_check_passed"] is False
        assert device["last_readiness_check_at"] is None

        validate_error(
            _attempt_pep_assignment(station["id"], device["id"]),
            ApiErrorId.ERR_DEVICE_NOT_READY,
            409,
        )

        total_count, _rows = _assignment_count(station["id"])
        assert total_count == 0, "a rejected create must not store a MonitoringAssignment"

    def test_half_passing_readiness_check_leaves_the_device_registered_and_the_create_rejected(self):
        """PRD §3.2: "On a unit in `REGISTERED` where either `self_test_passed` or `firmware_current` is false, the unit stays in `REGISTERED` — `REGISTERED` → `REGISTERED` — with `readiness_check_passed` set to false and `last_readiness_check_at` still stamped; the failed attempt is recorded, not discarded."
        PRD §3.3: "The referenced unit must currently be in `READY`, otherwise the create is rejected with `ERR_DEVICE_NOT_READY`, and the unit's `station_id` must equal the `station_id` in the payload, otherwise `ERR_DEVICE_STATION_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_requires_the_referenced_device_to_be_ready
        """
        _plan, station, device = _plan_station_and_registered_device()

        checked = get_success_data(
            api_client.readiness_check_device(
                device["id"],
                readiness_check_payload(self_test_passed=True, firmware_current=False),
                ENGINEER,
            )
        )
        assert checked["status"] == "REGISTERED", "one true flag does not earn READY"
        assert checked["readiness_check_passed"] is False
        assert checked["last_readiness_check_at"] is not None, (
            "the failed attempt is recorded, not discarded"
        )

        validate_error(
            _attempt_pep_assignment(station["id"], device["id"]),
            ApiErrorId.ERR_DEVICE_NOT_READY,
            409,
        )
        total_count, _rows = _assignment_count(station["id"])
        assert total_count == 0

    def test_assignment_create_succeeds_once_the_device_itself_reaches_ready(self):
        """PRD §3.2: "On a unit in `REGISTERED` where both are true, the unit advances `REGISTERED` → `READY`, `readiness_check_passed` is set to true, and `last_readiness_check_at` is stamped from the logical clock."
        PRD §3.3: "A successful create lands in `ACTIVE` with `last_receipt_at` and `silence_flagged_at` null, and sets `counts_toward_required_sources` to true exactly when the row's `status` is `ACTIVE` and its `source_type` appears in the governing plan's `required_source_types` — a row covering a source the plan does not require is stored and reported but never contributes coverage."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_requires_the_referenced_device_to_be_ready
        """
        _plan, station, device = _plan_station_and_registered_device()

        ready = get_success_data(
            api_client.readiness_check_device(
                device["id"],
                readiness_check_payload(self_test_passed=True, firmware_current=True),
                ENGINEER,
            )
        )
        assert ready["status"] == "READY"
        assert ready["readiness_check_passed"] is True

        assignment = validate_success(
            _attempt_pep_assignment(station["id"], device["id"]), 201
        )
        assert assignment["status"] == "ACTIVE"
        assert assignment["counts_toward_required_sources"] is True
        assert assignment["superseded_assignment_id"] is None

        summary = station_summary(station["id"])
        assert_summary_inputs(
            summary, accessible_source_count=1, missing_source_count=0
        )
        assert_score_and_posture(summary, 100.00, "COMPLIANT")


class TestFilingGatedOnStationPosture:
    def test_filing_rejected_while_the_station_posture_is_suspended_filings(self):
        """PRD §3.8: "Every monitoring assignment of the station whose `status` is `ACTIVE` and whose last evidence of life is strictly earlier than the current logical clock less eight days is pushed `ACTIVE` → `SILENT`, with `silence_flagged_at` stamped."
        PRD §3.8: "10.00 points for each assignment counted in `silent_assignment_count`;"
        PRD §3.7: "The owning station's `compliance_posture` must not be `SUSPENDED_FILINGS`, otherwise `ERR_FILINGS_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/filing_blocked_by_station_posture_then_allowed_after_posture_recovers
        """
        ctx = _station_suspended_with_a_logged_test_event()

        assert_score_and_posture(ctx["log_review"], 70.00, "SUSPENDED_FILINGS")
        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary,
            silent_assignment_count=3,
            accessible_source_count=1,
            missing_source_count=0,
        )

        covering = get_success_data(
            api_client.get_monitoring_assignment(
                ctx["assignments"]["PEP"]["id"], ADMIN
            )
        )
        assert covering["status"] == "ACTIVE", "the covering assignment heard a receipt"
        for padded in ctx["padding_assignments"]:
            row = get_success_data(
                api_client.get_monitoring_assignment(padded["id"], ADMIN)
            )
            assert row["status"] == "SILENT"
            assert row["silence_flagged_at"].startswith("2026-08-13T00:00:00")

        event_version = current_event_version(ctx["test_event_id"])
        validate_error(
            api_client.create_filing_record(
                filing_record_payload(ctx["test_event_id"], event_version), OFFICER
            ),
            ApiErrorId.ERR_FILINGS_SUSPENDED,
            422,
        )

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["status"] == "LOGGED", "a rejected filing does not advance the event"
        assert event["version"] == event_version

    def test_receipt_lifts_the_posture_and_the_same_filing_body_then_succeeds(self):
        """PRD §3.3: "On a row in `SILENT` it additionally moves the row `SILENT` → `ACTIVE` and clears `silence_flagged_at` back to null; on a row already in `ACTIVE` it leaves the status alone — `ACTIVE` → `ACTIVE` — and only refreshes `last_receipt_at`."
        PRD §3.7: "Lateness comes first: `late_days` is 0 when `filed_at` is at or before the event's `filing_deadline_at`, and otherwise the number of whole days obtained by dividing the elapsed time between `filing_deadline_at` and `filed_at` by 86400 seconds and rounding that quotient **up** to the next whole number — so any part of a day late counts as a full day late."
        PRD §2.7: "A successful filing increments the test event's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/filing_blocked_by_station_posture_then_allowed_after_posture_recovers
        """
        ctx = _station_suspended_with_a_logged_test_event()
        revived_id = ctx["padding_assignments"][0]["id"]

        revived = get_success_data(api_client.record_receipt(revived_id, ENGINEER))
        assert revived["status"] == "ACTIVE"
        assert revived["silence_flagged_at"] is None
        assert revived["last_receipt_at"].startswith("2026-08-13T00:00:00")

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(summary, silent_assignment_count=2)
        assert_score_and_posture(summary, 80.00, "WATCH")

        event_version = current_event_version(ctx["test_event_id"])
        filing = validate_success(
            api_client.create_filing_record(
                filing_record_payload(ctx["test_event_id"], event_version), OFFICER
            ),
            201,
        )
        assert filing["status"] == "SUBMITTED"
        assert filing["late_days"] == 0
        assert filing["entry_subtotal_points"] == pytest.approx(0.00, abs=0.01)
        assert filing["lateness_points"] == pytest.approx(0.00, abs=0.01)
        assert filing["unconfirmed_relay_points"] == pytest.approx(0.00, abs=0.01)
        assert filing["penalty_points"] == pytest.approx(0.00, abs=0.01)

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["status"] == "FILED"
        assert event["version"] == event_version + 1

        summary = station_summary(ctx["station_id"])
        assert summary["penalty_points_total"] == pytest.approx(0.00, abs=0.01)
        assert summary["compliance_variant_applied"] == "PROVISIONAL"
        assert_score_and_posture(summary, 80.00, "WATCH")


class TestDeviceDecommissionGatedOnLiveAssignments:
    def test_device_decommission_rejected_while_an_assignment_is_still_active(self):
        """PRD §3.2: "Two preconditions guard it: the unit must not already be `DECOMMISSIONED`, otherwise `ERR_DEVICE_DECOMMISSIONED`; and no monitoring assignment referencing the unit may be in `ACTIVE`, `SILENT` or `SUSPENDED`, otherwise `ERR_DEVICE_HAS_LIVE_ASSIGNMENTS`."

        Design: Difficulty/cross_entity_state_dependency/device_decommission_blocked_while_an_assignment_is_still_live
        """
        ctx = setup_station(required_source_types=("PEP",))
        assert ctx["assignments"]["PEP"]["status"] == "ACTIVE"

        validate_error(
            api_client.decommission_device(ctx["device_id"], ADMIN),
            ApiErrorId.ERR_DEVICE_HAS_LIVE_ASSIGNMENTS,
            409,
        )

        device = get_success_data(api_client.get_device(ctx["device_id"], ADMIN))
        assert device["status"] == "READY", "the rejected decommission left the unit in service"

    def test_device_decommission_succeeds_once_the_assignment_is_decommissioned(self):
        """PRD §3.3: "Deliberate retirement of an assignment by a `StationEngineer` is permitted from three starting statuses with identical effect — `ACTIVE` → `DECOMMISSIONED`, `SILENT` → `DECOMMISSIONED` and `SUSPENDED` → `DECOMMISSIONED` — each recomputing the station's `accessible_source_count` and firing a station recompute event; attempting it on a row already in `DECOMMISSIONED` is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE`."
        PRD §3.2: "Retiring equipment permanently is reserved for a `ComplianceAdmin` and is possible from three starting statuses with identical effect: `REGISTERED` → `DECOMMISSIONED`, `READY` → `DECOMMISSIONED` and `FAILED` → `DECOMMISSIONED`."
        PRD §3.8: "25.00 points for every required source type the station is missing, where the missing count is the plan's `required_source_count` less the station's `accessible_source_count`, floored at zero so that over-coverage never earns a credit;"

        Design: Difficulty/cross_entity_state_dependency/device_decommission_blocked_while_an_assignment_is_still_live
        """
        ctx = setup_station(required_source_types=("PEP",))
        assignment_id = ctx["assignments"]["PEP"]["id"]

        retired = get_success_data(
            api_client.decommission_assignment(assignment_id, ENGINEER)
        )
        assert retired["status"] == "DECOMMISSIONED"
        assert retired["counts_toward_required_sources"] is False

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary, accessible_source_count=0, missing_source_count=1
        )
        assert_score_and_posture(summary, 75.00, "WATCH")

        device = validate_success(
            api_client.decommission_device(ctx["device_id"], ADMIN), 200
        )
        assert device["status"] == "DECOMMISSIONED"

        still_there = get_success_data(
            api_client.get_monitoring_assignment(assignment_id, ADMIN)
        )
        assert still_there["device_id"] == ctx["device_id"], (
            "the assignment row survives and still references the retired unit"
        )

    def test_decommissioned_unit_leaves_the_readiness_denominator(self):
        """PRD §3.2: "Decommissioning has one lasting consequence for scoring: a `DECOMMISSIONED` unit leaves the readiness denominator described in §3.6 entirely, whereas units in `REGISTERED`, `READY` and `FAILED` all remain counted there."
        PRD §3.6: "The **device ratio** is the number of the station's units in `READY` divided by the number of the station's countable units, where countable means units whose `status` is `REGISTERED`, `READY` or `FAILED`; `DECOMMISSIONED` units leave the denominator entirely, and the denominator is treated as 1 whenever the countable count is 0, so a station with no equipment scores a device ratio of 0 rather than failing to compute."

        Design: Difficulty/cross_entity_state_dependency/device_decommission_blocked_while_an_assignment_is_still_live
        """
        ctx = setup_station(required_source_types=("PEP",))
        get_success_data(
            api_client.decommission_assignment(ctx["assignments"]["PEP"]["id"], ENGINEER)
        )
        device = get_success_data(api_client.decommission_device(ctx["device_id"], ADMIN))
        assert device["status"] == "DECOMMISSIONED"

        event = schedule_test_event(ctx["station_id"])
        set_clock("2026-08-12T00:30:00Z")
        evaluated = evaluate_readiness(event["id"])

        assert evaluated["readiness_score"] == pytest.approx(0.00, abs=0.01), (
            "no countable unit remains, so the device ratio is 0 rather than 1"
        )
        assert evaluated["status"] == "READINESS_PENDING"
