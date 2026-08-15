"""The simulation engine: NII/EVE projections, STATIC vs DYNAMIC variants,
pinned rounding order, OCC, gating checks, and publication (PRD §2.7, §3.3,
§3.4)."""
import pytest

from test_helpers import (
    AN1,
    CH1,
    MV1,
    ApiErrorId,
    activate_book,
    add_position,
    assert_simulation_run,
    create_approved_set,
    create_assumption_set,
    create_book,
    create_policy_limit,
    create_ramp_scenario,
    create_run,
    create_shock_scenario,
    create_simulation_run_payload,
    deposit_beta_params,
    deposit_decay_params,
    get_book,
    get_book_version,
    get_run,
    get_success_data,
    prepayment_params,
    publish_run,
    setup_book1_active,
    setup_book1_approved_sets,
    setup_book1_runnable,
    submit_assumption_set,
    validate_error,
    validate_paginated,
    validate_success,
)

# Expected outputs for the canonical worked-example book under a +200bps
# parallel shock, STATIC convention (PRD §3.4 formulas).
BOOK1_STATIC_BASE = 5_250_000
BOOK1_STATIC_UP200 = 5_010_000
BOOK1_STATIC_UP200_DELTA = -4.57
BOOK1_DYNAMIC_GROWTH5_BASE = 5_533_500
BOOK1_DYNAMIC_GROWTH5_UP200 = 5_336_940
BOOK1_DYNAMIC_GROWTH5_DELTA = -3.55


def _run_payload(ctx, convention="STATIC", annual_growth_pct=None,
                 expected_book_version=None):
    if expected_book_version is None:
        expected_book_version = get_book_version(ctx["book"]["id"])
    return create_simulation_run_payload(
        ctx["sc"]["id"], ctx["ps"]["id"], ctx["ds"]["id"], ctx["bs"]["id"],
        convention, expected_book_version,
        annual_growth_pct=annual_growth_pct)


class TestStaticVsDynamic:
    def test_static_convention_nii_values(self, api):
        """PRD §3.4: "Under the `STATIC` convention the balance used is the
        position's `balance_cents`". PRD §3.4: "The engine computes this
        projection twice: once at a delta of zero for the base
        (`nii_base_cents`) and once under the scenario delta
        (`nii_scenario_cents`). The reported `nii_delta_pct` is the scenario
        value minus the base value, divided by the base value, multiplied by
        one hundred, rounded half-up to two decimal places".

        Design: Difficulty/dual_variant_calc/nii_static_vs_dynamic_same_book_diverge
        """
        ctx = setup_book1_runnable()
        resp = api.create_simulation_run(ctx["book"]["id"],
                                         _run_payload(ctx, "STATIC"), AN1)
        run = validate_success(resp, 201)
        assert_simulation_run(run)
        assert run["nii_base_cents"] == BOOK1_STATIC_BASE
        assert run["nii_scenario_cents"] == BOOK1_STATIC_UP200
        assert run["nii_delta_pct"] == pytest.approx(BOOK1_STATIC_UP200_DELTA)

    def test_dynamic_convention_diverges_from_static(self, api):
        """PRD §3.4: "Under the `STATIC` convention the balance used is the
        position's `balance_cents`; under `DYNAMIC` it is `balance_cents`
        grown by `annual_growth_pct`." PRD §3.4: "under `STATIC` the balance
        is `balance_cents`, and under `DYNAMIC` the balance first shrinks by
        the effective annual decay percentage and then grows by
        `annual_growth_pct`, in that order." PRD §3.4: "Because balances
        differ between conventions, identical inputs produce different net
        interest income under `STATIC` and `DYNAMIC`."

        Design: Difficulty/dual_variant_calc/nii_static_vs_dynamic_same_book_diverge
        """
        ctx = setup_book1_runnable()
        static_run = validate_success(api.create_simulation_run(
            ctx["book"]["id"], _run_payload(ctx, "STATIC"), AN1), 201)
        dyn_run = validate_success(api.create_simulation_run(
            ctx["book"]["id"],
            _run_payload(ctx, "DYNAMIC", annual_growth_pct=5.0), AN1), 201)
        assert dyn_run["nii_base_cents"] == BOOK1_DYNAMIC_GROWTH5_BASE
        assert dyn_run["nii_scenario_cents"] == BOOK1_DYNAMIC_GROWTH5_UP200
        assert dyn_run["nii_delta_pct"] == pytest.approx(
            BOOK1_DYNAMIC_GROWTH5_DELTA)
        assert dyn_run["nii_delta_pct"] != static_run["nii_delta_pct"], (
            "identical inputs must produce different NII under the two "
            "conventions")


