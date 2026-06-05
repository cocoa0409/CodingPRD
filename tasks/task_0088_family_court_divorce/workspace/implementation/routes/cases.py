"""Case endpoints + Case state machine (PRD §3.1, §3.2, §3.5, §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_GUIDELINE_NOT_FOUND,
    ERR_ANSWER_EXISTS,
    ERR_CASE_TERMINAL,
)
from middleware import require_auth, get_json_body, paginate_params, slice_page, current_user_id
from response import ok_object, ok_array
from services.common import (
    serialize,
    serialize_list,
    sorted_by_creation,
    get_case,
    assert_case_not_terminal,
    petitioner_of,
    respondent_of,
    recompute_active_support_total,
)

bp = Blueprint("cases", __name__)

READ_ROLES = ["Clerk", "Judge", "Mediator", "Petitioner", "Respondent"]
LIST_ROLES = ["Clerk", "Judge"]


def _require_int(body, field, *, minimum=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be >= {minimum}")
    return v


@bp.post("/api/cases")
def create_case():
    require_auth(["Clerk"])()
    body = get_json_body()

    state_code = body.get("state_code")
    if not isinstance(state_code, str) or len(state_code) != 2 or not state_code.isupper():
        raise APIError(ERR_INVALID_REQUEST, 422, "state_code must be a 2-char uppercase string")
    caption = body.get("caption")
    if not isinstance(caption, str) or caption == "":
        raise APIError(ERR_INVALID_REQUEST, 422, "caption is required")
    marriage_months = _require_int(body, "marriage_months", minimum=0)
    filing_fee_cents = _require_int(body, "filing_fee_cents", minimum=0)

    # Guideline-existence is a referential check (ERR_GUIDELINE_NOT_FOUND, PRD §3.1).
    if not any(g["state_code"] == state_code for g in db.guideline_schedules.values()):
        raise APIError(ERR_GUIDELINE_NOT_FOUND, 404, "No guideline schedule for state_code")

    case = {
        "state_code": state_code,
        "caption": caption,
        "marriage_months": marriage_months,
        "filing_fee_cents": filing_fee_cents,
        "status": "FILED",
        "mediator_user_id": None,
        "judge_user_id": None,
        "active_support_total_cents": 0,
        "net_fees_collected_cents": filing_fee_cents,
        "petitioner_disclosure_verified": False,
        "respondent_disclosure_verified": False,
    }
    db.stamp_common(case)
    db.cases[case["id"]] = case
    return ok_object(serialize(case), 201)


@bp.get("/api/cases/<rid>")
def get_case_route(rid):
    require_auth(READ_ROLES)()
    case = get_case(rid)
    return ok_object(serialize(case), 200)


@bp.get("/api/cases")
def list_cases():
    require_auth(LIST_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.cases.values()))
    state_code = request.args.get("state_code")
    status = request.args.get("status")
    if state_code is not None:
        items = [c for c in items if c["state_code"] == state_code]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/api/cases/<rid>/default")
def default_case(rid):
    require_auth(["Clerk"])()
    case = get_case(rid)
    assert_case_not_terminal(case)
    if case["status"] != "AWAITING_RESPONSE":
        raise APIError(ERR_INVALID_STATE, 409, "Default requires AWAITING_RESPONSE")
    # No ANSWER pleading may exist (ERR_ANSWER_EXISTS).
    for p in db.pleadings.values():
        if p["case_id"] == case["id"] and p["pleading_type"] == "ANSWER":
            raise APIError(ERR_ANSWER_EXISTS, 409, "An ANSWER pleading exists")
    case["status"] = "DEFAULT_PENDING"
    db.bump(case)
    return ok_object(serialize(case), 200)


@bp.post("/api/cases/<rid>/advance")
def advance_case(rid):
    require_auth(["Clerk"])()
    case = get_case(rid)
    assert_case_not_terminal(case)
    body = get_json_body()
    to_status = body.get("to_status")
    if to_status not in ("DISCOVERY", "AWAITING_JUDGMENT"):
        raise APIError(ERR_INVALID_REQUEST, 422, "to_status must be DISCOVERY or AWAITING_JUDGMENT")

    if to_status == "DISCOVERY":
        if case["status"] != "CONTESTED":
            raise APIError(ERR_INVALID_STATE, 409, "DISCOVERY advance requires CONTESTED")
        # Both PETITIONER and RESPONDENT parties must exist.
        if petitioner_of(case["id"]) is None or respondent_of(case["id"]) is None:
            raise APIError(ERR_INVALID_STATE, 409, "Both parties must exist")
        case["status"] = "DISCOVERY"
    else:  # AWAITING_JUDGMENT (default path)
        if case["status"] != "DEFAULT_PENDING":
            raise APIError(ERR_INVALID_STATE, 409, "AWAITING_JUDGMENT advance requires DEFAULT_PENDING")
        # Petitioner disclosure must be VERIFIED.
        if not case.get("petitioner_disclosure_verified"):
            raise APIError(ERR_INVALID_STATE, 409, "Petitioner disclosure must be verified")
        case["status"] = "AWAITING_JUDGMENT"

    db.bump(case)
    return ok_object(serialize(case), 200)


@bp.post("/api/cases/<rid>/assign-mediator")
def assign_mediator(rid):
    require_auth(["Clerk"])()
    case = get_case(rid)
    assert_case_not_terminal(case)
    body = get_json_body()
    mediator_user_id = body.get("mediator_user_id")
    if not isinstance(mediator_user_id, str) or mediator_user_id == "":
        raise APIError(ERR_INVALID_REQUEST, 422, "mediator_user_id is required")
    if case["status"] != "DISCOVERY":
        raise APIError(ERR_INVALID_STATE, 409, "assign-mediator requires DISCOVERY")
    # Both parties' disclosures in SUBMITTED or VERIFIED.
    pet = petitioner_of(case["id"])
    resp = respondent_of(case["id"])
    if pet is None or resp is None:
        raise APIError(ERR_INVALID_STATE, 409, "Both parties must exist")
    if not _party_disclosure_in(pet["id"], {"SUBMITTED", "VERIFIED"}):
        raise APIError(ERR_INVALID_STATE, 409, "Petitioner disclosure must be submitted/verified")
    if not _party_disclosure_in(resp["id"], {"SUBMITTED", "VERIFIED"}):
        raise APIError(ERR_INVALID_STATE, 409, "Respondent disclosure must be submitted/verified")

    case["mediator_user_id"] = mediator_user_id
    case["status"] = "MEDIATION"
    db.bump(case)
    return ok_object(serialize(case), 200)


def _party_disclosure_in(party_id, states):
    return any(
        d["party_id"] == party_id and d["status"] in states
        for d in db.financial_disclosures.values()
    )


@bp.post("/api/cases/<rid>/dismiss")
def dismiss_case(rid):
    require_auth(["Clerk"])()
    case = get_case(rid)
    # Pre-judgment statuses only (terminal already excluded by this set).
    PRE_JUDGMENT = {
        "FILED", "AWAITING_RESPONSE", "DEFAULT_PENDING", "CONTESTED",
        "DISCOVERY", "MEDIATION", "AWAITING_JUDGMENT",
    }
    if case["status"] in ("JUDGMENT_ENTERED", "DISMISSED"):
        raise APIError(ERR_CASE_TERMINAL, 409, "Case is in a terminal status")
    if case["status"] not in PRE_JUDGMENT:
        raise APIError(ERR_INVALID_STATE, 409, "Case cannot be dismissed from this status")

    case["status"] = "DISMISSED"
    case["net_fees_collected_cents"] = 0  # filing fee refunded
    # Vacate every non-VACATED support order; each gets its own version bump.
    for so in db.support_orders.values():
        if so["case_id"] == case["id"] and so["status"] != "VACATED":
            so["status"] = "VACATED"
            db.bump(so)
    recompute_active_support_total(case)  # -> 0
    db.bump(case)
    return ok_object(serialize(case), 200)
