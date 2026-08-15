"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PRINCIPAL_NAME": "Apex Shipping",
    "PRINCIPAL_EMAIL": "ops@apex.example",
    "VESSEL_NAME": "SS Rye",
    "IMO_NUMBER": "9000020",
    "VESSEL_GT": 5000,
    "FLAG_STATE": "PA",
    "PORT_CODE": "NODUE",
    "ETA": "2026-06-01T10:00:00Z",
    "ETD": "2026-06-02T10:00:00Z",
    "CARGO_DESCRIPTION": "general",
    "VENDOR_NAME": "ChandlerCo",
    "VENDOR_EMAIL": "sales@chandler.example",
    "NEEDED_BY": "2026-06-01T09:00:00Z",
    "PASSPORT_EXPIRY": "2027-01-01T00:00:00Z",
}


def create_principal_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PRINCIPAL_NAME"],
        "contact_email": DEFAULTS["PRINCIPAL_EMAIL"],
        "credit_limit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_port_call_payload(principal_id, **overrides) -> dict:
    defaults = {
        "principal_id": principal_id,
        "vessel_name": DEFAULTS["VESSEL_NAME"],
        "imo_number": DEFAULTS["IMO_NUMBER"],
        "vessel_gt": DEFAULTS["VESSEL_GT"],
        "flag_state": DEFAULTS["FLAG_STATE"],
        "port_code": DEFAULTS["PORT_CODE"],
        "eta": DEFAULTS["ETA"],
        "etd": DEFAULTS["ETD"],
        "cargo_description": DEFAULTS["CARGO_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_notification_payload(port_call_id, authority_type="CUSTOMS", **overrides) -> dict:
    defaults = {
        "port_call_id": port_call_id,
        "authority_type": authority_type,
        "payload_summary": "filing package",
    }
    defaults.update(overrides)
    return defaults


def create_berth_window_payload(port_call_id, **overrides) -> dict:
    defaults = {
        "port_call_id": port_call_id,
        "berth_code": "BERTH-01",
        "start_at": "2026-06-01T08:00:00Z",
        "end_at": "2026-06-01T20:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_order_payload(port_call_id, **overrides) -> dict:
    defaults = {
        "port_call_id": port_call_id,
        "kind": "TUG",
        "resource_unit": "TUG-1",
        "window_start": "2026-06-01T12:00:00Z",
        "window_end": "2026-06-01T13:00:00Z",
        "estimated_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_crew_change_payload(port_call_id, **overrides) -> dict:
    defaults = {
        "port_call_id": port_call_id,
        "full_name": "A. Ng",
        "nationality": "SG",
        "passport_no": "S1",
        "passport_expiry": DEFAULTS["PASSPORT_EXPIRY"],
        "direction": "ON_SIGNER",
        "requires_visa": False,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VENDOR_NAME"],
        "categories": ["PROVISIONS"],
        "contact_email": DEFAULTS["VENDOR_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(port_call_id, vendor_id, **overrides) -> dict:
    defaults = {
        "port_call_id": port_call_id,
        "vendor_id": vendor_id,
        "category": "PROVISIONS",
        "estimated_cents": 10000,
        "needed_by": DEFAULTS["NEEDED_BY"],
    }
    defaults.update(overrides)
    return defaults


def create_cargo_document_payload(port_call_id, **overrides) -> dict:
    defaults = {
        "port_call_id": port_call_id,
        "doc_type": "BILL_OF_LADING",
        "bl_number": "BL-1",
        "consignee_name": "ConsCo",
    }
    defaults.update(overrides)
    return defaults


def create_tariff_payload(**overrides) -> dict:
    defaults = {
        "port_code": "SINGA",
        "component": "PORT_DUES",
        "effective_from": "2026-01-01T00:00:00Z",
        "night_surcharge_pct": 0.25,
        "hazmat_surcharge_pct": 0.40,
        "gt_tiers": [{"gt_up_to": None, "rate_cents": 2.0}],
    }
    defaults.update(overrides)
    return defaults


def create_da_payload(port_call_id, expected_port_call_version, **overrides) -> dict:
    defaults = {
        "port_call_id": port_call_id,
        "expected_port_call_version": expected_port_call_version,
    }
    defaults.update(overrides)
    return defaults


def create_da_line_payload(**overrides) -> dict:
    defaults = {
        "category": "SUNDRY",
        "description": "manual line",
        "estimated_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_funding_advance_payload(**overrides) -> dict:
    defaults = {"amount_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_cost_dispute_payload(da_id, **overrides) -> dict:
    defaults = {
        "da_id": da_id,
        "amount_cents": 1000,
        "reason": "dispute rationale",
    }
    defaults.update(overrides)
    return defaults


def create_husbandry_case_payload(port_call_id, **overrides) -> dict:
    defaults = {
        "port_call_id": port_call_id,
        "case_type": "MEDICAL",
        "severity": "URGENT",
        "summary": "case summary",
    }
    defaults.update(overrides)
    return defaults
