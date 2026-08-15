"""Payload factories — one per entity, input fields only.

All factories accept **overrides; only the fields the PRD lists as request inputs
for the corresponding endpoint are included in the defaults.
"""

SITE_COUNTER = {"n": 0}


def _unique(prefix: str) -> str:
    SITE_COUNTER["n"] += 1
    return f"{prefix}-{SITE_COUNTER['n']}"


def create_vault_site_payload(**overrides) -> dict:
    defaults = {
        "name": _unique("Site"),
        "site_type": "BRANCH",
        "vault_limit_cents": 100000000,
        "insurance_coverage_cents": 100000000,
        "dock_capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_staff_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": _unique("Staff"),
        "home_site_id": None,  # caller must supply
    }
    defaults.update(overrides)
    return defaults


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "name": _unique("Carrier"),
        "liability_cap_per_truck_cents": 50000000,
    }
    defaults.update(overrides)
    return defaults


def create_atm_machine_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,  # caller must supply
        "terminal_code": _unique("ATM"),
        "cash_capacity_cents": 10000000,
        "opening_balance_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults


def create_seasonal_window_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,  # caller must supply
        "name": _unique("Window"),
        "start_date": "2026-12-20",
        "end_date": "2026-12-26",
        "multiplier_bps": 12500,
    }
    defaults.update(overrides)
    return defaults


def create_fed_order_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,  # caller must supply
        "direction": "ORDER",
        "business_date": "2026-08-03",
    }
    defaults.update(overrides)
    return defaults


def create_denomination_line_payload(**overrides) -> dict:
    defaults = {
        "denomination_cents": 2000,
        "strap_count": 10,
        "expected_fed_order_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_cash_shipment_payload(**overrides) -> dict:
    defaults = {
        "carrier_id": None,  # caller must supply
        "scheduled_departure_at": "2026-08-10T10:00:00Z",
        "scheduled_arrival_at": "2026-08-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_fitness_batch_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,  # caller must supply
        "input_unfit_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_sort_results_payload(**overrides) -> dict:
    defaults = {
        "fit_recovered_cents": 300000,
        "unfit_remaining_cents": 200000,
        "counterfeit_face_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_counterfeit_case_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,  # caller must supply
        "denomination_cents": 2000,
        "note_count": 25,
    }
    defaults.update(overrides)
    return defaults


def create_cash_ledger_entry_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,  # caller must supply
        "business_date": "2026-08-01",
        "signed_amount_cents": 1000,
        "bucket": "FIT",
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,  # caller must supply
        "business_date": "2026-08-02",
        "opening_balance_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults


def create_atm_forecast_payload(**overrides) -> dict:
    defaults = {
        "atm_id": None,  # caller must supply
        "forecast_date": "2026-08-10",
        "w1_cents": 1000000,
        "w2_cents": 2000000,
        "w3_cents": 3000000,
    }
    defaults.update(overrides)
    return defaults
