"""Second covering test per difficulty-design instance.

Each difficulty instance requires >=2 tests; this file supplies an additional
assertion angle (a distinct observable field or a boundary partner) for instances
whose first test lives in test_02 / test_04 / test_05 / test_06.
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
)
from test_helpers.fixtures import (
    api_client,
    create_pool,
    create_active_plan,
    create_facility,
    create_contract,
    setup_active_contract,
    setup_authorized_claim,
    setup_under_review_claim,
    setup_disbursed_standard,
    set_clock,
    STANDARD_LINES,
)

ADMIN = TEST_USERS["admin_underwriter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# --- dual_variant_calc: refund mileage-basis partner ------------------------

def test_refund_basis_mileage_when_high_mileage_short_elapsed(api):
    """PRD §3.6: "When the mileage fraction is at least the time fraction the refund
    basis is `PRO_RATA_MILEAGE`; otherwise it is `PRO_RATA_TIME`."

    Design: Difficulty/dual_variant_calc/refund_basis_time_vs_mileage_on_cancellation
    """
    # High mileage consumed (one paid claim drives current_odometer up), short elapsed.
    base = setup_disbursed_standard(pool_name="Pool MIL", vin="VINMILE0001")
    # Latest claim odometer is 40000; miles_used = 40000-20000 = 20000; mileage_frac=0.2.
    # Clock at 2026-03-01 -> ~59 days; time_frac ~ 59/1800 ~ 0.033 < 0.2 -> MILEAGE basis.
    set_clock("2026-03-01T00:00:00Z")
    canc = validate_success(api.create_cancellation(
        {"contract_id": base["contract"]["id"], "reason": "CUSTOMER_REQUEST", "request_date": "2026-03-01T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    approved = validate_success(api.approve_cancellation(canc["id"], CONTRACT_ADMIN))
    assert approved["refund_basis"] == "PRO_RATA_MILEAGE", \
        f"expected PRO_RATA_MILEAGE (mileage_frac >= time_frac), got {approved['refund_basis']}"


# --- dual_variant_calc: pool surplus reserve-held value angle ----------------

def test_pool_surplus_under_review_reserve_basis_value(api):
    """PRD §2.9: "the `reserve_held_cents` is the sum of the pool's `RESERVE_SET` and
    `RESERVE_RELEASE` entries. The `surplus_cents` is then the ceded premium minus the
    paid loss minus the reserve held."

    Design: Difficulty/dual_variant_calc/pool_surplus_reserve_vs_loss_accounting
    """
    base = setup_under_review_claim(
        claim_overrides={"complaint": "transmission", "rental_days_claimed": 4, "towing_claimed": True},
        claim_lines=STANDARD_LINES,
        facility_overrides={"name": "Shop", "posted_labor_rate_cents_per_hour": 9500,
                            "network_status": "IN_NETWORK", "direct_pay_enrolled": True},
        pool_name="Pool S2",
        contract_overrides={"vin": "VINSURP0002"},
    )
    pool = validate_success(api.get_reinsurance_pool(base["pool"]["id"], ADMIN))
    assert pool["reserve_held_cents"] == 35349, \
        f"expected reserve_held 35349 while UNDER_REVIEW, got {pool['reserve_held_cents']}"
    assert pool["surplus_cents"] == -35349, \
        f"expected surplus -35349 on reserve-held basis, got {pool['surplus_cents']}"


# --- combinatorial_formula: labor rounding per-line allowed amounts ----------

def test_labor_round_per_line_allowed_amounts(api):
    """PRD §3.4: "that effective rate is multiplied by the line's `labor_hours`, and
    the product is rounded half up to whole cents to give the line's allowed amount."

    Design: Difficulty/combinatorial_formula/labor_round_per_line_then_sum
    """
    base = setup_under_review_claim(
        claim_overrides={"complaint": "noise"},
        claim_lines=[
            {"line_type": "LABOR", "labor_hours": 1.15, "covered": True},
            {"line_type": "LABOR", "labor_hours": 0.05, "covered": True},
        ],
        facility_overrides={"name": "Shop", "posted_labor_rate_cents_per_hour": 9500, "direct_pay_enrolled": True},
        pool_name="Pool R2",
        contract_overrides={"vin": "VINROUND002"},
    )
    lines, _meta = validate_paginated(api.list_claim_lines(base["claim"]["id"], ADJUSTER))
    by_hours = {round(float(l["labor_hours"]), 2): l["allowed_amount_cents"] for l in lines}
    assert by_hours[1.15] == 10925, f"expected line 1.15h allowed 10925, got {by_hours[1.15]}"
    assert by_hours[0.05] == 475, f"expected line 0.05h allowed 475, got {by_hours[0.05]}"


# --- combinatorial_formula: refund net flooring with fee/offset zero case ----

def test_refund_non_unwind_no_offset(api):
    """PRD §3.6: "for every other reason the claims offset is 0. The `net_refund_cents`
    is the gross refund minus the cancellation fee minus the claims offset, floored at
    0".

    Design: Difficulty/combinatorial_formula/refund_nested_min_max_with_fee_and_offset
    """
    base = setup_disbursed_standard(pool_name="Pool U2", vin="VINUNWIND02")
    set_clock("2027-01-01T00:00:00Z")
    canc = validate_success(api.create_cancellation(
        {"contract_id": base["contract"]["id"], "reason": "CUSTOMER_REQUEST", "request_date": "2027-01-01T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    approved = validate_success(api.approve_cancellation(canc["id"], CONTRACT_ADMIN))
    # gross 191333 (mileage basis dominates: miles_used 20000/100000=0.2 vs time 366/1800~0.203)
    # claims offset 0 (not DEALER_UNWIND); fee 5000 -> net = gross - 5000.
    assert approved["claims_offset_cents"] == 0, \
        f"non-unwind reason should yield offset 0, got {approved['claims_offset_cents']}"
    assert approved["net_refund_cents"] == approved["gross_refund_cents"] - 5000, \
        f"net should be gross - 5000 fee, got net {approved['net_refund_cents']} gross {approved['gross_refund_cents']}"


# --- non_linear_state_machine: parallel dims approve doesn't pay -------------

def test_approve_does_not_advance_payment_status(api):
    """PRD §3.4: "A claim carries two independent state dimensions that evolve
    separately." PRD §3.5: "Once a claim is approved, a `ClaimsAdjuster` authorizes
    it, which creates a repair authorization and is the moment the claim's payment
    dimension advances from `UNPAID` to `AUTHORIZED`."

    Design: Difficulty/non_linear_state_machine/claim_parallel_adjudication_and_payment_dimensions
    """
    base = setup_under_review_claim(
        claim_overrides={"complaint": "x"},
        claim_lines=[{"line_type": "PART", "part_number": "P-1", "requested_amount_cents": 30000, "covered": True}],
        facility_overrides={"name": "Shop", "posted_labor_rate_cents_per_hour": 9500, "direct_pay_enrolled": True},
        pool_name="Pool PD",
        contract_overrides={"vin": "VINPARD0001"},
    )
    approved = validate_success(api.approve_claim(base["claim"]["id"], ADJUSTER))
    assert approved["adjudication_status"] == "APPROVED", \
        f"expected APPROVED, got {approved['adjudication_status']}"
    assert approved["payment_status"] == "UNPAID", \
        f"approval must not move payment dimension; expected UNPAID, got {approved['payment_status']}"


# --- transitive_cascade: refund clawback ledger posting ---------------------

def test_refund_clawback_decreases_ceded_premium(api):
    """PRD §3.6: "a `REFUND_CLAWBACK` entry equal to the negative of the
    `net_refund_cents` is posted (decreasing the pool's `ceded_premium_cents` and
    recomputing surplus)".

    Design: Difficulty/transitive_cascade/refund_clawback_and_ancillary_refund_cascade
    """
    base = setup_active_contract(pool_name="Pool D2b", contract_overrides={"vin": "VIND200002"})
    set_clock("2026-01-20T00:00:00Z")
    canc = validate_success(api.create_cancellation(
        {"contract_id": base["contract"]["id"], "reason": "CUSTOMER_REQUEST", "request_date": "2026-01-20T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    validate_success(api.approve_cancellation(canc["id"], CONTRACT_ADMIN))
    validate_success(api.refund_cancellation(canc["id"], CONTRACT_ADMIN))
    pool = validate_success(api.get_reinsurance_pool(base["pool"]["id"], ADMIN))
    # FULL refund 240000 -> REFUND_CLAWBACK -240000 -> ceded_premium = -240000.
    assert pool["ceded_premium_cents"] == -240000, \
        f"expected ceded_premium -240000 after clawback, got {pool['ceded_premium_cents']}"


# --- priority_pair: start-review state-vs-safety (second angle) --------------

def test_start_review_pending_contract_surfaces_state_error_not_mileage(api):
    """PRD §3.7: "a disburse against a non-approved claim surfaces the claim-state
    error rather than a stale-version error." The same precedence principle puts the
    contract-active state error ahead of the mileage business check on start-review.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_start_review
    """
    pool = create_pool("Pool PR2")
    plan = create_active_plan()
    fac = create_facility(direct_pay_enrolled=True)
    contract = create_contract(plan["id"], pool["id"], vin="VINPRC00002")  # PENDING
    claim = validate_success(api.create_claim(
        {"contract_id": contract["id"], "repair_facility_id": fac["id"],
         "odometer_at_claim": 999999, "claim_date": "2026-02-01T00:00:00Z", "complaint": "x"}, ADJUSTER,
    ), expected_status=201)
    resp = api.start_review_claim(claim["id"], ADJUSTER)
    # Even with a wildly over-limit odometer, contract-active check (priority 6) wins.
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


# --- priority_pair: disburse safety-vs-referential (second angle) -----------

def test_disburse_oon_facility_with_stale_version_surfaces_facility_error(api):
    """PRD §3.5: "a `DIRECT_PAY` authorization whose facility is suspended or
    out-of-network is rejected with `ERR_FACILITY_NOT_DIRECT_PAY` (HTTP 422)."
    PRD §3.7: "the direct-pay facility check on disburse ... and the
    optimistic-concurrency check on disburse (`ERR_STALE_CONTRACT_VERSION`)" run in
    that order.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_disburse
    """
    base = setup_authorized_claim(
        claim_overrides={"complaint": "engine"},
        claim_lines=[{"line_type": "PART", "part_number": "EN-9", "requested_amount_cents": 50000, "covered": True}],
        facility_overrides={"name": "OON Shop", "posted_labor_rate_cents_per_hour": 9500,
                            "network_status": "OUT_OF_NETWORK", "direct_pay_enrolled": True},
        pool_name="Pool BR2",
        contract_overrides={"vin": "VINBRC00002"},
    )
    resp = api.disburse_repair_authorization(
        base["authorization"]["id"], {"expected_contract_version": base["contract_version"] - 5}, ADJUSTER,
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_DIRECT_PAY)


# --- boundary_precision: free-look zero-paid-claims partner (paid claim case) -

def test_free_look_window_with_paid_claim_falls_to_pro_rata(api):
    """PRD §3.6: "If the days in force is at most the 30-day free-look window and the
    contract's `paid_claim_total_cents` is exactly 0, the refund basis is `FULL`".
    A contract inside the window but with a paid claim therefore is NOT FULL.

    Design: Difficulty/boundary_precision_check/free_look_full_refund_zero_paid_claims_edge
    """
    base = setup_disbursed_standard(pool_name="Pool FL2", vin="VINFLC00002")
    # Within the 30-day free-look window, but the contract has a paid claim.
    set_clock("2026-01-20T00:00:00Z")
    canc = validate_success(api.create_cancellation(
        {"contract_id": base["contract"]["id"], "reason": "CUSTOMER_REQUEST", "request_date": "2026-01-20T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    approved = validate_success(api.approve_cancellation(canc["id"], CONTRACT_ADMIN))
    assert approved["refund_basis"] != "FULL", \
        f"paid_claim_total > 0 must disqualify FULL refund, got {approved['refund_basis']}"


# --- cross_entity_state_dependency: start-review under LAPSED contract -------

def test_start_review_rejected_when_contract_lapsed(api):
    """PRD §3.4: "The referenced contract must be in `ACTIVE` status, or the request
    is rejected with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_start_review_requires_contract_active
    """
    base = setup_active_contract(pool_name="Pool CE1b", contract_overrides={"vin": "VINCE100002"}, with_facility=True)
    claim = validate_success(api.create_claim(
        {"contract_id": base["contract"]["id"], "repair_facility_id": base["facility"]["id"],
         "odometer_at_claim": 40000, "claim_date": "2026-02-01T00:00:00Z", "complaint": "engine"}, ADJUSTER,
    ), expected_status=201)
    # Lapse the contract (no open claims yet, so allowed), then start-review must fail.
    validate_success(api.lapse_contract(base["contract"]["id"], CONTRACT_ADMIN))
    resp = api.start_review_claim(claim["id"], ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


# --- cross_entity_state_dependency: disburse facility (suspended angle) ------

def test_disburse_in_network_enrolled_facility_succeeds(api):
    """PRD §3.5: "On a successful disbursement the payout is paid out — to the facility
    when `pay_target` is `DIRECT_PAY` ... the claim's `payment_status` is set to
    `PAID`". A facility that IS ACTIVE and IN_NETWORK and enrolled clears the
    direct-pay check, confirming the rule is the facility-state gate (not a blanket ban).

    Design: Difficulty/cross_entity_state_dependency/disburse_requires_facility_active_enrolled
    """
    base = setup_disbursed_standard(pool_name="Pool CE2b", vin="VINCE200002")
    auth = validate_success(api.get_repair_authorization(base["authorization"]["id"], ADJUSTER))
    assert auth["status"] == "DISBURSED", \
        f"enrolled IN_NETWORK ACTIVE facility should disburse, got {auth['status']}"
    assert auth["pay_target"] == "DIRECT_PAY", f"expected DIRECT_PAY, got {auth['pay_target']}"


# --- resource_temporal_overlap: free-look just-before-boundary --------------

def test_free_look_one_day_before_boundary_is_full(api):
    """PRD §3.6: "If the days in force is at most the 30-day free-look window ... the
    refund basis is `FULL`".

    Design: Difficulty/resource_temporal_overlap/free_look_window_inclusive_boundary
    """
    base = setup_active_contract(pool_name="Pool TO1b", contract_overrides={"vin": "VINTO100002"})
    set_clock("2026-01-30T00:00:00Z")  # 29 days in force
    canc = validate_success(api.create_cancellation(
        {"contract_id": base["contract"]["id"], "reason": "CUSTOMER_REQUEST", "request_date": "2026-01-30T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    approved = validate_success(api.approve_cancellation(canc["id"], CONTRACT_ADMIN))
    assert approved["refund_basis"] == "FULL", f"29 days within free-look -> FULL, got {approved['refund_basis']}"


# --- resource_temporal_overlap: term expiry releases reserves ---------------

def test_coverage_term_before_expiry_still_active(api):
    """PRD §3.2: "when the months elapsed since `sale_date` is at least the plan's
    `term_months`, an `ACTIVE` contract automatically transitions to the terminal
    `EXPIRED` status." Below that boundary the contract stays ACTIVE.

    Design: Difficulty/resource_temporal_overlap/coverage_term_expiry_elapsed_months_boundary
    """
    base = setup_active_contract(pool_name="Pool TO2b", contract_overrides={"vin": "VINTO200002"})
    set_clock("2030-12-01T00:00:00Z")  # ~59 months elapsed, below 60
    contract = validate_success(api.get_contract(base["contract"]["id"], CONTRACT_ADMIN))
    assert contract["status"] == "ACTIVE", \
        f"months_elapsed below term_months should stay ACTIVE, got {contract['status']}"


# --- compensating_invariant: pool paid_loss (surplus angle) -----------------

def test_reverse_restores_pool_surplus(api):
    """PRD §3.5: "Reversal ... posts a `LOSS_REVERSED` entry equal to the negative of
    the `total_payout_cents` (decreasing the pool's `paid_loss_cents` and recomputing
    surplus)".

    Design: Difficulty/compensating_invariant/reverse_authorization_pool_paid_loss_conserved
    """
    base = setup_disbursed_standard(pool_name="Pool CI1b", vin="VINCI100002")
    pool_before = validate_success(api.get_reinsurance_pool(base["pool"]["id"], ADMIN))
    assert pool_before["paid_loss_cents"] == 48349
    validate_success(api.reverse_repair_authorization(base["authorization"]["id"], ADJUSTER))
    pool_after = validate_success(api.get_reinsurance_pool(base["pool"]["id"], ADMIN))
    assert pool_after["paid_loss_cents"] == 0, \
        f"LOSS_PAID + LOSS_REVERSED must net to 0, got {pool_after['paid_loss_cents']}"


# --- compensating_invariant: contract paid_claim_total (version angle) -------

def test_reverse_sets_claim_void_and_zeroes_contract_total(api):
    """PRD §3.5: "Reversal sets the claim's `payment_status` to `VOID` ... decrements
    the contract's `paid_claim_total_cents` by the `total_payout_cents`".

    Design: Difficulty/compensating_invariant/reverse_authorization_contract_paid_claim_total_conserved
    """
    base = setup_disbursed_standard(pool_name="Pool CI2b", vin="VINCI200002")
    contract_before = validate_success(api.get_contract(base["contract"]["id"], ADJUSTER))
    assert contract_before["paid_claim_total_cents"] == 48349
    validate_success(api.reverse_repair_authorization(base["authorization"]["id"], ADJUSTER))
    contract_after = validate_success(api.get_contract(base["contract"]["id"], ADJUSTER))
    assert contract_after["paid_claim_total_cents"] == 0, \
        f"reverse must zero paid_claim_total (48349 + -48349), got {contract_after['paid_claim_total_cents']}"
    claim = validate_success(api.get_claim(base["claim"]["id"], ADJUSTER))
    assert claim["payment_status"] == "VOID", f"expected VOID, got {claim['payment_status']}"
