"""Work-order scheduling: travel buffer, budget ledger conservation, and
validation precedence (PRD §3.7, §2.6, §2.9)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    setup_territory_technician_crew, setup_monitoring_incident,
    draft_determination, finalize_determination, list_work_orders,
    get_work_order, get_territory,
    TEST_USERS,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]


def _auto_work_order(terr, tech, priority="P2", address="1 A St", caller="A",
                     phone="555-0001", pct_lel=4.0):
    """Drive one leak-confirmed incident to a FINAL OUTSIDE_COMPANY
    determination; return the auto-created OPEN work order."""
    call, incident, disp = setup_monitoring_incident(
        terr["id"], tech["id"], priority=priority, leak_confirmed=True,
        pct_lel=pct_lel, reading_context="OUTSIDE", address_line=address,
        caller_name=caller, caller_phone=phone,
        location_context="OUTSIDE_STRUCTURE")
    det = draft_determination(call["incident_id"], "OUTSIDE_COMPANY",
                              "BARHOLE_SURVEY", drafter="sup-1")
    finalize_determination(det["id"], finalizer="sup-2")
    return list_work_orders(call["incident_id"])[0]


class TestRepairCrewTravelBufferGapRules:
    def test_gap_below_thirty_minutes_rejected(self, api):
        """PRD §3.7: "The travel buffer demands a gap of at least thirty
        minutes between the new window and the window of every other
        non-cancelled work order on the same crew: the new `window_start` must
        fall at or after an existing window's end plus thirty minutes, or the
        new `window_end` must fall at or before the existing window's start
        minus thirty minutes, and any closer approach is rejected with
        `ERR_TRAVEL_BUFFER_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/repair_crew_travel_buffer_gap_rules
        """
        terr, tech, crew = setup_territory_technician_crew(
            shift_start="2026-08-01T00:00:00Z", shift_end="2026-08-03T00:00:00Z",
            territory_overrides={"repair_budget_cap_cents": 10_000_000})
        wo1 = _auto_work_order(terr, tech, address="1 X St", caller="Ted",
                               phone="555-0119")
        wo2 = _auto_work_order(terr, tech, address="2 Y St", caller="Uma",
                               phone="555-0120")
        validate_success(api_client.schedule_work_order(
            wo1["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-02T09:00:00Z",
             "window_end": "2026-08-02T10:00:00Z"},
            SUPERVISOR))

        # 29-minute gap after the existing window: too close.
        resp = api_client.schedule_work_order(
            wo2["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-02T10:29:00Z",
             "window_end": "2026-08-02T11:30:00Z"},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_TRAVEL_BUFFER_VIOLATION)
        assert get_work_order(wo2["id"])["status"] == "OPEN"

    def test_gap_of_exactly_thirty_minutes_accepted(self, api):
        """PRD §3.7: "the new `window_start` must fall at or after an existing
        window's end plus thirty minutes" — a 30-minute gap satisfies the "at
        or after" boundary. "A successful schedule ... adds the current
        estimate to the territory reservation."

        Design: Difficulty/resource_temporal_overlap/repair_crew_travel_buffer_gap_rules
        """
        terr, tech, crew = setup_territory_technician_crew(
            shift_start="2026-08-01T00:00:00Z", shift_end="2026-08-03T00:00:00Z",
            territory_overrides={"repair_budget_cap_cents": 10_000_000})
        wo1 = _auto_work_order(terr, tech, address="1 X St", caller="Ted",
                               phone="555-0119")
        wo2 = _auto_work_order(terr, tech, address="2 Y St", caller="Uma",
                               phone="555-0120")
        validate_success(api_client.schedule_work_order(
            wo1["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-02T09:00:00Z",
             "window_end": "2026-08-02T10:00:00Z"},
            SUPERVISOR))

        # Exactly 30 minutes: 10:30 == 10:00 + 30min.
        scheduled = validate_success(api_client.schedule_work_order(
            wo2["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-02T10:30:00Z",
             "window_end": "2026-08-02T11:30:00Z"},
            SUPERVISOR))
        assert scheduled["status"] == "SCHEDULED"

        terr_after = get_territory(terr["id"])
        assert terr_after["repair_reserved_cents"] == 180000  # 2 x 90000 (P2)


class TestTemporalBeatsFiscalOnSchedule:
    def _setup_two_orders_low_cap(self):
        """Territory cap 100000c; two P2 OUTSIDE_COMPANY auto work orders
        (90000c each); WO1 scheduled [08:00, 09:00)."""
        terr, tech, crew = setup_territory_technician_crew(
            territory_overrides={"repair_budget_cap_cents": 100_000})
        wo1 = _auto_work_order(terr, tech, address="1 A St", caller="Mona",
                               phone="555-0112")
        wo2 = _auto_work_order(terr, tech, address="2 B St", caller="Ned",
                               phone="555-0113")
        validate_success(api_client.schedule_work_order(
            wo1["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-01T08:00:00Z",
             "window_end": "2026-08-01T09:00:00Z"},
            SUPERVISOR))
        return terr, tech, crew, wo1, wo2

    def test_buffer_violation_reported_not_budget_error(self, api):
        """PRD §2.6: "The server evaluates every request against a fixed
        validation cascade, and the ordering matters because an earlier
        failure masks all later ones." with temporal constraints (step 8,
        `ERR_TRAVEL_BUFFER_VIOLATION`) preceding the fiscal constraint
        (step 10, `ERR_REPAIR_BUDGET_EXCEEDED`).

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_work_order_schedule
        """
        terr, tech, crew, wo1, wo2 = self._setup_two_orders_low_cap()
        # 10-minute gap (buffer violation) AND 90000+90000 > 100000 (fiscal):
        # the temporal error must win.
        resp = api_client.schedule_work_order(
            wo2["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-01T09:10:00Z",
             "window_end": "2026-08-01T10:00:00Z"},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_TRAVEL_BUFFER_VIOLATION)

    def test_failed_schedule_leaves_order_and_reservation_untouched(self, api):
        """PRD §3.7: "A successful schedule moves the order `OPEN →
        SCHEDULED`, stores the crew and window, increments the order
        `version`, and adds the current estimate to the territory
        reservation." A rejected schedule performs none of these.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_work_order_schedule
        """
        terr, tech, crew, wo1, wo2 = self._setup_two_orders_low_cap()
        resp = api_client.schedule_work_order(
            wo2["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-01T09:10:00Z",
             "window_end": "2026-08-01T10:00:00Z"},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_TRAVEL_BUFFER_VIOLATION)

        assert get_work_order(wo2["id"])["status"] == "OPEN"
        assert get_territory(terr["id"])["repair_reserved_cents"] == 90000


class TestWorkOrderLifecycleConservesReservedBudget:
    def test_schedule_then_cancel_restores_reservation(self, api):
        """PRD §2.9: "Scheduling a work order adds its
        `current_estimate_cents` to the reservation" and "cancelling a
        `SCHEDULED` or `ON_HOLD` work order subtracts its
        `current_estimate_cents`; cancelling an `OPEN` work order changes
        nothing."

        Design: Difficulty/compensating_invariant/work_order_lifecycle_conserves_reserved_budget
        """
        terr, tech, crew = setup_territory_technician_crew()
        wo_a = _auto_work_order(terr, tech, priority="P2", address="5 V St",
                                caller="Xiu", phone="555-0123")
        assert get_territory(terr["id"])["repair_reserved_cents"] == 0, (
            "OPEN work orders hold no reservation")

        validate_success(api_client.schedule_work_order(
            wo_a["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-02T08:00:00Z",
             "window_end": "2026-08-02T09:00:00Z"},
            SUPERVISOR))
        assert get_territory(terr["id"])["repair_reserved_cents"] == 90000

        validate_success(api_client.cancel_work_order(wo_a["id"], SUPERVISOR))
        assert get_territory(terr["id"])["repair_reserved_cents"] == 0, (
            "schedule+cancel conserves the reservation")
        assert get_work_order(wo_a["id"])["status"] == "CANCELLED"

    def test_completion_releases_provisional_reservation(self, api):
        """PRD §2.9: "Completing a work order releases the reservation made at
        schedule time by subtracting its `provisional_estimate_cents`" — the
        release equals the reserved provisional estimate, not the final cost.
        §3.7 final cost for 2x1000c parts and 15 labor minutes at 6000c/h:
        2000 + 1500 = 3500.

        Design: Difficulty/compensating_invariant/work_order_lifecycle_conserves_reserved_budget
        """
        terr, tech, crew = setup_territory_technician_crew()
        wo_b = _auto_work_order(terr, tech, priority="P3", address="6 U St",
                                caller="Yan", phone="555-0124")
        assert wo_b["provisional_estimate_cents"] == 45000  # OUTSIDE_COMPANY x P3

        validate_success(api_client.schedule_work_order(
            wo_b["id"],
            {"crew_id": crew["id"], "window_start": "2026-08-02T10:00:00Z",
             "window_end": "2026-08-02T11:00:00Z"},
            SUPERVISOR))
        assert get_territory(terr["id"])["repair_reserved_cents"] == 45000

        validate_success(api_client.start_work_order(wo_b["id"], SUPERVISOR))
        completed = validate_success(api_client.complete_work_order(
            wo_b["id"],
            {"lines": [{"description": "valve", "quantity": 2,
                        "unit_price_cents": 1000, "discount_pct": 0}],
             "labor_minutes": 15},
            SUPERVISOR))
        assert completed["final_cost_cents"] == 3500  # 2000 + (15min -> 0.25h)*6000
        assert completed["labor_billed_minutes"] == 15, (
            "fifteen minutes bills as fifteen (PRD §3.7)")
        assert get_territory(terr["id"])["repair_reserved_cents"] == 0
