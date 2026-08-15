"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Customer",
    "CREDIT_LIMIT_CENTS": 100000000,
    "JOB_MODE": "SHOP",
    "JOB_INCOTERM": "FOB",
    "ITEM_LENGTH_CM": 50,
    "ITEM_WIDTH_CM": 50,
    "ITEM_HEIGHT_CM": 50,
    "ITEM_WEIGHT_KG": 50,
    "ITEM_FRAGILE_CLASS": "STANDARD",
    "ITEM_DECLARED_VALUE_CENTS": 30000,
    "HT_CERTIFICATE_NO": "HT-2026-9000",
    "TREATMENT_TYPE": "HT",
    "BATCH_EXPIRES_AT": "2027-12-31T00:00:00Z",
    "RECEIVED_BOARD_FEET": 5000,
    "STAMPS_ACQUIRED": 4,
    "UN_NUMBER": "UN1263",
    "DG_CLASS": "3",
    "PACKING_GROUP": "II",
    "CREW_NAME": "Crew A",
    "CREW_CAPABILITIES": ["SHOP_BUILD"],
    "CONTAINER_NO": "TCLU1000001",
    "CONTAINER_SIZE": "40FT",
    "CLAIM_TYPE": "IMPACT",
    "CLAIM_AMOUNT_CENTS": 50000,
    "WINDOW_START": "2026-08-10T09:00:00Z",
    "WINDOW_END": "2026-08-10T12:00:00Z",
}

_site_counter = {"n": 0}
_cert_counter = {"n": 0}
_container_counter = {"n": 0}


def _next_site_code() -> str:
    _site_counter["n"] += 1
    return f"SITE-{_site_counter['n']:04d}"


def _next_cert_no() -> str:
    _cert_counter["n"] += 1
    return f"HT-2026-{_cert_counter['n']:04d}"


def _next_container_no() -> str:
    _container_counter["n"] += 1
    return f"TCLU{_container_counter['n']:07d}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "site_code": _next_site_code(),
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_packing_job_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "mode": DEFAULTS["JOB_MODE"],
        "incoterm": DEFAULTS["JOB_INCOTERM"],
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(**overrides) -> dict:
    defaults = {
        "description": "Test item",
        "length_cm": DEFAULTS["ITEM_LENGTH_CM"],
        "width_cm": DEFAULTS["ITEM_WIDTH_CM"],
        "height_cm": DEFAULTS["ITEM_HEIGHT_CM"],
        "weight_kg": DEFAULTS["ITEM_WEIGHT_KG"],
        "fragile_class": DEFAULTS["ITEM_FRAGILE_CLASS"],
        "declared_value_cents": DEFAULTS["ITEM_DECLARED_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_design_payload(expected_item_version: int, **overrides) -> dict:
    defaults = {"expected_item_version": expected_item_version}
    defaults.update(overrides)
    return defaults


def approve_design_payload(wood_batch_id: str, **overrides) -> dict:
    defaults = {"wood_batch_id": wood_batch_id}
    defaults.update(overrides)
    return defaults


def create_wood_batch_payload(**overrides) -> dict:
    defaults = {
        "ht_certificate_no": _next_cert_no(),
        "treatment_type": DEFAULTS["TREATMENT_TYPE"],
        "expires_at": DEFAULTS["BATCH_EXPIRES_AT"],
        "received_board_feet": DEFAULTS["RECEIVED_BOARD_FEET"],
        "stamps_acquired": DEFAULTS["STAMPS_ACQUIRED"],
    }
    defaults.update(overrides)
    return defaults


def create_crate_payload(design_id: str, **overrides) -> dict:
    defaults = {"design_id": design_id}
    defaults.update(overrides)
    return defaults


def pack_crate_payload(indicator_g: int = 75, moisture_barrier: str = "NONE", **overrides) -> dict:
    defaults = {"indicator_g": indicator_g, "moisture_barrier": moisture_barrier}
    defaults.update(overrides)
    return defaults


def create_hazmat_declaration_payload(**overrides) -> dict:
    defaults = {
        "un_number": DEFAULTS["UN_NUMBER"],
        "dg_class": DEFAULTS["DG_CLASS"],
        "packing_group": DEFAULTS["PACKING_GROUP"],
    }
    defaults.update(overrides)
    return defaults


def packing_list_line(crate_id: str, description: str, qty: int,
                      net_weight_kg: float, gross_weight_kg: float) -> dict:
    return {
        "crate_id": crate_id,
        "description": description,
        "qty": qty,
        "net_weight_kg": net_weight_kg,
        "gross_weight_kg": gross_weight_kg,
    }


def create_packing_list_payload(lines: list, **overrides) -> dict:
    defaults = {"lines": lines}
    defaults.update(overrides)
    return defaults


def invoice_line(crate_id: str, description: str, qty: int,
                 unit_price_cents: int, duty_rate_bp: int = 0) -> dict:
    return {
        "crate_id": crate_id,
        "description": description,
        "qty": qty,
        "unit_price_cents": unit_price_cents,
        "duty_rate_bp": duty_rate_bp,
    }


def create_commercial_invoice_payload(lines: list, **overrides) -> dict:
    defaults = {"lines": lines}
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CREW_NAME"],
        "capabilities": list(DEFAULTS["CREW_CAPABILITIES"]),
    }
    defaults.update(overrides)
    return defaults


def create_labor_booking_payload(crew_id: str, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "mode": DEFAULTS["JOB_MODE"],
        "start_at": DEFAULTS["WINDOW_START"],
        "end_at": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_onsite_permit_payload(**overrides) -> dict:
    defaults = {
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_container_payload(**overrides) -> dict:
    defaults = {
        "container_no": _next_container_no(),
        "size": DEFAULTS["CONTAINER_SIZE"],
        "dunnage_weight_kg": 0,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(crate_id: str, **overrides) -> dict:
    defaults = {
        "crate_id": crate_id,
        "claim_type": DEFAULTS["CLAIM_TYPE"],
        "description": "Damage reported on arrival",
        "amount_claimed_cents": DEFAULTS["CLAIM_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults
