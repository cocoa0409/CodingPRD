"""Disbursement waterfall, cascades, four-eyes, seniority, and compensation."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_disbursement_payload,
    setup_certified_district, capture_increment, register_bond, accrue, disburse,
    register_developer_note, create_developer_entity, get_fund, fund_version,
    district_version, make_admin_headers, ADMIN_1_ID, ADMIN_2_ID,
)

ADMIN = TEST_USERS["municipal_admin_headers"]
CLERK = TEST_USERS["county_clerk_headers"]
SINGLE = [("School", "SCHOOL", 0.05)]


def _funded_district_with_registered_bond(principal_cents=20_000_000, interest_rate_bps=0,
                                          bodies=None, current_eav_cents=1_500_000_000,
                                          annual_cap_cents=None):
    """Certified district + 2026 increment + one registered SENIOR bond (admin-1)."""
    ctx = setup_certified_district(bodies=bodies or SINGLE, base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, current_eav_cents)
    bond = register_bond(d_id, principal_cents=principal_cents,
                         interest_rate_bps=interest_rate_bps,
                         final_maturity_tax_year=2040, annual_cap_cents=annual_cap_cents,
                         priority_rank=1)
    return d_id, bond


# ─── Difficulty: combinatorial formula — min-of-three + interest first ─────

def test_disbursement_splits_interest_before_principal():
    """PRD 3.4: "the `interest_portion_cents` is the smaller of the `amount_cents` and
    the obligation's current `accrued_interest_cents`, and the
    `principal_portion_cents` is whatever `amount_cents` remains after the interest
    portion."

    Design: Difficulty/combinatorial_formula/disbursement_min_of_three_with_interest_first
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # aggregate 0.08
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_500_000_000)  # fund 38,800,000
    bond = register_bond(d_id, principal_cents=20_000_000, interest_rate_bps=500,
                         final_maturity_tax_year=2040, priority_rank=1)
    accrue(bond["id"], 2026)  # accrued 1,000,000; outstanding 21,000,000
    disb = disburse(bond["id"], 5_000_000, 2026, d_id, actor_id=ADMIN_2_ID)
    assert disb["interest_portion_cents"] == 1_000_000
    assert disb["principal_portion_cents"] == 4_000_000


def test_disbursement_reduces_obligation_and_fund():
    """PRD 3.4: "The obligation's `accrued_interest_cents` is reduced by the interest
    portion, its `principal_remaining_cents` by the principal portion, and its
    `outstanding_balance_cents` by the full amount."
    PRD 3.4: "The fund's `balance_cents` is reduced by the amount, its
    `lifetime_disbursed_cents` is increased by the amount".

    Design: Difficulty/combinatorial_formula/disbursement_min_of_three_with_interest_first
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # aggregate 0.08
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_500_000_000)
    bond = register_bond(d_id, principal_cents=20_000_000, interest_rate_bps=500,
                         final_maturity_tax_year=2040, priority_rank=1)
    accrue(bond["id"], 2026)
    disburse(bond["id"], 5_000_000, 2026, d_id, actor_id=ADMIN_2_ID)
    updated = validate_success(api_client.get_obligation(bond["id"], ADMIN))
    assert updated["accrued_interest_cents"] == 0
    assert updated["principal_remaining_cents"] == 16_000_000
    assert updated["outstanding_balance_cents"] == 16_000_000
    assert get_fund(d_id)["balance_cents"] == 33_800_000


# ─── Difficulty: transitive cascade — disburse satisfies & clears district ─

def test_full_disbursement_satisfies_obligation():
    """PRD 3.4: "If that brings `outstanding_balance_cents` to exactly zero, the
    obligation automatically advances from `REGISTERED` to `SATISFIED`, and the
    district's `obligations_cleared` flag is re-evaluated."

    Design: Difficulty/transitive_cascade/disbursement_satisfies_and_clears_district
    """
    d_id, bond = _funded_district_with_registered_bond(
        principal_cents=20_000_000, bodies=SINGLE, current_eav_cents=1_500_000_000)
    disb = disburse(bond["id"], 20_000_000, 2026, d_id, actor_id=ADMIN_2_ID)
    assert disb["principal_portion_cents"] == 20_000_000
    updated = validate_success(api_client.get_obligation(bond["id"], ADMIN))
    assert updated["outstanding_balance_cents"] == 0
    assert updated["status"] == "SATISFIED"


def test_full_disbursement_sets_obligations_cleared_flag():
    """PRD 2.9: "A disbursement that drives an obligation's `outstanding_balance_cents`
    to exactly zero automatically transitions that obligation from `REGISTERED` to
    `SATISFIED`, and the system then re-evaluates whether every obligation of the
    district has reached a terminal state to keep the district's `obligations_cleared`
    flag current."

    Design: Difficulty/transitive_cascade/disbursement_satisfies_and_clears_district
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # aggregate 0.08 fund 38,800,000
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_500_000_000)
    bond = register_bond(d_id, principal_cents=20_000_000, final_maturity_tax_year=2040,
                         priority_rank=1)
    disburse(bond["id"], 20_000_000, 2026, d_id, actor_id=ADMIN_2_ID)
    district = validate_success(api_client.get_district(d_id, ADMIN))
    assert district["obligations_cleared"] is True
    assert get_fund(d_id)["balance_cents"] == 18_800_000


