"""Food batches: inspection cycle, expiry boundary, reject cascade, rescue
cap, and the conservation invariant over remaining_servings."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_food_batch,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    OFFICER,
    allocate,
    confirm_item,
    create_accepted_batch,
    create_food_batch,
    create_menu_day,
    create_menu_item,
    create_site,
    create_waste_log,
    inspect_batch,
    set_clock,
)


class TestQuarantineReinspectionCycle:
    """Queue A: non_linear_state_machine / food_batch_quarantine_reinspection_cycle."""

    def test_quarantined_batch_reinspected_to_accepted_with_reduced_remaining(self, api):
        """PRD 3.3: "the same begin-inspection action also re-opens inspection
        from `QUARANTINED` (the re-inspection cycle)".
        PRD 3.3: "A pass moves `INSPECTING` → `ACCEPTED` — again requiring the
        batch to be unexpired, else `ERR_BATCH_EXPIRED` — sets
        `inspection_result` to `PASSED`, and establishes `remaining_servings`
        as the batch's `quantity_servings` minus whatever has already been
        wasted."

        Design: Difficulty/non_linear_state_machine/food_batch_quarantine_reinspection_cycle
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="West Kitchen", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        batch = create_food_batch(
            site["id"], source_type="DONATION", item_description="Canned soup",
            quantity_servings=30, received_at="2026-08-10T07:00:00Z",
            use_by="2026-08-30T00:00:00Z",
        )
        batch = inspect_batch(batch["id"], "FAILED")
        assert batch["status"] == "QUARANTINED"

        menu_day = create_menu_day(site["id"], "2026-08-11")
        create_waste_log(menu_day["id"], batch["id"], as_officer=True,
                         servings_wasted=10, reason="SAFETY_DISCARD",
                         disposition="DISCARD")

        # Re-inspection cycle: QUARANTINED -> INSPECTING -> ACCEPTED.
        get_success_data(api.begin_inspection(batch["id"], OFFICER))
        batch = get_success_data(
            api.record_inspection(batch["id"], {"result": "PASSED"}, OFFICER)
        )
        assert batch["status"] == "ACCEPTED", (
            f"quarantined batch must be re-acceptable, got {batch['status']!r}"
        )
        assert batch["remaining_servings"] == 20, (
            f"remaining must be quantity 30 minus 10 discarded, "
            f"got {batch['remaining_servings']}"
        )

    def test_reinspection_from_quarantine_requires_safety_discard_log(self, api):
        """PRD 3.3: "Re-entering inspection from `QUARANTINED` additionally
        requires that a `SAFETY_DISCARD` waste log covering the contaminated
        portion has already been recorded for the batch".
        PRD 2.6: "State legality: the target entity is in a state from which
        the requested transition is defined, including all state-machine
        preconditions, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/food_batch_quarantine_reinspection_cycle
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="NoDiscard Kitchen", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        batch = create_food_batch(
            site["id"], source_type="DONATION", item_description="Dairy",
            quantity_servings=10, received_at="2026-08-10T07:00:00Z",
            use_by="2026-08-30T00:00:00Z",
        )
        batch = inspect_batch(batch["id"], "FAILED")
        assert batch["status"] == "QUARANTINED"

        # No SAFETY_DISCARD waste log recorded: the transition precondition fails.
        resp = api.begin_inspection(batch["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestUseByBoundary:
    """Queue A: boundary_precision_check / use_by_equality_expired."""

    def test_begin_inspection_at_exact_use_by_is_expired(self, api):
        """PRD 2.5: "a batch is unusable at or after its `use_by` (an instant
        exactly equal to `use_by` is already expired)".
        PRD 3.3: "Every begin-inspection path requires the logical clock to be
        strictly earlier than the batch's `use_by`; at or after that instant
        the batch is expired and the action fails with `ERR_BATCH_EXPIRED`."

        Design: Difficulty/boundary_precision_check/use_by_equality_expired
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Expiry Kitchen", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        b1 = create_food_batch(
            site["id"], source_type="DONATION", item_description="milk",
            quantity_servings=10, received_at="2026-08-10T07:00:00Z",
            use_by="2026-08-15T12:00:00Z",
        )
        set_clock("2026-08-15T12:00:00Z")
        resp = api.begin_inspection(b1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_BATCH_EXPIRED)

    def test_begin_inspection_one_second_before_use_by_succeeds(self, api):
        """PRD 3.3: "Every begin-inspection path requires the logical clock to
        be strictly earlier than the batch's `use_by`; at or after that
        instant the batch is expired and the action fails with
        `ERR_BATCH_EXPIRED`."

        Design: Difficulty/boundary_precision_check/use_by_equality_expired
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Expiry Kitchen 2", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        b2 = create_food_batch(
            site["id"], source_type="DONATION", item_description="yogurt",
            quantity_servings=10, received_at="2026-08-10T07:00:00Z",
            use_by="2026-08-15T12:00:01Z",
        )
        set_clock("2026-08-15T12:00:00Z")
        resp = api.begin_inspection(b2["id"], OFFICER)
        data = validate_success(resp, 200)
        assert data["status"] == "INSPECTING", (
            f"batch one second short of use_by must remain inspectable, "
            f"got {data['status']!r}"
        )


class TestStateBeatsSafetyPriority:
    """Queue A: priority_pair_validation_conflict / state_vs_business_safety_on_batch_inspection."""

    def test_rejected_and_expired_batch_begin_inspection_reports_invalid_state(self, api):
        """PRD 2.6: "the server evaluates them in a fixed priority order so
        the surfaced error is deterministic."
        PRD 2.6: "4. State legality: the target entity is in a state from
        which the requested transition is defined, including all state-machine
        preconditions, else `ERR_INVALID_STATE` (HTTP 409)." (listed before
        the food-safety gates of step 5)

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_batch_inspection
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Priority Kitchen", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        batch = create_food_batch(
            site["id"], source_type="DONATION", item_description="dairy",
            quantity_servings=10, received_at="2026-08-10T07:00:00Z",
            use_by="2026-08-15T00:00:00Z",
        )
        inspect_batch(batch["id"], "FAILED")
        get_success_data(api.reject_batch(batch["id"], OFFICER))
        # Advance past use_by so the batch is BOTH in a non-inspectable state
        # AND expired.
        set_clock("2026-08-20T00:00:00Z")

        resp = api.begin_inspection(batch["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, (
            "state legality (priority 4) precedes the food-safety gate "
            "(priority 5), so ERR_INVALID_STATE must surface"
        )

    def test_record_inspection_on_received_batch_reports_invalid_state(self, api):
        """PRD 2.6: "4. State legality: the target entity is in a state from
        which the requested transition is defined, including all state-machine
        preconditions, else `ERR_INVALID_STATE` (HTTP 409)."
        PRD 3.3: "Recording an outcome takes a `result` of `PASSED` or
        `FAILED`. A pass moves `INSPECTING` → `ACCEPTED`".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_batch_inspection
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Priority Kitchen 2", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        # Batch sits in RECEIVED (never began inspection) and is expired.
        batch = create_food_batch(
            site["id"], source_type="DONATION", item_description="oil",
            quantity_servings=10, received_at="2026-08-10T07:00:00Z",
            use_by="2026-08-12T00:00:00Z",
        )
        set_clock("2026-08-13T00:00:00Z")
        resp = api.record_inspection(batch["id"], {"result": "PASSED"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBatchRejectReleasesAllocations:
    def test_batch_reject_releases_allocations(self, api):
        """PRD 3.3: "A quarantined batch that will not be reworked is rejected
        outright, `QUARANTINED` → `REJECTED`, which forces `remaining_servings`
        to zero and releases all outstanding allocations."

        Design: Corner/state_machines/batch_reject_releases_allocations
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Rej Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        batch = create_accepted_batch(
            site["id"], item_description="fish", quantity_servings=20,
            unit_cost_cents_per_serving=90,
        )
        menu_day = create_menu_day(site["id"], "2026-08-11")
        item = create_menu_item(menu_day["id"], name="Fish Cake", planned_servings=10)
        allocate(item["id"], batch["id"], 10)

        # Routine re-inspection of the ACCEPTED batch, which fails.
        get_success_data(api.begin_inspection(batch["id"], OFFICER))
        batch = get_success_data(
            api.record_inspection(batch["id"], {"result": "FAILED"}, OFFICER)
        )
        assert batch["status"] == "QUARANTINED"

        get_success_data(api.reject_batch(batch["id"], OFFICER))
        batch = get_success_data(api.get_food_batch(batch["id"], MANAGER))
        assert batch["status"] == "REJECTED"
        assert batch["remaining_servings"] == 0, (
            f"rejection forces remaining_servings to zero, got {batch['remaining_servings']}"
        )

        data, meta = validate_paginated(api.list_item_allocations(item["id"], MANAGER))
        assert data == [], (
            f"rejecting the batch releases outstanding allocations, got {data!r}"
        )


class TestRescueCap:
    """Queue A: combinatorial_formula / portion_commitment_rescue_cap_mode_a."""

    def _setup_rescue_batch_and_item(self, api):
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="East Kitchen", dine_in_capacity=50,
                           togo_capacity_per_window=20, delivery_radius_km=8)
        batch = create_food_batch(
            site["id"], source_type="RESCUE", item_description="Rescued bread",
            quantity_servings=100, received_at="2026-08-10T07:00:00Z",
            use_by="2026-08-12T00:00:00Z",
        )
        batch = inspect_batch(batch["id"], "PASSED")
        menu_day = create_menu_day(site["id"], "2026-08-11")
        item = create_menu_item(menu_day["id"], name="Bread Pudding",
                                planned_servings=80)
        return site, batch, menu_day, item

    def test_rescue_cap_rejects_draw_above_half_quantity(self, api):
        """PRD 3.3: "The draw itself is bounded by four ceilings, and the
        recorded amount is the smallest of them: the requested amount, the
        batch's `remaining_servings`, the item's uncovered need (its
        `planned_servings` less servings already allocated), and — for
        `RESCUE` batches only — a rescue cap equal to one half of the batch's
        total `quantity_servings` for any single menu item."
        PRD 3.3: "A request asking for more servings than the batch still
        holds is rejected outright with `ERR_CAPACITY_FULL` rather than
        silently clamped, and a draw that would breach the rescue cap is
        rejected with the same code."

        Design: Difficulty/combinatorial_formula/portion_commitment_rescue_cap_mode_a
        """
        site, batch, menu_day, item = self._setup_rescue_batch_and_item(api)
        # min(70 requested, 100 remaining, 80 need, 50 rescue cap) = 50 < 70.
        resp = api.create_allocation(
            item["id"], {"food_batch_id": batch["id"], "servings": 70}, MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_FULL)

    def test_rescue_cap_boundary_accepts_half_rejects_one_more(self, api):
        """PRD 3.3: "The draw itself is bounded by four ceilings, and the
        recorded amount is the smallest of them: the requested amount, the
        batch's `remaining_servings`, the item's uncovered need (its
        `planned_servings` less servings already allocated), and — for
        `RESCUE` batches only — a rescue cap equal to one half of the batch's
        total `quantity_servings` for any single menu item."
        PRD 3.3: "A request asking for more servings than the batch still
        holds is rejected outright with `ERR_CAPACITY_FULL` rather than
        silently clamped, and a draw that would breach the rescue cap is
        rejected with the same code."

        Design: Difficulty/combinatorial_formula/portion_commitment_rescue_cap_mode_a
        """
        site, batch, menu_day, item = self._setup_rescue_batch_and_item(api)
        # Exactly at the cap (half of 100 = 50) is permitted.
        alloc = allocate(item["id"], batch["id"], 50)
        assert alloc["servings"] == 50
        batch = get_success_data(api.get_food_batch(batch["id"], MANAGER))
        assert batch["remaining_servings"] == 50

        # One more serving for the same item would take the item's draw to 51.
        resp = api.create_allocation(
            item["id"], {"food_batch_id": batch["id"], "servings": 1}, MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_FULL)


