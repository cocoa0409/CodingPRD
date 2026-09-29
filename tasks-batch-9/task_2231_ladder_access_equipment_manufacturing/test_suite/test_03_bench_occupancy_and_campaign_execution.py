"""Bench occupancy arithmetic, the bench-minute ledger and load-test verdicts."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_bench_reservation_payload,
    create_campaign,
    create_draft_revision,
    create_load_test_payload,
    create_product,
    create_test_bench,
    get_bench_data,
    get_campaign_data,
    get_reservation_data,
    start_campaign,
    start_campaign_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

TECHNICIAN = TEST_USERS["test_lab_technician_headers"]

# One calendar day is enough room for every window in this module.
DAY = "2026-08-03"
NEXT_DAY = "2026-08-04"


def _lab_with_two_campaigns(cooldown_minutes=60):
    """A bench with a cooldown buffer plus two campaigns that both want it."""
    product = create_product()
    revision = create_draft_revision(product["id"])
    bench = create_test_bench(cooldown_minutes=cooldown_minutes)
    first = create_campaign(product["id"], revision["id"], "DESIGN_QUALIFICATION")
    second = create_campaign(product["id"], revision["id"], "INCIDENT_INVESTIGATION")
    return product, revision, bench, first, second


def _reserve(bench_id, campaign_id, start_at, end_at):
    return api_client.create_bench_reservation(
        create_bench_reservation_payload(bench_id, campaign_id, start_at, end_at),
        TECHNICIAN,
    )


class TestBenchOccupancyWithCooldown:
    def test_reservation_starting_inside_the_cooldown_buffer_is_rejected(self):
        """PRD §3.4: "A new reservation is rejected with
        `ERR_BENCH_WINDOW_CONFLICT` when the same bench already carries a
        reservation in `HELD` or `CONSUMED` such that the new `start_at` is
        strictly earlier than that existing reservation's `end_at` advanced by
        the bench's `cooldown_minutes`, **and** the new `end_at` is strictly
        later than that existing reservation's `start_at`."

        Design: Difficulty/resource_temporal_overlap/bench_reservation_half_open_window_with_cooldown_buffer
        """
        _, _, bench, first, second = _lab_with_two_campaigns()
        validate_success(
            _reserve(bench["id"], first["id"], f"{DAY}T08:00:00Z", f"{DAY}T12:00:00Z"),
            201,
        )

        # 12:30 sits inside the 60-minute recovery buffer that runs to 13:00.
        response = _reserve(
            bench["id"], second["id"], f"{DAY}T12:30:00Z", f"{DAY}T14:30:00Z"
        )
        validate_error(response, ApiErrorId.ERR_BENCH_WINDOW_CONFLICT.value, 409)

        assert get_bench_data(bench["id"])["reserved_minutes_total"] == 240, (
            "a rejected reservation adds nothing to the bench ledger"
        )

    def test_reservation_starting_exactly_when_the_cooldown_expires_is_accepted(self):
        """PRD §3.4: "Because the comparison against the extended end is strict,
        a new reservation starting exactly at the moment the cooldown expires is
        accepted"
        PRD §2.9: "Creating a reservation adds its `duration_minutes` to the
        bench total."

        Design: Difficulty/resource_temporal_overlap/bench_reservation_half_open_window_with_cooldown_buffer
        """
        _, _, bench, first, second = _lab_with_two_campaigns()
        held = validate_success(
            _reserve(bench["id"], first["id"], f"{DAY}T08:00:00Z", f"{DAY}T12:00:00Z"),
            201,
        )

        accepted = validate_success(
            _reserve(bench["id"], second["id"], f"{DAY}T13:00:00Z", f"{DAY}T14:00:00Z"),
            201,
        )

        assert accepted["status"] == "HELD"
        assert accepted["duration_minutes"] == 60
        assert held["duration_minutes"] == 240
        assert get_bench_data(bench["id"])["reserved_minutes_total"] == 300

        rows, meta = validate_paginated(
            api_client.list_bench_reservations(
                TECHNICIAN, {"test_bench_id": bench["id"]}
            )
        )
        assert meta["total_count"] == 2, "both reservations are live on the bench"
        assert len(rows) == 2

    def test_reservation_ending_exactly_when_an_existing_one_begins_is_accepted(self):
        """PRD §3.4: "because the comparison against the existing start is also
        strict, a new reservation ending exactly when an existing one begins is
        accepted."

        Design: Difficulty/resource_temporal_overlap/bench_reservation_half_open_window_with_cooldown_buffer
        """
        _, _, bench, first, second = _lab_with_two_campaigns()
        validate_success(
            _reserve(bench["id"], first["id"], f"{DAY}T08:00:00Z", f"{DAY}T12:00:00Z"),
            201,
        )

        accepted = validate_success(
            _reserve(bench["id"], second["id"], f"{DAY}T06:00:00Z", f"{DAY}T08:00:00Z"),
            201,
        )

        assert accepted["status"] == "HELD"
        assert accepted["duration_minutes"] == 120
        assert get_bench_data(bench["id"])["reserved_minutes_total"] == 360


class TestBenchMinuteLedgerConservation:
    def _two_held_reservations(self):
        _, _, bench, first, second = _lab_with_two_campaigns()
        res1 = validate_success(
            _reserve(bench["id"], first["id"], f"{DAY}T08:00:00Z", f"{DAY}T12:00:00Z"),
            201,
        )
        res2 = validate_success(
            _reserve(
                bench["id"],
                second["id"],
                f"{NEXT_DAY}T08:00:00Z",
                f"{NEXT_DAY}T10:00:00Z",
            ),
            201,
        )
        assert get_bench_data(bench["id"])["reserved_minutes_total"] == 360
        return bench, first, second, res1, res2

    def test_consuming_a_held_reservation_leaves_the_bench_ledger_untouched(self):
        """PRD §2.9: "Consuming a reservation leaves the total untouched, because
        a `CONSUMED` reservation remains inside the conserved sum."
        PRD §3.4: "On success the named reservation moves `HELD` → `CONSUMED`,
        and the bench's `reserved_minutes_total` does not change."

        Design: Difficulty/compensating_invariant/bench_minutes_conserved_across_consume_and_cancel
        """
        bench, first, _, res1, _ = self._two_held_reservations()

        campaign = start_campaign(first["id"], res1["id"])

        assert campaign["status"] == "IN_PROGRESS"
        assert_instant_equals(campaign["started_at"], "2026-08-01T00:00:00Z", "started_at")
        assert get_reservation_data(res1["id"])["status"] == "CONSUMED"
        assert get_bench_data(bench["id"])["reserved_minutes_total"] == 360, (
            "HELD -> CONSUMED conserves the ledger exactly"
        )

    def test_cancelling_a_held_reservation_restores_the_pre_reservation_total(self):
        """PRD §2.9: "Cancelling a `HELD` reservation subtracts that same
        `duration_minutes`, restoring the pre-reservation value exactly."
        PRD §2.9: "A test bench's `reserved_minutes_total` always equals the sum
        of `duration_minutes` over the bench's reservations whose `status` is
        `HELD` or `CONSUMED`."

        Design: Difficulty/compensating_invariant/bench_minutes_conserved_across_consume_and_cancel
        """
        bench, first, _, res1, res2 = self._two_held_reservations()
        start_campaign(first["id"], res1["id"])

        cancelled = validate_success(
            api_client.cancel_bench_reservation(res2["id"], TECHNICIAN)
        )

        assert cancelled["status"] == "CANCELLED"
        reread = get_bench_data(bench["id"])
        assert reread["reserved_minutes_total"] == 240
        assert reread["reserved_minutes_total"] == res1["duration_minutes"], (
            "only the surviving CONSUMED reservation remains inside the sum"
        )

    def test_cancelling_a_consumed_reservation_is_rejected(self):
        """PRD §3.4: "cancellation requested on a reservation that is already
        `CONSUMED` or `CANCELLED` is rejected with `ERR_RESERVATION_NOT_HELD`."

        Design: Difficulty/compensating_invariant/bench_minutes_conserved_across_consume_and_cancel
        """
        bench, first, _, res1, _ = self._two_held_reservations()
        start_campaign(first["id"], res1["id"])

        response = api_client.cancel_bench_reservation(res1["id"], TECHNICIAN)
        validate_error(response, ApiErrorId.ERR_RESERVATION_NOT_HELD.value, 409)

        assert get_bench_data(bench["id"])["reserved_minutes_total"] == 360, (
            "the rejected cancellation subtracts nothing"
        )


class TestLoadVerdictBoundaries:
    def _campaign_in_progress(self):
        """A fiberglass TYPE_IA 24-foot model — required load 1350.00 lbf and a
        deflection ceiling of 1.600 in — with an IN_PROGRESS campaign."""
        product = create_product(
            product_type="EXTENSION_LADDER",
            material="FIBERGLASS_PULTRUSION",
            duty_rating="TYPE_IA",
            working_length_ft=24.0,
        )
        assert float(product["required_test_load_lb"]) == 1350.00
        assert float(product["max_allowed_deflection_in"]) == 1.600
        revision = create_draft_revision(product["id"])
        bench = create_test_bench()
        campaign = create_campaign(product["id"], revision["id"], "DESIGN_QUALIFICATION")
        reservation = validate_success(
            _reserve(
                bench["id"], campaign["id"], f"{DAY}T08:00:00Z", f"{DAY}T12:00:00Z"
            ),
            201,
        )
        validate_success(
            api_client.start_test_campaign(
                campaign["id"], start_campaign_payload(reservation["id"]), TECHNICIAN
            )
        )
        return product, campaign

    def _record(self, campaign_id, **kwargs):
        return validate_success(
            api_client.create_load_test(
                campaign_id, create_load_test_payload(**kwargs), TECHNICIAN
            ),
            201,
        )

    def test_load_test_at_the_exact_load_deflection_and_set_ceilings_passes(self):
        """PRD §3.4: "Every comparison is inclusive on the passing side, so a
        test that exactly meets the required load, exactly reaches the deflection
        ceiling, and exactly reaches the permanent-set ceiling passes."
        PRD §3.4: "Otherwise the `outcome` is `PASS` and `failure_reason_code` is
        null."

        Design: Difficulty/boundary_precision_check/load_test_passes_exactly_at_required_load_and_deflection
        """
        _, campaign = self._campaign_in_progress()

        at_limit = self._record(
            campaign["id"],
            test_code="STATIC_VERTICAL",
            applied_load_lb=1350.00,
            measured_deflection_in=1.600,
            permanent_set_in=0.020,
        )

        assert at_limit["outcome"] == "PASS"
        assert at_limit["failure_reason_code"] is None

    def test_load_one_hundredth_below_the_requirement_fails_on_load_first(self):
        """PRD §3.4: "If `applied_load_lb` is less than the model's
        `required_test_load_lb`, the `outcome` is `FAIL` with
        `failure_reason_code` `LOAD_BELOW_REQUIRED`."
        PRD §2.6: "Comparisons never round. A load test's `applied_load_lb`,
        `measured_deflection_in`, and `permanent_set_in` are compared against
        their thresholds at the full declared precision of the stored values,
        with no intermediate rounding."

        Design: Difficulty/boundary_precision_check/load_test_passes_exactly_at_required_load_and_deflection
        """
        _, campaign = self._campaign_in_progress()

        under = self._record(
            campaign["id"],
            test_code="RAIL_BENDING",
            applied_load_lb=1349.99,
            measured_deflection_in=1.600,
            permanent_set_in=0.020,
        )

        assert under["outcome"] == "FAIL"
        assert under["failure_reason_code"] == "LOAD_BELOW_REQUIRED"

    def test_deflection_one_thousandth_over_the_ceiling_fails_on_deflection(self):
        """PRD §3.4: "Otherwise, if `measured_deflection_in` is greater than the
        model's `max_allowed_deflection_in`, the `outcome` is `FAIL` with
        `failure_reason_code` `DEFLECTION_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/load_test_passes_exactly_at_required_load_and_deflection
        """
        _, campaign = self._campaign_in_progress()

        over = self._record(
            campaign["id"],
            test_code="SLIP_RESISTANCE",
            applied_load_lb=1350.00,
            measured_deflection_in=1.601,
            permanent_set_in=0.020,
        )

        assert over["outcome"] == "FAIL"
        assert over["failure_reason_code"] == "DEFLECTION_EXCEEDED"

    def test_campaign_counters_recount_after_each_recorded_load_test(self):
        """PRD §3.4: "After each insert, the campaign's `load_test_count` is
        recounted as the number of load test rows on the campaign regardless of
        outcome, and `failed_test_count` as the number whose `outcome` is
        `FAIL`."

        Design: Difficulty/boundary_precision_check/load_test_passes_exactly_at_required_load_and_deflection
        """
        _, campaign = self._campaign_in_progress()
        self._record(
            campaign["id"],
            test_code="STATIC_VERTICAL",
            applied_load_lb=1350.00,
            measured_deflection_in=1.600,
            permanent_set_in=0.020,
        )
        self._record(
            campaign["id"],
            test_code="RAIL_BENDING",
            applied_load_lb=1349.99,
            measured_deflection_in=1.600,
            permanent_set_in=0.020,
        )
        self._record(
            campaign["id"],
            test_code="SLIP_RESISTANCE",
            applied_load_lb=1350.00,
            measured_deflection_in=1.601,
            permanent_set_in=0.020,
        )

        reread = get_campaign_data(campaign["id"])
        assert reread["load_test_count"] == 3
        assert reread["failed_test_count"] == 2
        assert reread["status"] == "IN_PROGRESS", (
            "recording tests never concludes the campaign by itself"
        )
