"""Payload factories — one per entity, source: input fields only (PRD Section 3)."""
from typing import Optional


def create_region_payload(
    code: str = "TEST_REGION",
    name: str = "Test Region",
    fmr_year: int = 2026,
    is_special_mobility_area: Optional[bool] = None,
    **overrides,
) -> dict:
    payload = {"code": code, "name": name, "fmr_year": fmr_year}
    if is_special_mobility_area is not None:
        payload["is_special_mobility_area"] = is_special_mobility_area
    payload.update(overrides)
    return payload


def create_payment_standard_payload(
    region_id: str,
    bedroom_size: int = 2,
    amount_cents: int = 95000,
    fmr_cents: int = 100000,
    **overrides,
) -> dict:
    payload = {
        "region_id": region_id,
        "bedroom_size": bedroom_size,
        "amount_cents": amount_cents,
        "fmr_cents": fmr_cents,
    }
    payload.update(overrides)
    return payload


def create_household_payload(
    region_id: str,
    head_name: str = "Test Head",
    family_size: int = 3,
    annual_income_cents: int = 1800000,
    **overrides,
) -> dict:
    payload = {
        "head_name": head_name,
        "family_size": family_size,
        "annual_income_cents": annual_income_cents,
        "region_id": region_id,
    }
    payload.update(overrides)
    return payload


def create_voucher_payload(household_id: str, **overrides) -> dict:
    payload = {"household_id": household_id}
    payload.update(overrides)
    return payload


def create_landlord_payload(
    name: str = "Test Landlord",
    payee_account: str = "acct-test",
    **overrides,
) -> dict:
    payload = {"name": name, "payee_account": payee_account}
    payload.update(overrides)
    return payload


def create_unit_payload(
    landlord_id: str,
    region_id: str,
    bedroom_size: int = 2,
    asking_rent_cents: int = 90000,
    comparable_rent_cents: int = 90000,
    **overrides,
) -> dict:
    payload = {
        "landlord_id": landlord_id,
        "region_id": region_id,
        "bedroom_size": bedroom_size,
        "asking_rent_cents": asking_rent_cents,
        "comparable_rent_cents": comparable_rent_cents,
    }
    payload.update(overrides)
    return payload


def create_rent_reasonableness_payload(
    unit_id: str, requested_rent_cents: int = 90000, **overrides,
) -> dict:
    payload = {"unit_id": unit_id, "requested_rent_cents": requested_rent_cents}
    payload.update(overrides)
    return payload


def create_inspection_payload(
    unit_id: str,
    inspection_type: str = "INITIAL",
    scheduled_date: str = "2026-06-01T00:00:00Z",
    hap_contract_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "unit_id": unit_id,
        "inspection_type": inspection_type,
        "scheduled_date": scheduled_date,
    }
    if hap_contract_id is not None:
        payload["hap_contract_id"] = hap_contract_id
    payload.update(overrides)
    return payload


def create_hap_contract_payload(
    voucher_id: str,
    unit_id: str,
    contract_rent_cents: int,
    expected_voucher_version: int,
    **overrides,
) -> dict:
    payload = {
        "voucher_id": voucher_id,
        "unit_id": unit_id,
        "contract_rent_cents": contract_rent_cents,
        "expected_voucher_version": expected_voucher_version,
    }
    payload.update(overrides)
    return payload


def create_portability_move_payload(
    voucher_id: str, receiving_region_id: str, **overrides,
) -> dict:
    payload = {"voucher_id": voucher_id, "receiving_region_id": receiving_region_id}
    payload.update(overrides)
    return payload


def create_annual_review_payload(
    hap_contract_id: str,
    new_annual_income_cents: int,
    effective_date: str = "2026-07-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "hap_contract_id": hap_contract_id,
        "new_annual_income_cents": new_annual_income_cents,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def finalize_annual_review_payload(expected_hap_contract_version: int, **overrides) -> dict:
    payload = {"expected_hap_contract_version": expected_hap_contract_version}
    payload.update(overrides)
    return payload


def create_special_mobility_grant_payload(
    voucher_id: str,
    target_region_id: str,
    term_extension_days: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {"voucher_id": voucher_id, "target_region_id": target_region_id}
    if term_extension_days is not None:
        payload["term_extension_days"] = term_extension_days
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
