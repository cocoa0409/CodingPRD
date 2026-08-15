"""Demurrage/detention metering: provisional vs final variants, free-time
boundaries, tier walk, and the auto-created D&D invoice."""
from test_helpers import (
    find_booking_invoice,
    setup_discharged_fcl_scenario,
    validate_success,
)
from test_helpers.fixtures import BC, OPS


class TestProvisionalVsFinalDivergence:
    """Contract free time: 4 demurrage / 3 detention days; tiers
    (1-3 @15000, 4-7 @30000, 8+ @60000); detention 12000/day.
    Assignment DISCHARGED at 2026-09-21T12:00:00Z."""

    def test_provisional_read_closes_open_interval_at_logical_clock(self, api):
        """PRD §3.8: "`provisional_demurrage_cents` treats the still-open
        demurrage interval as closing at the current logical clock (that is,
        `gated_out_at` is treated as now while the assignment is
        `DISCHARGED`), and `provisional_detention_cents` does the same for the
        detention interval while the assignment is `GATED_OUT`. These
        provisional figures diverge from the eventual frozen values whenever
        the real event happens later."
        PRD §3.8: "the day count between two timestamps is the floor of their
        difference divided by 24 hours, with no fractional days."

        Design: Difficulty/dual_variant_calc/demurrage_provisional_vs_final_divergence
        """
        ctx = setup_discharged_fcl_scenario()
        assignment_id = ctx["assignment"]["id"]

        validate_success(api.set_clock("2026-09-27T12:00:00Z", OPS), 200)
        read = validate_success(
            api.get_container_assignment(assignment_id, BC), 200)
        assert read["status"] == "DISCHARGED"
        # 6 full days since discharge - 4 free = 2 chargeable days @15000.
        assert read["provisional_demurrage_cents"] == 30000
        assert read["provisional_detention_cents"] == 0, (
            "the detention interval has not started while DISCHARGED"
        )

        # The final variant uses the real gate-out event, not the read clock.
        validate_success(api.set_clock("2026-09-30T12:00:00Z", OPS), 200)
        gated_out = validate_success(
            api.gate_out_assignment(assignment_id, BC), 200)
        assert gated_out["demurrage_days"] == 5
        assert gated_out["demurrage_charge_cents"] == 105000, (
            "3 days @15000 + 2 days @30000; provisional 30000 diverges"
        )

    def test_final_values_freeze_and_dd_invoice_auto_created(self, api):
        """PRD §3.8: "The demurrage charge walks the contract's
        `demurrage_tiers` in ascending `from_day` order: each tier covers a
        span equal to the tier's `to_day` minus `from_day` plus one (or, for
        the unbounded final tier where `to_day` is null, all remaining days),
        capped by the remaining chargeable days; the tier's `per_diem_cents`
        is multiplied by the days it covers, the running charge accumulates,
        and the walk stops when no chargeable days remain. The detention
        charge is the flat `detention_per_diem_cents` multiplied by the
        chargeable detention days."
        PRD §3.8: "If the sum of `demurrage_charge_cents` and
        `detention_charge_cents` is greater than zero, empty-return
        auto-creates a `DEMURRAGE_DETENTION` invoice in `DRAFT` for the
        booking, with `DEMURRAGE` and `DETENTION` lines (zero-valued lines are
        skipped), and the shipper's exposure variants are recomputed."

        Design: Difficulty/dual_variant_calc/demurrage_provisional_vs_final_divergence
        """
        ctx = setup_discharged_fcl_scenario()
        assignment_id = ctx["assignment"]["id"]

        validate_success(api.set_clock("2026-09-30T12:00:00Z", OPS), 200)
        gated_out = validate_success(
            api.gate_out_assignment(assignment_id, BC), 200)
        assert gated_out["demurrage_days"] == 5
        assert gated_out["demurrage_charge_cents"] == 105000

        validate_success(api.set_clock("2026-10-06T12:00:00Z", OPS), 200)
        returned = validate_success(
            api.empty_return_assignment(assignment_id, BC), 200)
        assert returned["status"] == "EMPTY_RETURNED"
        # 6 full days gated out - 3 free = 3 chargeable days @12000.
        assert returned["detention_days"] == 3
        assert returned["detention_charge_cents"] == 36000

        dd = find_booking_invoice(ctx["booking"]["id"], "DEMURRAGE_DETENTION")
        assert dd is not None, "nonzero charges auto-create the D&D invoice"
        assert dd["status"] == "DRAFT"
        assert dd["total_cents"] == 141000, "105000 demurrage + 36000 detention"


class TestFreeTimeExactBoundary:
    """Same contract free time (4 demurrage / 3 detention days); discharge at
    2026-09-21T12:00:00Z, gate-out exactly +4 days, empty-return exactly +3."""

    def test_demurrage_exactly_free_days_yields_zero(self, api):
        """PRD §3.8: "Chargeable demurrage days are the whole days between
        `discharged_at` and `gated_out_at`, minus the contract's
        `demurrage_free_days`, floored at zero — a stay of exactly the
        free-day count yields zero chargeable days, and gate-out at the same
        instant as discharge yields zero."

        Design: Difficulty/boundary_precision_check/detention_free_time_exact_boundary_zero_charge
        """
        ctx = setup_discharged_fcl_scenario()
        assignment_id = ctx["assignment"]["id"]

        validate_success(api.set_clock("2026-09-25T12:00:00Z", OPS), 200)
        gated_out = validate_success(
            api.gate_out_assignment(assignment_id, BC), 200)
        assert gated_out["demurrage_days"] == 0, (
            "exactly 4 full days == demurrage_free_days: no +1, no charge"
        )
        assert gated_out["demurrage_charge_cents"] == 0

    def test_detention_exactly_free_days_yields_zero_and_no_invoice(self, api):
        """PRD §3.8: "Chargeable detention days are the whole days between
        `gated_out_at` and `empty_returned_at`, minus the contract's
        `detention_free_days`, floored at zero."
        PRD §3.8: "If the sum of `demurrage_charge_cents` and
        `detention_charge_cents` is greater than zero, empty-return
        auto-creates a `DEMURRAGE_DETENTION` invoice in `DRAFT` for the
        booking, with `DEMURRAGE` and `DETENTION` lines (zero-valued lines are
        skipped), and the shipper's exposure variants are recomputed."

        Design: Difficulty/boundary_precision_check/detention_free_time_exact_boundary_zero_charge
        """
        ctx = setup_discharged_fcl_scenario()
        assignment_id = ctx["assignment"]["id"]

        validate_success(api.set_clock("2026-09-25T12:00:00Z", OPS), 200)
        validate_success(api.gate_out_assignment(assignment_id, BC), 200)

        validate_success(api.set_clock("2026-09-28T12:00:00Z", OPS), 200)
        returned = validate_success(
            api.empty_return_assignment(assignment_id, BC), 200)
        assert returned["status"] == "EMPTY_RETURNED"
        assert returned["detention_days"] == 0, (
            "exactly 3 full days == detention_free_days: zero chargeable"
        )
        assert returned["detention_charge_cents"] == 0

        dd = find_booking_invoice(ctx["booking"]["id"], "DEMURRAGE_DETENTION")
        assert dd is None, "zero total charge skips D&D invoice auto-creation"
