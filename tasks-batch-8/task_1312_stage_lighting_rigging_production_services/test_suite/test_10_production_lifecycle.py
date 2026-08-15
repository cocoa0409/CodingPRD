"""Production lifecycle: the readiness gate, the cancel cascade, venue
occupancy windows, the close-out gates, and read-your-writes consistency."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_planning_production, setup_full_planning_surface, setup_load_in_production,
    create_venue, create_production, get_production, transition_production,
    create_plot, add_rigging_point, get_rigging_point,
    setup_approved_plot_with_point, setup_approved_power_plan, setup_prepped_entry,
    create_asset, get_asset, create_pull_list_entry, reserve_entry, prep_entry,
    get_pull_list_entry, return_entry,
    create_technician, create_crew_call, get_crew_call, transition_crew_call,
    create_assignment, get_crew_assignment, confirm_assignment, confirm_crew_call,
    create_inspection, transition_schedule, get_load_schedule,
    set_clock, certify_show, CLOCK_AFTER_SHOW,
)

PM = TEST_USERS["production_manager_headers"]


class TestProductionCancelCascade:
    def test_production_cancel_cascade_chain(self, api):
        """PRD §3.2: "Cancellation is available from `DRAFT`, `PLANNING`, and `READY_FOR_LOADIN`, and it triggers a full teardown cascade: every crew call in `DRAFT`, `PUBLISHED`, or `CONFIRMED` moves to `CANCELLED`, and each cancelled call's assignments in `ASSIGNED`, `CONFIRMED`, or `WORKED` move to `CANCELLED`; every rigging point in `RESERVED`, `UNDER_REVIEW`, `REJECTED`, or `APPROVED` moves to `RELEASED`, recomputing its plot's `total_factored_load_kg`; every pull list entry in `REQUESTED`, `RESERVED`, or `PREPPED` moves to `CANCELLED`, and each asset thereby freed (an asset in `RESERVED` or `PREPPED`) returns to `AVAILABLE`, immediately running the waitlist promotion scan of §3.6; every load schedule in `PLANNED`, `CONFIRMED`, or `AUTHORIZED` moves to `CANCELLED`; and every safety inspection in `SCHEDULED`, `IN_PROGRESS`, or `FAILED` moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/production_cancel_cascade_chain
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"])  # RESERVED
        asset = create_asset()
        entry = create_pull_list_entry(ctx["production"]["id"], asset["id"])
        reserve_entry(entry["id"])
        tech = create_technician()
        call = create_crew_call(ctx["production"]["id"])
        transition_crew_call(call["id"], "PUBLISHED")
        assignment = create_assignment(call["id"], tech["id"])  # ASSIGNED
        data = transition_production(ctx["production"]["id"], "CANCELLED")
        assert data["status"] == "CANCELLED"
        assert get_crew_call(call["id"])["status"] == "CANCELLED"
        assert get_crew_assignment(assignment["id"])["status"] == "CANCELLED"
        assert get_rigging_point(point["id"])["status"] == "RELEASED"
        assert get_pull_list_entry(entry["id"])["status"] == "CANCELLED"
        assert get_asset(asset["id"])["status"] == "AVAILABLE"

    def test_production_cancel_cascade_covers_schedules_and_inspections(self, api):
        """PRD §3.2: "every load schedule in `PLANNED`, `CONFIRMED`, or `AUTHORIZED` moves to `CANCELLED`; and every safety inspection in `SCHEDULED`, `IN_PROGRESS`, or `FAILED` moves to `CANCELLED`. Entities already in a terminal state are untouched by the cascade."

        Design: Difficulty/transitive_cascade/production_cancel_cascade_chain
        """
        ctx = setup_full_planning_surface()  # CONFIRMED call, PREPPED entry, CONFIRMED schedule
        inspection = create_inspection(ctx["production"]["id"], "RIGGING")  # SCHEDULED
        transition_production(ctx["production"]["id"], "CANCELLED")
        assert get_crew_call(ctx["crew_call"]["id"])["status"] == "CANCELLED"
        assert get_crew_assignment(ctx["assignment"]["id"])["status"] == "CANCELLED"
        assert get_load_schedule(ctx["schedule"]["id"])["status"] == "CANCELLED"
        assert validate_success(api.get_inspection(inspection["id"], PM))["status"] == "CANCELLED"
        assert get_pull_list_entry(ctx["entry"]["id"])["status"] == "CANCELLED"
        assert get_asset(ctx["asset"]["id"])["status"] == "AVAILABLE"


