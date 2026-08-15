"""Cold storage occupancy, temperature classes, and withdrawal gates (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_storage_invariant,
    create_storage_slot,
    get_lot,
    get_slot,
    make_qa_manager_headers,
    pin_clock,
    put_away,
    setup_qa_pending_lot,
    setup_releasable_lot,
    setup_released_lot,
    setup_stored_released_lot,
    validate_error,
    validate_success,
    withdraw,
)

WAREHOUSE = TEST_USERS["warehouse_lead_headers"]


class TestStorageCapacity:
    def test_storage_exact_fill_then_overflow_rejected(self, api):
        """PRD §3.7: "The slot must have room: if adding the cases would push
        `occupied_cases` above `capacity_cases` the request is rejected with
        `ERR_STORAGE_CAPACITY_EXCEEDED`, though an exact fill is allowed."

        Design: Corner/validations/storage_exact_fill_then_overflow_rejected
        """
        pin_clock()
        # 8400 RETAIL units -> 700 cases; the slot holds 600.
        env = setup_qa_pending_lot(
            order_over={"units_planned": 8400},
            batch_units=8400,
            cell_over={"capacity_kg": 3000},
            cycle_over={"load_kg": 2200},
            complete_over={"actual_end": "2026-08-02T06:00:00Z"},
            run_over={"units_planned": 8400},
            complete_run_over={"units_packed": 8400, "film_meters_consumed": 3740},
        )
        assert env["lot"]["cases_produced"] == 700
        slot = create_storage_slot(capacity_cases=600)
        stored = put_away(env["lot"]["id"], slot["id"], 600)
        assert stored["stored_cases"] == 600
        after_fill = get_slot(slot["id"])
        assert after_fill["occupied_cases"] == 600, "exact fill to capacity is allowed"
        assert_storage_invariant(after_fill)

        resp = api.put_away_lot(env["lot"]["id"], {"slot_id": slot["id"], "cases": 1}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED, expected_status=409)


class TestTemperatureClass:
    def test_temperature_class_mismatch_rejected(self, api):
        """PRD §3.7: "Temperature class is enforced at the same moment: a lot whose
        recipe's `shelf_life_days` exceeds 545 days may only be put away into a
        `DEEP` slot, and attempting a `STANDARD` slot is rejected with
        `ERR_TEMPERATURE_CLASS_MISMATCH`."
        PRD §3.7: "A successful put-away grows both the lot's `stored_cases` and
        the slot's `occupied_cases` by `cases`."

        Design: Corner/validations/temperature_class_mismatch_rejected
        """
        pin_clock()
        env = setup_qa_pending_lot(recipe_over={"name": "R-Deep", "shelf_life_days": 600})
        slot_std = create_storage_slot(slot_code="S-STD", temperature_class="STANDARD")
        slot_deep = create_storage_slot(
            slot_code="S-DEEP", zone="DEEP_FREEZE", temperature_class="DEEP"
        )
        resp = api.put_away_lot(env["lot"]["id"], {"slot_id": slot_std["id"], "cases": 100}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_TEMPERATURE_CLASS_MISMATCH, expected_status=409)

        stored = put_away(env["lot"]["id"], slot_deep["id"], 100)
        assert stored["stored_cases"] == 100, (
            f"the 600-day recipe's lot is accepted by a DEEP slot, got {stored['stored_cases']}"
        )


class TestWithdrawalGates:
    def test_withdraw_expired_lot_rejected(self, api):
        """PRD §3.7: "When the `purpose` is shipment, one more gate applies: the
        current logical date must be on or before the lot's `final_expiry_date`,
        otherwise the withdrawal is rejected with `ERR_LOT_EXPIRED`."
        PRD §3.7: "The `final_expiry_date` is the calendar date of that cycle's
        `actual_end` plus the recipe's `shelf_life_days`"

        Design: Corner/validations/withdraw_expired_lot_rejected
        """
        pin_clock()
        # shelf_life_days 10; cycle actual_end 2026-08-02 -> final expiry 2026-08-12.
        env = setup_stored_released_lot(
            recipe_over={"name": "R-Short", "shelf_life_days": 10},
            put_away_cases=500,
        )
        lot = get_lot(env["lot"]["id"])
        assert lot["final_expiry_date"] == "2026-08-12", (
            f"final expiry anchors to the verified cycle end + 10 days, got "
            f"{lot['final_expiry_date']}"
        )
        pin_clock("2026-08-13T00:00:00Z")  # one day past final_expiry_date
        resp = api.withdraw_lot(env["lot"]["id"], {"cases": 10, "purpose": "SHIPMENT"}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED, expected_status=409)

    def test_withdraw_above_stored_rejected(self, api):
        """PRD §3.7: "The lot must be `RELEASED` — withdrawing from any other
        status is rejected with `ERR_LOT_STATE` — and the count may not exceed the
        lot's `stored_cases`, otherwise `ERR_INSUFFICIENT_CASES`."

        Design: Corner/validations/withdraw_above_stored_rejected
        """
        pin_clock()
        env = setup_stored_released_lot(put_away_cases=500)
        resp = api.withdraw_lot(env["lot"]["id"], {"cases": 600, "purpose": "SHIPMENT"}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CASES, expected_status=409)


class TestStorageInvariantAndDepletion:
    def test_putaway_exact_fill_accepted(self, api):
        """PRD §3.7: "A slot's `occupied_cases` starts at zero and is maintained as
        the sum of `stored_cases` over the lots pointing at it, with the standing
        invariant that occupied cases plus remaining free capacity always equal
        `capacity_cases`."
        PRD §3.7: "The slot must have room: if adding the cases would push
        `occupied_cases` above `capacity_cases` the request is rejected with
        `ERR_STORAGE_CAPACITY_EXCEEDED`, though an exact fill is allowed."

        Design: Difficulty/compensating_invariant/storage_putaway_withdraw_invariant
        """
        pin_clock()
        # 7200 RETAIL units -> exactly 600 cases; slot capacity 600.
        env = setup_released_lot(
            order_over={"units_planned": 7200},
            batch_units=7200,
            cell_over={"capacity_kg": 2500},
            cycle_over={"load_kg": 1900},
            run_over={"units_planned": 7200},
            complete_run_over={"units_packed": 7200, "film_meters_consumed": 3205},
        )
        assert env["lot"]["cases_produced"] == 600
        slot = create_storage_slot(capacity_cases=600)
        stored = put_away(env["lot"]["id"], slot["id"], 600)
        assert stored["stored_cases"] == 600
        after = get_slot(slot["id"])
        assert after["occupied_cases"] == 600, "exact fill: occupied == capacity"
        assert_storage_invariant(after)

    def test_withdraw_all_restores_slot_and_depletes_lot(self, api):
        """PRD §3.7: "A successful withdrawal lowers the lot's `stored_cases` and
        `cases_on_hand` by `cases`, lowers the slot's `occupied_cases` by the same
        amount, and — for shipment withdrawals — adds `cases` to `cases_shipped`;
        when `cases_on_hand` reaches zero the lot automatically moves from
        `RELEASED` to `DEPLETED`."

        Design: Difficulty/compensating_invariant/storage_putaway_withdraw_invariant
        """
        pin_clock()
        env = setup_stored_released_lot(
            order_over={"units_planned": 7200},
            batch_units=7200,
            cell_over={"capacity_kg": 2500},
            cycle_over={"load_kg": 1900},
            run_over={"units_planned": 7200},
            complete_run_over={"units_packed": 7200, "film_meters_consumed": 3205},
            slot_over={"capacity_cases": 600},
            put_away_cases=600,
        )
        assert env["slot"]["occupied_cases"] == 600
        depleted = withdraw(env["lot"]["id"], 600, "SHIPMENT")
        assert depleted["cases_on_hand"] == 0
        assert depleted["release_status"] == "DEPLETED", (
            f"lot auto-depletes when its last case leaves, got {depleted['release_status']}"
        )
        after = get_slot(env["slot"]["id"])
        assert after["occupied_cases"] == 0, (
            f"the compensating withdrawal restores occupancy exactly, got {after['occupied_cases']}"
        )
        assert_storage_invariant(after)


class TestReleaseSegregation:
    def test_segregation_lot_release_same_user_rejected(self, api):
        """PRD §2.1: "The operator who releases a finished-goods lot must differ
        from every operator who recorded a critical-control-point check on that
        lot's batch."
        PRD §2.1: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Design: Corner/rbac/segregation_lot_release_same_user_rejected
        """
        pin_clock()
        # Both CCP checks are recorded by the user id "shared-user".
        env = setup_releasable_lot(ccp_user_id="shared-user")
        resp = api.release_lot(env["lot"]["id"], make_qa_manager_headers("shared-user"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        released = validate_success(
            api.release_lot(env["lot"]["id"], make_qa_manager_headers("qa-mgr-1")),
            expected_status=200,
        )
        assert released["release_status"] == "RELEASED", (
            "a QAManager who performed no check on the batch may release"
        )