# ─── Difficulty: validation priority — state beats fiscal on disburse ──────

def test_disburse_unregistered_over_balance_returns_state_error():
    """PRD 2.7: "6. Target-state legality — the resource is in a state that permits
    the operation (district, obligation, report, disbursement, or increment status),
    else the matching state error (409)."
    PRD 3.4: "The target obligation must be `REGISTERED`, or the request is rejected
    with `ERR_OBLIGATION_NOT_REGISTERED`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disburse
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_500_000_000)
    # BOND only submitted (UNDER_REVIEW), never registered.
    from test_helpers import propose_submit_bond
    ob = propose_submit_bond(d_id, principal_cents=20_000_000, final_maturity_tax_year=2040)
    resp = api_client.create_disbursement(
        ob["id"],
        create_disbursement_payload(99_000_000_000, 2026, fund_version(d_id)),
        make_admin_headers(ADMIN_2_ID))
    validate_error(resp, ApiErrorId.ERR_OBLIGATION_NOT_REGISTERED, expected_status=409)


def test_disburse_registered_over_balance_returns_fiscal_error():
    """PRD 2.7: "10. Fiscal capacity of a disbursement — amount within fund balance
    and within the annual cap — else `ERR_INSUFFICIENT_FUND_BALANCE` or
    `ERR_DISBURSEMENT_CAP_EXCEEDED` (402)."
    PRD 3.4: "If the requested amount exceeds the fund balance it is rejected with
    `ERR_INSUFFICIENT_FUND_BALANCE`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disburse
    """
    d_id, bond = _funded_district_with_registered_bond(
        principal_cents=20_000_000, bodies=SINGLE, current_eav_cents=1_500_000_000)
    resp = api_client.create_disbursement(
        bond["id"],
        create_disbursement_payload(99_000_000_000, 2026, fund_version(d_id)),
        make_admin_headers(ADMIN_2_ID))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUND_BALANCE, expected_status=402)


# ─── Difficulty: compensating invariant — cash conservation on void ────────

def test_void_restores_fund_cash_conservation():
    """PRD 3.4: "The fund's `balance_cents` is increased by the amount and its
    `lifetime_disbursed_cents` is decreased by the amount — so the lifetime-disbursed
    accumulator always reflects paid amounts net of voided ones".

    Design: Difficulty/compensating_invariant/cash_conservation_on_disburse_void
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # fund 38,800,000
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_500_000_000)
    bond = register_bond(d_id, principal_cents=20_000_000, interest_rate_bps=500,
                         final_maturity_tax_year=2040, priority_rank=1)
    accrue(bond["id"], 2026)
    disb = disburse(bond["id"], 5_000_000, 2026, d_id, actor_id=ADMIN_2_ID)
    voided = validate_success(api_client.void_disbursement(disb["id"], ADMIN))
    assert voided["status"] == "VOIDED"
    fund = get_fund(d_id)
    assert fund["balance_cents"] == 38_800_000
    assert fund["lifetime_disbursed_cents"] == 0
    assert fund["lifetime_increment_cents"] == 38_800_000


