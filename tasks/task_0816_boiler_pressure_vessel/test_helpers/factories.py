"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "JURISDICTION_CODE": "CA",
    "JURISDICTION_NAME": "California",
    "OWNER_NAME": "Acme Boilers",
    "OWNER_EMAIL": "o@x.com",
    "MANUFACTURER": "M",
    "NB_NUMBER": "NBV-1",
    "COMMISSION_NUMBER": "NBC-A",
    "MAWP": 120,
    "INSTALLED_AT": "2020-01-01T00:00:00Z",
}


def create_jurisdiction_payload(**overrides) -> dict:
    payload = {"code": DEFAULTS["JURISDICTION_CODE"], "name": DEFAULTS["JURISDICTION_NAME"]}
    payload.update(overrides)
    return payload


def create_insurance_company_payload(**overrides) -> dict:
    payload = {"name": "Insurer X", "nb_accreditation_number": "NBA-X"}
    payload.update(overrides)
    return payload


def create_owner_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["OWNER_NAME"], "contact_email": DEFAULTS["OWNER_EMAIL"]}
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> dict:
    payload = {
        "name": "Insp A",
        "commission_number": DEFAULTS["COMMISSION_NUMBER"],
        "inspector_type": "JURISDICTION",
    }
    payload.update(overrides)
    return payload


def create_vessel_payload(**overrides) -> dict:
    payload = {
        "manufacturer": DEFAULTS["MANUFACTURER"],
        "national_board_number": DEFAULTS["NB_NUMBER"],
        "vessel_class": "POWER_BOILER",
        "mawp_psig": DEFAULTS["MAWP"],
        "installed_at": DEFAULTS["INSTALLED_AT"],
    }
    payload.update(overrides)
    return payload


def create_insurance_policy_payload(**overrides) -> dict:
    payload = {
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(**overrides) -> dict:
    payload = {
        "inspection_type": "EXTERNAL",
        "scheduled_start": "2026-06-02T09:00:00Z",
        "scheduled_end": "2026-06-02T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_deficiency_payload(**overrides) -> dict:
    payload = {"severity": "NON_CRITICAL", "description": "finding"}
    payload.update(overrides)
    return payload


def create_repair_order_payload(**overrides) -> dict:
    payload = {"description": "repair"}
    payload.update(overrides)
    return payload


def create_incident_payload(**overrides) -> dict:
    payload = {"severity": "CRITICAL", "occurred_at": "2026-05-30T00:00:00Z", "narrative": "incident"}
    payload.update(overrides)
    return payload


def create_national_board_report_payload(**overrides) -> dict:
    payload = {"report_number": "NB-6", "findings_summary": "summary"}
    payload.update(overrides)
    return payload
