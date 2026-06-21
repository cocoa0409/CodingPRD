"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD:
- Supplier.accreditation_active: optional (defaults true, §3.1)
- HCPCSItem.requires_cmn / requires_prior_auth / is_cpap: optional (default false, §3.1)
- DMEOrder.modifier: optional (defaults NONE, §3.2)
- Delivery.pod_signature_name: optional at create (§3.5)
- RentalBillingCycle.period_start_utc: optional (back-bill, §3.7)
- PriorAuthorization.decision_reason: optional on approve/deny (§3.4)
"""

DEFAULTS = {
    "MONTHLY_RENTAL_CENTS": 10000,
    "PURCHASE_PRICE_CENTS": 100000,
}


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "medicare_id": "MBI-TEST-1",
        "date_of_birth": "1960-01-01",
        "address_state": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Supplier",
        "ptan": "PTAN-TEST-1",
        "accreditation_active": True,
    }
    defaults.update(overrides)
    return defaults


def create_hcpcs_item_payload(**overrides) -> dict:
    defaults = {
        "hcpcs_code": "K0001",
        "description": "Standard wheelchair",
        "billing_category": "CAPPED_RENTAL",
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
        "monthly_rental_cents": DEFAULTS["MONTHLY_RENTAL_CENTS"],
        "requires_cmn": False,
        "requires_prior_auth": False,
        "is_cpap": False,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(patient_id, supplier_id, hcpcs_item_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "supplier_id": supplier_id,
        "hcpcs_item_id": hcpcs_item_id,
        "acquisition_type": "RENTAL",
        "modifier": "KX",
        "ordered_at_utc": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cmn_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "physician_npi": "NPI-TEST",
        "length_of_need_months": 12,
        "signed_date": "2025-12-15",
    }
    defaults.update(overrides)
    return defaults


def create_prior_auth_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "payer_reference": "PR-TEST",
    }
    defaults.update(overrides)
    return defaults


def create_delivery_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "scheduled_for_utc": "2026-01-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_resupply_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "supply_kind": "MASK",
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(order_id, reason_code, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "reason_code": reason_code,
    }
    defaults.update(overrides)
    return defaults
