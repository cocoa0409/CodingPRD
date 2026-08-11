"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
(the server starts with an empty database for every test). Setup calls use the
lenient get_success_data() validator so failures surface as clear setup errors.

Identity threading (PRD §2.1): Owner and Veterinarian are entity-backed roles;
every ownership-gated call uses make_owner_headers(entity_id) /
make_veterinarian_headers(entity_id) with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from . import factories
from .test_users import TEST_USERS, make_owner_headers, make_veterinarian_headers

DEFAULT_BENCH_WINDOW = ("2026-05-01T09:00:00Z", "2026-05-01T10:00:00Z")


# ─── Single-entity creators ────────────────────────────

def create_owner(**overrides) -> dict:
    return get_success_data(api_client.create_owner(
        factories.create_owner_payload(**overrides), TEST_USERS["pharmacy_admin_headers"]))


def create_pet(owner_id, **overrides) -> dict:
    return get_success_data(api_client.create_pet(
        owner_id, factories.create_pet_payload(**overrides), TEST_USERS["pharmacy_admin_headers"]))


def create_veterinarian(with_dea: bool = True, **overrides) -> dict:
    return get_success_data(api_client.create_veterinarian(
        factories.create_veterinarian_payload(with_dea=with_dea, **overrides),
        TEST_USERS["pharmacy_admin_headers"]))


def create_verified_vet(with_dea: bool = True, **overrides) -> dict:
    vet = create_veterinarian(with_dea=with_dea, **overrides)
    return get_success_data(api_client.verify_veterinarian(
        vet["id"], TEST_USERS["compliance_officer_headers"]))


def create_drug(**overrides) -> dict:
    return get_success_data(api_client.create_drug_catalog_item(
        factories.create_drug_payload(**overrides), TEST_USERS["pharmacy_admin_headers"]))


def create_flavoring(**overrides) -> dict:
    return get_success_data(api_client.create_flavoring(
        factories.create_flavoring_payload(**overrides), TEST_USERS["pharmacy_admin_headers"]))


def create_formula(drug_id, **overrides) -> dict:
    return get_success_data(api_client.create_formula(
        factories.create_formula_payload(drug_id, **overrides), TEST_USERS["pharmacist_a_headers"]))


def create_lot(drug_id, **overrides) -> dict:
    return get_success_data(api_client.create_lot(
        factories.create_lot_payload(drug_id, **overrides), TEST_USERS["pharmacy_tech_headers"]))


def create_bench(**overrides) -> dict:
    return get_success_data(api_client.create_bench(
        factories.create_bench_payload(**overrides), TEST_USERS["pharmacy_admin_headers"]))


def create_cooler(**overrides) -> dict:
    return get_success_data(api_client.create_cooler(
        factories.create_cooler_payload(**overrides), TEST_USERS["pharmacy_admin_headers"]))


def create_wellness_plan(**overrides) -> dict:
    return get_success_data(api_client.create_wellness_plan(
        factories.create_wellness_plan_payload(**overrides), TEST_USERS["pharmacy_admin_headers"]))


# ─── Fetchers (current server state) ───────────────────

def fetch_owner(owner_id) -> dict:
    return get_success_data(api_client.get_owner(owner_id, TEST_USERS["pharmacy_admin_headers"]))


def fetch_prescription(rx_id) -> dict:
    return get_success_data(api_client.get_prescription(rx_id, TEST_USERS["pharmacy_tech_headers"]))


def fetch_compound_order(order_id) -> dict:
    return get_success_data(api_client.get_compound_order(order_id, TEST_USERS["pharmacy_tech_headers"]))


def fetch_lot(lot_id) -> dict:
    return get_success_data(api_client.get_lot(lot_id, TEST_USERS["pharmacy_tech_headers"]))


def fetch_shipment(shipment_id) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, TEST_USERS["pharmacy_tech_headers"]))


def fetch_enrollment(enrollment_id, owner_id) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, make_owner_headers(owner_id)))


def fetch_policy(policy_id) -> dict:
    return get_success_data(api_client.get_insurance_policy(policy_id, TEST_USERS["insurance_adjuster_headers"]))


def fetch_claim(claim_id) -> dict:
    return get_success_data(api_client.get_claim(claim_id, TEST_USERS["insurance_adjuster_headers"]))


def fetch_schedule(schedule_id, owner_id) -> dict:
    return get_success_data(api_client.get_auto_ship_schedule(schedule_id, make_owner_headers(owner_id)))


def fetch_cooler(cooler_id) -> dict:
    return get_success_data(api_client.get_cooler(cooler_id, TEST_USERS["pharmacy_admin_headers"]))


def fetch_recall(recall_id) -> dict:
    return get_success_data(api_client.get_recall(recall_id, TEST_USERS["compliance_officer_headers"]))


