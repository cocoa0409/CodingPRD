"""Cash pool lifecycle: sweeps (OCC, zero-sum), the two interest variants,
fee allocation rounding order, netting, and settlement."""
from test_helpers import (
    ADMIN,
    ANALYST,
    MANAGER,
    TREASURY,
    ApiErrorId,
    assert_cash_pool,
    begin_netting,
    create_fiscal_year,
    create_legal_entity,
    create_pool,
    find_position,
    post_sweep,
    set_clock,
    settle_pool,
    validate_error,
    validate_success,
    api_client,
)


class TestPoolLifecycleGates:

    def test_pool_settle_from_open_rejected(self):
        """PRD section 3.8: "Settlement by a `TreasuryManager` (`NETTING →
        SETTLED`) requires the sum of all positions' `balance_cents` to be
        exactly 0 after folding (`ERR_POOL_NOT_ZERO_SUM`)."
        PRD section 2.8: "4. **State legality** — the target resource must be
        in a state from which the requested transition or operation is
        defined, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/pool_settle_from_open_rejected
        """
        fy = create_fiscal_year()
        pool = create_pool(fy["id"])

        resp = api_client.settle_cash_pool(pool["id"], TREASURY)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api_client.get_cash_pool(pool["id"], TREASURY),
                                 200)
        assert after["status"] == "OPEN"

    def test_duplicate_cash_pool_rejected(self):
        """PRD section 3.8: "At most one pool may exist per fiscal year
        (`ERR_DUPLICATE_CASH_POOL`)."

        Design: Corner/errors/duplicate_cash_pool_rejected
        """
        fy = create_fiscal_year()
        create_pool(fy["id"])

        resp = api_client.create_cash_pool(
            {"fiscal_year_id": fy["id"], "interest_method": "CLOSING_BALANCE",
             "admin_fee_cents": 100},
            TREASURY,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASH_POOL)


