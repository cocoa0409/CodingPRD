"""IncomeRecord and AssetRecord routes (PRD §3.1)."""

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, gen_id, lock
from core.validation import require_body, require_field, require_enum
from services.mutations import stamp_create, bump
from services.projections import project_income_record, project_asset_record


bp = Blueprint("income_assets", __name__)


_INCOME_SOURCE_TYPES = {
    "WAGES", "SELF_EMPLOYMENT", "INTEREST", "DIVIDENDS",
    "CAPITAL_GAINS", "SOCIAL_SECURITY", "UNEMPLOYMENT",
    "CHILD_SUPPORT", "TANF", "SSI", "OTHER",
}
_INCOME_FREQUENCIES = {"ANNUAL", "MONTHLY", "BIWEEKLY", "WEEKLY"}
_ASSET_TYPES = {
    "PRIMARY_RESIDENCE", "VEHICLE", "CHECKING", "SAVINGS",
    "RETIREMENT", "INVESTMENT", "LIFE_INSURANCE", "OTHER",
}


def _resolve_household_applicant(household_id, applicant_id):
    household = STORE.households.get(household_id)
    if household is None:
        raise_error("ERR_NOT_FOUND", "Household not found")
    applicant = STORE.applicants.get(applicant_id)
    if applicant is None or applicant["household_id"] != household_id:
        raise_error("ERR_NOT_FOUND", "Applicant not found")
    return household, applicant


@bp.route("/households/<household_id>/applicants/<applicant_id>/income", methods=["POST"])
@require_roles("IntakeWorker")
def add_income(household_id, applicant_id):
    household, applicant = _resolve_household_applicant(household_id, applicant_id)
    body = require_body(request)
    source_type = require_enum(body, "source_type", _INCOME_SOURCE_TYPES)
    gross = require_field(body, "gross_amount", kind="number")
    frequency = require_enum(body, "frequency", _INCOME_FREQUENCIES)
    with lock():
        iid = gen_id()
        row = {
            "id": iid,
            "applicant_id": applicant_id,
            "source_type": source_type,
            "gross_amount": float(gross),
            "frequency": frequency,
        }
        stamp_create(row, append_only=True)
        STORE.income_records[iid] = row
        # Recompute household-derivatives: bump applicant + household
        bump(applicant)
        bump(household)
    return success_object(project_income_record(row), status=201)


@bp.route("/households/<household_id>/applicants/<applicant_id>/assets", methods=["POST"])
@require_roles("IntakeWorker")
def add_asset(household_id, applicant_id):
    household, applicant = _resolve_household_applicant(household_id, applicant_id)
    body = require_body(request)
    asset_type = require_enum(body, "asset_type", _ASSET_TYPES)
    market = require_field(body, "market_value", kind="number")
    with lock():
        aid = gen_id()
        row = {
            "id": aid,
            "applicant_id": applicant_id,
            "asset_type": asset_type,
            "market_value": float(market),
        }
        stamp_create(row, append_only=True)
        STORE.asset_records[aid] = row
        bump(applicant)
        bump(household)
    return success_object(project_asset_record(row), status=201)
