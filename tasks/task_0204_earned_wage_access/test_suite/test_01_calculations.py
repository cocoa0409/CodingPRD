"""Calculation-engine tests: available-earnings dual-variant, principal clamp, fee
round-then-sum + cap, payday waterfall fee-before-principal.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
Queue B (Corner): calculations.* instances.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    set_clock,
    create_employer,
    create_standard_policy,
    create_fee_schedule,
    create_pay_period,
    create_worker,
    post_time_entry,
    post_shifts_for_gross_80000,
    post_shift_6h_gross_12000,
    setup_base_scenario,
    request_advance,
    request_and_approve_advance,
    request_approve_disburse_advance,
    lock_and_post_batch,
    get_worker_version,
)

OFFICER = TEST_USERS["payroll_officer_headers"]


# ===========================================================================
# Queue A — dual_variant_calc / available_earnings_sum_then_round_on_worker
# ===========================================================================
def test_available_earnings_sum_then_round_on_worker(api):
    """PRD §3.4: "compute the period's gross earned for this worker as the sum, over that
    worker's `POSTED` time entries in that period, of `hours_worked` multiplied by the worker's
    `hourly_rate_cents`, with the entire sum rounded half up to whole cents exactly once at the
    end. This sum-then-round order is mandatory: rounding each entry first and then summing can
    differ by cents and is the wrong order."
    PRD §3.4: "take the accessible amount as the floor of that gross earned multiplied by the
    employer's `max_advance_pct_of_available`; the access fraction is floored, not rounded."

    Two 0.25h/3.25h shifts @ rate 2001: sum-then-round gross = round(0.25*2001 + 3.25*2001)
    = round(7003.5) = 7004; accessible = floor(7004*0.5) = 3502. Per-entry rounding would give
    3501, so 3502 proves sum-then-round.

    Design: Difficulty/dual_variant_calc/available_earnings_sum_then_round_on_worker
    """
    employer = create_employer()
    create_standard_policy(employer["id"])
    period = create_pay_period(employer["id"])
    worker = create_worker(employer["id"], hourly_rate_cents=2001)
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-02T08:15:00Z", 0.25)
    post_time_entry(period["id"], worker["id"], "2026-06-02T10:00:00Z", "2026-06-02T13:15:00Z", 3.25)

    w = validate_success(api.get_worker(worker["id"], OFFICER))
    assert w["net_available_earnings_cents"] == 3502, (
        f"sum-then-round gross 7004 => accessible 3502; got {w['net_available_earnings_cents']}"
    )


def test_available_earnings_gross_accrued_uses_sum_then_round(api):
    """PRD §3.4: "with the entire sum rounded half up to whole cents exactly once at the end.
    This sum-then-round order is mandatory: rounding each entry first and then summing can
    differ by cents and is the wrong order."

    Same two shifts (0.25h + 3.25h @ 2001): PayPeriod.gross_accrued_cents = round(7003.5) = 7004,
    not the per-entry-rounded sum 7003.

    Design: Difficulty/dual_variant_calc/available_earnings_sum_then_round_on_worker
    """
    employer = create_employer()
    create_standard_policy(employer["id"])
    period = create_pay_period(employer["id"])
    worker = create_worker(employer["id"], hourly_rate_cents=2001)
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-02T08:15:00Z", 0.25)
    post_time_entry(period["id"], worker["id"], "2026-06-02T10:00:00Z", "2026-06-02T13:15:00Z", 3.25)

    pp = validate_success(api.get_pay_period(period["id"], OFFICER))
    assert pp["gross_accrued_cents"] == 7004, (
        f"gross_accrued_cents must be sum-then-round 7004; got {pp['gross_accrued_cents']}"
    )


# ===========================================================================
# Queue A — combinatorial_formula / principal_clamp_four_way_min_mode_a
# ===========================================================================
def test_principal_clamp_binds_on_available_earnings(api):
    """PRD §3.6: "The approved `principal_cents` is then the smallest of the requested principal
    and these three candidates, clamped to a floor of 0 so it is never negative."
    PRD §3.6: "The third candidate is the worker's `net_available_earnings_cents`, which already
    nets committed advances by their full recoup target."

    Requested 45000; per_advance_ceiling 50000; cumulative-room 80000; available 40000
    (gross 80000 * 0.5). The smallest binding ceiling is available-earnings => principal 40000.

    Design: Difficulty/combinatorial_formula/principal_clamp_four_way_min_mode_a
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shifts_for_gross_80000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 45000, disbursement_speed="STANDARD")

    approved = validate_success(api.approve_advance(adv["id"], OFFICER))
    assert approved["principal_cents"] == 40000, (
        f"available-earnings ceiling 40000 binds; got {approved['principal_cents']}"
    )


