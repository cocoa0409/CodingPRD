"""ProbateFiling endpoints (SCAFFOLD §1.5 filings)."""
from __future__ import annotations

from flask import Blueprint, request

from config import FILING_STATUSES, FILING_TYPES
from db import store
from errors import ApiError
from middleware import current_role, require_auth
from response import list_success, success
from services.common import (
    bump,
    check_version,
    get_json_body,
    paginate,
    pop_pagination,
    require_child,
    require_estate,
    sort_by_created_at,
)
from services.serializers import serialize_filing
from utils import new_uuid


bp = Blueprint("filings", __name__)


@bp.post("/estates/<estate_id>/filings")
@require_auth(["Executor"])
def create_filing(estate_id: str):
    body = get_json_body(request)
    with store.lock:
        require_estate(estate_id)
        filing_type = body.get("filing_type")
        if filing_type not in FILING_TYPES:
            raise ApiError("ERR_BAD_REQUEST", 400, "filing_type must be one of the enum literals.")
        filer_id = body.get("filed_by_fiduciary_id")
        if not isinstance(filer_id, str) or not filer_id:
            raise ApiError("ERR_BAD_REQUEST", 400, "filed_by_fiduciary_id is required.")
        # Filing fiduciary must reference an existing fiduciary in this estate.
        filer = store.fiduciaries.get(filer_id)
        if not filer or filer["estate_id"] != estate_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "filed_by_fiduciary_id does not reference a fiduciary in this estate.")

        # Priority 9: non-PETITION filings must be filed by CONFIRMED EXECUTOR.
        if filing_type != "PETITION_TO_PROBATE":
            if not (filer["scope_type"] == "EXECUTOR" and filer["status"] == "CONFIRMED"):
                raise ApiError("ERR_FILING_NOT_PERMITTED", 403,
                               "Non-PETITION filings require a CONFIRMED EXECUTOR fiduciary.")

        # First-writer-wins on (estate_id, filing_type, status=SUBMITTED).
        for f in store.filings.values():
            if (f["estate_id"] == estate_id
                    and f["filing_type"] == filing_type
                    and f["status"] == "SUBMITTED"):
                raise ApiError("ERR_FILING_ALREADY_PENDING", 409,
                               f"Another {filing_type} filing is already in SUBMITTED status.")

        fid = new_uuid()
        now = store.now()
        f = {
            "id": fid,
            "estate_id": estate_id,
            "filing_type": filing_type,
            "filed_by_fiduciary_id": filer_id,
            "status": "SUBMITTED",
            "court_response_at": None,
            "rejection_reason": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.filings[fid] = f
    return success(serialize_filing(f), 201)


@bp.get("/estates/<estate_id>/filings/<filing_id>")
@require_auth(["Executor", "Beneficiary", "CourtClerk"])
def get_filing(estate_id: str, filing_id: str):
    with store.lock:
        require_estate(estate_id)
        f = require_child(store.filings, estate_id, filing_id)
    return success(serialize_filing(f), 200)


@bp.get("/estates/<estate_id>/filings")
@require_auth(["Executor", "Beneficiary", "CourtClerk"])
def list_filings(estate_id: str):
    limit, offset = pop_pagination(request.args)
    type_f = request.args.get("filing_type")
    status_f = request.args.get("status")
    if type_f is not None and type_f not in FILING_TYPES:
        raise ApiError("ERR_BAD_REQUEST", 400, "filing_type filter invalid.")
    if status_f is not None and status_f not in FILING_STATUSES:
        raise ApiError("ERR_BAD_REQUEST", 400, "status filter invalid.")

    with store.lock:
        require_estate(estate_id)
        rows = [f for f in store.filings.values() if f["estate_id"] == estate_id]
        if type_f:
            rows = [r for r in rows if r["filing_type"] == type_f]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        rows = sort_by_created_at(rows)
        page, total = paginate(rows, limit, offset)
        items = [serialize_filing(r) for r in page]
    return list_success(items, limit, offset, total, 200)


@bp.post("/estates/<estate_id>/filings/<filing_id>/state")
@require_auth(["CourtClerk", "Executor"])
def transition_filing_state(estate_id: str, filing_id: str):
    body = get_json_body(request)
    to_status = body.get("to_status")
    if to_status not in FILING_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Unknown target status for filing transition.")
    role = current_role()

    with store.lock:
        require_estate(estate_id)
        f = require_child(store.filings, estate_id, filing_id)
        check_version(f, body)
        current = f["status"]

        # SUBMITTED → ACCEPTED | REJECTED | REVISION_REQUESTED — CourtClerk only.
        if current == "SUBMITTED" and to_status in ("ACCEPTED", "REJECTED", "REVISION_REQUESTED"):
            if role != "CourtClerk":
                raise ApiError("ERR_FORBIDDEN", 403,
                               "Only CourtClerk may rule on a filing.")
            if to_status == "ACCEPTED":
                _check_acceptance_preconditions(f, estate_id)
                f["status"] = "ACCEPTED"
                f["court_response_at"] = store.now()
                bump(f)
                return success(serialize_filing(f), 200)
            else:
                reason = body.get("rejection_reason")
                if not isinstance(reason, str) or not reason.strip():
                    raise ApiError("ERR_BAD_REQUEST", 400,
                                   "rejection_reason is required for REJECTED/REVISION_REQUESTED.")
                f["status"] = to_status
                f["rejection_reason"] = reason
                f["court_response_at"] = store.now()
                bump(f)
                return success(serialize_filing(f), 200)

        # REVISION_REQUESTED → SUBMITTED — Executor re-submits.
        if current == "REVISION_REQUESTED" and to_status == "SUBMITTED":
            if role != "Executor":
                raise ApiError("ERR_FORBIDDEN", 403,
                               "Only Executor may re-submit a filing.")
            # Re-submit must not collide with another pending filing.
            for other in store.filings.values():
                if other["id"] == f["id"]:
                    continue
                if (other["estate_id"] == f["estate_id"]
                        and other["filing_type"] == f["filing_type"]
                        and other["status"] == "SUBMITTED"):
                    raise ApiError("ERR_FILING_ALREADY_PENDING", 409,
                                   f"Another {f['filing_type']} filing is already in SUBMITTED status.")
            f["status"] = "SUBMITTED"
            f["rejection_reason"] = None
            f["court_response_at"] = None
            bump(f)
            return success(serialize_filing(f), 200)

        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Cannot transition filing from {current} to {to_status}.")


def _check_acceptance_preconditions(filing: dict, estate_id: str):
    ftype = filing["filing_type"]
    if ftype == "INVENTORY_REPORT":
        for a in store.assets.values():
            if a["estate_id"] != estate_id:
                continue
            if a["status"] not in ("INVENTORIED", "APPRAISED", "EXCLUDED"):
                raise ApiError("ERR_ASSETS_NOT_INVENTORIED", 409,
                               f"Asset {a['id']} is still in status {a['status']}.")
    elif ftype == "DISTRIBUTION_PETITION":
        sums: dict[str, int] = {}
        for d in store.designations.values():
            if d["estate_id"] != estate_id:
                continue
            if d["status"] == "PROPOSED":
                sums[d["asset_id"]] = sums.get(d["asset_id"], 0) + d["share_basis_points"]
        for a in store.assets.values():
            if a["estate_id"] != estate_id:
                continue
            if a["status"] in ("APPRAISED", "INVENTORIED"):
                if sums.get(a["id"], 0) != 10000:
                    raise ApiError("ERR_DESIGNATIONS_INCOMPLETE", 422,
                                   f"Asset {a['id']} PROPOSED share sum is not 10000.")
    elif ftype == "FINAL_ACCOUNTING":
        for d in store.distributions.values():
            if d["estate_id"] != estate_id:
                continue
            if d["status"] != "EXECUTED":
                raise ApiError("ERR_DISTRIBUTIONS_PENDING", 409,
                               "All distributions must be EXECUTED before FINAL_ACCOUNTING.")
