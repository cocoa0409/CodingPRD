"""Composite setup helpers for the HCV landlord-participation workflows (PRD §3).

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints — the server is relaunched before every test, so nothing carries over.
Ownership-gated calls always use make_landlord_headers(landlord["id"]) per PRD §2.1.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_landlord_payload,
    create_property_payload,
    create_unit_payload,
    create_voucher_family_payload,
    create_payment_standard_payload,
    create_rent_comparable_payload,
    create_contract_payload,
    schedule_inspection_payload,
    create_repair_item_payload,
    record_result_payload,
    verify_item_payload,
    create_rent_increase_request_payload,
    create_recertification_payload,
    complete_recertification_payload,
)
from .test_users import TEST_USERS, make_landlord_headers

ADMIN = TEST_USERS["admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ── Tier 2: Entity hierarchy ─────────────────────────────────────

def create_landlord(**overrides):
    """Register a landlord (PRD §3.1). Returns the landlord dict."""
    resp = api_client.create_landlord(create_landlord_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_property(landlord_id: str, **overrides):
    """Create a property for a landlord (PRD §3.1). Returns the property dict."""
    resp = api_client.create_property(create_property_payload(landlord_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_unit(property_id: str, **overrides):
    """Create a unit within a property (PRD §3.1). Returns the unit dict."""
    resp = api_client.create_unit(property_id, create_unit_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_voucher_family(**overrides):
    """Register a voucher family (PRD §3.1). Returns the family dict."""
    resp = api_client.create_voucher_family(create_voucher_family_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_payment_standard(**overrides):
    """Create a payment standard row (PRD §3.2). Returns the standard dict."""
    resp = api_client.create_payment_standard(create_payment_standard_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_rent_comparable(**overrides):
    """Record a market-rent comparable (PRD §3.2). Returns the comparable dict."""
    resp = api_client.create_rent_comparable(create_rent_comparable_payload(**overrides), ADMIN)
    return get_success_data(resp)


def setup_landlord_property_unit(zip_code: str = "90001", bedroom_count: int = 1,
                                 landlord_overrides=None, **unit_overrides):
    """Landlord + property + unit. Returns (landlord, property, unit)."""
    landlord = create_landlord(**(landlord_overrides or {}))
    prop = create_property(landlord["id"], zip_code=zip_code)
    unit = create_unit(prop["id"], bedroom_count=bedroom_count, **unit_overrides)
    return landlord, prop, unit


def setup_priced_unit(zip_code: str = "90001", bedroom_count: int = 1,
                      standard_cents: int = 150_000, family_income_cents: int = 2_400_000,
                      family_code: str = "FAM-1", voucher_bedroom_size: int = None):
    """Landlord + property + unit + payment standard + voucher family.

    Returns (landlord, property, unit, family).
    """
    landlord, prop, unit = setup_landlord_property_unit(
        zip_code=zip_code, bedroom_count=bedroom_count
    )
    create_payment_standard(
        zip_code=zip_code, bedroom_count=bedroom_count, amount_cents=standard_cents
    )
    family = create_voucher_family(
        family_code=family_code,
        voucher_bedroom_size=voucher_bedroom_size if voucher_bedroom_size is not None else bedroom_count,
        annual_income_cents=family_income_cents,
    )
    return landlord, prop, unit, family


# ── Tier 1/3: Contract state progression ─────────────────────────

def create_draft_contract(unit, family, landlord, contract_rent_cents: int = 150_000,
                          lease_start_date: str = "2026-08-01"):
    """Create a HAP contract in DRAFT for a LISTED unit (PRD §3.3).

    Threads the unit's current version into expected_unit_version and uses the
    owning landlord's identity headers. Returns the contract dict.
    """
    resp = api_client.create_contract(
        create_contract_payload(
            unit["id"], family["id"], unit["version"],
            contract_rent_cents=contract_rent_cents, lease_start_date=lease_start_date,
        ),
        make_landlord_headers(landlord["id"]),
    )
    return get_success_data(resp)


def create_and_submit_contract(unit, family, landlord, **contract_kwargs):
    """Create contract + submit. Returns the PENDING_INSPECTION contract dict."""
    contract = create_draft_contract(unit, family, landlord, **contract_kwargs)
    resp = api_client.submit_contract(contract["id"], make_landlord_headers(landlord["id"]))
    return get_success_data(resp)


def _record_initial_pass(contract_id: str):
    """Record PASS on the auto-created INITIAL inspection (PRD §3.3, §3.4).

    Moves the contract PENDING_INSPECTION -> APPROVED. Returns the PASSED inspection.
    """
    inspections = get_success_data(api_client.list_contract_inspections(contract_id, ADMIN))
    initial = [i for i in inspections if i.get("inspection_type") == "INITIAL"]
    assert initial, f"Setup failed: no INITIAL inspection found for contract {contract_id}"
    resp = api_client.record_inspection_result(initial[0]["id"], record_result_payload("PASS"), INSPECTOR)
    return get_success_data(resp)


def create_and_approve_contract(unit, family, landlord, **contract_kwargs):
    """Create -> submit -> record INITIAL PASS. Returns the APPROVED contract dict."""
    contract = create_and_submit_contract(unit, family, landlord, **contract_kwargs)
    _record_initial_pass(contract["id"])
    resp = api_client.get_contract(contract["id"], ADMIN)
    return get_success_data(resp)


def create_and_activate_contract(unit, family, landlord, **contract_kwargs):
    """Full pipeline: create -> submit -> INITIAL PASS -> activate (PRD §3.5).

    Requires lease_start_date on or before the current logical date (default
    2026-08-01, PRD §2.7). Returns the ACTIVE contract dict.
    """
    contract = create_and_approve_contract(unit, family, landlord, **contract_kwargs)
    resp = api_client.activate_contract(contract["id"], ADMIN)
    return get_success_data(resp)


def setup_active_scenario(zip_code: str = "90001", bedroom_count: int = 1,
                          standard_cents: int = 150_000,
                          family_income_cents: int = 2_400_000,
                          family_code: str = "FAM-1",
                          contract_rent_cents: int = 150_000,
                          lease_start_date: str = "2026-08-01"):
    """Most common setup: priced unit + ACTIVE contract.

    Returns (landlord, property, unit, family, contract).
    """
    landlord, prop, unit, family = setup_priced_unit(
        zip_code=zip_code, bedroom_count=bedroom_count,
        standard_cents=standard_cents, family_income_cents=family_income_cents,
        family_code=family_code,
    )
    contract = create_and_activate_contract(
        unit, family, landlord,
        contract_rent_cents=contract_rent_cents, lease_start_date=lease_start_date,
    )
    return landlord, prop, unit, family, contract


# ── Tier 3: Inspection / repair lifecycle shortcuts ──────────────

def schedule_contract_inspection(contract_id: str, inspection_type: str = "ANNUAL",
                                 scheduled_date: str = "2026-08-05"):
    """Schedule a non-initial inspection (PRD §3.4). Returns the SCHEDULED inspection."""
    resp = api_client.schedule_inspection(
        contract_id,
        schedule_inspection_payload(
            inspection_type=inspection_type, scheduled_date=scheduled_date
        ),
        ADMIN,
    )
    return get_success_data(resp)


def attach_repair_item(inspection_id: str, description: str = "deficiency",
                       is_life_threatening: bool = False):
    """Attach a repair item to an inspection (PRD §3.4). Returns the OPEN item."""
    resp = api_client.create_repair_item(
        inspection_id,
        create_repair_item_payload(
            description=description, is_life_threatening=is_life_threatening
        ),
        INSPECTOR,
    )
    return get_success_data(resp)


def fail_inspection(inspection_id: str):
    """Record FAIL on a SCHEDULED inspection that has >= 1 repair item (PRD §3.4)."""
    resp = api_client.record_inspection_result(
        inspection_id, record_result_payload("FAIL"), INSPECTOR
    )
    return get_success_data(resp)


def setup_failed_inspection(contract, landlord, inspection_type: str = "ANNUAL",
                            scheduled_date: str = "2026-08-05",
                            description: str = "deficiency",
                            is_life_threatening: bool = False):
    """Active contract + inspection FAILED with one OPEN repair item (PRD §3.4).

    Returns (inspection, repair_item).
    """
    inspection = schedule_contract_inspection(
        contract["id"], inspection_type=inspection_type, scheduled_date=scheduled_date
    )
    item = attach_repair_item(
        inspection["id"], description=description, is_life_threatening=is_life_threatening
    )
    inspection = fail_inspection(inspection["id"])
    return inspection, item


def mark_item_repaired(repair_item_id: str, landlord):
    """Landlord marks a repair item repaired (owner-only, PRD §3.4)."""
    resp = api_client.mark_repair_item_repaired(
        repair_item_id, make_landlord_headers(landlord["id"])
    )
    return get_success_data(resp)


def request_reinspection(inspection_id: str, landlord):
    """Landlord requests reinspection once all items are REPAIRED (PRD §3.4)."""
    resp = api_client.request_reinspection(
        inspection_id, make_landlord_headers(landlord["id"])
    )
    return get_success_data(resp)


def verify_item(repair_item_id: str, outcome: str = "PASS"):
    """Inspector verifies (PASS) or refutes (FAIL) a repaired item (PRD §3.4)."""
    resp = api_client.verify_repair_item(repair_item_id, verify_item_payload(outcome), INSPECTOR)
    return get_success_data(resp)


def setup_repair_verification(contract, landlord, **fail_kwargs):
    """FAILED inspection with all items REPAIRED and inspection in REPAIR_VERIFICATION.

    Returns (inspection, repair_item).
    """
    inspection, item = setup_failed_inspection(contract, landlord, **fail_kwargs)
    mark_item_repaired(item["id"], landlord)
    inspection = request_reinspection(inspection["id"], landlord)
    return inspection, item


# ── Tier 5: Abatement terminal/cascade states ────────────────────

def setup_abated_contract(zip_code: str = "90001", standard_cents: int = 150_000,
                          family_income_cents: int = 2_400_000, family_code: str = "FAM-1",
                          contract_rent_cents: int = 150_000,
                          lease_start_date: str = "2026-08-01",
                          breach_clock: str = "2026-10-01T00:00:00Z",
                          is_life_threatening: bool = False):
    """Active contract -> FAILED inspection -> clock advanced past the repair deadline.

    After the clock advance the contract is ABATED, the unit SUSPENDED_ABATEMENT,
    and future SCHEDULED payments ABATED_HELD (PRD §3.4). The default FAIL occurs
    with the clock at 2026-08-01 (PRD §2.7), so an ordinary item's 30-day deadline
    is breached by 2026-10-01.

    Returns dict with landlord, property, unit, family, contract, inspection, item.
    """
    landlord, prop, unit, family, contract = setup_active_scenario(
        zip_code=zip_code, standard_cents=standard_cents,
        family_income_cents=family_income_cents, family_code=family_code,
        contract_rent_cents=contract_rent_cents, lease_start_date=lease_start_date,
    )
    inspection, item = setup_failed_inspection(
        contract, landlord, is_life_threatening=is_life_threatening
    )
    get_success_data(api_client.set_current_utc(breach_clock, ADMIN))
    contract = get_success_data(api_client.get_contract(contract["id"], ADMIN))
    return {
        "landlord": landlord, "property": prop, "unit": unit, "family": family,
        "contract": contract, "inspection": inspection, "item": item,
    }


def cure_abatement(abated: dict):
    """Cure an abated contract: mark repaired -> request reinspection -> verify PASS.

    On the last VERIFIED item the inspection CLOSES, the contract returns to ACTIVE
    and the unit returns to UNDER_CONTRACT (PRD §3.4). Returns the re-read contract.
    """
    landlord = abated["landlord"]
    inspection = abated["inspection"]
    item = abated["item"]
    contract = abated["contract"]
    mark_item_repaired(item["id"], landlord)
    request_reinspection(inspection["id"], landlord)
    verify_item(item["id"], "PASS")
    return get_success_data(api_client.get_contract(contract["id"], ADMIN))


def list_hap_payments(contract_id: str):
    """List HAP payments for a contract (PRD §3.6). Returns the data list."""
    return get_success_data(api_client.list_contract_hap_payments(contract_id, ADMIN))


# ── Recertification / rent-increase shortcuts ────────────────────

def open_recertification(contract_id: str, due_date: str = "2027-08-01",
                         new_family_income_cents: int = 3_000_000):
    """Open an annual recertification (PRD §3.7). Returns the OPEN recertification."""
    resp = api_client.create_recertification(
        create_recertification_payload(
            contract_id, due_date=due_date, new_family_income_cents=new_family_income_cents
        ),
        ADMIN,
    )
    return get_success_data(resp)


def create_increase_request(contract_id: str, landlord, requested_rent_cents: int = 160_000,
                            effective_date: str = "2027-08-01"):
    """Landlord requests a rent increase (owner-only, PRD §3.7). Returns the PENDING request."""
    resp = api_client.create_rent_increase_request(
        create_rent_increase_request_payload(
            contract_id, requested_rent_cents=requested_rent_cents,
            effective_date=effective_date,
        ),
        make_landlord_headers(landlord["id"]),
    )
    return get_success_data(resp)
