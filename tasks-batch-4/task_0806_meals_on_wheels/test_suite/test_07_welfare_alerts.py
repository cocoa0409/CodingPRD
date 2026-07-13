"""Wellness-check-driven welfare-alert cascade, severity derivation, and the
acknowledge/escalate/resolve lifecycle."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_volunteer_driver_headers,
    TEST_USERS,
)
from test_helpers.fixtures import (
    setup_open_welfare_alert,
    setup_active_client_with_plan,
    schedule_delivery,
    complete_delivery,
)

ROUTE_MGR = TEST_USERS["route_manager_headers"]


# ---------------------------------------------------------------------------
# NO_ANSWER transitive cascade (delivery -> wellness check -> welfare alert)
# ---------------------------------------------------------------------------
def test_no_answer_creates_wellness_check_and_increments_counter(api):
    """PRD §3.5: "First, a `WellnessCheck` is created for this delivery and client with
    `outcome` `NO_ANSWER`. Second, that check increments the client's `consecutive_no_answer`
    by 1."

    Design: Difficulty/transitive_cascade/no_answer_delivery_transitive_cascade
    """
    scenario = setup_active_client_with_plan(api)
    delivery = schedule_delivery(api, scenario["meal_plan"]["id"], "2026-03-02")
    complete_delivery(api, delivery["id"], scenario["driver"]["id"], "NO_ANSWER")
    checks, _ = validate_paginated(api.list_wellness_checks(ROUTE_MGR, params={"delivery_id": delivery["id"]}))
    assert len(checks) == 1
    assert checks[0]["outcome"] == "NO_ANSWER"
    client = validate_success(api.get_client(scenario["client"]["id"], ROUTE_MGR), 200)
    assert client["consecutive_no_answer"] == 1


def test_no_answer_opens_low_severity_welfare_alert(api):
    """PRD §3.6: "the alert is `HIGH` when the counter is at least 2 — meaning the second
    consecutive no-answer already yields `HIGH` — and `LOW` otherwise."
    PRD §3.6: "The alert records the at-risk client in `client_id` and the identifier of the
    no-answer check that opened it in `triggering_wellness_check_id`, both copied from the
    triggering event."

    Design: Difficulty/transitive_cascade/no_answer_delivery_transitive_cascade
    """
    scenario = setup_active_client_with_plan(api)
    delivery = schedule_delivery(api, scenario["meal_plan"]["id"], "2026-03-02")
    complete_delivery(api, delivery["id"], scenario["driver"]["id"], "NO_ANSWER")
    checks, _ = validate_paginated(api.list_wellness_checks(ROUTE_MGR, params={"delivery_id": delivery["id"]}))
    alerts, _ = validate_paginated(api.list_welfare_alerts(ROUTE_MGR, params={"client_id": scenario["client"]["id"]}))
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["status"] == "OPEN"
    assert alert["severity"] == "LOW", "first consecutive NO_ANSWER (counter 1) is LOW"
    assert alert["triggering_wellness_check_id"] == checks[0]["id"]


# ---------------------------------------------------------------------------
# Welfare-alert non-linear lifecycle
# ---------------------------------------------------------------------------
def test_alert_acknowledge_then_escalate_transitions(api):
    """PRD §3.6: "A `VolunteerDriver` or a `RouteManager` may acknowledge an `OPEN` alert,
    moving it `OPEN → ACKNOWLEDGED` and recording the acting operator's identifier in
    `acknowledged_by`. A `RouteManager` may escalate an alert that is either `OPEN` or
    `ACKNOWLEDGED`, moving it to `ESCALATED` (so both `OPEN → ESCALATED` and
    `ACKNOWLEDGED → ESCALATED` are valid)."

    Design: Difficulty/non_linear_state_machine/welfare_alert_branch_ack_escalate_resolve
    """
    scenario = setup_open_welfare_alert(api)
    alert_id = scenario["alert"]["id"]
    acked = validate_success(api.acknowledge_alert(alert_id, ROUTE_MGR), 200)
    assert acked["status"] == "ACKNOWLEDGED"
    escalated = validate_success(api.escalate_alert(alert_id, ROUTE_MGR), 200)
    assert escalated["status"] == "ESCALATED"


def test_alert_escalated_then_resolved(api):
    """PRD §3.6: "An alert is resolved by a `RouteManager` or an `IntakeCoordinator` from
    either `ACKNOWLEDGED` or `ESCALATED`, moving it to `RESOLVED` (both
    `ACKNOWLEDGED → RESOLVED` and `ESCALATED → RESOLVED` are valid)."

    Design: Difficulty/non_linear_state_machine/welfare_alert_branch_ack_escalate_resolve
    """
    scenario = setup_open_welfare_alert(api)
    alert_id = scenario["alert"]["id"]
    validate_success(api.acknowledge_alert(alert_id, ROUTE_MGR), 200)
    validate_success(api.escalate_alert(alert_id, ROUTE_MGR), 200)
    resolved = validate_success(api.resolve_alert(alert_id, ROUTE_MGR), 200)
    assert resolved["status"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Corner: HIGH severity on 2nd consecutive NO_ANSWER; invalid resolve; shared ack
# ---------------------------------------------------------------------------
def test_second_consecutive_no_answer_yields_high_severity(api):
    """PRD §3.6: "the alert is `HIGH` when the counter is at least 2 — meaning the second
    consecutive no-answer already yields `HIGH` — and `LOW` otherwise."

    Design: Corner/calculations/welfare_severity_high_on_second_consecutive_no_answer
    """
    scenario = setup_active_client_with_plan(api)
    plan_id, driver_id = scenario["meal_plan"]["id"], scenario["driver"]["id"]
    d1 = schedule_delivery(api, plan_id, "2026-03-02")
    d2 = schedule_delivery(api, plan_id, "2026-03-04")
    complete_delivery(api, d1["id"], driver_id, "NO_ANSWER")
    complete_delivery(api, d2["id"], driver_id, "NO_ANSWER")
    client = validate_success(api.get_client(scenario["client"]["id"], ROUTE_MGR), 200)
    assert client["consecutive_no_answer"] == 2
    alerts, _ = validate_paginated(
        api.list_welfare_alerts(ROUTE_MGR, params={"client_id": scenario["client"]["id"], "severity": "HIGH"})
    )
    assert any(a["severity"] == "HIGH" for a in alerts), "the 2nd consecutive NO_ANSWER opens a HIGH alert"


def test_resolve_open_alert_rejected(api):
    """PRD §3.6: "Any alert transition attempted from a state that does not permit it — for
    example acknowledging an alert that is not `OPEN`, escalating one that is neither `OPEN`
    nor `ACKNOWLEDGED`, or resolving one that is neither `ACKNOWLEDGED` nor `ESCALATED` — is
    rejected with `ERR_ALERT_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/welfare_alert_resolve_from_open_returns_invalid
    """
    scenario = setup_open_welfare_alert(api)
    resp = api.resolve_alert(scenario["alert"]["id"], ROUTE_MGR)
    validate_error(resp, "ERR_ALERT_INVALID_STATE", 409)


def test_volunteer_driver_can_acknowledge_alert(api):
    """PRD §3.6: "A `VolunteerDriver` or a `RouteManager` may acknowledge an `OPEN` alert,
    moving it `OPEN → ACKNOWLEDGED` and recording the acting operator's identifier in
    `acknowledged_by`."

    Design: Corner/rbac/acknowledge_alert_shared_by_driver_role
    """
    scenario = setup_open_welfare_alert(api)
    driver_id = scenario["driver"]["id"]
    resp = api.acknowledge_alert(scenario["alert"]["id"], make_volunteer_driver_headers(driver_id))
    acked = validate_success(resp, 200)
    assert acked["status"] == "ACKNOWLEDGED"
    assert acked["acknowledged_by"] == driver_id
