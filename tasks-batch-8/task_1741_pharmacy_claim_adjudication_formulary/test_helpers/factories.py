"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

_ndc_counter = itertools.count(1)
_ncpdp_counter = itertools.count(1)
_extref_counter = itertools.count(1)
_rx_counter = itertools.count(1)
_plan_counter = itertools.count(1)


def _next_ndc() -> str:
    return f"{55000 + next(_ndc_counter):05d}-0001"


def _next_ncpdp() -> str:
    return f"NCPDP-{next(_ncpdp_counter):05d}"


def _next_external_ref() -> str:
    return f"M-{next(_extref_counter):05d}"


def _next_rx_number() -> str:
    return f"RX-{next(_rx_counter):05d}"


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "name": f"Plan-{next(_plan_counter)}",
        "deductible_cents": 0,
        "oop_max_cents": 100000,
        "assistance_model": "ACCUMULATOR",
        "member_min_pay_cents": 0,
        "card_fill_cap_cents": 0,
        "dispensing_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_drug_payload(**overrides) -> dict:
    defaults = {
        "ndc": _next_ndc(),
        "name": "Testdrug",
        "therapeutic_class": "ANTACID",
        "unit_cost_cents": 1000,
        "max_daily_dose_units": 100,
        "is_specialty": False,
    }
    defaults.update(overrides)
    return defaults


def create_formulary_entry_payload(plan_id: str, drug_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "drug_id": drug_id,
        "tier": 1,
        "quantity_limit_per_fill": 90,
        "max_days_supply": 90,
        "copay_type": "FLAT",
        "copay_flat_cents": 100,
        "rebate_eligible": False,
    }
    defaults.update(overrides)
    return defaults


def create_pharmacy_payload(**overrides) -> dict:
    defaults = {
        "ncpdp_id": _next_ncpdp(),
        "name": "Rx Test",
        "channel": "RETAIL",
        "auto_suspend_threshold_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(plan_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "external_ref": _next_external_ref(),
        "full_name": "Pat Test",
        "eligibility_start_date": "2026-01-01",
        "eligibility_end_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_prior_authorization_payload(member_id: str, drug_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "drug_id": drug_id,
        "requested_quantity": 30,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(member_id: str, drug_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "drug_id": drug_id,
        "prescription_number": _next_rx_number(),
        "fill_date": "2026-03-01",
        "quantity": 10,
        "days_supply": 10,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(pharmacy_id: str, **overrides) -> dict:
    defaults = {
        "pharmacy_id": pharmacy_id,
        "window_start_date": "2026-01-01",
        "window_end_date": "2026-12-31",
        "extrapolation_method": "CLAIM_LEVEL",
    }
    defaults.update(overrides)
    return defaults
