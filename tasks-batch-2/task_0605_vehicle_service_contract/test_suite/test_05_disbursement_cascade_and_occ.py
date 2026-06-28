"""Disbursement cascade, OCC on contract version, cross-entity disburse guards,
parallel claim dimensions, and compensating reversal invariants.

Translates difficulty-design transitive_cascade, non_linear_state_machine
(parallel dims), cross_entity_state_dependency (disburse), priority_pair
(disburse), compensating_invariant, dual_variant (pool surplus) instances, plus
corner-design cross_cutting_complexity_layers (OCC) and rbac (auditor) instances.
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    ApiErrorId,
)
from test_helpers.fixtures import (
    setup_authorized_claim,
    setup_disbursed_standard,
    STANDARD_LINES,
    api_client,
)

ADMIN = TEST_USERS["admin_underwriter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# --- transitive_cascade -----------------------------------------------------

def test_disburse_three_hop_cascade(api):
    """PRD §3.5: "First, the claim's `payment_status` is set to `PAID`, the claim's
    reserve is released by posting a `RESERVE_RELEASE` entry equal to the negative of
    the claim's `reserve_cents` (decreasing the pool's `reserve_held_cents`) and the
    claim's `reserve_cents` is set to 0. Second, a `LOSS_PAID` entry equal to the
    positive `total_payout_cents` is posted, increasing the pool's `paid_loss_cents`
    and recomputing surplus. Third, the contract's `paid_claim_total_cents` is
    increased by the `total_payout_cents`."

    Design: Difficulty/transitive_cascade/disburse_reserve_release_loss_paid_contract_ledger
    """
    base = setup_disbursed_standard(pool_name="Pool D3", vin="VIND300001")
    pool = validate_success(api.get_reinsurance_pool(base["pool"]["id"], ADMIN))
    assert pool["reserve_held_cents"] == 0, f"hop1: expected reserve 0, got {pool['reserve_held_cents']}"
    assert pool["paid_loss_cents"] == 48349, f"hop2: expected paid_loss 48349, got {pool['paid_loss_cents']}"
    assert base["contract"]["paid_claim_total_cents"] == 48349, \
        f"hop3: expected paid_claim_total 48349, got {base['contract']['paid_claim_total_cents']}"


def test_disburse_loss_paid_posting_amount(api):
    """PRD §3.5: "a `LOSS_PAID` entry equal to the positive `total_payout_cents` is
    posted, increasing the pool's `paid_loss_cents` and recomputing surplus."

    Design: Difficulty/transitive_cascade/disburse_reserve_release_loss_paid_contract_ledger
    """
    base = setup_disbursed_standard(pool_name="Pool D3b", vin="VIND300002")
    assert base["authorization"]["total_payout_cents"] == 48349, \
        f"expected total payout 48349, got {base['authorization']['total_payout_cents']}"
    pool = validate_success(api.get_reinsurance_pool(base["pool"]["id"], ADMIN))
    assert pool["paid_loss_cents"] == 48349, f"expected paid_loss 48349, got {pool['paid_loss_cents']}"


# --- dual_variant_calc (pool surplus reserve vs loss) -----------------------

def test_pool_surplus_reserve_then_loss_basis(api):
    """PRD §2.9: "The `surplus_cents` is then the ceded premium minus the paid loss
    minus the reserve held."
    PRD §3.5: "a `LOSS_PAID` entry equal to the positive `total_payout_cents` is
    posted, increasing the pool's `paid_loss_cents` and recomputing surplus."

    Design: Difficulty/dual_variant_calc/pool_surplus_reserve_vs_loss_accounting
    """
    base = setup_authorized_claim(
        claim_overrides={"complaint": "transmission", "rental_days_claimed": 4, "towing_claimed": True},
        claim_lines=STANDARD_LINES,
        facility_overrides={"name": "Shop", "posted_labor_rate_cents_per_hour": 9500,
                            "network_status": "IN_NETWORK", "direct_pay_enrolled": True},
        pool_name="Pool S",
        contract_overrides={"vin": "VINSURP0001"},
    )
    pool_pre = validate_success(api.get_reinsurance_pool(base["pool"]["id"], ADMIN))
    assert pool_pre["surplus_cents"] == -35349, \
        f"reserve-held basis: expected surplus -35349, got {pool_pre['surplus_cents']}"
    validate_success(api.disburse_repair_authorization(
        base["authorization"]["id"], {"expected_contract_version": base["contract_version"]}, ADJUSTER,
    ))
    pool_post = validate_success(api.get_reinsurance_pool(base["pool"]["id"], ADMIN))
    assert pool_post["surplus_cents"] == -48349, \
        f"paid-loss basis: expected surplus -48349, got {pool_post['surplus_cents']}"
    assert pool_post["reserve_held_cents"] == 0, \
        f"expected reserve 0 after disburse, got {pool_post['reserve_held_cents']}"


# --- non_linear_state_machine (parallel dimensions) -------------------------

def test_claim_parallel_adjudication_and_payment_dimensions(api):
    """PRD §3.4: "A claim carries two independent state dimensions that evolve
    separately. The adjudication dimension, `adjudication_status`, runs `SUBMITTED`
    → `UNDER_REVIEW` → `APPROVED` or `DENIED`. The payment dimension,
    `payment_status`, runs `UNPAID` → `AUTHORIZED` → `PAID`".

    Design: Difficulty/non_linear_state_machine/claim_parallel_adjudication_and_payment_dimensions
    """
    base = setup_disbursed_standard(pool_name="Pool P", vin="VINPAR00001")
    claim = validate_success(api.get_claim(base["claim"]["id"], ADJUSTER))
    assert claim["adjudication_status"] == "APPROVED", \
        f"adjudication dimension should stay APPROVED, got {claim['adjudication_status']}"
    assert claim["payment_status"] == "PAID", \
        f"payment dimension should advance to PAID, got {claim['payment_status']}"


# --- cross_entity_state_dependency (disburse) -------------------------------

def test_disburse_requires_facility_active_enrolled(api):
    """PRD §3.5: "when the authorization's `pay_target` is `DIRECT_PAY`, the facility
    must additionally be `ACTIVE` and `IN_NETWORK` ...; a `DIRECT_PAY` authorization
    whose facility is suspended or out-of-network is rejected with
    `ERR_FACILITY_NOT_DIRECT_PAY` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/disburse_requires_facility_active_enrolled
    """
    base = setup_authorized_claim(
        claim_overrides={"complaint": "engine"},
        claim_lines=[{"line_type": "PART", "part_number": "EN-2", "requested_amount_cents": 50000, "covered": True}],
        facility_overrides={"name": "OON Shop", "posted_labor_rate_cents_per_hour": 9500,
                            "network_status": "OUT_OF_NETWORK", "direct_pay_enrolled": True},
        pool_name="Pool CE2",
        contract_overrides={"vin": "VINCE200001"},
    )
    resp = api.disburse_repair_authorization(
        base["authorization"]["id"], {"expected_contract_version": base["contract_version"]}, ADJUSTER,
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_DIRECT_PAY)


# --- priority_pair_validation_conflict (disburse) ---------------------------

def test_disburse_facility_check_precedes_occ(api):
    """PRD §3.7: "the direct-pay facility check on disburse
    (`ERR_FACILITY_NOT_DIRECT_PAY`) ... and the optimistic-concurrency check on
    disburse (`ERR_STALE_CONTRACT_VERSION`)" are evaluated in that order, so the
    facility check surfaces before the stale-version check.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_disburse
    """
    base = setup_authorized_claim(
        claim_overrides={"complaint": "transmission"},
        claim_lines=[{"line_type": "PART", "part_number": "TX-900", "requested_amount_cents": 13499, "covered": True}],
        facility_overrides={"name": "OON Shop", "posted_labor_rate_cents_per_hour": 9500,
                            "network_status": "OUT_OF_NETWORK", "direct_pay_enrolled": True},
        pool_name="Pool BR",
        contract_overrides={"vin": "VINBRC00001"},
    )
    stale_version = base["contract_version"] - 1
    resp = api.disburse_repair_authorization(
        base["authorization"]["id"], {"expected_contract_version": stale_version}, ADJUSTER,
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_DIRECT_PAY)


# --- OCC ---------------------------------------------------------------------

def _setup_two_authorized_on_same_contract(pool_name, vin):
    """Build two approved+authorized claims sharing one contract."""
    from test_helpers.fixtures import create_pool, create_active_plan, create_facility, create_contract
    pool = create_pool(pool_name)
    plan = create_active_plan()
    fac = create_facility(network_status="IN_NETWORK", direct_pay_enrolled=True)
    contract = create_contract(plan["id"], pool["id"], vin=vin)
    validate_success(api_client.activate_contract(contract["id"], CONTRACT_ADMIN))

    def make(complaint, odo, part, amount):
        claim = validate_success(api_client.create_claim(
            {"contract_id": contract["id"], "repair_facility_id": fac["id"],
             "odometer_at_claim": odo, "claim_date": "2026-02-01T00:00:00Z", "complaint": complaint}, ADJUSTER,
        ), expected_status=201)
        api_client.create_claim_line(claim["id"], {"line_type": "PART", "part_number": part,
                                                   "requested_amount_cents": amount, "covered": True}, ADJUSTER)
        api_client.start_review_claim(claim["id"], ADJUSTER)
        api_client.approve_claim(claim["id"], ADJUSTER)
        auth = validate_success(api_client.authorize_claim(claim["id"], ADJUSTER), expected_status=201)
        return auth

    auth1 = make("c1", 40000, "O-1", 50000)
    auth2 = make("c2", 45000, "O-2", 40000)
    contract = validate_success(api_client.get_contract(contract["id"], ADJUSTER))
    return contract, auth1, auth2


def test_occ_stale_version_rejected_on_second_disburse(api):
    """PRD §2.11: "If that value does not equal the contract's current `version`, the
    disbursement is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). ... a prior
    disburse or reverse on any sibling authorization for the same contract bumps the
    contract's `version` ... so a disburse still carrying a previously observed version
    is acting on a stale view of that contract's claim ledger and must be refused."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_disburse
    """
    contract, auth1, auth2 = _setup_two_authorized_on_same_contract("Pool OCC", "VINOCC0001")
    cver = contract["version"]
    validate_success(api.disburse_repair_authorization(auth1["id"], {"expected_contract_version": cver}, ADJUSTER))
    resp = api.disburse_repair_authorization(auth2["id"], {"expected_contract_version": cver}, ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION)


# --- compensating_invariant -------------------------------------------------

def test_reverse_authorization_pool_paid_loss_conserved(api):
    """PRD §3.5: "Reversal sets the claim's `payment_status` to `VOID`, posts a
    `LOSS_REVERSED` entry equal to the negative of the `total_payout_cents`
    (decreasing the pool's `paid_loss_cents` and recomputing surplus)".

    Design: Difficulty/compensating_invariant/reverse_authorization_pool_paid_loss_conserved
    """
    base = setup_disbursed_standard(pool_name="Pool CI1", vin="VINCI100001")
    validate_success(api.reverse_repair_authorization(base["authorization"]["id"], ADJUSTER))
    pool = validate_success(api.get_reinsurance_pool(base["pool"]["id"], ADMIN))
    assert pool["paid_loss_cents"] == 0, \
        f"expected paid_loss 0 after reverse (48349 + -48349), got {pool['paid_loss_cents']}"
    claim = validate_success(api.get_claim(base["claim"]["id"], ADJUSTER))
    assert claim["payment_status"] == "VOID", f"expected payment VOID, got {claim['payment_status']}"


def test_reverse_authorization_contract_paid_claim_total_conserved(api):
    """PRD §3.5: "Reversal ... decrements the contract's `paid_claim_total_cents` by
    the `total_payout_cents`, and increments the contract's `version`."

    Design: Difficulty/compensating_invariant/reverse_authorization_contract_paid_claim_total_conserved
    """
    base = setup_disbursed_standard(pool_name="Pool CI2", vin="VINCI200001")
    validate_success(api.reverse_repair_authorization(base["authorization"]["id"], ADJUSTER))
    contract = validate_success(api.get_contract(base["contract"]["id"], ADJUSTER))
    assert contract["paid_claim_total_cents"] == 0, \
        f"expected paid_claim_total 0 after reverse (48349 + -48349), got {contract['paid_claim_total_cents']}"


# --- rbac (auditor) ---------------------------------------------------------

def test_auditor_cannot_disburse(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.7: "The `Auditor` role sits across all of this with read-only access ...
    but performs no mutations."

    Design: Corner/rbac/auditor_cannot_disburse
    """
    base = setup_authorized_claim(
        claim_overrides={"complaint": "x"},
        claim_lines=[{"line_type": "PART", "part_number": "AU-1", "requested_amount_cents": 50000, "covered": True}],
        facility_overrides={"name": "Shop", "posted_labor_rate_cents_per_hour": 9500,
                            "network_status": "IN_NETWORK", "direct_pay_enrolled": True},
        pool_name="Pool AU",
        contract_overrides={"vin": "VINAU00001"},
    )
    resp = api.disburse_repair_authorization(
        base["authorization"]["id"], {"expected_contract_version": base["contract_version"]}, AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
