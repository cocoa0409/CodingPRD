"""Withdrawal settlement: pinned corridor->charge->MVA order, full-surrender
cascade, corridor boundary, reject conservation, cross-entity state guard.

Difficulty-queue instances each carry >=2 tests; one corner-design instance
(insufficient accumulation) is also translated here.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_requested_withdrawal, setup_active_variable_contract,
    setup_active_fixed_contract, setup_elected_annuitization, set_clock,
    create_withdrawal_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

SCHED_3YR = [
    {"contract_year": 0, "charge_bps": 700},
    {"contract_year": 1, "charge_bps": 600},
    {"contract_year": 2, "charge_bps": 500},
]


# ─── combinatorial_formula / withdrawal_pinned_order_corridor_then_charge_then_mva ─
def test_withdrawal_pinned_order_full_breakdown(api):
    """PRD §3.5: "Settling a withdrawal computes the money in a strictly pinned
    order: first the corridor split, then the surrender charge on whatever
    remains chargeable, then the market value adjustment on that same chargeable
    remainder."
    PRD §3.5: "The total reduction of the contract is the
    `gross_withdrawal_cents`, equal to `requested_amount_cents` plus
    `surrender_charge_cents` plus `mva_cents`".

    Design: Difficulty/combinatorial_formula/withdrawal_pinned_order_corridor_then_charge_then_mva
    """
    product, contract, withdrawal = setup_requested_withdrawal(
        requested_amount_cents=300000, fixed_annual_rate_bps=350,
        free_withdrawal_corridor_bps=1000, surrender_charge_schedule=SCHED_3YR,
        mva_enabled=True, gross_premium_cents=2_000_000)
    settled = validate_success(api.settle_withdrawal(withdrawal["id"], COMPLIANCE), 200)
    assert settled["free_amount_cents"] == 200000
    assert settled["chargeable_amount_cents"] == 100000
    assert settled["surrender_charge_cents"] == 7000
    assert settled["mva_cents"] == 45
    assert settled["gross_withdrawal_cents"] == 307045


def test_withdrawal_settle_debits_accumulation_by_gross(api):
    """PRD §3.5: "On a successful settle the server debits
    `accumulation_value_cents` by the gross".

    Design: Difficulty/combinatorial_formula/withdrawal_pinned_order_corridor_then_charge_then_mva
    """
    product, contract, withdrawal = setup_requested_withdrawal(
        requested_amount_cents=300000, fixed_annual_rate_bps=350,
        free_withdrawal_corridor_bps=1000, surrender_charge_schedule=SCHED_3YR,
        mva_enabled=True, gross_premium_cents=2_000_000)
    validate_success(api.settle_withdrawal(withdrawal["id"], COMPLIANCE), 200)
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    # 2,000,000 - 307,045 = 1,692,955.
    assert contract_after["accumulation_value_cents"] == 1692955


# ─── transitive_cascade / full_surrender_cascade_depth3 ───────────────────
def test_full_surrender_cascade_liquidates_allocations(api):
    """PRD §3.5: "If the withdrawal carried `is_full_surrender` set to true,
    settling it also liquidates the entire accumulation and cascades the
    contract from `ACTIVE` to `SURRENDERED`: the contract's
    `accumulation_value_cents` is set to 0, every `ACTIVE` sub-account
    allocation on the contract is set to `LIQUIDATED`".

    Design: Difficulty/transitive_cascade/full_surrender_cascade_depth3
    """
    product, contract, premium, alloc_ids = setup_active_variable_contract(
        gross_premium_cents=2_000_000, allocations=((6000, "EQUITY"), (4000, "BOND")),
        free_withdrawal_corridor_bps=0,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}])
    wd = validate_success(api.create_withdrawal(create_withdrawal_payload(
        contract["id"], 2_000_000, contract["version"], is_full_surrender=True), ADMIN), 201)
    settled = validate_success(api.settle_withdrawal(wd["id"], COMPLIANCE), 200)
    assert settled["status"] == "SETTLED"
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["status"] == "SURRENDERED"
    assert contract_after["accumulation_value_cents"] == 0
    for alloc_id in alloc_ids:
        alloc = validate_success(api.get_sub_account_allocation(alloc_id, ADMIN), 200)
        assert alloc["status"] == "LIQUIDATED"


def test_full_surrender_sets_contract_surrendered(api):
    """PRD §3.5: "settling it also liquidates the entire accumulation and
    cascades the contract from `ACTIVE` to `SURRENDERED`".

    Design: Difficulty/transitive_cascade/full_surrender_cascade_depth3
    """
    product, contract, premium, alloc_ids = setup_active_variable_contract(
        gross_premium_cents=2_000_000, allocations=((10000, "EQUITY"),),
        free_withdrawal_corridor_bps=0,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}])
    wd = validate_success(api.create_withdrawal(create_withdrawal_payload(
        contract["id"], 2_000_000, contract["version"], is_full_surrender=True), ADMIN), 201)
    validate_success(api.settle_withdrawal(wd["id"], COMPLIANCE), 200)
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["status"] == "SURRENDERED"


# ─── boundary_precision_check / free_corridor_exact_equality_is_fully_free ─
def test_corridor_exact_equality_fully_free(api):
    """PRD §3.5: "The `free_amount_cents` of this withdrawal is the smaller of
    the requested amount and the remaining corridor, so a withdrawal exactly
    equal to the remaining corridor is entirely free, while one cent beyond it
    makes exactly that one cent chargeable."

    Design: Difficulty/boundary_precision_check/free_corridor_exact_equality_is_fully_free
    """
    product, contract, withdrawal = setup_requested_withdrawal(
        requested_amount_cents=200000, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=1000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 700}],
        gross_premium_cents=2_000_000)
    settled = validate_success(api.settle_withdrawal(withdrawal["id"], COMPLIANCE), 200)
    assert settled["free_amount_cents"] == 200000
    assert settled["chargeable_amount_cents"] == 0
    assert settled["surrender_charge_cents"] == 0
    assert settled["gross_withdrawal_cents"] == 200000


def test_corridor_one_cent_over_makes_one_cent_chargeable(api):
    """PRD §3.5: "while one cent beyond it makes exactly that one cent
    chargeable."
    PRD §3.5: "`surrender_charge_cents` is the chargeable amount multiplied by
    that rate divided by 10000, rounded half up."

    Design: Difficulty/boundary_precision_check/free_corridor_exact_equality_is_fully_free
    """
    # Corridor allowance = floor(2,000,000 * 1000/10000) = 200,000. Request 200,001
    # -> free 200,000, chargeable 1, charge round_half_up(1*700/10000)=round(0.07)=0.
    product, contract, withdrawal = setup_requested_withdrawal(
        requested_amount_cents=200001, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=1000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 700}],
        gross_premium_cents=2_000_000)
    settled = validate_success(api.settle_withdrawal(withdrawal["id"], COMPLIANCE), 200)
    assert settled["free_amount_cents"] == 200000
    assert settled["chargeable_amount_cents"] == 1


# ─── compensating_invariant / withdrawal_request_then_reject_conserves_free_corridor ─
def test_withdrawal_reject_conserves_free_corridor(api):
    """PRD §3.5: "A `ComplianceOfficer` may reject a `REQUESTED` withdrawal,
    moving it to `REJECTED` with no change to `accumulation_value_cents` or
    `free_withdrawal_used_cents`."

    Design: Difficulty/compensating_invariant/withdrawal_request_then_reject_conserves_free_corridor
    """
    product, contract, withdrawal = setup_requested_withdrawal(
        requested_amount_cents=150000, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=1000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 700}],
        gross_premium_cents=2_000_000)
    rejected = validate_success(api.reject_withdrawal(withdrawal["id"], COMPLIANCE), 200)
    assert rejected["status"] == "REJECTED"
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["free_withdrawal_used_cents"] == 0
    assert contract_after["accumulation_value_cents"] == 2000000


def test_withdrawal_reject_leaves_accumulation_unchanged(api):
    """PRD §3.5: "A `ComplianceOfficer` may reject a `REQUESTED` withdrawal,
    moving it to `REJECTED` with no change to `accumulation_value_cents` or
    `free_withdrawal_used_cents`."

    Design: Difficulty/compensating_invariant/withdrawal_request_then_reject_conserves_free_corridor
    """
    product, contract, withdrawal = setup_requested_withdrawal(
        requested_amount_cents=500000, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=1000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 700}],
        gross_premium_cents=2_000_000)
    validate_success(api.reject_withdrawal(withdrawal["id"], COMPLIANCE), 200)
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["accumulation_value_cents"] == 2000000
    assert contract_after["free_withdrawal_used_cents"] == 0


# ─── cross_entity_state_dependency / withdrawal_settle_requires_contract_active ─
def test_settle_withdrawal_after_annuitization_invalid_state(api):
    """PRD §3.5: "A settle is permitted only while the withdrawal is `REQUESTED`
    and the contract is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/withdrawal_settle_requires_contract_active
    """
    set_clock("2026-01-01T00:00:00Z")
    product = validate_success(api.create_product({
        "name": "Fixed", "contract_type": "FIXED", "fixed_annual_rate_bps": 0,
        "free_withdrawal_corridor_bps": 10000, "death_benefit_type": "ACCOUNT_VALUE",
        "surrender_charge_schedule": [{"contract_year": 0, "charge_bps": 0}],
        "min_initial_premium_cents": 1_000_000}, ADMIN), 201)
    contract = validate_success(api.create_contract({
        "product_id": product["id"], "owner_name": "Owner", "annuitant_age": 60}, ADMIN), 201)
    premium = validate_success(api.create_premium({
        "contract_id": contract["id"], "gross_premium_cents": 2_000_000,
        "expected_contract_version": contract["version"]}, ADMIN), 201)
    validate_success(api.clear_premium(premium["id"], ADMIN), 200)
    fresh = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    wd = validate_success(api.create_withdrawal({
        "contract_id": contract["id"], "requested_amount_cents": 100000,
        "expected_contract_version": fresh["version"]}, ADMIN), 201)
    ann = validate_success(api.create_annuitization({
        "contract_id": contract["id"], "payout_option": "LIFE_ONLY"}, ADMIN), 201)
    validate_success(api.begin_payout(ann["id"], ADMIN), 200)
    annuitized = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert annuitized["status"] == "ANNUITIZED"
    res = api.settle_withdrawal(wd["id"], COMPLIANCE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_settle_requested_withdrawal_on_active_succeeds(api):
    """PRD §3.5: "A settle is permitted only while the withdrawal is `REQUESTED`
    and the contract is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/withdrawal_settle_requires_contract_active
    """
    product, contract, withdrawal = setup_requested_withdrawal(
        requested_amount_cents=100000, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=10000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}],
        gross_premium_cents=2_000_000)
    settled = validate_success(api.settle_withdrawal(withdrawal["id"], COMPLIANCE), 200)
    assert settled["status"] == "SETTLED"


# ─── validations / insufficient_accumulation_on_settle (corner) ───────────
def test_insufficient_accumulation_on_settle(api):
    """PRD §3.5: "At settle time, this gross must not exceed the contract's
    current `accumulation_value_cents`; an over-draw is rejected with
    `ERR_INSUFFICIENT_ACCUMULATION`."

    Design: Corner/validations/insufficient_accumulation_on_settle
    """
    # accumulation 100,000; request 100,000 with corridor 0 + year0 700bps ->
    # chargeable 100,000, charge 7,000, gross 107,000 > 100,000.
    product, contract, withdrawal = setup_requested_withdrawal(
        requested_amount_cents=100000, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=0,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 700}],
        gross_premium_cents=100_000, min_initial_premium_cents=100_000)
    res = api.settle_withdrawal(withdrawal["id"], COMPLIANCE)
    validate_error(res, "ERR_INSUFFICIENT_ACCUMULATION", expected_status=409)
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["accumulation_value_cents"] == 100000
