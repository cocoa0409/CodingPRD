"""Second tests for every difficulty-design instance: complementary boundaries,
opposite branches, and success-path counterparts. Each cites the same PRD rule and
carries the same Design tag as its sibling in test_01..test_04."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    create_check_cash_payload, create_prepaid_load_payload, create_money_order_payload,
    create_cash_drawer_payload, create_compliance_screen_payload,
    setup_verified_customer_and_drawer, setup_verified_customer_drawer_and_schedule,
    setup_risk_held_check, setup_partially_recovered_check, setup_returned_check,
    setup_velocity_saturated_customer, setup_closed_drawer,
    create_customer, create_govt_schedule, create_payroll_divergent_schedule, open_drawer,
    get_check_item_for_transaction, return_payload, recover_payload, set_clock,
    make_teller_headers, make_store_manager_headers,
)

TELLER = make_teller_headers("teller-1")
MANAGER = make_store_manager_headers("manager-9")


# ===== Rule 1: dual-variant calc =====

def test_check_cash_fee_marginal_tier_above_breakpoint(api):
    """PRD §3.2: "If the face amount is above the breakpoint, the percentage portion is
    the sum of two legs computed separately: a low leg equal to the breakpoint multiplied
    by `percent_rate_bps` divided by 10000 (floored), plus a high leg equal to the excess
    of the face over the breakpoint multiplied by `high_percent_rate_bps` divided by 10000
    (floored)."

    base=99, pr=100, bp=500000, hpr=200, face=600000 (>bp), maker LOW auto-clears (face<
    300000? no — face 600000 >= 300000 so it would AMOUNT-hold). Use STANDARD ceiling
    headroom but avoid hold: keep face below 300000 is impossible above a 500000 bp, so we
    assert via the held check's parent fee instead. Simpler: use a low breakpoint schedule.
    base=99, pr=100, bp=100000, hpr=200, face=250000 -> low floor(100000*100/10000)=1000,
    high floor(150000*200/10000)=3000, fee=99+4000=4099. face 250000 < 300000 auto-clears.

    Design: Difficulty/dual_variant_calc/check_cash_fee_float_gross_on_full_face
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="R1", opening_float_cents=2000000,
        schedule_overrides={
            "check_type": "GOVERNMENT", "base_fee_cents": 99, "percent_rate_bps": 100,
            "tier_breakpoint_cents": 100000, "high_percent_rate_bps": 200,
            "max_fee_cents": 50000, "active": True,
        })
    txn = validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 250000, sched["id"], "LOW"),
        TELLER), 201)
    assert txn["fee_cents"] == 4099, f"expected marginal fee 4099, got {txn['fee_cents']}"
    assert txn["lifecycle_state"] == "POSTED"


def test_risk_score_confirmed_on_reject_high_maker(api):
    """PRD §3.8: "When a held check is resolved (released or rejected), the hold-derived
    delta is confirmed: 120 points if the held check's maker account risk was `HIGH`, plus
    60 points if the hold reason was `AMOUNT_THRESHOLD`, plus 90 points if the hold reason
    was `VELOCITY`."
    PRD §3.5: "a provisional risk increment is computed and surfaced on the check but is
    **not** written to the customer's confirmed `risk_score`".

    A face=100000 maker HIGH check holds with hold_reason MAKER_RISK; risk_score stays 0
    while held; rejecting confirms +120 (HIGH_MAKER_PTS) -> 120.

    Design: Difficulty/dual_variant_calc/customer_risk_score_provisional_vs_confirmed
    """
    cust, drawer, sched, txn, check = setup_risk_held_check(
        store_code="R2", face_amount_cents=100000, maker_account_risk="HIGH",
        teller_id="teller-1", schedule="govt")
    assert check["hold_reason"] == "MAKER_RISK"
    before = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert before["risk_score"] == 0

    validate_success(api.reject_check_item(check["id"], MANAGER), 200)
    after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert after["risk_score"] == 120, f"expected confirmed risk_score 120, got {after['risk_score']}"


# ===== Rule 2: combinatorial formula =====