# ─── Prescription lifecycle ────────────────────────────

def create_prescription(pet, owner, vet, formula, **overrides) -> dict:
    """Script intake by PharmacyTech. Returns the RECEIVED prescription."""
    return get_success_data(api_client.create_prescription(
        factories.create_prescription_payload(pet["id"], owner["id"], vet["id"], formula["id"],
                                              **overrides),
        TEST_USERS["pharmacy_tech_headers"]))


def submit_for_verification(rx_id) -> dict:
    return get_success_data(api_client.submit_verification(rx_id, TEST_USERS["pharmacy_tech_headers"]))


def vet_confirm_prescription(rx_id, vet_id) -> dict:
    return get_success_data(api_client.vet_confirm(rx_id, make_veterinarian_headers(vet_id)))


def verify_prescription(rx_id, vet_id) -> dict:
    """RECEIVED -> VET_VERIFICATION_PENDING -> VERIFIED. Returns VERIFIED data."""
    submit_for_verification(rx_id)
    return vet_confirm_prescription(rx_id, vet_id)


# ─── Compound order lifecycle ──────────────────────────

def current_rx_version(rx_id) -> int:
    return fetch_prescription(rx_id)["version"]


def create_compound_order(rx_id, flavoring_id=None, is_refill=False,
                          expected_prescription_version=None) -> dict:
    """Create a first-fill or refill order (OCC on Prescription). Fetches the
    current prescription version when not supplied."""
    if expected_prescription_version is None:
        expected_prescription_version = current_rx_version(rx_id)
    return get_success_data(api_client.create_compound_order(
        rx_id,
        factories.create_compound_order_payload(expected_prescription_version,
                                                flavoring_id=flavoring_id, is_refill=is_refill),
        TEST_USERS["pharmacy_tech_headers"]))


def allocate_order(order_id) -> dict:
    return get_success_data(api_client.allocate_order(order_id, TEST_USERS["pharmacy_tech_headers"]))


def start_compounding(order_id, bench_id, window=DEFAULT_BENCH_WINDOW,
                      pharmacist_headers=None) -> dict:
    headers = pharmacist_headers or TEST_USERS["pharmacist_a_headers"]
    return get_success_data(api_client.start_compounding(
        order_id, {"bench_id": bench_id, "start_at": window[0], "end_at": window[1]}, headers))


def complete_compounding(order_id, pharmacist_headers=None) -> dict:
    headers = pharmacist_headers or TEST_USERS["pharmacist_a_headers"]
    return get_success_data(api_client.complete_compounding(order_id, headers))


def complete_flavoring(order_id, pharmacist_headers=None) -> dict:
    headers = pharmacist_headers or TEST_USERS["pharmacist_a_headers"]
    return get_success_data(api_client.complete_flavoring(order_id, headers))


def qa_pass_order(order_id, pharmacist_headers=None) -> dict:
    headers = pharmacist_headers or TEST_USERS["pharmacist_b_headers"]
    return get_success_data(api_client.qa_pass(order_id, headers))


def pay_order_card(order_id, owner_id) -> dict:
    return get_success_data(api_client.pay_order(
        order_id, {"payment_method": "CARD"}, make_owner_headers(owner_id)))


def create_shipment_for_order(order_id, cooler_id=None, **overrides) -> dict:
    return get_success_data(api_client.create_shipment(
        order_id, factories.create_shipment_payload(cooler_asset_id=cooler_id, **overrides),
        TEST_USERS["pharmacist_a_headers"]))


def pickup_shipment(shipment_id) -> dict:
    return get_success_data(api_client.mark_picked_up(shipment_id, TEST_USERS["pharmacist_a_headers"]))


def order_to_ready(rx_id, bench_id, flavoring_id=None, window=DEFAULT_BENCH_WINDOW,
                   is_refill=False) -> dict:
    """Create -> allocate -> compound -> (flavor) -> QA pass. Returns READY_TO_DISPATCH order."""
    order = create_compound_order(rx_id, flavoring_id=flavoring_id, is_refill=is_refill)
    allocate_order(order["id"])
    start_compounding(order["id"], bench_id, window)
    complete_compounding(order["id"])
    if flavoring_id is not None:
        complete_flavoring(order["id"])
    return qa_pass_order(order["id"])


def order_to_paid(rx_id, bench_id, flavoring_id=None, window=DEFAULT_BENCH_WINDOW) -> dict:
    """READY_TO_DISPATCH order, paid by CARD. Returns paid order data."""
    order = order_to_ready(rx_id, bench_id, flavoring_id=flavoring_id, window=window)
    return pay_order_card(order["id"], _prescription_owner_id(rx_id))


