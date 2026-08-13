"""Cross-entity cascades: delivery and incident-close chains.

Covers PRD §3.6 (the five-link delivery cascade), §3.7 (the three-link
incident-close cascade), §2.9 (derived-state consistency), and §3.2
(reserved_until recompute).
"""
from test_helpers import (
    TEST_USERS,
    assert_ts_eq,
    make_driver_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    append_duty_event,
    assign_driver,
    close_incident,
    get_driver,
    get_load,
    get_settlement_of_load,
    get_trailer,
    record_delivery_ticket,
    report_incident,
    set_clock,
    setup_arrived_load,
    setup_assigned_load,
    setup_delivered_load,
    setup_in_transit_load,
    setup_verified_load,
    start_review,
)

ADMIN = TEST_USERS["admin_headers"]
CONSIGNEE = TEST_USERS["consignee_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestDeliverCascadeCycleExhaustion:
    def test_deliver_flips_driver_to_cycle_exhausted(self, api):
        """PRD §3.6: "Fourth, the driver's hours-of-service fields are
        recomputed from the appended duty events. Fifth — chain link 3 — if that
        recomputation leaves `cycle_on_duty_minutes_8d` at or above 4200, the
        driver's `hos_status` becomes `CYCLE_EXHAUSTED` and every other load
        still holding this driver in `ASSIGNED` is force-unassigned back to
        `PAPERWORK_VERIFIED`: its `driver_id` is set to null, its `version`
        increments by 1, and its trailer's `reserved_until` is recomputed."

        Design: Difficulty/transitive_cascade/deliver_cascade_cycle_exhaustion_unassigns_future_load
        """
        # L1 assigned to the driver (planned 2026-08-08 08:00 + 10h); the
        # trailer wash and brand inspection are fresh for the 08-08 departure.
        ctx1 = setup_assigned_load(
            planned_departure_at="2026-08-08T08:00:00Z",
            planned_duration_hours=10,
            wash_at="2026-08-07T20:00:00Z",
            brand_inspected_at="2026-08-07T20:30:00Z",
            paperwork_clock="2026-08-07T21:00:00Z")
        driver = ctx1["driver"]

        # 4100 on-duty minutes already inside the trailing 8-day window
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-05T00:00:00Z")
        append_duty_event(driver["id"], "DUTY_OFF", "2026-08-07T20:20:00Z")

        # L1 trip: depart 08:00, arrive 12:00, ticket, deliver at 12:00.
        # The trip adds 240 more on-duty minutes -> 4340 >= 4200.
        set_clock("2026-08-08T08:00:00Z")
        validate_success(
            api.depart(ctx1["load"]["id"], {"origin_temperature_f": 70},
                       make_driver_headers(driver["id"])), 200)
        set_clock("2026-08-08T12:00:00Z")
        validate_success(api.arrive(ctx1["load"]["id"],
                                    make_driver_headers(driver["id"])), 200)
        record_delivery_ticket(ctx1["load"]["id"], 40000,
                               weighed_at="2026-08-08T11:30:00Z")
        validate_success(api.deliver(ctx1["load"]["id"], CONSIGNEE), 200)

        d = get_driver(driver["id"])
        assert d["cycle_on_duty_minutes_8d"] == 4340
        assert d["hos_status"] == "CYCLE_EXHAUSTED"
        assert get_load(ctx1["load"]["id"])["status"] == "DELIVERED"

    def test_deliver_cascade_force_unassigns_other_assigned_load(self, api):
        """PRD §3.6: "Fifth — chain link 3 — if that recomputation leaves
        `cycle_on_duty_minutes_8d` at or above 4200, the driver's `hos_status`
        becomes `CYCLE_EXHAUSTED` and every other load still holding this
        driver in `ASSIGNED` is force-unassigned back to `PAPERWORK_VERIFIED`:
        its `driver_id` is set to null, its `version` increments by 1, and its
        trailer's `reserved_until` is recomputed."
        PRD §3.2: "A trailer also exposes `reserved_until`: the latest planned
        window end — each window running from the load's `planned_departure_at`
        for `planned_duration_hours` hours — over this trailer's loads in
        `ASSIGNED`, `IN_TRANSIT`, `WEATHER_HOLD`, `REST_UNLOAD`, or `ARRIVED`;
        it is null when no such load exists."

        Design: Difficulty/transitive_cascade/deliver_cascade_cycle_exhaustion_unassigns_future_load
        """
        # L1 (planned 2026-08-08 08:00 + 10h)
        ctx1 = setup_assigned_load(
            planned_departure_at="2026-08-08T08:00:00Z",
            planned_duration_hours=10,
            wash_at="2026-08-07T20:00:00Z",
            brand_inspected_at="2026-08-07T20:30:00Z",
            paperwork_clock="2026-08-07T21:00:00Z")
        driver = ctx1["driver"]

        # 4100 on-duty minutes inside the trailing 8-day window
        append_duty_event(driver["id"], "DUTY_ON", "2026-08-05T00:00:00Z")
        append_duty_event(driver["id"], "DUTY_OFF", "2026-08-07T20:20:00Z")

        # L2 on its own trailer, same driver, planned 2026-08-09 08:00 + 10h
        # (windows disjoint from L1's)
        ctx2 = setup_verified_load(
            head_count=20, weight_lb=20000,
            origin="B", destination="C",
            planned_departure_at="2026-08-09T08:00:00Z",
            planned_duration_hours=10,
            start_clock="2026-08-07T21:20:00Z",
            brand_inspected_at="2026-08-07T20:40:00Z",
            paperwork_clock="2026-08-07T21:30:00Z")
        assign_driver(ctx2["load"]["id"], driver["id"])

        # L1 trip crosses the driver's cycle limit at deliver
        set_clock("2026-08-08T08:00:00Z")
        validate_success(
            api.depart(ctx1["load"]["id"], {"origin_temperature_f": 70},
                       make_driver_headers(driver["id"])), 200)
        set_clock("2026-08-08T12:00:00Z")
        validate_success(api.arrive(ctx1["load"]["id"],
                                    make_driver_headers(driver["id"])), 200)
        record_delivery_ticket(ctx1["load"]["id"], 40000,
                               weighed_at="2026-08-08T11:30:00Z")
        validate_success(api.deliver(ctx1["load"]["id"], CONSIGNEE), 200)

        # chain link 3: the OTHER assigned load is force-unassigned
        l2 = get_load(ctx2["load"]["id"])
        assert l2["status"] == "PAPERWORK_VERIFIED"
        assert l2["driver_id"] is None
        trailer2 = get_trailer(ctx2["trailer"]["id"])
        assert trailer2["reserved_until"] is None


class TestIncidentCloseCascade:
    def test_first_critical_close_leaves_driver_active(self, api):
        """PRD §3.7: "Chain link 2: the driver's `critical_incident_count_90d`
        is recomputed — closed `CRITICAL` incidents occurring within the
        trailing 90 days — and when the count reaches 2 while the driver is
        `ACTIVE`, the driver's `status` becomes `SUSPENDED`."

        Design: Difficulty/transitive_cascade/incident_close_cascade_suspends_driver_and_unassigns
        """
        ctx = setup_delivered_load(loaded_miles=2000)
        driver_id = ctx["driver"]["id"]
        # one CRITICAL DOWNER reported in transit, closed after delivery
        set_clock("2026-08-03T10:00:00Z")
        incident = report_incident(
            ctx["load"]["id"], driver_id, incident_type="DOWNER",
            severity="CRITICAL", head_count_affected=1,
            occurred_at="2026-08-02T09:00:00Z")
        start_review(incident["id"])
        closed = close_incident(incident["id"])

        # round_half_up(41667 * 1 * 4.0) = 166668
        assert closed["fine_cents"] == 166668
        s = get_settlement_of_load(ctx["load"]["id"])
        assert s["welfare_deduction_cents"] == 166668
        # base 300 c/mi * 2000 mi = 600000; no excess shrink (on-weight)
        assert s["final_amount_cents"] == 600000 - 166668

        d = get_driver(driver_id)
        assert d["critical_incident_count_90d"] == 1
        assert d["status"] == "ACTIVE"

    def test_second_critical_close_suspends_and_force_unassigns(self, api):
        """PRD §3.7: "Chain link 1: when the load's settlement exists and is
        not `PAID`, its `welfare_deduction_cents` is recomputed as the sum of
        `fine_cents` over the load's closed, non-waived incidents, and
        `final_amount_cents` is recomputed per §3.6. Chain link 2: the driver's
        `critical_incident_count_90d` is recomputed — closed `CRITICAL`
        incidents occurring within the trailing 90 days — and when the count
        reaches 2 while the driver is `ACTIVE`, the driver's `status` becomes
        `SUSPENDED`. Chain link 3: upon suspension, every load holding this
        driver in `ASSIGNED` is force-unassigned back to `PAPERWORK_VERIFIED` —
        `driver_id` set to null, load `version` incremented by 1 — and each
        affected trailer's `reserved_until` is recomputed."

        Design: Difficulty/transitive_cascade/incident_close_cascade_suspends_driver_and_unassigns
        """
        # L1: 40/40000, rate 300 c/mi x 2000 mi -> base 600000, on-weight
        # delivery; two CRITICAL DOWNER incidents (1 head each) in transit.
        set_clock("2026-08-01T01:00:00Z")
        ctx = setup_in_transit_load(loaded_miles=2000)
        driver_id = ctx["driver"]["id"]
        set_clock("2026-08-02T10:00:00Z")
        i1 = report_incident(ctx["load"]["id"], driver_id,
                             incident_type="DOWNER", severity="CRITICAL",
                             head_count_affected=1,
                             occurred_at="2026-08-02T09:00:00Z")
        i2 = report_incident(ctx["load"]["id"], driver_id,
                             incident_type="DOWNER", severity="CRITICAL",
                             head_count_affected=1,
                             occurred_at="2026-08-02T09:30:00Z")
        set_clock("2026-08-02T16:00:00Z")
        validate_success(api.arrive(ctx["load"]["id"],
                                    make_driver_headers(driver_id)), 200)
        record_delivery_ticket(ctx["load"]["id"], 40000)
        set_clock("2026-08-02T16:30:00Z")
        validate_success(api.deliver(ctx["load"]["id"], CONSIGNEE), 200)

        # L3: same driver still ASSIGNED on a fresh trailer
        set_clock("2026-08-03T08:30:00Z")
        ctx3 = setup_assigned_load(
            driver=ctx["driver"], head_count=20, weight_lb=20000,
            origin="B", destination="C",
            planned_departure_at="2026-08-05T08:00:00Z",
            planned_duration_hours=10,
            brand_inspected_at="2026-08-03T08:15:00Z",
            paperwork_clock="2026-08-03T08:45:00Z")

        # close the first CRITICAL: fine posts, driver still ACTIVE
        set_clock("2026-08-03T10:00:00Z")
        start_review(i1["id"])
        close_incident(i1["id"])
        assert get_driver(driver_id)["status"] == "ACTIVE"

        # close the second CRITICAL: the count reaches 2 -> SUSPENDED, and the
        # suspension force-unassigns L3
        start_review(i2["id"])
        closed2 = close_incident(i2["id"])
        assert closed2["fine_cents"] == 166668

        s = get_settlement_of_load(ctx["load"]["id"])
        assert s["welfare_deduction_cents"] == 333336
        assert s["final_amount_cents"] == 266664

        d = get_driver(driver_id)
        assert d["critical_incident_count_90d"] == 2
        assert d["status"] == "SUSPENDED"

        l3 = get_load(ctx3["load"]["id"])
        assert l3["status"] == "PAPERWORK_VERIFIED"
        assert l3["driver_id"] is None
        assert get_trailer(ctx3["trailer"]["id"])["reserved_until"] is None


class TestAssignSuspendedDriver:
    def test_assign_suspended_driver_rejected(self, api):
        """PRD §3.5: "the driver is `ACTIVE` (`ERR_DRIVER_SUSPENDED`,
        HTTP 422)"
        PRD §3.7: "Chain link 2: the driver's `critical_incident_count_90d` is
        recomputed — closed `CRITICAL` incidents occurring within the trailing
        90 days — and when the count reaches 2 while the driver is `ACTIVE`,
        the driver's `status` becomes `SUSPENDED`."
        PRD §3.7: "A suspended driver can neither be assigned nor depart until
        standing is restored."

        Design: Corner/errors/assign_suspended_driver_rejected
        """
        # driver picks up two CLOSED CRITICAL incidents on a delivered trip
        ctx = setup_delivered_load(loaded_miles=2000)
        driver = ctx["driver"]
        set_clock("2026-08-03T10:00:00Z")
        i1 = report_incident(ctx["load"]["id"], driver["id"],
                             incident_type="DOWNER", severity="CRITICAL",
                             head_count_affected=1,
                             occurred_at="2026-08-02T09:00:00Z")
        i2 = report_incident(ctx["load"]["id"], driver["id"],
                             incident_type="DOWNER", severity="CRITICAL",
                             head_count_affected=1,
                             occurred_at="2026-08-02T09:30:00Z")
        start_review(i1["id"])
        close_incident(i1["id"])
        assert get_driver(driver["id"])["status"] == "ACTIVE"
        start_review(i2["id"])
        close_incident(i2["id"])
        assert get_driver(driver["id"])["status"] == "SUSPENDED"

        # a fresh, fully verified load on another trailer cannot be assigned
        # to the suspended driver (clock keeps moving forward)
        ctx2 = setup_verified_load(
            head_count=20, weight_lb=20000,
            origin="B", destination="C",
            planned_departure_at="2026-08-05T08:00:00Z",
            planned_duration_hours=10,
            start_clock="2026-08-03T10:30:00Z",
            brand_inspected_at="2026-08-03T10:15:00Z",
            paperwork_clock="2026-08-03T10:45:00Z")
        d = get_driver(driver["id"])
        resp = api.assign_driver(
            ctx2["load"]["id"],
            {"driver_id": driver["id"], "expected_driver_version": d["version"]},
            DISP)
        validate_error(resp, E.ERR_DRIVER_SUSPENDED)

        l2 = get_load(ctx2["load"]["id"])
        assert l2["status"] == "PAPERWORK_VERIFIED"
        assert l2["driver_id"] is None


class TestReweighReconciliation:
    def test_settlement_recompute_on_reweigh_while_pending(self, api):
        """PRD §3.6: "A `DELIVERY` ticket recorded while the settlement is
        `PENDING` is a reweigh: the settlement's `delivered_weight_lb` and
        `effective_delivered_weight_lb` are refreshed from the new latest
        `DELIVERY` ticket and the final settlement is recomputed as specified
        below."
        PRD §3.6: "`delivered_weight_lb` becomes the `net_weight_lb` of the
        latest `DELIVERY` ticket — ordered by `weighed_at` descending with
        `created_at` descending as the tie-break"

        Design: Corner/complexity_layers/settlement_recompute_on_reweigh_while_pending
        """
        ctx = setup_delivered_load(net_lb=38800)
        s_before = ctx["settlement"]
        assert s_before["final_amount_cents"] == 149000

        # reweigh while PENDING: net 39900 (gross 45900), weighed later
        set_clock("2026-08-03T10:00:00Z")
        record_delivery_ticket(ctx["load"]["id"], 39900,
                               weighed_at="2026-08-02T16:15:00Z")

        s = get_settlement_of_load(ctx["load"]["id"])
        assert s["delivered_weight_lb"] == 39900
        # shrink 100 <= allowance 800 -> no excess, no penalty
        assert s["excess_shrink_lb"] == 0
        assert s["shrink_penalty_cents"] == 0
        assert s["final_amount_cents"] == 150000


class TestDeliverReconciliation:
    def test_compartment_occupied_reconciles_after_delivery(self, api):
        """PRD §3.6: "First — chain link 1 — every `ACTIVE` allocation is
        released with `release_reason` `DELIVERED`, and compartment occupancy
        and the load's allocated totals are recomputed. Second — chain link 2 —
        because the release reason is `DELIVERED`, the trailer's `dirtied_at`
        is set to the delivery time and its `washout_status` recomputes to
        `DIRTY`; releases with reason `CANCELLED` or `REPLANNED` never dirty a
        trailer."

        Design: Corner/complexity_layers/compartment_occupied_reconciles_after_delivery
        """
        ctx = setup_arrived_load()
        # occupied before deliver
        comps_before, _ = validate_paginated(
            api.list_compartments(ctx["trailer"]["id"], ADMIN))
        assert comps_before[0]["occupied_head_count"] == 40
        assert comps_before[0]["occupied_weight_lb"] == 40000

        record_delivery_ticket(ctx["load"]["id"], 40000)
        set_clock("2026-08-02T16:30:00Z")
        validate_success(api.deliver(ctx["load"]["id"], CONSIGNEE), 200)

        comps_after, _ = validate_paginated(
            api.list_compartments(ctx["trailer"]["id"], ADMIN))
        assert comps_after[0]["occupied_head_count"] == 0
        assert comps_after[0]["occupied_weight_lb"] == 0

        trailer = get_trailer(ctx["trailer"]["id"])
        assert trailer["washout_status"] == "DIRTY"
        assert_ts_eq(trailer["dirtied_at"], "2026-08-02T16:30:00Z",
                     "trailer.dirtied_at")

        allocs, _ = validate_paginated(
            api.list_load_allocations(ctx["load"]["id"], ADMIN))
        assert len(allocs) == 1
        assert allocs[0]["status"] == "RELEASED"
        assert allocs[0]["release_reason"] == "DELIVERED"


class TestReservedUntilReconciliation:
    def test_trailer_reserved_until_reconciles_on_unassign(self, api):
        """PRD §3.2: "A trailer also exposes `reserved_until`: the latest
        planned window end — each window running from the load's
        `planned_departure_at` for `planned_duration_hours` hours — over this
        trailer's loads in `ASSIGNED`, `IN_TRANSIT`, `WEATHER_HOLD`,
        `REST_UNLOAD`, or `ARRIVED`; it is null when no such load exists. The
        value is recomputed whenever assignments or load states touching the
        trailer change."
        PRD §3.5: "Unassigning compensates an assignment: a `Dispatcher` moves
        an `ASSIGNED` load back to `PAPERWORK_VERIFIED` (any other state fails
        with `ERR_LOAD_NOT_ASSIGNED`). The load's `driver_id` is cleared to
        null, the driver `version` increments by 1, the load `version`
        increments by 1, and the trailer's `reserved_until` is recomputed."

        Design: Corner/complexity_layers/trailer_reserved_until_reconciles_on_unassign
        """
        ctx = setup_assigned_load()
        trailer = get_trailer(ctx["trailer"]["id"])
        # window 2026-08-02T08:00 + 10h ends 2026-08-02T18:00
        assert_ts_eq(trailer["reserved_until"], "2026-08-02T18:00:00Z",
                     "reserved_until after assign")

        validate_success(api.unassign_driver(ctx["load"]["id"], DISP), 200)
        trailer_after = get_trailer(ctx["trailer"]["id"])
        assert trailer_after["reserved_until"] is None