def test_check_cash_fee_at_or_below_breakpoint_single_leg(api):
    """PRD §3.2: "If the face amount is at or below the `tier_breakpoint_cents`, the
    percentage portion is the face amount multiplied by `percent_rate_bps`, divided by
    10000 with integer floor division."

    base=199, pr=150, bp=199999, face=199999 (== bp, at-or-below branch):
    pct = floor(199999*150/10000) = 2999; fee = 199 + 2999 = 3198. face < 300000 auto-clears.

    Design: Difficulty/combinatorial_formula/check_cash_fee_per_leg_floor_then_sum_mode_b
    """
    cust, drawer = setup_verified_customer_and_drawer("R3", opening_float_cents=2000000)
    sched = create_payroll_divergent_schedule()
    txn = validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 199999, sched["id"], "LOW"),
        TELLER), 201)
    assert txn["fee_cents"] == 3198, f"expected single-leg fee 3198, got {txn['fee_cents']}"


def test_money_order_fee_capped_at_max(api):
    """PRD §3.2: "For a `MONEY_ORDER`, the fee is the smaller of (99 cents plus the face
    multiplied by 50 basis points divided by 10000, floored) and a 500-cent cap."

    face=200000: 99 + floor(200000*50/10000) = 99 + 1000 = 1099, capped to 500.

    Design: Difficulty/combinatorial_formula/service_fee_greater_of_and_cap_mode_a
    """
    cust, drawer = setup_verified_customer_and_drawer("R4", opening_float_cents=2000000)
    txn = validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 200000, "Acme"), TELLER), 201)
    assert txn["fee_cents"] == 500, f"expected capped MO fee 500, got {txn['fee_cents']}"


# ===== Rule 3: non-linear state machine =====

def test_checkitem_riskheld_then_release_posts_txn(api):
    """PRD §3.7: "On release, the parent transaction moves to `lifecycle_state` `POSTED`
    with `settlement_state` `SETTLED`, the customer's `daily_cashed_amount_cents` is
    increased by the check's face, the drawer's expected cash is recomputed, and the
    hold-derived risk delta is confirmed onto the customer's `risk_score`".

    The opposite branch of reject: a RISK_HELD check released -> CLEARED, txn POSTED+SETTLED.

    Design: Difficulty/non_linear_state_machine/checkitem_branch_verifying_to_riskheld_then_reject
    """
    cust, drawer, sched, txn, check = setup_risk_held_check(
        store_code="R5", face_amount_cents=350000, maker_account_risk="LOW",
        teller_id="teller-1", schedule="payroll")
    released = validate_success(api.release_check_item(check["id"], MANAGER), 200)
    assert released["verification_state"] == "CLEARED"
    txn_after = validate_success(api.get_transaction(txn["id"], TELLER), 200)
    assert txn_after["lifecycle_state"] == "POSTED"
    assert txn_after["settlement_state"] == "SETTLED"


def test_returned_item_outstanding_directly_to_recovered(api):
    """PRD §3.9: "If the payment brings `recovered_cents` to exactly the total owed, the
    returned item moves to `RECOVERED` (whether arriving from `OUTSTANDING` directly or
    from `PARTIALLY_RECOVERED`)".

    The non-cyclic arm of the recovery machine: a single recover of the full total_owed
    102500 from OUTSTANDING goes straight to RECOVERED.

    Design: Difficulty/non_linear_state_machine/returned_item_cyclic_partial_recovery_loop
    """
    cust, drawer, sched, txn, ri = setup_returned_check(
        store_code="R6", face_amount_cents=100000, teller_id="teller-1")
    assert ri["status"] == "OUTSTANDING"
    final = validate_success(api.recover_returned_item(
        ri["id"], recover_payload(102500), TELLER), 200)
    assert final["status"] == "RECOVERED"
    assert final["recovered_cents"] == 102500


# ===== Rule 4: transitive cascade =====

