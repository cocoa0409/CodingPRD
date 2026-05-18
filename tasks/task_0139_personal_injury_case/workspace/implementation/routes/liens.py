"""Lien endpoints (PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

from config import (
    LIEN_TYPES,
    LIEN_TYPES_NEGOTIABLE,
    LIEN_TYPES_STATUTORY,
    ROLE_ATTORNEY,
    ROLE_MANAGING_PARTNER,
    ROLE_PARALEGAL,
)
from db import store
from errors import raise_error
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    get_json_body,
    get_pagination_args,
    paginate,
    require_field,
)
from services.case_engine import (
    assert_case_not_closed,
    check_version_match,
    get_case_or_404,
    now,
    touch,
)
from services.serializers import lien_to_dict
from utils import new_uuid


bp = Blueprint("liens", __name__)

ALL_ROLES = [ROLE_PARALEGAL, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER]
RW_ROLES = [ROLE_PARALEGAL, ROLE_ATTORNEY]


def _get_lien_or_404(cid: str, lid: str) -> dict:
    get_case_or_404(cid)
    lien = store.liens.get(lid)
    if not lien or lien["case_id"] != cid:
        raise_error("ERR_NOT_FOUND", f"Lien {lid} not found on case {cid}.")
    return lien


@bp.post("/pi-cases/<cid>/liens")
@require_auth(RW_ROLES)
def create_lien(cid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    assert_case_not_closed(case_row)

    name = require_field(body, "lienholder_name")
    if not isinstance(name, str):
        raise_error("ERR_VALIDATION", "lienholder_name must be a string.")

    lien_type = require_field(body, "lien_type")
    if lien_type not in LIEN_TYPES:
        raise_error("ERR_VALIDATION", f"Invalid lien_type {lien_type}.")

    if "face_amount_cents" not in body:
        raise_error("ERR_VALIDATION", "face_amount_cents is required.")
    face = body["face_amount_cents"]
    if not isinstance(face, int) or isinstance(face, bool) or face <= 0:
        raise_error("ERR_VALIDATION", "face_amount_cents must be a positive integer.")

    with store.lock:
        row = {
            "id": new_uuid(),
            "case_id": cid,
            "created_at": now(),
            "updated_at": now(),
            "version": 1,
            "lienholder_name": name,
            "lien_type": lien_type,
            "face_amount_cents": int(face),
            "negotiated_amount_cents": None,
            "status": "ASSERTED",
            "final_paid_amount_cents": None,
            "priority_rank": None,
        }
        store.liens[row["id"]] = row

    return success(lien_to_dict(row), 201)


@bp.post("/pi-cases/<cid>/liens/<lid>/negotiate")
@require_auth(RW_ROLES)
def negotiate_lien(cid, lid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    lien = _get_lien_or_404(cid, lid)
    assert_case_not_closed(case_row)

    check_version_match(lien, body.get("version"))

    if lien["status"] != "ASSERTED":
        raise_error("ERR_INVALID_STATE", f"Lien must be ASSERTED (was {lien['status']}).")
    if lien["lien_type"] not in LIEN_TYPES_NEGOTIABLE:
        raise_error(
            "ERR_INVALID_STATE",
            f"Lien type {lien['lien_type']} is not negotiable by paralegal action.",
        )

    with store.lock:
        lien["status"] = "NEGOTIATING"
        touch(lien)

    return success(lien_to_dict(lien), 200)


@bp.patch("/pi-cases/<cid>/liens/<lid>")
@require_auth(RW_ROLES)
def patch_lien(cid, lid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    lien = _get_lien_or_404(cid, lid)
    assert_case_not_closed(case_row)

    check_version_match(lien, body.get("version"))

    if lien["status"] not in ("NEGOTIATING", "ASSERTED"):
        raise_error(
            "ERR_INVALID_STATE",
            f"Lien is not in a state allowing patch (was {lien['status']}).",
        )

    if "negotiated_amount_cents" not in body:
        raise_error("ERR_VALIDATION", "negotiated_amount_cents is required for patch.")
    amount = body["negotiated_amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise_error("ERR_LIEN_NEGOTIATION_INVALID", "negotiated_amount_cents must be an integer.")
    if amount <= 0 or amount > int(lien["face_amount_cents"]):
        raise_error(
            "ERR_LIEN_NEGOTIATION_INVALID",
            "negotiated_amount_cents must satisfy 0 < value <= face_amount_cents.",
        )

    # State transition: NEGOTIATING → REDUCED (for negotiable liens). For
    # statutory ASSERTED liens, the PRD says they are auto-reduced at
    # disbursement time, so a manual PATCH on a statutory ASSERTED lien
    # should be rejected.
    if lien["status"] == "ASSERTED" and lien["lien_type"] in LIEN_TYPES_STATUTORY:
        raise_error(
            "ERR_INVALID_STATE",
            "Statutory liens are auto-reduced at disbursement; not by direct PATCH.",
        )

    with store.lock:
        lien["negotiated_amount_cents"] = int(amount)
        lien["status"] = "REDUCED"
        touch(lien)

    return success(lien_to_dict(lien), 200)


@bp.post("/pi-cases/<cid>/liens/<lid>/dispute")
@require_auth([ROLE_ATTORNEY])
def dispute_lien(cid, lid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    lien = _get_lien_or_404(cid, lid)
    assert_case_not_closed(case_row)

    check_version_match(lien, body.get("version"))

    if lien["status"] in ("RESOLVED", "DISPUTED"):
        raise_error(
            "ERR_INVALID_STATE",
            f"Lien is already terminal (status={lien['status']}).",
        )

    with store.lock:
        lien["status"] = "DISPUTED"
        touch(lien)

    return success(lien_to_dict(lien), 200)


@bp.get("/pi-cases/<cid>/liens")
@require_auth(ALL_ROLES)
def list_liens(cid):
    get_case_or_404(cid)
    limit, offset = get_pagination_args()
    status_filter = request.args.get("status")

    rows = [l for l in store.liens.values() if l["case_id"] == cid]
    if status_filter:
        rows = [l for l in rows if l["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return list_success([lien_to_dict(r) for r in page], limit, offset, total)
