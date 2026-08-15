"""Distribution waterfall, remittance lifecycle, year close and reopen."""
from test_helpers import (
    ADMIN, AUDITOR, PAYMENTS, ApiErrorId, authorize_settlement,
    build_pipeline, canonical_two_member_journey, get_settlement, get_year,
    mark_year_settled, pay_remittance, approve_remittance,
    remittance_for_practice, setup_org, single_member_journey,
    validate_error, validate_success,
)
from test_helpers import SINGLE_MEASURE_CATALOG, suspend_group_payload


def test_remittance_approve_requires_group_active(api, payment_ops_headers, payer_admin_headers):
    """PRD §3.12: "A `PaymentOps` operator approves a remittance (`SCHEDULED → APPROVED`); approval requires the settlement to be in `AUTHORIZED` (`ERR_SETTLEMENT_NOT_AUTHORIZED`) and the practice's owning group to be in `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/remittance_approve_requires_group_active
    """
    pipe = single_member_journey(stage="AUTHORIZED")
    rem = pipe["remittances"][0]
    assert rem["amount_cents"] == 74200, "single practice receives the full net"
    assert rem["remittance_status"] == "SCHEDULED"

    validate_success(api.suspend_practice_group(
        pipe["group"]["id"], suspend_group_payload("audit hold"), payer_admin_headers
    ))
    blocked = api.approve_remittance(rem["id"], payment_ops_headers)
    validate_error(blocked, ApiErrorId.ERR_GROUP_NOT_ACTIVE)

    validate_success(api.reinstate_practice_group(pipe["group"]["id"], payer_admin_headers))
    approved = api.approve_remittance(rem["id"], payment_ops_headers)
    assert validate_success(approved)["remittance_status"] == "APPROVED"


def test_remittance_pays_through_after_group_reinstated(api, payment_ops_headers, payer_admin_headers):
    """PRD §3.12: "A `PaymentOps` operator approves a remittance (`SCHEDULED → APPROVED`); approval requires the settlement to be in `AUTHORIZED` (`ERR_SETTLEMENT_NOT_AUTHORIZED`) and the practice's owning group to be in `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`)."
    PRD §3.12: "From `APPROVED` the operator may mark it paid (`APPROVED → PAID`), which stamps `paid_on` from the logical clock; when every remittance of the settlement has reached `PAID`, the settlement automatically transitions `AUTHORIZED → DISTRIBUTED`."

    Design: Difficulty/cross_entity_state_dependency/remittance_approve_requires_group_active
    """
    pipe = single_member_journey(stage="AUTHORIZED")
    rem = pipe["remittances"][0]

    validate_success(api.suspend_practice_group(
        pipe["group"]["id"], suspend_group_payload("audit hold"), payer_admin_headers
    ))
    validate_error(
        api.approve_remittance(rem["id"], payment_ops_headers),
        ApiErrorId.ERR_GROUP_NOT_ACTIVE,
    )
    reread = validate_success(api.get_remittance(rem["id"], payment_ops_headers))
    assert reread["remittance_status"] == "SCHEDULED", "a rejected approve mutates nothing"

    validate_success(api.reinstate_practice_group(pipe["group"]["id"], payer_admin_headers))
    approve_remittance(rem["id"])
    paid = pay_remittance(rem["id"])
    assert paid["remittance_status"] == "PAID"
    assert get_settlement(pipe["settlement"]["id"])["settlement_status"] == "DISTRIBUTED"


def test_remittance_return_requeue_pool_conserved(api, payment_ops_headers):
    """PRD §3.10: "Eighth, `undistributed_balance_cents` is the positive part of `net_payable_cents` minus the sum of `amount_cents` over the settlement's remittances in `SCHEDULED`, `APPROVED`, or `PAID`."
    PRD §3.12: "Alternatively, the operator may return a remittance (`APPROVED → RETURNED`); the `RETURNED` amount is released back into the settlement's `undistributed_balance_cents`, which is recomputed. A returned remittance may be requeued (`RETURNED → SCHEDULED`), which again requires the settlement to be in `AUTHORIZED` (`ERR_SETTLEMENT_NOT_AUTHORIZED`) and again recomputes `undistributed_balance_cents`."

    Design: Difficulty/compensating_invariant/remittance_return_requeue_pool_conserved
    """
    pipe = canonical_two_member_journey(stage="AUTHORIZED")
    settlement_id = pipe["settlement"]["id"]
    rem1 = remittance_for_practice(pipe["practices"][0]["id"])
    assert rem1["amount_cents"] == 78333
    assert get_settlement(settlement_id)["undistributed_balance_cents"] == 0

    approve_remittance(rem1["id"])
    assert get_settlement(settlement_id)["undistributed_balance_cents"] == 0, (
        "APPROVED amounts still count against the balance"
    )

    returned = validate_success(api.return_remittance(rem1["id"], payment_ops_headers))
    assert returned["remittance_status"] == "RETURNED"
    assert get_settlement(settlement_id)["undistributed_balance_cents"] == 78333, (
        "RETURNED releases the amount back into the balance"
    )

    requeued = validate_success(api.requeue_remittance(rem1["id"], payment_ops_headers))
    assert requeued["remittance_status"] == "SCHEDULED"
    assert get_settlement(settlement_id)["undistributed_balance_cents"] == 0, (
        "return-then-requeue conserves the pool exactly"
    )