def test_single_return_cascade_keeps_standard_tier(api):
    """PRD §3.9: "As a first cascade hop, the customer's `outstanding_recovery_cents` is
    increased by the sum of the check face plus the 2500-cent return fee. As a second
    cascade hop, 250 points are confirmed onto the customer's `risk_score`".
    PRD §3.8: "it is `STANDARD` while the score is below 350".

    A single return: outstanding 102500, risk_score 250 < 350 so tier stays STANDARD
    (the boundary not yet crossed — complement of the two-return ELEVATED bump).

    Design: Difficulty/transitive_cascade/return_cascade_depth3_recovery_then_risk_tier_bump
    """
    cust, drawer, sched, txn, ri = setup_returned_check(
        store_code="R7", face_amount_cents=100000, teller_id="teller-1")
    cust_after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_after["outstanding_recovery_cents"] == 102500
    assert cust_after["risk_score"] == 250
    assert cust_after["risk_tier"] == "STANDARD"


def test_void_check_cash_cascade_restores_drawer_and_counters(api):
    """PRD §3.7: "Voiding moves the transaction to `lifecycle_state` `VOIDED`, ... recomputes
    the drawer's expected cash by reversing the original net impact, and decrements the
    customer's `daily_cashed_amount_cents` and `daily_transaction_count` as compensation
    for the original posting."

    A different trigger shape than the MONEY_ORDER void: voiding a CHECK_CASH (cash-OUT,
    net = face-fee) restores the drawer to opening float and zeroes the counters.

    Design: Difficulty/transitive_cascade/void_cascade_depth2_drawer_and_velocity_reversal
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="R8", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER), 201)
    # CHECK_CASH net = +(100000 - 1099); expected = 1000000 - 98901 = 901099.
    drawer_before = validate_success(api.get_cash_drawer(drawer["id"], MANAGER), 200)
    assert drawer_before["expected_cash_cents"] == 901099

    validate_success(api.void_transaction(txn["id"], MANAGER), 200)
    drawer_after = validate_success(api.get_cash_drawer(drawer["id"], MANAGER), 200)
    assert drawer_after["expected_cash_cents"] == 1000000
    cust_after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_after["daily_transaction_count"] == 0
    assert cust_after["daily_cashed_amount_cents"] == 0


# ===== Rule 5: validation-priority conflicts =====

def test_sod_satisfied_distinct_manager_releases_despite_kyc_ok(api):
    """PRD §2.7: "the operator who originates a transaction may not be the operator who
    later approves, reverses, or otherwise passes judgment on it."
    PRD §3.7: "Both resolution paths enforce segregation of duties: the resolving manager's
    `X-User-ID` must differ from the creating Teller's, or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Complement of the SoD-beats-KYC conflict: when the manager id differs AND the customer
    stays VERIFIED, neither priority-5 nor priority-6 fires and the release succeeds.

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_kyc_on_release
    """
    cust, drawer, sched, txn, check = setup_risk_held_check(
        store_code="R9", face_amount_cents=350000, maker_account_risk="LOW",
        teller_id="teller-1", schedule="payroll")
    released = validate_success(
        api.release_check_item(check["id"], make_store_manager_headers("manager-9")), 200)
    assert released["verification_state"] == "CLEARED"


def test_daily_limit_enforced_when_drawer_open(api):
    """PRD §3.8: "The projected cashed amount is the current `daily_cashed_amount_cents`
    plus the face amount for a check-cash posting ...; if that projected cashed amount
    would exceed the daily cash limit of 1000000 cents, a check-cash posting is rejected
    with `ERR_DAILY_LIMIT_EXCEEDED`."

    Complement of the priority conflict: with the drawer left OPEN (so ERR_DRAWER_NOT_OPEN
    cannot pre-empt), the same over-limit CHECK_CASH surfaces ERR_DAILY_LIMIT_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/drawer_not_open_beats_daily_limit_on_post
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="R10", opening_float_cents=2000000)
    for _ in range(5):
        validate_success(api.create_transaction(
            create_check_cash_payload(cust["id"], drawer["id"], 180000, sched["id"], "LOW"),
            TELLER), 201)
    # Drawer stays OPEN; projected cashed 900000 + 200000 = 1100000 > 1000000.
    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 200000, sched["id"], "LOW"),
        TELLER)
    validate_error(res, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED, expected_status=422)


# ===== Rule 6: boundary precision =====

