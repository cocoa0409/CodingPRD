"""Monitoring calendar and field visits (PRD §3.2, §2.5)."""
from test_helpers import (
    ApiErrorId,
    complete_visit_payload,
    create_monitoring_visit_payload,
    create_recorded_easement,
    get_easement,
    make_field_monitor_headers,
    schedule_visit,
    set_clock,
    validate_error,
    validate_success,
)

COORD_ID = "coord-1"


def _get_visit(api, visit_id, headers):
    return validate_success(api.get_monitoring_visit(visit_id, headers), 200)


class TestVisitStateRules:
    def test_visit_complete_after_cancel_rejected(self, api, coordinator_headers,
                                                  trust_admin_headers):
        """PRD §3.2: "Completion enforces its checks in pipeline order: the visit
        must be `SCHEDULED`, else `ERR_INVALID_VISIT_STATE`"
        PRD §3.2: "A coordinator may also cancel a `SCHEDULED` visit, moving it
        to `CANCELLED`; attempting cancellation from any other state is rejected
        with `ERR_INVALID_VISIT_STATE`."

        Design: Corner/state_machines/visit_complete_after_cancel_rejected
        """
        ctx = create_recorded_easement(name="E-VC", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED"})
        visit = schedule_visit(ctx["easement"]["id"], monitor_user_id="mon-1",
                               window_start_on="2026-09-01", window_end_on="2026-09-10")
        validate_success(api.cancel_monitoring_visit(visit["id"], coordinator_headers), 200)

        resp = api.complete_monitoring_visit(
            visit["id"],
            complete_visit_payload(actual_visit_on="2026-09-05",
                                   stewardship_cost_cents=1000),
            make_field_monitor_headers("mon-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_VISIT_STATE)
        assert _get_visit(api, visit["id"], trust_admin_headers)["status"] == "CANCELLED"

    def test_complete_by_other_monitor_rejected(self, api, trust_admin_headers):
        """PRD §3.2: "the caller's `X-User-ID` must equal the visit's
        `monitor_user_id`, else `ERR_NOT_ASSIGNED_MONITOR`"
        PRD §2.11: "completing a monitoring visit is restricted to the visit's
        assigned `monitor_user_id` (`ERR_NOT_ASSIGNED_MONITOR`, 403)"

        Design: Corner/errors/complete_by_other_monitor_rejected
        """
        ctx = create_recorded_easement(name="E-NM", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED"})
        visit = schedule_visit(ctx["easement"]["id"], monitor_user_id="mon-1",
                               window_start_on="2026-09-01", window_end_on="2026-09-10")

        resp = api.complete_monitoring_visit(
            visit["id"],
            complete_visit_payload(actual_visit_on="2026-09-05",
                                   stewardship_cost_cents=1000),
            make_field_monitor_headers("mon-2"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_MONITOR)
        assert _get_visit(api, visit["id"], trust_admin_headers)["status"] == "SCHEDULED"

    def test_visit_complete_outside_window_rejected(self, api, trust_admin_headers):
        """PRD §3.2: "`actual_visit_on` must fall inside the planned window — on
        or after `window_start_on` and strictly before `window_end_on` — else
        `ERR_VISIT_OUTSIDE_WINDOW` (422)."

        Design: Corner/errors/visit_complete_outside_window_rejected
        """
        ctx = create_recorded_easement(name="E-OW", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED"})
        visit = schedule_visit(ctx["easement"]["id"], monitor_user_id="mon-1",
                               window_start_on="2026-09-01", window_end_on="2026-09-10")

        # 2026-09-10 equals window_end_on; the window end is exclusive.
        resp = api.complete_monitoring_visit(
            visit["id"],
            complete_visit_payload(actual_visit_on="2026-09-10",
                                   stewardship_cost_cents=1000),
            make_field_monitor_headers("mon-1"),
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_OUTSIDE_WINDOW)
        assert _get_visit(api, visit["id"], trust_admin_headers)["status"] == "SCHEDULED"


class TestCompletionCascade:
    def test_monitor_completion_updates_easement_derived_fields(self, api, trust_admin_headers):
        """PRD §3.2: "The easement's `last_monitoring_completed_on` then becomes
        `actual_visit_on`, and `next_monitoring_due_on` is recomputed as that
        completion date plus `monitoring_interval_months` months."
        PRD §3.2: "The completion finally recomputes the easement's `posture`
        and advances the easement's `version` by one, per §2.5."
        PRD §3.2: "the visit is on time when `actual_visit_on` is on or before
        the easement's `next_monitoring_due_on` — completing on the due date
        itself counts as on time, while completing one day later does not."

        Design: Corner/endpoints/monitor_completion_updates_easement_derived_fields
        """
        ctx = create_recorded_easement(name="E-MC", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED"},
                                       monitoring_interval_months=12)
        version_at_record = ctx["version"]
        visit = schedule_visit(ctx["easement"]["id"], monitor_user_id="mon-1",
                               window_start_on="2026-09-01", window_end_on="2026-09-10")

        completed = validate_success(
            api.complete_monitoring_visit(
                visit["id"],
                complete_visit_payload(actual_visit_on="2026-09-05",
                                       findings_summary="all quiet",
                                       stewardship_cost_cents=18000),
                make_field_monitor_headers("mon-1"),
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["on_time"] is True, "2026-09-05 <= due 2027-08-01"

        easement = get_easement(ctx["easement"]["id"])
        assert easement["last_monitoring_completed_on"] == "2026-09-05"
        assert easement["next_monitoring_due_on"] == "2027-09-05", (
            "due date recomputed from the completion date, not the record date"
        )
        assert easement["version"] == version_at_record + 1


class TestMonitoringDueBoundary:
    def test_monitoring_due_posture_boundary(self, api, trust_admin_headers):
        """PRD §2.5: "Failing that, it is `MONITORING_DUE` when the logical
        clock's date is strictly later than `next_monitoring_due_on` — on the due
        date itself the easement is not yet due. Otherwise it is
        `GOOD_STANDING`."

        Design: Corner/calculations/monitoring_due_posture_boundary
        """
        ctx = create_recorded_easement(name="E-MD", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED"},
                                       monitoring_interval_months=12)
        assert ctx["easement"]["next_monitoring_due_on"] == "2027-08-01"

        set_clock("2027-08-01T00:00:00Z")
        on_due = get_easement(ctx["easement"]["id"])
        assert on_due["posture"] == "GOOD_STANDING", "the due date itself is not yet due"

        set_clock("2027-08-02T00:00:00Z")
        past_due = get_easement(ctx["easement"]["id"])
        assert past_due["posture"] == "MONITORING_DUE", "strictly later than the due date flips posture"


class TestOnTimeInclusiveBoundary:
    def test_complete_on_due_date_is_on_time(self, api, trust_admin_headers):
        """PRD §3.2: "The visit's `on_time` flag is computed against the due date
        in force before this completion: the visit is on time when
        `actual_visit_on` is on or before the easement's
        `next_monitoring_due_on` — completing on the due date itself counts as on
        time, while completing one day later does not."
        PRD §3.2: "The easement's `last_monitoring_completed_on` then becomes
        `actual_visit_on`, and `next_monitoring_due_on` is recomputed as that
        completion date plus `monitoring_interval_months` months."

        Design: Difficulty/boundary_precision_check/monitoring_due_date_inclusive_boundary
        """
        ctx = create_recorded_easement(name="E-BM1", parcel_acreage=500,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"},
                                       monitoring_interval_months=12)
        assert ctx["easement"]["next_monitoring_due_on"] == "2027-08-01"
        set_clock("2027-07-20T00:00:00Z")
        visit = schedule_visit(ctx["easement"]["id"], monitor_user_id="mon-1",
                               window_start_on="2027-07-25", window_end_on="2027-08-08")

        completed = validate_success(
            api.complete_monitoring_visit(
                visit["id"],
                complete_visit_payload(actual_visit_on="2027-08-01",
                                       findings_summary="on due date",
                                       stewardship_cost_cents=25000),
                make_field_monitor_headers("mon-1"),
            ),
            200,
        )
        assert completed["on_time"] is True, "actual == due date is inclusive"

        easement = get_easement(ctx["easement"]["id"])
        assert easement["next_monitoring_due_on"] == "2028-08-01"

    def test_complete_one_day_after_due_is_late(self, api, trust_admin_headers):
        """PRD §3.2: "The visit's `on_time` flag is computed against the due date
        in force before this completion: the visit is on time when
        `actual_visit_on` is on or before the easement's
        `next_monitoring_due_on` — completing on the due date itself counts as on
        time, while completing one day later does not."

        Design: Difficulty/boundary_precision_check/monitoring_due_date_inclusive_boundary
        """
        ctx = create_recorded_easement(name="E-BM2", parcel_acreage=500,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"},
                                       monitoring_interval_months=12)
        assert ctx["easement"]["next_monitoring_due_on"] == "2027-08-01"
        set_clock("2027-07-20T00:00:00Z")
        visit = schedule_visit(ctx["easement"]["id"], monitor_user_id="mon-2",
                               window_start_on="2027-07-25", window_end_on="2027-08-08")

        completed = validate_success(
            api.complete_monitoring_visit(
                visit["id"],
                complete_visit_payload(actual_visit_on="2027-08-02",
                                       findings_summary="one day late",
                                       stewardship_cost_cents=25000),
                make_field_monitor_headers("mon-2"),
            ),
            200,
        )
        assert completed["on_time"] is False, "due date + 1 day is late"


class TestMonitorWindowOverlap:
    def test_monitor_window_adjacent_and_cancelled_allowed(self, api, coordinator_headers):
        """PRD §3.2: "Windows use half-open semantics, so one visit ending on the
        day another begins — the end of one equal to the start of the next —
        does not count as an overlap, and cancelled visits do not participate in
        the check at all."

        Design: Difficulty/resource_temporal_overlap/monitor_window_half_open_adjacency
        """
        ctx = create_recorded_easement(name="E-OV1", parcel_acreage=500,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        easement_id = ctx["easement"]["id"]
        first = schedule_visit(easement_id, monitor_user_id="mon-1",
                               window_start_on="2026-09-01", window_end_on="2026-09-10")

        # Adjacent half-open window: first end == second start touches without overlap.
        adjacent = validate_success(
            api.create_monitoring_visit(
                create_monitoring_visit_payload(
                    easement_id, monitor_user_id="mon-1",
                    window_start_on="2026-09-10", window_end_on="2026-09-20",
                ),
                coordinator_headers,
            ),
            201,
        )
        assert adjacent["status"] == "SCHEDULED"

        # Cancelled visits drop out of the check entirely.
        validate_success(api.cancel_monitoring_visit(adjacent["id"], coordinator_headers), 200)
        validate_success(api.cancel_monitoring_visit(first["id"], coordinator_headers), 200)
        third = validate_success(
            api.create_monitoring_visit(
                create_monitoring_visit_payload(
                    easement_id, monitor_user_id="mon-1",
                    window_start_on="2026-09-05", window_end_on="2026-09-12",
                ),
                coordinator_headers,
            ),
            201,
        )
        assert third["status"] == "SCHEDULED"

    def test_monitor_window_interior_overlap_rejected(self, api, coordinator_headers):
        """PRD §3.2: "A monitor may not hold overlapping commitments: if the new
        window intersects another `SCHEDULED` or `COMPLETED` visit assigned to
        the same `monitor_user_id`, creation is rejected with
        `ERR_MONITOR_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/monitor_window_half_open_adjacency
        """
        ctx = create_recorded_easement(name="E-OV1B", parcel_acreage=500,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        easement_id = ctx["easement"]["id"]
        schedule_visit(easement_id, monitor_user_id="mon-1",
                       window_start_on="2026-09-01", window_end_on="2026-09-10")

        resp = api.create_monitoring_visit(
            create_monitoring_visit_payload(
                easement_id, monitor_user_id="mon-1",
                window_start_on="2026-09-09", window_end_on="2026-09-11",
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MONITOR_WINDOW_OVERLAP)