def test_void_restores_obligation_balances():
    """PRD 3.4: "the obligation's `accrued_interest_cents` is increased by the
    disbursement's `interest_portion_cents`, its `principal_remaining_cents` by the
    `principal_portion_cents`, and its `outstanding_balance_cents` by the full
    `amount_cents`".

    Design: Difficulty/compensating_invariant/cash_conservation_on_disburse_void
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_500_000_000)
    bond = register_bond(d_id, principal_cents=20_000_000, interest_rate_bps=500,
                         final_maturity_tax_year=2040, priority_rank=1)
    accrue(bond["id"], 2026)
    disb = disburse(bond["id"], 5_000_000, 2026, d_id, actor_id=ADMIN_2_ID)
    api_client.void_disbursement(disb["id"], ADMIN)
    updated = validate_success(api_client.get_obligation(bond["id"], ADMIN))
    assert updated["outstanding_balance_cents"] == 21_000_000
    assert updated["accrued_interest_cents"] == 1_000_000
    assert updated["principal_remaining_cents"] == 20_000_000


# ─── Corner: annual cap exceeded ───────────────────────────────────────────

def test_disbursement_exceeding_annual_cap_rejected():
    """PRD 3.4: "if it is within the balance but exceeds the remaining annual cap it
    is rejected with `ERR_DISBURSEMENT_CAP_EXCEEDED`."

    Design: Corner/calculations/disbursement_annual_cap_exceeded
    """
    d_id, bond = _funded_district_with_registered_bond(
        principal_cents=20_000_000, bodies=SINGLE, current_eav_cents=1_500_000_000,
        annual_cap_cents=3_000_000)
    resp = api_client.create_disbursement(
        bond["id"],
        create_disbursement_payload(5_000_000, 2026, fund_version(d_id)),
        make_admin_headers(ADMIN_2_ID))
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_CAP_EXCEEDED, expected_status=402)


# ─── Corner: void already voided ───────────────────────────────────────────

def test_void_already_voided_returns_not_voidable():
    """PRD 3.4: "Voiding is permitted only on a disbursement still in `PAID`; voiding
    one already `VOIDED` is rejected with `ERR_DISBURSEMENT_NOT_VOIDABLE`."

    Design: Corner/state_machines/void_already_voided_returns_not_voidable
    """
    d_id, bond = _funded_district_with_registered_bond(
        principal_cents=20_000_000, bodies=SINGLE, current_eav_cents=1_500_000_000)
    disb = disburse(bond["id"], 1_000_000, 2026, d_id, actor_id=ADMIN_2_ID)
    api_client.void_disbursement(disb["id"], ADMIN)
    resp = api_client.void_disbursement(disb["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_NOT_VOIDABLE, expected_status=409)


# ─── Corner: amount not positive ───────────────────────────────────────────

def test_disburse_zero_amount_returns_amount_not_positive():
    """PRD 3.4: "The `amount_cents` must be greater than zero, else
    `ERR_AMOUNT_NOT_POSITIVE`."

    Design: Corner/validations/disburse_amount_not_positive_returns_error
    """
    d_id, bond = _funded_district_with_registered_bond(
        principal_cents=20_000_000, bodies=SINGLE, current_eav_cents=1_500_000_000)
    resp = api_client.create_disbursement(
        bond["id"],
        create_disbursement_payload(0, 2026, fund_version(d_id)),
        make_admin_headers(ADMIN_2_ID))
    validate_error(resp, ApiErrorId.ERR_AMOUNT_NOT_POSITIVE, expected_status=422)


# ─── Corner: insufficient fund balance ─────────────────────────────────────

def test_disburse_over_fund_balance_returns_insufficient():
    """PRD 3.4: "If the requested amount exceeds the fund balance it is rejected with
    `ERR_INSUFFICIENT_FUND_BALANCE`".

    Design: Corner/validations/disburse_insufficient_fund_balance
    """
    # aggregate 0.08; incremental 12,500 -> gross 1,000, admin 30, captured 970.
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_000_012_500)  # fund 970
    bond = register_bond(d_id, principal_cents=20_000_000, final_maturity_tax_year=2040,
                         priority_rank=1)
    resp = api_client.create_disbursement(
        bond["id"],
        create_disbursement_payload(5_000_000, 2026, fund_version(d_id)),
        make_admin_headers(ADMIN_2_ID))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUND_BALANCE, expected_status=402)


# ─── Corner: seniority ordering ────────────────────────────────────────────

def test_subordinate_paid_before_senior_returns_seniority_violation():
    """PRD 3.4: "if the obligation is `SUBORDINATE`, no `SENIOR` obligation of the
    same district may still have an `outstanding_balance_cents` greater than zero; a
    subordinate developer note paid ahead of an unsatisfied senior bond is rejected
    with `ERR_SENIORITY_ORDER_VIOLATION`."

    Design: Corner/validations/disburse_subordinate_before_senior_returns_seniority_violation
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_500_000_000)
    register_bond(d_id, principal_cents=5_000_000, final_maturity_tax_year=2040,
                  priority_rank=1)
    dev = create_developer_entity(legal_name="Note Dev", contact_email="n@x.com")
    note = register_developer_note(d_id, dev["id"], principal_cents=4_000_000,
                                   final_maturity_tax_year=2040, priority_rank=2)
    resp = api_client.create_disbursement(
        note["id"],
        create_disbursement_payload(1_000_000, 2026, fund_version(d_id)),
        make_admin_headers(ADMIN_2_ID))
    validate_error(resp, ApiErrorId.ERR_SENIORITY_ORDER_VIOLATION, expected_status=409)


