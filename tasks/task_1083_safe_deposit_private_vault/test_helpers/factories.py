"""Payload factories — one per entity, input fields only."""

import itertools

_email_counter = itertools.count(1)
_code_counter = itertools.count(1)


def unique_email(prefix: str = "renter") -> str:
    return f"{prefix}-{next(_email_counter)}@vault.test"


def unique_code(prefix: str = "BR") -> str:
    return f"{prefix}{next(_code_counter)}"


def create_branch_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Branch",
        "code": unique_code("BR"),
        "viewing_room_capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_box_type_payload(**overrides) -> dict:
    defaults = {
        "size_class": "MEDIUM",
        "annual_rate_cents": 24000,
        "height_mm": 100,
        "width_mm": 250,
        "depth_mm": 500,
    }
    defaults.update(overrides)
    return defaults


def create_box_payload(branch_id: str, box_type_id: str, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "box_type_id": box_type_id,
        "box_number": unique_code("BOX-"),
    }
    defaults.update(overrides)
    return defaults


def create_renter_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Renter",
        "email": unique_email(),
        "gov_id_ref": "GID-TEST",
        "date_of_birth": "1985-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(box_id: str, renter_id: str, **overrides) -> dict:
    defaults = {
        "box_id": box_id,
        "renter_id": renter_id,
        "plan_term_months": 12,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(rental_id: str, period_start: str, period_end: str, **overrides) -> dict:
    defaults = {
        "rental_id": rental_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(rental_id: str, amount_cents: int, method: str = "WIRE", **overrides) -> dict:
    defaults = {
        "rental_id": rental_id,
        "amount_cents": amount_cents,
        "method": method,
    }
    defaults.update(overrides)
    return defaults


def create_access_grant_payload(rental_id: str, grant_type: str, grantee_name: str, **overrides) -> dict:
    defaults = {
        "rental_id": rental_id,
        "grant_type": grant_type,
        "grantee_name": grantee_name,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(box_id: str, rental_id: str, scheduled_start: str, scheduled_end: str, **overrides) -> dict:
    defaults = {
        "box_id": box_id,
        "rental_id": rental_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_access_event_payload(appointment_id: str, box_id: str, rental_id: str, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "box_id": box_id,
        "rental_id": rental_id,
        "event_type": "ENTRY",
        "primary_accessor_ref": "accessor-1",
        "dual_control_officer_ref": "officer-1",
        "witness_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(rental_id: str, category: str = "OTHER", declared_value_cents: int = 10000, **overrides) -> dict:
    defaults = {
        "rental_id": rental_id,
        "description": "Test item",
        "category": category,
        "declared_value_cents": declared_value_cents,
    }
    defaults.update(overrides)
    return defaults


def create_precious_metal_payload(rental_id: str, declared_value_cents: int, weight_grams: float = 100,
                                  purity: float = 0.999, metal_type: str = "GOLD", **overrides) -> dict:
    defaults = {
        "rental_id": rental_id,
        "description": "Precious metal item",
        "category": "PRECIOUS_METAL",
        "metal_type": metal_type,
        "weight_grams": weight_grams,
        "purity": purity,
        "declared_value_cents": declared_value_cents,
    }
    defaults.update(overrides)
    return defaults


def create_drilling_order_payload(box_id: str, rental_id: str, reason: str = "DELINQUENCY", **overrides) -> dict:
    defaults = {
        "box_id": box_id,
        "rental_id": rental_id,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_case_payload(renter_id: str, case_type: str = "SANCTIONS", **overrides) -> dict:
    defaults = {
        "renter_id": renter_id,
        "case_type": case_type,
    }
    defaults.update(overrides)
    return defaults
