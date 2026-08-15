"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from typing import List, Optional

from .constants import (
    BASE_ATTAINMENT_TIERS,
    BASE_FAMILY_RATES,
    CLOCK_DEFAULT,
    TEST_DEFAULTS,
)


def create_principal_payload(**overrides) -> dict:
    defaults = {
        "name": "P1",
        "annual_quota_cents": TEST_DEFAULTS["QUOTA_CENTS"],
        "notice_period_days": TEST_DEFAULTS["NOTICE_PERIOD_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "territory_codes": ["CA", "OR", "WA", "TX"],
        "effective_start": TEST_DEFAULTS["EFFECTIVE_START"],
        "specify_share_bp": TEST_DEFAULTS["SPECIFY_SHARE_BP"],
        "registered_protection_share_bp": TEST_DEFAULTS["REGISTERED_PROTECTION_SHARE_BP"],
        "tail_period_days": TEST_DEFAULTS["TAIL_PERIOD_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(expected_principal_version: int, **overrides) -> dict:
    defaults = {
        "family_rates": [dict(row) for row in BASE_FAMILY_RATES],
        "attainment_tiers": [dict(row) for row in BASE_ATTAINMENT_TIERS],
        "registration_bonus_bp": TEST_DEFAULTS["REGISTRATION_BONUS_BP"],
        "expected_principal_version": expected_principal_version,
    }
    defaults.update(overrides)
    return defaults


def create_rep_payload(**overrides) -> dict:
    defaults = {"display_name": "R1", "territory_codes": ["CA", "OR"]}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {"name": "C1", "spec_territory_code": "CA", "ship_to_territory_code": "WA"}
    defaults.update(overrides)
    return defaults


def create_registration_payload(**overrides) -> dict:
    defaults = {
        "principal_id": None,
        "customer_id": None,
        "family_code": "CONNECTORS",
        "project_name": "Project Falcon",
    }
    defaults.update(overrides)
    return defaults


def make_order_line(line_id: str = "L1", family_code: str = "CONNECTORS",
                    quantity: int = 100, unit_price_cents: int = 5000,
                    **overrides) -> dict:
    line = {
        "line_id": line_id,
        "family_code": family_code,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
    }
    line.update(overrides)
    return line


def create_order_payload(customer_id: str, principal_id: str,
                         external_order_ref: str = "PO-1",
                         placed_at: str = CLOCK_DEFAULT,
                         lines: Optional[List[dict]] = None,
                         **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "principal_id": principal_id,
        "external_order_ref": external_order_ref,
        "placed_at": placed_at,
        "lines": lines if lines is not None else [make_order_line()],
    }
    payload.update(overrides)
    return payload


def create_rma_payload(order_id: str, lines: List[dict]) -> dict:
    return {"order_id": order_id, "lines": lines}


def create_statement_payload(principal_id: str, period_label: str,
                             lines: List[dict]) -> dict:
    return {"principal_id": principal_id, "period_label": period_label, "lines": lines}


def make_statement_line(line_id: str, external_order_ref: str, amount_cents: int) -> dict:
    return {"line_id": line_id, "external_order_ref": external_order_ref,
            "amount_cents": amount_cents}


def create_sample_unit_payload(principal_id: str, **overrides) -> dict:
    defaults = {
        "principal_id": principal_id,
        "serial_number": "S-1",
        "family_code": "CONNECTORS",
        "value_cents": 80_000,
    }
    defaults.update(overrides)
    return defaults


def create_sample_checkout_payload(sample_unit_id: str) -> dict:
    return {"sample_unit_id": sample_unit_id}


def create_adjustment_payload(amount_cents: int, note: str = "manual adjustment",
                              principal_id: Optional[str] = None) -> dict:
    payload = {"amount_cents": amount_cents, "note": note}
    if principal_id is not None:
        payload["principal_id"] = principal_id
    return payload


def put_splits_payload(splits: List[dict], expected_order_version: int) -> dict:
    return {"splits": splits, "expected_order_version": expected_order_version}