class TestReadinessGate:
    def test_production_ready_gate_reads_children(self, api):
        """PRD §3.2: "The gate into `READY_FOR_LOADIN` is the derived readiness posture, and advancing without it fails with `ERR_PRODUCTION_NOT_READY` (HTTP 409)."
        PRD §3.2: "A production's `posture` is `READY` only when all five of the following hold: (a) the production has a lighting plot in `APPROVED` status; (b) that approved plot carries at least one rigging point in `APPROVED` status, and every rigging point on it is either `APPROVED` or `RELEASED`; (c) the production has a power plan in `APPROVED` status; (d) no pull list entry of the production is still in `REQUESTED` or `RESERVED`; and (e) no crew call of the production is still in `DRAFT` or `PUBLISHED`."

        Design: Difficulty/cross_entity_state_dependency/production_ready_gate_reads_children
        """
        ctx = setup_planning_production()
        setup_approved_plot_with_point(ctx)
        setup_approved_power_plan(ctx)
        setup_prepped_entry(ctx)
        tech = create_technician()
        call = create_crew_call(ctx["production"]["id"])
        transition_crew_call(call["id"], "PUBLISHED")
        assignment = create_assignment(call["id"], tech["id"])
        confirm_assignment(assignment["id"], tech["id"])
        # The call itself is still PUBLISHED: condition (e) fails -> PARTIAL.
        resp = api.transition_production(ctx["production"]["id"], {"to": "READY_FOR_LOADIN"}, PM)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_NOT_READY)
        assert get_production(ctx["production"]["id"])["posture"] == "PARTIAL"
        confirm_crew_call(call["id"])
        data = transition_production(ctx["production"]["id"], "READY_FOR_LOADIN")
        assert data["status"] == "READY_FOR_LOADIN"
        assert data["posture"] == "READY"

    def test_requested_pull_entry_blocks_readiness(self, api):
        """PRD §3.2: "A production's `posture` is `READY` only when all five of the following hold: (a) the production has a lighting plot in `APPROVED` status; (b) that approved plot carries at least one rigging point in `APPROVED` status, and every rigging point on it is either `APPROVED` or `RELEASED`; (c) the production has a power plan in `APPROVED` status; (d) no pull list entry of the production is still in `REQUESTED` or `RESERVED`; and (e) no crew call of the production is still in `DRAFT` or `PUBLISHED`."
        PRD §3.2: "When condition (a) fails — no approved plot at all — the posture is `BLOCKED`; when (a) holds but any of (b) through (e) fails, the posture is `PARTIAL`."

        Design: Difficulty/cross_entity_state_dependency/production_ready_gate_reads_children
        """
        ctx = setup_planning_production()
        setup_approved_plot_with_point(ctx)
        setup_approved_power_plan(ctx)
        asset = create_asset()
        entry = create_pull_list_entry(ctx["production"]["id"], asset["id"])  # REQUESTED
        resp = api.transition_production(ctx["production"]["id"], {"to": "READY_FOR_LOADIN"}, PM)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_NOT_READY)
        assert get_production(ctx["production"]["id"])["posture"] == "PARTIAL"
        reserve_entry(entry["id"])
        prep_entry(entry["id"])
        data = transition_production(ctx["production"]["id"], "READY_FOR_LOADIN")
        assert data["status"] == "READY_FOR_LOADIN"
        assert data["posture"] == "READY"


