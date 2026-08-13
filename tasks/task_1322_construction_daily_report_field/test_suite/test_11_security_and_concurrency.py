"""RBAC denials, header context, optimistic concurrency, idempotent capture."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_crew_entry,
    add_tm_ticket,
    api_client,
    build_user_headers,
    create_incident_payload,
    create_quantity_entry_payload,
    get_report,
    get_success_data,
    make_active_project,
    make_project,
    make_report,
    make_report_bundle,
    make_under_review_report,
    make_work_area,
    make_work_item,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_PM = TEST_USERS["project_manager_headers"]
_SO = TEST_USERS["safety_officer_headers"]
_SUPT = TEST_USERS["superintendent_headers"]


class TestRoleDenials:
    def test_superintendent_cannot_approve_report(self, api):
        """PRD section 2.1: "an authenticated operator attempting an action
        outside their role is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        section 4: `/daily-reports/{id}/approve` is authorized for
        ProjectManager only.

        Design: Corner/rbac/superintendent_cannot_approve_report
        """
        ctx = make_under_review_report()
        rid = ctx["report"]["id"]

        resp = api_client.approve_report(
            rid, build_user_headers("pm-9", "Superintendent"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403
        assert get_report(rid)["status"] == "UNDER_REVIEW"

    def test_safety_officer_cannot_classify_delay(self, api):
        """PRD section 2.1: "an authenticated operator attempting an action
        outside their role is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        section 4: `/delay-events/{id}/classify` is authorized for
        ProjectManager only.

        Design: Corner/rbac/safety_officer_cannot_classify_delay
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        event_resp = api_client.create_delay_event(
            {"report_id": ctx["report"]["id"], "work_area_id": ctx["area"]["id"],
             "start_at": "2026-08-05T09:00:00Z", "end_at": "2026-08-05T10:00:00Z",
             "cause": "LABOR"},
            _SUPT)
        event = validate_success(event_resp, 201)

        resp = api_client.classify_delay_event(
            event["id"], {"classification": "NON_EXCUSABLE"}, _SO)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403
        assert api_client.get_delay_event(
            event["id"], _PM).json()["data"]["status"] == "RECORDED"

    def test_superintendent_cannot_create_safety_observation(self, api):
        """PRD section 2.1: "an authenticated operator attempting an action
        outside their role is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        section 4: `/safety-observations` is authorized for SafetyOfficer only.

        Design: Corner/rbac/superintendent_cannot_create_safety_observation
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)

        resp = api_client.create_safety_observation(
            {"report_id": ctx["report"]["id"], "work_area_id": ctx["area"]["id"],
             "description": "x", "risk_level": "LOW"},
            _SUPT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403

    def test_undeclared_role_rejected_as_bad_context(self, api):
        """PRD section 2.1: "A request missing either header, or carrying a role
        the system does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/missing_role_header_unauthenticated
        """
        project = make_project()

        resp = api_client.get_project(
            project["id"], {"X-User-ID": "test-norole",
                            "X-User-Role": "NoSuchRole",
                            "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400

        missing_role = api_client.get_project(
            project["id"], {"X-User-ID": "test-norole",
                            "Content-Type": "application/json"})
        validate_error(missing_role,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestOptimisticConcurrency:
    def test_report_header_edit_stale_version_conflict(self, api):
        """PRD section 2.7: "Editing a daily report's header requires the
        request to carry `expected_report_version`, holding the report
        `version` the client last observed. If that value does not equal the
        report's current `version` — because any child-entry write or transition
        has legitimately advanced the aggregate version in between — the edit is
        rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/report_header_put_stale_version_conflict
        """
        project = make_active_project()
        report = make_report(project["id"])
        v1 = report["version"]

        edited = validate_success(api_client.update_daily_report(
            report["id"],
            {"expected_report_version": v1, "general_notes": "first edit"},
            _SUPT))
        assert edited["version"] == v1 + 1

        stale = api_client.update_daily_report(
            report["id"],
            {"expected_report_version": v1, "general_notes": "stale edit"},
            _SUPT)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412

    def test_quantity_entry_create_with_stale_report_version(self, api):
        """PRD section 2.7: "Recording a quantity entry against a report
        likewise requires `expected_report_version` matching the report's
        current `version`. The create can legitimately supersede — that is,
        void — a prior active entry for the same report, work item, and work
        area, so a writer working from a stale snapshot must not silently void
        entries it never saw; a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/quantity_entry_create_stale_report_version
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        wi = make_work_item(project["id"], budgeted_quantity=100, unit="LF",
                            unit_cost_cents=1000)
        report = make_report(project["id"])
        v1 = report["version"]

        # Any child write advances the aggregate version, staling v1.
        add_crew_entry(report["id"], area["id"], worker_count=1)

        stale = api_client.create_quantity_entry(
            create_quantity_entry_payload(report["id"], wi["id"], area["id"],
                                          expected_report_version=v1,
                                          quantity_installed=5),
            _SUPT)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412

        fresh_version = get_report(report["id"])["version"]
        ok = validate_success(api_client.create_quantity_entry(
            create_quantity_entry_payload(report["id"], wi["id"], area["id"],
                                          expected_report_version=fresh_version,
                                          quantity_installed=5),
            _SUPT), 201)
        assert ok["status"] == "ACTIVE"

    def test_tm_ticket_put_reprices_and_stale_replay_conflicts(self, api):
        """PRD section 2.7: "Replacing the lines of a `DRAFT` T&M ticket
        requires `expected_ticket_version` matching the ticket's own current
        `version`. A prior edit has already repriced the ticket, so a stale
        writer's total and ceiling assumptions no longer hold; a mismatch is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/tm_ticket_put_reprice_and_stale_conflict
        """
        project = make_active_project()
        wi = make_work_item(project["id"], budgeted_quantity=500, unit="EA",
                            unit_cost_cents=100)
        report = make_report(project["id"])
        ticket = add_tm_ticket(report["id"], wi["id"], description="d",
                               labor_lines=[{"trade": "Labor", "worker_count": 1,
                                             "regular_hours": 2, "ot_hours": 0,
                                             "dt_hours": 0, "rate_cents": 100}])
        tv = ticket["version"]
        assert ticket["total_cents"] == 200

        edited = validate_success(api_client.update_tm_ticket(
            ticket["id"],
            {"expected_ticket_version": tv,
             "labor_lines": [{"trade": "Labor", "worker_count": 1,
                              "regular_hours": 2, "ot_hours": 0,
                              "dt_hours": 0, "rate_cents": 200}]},
            _SUPT))
        assert edited["total_cents"] == 400, "PUT repriced the doubled rate"
        assert edited["version"] == tv + 1

        stale = api_client.update_tm_ticket(
            ticket["id"],
            {"expected_ticket_version": tv, "description": "stale"},
            _SUPT)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412


