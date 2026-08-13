"""Payload factories — one per entity, input fields only per PRD endpoint catalogue."""
from .constants import KILN_WINDOW, DEFAULT_TARGET_MOISTURE_PCT


def create_log_load_payload(**overrides) -> dict:
    defaults = {
        "supplier_name": "Olympic Log Co",
        "species": "DOUGLAS_FIR",
        "log_grade": "SAWLOG_1",
    }
    defaults.update(overrides)
    return defaults


def scale_payload(**overrides) -> dict:
    defaults = {
        "scaled_mbf": 100,
        "price_per_mbf_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def dispute_payload(**overrides) -> dict:
    defaults = {
        "reason": "supplier contests Scribner short",
    }
    defaults.update(overrides)
    return defaults


def package_entry_payload(**overrides) -> dict:
    """One entry of the packages[] array recorded at sawing-run completion."""
    defaults = {
        "species": "DOUGLAS_FIR",
        "dimension": "2X4",
        "length_ft": 12,
        "pieces": 100,
        "green_mbf": 20.0,
    }
    defaults.update(overrides)
    return defaults


def create_sawing_run_payload(log_load_ids, **overrides) -> dict:
    defaults = {
        "saw_line": "LINE_A",
        "scheduled_date": "2026-08-02",
        "sawing_pattern": "DIMENSION_2X4",
        "log_load_ids": list(log_load_ids),
    }
    defaults.update(overrides)
    return defaults


def complete_sawing_run_payload(packages, **overrides) -> dict:
    defaults = {
        "packages": list(packages),
        "chip_tons": 5,
        "sawdust_tons": 2,
        "bark_tons": 2,
    }
    defaults.update(overrides)
    return defaults


def create_kiln_charge_payload(package_ids, **overrides) -> dict:
    defaults = {
        "chamber": "KILN_1",
        "species": "DOUGLAS_FIR",
        "package_ids": list(package_ids),
        "scheduled_start": KILN_WINDOW["START"],
        "scheduled_end": KILN_WINDOW["END"],
        "target_moisture_pct": DEFAULT_TARGET_MOISTURE_PCT,
    }
    defaults.update(overrides)
    return defaults


def kiln_reading_payload(package_id, **overrides) -> dict:
    """One per-package reading recorded at kiln-charge completion."""
    defaults = {
        "package_id": package_id,
        "exit_moisture_pct": 14.0,
        "measured_dry_mbf": 18.8,
    }
    defaults.update(overrides)
    return defaults


def create_grade_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspector_grade": "NO_2",
        "action": "STAMP",
    }
    defaults.update(overrides)
    return defaults


def create_price_list_payload(**overrides) -> dict:
    defaults = {
        "species": "DOUGLAS_FIR",
        "grade": "NO_2",
        "base_price_per_mbf_cents": 60000,
        "effective_from": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_sales_contract_payload(**overrides) -> dict:
    defaults = {
        "customer_name": "Acme Builders",
        "species": "DOUGLAS_FIR",
        "grade": "NO_2",
        "committed_mbf": 100,
        "contract_price_per_mbf_cents": 60000,
        "start_date": "2026-08-01",
        "end_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def amend_sales_contract_payload(expected_contract_version, **overrides) -> dict:
    defaults = {
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(**overrides) -> dict:
    defaults = {
        "customer_name": "Spot Buyer",
        "species": "DOUGLAS_FIR",
        "grade": "NO_2",
        "length_spec": 12,
        "volume_mbf": 5,
    }
    defaults.update(overrides)
    return defaults


def create_byproduct_sale_payload(**overrides) -> dict:
    defaults = {
        "product": "CHIP",
        "volume_tons": 7,
        "price_per_ton_cents": 9000,
        "buyer_name": "PanelBoard Inc",
    }
    defaults.update(overrides)
    return defaults
