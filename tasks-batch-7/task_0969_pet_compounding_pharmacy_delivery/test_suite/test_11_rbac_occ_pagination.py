"""RBAC denials, optimistic concurrency guards, existence ordering, pagination."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_owner, create_pet, create_verified_vet, create_drug, create_formula,
    create_prescription, submit_for_verification, verify_prescription,
    create_compound_order, create_policy_for_pet, create_claim_for_order,
    fetch_policy, fetch_prescription, setup_verified_scenario,
    list_order_ids_for_prescription,
    TEST_USERS, make_owner_headers, make_veterinarian_headers,
)


def test_vet_cannot_confirm_other_vets_rx(api):
    """PRD §2.1: "Endpoints that declare an ownership rule — veterinary
    confirmation, rejection, and clarification of a prescription; an owner paying
    for an order; an owner appealing a claim; an owner acknowledging a recall task;
    enrollment suspension, resumption, and cancellation; and auto-ship pause,
    resume, and cancellation — reject a caller whose entity-backed `X-User-ID` does
    not own the targeted resource with `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.3: "The veterinarian — and only that veterinarian, enforced by the
    ownership rule on the prescription's `veterinarian_id` — then has three moves."

    Design: Corner/rbac/vet_cannot_confirm_other_vets_rx
    """
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=6)
    vet_a = create_verified_vet()
    vet_b = create_verified_vet()
    drug = create_drug()
    formula = create_formula(drug["id"])
    rx = create_prescription(pet, owner, vet_a, formula, quantity=5, days_supply=5)
    submit_for_verification(rx["id"])
    res = api_client.vet_confirm(rx["id"], make_veterinarian_headers(vet_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert fetch_prescription(rx["id"])["status"] == "VET_VERIFICATION_PENDING"


def test_owner_cannot_create_catalog_drug(api):
    """PRD §2.1: "A request whose role is not listed among the endpoint's
    authorized roles is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.2: "The drug catalog is administered by a `PharmacyAdmin`."

    Design: Corner/rbac/owner_cannot_create_catalog_drug
    """
    owner = create_owner()
    res = api_client.create_drug_catalog_item(
        {"drug_name": "HackR2", "schedule": "NON_CONTROLLED", "requires_cold_chain": False,
         "unit_cost_cents": 1, "default_beyond_use_days": 1},
        make_owner_headers(owner["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_existence_precedes_state_on_cancel(api):
    """PRD §2.8: "The request is rejected immediately with `ERR_NOT_FOUND` (HTTP
    404) at the first path identifier that does not correspond to an existing
    resource, before any later identifier or business rule is examined."
    Cancelling a nonexistent order id returns 404, never a state error.

    Design: Corner/validations/existence_precedes_state_on_cancel
    """
    res = api_client.cancel_order(NON_EXISTENT_UUID, TEST_USERS["pharmacist_a_headers"])
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_pagination_limit_offset_envelope(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned;
    it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter sets the number of items skipped and defaults to 0."
    PRD §2.3: "Paginated list responses include `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."
    With 2 prescriptions, limit=1 returns one item with total_count 2 and
    has_more true; offset=1 returns the other one with has_more false.

    Design: Corner/endpoints/pagination_limit_offset_envelope
    """
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=6)
    vet = create_verified_vet()
    drug = create_drug()
    formula = create_formula(drug["id"])
    rx1 = create_prescription(pet, owner, vet, formula, quantity=5, days_supply=5)
    rx2 = create_prescription(pet, owner, vet, formula, quantity=6, days_supply=6,
                              directions="BID")
    tech = TEST_USERS["pharmacy_tech_headers"]
    page1, meta1 = validate_paginated(api_client.list_prescriptions(
        tech, params={"owner_id": owner["id"], "limit": 1, "offset": 0}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0
    page2, meta2 = validate_paginated(api_client.list_prescriptions(
        tech, params={"owner_id": owner["id"], "limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert meta2["offset"] == 1
    assert {page1[0]["id"], page2[0]["id"]} == {rx1["id"], rx2["id"]}


def test_occ_compound_order_stale_version_rejected(api):
    """PRD §2.7: "Creating a compound order against a prescription requires
    `expected_prescription_version` carrying the prescription's current `version`
    as the client last observed it. Because the create legitimately supersedes an
    existing `CREATED` or `ALLOCATED` order, a writer holding a stale prescription
    view is turned away: if the value does not match the prescription's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_compound_order_stale_version_rejected
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5,
                                  refills_authorized=1)
    payload = {"is_refill": False, "expected_prescription_version": scn["rx_version"]}
    first = api_client.create_compound_order(scn["rx"]["id"], payload,
                                             TEST_USERS["pharmacy_tech_headers"])
    validate_success(first, 201)
    stale = api_client.create_compound_order(scn["rx"]["id"], payload,
                                             TEST_USERS["pharmacy_tech_headers"])
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert len(list_order_ids_for_prescription(scn["rx"]["id"])) == 1


def test_occ_claim_stale_version_rejected(api):
    """PRD §2.7: "Creating an insurance claim against a policy requires
    `expected_policy_version`; claim creation recomputes the policy's deductible
    estimate reserve and bumps its version, so a stale policy view is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_claim_stale_version_rejected
    """
    scn = setup_verified_scenario(pet_weight_kg=2, pet_species="CAT", quantity=5,
                                  days_supply=5)
    rx2 = verify_prescription(create_prescription(
        scn["pet"], scn["owner"], scn["vet"], scn["formula"], quantity=5,
        days_supply=5)["id"], scn["vet"]["id"])
    order1 = create_compound_order(scn["rx"]["id"],
                                   expected_prescription_version=scn["rx_version"])
    order2 = create_compound_order(rx2["id"], expected_prescription_version=rx2["version"])
    policy = create_policy_for_pet(scn["pet"]["id"], scn["owner"]["id"],
                                   deductible_cents=0, coverage_pct=1.0,
                                   annual_limit_cents=100000)
    headers = make_owner_headers(scn["owner"]["id"])
    first = api_client.create_claim(
        policy["id"], {"compound_order_id": order1["id"], "claimed_amount_cents": 500,
                       "expected_policy_version": policy["version"]}, headers)
    validate_success(first, 201)
    stale = api_client.create_claim(
        policy["id"], {"compound_order_id": order2["id"], "claimed_amount_cents": 500,
                       "expected_policy_version": policy["version"]}, headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    data, meta = validate_paginated(api_client.list_claims(
        headers, params={"policy_id": policy["id"]}))
    assert meta["total_count"] == 1
