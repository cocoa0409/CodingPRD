"""Supply contracts: window guards, tier pricing, annual rebate, OCC, expiry sweep."""

from test_helpers import (
    INDEX_NAME_SPOT,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_qty,
    assert_rebate_read,
    close_coa_review_response,
    create_contract_payload,
    create_pending_contract,
    create_price_index_payload,
    disposition_finding,
    fresh_source_version,
    register_and_accept_coa,
    register_coa,
    set_clock,
    setup_source_with_contract,
    start_coa_review,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_priced_contract(ingredient_code, supplier_code, contract_kwargs, parameters=None):
    """ACTIVE source + ACTIVE contract ready for CoA lots."""
    return setup_source_with_contract(
        ingredient_code, supplier_code=supplier_code, contract_kwargs=contract_kwargs,
        parameters=parameters,
    )


def _accept_lot(ctx, lot_number, qty, received_at, observed=5, parameter_name="moisture"):
    return register_and_accept_coa(
        ctx["source"]["id"], ctx["contract"]["id"], lot_number, qty, received_at,
        [{"parameter_name": parameter_name, "observed_value": observed}],
    )


def _post_index(value, observed_at):
    return api_client.create_price_index_observation(
        create_price_index_payload(
            index_name=INDEX_NAME_SPOT, observed_at=observed_at, index_value=value,
        ),
        TEST_USERS["platform_admin_headers"],
    )


class TestTierStraddlePricing:
    def _setup_straddle(self):
        """Contract at cumulative 46000 kg with index factor 1.054, then an 8000 kg
        lot that straddles the tier-2/tier-3 boundary."""
        ctx = _setup_priced_contract(
            "PROT-1", "SUP-P",
            {
                "annual_committed_volume_kg": 60000,
                "index_base_value": 200,
                "index_pass_through_pct": 0.6,
            },
        )
        validate_success(_post_index(218, "2026-07-01T00:00:00Z"), expected_status=201)
        _accept_lot(ctx, "P1", 10000, "2026-07-02T00:00:00Z")
        _accept_lot(ctx, "P2", 10000, "2026-07-03T00:00:00Z")
        _accept_lot(ctx, "P3", 26000, "2026-07-04T00:00:00Z")
        return ctx

    def test_tier_straddle_blended_unit_price(self, api, procurement_manager_headers):
        """PRD §3.7: "The lot's kilograms are allocated marginally across tiers,
        starting from the contract's `cumulative_shipped_kg` before the lot." —
        with prior 46000 kg, an 8000 kg lot prices 4000 kg at the tier-2 adjusted
        base round(4.20 x 1.054, 4) = 4.4268 and 4000 kg at the tier-3 adjusted
        base round(3.95 x 1.054, 4) = 4.1633, blending to
        (17707.20 + 16653.20) / 8000 = 4.2951. "Tier crossings are not
        retroactive: if adding this lot's volume pushes `cumulative_shipped_kg`
        across a tier boundary, only subsequent lots price at the new tier."

        Design: Difficulty/combinatorial_formula/contract_tier_price_straddling_with_index_adjustment
        """
        ctx = self._setup_straddle()
        lot = _accept_lot(ctx, "P4", 8000, "2026-07-05T00:00:00Z")
        assert_qty(lot["unit_price_applied"], 4.2951, places=4)

        contracts, _meta = validate_paginated(
            api.list_contracts(ctx["source"]["id"], procurement_manager_headers)
        )
        contract = [c for c in contracts if c["id"] == ctx["contract"]["id"]][0]
        assert contract["cumulative_shipped_kg"] == 54000, (
            f"46000 + 8000 = 54000 cumulative, got {contract['cumulative_shipped_kg']}"
        )

    def test_tier_straddle_lot_accepted_clean(self, api):
        """PRD §3.6: "lands the CoA in `ACCEPTED` status — or in
        `CONDITIONALLY_ACCEPTED` if at least one finding carries disposition
        `ACCEPT_AS_IS`" — an in-spec lot with zero findings lands in `ACCEPTED`,
        and its blended price (4.2951) is distinct from a pure tier-2 price
        (4.4268).

        Design: Difficulty/combinatorial_formula/contract_tier_price_straddling_with_index_adjustment
        """
        ctx = self._setup_straddle()
        lot = _accept_lot(ctx, "P4", 8000, "2026-07-05T00:00:00Z")
        assert lot["status"] == "ACCEPTED"
        price = float(lot["unit_price_applied"])
        assert abs(price - 4.4268) > 0.001, "pure tier-2 pricing would be a marginal-allocation bug"
        assert_qty(price, 4.2951, places=4)


class TestAnnualRebateRounding:
    def _setup_rebate(self):
        """Contract with index factor 1.0002 (tier-1 unit price 4.5009/kg) and
        three accepted 1000 kg lots."""
        ctx = _setup_priced_contract(
            "STARCH-1", "SUP-S",
            {
                "annual_committed_volume_kg": 100000,
                "index_base_value": 100,
                "index_pass_through_pct": 0.5,
            },
        )
        validate_success(_post_index(100.04, "2026-06-01T00:00:00Z"), expected_status=201)
        _accept_lot(ctx, "S1", 1000, "2026-07-02T00:00:00Z")
        _accept_lot(ctx, "S2", 1000, "2026-07-03T00:00:00Z")
        _accept_lot(ctx, "S3", 1000, "2026-07-04T00:00:00Z")
        return ctx

    def test_rebate_per_line_rounding_then_sum(self, api, procurement_manager_headers):
        """PRD §3.7: "for each qualifying CoA, the line rebate is `shipped_qty_kg`
        times `unit_price_applied` times the rebate rate, rounded half-up to two
        decimal places; the total rebate is the exact sum of the rounded lines.
        This per-line-then-sum order is pinned — the alternative (sum first, round
        once) is not used because the two orders diverge." Three lots of 1000 kg at
        4.5009 give per-line round(4500.90 x 0.015, 2) = 67.51 and total 202.53
        (sum-then-round would give 202.54).

        Design: Difficulty/combinatorial_formula/annual_rebate_per_line_rounding_then_sum
        """
        ctx = self._setup_rebate()
        rebate = validate_success(
            api.get_contract_rebate(ctx["source"]["id"], ctx["contract"]["id"], procurement_manager_headers)
        )
        assert_rebate_read(rebate)
        assert_qty(rebate["rebate_rate"], 0.015, places=4)
        assert_qty(rebate["total_rebate"], 202.53, places=2)
        assert rebate["line_count"] == 3

    def test_rebate_accepted_value_total_distinguishes_rounding_order(self, api, procurement_manager_headers):
        """PRD §3.7: "The rebate rate is 0.02 when the contract's
        `accepted_value_total` is at least 250,000 and 0.015 otherwise;
        `accepted_value_total` is the sum, at full precision, of `shipped_qty_kg`
        times `unit_price_applied` over all CoAs of the contract in `ACCEPTED` or
        `CONDITIONALLY_ACCEPTED` status whose `received_at` falls within the
        contract's `[window_start, window_end)` window." — 3 x 4500.90 = 13502.70
        keeps the low rate; the pinned per-line order yields exactly 202.53.

        Design: Difficulty/combinatorial_formula/annual_rebate_per_line_rounding_then_sum
        """
        ctx = self._setup_rebate()
        rebate = validate_success(
            api.get_contract_rebate(ctx["source"]["id"], ctx["contract"]["id"], procurement_manager_headers)
        )
        assert_qty(rebate["accepted_value_total"], 13502.70, places=2)
        assert_qty(rebate["rebate_rate"], 0.015, places=4)
        # 202.53 (per-line-then-sum) vs 202.54 (sum-then-round): the pinned order wins.
        assert_qty(rebate["total_rebate"], 202.53, places=2)


class TestCumulativeVolumeInvariant:
    def _setup_accept_reject(self):
        """Spec with one CRITICAL purity parameter [95, 100] target 97; ACTIVE
        source + contract; one accepted 1000 kg in-spec lot already in place."""
        ctx = _setup_priced_contract(
            "ACD-1", "SUP-C",
            {
                "annual_committed_volume_kg": 40000,
                "index_base_value": 100,
                "index_pass_through_pct": 0.5,
            },
            parameters=[{
                "parameter_name": "purity", "criticality": "CRITICAL", "uom": "percent",
                "target_value": 97, "min_value": 95, "max_value": 100,
            }],
        )
        _accept_lot(ctx, "OK-1", 1000, "2026-08-01T00:00:00Z", observed=97, parameter_name="purity")
        return ctx

    def _register_and_reject_bad_lot(self, ctx):
        """700 kg lot with purity 90.0 (below the 95 floor): one CRITICAL finding
        dispositioned REJECT_LOT, then close-review REJECT."""
        coa = register_coa(
            ctx["source"]["id"], ctx["contract"]["id"],
            lot_number="BAD-1", shipped_qty_kg=700, received_at="2026-08-02T00:00:00Z",
            measured_values=[{"parameter_name": "purity", "observed_value": 90.0}],
        )
        _under_review, findings = start_coa_review(ctx["source"]["id"], coa["id"])
        assert len(findings) == 1
        disposition_finding(
            ctx["source"]["id"], coa["id"], findings[0]["id"],
            "REJECT_LOT", note="critical failure reject",
        )
        return coa, validate_success(
            close_coa_review_response(ctx["source"]["id"], coa["id"], "REJECT")
        )

    def test_contract_cumulative_volume_conserved_on_reject(self, api, procurement_manager_headers):
        """PRD §3.6: on accept the system "adds `shipped_qty_kg` to the contract's
        `cumulative_shipped_kg`"; on reject "the lot is not priced:
        `final_deviation_score` is computed, `cumulative_shipped_kg` is left
        unchanged, and the CoA lands in `REJECTED`." — the accumulator after
        accept+reject equals the value after accept alone.

        Design: Difficulty/compensating_invariant/contract_cumulative_volume_conserved_on_reject
        """
        ctx = self._setup_accept_reject()

        def cumulative():
            contracts, _meta = validate_paginated(
                api.list_contracts(ctx["source"]["id"], procurement_manager_headers)
            )
            return [c for c in contracts if c["id"] == ctx["contract"]["id"]][0]["cumulative_shipped_kg"]

        assert cumulative() == 1000, "the accepted lot adds exactly its shipped_qty_kg"

        _coa, rejected = self._register_and_reject_bad_lot(ctx)
        assert rejected["status"] == "REJECTED"

        assert cumulative() == 1000, "the rejected lot accrues zero — no drift from the rejection"

    def test_rejected_lot_not_priced_final_score_computed(self, api):
        """PRD §3.6: "For `outcome=REJECT`, the state and segregation and
        undisposed-findings guards are the same, but the lot is not priced:
        `final_deviation_score` is computed, `cumulative_shipped_kg` is left
        unchanged, and the CoA lands in `REJECTED`." — purity 90.0 on CRITICAL
        [95, 100] gives excess_ratio 1.0000 x weight 3 x 100 = 300.00.

        Design: Difficulty/compensating_invariant/contract_cumulative_volume_conserved_on_reject
        """
        ctx = self._setup_accept_reject()
        _coa, rejected = self._register_and_reject_bad_lot(ctx)
        assert rejected["status"] == "REJECTED"
        assert_qty(rejected["final_deviation_score"], 300.0, places=2)
        assert rejected["unit_price_applied"] is None, "a rejected lot is not priced"


class TestContractActivationGuards:
    def _setup_two_overlapping_contracts(self):
        ctx = _setup_priced_contract(
            "OIL-1", "SUP-O",
            {
                "annual_committed_volume_kg": 20000,
                "index_base_value": 100,
                "index_pass_through_pct": 0.5,
            },
        )
        c2 = create_pending_contract(
            ctx["source"]["id"],
            annual_committed_volume_kg=5000,
            window_start="2026-06-01T00:00:00Z",
            window_end="2026-12-01T00:00:00Z",
        )
        ctx["c2"] = c2
        return ctx

    def test_terminated_contract_activate_reports_invalid_state(self, api, procurement_manager_headers):
        """PRD §3.5: "It is rejected with `ERR_INVALID_STATE` if the contract is not
        `PENDING`" and PRD §2.12: "then state-machine permission for the requested
        transition; ... then contract-window overlap" — a TERMINATED contract whose
        window overlaps an ACTIVE sibling reports the state error, never the
        overlap error.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_contract_activate
        """
        ctx = self._setup_two_overlapping_contracts()
        source, c2 = ctx["source"], ctx["c2"]
        validate_success(api.terminate_contract(source["id"], c2["id"], procurement_manager_headers))

        resp = api.activate_contract(source["id"], c2["id"], procurement_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_pending_contract_overlapping_active_sibling_rejected(self, api, procurement_manager_headers):
        """PRD §3.5: "It is rejected with `ERR_INVALID_STATE` if the contract is not
        `PENDING`, with `ERR_SOURCE_NOT_ACTIVE` if the parent source is not
        `ACTIVE`, with `ERR_CONTRACT_WINDOW_NOT_OPEN` if the logical clock is before
        `window_start` or at or after `window_end`, and with
        `ERR_CONTRACT_WINDOW_OVERLAP` if another `ACTIVE` contract of the same
        source has a window that overlaps this one."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_contract_activate
        """
        ctx = self._setup_two_overlapping_contracts()
        source, c2 = ctx["source"], ctx["c2"]
        # C2 stays PENDING; its [2026-06-01, 2026-12-01) window overlaps the ACTIVE
        # contract's [2026-01-01, 2027-01-01) window and the clock 2026-08-01 is
        # inside C2's window, so the overlap guard is the one that fires.
        resp = api.activate_contract(source["id"], c2["id"], procurement_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)

    def test_touching_contract_window_activates(self, api, procurement_manager_headers):
        """PRD §3.5: "Overlap is judged with half-open interval arithmetic:
        `[window_start, window_end)` intervals that merely touch at an endpoint do
        not overlap." — a contract starting exactly at the prior contract's
        window_end activates cleanly.

        Design: Difficulty/resource_temporal_overlap/contract_window_half_open_touching_ok_overlap_rejected
        """
        ctx = self._setup_touching_contracts()
        set_clock("2026-09-01T00:00:00Z")
        activated = validate_success(
            api.activate_contract(ctx["source"]["id"], ctx["c2"]["id"], procurement_manager_headers)
        )
        assert activated["status"] == "ACTIVE"

    def test_one_second_overlap_rejected(self, api, procurement_manager_headers):
        """PRD §3.5: "`[window_start, window_end)` intervals that merely touch at
        an endpoint do not overlap" — but starting one second before the ACTIVE
        contract's window_start DOES overlap and is rejected with
        `ERR_CONTRACT_WINDOW_OVERLAP`.

        Design: Difficulty/resource_temporal_overlap/contract_window_half_open_touching_ok_overlap_rejected
        """
        ctx = self._setup_touching_contracts()
        set_clock("2026-09-01T00:00:00Z")
        validate_success(
            api.activate_contract(ctx["source"]["id"], ctx["c2"]["id"], procurement_manager_headers)
        )
        resp = api.activate_contract(ctx["source"]["id"], ctx["c3"]["id"], procurement_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)

    def _setup_touching_contracts(self):
        """C1 ACTIVE [2026-01-01, 2026-09-01); C2 PENDING [2026-09-01, 2027-01-01)
        touching C1's exclusive end; C3 PENDING [2026-08-31T23:59:59Z, 2027-01-01)
        one second earlier."""
        ctx = setup_source_with_contract(
            "EML-1", supplier_code="SUP-E",
            parameters=[{
                "parameter_name": "hlb", "criticality": "MINOR", "uom": "index",
                "target_value": 12, "min_value": 10, "max_value": 14,
            }],
            contract_kwargs={
                "annual_committed_volume_kg": 30000,
                "index_base_value": 100,
                "index_pass_through_pct": 0.5,
                "window_start": "2026-01-01T00:00:00Z",
                "window_end": "2026-09-01T00:00:00Z",
            },
        )
        ctx["c2"] = create_pending_contract(
            ctx["source"]["id"],
            annual_committed_volume_kg=15000,
            window_start="2026-09-01T00:00:00Z",
            window_end="2027-01-01T00:00:00Z",
        )
        ctx["c3"] = create_pending_contract(
            ctx["source"]["id"],
            annual_committed_volume_kg=15000,
            window_start="2026-08-31T23:59:59Z",
            window_end="2027-01-01T00:00:00Z",
        )
        return ctx

    def test_contract_window_not_open_blocks_activate(self, api, procurement_manager_headers):
        """PRD §3.5: "with `ERR_CONTRACT_WINDOW_NOT_OPEN` if the logical clock is
        before `window_start` or at or after `window_end`" — the default clock
        2026-08-01 is before this contract's window_start 2026-09-01.

        Design: Corner/validations/contract_window_not_open_blocks_activate
        """
        ctx = setup_source_with_contract("ENZ-CWO", supplier_code="SUP-CWO")
        pending = create_pending_contract(
            ctx["source"]["id"],
            annual_committed_volume_kg=5000,
            window_start="2026-09-01T00:00:00Z",
            window_end="2027-01-01T00:00:00Z",
        )
        resp = api.activate_contract(ctx["source"]["id"], pending["id"], procurement_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_NOT_OPEN)


class TestContractClockSweepAndOcc:
    def test_contract_auto_expiry_on_clock_sweep(self, api, procurement_manager_headers):
        """PRD §2.6: "**Contract expiry sweep** — every `ACTIVE` supply contract
        whose `window_end` is at or before the new clock transitions to `EXPIRED`."

        Design: Corner/state_machines/contract_auto_expiry_on_clock_sweep
        """
        ctx = setup_source_with_contract(
            "ENZ-EXP", supplier_code="SUP-EXP",
            contract_kwargs={
                "annual_committed_volume_kg": 10000,
                "index_base_value": 100,
                "index_pass_through_pct": 0.5,
                "window_start": "2026-01-01T00:00:00Z",
                "window_end": "2026-08-10T00:00:00Z",
            },
        )
        set_clock("2026-08-10T00:00:00Z")  # exactly window_end: end-exclusive expiry
        contracts, _meta = validate_paginated(
            api.list_contracts(ctx["source"]["id"], procurement_manager_headers)
        )
        contract = [c for c in contracts if c["id"] == ctx["contract"]["id"]][0]
        assert contract["status"] == "EXPIRED"

    def test_occ_stale_version_on_contract_create(self, api, procurement_manager_headers):
        """PRD §2.7: "Creating a supply contract under an approved source requires
        `expected_approved_source_version`. A prior contract creation or a source
        suspension has already changed the source row, so the overlap-window
        computation the client assumed no longer holds." and "if it does not match
        the parent's current `version`, the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_contract_create
        """
        ctx = setup_source_with_contract("OCC-2", supplier_code="SUP-OCC2")
        source = ctx["source"]
        # Capture the source version before the first contract create (that create
        # bumps the parent source's version, PRD §3.5).
        stale_version = fresh_source_version(source["id"])
        c1 = create_pending_contract(
            source["id"],
            annual_committed_volume_kg=5000,
            window_start="2026-01-01T00:00:00Z",
            window_end="2026-07-01T00:00:00Z",
        )
        assert c1["id"]

        resp = api.create_contract(
            source["id"],
            create_contract_payload(
                stale_version,
                annual_committed_volume_kg=7000,
                window_start="2026-07-01T00:00:00Z",
                window_end="2027-01-01T00:00:00Z",
            ),
            procurement_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        retry = api.create_contract(
            source["id"],
            create_contract_payload(
                fresh_source_version(source["id"]),
                annual_committed_volume_kg=7000,
                window_start="2026-07-01T00:00:00Z",
                window_end="2027-01-01T00:00:00Z",
            ),
            procurement_manager_headers,
        )
        assert retry.status_code == 201, f"retry with the fresh version must succeed: {retry.text[:300]}"


class TestIndexSelectorFallback:
    def test_index_selector_fallback_to_contract_base(self, api):
        """PRD §3.7: "If no such observation exists, the contract's
        `index_base_value` is used as `index_current`." — with an empty observation
        pool the adjustment factor is exactly 1 and the tier-1 lot prices at the
        base 4.50.

        Design: Corner/calculations/index_selector_fallback_to_contract_base
        """
        ctx = _setup_priced_contract(
            "ENZ-IDX", "SUP-IDX",
            {
                "annual_committed_volume_kg": 9000,
                "index_base_value": 150,
                "index_pass_through_pct": 0.8,
            },
        )
        lot = _accept_lot(ctx, "IDX-1", 100, "2026-08-01T00:00:00Z")
        assert_qty(lot["unit_price_applied"], 4.5, places=4)
        assert lot["status"] == "ACCEPTED"
