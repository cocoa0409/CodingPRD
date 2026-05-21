"""Applicant lifecycle and revocation."""

from __future__ import annotations

from typing import Optional

from app import calculations, clock, store
from app.errors import APIError, validation
from app.services.common import occ_check, touch
from app.util import new_id, require_bool, require_int, require_str


_VALID_INCOME_BANDS = ("EXTREMELY_LOW", "VERY_LOW", "LOW", "OVER_INCOME")

# Income limit thresholds (annual income in cents). These mimic HUD bands;
# precise thresholds are not specified in the PRD beyond banding so we use
# defensible defaults. Tests should not depend on band boundaries beyond
# (ELIGIBLE iff in {EXTREMELY_LOW, VERY_LOW, LOW}, INELIGIBLE iff OVER_INCOME).
EXTREMELY_LOW_CEILING_CENTS = 30_000 * 100  # $30,000
VERY_LOW_CEILING_CENTS = 50_000 * 100       # $50,000
LOW_CEILING_CENTS = 80_000 * 100            # $80,000


def _classify_band(adjusted_cents: int) -> str:
    if adjusted_cents <= EXTREMELY_LOW_CEILING_CENTS:
        return "EXTREMELY_LOW"
    if adjusted_cents <= VERY_LOW_CEILING_CENTS:
        return "VERY_LOW"
    if adjusted_cents <= LOW_CEILING_CENTS:
        return "LOW"
    return "OVER_INCOME"


def _eligibility_for(band: str) -> str:
    return "INELIGIBLE" if band == "OVER_INCOME" else "ELIGIBLE"


def create_applicant(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation("Body must be a JSON object")

    try:
        household_name = require_str(payload.get("household_name"), field="household_name")
        household_size = require_int(payload.get("household_size"), field="household_size", min_value=1, max_value=20)
        dependents_count = require_int(payload.get("dependents_count"), field="dependents_count", min_value=0)
        if dependents_count > household_size:
            raise ValueError("dependents_count cannot exceed household_size")
        elderly_or_disabled_head = require_bool(payload.get("elderly_or_disabled_head"), field="elderly_or_disabled_head")
        gross_cents = require_int(payload.get("gross_annual_income_cents"), field="gross_annual_income_cents", min_value=0)
        childcare_cents = require_int(payload.get("childcare_expense_annual_cents", 0), field="childcare_expense_annual_cents", min_value=0)
        medical_cents = require_int(payload.get("medical_expense_annual_cents", 0), field="medical_expense_annual_cents", min_value=0)
    except ValueError as exc:
        raise validation(str(exc))

    adjusted = calculations.calc_adjusted_income(
        gross_cents=gross_cents,
        dependents_count=dependents_count,
        elderly_or_disabled_head=elderly_or_disabled_head,
        medical_expense_cents=medical_cents,
        childcare_expense_cents=childcare_cents,
    )
    band = _classify_band(adjusted)
    eligibility = _eligibility_for(band)

    now = clock.now()
    applicant_id = new_id()
    record = {
        "id": applicant_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "household_name": household_name,
        "household_size": household_size,
        "dependents_count": dependents_count,
        "elderly_or_disabled_head": elderly_or_disabled_head,
        "gross_annual_income_cents": gross_cents,
        "childcare_expense_annual_cents": childcare_cents,
        "medical_expense_annual_cents": medical_cents,
        "adjusted_annual_income_cents": adjusted,
        "income_band": band,
        "eligibility_status": eligibility,
    }
    store.applicants[applicant_id] = record
    return record


def revoke_applicant(applicant_id: str, payload: Optional[dict]) -> dict:
    applicant = store.applicants.get(applicant_id)
    if applicant is None:
        from app.errors import not_found
        raise not_found("Applicant not found")
    payload = payload or {}
    occ_check(applicant, payload.get("version"))

    applicant["eligibility_status"] = "INELIGIBLE"
    touch(applicant)

    # Cascade: any Voucher with this applicant in status ISSUED → REVOKED.
    for voucher in list(store.vouchers.values()):
        if voucher.get("applicant_id") == applicant_id and voucher.get("status") == "ISSUED":
            voucher["status"] = "REVOKED"
            touch(voucher)

    return applicant
