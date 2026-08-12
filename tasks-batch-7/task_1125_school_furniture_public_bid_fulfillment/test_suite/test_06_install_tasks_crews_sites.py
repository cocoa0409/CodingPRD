"""Install tasks: half-open occupancy, crew double-booking, site capacity,
crew booking ledger, and the verification cascade (PRD §2.1, §2.10, §3.6)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, assert_crew_booking_invariant,
    make_crew_lead_headers, validate_error, validate_success, add_accepted_po,
    build_accepted_award_context, complete_task, create_crew, create_shipment,
    create_task, deliver_shipment, get_crew, get_po, get_po_line, set_clock,
    ship_and_deliver, start_task,
)

FC = TEST_USERS["fulfillment_coordinator_headers"]


def _delivered_ctx(api, ordered_qty=10, site_capacity=5):
    """Accepted award + PO with one line; shipment delivered; crew available."""
    ctx = build_accepted_award_context(site_capacity=site_capacity)
    po, lines = add_accepted_po(ctx, line_qtys=(ordered_qty,))
    shipment = create_shipment(
        po["id"], ctx["site"]["id"],
        [{"po_line_id": lines[0]["id"], "qty": ordered_qty}],
        scheduled_date="2026-07-01")
    deliver_shipment(shipment["id"], [{
        "po_line_id": lines[0]["id"], "delivered_qty": ordered_qty,
        "manufacturer": "Acme", "model": "Desk-100",
    }])
    return ctx, po, lines, shipment


class TestCrewDoubleBooking:
    def test_crew_adjacent_tasks_allowed_overlap_rejected(self, api):
        """PRD §3.6: "no two non-`CANCELLED` tasks of the same crew may have
        overlapping half-open intervals — adjacency, where one task's `end_date`
        equals the next task's `start_date`, is allowed — and a violation is
        `ERR_CREW_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/crew_double_booking_half_open_adjacency_allowed_overlap_rejected
        """
        ctx, _po, _lines, shipment = _delivered_ctx(api)
        crew_id = ctx["crew"]["id"]
        site_id = ctx["site"]["id"]

        t1 = create_task(shipment["id"], crew_id, site_id,
                         start_date="2026-07-06", end_date="2026-07-08", room_label="W-1")
        t2 = validate_success(api.create_install_task(
            {"shipment_id": shipment["id"], "crew_id": crew_id, "school_site_id": site_id,
             "room_label": "W-2", "start_date": "2026-07-08", "end_date": "2026-07-10",
             "crew_count": 1}, FC), 201)
        assert t2["status"] == "SCHEDULED"

        resp = api.create_install_task(
            {"shipment_id": shipment["id"], "crew_id": crew_id, "school_site_id": site_id,
             "room_label": "W-3", "start_date": "2026-07-09", "end_date": "2026-07-11",
             "crew_count": 1}, FC)
        validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)
        assert_crew_booking_invariant(get_crew(crew_id), 4)

    def test_crew_overlap_on_shared_date_rejected(self, api):
        """PRD §3.6: "The occupation interval is half-open: the task occupies every
        date from `start_date` up to but not including `end_date`, so `end_date`
        must be strictly later than `start_date`."
        PRD §3.6: "no two non-`CANCELLED` tasks of the same crew may have
        overlapping half-open intervals"

        Design: Difficulty/resource_temporal_overlap/crew_double_booking_half_open_adjacency_allowed_overlap_rejected
        """
        ctx, _po, _lines, shipment = _delivered_ctx(api)
        crew_id = ctx["crew"]["id"]
        site_id = ctx["site"]["id"]

        create_task(shipment["id"], crew_id, site_id,
                    start_date="2026-07-06", end_date="2026-07-08", room_label="W-1")
        overlap = api.create_install_task(
            {"shipment_id": shipment["id"], "crew_id": crew_id, "school_site_id": site_id,
             "room_label": "W-2", "start_date": "2026-07-07", "end_date": "2026-07-09",
             "crew_count": 1}, FC)
        validate_error(overlap, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)

        adjacent_before = validate_success(api.create_install_task(
            {"shipment_id": shipment["id"], "crew_id": crew_id, "school_site_id": site_id,
             "room_label": "W-3", "start_date": "2026-07-05", "end_date": "2026-07-06",
             "crew_count": 1}, FC), 201)
        assert adjacent_before["status"] == "SCHEDULED"
        assert_crew_booking_invariant(get_crew(crew_id), 3)


class TestSiteDailyCapacity:
    def test_site_capacity_exact_load_allowed_over_rejected(self, api):
        """PRD §3.6: "for every date the new task occupies, the sum of `crew_count`
        across the site's non-`CANCELLED` tasks occupying that date, plus the new
        task's `crew_count`, must not exceed the site's `daily_crew_capacity`; a
        load exactly equal to capacity is permitted, and anything beyond it is
        rejected with `ERR_SITE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/site_daily_capacity_aggregate_boundary_exact_vs_over
        """
        ctx, _po, _lines, shipment = _delivered_ctx(api, site_capacity=3)
        site_id = ctx["site"]["id"]
        crew_b = create_crew("Crew B")
        crew_c = create_crew("Crew C")

        create_task(shipment["id"], ctx["crew"]["id"], site_id,
                    start_date="2026-07-06", end_date="2026-07-07", crew_count=2, room_label="W-1")
        t2 = validate_success(api.create_install_task(
            {"shipment_id": shipment["id"], "crew_id": crew_b["id"], "school_site_id": site_id,
             "room_label": "W-2", "start_date": "2026-07-06", "end_date": "2026-07-07",
             "crew_count": 1}, FC), 201)
        assert t2["status"] == "SCHEDULED"  # 2 + 1 == capacity 3

        over = api.create_install_task(
            {"shipment_id": shipment["id"], "crew_id": crew_c["id"], "school_site_id": site_id,
             "room_label": "W-3", "start_date": "2026-07-06", "end_date": "2026-07-07",
             "crew_count": 1}, FC)
        validate_error(over, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED)  # 3 + 1 > 3

    def test_site_capacity_boundary_on_smaller_site(self, api):
        """PRD §3.6: "a load exactly equal to capacity is permitted, and anything
        beyond it is rejected with `ERR_SITE_CAPACITY_EXCEEDED`."
        PRD §3.1: "a `daily_crew_capacity` — the maximum total `crew_count` allowed
        to occupy the site on any single date, which must be at least 1"

        Design: Difficulty/resource_temporal_overlap/site_daily_capacity_aggregate_boundary_exact_vs_over
        """
        ctx, _po, _lines, shipment = _delivered_ctx(api, site_capacity=2)
        site_id = ctx["site"]["id"]
        crew_b = create_crew("Crew B")
        crew_c = create_crew("Crew C")

        create_task(shipment["id"], ctx["crew"]["id"], site_id,
                    start_date="2026-07-06", end_date="2026-07-07", crew_count=1, room_label="W-1")
        exact = validate_success(api.create_install_task(
            {"shipment_id": shipment["id"], "crew_id": crew_b["id"], "school_site_id": site_id,
             "room_label": "W-2", "start_date": "2026-07-06", "end_date": "2026-07-07",
             "crew_count": 1}, FC), 201)
        assert exact["status"] == "SCHEDULED"  # 1 + 1 == capacity 2

        over = api.create_install_task(
            {"shipment_id": shipment["id"], "crew_id": crew_c["id"], "school_site_id": site_id,
             "room_label": "W-3", "start_date": "2026-07-06", "end_date": "2026-07-07",
             "crew_count": 1}, FC)
        validate_error(over, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED)


class TestCrewBookedDaysLedger:
    def test_crew_booked_days_assign_then_unassign_restores_zero(self, api):
        """PRD §2.10: "A crew's `booked_days` is always the sum of `crew_days` over
        that crew's tasks currently `SCHEDULED` or `IN_PROGRESS`; assignment debits
        it, and unassignment or completion credits exactly the same amount back, so
        the ledger never drifts."
        PRD §3.6: "A `FulfillmentCoordinator` may also unassign a `SCHEDULED` task,
        moving it to `CANCELLED` and crediting the crew's `booked_days` back the
        same `crew_days`"

        Design: Difficulty/compensating_invariant/crew_booked_days_assign_then_unassign_restores_zero
        """
        ctx, _po, _lines, shipment = _delivered_ctx(api)
        crew_id = ctx["crew"]["id"]
        assert get_crew(crew_id)["booked_days"] == 0

        task = create_task(shipment["id"], crew_id, ctx["site"]["id"],
                           start_date="2026-07-06", end_date="2026-07-09", crew_count=2)
        assert task["crew_days"] == 6  # 2 crew x 3 dates in [2026-07-06, 2026-07-09)
        assert_crew_booking_invariant(get_crew(crew_id), 6)

        cancelled = validate_success(api.unassign_install_task(task["id"], FC))
        assert cancelled["status"] == "CANCELLED"
        assert_crew_booking_invariant(get_crew(crew_id), 0)

    def test_crew_booked_days_released_on_completion(self, api):
        """PRD §3.6: "its crew's `booked_days` is credited back the task's
        `crew_days` (the ledger counts only `SCHEDULED` and `IN_PROGRESS` tasks)"
        PRD §3.6: "The derived `crew_days` of a task is its `crew_count` multiplied
        by the number of dates in that half-open interval."

        Design: Difficulty/compensating_invariant/crew_booked_days_assign_then_unassign_restores_zero
        """
        ctx, _po, _lines, shipment = _delivered_ctx(api)
        crew_id = ctx["crew"]["id"]

        task = create_task(shipment["id"], crew_id, ctx["site"]["id"],
                           start_date="2026-07-06", end_date="2026-07-09", crew_count=2)
        assert task["crew_days"] == 6
        assert_crew_booking_invariant(get_crew(crew_id), 6)

        start_task(task["id"], crew_id)
        done = complete_task(task["id"], crew_id)
        assert done["status"] == "COMPLETED"
        assert_crew_booking_invariant(get_crew(crew_id), 0)


class TestInstallCompletionCascade:
    def test_install_complete_requires_full_checklist_then_verifies_lines(self, api):
        """PRD §3.6: "The completion payload carries three booleans — `uncrated`,
        `debris_removed`, and `placed` — and all three must be true; an incomplete
        checklist is rejected with `ERR_INSTALL_CHECKLIST_INCOMPLETE`."
        PRD §3.6: "every PO line on the shipment with `delivered_qty` greater than
        zero moves `DELIVERED` → `VERIFIED` with `installed_at` stamped from the
        logical clock"

        Design: Corner/state_machines/install_complete_requires_full_checklist_then_verifies_lines
        """
        ctx, po, lines, shipment = _delivered_ctx(api)
        crew_id = ctx["crew"]["id"]
        task = create_task(shipment["id"], crew_id, ctx["site"]["id"],
                           start_date="2026-07-06", end_date="2026-07-08", room_label="W-12")
        start_task(task["id"], crew_id)
        set_clock("2026-07-08T10:00:00Z")

        incomplete = api.complete_install_task(
            task["id"], {"uncrated": True, "debris_removed": True, "placed": False},
            make_crew_lead_headers(crew_id))
        validate_error(incomplete, ApiErrorId.ERR_INSTALL_CHECKLIST_INCOMPLETE)

        done = validate_success(api.complete_install_task(
            task["id"], {"uncrated": True, "debris_removed": True, "placed": True},
            make_crew_lead_headers(crew_id)))
        assert done["status"] == "COMPLETED"
        assert done["completed_checklist"] == ["UNCRATED", "DEBRIS_REMOVED", "PLACED"]

        line = get_po_line(lines[0]["id"])
        assert line["status"] == "VERIFIED"
        # PRD §2.5/§3.6 cover only that installed_at is stamped from the logical
        # clock's full timestamp; the serialization precision (zero vs three
        # fractional digits) is not pinned by PRD, so compare the instant in a
        # format-agnostic way.
        assert line["installed_at"].replace(".000Z", "Z") == "2026-07-08T10:00:00Z"

        ship = validate_success(api.get_shipment(shipment["id"], FC))
        assert ship["status"] == "COMPLETED"
        assert get_po(po["id"])["status"] == "FULFILLED"


class TestCrewLeadScope:
    def test_crew_lead_cannot_complete_other_crews_task(self, api):
        """PRD §3.6: "Completion moves the task `IN_PROGRESS` → `COMPLETED` and
        again enforces crew ownership."
        PRD §2.1: "a crew lead may start or complete only install tasks assigned to
        their own crew ... with violations again rejected as `ERR_SCOPE_VIOLATION`"

        Design: Corner/rbac/crew_lead_cannot_complete_other_crews_task
        """
        ctx, _po, _lines, shipment = _delivered_ctx(api)
        crew_b = create_crew("Crew B")
        task = create_task(shipment["id"], ctx["crew"]["id"], ctx["site"]["id"],
                           start_date="2026-07-06", end_date="2026-07-08", room_label="W-12")
        start_task(task["id"], ctx["crew"]["id"])

        resp = api.complete_install_task(
            task["id"], {"uncrated": True, "debris_removed": True, "placed": True},
            make_crew_lead_headers(crew_b["id"]))
        validate_error(resp, ApiErrorId.ERR_SCOPE_VIOLATION)

        still = validate_success(api.get_install_task(task["id"], FC))
        assert still["status"] == "IN_PROGRESS"
