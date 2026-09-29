"""Corner behaviour of the tail of the validation ladder: the quality and asset gates, delivery-mode
coherence, the window and isolation conflicts, and the fiscal ceilings evaluated last of all."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    fixtures as fx, factories as F,
)

BIG_CREDIT = 100_000_000_000
LONG_PERMIT = {"valid_from_utc": "2025-01-01T00:00:00Z",
               "valid_until_utc": "2028-01-01T00:00:00Z"}


class TestQualityAndAssetGateCorners:
    def test_free_water_is_reported_as_water_and_not_as_a_quarantine(self, api):
        """PRD §3.4: "Signing a tank's quality release, `ON_TEST → RELEASED`, is a `QualityInspector`
        action requiring three things: a periodic tank QA sample exists for this tank whose
        `sample_purpose` is `PERIODIC_TANK_QA`, whose `status` is `TESTED`, whose `verdict` is `PASS`, and
        whose `created_at` is the latest of any sample for this tank; the acting identifier differs from
        that sample's `drawn_by_user_id`, since an inspector may not release a tank on the strength of a
        sample they drew themselves; and the tank's `water_bottom_mm` is strictly below 25.0."
        PRD §3.4: "Quarantining a tank, `RELEASED → QUARANTINED`, arrives by three different routes: a
        direct request by a `QualityInspector` carrying an optional `reason`, the cascade hop from a receipt
        quarantine described above, or a gauge measurement reporting free water at or above 25.0
        millimetres."
        PRD §3.4: "The measurement writes `last_gauge_volume_liters`, stamps `last_gauge_at_utc` from the
        logical clock, and stores the water depth."

        Design: Corner/validations/water_bottom_exceeded_is_its_own_diagnosis
        """
        env = fx.setup_fuel_farm()
        tank = fx.register_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                opening_volume_liters=100_000.0)
        sample = fx.draw_tank_sample(tank["id"], fx.INSPECTOR_A)
        fx.post_results(sample["id"], fx.INSPECTOR_A, observed_density_kg_per_m3=795.0)

        fx.gauge_tank(tank["id"], 100_000.0, water_bottom_mm=30.0)
        wet = fx.read_tank(tank["id"])
        assert wet["quality_status"] == "ON_TEST", \
            "the gauge quarantine hop starts from RELEASED, so a tank on test simply stays on test"
        assert wet["water_bottom_mm"] == pytest.approx(30.0, abs=0.005)

        validate_error(api.release_tank_quality(tank["id"], fx.INSPECTOR_B),
                       ApiErrorId.ERR_WATER_BOTTOM_EXCEEDED, 409)

        fx.gauge_tank(tank["id"], 100_000.0, water_bottom_mm=1.0)
        released = fx.release_tank_quality(tank["id"], fx.INSPECTOR_B)
        assert released["quality_status"] == "RELEASED", \
            "with the water drained the very same signature is accepted"

    def test_all_three_down_states_refuse_an_assignment_with_one_identifier(self, api):
        """PRD §3.6: "Both branches require the asset's `status` to be `IN_SERVICE` (otherwise
        `ERR_ASSET_NOT_SERVICEABLE`) and the farm not to be `FROZEN`."
        PRD §3.7: "A `FarmOperator` or `ConsortiumAdmin` may also drive an asset's `status` directly by
        supplying a `to_status`; moving to `DOWN_FOR_FILTER` from either `FILTER_DUE` or `IN_SERVICE`
        requires that no order on the asset is currently `ASSIGNED` or `FUELING`."
        PRD §3.7: "Once the score falls **below 60** the asset is driven `IN_SERVICE →
        DOWN_MAINTENANCE`; that move is also reachable from `FILTER_DUE`, by an explicit status change, and
        by the farm freeze cascade."

        Design: Corner/validations/asset_not_serviceable_covers_all_three_down_states
        """
        env = fx.setup_fuel_farm(clock="2025-08-10T06:00:00Z", permit_overrides=LONG_PERMIT)
        farm_id = env["farm"]["id"]
        tank = fx.make_released_tank(farm_id, capacity_liters=5_000_000.0,
                                     safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                     opening_volume_liters=1_000_000.0)
        trucks = [fx.register_truck(farm_id, tank_capacity_liters=40_000.0) for _ in range(3)]

        fx.set_clock("2026-08-10T06:00:00Z")
        assert all(fx.read_asset(t["id"])["status"] == "FILTER_DUE" for t in trucks), \
            "a whole year of shelf life has expired on every one of them"
        validate_success(api.change_asset_status(trucks[1]["id"],
                                                 {"to_status": "DOWN_FOR_FILTER"}, fx.OPERATOR))
        validate_success(api.change_asset_status(trucks[2]["id"],
                                                 {"to_status": "DOWN_MAINTENANCE"}, fx.OPERATOR))

        account = fx.open_account(base_price_cents_per_liter=62.00,
                                  credit_limit_cents=BIG_CREDIT)
        flight = fx.register_flight(account["id"], stand_code="F01",
                                    scheduled_departure_utc="2026-08-10T08:00:00Z")
        auth = fx.issue_authorization(account["id"], flight["id"],
                                      max_authorized_liters=20_000.0)
        order = fx.create_order(flight["id"], auth["id"], tank["id"],
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=20_000.0,
                                window_start_utc=fx.WINDOW_START,
                                window_end_utc=fx.WINDOW_END)
        fx.authorize_order(order["id"])

        for truck in trucks:
            validate_error(api.assign_order(order["id"],
                                            {"fueling_asset_id": truck["id"]}, fx.AGENT),
                           ApiErrorId.ERR_ASSET_NOT_SERVICEABLE, 409)
        assert fx.read_order(order["id"])["status"] == "AUTHORIZED"
        assert fx.read_order(order["id"])["fueling_asset_id"] is None, \
            "one identifier covers advisory, filter and maintenance downtime alike"


class TestDeliveryModeCorners:
    def test_the_mode_mismatch_bites_in_both_directions_at_assignment(self, api):
        """PRD §3.6: "**For `TRUCK` delivery** the asset's `asset_type` must be `TRUCK`, no
        `hydrant_pit_id` may be present, and the truck must be able to supply the volume — either its own
        `onboard_volume_liters` is at least the requested volume, or its source tank's
        `available_volume_liters` is at least the requested volume."
        PRD §3.6: "**For `HYDRANT` delivery** the asset's `asset_type` must be `HYDRANT_CART`, a
        `hydrant_pit_id` must be supplied, that pit's `status` must be `AVAILABLE`, and the pit's
        `stand_code` must equal the flight's `stand_code` — a cart cannot reach a stand the pit does not
        serve."
        PRD §2.10: "**Mode, temporal and capacity checks.** Delivery-mode coherence
        (`ERR_DELIVERY_MODE_MISMATCH`) is checked on order creation and order assignment."

        Design: Corner/validations/delivery_mode_mismatch_covers_both_directions
        """
        hydrant = fx.setup_hydrant_order(target_state="AUTHORIZED", stand_code="A12",
                                         account_overrides={"credit_limit_cents": BIG_CREDIT})
        wrong_asset = fx.register_truck(hydrant["farm"]["id"], tank_capacity_liters=40_000.0)
        validate_error(api.assign_order(hydrant["order"]["id"],
                                        {"fueling_asset_id": wrong_asset["id"],
                                         "hydrant_pit_id": hydrant["pit"]["id"]}, fx.AGENT),
                       ApiErrorId.ERR_DELIVERY_MODE_MISMATCH, 422)

        truck = fx.setup_truck_order(target_state="AUTHORIZED",
                                     account_overrides={"credit_limit_cents": BIG_CREDIT})
        pit = fx.register_pit(truck["farm"]["id"], truck["tank"]["id"], stand_code="A12")
        validate_error(api.assign_order(truck["order"]["id"],
                                        {"fueling_asset_id": truck["truck"]["id"],
                                         "hydrant_pit_id": pit["id"]}, fx.AGENT),
                       ApiErrorId.ERR_DELIVERY_MODE_MISMATCH, 422)

        assert fx.read_order(truck["order"]["id"])["hydrant_pit_id"] is None, \
            "a truck order must leave the pit reference null, and a hydrant order must fill it"

    def test_a_farm_without_a_loop_cannot_take_a_hydrant_order_at_all(self, api):
        """PRD §3.6: "Delivery-mode coherence is likewise checked at creation and again at assignment:
        `HYDRANT` demands a farm whose `hydrant_system_available` is true, and `TRUCK` demands that no
        `hydrant_pit_id` be supplied; violations are `ERR_DELIVERY_MODE_MISMATCH`."
        PRD §3.1: "Two optional inputs shape the farm's later arithmetic: `hydrant_system_available`, a
        boolean defaulting to false that determines whether the farm can serve hydrant deliveries at all,
        and `unpumpable_bottom_liters`, the volume in each tank that sits below the suction point and can
        never be issued, which must be zero or greater and defaults to 500.0 liters."
        PRD §2.10: "**Mode, temporal and capacity checks.** Delivery-mode coherence
        (`ERR_DELIVERY_MODE_MISMATCH`) is checked on order creation and order assignment."

        Design: Corner/validations/order_mode_must_match_the_farm_capability
        """
        env = fx.setup_farm_with_released_tank(hydrant_system_available=False)
        assert fx.read_farm(env["farm"]["id"])["hydrant_system_available"] is False
        airline = fx.setup_airline(account_overrides={"credit_limit_cents": BIG_CREDIT})

        validate_error(api.create_fueling_order(
            F.create_fueling_order_payload(
                airline["flight"]["id"], airline["auth"]["id"], env["tank"]["id"],
                airline["auth"]["authorization_code"], delivery_mode="HYDRANT",
                requested_uplift_liters=20_000.0, window_start_utc=fx.WINDOW_START,
                window_end_utc=fx.WINDOW_END), fx.AGENT),
            ApiErrorId.ERR_DELIVERY_MODE_MISMATCH, 422)

        overland = fx.create_order(airline["flight"]["id"], airline["auth"]["id"],
                                   env["tank"]["id"], airline["auth"]["authorization_code"],
                                   delivery_mode="TRUCK", requested_uplift_liters=20_000.0,
                                   window_start_utc=fx.WINDOW_START,
                                   window_end_utc=fx.WINDOW_END)
        assert overland["status"] == "REQUESTED", \
            "the refusal lands at creation, long before any pit could be named"


class TestWindowAndIsolationCorners:
    def test_the_window_end_instant_is_already_too_late_to_start(self, api):
        """PRD §3.6: "Starting fuelling, `ASSIGNED → FUELING`, is gated on time and fitness."
        PRD §3.6: "The logical clock must be at or after `window_start_utc` and strictly before
        `window_end_utc`, or the start is refused with `ERR_OUTSIDE_FUELING_WINDOW`."
        PRD §2.2: "Time windows in this domain are consistently **half-open** — start inclusive, end
        exclusive — with exactly one deliberate exception."

        Design: Corner/validations/outside_fueling_window_is_evaluated_against_the_logical_clock
        """
        env = fx.setup_truck_order(target_state="ASSIGNED", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"credit_limit_cents": BIG_CREDIT},
                                   order_overrides={"window_start_utc": "2026-08-10T06:00:00Z",
                                                    "window_end_utc": "2026-08-10T07:30:00Z"})
        account_id, tank_id = env["account"]["id"], env["tank"]["id"]

        fx.set_clock("2026-08-10T07:30:00Z")
        validate_error(api.start_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_OUTSIDE_FUELING_WINDOW, 409)

        flight = fx.register_flight(account_id, stand_code="G02",
                                    scheduled_departure_utc="2026-08-10T10:00:00Z")
        auth = fx.issue_authorization(account_id, flight["id"],
                                      max_authorized_liters=20_000.0)
        later = fx.create_order(flight["id"], auth["id"], tank_id,
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=20_000.0,
                                window_start_utc="2026-08-10T08:00:00Z",
                                window_end_utc="2026-08-10T09:00:00Z")
        fx.authorize_order(later["id"])
        fx.assign_order(later["id"], env["truck"]["id"])

        fx.set_clock("2026-08-10T08:00:00Z")
        started = fx.start_order(later["id"])
        assert started["status"] == "FUELING", \
            "the opening instant is inside the window even though the closing instant is not"

    def test_two_tanks_competing_for_isolation_get_their_own_conflict_identifier(self, api):
        """PRD §3.4: "Isolating a tank, `IN_SERVICE → ISOLATED`, requires an isolation window supplied as
        `isolation_window_start_utc` and `isolation_window_end_utc`, and it competes for a scarce resource:
        **a farm may have at most one tank isolated over any given instant.**"
        PRD §3.4: "No order drawing on the tank may be `ASSIGNED` or `FUELING`, and the requested half-open
        window must not intersect the isolation window of any other tank at the same farm whose
        `service_status` is already `ISOLATED`; a conflict is `ERR_TANK_ISOLATION_CONFLICT`."
        PRD §2.10: "Then the two scheduling conflicts, pit first and asset second:
        `ERR_PIT_WINDOW_CONFLICT` then `ERR_ASSET_WINDOW_CONFLICT`, both only on order assignment."

        Design: Corner/validations/tank_isolation_conflict_is_not_an_asset_conflict
        """
        env = fx.setup_fuel_farm()
        farm_id = env["farm"]["id"]
        first = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                 safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                 opening_volume_liters=100_000.0)
        second = fx.register_tank(farm_id, capacity_liters=5_000_000.0,
                                  safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                  opening_volume_liters=100_000.0)

        fx.isolate_tank(first["id"], "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")

        validate_error(api.change_tank_service_status(
            second["id"], {"to_status": "ISOLATED",
                           "isolation_window_start_utc": "2026-08-10T09:00:00Z",
                           "isolation_window_end_utc": "2026-08-10T12:00:00Z"}, fx.OPERATOR),
            ApiErrorId.ERR_TANK_ISOLATION_CONFLICT, 409)
        assert fx.read_tank(second["id"])["service_status"] == "IN_SERVICE", \
            "no asset and no pit is anywhere near this collision"

        adjacent = fx.isolate_tank(second["id"], "2026-08-10T10:00:00Z",
                                   "2026-08-10T12:00:00Z")
        assert adjacent["service_status"] == "ISOLATED", \
            "the windows are half-open, so touching at 10:00 is not intersecting"


class TestEmptyAggregateAndOverrideCorners:
    def test_an_empty_sweep_is_a_422_while_an_empty_order_is_a_409(self, api):
        """PRD §3.9: "If the sweep finds nothing, the create is rejected with `ERR_NOTHING_TO_SWEEP`."
        PRD §3.6: "**Completion**, `FUELING → COMPLETED`, requires at least one `POSTED` ticket on the
        order (otherwise `ERR_NO_UPLIFT_RECORDED`) and requires the order's `posted_net_liters` to be at
        most the authorization's `max_authorized_liters` — with **no tolerance at all** at this gate, in
        contrast to the five percent allowed when posting."
        PRD §2.10: "Then tank isolation conflict (`ERR_TANK_ISOLATION_CONFLICT`) on tank service-status
        changes; then fuelling-window membership (`ERR_OUTSIDE_FUELING_WINDOW`) on fuelling start and uplift
        posting; then reconciliation period elapse (`ERR_PERIOD_NOT_ELAPSED`) followed by measurement-set
        completeness (`ERR_MEASUREMENT_SET_INCOMPLETE`), both on posting measurements; then the variance
        override requirement (`ERR_VARIANCE_OVERRIDE_REQUIRED`) on posting a run; then the at-least-one-ticket
        rule (`ERR_NO_UPLIFT_RECORDED`) on order completion; then the empty-sweep rule
        (`ERR_NOTHING_TO_SWEEP`) on invoice creation; then the dispute ceiling
        (`ERR_DISPUTE_LIMIT_REACHED`) on raising a dispute."

        Design: Corner/validations/nothing_to_sweep_versus_no_uplift_recorded
        """
        fx.set_clock()
        quiet = fx.open_account(base_price_cents_per_liter=62.00,
                               credit_limit_cents=BIG_CREDIT)
        validate_error(api.create_invoice(
            F.create_invoice_payload(quiet["id"], quiet["version"],
                                     period_start_utc="2026-08-01T00:00:00Z",
                                     period_end_utc="2026-09-01T00:00:00Z"), fx.BILLING),
            ApiErrorId.ERR_NOTHING_TO_SWEEP, 422)

        env = fx.setup_truck_order(target_state="FUELING", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        validate_error(api.complete_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_NO_UPLIFT_RECORDED, 409)
        assert fx.read_order(env["order"]["id"])["status"] == "FUELING", \
            "an empty aggregate is a payload failure on the billing side and a state failure on the ramp"

    def test_a_held_run_needs_words_and_not_merely_a_field(self, api):
        """PRD §3.9: "From `MEASURED` it needs nothing further; from `VARIANCE_HOLD` it needs a non-empty
        `variance_override_reason` in the payload, and posting a held run without one is rejected with
        `ERR_VARIANCE_OVERRIDE_REQUIRED`."
        PRD §3.9: "Posting a run is a `ConsortiumAdmin` action and requires that no storage tank at the
        farm has `quality_status` `QUARANTINED`."
        PRD §3.9: "The run auto-transitions `MEASURED → VARIANCE_HOLD` on the same request that computed
        the variance when the governing percentage is **strictly greater than** 0.50 percent; a run sitting
        at exactly 0.5000 percent does not hold and posts clean."

        Design: Corner/validations/variance_override_reason_must_be_non_empty
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        run = fx.open_reconciliation_run(env["farm"]["id"],
                                        period_start_utc="2026-08-10T00:00:00Z",
                                        period_end_utc="2026-08-10T07:00:00Z")
        fx.set_clock("2026-08-10T07:00:00Z")
        measured = fx.measure_reconciliation_run(
            run["id"], [{"storage_tank_id": env["tank"]["id"],
                         "measured_volume_liters": 990_000.0, "temperature_c": 15.0}])
        assert measured["status"] == "VARIANCE_HOLD"

        validate_error(api.post_reconciliation_run(run["id"], fx.ADMIN,
                                                   {"variance_override_reason": ""}),
                       ApiErrorId.ERR_VARIANCE_OVERRIDE_REQUIRED, 409)

        posted = validate_success(api.post_reconciliation_run(
            run["id"], fx.ADMIN, {"variance_override_reason": "meter drift under review"}))
        assert posted["status"] == "POSTED", "the same request with words in it goes through"
        assert fx.read_tank(env["tank"]["id"])["book_volume_liters"] == \
            pytest.approx(990000.00, abs=0.005)


class TestFiscalCeilingCorners:
    def test_a_full_tank_can_still_refuse_a_thousand_litres(self, api):
        """PRD §3.6: "The source tank must be `RELEASED` on quality and `IN_SERVICE` on service — anything
        else is `ERR_TANK_QUARANTINED` — and its `available_volume_liters` must be at least the order's
        `requested_uplift_liters`, or `ERR_INSUFFICIENT_TANK_VOLUME`."
        PRD §3.4: "The `available_volume_liters` is the book volume less the reserved volume less the
        farm's `unpumpable_bottom_liters`, rounded half up to two decimals and then floored at 0.0 so it can
        never go negative."
        PRD §3.6: "On success the order's reservation amount is computed, the requested volume is added to
        the tank's `reserved_volume_liters` and its `available_volume_liters` drops by the same amount, the
        account's accrual exposure is recomputed, and the order's, tank's and account's `version` each rise
        by one."

        Design: Corner/validations/insufficient_tank_volume_uses_available_not_book
        """
        env = fx.setup_truck_order(target_state="AUTHORIZED", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   opening_volume_liters=21_000.0,
                                   account_overrides={"base_price_cents_per_liter": 62.00,
                                                      "credit_limit_cents": BIG_CREDIT})
        tank = fx.read_tank(env["tank"]["id"])
        assert tank["book_volume_liters"] == pytest.approx(21000.00, abs=0.005)
        assert tank["reserved_volume_liters"] == pytest.approx(20000.00, abs=0.005)
        assert tank["available_volume_liters"] == pytest.approx(500.00, abs=0.005)

        account_id = env["account"]["id"]
        flight = fx.register_flight(account_id, stand_code="H03",
                                    scheduled_departure_utc="2026-08-10T10:00:00Z")
        auth = fx.issue_authorization(account_id, flight["id"],
                                      max_authorized_liters=1_000.0)
        small = fx.create_order(flight["id"], auth["id"], tank["id"],
                               auth["authorization_code"], delivery_mode="TRUCK",
                               requested_uplift_liters=1_000.0,
                               window_start_utc="2026-08-10T08:00:00Z",
                               window_end_utc="2026-08-10T09:00:00Z")

        validate_error(api.authorize_order(small["id"], fx.AGENT),
                       ApiErrorId.ERR_INSUFFICIENT_TANK_VOLUME, 409)
        assert fx.read_order(small["id"])["status"] == "REQUESTED", \
            "the heel and the standing reservation are both subtracted before the comparison"

    def test_exposure_may_touch_the_credit_limit_but_never_pass_it(self, api):
        """PRD §3.6: "The airline account's `status` must be `ACTIVE` and the accrual-basis exposure,
        including this order's freshly computed `reserved_amount_cents`, must not exceed the account's
        `credit_limit_cents`; failure either way is `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402), which is also
        how a `CREDIT_HOLD` account is refused."
        PRD §3.5: "The reservation term for a single order is computed once, at authorization time, and is
        the sum of two components: the requested volume multiplied by the account's
        `base_price_cents_per_liter` plus the applicable tier differential, rounded half up to whole cents;
        plus an into-plane handling component that is the larger of 2,500 cents and the requested volume
        multiplied by 0.45 cents per liter rounded half up to whole cents."
        PRD §3.5: "The result is `accrual_exposure_cents`."

        Design: Corner/validations/credit_limit_boundary_is_inclusive
        """
        exact = fx.setup_truck_order(target_state="REQUESTED", requested_uplift_liters=20_000.0,
                                     max_authorized_liters=20_000.0,
                                     account_overrides={"base_price_cents_per_liter": 62.00,
                                                        "credit_limit_cents": 1_313_000})
        authorized = fx.authorize_order(exact["order"]["id"])
        assert authorized["reserved_amount_cents"] == 1313000
        assert fx.read_account(exact["account"]["id"])["accrual_exposure_cents"] == 1313000, \
            "exposure that exactly equals the limit does not exceed it"

        tight = fx.setup_truck_order(target_state="REQUESTED", requested_uplift_liters=20_000.0,
                                     max_authorized_liters=20_000.0,
                                     account_overrides={"base_price_cents_per_liter": 62.00,
                                                        "credit_limit_cents": 1_312_999})
        validate_error(api.authorize_order(tight["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 402)
        assert fx.read_order(tight["order"]["id"])["reserved_amount_cents"] == 0, \
            "one cent of shortfall is the only 402 in the whole ladder"

    def test_the_five_percent_posting_tolerance_is_repaid_at_completion(self, api):
        """PRD §3.6: "Posting is gated on the fuelling window, on the source tank still being `RELEASED`,
        on the asset still being serviceable, on the farm not being `FROZEN` and having an active permit, on
        the tank's `book_volume_liters` less the farm's `unpumpable_bottom_liters` being at least the
        ticket's `net_liters` (`ERR_INSUFFICIENT_TANK_VOLUME`), on the farm's permit-day throughput
        including this volume staying within `max_daily_throughput_liters`
        (`ERR_PERMIT_THROUGHPUT_EXCEEDED`), and on the order's `posted_net_liters` after this ticket not
        exceeding **105 percent** of the authorization's `max_authorized_liters` — a deliberate five percent
        posting tolerance, breach of which is `ERR_UPLIFT_EXCEEDS_AUTHORIZATION`."
        PRD §3.6: "**Completion**, `FUELING → COMPLETED`, requires at least one `POSTED` ticket on the
        order (otherwise `ERR_NO_UPLIFT_RECORDED`) and requires the order's `posted_net_liters` to be at
        most the authorization's `max_authorized_liters` — with **no tolerance at all** at this gate, in
        contrast to the five percent allowed when posting."
        PRD §2.10: "then the authorization ceiling (`ERR_UPLIFT_EXCEEDS_AUTHORIZATION`) on uplift posting
        and order completion; and finally the payment bounds check (`ERR_PAYMENT_EXCEEDS_BALANCE`) on
        recording a payment."

        Design: Corner/validations/uplift_exceeds_authorization_only_bites_at_completion
        """
        env = fx.setup_truck_order(target_state="FUELING", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"base_price_cents_per_liter": 62.00,
                                                      "credit_limit_cents": BIG_CREDIT})
        order_id = env["order"]["id"]

        ticket = fx.post_uplift(order_id, meter_start_liters=0.0, meter_end_liters=20_400.0,
                                temperature_c=15.0)
        assert ticket["status"] == "POSTED"
        assert ticket["net_liters"] == pytest.approx(20400.00, abs=0.005), \
            "102 percent sits comfortably inside the posting tolerance"

        validate_error(api.complete_order(order_id, fx.AGENT),
                       ApiErrorId.ERR_UPLIFT_EXCEEDS_AUTHORIZATION, 409)
        held = fx.read_order(order_id)
        assert held["status"] == "FUELING"
        assert held["posted_net_liters"] == pytest.approx(20400.00, abs=0.005), \
            "the closing gate allows no tolerance whatsoever"

    def test_an_overpayment_is_a_payload_failure_and_leaves_the_invoice_alone(self, api):
        """PRD §3.9: "Payments are recorded against an issued invoice with an `amount_cents` that must be
        strictly positive and must not push the cumulative `amount_paid_cents` above the invoice's
        `total_cents`; a violation of either bound is `ERR_PAYMENT_EXCEEDS_BALANCE`."
        PRD §3.9: "Once the cumulative paid amount reaches the total the invoice moves `ISSUED → PAID`,
        both exposure figures fall by the invoice total, and the invoice's and account's `version` each rise
        by one."
        PRD §2.10: "then the authorization ceiling (`ERR_UPLIFT_EXCEEDS_AUTHORIZATION`) on uplift posting
        and order completion; and finally the payment bounds check (`ERR_PAYMENT_EXCEEDS_BALANCE`) on
        recording a payment."

        Design: Corner/validations/payment_exceeds_balance_is_422_not_409
        """
        env = fx.setup_issued_invoice(
            meter_end_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": BIG_CREDIT, "tax_exempt": False})
        invoice_id = env["invoice"]["id"]
        assert env["invoice"]["total_cents"] == 1439127

        validate_error(api.create_payment(invoice_id, {"amount_cents": 1439128}, fx.BILLING),
                       ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, 422)
        validate_error(api.create_payment(invoice_id, {"amount_cents": 0}, fx.BILLING),
                       ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, 422)

        untouched = fx.read_invoice(invoice_id)
        assert untouched["status"] == "ISSUED"
        assert untouched["amount_paid_cents"] == 0, \
            "not a cent of a refused payment is recorded"
