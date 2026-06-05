"""Damages-item routes (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, request

from db import (
    damages_items, cases, medical_records_requests, demand_letters,
    stamp_common, bump,
)
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CROSS_ENTITY_STATE,
    ERR_DAMAGES_OVER_CAP,
    ERR_MISSING_MEDICAL_RECORDS,
)
from middleware import require_auth, get_json_body, current_role
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_str, require_int, require_enum,
    get_or_404_path, get_or_fk_404,
)
from routes.cases import recompute_included_damages_total


bp = Blueprint("damages_items", __name__)


VALID_CATEGORIES = {
    "MEDICAL_BILLS", "LOST_WAGES", "PAIN_SUFFERING",
    "FUTURE_MEDICAL", "PROPERTY",
}
PAIN_CAP_JURISDICTIONS = {"CA", "FL"}
PAIN_CAP_CENTS = 25000000  # $250,000


def _view(d: dict) -> dict:
    return {
        "id": d["id"],
        "case_id": d["case_id"],
        "category": d["category"],
        "amount_cents": d["amount_cents"],
        "status": d["status"],
        "documentation_note": d.get("documentation_note", ""),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/damages-items")
def create_damages_item():
    require_auth({"Paralegal", "Attorney"})()
    body = get_json_body()
    case_id = require_str(body, "case_id")
    category = require_enum(body, "category", VALID_CATEGORIES)
    amount_cents = require_int(body, "amount_cents", min_value=0)
    doc_note = body.get("documentation_note", "")
    if not isinstance(doc_note, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "documentation_note must be a string")

    case = get_or_fk_404(cases, case_id, "Case")

    # Jurisdictional cap: CA/FL PAIN_SUFFERING <= $250,000.
    if category == "PAIN_SUFFERING" and case["jurisdiction"] in PAIN_CAP_JURISDICTIONS:
        if amount_cents > PAIN_CAP_CENTS:
            raise APIError(
                ERR_DAMAGES_OVER_CAP, 422,
                "PAIN_SUFFERING amount exceeds the jurisdictional $250,000 cap",
            )

    d = {
        "case_id": case_id,
        "category": category,
        "amount_cents": amount_cents,
        "status": "PROPOSED",
        "documentation_note": doc_note,
    }
    stamp_common(d)
    damages_items[d["id"]] = d
    return ok_object(_view(d), 201)


@bp.get("/damages-items/<did>")
def get_damages_item(did):
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    d = get_or_404_path(damages_items, did, "DamagesItem")
    return ok_object(_view(d), 200)


@bp.get("/damages-items")
def list_damages_items():
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    limit, offset = paginate_params(request.args)
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    category = request.args.get("category")
    items = list(damages_items.values())
    if case_id is not None:
        items = [d for d in items if d["case_id"] == case_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if category is not None:
        items = [d for d in items if d["category"] == category]
    items.sort(key=lambda d: d["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array([_view(d) for d in page], limit, offset, total, 200)


@bp.post("/damages-items/<did>/include")
def include_item(did):
    require_auth({"Attorney"})()
    d = get_or_404_path(damages_items, did, "DamagesItem")
    if d["status"] != "PROPOSED":
        raise APIError(ERR_INVALID_STATE, 409, "Item must be PROPOSED to include")
    case = cases.get(d["case_id"])
    if case is None:
        # Should be unreachable: case existed on create. Defensive.
        raise APIError(ERR_CROSS_ENTITY_STATE, 409, "Parent case not found")
    if case["status"] not in ("ACTIVE", "DEMAND_SENT", "IN_NEGOTIATION"):
        raise APIError(
            ERR_CROSS_ENTITY_STATE, 409,
            "Case must be ACTIVE, DEMAND_SENT, or IN_NEGOTIATION to include a damages item",
        )
    # MEDICAL_BILLS requires at least one REVIEWED records request.
    if d["category"] == "MEDICAL_BILLS":
        has_reviewed = any(
            r for r in medical_records_requests.values()
            if r["case_id"] == d["case_id"] and r["status"] == "REVIEWED"
        )
        if not has_reviewed:
            raise APIError(
                ERR_MISSING_MEDICAL_RECORDS, 422,
                "MEDICAL_BILLS items require at least one REVIEWED records request",
            )
    d["status"] = "INCLUDED"
    bump(d)
    recompute_included_damages_total(d["case_id"])
    bump(case)
    return ok_object(_view(d), 200)


@bp.post("/damages-items/<did>/exclude")
def exclude_item(did):
    require_auth({"Attorney", "ManagingPartner"})()
    d = get_or_404_path(damages_items, did, "DamagesItem")
    role = current_role()
    case = cases.get(d["case_id"])
    if case is None:
        raise APIError(ERR_CROSS_ENTITY_STATE, 409, "Parent case not found")

    if d["status"] == "PROPOSED":
        if role not in ("Attorney", "ManagingPartner"):
            # Should be unreachable; require_auth already filtered.
            raise APIError(ERR_INVALID_STATE, 409, "Role cannot exclude")
        # Scaffold §1.2: PROPOSED->EXCLUDED actor is Attorney; PRD doesn't
        # explicitly forbid ManagingPartner here but says "by the Attorney"
        # for the PROPOSED->EXCLUDED path. The RBAC table on POST
        # /damages-items/{id}/exclude lists Attorney+ManagingPartner. We
        # accept either here, since PRD's exclude text in §3.3 says the
        # promotion path: "An item can also be moved from PROPOSED to
        # EXCLUDED by the Attorney" — but the endpoint table allows
        # both. The shared scope is consistent with the endpoint table;
        # the PROPOSED-only path doesn't require any cross-entity check.
        d["status"] = "EXCLUDED"
        bump(d)
        return ok_object(_view(d), 200)

    if d["status"] == "INCLUDED":
        # PRD §3.3: only a ManagingPartner may retract an already-INCLUDED item.
        if role != "ManagingPartner":
            raise APIError(
                ERR_INVALID_STATE, 409,
                "Only a ManagingPartner can exclude an INCLUDED damages item",
            )
        if case["status"] not in ("ACTIVE", "DEMAND_SENT", "IN_NEGOTIATION"):
            raise APIError(
                ERR_CROSS_ENTITY_STATE, 409,
                "Case must be ACTIVE, DEMAND_SENT, or IN_NEGOTIATION to retract",
            )
        # Cannot retract if any demand letter on the case is SENT or
        # ACKNOWLEDGED.
        for dl in demand_letters.values():
            if dl["case_id"] == d["case_id"] and dl["status"] in ("SENT", "ACKNOWLEDGED"):
                raise APIError(
                    ERR_CROSS_ENTITY_STATE, 409,
                    "Cannot retract a line item used in a SENT/ACKNOWLEDGED demand letter",
                )
        d["status"] = "EXCLUDED"
        bump(d)
        recompute_included_damages_total(d["case_id"])
        bump(case)
        return ok_object(_view(d), 200)

    raise APIError(ERR_INVALID_STATE, 409,
                   "Item must be PROPOSED or INCLUDED to exclude")
