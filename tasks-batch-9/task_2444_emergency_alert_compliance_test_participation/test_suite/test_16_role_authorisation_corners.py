"""Role authorisation corners: who may call what, and what a refusal leaves behind.

Every test in this module exercises the role model of PRD §2.1 — the four declared
roles, the 401 header gate, the 403 role gate, the two station-scoped ownership
gates and the segregation-of-duties bar of PRD §2.12.
"""

import pytest

from test_helpers import (
    ADMIN,
    DUAL_ENGINEER,
    DUAL_OFFICER,
    DUAL_ROLE_USER_ID,
    ENGINEER,
    ENGINEER_USER_ID,
    INSPECTOR,
    OFFICER,
    SOURCE_CALL_SIGNS,
    TEST_DEFAULTS,
    UNRESOLVABLE_UUID,
    ApiErrorId,
    alert_event_payload,
    api_client,
    append_log_entry,
    assert_score_and_posture,
    create_active_plan,
    create_ready_device,
    create_relay_rule,
    device_payload,
    draft_response_payload,
    equipment_outage_payload,
    evaluate_readiness,
    filing_record_payload,
    get_success_data,
    inspection_request_payload,
    make_engineer_headers,
    make_officer_headers,
    monitoring_assignment_payload,
    public_file_document_payload,
    readiness_check_payload,
    register_device,
    register_station,
    schedule_test_event,
    set_clock,
    setup_drafted_inspection,
    setup_inspection,
    setup_logged_test_event,
    setup_station,
    state_plan_payload,
    station_payload,
    station_summary,
    station_version,
    test_event_payload as make_test_event_payload,
    test_event_version as read_test_event_version,
    test_log_entry_payload as make_test_log_entry_payload,
    validate_error,
    validate_paginated,
    validate_success,
    wireless_alert_notice_payload,
)

# Operators holding the right role but belonging to no station roster.
FOREIGN_ENGINEER = make_engineer_headers("eng-9")
FOREIGN_OFFICER = make_officer_headers("cert-9")


# ---------------------------------------------------------------------------
# Local scopes — built inline from the shared primitives so this module owns
# its own preconditions (the harness restarts the server before every test).
# ---------------------------------------------------------------------------
def _admin_scope():
    """Activated plan + station + one ACTIVE relay rule + one REGISTERED device."""
    plan = create_active_plan(("PEP",))
    station = register_station(plan["id"])
    rule = create_relay_rule(plan["id"], priority=1)
    device = register_device(station["id"])
    return {
        "plan_id": plan["id"],
        "station_id": station["id"],
        "rule_id": rule["id"],
        "device_id": device["id"],
    }


def _engineer_scope():
    """Station with one READY device and one SCHEDULED test event, no assignment."""
    plan = create_active_plan(("PEP",))
    station = register_station(plan["id"])
    device = create_ready_device(station["id"])
    event = schedule_test_event(station["id"])
    return {
        "plan_id": plan["id"],
        "station_id": station["id"],
        "device_id": device["id"],
        "device": device,
        "test_event_id": event["id"],
        "station_version": station["version"],
    }


def _officer_inspector_scope():
    """LOGGED test event plus an OPEN inspection request on the same station."""
    ctx = setup_logged_test_event()
    ctx["inspection"] = setup_inspection(
        ctx["station_id"], ["STATION_LOG", "PLAN_COPY"]
    )
    ctx["inspection_id"] = ctx["inspection"]["id"]
    return ctx


def _identity_scope():
    """LOGGED test event plus a RESPONSE_DRAFTED inspection on a rostered station."""
    ctx = setup_logged_test_event()
    ctx["inspection"] = setup_drafted_inspection(ctx["station_id"], ["STATION_LOG"])
    ctx["inspection_id"] = ctx["inspection"]["id"]
    return ctx


# ===========================================================================
# ComplianceAdmin-exclusive writes
# ===========================================================================
ADMIN_EXCLUSIVE_PROBES = [
    pytest.param(
        lambda ctx: api_client.set_clock("2026-09-01T00:00:00Z", ENGINEER),
        id="clock_set_by_engineer",
    ),
    pytest.param(
        lambda ctx: api_client.create_state_plan(
            state_plan_payload(state_code="NE"), OFFICER
        ),
        id="plan_create_by_officer",
    ),
    pytest.param(
        lambda ctx: api_client.create_station(
            station_payload(ctx["plan_id"], call_sign="KIN1", service_type="FM"),
            INSPECTOR,
        ),
        id="station_create_by_inspector",
    ),
    pytest.param(
        lambda ctx: api_client.run_log_review(ctx["station_id"], ENGINEER),
        id="log_review_by_engineer",
    ),
    pytest.param(
        lambda ctx: api_client.retire_relay_rule(ctx["rule_id"], INSPECTOR),
        id="relay_rule_retire_by_inspector",
    ),
    pytest.param(
        lambda ctx: api_client.decommission_device(ctx["device_id"], ENGINEER),
        id="device_decommission_by_engineer",
    ),
    pytest.param(
        lambda ctx: api_client.create_test_event(
            make_test_event_payload(ctx["station_id"]), OFFICER
        ),
        id="test_event_create_by_officer",
    ),
    pytest.param(
        lambda ctx: api_client.create_wireless_alert_notice(
            wireless_alert_notice_payload(ctx["station_id"], "2026-08-01T00:00:00Z"),
            ENGINEER,
        ),
        id="wireless_notice_by_engineer",
    ),
]


