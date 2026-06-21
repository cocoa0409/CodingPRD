"""Initial-premium clearing cascade, forward-looking projection variants, and
premium/allocation/annuitization input validations.

Difficulty-queue instances each carry >=2 tests; several corner-design
validation instances are also translated here.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_active_fixed_contract, set_clock,
    create_product_payload, create_contract_payload, create_premium_payload,
    create_sub_account_allocation_payload, create_crediting_event_payload,
    create_annuitization_payload, create_exchange_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
CREDITING = TEST_USERS["crediting_officer_headers"]

SCHED_3YR = [
    {"contract_year": 0, "charge_bps": 700},
    {"contract_year": 1, "charge_bps": 600},
    {"contract_year": 2, "charge_bps": 500},
]


# ─── transitive_cascade / premium_clear_cascade_depth2 ────────────────────
def test_initial_premium_clear_activates_contract(api):
    """PRD §3.2: "Clearing the **initial** premium additionally drives the
    contract from `PENDING` to `ACTIVE`: at that moment the server stamps
    `issue_date` to the current clock, recomputes the accumulation and
    cumulative-premium totals to include the just-cleared net premium, and sets
    `highest_anniversary_value_cents` equal to the new accumulation value."

    Design: Difficulty/transitive_cascade/premium_clear_cascade_depth2
    """
    set_clock("2026-03-15T00:00:00Z")
    product = validate_success(api.create_product(create_product_payload(
        fixed_annual_rate_bps=350,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 700}]), ADMIN), 201)
    contract = validate_success(api.create_contract(
        create_contract_payload(product["id"]), ADMIN), 201)
    premium = validate_success(api.create_premium(create_premium_payload(
        contract["id"], contract["version"], gross_premium_cents=2_000_000), ADMIN), 201)
    validate_success(api.clear_premium(premium["id"], ADMIN), 200)
    after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert after["status"] == "ACTIVE"
    assert after["accumulation_value_cents"] == 2000000
    assert after["highest_anniversary_value_cents"] == 2000000


def test_initial_premium_clear_stamps_issue_date(api):
    """PRD §3.2: "at that moment the server stamps `issue_date` to the current
    clock".
    PRD §2.10: "The contract's `issue_date` is stamped from the server clock at
    the moment its first premium clears".

    Design: Difficulty/transitive_cascade/premium_clear_cascade_depth2
    """
    set_clock("2026-03-15T00:00:00Z")
    product = validate_success(api.create_product(create_product_payload(
        fixed_annual_rate_bps=350,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 700}]), ADMIN), 201)
    contract = validate_success(api.create_contract(
        create_contract_payload(product["id"]), ADMIN), 201)
    premium = validate_success(api.create_premium(create_premium_payload(
        contract["id"], contract["version"], gross_premium_cents=2_000_000), ADMIN), 201)
    validate_success(api.clear_premium(premium["id"], ADMIN), 200)
    after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert after["issue_date"].startswith("2026-03-15T00:00:00")


# ─── dual_variant_calc / projection_settled_vs_include_pending_on_contract ─
def _setup_projection_contract(api):
    """FIXED 3yr (rate 350bps): cleared 2,000,000 + one still-SUBMITTED 500,000."""
    set_clock("2026-01-01T00:00:00Z")
    product = validate_success(api.create_product(create_product_payload(
        name="Fixed 3yr", fixed_annual_rate_bps=350,
        surrender_charge_schedule=SCHED_3YR), ADMIN), 201)
    contract = validate_success(api.create_contract(
        create_contract_payload(product["id"], owner_name="Ada Owner"), ADMIN), 201)
    prem0 = validate_success(api.create_premium(create_premium_payload(
        contract["id"], contract["version"], gross_premium_cents=2_000_000), ADMIN), 201)
    validate_success(api.clear_premium(prem0["id"], ADMIN), 200)
    fresh = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    # A subsequent SUBMITTED (not cleared) premium net 500,000.
    validate_success(api.create_premium(create_premium_payload(
        contract["id"], fresh["version"], gross_premium_cents=500_000), ADMIN), 201)
    return contract


def test_projection_settled_only_excludes_pending(api):
    """PRD §3.6: "With `include_pending` false, those pending premiums are
    excluded and the projection runs from the settled chronological base alone".
    PRD §3.6: "For each remaining year the projected value is multiplied by one
    plus the rate divided by 10000 and rounded half up, compounding year over
    year."

    Design: Difficulty/dual_variant_calc/projection_settled_vs_include_pending_on_contract
    """
    contract = _setup_projection_contract(api)
    res = api.get_projection(contract["id"], ADMIN, params={"include_pending": False})
    data = validate_success(res, 200)
    assert data["projected_maturity_value_cents"] == 2217436


def test_projection_include_pending_folds_submitted_premiums(api):
    """PRD §3.6: "by default, also adds the net amounts of all `SUBMITTED`
    (not-yet-cleared) premiums as if they will clear — this inclusion of pending
    premiums is the one difference from the chronological value."
    PRD §3.6: "the same contract therefore yields a different number under the
    two settings."

    Design: Difficulty/dual_variant_calc/projection_settled_vs_include_pending_on_contract
    """
    contract = _setup_projection_contract(api)
    settled = validate_success(
        api.get_projection(contract["id"], ADMIN, params={"include_pending": False}), 200)
    pending = validate_success(
        api.get_projection(contract["id"], ADMIN, params={"include_pending": True}), 200)
    assert pending["projected_maturity_value_cents"] == 2771795
    assert settled["projected_maturity_value_cents"] != pending["projected_maturity_value_cents"]


# ─── validations (corner) ─────────────────────────────────────────────────
def test_initial_premium_below_minimum_rejected(api):
    """PRD §3.2: "The initial premium's `gross_premium_cents` must be at least
    the product's `min_initial_premium_cents`, and falling short is rejected
    with `ERR_BELOW_MINIMUM_PREMIUM`."

    Design: Corner/validations/initial_premium_below_minimum_rejected
    """
    product = validate_success(api.create_product(create_product_payload(
        min_initial_premium_cents=1_000_000), ADMIN), 201)
    contract = validate_success(api.create_contract(
        create_contract_payload(product["id"]), ADMIN), 201)
    res = api.create_premium(create_premium_payload(
        contract["id"], contract["version"], gross_premium_cents=500_000), ADMIN)
    validate_error(res, "ERR_BELOW_MINIMUM_PREMIUM", expected_status=422)
    after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert after["status"] == "PENDING"


def test_variable_allocation_incomplete_blocks_initial_clear(api):
    """PRD §3.2: "The sum of `allocation_bps` across all `ACTIVE` allocations on
    the contract must equal exactly 10000 before the initial premium may clear;
    a partial set of allocations causes the clear to be rejected with
    `ERR_ALLOCATION_INCOMPLETE`."

    Design: Corner/validations/variable_allocation_incomplete_blocks_initial_clear
    """
    product = validate_success(api.create_product(create_product_payload(
        name="Var", contract_type="VARIABLE", fixed_annual_rate_bps=None,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}]), ADMIN), 201)
    contract = validate_success(api.create_contract(
        create_contract_payload(product["id"]), ADMIN), 201)
    validate_success(api.create_sub_account_allocation(
        create_sub_account_allocation_payload(
            contract["id"], division_name="EQUITY", allocation_bps=6000, unit_value_cents=1000),
        ADMIN), 201)
    premium = validate_success(api.create_premium(create_premium_payload(
        contract["id"], contract["version"], gross_premium_cents=2_000_000), ADMIN), 201)
    res = api.clear_premium(premium["id"], ADMIN)
    validate_error(res, "ERR_ALLOCATION_INCOMPLETE", expected_status=409)
    after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert after["status"] == "PENDING"


def test_crediting_kind_mismatch_rejected(api):
    """PRD §3.3: "Every event names its `contract_id` and a `crediting_kind`
    that must agree with the contract's product type: ... `INDEX_SEGMENT` only
    on an `INDEXED` contract".
    PRD §3.3: "A kind that does not match the product type ... is rejected with
    `ERR_CREDITING_KIND_MISMATCH`."

    Design: Corner/validations/crediting_kind_mismatch_rejected
    """
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, fixed_annual_rate_bps=350)
    res = api.create_crediting_event(create_crediting_event_payload(
        contract["id"], "INDEX_SEGMENT", raw_index_return_bps=500), CREDITING)
    validate_error(res, "ERR_CREDITING_KIND_MISMATCH", expected_status=422)


def test_payout_option_arity_period_certain_requires_years(api):
    """PRD §3.8: "`period_certain_years` must be present and at least 1 for
    `PERIOD_CERTAIN` and `LIFE_WITH_PERIOD_CERTAIN`, and must be absent for
    `LIFE_ONLY` and `JOINT_LIFE`; a violation is rejected with
    `ERR_PAYOUT_OPTION_ARITY`."

    Design: Corner/validations/payout_option_arity_period_certain_requires_years
    """
    product, contract, _ = setup_active_fixed_contract(gross_premium_cents=2_000_000)
    res = api.create_annuitization(
        create_annuitization_payload(contract["id"], "PERIOD_CERTAIN"), ADMIN)
    validate_error(res, "ERR_PAYOUT_OPTION_ARITY", expected_status=422)


def test_invalid_cost_basis_exceeds_transfer_rejected(api):
    """PRD §3.10: "The basis must lie between 0 and the transfer amount
    inclusive; a basis above the transfer is rejected with
    `ERR_INVALID_COST_BASIS`, both at creation and at submit."

    Design: Corner/validations/invalid_cost_basis_exceeds_transfer_rejected
    """
    product = validate_success(api.create_product(create_product_payload(), ADMIN), 201)
    source = validate_success(api.create_contract(
        create_contract_payload(product["id"]), ADMIN), 201)
    res = api.create_exchange(create_exchange_payload(
        "OUTBOUND", 1_000_000, 1_500_000,
        source_contract_id=source["id"], external_carrier="OtherCo"), ADMIN)
    validate_error(res, "ERR_INVALID_COST_BASIS", expected_status=422)