def test_principal_clamp_recoup_target_matches_clamped_principal(api):
    """PRD §3.7: "`recoup_target_cents` is the approved `principal_cents` plus `total_fee_cents`
    — the total the worker owes back at payday."

    STANDARD speed (expedite 0, tip 0) so recoup_target equals the clamped principal 40000,
    confirming the clamp drove the binding ceiling (available 40000), not the requested 45000.

    Design: Difficulty/combinatorial_formula/principal_clamp_four_way_min_mode_a
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shifts_for_gross_80000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 45000, disbursement_speed="STANDARD")

    approved = validate_success(api.approve_advance(adv["id"], OFFICER))
    assert approved["principal_cents"] == 40000
    assert approved["recoup_target_cents"] == 40000, (
        f"recoup_target = principal 40000 + fee 0; got {approved['recoup_target_cents']}"
    )


# ===========================================================================
# Queue A — combinatorial_formula / advance_fee_round_then_sum_with_cap_mode_b
# ===========================================================================
def test_advance_fee_round_then_sum_expedite_component(api):
    """PRD §3.7: "the `expedite_fee_cents` is the fee schedule's `expedite_flat_fee_cents` plus
    the product of `principal_cents` and the schedule's `expedite_pct_fee`, where that percent
    component is rounded half up to whole cents before being added to the flat component
    (round-then-sum order)."

    INSTANT, principal 40000: expedite = 199 + round(40000*0.02) = 199 + 800 = 999.

    Design: Difficulty/combinatorial_formula/advance_fee_round_then_sum_with_cap_mode_b
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shifts_for_gross_80000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 40000,
                          disbursement_speed="INSTANT", tip_cents=2000)

    approved = validate_success(api.approve_advance(adv["id"], OFFICER))
    assert approved["expedite_fee_cents"] == 999, (
        f"expedite = 199 + round(40000*0.02)=800 => 999; got {approved['expedite_fee_cents']}"
    )


def test_advance_fee_cap_trims_tip_keeps_expedite(api):
    """PRD §3.7: "The combined fee is then capped at the schedule's `max_total_fee_cents`. When
    the raw combined fee exceeds the cap, `total_fee_cents` is set to the cap, and the cap is
    absorbed by trimming the tip portion first while the mandatory expedite fee is never reduced".
    PRD §3.7: "`recoup_target_cents` is the approved `principal_cents` plus `total_fee_cents`".

    Raw combined = expedite 999 + tip 2000 = 2999 > cap 1500 => total_fee 1500;
    recoup_target = 40000 + 1500 = 41500.

    Design: Difficulty/combinatorial_formula/advance_fee_round_then_sum_with_cap_mode_b
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shifts_for_gross_80000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 40000,
                          disbursement_speed="INSTANT", tip_cents=2000)

    approved = validate_success(api.approve_advance(adv["id"], OFFICER))
    assert approved["total_fee_cents"] == 1500, (
        f"combined fee capped at 1500; got {approved['total_fee_cents']}"
    )
    assert approved["recoup_target_cents"] == 41500, (
        f"recoup_target = 40000 + 1500; got {approved['recoup_target_cents']}"
    )


# ===========================================================================
# Queue B — calculations / payday_recoup_fee_before_principal_split
# ===========================================================================
def test_payday_recoup_fee_before_principal_split(api):
    """PRD §3.10: "That taken amount is split fee-before-principal: the fee owed is the advance's
    `total_fee_cents` minus fees already recouped on it, the fee slice is the smaller of the
    taken amount and the fee owed, and the principal slice is whatever of the taken amount
    remains. A `Repayment` row is created for any positive fee slice with `applied_to` set to
    `FEE`, and a separate row for any positive principal slice with `applied_to` set to
    `PRINCIPAL`."

    INSTANT advance principal 6000, fee 319 (rt 6319). Worker gross 12000 => per-worker cap
    floor(12000*0.5)=6000. Take 6000 split fee-first: FEE 319 then PRINCIPAL 5681.

    Design: Corner/calculations/payday_recoup_fee_before_principal_split
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shift_6h_gross_12000(period["id"], worker["id"])
    adv = request_approve_disburse_advance(worker["id"], period["id"], 6000,
                                           disbursement_speed="INSTANT")
    lock_and_post_batch(period["id"])

    rows, _meta = _list_repayments(api, adv["id"])
    by_type = {r["applied_to"]: r for r in rows}
    assert by_type.get("FEE", {}).get("amount_cents") == 319, f"FEE slice must be 319; rows={rows}"
    assert by_type.get("PRINCIPAL", {}).get("amount_cents") == 5681, (
        f"PRINCIPAL slice must be 5681; rows={rows}"
    )
    adv_after = validate_success(api.get_advance(adv["id"], OFFICER))
    assert adv_after["amount_recouped_cents"] == 6000
    assert adv_after["principal_outstanding_cents"] == 319


# ===========================================================================
# Queue B — calculations / advance_fee_standard_speed_zero_expedite
# ===========================================================================
def test_advance_fee_standard_speed_zero_expedite(api):
    """PRD §3.7: "If the `disbursement_speed` is `STANDARD`, the `expedite_fee_cents` is 0."
    PRD §3.7: "`recoup_target_cents` is the approved `principal_cents` plus `total_fee_cents`".

    STANDARD, tip 0, principal 5000: expedite 0, total_fee 0, recoup_target 5000.

    Design: Corner/calculations/advance_fee_standard_speed_zero_expedite
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shifts_for_gross_80000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 5000, disbursement_speed="STANDARD")

    approved = validate_success(api.approve_advance(adv["id"], OFFICER))
    assert approved["expedite_fee_cents"] == 0
    assert approved["total_fee_cents"] == 0
    assert approved["recoup_target_cents"] == 5000


def _list_repayments(api, advance_id):
    resp = api.list_repayments(OFFICER, params={"advance_id": advance_id})
    body = resp.json()
    return body["data"], body["meta"]