@pytest.mark.parametrize("probe", ADMIN_EXCLUSIVE_PROBES)
def test_admin_exclusive_write_refused_to_every_other_role(probe):
    """PRD §2.1: "This role owns state plans and forwarding rules, registers stations, drives the logical clock, runs station log reviews, schedules test events, records wireless alert notices, accepts and reverses filings, verifies or rejects reported equipment restorations, and permanently decommissions devices."
    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/compliance_admin_exclusive_writes_are_forbidden_to_the_other_three_roles
    """
    ctx = _admin_scope()
    response = probe(ctx)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)


def test_refused_admin_exclusive_writes_leave_no_trace():
    """PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.10: "A station is created in `PROVISIONING` with `compliance_score` null, `compliance_variant_applied` null and `version` 1, and it stays in `PROVISIONING` until the first recompute event fires against it; from that moment on it is always in exactly one of `COMPLIANT`, `WATCH` or `SUSPENDED_FILINGS`."
    PRD §3.1: "New rules begin with `status` set to `ACTIVE`."
    PRD §3.2: "A newly registered unit sits in `REGISTERED` with `readiness_check_passed` false and `last_readiness_check_at` null."

    Design: Corner/rbac/compliance_admin_exclusive_writes_are_forbidden_to_the_other_three_roles
    """
    ctx = _admin_scope()

    validate_error(
        api_client.run_log_review(ctx["station_id"], ENGINEER),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.retire_relay_rule(ctx["rule_id"], INSPECTOR),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.decommission_device(ctx["device_id"], ENGINEER),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_state_plan(state_plan_payload(state_code="NE"), OFFICER),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_station(
            station_payload(ctx["plan_id"], call_sign="KIN1", service_type="FM"),
            INSPECTOR,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    summary = station_summary(ctx["station_id"])
    assert summary["compliance_score"] is None, (
        "the refused run-log-review computed no score"
    )
    assert summary["last_log_review_at"] is None, (
        "the refused run-log-review stamped no review instant"
    )
    assert summary["compliance_posture"] == "PROVISIONING"

    rule = validate_success(api_client.get_relay_rule(ctx["rule_id"], ADMIN))
    assert rule["status"] == "ACTIVE", "the refused retire left the rule ACTIVE"

    device = validate_success(api_client.get_device(ctx["device_id"], ADMIN))
    assert device["status"] == "REGISTERED", (
        "the refused decommission left the device REGISTERED"
    )

    _, stations_meta = validate_paginated(api_client.list_stations(ADMIN))
    assert stations_meta["total_count"] == 1, "the refused station create persisted nothing"
    _, plans_meta = validate_paginated(api_client.list_state_plans(ADMIN))
    assert plans_meta["total_count"] == 1, "the refused plan create persisted nothing"


def test_refused_clock_set_leaves_the_logical_clock_at_its_startup_default():
    """PRD §2.4: "The server maintains a **logical clock** whose value at startup is exactly `2026-08-01T00:00:00Z`, and it keeps reading that default until an administrator moves it; there is no fallback to real time under any circumstance."
    PRD §2.4: "A `ComplianceAdmin` moves the clock by supplying `to_iso8601`, an ISO 8601 UTC instant, to the administrative clock-setting capability; the call returns 200 OK, mutates no entity, and fires no recompute event of any kind."
    PRD §2.5: "Every stored row carries an `id` that the server mints as a UUID with no type prefix, and a `created_at` that is an ISO 8601 UTC timestamp with three fractional digits taken from the logical clock at insert time."

    Design: Corner/rbac/compliance_admin_exclusive_writes_are_forbidden_to_the_other_three_roles
    """
    ctx = _admin_scope()

    validate_error(
        api_client.set_clock("2026-09-01T00:00:00Z", ENGINEER),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.set_clock("2026-09-01T00:00:00Z", INSPECTOR),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    later_device = register_device(ctx["station_id"], model_code="SAGE-3644")
    assert later_device["created_at"].startswith("2026-08-01T00:00:00"), (
        "a refused clock move must leave the logical clock at its startup default, "
        f"but a row inserted afterwards reads {later_device['created_at']}"
    )


# ===========================================================================
# StationEngineer-exclusive writes
# ===========================================================================
ENGINEER_EXCLUSIVE_PROBES = [
    pytest.param(
        lambda ctx: api_client.create_device(
            device_payload(ctx["station_id"], device_role="ENCODER"), ADMIN
        ),
        id="device_create_by_admin",
    ),
    pytest.param(
        lambda ctx: api_client.readiness_check_device(
            ctx["device_id"], readiness_check_payload(), ADMIN
        ),
        id="readiness_check_by_admin",
    ),
    pytest.param(
        lambda ctx: api_client.create_monitoring_assignment(
            monitoring_assignment_payload(
                ctx["station_id"], ctx["device_id"], ctx["station_version"]
            ),
            OFFICER,
        ),
        id="assignment_create_by_officer",
    ),
    pytest.param(
        lambda ctx: api_client.create_equipment_outage(
            equipment_outage_payload(ctx["device_id"], "2026-08-01T00:00:00Z"), ADMIN
        ),
        id="outage_create_by_admin",
    ),
    pytest.param(
        lambda ctx: api_client.create_alert_event(
            alert_event_payload(ctx["station_id"], "2026-08-01T00:00:00Z"), INSPECTOR
        ),
        id="alert_create_by_inspector",
    ),
    pytest.param(
        lambda ctx: api_client.create_test_log_entry(
            make_test_log_entry_payload(ctx["test_event_id"], ctx["device_id"]), OFFICER
        ),
        id="log_entry_create_by_officer",
    ),
    pytest.param(
        lambda ctx: api_client.evaluate_readiness(ctx["test_event_id"], ADMIN),
        id="evaluate_readiness_by_admin",
    ),
    pytest.param(
        lambda ctx: api_client.create_public_file_document(
            ctx["station_id"], public_file_document_payload(), INSPECTOR
        ),
        id="public_file_upload_by_inspector",
    ),
]


@pytest.mark.parametrize("probe", ENGINEER_EXCLUSIVE_PROBES)
def test_engineer_exclusive_write_refused_to_every_other_role(probe):
    """PRD §2.1: "A `StationEngineer` works on the station side: registering and readiness-checking equipment, maintaining monitoring assignments, filing outages and their repairs, logging received alerts and test log lines, drafting inspection responses and uploading public-file documents."
    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/station_engineer_exclusive_writes_are_unauthorized_for_the_other_roles
    """
    ctx = _engineer_scope()
    response = probe(ctx)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)


def test_role_refusal_on_assignment_create_precedes_the_station_version_guard():
    """PRD §2.8: "When a single request violates more than one rule, the response reports the violation with the lowest ladder position below."
    PRD §2.8: "The ladder is evaluated strictly in this order, and a check never runs before every lower-numbered check has passed."
    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.7: "If that value does not equal the station's current `version`, the create is rejected with `ERR_STALE_STATION_VERSION` and HTTP 412."

    Design: Corner/rbac/station_engineer_exclusive_writes_are_unauthorized_for_the_other_roles
    """
    ctx = _engineer_scope()

    response = api_client.create_monitoring_assignment(
        monitoring_assignment_payload(ctx["station_id"], ctx["device_id"], 999),
        OFFICER,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    station = validate_success(api_client.get_station(ctx["station_id"], ADMIN))
    assert station["version"] == ctx["station_version"], (
        "the refused assignment create must not bump the station's version"
    )


def test_refused_engineer_writes_leave_the_station_and_test_event_untouched():
    """PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.2: "A freshly registered station has `compliance_posture` `PROVISIONING`, `compliance_score` and `compliance_variant_applied` both null, `accessible_source_count` 0, `silent_assignment_count` 0, `penalty_points_total` 0, `plan_revalidation_required` false, `public_file_document_count` 0, `last_log_review_at` null and `version` 1."
    PRD §3.6: "A newly scheduled event sits in `SCHEDULED` with `readiness_score` and `readiness_evaluated_at` null, `logged_entry_count` 0 and `retention_until_max` null, and the server derives `filing_deadline_at` at create time as `window_end_at` plus five days."

    Design: Corner/rbac/station_engineer_exclusive_writes_are_unauthorized_for_the_other_roles
    """
    ctx = _engineer_scope()
    readiness_stamp = ctx["device"]["last_readiness_check_at"]

    for probe in ENGINEER_EXCLUSIVE_PROBES:
        validate_error(probe.values[0](ctx), ApiErrorId.ERR_UNAUTHORIZED)

    summary = station_summary(ctx["station_id"])
    assert summary["accessible_source_count"] == 0
    assert summary["public_file_document_count"] == 0
    assert summary["compliance_score"] is None

    event = validate_success(api_client.get_test_event(ctx["test_event_id"], ADMIN))
    assert event["status"] == "SCHEDULED", "the refused evaluate-readiness left SCHEDULED"
    assert event["readiness_score"] is None
    assert event["logged_entry_count"] == 0

    device = validate_success(api_client.get_device(ctx["device_id"], ADMIN))
    assert device["status"] == "READY"
    assert device["last_readiness_check_at"] == readiness_stamp, (
        "the refused readiness-check must not refresh last_readiness_check_at"
    )

    _, outages_meta = validate_paginated(api_client.list_equipment_outages(ADMIN))
    assert outages_meta["total_count"] == 0
    _, alerts_meta = validate_paginated(api_client.list_alert_events(ADMIN))
    assert alerts_meta["total_count"] == 0
    _, events_meta = validate_paginated(
        api_client.list_test_events(
            ADMIN, params={"station_id": ctx["station_id"], "status": "SCHEDULED"}
        )
    )
    assert events_meta["total_count"] == 1


# ===========================================================================
# CertifyingOfficer- and FieldInspector-exclusive writes
# ===========================================================================
CROSS_ROLE_PROBES = [
    pytest.param(
        lambda ctx: api_client.create_filing_record(
            filing_record_payload(
                ctx["test_event_id"], read_test_event_version(ctx["test_event_id"], ADMIN)
            ),
            ENGINEER,
        ),
        id="filing_by_engineer",
    ),
    pytest.param(
        lambda ctx: api_client.create_filing_record(
            filing_record_payload(
                ctx["test_event_id"], read_test_event_version(ctx["test_event_id"], ADMIN)
            ),
            ADMIN,
        ),
        id="filing_by_admin",
    ),
    pytest.param(
        lambda ctx: api_client.create_inspection_request(
            inspection_request_payload(
                ctx["station_id"], requested_document_kinds=["TEST_LOGS"]
            ),
            OFFICER,
        ),
        id="inspection_open_by_officer",
    ),
    pytest.param(
        lambda ctx: api_client.draft_response(
            ctx["inspection_id"],
            draft_response_payload(["STATION_LOG", "PLAN_COPY"]),
            INSPECTOR,
        ),
        id="draft_response_by_inspector",
    ),
    pytest.param(
        lambda ctx: api_client.submit_response(ctx["inspection_id"], ENGINEER),
        id="submit_response_by_engineer",
    ),
    pytest.param(
        lambda ctx: api_client.close_inspection(ctx["inspection_id"], OFFICER),
        id="inspection_close_by_officer",
    ),
    pytest.param(
        lambda ctx: api_client.close_inspection(ctx["inspection_id"], ADMIN),
        id="inspection_close_by_admin",
    ),
]


@pytest.mark.parametrize("probe", CROSS_ROLE_PROBES)
def test_officer_and_inspector_exclusive_writes_refused_across_roles(probe):
    """PRD §2.1: "A `CertifyingOfficer` is the station's certifying official and the only role permitted to file post-test results or to submit an inspection response."
    PRD §2.1: "This role opens public-file inspection requests and closes them, and holds no other write power."
    PRD §3.9: "A `StationEngineer` drafts by supplying `provided_document_kinds`, an array whose members are drawn from the same five document kinds."
    PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/certifying_officer_and_field_inspector_exclusive_writes_are_forbidden_across_roles
    """
    ctx = _officer_inspector_scope()
    response = probe(ctx)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)


def test_refused_filings_create_no_row_and_leave_the_event_logged():
    """PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.7: "A successful filing is stored in `SUBMITTED` with `reversal_reason` null, increments the event's `version` by one, and advances the event to `FILED`."
    PRD §3.9: "The request opens in `OPEN` with `requested_at` stamped from the logical clock, `provided_document_kinds` an empty array, `responded_at` null and `completeness_score` null, and the server derives `response_due_at` as `requested_at` plus seven days."

    Design: Corner/rbac/certifying_officer_and_field_inspector_exclusive_writes_are_forbidden_across_roles
    """
    ctx = _officer_inspector_scope()
    event_version = read_test_event_version(ctx["test_event_id"], ADMIN)

    for headers in (ENGINEER, ADMIN):
        validate_error(
            api_client.create_filing_record(
                filing_record_payload(ctx["test_event_id"], event_version), headers
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
    validate_error(
        api_client.draft_response(
            ctx["inspection_id"], draft_response_payload(["STATION_LOG"]), INSPECTOR
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_inspection_request(
            inspection_request_payload(
                ctx["station_id"], requested_document_kinds=["TEST_LOGS"]
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    event = validate_success(api_client.get_test_event(ctx["test_event_id"], ADMIN))
    assert event["status"] == "LOGGED", "a refused filing must not advance the event"
    assert event["version"] == event_version, (
        "a refused filing must not bump the test event's version"
    )

    _, filings_meta = validate_paginated(
        api_client.list_filing_records(
            ADMIN, params={"test_event_id": ctx["test_event_id"]}
        )
    )
    assert filings_meta["total_count"] == 0, "a 403 never creates the filing row"

    inspection = validate_success(
        api_client.get_inspection_request(ctx["inspection_id"], INSPECTOR)
    )
    assert inspection["status"] == "OPEN"
    assert inspection["provided_document_kinds"] == []
    assert inspection["responded_at"] is None

    _, inspections_meta = validate_paginated(
        api_client.list_inspection_requests(
            INSPECTOR, params={"station_id": ctx["station_id"]}
        )
    )
    assert inspections_meta["total_count"] == 1, (
        "the officer's refused open created no second request"
    )


# ===========================================================================
# The 401 header gate
# ===========================================================================
NO_HEADERS = {"Content-Type": "application/json"}
ROLE_ONLY = {"X-User-Role": "ComplianceAdmin", "Content-Type": "application/json"}
USER_ONLY = {"X-User-ID": "adm-1", "Content-Type": "application/json"}
UNDECLARED_ROLE = {
    "X-User-ID": "bc-1",
    "X-User-Role": "StateBroadcaster",
    "Content-Type": "application/json",
}

MISSING_AUTH_PROBES = [
    pytest.param(
        lambda ctx: api_client.get_station(ctx["station_id"], NO_HEADERS),
        id="read_with_no_headers",
    ),
    pytest.param(
        lambda ctx: api_client.get_station(ctx["station_id"], ROLE_ONLY),
        id="read_with_role_but_no_user_id",
    ),
    pytest.param(
        lambda ctx: api_client.get_station(ctx["station_id"], USER_ONLY),
        id="read_with_user_id_but_no_role",
    ),
    pytest.param(
        lambda ctx: api_client.create_state_plan(
            state_plan_payload(state_code="NE"), UNDECLARED_ROLE
        ),
        id="write_with_undeclared_role",
    ),
    pytest.param(
        lambda ctx: api_client.run_log_review(ctx["station_id"], UNDECLARED_ROLE),
        id="admin_only_write_with_undeclared_role",
    ),
]


@pytest.mark.parametrize("probe", MISSING_AUTH_PROBES)
def test_absent_or_undeclared_auth_headers_are_rejected_with_401(probe):
    """PRD §2.1: "Every request — reads included — must carry two headers."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the four role names below, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
    PRD §2.1: "The four recognised roles are `ComplianceAdmin`, `StationEngineer`, `CertifyingOfficer` and `FieldInspector`."

    Design: Corner/rbac/missing_auth_headers_and_unknown_roles_are_rejected_before_any_lookup
    """
    plan = create_active_plan(("PEP",))
    station = register_station(plan["id"])
    response = probe({"station_id": station["id"], "plan_id": plan["id"]})
    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS)


def test_missing_headers_beat_schema_and_existence_reporting():
    """PRD §2.8: "When a single request violates more than one rule, the response reports the violation with the lowest ladder position below."
    PRD §2.8: "The ladder is evaluated strictly in this order, and a check never runs before every lower-numbered check has passed."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the four role names below, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
    PRD §2.10: "A station is created in `PROVISIONING` with `compliance_score` null, `compliance_variant_applied` null and `version` 1, and it stays in `PROVISIONING` until the first recompute event fires against it; from that moment on it is always in exactly one of `COMPLIANT`, `WATCH` or `SUSPENDED_FILINGS`."

    Design: Corner/rbac/missing_auth_headers_and_unknown_roles_are_rejected_before_any_lookup
    """
    plan = create_active_plan(("PEP",))
    station = register_station(plan["id"])

    # Unauthenticated + unresolvable station id + a body missing reference_label.
    response = api_client.create_public_file_document(
        UNRESOLVABLE_UUID, {"document_kind": "STATION_LOG"}, NO_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS)

    summary = station_summary(station["id"])
    assert summary["compliance_score"] is None
    assert summary["public_file_document_count"] == 0
    assert summary["last_log_review_at"] is None


# ===========================================================================
# Reads are shared by all four roles
# ===========================================================================
ALL_FOUR_ROLES = (ADMIN, ENGINEER, OFFICER, INSPECTOR)


def test_every_read_returns_the_same_body_for_all_four_roles():
    """PRD §2.1: "All four roles may call every read (`GET`) endpoint in the system."
    PRD §2.3: "Every list response repeats `limit` and `offset` in the `meta` object alongside `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current page)."
    PRD §2.3: "`limit` sets the maximum number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."

    Design: Corner/rbac/every_read_endpoint_is_shared_identically_by_all_four_roles
    """
    plan = create_active_plan(("PEP",))
    station = register_station(plan["id"])
    device = register_device(station["id"])

    plan_reads = [
        validate_success(api_client.get_state_plan(plan["id"], headers))
        for headers in ALL_FOUR_ROLES
    ]
    for body in plan_reads:
        assert body == plan_reads[0], "plan detail reads must be role-blind"
        assert body["status"] == "ACTIVE"
        assert body["required_source_count"] == 1
        assert body["required_source_types"] == ["PEP"]

    summary_reads = [
        validate_success(api_client.get_compliance_summary(station["id"], headers))
        for headers in ALL_FOUR_ROLES
    ]
    for body in summary_reads:
        assert body == summary_reads[0], "compliance-summary reads must be role-blind"
        assert body["compliance_score"] is None
        assert body["compliance_posture"] == "PROVISIONING"
        assert body["required_source_count"] == 1
        assert body["accessible_source_count"] == 0
        assert body["public_file_document_count"] == 0

    device_reads = []
    for headers in ALL_FOUR_ROLES:
        rows, meta = validate_paginated(
            api_client.list_devices(headers, params={"station_id": station["id"]})
        )
        assert meta["total_count"] == 1
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [device["id"]]
        assert rows[0]["status"] == "REGISTERED"
        device_reads.append(rows)
    for rows in device_reads:
        assert rows == device_reads[0], "device list reads must be role-blind"

    for headers in ALL_FOUR_ROLES:
        rows, meta = validate_paginated(api_client.list_filing_records(headers))
        assert rows == [], "an empty list is a 200 with no rows, never a 404"
        assert meta["total_count"] == 0
        assert meta["has_more"] is False


def test_engineer_outside_the_station_roster_may_still_read():
    """PRD §2.1: "All four roles may call every read (`GET`) endpoint in the system."
    PRD §2.1: "For every write endpoint reached by a `StationEngineer`, the acting `X-User-ID` must appear in the `engineer_user_ids` array of the station the write ultimately targets; if it does not, the request is rejected with `ERR_ENGINEER_NOT_ASSIGNED` (HTTP 403)."

    Design: Corner/rbac/every_read_endpoint_is_shared_identically_by_all_four_roles
    """
    ctx = setup_station()

    assert validate_success(
        api_client.get_station(ctx["station_id"], FOREIGN_ENGINEER)
    ) == validate_success(api_client.get_station(ctx["station_id"], ADMIN))

    assert validate_success(
        api_client.get_compliance_summary(ctx["station_id"], FOREIGN_ENGINEER)
    ) == validate_success(api_client.get_compliance_summary(ctx["station_id"], ADMIN))

    foreign_rows, foreign_meta = validate_paginated(
        api_client.list_monitoring_assignments(
            FOREIGN_ENGINEER, params={"station_id": ctx["station_id"]}
        )
    )
    inspector_rows, inspector_meta = validate_paginated(
        api_client.list_monitoring_assignments(
            INSPECTOR, params={"station_id": ctx["station_id"]}
        )
    )
    assert foreign_rows == inspector_rows
    assert foreign_meta["total_count"] == inspector_meta["total_count"] == 1


# ===========================================================================
# One end-to-end pass in which every role performs its own exclusive operation
# ===========================================================================
def _run_full_role_chain():
    """Drive one clean pass: each step is performed by the single role PRD §2.1 gives it.

    Returns ``(steps, rows)`` where ``steps`` is a list of
    ``(label, response, expected_status)`` tuples and ``rows`` holds the parsed rows.
    """
    steps = []
    rows = {}

    def step(label, response, expected_status):
        steps.append((label, response, expected_status))
        return response

    plan = get_success_data(
        step(
            "plan_create",
            api_client.create_state_plan(state_plan_payload(), ADMIN),
            201,
        )
    )
    get_success_data(
        step(
            "plan_activate",
            api_client.activate_state_plan(plan["id"], ADMIN),
            200,
        )
    )
    station = get_success_data(
        step(
            "station_create",
            api_client.create_station(station_payload(plan["id"]), ADMIN),
            201,
        )
    )
    device = get_success_data(
        step(
            "device_create",
            api_client.create_device(device_payload(station["id"]), ENGINEER),
            201,
        )
    )
    device = get_success_data(
        step(
            "readiness_check",
            api_client.readiness_check_device(
                device["id"], readiness_check_payload(), ENGINEER
            ),
            200,
        )
    )
    version = station_version(station["id"])
    assignment = get_success_data(
        step(
            "assignment_create",
            api_client.create_monitoring_assignment(
                monitoring_assignment_payload(station["id"], device["id"], version),
                ENGINEER,
            ),
            201,
        )
    )
    event = get_success_data(
        step(
            "test_event_create",
            api_client.create_test_event(
                make_test_event_payload(
                    station["id"],
                    window_start_at="2026-08-12T00:00:00Z",
                    window_end_at="2026-08-12T01:00:00Z",
                ),
                ADMIN,
            ),
            201,
        )
    )
    set_clock("2026-08-11T00:00:00Z")
    event = get_success_data(
        step(
            "evaluate_readiness",
            api_client.evaluate_readiness(event["id"], ENGINEER),
            200,
        )
    )
    set_clock("2026-08-12T00:30:00Z")
    entry = get_success_data(
        step(
            "log_entry_create",
            api_client.create_test_log_entry(
                make_test_log_entry_payload(
                    event["id"],
                    device["id"],
                    entry_kind="RECEIPT",
                    source_call_sign=SOURCE_CALL_SIGNS["PEP"],
                ),
                ENGINEER,
            ),
            201,
        )
    )
    event = get_success_data(
        step(
            "close_logging",
            api_client.close_logging(event["id"], ENGINEER),
            200,
        )
    )
    inspection = get_success_data(
        step(
            "inspection_open",
            api_client.create_inspection_request(
                inspection_request_payload(
                    station["id"],
                    requested_document_kinds=["STATION_LOG", "PLAN_COPY"],
                ),
                INSPECTOR,
            ),
            201,
        )
    )
    set_clock("2026-08-12T00:40:00Z")
    filing = get_success_data(
        step(
            "filing_create",
            api_client.create_filing_record(
                filing_record_payload(
                    event["id"], read_test_event_version(event["id"], OFFICER)
                ),
                OFFICER,
            ),
            201,
        )
    )
    filing = get_success_data(
        step(
            "filing_accept",
            api_client.accept_filing(filing["id"], ADMIN),
            200,
        )
    )
    inspection = get_success_data(
        step(
            "draft_response",
            api_client.draft_response(
                inspection["id"],
                draft_response_payload(["STATION_LOG", "PLAN_COPY"]),
                ENGINEER,
            ),
            200,
        )
    )
    inspection = get_success_data(
        step(
            "submit_response",
            api_client.submit_response(inspection["id"], OFFICER),
            200,
        )
    )
    inspection = get_success_data(
        step(
            "inspection_close",
            api_client.close_inspection(inspection["id"], INSPECTOR),
            200,
        )
    )
    set_clock("2026-08-12T00:45:00Z")
    station = get_success_data(
        step(
            "log_review",
            api_client.run_log_review(station["id"], ADMIN),
            200,
        )
    )

    # The `event` snapshot above is the close-logging response, taken before the
    # filing advanced the event LOGGED -> FILED, so re-read it for its final state.
    event = validate_success(api_client.get_test_event(event["id"], ADMIN))

    rows.update(
        plan=plan,
        station=station,
        device=device,
        assignment=assignment,
        test_event=event,
        log_entry=entry,
        filing=filing,
        inspection=inspection,
    )
    return steps, rows


def test_each_role_completes_its_own_exclusive_operations_in_one_pass():
    """PRD §2.1: "This role owns state plans and forwarding rules, registers stations, drives the logical clock, runs station log reviews, schedules test events, records wireless alert notices, accepts and reverses filings, verifies or rejects reported equipment restorations, and permanently decommissions devices."
    PRD §2.1: "A `StationEngineer` works on the station side: registering and readiness-checking equipment, maintaining monitoring assignments, filing outages and their repairs, logging received alerts and test log lines, drafting inspection responses and uploading public-file documents."
    PRD §2.1: "A `CertifyingOfficer` is the station's certifying official and the only role permitted to file post-test results or to submit an inspection response."
    PRD §2.1: "This role opens public-file inspection requests and closes them, and holds no other write power."
    PRD §4: "Operations that create a new stored row return `201 Created`; operations that mutate an existing row, run a computation, drive a state transition or set the logical clock return `200 OK`."

    Design: Corner/rbac/each_role_completes_its_own_exclusive_operations_in_one_end_to_end_pass
    """
    steps, rows = _run_full_role_chain()

    for label, response, expected_status in steps:
        assert response.status_code == expected_status, (
            f"step {label} expected HTTP {expected_status}, got {response.status_code}: "
            f"{response.text}"
        )

    assert rows["test_event"]["status"] == "FILED"
    assert rows["test_event"]["readiness_score"] == pytest.approx(80.00, abs=0.01)
    assert rows["test_event"]["logged_entry_count"] == 1
    assert rows["filing"]["status"] == "ACCEPTED"
    assert rows["filing"]["late_days"] == 0
    assert rows["filing"]["penalty_points"] == pytest.approx(0.00, abs=0.01)
    assert rows["inspection"]["status"] == "CLOSED_SATISFIED"
    assert rows["inspection"]["completeness_score"] == pytest.approx(100.00, abs=0.01)


def test_the_end_to_end_pass_lands_certified_and_compliant():
    """PRD §3.7: "Acceptance fires a station recompute event, and its consequence is significant: an accepted filing is what makes the station eligible for the certified scoring variant of §3.8, so a station scoring a perfect 100.00 provisionally can drop two posture bands the moment its first filing is accepted."
    PRD §3.8: "When it is certified-eligible, `compliance_variant_applied` is `CERTIFIED` and all six deductions are applied."
    PRD §2.10: "The band mapping is: a score of 90.00 or greater yields `COMPLIANT`; a score of at least 75.00 but below 90.00 yields `WATCH`; anything below 75.00 yields `SUSPENDED_FILINGS`."
    PRD §3.8: "The scoring variant is chosen, `compliance_score` and `compliance_variant_applied` are written, `compliance_posture` is set from the score bands, and `last_log_review_at` is stamped from the logical clock."

    Design: Corner/rbac/each_role_completes_its_own_exclusive_operations_in_one_end_to_end_pass
    """
    _, rows = _run_full_role_chain()

    summary = station_summary(rows["station"]["id"])
    assert summary["compliance_variant_applied"] == "CERTIFIED"
    assert_score_and_posture(summary, 100.00, "COMPLIANT")
    assert summary["penalty_points_total"] == pytest.approx(0.00, abs=0.01)
    assert summary["unfiled_test_count"] == 0
    assert summary["silent_assignment_count"] == 0
    assert summary["accessible_source_count"] == 1
    assert summary["last_log_review_at"].startswith("2026-08-12T00:45:00"), (
        "last_log_review_at is stamped from the logical clock at review time, got "
        f"{summary['last_log_review_at']}"
    )


# ===========================================================================
# Station-scoped identity denials inside the correct role
# ===========================================================================
FOREIGN_IDENTITY_PROBES = [
    pytest.param(
        lambda ctx: api_client.create_monitoring_assignment(
            monitoring_assignment_payload(
                ctx["station_id"],
                ctx["device_id"],
                station_version(ctx["station_id"], ADMIN),
                source_type="LP1",
            ),
            FOREIGN_ENGINEER,
        ),
        ApiErrorId.ERR_ENGINEER_NOT_ASSIGNED,
        id="foreign_engineer_assignment_create",
    ),
    pytest.param(
        lambda ctx: api_client.create_public_file_document(
            ctx["station_id"], public_file_document_payload(), FOREIGN_ENGINEER
        ),
        ApiErrorId.ERR_ENGINEER_NOT_ASSIGNED,
        id="foreign_engineer_public_file_upload",
    ),
    pytest.param(
        lambda ctx: api_client.record_receipt(
            ctx["assignments"]["PEP"]["id"], FOREIGN_ENGINEER
        ),
        ApiErrorId.ERR_ENGINEER_NOT_ASSIGNED,
        id="foreign_engineer_record_receipt",
    ),
    pytest.param(
        lambda ctx: api_client.create_filing_record(
            filing_record_payload(
                ctx["test_event_id"], read_test_event_version(ctx["test_event_id"], ADMIN)
            ),
            FOREIGN_OFFICER,
        ),
        ApiErrorId.ERR_NOT_CERTIFYING_OFFICER,
        id="foreign_officer_filing",
    ),
    pytest.param(
        lambda ctx: api_client.submit_response(ctx["inspection_id"], FOREIGN_OFFICER),
        ApiErrorId.ERR_NOT_CERTIFYING_OFFICER,
        id="foreign_officer_submit_response",
    ),
]


@pytest.mark.parametrize("probe,expected_error", FOREIGN_IDENTITY_PROBES)
def test_station_scoped_identity_denials_apply_within_the_correct_role(
    probe, expected_error
):
    """PRD §2.1: "For every write endpoint reached by a `StationEngineer`, the acting `X-User-ID` must appear in the `engineer_user_ids` array of the station the write ultimately targets; if it does not, the request is rejected with `ERR_ENGINEER_NOT_ASSIGNED` (HTTP 403)."
    PRD §2.1: "For every write endpoint reached by a `CertifyingOfficer`, the acting `X-User-ID` must be exactly equal to the target station's `certification_officer_user_id`; otherwise the request is rejected with `ERR_NOT_CERTIFYING_OFFICER` (HTTP 403)."

    Design: Corner/rbac/station_scoped_identity_denials_apply_within_the_correct_role
    """
    ctx = _identity_scope()
    validate_error(probe(ctx), expected_error)


def test_ownership_refusal_precedes_the_station_version_guard():
    """PRD §2.8: "When a single request violates more than one rule, the response reports the violation with the lowest ladder position below."
    PRD §2.8: "The ladder is evaluated strictly in this order, and a check never runs before every lower-numbered check has passed."
    PRD §2.1: "For every write endpoint reached by a `StationEngineer`, the acting `X-User-ID` must appear in the `engineer_user_ids` array of the station the write ultimately targets; if it does not, the request is rejected with `ERR_ENGINEER_NOT_ASSIGNED` (HTTP 403)."
    PRD §2.7: "If that value does not equal the station's current `version`, the create is rejected with `ERR_STALE_STATION_VERSION` and HTTP 412."

    Design: Corner/rbac/station_scoped_identity_denials_apply_within_the_correct_role
    """
    ctx = setup_station()
    before = station_version(ctx["station_id"], ADMIN)

    response = api_client.create_monitoring_assignment(
        monitoring_assignment_payload(
            ctx["station_id"], ctx["device_id"], 999, source_type="LP1"
        ),
        FOREIGN_ENGINEER,
    )
    validate_error(response, ApiErrorId.ERR_ENGINEER_NOT_ASSIGNED)

    assert station_version(ctx["station_id"], ADMIN) == before, (
        "the ownership refusal must leave the station's version untouched"
    )


def test_assigned_engineer_upload_succeeds_where_the_foreign_one_failed():
    """PRD §2.1: "For every write endpoint reached by a `StationEngineer`, the acting `X-User-ID` must appear in the `engineer_user_ids` array of the station the write ultimately targets; if it does not, the request is rejected with `ERR_ENGINEER_NOT_ASSIGNED` (HTTP 403)."
    PRD §3.2: "Each recorded upload names a `document_kind` and a `reference_label`, advances the station's `public_file_document_count` by one, and returns the updated station row rather than a document row."
    PRD §3.2: "Because the upload registers a new public-file item, this operation answers with `201 Created` even though its response body is the station."

    Design: Corner/rbac/station_scoped_identity_denials_apply_within_the_correct_role
    """
    ctx = setup_station()

    validate_error(
        api_client.create_public_file_document(
            ctx["station_id"], public_file_document_payload(), FOREIGN_ENGINEER
        ),
        ApiErrorId.ERR_ENGINEER_NOT_ASSIGNED,
    )

    station = validate_success(
        api_client.create_public_file_document(
            ctx["station_id"], public_file_document_payload(), ENGINEER
        ),
        201,
    )
    assert station["public_file_document_count"] == 1, (
        "only the rostered engineer's upload counted"
    )
    assert station_summary(ctx["station_id"])["public_file_document_count"] == 1


# ===========================================================================
# Segregation of duties: the per-user bar on self-certification
# ===========================================================================
def _dual_role_scope():
    """A station whose certifying officer also sits on the engineer roster.

    Returns the context of a READY test event on that station, ready for one log
    line and one filing.
    """
    ctx = setup_station(
        engineer_user_ids=[ENGINEER_USER_ID, DUAL_ROLE_USER_ID],
        certification_officer_user_id=DUAL_ROLE_USER_ID,
        call_sign=TEST_DEFAULTS["DUAL_ROLE_CALL_SIGN"],
    )
    event = schedule_test_event(
        ctx["station_id"], "2026-08-12T00:00:00Z", "2026-08-12T01:00:00Z"
    )
    set_clock("2026-08-12T00:10:00Z")
    ctx["test_event"] = evaluate_readiness(event["id"])
    ctx["test_event_id"] = event["id"]
    return ctx


def test_officer_cannot_file_a_test_whose_log_line_the_officer_wrote():
    """PRD §2.12: "A `CertifyingOfficer` filing post-test results must not be the same operator who produced any of the evidence: if the acting `X-User-ID` equals the `logged_by_user_id` recorded on **any** `TestLogEntry` belonging to that test event, the filing is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."
    PRD §2.1: "Nothing forbids the same opaque identifier from appearing both in `engineer_user_ids` and as `certification_officer_user_id` — that overlap is legal at station registration time and is precisely what makes the segregation-of-duties rule in §2.12 reachable."
    PRD §3.6: "An accepted line stamps `logged_at` from the logical clock and records the acting `X-User-ID` as `logged_by_user_id` — the value the segregation-of-duties check of §2.12 later compares against."

    Design: Corner/rbac/same_user_cannot_log_a_test_line_and_then_file_that_same_test
    """
    ctx = _dual_role_scope()
    event_id = ctx["test_event_id"]

    set_clock("2026-08-12T00:30:00Z")
    entry = validate_success(
        api_client.create_test_log_entry(
            make_test_log_entry_payload(
                event_id,
                ctx["device_id"],
                entry_kind="RECEIPT",
                source_call_sign=SOURCE_CALL_SIGNS["PEP"],
            ),
            DUAL_ENGINEER,
        ),
        201,
    )
    assert entry["logged_by_user_id"] == DUAL_ROLE_USER_ID, (
        "the line is legally written by an operator on the engineer roster"
    )
    get_success_data(api_client.close_logging(event_id, ENGINEER))

    event_version = read_test_event_version(event_id, DUAL_OFFICER)
    response = api_client.create_filing_record(
        filing_record_payload(event_id, event_version), DUAL_OFFICER
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    event = validate_success(api_client.get_test_event(event_id, ADMIN))
    assert event["status"] == "LOGGED", "the refused filing left the event LOGGED"
    assert event["version"] == event_version, (
        "the refused filing did not bump the test event's version"
    )
    _, meta = validate_paginated(api_client.list_filing_records(ADMIN))
    assert meta["total_count"] == 0, "no filing row exists after the 422"


def test_same_officer_files_a_test_event_logged_by_another_engineer():
    """PRD §2.12: "A `CertifyingOfficer` filing post-test results must not be the same operator who produced any of the evidence: if the acting `X-User-ID` equals the `logged_by_user_id` recorded on **any** `TestLogEntry` belonging to that test event, the filing is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."
    PRD §3.7: "A successful filing is stored in `SUBMITTED` with `reversal_reason` null, increments the event's `version` by one, and advances the event to `FILED`."

    Design: Corner/rbac/same_user_cannot_log_a_test_line_and_then_file_that_same_test
    """
    ctx = _dual_role_scope()
    event_id = ctx["test_event_id"]

    set_clock("2026-08-12T00:30:00Z")
    entry = append_log_entry(
        event_id,
        ctx["device_id"],
        "RECEIPT",
        headers=ENGINEER,
        source_call_sign=SOURCE_CALL_SIGNS["PEP"],
    )
    assert entry["logged_by_user_id"] == ENGINEER_USER_ID
    get_success_data(api_client.close_logging(event_id, ENGINEER))

    filing = validate_success(
        api_client.create_filing_record(
            filing_record_payload(event_id, read_test_event_version(event_id, DUAL_OFFICER)),
            DUAL_OFFICER,
        ),
        201,
    )
    assert filing["status"] == "SUBMITTED"
    assert filing["late_days"] == 0
    assert filing["penalty_points"] == pytest.approx(0.00, abs=0.01)
    assert filing["filed_by_user_id"] == DUAL_ROLE_USER_ID

    event = validate_success(api_client.get_test_event(event_id, ADMIN))
    assert event["status"] == "FILED", "the block is per test event, not per station"
