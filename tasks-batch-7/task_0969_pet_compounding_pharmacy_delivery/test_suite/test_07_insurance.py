"""Insurance claims: estimate vs adjudication waterfall, appeals, and pay gates."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_owner, create_pet, create_lot, create_bench,
    create_compound_order, create_policy_for_pet, create_claim_for_order,
    fetch_claim, fetch_policy, fetch_compound_order,
    setup_verified_scenario, order_to_ready, allocate_order, start_compounding,
    complete_compounding, complete_flavoring, qa_pass_order,
    TEST_USERS, make_owner_headers,
)

CHICKEN_FLAVOR = {"allergen_tags": ["CHICKEN"], "surcharge_cents": 250,
                  "compatible_species": ["DOG", "CAT"]}


def _setup_d2():
    """Verified rx qty 300 (12 kg dog, chicken flavor); lots 200@110 and 200@130;
    policy deductible 5000, coverage 0.8, limit 100000, nothing used."""
    scn = setup_verified_scenario(pet_weight_kg=12, catalog_unit_cost=120,
                                  flavor=CHICKEN_FLAVOR, quantity=300, days_supply=30)
    create_lot(scn["drug"]["id"], received_qty=200, unit_cost_cents=110,
               expiration_date="2027-01-01")
    create_lot(scn["drug"]["id"], received_qty=200, unit_cost_cents=130,
               expiration_date="2027-06-01")
    scn["bench"] = create_bench()
    order = create_compound_order(scn["rx"]["id"], flavoring_id=scn["flavoring"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    policy = create_policy_for_pet(scn["pet"]["id"], scn["owner"]["id"],
                                   deductible_cents=5000, coverage_pct=0.8,
                                   annual_limit_cents=100000)
    scn.update({"order": order, "policy": policy})
    return scn


def _run_d2(scn):
    claim = create_claim_for_order(scn["policy"], scn["order"], 41688, scn["owner"]["id"])
    allocate_order(scn["order"]["id"])
    start_compounding(scn["order"]["id"], scn["bench"]["id"])
    complete_compounding(scn["order"]["id"])
    complete_flavoring(scn["order"]["id"])
    qa_pass_order(scn["order"]["id"])
    adjudicated = get_success_data(api_client.adjudicate_claim(
        claim["id"], {"outcome": "APPROVE"}, TEST_USERS["insurance_adjuster_headers"]))
    return claim, adjudicated


def test_claim_estimate_uses_provisional_price(api):
    """PRD §3.6: "At creation the claim's `estimate_cents` is computed by running
    the adjudication waterfall over the provisional price against the policy's
    snapshot at that moment, without mutating any policy counter"
    PRD §3.6: "The deductible applied is the lesser of the amount and the policy's
    remaining deductible — `deductible_cents` minus `deductible_met_cents`. The
    remainder after the deductible is multiplied by `coverage_pct` and rounded half
    up to whole cents to get the covered amount."
    Over the provisional 41688: deductible 5000, round(36688*0.8) = 29350.

    Design: Difficulty/dual_variant_calc/claim_estimate_vs_adjudicated
    """
    scn = _setup_d2()
    claim, adjudicated = _run_d2(scn)
    assert claim["estimate_cents"] == 29350, (
        f"estimate expected 29350, got {claim['estimate_cents']}")
    assert adjudicated["deductible_applied_cents"] == 5000


def test_claim_adjudication_uses_final_price(api):
    """PRD §3.6: "Either approval runs the waterfall over the final price against
    the policy's live counters"
    Over the final price 41745 (per-line lot economics): deductible 5000,
    round(36745*0.8) = 29396 — diverging from the provisional-keyed estimate 29350.

    Design: Difficulty/dual_variant_calc/claim_estimate_vs_adjudicated
    """
    scn = _setup_d2()
    claim, adjudicated = _run_d2(scn)
    assert adjudicated["approved_amount_cents"] == 29396, (
        f"approved expected 29396, got {adjudicated['approved_amount_cents']}")
    assert adjudicated["approved_amount_cents"] != claim["estimate_cents"]


def _setup_x2():
    """Order qty 5 (2 kg pet, no flavor; provisional 500, final 515) QA-passed;
    policy deductible 0, coverage 1.0, limit 100000; claim APPROVED with 515."""
    scn = setup_verified_scenario(pet_weight_kg=2, pet_species="CAT", quantity=5,
                                  days_supply=5)
    create_lot(scn["drug"]["id"], received_qty=50, unit_cost_cents=100)
    scn["bench"] = create_bench()
    order = order_to_ready(scn["rx"]["id"], scn["bench"]["id"])
    policy = create_policy_for_pet(scn["pet"]["id"], scn["owner"]["id"],
                                   deductible_cents=0, coverage_pct=1.0,
                                   annual_limit_cents=100000)
    claim = create_claim_for_order(policy, order, 500, scn["owner"]["id"])
    adjudicated = get_success_data(api_client.adjudicate_claim(
        claim["id"], {"outcome": "APPROVE"}, TEST_USERS["insurance_adjuster_headers"]))
    scn.update({"order": order, "policy": policy, "claim": adjudicated})
    return scn


def test_claim_approval_amount_from_final_price(api):
    """PRD §3.6: "Approving a `SUBMITTED` claim requires the policy to be `ACTIVE`
    and the order's `final_price_cents` to be present"
    Final price 515 (round(5*100*1.03)) with zero deductible and coverage 1.0
    yields approved_amount_cents 515.

    Design: Difficulty/cross_entity_state_dependency/claim_pay_requires_policy_active
    """
    scn = _setup_x2()
    assert scn["claim"]["approved_amount_cents"] == 515, (
        f"approved expected 515, got {scn['claim']['approved_amount_cents']}")
    assert scn["claim"]["status"] == "APPROVED"


def test_claim_pay_blocked_after_policy_lapse(api):
    """PRD §3.6: "Finally, an `InsuranceAdjuster` pays an `APPROVED` claim: the
    policy must be `ACTIVE`, otherwise `ERR_POLICY_NOT_ACTIVE`; the claim moves to
    the terminal `PAID`, the policy's `annual_used_cents` rises by
    `approved_amount_cents`"
    Once the policy is LAPSED the pay transition is rejected; the claim stays
    APPROVED and annual_used_cents stays 0.

    Design: Difficulty/cross_entity_state_dependency/claim_pay_requires_policy_active
    """
    scn = _setup_x2()
    get_success_data(api_client.lapse_policy(scn["policy"]["id"],
                                             TEST_USERS["insurance_adjuster_headers"]))
    res = api_client.pay_claim(scn["claim"]["id"], TEST_USERS["insurance_adjuster_headers"])
    validate_error(res, ApiErrorId.ERR_POLICY_NOT_ACTIVE)
    assert fetch_claim(scn["claim"]["id"])["status"] == "APPROVED"
    assert fetch_policy(scn["policy"]["id"])["annual_used_cents"] == 0


def _setup_s5():
    """Order provisional 500 (qty 5 @100, 2 kg pet); policy deductible 0 coverage
    1.0; claim SUBMITTED."""
    scn = setup_verified_scenario(pet_weight_kg=2, pet_species="CAT", quantity=5,
                                  days_supply=5)
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    policy = create_policy_for_pet(scn["pet"]["id"], scn["owner"]["id"],
                                   deductible_cents=0, coverage_pct=1.0,
                                   annual_limit_cents=100000)
    claim = create_claim_for_order(policy, order, 500, scn["owner"]["id"])
    scn.update({"order": order, "policy": policy, "claim": claim})
    return scn


def test_claim_appeal_loop_max_two(api):
    """PRD §3.6: "The owner may appeal a rejected claim — ownership-checked against
    the policy's owner — as long as `appeal_count` is below two; an appeal beyond
    the second is rejected with `ERR_MAX_APPEALS_EXCEEDED`, and each appeal
    increments `appeal_count` while moving the claim to `APPEALED`."

    Design: Corner/state_machines/claim_appeal_loop_max_two
    """
    scn = _setup_s5()
    claim_id = scn["claim"]["id"]
    adjuster = TEST_USERS["insurance_adjuster_headers"]
    owner_headers = make_owner_headers(scn["owner"]["id"])
    for reason in ("not covered", "still not covered", "final"):
        get_success_data(api_client.adjudicate_claim(
            claim_id, {"outcome": "REJECT", "denial_reason": reason}, adjuster))
        if reason != "final":
            get_success_data(api_client.appeal_claim(claim_id, owner_headers))
    res = api_client.appeal_claim(claim_id, owner_headers)
    validate_error(res, ApiErrorId.ERR_MAX_APPEALS_EXCEEDED)
    claim = fetch_claim(claim_id)
    assert claim["appeal_count"] == 2
    assert claim["status"] == "REJECTED"


def test_claim_amount_mismatch_rejected(api):
    """PRD §3.6: "a `claimed_amount_cents` that must equal the order's
    `provisional_price_cents` — a mismatch is rejected with
    `ERR_CLAIM_AMOUNT_MISMATCH`"

    Design: Corner/validations/claim_amount_mismatch_rejected
    """
    scn = _setup_s5()
    res = api_client.create_claim(
        scn["policy"]["id"],
        {"compound_order_id": scn["order"]["id"], "claimed_amount_cents": 999,
         "expected_policy_version": fetch_policy(scn["policy"]["id"])["version"]},
        make_owner_headers(scn["owner"]["id"]))
    validate_error(res, ApiErrorId.ERR_CLAIM_AMOUNT_MISMATCH)


def test_policy_number_must_be_unique(api):
    """PRD §3.6: "a `policy_number` that must be unique — duplicates are rejected
    with `ERR_POLICY_NUMBER_EXISTS`"

    Design: Corner/validations/policy_number_must_be_unique
    """
    owner = create_owner()
    pet = create_pet(owner["id"], species="CAT", weight_kg=4)
    create_policy_for_pet(pet["id"], owner["id"], policy_number="POL-V9",
                          deductible_cents=0, coverage_pct=0.8)
    res = api_client.create_insurance_policy(
        {"pet_id": pet["id"], "insurer_name": "OtherIns", "policy_number": "POL-V9",
         "deductible_cents": 1000, "coverage_pct": 0.7, "annual_limit_cents": 50000,
         "renewal_date": "2027-06-01"},
        make_owner_headers(owner["id"]))
    validate_error(res, ApiErrorId.ERR_POLICY_NUMBER_EXISTS)


def test_pharmacist_cannot_adjudicate_claim(api):
    """PRD §2.1: "A request whose role is not listed among the endpoint's
    authorized roles is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.6: "Adjudication is an `InsuranceAdjuster` decision supplied as an
    `outcome` of `APPROVE` or `REJECT`." — a Pharmacist attempt is not in the
    endpoint's authorized set.

    Design: Corner/rbac/pharmacist_cannot_adjudicate_claim
    """
    scn = _setup_s5()
    res = api_client.adjudicate_claim(scn["claim"]["id"], {"outcome": "APPROVE"},
                                      TEST_USERS["pharmacist_a_headers"])
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert fetch_claim(scn["claim"]["id"])["status"] == "SUBMITTED"