def test_remittance_return_requeue_conserves_amounts(api, payment_ops_headers):
    """PRD §3.12: "Return-then-requeue is the compensating invariant that lets a payment operation recover from a bad instruction without disturbing the rest of the distribution."
    PRD §3.12: "Conservation holds: the sum of allocated `amount_cents` equals the pool exactly."

    Design: Difficulty/compensating_invariant/remittance_return_requeue_pool_conserved
    """
    pipe = canonical_two_member_journey(stage="AUTHORIZED")
    settlement_id = pipe["settlement"]["id"]
    rem1 = remittance_for_practice(pipe["practices"][0]["id"])
    rem2 = remittance_for_practice(pipe["practices"][1]["id"])
    assert rem1["amount_cents"] + rem2["amount_cents"] == 117500

    approve_remittance(rem1["id"])
    validate_success(api.return_remittance(rem1["id"], payment_ops_headers))
    mid = get_settlement(settlement_id)["undistributed_balance_cents"]
    assert mid + rem2["amount_cents"] == 117500, (
        "counted remittances plus balance conserve the pool mid-cycle"
    )

    requeued = validate_success(api.requeue_remittance(rem1["id"], payment_ops_headers))
    assert requeued["amount_cents"] == 78333, "requeue restores the same amount"
    assert requeued["remittance_status"] == "SCHEDULED"
    final = get_settlement(settlement_id)
    assert final["undistributed_balance_cents"] == 0
    assert remittance_for_practice(pipe["practices"][0]["id"])["amount_cents"] == 78333


def test_distribution_largest_remainder_split(api):
    """PRD §3.12: "Otherwise, for each practice, the exact share is the pool multiplied by the practice's weight and divided by the total weight; the practice's `amount_cents` is the floor of that exact share. The remainder — the pool minus the sum of the floored amounts, which is always non-negative and strictly less than the number of practices — is then distributed as one additional cent per practice, ordered by descending fractional part (exact share minus floored share), with ties broken by ascending `Practice.created_at` and never by id. Each practice receives at most one additional cent."
    PRD §3.12: "Conservation holds: the sum of allocated `amount_cents` equals the pool exactly."

    Design: Corner/calculations/distribution_largest_remainder_split
    """
    pipe = canonical_two_member_journey(stage="AUTHORIZED")
    settlement = pipe["settlement"]
    rem1 = remittance_for_practice(pipe["practices"][0]["id"])
    rem2 = remittance_for_practice(pipe["practices"][1]["id"])

    assert rem1["practice_member_months"] == 12
    assert rem1["amount_cents"] == 78333       # floor(117500 * 12/18)
    assert rem2["practice_member_months"] == 6
    assert rem2["amount_cents"] == 39167       # floor 39166 + the remainder cent
    assert rem1["amount_cents"] + rem2["amount_cents"] == 117500
    assert settlement["undistributed_balance_cents"] == 0


def test_distribution_tie_break_by_practice_created_at(api):
    """PRD §3.12: "The remainder — the pool minus the sum of the floored amounts, which is always non-negative and strictly less than the number of practices — is then distributed as one additional cent per practice, ordered by descending fractional part (exact share minus floored share), with ties broken by ascending `Practice.created_at` and never by id. Each practice receives at most one additional cent."
    PRD §3.10: "If the composite is greater than or equal to the contract's `quality_gate_excellence_points`, the multiplier is 10000."

    Design: Corner/calculations/distribution_tie_break_by_practice_created_at
    """
    org = setup_org(
        member_specs=[
            ("M-A", 1980, "2026-07-01", "2026-12-31"),
            ("M-B", 1975, "2026-07-01", "2026-12-31"),
        ],
        practice_count=2,
    )
    pipe = build_pipeline(
        org, stage="AUTHORIZED",
        claim_specs=[
            {"member": 0, "ref": "CL-A", "service_date": "2026-08-10", "amount": 610030},
            {"member": 1, "ref": "CL-B", "service_date": "2026-09-05", "amount": 500000},
        ],
        quality_specs=[("HBA1C", 850, 1000)],
        contract_overrides={"quality_measures": SINGLE_MEASURE_CATALOG},
    )
    settlement = pipe["settlement"]
    # HBA1C 850/1000 -> 8 points -> composite 89 >= excellence 80 -> mult 10000.
    # benchmark 1,200,000 - actual 1,110,030 = 89,970 gross; rate 749;
    # shared 44,985; pool 55,502; net 100,487.
    assert settlement["net_payable_cents"] == 100487

    rem_a = remittance_for_practice(pipe["practices"][0]["id"])  # created first
    rem_b = remittance_for_practice(pipe["practices"][1]["id"])
    # exact share 50,243.5 each; tied fractions -> the earlier-created practice
    # collects the single remainder cent.
    assert rem_a["amount_cents"] == 50244
    assert rem_b["amount_cents"] == 50243
    assert rem_a["amount_cents"] + rem_b["amount_cents"] == 100487