class TestDepositBetaBranches:
    def _three_scenarios(self, ctx):
        book_id = ctx["book"]["id"]
        up = ctx["sc"]
        down = create_shock_scenario(book_id, -200, "DN200")
        ramp = create_ramp_scenario(book_id, 300, 12, "RAMP300")
        return up, down, ramp

    def test_deposit_beta_up_and_down_shock_symmetry(self, api):
        """PRD §3.4: "the beta applied is `up_beta_pct` when the year-one
        delta is positive and `down_beta_pct` otherwise. The pass-through
        fraction is 1.0 for `PARALLEL_SHOCK` and `REGULATORY_PRESET`
        scenarios". PRD §3.4: "For each prepayment-eligible loan, the
        effective annual prepayment rate is `base_cpr_pct` plus
        `prepay_sensitivity_per_100bps` for every full 100 basis points of
        rate decline — that is, the positive part of the negated year-one
        delta, divided by 100, multiplied by the sensitivity — with the
        result clamped to the 0-to-100 percent range." PRD §3.4: "Falling
        rates speed prepayments up; rising rates never slow them below
        `base_cpr_pct`."

        Design: Difficulty/combinatorial_formula/deposit_beta_asymmetric_and_ramp_lagged
        """
        ctx = setup_book1_runnable()
        up, down, _ = self._three_scenarios(ctx)
        run_up = validate_success(api.create_simulation_run(
            ctx["book"]["id"], _run_payload(ctx), AN1), 201)
        run_down = validate_success(api.create_simulation_run(
            ctx["book"]["id"],
            create_simulation_run_payload(
                down["id"], ctx["ps"]["id"], ctx["ds"]["id"], ctx["bs"]["id"],
                "STATIC", get_book_version(ctx["book"]["id"])),
            AN1), 201)
        # +200 (up beta 40% on the deposit, no prepay acceleration) and -200
        # (down beta 20%, prepay speeds to 14%) land on the same NII here.
        assert run_up["nii_scenario_cents"] == BOOK1_STATIC_UP200
        assert run_down["nii_scenario_cents"] == BOOK1_STATIC_UP200

    def test_ramp_lagged_pass_through_and_terminal_eve(self, api):
        """PRD §3.4: "when the ramp completes within the first year
        (`ramp_months` not greater than 12), the year-one delta equals
        `ramp_total_bps` multiplied by the quantity twelve minus half of
        `ramp_months`, all divided by twelve". PRD §3.4: "for a `RAMP` it is
        the greater of zero and twelve minus `lag_months`, divided by twelve."
        PRD §3.4: "The economic-value computation always uses the terminal
        shock instead: the effective shock for `PARALLEL_SHOCK` and
        `REGULATORY_PRESET`, and `ramp_total_bps` for a `RAMP`."

        Design: Difficulty/combinatorial_formula/deposit_beta_asymmetric_and_ramp_lagged
        """
        ctx = setup_book1_runnable()
        ramp = create_ramp_scenario(ctx["book"]["id"], 300, 12, "RAMP300")
        run = validate_success(api.create_simulation_run(
            ctx["book"]["id"],
            create_simulation_run_payload(
                ramp["id"], ctx["ps"]["id"], ctx["ds"]["id"], ctx["bs"]["id"],
                "STATIC", get_book_version(ctx["book"]["id"])),
            AN1), 201)
        # Year-1 average delta 150 (half passed through a 6-month beta lag)
        # drives NII; EVE uses the terminal 300.
        assert run["nii_scenario_cents"] == 5_310_000
        assert run["nii_delta_pct"] == pytest.approx(1.14)
        assert run["eve_scenario_cents"] == 18_600_000


