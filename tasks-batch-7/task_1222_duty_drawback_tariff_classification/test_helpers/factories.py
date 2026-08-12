"""Payload factories — input fields only (PRD 3-4)."""

DEFAULTS = {
    "CLIENT_NAME": "Acme Imports",
    "CLIENT_IOR": "12-3456789",
    "CLIENT_FEE_BPS": 2500,
    "CLIENT_B_NAME": "Beta Trade",
    "CLIENT_B_IOR": "98-7654321",
    "CLIENT_B_FEE_BPS": 2000,
    "PRODUCT_SKU": "PANT-01",
    "HTS_CODE": "6203.42.4011",
    "COUNTRY_OF_ORIGIN": "CN",
    "DUTY_RATE_BPS": 1650,
    "DECLARED_UNIT_VALUE_CENTS": 5000,
    "ENTRY_NUMBER": "E100",
    "ENTRY_DATE": "2026-03-10T00:00:00Z",
    "PORT_CODE": "2704",
    "LINE_QUANTITY": 100,
    "ENTERED_VALUE_CENTS": 500000,
    "DUTY_PAID_CENTS": 82500,
    "EXPORT_DATE": "2026-04-01T00:00:00Z",
    "EXPORT_QUANTITY": 100,
    "FOB_VALUE_CENTS": 480000,
    "DEST_COUNTRY": "MX",
    "SUBSTITUTED_DUTY_RATE_BPS": 1650,
    "CLAIM_PERIOD_START": "2026-01-01T00:00:00Z",
    "CLAIM_PERIOD_END": "2026-03-31T00:00:00Z",
    "AUDIT_DUE_DATE": "2026-06-01T00:00:00Z",
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CLIENT_NAME"],
        "importer_of_record_number": DEFAULTS["CLIENT_IOR"],
        "contingency_fee_bps": DEFAULTS["CLIENT_FEE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_client_b_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CLIENT_B_NAME"],
        "importer_of_record_number": DEFAULTS["CLIENT_B_IOR"],
        "contingency_fee_bps": DEFAULTS["CLIENT_B_FEE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_classification_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "product_sku": DEFAULTS["PRODUCT_SKU"],
        "hts_code": DEFAULTS["HTS_CODE"],
        "country_of_origin": DEFAULTS["COUNTRY_OF_ORIGIN"],
        "duty_rate_bps": DEFAULTS["DUTY_RATE_BPS"],
        "declared_unit_value_cents": DEFAULTS["DECLARED_UNIT_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_binding_ruling_payload(classification_id: str, **overrides) -> dict:
    defaults = {
        "classification_id": classification_id,
        "requested_hts_code": DEFAULTS["HTS_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_import_entry_payload(client_id: str, classification_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "classification_id": classification_id,
        "entry_number": DEFAULTS["ENTRY_NUMBER"],
        "entry_date": DEFAULTS["ENTRY_DATE"],
        "port_code": DEFAULTS["PORT_CODE"],
        "line_quantity": DEFAULTS["LINE_QUANTITY"],
        "entered_value_cents": DEFAULTS["ENTERED_VALUE_CENTS"],
        "duty_paid_cents": DEFAULTS["DUTY_PAID_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_export_shipment_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "export_date": DEFAULTS["EXPORT_DATE"],
        "hts_code": DEFAULTS["HTS_CODE"],
        "quantity": DEFAULTS["EXPORT_QUANTITY"],
        "fob_value_cents": DEFAULTS["FOB_VALUE_CENTS"],
        "dest_country": DEFAULTS["DEST_COUNTRY"],
        "substituted_duty_rate_bps": DEFAULTS["SUBSTITUTED_DUTY_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "claim_type": "DIRECT_IDENTIFICATION",
        "period_start": DEFAULTS["CLAIM_PERIOD_START"],
        "period_end": DEFAULTS["CLAIM_PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_claim_line_payload(
    import_entry_id: str, export_shipment_id: str, **overrides
) -> dict:
    defaults = {
        "import_entry_id": import_entry_id,
        "export_shipment_id": export_shipment_id,
        "matched_quantity": 40,
    }
    defaults.update(overrides)
    return defaults


def create_tariff_measure_payload(**overrides) -> dict:
    defaults = {
        "hts_code_prefix": "6203",
        "measure_type": "SECTION_301",
        "surcharge_bps": 500,
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_audit_case_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "opened_reason": "CF28",
        "due_date": DEFAULTS["AUDIT_DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults
