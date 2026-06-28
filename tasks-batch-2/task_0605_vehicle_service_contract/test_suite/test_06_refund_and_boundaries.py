"""Pro-rata refund variants, free-look boundaries, refund cascade, term expiry,
and the start-review cross-entity / priority instances.

Translates difficulty-design dual_variant_calc (refund), combinatorial_formula
(refund), transitive_cascade (refund cascade), boundary_precision_check,
resource_temporal_overlap, cross_entity_state_dependency (start-review), and
priority_pair (start-review) instances.
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    ApiErrorId,
)
from test_helpers.fixtures import (
    api_client,
    create_pool,
    create_active_plan,
    create_facility,
    create_contract,
    setup_active_contract,
    setup_requested_cancellation,
    setup_disbursed_standard,
    set_clock,
    STANDARD_LINES,
)

ADMIN = TEST_USERS["admin_underwriter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# --- dual_variant_calc (refund time vs mileage) -----------------------------

def test_refund_basis_time_when_low_mileage_long_elapsed(api):
    """PRD §3.6: "The earned fraction is the greater of the time fraction and the
    mileage fraction — deliberately the greater fraction, hence the smaller refund.
    When the mileage fraction is at least the time fraction the refund basis is
    `PRO_RATA_MILEAGE`; otherwise it is `PRO_RATA_TIME`."
    PRD §3.6: "The gross refund is the contract's `sale_price_cents` multiplied by one
    minus the earned fraction, with that product rounded half up to whole cents".

    Design: Difficulty/dual_variant_calc/refund_basis_time_vs_mileage_on_cancellation
    """
    base = setup_active_contract(
        pool_name="Pool A",
        contract_overrides={"vin": "VINTIME0001", "odometer_at_sale": 20000, "sale_price_cents": 240000},
    )
    set_clock("2027-01-01T00:00:00Z")  # 365 days in force; no claims so miles_used=0
    canc = validate_success(api.create_cancellation(
        {"contract_id": base["contract"]["id"], "reason": "CUSTOMER_REQUEST", "request_date": "2027-01-01T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    approved = validate_success(api.approve_cancellation(canc["id"], CONTRACT_ADMIN))
    assert approved["refund_basis"] == "PRO_RATA_TIME", \
        f"expected PRO_RATA_TIME, got {approved['refund_basis']}"
    assert approved["gross_refund_cents"] == 191333, \
        f"expected gross 191333, got {approved['gross_refund_cents']}"
    assert approved["net_refund_cents"] == 186333, \
        f"expected net 186333, got {approved['net_refund_cents']}"


# --- combinatorial_formula (refund with fee + offset) -----------------------

def test_refund_dealer_unwind_nets_paid_claims(api):
    """PRD §3.6: "A claims offset applies only when the reason is `DEALER_UNWIND`, in
    which case the `claims_offset_cents` equals the contract's `paid_claim_total_cents`
    ... The `net_refund_cents` is the gross refund minus the cancellation fee minus
    the claims offset, floored at 0".
    PRD §3.6: "the `cancellation_fee_cents` is 0 when the refund basis is `FULL` and
    is 5000 cents otherwise."

    Design: Difficulty/combinatorial_formula/refund_nested_min_max_with_fee_and_offset
    """
    base = setup_disbursed_standard(pool_name="Pool U", vin="VINUNWIND01")
    set_clock("2027-01-01T00:00:00Z")
    canc = validate_success(api.create_cancellation(
        {"contract_id": base["contract"]["id"], "reason": "DEALER_UNWIND", "request_date": "2027-01-01T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    approved = validate_success(api.approve_cancellation(canc["id"], CONTRACT_ADMIN))
    assert approved["gross_refund_cents"] == 191333, f"expected gross 191333, got {approved['gross_refund_cents']}"
    assert approved["cancellation_fee_cents"] == 5000, f"expected fee 5000, got {approved['cancellation_fee_cents']}"
    assert approved["claims_offset_cents"] == 48349, \
        f"expected claims offset 48349, got {approved['claims_offset_cents']}"
    assert approved["net_refund_cents"] == 137984, f"expected net 137984, got {approved['net_refund_cents']}"


# --- transitive_cascade (refund clawback + ancillary refund) ----------------

def test_refund_cascade_cancels_contract_and_refunds_ancillary(api):
    """PRD §3.6: "the contract transitions to the terminal `CANCELLED` status, a
    `REFUND_CLAWBACK` entry equal to the negative of the `net_refund_cents` is posted
    ... and every `BUNDLED` refundable ancillary product on the contract is set to
    `REFUNDED`."

    Design: Difficulty/transitive_cascade/refund_clawback_and_ancillary_refund_cascade
    """
    pool = create_pool("Pool D2")
    plan = create_active_plan()
    contract = create_contract(plan["id"], pool["id"], vin="VIND200001")
    anc = validate_success(api.create_ancillary_product(
        {"contract_id": contract["id"], "product_type": "GAP", "premium_cents": 30000,
         "gap_cap_cents": 500000, "refundable": True}, CONTRACT_ADMIN,
    ), expected_status=201)
    validate_success(api.activate_contract(contract["id"], CONTRACT_ADMIN))
    set_clock("2026-01-20T00:00:00Z")
    canc = validate_success(api.create_cancellation(
        {"contract_id": contract["id"], "reason": "CUSTOMER_REQUEST", "request_date": "2026-01-20T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    validate_success(api.approve_cancellation(canc["id"], CONTRACT_ADMIN))
    validate_success(api.refund_cancellation(canc["id"], CONTRACT_ADMIN))
    contract_after = validate_success(api.get_contract(contract["id"], CONTRACT_ADMIN))
    assert contract_after["status"] == "CANCELLED", \
        f"hop1: expected CANCELLED, got {contract_after['status']}"
    anc_after = validate_success(api.get_ancillary_product(anc["id"], CONTRACT_ADMIN))
    assert anc_after["status"] == "REFUNDED", f"hop2: expected REFUNDED ancillary, got {anc_after['status']}"


# --- boundary_precision_check -----------------------------------------------

def test_mileage_coverage_boundary_at_term_limit(api):
    """PRD §3.4: "the claim's odometer must be within coverage: `odometer_at_claim`
    must be at most the contract's `odometer_at_sale` plus the plan's `term_miles`,
    or the request is rejected with `ERR_MILEAGE_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/mileage_coverage_boundary_at_term_limit
    """
    pool = create_pool("Pool BD")
    plan = create_active_plan()
    fac = create_facility(direct_pay_enrolled=True)
    contract = create_contract(plan["id"], pool["id"], vin="VINBDC00001", odometer_at_sale=20000)
    validate_success(api.activate_contract(contract["id"], CONTRACT_ADMIN))
    claim = validate_success(api.create_claim(
        {"contract_id": contract["id"], "repair_facility_id": fac["id"],
         "odometer_at_claim": 120000, "claim_date": "2026-02-01T00:00:00Z", "complaint": "engine"}, ADJUSTER,
    ), expected_status=201)
    api.create_claim_line(claim["id"], {"line_type": "PART", "part_number": "EN-1",
                                       "requested_amount_cents": 50000, "covered": True}, ADJUSTER)
    # 20000 + 100000 = 120000 == boundary, covered (<= passes)
    reviewed = validate_success(api.start_review_claim(claim["id"], ADJUSTER))
    assert reviewed["adjudication_status"] == "UNDER_REVIEW", \
        f"odometer 120000 == boundary should be covered, got {reviewed['adjudication_status']}"


def test_mileage_coverage_one_over_boundary_rejected(api):
    """PRD §3.4: "`odometer_at_claim` must be at most the contract's `odometer_at_sale`
    plus the plan's `term_miles`, or the request is rejected with `ERR_MILEAGE_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/mileage_coverage_boundary_at_term_limit
    """
    pool = create_pool("Pool BD2")
    plan = create_active_plan()
    fac = create_facility(direct_pay_enrolled=True)
    contract = create_contract(plan["id"], pool["id"], vin="VINBDC00002", odometer_at_sale=20000)
    validate_success(api.activate_contract(contract["id"], CONTRACT_ADMIN))
    claim = validate_success(api.create_claim(
        {"contract_id": contract["id"], "repair_facility_id": fac["id"],
         "odometer_at_claim": 120001, "claim_date": "2026-02-01T00:00:00Z", "complaint": "engine"}, ADJUSTER,
    ), expected_status=201)
    api.create_claim_line(claim["id"], {"line_type": "PART", "part_number": "EN-1",
                                       "requested_amount_cents": 50000, "covered": True}, ADJUSTER)
    resp = api.start_review_claim(claim["id"], ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_MILEAGE_EXCEEDED)


def test_free_look_full_refund_zero_paid_claims(api):
    """PRD §3.6: "If the days in force is at most the 30-day free-look window and the
    contract's `paid_claim_total_cents` is exactly 0, the refund basis is `FULL` and
    the gross refund equals the contract's full `sale_price_cents`."

    Design: Difficulty/boundary_precision_check/free_look_full_refund_zero_paid_claims_edge
    """
    base = setup_active_contract(pool_name="Pool FL", contract_overrides={"vin": "VINFLC00001"})
    set_clock("2026-01-20T00:00:00Z")  # 19 days in force
    canc = validate_success(api.create_cancellation(
        {"contract_id": base["contract"]["id"], "reason": "CUSTOMER_REQUEST", "request_date": "2026-01-20T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    approved = validate_success(api.approve_cancellation(canc["id"], CONTRACT_ADMIN))
    assert approved["refund_basis"] == "FULL", f"expected FULL, got {approved['refund_basis']}"
    assert approved["cancellation_fee_cents"] == 0, f"expected fee 0, got {approved['cancellation_fee_cents']}"
    assert approved["net_refund_cents"] == 240000, f"expected net 240000, got {approved['net_refund_cents']}"


# --- resource_temporal_overlap ----------------------------------------------

def test_free_look_window_inclusive_boundary(api):
    """PRD §3.6: "If the days in force is at most the 30-day free-look window and the
    contract's `paid_claim_total_cents` is exactly 0, the refund basis is `FULL`".

    Design: Difficulty/resource_temporal_overlap/free_look_window_inclusive_boundary
    """
    base = setup_active_contract(pool_name="Pool TO1", contract_overrides={"vin": "VINTO100001"})
    set_clock("2026-01-31T00:00:00Z")  # exactly 30 days
    canc = validate_success(api.create_cancellation(
        {"contract_id": base["contract"]["id"], "reason": "CUSTOMER_REQUEST", "request_date": "2026-01-31T00:00:00Z"},
        CONTRACT_ADMIN,
    ), expected_status=201)
    approved = validate_success(api.approve_cancellation(canc["id"], CONTRACT_ADMIN))
    assert approved["refund_basis"] == "FULL", \
        f"30 days is inclusive boundary -> FULL, got {approved['refund_basis']}"
    assert approved["net_refund_cents"] == 240000, f"expected net 240000, got {approved['net_refund_cents']}"


def test_coverage_term_expiry_elapsed_months_boundary(api):
    """PRD §3.2: "Reading a contract recomputes its `earned_premium_cents` against the
    current clock and may automatically expire it: when the months elapsed since
    `sale_date` is at least the plan's `term_months`, an `ACTIVE` contract
    automatically transitions to the terminal `EXPIRED` status."

    Design: Difficulty/resource_temporal_overlap/coverage_term_expiry_elapsed_months_boundary
    """
    base = setup_active_contract(pool_name="Pool TO2", contract_overrides={"vin": "VINTO200001"})
    set_clock("2031-01-01T00:00:00Z")  # 60 months elapsed == term_months
    contract = validate_success(api.get_contract(base["contract"]["id"], CONTRACT_ADMIN))
    assert contract["status"] == "EXPIRED", \
        f"months_elapsed 60 >= term_months 60 should auto-EXPIRE, got {contract['status']}"


# --- cross_entity_state_dependency (start-review) ---------------------------

def test_claim_start_review_requires_contract_active(api):
    """PRD §3.4: "The referenced contract must be in `ACTIVE` status, or the request
    is rejected with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_start_review_requires_contract_active
    """
    pool = create_pool("Pool CE1")
    plan = create_active_plan()
    fac = create_facility(direct_pay_enrolled=True)
    contract = create_contract(plan["id"], pool["id"], vin="VINCE100001")  # left PENDING
    claim = validate_success(api.create_claim(
        {"contract_id": contract["id"], "repair_facility_id": fac["id"],
         "odometer_at_claim": 40000, "claim_date": "2026-02-01T00:00:00Z", "complaint": "engine"}, ADJUSTER,
    ), expected_status=201)
    resp = api.start_review_claim(claim["id"], ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


# --- priority_pair_validation_conflict (start-review) -----------------------

def test_start_review_contract_active_check_precedes_mileage(api):
    """PRD §3.7: "the contract-active check on start-review
    (`ERR_CONTRACT_NOT_ACTIVE`) ... [then] the mileage-coverage check on start-review
    (`ERR_MILEAGE_EXCEEDED`)" — the contract-active check is evaluated first.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_start_review
    """
    pool = create_pool("Pool PR")
    plan = create_active_plan()
    fac = create_facility(direct_pay_enrolled=True)
    contract = create_contract(plan["id"], pool["id"], vin="VINPRC00001")  # left PENDING
    claim = validate_success(api.create_claim(
        {"contract_id": contract["id"], "repair_facility_id": fac["id"],
         "odometer_at_claim": 200000, "claim_date": "2026-02-01T00:00:00Z", "complaint": "engine"}, ADJUSTER,
    ), expected_status=201)
    resp = api.start_review_claim(claim["id"], ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
