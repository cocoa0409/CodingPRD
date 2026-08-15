"""Claims, stop-loss cost measurement, per-claim withhold rounding, cascades."""
from test_helpers import (
    ACTUARY, CLAIMS, CLOCK_LATE_PAID, CLOCK_MAR,
    INTERIM_RESERVE_ACCRUAL_CENTS, ApiErrorId, begin_measurement,
    build_pipeline, get_settlement, get_year, make_claim, make_contract,
    make_year, recalculate_settlement, set_clock, setup_org,
    single_member_journey, validate_error, validate_success,
)


def test_withhold_pool_per_claim_rounding_order(api):
    """PRD §3.7: "For each claim in the set, the per-claim withhold is the claim's `paid_amount_cents` multiplied by the contract's `withhold_rate_bp` and divided by 10000, rounded half-up to a whole cent. The year's `withhold_pool_cents` is the sum of these per-claim amounts. Rounding is pinned at the per-claim level; sum-then-round is forbidden."

    Design: Difficulty/combinatorial_formula/withhold_pool_per_claim_rounding_order
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(
        org, stage="ATTRIBUTION_LOCKED",
        claim_specs=[
            {"member": 0, "ref": "CL-1", "service_date": "2026-03-10", "amount": 10},
            {"member": 0, "ref": "CL-2", "service_date": "2026-04-10", "amount": 10},
            {"member": 0, "ref": "CL-3", "service_date": "2026-05-10", "amount": 10},
        ],
    )
    year = begin_measurement(pipe["year"]["id"])
    # round_half_up(10 * 500 / 10000) = round_half_up(0.5) = 1 per claim, x3 = 3;
    # the forbidden sum-then-round order would give round_half_up(30 * 0.05) = 2.
    assert year["withhold_pool_cents"] == 3
    assert year["actual_cost_cents"] == 30


def test_withhold_pool_conserved_into_settlement(api):
    """PRD §3.7: "Rounding is pinned at the per-claim level; sum-then-round is forbidden."
    PRD §3.10: "Sixth, `withhold_released_cents` is the round-half-up of `withhold_pool_cents` multiplied by `quality_multiplier_bp` and divided by 10000, and `withhold_forfeited_cents` is `withhold_pool_cents` minus `withhold_released_cents`."

    Design: Difficulty/combinatorial_formula/withhold_pool_per_claim_rounding_order
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(
        org, stage="SETTLEMENT",
        claim_specs=[
            {"member": 0, "ref": "CL-1", "service_date": "2026-03-10", "amount": 10},
            {"member": 0, "ref": "CL-2", "service_date": "2026-04-10", "amount": 10},
            {"member": 0, "ref": "CL-3", "service_date": "2026-05-10", "amount": 10},
        ],
        quality_specs=[("HBA1C", 350, 1000)],
        contract_overrides={"quality_measures": [
            {"measure_code": "HBA1C", "weight_bp": 10000,
             "decile_thresholds_bp": [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000]}
        ]},
    )
    settlement = pipe["settlement"]
    assert get_year(pipe["year"]["id"])["withhold_pool_cents"] == 3
    # composite 33 -> multiplier 5300: released = round_half_up(3 * 0.53) = 2, forfeited = 1
    assert settlement["withhold_released_cents"] == 2
    assert settlement["withhold_forfeited_cents"] == 1
    assert settlement["withhold_released_cents"] + settlement["withhold_forfeited_cents"] == 3


def test_claim_void_cascade_depth3(api):
    """PRD §3.7: "A claim void triggers the same three-link cascade — recompute the two year totals, stale the published interim reports, and flag the settlement."
    PRD §2.10: "Whenever the year's `actual_cost_cents`, `withhold_pool_cents`, or the underlying population rollups mutate — through claim mark-paid or void, attribution exclude or reinstate, or risk-score finalize or supersede — every `PUBLISHED` `InterimReport` of the year transitions to `STALE`."

    Design: Difficulty/transitive_cascade/claim_void_cascade_depth3
    """
    pipe = single_member_journey(
        stage="SETTLEMENT",
        claim_amounts=[("2026-02-10", 400000), ("2026-03-20", 100000)],
        interim_months=6,
    )
    # Re-drive the per-claim pay clocks of the recipe: CL-1 paid in March,
    # CL-2 paid in April (both paid_on values precede the July report).
    year_id = pipe["year"]["id"]
    report_id = pipe["report"]["id"]
    settlement_id = pipe["settlement"]["id"]
    cl2 = pipe["claims"][1]

    validate_success(api.void_claim(cl2["id"], CLAIMS))

    year = get_year(year_id)
    assert year["actual_cost_cents"] == 400000, "voided claim removed from actual cost"
    assert year["withhold_pool_cents"] == 20000

    report = validate_success(api.get_interim_report(report_id, ACTUARY))
    assert report["report_status"] == "STALE"

    settlement = get_settlement(settlement_id)
    assert settlement["needs_recompute"] is True
    assert settlement["settlement_status"] == "PROVISIONAL"


