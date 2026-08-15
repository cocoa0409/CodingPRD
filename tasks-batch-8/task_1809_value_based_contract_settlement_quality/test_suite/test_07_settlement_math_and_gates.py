"""Settlement computation chain: MSR/MLR gates, caps, corridor, stale gate."""
from test_helpers import (
    ADMIN, CLAIMS, ApiErrorId, CLOCK_FINALIZE, CLOCK_RECONCILE,
    CLOCK_WINDOW_PAST, OFFICER, assert_settlement_chain, begin_measurement,
    build_pipeline, canonical_two_member_journey, create_claim_payload,
    get_settlement, get_year, lock_year_attribution, make_locked_run,
    recalculate_settlement, set_clock, setup_org, single_member_journey,
    validate_error, validate_success,
)



def test_shared_savings_cap_binds_over_rate_share(api):
    """PRD §3.10: "The gross, stored on `gross_savings_cents`, is `benchmark_cost_cents` minus `actual_cost_cents` and may be negative."
    PRD §3.10: "When gross is non-negative, the savings branch applies: if `savings_rate_bp` is greater than or equal to the contract's `min_savings_rate_bp`, the uncapped shared savings is the round-half-up of gross multiplied by `shared_savings_rate_bp` and divided by 10000, and the cap is the round-half-up of `benchmark_cost_cents` multiplied by `savings_cap_bp` and divided by 10000; `shared_savings_cents` is the lesser of the two, with the minimum applied **after** both sides have been rounded."

    Design: Difficulty/combinatorial_formula/shared_savings_cap_corridor_nested_branches
    """
    pipe = canonical_two_member_journey(stage="SETTLEMENT")
    settlement = pipe["settlement"]
    assert_settlement_chain(
        settlement,
        gross_savings_cents=700000,       # 1,800,000 benchmark - 1,100,000 actual
        savings_rate_bp=3888,             # trunc(700000*10000/1800000)
        shared_savings_cents=180000,      # min(350000 uncapped, 180000 cap)
        shared_losses_cents=0,            # loss branch inert on non-negative gross
    )


def test_shared_savings_full_chain_to_net_payable(api):
    """PRD §3.10: "Fifth, `quality_adjusted_savings_cents` is the round-half-up of `shared_savings_cents` multiplied by `quality_multiplier_bp` and divided by 10000. Sixth, `withhold_released_cents` is the round-half-up of `withhold_pool_cents` multiplied by `quality_multiplier_bp` and divided by 10000, and `withhold_forfeited_cents` is `withhold_pool_cents` minus `withhold_released_cents`. Seventh, `net_payable_cents` is `quality_adjusted_savings_cents` plus `withhold_released_cents` minus `shared_losses_cents` and may be negative."
    PRD §3.10: "If the composite is greater than or equal to the `quality_gate_floor_points` but below excellence, the multiplier is 5000 plus the round-half-up of the composite-minus-floor, multiplied by 5000, divided by the excellence-minus-floor gap."

    Design: Difficulty/combinatorial_formula/shared_savings_cap_corridor_nested_branches
    """
    pipe = canonical_two_member_journey(stage="SETTLEMENT")
    settlement = pipe["settlement"]
    assert_settlement_chain(
        settlement,
        quality_composite_points=30,      # 3 pts (w9000) + 0 pts (w1000)
        quality_multiplier_bp=5000,       # composite == floor -> sliding base
        quality_adjusted_savings_cents=90000,
        withhold_released_cents=27500,    # pool 55,000 x 5000 bp
        withhold_forfeited_cents=27500,
        net_payable_cents=117500,
    )


def test_msr_exact_threshold_qualifies_for_shared_savings(api):
    """PRD §3.3: "`min_savings_rate_bp` is the minimum savings rate (MSR) in basis points of benchmark that must be reached before any shared savings are paid; the comparison is greater-than-or-equal."
    PRD §3.10: "When gross is non-negative, the savings branch applies: if `savings_rate_bp` is greater than or equal to the contract's `min_savings_rate_bp`, the uncapped shared savings is the round-half-up of gross multiplied by `shared_savings_rate_bp` and divided by 10000, and the cap is the round-half-up of `benchmark_cost_cents` multiplied by `savings_cap_bp` and divided by 10000; `shared_savings_cents` is the lesser of the two, with the minimum applied **after** both sides have been rounded."

    Design: Difficulty/boundary_precision_check/msr_exact_threshold_qualifies_for_shared_savings
    """
    pipe = canonical_two_member_journey(
        stage="SETTLEMENT",
        claim_amounts=[("2026-03-10", 1064000, 0), ("2026-09-05", 700000, 1)],
    )
    settlement = pipe["settlement"]
    # gross = 36,000 -> rate = trunc(36000*10000/1800000) = 200 == MSR -> qualifies
    assert_settlement_chain(
        settlement,
        savings_rate_bp=200,
        shared_savings_cents=18000,       # round(36000*0.5); cap 180,000 does not bind
        quality_adjusted_savings_cents=9000,
        withhold_released_cents=44100,    # pool 88,200 x 5000 bp
        net_payable_cents=53100,
    )


