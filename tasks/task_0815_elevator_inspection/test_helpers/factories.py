"""Payload factories — one per create/action endpoint, input fields only."""

_COUNTER = {"n": 0}


def _next() -> int:
    _COUNTER["n"] += 1
    return _COUNTER["n"]


def create_owner_payload(**overrides) -> dict:
    n = _next()
    defaults = {"name": f"Owner {n}", "contact_email": f"owner{n}@example.com"}
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Inspector {n}",
        "license_number": f"L-{n}",
        "license_expiry_period": 999,
        "certified_categories": ["PASSENGER_ELEVATOR"],
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(owner_id, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "category": "PASSENGER_ELEVATOR",
        "location_description": "Test location",
        "install_period": 0,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(device_id, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "type": "ANNUAL",
        "scheduled_start_period": 1,
        "scheduled_end_period": 2,
    }
    defaults.update(overrides)
    return defaults


def create_fee_invoice_payload(device_id, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "type": "ANNUAL_RENEWAL",
        "due_period": 12,
    }
    defaults.update(overrides)
    return defaults


def create_citation_payload(deficiency_id, **overrides) -> dict:
    defaults = {"deficiency_id": deficiency_id}
    defaults.update(overrides)
    return defaults


def create_certificate_payload(device_id, source_inspection_id, expected_device_version, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "source_inspection_id": source_inspection_id,
        "expected_device_version": expected_device_version,
    }
    defaults.update(overrides)
    return defaults


def create_oos_order_payload(device_id, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "reason": "NONPAYMENT",
        "effective_start_period": 0,
        "effective_end_period": 5,
    }
    defaults.update(overrides)
    return defaults


def create_accident_report_payload(device_id, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "severity": "SEVERE",
        "occurred_period": 1,
        "description": "Test accident narrative",
    }
    defaults.update(overrides)
    return defaults


def assign_payload(assigned_inspector_id) -> dict:
    return {"assigned_inspector_id": assigned_inspector_id}


def complete_payload(result, deficiencies=None) -> dict:
    payload = {"result": result}
    if deficiencies is not None:
        payload["deficiencies"] = deficiencies
    return payload


def deficiency_entry(code="D-1", severity="MINOR", description="finding") -> dict:
    return {"code": code, "severity": severity, "description": description}


def open_investigation_payload(lead_investigator_id) -> dict:
    return {"lead_investigator_id": lead_investigator_id}


def close_payload(finding) -> dict:
    return {"finding": finding}


def resolve_contest_payload(outcome) -> dict:
    return {"outcome": outcome}
