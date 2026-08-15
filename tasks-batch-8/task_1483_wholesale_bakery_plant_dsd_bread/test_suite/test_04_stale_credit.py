"""Stale-return credit: dual provisional/verified variants, pinned rounding
order, age-tier boundaries, and zero-rate tier (PRD §3.8, §2.8)."""
from test_helpers import (
    create_stale_return,
    make_qa_headers,
    set_clock,
    setup_delivered_stop_scenario,
    setup_two_product_delivered_scenario,
    validate_success,
)


class TestStaleCreditProvisionalVsVerified:
    def test_provisional_computed_from_declared_lines(self, api):
        """PRD §3.8: "The provisional variant, computed at creation, uses the
        driver-declared `lines` and the creation clock." And: "each line's
        credit is its `qty` multiplied by the product's `base_price_cents` and
        the applicable rate, rounded half-up to whole cents, and the return's
        credit is the sum of those per-line amounts."

        Design: Difficulty/dual_variant_calc/stale_credit_provisional_vs_verified
        """
        ctx = setup_two_product_delivered_scenario(plant_name="Plant Alpha")
        store = ctx["store"]
        driver = ctx["driver"]
        stop = ctx["stop"]
        batch_a = ctx["batch"]
        batch_d = ctx["batch_d"]

        sre = create_stale_return(
            store["id"],
            stop["id"],
            [{"batch_id": batch_a["id"], "qty": 3},
             {"batch_id": batch_d["id"], "qty": 3}],
            driver["id"],
        )
        # Per-line round-half-up: round_half_up(3*199*0.5)=299 +
        # round_half_up(3*99*0.5)=149 -> 448.
        assert sre["provisional_credit_cents"] == 448, (
            f"provisional must be 299+149=448, got {sre['provisional_credit_cents']}"
        )
        assert sre["status"] == "PENDING_VERIFICATION"

    def test_verified_computed_from_qa_lines_and_differs(self, api):
        """PRD §3.8: "The verified variant, computed at QA verification, takes
        its quantities from the QA-supplied `verified_lines` but recomputes
        each line's age from the original creation clock — pickup time is
        fixed at creation and does not move with the verification."

        Design: Difficulty/dual_variant_calc/stale_credit_provisional_vs_verified
        """
        ctx = setup_two_product_delivered_scenario(plant_name="Plant Alpha 2")
        store = ctx["store"]
        driver = ctx["driver"]
        stop = ctx["stop"]
        batch_a = ctx["batch"]
        batch_d = ctx["batch_d"]

        sre = create_stale_return(
            store["id"],
            stop["id"],
            [{"batch_id": batch_a["id"], "qty": 3},
             {"batch_id": batch_d["id"], "qty": 3}],
            driver["id"],
        )
        verified = validate_success(
            api.verify_stale_return(
                sre["id"],
                {"verified_lines": [{"batch_id": batch_a["id"], "qty": 3},
                                    {"batch_id": batch_d["id"], "qty": 2}]},
                make_qa_headers("qa-1"),
            )
        )
        # Verified: 299 + round_half_up(2*99*0.5)=99 -> 398. The SAME physical
        # pickup yields a different credit under the two variants because QA
        # adjusted the second line's qty from 3 to 2.
        assert verified["final_credit_cents"] == 398, (
            f"final must be 299+99=398, got {verified['final_credit_cents']}"
        )
        assert verified["status"] == "VERIFIED"
        assert verified["provisional_credit_cents"] != verified["final_credit_cents"]


