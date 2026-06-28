"""Payload factories — one per entity, input fields only.

Each factory provides PRD-valid defaults and accepts **overrides.
Only fields the client supplies (source: input) appear here; server-computed
and system fields are never sent.
"""

# ---- catalog / config ----

def create_state_tint_regulation_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "front_side_min_vlt_pct": 35,
        "windshield_strip_max_inches": 5,
        "medical_exemption_allowed": True,
    }
    defaults.update(overrides)
    return defaults


def create_shop_location_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Shop",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_film_material_payload(**overrides) -> dict:
    defaults = {
        "sku": "CER-TINT",
        "category": "TINT_FILM",
        "cure_hours": 24,
        "price_multiplier_bps": 14500,
    }
    defaults.update(overrides)
    return defaults


def create_service_package_payload(**overrides) -> dict:
    defaults = {
        "name": "Tint Full Sedan",
        "service_type": "TINT",
        "base_rate_cents": 28000,
        "duration_minutes": 120,
        "cure_buffer_minutes": 0,
        "warranty_days": 365,
        "requires_proof": False,
    }
    defaults.update(overrides)
    return defaults


# ---- vehicle / fleet ----

def create_vehicle_profile_payload(**overrides) -> dict:
    defaults = {
        "customer_user_id": "cust-1",
        "vin": "VIN-TEST-1",
        "size_class": "SEDAN",
    }
    defaults.update(overrides)
    return defaults


def create_fleet_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": "FleetCo",
        "fleet_manager_user_id": "fm-1",
        "discount_bps": 0,
        "credit_limit_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults


# ---- medical exemption ----

def create_medical_exemption_payload(**overrides) -> dict:
    defaults = {
        "vehicle_profile_id": None,
        "certificate_ref": "CERT-1",
        "exempt_min_vlt_pct": 20,
    }
    defaults.update(overrides)
    return defaults


# ---- bays / installers ----

def create_bay_payload(**overrides) -> dict:
    defaults = {
        "shop_location_id": None,
        "label": "Bay 1",
    }
    defaults.update(overrides)
    return defaults


def create_installer_payload(**overrides) -> dict:
    defaults = {
        "shop_location_id": None,
        "installer_user_id": "inst-1",
        "full_name": "Ivy",
        "certified_service_types": ["TINT"],
    }
    defaults.update(overrides)
    return defaults


# ---- quotes ----

def create_quote_payload(**overrides) -> dict:
    defaults = {
        "vehicle_profile_id": None,
        "shop_location_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_quote_line_payload(**overrides) -> dict:
    defaults = {
        "service_package_id": None,
        "film_material_id": None,
        "coverage": "FULL",
        "window_position": "REAR_SIDE",
        "requested_vlt_pct": 50,
        "expected_quote_version": 0,
    }
    defaults.update(overrides)
    return defaults


# ---- work orders ----

def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "quote_id": None,
        "bay_id": None,
        "installer_id": None,
        "scheduled_start": "2026-06-02T09:00:00Z",
        "expected_quote_version": 0,
    }
    defaults.update(overrides)
    return defaults


# ---- proofs ----

def create_proof_payload(**overrides) -> dict:
    defaults = {
        "design_ref": "draft-v1",
    }
    defaults.update(overrides)
    return defaults


# ---- callbacks ----

def create_callback_payload(**overrides) -> dict:
    defaults = {
        "work_order_id": None,
        "reason": "BUBBLING",
    }
    defaults.update(overrides)
    return defaults
