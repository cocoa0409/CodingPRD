"""Annual settlement computation: per-airline true-up shares, per-line
rounding-remainder reconciliation, and the recompute compensating invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_activity,
    assert_settlement_true_up_invariant,
    compute_settlement,
    get_success_data,
    list_lines,
    recompute_payload,
    setup_computed_settlement,
    setup_signatory_year,
    setup_year_with_activity,
    validate_error,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]


def _lines_by_airline(ws, settlement_id):
    lines = list_lines(settlement_id)
    by_airline = {}
    for iata, airline in ws["airlines"].items():
        for line in lines:
            if line["airline_id"] == airline["id"]:
                by_airline[iata] = line
    return by_airline


class TestFinalTrueUp:
    PROV_POOL = dict(
        airfield_opex_cents=1000000000,
        terminal_opex_cents=0,
        nonairline_airfield_revenue_cents=0,
        nonairline_terminal_revenue_cents=0,
        terminal_total_space_sqft=100000,
        forecast_landed_weight_kg=1000000,
        prior_year_surplus_cents=0,
    )
    PROV_AIRLINES = [{"iata_code": "AA"}, {"iata_code": "AB"}]
    PROV_ACTIVITY = [
        {"iata_code": "AA", "landed_weight_kg": 300000},
        {"iata_code": "AB", "landed_weight_kg": 300000},
    ]

    def test_compute_creates_per_airline_lines_with_actual_shares(self, api):
        """PRD §3.5: "A successful computation runs the true-up waterfall
        below, creates one **AirlineSettlementLine** per airline that had any
        activity or any rented space during the year, sets the year's
        `settlement_id` to the new settlement"
        PRD §3.5: "each signatory carrier's `actual_airfield_share_cents` is
        the actual airfield requirement multiplied by that carrier's own
        signatory-snapshot landed weight and divided by the signatory pool
        weight, rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/annual_true_up_provisional_vs_final_divergence
        """
        ws = setup_year_with_activity("FY_PROV", "RESIDUAL", self.PROV_AIRLINES,
                                      self.PROV_ACTIVITY, **self.PROV_POOL)
        settlement = compute_settlement(ws)
        assert settlement["status"] == "COMPUTED"
        assert settlement["actual_airfield_requirement_cents"] == 1000000000, (
            "The actual airfield requirement is rebuilt against actuals")

        lines = _lines_by_airline(ws, settlement["id"])
        assert set(lines.keys()) == {"AA", "AB"}, (
            "One line per airline that had activity")
        # rate = 1e9 * 1000 / 1e6 = 1_000_000 per unit; 300_000 kg = 300 units.
        for iata in ("AA", "AB"):
            assert lines[iata]["actual_airfield_share_cents"] == 500000000
            assert lines[iata]["billed_landing_cents"] == 300000000

    def test_true_up_and_totals_follow_the_waterfall(self, api):
        """PRD §3.5: "Each line's `true_up_cents` is then the sum of its
        `actual_airfield_share_cents` and `actual_terminal_share_cents` minus
        the sum of what the carrier was already billed — its
        `billed_landing_cents` and `billed_terminal_cents`."
        PRD §3.5: "One invariant must always hold: `total_true_up_cents` equals
        the sum of `actual_airfield_requirement_cents` and
        `actual_terminal_requirement_cents` minus the sum of
        `total_billed_landing_cents` and `total_billed_terminal_cents`."

        Design: Difficulty/dual_variant_calc/annual_true_up_provisional_vs_final_divergence
        """
        ws = setup_year_with_activity("FY_PRV2", "RESIDUAL", self.PROV_AIRLINES,
                                      self.PROV_ACTIVITY, **self.PROV_POOL)
        settlement = compute_settlement(ws)

        lines = _lines_by_airline(ws, settlement["id"])
        for iata in ("AA", "AB"):
            assert lines[iata]["true_up_cents"] == 200000000, (
                "500_000_000 share minus 300_000_000 billed")

        assert settlement["total_billed_landing_cents"] == 600000000
        assert settlement["total_billed_terminal_cents"] == 0
        assert settlement["total_true_up_cents"] == 400000000
        assert_settlement_true_up_invariant(settlement)


class TestRoundingRemainderReconciliation:
    RND_POOL = dict(
        airfield_opex_cents=10001,
        terminal_opex_cents=0,
        nonairline_airfield_revenue_cents=0,
        nonairline_terminal_revenue_cents=0,
        terminal_total_space_sqft=100000,
        forecast_landed_weight_kg=300,
        prior_year_surplus_cents=0,
    )
    RND_AIRLINES = [{"iata_code": "RA"}, {"iata_code": "RB"},
                    {"iata_code": "RC"}]
    RND_ACTIVITY = [
        {"iata_code": "RA", "landed_weight_kg": 100},
        {"iata_code": "RB", "landed_weight_kg": 100},
        {"iata_code": "RC", "landed_weight_kg": 100},
    ]

    def test_airfield_shares_reconcile_to_requirement(self, api):
        """PRD §3.5: "Per-line rounding can drift from the requirement by a few
        cents, and the drift is reconciled rather than absorbed. After every
        airfield share is rounded, the difference between their sum and the
        actual airfield requirement is allocated, cent for cent, to the carrier
        with the largest signatory-snapshot landed weight"

        Design: Difficulty/combinatorial_formula/annual_true_up_per_line_rounding_remainder_allocation
        """
        ws = setup_year_with_activity("FY_RND", "RESIDUAL", self.RND_AIRLINES,
                                      self.RND_ACTIVITY, **self.RND_POOL)
        settlement = compute_settlement(ws)

        lines = _lines_by_airline(ws, settlement["id"])
        shares = sorted(lines[iata]["actual_airfield_share_cents"]
                        for iata in ("RA", "RB", "RC"))
        # round_half_up(10001 * 100/300) = 3334 per carrier; the -1 cent drift
        # lands on one carrier, so the shares are {3333, 3334, 3334}.
        assert shares == [3333, 3334, 3334]
        assert sum(shares) == 10001, (
            "The rounded shares reconcile cent-for-cent to the requirement")
        assert settlement["total_true_up_cents"] == 10001, (
            "Nothing was billed (100 kg lands below the 500 kg round-up), so "
            "the true-up equals the requirement")

    def test_remainder_lands_on_earliest_created_tied_carrier(self, api):
        """PRD §3.5: "Ties on either side are broken in favor of the carrier
        whose `Airline` record has the earliest `created_at`."
        PRD §3.5: "After every airfield share is rounded, the difference
        between their sum and the actual airfield requirement is allocated,
        cent for cent, to the carrier with the largest signatory-snapshot
        landed weight"

        Design: Difficulty/combinatorial_formula/annual_true_up_per_line_rounding_remainder_allocation
        """
        ws = setup_year_with_activity("FY_RND2", "RESIDUAL", self.RND_AIRLINES,
                                      self.RND_ACTIVITY, **self.RND_POOL)
        settlement = compute_settlement(ws)

        lines = _lines_by_airline(ws, settlement["id"])
        # All three carriers tie at 100 kg; R1 was registered first.
        assert lines["RA"]["actual_airfield_share_cents"] == 3333, (
            "The earliest-created carrier absorbs the -1 cent remainder")
        assert lines["RB"]["actual_airfield_share_cents"] == 3334
        assert lines["RC"]["actual_airfield_share_cents"] == 3334
        # No carrier was billed anything, so each true-up equals its share.
        assert lines["RA"]["true_up_cents"] == 3333


class TestRecomputeInvariant:
    INV_POOL = dict(
        airfield_opex_cents=1000000,
        terminal_opex_cents=0,
        nonairline_airfield_revenue_cents=0,
        nonairline_terminal_revenue_cents=0,
        terminal_total_space_sqft=100000,
        forecast_landed_weight_kg=1000,
        prior_year_surplus_cents=0,
    )

    def _setup_computed_then_extra_activity(self, api, label):
        ws = setup_computed_settlement(
            label,
            airline_specs=[{"iata_code": "IV"}],
            activity_specs=[{"iata_code": "IV", "landed_weight_kg": 1000}],
            **self.INV_POOL)
        # A further 500 kg arrives after the first computation: the 500 kg
        # remainder rounds up, so this record bills one more unit of 1_000_000.
        add_activity(ws["fy"]["id"], ws["airlines"]["IV"]["id"], 500,
                     activity_date="2026-09-06T00:00:00Z")
        return ws

    def test_recompute_updates_billed_totals(self, api):
        """PRD §3.5: "A computed settlement can be recomputed against the
        year's current activity records. This is the second
        optimistic-concurrency-guarded write of §2.10: the request must carry
        `expected_annual_settlement_version` matching the settlement's current
        `version`"
        PRD §3.5: "At the settlement level, `total_billed_landing_cents` is the
        sum of `billed_landing_fee_cents` across the year's activity records"

        Design: Difficulty/compensating_invariant/settlement_recompute_total_true_up_conserved
        """
        ws = self._setup_computed_then_extra_activity(api, "FY_INV1")
        settlement = ws["settlement"]

        recomputed = validate_success(api.recompute_settlement(
            settlement["id"], recompute_payload(settlement["version"]),
            FINANCE))
        assert recomputed["total_billed_landing_cents"] == 2000000, (
            "Both activity records (1_000_000 + 1_000_000) are now billed in")
        assert recomputed["version"] > settlement["version"], (
            "A successful recompute increments the settlement's version")

    def test_recompute_preserves_compensating_invariant(self, api):
        """PRD §3.5: "One invariant must always hold: `total_true_up_cents`
        equals the sum of `actual_airfield_requirement_cents` and
        `actual_terminal_requirement_cents` minus the sum of
        `total_billed_landing_cents` and `total_billed_terminal_cents`. This
        compensating invariant is what makes a later recompute safe."

        Design: Difficulty/compensating_invariant/settlement_recompute_total_true_up_conserved
        """
        ws = self._setup_computed_then_extra_activity(api, "FY_INV2")
        settlement = ws["settlement"]

        recomputed = validate_success(api.recompute_settlement(
            settlement["id"], recompute_payload(settlement["version"]),
            FINANCE))
        assert_settlement_true_up_invariant(recomputed)
        # requirement 1_000_000 - billed 2_000_000 -> the airport credits 1e6.
        assert recomputed["total_true_up_cents"] == -1000000


class TestComputePreconditions:
    def test_compute_without_activity_rejected(self, api):
        """PRD §3.5: "Computation requires the year to stand `OPEN` and at
        least one activity record to exist for it; with no activity at all the
        attempt is rejected with `ERR_NO_ACTIVITY`."

        Design: Corner/state_machines/settle_compute_requires_activity
        """
        ws = setup_signatory_year("FY_NA", airline_specs=[{"iata_code": "NA"}])

        resp = api.compute_settlement(ws["fy"]["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVITY)