class TestInventoryConservation:
    """Queue A: compensating_invariant / batch_servings_conservation_under_alloc_and_waste."""

    def test_remaining_after_allocation_and_mixed_waste(self, api):
        """PRD 3.8: "After every log the invariant must hold exactly:
        `quantity_servings` equals allocated plus wasted plus remaining."
        PRD 3.8: "servings sent onward as `RESCUE_REDIRECT` also reduce
        `remaining_servings` — the food left the building, and they count when
        the system checks whether the batch should auto-transition to
        `DEPLETED` — but they are deliberately excluded from the kitchen's
        waste totals".

        Design: Difficulty/compensating_invariant/batch_servings_conservation_under_alloc_and_waste
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Conservation Kitchen", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        batch = create_accepted_batch(
            site["id"], item_description="potatoes", quantity_servings=50,
            unit_cost_cents_per_serving=40,
        )
        menu_day = create_menu_day(site["id"], "2026-08-11")
        item = create_menu_item(menu_day["id"], name="Potato Stew",
                                planned_servings=20)

        allocate(item["id"], batch["id"], 20)
        create_waste_log(menu_day["id"], batch["id"], servings_wasted=5,
                         reason="SPOILAGE", disposition="DISCARD")
        create_waste_log(menu_day["id"], batch["id"], servings_wasted=10,
                         reason="OVERPRODUCTION", disposition="RESCUE_REDIRECT")

        batch = get_success_data(api.get_food_batch(batch["id"], MANAGER))
        # 50 - 20 allocated - 5 discarded - 10 rescue-redirected = 15.
        assert batch["remaining_servings"] == 15, (
            f"conservation: 50 - 20 - 5 - 10 = 15, got {batch['remaining_servings']}"
        )

    def test_batch_depleted_when_remaining_reaches_zero(self, api):
        """PRD 3.3: "Finally, an `ACCEPTED` batch auto-transitions to
        `DEPLETED` the moment its `remaining_servings` reaches zero —
        everything allocated, served, wasted, or redirected."

        Design: Difficulty/compensating_invariant/batch_servings_conservation_under_alloc_and_waste
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Depletion Kitchen", dine_in_capacity=40,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        batch = create_accepted_batch(
            site["id"], item_description="rice", quantity_servings=10,
            unit_cost_cents_per_serving=40,
        )
        menu_day = create_menu_day(site["id"], "2026-08-11")
        item = create_menu_item(menu_day["id"], name="Rice Bowl",
                                planned_servings=10)
        allocate(item["id"], batch["id"], 10)

        batch = get_success_data(api.get_food_batch(batch["id"], MANAGER))
        assert batch["remaining_servings"] == 0
        assert batch["status"] == "DEPLETED", (
            f"batch with remaining_servings 0 must be DEPLETED, got {batch['status']!r}"
        )