class TestStaleCreditPerLineRoundingOrder:
    def test_per_line_rounding_then_sum(self, api):
        """PRD §2.8: "stale-return credit rounds each line to whole cents
        first and then sums the lines." PRD §3.8: "each line's credit is its
        `qty` multiplied by the product's `base_price_cents` and the
        applicable rate, rounded half-up to whole cents, and the return's
        credit is the sum of those per-line amounts."

        Design: Difficulty/combinatorial_formula/stale_credit_per_line_rounding_order
        """
        ctx = setup_two_product_delivered_scenario(plant_name="Plant Delta")
        store = ctx["store"]
        driver = ctx["driver"]
        stop = ctx["stop"]
        batch_a = ctx["batch"]
        batch_d = ctx["batch_d"]

        sre = create_stale_return(
            store["id"],
            stop["id"],
            [{"batch_id": batch_a["id"], "qty": 3},
             {"batch_id": batch_d["id"], "qty": 3}],
            driver["id"],
        )
        # Pinned order: round_half_up(3*199*0.5)=299 + round_half_up(3*99*0.5)=149 = 448.
        # The alternative sum-then-round order would give 447.
        assert sre["provisional_credit_cents"] == 448, (
            f"per-line rounding then sum must yield 448, got {sre['provisional_credit_cents']}"
        )

    def test_per_line_rounding_persists_on_verify(self, api):
        """PRD §3.8: "The rounding order is pinned: each line's credit is its
        `qty` multiplied by the product's `base_price_cents` and the
        applicable rate, rounded half-up to whole cents, and the return's
        credit is the sum of those per-line amounts." (the verified variant
        shares this pinned rounding order.)

        Design: Difficulty/combinatorial_formula/stale_credit_per_line_rounding_order
        """
        ctx = setup_two_product_delivered_scenario(plant_name="Plant Delta 2")
        store = ctx["store"]
        driver = ctx["driver"]
        stop = ctx["stop"]
        batch_a = ctx["batch"]
        batch_d = ctx["batch_d"]

        sre = create_stale_return(
            store["id"],
            stop["id"],
            [{"batch_id": batch_a["id"], "qty": 3},
             {"batch_id": batch_d["id"], "qty": 3}],
            driver["id"],
        )
        verified = validate_success(
            api.verify_stale_return(
                sre["id"],
                {"verified_lines": [{"batch_id": batch_a["id"], "qty": 3},
                                    {"batch_id": batch_d["id"], "qty": 3}]},
                make_qa_headers("qa-1"),
            )
        )
        # Same per-line rounding on the verified variant: 299 + 149 = 448.
        assert verified["final_credit_cents"] == 448, (
            f"verified per-line rounding must yield 448, got {verified['final_credit_cents']}"
        )


class TestStaleAgeTierBoundary:
    def test_age_exactly_24h_earns_full_rate(self, api):
        """PRD §3.8: "At 24 hours or less the line credits at the full rate of
        1.00."

        Design: Difficulty/boundary_precision_check/stale_age_tier_24h_boundary
        """
        ctx = setup_delivered_stop_scenario(
            plant_name="Plant Xi",
            order_qty=100,
            bake_complete_clock="2026-08-09T09:00:00Z",
        )
        store = ctx["store"]
        driver = ctx["driver"]
        stop = ctx["stop"]
        batch = ctx["batch"]

        # Age exactly 24h after bake_completed_at.
        set_clock("2026-08-10T09:00:00Z")
        sre = create_stale_return(
            store["id"], stop["id"], [{"batch_id": batch["id"], "qty": 2}], driver["id"]
        )
        # rate 1.00: 2 * 199 = 398.
        assert sre["provisional_credit_cents"] == 398, (
            f"age 24h must earn rate 1.00: 2*199=398, got {sre['provisional_credit_cents']}"
        )

    def test_age_25h_drops_to_half_rate(self, api):
        """PRD §3.8: "from 25 through 48 hours the rate is 0.50."

        Design: Difficulty/boundary_precision_check/stale_age_tier_24h_boundary
        """
        ctx = setup_delivered_stop_scenario(
            plant_name="Plant Xi 25h",
            order_qty=100,
            bake_complete_clock="2026-08-09T09:00:00Z",
        )
        store = ctx["store"]
        driver = ctx["driver"]
        stop = ctx["stop"]
        batch = ctx["batch"]

        # Age exactly 25h.
        set_clock("2026-08-10T10:00:00Z")
        sre = create_stale_return(
            store["id"], stop["id"], [{"batch_id": batch["id"], "qty": 2}], driver["id"]
        )
        # rate 0.50: round_half_up(2*199*0.5) = 199.
        assert sre["provisional_credit_cents"] == 199, (
            f"age 25h must earn rate 0.50: 2*199*0.5=199, got {sre['provisional_credit_cents']}"
        )


class TestStaleCreditZeroRate:
    def test_stale_credit_zero_rate_for_old_bread(self, api):
        """PRD §3.8: "beyond 48 hours the rate is 0.00."
        PRD §3.8: "The return window is 72 hours: a pickup recorded more than
        72 hours after a line's `bake_completed_at` is rejected with
        `ERR_RETURN_WINDOW_CLOSED`."

        Design: Corner/calculations/stale_credit_zero_rate_for_old_bread
        """
        ctx = setup_delivered_stop_scenario(
            plant_name="Plant P ZeroRate",
            order_qty=100,
            bake_complete_clock="2026-08-09T09:00:00Z",
        )
        store = ctx["store"]
        driver = ctx["driver"]
        stop = ctx["stop"]
        batch = ctx["batch"]

        # Age 50h — past the 48h positive-rate tier but still inside the 72h
        # return window.
        set_clock("2026-08-11T11:00:00Z")
        sre = create_stale_return(
            store["id"], stop["id"], [{"batch_id": batch["id"], "qty": 4}], driver["id"]
        )
        assert sre["provisional_credit_cents"] == 0, (
            f"age 50h must earn rate 0.00 (credit 0), got {sre['provisional_credit_cents']}"
        )