def test_claim_void_keeps_stale_amounts_and_reserve(api):
    """PRD §2.10: "The year's `accrued_reserve_cents` is not retroactively adjusted by this transition; it remains at the value posted by the most recently published report until a newer report is published or the year settles."
    PRD §3.10: "A `PROVISIONAL` settlement whose `needs_recompute` is true can be brought current via the recalculate action, which performs a full recompute against current data, clears `needs_recompute` to `false`, and leaves the settlement in `PROVISIONAL` with `settlement_seq` unchanged."

    Design: Difficulty/transitive_cascade/claim_void_cascade_depth3
    """
    pipe = single_member_journey(
        stage="SETTLEMENT",
        claim_amounts=[("2026-02-10", 400000), ("2026-03-20", 100000)],
        interim_months=6,
    )
    year_id = pipe["year"]["id"]
    settlement_id = pipe["settlement"]["id"]
    cl2 = pipe["claims"][1]
    assert pipe["settlement"]["net_payable_cents"] == 76850  # two-claim baseline

    validate_success(api.void_claim(cl2["id"], CLAIMS))

    settlement = get_settlement(settlement_id)
    assert settlement["settlement_status"] == "PROVISIONAL"
    assert settlement["needs_recompute"] is True
    assert settlement["net_payable_cents"] == 76850, (
        "amounts stay stale until recalculate is called"
    )
    year = get_year(year_id)
    assert year["accrued_reserve_cents"] == INTERIM_RESERVE_ACCRUAL_CENTS, (
        "staleness never retroactively adjusts the posted reserve"
    )

    recalced = recalculate_settlement(settlement_id)
    assert recalced["needs_recompute"] is False
    # After the void: actual 400000, pool 20000 -> shared 120000 (cap) x 5300 bp
    # = 63600, released 10600 -> net 74200.
    assert recalced["net_payable_cents"] == 74200


def test_stop_loss_truncates_member_cost_but_not_withhold(api):
    """PRD §3.7: "For each attributed member, the allowed cost is the lesser of the sum of that member's `paid_amount_cents` over the input set and the contract's `stop_loss_cents`."
    PRD §3.7: "The withhold pool is computed over the same claim set, evaluated **before** stop-loss truncation."

    Design: Corner/calculations/stop_loss_truncates_member_cost_but_not_withhold
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(
        org, stage="ATTRIBUTION_LOCKED",
        claim_specs=[{"member": 0, "ref": "CL-1", "service_date": "2026-03-10", "amount": 3500000}],
    )
    year = begin_measurement(pipe["year"]["id"])
    assert year["actual_cost_cents"] == 2000000, "claim truncated at the 2,000,000 stop-loss"
    assert year["withhold_pool_cents"] == 175000, (
        "withhold computed pre-truncation: round_half_up(3,500,000 x 500/10000)"
    )


def test_claim_void_from_denied_rejected(api, claims_processor_headers):
    """PRD §3.7: "From `RECEIVED` the processor may mark it paid (`RECEIVED → PAID`), which stamps `paid_on` with the logical clock date, or deny it (`RECEIVED → DENIED`). From `PAID` the processor may void it (`PAID → VOIDED`) provided the year is not in `SETTLED` or `CLOSED` (`ERR_YEAR_LOCKED`)."
    PRD §2.8: "6. **State preconditions** — the target resource is in a from-state of the invoked transition; failures produce `ERR_INVALID_STATE_TRANSITION` or one of the more specific state-family errors listed in §5 (all 409)."

    Design: Corner/state_machines/claim_void_from_denied_rejected
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    contract = make_contract(org["program"]["id"], org["group"]["id"])
    year = make_year(contract["id"])
    claim = make_claim(
        year["id"], org["members"][0]["id"], "CL-1", "2026-03-10", 1000
    )
    denied = api.deny_claim(claim["id"], claims_processor_headers)
    assert validate_success(denied)["claim_status"] == "DENIED"
    resp = api.void_claim(claim["id"], claims_processor_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    reread = validate_success(api.get_claim(claim["id"], claims_processor_headers))
    assert reread["claim_status"] == "DENIED"


def test_mark_paid_after_measuring_propagates_staleness(api, claims_processor_headers):
    """PRD §3.7: "A claim mark-paid that occurs when the year is past `MEASURING` (that is, in `RECONCILING` or later) recomputes both `actual_cost_cents` and `withhold_pool_cents`, transitions every `PUBLISHED` `InterimReport` of the year to `STALE`, and sets `needs_recompute` on the year's settlement when in `PROVISIONAL` or `FINALIZED`."
    PRD §3.7: "From `RECEIVED` the processor may mark it paid (`RECEIVED → PAID`), which stamps `paid_on` with the logical clock date, or deny it (`RECEIVED → DENIED`)."

    Design: Corner/complexity_layers/mark_paid_after_measuring_propagates_staleness
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    pipe = build_pipeline(
        org, stage="SETTLEMENT", interim_months=6,
        claim_specs=[
            {"member": 0, "ref": "CL-1", "service_date": "2026-02-10",
             "amount": 400000, "pay_clock": CLOCK_MAR},
            {"member": 0, "ref": "CL-2", "service_date": "2026-04-10",
             "amount": 100000, "pay": False},
        ],
        quality_specs=[("HBA1C", 350, 1000)],
        contract_overrides={"quality_measures": [
            {"measure_code": "HBA1C", "weight_bp": 10000,
             "decile_thresholds_bp": [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000]}
        ]},
    )
    year_id = pipe["year"]["id"]
    cl2 = pipe["claims"][1]
    assert cl2["claim_status"] == "RECEIVED"

    set_clock(CLOCK_LATE_PAID)
    paid = validate_success(api.mark_claim_paid(cl2["id"], claims_processor_headers))
    assert paid["paid_on"] == "2027-01-06", "paid_on stamps from the logical clock"

    year = get_year(year_id)
    assert year["actual_cost_cents"] == 500000, "the late-paid claim folds into actual cost"
    assert year["withhold_pool_cents"] == 25000

    report = validate_success(api.get_interim_report(pipe["report"]["id"], ACTUARY))
    assert report["report_status"] == "STALE"

    settlement = get_settlement(pipe["settlement"]["id"])
    assert settlement["needs_recompute"] is True

