"""Bank endpoints."""

from __future__ import annotations

from flask import Blueprint

from db import banks, stamp_new
from errors import raise_err, ERR_DUPLICATE_CHARTER_ID
from middleware import require_roles
from response import success_object, success_list
from services.core import ser_bank, get_bank
from util import get_body, req_str, opt_enum, apply_filters, sorted_page

bp = Blueprint("banks", __name__)

RWA_METHODOLOGIES = {"STANDARDIZED", "ADVANCED"}


@bp.route("/banks", methods=["POST"])
@require_roles("SystemOperator")
def create_bank(_user_id: str, _role: str):
    body = get_body()
    legal_name = req_str(body, "legal_name")
    charter_id = req_str(body, "charter_id")
    methodology = opt_enum(body, "rwa_methodology", RWA_METHODOLOGIES) or "STANDARDIZED"
    if any(b["charter_id"] == charter_id for b in banks.values()):
        raise_err(ERR_DUPLICATE_CHARTER_ID, "Bank with this charter_id already exists")
    bank = {
        "legal_name": legal_name,
        "charter_id": charter_id,
        "rwa_methodology": methodology,
        "is_advanced_approaches_bank": methodology == "ADVANCED",
        "pca_bucket": "ADEQUATELY_CAPITALIZED",
        "pca_bucket_as_of_period_id": None,
        "mdba_cents": 0,
        "pending_distribution_cents": 0,
        "stressed_capital_buffer_bps": None,
        "supervisory_status": "NORMAL",
    }
    stamp_new(bank)
    banks[bank["id"]] = bank
    return success_object(ser_bank(bank), 201)


@bp.route("/banks/<bankId>", methods=["GET"])
@require_roles("Any")
def get_one_bank(bankId: str, _user_id: str, _role: str):
    return success_object(ser_bank(get_bank(bankId)))


@bp.route("/banks", methods=["GET"])
@require_roles("Any")
def list_banks(_user_id: str, _role: str):
    items = list(banks.values())
    items = apply_filters(items, {
        "charter_id": "charter_id",
        "pca_bucket_as_of_period_id": "pca_bucket_as_of_period_id",
    })
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_bank(b) for b in page], limit, offset, total)
