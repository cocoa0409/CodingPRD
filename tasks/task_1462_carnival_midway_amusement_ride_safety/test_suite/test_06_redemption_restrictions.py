"""Redemption gating: validation-family ordering (state masks safety, safety
masks fiscal), inclusive rider-height bounds, and cross-fair referential
integrity (PRD sections 2.8, 2.10, 3.6, 3.7).

Covers design instances:
  Difficulty/priority_pair_validation_conflict/redemption_state_error_beats_safety_error
  Difficulty/priority_pair_validation_conflict/redemption_safety_error_beats_fiscal_error
  Corner/validations/rider_height_bounds_are_inclusive
  Corner/errors/cross_fair_redemption_rejected
"""
from test_helpers import (
    ApiErrorId,
    make_inspector_headers,
    make_manager_headers,
    make_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


class TestStateErrorBeatsSafetyError:
    def _setup_ride2_closed_after_incident(self, api, name):
        ctx = fx.setup_two_ride_permitted_fair(name)
        fx.begin_day(ctx)
        fx.clear_ride(ctx, ctx["ride1"]["id"])
        fx.clear_ride(ctx, ctx["ride2"]["id"])
        fx.open_gates(ctx)
        return ctx

    def test_closed_ride_with_height_violation_returns_state_error(self, api):
        """PRD section 2.10: "Every request is evaluated against a fixed
        pipeline of check families, and the first failure stops the pipeline —
        later families are never consulted. A malformed body therefore surfaces
        `ERR_INVALID_REQUEST` even when the target resource is also in the
        wrong state, and a state error masks a safety violation that would
        otherwise also apply." Family 7 is "State preconditions"; family 8 is
        "Safety and compliance".

        PRD section 3.6: "the ride's `daily_status` must be `OPEN`
        (`ERR_RIDE_NOT_OPEN`)".

        The ride is CLOSED (a SERIOUS incident was filed and then cleared) and
        the guest is also too short for it — the state error wins.

        Design: Difficulty/priority_pair_validation_conflict/redemption_state_error_beats_safety_error
        """
        ctx = self._setup_ride2_closed_after_incident(api, "J")
        sup, op, clerk = ctx["sup"], ctx["op"], ctx["clerk"]
        ride2_id, day_id = ctx["ride2"]["id"], ctx["day"]["id"]
        inc = fx.file_incident(op, "operator", ride2_id, day_id, severity="SERIOUS",
                               injury_count=1, description="guest struck knee")
        validate_success(api.clear_incident(
            inc["id"], {}, make_inspector_headers(ctx["inspectors"][0]["id"])))
        ride2 = fx.get_ride(sup, ride2_id)
        assert ride2["daily_status"] == "CLOSED", (
            "clearing the only open incident must drop INCIDENT_HOLD to CLOSED")
        assert ride2["license_status"] == "SUSPENDED"
        prod = fx.create_product(sup)
        sale = fx.sell(clerk, prod["id"], day_id, quantity=1, holder_height_in=30)
        resp = api.create_redemption(
            {"wristband_id": sale["id"], "ride_id": ride2_id},
            make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_RIDE_NOT_OPEN, 409)

    def test_height_error_in_isolation_when_ride_open(self, api):
        """PRD section 3.6: "the guest's `holder_height_in`, recorded at sale
        time, must fall inside the ride's inclusive window from
        `min_rider_height_in` to `max_rider_height_in`, else
        `ERR_HEIGHT_RESTRICTION`".

        With the ride OPEN, the safety gate that was masked in the sibling
        test fires on its own.

        Design: Difficulty/priority_pair_validation_conflict/redemption_state_error_beats_safety_error
        """
        ctx = fx.setup_two_ride_permitted_fair("Jb")
        fx.begin_day(ctx)
        fx.clear_ride(ctx, ctx["ride1"]["id"])
        fx.clear_ride(ctx, ctx["ride2"]["id"])
        fx.open_gates(ctx)
        sup, op, clerk = ctx["sup"], ctx["op"], ctx["clerk"]
        prod = fx.create_product(sup)
        sale = fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=1,
                       holder_height_in=30)
        resp = api.create_redemption(
            {"wristband_id": sale["id"], "ride_id": ctx["ride2"]["id"]},
            make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_HEIGHT_RESTRICTION, 422)