class TestIdempotentCapture:
    def test_replay_returns_original_and_conflict_on_different_body(self, api):
        """PRD section 2.11: "Replaying the same key with an identical body
        returns the originally created resource rather than creating a second
        one; reusing the same key with a different body is rejected with
        `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409)."

        Design: Corner/cross_cutting_layers/idempotency_replay_and_conflict
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        report = make_report(project["id"])
        set_clock("2026-08-05T17:00:00Z")

        body = create_incident_payload(
            report["id"], area["id"], occurred_at="2026-08-05T09:00:00Z",
            severity="FIRST_AID", narrative="cut hand", idempotency_key="k-1")
        first = validate_success(api_client.create_incident(body, _SO), 201)

        replay = get_success_data(api_client.create_incident(dict(body), _SO))
        assert replay["id"] == first["id"], \
            "replay with identical body returns the original, no duplicate"

        different = api_client.create_incident(
            create_incident_payload(
                report["id"], area["id"], occurred_at="2026-08-05T10:00:00Z",
                severity="FIRST_AID", narrative="different body",
                idempotency_key="k-1"),
            _SO)
        validate_error(different, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)
        assert different.status_code == 409

        rows, meta = validate_paginated(api_client.list_incidents(
            _SO, params={"report_id": report["id"]}))
        assert meta["total_count"] == 1, "exactly one incident exists"