def test_hold_threshold_one_below_auto_clears(api):
    """PRD §3.5: "A check is placed on hold — moving `VERIFYING → RISK_HELD` — if any of
    three conditions is met: the face amount is at least 300000 cents".
    PRD §3.5: "If none of the three hold conditions is met, the check clears automatically:
    it moves `VERIFYING → CLEARED`, the parent transaction moves to `POSTED` with
    `settlement_state` `SETTLED`".

    face=299999 (one cent below the threshold), maker LOW, count 0 -> auto-clears.

    Design: Difficulty/boundary_precision_check/hold_threshold_exact_ge_boundary_on_post
    """
    cust, drawer = setup_verified_customer_and_drawer("R11", opening_float_cents=2000000)
    sched = create_payroll_divergent_schedule()
    txn = validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 299999, sched["id"], "LOW"),
        TELLER), 201)
    check = get_check_item_for_transaction(txn["id"])
    assert check["verification_state"] == "CLEARED"
    txn_after = validate_success(api.get_transaction(txn["id"], TELLER), 200)
    assert txn_after["lifecycle_state"] == "POSTED"
    assert txn_after["settlement_state"] == "SETTLED"


def test_recovery_one_over_remaining_rejected(api):
    """PRD §3.9: "The amount must be greater than 0 and must not exceed the remaining
    balance, which is the total owed minus the amount already recovered; an amount of 0 or
    less, or any amount that would overpay the remaining balance, is rejected with
    `ERR_RECOVERY_OVERPAYMENT` (overpayment is refused outright, not silently capped)."

    remaining 62500 after 40000 recovered; an amount of 62501 (one cent over) is rejected.

    Design: Difficulty/boundary_precision_check/recovery_exact_balance_equality_boundary
    """
    cust, drawer, sched, txn, ri = setup_partially_recovered_check(
        store_code="R12", face_amount_cents=100000, first_recovery=40000,
        teller_id="teller-1")
    res = api.recover_returned_item(ri["id"], recover_payload(62501), TELLER)
    validate_error(res, ApiErrorId.ERR_RECOVERY_OVERPAYMENT, expected_status=422)


# ===== Rule 7: cross-entity state dependency =====

def test_post_rejected_for_rejected_kyc_status(api):
    """PRD §2.8: "Before any posting, the customer's `kyc_status` must be `VERIFIED`; if it
    is anything else, the posting is rejected with `ERR_KYC_NOT_VERIFIED`."

    A different non-VERIFIED state than PENDING: a customer screened to REJECTED
    (kyc_documents_valid false) posting a CHECK_CASH is rejected with ERR_KYC_NOT_VERIFIED.

    Design: Difficulty/cross_entity_state_dependency/transaction_post_requires_customer_kyc_verified
    """
    cust = create_customer(full_name="Rej Kyc", id_type="STATE_ID",
                           id_number="SID-R13", date_of_birth="1990-01-01")
    validate_success(api.create_compliance_screen(
        create_compliance_screen_payload(cust["id"], ofac_list_hit=False,
                                         kyc_documents_valid=False), MANAGER), 201)
    sched = create_govt_schedule()
    drawer = open_drawer(store_code="R13", opening_float_cents=1000000)
    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER)
    validate_error(res, ApiErrorId.ERR_KYC_NOT_VERIFIED, expected_status=403)


