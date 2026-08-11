"""Prescription intake: computed fields, type constraints, and safety screens."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_owner, create_pet, create_veterinarian, create_verified_vet,
    create_drug, create_flavoring, create_formula, create_prescription,
    verify_prescription, submit_for_verification, setup_verified_scenario,
    list_orders_for_prescription,
    TEST_USERS, make_veterinarian_headers,
)


def test_pet_weight_must_be_positive(api):
    """PRD §3.1: "a `weight_kg` that must be greater than zero because it drives
    the pricing tier".
    PRD §2.9: "required fields present and correctly typed, enum values within
    their declared sets, pet weight greater than zero, reservation end after
    start, otherwise `ERR_INVALID_REQUEST`."
    weight_kg 0 is rejected at intake with ERR_INVALID_REQUEST 400.

    Design: Corner/entities/pet_weight_must_be_positive
    """
    owner = create_owner()
    res = api_client.create_pet(owner["id"],
                                {"name": "Zero", "species": "DOG", "weight_kg": 0,
                                 "allergies": []},
                                TEST_USERS["pharmacy_admin_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_prescription_controlled_expiration_computed(api):
    """PRD §3.3: "The `expiration_date` is computed as the `written_date` plus 365
    days for a `NON_CONTROLLED` drug, or plus 180 days for any controlled schedule;
    any client-supplied expiration value is ignored."
    PRD §3.3: "The `schedule_snapshot` copies the drug's `schedule` from the catalog
    item at that moment — later catalog edits do not mutate it — and `is_controlled`
    is derived as true whenever the formula's drug schedule is anything other than
    `NON_CONTROLLED`."
    A C_IV script written 2026-05-01 expires 2026-10-28 (+180d); a NON_CONTROLLED
    script the same day expires 2027-05-01 (+365d).

    Design: Corner/entities/prescription_controlled_expiration_computed
    """
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=7)
    vet = create_verified_vet()
    drug_c = create_drug(schedule="C_IV", unit_cost_cents=350, default_beyond_use_days=30)
    drug_n = create_drug(schedule="NON_CONTROLLED", unit_cost_cents=100)
    frm_c = create_formula(drug_c["id"], beyond_use_days=30)
    frm_n = create_formula(drug_n["id"])
    rx_c = create_prescription(pet, owner, vet, frm_c, quantity=10, days_supply=10,
                               refills_authorized=1, directions="BID")
    rx_n = create_prescription(pet, owner, vet, frm_n, quantity=10, days_supply=10,
                               refills_authorized=1)
    assert rx_c["expiration_date"] == "2026-10-28", (
        f"C_IV expiration expected 2026-10-28, got {rx_c['expiration_date']}")
    assert rx_c["is_controlled"] is True
    assert rx_c["schedule_snapshot"] == "C_IV"
    assert rx_n["expiration_date"] == "2027-05-01", (
        f"NON_CONTROLLED expiration expected 2027-05-01, got {rx_n['expiration_date']}")
    assert rx_n["is_controlled"] is False
    assert rx_n["schedule_snapshot"] == "NON_CONTROLLED"


def test_prescription_not_found_returns_404(api):
    """PRD §2.8: "The request is rejected immediately with `ERR_NOT_FOUND` (HTTP
    404) at the first path identifier that does not correspond to an existing
    resource, before any later identifier or business rule is examined."

    Design: Corner/entities/prescription_not_found_returns_404
    """
    res = api_client.get_prescription(NON_EXISTENT_UUID, TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_prescription_initial_state_received(api):
    """PRD §3.3: "The prescription's `refills_remaining` is initialized to
    `refills_authorized`, `clarification_count` starts at zero, and `status` starts
    at `RECEIVED`."

    Design: Corner/state_machines/prescription_initial_state_received
    """
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=7)
    vet = create_verified_vet()
    drug = create_drug()
    formula = create_formula(drug["id"])
    rx = create_prescription(pet, owner, vet, formula, quantity=10, days_supply=10,
                             refills_authorized=3)
    assert rx["status"] == "RECEIVED"
    assert rx["refills_remaining"] == 3
    assert rx["clarification_count"] == 0


def test_dea_required_for_controlled_intake(api):
    """PRD §3.3: "a formula built on a controlled drug requires the prescribing
    veterinarian to hold a `dea_registration_number`, otherwise the intake is
    rejected with `ERR_CONTROLLED_DEA_REQUIRED`".

    Design: Corner/validations/dea_required_for_controlled_intake
    """
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=6)
    vet = create_verified_vet(with_dea=False)
    drug = create_drug(schedule="C_IV", unit_cost_cents=350, default_beyond_use_days=30)
    formula = create_formula(drug["id"], beyond_use_days=30)
    res = api_client.create_prescription(
        {"pet_id": pet["id"], "owner_id": owner["id"], "veterinarian_id": vet["id"],
         "formula_id": formula["id"], "quantity": 10, "days_supply": 10,
         "refills_authorized": 0, "directions": "BID", "written_date": "2026-05-01"},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_CONTROLLED_DEA_REQUIRED)


def test_cii_refills_forbidden_at_intake(api):
    """PRD §3.3: "a `C_II` prescription must carry zero `refills_authorized`,
    otherwise it is rejected with `ERR_CONTROLLED_REFILL_FORBIDDEN`".

    Design: Corner/validations/cii_refills_forbidden_at_intake
    """
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=6)
    vet = create_verified_vet()
    drug = create_drug(schedule="C_II", unit_cost_cents=900, default_beyond_use_days=30)
    formula = create_formula(drug["id"], beyond_use_days=30)
    res = api_client.create_prescription(
        {"pet_id": pet["id"], "owner_id": owner["id"], "veterinarian_id": vet["id"],
         "formula_id": formula["id"], "quantity": 10, "days_supply": 10,
         "refills_authorized": 1, "directions": "BID", "written_date": "2026-05-01"},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_CONTROLLED_REFILL_FORBIDDEN)


def _setup_allergen_scenario():
    """VERIFIED rx for a CHICKEN-allergic dog; chicken flavor tagged CHICKEN."""
    scn = setup_verified_scenario(pet_weight_kg=6, pet_allergies=["CHICKEN"],
                                  flavor={"name": "ChickenV2", "allergen_tags": ["CHICKEN"],
                                          "surcharge_cents": 250,
                                          "compatible_species": ["DOG", "CAT"]},
                                  quantity=5, days_supply=5)
    return scn


def test_allergen_conflict_rejects_create(api):
    """PRD §3.4: "If any element of the chosen flavoring's `allergen_tags` appears
    in the pet's `allergies`, creation is rejected with `ERR_ALLERGEN_CONFLICT`."

    Design: Corner/validations/allergen_conflict_rejects_create
    """
    scn = _setup_allergen_scenario()
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"flavoring_id": scn["flavoring"]["id"], "is_refill": False,
         "expected_prescription_version": scn["rx_version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_ALLERGEN_CONFLICT)
    assert list_orders_for_prescription(scn["rx"]["id"]) == []


def test_species_incompatible_flavor_rejected(api):
    """PRD §3.4: "If the pet's `species` is not among the flavoring's
    `compatible_species`, creation is rejected with
    `ERR_SPECIES_FLAVOR_INCOMPATIBLE`."

    Design: Corner/validations/species_incompatible_flavor_rejected
    """
    scn = setup_verified_scenario(pet_weight_kg=4, pet_species="CAT",
                                  flavor={"name": "BeefV3", "allergen_tags": [],
                                          "surcharge_cents": 200,
                                          "compatible_species": ["DOG"]},
                                  quantity=5, days_supply=5)
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"flavoring_id": scn["flavoring"]["id"], "is_refill": False,
         "expected_prescription_version": scn["rx_version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_SPECIES_FLAVOR_INCOMPATIBLE)


def _build_rejected_rx_scenario():
    """Owner/pet(CHICKEN allergy)/vet/drug/flavor/formula; rx REJECTED by vet."""
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=8, allergies=["CHICKEN"])
    vet = create_verified_vet()
    drug = create_drug()
    flavoring = create_flavoring(name="ChickenP1", allergen_tags=["CHICKEN"],
                                 surcharge_cents=250, compatible_species=["DOG", "CAT"])
    formula = create_formula(drug["id"])
    rx = create_prescription(pet, owner, vet, formula, quantity=10, days_supply=10)
    submit_for_verification(rx["id"])
    rejected = get_success_data(api_client.vet_reject(
        rx["id"], {"reason": "contraindicated"}, make_veterinarian_headers(vet["id"])))
    return {"owner": owner, "pet": pet, "vet": vet, "flavoring": flavoring,
            "rx": rejected, "rx_version": rejected["version"]}


def test_state_gate_precedes_allergen_screen_error_id(api):
    """PRD §3.4: "The create is guarded by a fixed sequence of checks: the
    stale-version guard first (`ERR_STALE_VERSION`), then prescription state — an
    `EXPIRED` script is reported distinctly as `ERR_PRESCRIPTION_EXPIRED`, any other
    non-`VERIFIED` status as `ERR_PRESCRIPTION_NOT_VERIFIED`"
    PRD §3.4: "Two patient-safety screens then apply to flavored orders."
    A REJECTED prescription whose chosen flavor also conflicts with the pet's
    allergies reports ERR_PRESCRIPTION_NOT_VERIFIED, never ERR_ALLERGEN_CONFLICT.

    Design: Difficulty/priority_pair_validation_conflict/state_over_safety_on_order_create
    """
    scn = _build_rejected_rx_scenario()
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"flavoring_id": scn["flavoring"]["id"], "is_refill": False,
         "expected_prescription_version": scn["rx_version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_PRESCRIPTION_NOT_VERIFIED)


def test_state_gate_precedes_allergen_screen_no_order_created(api):
    """PRD §3.4: "Two patient-safety screens then apply to flavored orders. If any
    element of the chosen flavoring's `allergen_tags` appears in the pet's
    `allergies`, creation is rejected with `ERR_ALLERGEN_CONFLICT`."
    Because the state gate fires first on a REJECTED prescription, no CompoundOrder
    is persisted at all.

    Design: Difficulty/priority_pair_validation_conflict/state_over_safety_on_order_create
    """
    scn = _build_rejected_rx_scenario()
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"flavoring_id": scn["flavoring"]["id"], "is_refill": False,
         "expected_prescription_version": scn["rx_version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_PRESCRIPTION_NOT_VERIFIED)
    assert list_orders_for_prescription(scn["rx"]["id"]) == []
