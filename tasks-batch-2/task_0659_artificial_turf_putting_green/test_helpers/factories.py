"""Payload factories — one per entity, input (client-supplied) fields only.

The owning project_id and other path-bound identifiers are supplied as path
segments by the ApiClient methods (the PRD routes children under their project),
so they are NOT part of these body payloads except where the PRD lists them as
body input (design/scope/quote FK references, crew_id, warranty_plan_id, kind,
amount, etc.).
"""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Customer",
    "SITE_ADDRESS": "1 Lawn Way",
    "TURF_NAME": "Test Turf",
    "INFILL_NAME": "Test Infill",
    "CREW_NAME": "Test Crew",
}

# Counter to keep email/sku unique within a single test if a factory is called
# more than once. Each test runs against a fresh DB, so module-level state only
# needs to disambiguate within one test process invocation.
_seq = {"n": 0}


def _next() -> int:
    _seq["n"] += 1
    return _seq["n"]


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "email": f"customer{_next()}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_turf_product_payload(**overrides) -> dict:
    defaults = {
        "sku": f"TURF-{_next()}",
        "name": DEFAULTS["TURF_NAME"],
        "pile_height_mm": 35,
        "price_per_sqft_cents": 500,
        "roll_width_ft": 15,
    }
    defaults.update(overrides)
    return defaults


def create_infill_product_payload(**overrides) -> dict:
    defaults = {
        "sku": f"INFILL-{_next()}",
        "name": DEFAULTS["INFILL_NAME"],
        "material": "SILICA",
        "price_per_sqft_cents": 100,
        "coverage_lbs_per_sqft": 2,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CREW_NAME"],
        "daily_capacity_sqft": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "site_address": DEFAULTS["SITE_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_site_measure_payload(**overrides) -> dict:
    defaults = {
        "gross_area_sqft": 600,
        "longest_run_ft": 20,
        "slope_pct": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_design_layout_payload(
    site_measure_id: str, turf_product_id: str, infill_product_id: str, variant: str, **overrides
) -> dict:
    defaults = {
        "site_measure_id": site_measure_id,
        "turf_product_id": turf_product_id,
        "infill_product_id": infill_product_id,
        "variant": variant,
    }
    defaults.update(overrides)
    return defaults


def create_base_prep_scope_payload(design_layout_id: str, base_depth_in: float = 3, **overrides) -> dict:
    defaults = {
        "design_layout_id": design_layout_id,
        "base_depth_in": base_depth_in,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(design_layout_id: str, base_prep_scope_id: str, **overrides) -> dict:
    defaults = {
        "design_layout_id": design_layout_id,
        "base_prep_scope_id": base_prep_scope_id,
    }
    defaults.update(overrides)
    return defaults


def accept_quote_payload(expected_project_version: int, **overrides) -> dict:
    defaults = {"expected_project_version": expected_project_version}
    defaults.update(overrides)
    return defaults


def create_payment_payload(kind: str, amount_cents: int, **overrides) -> dict:
    defaults = {"kind": kind, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def settle_payment_payload(payment_id: str) -> dict:
    return {"payment_id": payment_id}


def fail_payment_payload(payment_id: str) -> dict:
    return {"payment_id": payment_id}


def create_install_job_payload(
    crew_id: str, scheduled_start: str, scheduled_end: str, **overrides
) -> dict:
    defaults = {
        "crew_id": crew_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_plan_payload(tier: str, **overrides) -> dict:
    defaults = {"tier": tier}
    defaults.update(overrides)
    return defaults


def create_callback_payload(reason: str, warranty_plan_id: str = None, **overrides) -> dict:
    defaults = {"reason": reason}
    if warranty_plan_id is not None:
        defaults["warranty_plan_id"] = warranty_plan_id
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
