"""Taxpayer endpoints (§3.1)."""
from __future__ import annotations

from flask import Blueprint, request

from app.auth import enforce_taxpayer_ownership, require_roles
from app.envelope import success, success_list
from app.errors import (
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)
from app.services.common import bump_version, check_version, init_common_fields
from app.services.taxpayers import refresh_taxpayer_aggregates
from app.store import STORE, new_id
from app.util import (
    get_json_body,
    get_pagination,
    optional_version,
    paginate,
    require_enum,
    require_fields,
    require_int,
    require_str,
)


bp = Blueprint("taxpayers", __name__, url_prefix="/collections/taxpayers")


FILING_STATUSES = ("SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD")
COLLECTION_STATUSES = ("ACTIVE", "IN_AGREEMENT", "IN_OIC_REVIEW", "IN_COMPROMISE", "CNC", "PAID_IN_FULL")


def _serialize(tp: dict) -> dict:
    return {
        "id": tp["id"],
        "tin": tp["tin"],
        "filing_status": tp["filing_status"],
        "monthly_disposable_income_cents": tp["monthly_disposable_income_cents"],
        "total_assessed_debt_cents": tp["total_assessed_debt_cents"],
        "collection_status": tp["collection_status"],
        "created_at": tp["created_at"],
        "updated_at": tp["updated_at"],
        "version": tp["version"],
    }


@bp.route("", methods=["POST"])
@require_roles("IRSOfficer")
def create_taxpayer(identity):
    body = get_json_body()
    require_fields(body, ["tin", "filing_status", "monthly_disposable_income_cents"])
    tin = require_str(body, "tin")
    if not (tin.isdigit() and len(tin) == 9):
        raise_error(ERR_VALIDATION, "tin must be exactly 9 digits.")
    filing = require_enum(body, "filing_status", FILING_STATUSES)
    mdi = require_int(body, "monthly_disposable_income_cents", minimum=0)

    with STORE.lock:
        for existing in STORE.taxpayers.values():
            if existing["tin"] == tin:
                raise_error(ERR_VALIDATION, "tin already exists.")
        tp = {
            "id": new_id(),
            "tin": tin,
            "filing_status": filing,
            "monthly_disposable_income_cents": mdi,
            "total_assessed_debt_cents": 0,
            "collection_status": "ACTIVE",
        }
        init_common_fields(tp)
        STORE.taxpayers[tp["id"]] = tp

    return success(_serialize(tp), status=201)


@bp.route("/<tp_id>", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer", "Taxpayer")
def get_taxpayer(identity, tp_id):
    with STORE.lock:
        tp = STORE.taxpayers.get(tp_id)
        if tp is None:
            raise_error(ERR_NOT_FOUND, f"Taxpayer {tp_id!r} not found.")
        enforce_taxpayer_ownership(identity, tp["id"])
        refresh_taxpayer_aggregates(tp_id)
        return success(_serialize(tp))


@bp.route("/<tp_id>", methods=["PATCH"])
@require_roles("IRSOfficer")
def patch_taxpayer(identity, tp_id):
    body = get_json_body()
    with STORE.lock:
        tp = STORE.taxpayers.get(tp_id)
        if tp is None:
            raise_error(ERR_NOT_FOUND, f"Taxpayer {tp_id!r} not found.")
        check_version(tp, optional_version(body))

        changed = False
        if "filing_status" in body and body["filing_status"] is not None:
            new_filing = require_enum(body, "filing_status", FILING_STATUSES)
            if new_filing != tp["filing_status"]:
                tp["filing_status"] = new_filing
                changed = True
        if "monthly_disposable_income_cents" in body and body["monthly_disposable_income_cents"] is not None:
            new_mdi = require_int(body, "monthly_disposable_income_cents", minimum=0)
            if new_mdi != tp["monthly_disposable_income_cents"]:
                tp["monthly_disposable_income_cents"] = new_mdi
                changed = True

        if changed:
            bump_version(tp)
        refresh_taxpayer_aggregates(tp_id)
        return success(_serialize(tp))


@bp.route("", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer")
def list_taxpayers(identity):
    limit, offset = get_pagination()
    status_filter = request.args.get("collection_status")
    if status_filter is not None and status_filter not in COLLECTION_STATUSES:
        raise_error(ERR_VALIDATION, "Invalid collection_status filter.")

    with STORE.lock:
        for tp_id in STORE.taxpayers:
            refresh_taxpayer_aggregates(tp_id)
        items = list(STORE.taxpayers.values())
        if status_filter:
            items = [t for t in items if t["collection_status"] == status_filter]
        items.sort(key=lambda t: t["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([_serialize(t) for t in page], limit, offset, total)
