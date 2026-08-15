"""Scheduling battery: technician half-open overlap, vessel 2-hour downtime buffer,
window-in-past, credit hold, and validation priority."""
import pytest

from test_helpers import (
    ApiErrorId,
    make_plant_operator_headers,
    make_technician_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_approved_ticket,
    create_draft_permit,
    create_scheduled_ticket,
    create_site,
    create_site_vessel_technician,
    create_technician,
    create_vessel,
    create_vessel_with_dispatched_order,
    post_scale_calibration,
)
from test_helpers.test_users import TEST_USERS

SM = TEST_USERS["service_manager_headers"]
SO = TEST_USERS["safety_officer_headers"]


def _three_approved_tickets(site, vessels):
    return [
        create_approved_ticket(
            site["id"], v["id"],
            job_type="INSPECTION", requires_entry=False, est_hours=2, crew_size=1,
        )
        for v in vessels
    ]


class TestTechnicianWindowOverlap:
    def _setup(self):
        site = create_site(name="Site Fourteen", state_code="OK")
        vr = create_vessel(site["id"], name="SILO-R", capacity_tons=100,
                           material_name="rice", reorder_point_pct=30)
        vs = create_vessel(site["id"], name="SILO-S", capacity_tons=100,
                           material_name="rice", reorder_point_pct=30)
        vt = create_vessel(site["id"], name="SILO-T", capacity_tons=100,
                           material_name="rice", reorder_point_pct=30)
        tech = create_technician(name="Tech Nine", weekly_capacity_hours=40)
        tr, ts, tt = _three_approved_tickets(site, [vr, vs, vt])
        validate_success(
            api_client_schedule(tr, tech),
            200,
        )
        return site, tech, tr, ts, tt

    def test_adjacent_window_is_allowed(self, api):
        """PRD §3.7: "The technician must not already occupy a half-open-overlapping
        window on another ticket in `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD`
        status; adjacency is permitted, but any positive overlap is rejected with
        `ERR_TECHNICIAN_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/technician_window_half_open_overlap
        """
        site, tech, tr, ts, tt = self._setup()
        scheduled = validate_success(
            api.schedule_service_ticket(
                ts["id"],
                {
                    "technician_id": tech["id"],
                    "window_start": "2026-08-10T12:00:00Z",
                    "window_end": "2026-08-10T15:00:00Z",
                },
                SM,
            ),
            200,
        )
        # half-open semantics: 12:00 start exactly at the 09:00-12:00 end is adjacent
        assert scheduled["status"] == "SCHEDULED"

    def test_overlapping_window_rejected_double_booked(self, api):
        """PRD §3.7: "The technician must not already occupy a half-open-overlapping
        window on another ticket in `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD`
        status; adjacency is permitted, but any positive overlap is rejected with
        `ERR_TECHNICIAN_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/technician_window_half_open_overlap
        """
        site, tech, tr, ts, tt = self._setup()
        res = api.schedule_service_ticket(
            tt["id"],
            {
                "technician_id": tech["id"],
                "window_start": "2026-08-10T11:30:00Z",
                "window_end": "2026-08-10T13:00:00Z",
            },
            SM,
        )
        validate_error(
            res, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED, expected_status=409
        )
        fetched = validate_success(api.get_service_ticket(tt["id"], SM), 200)
        assert fetched["status"] == "APPROVED"


def api_client_schedule(ticket, tech):
    from test_helpers import api_client

    return api_client.schedule_service_ticket(
        ticket["id"],
        {
            "technician_id": tech["id"],
            "window_start": "2026-08-10T09:00:00Z",
            "window_end": "2026-08-10T12:00:00Z",
        },
        SM,
    )


