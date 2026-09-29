"""PSPS event endpoints: opening, scoping, arming, execution, restoration, close."""

from flask import Blueprint

import db
import validation as v
from errors import ApiError
from middleware import (
    ALL_ROLES,
    COMMUNITY_LIAISON,
    GRID_PLANNER,
    METEOROLOGY_ANALYST,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
    roles,
)
from response import object_response
from services import calc, centers, events, notifications

bp = Blueprint("events", __name__)

SCOPE_STATUSES = (
    "DRAFT",
    "SCOPED",
    "ARMED",
    "ACTIVE",
    "RESTORING",
    "CLOSED",
    "CANCELLED",
)
NOTIFICATION_STATUSES = (
    "NOT_STARTED",
    "ADVANCE_SENT",
    "IMMINENT_SENT",
    "ACTIVATION_SENT",
    "RESTORATION_SENT",
)
BATCH_STAGES = ("ADVANCE_48H", "ADVANCE_24H", "IMMINENT_1H", "ACTIVATION", "RESTORATION")
BATCH_STATUSES = ("PENDING", "DISPATCHED", "FAILED_PARTIAL")
CENTER_STATUSES = ("STANDBY", "ACTIVATED", "DEMOBILIZED")

CENTER_READ_ROLES = (
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    COMMUNITY_LIAISON,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
)


def _require_state(event, allowed, error_id, note):
    """Own-state guard (priority 8); a terminal event always answers TERMINAL."""
    events.assert_not_terminal(event)
    if event["scope_status"] not in allowed:
        raise ApiError(error_id, "%s (the event is %s)." % (note, event["scope_status"]))


# ------------------------------------------------------------------- lifecycle
@bp.post("/psps-events")
@roles(PSPS_DUTY_OFFICER)
def create_event():
    body = v.Body()
    event_code = body.string("event_code", 3, 40)
    trigger_id = body.string("trigger_fire_potential_index_id", 1, None)
    onset, onset_raw = body.timestamp("forecast_onset_at")
    all_clear, all_clear_raw = body.timestamp("forecast_all_clear_at")

    index = v.fire_potential_index(trigger_id)

    if all_clear <= onset:
        raise ApiError(
            "ERR_EVENT_WINDOW_INVALID",
            "forecast_all_clear_at must be strictly later than forecast_onset_at.",
        )

    v.unique_code(db.psps_events, "event_code", event_code)

    row = db.new_row()
    row["event_code"] = event_code
    row["trigger_fire_potential_index_id"] = index["id"]
    db.set_dt(row, "forecast_onset_at", onset, onset_raw)
    db.set_dt(row, "forecast_all_clear_at", all_clear, all_clear_raw)
    events.new_event_defaults(row)
    db.psps_events[row["id"]] = row
    return object_response(db.psps_event_out(row), 201)


@bp.get("/psps-events")
@roles(*ALL_ROLES)
def list_events():
    scope_status = v.query_enum("scope_status", SCOPE_STATUSES)
    notification_status = v.query_enum("notification_status", NOTIFICATION_STATUSES)
    trigger_id = v.query_string("trigger_fire_potential_index_id")

    rows = db.in_order(db.psps_events.values())
    if scope_status is not None:
        rows = [r for r in rows if r["scope_status"] == scope_status]
    if notification_status is not None:
        rows = [r for r in rows if r["notification_status"] == notification_status]
    if trigger_id is not None:
        rows = [r for r in rows if r["trigger_fire_potential_index_id"] == trigger_id]
    return v.paged(rows, db.psps_event_out)


@bp.get("/psps-events/<event_id>")
@roles(*ALL_ROLES)
def get_event(event_id):
    return object_response(db.psps_event_out(v.psps_event(event_id)))


@bp.post("/psps-events/<event_id>/scope")
@roles(PSPS_DUTY_OFFICER)
def scope_event(event_id):
    event = v.psps_event(event_id)
    body = v.Body()
    expected = body.integer("expected_psps_event_version")

    # Priority 7 - the parent version guard.
    if expected != event["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_psps_event_version %s does not match the stored version %s."
            % (expected, event["version"]),
        )

    _require_state(
        event,
        ("DRAFT", "SCOPED"),
        "ERR_EVENT_NOT_SCOPED",
        "Scope determination runs only from DRAFT or SCOPED",
    )

    events.determine_scope(event)
    return object_response(db.psps_event_out(event))


@bp.get("/psps-events/<event_id>/scopes")
@roles(*ALL_ROLES)
def list_event_scopes(event_id):
    event = v.psps_event(event_id)
    scope_status = v.query_enum("scope_status", ("CONFIRMED", "EXCLUDED"))
    rows = events.scopes_of(event)
    if scope_status is not None:
        rows = [r for r in rows if r["scope_status"] == scope_status]
    return v.paged(rows, db.event_scope_out)