def test_remittance_terminal_lockdown_paid_rejects_return(api, payment_ops_headers):
    """PRD §3.12: "From `APPROVED` the operator may mark it paid (`APPROVED → PAID`), which stamps `paid_on` from the logical clock; when every remittance of the settlement has reached `PAID`, the settlement automatically transitions `AUTHORIZED → DISTRIBUTED`."
    PRD §2.8: "6. **State preconditions** — the target resource is in a from-state of the invoked transition; failures produce `ERR_INVALID_STATE_TRANSITION` or one of the more specific state-family errors listed in §5 (all 409)."

    Design: Corner/state_machines/remittance_terminal_lockdown_paid_rejects_return
    """
    pipe = single_member_journey(stage="AUTHORIZED")
    rem = pipe["remittances"][0]
    approve_remittance(rem["id"])
    paid = pay_remittance(rem["id"])
    assert paid["remittance_status"] == "PAID"
    assert paid["paid_on"] == "2028-06-01", "paid_on stamps from the logical clock"

    resp = api.return_remittance(rem["id"], payment_ops_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_settlement(pipe["settlement"]["id"])["settlement_status"] == "DISTRIBUTED", (
        "paying the sole remittance bubbles the settlement to DISTRIBUTED"
    )


def test_year_close_before_distribution_rejected(api, auditor_headers):
    """PRD §3.4: "Finally, an `Auditor` closes the year (`SETTLED → CLOSED`); this requires the settlement to be in `DISTRIBUTED` (`ERR_SETTLEMENT_NOT_DISTRIBUTED`)."
    PRD §3.4: "The other exit is taken by a `SettlementOfficer` who marks the year settled (`RECONCILING → SETTLED`); this requires a settlement in `FINALIZED`, `AUTHORIZED`, or `DISTRIBUTED` (`ERR_SETTLEMENT_NOT_FINAL` otherwise) and requires the logical clock date to be strictly greater than the settlement's `finalized_on` plus the dispute window (`ERR_DISPUTE_WINDOW_OPEN` otherwise). Marking settled releases the reserve: `accrued_reserve_cents` is set to 0."

    Design: Corner/state_machines/year_close_before_distribution_rejected
    """
    pipe = single_member_journey(stage="FINALIZED")
    year_id = pipe["year"]["id"]

    settled = mark_year_settled(year_id)
    assert settled["year_status"] == "SETTLED"
    assert settled["accrued_reserve_cents"] == 0

    resp = api.close_year(year_id, auditor_headers)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_DISTRIBUTED)
    assert get_year(year_id)["year_status"] == "SETTLED"


def test_reopen_attribution_resets_year_cycle(api, payer_admin_headers, attribution_analyst_headers):
    """PRD §3.4: "The reopen performs a coordinated reset: the currently `LOCKED` attribution run is moved to `SUPERSEDED` (a `LOCKED → SUPERSEDED` transition on the run), the year's `locked_run_id` is cleared to null, the `PROVISIONAL` settlement is moved to `VOID` (a `PROVISIONAL → VOID` transition on the settlement), and the rollups are zeroed — `total_member_months` to 0, `benchmark_cost_cents` to 0, `risk_adjustment_factor_milli` to null, `actual_cost_cents` to 0, and `withhold_pool_cents` to 0."

    Design: Corner/state_machines/reopen_attribution_resets_year_cycle
    """
    pipe = single_member_journey(stage="SETTLEMENT")
    year_id = pipe["year"]["id"]

    reopened = validate_success(api.reopen_attribution(year_id, payer_admin_headers))
    assert reopened["year_status"] == "ATTRIBUTION_OPEN"
    assert reopened["locked_run_id"] is None
    assert reopened["total_member_months"] == 0
    assert reopened["benchmark_cost_cents"] == 0
    assert reopened["risk_adjustment_factor_milli"] is None
    assert reopened["actual_cost_cents"] == 0
    assert reopened["withhold_pool_cents"] == 0

    run = validate_success(api.get_attribution_run(pipe["run"]["id"], attribution_analyst_headers))
    assert run["run_status"] == "SUPERSEDED"
    assert get_settlement(pipe["settlement"]["id"])["settlement_status"] == "VOID"
