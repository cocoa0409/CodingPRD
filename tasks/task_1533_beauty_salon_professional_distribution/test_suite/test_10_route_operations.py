"""Route plans and stops: buffer rule, territory rule, publish gates, stop
lifecycle cycles, and consultant ownership (PRD §3.10)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_route_stop,
    create_published_plan,
    create_route_plan,
    make_consultant,
    make_sales_consultant_headers,
    make_salon,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

D = "2026-08-10"  # route windows are future wall dates; the buffer rule is
# evaluated between stops, independent of the logical clock.


class TestStopBufferRule:
    def test_zero_gap_stop_rejected(self, api):
        """PRD §3.10: "Two constraints guard stop creation, in pipeline order:
        adjacent non-`CANCELLED` stops on the same plan, sorted by `start_at`,
        must keep at least a 30-minute gap between one stop's `end_at` and the
        next stop's `start_at` — a violation is
        `ERR_ROUTE_STOP_BUFFER_VIOLATION` (HTTP 409), checked for the new stop
        against all siblings"

        Design: Difficulty/resource_temporal_overlap/route_stop_thirty_minute_buffer
        """
        consultant = make_consultant()
        s1 = make_salon(legal_name="Salon Q1", consultant=consultant)
        s2 = make_salon(legal_name="Salon Q2", consultant=consultant)
        plan = create_route_plan(consultant["id"], name="Monday Route")
        add_route_stop(plan["id"], s1["id"],
                       f"{D}T09:00:00Z", f"{D}T10:00:00Z", consultant["id"])

        resp = api.add_route_stop(
            plan["id"],
            {"salon_account_id": s2["id"],
             "start_at": f"{D}T10:00:00Z", "end_at": f"{D}T11:00:00Z"},
            make_sales_consultant_headers(consultant["id"]))
        validate_error(resp, ApiErrorId.ERR_ROUTE_STOP_BUFFER_VIOLATION)

    def test_thirty_minute_gap_stop_accepted(self, api):
        """PRD §3.10: "Two constraints guard stop creation, in pipeline order:
        adjacent non-`CANCELLED` stops on the same plan, sorted by `start_at`,
        must keep at least a 30-minute gap between one stop's `end_at` and the
        next stop's `start_at` — a violation is
        `ERR_ROUTE_STOP_BUFFER_VIOLATION` (HTTP 409), checked for the new stop
        against all siblings"

        Design: Difficulty/resource_temporal_overlap/route_stop_thirty_minute_buffer
        """
        consultant = make_consultant()
        s1 = make_salon(legal_name="Salon Q1", consultant=consultant)
        s2 = make_salon(legal_name="Salon Q2", consultant=consultant)
        plan = create_route_plan(consultant["id"], name="Monday Route")
        add_route_stop(plan["id"], s1["id"],
                       f"{D}T09:00:00Z", f"{D}T10:00:00Z", consultant["id"])

        stop = validate_success(api.add_route_stop(
            plan["id"],
            {"salon_account_id": s2["id"],
             "start_at": f"{D}T10:30:00Z", "end_at": f"{D}T11:30:00Z"},
            make_sales_consultant_headers(consultant["id"])), 201)
        assert stop["status"] == "SCHEDULED"


class TestStopCreationRules:
    def test_route_stop_window_inverted_returns_400(self, api):
        """PRD §3.10: "Stops are added to a `DRAFT` plan with a
        `salon_account_id`, a `start_at`, and an `end_at` strictly after
        `start_at` (`ERR_INVALID_TIME_WINDOW` otherwise)."

        Design: Corner/validations/route_stop_window_inverted_returns_400
        """
        consultant = make_consultant()
        salon = make_salon(legal_name="Salon 25", consultant=consultant)
        plan = create_route_plan(consultant["id"], name="Route 25")

        resp = api.add_route_stop(
            plan["id"],
            {"salon_account_id": salon["id"],
             "start_at": "2026-08-18T10:00:00Z",
             "end_at": "2026-08-18T10:00:00Z"},
            make_sales_consultant_headers(consultant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)

    def test_consultant_territory_mismatch_on_stop(self, api):
        """PRD §3.10: "the stop's salon territory must appear in the plan
        consultant's `territory_codes` — a violation is
        `ERR_CONSULTANT_TERRITORY_MISMATCH` (HTTP 422)."

        Design: Corner/validations/consultant_territory_mismatch_on_stop
        """
        consultant = make_consultant(territory_codes=["CA"])
        ny_salon = make_salon(territory_code="NY", legal_name="Salon 26",
                              consultant=consultant)
        plan = create_route_plan(consultant["id"], name="Route 26")

        resp = api.add_route_stop(
            plan["id"],
            {"salon_account_id": ny_salon["id"],
             "start_at": "2026-08-18T09:00:00Z",
             "end_at": "2026-08-18T10:00:00Z"},
            make_sales_consultant_headers(consultant["id"]))
        validate_error(resp, ApiErrorId.ERR_CONSULTANT_TERRITORY_MISMATCH)


class TestPlanAndStopLifecycle:
    def test_route_plan_autocompletes_when_all_stops_terminal(self, api):
        """PRD §3.10: "Completing or cancelling a stop bubbles up: when every
        stop of the plan is terminal and at least one is `COMPLETED`, the plan
        moves `PUBLISHED` → `COMPLETED`."
        PRD §3.10: "On a published plan, a stop can be completed — stamping
        `visited_at` with the logical clock"

        Design: Corner/state_machines/route_plan_autocompletes_when_all_stops_terminal
        """
        consultant = make_consultant()
        salon = make_salon(legal_name="Salon 5", consultant=consultant)
        plan, stops = create_published_plan(
            consultant["id"],
            [(salon["id"], "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z")])

        completed = validate_success(api.complete_route_stop(
            stops[0]["id"], make_sales_consultant_headers(consultant["id"])), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["visited_at"] is not None

        plan_after = validate_success(api.get_route_plan(plan["id"], ADMIN), 200)
        assert plan_after["status"] == "COMPLETED", (
            "the only stop completing bubbles the plan up to COMPLETED")

    def test_route_stop_no_show_reschedule_cycle(self, api):
        """PRD §3.10: "On a published plan, a stop can be completed — stamping
        `visited_at` with the logical clock — marked `NO_SHOW`, rescheduled
        from `NO_SHOW` back to `SCHEDULED` with a replacement
        `start_at`/`end_at` window that re-passes the 30-minute buffer rule
        against all non-`CANCELLED` siblings, or cancelled from either
        `SCHEDULED` or `NO_SHOW`."

        Design: Corner/state_machines/route_stop_no_show_reschedule_cycle
        """
        consultant = make_consultant()
        s1 = make_salon(legal_name="Salon 6a", consultant=consultant)
        s2 = make_salon(legal_name="Salon 6b", consultant=consultant)
        plan, stops = create_published_plan(consultant["id"], [
            (s1["id"], "2026-08-11T12:00:00Z", "2026-08-11T13:00:00Z"),
            (s2["id"], "2026-08-11T14:00:00Z", "2026-08-11T15:00:00Z"),
        ])
        validate_success(api.no_show_route_stop(
            stops[1]["id"], make_sales_consultant_headers(consultant["id"])), 200)

        rescheduled = validate_success(api.reschedule_route_stop(
            stops[1]["id"],
            {"start_at": "2026-08-11T13:30:00Z",
             "end_at": "2026-08-11T14:30:00Z"},
            make_sales_consultant_headers(consultant["id"])), 200)
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["start_at"].startswith("2026-08-11T13:30:00"), (
            "the replacement window re-passes the 30-minute buffer against "
            "the 12:00-13:00 sibling")

        plan_after = validate_success(api.get_route_plan(plan["id"], ADMIN), 200)
        assert plan_after["status"] == "PUBLISHED"

    def test_unpublish_rejected_after_a_stop_completed(self, api):
        """PRD §3.10: "Unpublishing returns a `PUBLISHED` plan to `DRAFT` only
        while no stop of the plan is `COMPLETED`
        (`ERR_INVALID_ROUTE_PLAN_STATE` otherwise)."

        Design: Corner/state_machines/unpublish_rejected_after_a_stop_completed
        """
        consultant = make_consultant()
        s1 = make_salon(legal_name="Salon 10a", consultant=consultant)
        s2 = make_salon(legal_name="Salon 10b", consultant=consultant)
        plan, stops = create_published_plan(consultant["id"], [
            (s1["id"], "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z"),
            (s2["id"], "2026-08-12T10:30:00Z", "2026-08-12T11:30:00Z"),
        ])
        validate_success(api.complete_route_stop(
            stops[0]["id"], make_sales_consultant_headers(consultant["id"])), 200)

        resp = api.unpublish_route_plan(
            plan["id"], make_sales_consultant_headers(consultant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_ROUTE_PLAN_STATE)
        plan_after = validate_success(api.get_route_plan(plan["id"], ADMIN), 200)
        assert plan_after["status"] == "PUBLISHED", (
            "one stop still SCHEDULED: no auto-complete, and no unpublish")

    def test_add_stop_to_published_plan_rejected(self, api):
        """PRD §3.10: "Stops are added to a `DRAFT` plan with a
        `salon_account_id`, a `start_at`, and an `end_at` strictly after
        `start_at` (`ERR_INVALID_TIME_WINDOW` otherwise)."
        PRD §2.8: "**State legality** — the target entity sits in a valid
        from-state for the requested transition, yielding the entity-specific
        invalid-state error (409)."

        Design: Corner/state_machines/add_stop_to_published_plan_rejected
        """
        consultant = make_consultant()
        s1 = make_salon(legal_name="Salon 11a", consultant=consultant)
        s2 = make_salon(legal_name="Salon 11b", consultant=consultant)
        plan, _ = create_published_plan(
            consultant["id"],
            [(s1["id"], "2026-08-13T09:00:00Z", "2026-08-13T10:00:00Z")])

        resp = api.add_route_stop(
            plan["id"],
            {"salon_account_id": s2["id"],
             "start_at": "2026-08-13T11:00:00Z",
             "end_at": "2026-08-13T12:00:00Z"},
            make_sales_consultant_headers(consultant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_ROUTE_PLAN_STATE)

    def test_publish_plan_without_stops_rejected(self, api):
        """PRD §3.10: "Publishing requires the plan to be `DRAFT`, to hold at
        least one `SCHEDULED` stop, and to belong to an `ACTIVE` consultant —
        violations surface as `ERR_INVALID_ROUTE_PLAN_STATE` or, for the
        consultant condition, `ERR_INVALID_CONSULTANT_STATE` (HTTP 409)."

        Design: Corner/state_machines/publish_plan_without_stops_rejected
        """
        consultant = make_consultant()
        plan = create_route_plan(consultant["id"], name="Empty Route")

        resp = api.publish_route_plan(
            plan["id"], make_sales_consultant_headers(consultant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_ROUTE_PLAN_STATE)

    def test_publish_plan_with_inactive_consultant_rejected(self, api):
        """PRD §3.10: "Publishing requires the plan to be `DRAFT`, to hold at
        least one `SCHEDULED` stop, and to belong to an `ACTIVE` consultant —
        violations surface as `ERR_INVALID_ROUTE_PLAN_STATE` or, for the
        consultant condition, `ERR_INVALID_CONSULTANT_STATE` (HTTP 409)."

        Design: Corner/state_machines/publish_plan_with_inactive_consultant_rejected
        """
        consultant = make_consultant()
        salon = make_salon(legal_name="Salon 13", consultant=consultant)
        plan = create_route_plan(consultant["id"], name="Route 13")
        add_route_stop(plan["id"], salon["id"],
                       "2026-08-14T09:00:00Z", "2026-08-14T10:00:00Z",
                       consultant["id"])
        validate_success(api.update_sales_consultant(
            consultant["id"], {"status": "INACTIVE"}, ADMIN), 200)

        resp = api.publish_route_plan(
            plan["id"], make_sales_consultant_headers(consultant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CONSULTANT_STATE)

    def test_complete_no_show_stop_rejected(self, api):
        """PRD §3.10: "Stop actions require the stop to be in the matching
        from-state (`ERR_INVALID_ROUTE_STOP_STATE`) and the owning plan to be
        `PUBLISHED` (`ERR_INVALID_ROUTE_PLAN_STATE` — stop actions on a
        `DRAFT` plan are rejected)."

        Design: Corner/state_machines/complete_no_show_stop_rejected
        """
        consultant = make_consultant()
        salon = make_salon(legal_name="Salon 17", consultant=consultant)
        plan, stops = create_published_plan(
            consultant["id"],
            [(salon["id"], "2026-08-17T09:00:00Z", "2026-08-17T10:00:00Z")])
        validate_success(api.no_show_route_stop(
            stops[0]["id"], make_sales_consultant_headers(consultant["id"])), 200)

        resp = api.complete_route_stop(
            stops[0]["id"], make_sales_consultant_headers(consultant["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_ROUTE_STOP_STATE)
        after = validate_success(api.get_route_stop(stops[0]["id"], ADMIN), 200)
        assert after["status"] == "NO_SHOW"


class TestConsultantRouteOwnership:
    def test_consultant_cannot_publish_other_consultants_route(self, api):
        """PRD §2.1: "When `X-User-Role` is `SalesConsultant`, `X-User-ID` is
        the `id` of the acting `SalesConsultant`; ownership checks on any
        resource that references a `SalesConsultant` compare the resource's
        consultant field to `X-User-ID` — a consultant manages only route
        plans and stops whose `sales_consultant_id` equals `X-User-ID`."
        PRD §2.1: "Ownership violations by entity-backed callers are rejected
        with `ERR_FORBIDDEN_RESOURCE` (HTTP 403)."

        Design: Corner/rbac/consultant_cannot_publish_other_consultants_route
        """
        consultant_a = make_consultant(full_name="C 44A")
        consultant_b = make_consultant(full_name="C 44B")
        salon = make_salon(legal_name="Salon 44", consultant=consultant_a)
        plan = create_route_plan(consultant_a["id"], name="Route 44")
        add_route_stop(plan["id"], salon["id"],
                       "2026-08-19T09:00:00Z", "2026-08-19T10:00:00Z",
                       consultant_a["id"])

        resp = api.publish_route_plan(
            plan["id"], make_sales_consultant_headers(consultant_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE)
        plan_after = validate_success(api.get_route_plan(plan["id"], ADMIN), 200)
        assert plan_after["status"] == "DRAFT"
