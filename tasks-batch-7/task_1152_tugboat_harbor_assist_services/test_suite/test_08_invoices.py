"""Invoice calculation: dual variants, per-line rounding, standby boundaries,
weather surcharge, OCC on finalize."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_invoice_lines_consistent,
    complete_job,
    confirm_assignment,
    confirm_booking,
    confirm_job_order,
    create_job_order,
    create_pilot,
    create_tariff_rate,
    create_tug,
    create_vessel,
    create_weather_restriction,
    dispatch_job,
    finalize_invoice,
    get_invoice_for_job,
    get_job,
    lift_weather_restriction,
    propose_assignment,
    propose_pilot_booking,
    record_passed_inspection,
    set_clock,
    setup_completed_job,
    setup_dispatched_job,
    start_job,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client


class TestProvisionalVsFinalStandbyDivergence:
    """Same job data priced twice: PROVISIONAL (SCHEDULED basis, standby 0) vs
    FINALIZED (ACTUAL basis, 45 min standby)."""

    def _setup_job_with_45_min_standby(self):
        ctx = setup_dispatched_job()
        set_clock("2026-06-01T08:45:00Z")  # 45 minutes past scheduled_start
        start_job(ctx["job"]["id"])
        complete_job(ctx["job"]["id"])
        ctx["invoice"] = get_invoice_for_job(ctx["job"]["id"])
        return ctx

    def test_provisional_invoice_uses_scheduled_basis(self, api):
        """PRD §3.8: "Under the `SCHEDULED` basis — used by the provisional invoice
        minted at completion — the scheduled times stand in for execution and
        `standby_minutes` is zero."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_standby_divergence
        """
        ctx = self._setup_job_with_45_min_standby()
        inv = ctx["invoice"]
        assert inv["status"] == "PROVISIONAL"
        assert inv["variant_basis"] == "SCHEDULED"
        assert inv["standby_minutes"] == 0
        # base 500000 + tug hire 2.0h * 120000 = 240000 + standby 0 = 740000
        assert inv["total_cents"] == 740000
        assert_invoice_lines_consistent(inv)

    def test_finalized_invoice_uses_actual_basis(self, api):
        """PRD §3.8: "Under the `ACTUAL` basis — used when the invoice is finalized
        — standby is the elapsed minutes from `scheduled_start` to `actual_start`,
        floored at zero so an early start bills nothing."
        PRD §3.8: "Finalization recomputes every charge line under the `ACTUAL`
        basis, flips `variant_basis` to `ACTUAL`, moves the invoice `PROVISIONAL` →
        `FINALIZED`, advances the owning job `COMPLETED` → `INVOICED`."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_standby_divergence
        """
        ctx = self._setup_job_with_45_min_standby()
        inv = ctx["invoice"]
        finalized = finalize_invoice(inv["id"], inv["version"])
        assert finalized["variant_basis"] == "ACTUAL"
        assert finalized["status"] == "FINALIZED"
        # standby 45 min -> billable 15 -> ceil(15/15) = 1 block -> 25000
        # total = 500000 + 240000 + 25000 = 765000
        assert finalized["standby_minutes"] == 45
        assert finalized["standby_cents"] == 25000
        assert finalized["total_cents"] == 765000
        assert_invoice_lines_consistent(finalized)
        job_after = get_job(ctx["job"]["id"])
        assert job_after["status"] == "INVOICED"


class TestPerLineRoundingThenSum:
    """Per-line rounding pinned: 2 lines of 100001 * 0.33 = 33000.33 -> 33000 each."""

    def _setup_two_tug_job(self):
        # Two tugs at 100001 cents/hour, 20-minute windows each (0.33h rounded).
        tug_r1 = create_tug(
            name="Tug R1",
            bollard_pull_tons=25.0,
            horsepower=2200,
            hourly_rate_cents=100001,
            insured_value_cents=8000000,
        )
        tug_r2 = create_tug(
            name="Tug R2",
            bollard_pull_tons=25.0,
            horsepower=2200,
            hourly_rate_cents=100001,
            insured_value_cents=8000000,
        )
        vessel = create_vessel(
            name="MV Sprite",
            imo_number="IMO2222222",
            deadweight_tonnage=10000,
            loa_meters=100.0,
        )
        pilot = create_pilot(name="Pilot Reyes", license_class="CLASS_I")
        tariff = create_tariff_rate(
            tariff_code="TAR-SHIFT-RR",
            maneuver_type="SHIFTING",
            base_fee_cents=0,
            standby_block_rate_cents=25000,
        )
        set_clock("2026-06-01T00:00:00Z")
        job = create_job_order(
            vessel["id"],
            tariff["id"],
            maneuver_type="SHIFTING",
            scheduled_start="2026-06-01T08:00:00Z",
            scheduled_end="2026-06-01T09:00:00Z",
        )
        job = confirm_job_order(job["id"])
        record_passed_inspection(tug_r1["id"])
        record_passed_inspection(tug_r2["id"])
        asg1 = propose_assignment(
            job["id"],
            tug_r1["id"],
            job["version"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T08:20:00Z",
        )
        job = get_job(job["id"])
        asg2 = propose_assignment(
            job["id"],
            tug_r2["id"],
            job["version"],
            window_start="2026-06-01T08:20:00Z",
            window_end="2026-06-01T08:40:00Z",
        )
        confirm_assignment(asg1["id"], tug_r1["id"])
        confirm_assignment(asg2["id"], tug_r2["id"])
        booking = propose_pilot_booking(
            job["id"],
            pilot["id"],
            window_start="2026-06-01T08:00:00Z",
            window_end="2026-06-01T09:00:00Z",
        )
        confirm_booking(booking["id"], pilot["id"])
        dispatch_job(job["id"])
        set_clock("2026-06-01T08:00:00Z")
        start_job(job["id"])
        complete_job(job["id"])
        return job

    def test_per_line_rounding_produces_66000(self, api):
        """PRD §2.7: "every money line is rounded half-up to whole cents before any
        summation takes place — summing unrounded lines and rounding once at the end
        is a rejected alternative, and this rounding order is pinned for invoices."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        job = self._setup_two_tug_job()
        inv = get_invoice_for_job(job["id"])
        # Each line: 0.33h * 100001 = 33000.33 -> round_half_up = 33000.
        # Two lines summed: 66000. Sum-then-round would give 66001.
        assert inv["tug_hire_cents"] == 66000

    def test_total_matches_per_line_sum(self, api):
        """PRD §3.8: "Tug hire sums one line per participating assignment — those
        with `participated` true: the assignment's window duration is converted from
        seconds to hours and rounded half-up to two decimal places, then multiplied
        by that tug's `hourly_rate_cents`, and the product is itself rounded half-up
        to whole cents before being added into `tug_hire_cents`."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        job = self._setup_two_tug_job()
        inv = get_invoice_for_job(job["id"])
        assert inv["tug_hire_cents"] == 66000
        # base 0 + tug hire 66000 + standby 0 + surcharge 0 = 66000
        assert inv["total_cents"] == 66000
        assert_invoice_lines_consistent(inv)


class TestStandbyBoundaries:
    """Standby billing boundary at exactly the free allowance, and ceil of blocks."""

    def _run_standby_case(self, start_clock_iso):
        ctx = setup_dispatched_job()
        set_clock(start_clock_iso)
        start_job(ctx["job"]["id"])
        complete_job(ctx["job"]["id"])
        inv = get_invoice_for_job(ctx["job"]["id"])
        return finalize_invoice(inv["id"], inv["version"])

    def test_standby_exactly_at_free_allowance_bills_nothing(self, api):
        """PRD §3.8: "Standby exactly equal to the free allowance therefore bills
        nothing; only standby strictly greater than the allowance bills."

        Design: Difficulty/boundary_precision_check/standby_free_allowance_thirty_minute_boundary
        """
        finalized = self._run_standby_case("2026-06-01T08:30:00Z")
        assert finalized["standby_minutes"] == 30
        assert finalized["standby_cents"] == 0
        assert finalized["total_cents"] == 740000

    def test_standby_one_minute_over_free_allowance_bills_one_block(self, api):
        """PRD §3.8: "Only standby beyond the tariff's `free_standby_minutes` is
        billable: subtract the free allowance, floor at zero, divide the remainder
        into `standby_block_minutes` blocks rounding up to a whole block, and
        charge `standby_block_rate_cents` per block."

        Design: Difficulty/boundary_precision_check/standby_free_allowance_thirty_minute_boundary
        """
        finalized = self._run_standby_case("2026-06-01T08:31:00Z")
        assert finalized["standby_minutes"] == 31
        # billable 1 -> ceil(1/15) = 1 block -> 25000
        assert finalized["standby_cents"] == 25000
        assert finalized["total_cents"] == 765000

    def test_partial_block_rounds_up_to_two_blocks(self, api):
        """PRD §3.8: "divide the remainder into `standby_block_minutes` blocks
        rounding up to a whole block."

        Design: Corner/calculations/standby_ceil_partial_block_bills_two_blocks
        """
        finalized = self._run_standby_case("2026-06-01T08:46:00Z")
        assert finalized["standby_minutes"] == 46
        # billable 16 -> ceil(16/15) = 2 blocks -> 50000
        assert finalized["standby_cents"] == 50000
        assert finalized["total_cents"] == 790000


class TestWeatherSurcharge:
    def test_weather_surcharge_applied_after_hold(self, api):
        """PRD §3.8: "if the job's `had_weather_hold` flag is set, a surcharge of
        the tariff's `weather_surcharge_pct` times the running subtotal — base fee
        plus tug hire plus standby — is added, rounded half-up to whole cents;
        without a weather hold the surcharge line is zero."

        Design: Corner/calculations/weather_surcharge_applied_after_hold
        """
        ctx = setup_dispatched_job(
            tariff_overrides={"tariff_code": "TAR-DOCK-WX", "weather_surcharge_pct": 0.15}
        )
        wr = create_weather_restriction(
            restriction_type="WIND",
            threshold_value=35.0,
            port_area="NORTH_HARBOR",
            effective_start="2026-06-01T09:00:00Z",
            effective_end="2026-06-01T11:00:00Z",
        )
        lift_weather_restriction(wr["id"])
        set_clock("2026-06-01T08:00:00Z")
        start_job(ctx["job"]["id"])
        complete_job(ctx["job"]["id"])
        inv = get_invoice_for_job(ctx["job"]["id"])
        finalized = finalize_invoice(inv["id"], inv["version"])
        # subtotal = 500000 + 240000 + 0 = 740000; surcharge = round(740000*0.15)=111000
        assert finalized["weather_surcharge_cents"] == 111000
        assert finalized["total_cents"] == 851000
        assert_invoice_lines_consistent(finalized)


class TestInvoiceFinalizeOcc:
    def test_finalize_with_stale_invoice_version_returns_412(self, api):
        """PRD §2.6: "finalizing an invoice requires `expected_invoice_version`
        equal to that invoice's current `version` ... the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/finalize_with_stale_invoice_version_returns_412
        """
        ctx = setup_completed_job()
        inv = ctx["invoice"]
        res = api.finalize_invoice(
            inv["id"],
            {"expected_invoice_version": inv["version"] - 1},
            TEST_USERS["port_dispatcher_headers"],
        )
        validate_error(res, "ERR_STALE_VERSION")


class TestCompleteCascadeToVessel:
    """Depth-2 cascade: complete auto-creates the invoice (hop 1), which recomputes
    the vessel's outstanding balance (hop 2)."""

    def test_complete_creates_provisional_invoice(self, api):
        """PRD §3.8: "Completion closes the execution phase: the job moves
        `IN_PROGRESS` → `COMPLETED`, `actual_end` is stamped from the logical clock,
        each `ACTIVE` assignment is released, boarded pilots are completed and
        no-shows recorded (§3.4), and — in the same step — the system mints the
        job's invoice and recomputes the vessel's outstanding balance."

        Design: Difficulty/transitive_cascade/complete_creates_invoice_then_recomputes_vessel_outstanding
        """
        ctx = setup_completed_job()
        inv = ctx["invoice"]
        assert inv["status"] == "PROVISIONAL"
        assert inv["variant_basis"] == "SCHEDULED"
        assert inv["total_cents"] == 740000

    def test_vessel_outstanding_reflects_new_invoice(self, api):
        """PRD §3.9: "That balance — the vessel's `outstanding_billed_cents` — is
        its ledger position with the port: the sum of `total_cents` over every
        invoice of the vessel's jobs in `PROVISIONAL` or `FINALIZED` status, minus
        the sum of `payout_cents` over the vessel's `SETTLED` claims, floored at
        zero."

        Design: Difficulty/transitive_cascade/complete_creates_invoice_then_recomputes_vessel_outstanding
        """
        ctx = setup_completed_job()
        vessel = validate_success(
            api.get_vessel(ctx["vessel"]["id"], TEST_USERS["port_dispatcher_headers"]),
            200,
        )
        assert vessel["outstanding_billed_cents"] == 740000