class TestPinnedRoundingOrder:
    def _rounding_book(self, api):
        book = create_book("Book R")
        add_position(book["id"], category="LOAN", balance_cents=10_000_050,
                     rate_bps=333, scheduled_runoff_pct=0.0,
                     duration_years=1.0)
        add_position(book["id"], category="LOAN", balance_cents=10_000_050,
                     rate_bps=333, scheduled_runoff_pct=0.0,
                     duration_years=1.0)
        add_position(book["id"], category="DEPOSIT",
                     deposit_segment="RETAIL_NONMATURITY",
                     balance_cents=100_000, rate_bps=10,
                     scheduled_runoff_pct=0.0, duration_years=0.5)
        activate_book(book["id"])
        ps = create_approved_set(book["id"], "PREPAYMENT",
                                 prepayment_params(0.0, 0.0))
        ds = create_approved_set(book["id"], "DEPOSIT_DECAY",
                                 deposit_decay_params(0.0, 0.0))
        bs = create_approved_set(book["id"], "DEPOSIT_BETA",
                                 deposit_beta_params(40.0, 20.0, 6))
        sc = create_shock_scenario(book["id"], 200, "UP200")
        return book, ps, ds, bs, sc

    def test_per_position_rounding_pins_base_value(self, api):
        """PRD §2.6: "Interest and expense amounts are rounded half-up to
        integer cents **per position first**, and only then summed. Unrounded
        per-position values are never summed and rounded once at the end."

        Design: Difficulty/combinatorial_formula/nii_per_position_rounding_order_pinned
        """
        book, ps, ds, bs, sc = self._rounding_book(api)
        run = create_run(book["id"], sc["id"], ps["id"], ds["id"], bs["id"])
        # Each loan rounds 333,001.665c up to 333,002 before summing;
        # sum-then-round would give 666,003.
        assert run["nii_base_cents"] == 665_904

    def test_per_position_rounding_pins_scenario_value(self, api):
        """PRD §2.6: "Interest and expense amounts are rounded half-up to
        integer cents **per position first**, and only then summed." PRD §3.4:
        "the rounding order is pinned and unrounded values are never summed
        first."

        Design: Difficulty/combinatorial_formula/nii_per_position_rounding_order_pinned
        """
        book, ps, ds, bs, sc = self._rounding_book(api)
        run = create_run(book["id"], sc["id"], ps["id"], ds["id"], bs["id"])
        assert run["nii_scenario_cents"] == 665_104