def order_to_dispensed(rx_id, bench_id, flavoring_id=None, cooler_id=None,
                       shipment_overrides=None, window=DEFAULT_BENCH_WINDOW) -> tuple:
    """Full pipeline through carrier pickup (order DISPENSED). Returns (order, shipment)."""
    order = order_to_paid(rx_id, bench_id, flavoring_id=flavoring_id, window=window)
    shipment = create_shipment_for_order(order["id"], cooler_id=cooler_id,
                                         **(shipment_overrides or {}))
    pickup_shipment(shipment["id"])
    return fetch_compound_order(order["id"]), fetch_shipment(shipment["id"])


def _prescription_owner_id(rx_id) -> str:
    return fetch_prescription(rx_id)["owner_id"]


# ─── Wellness / insurance helpers ──────────────────────

def create_enrollment_for_pet(pet_id, plan_id, owner_id) -> dict:
    """Enroll a pet (OCC on Owner); fetches the current owner version."""
    owner_version = fetch_owner(owner_id)["version"]
    return get_success_data(api_client.create_enrollment(
        factories.create_enrollment_payload(pet_id, plan_id, owner_version),
        make_owner_headers(owner_id)))


def create_policy_for_pet(pet_id, owner_id, **overrides) -> dict:
    return get_success_data(api_client.create_insurance_policy(
        factories.create_policy_payload(pet_id, **overrides), make_owner_headers(owner_id)))


def create_claim_for_order(policy, order, claimed_amount_cents, owner_id) -> dict:
    """Submit a claim (OCC on InsurancePolicy); fetches the current policy version."""
    policy_version = fetch_policy(policy["id"])["version"]
    return get_success_data(api_client.create_claim(
        policy["id"],
        factories.create_claim_payload(order["id"], claimed_amount_cents, policy_version),
        make_owner_headers(owner_id)))


def create_schedule_for_rx(rx_id, owner_id, **overrides) -> dict:
    """Create an auto-ship schedule (OCC on Prescription); fetches current version."""
    rx_version = current_rx_version(rx_id)
    return get_success_data(api_client.create_auto_ship_schedule(
        factories.create_auto_ship_payload(rx_id, rx_version, **overrides),
        make_owner_headers(owner_id)))


# ─── Full verified scenario builder ────────────────────

def setup_verified_scenario(*, pet_weight_kg=6.0, pet_species="DOG", pet_allergies=None,
                            drug_schedule="NON_CONTROLLED", requires_cold_chain=False,
                            catalog_unit_cost=100, cold_min=2, cold_max=8,
                            drug_beyond_use_days=14,
                            flavor=None, quantity=5, days_supply=5, refills_authorized=0,
                            vet_dea=True, directions="QD") -> dict:
    """Owner + pet + verified vet + catalog drug + formula + VERIFIED prescription.

    flavor: optional dict of flavoring payload overrides (creates a Flavoring).
    Returns a dict with owner, pet, vet, drug, flavoring, formula, rx (VERIFIED),
    and rx_version (current prescription version after vet confirmation).
    """
    owner = create_owner()
    pet = create_pet(owner["id"], species=pet_species, weight_kg=pet_weight_kg,
                     allergies=pet_allergies if pet_allergies is not None else [])
    vet = create_verified_vet(with_dea=vet_dea)
    drug_kwargs = dict(schedule=drug_schedule, requires_cold_chain=requires_cold_chain,
                       unit_cost_cents=catalog_unit_cost, default_beyond_use_days=drug_beyond_use_days)
    if requires_cold_chain:
        drug_kwargs["cold_chain_min_celsius"] = cold_min
        drug_kwargs["cold_chain_max_celsius"] = cold_max
    drug = create_drug(**drug_kwargs)
    flavoring = create_flavoring(**flavor) if flavor is not None else None
    formula = create_formula(drug["id"], beyond_use_days=drug_beyond_use_days)
    rx = create_prescription(pet, owner, vet, formula, quantity=quantity,
                             days_supply=days_supply, refills_authorized=refills_authorized,
                             directions=directions)
    rx = verify_prescription(rx["id"], vet["id"])
    return {
        "owner": owner,
        "pet": pet,
        "vet": vet,
        "drug": drug,
        "flavoring": flavoring,
        "formula": formula,
        "rx": rx,
        "rx_version": rx["version"],
    }


def list_order_ids_for_prescription(rx_id) -> list:
    data, _meta = validate_paginated(api_client.list_prescription_compound_orders(
        rx_id, TEST_USERS["pharmacy_tech_headers"]))
    return [o["id"] for o in data]


def list_orders_for_prescription(rx_id) -> list:
    data, _meta = validate_paginated(api_client.list_compound_orders(
        TEST_USERS["pharmacy_tech_headers"], params={"prescription_id": rx_id}))
    return data