class TestSafetyErrorBeatsFiscalError:
    def test_height_violation_with_empty_wristband_returns_safety_error(self, api):
        """PRD section 2.10: "12. **Fiscal gates, last among the business rules
        (redemption creation, ticket-sale creation).** A credit-bearing
        wristband must hold at least one credit, and the day must have
        attendance headroom — else `ERR_INSUFFICIENT_CREDITS` or
        `ERR_DAY_AT_CAPACITY` (both 422)." Safety and compliance is family 8
        and runs before it.

        The guest is too short for the THRILL ride [48, 80] AND the wristband
        was drained on the FAMILY ride — the safety error wins.

        Design: Difficulty/priority_pair_validation_conflict/redemption_safety_error_beats_fiscal_error
        """
        ctx = fx.setup_two_ride_permitted_fair("K", ride2_overrides={
            "min_rider_height_in": 36, "max_rider_height_in": 60})
        fx.begin_day(ctx)
        fx.clear_ride(ctx, ctx["ride1"]["id"])
        fx.clear_ride(ctx, ctx["ride2"]["id"])
        fx.open_gates(ctx)
        sup, op, clerk = ctx["sup"], ctx["op"], ctx["clerk"]
        day_id = ctx["day"]["id"]
        prod = fx.create_product(sup)
        sale = fx.sell(clerk, prod["id"], day_id, quantity=1, holder_height_in=40)
        fx.queue_redemption(op, sale["id"], ctx["ride2"]["id"])
        cyc = fx.open_cycle(op, ctx["ride2"]["id"], day_id)
        fx.cycle_action(op, cyc["id"], "load")
        sale_after = fx.get_sale(sup, sale["id"])
        assert sale_after["credits_remaining"] == 0
        assert sale_after["credits_redeemed"] == 1
        resp = api.create_redemption(
            {"wristband_id": sale["id"], "ride_id": ctx["ride1"]["id"]},
            make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_HEIGHT_RESTRICTION, 422)

    def test_credit_error_in_isolation_when_height_legal(self, api):
        """PRD section 3.6: "a credit-bearing wristband must hold at least one
        remaining credit, else `ERR_INSUFFICIENT_CREDITS`".

        With the height legal, the fiscal gate fires on its own.

        Design: Difficulty/priority_pair_validation_conflict/redemption_safety_error_beats_fiscal_error
        """
        ctx = fx.setup_open_day("Kb")
        sup, op, clerk = ctx["sup"], ctx["op"], ctx["clerk"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        prod = fx.create_product(sup)
        sale = fx.sell(clerk, prod["id"], day_id, quantity=1, holder_height_in=60)
        fx.queue_redemption(op, sale["id"], ride_id)
        cyc = fx.open_cycle(op, ride_id, day_id)
        fx.cycle_action(op, cyc["id"], "load")
        resp = api.create_redemption(
            {"wristband_id": sale["id"], "ride_id": ride_id},
            make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDITS, 422)


class TestRiderHeightBounds:
    def test_height_bounds_are_inclusive(self, api):
        """PRD section 3.6: "the guest's `holder_height_in`, recorded at sale
        time, must fall inside the ride's inclusive window from
        `min_rider_height_in` to `max_rider_height_in`, else
        `ERR_HEIGHT_RESTRICTION`".

        Ride window [48, 80]: 48 and 80 queue successfully; 47 and 81 are
        rejected — the comparison is inclusive at both ends.

        Design: Corner/validations/rider_height_bounds_are_inclusive
        """
        ctx = fx.setup_open_day("V7")
        sup, op, clerk = ctx["sup"], ctx["op"], ctx["clerk"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        prod = fx.create_product(sup)
        sales = {h: fx.sell(clerk, prod["id"], day_id, quantity=1,
                            holder_height_in=h) for h in (47, 48, 80, 81)}
        for h in (48, 80):
            red = fx.queue_redemption(op, sales[h]["id"], ride_id)
            assert red["status"] == "QUEUED", (
                f"height {h} is exactly at a bound and must queue")
        for h in (47, 81):
            resp = api.create_redemption(
                {"wristband_id": sales[h]["id"], "ride_id": ride_id},
                make_operator_headers(op["id"]))
            validate_error(resp, ApiErrorId.ERR_HEIGHT_RESTRICTION, 422)


class TestCrossFairRedemption:
    def test_wristband_from_other_fair_rejected(self, api):
        """PRD section 2.8: "any operation that pairs two resources — a
        checklist or cycle pairing a ride with an operating day, a redemption
        pairing a wristband with a ride, an appointment pairing a ride with a
        fair — requires both sides to belong to the same fair. A disagreement
        is rejected with `ERR_CROSS_FAIR_REFERENCE` (HTTP 422)."

        Both fairs are fully OPEN on the same date; fair A's wristband still
        cannot board fair B's ride.

        Design: Corner/errors/cross_fair_redemption_rejected
        """
        ctx = fx.setup_two_open_fairs("X")
        a, b = ctx["a"], ctx["b"]
        prod_a = fx.create_product(a["sup"])
        sale_a = fx.sell(a["clerk"], prod_a["id"], a["day"]["id"], quantity=3)
        resp = api.create_redemption(
            {"wristband_id": sale_a["id"], "ride_id": b["ride"]["id"]},
            make_operator_headers(b["op"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CROSS_FAIR_REFERENCE, 422)
        sale_after = fx.get_sale(a["sup"], sale_a["id"])
        assert sale_after["credits_remaining"] == 3, (
            "a rejected cross-fair redemption must not touch credits")
        data, meta = validate_paginated(api.list_redemptions(
            make_manager_headers(a["sup"]["id"]),
            params={"wristband_id": sale_a["id"]}))
        assert meta["total_count"] == 0 and data == []
