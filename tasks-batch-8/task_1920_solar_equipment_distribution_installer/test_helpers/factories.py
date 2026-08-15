"""Payload factories — one per creatable resource, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_product_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "sku": f"MOD-400-{n}",
        "product_kind": "MODULE",
        "manufacturer_name": "SolarCo",
        "wattage_w": TEST_DEFAULTS["MODULE_WATTAGE_W"],
        "ac_output_w": 0,
        "dc_input_max_w": 0,
        "technology_generation": 3,
        "hts_code": TEST_DEFAULTS["HTS_MODULE"],
        "list_price_cents": TEST_DEFAULTS["MODULE_LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_inverter_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "sku": f"INV-5K-{n}",
        "product_kind": "INVERTER",
        "manufacturer_name": "InvertCo",
        "wattage_w": 0,
        "ac_output_w": 5000,
        "dc_input_max_w": 8000,
        "technology_generation": 3,
        "hts_code": TEST_DEFAULTS["HTS_INVERTER"],
        "list_price_cents": TEST_DEFAULTS["INVERTER_LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_compatibility_rule_payload(module_product_id, inverter_product_id,
                                      **overrides) -> dict:
    defaults = {
        "module_product_id": module_product_id,
        "inverter_product_id": inverter_product_id,
        "max_modules_per_inverter": TEST_DEFAULTS["RULE_MAX_MODULES"],
        "min_modules_per_inverter": TEST_DEFAULTS["RULE_MIN_MODULES"],
        "effective_from": TEST_DEFAULTS["TARIFF_EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_tariff_rate_payload(**overrides) -> dict:
    defaults = {
        "hts_code": TEST_DEFAULTS["HTS_MODULE"],
        "duty_rate_bp": TEST_DEFAULTS["MODULE_DUTY_RATE_BP"],
        "effective_from": TEST_DEFAULTS["TARIFF_EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_installer_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "legal_name": f"SunInstall LLC {n}",
        "license_number": f"CA-C10-{n:05d}",
        "credit_limit_cents": TEST_DEFAULTS["INSTALLER_CREDIT_LIMIT_CENTS"],
        "progress_payment_pct_bp": TEST_DEFAULTS["INSTALLER_PROGRESS_PCT_BP"],
        "payment_terms_days": TEST_DEFAULTS["INSTALLER_PAYMENT_TERMS_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_container_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "container_number": f"MSKU{n:06d}",
        "bol_number": f"BL-{n}",
        "origin_port": "CNSHA",
        "eta_utc": TEST_DEFAULTS["CONTAINER_ETA"],
        "freight_cost_cents": 0,
        "insurance_cost_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_container_line_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "qty_booked": 5,
        "declared_unit_value_cents": TEST_DEFAULTS[
            "MODULE_DECLARED_UNIT_VALUE_CENTS"
        ],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(module_product_id, inverter_product_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "project_name": f"Residence {n}",
        "site_postal_code": "94110",
        "module_product_id": module_product_id,
        "inverter_product_id": inverter_product_id,
        "module_qty": 5,
        "inverter_qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(inventory_lot_id, qty_allocated,
                              expected_lot_version, **overrides) -> dict:
    defaults = {
        "inventory_lot_id": inventory_lot_id,
        "qty_allocated": qty_allocated,
        "expected_lot_version": expected_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_rma_claim_payload(installer_id, product_id, allocation_id,
                             qty_claimed, **overrides) -> dict:
    defaults = {
        "installer_id": installer_id,
        "product_id": product_id,
        "allocation_id": allocation_id,
        "qty_claimed": qty_claimed,
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(container_line_id, qty_damaged, **overrides) -> dict:
    defaults = {
        "container_line_id": container_line_id,
        "qty_damaged": qty_damaged,
    }
    defaults.update(overrides)
    return defaults


def post_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
