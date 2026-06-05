"""Demand-letter routes (PRD §3.4)."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

import db
from db import (
    demand_letters, cases, damages_items, medical_records_requests,
    stamp_common, bump,
)
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_DEMAND_PREREQUISITES_NOT_MET,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_auth, get_json_body, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_str, require_decimal_range,
    get_or_404_path, get_or_fk_404,
    assert_sol_not_expired,
)
from services.calculations import compute_demand_amount_cents
from services.cascades import cascade_case_to_demand_sent


bp = Blueprint("demand_letters", __name__)


def _view(d: dict) -> dict:
    pm = d["pain_multiplier"]
    if isinstance(pm, Decimal):
        pm_out = float(pm)
    else:
        pm_out = pm
    return {
        "id": d["id"],
        "case_id": d["case_id"],
        "demand_amount_cents": d["demand_amount_cents"],
        "pain_multiplier": pm_out,
        "status": d["status"],
        "drafted_by_user_id": d.get("drafted_by_user_id"),
        "sent_at": d.get("sent_at"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/demand-letters")
def draft_demand():
    require_auth({"Attorney"})()
    body = get_json_body()
    case_id = require_str(body, "case_id")
    pain_multiplier = require_decimal_range(body, "pain_multiplier", "1.0", "5.0")

    case = get_or_fk_404(cases, case_id, "Case")

    # State precondition: case must be ACTIVE; need a REVIEWED records request.
    # Priority 7 SOL fires before priority 11 referential check.
    assert_sol_not_expired(case)
    if case["status"] != "ACTIVE":
        raise APIError(
            ERR_DEMAND_PREREQUISITES_NOT_MET, 422,
            "Demand letter requires Case.status == ACTIVE",
        )
    has_reviewed = any(
        r for r in medical_records_requests.values()
        if r["case_id"] == case_id and r["status"] == "REVIEWED"
    )
    if not has_reviewed:
        raise APIError(
            ERR_DEMAND_PREREQUISITES_NOT_MET, 422,
            "Demand letter requires at least one REVIEWED records request",
        )

    # Compute the demand amount from the case's INCLUDED damages items at this
    # moment. The order is pinned per PRD §3.4.
    included = [
        di for di in damages_items.values()
        if di["case_id"] == case_id and di["status"] == "INCLUDED"
    ]
    amount = compute_demand_amount_cents(included, pain_multiplier)

    drafted_by = current_user_id() or ""

    dl = {
        "case_id": case_id,
        "demand_amount_cents": amount,
        "pain_multiplier": pain_multiplier,
        "status": "DRAFT",
        "drafted_by_user_id": drafted_by,
        "sent_at": None,
    }
    stamp_common(dl)
    demand_letters[dl["id"]] = dl
    return ok_object(_view(dl), 201)


@bp.get("/demand-letters/<dlid>")
def get_demand(dlid):
    require_auth({"Attorney", "ManagingPartner", "Paralegal"})()
    dl = get_or_404_path(demand_letters, dlid, "DemandLetter")
    return ok_object(_view(dl), 200)


@bp.get("/demand-letters")
def list_demands():
    require_auth({"Attorney", "ManagingPartner", "Paralegal"})()
    limit, offset = paginate_params(request.args)
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    items = list(demand_letters.values())
    if case_id is not None:
        items = [d for d in items if d["case_id"] == case_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: d["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array([_view(d) for d in page], limit, offset, total, 200)


@bp.post("/demand-letters/<dlid>/send")
def send_demand(dlid):
    require_auth({"ManagingPartner"})()
    dl = get_or_404_path(demand_letters, dlid, "DemandLetter")
    if dl["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "DemandLetter must be DRAFT to send")
    case = cases.get(dl["case_id"])
    if case is None:
        raise APIError(ERR_INVALID_STATE, 409, "Parent case not found")
    if case["status"] != "ACTIVE":
        # Cross-entity: case must be ACTIVE
        from errors import ERR_CROSS_ENTITY_STATE
        raise APIError(
            ERR_CROSS_ENTITY_STATE, 409,
            "Case must be ACTIVE to send the demand letter",
        )
    # Need a REVIEWED records request still on the case (PRD §3.4 "at least one
    # REVIEWED records request must still be present").
    has_reviewed = any(
        r for r in medical_records_requests.values()
        if r["case_id"] == dl["case_id"] and r["status"] == "REVIEWED"
    )
    if not has_reviewed:
        from errors import ERR_CROSS_ENTITY_STATE
        raise APIError(
            ERR_CROSS_ENTITY_STATE, 409,
            "Demand letter send requires a REVIEWED records request",
        )

    # Segregation of duties — partner's X-User-ID != drafted_by_user_id.
    sender_uid = current_user_id() or ""
    if sender_uid == dl.get("drafted_by_user_id"):
        raise APIError(
            ERR_SEGREGATION_OF_DUTIES, 422,
            "ManagingPartner cannot send a DemandLetter they drafted",
        )

    dl["status"] = "SENT"
    dl["sent_at"] = db.get_current_utc()
    bump(dl)
    # Cascade: case ACTIVE -> DEMAND_SENT.
    cascade_case_to_demand_sent(case)
    return ok_object(_view(dl), 200)


@bp.post("/demand-letters/<dlid>/acknowledge")
def acknowledge(dlid):
    require_auth({"Attorney"})()
    dl = get_or_404_path(demand_letters, dlid, "DemandLetter")
    if dl["status"] != "SENT":
        raise APIError(ERR_INVALID_STATE, 409, "DemandLetter must be SENT to acknowledge")
    dl["status"] = "ACKNOWLEDGED"
    bump(dl)
    return ok_object(_view(dl), 200)


@bp.post("/demand-letters/<dlid>/withdraw")
def withdraw(dlid):
    require_auth({"Attorney"})()
    dl = get_or_404_path(demand_letters, dlid, "DemandLetter")
    if dl["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "DemandLetter must be DRAFT to withdraw")
    dl["status"] = "WITHDRAWN"
    bump(dl)
    return ok_object(_view(dl), 200)