def test_one_cent_more_claims_drops_below_msr(api):
    """PRD §3.3: "`min_savings_rate_bp` is the minimum savings rate (MSR) in basis points of benchmark that must be reached before any shared savings are paid; the comparison is greater-than-or-equal."
    PRD §3.10: "If the rate falls below the MSR, `shared_savings_cents` is zero."

    Design: Difficulty/boundary_precision_check/msr_exact_threshold_qualifies_for_shared_savings
    """
    pipe = canonical_two_member_journey(
        stage="SETTLEMENT",
        claim_amounts=[("2026-03-10", 1064001, 0), ("2026-09-05", 700000, 1)],
    )
    settlement = pipe["settlement"]
    # gross = 35,999 -> rate = trunc(199.99) = 199 < MSR -> zero sharing
    assert settlement["savings_rate_bp"] == 199
    assert settlement["shared_savings_cents"] == 0
    assert settlement["quality_adjusted_savings_cents"] == 0
    # pool: round(1064001*0.05) = 53200 + 35000 = 88200; released 44100
    assert settlement["withhold_released_cents"] == 44100
    assert settlement["net_payable_cents"] == 44100


def test_state_beats_temporal_on_authorize_distribution(api, settlement_officer_headers):
    """PRD §2.8: "Every request traverses a fixed priority cascade; the first failing rule wins and produces the response. Lower-priority checks are not evaluated once a higher-priority check has failed."
    PRD §2.8: "6. **State preconditions** — the target resource is in a from-state of the invoked transition; failures produce `ERR_INVALID_STATE_TRANSITION` or one of the more specific state-family errors listed in §5 (all 409)."
    PRD §3.10: "If no dispute is filed inside the dispute window, an officer may authorize distribution (`FINALIZED → AUTHORIZED`) once the logical clock date is strictly greater than `finalized_on` plus the dispute window (`ERR_DISPUTE_WINDOW_OPEN`); §3.12 covers the remittance waterfall this triggers."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_authorize_distribution
    """
    pipe = single_member_journey(stage="SETTLEMENT")
    settlement = pipe["settlement"]
    set_clock("2027-01-10T00:00:00Z")
    resp = api.authorize_distribution(settlement["id"], settlement_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    reread = get_settlement(settlement["id"])
    assert reread["settlement_status"] == "PROVISIONAL"


def test_state_gate_on_authorize_independent_of_clock(api, settlement_officer_headers):
    """PRD §2.8: "Every request traverses a fixed priority cascade; the first failing rule wins and produces the response. Lower-priority checks are not evaluated once a higher-priority check has failed."
    PRD §2.8: "6. **State preconditions** — the target resource is in a from-state of the invoked transition; failures produce `ERR_INVALID_STATE_TRANSITION` or one of the more specific state-family errors listed in §5 (all 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_authorize_distribution
    """
    pipe = single_member_journey(stage="SETTLEMENT")
    settlement = pipe["settlement"]
    # Even with the clock far past any dispute window, a PROVISIONAL settlement
    # fails the state precondition before any temporal check is consulted.
    set_clock(CLOCK_WINDOW_PAST)
    resp = api.authorize_distribution(settlement["id"], settlement_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_settlement(settlement["id"])["settlement_status"] == "PROVISIONAL"


def test_temporal_beats_fiscal_on_claim_create(api, claims_processor_headers):
    """PRD §2.8: "Every request traverses a fixed priority cascade; the first failing rule wins and produces the response. Lower-priority checks are not evaluated once a higher-priority check has failed."
    PRD §2.8: "8. **Temporal and window rules** — dispute filing within the dispute window (`ERR_DISPUTE_WINDOW_CLOSED`), mark-settled and authorize-distribution only after the dispute window (`ERR_DISPUTE_WINDOW_OPEN`), dispute resolve within the resolution window (`ERR_DISPUTE_RESOLUTION_WINDOW_ELAPSED`), dispute expire only after it (`ERR_DISPUTE_NOT_EXPIRABLE`), begin-reconciliation at or after `period_end` (`ERR_MEASUREMENT_PERIOD_NOT_ENDED`), settlement finalize at or after `period_end` plus the reconciliation runout (`ERR_RECONCILIATION_RUNOUT_INCOMPLETE`), year window contained in the contract term (`ERR_YEAR_OUTSIDE_TERM`), claim `service_date` inside the year window (`ERR_CLAIM_OUTSIDE_PERIOD`). All 409."
    PRD §2.8: "12. **Fiscal and rate sanity** — `benchmark_pmpm_cents` strictly positive; all basis-point rates in 0..10000 inclusive; a `TWO_SIDED` contract must carry `shared_loss_rate_bp` and `loss_cap_bp`; `quality_gate_floor_points` strictly less than `quality_gate_excellence_points` with both in 0..100; every entry in `quality_measures` has a positive weight and exactly 9 strictly ascending decile thresholds. Violations of this family produce `ERR_INVALID_RATE_CONFIG` (422). `paid_amount_cents` and `claimed_adjustment_cents` must be strictly positive (`ERR_INVALID_AMOUNT`, 422). Start dates must be strictly before end dates on span, contract, and year creation (`ERR_INVALID_DATE_RANGE`, 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_claim_create
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(org, stage="SETUP")
    year_id = pipe["year"]["id"]
    member_id = org["members"][0]["id"]

    both_bad = api.create_claim(
        create_claim_payload(
            year_id, member_id, claim_ref="CL-X",
            service_date="2025-12-31", paid_amount_cents=-5,
        ),
        claims_processor_headers,
    )
    err = validate_error(both_bad, ApiErrorId.ERR_CLAIM_OUTSIDE_PERIOD)
    assert err["error_id"] != "ERR_INVALID_AMOUNT"


def test_claim_temporal_and_fiscal_failures_isolated(api, claims_processor_headers):
    """PRD §3.7: "The `service_date` must lie on or after the year's `period_start` and strictly before its `period_end` (`ERR_CLAIM_OUTSIDE_PERIOD`)."
    PRD §2.8: "12. **Fiscal and rate sanity** — `benchmark_pmpm_cents` strictly positive; all basis-point rates in 0..10000 inclusive; a `TWO_SIDED` contract must carry `shared_loss_rate_bp` and `loss_cap_bp`; `quality_gate_floor_points` strictly less than `quality_gate_excellence_points` with both in 0..100; every entry in `quality_measures` has a positive weight and exactly 9 strictly ascending decile thresholds. Violations of this family produce `ERR_INVALID_RATE_CONFIG` (422). `paid_amount_cents` and `claimed_adjustment_cents` must be strictly positive (`ERR_INVALID_AMOUNT`, 422). Start dates must be strictly before end dates on span, contract, and year creation (`ERR_INVALID_DATE_RANGE`, 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_claim_create
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(org, stage="SETUP")
    year_id = pipe["year"]["id"]
    member_id = org["members"][0]["id"]

    outside_only = api.create_claim(
        create_claim_payload(
            year_id, member_id, claim_ref="CL-T",
            service_date="2025-12-31", paid_amount_cents=1000,
        ),
        claims_processor_headers,
    )
    validate_error(outside_only, ApiErrorId.ERR_CLAIM_OUTSIDE_PERIOD)

    negative_only = api.create_claim(
        create_claim_payload(
            year_id, member_id, claim_ref="CL-F",
            service_date="2026-03-10", paid_amount_cents=-5,
        ),
        claims_processor_headers,
    )
    validate_error(negative_only, ApiErrorId.ERR_INVALID_AMOUNT)


def test_corridor_between_msr_and_mlr_zero_sharing(api):
    """PRD §3.10: "Between the MSR and the negative MLR lies the zero corridor in which neither savings nor losses are paid."
    PRD §3.10: "If the rate falls below the MSR, `shared_savings_cents` is zero. `shared_losses_cents` is zero on this branch."

    Design: Corner/calculations/corridor_between_msr_and_mlr_zero_sharing
    """
    pipe = canonical_two_member_journey(
        stage="SETTLEMENT",
        claim_amounts=[("2026-03-10", 1073000, 0), ("2026-09-05", 700000, 1)],
    )
    settlement = pipe["settlement"]
    assert_settlement_chain(
        settlement,
        gross_savings_cents=27000,
        savings_rate_bp=150,              # corridor: below MSR 200, above -MLR
        shared_savings_cents=0,
        shared_losses_cents=0,
        withhold_released_cents=44325,    # pool 88,650 x 5000 bp
        net_payable_cents=44325,
    )


def test_two_sided_loss_breach_applies_mlr_and_cap(api):
    """PRD §3.10: "When gross is negative, the loss branch applies and `shared_savings_cents` is zero; if the contract's `risk_track` is `TWO_SIDED` and the `savings_rate_bp` is less than or equal to the negation of the contract's `min_loss_rate_bp`, the uncapped shared loss is the round-half-up of the absolute gross multiplied by `shared_loss_rate_bp` and divided by 10000, the cap is the round-half-up of `benchmark_cost_cents` multiplied by `loss_cap_bp` and divided by 10000, and `shared_losses_cents` is the lesser of the two. Otherwise `shared_losses_cents` is zero."
    PRD §3.10: "Seventh, `net_payable_cents` is `quality_adjusted_savings_cents` plus `withhold_released_cents` minus `shared_losses_cents` and may be negative."

    Design: Corner/calculations/two_sided_loss_breach_applies_mlr_and_cap
    """
    pipe = canonical_two_member_journey(
        stage="SETTLEMENT",
        claim_amounts=[("2026-03-10", 1850000, 0)],
    )
    settlement = pipe["settlement"]
    assert_settlement_chain(
        settlement,
        gross_savings_cents=-50000,
        savings_rate_bp=-277,             # trunc toward zero of -277.77
        shared_savings_cents=0,
        shared_losses_cents=20000,        # min(50000 x 4000bp, 1800000 x 800bp)
        withhold_released_cents=46250,    # pool 92,500 x 5000 bp
        net_payable_cents=26250,
    )


def test_one_sided_contract_never_shares_losses(api):
    """PRD §3.10: "When gross is negative, the loss branch applies and `shared_savings_cents` is zero; if the contract's `risk_track` is `TWO_SIDED` and the `savings_rate_bp` is less than or equal to the negation of the contract's `min_loss_rate_bp`, the uncapped shared loss is the round-half-up of the absolute gross multiplied by `shared_loss_rate_bp` and divided by 10000, the cap is the round-half-up of `benchmark_cost_cents` multiplied by `loss_cap_bp` and divided by 10000, and `shared_losses_cents` is the lesser of the two. Otherwise `shared_losses_cents` is zero."
    PRD §3.3: "The `risk_track` is either `ONE_SIDED_UPSIDE` or `TWO_SIDED`."

    Design: Corner/calculations/one_sided_contract_never_shares_losses
    """
    pipe = canonical_two_member_journey(
        stage="SETTLEMENT",
        claim_amounts=[("2026-03-10", 1850000, 0)],
        contract_overrides={"risk_track": "ONE_SIDED_UPSIDE"},
        contract_drop_fields=("shared_loss_rate_bp", "loss_cap_bp", "min_loss_rate_bp"),
    )
    settlement = pipe["settlement"]
    assert settlement["savings_rate_bp"] == -277
    assert settlement["shared_losses_cents"] == 0, (
        "ONE_SIDED_UPSIDE suppresses the loss branch at the same rate"
    )
    assert settlement["net_payable_cents"] == 46250  # withhold release only


def test_empty_population_begin_reconciliation_rejected(api, payer_admin_headers):
    """PRD §3.4: "From `MEASURING` the admin begins reconciliation (`MEASURING → RECONCILING`); this is gated by three preconditions evaluated together — the logical clock date must be at or after `period_end` (`ERR_MEASUREMENT_PERIOD_NOT_ENDED`), the year's `total_member_months` must be strictly positive (`ERR_EMPTY_POPULATION`), and every `QualityMeasureResult` of the year must be in either `LOCKED` or `EXCLUDED` (`ERR_QUALITY_RESULTS_UNLOCKED`)."

    Design: Corner/validations/empty_population_begin_reconciliation_rejected
    """
    org = setup_org(member_specs=[], practice_count=1)
    pipe = build_pipeline(org, stage="OPEN", attributions=[])
    year_id = pipe["year"]["id"]

    run, records = make_locked_run(year_id, [])
    assert records == []
    assert run["attributed_member_count"] == 0
    year = lock_year_attribution(year_id)
    assert year["total_member_months"] == 0
    assert year["benchmark_cost_cents"] == 0
    begin_measurement(year_id)

    set_clock(CLOCK_RECONCILE)
    resp = api.begin_reconciliation(year_id, payer_admin_headers)
    validate_error(resp, ApiErrorId.ERR_EMPTY_POPULATION)


def test_settlement_exists_second_create_rejected(api, settlement_officer_headers):
    """PRD §3.10: "Once the year is in `RECONCILING`, a `SettlementOfficer` creates a `Settlement` against it by supplying the `performance_year_id`. Creating a settlement against a year not in `RECONCILING` is rejected with `ERR_YEAR_NOT_RECONCILING`. At most one non-`VOID` settlement exists per year (`ERR_SETTLEMENT_EXISTS`). The settlement's `settlement_status` is created as `PROVISIONAL`, and the settlement is assigned `settlement_seq` starting at 1 for the first non-`VOID` settlement of the year."
    PRD §3.4: "The reopen performs a coordinated reset: the currently `LOCKED` attribution run is moved to `SUPERSEDED` (a `LOCKED → SUPERSEDED` transition on the run), the year's `locked_run_id` is cleared to null, the `PROVISIONAL` settlement is moved to `VOID` (a `PROVISIONAL → VOID` transition on the settlement), and the rollups are zeroed — `total_member_months` to 0, `benchmark_cost_cents` to 0, `risk_adjustment_factor_milli` to null, `actual_cost_cents` to 0, and `withhold_pool_cents` to 0."

    Design: Corner/validations/settlement_exists_second_create_rejected
    """
    pipe = single_member_journey(stage="SETTLEMENT")
    year_id = pipe["year"]["id"]
    s1 = pipe["settlement"]
    assert s1["settlement_seq"] == 1, "the first non-VOID settlement starts the sequence"

    dup = api.create_settlement({"performance_year_id": year_id}, settlement_officer_headers)
    validate_error(dup, ApiErrorId.ERR_SETTLEMENT_EXISTS)

    # Reopening voids the PROVISIONAL settlement; after re-running the
    # attribution pipeline a fresh settlement can be created.
    validate_success(api.reopen_attribution(year_id, ADMIN))
    assert get_settlement(s1["id"])["settlement_status"] == "VOID"
    run, _records = make_locked_run(
        year_id, [(pipe["members"][0]["id"], pipe["practices"][0]["id"])]
    )
    lock_year_attribution(year_id)
    begin_measurement(year_id)
    set_clock(CLOCK_RECONCILE)
    validate_success(api.begin_reconciliation(year_id, ADMIN))
    s2 = validate_success(
        api.create_settlement({"performance_year_id": year_id}, settlement_officer_headers), 201
    )
    assert s2["settlement_status"] == "PROVISIONAL"
    assert s2["id"] != s1["id"]


def test_stale_settlement_finalize_rejected_then_recalculated(api):
    """PRD §3.10: "Finalization (`PROVISIONAL → FINALIZED`) is performed by a `SettlementOfficer` and is gated by two preconditions: the logical clock date must be at or after the year's `period_end` plus the reconciliation runout (`ERR_RECONCILIATION_RUNOUT_INCOMPLETE`), and `needs_recompute` must be `false` (`ERR_SETTLEMENT_STALE` while it is true)."
    PRD §3.10: "A `PROVISIONAL` settlement whose `needs_recompute` is true can be brought current via the recalculate action, which performs a full recompute against current data, clears `needs_recompute` to `false`, and leaves the settlement in `PROVISIONAL` with `settlement_seq` unchanged. Recalculate is the only way to clear the flag; finalize refuses to run while it is set."

    Design: Corner/errors/stale_settlement_finalize_rejected_then_recalculated
    """
    pipe = single_member_journey(
        stage="SETTLEMENT",
        claim_amounts=[("2026-03-10", 400000), ("2026-04-10", 100000)],
    )
    settlement = pipe["settlement"]
    # Two-claim baseline: actual 500,000, pool 25,000 -> shared 120,000 (cap),
    # adjusted 63,600, released 13,250 -> net 76,850.
    assert_settlement_chain(settlement, net_payable_cents=76850)

    # Voiding the second claim flags the settlement for recompute.
    validate_success(api.void_claim(pipe["claims"][1]["id"], CLAIMS))
    assert get_settlement(settlement["id"])["needs_recompute"] is True

    set_clock(CLOCK_FINALIZE)
    stale = api.finalize_settlement(settlement["id"], OFFICER)
    validate_error(stale, ApiErrorId.ERR_SETTLEMENT_STALE)

    recalced = recalculate_settlement(settlement["id"])
    assert recalced["needs_recompute"] is False
    assert recalced["settlement_status"] == "PROVISIONAL"
    assert_settlement_chain(recalced, net_payable_cents=74200)

    finalized = api.finalize_settlement(settlement["id"], OFFICER)
    assert validate_success(finalized)["settlement_status"] == "FINALIZED"
