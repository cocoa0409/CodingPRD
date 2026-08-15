"""Safety alert tests: pipeline, deadlines, reopen window, segregation (PRD §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_geography, create_draft_incident, create_submitted_incident,
    create_pending_alert, create_decided_alert, create_authorized_alert,
    create_decision_payload, set_clock,
    ApiErrorId, assert_safety_alert, TEST_USERS,
)

CHIEF = TEST_USERS["chief_headers"]
COORD = TEST_USERS["coordinator_headers"]


def test_alert_create_requires_incident_not_draft(api):
    """PRD §3.6: "Creation requires the parent incident to be in `SUBMITTED`,
    `UNDER_CLASSIFICATION`, `CLASSIFIED`, or `UNDER_RECLASSIFICATION`; an
    incident still `DRAFT`, or already `UNFOUNDED` or `WITHDRAWN`, cannot spawn
    an alert and yields `ERR_INVALID_STATE`."
    PRD §3.6: "The decision deadline `decision_deadline_at` is fixed at the
    incident's `reported_at` plus 48 hours".

    Design: Difficulty/cross_entity_state_dependency/alert_create_requires_incident_not_draft
    """
    geography = create_geography(name="North Gate", category="PUBLIC_PROPERTY")
    incident = create_draft_incident(
        geography["id"], reported_at="2026-05-05T09:00:00Z",
        occurred_at="2026-05-05T08:00:00Z",
    )
    res = api.create_safety_alert(incident["id"], {"alert_type": "EMERGENCY_NOTIFICATION"}, COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    validate_success(api.submit_incident(incident["id"], CHIEF), 200)
    alert = validate_success(api.create_safety_alert(
        incident["id"], {"alert_type": "EMERGENCY_NOTIFICATION"}, COORD
    ), 201)
    assert_safety_alert(alert)
    assert alert["status"] == "PENDING_REVIEW"
    assert alert["decision_deadline_at"] == "2026-05-07T09:00:00Z", (
        "decision_deadline_at = reported_at + 48h"
    )


def test_alert_create_blocked_when_incident_unfounded(api):
    """PRD §3.6: "Creation requires the parent incident to be in `SUBMITTED`,
    `UNDER_CLASSIFICATION`, `CLASSIFIED`, or `UNDER_RECLASSIFICATION`; an
    incident still `DRAFT`, or already `UNFOUNDED` or `WITHDRAWN`, cannot spawn
    an alert and yields `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/alert_create_requires_incident_not_draft
    """
    geography = create_geography(name="North Gate East", category="PUBLIC_PROPERTY")
    incident = create_draft_incident(
        geography["id"], reported_at="2026-05-06T09:00:00Z",
        occurred_at="2026-05-06T08:00:00Z",
    )
    validate_success(api.withdraw_incident(incident["id"], COORD), 200)
    res = api.create_safety_alert(incident["id"], {"alert_type": "TIMELY_WARNING"}, COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_close_pending_alert_returns_invalid_state(api):
    """PRD §3.6: "Either terminal branch of the decision — disseminated, or
    decided not to issue — is closed by a coordinator, moving
    `DISSEMINATED → CLOSED` or `DECIDED_NO_ISSUE → CLOSED` and stamping
    `closed_at`."

    Design: Corner/state_machines/close_pending_alert_returns_invalid_state
    """
    geography = create_geography(name="Ave", category="PUBLIC_PROPERTY")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-04-04T09:00:00Z",
        occurred_at="2026-04-04T08:00:00Z",
    )
    alert = create_pending_alert(incident, alert_type="TIMELY_WARNING")

    res = api.close_alert(alert["id"], COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    after = validate_success(api.get_safety_alert(alert["id"], COORD), 200)
    assert after["status"] == "PENDING_REVIEW"


def test_duplicate_active_alert_rejected(api):
    """PRD §3.6: "At most one alert per incident may exist in a non-`CLOSED`
    status at any time; opening a second live alert is rejected with
    `ERR_DUPLICATE_ACTIVE_ALERT` (HTTP 409)."

    Design: Corner/validations/duplicate_active_alert_rejected
    """
    geography = create_geography(name="W", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-04-08T09:00:00Z",
        occurred_at="2026-04-08T08:00:00Z",
    )
    create_pending_alert(incident, alert_type="TIMELY_WARNING")

    res = api.create_safety_alert(incident["id"], {"alert_type": "EMERGENCY_NOTIFICATION"}, COORD)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_ALERT.value, expected_status=409)


def test_decision_at_exactly_48h_not_overdue(api):
    """PRD §3.6: "`decision_overdue` is true when `decided_at` is strictly
    later than that deadline — deciding exactly at the 48-hour mark is on
    time."
    PRD §3.6: "The decision deadline `decision_deadline_at` is fixed at the
    incident's `reported_at` plus 48 hours".

    Design: Difficulty/boundary_precision_check/decision_at_exactly_48h_not_overdue
    """
    geography = create_geography(name="Central Green", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-08-01T00:00:00Z",
        occurred_at="2026-07-31T20:00:00Z",
    )
    alert = create_pending_alert(incident, alert_type="TIMELY_WARNING")

    # Exactly reported_at + 48h.
    set_clock("2026-08-03T00:00:00Z")
    decided = validate_success(api.decide_alert(
        alert["id"],
        {"decision": "ISSUE", "decision_rationale": "Serious continuing threat"},
        COORD,
    ), 200)
    assert decided["decision_overdue"] is False, (
        "Exactly at the 48h deadline is on time (rule is strictly greater-than)"
    )
    assert decided["decided_at"] == "2026-08-03T00:00:00Z"
    assert decided["decision_deadline_at"] == "2026-08-03T00:00:00Z"


def test_decision_one_second_before_48h_not_overdue(api):
    """PRD §3.6: "`decision_overdue` is true when `decided_at` is strictly
    later than that deadline — deciding exactly at the 48-hour mark is on
    time."

    Design: Difficulty/boundary_precision_check/decision_at_exactly_48h_not_overdue
    """
    geography = create_geography(name="Central Green West", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-08-01T00:00:00Z",
        occurred_at="2026-07-31T21:00:00Z",
    )
    alert = create_pending_alert(incident, alert_type="TIMELY_WARNING")

    # One second before the deadline.
    set_clock("2026-08-02T23:59:59Z")
    decided = validate_success(api.decide_alert(
        alert["id"],
        {"decision": "NO_ISSUE", "decision_rationale": "No continuing threat"},
        COORD,
    ), 200)
    assert decided["decision_overdue"] is False, (
        "47h59m59s < 48h must be on time"
    )


def test_warning_decision_overdue_one_second_past_deadline(api):
    """PRD §3.6: "`decision_overdue` is true when `decided_at` is strictly
    later than that deadline — deciding exactly at the 48-hour mark is on
    time."

    Design: Corner/calculations/warning_decision_overdue_one_second_past_deadline
    """
    geography = create_geography(name="Row", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-08-01T00:00:00Z",
        occurred_at="2026-07-31T22:00:00Z",
    )
    alert = create_pending_alert(incident, alert_type="TIMELY_WARNING")

    set_clock("2026-08-03T00:00:01Z")
    decided = validate_success(api.decide_alert(
        alert["id"],
        {"decision": "ISSUE", "decision_rationale": "threat"},
        COORD,
    ), 200)
    assert decided["decision_overdue"] is True, (
        "48h00m01s is strictly past the 48h deadline"
    )


def test_dissemination_overdue_one_second_past_24h(api):
    """PRD §3.6: "The chief disseminates via a non-empty `distribution_channels`
    set, moving `AUTHORIZED → DISSEMINATED`, stamping `disseminated_at`, and
    computing `dissemination_overdue`, true when dissemination happened
    strictly after the dissemination deadline."

    Design: Corner/calculations/dissemination_overdue_one_second_past_24h
    """
    geography = create_geography(name="Blvd", category="PUBLIC_PROPERTY")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-07-30T00:00:00Z",
        occurred_at="2026-07-29T22:00:00Z",
    )
    # Authorize at the default clock 2026-08-01T00:00:00Z.
    alert = create_authorized_alert(incident, alert_type="EMERGENCY_NOTIFICATION")
    assert alert["dissemination_deadline_at"] == "2026-08-02T00:00:00Z"

    # One second past authorized_at + 24h.
    set_clock("2026-08-02T00:00:01Z")
    disseminated = validate_success(api.disseminate_alert(
        alert["id"], {"distribution_channels": ["SIREN", "SMS"]}, CHIEF
    ), 200)
    assert disseminated["status"] == "DISSEMINATED"
    assert disseminated["dissemination_overdue"] is True, (
        "24h00m01s is strictly past the 24h dissemination deadline"
    )


def test_disseminate_without_channels_rejected(api):
    """PRD §2.8: "`distribution_channels` at dissemination time must be a
    non-empty subset of `EMAIL`, `SMS`, `POSTERS`, `WEBSITE`, `SIREN`.
    Violations of these field-level constraints are rejected with
    `ERR_VALIDATION_FAILED` (HTTP 422); a dissemination attempt with an empty
    channel set is rejected with the more specific
    `ERR_NO_DISTRIBUTION_CHANNELS` (HTTP 422)."

    Design: Corner/validations/disseminate_without_channels_rejected
    """
    geography = create_geography(name="U", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-07-30T09:00:00Z",
        occurred_at="2026-07-30T08:00:00Z",
    )
    alert = create_authorized_alert(incident, alert_type="EMERGENCY_NOTIFICATION")

    res = api.disseminate_alert(alert["id"], {"distribution_channels": []}, CHIEF)
    validate_error(res, ApiErrorId.ERR_NO_DISTRIBUTION_CHANNELS.value, expected_status=422)

    after = validate_success(api.get_safety_alert(alert["id"], CHIEF), 200)
    assert after["status"] == "AUTHORIZED"


def test_safety_alert_branching_fork_with_reopen_cycle(api):
    """PRD §3.6: "A `CleryCoordinator` records the decision with a `decision`
    of `ISSUE` or `NO_ISSUE` and a required `decision_rationale`, moving the
    alert `PENDING_REVIEW → DECIDED_ISSUE` or `PENDING_REVIEW →
    DECIDED_NO_ISSUE` and stamping `decided_at` and `decided_by`."
    PRD §3.6: "Within 72 hours of `closed_at` a coordinator may reopen the
    alert, returning it `CLOSED → PENDING_REVIEW` with `reason` recorded and
    every decision field reset: `decision`, `decided_at`, `authorized_at`,
    `disseminated_at`, and `closed_at` all return to null, and both overdue
    flags reset to false."

    Design: Difficulty/non_linear_state_machine/safety_alert_branching_fork_with_reopen_cycle
    """
    geography = create_geography(name="Stadium", category="PUBLIC_PROPERTY")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-06-01T06:00:00Z",
        occurred_at="2026-06-01T05:00:00Z",
    )
    alert = create_pending_alert(incident, alert_type="TIMELY_WARNING")

    # Fork branch 1: NO_ISSUE.
    decided = validate_success(api.decide_alert(
        alert["id"],
        {"decision": "NO_ISSUE", "decision_rationale": "Not a continuing threat"},
        COORD,
    ), 200)
    assert decided["status"] == "DECIDED_NO_ISSUE"

    closed = validate_success(api.close_alert(alert["id"], COORD), 200)
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None

    reopened = validate_success(api.reopen_alert(
        alert["id"], {"reason": "New witness information"}, COORD
    ), 200)
    assert reopened["status"] == "PENDING_REVIEW"
    assert reopened["decision"] is None
    assert reopened["decided_at"] is None
    assert reopened["closed_at"] is None

    # Fork branch 2: ISSUE -> authorize -> disseminate.
    decided2 = validate_success(api.decide_alert(
        alert["id"],
        {"decision": "ISSUE", "decision_rationale": "Continuing threat confirmed"},
        COORD,
    ), 200)
    assert decided2["status"] == "DECIDED_ISSUE"

    authorized = validate_success(api.authorize_alert(alert["id"], CHIEF), 200)
    assert authorized["status"] == "AUTHORIZED"

    disseminated = validate_success(api.disseminate_alert(
        alert["id"], {"distribution_channels": ["EMAIL", "SMS"]}, CHIEF
    ), 200)
    assert disseminated["status"] == "DISSEMINATED"
    assert disseminated["disseminated_at"] is not None
    assert sorted(disseminated["distribution_channels"]) == ["EMAIL", "SMS"]


def test_reopen_resets_overdue_flags(api):
    """PRD §3.6: "Within 72 hours of `closed_at` a coordinator may reopen the
    alert, returning it `CLOSED → PENDING_REVIEW` with `reason` recorded and
    every decision field reset: `decision`, `decided_at`, `authorized_at`,
    `disseminated_at`, and `closed_at` all return to null, and both overdue
    flags reset to false."

    Design: Difficulty/non_linear_state_machine/safety_alert_branching_fork_with_reopen_cycle
    """
    geography = create_geography(name="Stadium Annex", category="PUBLIC_PROPERTY")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-06-02T06:00:00Z",
        occurred_at="2026-06-02T05:00:00Z",
    )
    alert = create_pending_alert(incident, alert_type="TIMELY_WARNING")
    validate_success(api.decide_alert(
        alert["id"], {"decision": "NO_ISSUE", "decision_rationale": "no threat"}, COORD
    ), 200)
    validate_success(api.close_alert(alert["id"], COORD), 200)

    reopened = validate_success(api.reopen_alert(
        alert["id"], {"reason": "Reopen requested"}, COORD
    ), 200)
    assert reopened["decision_overdue"] is False
    assert reopened["dissemination_overdue"] is False
    assert reopened["authorized_at"] is None
    assert reopened["disseminated_at"] is None


def test_reopen_after_72h_window_expired(api):
    """PRD §3.6: "A reopen attempted more than 72 hours after closure is
    rejected with `ERR_ALERT_WINDOW_EXPIRED` (HTTP 422); reopening exactly at
    the 72-hour mark is permitted."

    Design: Corner/validations/reopen_after_72h_window_expired
    """
    geography = create_geography(name="T", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-07-28T09:00:00Z",
        occurred_at="2026-07-28T08:00:00Z",
    )
    # Decide and close at the default clock 2026-08-01T00:00:00Z.
    alert = create_decided_alert(incident, decision="NO_ISSUE",
                                 decision_rationale="no threat")
    closed = validate_success(api.close_alert(alert["id"], COORD), 200)
    assert closed["closed_at"] == "2026-08-01T00:00:00Z"

    # 72h00m01s after closure.
    set_clock("2026-08-04T00:00:01Z")
    res = api.reopen_alert(alert["id"], {"reason": "late info"}, COORD)
    validate_error(res, ApiErrorId.ERR_ALERT_WINDOW_EXPIRED.value, expected_status=422)

    after = validate_success(api.get_safety_alert(alert["id"], COORD), 200)
    assert after["status"] == "CLOSED"


def test_coordinator_cannot_authorize_alert(api):
    """PRD §2.1: "Segregation of duties is deliberate: the role that decides an
    alert (`CleryCoordinator`) may not authorize or disseminate it
    (`PoliceChief`), and the role that compiles a report (`CleryCoordinator`)
    may not publish it (`PoliceChief`)."

    Design: Corner/rbac/coordinator_cannot_authorize_alert
    """
    geography = create_geography(name="M", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-07-29T09:00:00Z",
        occurred_at="2026-07-29T08:00:00Z",
    )
    alert = create_decided_alert(incident, decision="ISSUE",
                                 decision_rationale="threat")
    assert alert["status"] == "DECIDED_ISSUE"

    res = api.authorize_alert(alert["id"], COORD)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

    after = validate_success(api.get_safety_alert(alert["id"], COORD), 200)
    assert after["status"] == "DECIDED_ISSUE"


def test_chief_cannot_decide_alert(api):
    """PRD §2.1: "Segregation of duties is deliberate: the role that decides an
    alert (`CleryCoordinator`) may not authorize or disseminate it
    (`PoliceChief`), and the role that compiles a report (`CleryCoordinator`)
    may not publish it (`PoliceChief`)."
    PRD §3.6: "A `CleryCoordinator` records the decision with a `decision` of
    `ISSUE` or `NO_ISSUE` and a required `decision_rationale`."

    Design: Corner/rbac/chief_cannot_decide_alert
    """
    geography = create_geography(name="L", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-07-29T10:00:00Z",
        occurred_at="2026-07-29T09:00:00Z",
    )
    alert = create_pending_alert(incident, alert_type="TIMELY_WARNING")

    res = api.decide_alert(alert["id"], {"decision": "ISSUE", "decision_rationale": "x"}, CHIEF)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
