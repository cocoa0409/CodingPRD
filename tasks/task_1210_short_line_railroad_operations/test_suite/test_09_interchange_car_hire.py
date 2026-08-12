"""Class I interchange booking guards and the car-hire statement's dual money
variants: live provisional estimate vs frozen final amount (PRD §2.7, §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_interchange_event_payload,
    create_railcar,
    receive_foreign_car,
    report_and_confirm_interchange,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


def _foreign_car_on_line_240h(api):
    """FOREIGN car received at the startup epoch; clock advanced 240 hours."""
    railcar = create_railcar(
        reporting_mark="GNWR 9001", car_type="HOPPER", ownership="FOREIGN", home_road_mark="CSX",
        hire_rate_per_hour_cents=120, hire_rate_per_mile_cents=85,
    )
    report_and_confirm_interchange(railcar["id"], "RECEIVED", class_i_partner="CSX")
    set_clock("2026-05-11T00:00:00Z")  # 10 days == 240 accrued hours
    return railcar


class TestCarHireDualVariant:
    def test_car_hire_provisional_amount_time_only(self, api, settlement_clerk_headers):
        """PRD §3.3: "While a statement is `OPEN` — or later `DISPUTED` — it
        carries a live estimate, `provisional_amount_cents`, recomputed on every
        read from the computed `accrued_hours`: the whole hours elapsed between
        `hire_accrual_start` and the earlier of the current clock and
        `hire_accrual_end` (with no end set, simply the current clock), any
        partial hour discarded, multiplied by the car's
        `hire_rate_per_hour_cents`. The estimate is time-based only:
        `accrued_miles` and the mileage rate play no part in it, and no minimum
        applies."
        PRD §3.3: "Confirming a `RECEIVED` event for a `FOREIGN` car opens
        car-hire accrual: a **CarHireStatement** is created in `OPEN` status for
        the car — or the existing `OPEN` statement for that car and the current
        accrual period is reused — with `hire_accrual_start` stamped from the
        clock and `period_month` set to that instant's year-month."

        Design: Difficulty/dual_variant_calc/car_hire_provisional_vs_final
        """
        railcar = _foreign_car_on_line_240h(api)
        statements, meta = validate_paginated(
            api.list_car_hire_statements(settlement_clerk_headers, params={"railcar_id": railcar["id"]})
        )
        assert meta["total_count"] == 1, f"one OPEN statement must exist for the received car, got {meta['total_count']}"
        stmt = statements[0]
        assert stmt["status"] == "OPEN"
        assert stmt["accrued_hours"] == 240, (
            f"2026-05-01T00:00:00Z -> 2026-05-11T00:00:00Z must accrue 240 whole hours, got {stmt['accrued_hours']}"
        )
        assert stmt["provisional_amount_cents"] == 28800, (
            f"240 hours * 120 cents with mileage excluded must estimate 28800, "
            f"got {stmt['provisional_amount_cents']}"
        )

    def test_car_hire_final_amount_after_delivery(self, api, settlement_clerk_headers, dispatcher_headers):
        """PRD §3.3: "At close — manually by a `SettlementClerk`, or through the
        delivered-confirmation cascade — the final figure is computed and frozen
        into `final_amount_cents`: the time component (the accrued hours times the
        hourly rate) plus the mileage component (`accrued_miles` times
        `hire_rate_per_mile_cents`), each component rounded to whole cents first,
        then summed, and finally raised to a 3,600-cent — $36.00 — minimum when
        the sum falls short."
        PRD §3.3: "Confirming a `DELIVERED` event moves the car to
        `INTERCHANGED_OUT` regardless of ownership and, for a `FOREIGN` car, stops
        the meter: `hire_accrual_end` is stamped from the clock, `accrued_miles`
        records the reported miles (it is zero until that moment), the final
        amount is computed, and the statement moves from `OPEN` to `CLOSED`."

        Design: Difficulty/dual_variant_calc/car_hire_provisional_vs_final
        """
        railcar = _foreign_car_on_line_240h(api)
        statements, _ = validate_paginated(
            api.list_car_hire_statements(settlement_clerk_headers, params={"railcar_id": railcar["id"]})
        )
        stmt_id = statements[0]["id"]
        provisional_before = statements[0]["provisional_amount_cents"]

        delivered = validate_success(
            api.create_interchange_event(
                create_interchange_event_payload(
                    railcar["id"], direction="DELIVERED", miles_traveled_on_line=120
                ),
                dispatcher_headers,
            ),
            expected_status=201,
        )
        validate_success(api.confirm_interchange_event(delivered["id"], settlement_clerk_headers))

        stmt = validate_success(api.get_car_hire_statement(stmt_id, settlement_clerk_headers))
        assert stmt["status"] == "CLOSED", f"the delivered confirm must close the statement, got {stmt['status']}"
        assert stmt["accrued_hours"] == 240
        assert stmt["accrued_miles"] == 120, f"accrued_miles must record the reported 120, got {stmt['accrued_miles']}"
        assert stmt["final_amount_cents"] == 39000, (
            f"240*120 + 120*85 = 28800 + 10200 must freeze at 39000 (above the 3600 floor), "
            f"got {stmt['final_amount_cents']}"
        )
        assert stmt["final_amount_cents"] != provisional_before, (
            "the final figure adds the mileage component the provisional estimate excludes"
        )
        car = validate_success(api.get_railcar(railcar["id"], dispatcher_headers))
        assert car["status"] == "INTERCHANGED_OUT", (
            f"the delivered confirm must move the car to INTERCHANGED_OUT, got {car['status']}"
        )


class TestStatementLifecycle:
    def test_statement_settled_terminal_lockdown(self, api, settlement_clerk_headers):
        """PRD §3.3: "A `CLOSED` statement may be settled, reaching the terminal
        `SETTLED`, or disputed to `DISPUTED`; a disputed statement can be reopened
        to `OPEN`, in which case the final amount is recomputed afresh at the next
        close."
        PRD §2.9: "Fourth, state legality: the target resource must be in a state
        from which the requested transition is defined, failing as
        `ERR_INVALID_STATE` (HTTP 409) — or the more specific state errors
        `ERR_ORDER_NOT_AMENDABLE` and `ERR_MEMBER_NOT_AVAILABLE` where §3 names
        them."

        Design: Corner/state_machines/statement_settled_terminal_lockdown
        """
        ctx = receive_foreign_car(
            mark="GNWR 9100", hire_rate_per_hour_cents=100, hire_rate_per_mile_cents=50, partner="NS"
        )
        railcar = ctx["railcar"]
        report_and_confirm_interchange(railcar["id"], "DELIVERED", class_i_partner="NS",
                                       miles_traveled_on_line=40)
        stmt_id = ctx["statement"]["id"]
        settled = validate_success(api.settle_car_hire_statement(stmt_id, settlement_clerk_headers))
        assert settled["status"] == "SETTLED"

        resp = api.dispute_car_hire_statement(stmt_id, settlement_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestInterchangeGuards:
    def test_interchange_duplicate_received_rejected(self, api, dispatcher_headers):
        """PRD §3.3: "A `RECEIVED` report is refused with
        `ERR_INTERCHANGE_DUPLICATE` when the same car already has an open received
        event: one in `REPORTED` or `CONFIRMED` status with no matching delivered
        confirmation."

        Design: Corner/errors/interchange_duplicate_received_rejected
        """
        railcar = create_railcar(
            reporting_mark="CSXT 100", car_type="HOPPER", ownership="FOREIGN", home_road_mark="CSX",
            hire_rate_per_hour_cents=110, hire_rate_per_mile_cents=70,
        )
        report_and_confirm_interchange(railcar["id"], "RECEIVED", class_i_partner="CSX")
        resp = api.create_interchange_event(
            create_interchange_event_payload(railcar["id"], direction="RECEIVED", class_i_partner="CSX"),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INTERCHANGE_DUPLICATE)

    def test_interchange_delivered_for_bad_order_car_rejected(self, api, dispatcher_headers):
        """PRD §3.3: "A `DELIVERED` report requires the car to be on the line in
        `AVAILABLE`, `LOADED`, or `IN_TRANSIT` status, and for a `FOREIGN` car the
        `miles_traveled_on_line` figure is mandatory; either violation surfaces
        `ERR_INTERCHANGE_DIRECTION_INVALID`."

        Design: Corner/errors/interchange_delivered_for_bad_order_car_rejected
        """
        railcar = create_railcar(
            reporting_mark="CSXT 200", car_type="TANK", ownership="FOREIGN", home_road_mark="CSX",
            hire_rate_per_hour_cents=110, hire_rate_per_mile_cents=70,
        )
        validate_success(api.bad_order_railcar(railcar["id"], dispatcher_headers))
        resp = api.create_interchange_event(
            create_interchange_event_payload(
                railcar["id"], direction="DELIVERED", miles_traveled_on_line=10
            ),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INTERCHANGE_DIRECTION_INVALID)
