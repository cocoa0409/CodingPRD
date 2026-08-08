"""Difficulty queue A — resource temporal-overlap semantics and compensating
invariants.

Covers closed-interval room turnover with a strict buffer, half-open house
visit-calendar capacity, the balance-neutral assess/waive pair, and the
room-state partition conserved by a cancel.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    active_tenancy, active_tenancy_with_open_invoice, base_portfolio,
    new_room, new_member, new_application, screen, decide, new_membership,
    file_notice, do_move_out, set_clock, open_ticket, house_version,
    assess_fee, read_membership, read_room, read_house, read_ticket, read_invoice,
    read_application,
    create_membership_payload, manager_headers, finance_headers,
)


# ==========================================================================
# resource_temporal_overlap / room_turnover_closed_interval_plus_buffer_boundary
# ==========================================================================
class TestRoomTurnoverBuffer:
    def _setup_vacated_room_with_new_applicant(self, api):
        ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
        mem1 = ctx["membership"]["id"]
        file_notice(api, mem1, "MEMBER_INITIATED", "2026-06-18", member_id=ctx["member"]["id"])
        set_clock(api, "2026-06-18T00:00:00Z")
        do_move_out(api, mem1, "2026-06-18")
        bea = new_member(api, full_name="Bea Novak", email="bea@resident.example",
                         declared_monthly_income_cents=400000)
        app2 = new_application(api, bea["id"], ctx["room"]["id"],
                               requested_move_in_date="2026-06-20", billing_cycle="WEEKLY")
        screen(api, app2["id"], verified_monthly_income_cents=400000, report_reference="SCR-B1")
        decide(api, app2["id"], decision="APPROVE")
        return ctx, app2

    def test_move_in_on_buffered_edge_is_a_conflict(self, api):
        """PRD §3.4: "it must be strictly later than the effective_end_date plus the
        two-day turnover buffer of every prior tenancy on that same room whose
        tenancy_status is MOVED_OUT or NOTICE_GIVEN (ERR_ROOM_TURNOVER_CONFLICT).
        The occupancy interval on a room is closed on both ends, and the buffer is
        strict — a new move-in exactly on the buffered edge is a conflict."

        Design: Difficulty/resource_temporal_overlap/room_turnover_closed_interval_plus_buffer_boundary
        """
        ctx, app2 = self._setup_vacated_room_with_new_applicant(api)
        prior = read_membership(api, ctx["membership"]["id"])
        assert prior["effective_end_date"] == "2026-06-18"
        assert prior["tenancy_status"] == "MOVED_OUT"
        resp = api.create_membership(
            create_membership_payload(app2["id"], "2026-06-20"), manager_headers())
        validate_error(resp, ApiErrorId.ERR_ROOM_TURNOVER_CONFLICT.value)

    def test_move_in_one_day_past_the_buffer_is_accepted(self, api):
        """PRD §3.4: "it must be strictly later than the effective_end_date plus the
        two-day turnover buffer of every prior tenancy on that same room whose
        tenancy_status is MOVED_OUT or NOTICE_GIVEN (ERR_ROOM_TURNOVER_CONFLICT)."

        Design: Difficulty/resource_temporal_overlap/room_turnover_closed_interval_plus_buffer_boundary
        """
        ctx, app2 = self._setup_vacated_room_with_new_applicant(api)
        result = validate_success(api.create_membership(
            create_membership_payload(app2["id"], "2026-06-21"), manager_headers()), 201)
        assert result["tenancy_status"] == "PENDING_MOVE_IN"
        assert result["move_in_date"] == "2026-06-21"
        assert read_room(api, ctx["room"]["id"])["occupancy_state"] == "RESERVED"
        house = read_house(api, ctx["house"]["id"])
        assert house["reserved_room_count"] == 1
        assert house["vacant_room_count"] == 0


# ==========================================================================
# resource_temporal_overlap / house_visit_calendar_half_open_windows_with_capacity_two
# ==========================================================================
class TestHouseVisitCalendarCapacity:
    def _setup_two_scheduled_visits(self, api):
        base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
        house_id = base["house"]["id"]
        tickets = []
        for area, desc in [("COMMON_AREA", "Hallway light flickers"),
                           ("LAUNDRY", "Dryer drum squeals"),
                           ("SHARED_KITCHEN", "Disposal jammed"),
                           ("SHARED_BATH", "Slow drain")]:
            tickets.append(open_ticket(api, house_id, area=area, severity="NORMAL",
                                       description=desc))
        hv1 = house_version(api, house_id)
        validate_success(api.schedule_ticket(
            tickets[0]["id"], {"visit_start": "2026-06-10T09:00:00.000Z",
                               "visit_end": "2026-06-10T12:00:00.000Z",
                               "expected_house_version": hv1}, manager_headers()))
        hv2 = house_version(api, house_id)
        validate_success(api.schedule_ticket(
            tickets[1]["id"], {"visit_start": "2026-06-10T11:00:00.000Z",
                               "visit_end": "2026-06-10T13:00:00.000Z",
                               "expected_house_version": hv2}, manager_headers()))
        return base, tickets

    def test_third_overlapping_visit_exceeds_capacity(self, api):
        """PRD §3.9: "over the half-open interval from visit_start up to but
        excluding visit_end, no instant may be covered by more than two SCHEDULED
        visits of the same house, counting the new one. Touching windows do not
        overlap — a visit ending exactly when another begins is fine — but exceeding
        the ceiling anywhere is ERR_VISIT_CAPACITY_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/house_visit_calendar_half_open_windows_with_capacity_two
        """
        base, tickets = self._setup_two_scheduled_visits(api)
        house_id = base["house"]["id"]
        assert read_ticket(api, tickets[0]["id"])["status"] == "SCHEDULED"
        assert read_ticket(api, tickets[1]["id"])["status"] == "SCHEDULED"
        hv3 = house_version(api, house_id)
        resp = api.schedule_ticket(
            tickets[2]["id"], {"visit_start": "2026-06-10T11:30:00.000Z",
                               "visit_end": "2026-06-10T12:30:00.000Z",
                               "expected_house_version": hv3}, manager_headers())
        validate_error(resp, ApiErrorId.ERR_VISIT_CAPACITY_CONFLICT.value)
        t3 = read_ticket(api, tickets[2]["id"])
        assert t3["status"] == "OPEN"
        assert t3["visit_start"] is None
        assert house_version(api, house_id) == hv3  # rejected schedule left version untouched

    def test_touching_window_at_exclusive_end_is_accepted(self, api):
        """PRD §3.9: "Touching windows do not overlap — a visit ending exactly when
        another begins is fine — but exceeding the ceiling anywhere is
        ERR_VISIT_CAPACITY_CONFLICT." PRD §3.9: "Scheduling stores visit_start and
        visit_end, advances the ticket OPEN → SCHEDULED, and increments the house's
        version by one."

        Design: Difficulty/resource_temporal_overlap/house_visit_calendar_half_open_windows_with_capacity_two
        """
        base, tickets = self._setup_two_scheduled_visits(api)
        house_id = base["house"]["id"]
        # burn the capacity-conflict attempt so the version state matches the recipe
        hv3 = house_version(api, house_id)
        api.schedule_ticket(tickets[2]["id"],
                            {"visit_start": "2026-06-10T11:30:00.000Z",
                             "visit_end": "2026-06-10T12:30:00.000Z",
                             "expected_house_version": hv3}, manager_headers())
        hv4 = house_version(api, house_id)
        result = validate_success(api.schedule_ticket(
            tickets[3]["id"], {"visit_start": "2026-06-10T12:00:00.000Z",
                               "visit_end": "2026-06-10T14:00:00.000Z",
                               "expected_house_version": hv4}, manager_headers()))
        assert result["status"] == "SCHEDULED"
        assert result["visit_start"] == "2026-06-10T12:00:00.000Z"


# ==========================================================================
# compensating_invariant / late_fee_assess_then_waive_conserves_membership_balance_due
# ==========================================================================
class TestAssessWaiveConservesBalance:
    def _setup_overdue(self, api):
        ctx = active_tenancy_with_open_invoice(
            api, weekly=25000, monthly=100000, budget=60000,
            period_start="2026-06-01", period_end="2026-06-07")
        before = read_membership(api, ctx["membership"]["id"])["balance_due_cents"]
        set_clock(api, "2026-06-06T00:00:00Z")
        return ctx, before

    def test_assess_raises_balance_then_waive_restores_it(self, api):
        """PRD §3.6: "Assessing a fee and then waiving it must be perfectly
        balance-neutral." PRD §3.6: "it lowers total_amount_cents by exactly the
        current late_fee_cents, and it resets late_fee_cents to zero."

        Design: Difficulty/compensating_invariant/late_fee_assess_then_waive_conserves_membership_balance_due
        """
        ctx, before = self._setup_overdue(api)
        assert before == 39000
        invoice_id, mem_id = ctx["invoice"]["id"], ctx["membership"]["id"]
        assessed = assess_fee(api, invoice_id)
        assert assessed["late_fee_cents"] == 2500
        assert assessed["total_amount_cents"] == 41500
        assert read_membership(api, mem_id)["balance_due_cents"] == 41500
        waived = validate_success(api.fee_adjustment(invoice_id, {"action": "WAIVE"},
                                                     finance_headers()))
        assert waived["late_fee_cents"] == 0
        assert waived["total_amount_cents"] == 39000
        assert read_membership(api, mem_id)["balance_due_cents"] == 39000

    def test_waive_keeps_past_due_and_subtotal_stable(self, api):
        """PRD §3.6: "The invoice's status deliberately stays PAST_DUE — only a full
        payment clears that — and the tenancy's balance_due_cents returns to exactly
        its pre-assessment value."

        Design: Difficulty/compensating_invariant/late_fee_assess_then_waive_conserves_membership_balance_due
        """
        ctx, before = self._setup_overdue(api)
        invoice_id, mem_id = ctx["invoice"]["id"], ctx["membership"]["id"]
        assess_fee(api, invoice_id)
        validate_success(api.fee_adjustment(invoice_id, {"action": "WAIVE"}, finance_headers()))
        inv = read_invoice(api, invoice_id)
        assert inv["status"] == "PAST_DUE"
        assert inv["subtotal_cents"] == 39000
        assert read_membership(api, mem_id)["billing_status"] == "PAST_DUE"


def finance_headers():
    from test_helpers import finance_headers
    return finance_headers()


# ==========================================================================
# compensating_invariant / membership_cancel_conserves_house_room_state_partition
# ==========================================================================
class TestCancelConservesPartition:
    def _setup_three_rooms_one_approved(self, api):
        base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
        host_id, house_id = base["host"]["id"], base["house"]["id"]
        new_room(api, house_id, host_id, "101", weekly_rate_cents=25000, monthly_rate_cents=100000)
        room2 = new_room(api, house_id, host_id, "102",
                         weekly_rate_cents=20000, monthly_rate_cents=80000, private_bath=False)
        new_room(api, house_id, host_id, "103", weekly_rate_cents=30000,
                 monthly_rate_cents=120000, private_bath=False)
        ada = new_member(api, full_name="Ada Reyes", email="ada@resident.example",
                         declared_monthly_income_cents=400000)
        app1 = new_application(api, ada["id"], room2["id"],
                               requested_move_in_date="2026-06-04", billing_cycle="WEEKLY")
        screen(api, app1["id"], verified_monthly_income_cents=400000, report_reference="SCR-A1")
        decide(api, app1["id"], decision="APPROVE")
        return base, room2, app1

    def test_membership_create_reserves_room_and_partition_holds(self, api):
        """PRD §2.8: "after every request — cascades included — total_room_count
        must equal the sum of the other five counts." PRD §3.4: "it drives the room
        from VACANT to RESERVED; and it recomputes the house's room-state counts".

        Design: Difficulty/compensating_invariant/membership_cancel_conserves_house_room_state_partition
        """
        base, room2, app1 = self._setup_three_rooms_one_approved(api)
        before = read_house(api, base["house"]["id"])
        assert before["vacant_room_count"] == 3 and before["occupied_room_count"] == 0
        new_membership(api, app1["id"], "2026-06-04")
        house = read_house(api, base["house"]["id"])
        assert house["vacant_room_count"] == 2
        assert house["reserved_room_count"] == 1
        assert house["occupied_room_count"] == 0
        assert house["total_room_count"] == 3
        assert (house["vacant_room_count"] + house["reserved_room_count"]
                + house["occupied_room_count"] + house["notice_pending_room_count"]
                + house["out_of_service_room_count"]) == 3

    def test_cancel_restores_counts_to_pre_creation_values(self, api):
        """PRD §3.4: "It advances the tenancy PENDING_MOVE_IN → CANCELLED (terminal),
        returns the room RESERVED → VACANT, clears the room's available_from_date to
        null, and recomputes the house's room-state counts so that occupied_room_count
        and the partition invariant return to exactly their pre-creation values."

        Design: Difficulty/compensating_invariant/membership_cancel_conserves_house_room_state_partition
        """
        base, room2, app1 = self._setup_three_rooms_one_approved(api)
        mem = new_membership(api, app1["id"], "2026-06-04")
        cancelled = validate_success(api.cancel_membership(
            mem["id"], {"cancel_reason": "applicant took another room off-platform"},
            manager_headers()))
        assert cancelled["tenancy_status"] == "CANCELLED"
        house = read_house(api, base["house"]["id"])
        assert house["vacant_room_count"] == 3
        assert house["reserved_room_count"] == 0
        assert house["occupied_room_count"] == 0
        assert house["notice_pending_room_count"] == 0
        assert house["out_of_service_room_count"] == 0
        assert house["total_room_count"] == 3
        room = read_room(api, room2["id"])
        assert room["occupancy_state"] == "VACANT"
        assert room["available_from_date"] is None
        assert read_application(api, app1["id"])["status"] == "CONVERTED"