class TestRescueRedirectViewDivergence:
    """Queue A: dual_variant_calc / inventory_conservation_view_divergence."""

    def test_rescue_redirect_depletes_batch_without_counting_as_waste(self, api):
        """PRD 3.8: "servings sent onward as `RESCUE_REDIRECT` also reduce
        `remaining_servings` — the food left the building, and they count when
        the system checks whether the batch should auto-transition to
        `DEPLETED`".
        PRD 3.3: "Finally, an `ACCEPTED` batch auto-transitions to `DEPLETED`
        the moment its `remaining_servings` reaches zero".

        Design: Difficulty/dual_variant_calc/inventory_conservation_view_divergence
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="North Kitchen", dine_in_capacity=50,
                           togo_capacity_per_window=20, delivery_radius_km=8)
        batch = create_accepted_batch(
            site["id"], item_description="Rice 50kg", quantity_servings=100,
            received_at="2026-08-10T07:00:00Z", use_by="2026-08-20T00:00:00Z",
            unit_cost_cents_per_serving=50,
        )
        menu_day = create_menu_day(site["id"], "2026-08-11")
        item = create_menu_item(menu_day["id"], name="Rice Bowl",
                                planned_servings=60)
        allocate(item["id"], batch["id"], 60)

        create_waste_log(menu_day["id"], batch["id"], servings_wasted=40,
                         reason="OVERPRODUCTION", disposition="RESCUE_REDIRECT")

        batch = get_success_data(api.get_food_batch(batch["id"], MANAGER))
        assert batch["remaining_servings"] == 0, (
            f"rescue-redirected servings leave the building: remaining must be "
            f"0, got {batch['remaining_servings']}"
        )
        assert batch["status"] == "DEPLETED", (
            f"remaining 0 must drive DEPLETED, got {batch['status']!r}"
        )

    def test_rescue_redirect_excluded_from_waste_ratio_numerator(self, api):
        """PRD 3.8: "Reconciliation computes the day's waste ratio: the
        numerator is the sum of `servings_wasted` over the day's waste logs
        with disposition `DISCARD` or `COMPOST`, and the denominator is the
        day's `committed_servings` at reconcile time."
        PRD 3.8: "but they are deliberately excluded from the kitchen's waste
        totals, because a successful diversion to another program is not
        waste."

        Design: Difficulty/dual_variant_calc/inventory_conservation_view_divergence
        """
        from test_helpers.fixtures import (
            create_service,
            lock_forecast,
            open_service,
            start_production,
        )

        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Diversion Kitchen", dine_in_capacity=200,
                           togo_capacity_per_window=100, delivery_radius_km=10)
        batch = create_accepted_batch(
            site["id"], item_description="stock", quantity_servings=140,
            unit_cost_cents_per_serving=50,
        )
        menu_day = create_menu_day(site["id"], "2026-08-10")
        item = create_menu_item(menu_day["id"], name="Meal", planned_servings=100)
        allocate(item["id"], batch["id"], 100)
        confirm_item(item["id"])
        lock_forecast(menu_day["id"])
        start_production(menu_day["id"])
        service = create_service(
            menu_day["id"], service_model="DINE_IN",
            window_start="2026-08-10T11:00:00Z",
            window_end="2026-08-10T13:00:00Z", capacity=200,
        )
        set_clock("2026-08-10T10:30:00Z")
        open_service(service["id"])
        get_success_data(api.close_service(service["id"], MANAGER))

        # 40 servings leave via rescue redirect: excluded from the numerator.
        create_waste_log(menu_day["id"], batch["id"], servings_wasted=40,
                         reason="OVERPRODUCTION", disposition="RESCUE_REDIRECT")
        get_success_data(api.reconcile_menu_day(menu_day["id"], MANAGER))

        summary = get_success_data(api.get_menu_day_summary(menu_day["id"], MANAGER))
        ratio = summary.get("waste_ratio")
        assert ratio is not None and float(ratio) == pytest.approx(0.0, abs=1e-9), (
            f"RESCUE_REDIRECT must not count as waste: ratio must be 0, got {ratio!r}"
        )
