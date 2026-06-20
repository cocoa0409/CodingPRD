"""Payload factories — one per entity, input fields only (PRD §3, §4).

Each test runs against a freshly restarted, empty server, but factories still mint
unique natural keys (hrsa_id, ndc, npi) so that multiple entities created within a
single test never collide.
"""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_covered_entity_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "hrsa_id": f"DSH{n:07d}",
        "legal_name": "Test Covered Entity",
        "entity_type": "FQHC",
        "medicaid_billing_mode": "CARVE_OUT",
    }
    defaults.update(overrides)
    return defaults


def create_child_site_payload(**overrides) -> dict:
    defaults = {
        "site_name": "Test Child Site",
        "service_address": "1 Test Way",
    }
    defaults.update(overrides)
    return defaults


def create_prescriber_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "npi": f"{1000000000 + n}",
        "full_name": "Dr Test Prescriber",
        "relationship_type": "EMPLOYED",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "mrn": f"MRN-{n}",
        "has_ce_care_record": True,
        "ce_retains_responsibility": True,
        "medicaid_ffs_enrolled": False,
    }
    defaults.update(overrides)
    return defaults


def create_drug_product_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "ndc": f"{n % 100000:05d}-{n % 10000:04d}-{n % 100:02d}",
        "drug_name": "Test Drug",
        "package_size_units": 30,
        "wac_price_per_unit_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_ceiling_price_payload(**overrides) -> dict:
    defaults = {
        "quarter": "2026Q2",
        "amp_per_unit_cents": 4000,
        "ura_per_unit_cents": 1500,
        "is_published": True,
    }
    defaults.update(overrides)
    return defaults


def create_contract_pharmacy_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "pharmacy_name": "Test Pharmacy",
        "ship_to_bill_to_npi": f"{2000000000 + n}",
        "effective_start": "2026-01-01",
        "effective_end": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_accumulator_payload(drug_product_id: str, **overrides) -> dict:
    defaults = {"drug_product_id": drug_product_id}
    defaults.update(overrides)
    return defaults


def create_dispense_payload(covered_entity_id, patient_id, prescriber_id,
                            drug_product_id, quantity_units=4, quarter="2026Q2",
                            **overrides) -> dict:
    defaults = {
        "covered_entity_id": covered_entity_id,
        "patient_id": patient_id,
        "prescriber_id": prescriber_id,
        "drug_product_id": drug_product_id,
        "quantity_units": quantity_units,
        "quarter": quarter,
    }
    defaults.update(overrides)
    return defaults


def create_medicaid_claim_payload(**overrides) -> dict:
    defaults = {"medicaid_state_code": "CA"}
    defaults.update(overrides)
    return defaults


def create_audit_finding_payload(covered_entity_id, prescription_dispense_id,
                                 finding_type="DIVERSION", assessed_units=4,
                                 **overrides) -> dict:
    defaults = {
        "covered_entity_id": covered_entity_id,
        "prescription_dispense_id": prescription_dispense_id,
        "finding_type": finding_type,
        "assessed_units": assessed_units,
    }
    defaults.update(overrides)
    return defaults


def create_self_disclosure_payload(prescription_dispense_id, finding_type="DIVERSION",
                                   assessed_units=4, **overrides) -> dict:
    defaults = {
        "prescription_dispense_id": prescription_dispense_id,
        "finding_type": finding_type,
        "assessed_units": assessed_units,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(covered_entity_id, drug_product_id, channel="B340B",
                                  packages_ordered=1, quarter="2026Q2",
                                  unit_price_paid_cents=2700, **overrides) -> dict:
    defaults = {
        "covered_entity_id": covered_entity_id,
        "drug_product_id": drug_product_id,
        "channel": channel,
        "packages_ordered": packages_ordered,
        "quarter": quarter,
        "unit_price_paid_cents": unit_price_paid_cents,
    }
    defaults.update(overrides)
    return defaults


def remit_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def reconcile_payload(quarter: str, expected_drug_product_version: int) -> dict:
    return {"quarter": quarter, "expected_drug_product_version": expected_drug_product_version}


def replenish_payload(expected_accumulator_version: int) -> dict:
    return {"expected_accumulator_version": expected_accumulator_version}