def test_post_rejected_against_reconciling_drawer(api):
    """PRD §3.3: "Any attempt to post a transaction, void a transaction, or release a
    risk-held check against a drawer that is `RECONCILING`, `CLOSED`, or `OVER_SHORT` is
    rejected with `ERR_DRAWER_NOT_OPEN`."

    A different non-OPEN drawer state than CLOSED: a posting against a RECONCILING drawer
    is rejected with ERR_DRAWER_NOT_OPEN.

    Design: Difficulty/cross_entity_state_dependency/transaction_post_requires_drawer_open
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="R14", opening_float_cents=1000000)
    validate_success(api.begin_reconcile_drawer(drawer["id"], MANAGER), 200)
    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER)
    validate_error(res, ApiErrorId.ERR_DRAWER_NOT_OPEN, expected_status=409)


# ===== Rule 8: resource temporal-overlap =====

def test_drawer_no_conflict_different_business_date(api):
    """PRD §3.3: "The conflict is on the exact pair only — there is no buffer and no
    aggregate capacity; once the existing drawer is no longer `OPEN`, a new one may be
    opened for that same key."

    Complement of the same-key conflict: an OPEN drawer for (S15X, 2026-05-01) does NOT
    conflict with a second drawer for (S15X, 2026-05-02) — a different business_date.

    Design: Difficulty/resource_temporal_overlap/drawer_single_occupancy_same_store_date_conflict
    """
    open_drawer(store_code="S15X", business_date="2026-05-01", opening_float_cents=1000000)
    res = api.create_cash_drawer(
        create_cash_drawer_payload(store_code="S15X", business_date="2026-05-02",
                                   opening_float_cents=800000), MANAGER)
    second = validate_success(res, 201)
    assert second["status"] == "OPEN"


def test_velocity_window_rolls_at_24h_boundary(api):
    """PRD §3.8: "if `limit_window_opened_at` is unset, or if the current clock time is at
    or after `limit_window_opened_at` plus 24 hours, the window rolls — `limit_window_opened_at`
    is reset to the current time and both `daily_transaction_count` and
    `daily_cashed_amount_cents` are reset to 0. The boundary is half-open: a posting whose
    clock time falls exactly at the 24-hour mark rolls the window".

    With 12 postings saturating the window at 08:00:00Z, advancing the clock to exactly
    +24h (2026-05-02T08:00:00Z) rolls the window so a 13th posting succeeds and
    daily_transaction_count resets to 1.

    Design: Difficulty/resource_temporal_overlap/velocity_rolling_window_half_open_aggregate
    """
    cust, drawer = setup_velocity_saturated_customer(
        store_code="R16", clock="2026-05-01T08:00:00Z", n=12, face_amount_cents=1000)
    set_clock("2026-05-02T08:00:00Z")
    txn = validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 1000, "P13"), TELLER), 201)
    assert txn["lifecycle_state"] == "POSTED"
    cust_after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_after["daily_transaction_count"] == 1


# ===== Rule 9: compensating invariant =====

def test_void_conserves_drawer_cash_check_cash_arm(api):
    """PRD §2.9: "A drawer's `expected_cash_cents` is derived, never set directly: it is
    its opening float adjusted by the cash impact of every posted transaction flowing
    through it".
    PRD §3.7: "recomputes the drawer's expected cash by reversing the original net impact".

    The cash-OUT arm of the invariant: a CHECK_CASH face=100000 fee=1099 drives expected
    down to 901099; voiding restores it exactly to the opening float 1000000.

    Design: Difficulty/compensating_invariant/void_conserves_drawer_expected_cash
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="R17", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER), 201)
    before = validate_success(api.get_cash_drawer(drawer["id"], MANAGER), 200)
    assert before["expected_cash_cents"] == 901099
    validate_success(api.void_transaction(txn["id"], MANAGER), 200)
    after = validate_success(api.get_cash_drawer(drawer["id"], MANAGER), 200)
    assert after["expected_cash_cents"] == 1000000


def test_void_conserves_velocity_counters_money_order_arm(api):
    """PRD §3.7: "decrements the customer's `daily_cashed_amount_cents` and
    `daily_transaction_count` as compensation for the original posting."
    PRD §3.8: "non-check-cash postings add nothing to the cashed amount".

    Complement on a MONEY_ORDER: posting bumps daily_transaction_count to 1 but leaves
    daily_cashed_amount_cents at 0 (non-check-cash); voiding restores count to 0.

    Design: Difficulty/compensating_invariant/void_conserves_customer_velocity_counters
    """
    cust, drawer = setup_verified_customer_and_drawer("R18", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 50000, "Acme"), TELLER), 201)
    before = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert before["daily_transaction_count"] == 1
    assert before["daily_cashed_amount_cents"] == 0

    validate_success(api.void_transaction(txn["id"], MANAGER), 200)
    after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert after["daily_transaction_count"] == 0
    assert after["daily_cashed_amount_cents"] == 0
