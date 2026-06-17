"""Payload factories — one per entity, input fields only.

Only ``source: input`` fields appear here; system/computed fields are server-set.
Optional fields with PRD-stated defaults are omitted from defaults unless a test
needs them.
"""
import itertools

from .constants import (
    TEST_SHEET_AREA_MM2,
    SPEC_W,
    SPEC_H,
    SPEC_D,
)

# Monotonic counter so factory-minted unique fields (sku, email) never collide
# within a single test. The server is restarted before every test, so a fresh
# counter per process is fine.
_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_shop_payload(**overrides) -> dict:
    defaults = {"name": "Test Mill"}
    defaults.update(overrides)
    return defaults


def create_material_payload(**overrides) -> dict:
    defaults = {
        "sku": f"SKU-{_uniq()}",
        "sheet_area_mm2": TEST_SHEET_AREA_MM2,
        "sheet_price_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(**overrides) -> dict:
    defaults = {"name": f"CNC-{_uniq()}"}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": f"cust{_uniq()}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    defaults = {"title": "Test Project"}
    defaults.update(overrides)
    return defaults


def create_spec_payload(material_id, **overrides) -> dict:
    defaults = {
        "label": "Base",
        "width_mm": SPEC_W,
        "height_mm": SPEC_H,
        "depth_mm": SPEC_D,
        "quantity": 4,
        "base_unit_price_cents": 100000,
        "material_id": material_id,
    }
    defaults.update(overrides)
    return defaults


def create_finish_selection_payload(finish_code="STAIN", **overrides) -> dict:
    defaults = {"finish_code": finish_code}
    defaults.update(overrides)
    return defaults


def create_reservation_payload(material_id, sheets, **overrides) -> dict:
    defaults = {"material_id": material_id, "sheets": sheets}
    defaults.update(overrides)
    return defaults


def create_build_job_payload(machine_id, start_utc, end_utc, **overrides) -> dict:
    defaults = {
        "machine_id": machine_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(spec_price_delta_cents, **overrides) -> dict:
    defaults = {
        "description": "Change",
        "spec_price_delta_cents": spec_price_delta_cents,
    }
    defaults.update(overrides)
    return defaults


def create_draw_payload(draw_type, **overrides) -> dict:
    defaults = {"draw_type": draw_type}
    defaults.update(overrides)
    return defaults


def create_installation_payload(install_date, window_start_utc, window_end_utc, **overrides) -> dict:
    defaults = {
        "install_date": install_date,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    defaults.update(overrides)
    return defaults


def create_punch_item_payload(description="Defect", **overrides) -> dict:
    defaults = {"description": description}
    defaults.update(overrides)
    return defaults