class TestRunCreationGates:
    def test_dynamic_run_missing_growth_rejected(self, api):
        """PRD §3.4: "`annual_growth_pct` is required exactly when the
        convention is `DYNAMIC`, and a `DYNAMIC` run without it is rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/dynamic_run_missing_growth_rejected
        """
        ctx = setup_book1_runnable(with_security_and_borrowing=False)
        payload = create_simulation_run_payload(
            ctx["sc"]["id"], ctx["ps"]["id"], ctx["ds"]["id"], ctx["bs"]["id"],
            "DYNAMIC", get_book_version(ctx["book"]["id"]))
        resp = api.create_simulation_run(ctx["book"]["id"], payload, AN1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_run_create_on_draft_book_rejected(self, api):
        """PRD §3.4: "The book must be `ACTIVE`, else the request is rejected
        with `ERR_BOOK_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/endpoints/run_create_on_draft_book_rejected
        """
        book = create_book()
        add_position(book["id"], category="LOAN", balance_cents=1_000_000,
                     rate_bps=600, scheduled_runoff_pct=20.0,
                     duration_years=3.0)
        add_position(book["id"], category="DEPOSIT",
                     deposit_segment="RETAIL_NONMATURITY",
                     balance_cents=80_000_000, rate_bps=50,
                     scheduled_runoff_pct=0.0, duration_years=0.5)
        sets = setup_book1_approved_sets(book["id"])
        sc = create_shock_scenario(book["id"], 200, "UP200")
        payload = create_simulation_run_payload(
            sc["id"], sets["ps"]["id"], sets["ds"]["id"], sets["bs"]["id"],
            "STATIC", get_book_version(book["id"]))
        resp = api.create_simulation_run(book["id"], payload, AN1)
        validate_error(resp, ApiErrorId.ERR_BOOK_NOT_ACTIVE)
        assert get_book(book["id"])["status"] == "DRAFT"

    def test_scenario_archive_blocks_new_runs(self, api):
        """PRD §3.3: "Once a scenario is `ARCHIVED`, creating a simulation run
        that references it is rejected with `ERR_SCENARIO_NOT_ACTIVE`
        (HTTP 409)."

        Design: Corner/state_machines/scenario_archive_blocks_new_runs
        """
        ctx = setup_book1_runnable(with_security_and_borrowing=False)
        run = create_run(ctx["book"]["id"], ctx["sc"]["id"], ctx["ps"]["id"],
                         ctx["ds"]["id"], ctx["bs"]["id"])
        archived = get_success_data(api.archive_scenario(ctx["sc"]["id"], AN1))
        assert archived["status"] == "ARCHIVED"
        payload = create_simulation_run_payload(
            ctx["sc"]["id"], ctx["ps"]["id"], ctx["ds"]["id"],
            ctx["bs"]["id"], "STATIC", get_book_version(ctx["book"]["id"]))
        resp = api.create_simulation_run(ctx["book"]["id"], payload, AN1)
        validate_error(resp, ApiErrorId.ERR_SCENARIO_NOT_ACTIVE)
        assert get_run(run["id"])["status"] == "COMPLETED", (
            "the pre-existing run is untouched by archiving")


class TestRunRequiresApprovedSets:
    def _setup_submitted_prepay(self, api):
        ctx = setup_book1_active(with_security_and_borrowing=False)
        book_id = ctx["book"]["id"]
        ps = create_assumption_set(book_id, "PREPAYMENT",
                                   prepayment_params(), "an-1")
        submit_assumption_set(ps["id"], "an-1")  # SUBMITTED, never approved
        ds = create_approved_set(book_id, "DEPOSIT_DECAY",
                                 deposit_decay_params())
        bs = create_approved_set(book_id, "DEPOSIT_BETA",
                                 deposit_beta_params())
        sc = create_shock_scenario(book_id, 200, "UP200")
        return ctx, ps, ds, bs, sc

    def test_run_rejected_when_pinned_set_not_approved(self, api):
        """PRD §3.4: "Each pinned set must belong to its matching domain, must
        be `APPROVED` (otherwise `ERR_ASSUMPTION_NOT_APPROVED`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/run_rejected_when_pinned_set_not_approved
        """
        ctx, ps, ds, bs, sc = self._setup_submitted_prepay(api)
        payload = create_simulation_run_payload(
            sc["id"], ps["id"], ds["id"], bs["id"], "STATIC",
            get_book_version(ctx["book"]["id"]))
        resp = api.create_simulation_run(ctx["book"]["id"], payload, AN1)
        validate_error(resp, ApiErrorId.ERR_ASSUMPTION_NOT_APPROVED)

    def test_rejected_run_leaves_no_run_rows(self, api):
        """PRD §3.4: "Each pinned set must belong to its matching domain, must
        be `APPROVED` (otherwise `ERR_ASSUMPTION_NOT_APPROVED`, HTTP 409)".
        PRD §3.4: "Runs can be listed filtered by `book_id`, `scenario_id`,
        `prepayment_set_id`, `decay_set_id`, `beta_set_id`, and `status`."

        Design: Difficulty/cross_entity_state_dependency/run_rejected_when_pinned_set_not_approved
        """
        ctx, ps, ds, bs, sc = self._setup_submitted_prepay(api)
        payload = create_simulation_run_payload(
            sc["id"], ps["id"], ds["id"], bs["id"], "STATIC",
            get_book_version(ctx["book"]["id"]))
        validate_error(api.create_simulation_run(ctx["book"]["id"], payload,
                                                 AN1),
                       ApiErrorId.ERR_ASSUMPTION_NOT_APPROVED)
        data, meta = validate_paginated(api.list_simulation_runs(
            AN1, params={"book_id": ctx["book"]["id"]}))
        assert data == [] and meta["total_count"] == 0, (
            "a rejected run creation must not persist a SimulationRun")


class TestRunBlockedByOpenBreachReview:
    def test_assumption_under_review_blocks_run(self, api):
        """PRD §3.7: "A `BREACH` outcome raises the set's `governance_flag` to
        `REVIEW_REQUIRED`, and while any `BREACH` review remains `OPEN` for a
        set, simulation-run creation pinning that set is rejected with
        `ERR_ASSUMPTION_UNDER_REVIEW` (HTTP 409)". PRD §3.7: "When a closure
        leaves no other `OPEN` review referencing the same set, the set's
        `governance_flag` returns to `NONE`."

        Design: Corner/validations/assumption_under_review_blocks_run
        """
        ctx = setup_book1_runnable(with_security_and_borrowing=False)
        book_id = ctx["book"]["id"]
        get_success_data(api.set_clock("2026-11-01T00:00:00Z", MV1))
        rev = get_success_data(api.create_backtest(
            book_id,
            {"assumption_set_id": ctx["ps"]["id"], "start_month": "2026-08",
             "observation_months": 3, "observed_value_pct": 14.0},
            MV1), 201)
        assert rev["outcome"] == "BREACH"  # deviation 4.0 > 3.0 tolerance
        bv = get_book_version(book_id)
        payload = create_simulation_run_payload(
            ctx["sc"]["id"], ctx["ps"]["id"], ctx["ds"]["id"],
            ctx["bs"]["id"], "STATIC", bv)
        resp = api.create_simulation_run(book_id, payload, AN1)
        validate_error(resp, ApiErrorId.ERR_ASSUMPTION_UNDER_REVIEW)

        closed = get_success_data(api.close_backtest(
            rev["id"], {"outcome": "CLOSED_ACCEPTED"}, CH1))
        assert closed["status"] == "CLOSED_ACCEPTED"
        ps_after = validate_success(
            api.get_assumption_set(ctx["ps"]["id"], AN1))
        assert ps_after["governance_flag"] == "NONE", (
            "closing the only OPEN review clears the governance flag")
        run = validate_success(api.create_simulation_run(book_id, payload,
                                                         AN1), 201)
        assert run["status"] == "COMPLETED"


class TestRunOcc:
    def test_occ_run_create_stale_book_version_rejected(self, api):
        """PRD §2.7: "Because position creation, position patching, position
        retirement, book activation, and simulation-run creation each advance
        the book's `version`, a client whose observed version no longer
        matches the book's current `version` is modeling a balance sheet that
        has since changed; the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and the client must re-read the book and resubmit with the
        fresh version." PRD §3.4: "snapshots the book's `version` at creation
        into `book_version_pinned`".

        Design: Corner/cross_cutting_complexity_layers/occ_run_create_stale_book_version_rejected
        """
        ctx = setup_book1_runnable(with_security_and_borrowing=False)
        book_id = ctx["book"]["id"]
        bv = get_book_version(book_id)
        # A position patch advances the book version, staling bv.
        get_success_data(api.patch_position(
            ctx["l1"]["id"], {"expected_book_version": bv, "rate_bps": 610},
            AN1))
        resp = api.create_simulation_run(
            book_id,
            create_simulation_run_payload(
                ctx["sc"]["id"], ctx["ps"]["id"], ctx["ds"]["id"],
                ctx["bs"]["id"], "STATIC", bv),
            AN1)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        bv2 = get_book_version(book_id)
        run = validate_success(api.create_simulation_run(
            book_id,
            create_simulation_run_payload(
                ctx["sc"]["id"], ctx["ps"]["id"], ctx["ds"]["id"],
                ctx["bs"]["id"], "STATIC", bv2),
            AN1), 201)
        assert run["status"] == "COMPLETED"
        assert run["book_version_pinned"] == bv2


class TestPublication:
    def test_publish_run_twice_rejected(self, api):
        """PRD §3.4: "Publishing moves a run `COMPLETED → PUBLISHED`." — no
        transition out of `PUBLISHED` exists, so a second publish is a state
        error. PRD §3.8: "`run_count` is the number of `PUBLISHED` simulation
        runs of the book in the period."

        Design: Corner/state_machines/publish_run_twice_rejected
        """
        ctx = setup_book1_runnable(with_security_and_borrowing=False)
        run = create_run(ctx["book"]["id"], ctx["sc"]["id"], ctx["ps"]["id"],
                         ctx["ds"]["id"], ctx["bs"]["id"])
        publish_run(run["id"])
        resp = api.publish_simulation_run(run["id"], AN1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        reports = get_success_data(
            api.list_alco_reports(ctx["book"]["id"], AN1))
        assert len(reports) == 1
        assert reports[0]["status"] == "DRAFT"
        assert reports[0]["run_count"] == 1, (
            "the failed re-publish must not double-count the run")

    def test_publish_upserts_period_report(self, api):
        """PRD §3.4: "Publication upserts the period ALCO report for the run's
        book and `period_month` — creating it in `DRAFT` when absent — and
        recomputes its aggregates". PRD §3.8: "`worst_nii_delta_pct` and
        `worst_eve_delta_pct` are the minimum `nii_delta_pct` and
        `eve_delta_pct` over those runs". PRD §3.8:
        "`regulatory_coverage_complete` is true exactly when each of the six
        `preset_code` values has at least one `PUBLISHED` run in the period."

        Design: Corner/endpoints/publish_upserts_period_report
        """
        ctx = setup_book1_runnable()
        run = create_run(ctx["book"]["id"], ctx["sc"]["id"], ctx["ps"]["id"],
                         ctx["ds"]["id"], ctx["bs"]["id"])
        publish_run(run["id"])
        reports = get_success_data(
            api.list_alco_reports(ctx["book"]["id"], AN1))
        assert len(reports) == 1, "publish auto-creates the absent report"
        report = reports[0]
        assert report["status"] == "DRAFT"
        assert report["period_month"] == "2026-08"
        assert report["run_count"] == 1
        assert report["worst_nii_delta_pct"] == pytest.approx(-4.57)
        assert report["worst_eve_delta_pct"] == pytest.approx(-25.33)
        assert report["regulatory_coverage_complete"] is False


class TestInlineComputation:
    def test_run_response_computes_inline_immediate(self, api):
        """PRD §3.4: "The run is computed synchronously and lands in
        `COMPLETED` status. The server records `period_month` as the logical
        clock's `YYYY-MM` at creation, snapshots the book's `version` at
        creation into `book_version_pinned`, and increments the book's
        `version` by one." PRD §2.2: "Unless otherwise noted, operations that
        create or modify a resource will return the created or updated
        resource object in the data field."

        Design: Corner/consistency_model/run_response_computes_inline_immediate
        """
        ctx = setup_book1_runnable()
        create_policy_limit(ctx["book"]["id"], "EVE_DELTA_PCT", 12.0)
        payload = _run_payload(ctx, "STATIC")
        resp = api.create_simulation_run(ctx["book"]["id"], payload, AN1)
        run = validate_success(resp, 201)
        # Every computed field is already on the create response.
        assert run["status"] == "COMPLETED"
        assert run["nii_base_cents"] == 5_250_000
        assert run["nii_scenario_cents"] == 5_010_000
        assert run["nii_delta_pct"] == pytest.approx(-4.57)
        assert run["eve_base_cents"] == 30_000_000
        assert run["eve_scenario_cents"] == 22_400_000
        assert run["eve_delta_pct"] == pytest.approx(-25.33)
        assert run["breach_summary"] == "EVE"
        assert run["assumption_stale"] is False
        assert run["period_month"] == "2026-08"
