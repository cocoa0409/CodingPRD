"""Alert response workflow tests (PRD §3.7).

Difficulty-design instances exercised:
- # difficulty: cross_entity_state_dependency/alert_resolve_requires_task_not_terminal
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    DISP,
    TaskParties,
    advance_clock,
    advance_clock_to,
    abort_payload,
    assert_response_action,
    get_clock_now,
    ingest_reading,
    open_alert_via_reading,
    parse_iso,
    response_action_payload,
    setup_in_transit_task,
    validate_error,
    validate_success,
    walk_alert_to_resolved,
)


# ===========================================================================
# Acknowledge / response / resolve happy paths
# ===========================================================================
def test_acknowledge_open_alert_moves_to_acknowledged(api):
    """PRD §3.7: 'A DRIVER or DISPATCHER acknowledges an alert, moving
    it from OPEN to ACKNOWLEDGED.'"""
    scenario = setup_in_transit_task(temp_max_celsius=8.00)
    alert = open_alert_via_reading(scenario=scenario, breach_temp=20.00)
    ack = validate_success(api.acknowledge_alert(alert["id"], DISP))
    assert ack["status"] == "ACKNOWLEDGED"


def test_response_advances_to_in_response(api):
    """PRD §3.7: 'Recording a first ResponseAction advances the alert
    from ACKNOWLEDGED to IN_RESPONSE.'"""
    scenario = setup_in_transit_task(temp_max_celsius=8.00)
    alert = open_alert_via_reading(scenario=scenario, breach_temp=20.00)
    validate_success(api.acknowledge_alert(alert["id"], DISP))
    resp_action = validate_success(
        api.respond_alert(alert["id"],
                          response_action_payload("VENTILATION"), DISP),
        expected_status=201,
    )
    assert_response_action(resp_action)
    refreshed = validate_success(api.get_alert(alert["id"], DISP))
    assert refreshed["status"] == "IN_RESPONSE"


def test_escalate_in_response_alert(api):
    """PRD §3.7: 'A DISPATCHER may escalate an IN_RESPONSE alert,
    advancing it to ESCALATED. Escalation expands notified_channels to
    include CUSTOMER.'"""
    scenario = setup_in_transit_task(temp_max_celsius=8.00)
    alert = open_alert_via_reading(scenario=scenario, breach_temp=9.00)
    validate_success(api.acknowledge_alert(alert["id"], DISP))
    validate_success(
        api.respond_alert(alert["id"],
                          response_action_payload("VENTILATION"), DISP),
        expected_status=201,
    )
    escalated = validate_success(api.escalate_alert(alert["id"], DISP))
    assert escalated["status"] == "ESCALATED"
    assert "CUSTOMER" in escalated["notified_channels"]


def test_resolve_requires_at_least_one_response_action(api):
    """PRD §3.7: 'at least one ResponseAction must already exist on the
    alert.'"""
    scenario = setup_in_transit_task(temp_max_celsius=8.00)
    alert = open_alert_via_reading(scenario=scenario, breach_temp=9.00)
    validate_success(api.acknowledge_alert(alert["id"], DISP))
    # Attempt to resolve without recording a ResponseAction first.
    resp = api.resolve_alert(alert["id"], DISP)
    # State check would say IN_RESPONSE/ESCALATED required, so
    # ERR_INVALID_STATE is plausible from priority 5; priority 7 is the
    # cross-entity check, not this one. PRD does not pin a unique
    # error_id for this fail mode beyond status preconditions failing.
    assert resp.status_code >= 400


def test_resolve_sets_resolved_at_and_finalizes_duration(api):
    """PRD §3.7: 'As a side effect the server sets resolved_at to the
    current clock, finalises duration_seconds as resolved_at minus
    opened_at, runs the final level recomputation.'"""
    scenario = setup_in_transit_task(temp_max_celsius=8.00)
    alert = open_alert_via_reading(scenario=scenario, breach_temp=9.00)
    # Hold violation a bit so duration is non-zero.
    advance_clock(120)
    resolved = walk_alert_to_resolved(alert_id=alert["id"],
                                      scenario=scenario)
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] is not None
    assert resolved["duration_seconds"] >= 0


# ===========================================================================
# Cross-entity: alert resolve gated on parent task state — difficulty
# ===========================================================================
def test_resolve_rejected_when_parent_task_aborted(api):
    """PRD §3.7: 'the parent task must be in IN_TRANSIT, AT_STOP, or
    DELIVERED and not in CLOSED or ABORTED (the cross-entity rule,
    reported as ERR_TASK_NOT_RESOLVABLE when violated).'

    # difficulty: cross_entity_state_dependency/alert_resolve_requires_task_not_terminal
    """
    scenario = setup_in_transit_task(temp_max_celsius=8.00)
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    alert = open_alert_via_reading(scenario=scenario, breach_temp=9.00)
    # Acknowledge + record a response so alert is in IN_RESPONSE.
    validate_success(api.acknowledge_alert(alert["id"], DISP))
    validate_success(
        api.respond_alert(alert["id"],
                          response_action_payload("VENTILATION"), DISP),
        expected_status=201,
    )
    # Abort the parent task -> ABORTED (terminal).
    from test_helpers import make_dispatcher_headers
    aborted = validate_success(
        api.abort_task(task["id"], abort_payload(), make_dispatcher_headers())
    )
    assert aborted["status"] == "ABORTED"
    # Now try to resolve the alert.
    resp = api.resolve_alert(alert["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_TASK_NOT_RESOLVABLE.value)
    # And the alert must remain IN_RESPONSE.
    refreshed = validate_success(api.get_alert(alert["id"], DISP))
    assert refreshed["status"] == "IN_RESPONSE", (
        "PRD §3.7: rejected resolve must NOT advance status"
    )


def test_resolve_allowed_when_parent_task_in_transit(api):
    """PRD §3.7: 'the parent task must be in IN_TRANSIT, AT_STOP, or
    DELIVERED and not in CLOSED or ABORTED'.

    Positive-side companion to the ABORTED rejection: while the parent
    task is IN_TRANSIT, the resolve transition is permitted. Closes the
    'permitted set' branch of the cross-entity rule.

    # difficulty: cross_entity_state_dependency/alert_resolve_requires_task_not_terminal
    """
    scenario = setup_in_transit_task(temp_max_celsius=8.00)
    alert = open_alert_via_reading(scenario=scenario, breach_temp=9.00)
    resolved = walk_alert_to_resolved(alert_id=alert["id"],
                                      scenario=scenario)
    assert resolved["status"] == "RESOLVED"
