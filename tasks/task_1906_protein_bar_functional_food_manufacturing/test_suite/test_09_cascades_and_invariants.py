"""Cross-entity cascades (lot reject, revision supersede) and conserved
quantities (lot kilograms, line-day minutes) (PRD §2.8, §3.2, §3.4, §3.6)."""
from test_helpers import (
    assert_2dp,
    assert_day_availability_invariant,
    assert_lot_mass_invariant,
    fixtures,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

QM = TEST_USERS["quality_manager_headers"]
PP = TEST_USERS["production_planner_headers"]


def _lot_amounts(lot_id):
    lot = validate_success(client.get_ingredient_lot(lot_id, PP), 200)
    assert_lot_mass_invariant(lot)
    return lot["available_qty_kg"], lot["reserved_qty_kg"], lot["consumed_qty_kg"]


def _day_availability(line_id, date="2026-08-05"):
    data = validate_success(client.get_day_availability(line_id, date, PP), 200)
    assert_day_availability_invariant(data)
    return data


class TestLotRejectCascade:
    def test_reject_releases_reservation_and_deschedules_run(self, api):
        """PRD §3.2: "Link two: each such run recomputes its
        `ingredient_readiness`, and any run whose ingredient lines are no
        longer fully reserved drops to `BLOCKED`."
        PRD §3.2: "Link three: a run whose readiness flipped from `READY` to
        `BLOCKED` while sitting in `SCHEDULED` automatically falls back to
        `PLANNED` with `cancel_reason` `INGREDIENT_SHORTAGE`; its line slot
        moves from `CONFIRMED` to `RELEASED`, and its changeover event moves
        to `CANCELLED`."

        Design: Difficulty/transitive_cascade/lot_reject_deshedule_chain
        """
        ns = fixtures.setup_run_scheduled(planned_cases=100)
        plant = ns.plant
        # Control: the run was fully reserved at creation.
        assert ns.run["ingredient_readiness"] == "READY"
        rejected = validate_success(client.reject_lot(plant.wl["id"], QM), 200)
        assert rejected["status"] == "REJECTED"
        assert_2dp(rejected["reserved_qty_kg"], 0.0, "reserved_qty_kg")
        run = validate_success(client.get_production_run(ns.run["id"], QM), 200)
        assert run["ingredient_readiness"] == "BLOCKED"
        assert run["status"] == "PLANNED"
        assert run["cancel_reason"] == "INGREDIENT_SHORTAGE"

    def test_reject_releases_slot_but_validated_changeover_survives(self, api):
        """PRD §3.2: "Link three: a run whose readiness flipped from `READY`
        to `BLOCKED` while sitting in `SCHEDULED` automatically falls back to
        `PLANNED` with `cancel_reason` `INGREDIENT_SHORTAGE`; its line slot
        moves from `CONFIRMED` to `RELEASED`, and its changeover event moves
        to `CANCELLED`."
        PRD §3.7: "When the run an event feeds is cancelled or de-scheduled,
        the system moves the event to `CANCELLED` from `PENDING`,
        `CLEANING_LOGGED`, or `FAILED`; these system cancellations are
        bookkeeping-only and do not increment the event's `version`."

        Design: Difficulty/transitive_cascade/lot_reject_deshedule_chain
        """
        ns = fixtures.setup_run_scheduled(planned_cases=100)
        plant = ns.plant
        validate_success(client.reject_lot(plant.wl["id"], QM), 200)
        slot = fixtures.get_run_slot(ns.run["id"])
        assert slot["status"] == "RELEASED"
        # The fresh-line changeover was NONE and thus created VALIDATED, a
        # terminal state the cascade does not retroactively cancel.
        changeover = fixtures.get_to_changeover(ns.run["id"])
        assert changeover["required_level"] == "NONE"
        assert changeover["status"] == "VALIDATED"


class TestRevisionApproveSupersedeCascade:
    def test_approve_supersedes_predecessor_and_cancels_open_run(self, api):
        """PRD §3.4: "Approval fires the two-link **CASCADE-SUPERSEDE**: the
        previously `APPROVED` revision of the same formula, if one exists,
        moves to `SUPERSEDED` (a terminal, self-referential transition within
        the formula's own revision set); and every production run still in
        `PLANNED` or `SCHEDULED` that references the superseded revision is
        automatically `CANCELLED` with `cancel_reason` `FORMULA_SUPERSEDED`"
        PRD §3.4: "the formula's `approved_revision_id` is recomputed to point
        at the newly approved revision."

        Design: Difficulty/transitive_cascade/revision_approve_supersede_cancel_chain
        """
        ns = fixtures.setup_supersede_scenario()
        validate_success(client.approve_revision(ns.r9b["id"], QM), 200)
        superseded = validate_success(client.get_revision(ns.r9a["id"], QM), 200)
        assert superseded["status"] == "SUPERSEDED"
        run = validate_success(client.get_production_run(ns.run_x["id"], QM), 200)
        assert run["status"] == "CANCELLED"
        assert run["cancel_reason"] == "FORMULA_SUPERSEDED"
        formula = validate_success(client.get_formula(ns.plant.f1["id"], QM), 200)
        assert formula["approved_revision_id"] == ns.r9b["id"]

    def test_supersede_releases_slot_and_lot_reservation(self, api):
        """PRD §3.4: "every production run still in `PLANNED` or `SCHEDULED`
        that references the superseded revision is automatically `CANCELLED`
        with `cancel_reason` `FORMULA_SUPERSEDED`, its line slot moving from
        `CONFIRMED` to `RELEASED`, its changeover event moving to `CANCELLED`,
        and its lot reservations released with each affected lot's
        `reserved_qty_kg` decremented."

        Design: Difficulty/transitive_cascade/revision_approve_supersede_cancel_chain
        """
        ns = fixtures.setup_supersede_scenario()
        validate_success(client.approve_revision(ns.r9b["id"], QM), 200)
        slot = fixtures.get_run_slot(ns.run_x["id"])
        assert slot["status"] == "RELEASED"
        lot = validate_success(client.get_ingredient_lot(ns.plant.wl["id"], QM), 200)
        assert_2dp(lot["reserved_qty_kg"], 0.0, "reserved_qty_kg")
        assert_2dp(lot["available_qty_kg"], 200.0, "available_qty_kg")
        assert_lot_mass_invariant(lot)


class TestLotMassConservation:
    def test_reservations_accumulate_within_conservation(self, api):
        """PRD §2.8: "Every ingredient lot is a small ledger governed by a
        conservation invariant: its `available_qty_kg` always equals its
        `received_qty_kg` minus its `reserved_qty_kg` minus its
        `consumed_qty_kg`."
        PRD §2.8: "Reservations are created when a production run is planned,
        drawing first-in-first-out from `RELEASED` lots of the required
        ingredient ordered by `received_at` ascending with ties broken by
        `created_at` ascending"

        Design: Difficulty/compensating_invariant/lot_mass_conservation_across_reserve_consume_release
        """
        plant = fixtures.setup_basic_plant(whey_qty=100, syrup_qty=100)
        fixtures.set_clock("2026-08-05T06:00:00Z")
        fixtures.create_run(plant.r1["id"], plant.ag["id"], plant.ln1["id"], 100)
        av, rv, cv = _lot_amounts(plant.wl["id"])
        assert (round(av, 2), round(rv, 2), round(cv, 2)) == (60.0, 40.0, 0.0)
        fixtures.create_run(plant.r1["id"], plant.ag["id"], plant.ln1["id"], 100)
        av, rv, cv = _lot_amounts(plant.wl["id"])
        assert (round(av, 2), round(rv, 2), round(cv, 2)) == (20.0, 80.0, 0.0)

    def test_cancel_restores_and_start_converts_reservation(self, api):
        """PRD §2.8: "Every ingredient lot is a small ledger governed by a
        conservation invariant: its `available_qty_kg` always equals its
        `received_qty_kg` minus its `reserved_qty_kg` minus its
        `consumed_qty_kg`."
        PRD §3.8: "Cancelling a `PLANNED` run releases all of its
        reservations, decrementing each affected lot's `reserved_qty_kg`, and
        stamps `cancel_reason` `OPERATOR_CANCEL`."
        PRD §2.8: "Consumption happens when a run actually starts production,
        moving quantity from `reserved_qty_kg` into `consumed_qty_kg` without
        changing `available_qty_kg`."

        Design: Difficulty/compensating_invariant/lot_mass_conservation_across_reserve_consume_release
        """
        plant = fixtures.setup_basic_plant(whey_qty=100, syrup_qty=100)
        fixtures.set_clock("2026-08-05T06:00:00Z")
        run1 = fixtures.create_run(plant.r1["id"], plant.ag["id"],
                                   plant.ln1["id"], 100)
        run2 = fixtures.create_run(plant.r1["id"], plant.ag["id"],
                                   plant.ln1["id"], 100)
        # Compensating action: cancelling run2 restores its reservation.
        validate_success(client.cancel_run(run2["id"], PP), 200)
        av, rv, cv = _lot_amounts(plant.wl["id"])
        assert (round(av, 2), round(rv, 2), round(cv, 2)) == (60.0, 40.0, 0.0)
        # Starting run1 converts its reservation into consumption.
        fixtures.schedule_run_fresh(run1["id"], plant.ln1["id"])
        validate_success(client.verify_pre_run(run1["id"], QM), 200)
        validate_success(client.start_run(run1["id"], PP), 200)
        av, rv, cv = _lot_amounts(plant.wl["id"])
        assert (round(av, 2), round(rv, 2), round(cv, 2)) == (60.0, 0.0, 40.0)


class TestLineFreeMinutesRestored:
    def test_occupied_buffered_free_accumulate_per_day(self, api):
        """PRD §3.6: "reports `occupied_minutes` — the sum, over the line's
        `CONFIRMED` slots, of each slot's overlap with the day window running
        from midnight UTC of that date (inclusive) to midnight UTC of the next
        (exclusive) — plus `buffered_minutes`, the sum of `buffer_minutes`
        over the `CONFIRMED` slots whose `start_utc` falls inside that day,
        and `free_minutes`, the day's 1,440 minutes minus occupied minus
        buffered."

        Design: Difficulty/compensating_invariant/line_free_minutes_restored_after_cancel
        """
        ns = fixtures.setup_day_availability_scenario()
        day = _day_availability(ns.plant.ln1["id"])
        # run A 120 min (buffer 0, first-run NONE) + run C 90 min (buffer 30,
        # DRY_CLEAN): occupied 210, buffered 30, free 1200.
        assert day["occupied_minutes"] == 210
        assert day["buffered_minutes"] == 30
        assert day["free_minutes"] == 1200
        run_b = fixtures.create_run(
            ns.plant.r1["id"], ns.plant.ag["id"], ns.plant.ln1["id"], 100
        )
        fixtures.schedule_run_fresh(
            run_b["id"], ns.plant.ln1["id"],
            "2026-08-05T10:30:00Z", "2026-08-05T12:00:00Z",
        )
        day = _day_availability(ns.plant.ln1["id"])
        # run B adds 90 occupied + 30 buffered (DRY_CLEAN): 300/60/1080.
        assert day["occupied_minutes"] == 300
        assert day["buffered_minutes"] == 60
        assert day["free_minutes"] == 1080

    def test_cancel_restores_free_minutes_exactly(self, api):
        """PRD §3.6: "Free minutes are never negative, and scheduling a slot
        followed by its compensating cancellation or release restores the
        day's free minutes exactly."
        PRD §3.8: "Cancelling a `SCHEDULED` run does the same and additionally
        moves its slot from `CONFIRMED` to `RELEASED` and its changeover event
        to `CANCELLED` unless that event already rests in the terminal
        `VALIDATED` state."

        Design: Difficulty/compensating_invariant/line_free_minutes_restored_after_cancel
        """
        ns = fixtures.setup_day_availability_scenario()
        run_b = fixtures.create_run(
            ns.plant.r1["id"], ns.plant.ag["id"], ns.plant.ln1["id"], 100
        )
        fixtures.schedule_run_fresh(
            run_b["id"], ns.plant.ln1["id"],
            "2026-08-05T10:30:00Z", "2026-08-05T12:00:00Z",
        )
        assert _day_availability(ns.plant.ln1["id"])["free_minutes"] == 1080
        cancelled = validate_success(client.cancel_run(run_b["id"], PP), 200)
        assert cancelled["status"] == "CANCELLED"
        day = _day_availability(ns.plant.ln1["id"])
        assert day["occupied_minutes"] == 210
        assert day["buffered_minutes"] == 30
        assert day["free_minutes"] == 1200
