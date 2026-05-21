"""Federal tax lien endpoints (§3.7)."""
from __future__ import annotations

from flask import Blueprint, request

from app.auth import enforce_taxpayer_ownership, require_roles
from app.envelope import success, success_list
from app.errors import (
    ERR_INVALID_STATE,
    ERR_LIABILITY_NOT_OWNED,
    ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)
from app.services.common import bump_version, check_version, init_common_fields
from app.store import STORE, new_id
from app.timeutil import now_iso, parse_iso
from app.util import (
    get_json_body,
    get_pagination,
    optional_version,
    paginate,
    require_fields,
    require_list,
    require_str,
)


bp = Blueprint("liens", __name__, url_prefix="/collections/liens")


LIEN_STATUSES = ("FILED", "WITHDRAWN", "RELEASED")
AGGREGATE_DDIA_THRESHOLD = 2_500_000


def _serialize(l: dict) -> dict:
    return {
        "id": l["id"],
        "taxpayer_id": l["taxpayer_id"],
        "liability_ids": list(l["liability_ids"]),
        "filed_date": l["filed_date"],
        "status": l["status"],
        "released_at": l.get("released_at"),
        "release_reason": l.get("release_reason"),
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


@bp.route("", methods=["POST"])
@require_roles("IRSOfficer")
def file_lien(identity):
    body = get_json_body()
    require_fields(body, ["taxpayer_id", "liability_ids", "filed_date"])
    taxpayer_id = require_str(body, "taxpayer_id")
    liab_ids = require_list(body, "liability_ids", min_len=1)
    if any(not isinstance(x, str) for x in liab_ids):
        raise_error(ERR_VALIDATION, "liability_ids must be an array of strings.")
    filed_date = require_str(body, "filed_date")
    try:
        parse_iso(filed_date)
    except ValueError:
        raise_error(ERR_VALIDATION, "filed_date must be ISO 8601 UTC.")

    with STORE.lock:
        tp = STORE.taxpayers.get(taxpayer_id)
        if tp is None:
            raise_error(ERR_NOT_FOUND, f"Taxpayer {taxpayer_id!r} not found.")
        for lid in liab_ids:
            l = STORE.tax_liabilities.get(lid)
            if l is None or l["taxpayer_id"] != taxpayer_id:
                raise_error(ERR_LIABILITY_NOT_OWNED, f"Liability {lid!r} not owned by taxpayer.")

        lien = {
            "id": new_id(),
            "taxpayer_id": taxpayer_id,
            "liability_ids": list(liab_ids),
            "filed_date": filed_date,
            "status": "FILED",
            "released_at": None,
            "release_reason": None,
        }
        init_common_fields(lien)
        STORE.liens[lien["id"]] = lien

    return success(_serialize(lien), status=201)


@bp.route("/<lien_id>/withdraw", methods=["POST"])
@require_roles("IRSOfficer")
def withdraw_lien(identity, lien_id):
    body = get_json_body()
    with STORE.lock:
        lien = STORE.liens.get(lien_id)
        if lien is None:
            raise_error(ERR_NOT_FOUND, f"Lien {lien_id!r} not found.")
        if lien["status"] != "FILED":
            raise_error(ERR_INVALID_STATE, f"Lien is in status {lien['status']}, cannot withdraw.")
        check_version(lien, optional_version(body))

        liab_ids = set(lien["liability_ids"])
        covered = [STORE.tax_liabilities[lid] for lid in liab_ids if lid in STORE.tax_liabilities]

        # Every liability must currently be in IN_AGREEMENT
        if not all(l["status"] == "IN_AGREEMENT" for l in covered):
            raise_error(ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE,
                        "All lien liabilities must be in IN_AGREEMENT for DDIA streamlined withdrawal.")

        # Every covered liability's covering agreement must be DDIA
        covering_agreement_ids = set()
        for l in covered:
            agreement_found = None
            for ia in STORE.installment_agreements.values():
                if l["id"] in ia["liability_ids"] and ia["status"] == "ACTIVE":
                    agreement_found = ia
                    break
            if agreement_found is None:
                raise_error(ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE,
                            f"No covering ACTIVE agreement for liability {l['id']!r}.")
            if agreement_found["payment_method"] != "DDIA":
                raise_error(ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE,
                            "Covering agreement must use DDIA.")
            covering_agreement_ids.add(agreement_found["id"])

        # Aggregate debt across the lien's liabilities <= $25,000
        aggregate = sum(l["current_balance_cents"] for l in covered)
        if aggregate > AGGREGATE_DDIA_THRESHOLD:
            raise_error(ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE,
                        f"Aggregate debt {aggregate} exceeds DDIA withdrawal cap of {AGGREGATE_DDIA_THRESHOLD}.")

        lien["status"] = "WITHDRAWN"
        lien["released_at"] = now_iso()
        lien["release_reason"] = "ADMIN_RELEASE"
        bump_version(lien)
        return success(_serialize(lien))


@bp.route("/<lien_id>", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer", "Taxpayer")
def get_lien(identity, lien_id):
    with STORE.lock:
        lien = STORE.liens.get(lien_id)
        if lien is None:
            raise_error(ERR_NOT_FOUND, f"Lien {lien_id!r} not found.")
        enforce_taxpayer_ownership(identity, lien["taxpayer_id"])
        return success(_serialize(lien))


@bp.route("", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer")
def list_liens(identity):
    limit, offset = get_pagination()
    taxpayer_filter = request.args.get("taxpayer_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in LIEN_STATUSES:
        raise_error(ERR_VALIDATION, "Invalid status filter.")

    with STORE.lock:
        items = list(STORE.liens.values())
        if taxpayer_filter:
            items = [l for l in items if l["taxpayer_id"] == taxpayer_filter]
        if status_filter:
            items = [l for l in items if l["status"] == status_filter]
        items.sort(key=lambda l: l["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([_serialize(l) for l in page], limit, offset, total)
