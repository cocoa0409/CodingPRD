"""Payload factories — one per resource, input fields only.

Every factory accepts **overrides so tests control exactly the values the
scenario needs while sensible defaults cover everything else.
"""
from .constants import (
    DEFAULT_AGREEMENT,
    DEFAULT_BENCH,
    DEFAULT_SHOT_PLAN,
    DEFAULT_SITE,
    DEFAULT_TRUCK,
    DEFAULT_ZONE,
)

DEFAULT_COARSE_BANDS = [{"sieve": "1.5in", "min_pct": 90, "max_pct": 100}]
DEFAULT_FINE_BANDS = [{"sieve": "No4", "min_pct": 90, "max_pct": 100}]


def create_site_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_SITE)
    defaults.update(overrides)
    return defaults


def create_bench_payload(site_id, **overrides) -> dict:
    defaults = dict(DEFAULT_BENCH)
    defaults["site_id"] = site_id
    defaults.update(overrides)
    return defaults


def create_shot_plan_payload(bench_id, **overrides) -> dict:
    defaults = dict(DEFAULT_SHOT_PLAN)
    defaults["bench_id"] = bench_id
    defaults.update(overrides)
    return defaults


def create_product_spec_payload(**overrides) -> dict:
    defaults = {
        "spec_code": "A57",
        "category": "COARSE",
        "gradation_bands": [dict(b) for b in DEFAULT_COARSE_BANDS],
        "base_price_per_ton": 12.50,
    }
    defaults.update(overrides)
    return defaults


def create_stockpile_payload(site_id, product_spec_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "product_spec_id": product_spec_id,
        "capacity_tons": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_gradation_test_payload(stockpile_id, **overrides) -> dict:
    defaults = {
        "stockpile_id": stockpile_id,
        "sampled_at": "2026-08-01T06:00:00Z",
        "sieve_results": [{"sieve": "1.5in", "pct_passing": 95}],
    }
    defaults.update(overrides)
    return defaults


def create_scale_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "scale_code": "TRUCK-01",
        "scale_type": "TRUCK",
    }
    defaults.update(overrides)
    return defaults


def create_scale_calibration_payload(scale_id, **overrides) -> dict:
    defaults = {
        "scale_id": scale_id,
        "calibrated_on": "2026-02-02",
        "as_found_error_pct": 0.10,
        "as_left_error_pct": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_plant_run_payload(site_id, muckpile_id, belt_scale_id,
                             **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "muckpile_id": muckpile_id,
        "belt_scale_id": belt_scale_id,
        "circuit_line": "PRIMARY",
    }
    defaults.update(overrides)
    return defaults


def create_freight_zone_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_ZONE)
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(site_id, product_spec_id, freight_zone_id,
                               **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "product_spec_id": product_spec_id,
        "freight_zone_id": freight_zone_id,
        "customer_name": "ACME",
        "quantity_tons": 100,
    }
    defaults.update(overrides)
    return defaults


def create_scale_ticket_payload(queue_entry_id, sales_order_id, scale_id,
                                **overrides) -> dict:
    defaults = {
        "queue_entry_id": queue_entry_id,
        "sales_order_id": sales_order_id,
        "scale_id": scale_id,
        "gross_lbs": 80000,
    }
    defaults.update(overrides)
    return defaults


def create_royalty_agreement_payload(site_id, **overrides) -> dict:
    defaults = dict(DEFAULT_AGREEMENT)
    defaults["site_id"] = site_id
    defaults.update(overrides)
    return defaults


def create_royalty_statement_payload(site_id, period_start, period_end,
                                     **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_msha_inspection_payload(site_id, **overrides) -> dict:
    defaults = {"site_id": site_id, "inspection_type": "REGULAR"}
    defaults.update(overrides)
    return defaults


def create_msha_citation_payload(msha_inspection_id, **overrides) -> dict:
    defaults = {
        "msha_inspection_id": msha_inspection_id,
        "citation_code": "56.14100",
        "s_and_s": True,
        "abatement_due_on": "2026-07-15",
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(**overrides) -> dict:
    defaults = {
        "miner_name": "Blaster One",
        "miner_user_id": "bf-1",
        "course_type": "TASK_TRAINING",
        "completed_on": "2026-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_reclamation_bond_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "surety_name": "SuretyCo",
        "amount_usd": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_queue_entry_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "truck_id": "TRK-1",
        "priority_class": "CONTRACT",
        "certified_tare_lbs": DEFAULT_TRUCK["certified_tare_lbs"],
        "max_payload_lbs": DEFAULT_TRUCK["max_payload_lbs"],
    }
    defaults.update(overrides)
    return defaults


def stockpile_adjustment_payload(delta_tons, expected_stockpile_version,
                                 reason="opening survey") -> dict:
    return {
        "delta_tons": delta_tons,
        "reason": reason,
        "expected_stockpile_version": expected_stockpile_version,
    }


def run_completion_payload(input_tons, outputs) -> dict:
    return {"input_tons": input_tons, "outputs": outputs}


def run_output(stockpile_id, product_spec_id, tons) -> dict:
    return {
        "stockpile_id": stockpile_id,
        "product_spec_id": product_spec_id,
        "tons": tons,
    }


def bond_release_payload(release_amount_usd,
                         expected_reclamation_bond_version) -> dict:
    return {
        "release_amount_usd": release_amount_usd,
        "expected_reclamation_bond_version": expected_reclamation_bond_version,
    }