class TestVenueOccupancy:
    def test_venue_occupancy_closed_interval(self, api):
        """PRD §3.2: "Beyond schema validity, the venue's calendar is exclusive: if the closed occupancy window of the new production intersects the closed occupancy window of any other non-`CANCELLED` production at the same venue, the booking is rejected with `ERR_VENUE_DOUBLE_BOOKED` (HTTP 409). Two productions that merely touch — one loading out exactly when another loads in — still intersect under the closed-interval rule, since both endpoints count."

        Design: Difficulty/resource_temporal_overlap/venue_occupancy_closed_interval
        """
        ctx = setup_planning_production()  # P1 occupies [09-01T08:00, 09-03T23:00] closed
        resp = api.create_production(
            {"venue_id": ctx["venue"]["id"], "name": "P2-touching",
             "load_in_at": "2026-09-03T23:00:00Z", "show_at": "2026-09-04T19:00:00Z",
             "load_out_at": "2026-09-05T23:00:00Z"}, PM)
        validate_error(resp, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED)
        data = create_production(ctx["venue"]["id"], name="P3-after",
                                 load_in_at="2026-09-03T23:01:00Z",
                                 show_at="2026-09-04T19:00:00Z",
                                 load_out_at="2026-09-05T23:00:00Z")
        assert data["status"] == "DRAFT"

    def test_cancelled_production_frees_the_venue(self, api):
        """PRD §3.2: "if the closed occupancy window of the new production intersects the closed occupancy window of any other non-`CANCELLED` production at the same venue, the booking is rejected with `ERR_VENUE_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/venue_occupancy_closed_interval
        """
        ctx = setup_planning_production()
        transition_production(ctx["production"]["id"], "CANCELLED")
        data = create_production(ctx["venue"]["id"], name="P2-same-window")
        assert data["status"] == "DRAFT", \
            "a CANCELLED production no longer occupies the venue calendar"


class TestCloseOutGates:
    def test_close_blocked_open_entries_then_schedules(self, api):
        """PRD §3.2: "Closing the production — `LOAD_OUT` → `CLOSED` — is gated on two open-item checks, evaluated in order: first, every pull list entry of the production must have reached `RETURNED`, `DAMAGED`, `LOST`, or `CANCELLED`, otherwise the close is rejected with `ERR_OPEN_PULL_LIST` (HTTP 409); second, every load schedule of the production must be `COMPLETE` or `CANCELLED`, otherwise `ERR_OPEN_LOAD_SCHEDULE` (HTTP 409)."
        PRD §3.6: "Billable days count every calendar date touched from the date of `out_at` through the date of `returned_at`, both endpoints inclusive, so a same-day return bills exactly one day."

        Design: Corner/errors/close_blocked_open_entries_then_schedules
        """
        ctx = setup_load_in_production()  # entry OUT at 2026-09-01T08:00 on AUTHORIZED LS
        certify_show(ctx)
        set_clock(CLOCK_AFTER_SHOW)
        transition_production(ctx["production"]["id"], "SHOW_COMPLETE")
        transition_production(ctx["production"]["id"], "LOAD_OUT")
        resp = api.transition_production(ctx["production"]["id"], {"to": "CLOSED"}, PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_PULL_LIST)
        # Check-in at clock 2026-09-02T20:00: dates 09-01 and 09-02 = 2 days at 100%.
        data = return_entry(ctx["entry"]["id"])
        assert data["rental_charge_cents"] == 10000
        resp = api.transition_production(ctx["production"]["id"], {"to": "CLOSED"}, PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_LOAD_SCHEDULE)
        transition_schedule(ctx["schedule"]["id"], "COMPLETE")
        data = transition_production(ctx["production"]["id"], "CLOSED")
        assert data["status"] == "CLOSED"


class TestImmediateConsistency:
    def test_transition_response_immediate_visibility(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §2.4: "The `version` is a system-managed integer that increments by exactly 1 on every mutation, including mutations driven indirectly by cascades or by recomputation of a derived field."

        Design: Corner/consistency_model/transition_response_immediate_visibility
        """
        venue = create_venue()
        production = create_production(venue["id"])
        created_version = production["version"]
        data = transition_production(production["id"], "PLANNING")
        assert data["status"] == "PLANNING"
        assert data["version"] == created_version + 1
        fetched = get_production(production["id"])
        assert fetched["status"] == data["status"]
        assert fetched["version"] == data["version"], \
            "the post-transition state is immediately visible on a re-read"