class TestVesselDowntimeBuffer:
    def _setup(self):
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "Site Fifteen", "state_code": "OK"},
            vessel_overrides={
                "name": "SILO-U", "capacity_tons": 100, "material_name": "soy",
                "reorder_point_pct": 30,
            },
            tech_overrides={"name": "Tech Ten", "weekly_capacity_hours": 40},
        )
        t15a = create_scheduled_ticket(
            site["id"], vessel["id"], tech["id"],
            window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T10:00:00Z",
            job_type="INSPECTION", requires_entry=False, est_hours=2, crew_size=1,
        )
        t15b = create_approved_ticket(
            site["id"], vessel["id"],
            job_type="CLEANOUT", requires_entry=True, est_hours=4, crew_size=1,
        )
        return site, vessel, tech, t15a, t15b

    def test_permit_window_inside_two_hour_buffer_rejected(self, api):
        """PRD §3.7: "The vessel must observe a 2-hour downtime buffer against every
        other occupied downtime interval on the same vessel — that is, every other
        ticket's window whose status is `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD`,
        and every `EntryPermit` window whose status is `DRAFT`, `ISSUED`, `ACTIVE`,
        or `SUSPENDED`, excluding any interval that shares this ticket's `id`. The
        gap from this window to each such interval must be at least 2 hours on both
        sides; a closer interval is rejected with `ERR_VESSEL_DOWNTIME_CONFLICT`."
        PRD §3.8: "The permit's window joins the vessel's downtime calendar — the
        same 2-hour buffer rule of §3.7 applies at draft time, evaluated against
        other tickets' occupied windows and other permits' windows, exempting any
        interval that shares the same `ticket_id`."

        Design: Difficulty/resource_temporal_overlap/vessel_downtime_two_hour_buffer
        """
        site, vessel, tech, t15a, t15b = self._setup()
        res = api.create_entry_permit(
            {
                "vessel_id": vessel["id"],
                "ticket_id": t15b["id"],
                "entrant_technician_id": tech["id"],
                "window_start": "2026-08-10T10:30:00Z",
                "window_end": "2026-08-10T12:00:00Z",
            },
            SO,
        )
        # 0.5 h gap < 2 h buffer
        validate_error(
            res, ApiErrorId.ERR_VESSEL_DOWNTIME_CONFLICT, expected_status=409
        )

    def test_permit_window_exactly_two_hours_gap_accepted(self, api):
        """PRD §3.7: "The gap from this window to each such interval must be at
        least 2 hours on both sides; a closer interval is rejected with
        `ERR_VESSEL_DOWNTIME_CONFLICT`."
        PRD §3.8: "The permit's window joins the vessel's downtime calendar — the
        same 2-hour buffer rule of §3.7 applies at draft time, evaluated against
        other tickets' occupied windows and other permits' windows, exempting any
        interval that shares the same `ticket_id`."

        Design: Difficulty/resource_temporal_overlap/vessel_downtime_two_hour_buffer
        """
        site, vessel, tech, t15a, t15b = self._setup()
        res = api.create_entry_permit(
            {
                "vessel_id": vessel["id"],
                "ticket_id": t15b["id"],
                "entrant_technician_id": tech["id"],
                "window_start": "2026-08-10T12:00:00Z",
                "window_end": "2026-08-10T14:00:00Z",
            },
            SO,
        )
        # gap exactly 2 h (>= semantics) is accepted
        permit = validate_success(res, 201)
        assert permit["status"] == "DRAFT"

        from test_helpers import validate_paginated

        data, meta = validate_paginated(
            api.list_entry_permits(SM, params={"ticket_id": t15b["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == permit["id"]


class TestSchedulePriorityAndCreditHold:
    def _setup(self):
        site_a = create_site(name="Site A", state_code="KS")
        site_b = create_site(name="Site B", state_code="KS", credit_hold=True)
        vla = create_vessel(site_a["id"], name="SILO-A1", capacity_tons=100,
                            material_name="corn", reorder_point_pct=30)
        vlb = create_vessel(site_b["id"], name="SILO-B1", capacity_tons=100,
                            material_name="corn", reorder_point_pct=30)
        tech = create_technician(name="Tech Six", weekly_capacity_hours=40)
        ta = create_scheduled_ticket(
            site_a["id"], vla["id"], tech["id"],
            window_start="2026-08-10T09:00:00Z",
            window_end="2026-08-10T12:00:00Z",
            job_type="INSPECTION", requires_entry=False, est_hours=2, crew_size=1,
        )
        tb = create_approved_ticket(
            site_b["id"], vlb["id"],
            job_type="INSPECTION", requires_entry=False, est_hours=2, crew_size=1,
        )
        return site_a, site_b, tech, ta, tb

    def test_double_booking_beats_credit_hold(self, api):
        """PRD §2.10: "Only after the body is well-formed does role-based
        authorization run (`ERR_FORBIDDEN`), then existence of every referenced
        resource (the appropriate `ERR_*_NOT_FOUND`), then the OCC check
        `ERR_STALE_VERSION` where applicable, then state-machine from-state
        validation (`ERR_INVALID_TICKET_STATE`, `ERR_INVALID_ORDER_STATE`,
        `ERR_INVALID_PERMIT_STATE`), then the bin-entry safety cluster (lockout,
        segregation of duties, engulfment control, atmosphere limits, entry-permit
        presence), then the temporal/scheduling cluster (window-in-past, technician
        double-booking, vessel downtime buffer, scale tolerance, inventory
        non-negativity), and finally the fiscal gate (`ERR_CREDIT_HOLD`)."

        Design: Difficulty/priority_pair_validation_conflict/schedule_double_booking_beats_credit_hold
        """
        site_a, site_b, tech, ta, tb = self._setup()
        res = api.schedule_service_ticket(
            tb["id"],
            {
                "technician_id": tech["id"],
                "window_start": "2026-08-10T11:00:00Z",
                "window_end": "2026-08-10T13:00:00Z",
            },
            SM,
        )
        # temporal cluster (double-booking) fires before the fiscal gate
        validate_error(
            res, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED, expected_status=409
        )
        fetched = validate_success(api.get_service_ticket(tb["id"], SM), 200)
        assert fetched["status"] == "APPROVED"

    def test_free_window_on_held_site_surfaces_credit_hold(self, api):
        """PRD §2.10: "This ordering guarantees, for example, that a mid-flight
        credit hold surfaces as `ERR_CREDIT_HOLD` only after the request has
        already passed every structural and safety check, and that a stale
        `expected_vessel_version` always masks any later business rule."
        PRD §3.7: "Finally, the site's `credit_hold` must be false; otherwise the
        schedule is rejected with `ERR_CREDIT_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_double_booking_beats_credit_hold
        """
        site_a, site_b, tech, ta, tb = self._setup()
        res = api.schedule_service_ticket(
            tb["id"],
            {
                "technician_id": tech["id"],
                "window_start": "2026-08-10T13:00:00Z",
                "window_end": "2026-08-10T15:00:00Z",
            },
            SM,
        )
        # non-overlapping window: only the fiscal gate can fire
        validate_error(res, ApiErrorId.ERR_CREDIT_HOLD, expected_status=409)
        fetched = validate_success(api.get_service_ticket(tb["id"], SM), 200)
        assert fetched["status"] == "APPROVED"


class TestWindowInPast:
    def test_schedule_window_in_past_rejected(self, api):
        """PRD §3.7: "The window must be strictly in the future — `window_end` must
        be strictly after `window_start`, and `window_start` must be strictly after
        the current logical clock — otherwise `ERR_WINDOW_IN_PAST`."
        PRD §2.11: "At startup the clock is exactly `2026-08-01T00:00:00Z`. A
        `ServiceManager` may advance it via the clock-set capability, supplying a
        `to_iso8601` timestamp."

        Design: Corner/validations/schedule_window_in_past_rejected
        """
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "WP Site", "state_code": "IA"},
            vessel_overrides={
                "name": "BIN-WP", "vessel_kind": "BIN", "capacity_tons": 50,
                "material_name": "salt", "reorder_point_pct": 30,
            },
            tech_overrides={"name": "Tech W", "weekly_capacity_hours": 40},
        )
        ticket = create_approved_ticket(
            site["id"], vessel["id"],
            job_type="INSPECTION", requires_entry=False, est_hours=2, crew_size=1,
        )
        validate_success(
            api.set_clock({"to_iso8601": "2026-08-10T00:00:00Z"}, SM), 200
        )
        res = api.schedule_service_ticket(
            ticket["id"],
            {
                "technician_id": tech["id"],
                "window_start": "2026-08-09T08:00:00Z",
                "window_end": "2026-08-09T10:00:00Z",
            },
            SM,
        )
        validate_error(res, ApiErrorId.ERR_WINDOW_IN_PAST, expected_status=409)
        fetched = validate_success(api.get_service_ticket(ticket["id"], SM), 200)
        assert fetched["status"] == "APPROVED"


class TestReceiveBlockedByScale:
    def _setup_out_of_tolerance_with_dispatched_order(self):
        site, vessel, order, _ = create_vessel_with_dispatched_order(
            site_overrides={"name": "Site Thirteen", "state_code": "NE"},
            vessel_overrides={
                "name": "SILO-Q", "capacity_tons": 100, "material_name": "barley",
                "reorder_point_pct": 30, "target_fill_pct": 90,
                "error_basis": "OF_READING",
            },
        )
        tech = create_technician(name="Tech Eight", weekly_capacity_hours=40)
        # Failing calibration: 0.300 pct > 0.25 -> OUT_OF_TOLERANCE
        post_scale_calibration(
            vessel["id"], tech["id"],
            tested_at="2026-08-02T12:00:00Z",
            test_weight_tons=20.0, indicated_tons=20.06,
        )
        return site, vessel, tech, order

    def test_receive_blocked_by_out_of_tolerance_scale(self, api):
        """PRD §2.5: "Receiving a replenishment order against a vessel whose
        `scale_status` is `OUT_OF_TOLERANCE` is rejected with
        `ERR_SCALE_OUT_OF_TOLERANCE` (HTTP 409) — an out-of-tolerance load-out
        scale is treated as a hard receiving block."

        Design: Difficulty/cross_entity_state_dependency/receive_blocked_by_out_of_tolerance_scale
        """
        site, vessel, tech, order = (
            self._setup_out_of_tolerance_with_dispatched_order()
        )
        res = api.receive_replenishment_order(
            order["id"],
            {"delivered_tons": 10.0, "received_at": "2026-08-03T00:00:00Z"},
            make_technician_headers(tech["id"]),
        )
        validate_error(
            res, ApiErrorId.ERR_SCALE_OUT_OF_TOLERANCE, expected_status=409
        )
        fetched_order = validate_success(
            api.get_replenishment_order(order["id"], SM), 200
        )
        assert fetched_order["status"] == "DISPATCHED"
        fetched_vessel = validate_success(api.get_vessel(vessel["id"], SM), 200)
        assert fetched_vessel["current_inventory_tons"] == pytest.approx(
            25.0, abs=1e-9
        )

    def test_scale_status_out_of_tolerance_set_by_failing_calibration(self, api):
        """PRD §2.5: "A pass sets `scale_status` to `IN_TOLERANCE`; a failure sets
        it to `OUT_OF_TOLERANCE`."
        PRD §3.4: "Under `OF_READING`, the error is the difference between
        `indicated_tons` and `test_weight_tons`, divided by `test_weight_tons`,
        multiplied by 100 — error expressed relative to the applied test weight."

        Design: Difficulty/cross_entity_state_dependency/receive_blocked_by_out_of_tolerance_scale
        """
        site, vessel, tech, order = (
            self._setup_out_of_tolerance_with_dispatched_order()
        )
        fetched_vessel = validate_success(api.get_vessel(vessel["id"], SM), 200)
        assert fetched_vessel["scale_status"] == "OUT_OF_TOLERANCE"
