"""Consistency model: cascades land inside their triggering request and refusals move nothing."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COORDINATOR_HEADERS,
    make_laboratory_user_headers,
)

STARTUP_CLOCK = "2026-08-01T00:00:00Z"
LATER_CLOCK = "2026-09-01T00:00:00Z"


def _report_a_failure(api):
    """A certified, furnished, released product whose fresh order has just failed."""
    env = fx.distributed_env(api, batch_specs=[{"quantity": 300}])
    order = fx.book_order(
        api,
        env["product"]["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
    )
    fx.start_order(api, order["id"], env["laboratory"]["id"])
    reported = validate_success(
        api.report_result(
            order["id"],
            {"measured_value": 250},
            headers=make_laboratory_user_headers(env["laboratory"]["id"]),
        ),
        200,
    )
    return env, order, reported


class TestEveryCascadeHopIsVisibleInTheTriggeringResponse:
    """The four-hop stop-distribution cascade completes inside the report-result request."""

    def test_the_report_response_already_carries_the_failing_verdict(self, api):
        """PRD 3.6: "On a fail, the order advances `IN_TESTING → REPORTED_FAIL` and the four-hop
        stop-distribution cascade fires." — the same request stores "`measured_value`, `result`,
        `reported_at` and `reported_by_user_id`".

        Design: Corner/consistency_model/corner_consistency_every_cascade_hop_is_visible_in_the_triggering_response
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, order, reported = _report_a_failure(api)

        assert reported["order_state"] == "REPORTED_FAIL"
        assert reported["result"] == "FAIL"
        assert reported["measured_value"] == 250
        assert reported["reported_at"] == STARTUP_CLOCK
        assert reported["reported_by_user_id"] == env["laboratory"]["id"]

    def test_the_product_certificate_and_batch_hops_need_no_second_call(self, api):
        """PRD 3.6: "Hop two: the product moves `CERTIFIED → SUSPENDED` ... Hop three: every
        children's product certificate of that product whose `issuance_status` is `ISSUED` moves
        to `WITHDRAWN`. Hop four: every production batch referencing a withdrawn certificate whose
        `distribution_state` is `RELEASED` moves `RELEASED → STOP_DISTRIBUTION`".

        Design: Corner/consistency_model/corner_consistency_every_cascade_hop_is_visible_in_the_triggering_response
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, _, _ = _report_a_failure(api)

        product = fx.get_product(api, env["product"]["id"])
        assert product["certification_state"] == "SUSPENDED"
        assert product["compliance_posture"] == "SUSPENDED"
        certificate = fx.get_certificate(api, env["certificate"]["id"])
        assert certificate["issuance_status"] == "WITHDRAWN"
        batch = fx.get_batch(api, env["batches"][0]["id"])
        assert batch["distribution_state"] == "STOP_DISTRIBUTION"

    def test_the_case_and_the_ledger_move_with_the_cascade_not_after_it(self, api):
        """PRD 3.6: "Hop one: when `is_retest` is false, a noncompliance case is opened in `OPEN`
        with its `product_id`, `triggering_test_order_id` and `failed_rule_id` copied from this
        order" and hop four moves the batch quantity "out of the product's `units_released` and
        into `units_stopped`".

        Design: Corner/consistency_model/corner_consistency_every_cascade_hop_is_visible_in_the_triggering_response
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, order, _ = _report_a_failure(api)

        cases = fx.list_cases_for_product(api, env["product"]["id"])
        assert len(cases) == 1
        assert cases[0]["case_state"] == "OPEN"
        assert cases[0]["triggering_test_order_id"] == order["id"]
        assert cases[0]["failed_rule_id"] == env["rules"][0]["id"]

        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["open_case_count"] == 1
        assert summary["units_stopped"] == 300
        assert summary["units_released"] == 0
        assert summary["units_total_produced"] == 300
        assert summary["ledger_balanced"] is True

    def test_advancing_the_clock_afterwards_leaves_nothing_pending(self, api):
        """PRD 2.4: "Moving the clock mutates no entity row — state machines observe the new
        instant only when a subsequent request arrives and re-evaluates its own preconditions
        against it."

        Design: Corner/consistency_model/corner_consistency_every_cascade_hop_is_visible_in_the_triggering_response
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env, _, _ = _report_a_failure(api)
        before = (
            fx.get_product(api, env["product"]["id"]),
            fx.get_certificate(api, env["certificate"]["id"]),
            fx.get_batch(api, env["batches"][0]["id"]),
            fx.get_summary(api, env["product"]["id"]),
        )

        fx.set_clock(api, LATER_CLOCK)
        after = (
            fx.get_product(api, env["product"]["id"]),
            fx.get_certificate(api, env["certificate"]["id"]),
            fx.get_batch(api, env["batches"][0]["id"]),
            fx.get_summary(api, env["product"]["id"]),
        )
        assert before == after
        fx.set_clock(api, STARTUP_CLOCK)


class TestNoWriteIsPartiallyVisible:
    """A refused booking moves none of the three rows an accepted booking would touch."""

    @staticmethod
    def _tight_budget_env(api):
        """A plan of 6 authorised units on a product that can afford exactly one order of 2."""
        return fx.booking_env(
            api,
            product={"projected_annual_units": 6000, "testing_budget_cents": 50000},
        )

    def test_an_accepted_booking_is_visible_in_every_row_it_touches(self, api):
        """PRD 3.6: "The order's `sample_count` is added to the plan's `units_committed` and
        subtracted from its `units_available` ... And the order's `invoice_total_cents` is added to
        the laboratory's `billed_fee_cents_total` at creation".

        Design: Corner/consistency_model/corner_consistency_reads_are_monotonic_and_no_write_is_partially_visible
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._tight_budget_env(api)
        assert env["plan"]["units_authorized"] == 6
        assert env["plan"]["units_available"] == 6

        order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=2,
        )
        assert order["invoice_total_cents"] == 37400

        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_committed"] == 2
        assert plan["units_available"] == 4
        laboratory = fx.get_laboratory(api, env["laboratory"]["id"])
        assert laboratory["billed_fee_cents_total"] == order["invoice_total_cents"]

    def test_a_refused_booking_leaves_the_plan_and_the_laboratory_untouched(self, api):
        """PRD 3.6: "Before either movement is applied, the fiscal ceiling is checked: the sum of
        `invoice_total_cents` over the product's orders in `SCHEDULED`, `IN_TESTING`,
        `REPORTED_PASS` or `REPORTED_FAIL`, plus the candidate's own `invoice_total_cents`, must
        not exceed the product's `testing_budget_cents`, or the booking is refused with
        `ERR_PRODUCT_TESTING_BUDGET_EXCEEDED`."

        Design: Corner/consistency_model/corner_consistency_reads_are_monotonic_and_no_write_is_partially_visible
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._tight_budget_env(api)
        fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=2,
        )
        plan_before = fx.get_plan(api, env["plan"]["id"])
        laboratory_before = fx.get_laboratory(api, env["laboratory"]["id"])

        validate_error(
            api.create_test_order(
                factories.test_order_payload(
                    env["product"]["id"],
                    env["plan"]["id"],
                    env["laboratory"]["id"],
                    env["rules"][0]["id"],
                    sample_count=2,
                ),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.PRODUCT_TESTING_BUDGET_EXCEEDED.value,
            402,
        )

        plan_after = fx.get_plan(api, env["plan"]["id"])
        laboratory_after = fx.get_laboratory(api, env["laboratory"]["id"])
        assert plan_after["units_committed"] == 2
        assert plan_after["units_available"] == 4
        assert laboratory_after["billed_fee_cents_total"] == 37400
        assert laboratory_after["credited_fee_cents_total"] == 0
        assert plan_after == plan_before
        assert laboratory_after == laboratory_before

    def test_the_refused_booking_leaves_no_order_row_behind(self, api):
        """PRD 3.6: "On creation the order's `order_state` is `SCHEDULED`" — a refused booking
        never reaches creation, so the product still shows the single accepted order.

        Design: Corner/consistency_model/corner_consistency_reads_are_monotonic_and_no_write_is_partially_visible
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._tight_budget_env(api)
        accepted = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=2,
        )

        validate_error(
            api.create_test_order(
                factories.test_order_payload(
                    env["product"]["id"],
                    env["plan"]["id"],
                    env["laboratory"]["id"],
                    env["rules"][0]["id"],
                    sample_count=2,
                ),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.PRODUCT_TESTING_BUDGET_EXCEEDED.value,
            402,
        )

        rows, meta = validate_paginated(
            api.list_test_orders({"product_id": env["product"]["id"]}, headers=ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [accepted["id"]]

    def test_two_reads_around_the_refusal_agree_on_version_and_timestamp(self, api):
        """PRD 2.8: "The invariant is that `units_committed` plus `units_available` equals
        `units_authorized` at all times, and it must hold identically before an order is booked
        and after that same order is cancelled".

        Design: Corner/consistency_model/corner_consistency_reads_are_monotonic_and_no_write_is_partially_visible
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._tight_budget_env(api)
        fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=2,
        )
        first_read = fx.get_plan(api, env["plan"]["id"])

        validate_error(
            api.create_test_order(
                factories.test_order_payload(
                    env["product"]["id"],
                    env["plan"]["id"],
                    env["laboratory"]["id"],
                    env["rules"][0]["id"],
                    sample_count=2,
                ),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.PRODUCT_TESTING_BUDGET_EXCEEDED.value,
            402,
        )
        second_read = fx.get_plan(api, env["plan"]["id"])

        assert second_read["version"] == first_read["version"]
        assert second_read["updated_at"] == first_read["updated_at"]
        assert (
            second_read["units_committed"] + second_read["units_available"]
            == second_read["units_authorized"]
        )