@bp.post("/event-scopes/<scope_id>/exclude")
@roles(TRANSMISSION_ENGINEER)
def exclude_scope(scope_id):
    scope = v.event_scope(scope_id)
    body = v.Body()
    justification = body.string("exclusion_justification", 1, None)

    # Priority 8 - the scope row's own state.
    if scope["scope_status"] == "EXCLUDED":
        raise ApiError(
            "ERR_SCOPE_ALREADY_EXCLUDED",
            "The scope row is already EXCLUDED.",
        )

    event = db.psps_events.get(scope["psps_event_id"])

    # Priority 9 - the parent event must still be SCOPED or ARMED.
    if event is None or event["scope_status"] not in ("SCOPED", "ARMED"):
        raise ApiError(
            "ERR_EVENT_NOT_SCOPED",
            "Exclusion is admitted only while the event is SCOPED or ARMED.",
        )

    scope["scope_status"] = "EXCLUDED"
    scope["exclusion_justification"] = justification
    scope["ignition_risk_term"] = calc.D("0.00")
    db.touch(scope)

    circuit = db.circuits.get(scope["circuit_id"])
    if circuit is not None and circuit["energization_state"] == "DE_ENERGIZATION_PENDING":
        circuit["energization_state"] = "ENERGIZED"
        calc.recompute_risk_posture(circuit)
        db.touch(circuit)

    events.refresh_event_metrics(event)
    db.touch(event)
    return object_response(db.event_scope_out(scope))


@bp.post("/psps-events/<event_id>/arm")
@roles(PSPS_DUTY_OFFICER)
def arm_event(event_id):
    event = v.psps_event(event_id)
    _require_state(
        event, ("SCOPED",), "ERR_EVENT_NOT_SCOPED", "Arming runs only from SCOPED"
    )

    # Priority 11 - the advance-notification gate.
    notifications.assert_advance_notification(event)

    # Priority 14 - at least one CONFIRMED scope row.
    if int(event["confirmed_scope_count"]) < 1:
        raise ApiError(
            "ERR_NO_CIRCUITS_IN_SCOPE", "The event holds no CONFIRMED scope row."
        )

    # Priority 17 - the net-benefit threshold.
    if calc.D(event["net_benefit_ratio"]) < calc.MIN_NET_BENEFIT_RATIO:
        raise ApiError(
            "ERR_NET_BENEFIT_BELOW_THRESHOLD",
            "net_benefit_ratio %s is below the 0.25 arming threshold."
            % event["net_benefit_ratio"],
        )

    events.arm(event)
    return object_response(db.psps_event_out(event))


@bp.post("/psps-events/<event_id>/de-energize")
@roles(PSPS_DUTY_OFFICER)
def de_energize_event(event_id):
    event = v.psps_event(event_id)
    _require_state(
        event, ("ARMED",), "ERR_EVENT_NOT_ARMED", "De-energization runs only from ARMED"
    )

    # Priority 11 - the critical-customer notification gate.
    notifications.assert_critical_notification(event)

    events.de_energize(event)
    return object_response(db.psps_event_out(event))


@bp.post("/psps-events/<event_id>/all-clear")
@roles(METEOROLOGY_ANALYST)
def all_clear_event(event_id):
    event = v.psps_event(event_id)
    _require_state(
        event, ("ACTIVE",), "ERR_EVENT_NOT_ACTIVE", "All-clear runs only from ACTIVE"
    )
    events.all_clear(event)
    return object_response(db.psps_event_out(event))


@bp.post("/psps-events/<event_id>/close")
@roles(PSPS_DUTY_OFFICER)
def close_event(event_id):
    event = v.psps_event(event_id)
    _require_state(
        event,
        ("RESTORING",),
        "ERR_EVENT_NOT_IN_RESTORATION",
        "Closing runs only from RESTORING",
    )

    # Priority 10 - every CONFIRMED scope row must already carry a restored_at.
    outstanding = [
        s for s in events.confirmed_scopes(event) if s.get("restored_at") is None
    ]
    if outstanding or event.get("actual_restored_at") is None:
        raise ApiError(
            "ERR_PATROL_NOT_COMPLETED",
            "Not every CONFIRMED scope row of the event has been restored.",
        )

    events.close(event)
    return object_response(db.psps_event_out(event))


@bp.post("/psps-events/<event_id>/cancel")
@roles(PSPS_DUTY_OFFICER)
def cancel_event(event_id):
    event = v.psps_event(event_id)
    body = v.Body()
    reason = body.string("cancellation_reason", 1, None)

    _require_state(
        event,
        ("DRAFT", "SCOPED", "ARMED"),
        "ERR_EVENT_NOT_CANCELLABLE",
        "Cancellation is available only before the breakers open",
    )

    events.cancel(event, reason)
    return object_response(db.psps_event_out(event))


# ------------------------------------------------------------ resource centers
@bp.post("/psps-events/<event_id>/activate-resource-centers")
@roles(PSPS_DUTY_OFFICER)
def activate_resource_centers(event_id):
    event = v.psps_event(event_id)
    body = v.Body()
    requested_ids = body.string_list("requested_resource_center_ids")

    # Priority 6 - every named site resolves, left to right.
    if requested_ids is not None:
        for center_id in requested_ids:
            v.resource_center(center_id)

    events.assert_not_terminal(event)

    summary = centers.activate(event, requested_ids)
    return object_response(summary)


@bp.get("/psps-events/<event_id>/resource-centers")
@roles(*CENTER_READ_ROLES)
def list_event_centers(event_id):
    event = v.psps_event(event_id)
    status = v.query_enum("status", CENTER_STATUSES)
    rows = events.centers_of(event)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return v.paged(rows, db.resource_center_out)


@bp.get("/psps-events/<event_id>/notification-batches")
@roles(*CENTER_READ_ROLES)
def list_event_batches(event_id):
    event = v.psps_event(event_id)
    stage = v.query_enum("stage", BATCH_STAGES)
    status = v.query_enum("status", BATCH_STATUSES)
    rows = events.batches_of(event)
    if stage is not None:
        rows = [r for r in rows if r["stage"] == stage]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return v.paged(rows, db.notification_batch_out)
