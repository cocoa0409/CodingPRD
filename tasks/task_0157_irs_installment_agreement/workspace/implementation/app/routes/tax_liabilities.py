"""Tax liability endpoints (§3.1)."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, request

from app.auth import enforce_taxpayer_ownership, require_roles
from app.envelope import success, success_list
from app.errors import (
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)
from app.services.common import init_common_fields
from app.services.csed import init_csed_for_new_liability, recompute_csed_for_read
from app.services.liabilities import recompute_balance
from app.services.taxpayers import refresh_taxpayer_aggregates
from app.store import STORE, new_id
from app.timeutil import CLOCK, parse_iso
from app.util import (
    get_json_body,
    get_pagination,
    paginate,
    require_fields,
    require_int,
    require_str,
)


bp = Blueprint("tax_liabilities", __name__, url_prefix="/collections/tax-liabilities")


LIABILITY_STATUSES = ("OPEN", "IN_AGREEMENT", "IN_COMPROMISE", "CNC", "EXPIRED", "PAID")


def _serialize(l: dict) -> dict:
    # PRD §3.3: while at least one tolling event remains open, the
    # effective expiration drifts forward as wall-clock time advances.
    # We compute a drift-adjusted view on read without mutating storage.
    csed_effective_view = recompute_csed_for_read(l["id"]) or l["csed_effective_date"]
    return {
        "id": l["id"],
        "taxpayer_id": l["taxpayer_id"],
        "tax_year": l["tax_year"],
        "assessment_date": l["assessment_date"],
        "original_assessed_amount_cents": l["original_assessed_amount_cents"],
        "accrued_interest_cents": l["accrued_interest_cents"],
        "accrued_penalty_cents": l["accrued_penalty_cents"],
        "payments_applied_cents": l["payments_applied_cents"],
        "current_balance_cents": l["current_balance_cents"],
        "csed_base_date": l["csed_base_date"],
        "csed_effective_date": csed_effective_view,
        "status": l["status"],
        "last_accrual_cycle_date": l.get("last_accrual_cycle_date"),
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


@bp.route("", methods=["POST"])
@require_roles("IRSOfficer")
def create_liability(identity):
    body = get_json_body()
    require_fields(body, ["taxpayer_id", "tax_year", "assessment_date", "original_assessed_amount_cents"])
    taxpayer_id = require_str(body, "taxpayer_id")

    current_year = CLOCK.now().year
    tax_year = require_int(body, "tax_year", minimum=1900, maximum=current_year - 1)

    assessment_date = require_str(body, "assessment_date")
    try:
        parse_iso(assessment_date)
    except ValueError:
        raise_error(ERR_VALIDATION, "assessment_date must be ISO 8601 UTC.")

    original = require_int(body, "original_assessed_amount_cents", minimum=1)

    with STORE.lock:
        tp = STORE.taxpayers.get(taxpayer_id)
        if tp is None:
            raise_error(ERR_NOT_FOUND, f"Taxpayer {taxpayer_id!r} not found.")

        liab = {
            "id": new_id(),
            "taxpayer_id": taxpayer_id,
            "tax_year": tax_year,
            "assessment_date": assessment_date,
            "original_assessed_amount_cents": original,
            "accrued_interest_cents": 0,
            "accrued_penalty_cents": 0,
            "payments_applied_cents": 0,
            "status": "OPEN",
            "last_accrual_cycle_date": None,
        }
        init_csed_for_new_liability(liab)
        recompute_balance(liab)
        init_common_fields(liab)
        STORE.tax_liabilities[liab["id"]] = liab

        refresh_taxpayer_aggregates(taxpayer_id)

    return success(_serialize(liab), status=201)


@bp.route("/<liab_id>", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer", "Taxpayer")
def get_liability(identity, liab_id):
    with STORE.lock:
        liab = STORE.tax_liabilities.get(liab_id)
        if liab is None:
            raise_error(ERR_NOT_FOUND, f"TaxLiability {liab_id!r} not found.")
        enforce_taxpayer_ownership(identity, liab["taxpayer_id"])
        return success(_serialize(liab))


@bp.route("", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer")
def list_liabilities(identity):
    limit, offset = get_pagination()
    taxpayer_filter = request.args.get("taxpayer_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in LIABILITY_STATUSES:
        raise_error(ERR_VALIDATION, "Invalid status filter.")

    with STORE.lock:
        items = list(STORE.tax_liabilities.values())
        if taxpayer_filter:
            items = [l for l in items if l["taxpayer_id"] == taxpayer_filter]
        if status_filter:
            items = [l for l in items if l["status"] == status_filter]
        items.sort(key=lambda l: l["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([_serialize(l) for l in page], limit, offset, total)