class TestSweepValidation:

    def test_non_zero_sum_sweep_rejected(self):
        """PRD section 3.8: "The amounts within one sweep request must sum to
        zero across entities (`ERR_POOL_NOT_ZERO_SUM`)."
        PRD section 2.4: "`version` (integer): a system-managed integer that
        increments by exactly 1 on every mutation of the resource."
        PRD section 3.8: "The pool opens in `OPEN` with an empty `positions`
        array"

        Design: Corner/errors/non_zero_sum_sweep_rejected
        """
        fy = create_fiscal_year()
        e1 = create_legal_entity(name="E1", country_code="US",
                                 functional_currency="USD")
        e2 = create_legal_entity(name="E2", country_code="DE",
                                 functional_currency="EUR")
        pool = create_pool(fy["id"])

        resp = api_client.post_sweeps(
            pool["id"],
            {"movements": [{"entity_id": e1["id"], "amount_cents": 100_000},
                           {"entity_id": e2["id"], "amount_cents": -50_000}],
             "expected_cash_pool_version": pool["version"]},
            TREASURY,
        )
        validate_error(resp, ApiErrorId.ERR_POOL_NOT_ZERO_SUM)

        after = validate_success(api_client.get_cash_pool(pool["id"], TREASURY),
                                 200)
        assert after["version"] == pool["version"], \
            "a rejected sweep must not advance the pool version"
        assert after["positions"] == []

    def test_sweeps_forbidden_for_tax_manager(self):
        """PRD section 2.1: "Each write endpoint admits a specific subset of
        these roles (enumerated in §4); a caller whose role is not admitted
        by the endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP
        403)."
        PRD section 4: the cash-pool sweeps endpoint admits TreasuryManager.

        Design: Corner/rbac/sweeps_forbidden_for_tax_manager
        """
        fy = create_fiscal_year()
        e1 = create_legal_entity(name="E1", country_code="US",
                                 functional_currency="USD")
        e2 = create_legal_entity(name="E2", country_code="DE",
                                 functional_currency="EUR")
        pool = create_pool(fy["id"])

        resp = api_client.post_sweeps(
            pool["id"],
            {"movements": [{"entity_id": e1["id"], "amount_cents": 100_000},
                           {"entity_id": e2["id"], "amount_cents": -100_000}],
             "expected_cash_pool_version": pool["version"]},
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestFiscalYearRbac:

    def test_begin_closing_forbidden_for_tax_analyst(self):
        """PRD section 2.1: "Each write endpoint admits a specific subset of
        these roles (enumerated in §4); a caller whose role is not admitted
        by the endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP
        403)."
        PRD section 4: the fiscal-year begin-closing endpoint admits
        GroupTaxAdmin.

        Design: Corner/rbac/begin_closing_forbidden_for_tax_analyst
        """
        fy = create_fiscal_year()

        resp = api_client.begin_closing(fy["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        after = validate_success(api_client.get_fiscal_year(fy["id"], ADMIN),
                                 200)
        assert after["status"] == "OPEN"


class TestPoolSweepOcc:

    def test_occ_stale_pool_sweep_rejected(self):
        """PRD section 2.7: "Posting sweep movements against a cash pool
        requires the request to carry `expected_cash_pool_version`, the
        pool's `version` as the client last observed it. A mismatch with the
        pool's current `version` is likewise rejected with `ERR_STALE_VERSION`
        (HTTP 412), because sweep amounts are computed from observed position
        balances and a stale expectation would net against positions the
        client never saw."

        Design: Corner/cross_cutting_layers/occ_stale_pool_sweep_rejected
        """
        fy = create_fiscal_year()
        e1 = create_legal_entity(name="E1", country_code="US",
                                 functional_currency="USD")
        e2 = create_legal_entity(name="E2", country_code="DE",
                                 functional_currency="EUR")
        pool = create_pool(fy["id"])
        observed_version = pool["version"]

        swept = post_sweep(pool["id"],
                           [{"entity_id": e1["id"], "amount_cents": 100_000},
                            {"entity_id": e2["id"], "amount_cents": -100_000}],
                           observed_version)
        assert swept["version"] == observed_version + 1

        resp = api_client.post_sweeps(
            pool["id"],
            {"movements": [{"entity_id": e1["id"], "amount_cents": 50_000},
                           {"entity_id": e2["id"], "amount_cents": -50_000}],
             "expected_cash_pool_version": observed_version},
            TREASURY,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api_client.get_cash_pool(pool["id"], TREASURY),
                                 200)
        assert find_position(after, e1["id"])["balance_cents"] == 100_000, \
            "the stale sweep was not applied"


class TestInterestVariantsDiverge:
    """Identical sweeps under both interest conventions. Default clock is
    2026-08-01T00:00:00Z (PRD 2.5); sweeps land at t0 and t0+30d, netting at
    t0+60d."""

    def _setup_pools_with_identical_sweeps(self):
        fy26 = create_fiscal_year(year_index=2026)
        fy27 = create_fiscal_year(year_index=2027)
        e1 = create_legal_entity(name="USCo", country_code="US",
                                 functional_currency="USD")
        e2 = create_legal_entity(name="DECo", country_code="DE",
                                 functional_currency="EUR")
        pool_a = create_pool(fy26["id"], interest_method="AVERAGE_BALANCE",
                             admin_fee_cents=0)
        pool_b = create_pool(fy27["id"], interest_method="CLOSING_BALANCE",
                             admin_fee_cents=0)

        # t0 (2026-08-01): +1000000 on E1 / mirrored on E2, both pools.
        va = post_sweep(pool_a["id"],
                        [{"entity_id": e1["id"], "amount_cents": 1_000_000},
                         {"entity_id": e2["id"], "amount_cents": -1_000_000}],
                        pool_a["version"])["version"]
        vb = post_sweep(pool_b["id"],
                        [{"entity_id": e1["id"], "amount_cents": 1_000_000},
                         {"entity_id": e2["id"], "amount_cents": -1_000_000}],
                        pool_b["version"])["version"]

        set_clock("2026-08-31T00:00:00Z")
        va = post_sweep(pool_a["id"],
                        [{"entity_id": e1["id"], "amount_cents": 2_000_000},
                         {"entity_id": e2["id"], "amount_cents": -2_000_000}],
                        va)["version"]
        vb = post_sweep(pool_b["id"],
                        [{"entity_id": e1["id"], "amount_cents": 2_000_000},
                         {"entity_id": e2["id"], "amount_cents": -2_000_000}],
                        vb)["version"]

        set_clock("2026-09-30T00:00:00Z")
        return pool_a, pool_b, e1, e2

    def test_average_balance_interest(self):
        """PRD section 3.8: "Second, interest is computed per position at a
        per-diem spread of 85 basis points per annum — that is, 85 divided by
        10000 and by 365 per cent-day. Under `AVERAGE_BALANCE` the interest
        base is the position's accumulated `accrued_balance_day_cents`, so
        the intra-period timing of sweeps changes the result"
        PRD section 3.8: "under the average-balance convention, each sweep
        adds the position's balance immediately before the sweep multiplied
        by the whole days elapsed since the previous event, measured on the
        logical clock."

        Design: Difficulty/dual_variant_calc/pool_interest_average_vs_closing_balance_diverge
        """
        pool_a, _, e1, e2 = self._setup_pools_with_identical_sweeps()
        netted = begin_netting(pool_a["id"])
        assert_cash_pool(netted)

        # balance-days: 0 (first sweep) + 1000000*30 + 3000000*30 = 120000000
        # interest = round_half_up(120000000 * 85 / 10000 / 365) = 2795
        assert find_position(netted, e1["id"])["interest_cents"] == 2795
        assert find_position(netted, e2["id"])["interest_cents"] == -2795

    def test_closing_balance_interest_diverges(self):
        """PRD section 3.8: "under `CLOSING_BALANCE` the base is the
        position's `balance_cents` multiplied by the whole days from
        `opened_at_utc` to `netting_at_utc`, ignoring intra-period timing
        entirely and yielding different cents for identical sweeps."

        Design: Difficulty/dual_variant_calc/pool_interest_average_vs_closing_balance_diverge
        """
        pool_a, pool_b, e1, e2 = self._setup_pools_with_identical_sweeps()
        netted_a = begin_netting(pool_a["id"])
        netted_b = begin_netting(pool_b["id"])

        # closing base: 3000000 * 60 days = 180000000 cent-days
        # interest = round_half_up(180000000 * 85 / 10000 / 365) = 4192
        assert find_position(netted_b, e1["id"])["interest_cents"] == 4192
        assert find_position(netted_b, e2["id"])["interest_cents"] == -4192

        assert find_position(netted_a, e1["id"])["interest_cents"] != \
            find_position(netted_b, e1["id"])["interest_cents"], \
            "identical sweeps must price differently under the two variants"


class TestFeeAllocationRoundingOrder:

    def _setup_fee_scenario(self):
        fy = create_fiscal_year()
        e1 = create_legal_entity(name="E1", country_code="US",
                                 functional_currency="USD")
        e2 = create_legal_entity(name="E2", country_code="DE",
                                 functional_currency="EUR")
        e3 = create_legal_entity(name="E3", country_code="FR",
                                 functional_currency="EUR")
        e4 = create_legal_entity(name="E4", country_code="NL",
                                 functional_currency="EUR")
        pool = create_pool(fy["id"], interest_method="AVERAGE_BALANCE",
                           admin_fee_cents=10_000)
        post_sweep(pool["id"],
                   [{"entity_id": e1["id"], "amount_cents": 100},
                    {"entity_id": e2["id"], "amount_cents": 100},
                    {"entity_id": e3["id"], "amount_cents": 100},
                    {"entity_id": e4["id"], "amount_cents": -300}],
                   pool["version"])
        return pool, (e1, e2, e3, e4)

    def test_pool_fee_round_per_position(self):
        """PRD section 3.8: "walking positions in order of their entity's
        `created_at` ascending, each position's `fee_cents` is the
        `admin_fee_cents` multiplied by the position's absolute balance and
        divided by the fee base, rounded half-up per position first; the
        residual — the fee minus the sum of the rounded per-position amounts,
        which may be positive or negative — is assigned to the position with
        the largest absolute balance, with ties broken by the entity's
        `created_at` ascending, never by entity identifier."

        Design: Difficulty/combinatorial_formula/pool_fee_round_per_position_then_residual
        """
        pool, (e1, e2, e3, e4) = self._setup_fee_scenario()
        netted = begin_netting(pool["id"])

        # B = 600; raw shares 1666.67 x3 + 5000; round-per-position gives
        # 1667/1667/1667/5000, overshooting by 1, so the residual -1 lands on
        # E4 (largest |balance|): 1667/1667/1667/4999.
        assert find_position(netted, e1["id"])["fee_cents"] == 1667
        assert find_position(netted, e2["id"])["fee_cents"] == 1667
        assert find_position(netted, e3["id"])["fee_cents"] == 1667
        assert find_position(netted, e4["id"])["fee_cents"] == 4999

    def test_pool_fee_residual_conserves_total(self):
        """PRD section 3.8: "Third, the administration fee is allocated: the
        fee base is the sum of the absolute balances across all positions
        after pending amounts and transaction netting have been folded in"
        PRD section 3.8: "This pinned order — round per position, then sum,
        then residual — is the only accepted sequence; summing first and
        rounding once is a rejected alternative."

        Design: Difficulty/combinatorial_formula/pool_fee_round_per_position_then_residual
        """
        pool, (e1, e2, e3, e4) = self._setup_fee_scenario()
        netted = begin_netting(pool["id"])

        total_fee = sum(find_position(netted, e["id"])["fee_cents"]
                        for e in (e1, e2, e3, e4))
        assert total_fee == 10_000, \
            "rounded per-position fees plus residual reassemble the admin fee"
        # The largest |balance| (E4 at 300) absorbed the -1 residual:
        # sum-then-round would have given E4 exactly 5000.
        assert find_position(netted, e4["id"])["fee_cents"] == 4999


class TestZeroSumInvariant:

    def _setup_reversed_sweeps(self):
        fy = create_fiscal_year()
        e1 = create_legal_entity(name="E1", country_code="US",
                                 functional_currency="USD")
        e2 = create_legal_entity(name="E2", country_code="DE",
                                 functional_currency="EUR")
        e3 = create_legal_entity(name="E3", country_code="FR",
                                 functional_currency="EUR")
        pool = create_pool(fy["id"])
        v = post_sweep(pool["id"],
                       [{"entity_id": e1["id"], "amount_cents": 500_000},
                        {"entity_id": e2["id"], "amount_cents": -200_000},
                        {"entity_id": e3["id"], "amount_cents": -300_000}],
                       pool["version"])["version"]
        post_sweep(pool["id"],
                   [{"entity_id": e1["id"], "amount_cents": -500_000},
                    {"entity_id": e2["id"], "amount_cents": 200_000},
                    {"entity_id": e3["id"], "amount_cents": 300_000}],
                   v)
        return pool, (e1, e2, e3)

    def test_reverse_sweep_restores_zero_positions(self):
        """PRD section 3.8: "Each movement upserts the entity's position
        object — which carries `entity_id`, `balance_cents`,
        `accrued_balance_day_cents`, `pending_cents`, `interest_cents`,
        `fee_cents`, and a `status` — adding the amount to the position's
        `balance_cents`"
        PRD section 3.8: "At every step the positions remain zero-sum in
        aggregate: sweeps are zero-sum validated, pending accruals are
        symmetric, and transaction folds are symmetric."

        Design: Difficulty/compensating_invariant/sweep_and_reverse_sweep_conserve_pool_zero_sum
        """
        pool, entities = self._setup_reversed_sweeps()
        after = validate_success(api_client.get_cash_pool(pool["id"], TREASURY),
                                 200)
        for entity in entities:
            assert find_position(after, entity["id"])["balance_cents"] == 0
        assert sum(p["balance_cents"] for p in after["positions"]) == 0

    def test_zero_sum_pool_settles(self):
        """PRD section 3.8: "Settlement by a `TreasuryManager` (`NETTING →
        SETTLED`) requires the sum of all positions' `balance_cents` to be
        exactly 0 after folding (`ERR_POOL_NOT_ZERO_SUM`). On success every
        position's `status` becomes `SETTLED` and every `NETTED` transaction
        of the year becomes `SETTLED`, ending both the pool lifecycle and the
        settlement dimension of its transactions."

        Design: Difficulty/compensating_invariant/sweep_and_reverse_sweep_conserve_pool_zero_sum
        """
        pool, entities = self._setup_reversed_sweeps()
        begin_netting(pool["id"])
        settled = settle_pool(pool["id"])
        assert settled["status"] == "SETTLED"
        for position in settled["positions"]:
            assert position["balance_cents"] == 0
            assert position["status"] == "SETTLED"
