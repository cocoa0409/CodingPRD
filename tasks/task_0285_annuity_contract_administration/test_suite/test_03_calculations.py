"""Crediting, annuitization, distribution, surrender-charge, and projection-read
calculations. Each test translates exactly one corner-design instance (queue B).
"""
import pytest
from test_helpers import (
    validate_success,
    create_crediting_event_payload, create_annuitization_payload,
    setup_indexed_with_open_segment, setup_active_variable_contract,
    setup_elected_annuitization, setup_death_claim_valued,
    setup_active_fixed_contract, set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
CREDITING = TEST_USERS["crediting_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_index_credit_floor_clamps_negative_to_zero(api):
    """PRD §3.3: "then floors the result at the segment's `floor_bps` by taking
    the larger of the capped value and the floor".
    PRD §3.3: "In every kind the computed `credit_cents` is floored at zero so a
    credit is never negative."

    Design: Corner/calculations/index_credit_floor_clamps_negative_to_zero
    """
    product, contract, segment = setup_indexed_with_open_segment(
        segment_premium_cents=1_000_000, cap_bps=800, floor_bps=0, participation_bps=10000)
    event = validate_success(api.create_crediting_event(create_crediting_event_payload(
        contract["id"], "INDEX_SEGMENT", source_segment_id=segment["id"],
        raw_index_return_bps=-500, credit_period_start="2026-01-01T00:00:00Z",
        credit_period_end="2026-07-01T00:00:00Z"), CREDITING), 201)
    assert event["credit_cents"] == 0
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["accumulation_value_cents"] == 2000000


def test_subaccount_credit_share_of_accumulation(api):
    """PRD §3.3: "the server takes the allocation's share of the contract —
    `accumulation_value_cents` multiplied by the allocation's `allocation_bps`
    divided by 10000 — and multiplies that share by the division return divided
    by 10000, rounded half up."

    Design: Corner/calculations/subaccount_credit_share_of_accumulation
    """
    product, contract, premium, alloc_ids = setup_active_variable_contract(
        gross_premium_cents=2_000_000, allocations=((6000, "EQUITY"), (4000, "BOND")))
    event = validate_success(api.create_crediting_event(create_crediting_event_payload(
        contract["id"], "SUBACCOUNT_RETURN", source_allocation_id=alloc_ids[0],
        raw_index_return_bps=600), CREDITING), 201)
    assert event["credit_cents"] == 72000
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["accumulation_value_cents"] == 2072000


def test_annuitization_monthly_benefit_life_only(api):
    """PRD §3.8: "Begin with the snapshot `annuitization_value_cents` expressed
    per one thousand dollars — that is, the snapshot divided by 100,000 —
    multiplied by an age factor selected from a coarse age band: ... 540 from 60
    through 69".
    PRD §3.8: "applied as a percentage (divide by 100): 100 for `LIFE_ONLY`".

    Design: Corner/calculations/annuitization_monthly_benefit_life_only
    """
    contract, annuitization = setup_elected_annuitization(
        payout_option="LIFE_ONLY", gross_premium_cents=2_000_000, annuitant_age=60)
    begun = validate_success(api.begin_payout(annuitization["id"], ADMIN), 200)
    assert begun["annuitization_value_cents"] == 2000000
    assert begun["monthly_benefit_cents"] == 10800
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["status"] == "ANNUITIZED"


def test_beneficiary_distribution_remainder_to_earliest_created(api):
    """PRD §3.9: "each beneficiary's `payout_cents` is the floor of the total
    death benefit multiplied by that beneficiary's `share_bps` divided by
    10000."
    PRD §3.9: "that remainder is added to the `payout_cents` of the
    earliest-created `ACTIVE` beneficiary, never chosen by `id`."

    Design: Corner/calculations/beneficiary_distribution_remainder_to_earliest_created
    """
    product, contract, claim, ben_ids = setup_death_claim_valued(
        gross_premium_cents=2_000_000,
        beneficiary_shares=((3334, "First"), (3333, "Second"), (3333, "Third")))
    validate_success(api.fund_death_claim(claim["id"], COMPLIANCE), 200)
    b1 = validate_success(api.get_beneficiary(ben_ids[0], ADMIN), 200)
    b2 = validate_success(api.get_beneficiary(ben_ids[1], ADMIN), 200)
    b3 = validate_success(api.get_beneficiary(ben_ids[2], ADMIN), 200)
    assert b1["payout_cents"] == 666800
    assert b2["payout_cents"] == 666600
    assert b3["payout_cents"] == 666600


def test_surrender_charge_zero_out_of_surrender_period(api):
    """PRD §3.4: "once `contract_year` reaches or exceeds the schedule's length
    the contract is past its surrender period and `surrender_charge_bps` is 0."
    PRD §3.5: "When the contract is past its surrender period the rate is 0 and
    the surrender charge is therefore 0 regardless of the chargeable amount".

    Design: Corner/calculations/surrender_charge_zero_out_of_surrender_period
    """
    set_clock("2026-01-01T00:00:00Z")
    product = validate_success(api.create_product({
        "name": "Fixed1yr", "contract_type": "FIXED", "fixed_annual_rate_bps": 0,
        "free_withdrawal_corridor_bps": 0, "death_benefit_type": "ACCOUNT_VALUE",
        "surrender_charge_schedule": [{"contract_year": 0, "charge_bps": 700}],
        "min_initial_premium_cents": 1_000_000}, ADMIN), 201)
    contract = validate_success(api.create_contract({
        "product_id": product["id"], "owner_name": "Owner", "annuitant_age": 60}, ADMIN), 201)
    premium = validate_success(api.create_premium({
        "contract_id": contract["id"], "gross_premium_cents": 2_000_000,
        "expected_contract_version": contract["version"]}, ADMIN), 201)
    validate_success(api.clear_premium(premium["id"], ADMIN), 200)
    validate_success(api.set_clock("2027-02-01T00:00:00Z", ADMIN), 200)
    validate_success(api.roll_anniversary(contract["id"], ADMIN), 200)
    rolled = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert rolled["surrender_charge_bps"] == 0
    wd = validate_success(api.create_withdrawal({
        "contract_id": contract["id"], "requested_amount_cents": 100000,
        "expected_contract_version": rolled["version"]}, ADMIN), 201)
    settled = validate_success(api.settle_withdrawal(wd["id"], COMPLIANCE), 200)
    assert settled["chargeable_amount_cents"] == 100000
    assert settled["surrender_charge_cents"] == 0


def test_projection_computed_read_settled_base(api):
    """PRD §3.6: "This projection starts from the settled chronological
    accumulation value as its base".
    PRD §3.6: "The number of years to project is the schedule length minus the
    current `contract_year`, never less than zero."
    PRD §3.6: "The response reports the projected maturity value, the settled
    base it started from, and the number of years projected."

    Design: Corner/endpoints/projection_computed_read_settled_base
    """
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, fixed_annual_rate_bps=350,
        surrender_charge_schedule=[
            {"contract_year": 0, "charge_bps": 700},
            {"contract_year": 1, "charge_bps": 600},
            {"contract_year": 2, "charge_bps": 500}])
    res = api.get_projection(contract["id"], ADMIN, params={"include_pending": False})
    data = validate_success(res, 200)
    assert data["settled_base_cents"] == 2000000
    assert data["years_projected"] == 3


def test_anniversary_roll_resets_free_corridor_and_updates_hav(api):
    """PRD §3.4: "the roll sets `highest_anniversary_value_cents` to the larger
    of its prior value and the current `accumulation_value_cents`, resets
    `free_withdrawal_used_cents` to zero".

    Design: Corner/endpoints/anniversary_roll_resets_free_corridor_and_updates_hav
    """
    set_clock("2026-01-01T00:00:00Z")
    product = validate_success(api.create_product({
        "name": "Fixed", "contract_type": "FIXED", "fixed_annual_rate_bps": 350,
        "free_withdrawal_corridor_bps": 1000, "death_benefit_type": "ACCOUNT_VALUE",
        "surrender_charge_schedule": [
            {"contract_year": 0, "charge_bps": 700}, {"contract_year": 1, "charge_bps": 600}],
        "min_initial_premium_cents": 1_000_000}, ADMIN), 201)
    contract = validate_success(api.create_contract({
        "product_id": product["id"], "owner_name": "Owner", "annuitant_age": 60}, ADMIN), 201)
    premium = validate_success(api.create_premium({
        "contract_id": contract["id"], "gross_premium_cents": 2_000_000,
        "expected_contract_version": contract["version"]}, ADMIN), 201)
    validate_success(api.clear_premium(premium["id"], ADMIN), 200)
    validate_success(api.create_crediting_event(
        create_crediting_event_payload(contract["id"], "FIXED_GUARANTEED"), CREDITING), 201)
    pre = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    wd = validate_success(api.create_withdrawal({
        "contract_id": contract["id"], "requested_amount_cents": 200000,
        "expected_contract_version": pre["version"]}, ADMIN), 201)
    validate_success(api.settle_withdrawal(wd["id"], COMPLIANCE), 200)
    validate_success(api.set_clock("2027-02-01T00:00:00Z", ADMIN), 200)
    rolled = validate_success(api.roll_anniversary(contract["id"], ADMIN), 200)
    assert rolled["free_withdrawal_used_cents"] == 0
    assert rolled["highest_anniversary_value_cents"] == 2000000


def test_immediate_consistency_accumulation_visible_in_same_response(api):
    """PRD §3.3: "When the event posts, the server computes its `credit_cents`,
    adds that amount to `accumulation_value_cents`".
    PRD §3.5: "This replay is recomputed on every premium clear, crediting post,
    and withdrawal settle, and whenever a contract is retrieved."

    Design: Corner/consistency_model/immediate_consistency_accumulation_visible_in_same_response
    """
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, fixed_annual_rate_bps=350)
    validate_success(api.create_crediting_event(
        create_crediting_event_payload(contract["id"], "FIXED_GUARANTEED"), CREDITING), 201)
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
    assert contract_after["accumulation_value_cents"] == 2070000