# ─── Corner: four-eyes segregation of duties ───────────────────────────────

def test_registrar_cannot_disburse_own_obligation():
    """PRD 2.8: "A later disbursement against that obligation must be authorized by a
    *different* `MunicipalAdmin` identity: if the acting `X-User-ID` on the
    disbursement equals the obligation's `registered_by_user_id`, the request is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/disburse_same_admin_returns_segregation_of_duties
    """
    d_id, bond = _funded_district_with_registered_bond(
        principal_cents=20_000_000, bodies=SINGLE, current_eav_cents=1_500_000_000)
    resp = api_client.create_disbursement(
        bond["id"],
        create_disbursement_payload(1_000_000, 2026, fund_version(d_id)),
        make_admin_headers(ADMIN_1_ID))  # same admin who registered
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)


# ─── Corner: OCC stale fund version on disburse ────────────────────────────

def test_second_disburse_with_stale_fund_version_rejected():
    """PRD 2.6: "if the fund's `version` has advanced since that observation —
    because an increment capture, another disbursement, a void, or a surplus sweep
    changed the balance — the create is rejected with `ERR_STALE_FUND_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_disburse_stale_fund_version
    """
    d_id, bond = _funded_district_with_registered_bond(
        principal_cents=20_000_000, bodies=SINGLE, current_eav_cents=1_500_000_000)
    stale_ver = fund_version(d_id)
    disburse(bond["id"], 1_000_000, 2026, d_id, expected_fund_version=stale_ver,
             actor_id=ADMIN_2_ID)  # bumps fund version
    resp = api_client.create_disbursement(
        bond["id"],
        create_disbursement_payload(1_000_000, 2026, stale_ver),
        make_admin_headers(ADMIN_2_ID))
    validate_error(resp, ApiErrorId.ERR_STALE_FUND_VERSION, expected_status=412)
