"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_email() -> str:
    return f"{_uniq('user')}@example.com"


def unique_sku() -> str:
    return _uniq("SKU").upper()


def unique_name(prefix: str = "Bay") -> str:
    return _uniq(prefix)


def create_customer_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Customer", "email": unique_email()}
    defaults.update(overrides)
    return defaults


def create_staff_payload(staff_role="FITTING_SPECIALIST", **overrides) -> dict:
    defaults = {"full_name": "Test Staff", "staff_role": staff_role}
    defaults.update(overrides)
    return defaults


def create_bay_payload(**overrides) -> dict:
    defaults = {"bay_name": unique_name("Bay")}
    defaults.update(overrides)
    return defaults


def create_lesson_package_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "total_credits": 5,
        "price_cents": 50_000,
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_fitting_session_payload(customer_id, bay_id, specialist_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "bay_id": bay_id,
        "specialist_id": specialist_id,
        "starts_at": "2026-05-10T10:00:00Z",
        "ends_at": "2026-05-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_component_item_payload(component_type="HEAD", **overrides) -> dict:
    defaults = {
        "sku": unique_sku(),
        "component_type": component_type,
        "unit_cost_cents": 40_000,
        "msrp_cents": 55_000,
        "initial_stock": 5,
    }
    defaults.update(overrides)
    return defaults


def create_build_spec_payload(customer_id, fitting_session_id, head_item_id,
                              shaft_item_id, grip_item_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "fitting_session_id": fitting_session_id,
        "head_item_id": head_item_id,
        "shaft_item_id": shaft_item_id,
        "grip_item_id": grip_item_id,
        "length_inches": 45.5,
        "loft_deg": 10.5,
        "lie_deg": 58,
        "labor_cents": 15_000,
    }
    defaults.update(overrides)
    return defaults


def create_repair_ticket_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "club_description": "7-iron",
        "service_type": "REGRIP",
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(customer_id, clubs=None, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "clubs": clubs if clubs is not None else [{"club_type": "DRIVER", "condition_grade": "A"}],
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(description="defect", **overrides) -> dict:
    defaults = {"description": description}
    defaults.update(overrides)
    return defaults
