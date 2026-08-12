"""Cleaning cycles, the unit rental loop, deep-clean cadence, and the recall
quarantine cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_and_activate_recall,
    create_catalog_item,
    create_customer,
    create_quoted_reservation,
    create_route,
    create_stop_payload,
    create_unit,
    confirm_reservation,
    deliver_reservation,
    get_reservation,
    get_route,
    get_route_stop,
    get_unit,
    list_lines,
    list_unit_tickets,
    open_manual_ticket,
    pickup_reservation,
    setup_confirmed_reservation,
    setup_delivered_reservation,
    setup_returned_reservation,
    validate_error,
    validate_success,
)


def _ops():
    return TEST_USERS["ops_admin_headers"]


def _insp():
    return TEST_USERS["inspector_1_headers"]


class TestInventoryUnitFullCleaningCycle:
    def test_pickup_moves_unit_to_in_cleaning_with_blocked_until(self, api):
        """PRD 3.5: "Completing a `PICKUP` stop moves the reservation
        `DELIVERED` to `RETURNED`: `returned_at` is stamped from the same
        clock, every `OUT` line becomes `RETURNED`, and each assigned unit
        moves `RENTED_OUT` to `AWAITING_CLEANING` with `blocked_until` set to
        `returned_at` plus the catalog item's `cleaning_turnaround_hours` —
        then, per returned unit, a cleaning ticket is auto-created and the unit
        moves immediately on to `IN_CLEANING`, as §3.6 describes."

        Returned at 2026-06-13T04:00:00Z with a 24h turnaround:
        blocked_until == 2026-06-14T04:00:00Z, unit IN_CLEANING, and the
        auto-created ticket is an OPEN STANDARD ticket.

        Design: Difficulty/non_linear_state_machine/inventory_unit_full_cleaning_cycle
        """
        ctx = setup_returned_reservation(pickup_clock="2026-06-13T04:00:00Z")
        unit = get_unit(ctx["units"][0]["id"])
        assert unit["status"] == "IN_CLEANING"
        assert unit["blocked_until"] == "2026-06-14T04:00:00Z"
        tickets = list_unit_tickets(unit["id"])
        assert len(tickets) == 1
        assert tickets[0]["ticket_type"] == "STANDARD"
        assert tickets[0]["status"] == "OPEN"

    def test_pass_returns_unit_to_available_and_increments_cycle(self, api):
        """PRD 3.6: "Passing a `STANDARD` ticket increments the unit's
        `cleans_since_deep` by one; passing a `DEEP` or
        `RECALL_DECONTAMINATION` ticket resets `cleans_since_deep` to zero."
        PRD 3.6: "A passed ticket returns an `IN_CLEANING` unit to
        `AVAILABLE`"

        Design: Difficulty/non_linear_state_machine/inventory_unit_full_cleaning_cycle
        """
        ctx = setup_returned_reservation(pickup_clock="2026-06-13T04:00:00Z")
        unit_id = ctx["units"][0]["id"]
        ticket = list_unit_tickets(unit_id)[0]
        passed = validate_success(
            api.pass_cleaning_ticket(
                ticket["id"], {"resolution_note": "ok"}, _insp()
            ),
            200,
        )
        assert passed["status"] == "PASSED"
        unit = get_unit(unit_id)
        assert unit["status"] == "AVAILABLE"
        assert unit["cleans_since_deep"] == 1


class TestRecallActivationDepth3Cascade:
    def _setup_confirmed_with_scheduled_delivery(self):
        ctx = setup_confirmed_reservation()
        route = create_route(route_date="2026-06-10", zone_code="Z1")
        stop = validate_success(
            api_client.add_route_stop(
                route["id"],
                create_stop_payload(
                    ctx["reservation"]["id"],
                    "DELIVERY_SETUP",
                    address="8 Cedar Rd",
                    time_window_start="2026-06-10T08:00:00Z",
                    time_window_end="2026-06-10T10:00:00Z",
                ),
                _ops(),
            ),
            201,
        )
        ctx["route"] = route
        ctx["stop"] = stop
        ctx["line"] = list_lines(ctx["reservation"]["id"])[0]
        return ctx

    def test_recall_quarantines_unit_and_strands_line(self, api):
        """PRD 3.6: "A `MANDATORY` activation triggers a three-deep cascade:
        first, every unit of the recalled catalog item in `AVAILABLE`,
        `RESERVED`, `RENTED_OUT`, `AWAITING_CLEANING`, or `IN_CLEANING` moves
        to `QUARANTINED` with its `version` bumped; second, for each
        quarantined unit that had been `RESERVED`, the holding `ALLOCATED` line
        drops to `PENDING_REALLOCATION` with its `assigned_unit_id` cleared to
        null and both line and reservation versions bumped"

        Design: Difficulty/transitive_cascade/recall_activation_depth3_cascade
        """
        ctx = self._setup_confirmed_with_scheduled_delivery()
        create_and_activate_recall(ctx["catalog"]["id"], severity="MANDATORY")
        assert get_unit(ctx["units"][0]["id"])["status"] == "QUARANTINED"
        line = list_lines(ctx["reservation"]["id"])[0]
        assert line["status"] == "PENDING_REALLOCATION"
        assert line["assigned_unit_id"] is None

    def test_recall_skips_delivery_stop_and_recomputes_weight(self, api):
        """PRD 3.6: "third, for every reservation holding a
        now-`PENDING_REALLOCATION` line, any `SCHEDULED` `DELIVERY_SETUP` stop
        for that reservation moves to `SKIPPED` and its route's
        `planned_weight_kg` is recomputed."

        Design: Difficulty/transitive_cascade/recall_activation_depth3_cascade
        """
        ctx = self._setup_confirmed_with_scheduled_delivery()
        assert get_route(ctx["route"]["id"])["planned_weight_kg"] == pytest.approx(12.0)
        create_and_activate_recall(ctx["catalog"]["id"], severity="MANDATORY")
        assert get_route_stop(ctx["stop"]["id"])["status"] == "SKIPPED"
        assert get_route(ctx["route"]["id"])["planned_weight_kg"] == pytest.approx(0.0)


class TestPickupCompletionDepth3Cascade:
    def test_pickup_returns_reservation_with_returned_at(self, api):
        """PRD 3.5: "Completing a `PICKUP` stop moves the reservation
        `DELIVERED` to `RETURNED`: `returned_at` is stamped from the same
        clock, every `OUT` line becomes `RETURNED`, and each assigned unit
        moves `RENTED_OUT` to `AWAITING_CLEANING` with `blocked_until` set to
        `returned_at` plus the catalog item's `cleaning_turnaround_hours` —
        then, per returned unit, a cleaning ticket is auto-created and the unit
        moves immediately on to `IN_CLEANING`, as §3.6 describes."

        Hop 1: the reservation lands RETURNED with returned_at stamped from the
        logical clock.

        Design: Difficulty/transitive_cascade/pickup_completion_depth3_cascade
        """
        ctx = setup_delivered_reservation()
        pickup = pickup_reservation(
            ctx["reservation"], clock="2026-06-13T04:00:00Z"
        )
        reservation = pickup["reservation"]
        assert reservation["status"] == "RETURNED"
        assert reservation["returned_at"] == "2026-06-13T04:00:00Z"
        lines = list_lines(reservation["id"])
        assert all(line["status"] == "RETURNED" for line in lines)

    def test_pickup_blocks_unit_and_autocreates_ticket(self, api):
        """PRD 3.5: "each assigned unit moves `RENTED_OUT` to
        `AWAITING_CLEANING` with `blocked_until` set to `returned_at` plus the
        catalog item's `cleaning_turnaround_hours`"
        PRD 3.6: "The auto-created ticket at pickup chooses its `ticket_type`
        by the unit's cycle counter: a `DEEP` ticket when the unit's
        `cleans_since_deep` has already reached the catalog item's
        `deep_clean_every_cycles`, otherwise `STANDARD`."

        Hops 2-3: returned at 2026-06-13T04:00:00Z with 24h turnaround, the
        unit sits IN_CLEANING with blocked_until 2026-06-14T04:00:00Z behind an
        auto-created OPEN STANDARD ticket.

        Design: Difficulty/transitive_cascade/pickup_completion_depth3_cascade
        """
        ctx = setup_returned_reservation(pickup_clock="2026-06-13T04:00:00Z")
        unit = get_unit(ctx["units"][0]["id"])
        assert unit["status"] == "IN_CLEANING"
        assert unit["blocked_until"] == "2026-06-14T04:00:00Z"
        tickets = list_unit_tickets(unit["id"])
        assert any(
            t["status"] == "OPEN" and t["ticket_type"] == "STANDARD" for t in tickets
        )


def test_cleaning_fail_returns_unit_to_awaiting(api):
    """PRD 3.6: "Failing a ticket sends an `IN_CLEANING` unit back to
    `AWAITING_CLEANING` with `cleans_since_deep` unchanged — the unit must be
    cleaned again — while a failed `RECALL_DECONTAMINATION` ticket leaves the
    unit `QUARANTINED`."

    Design: Corner/state_machines/cleaning_fail_returns_unit_to_awaiting
    """
    ctx = setup_returned_reservation(pickup_clock="2026-06-13T04:00:00Z")
    unit_id = ctx["units"][0]["id"]
    ticket = list_unit_tickets(unit_id)[0]
    failed = validate_success(
        api.fail_cleaning_ticket(
            ticket["id"], {"resolution_note": "still dirty"}, _insp()
        ),
        200,
    )
    assert failed["status"] == "FAILED"
    unit = get_unit(unit_id)
    assert unit["status"] == "AWAITING_CLEANING"
    assert unit["cleans_since_deep"] == 0


def test_deep_clean_required_when_cycles_reached(api):
    """PRD 3.6: "The auto-created ticket at pickup chooses its `ticket_type` by
    the unit's cycle counter: a `DEEP` ticket when the unit's
    `cleans_since_deep` has already reached the catalog item's
    `deep_clean_every_cycles`, otherwise `STANDARD`."
    PRD 3.6: "a manual `STANDARD` ticket is refused with
    `ERR_DEEP_CLEAN_REQUIRED` when the unit's `cleans_since_deep` has already
    reached the deep-clean cadence — a deep clean is due and cannot be
    skipped."

    With deep_clean_every_cycles 1: after one STANDARD pass
    (cleans_since_deep 1) the second pickup auto-creates a DEEP ticket; failing
    it leaves the count at 1, so a manual STANDARD ticket is rejected.

    Design: Corner/state_machines/deep_clean_required_when_cycles_reached
    """
    customer = create_customer()
    catalog = create_catalog_item(deep_clean_every_cycles=1)
    unit = create_unit(catalog["id"])

    # Cycle 1: rent 06-10 -> 06-13, return on time, pass the STANDARD ticket.
    res1 = create_quoted_reservation(
        customer["id"], lines=[{"catalog_item_id": catalog["id"]}]
    )
    confirm_reservation(res1["id"], customer["id"])
    deliver_reservation(get_reservation(res1["id"]))
    pickup_reservation(
        get_reservation(res1["id"]), clock="2026-06-13T04:00:00Z"
    )
    ticket1 = list_unit_tickets(unit["id"])[0]
    assert ticket1["ticket_type"] == "STANDARD"
    validate_success(api.pass_cleaning_ticket(ticket1["id"], {}, _insp()), 200)
    assert get_unit(unit["id"])["cleans_since_deep"] == 1

    # Cycle 2: rent 06-15 -> 06-18, return on time; the auto ticket must be DEEP.
    res2 = create_quoted_reservation(
        customer["id"],
        lines=[{"catalog_item_id": catalog["id"]}],
        start_date="2026-06-15",
        end_date="2026-06-18",
    )
    confirm_reservation(res2["id"], customer["id"])
    deliver_reservation(
        get_reservation(res2["id"]),
        clock="2026-06-15T09:00:00Z",
        route_date="2026-06-15",
    )
    pickup_reservation(
        get_reservation(res2["id"]),
        clock="2026-06-18T00:00:00Z",
        route_date="2026-06-18",
    )
    tickets = list_unit_tickets(unit["id"])
    ticket2 = tickets[1]
    assert ticket2["ticket_type"] == "DEEP", (
        "cleans_since_deep 1 >= deep_clean_every_cycles 1 must auto-create DEEP"
    )
    validate_success(api.fail_cleaning_ticket(ticket2["id"], {}, _insp()), 200)

    res = open_manual_ticket(unit["id"], ticket_type="STANDARD")
    validate_error(res, "ERR_DEEP_CLEAN_REQUIRED", expected_status=409)
