"""QualitativeFactor endpoints."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_FACTOR_DOCUMENTATION_INSUFFICIENT,
    ERR_FACTOR_WINDOW_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
)
from middleware import ALL_ROLES, require_roles
from response import success_response
from services import FACTOR_CODES, get_or_404, public, stamp_new, touch
from validation import (
    get_body,
    opt_str,
    quarter_index,
    req_enum,
    req_int,
    req_period,
    req_str,
)

bp = Blueprint("factors", __name__)


@bp.post("/cecl/qualitative-factors")
def create_factor():
    require_roles(["CreditAnalyst"])
    body = get_body()
    segment_id = req_str(body, "segment_id")
    factor_code = req_enum(body, "factor_code", FACTOR_CODES)
    adjustment_bps = req_int(body, "adjustment_bps")
    from_period = req_period(body, "effective_from_period")
    to_period = req_period(body, "effective_to_period")
    documentation_text = opt_str(body, "documentation_text", "")
    segment = db.segments.get(segment_id)
    if segment is None:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "segment_id does not identify an existing segment"
        )
    if not (-2000 <= adjustment_bps <= 2000) or adjustment_bps == 0:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "adjustment_bps must be in -2000..2000 and non-zero",
        )
    from_idx = quarter_index(from_period)
    to_idx = quarter_index(to_period)
    if to_idx < from_idx:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "effective_to_period must not precede effective_from_period",
        )
    for existing in db.factors.values():
        if existing["segment_id"] != segment_id:
            continue
        if existing["factor_code"] != factor_code:
            continue
        if existing["status"] == "RETIRED":
            continue
        ex_from = quarter_index(existing["effective_from_period"])
        ex_to = quarter_index(existing["effective_to_period"])
        # Closed windows [from, to] overlap iff from1 <= to2 and from2 <= to1
        if from_idx <= ex_to and ex_from <= to_idx:
            raise ApiError(
                ERR_FACTOR_WINDOW_OVERLAP,
                409,
                "Closed window overlaps another non-RETIRED factor with the same segment and code",
            )
    factor = stamp_new(
        {
            "segment_id": segment_id,
            "factor_code": factor_code,
            "adjustment_bps": adjustment_bps,
            "effective_from_period": from_period,
            "effective_to_period": to_period,
            "documentation_text": documentation_text,
            "status": "DRAFT",
        }
    )
    db.factors[factor["id"]] = factor
    return success_response(public(factor), 201)


@bp.get("/cecl/qualitative-factors/<factorId>")
def get_factor(factorId):
    require_roles(ALL_ROLES)
    factor = get_or_404(db.factors, factorId, "QualitativeFactor")
    return success_response(public(factor), 200)


@bp.post("/cecl/qualitative-factors/<factorId>/document")
def document_factor(factorId):
    require_roles(["CreditAnalyst"])
    factor = get_or_404(db.factors, factorId, "QualitativeFactor")
    body = get_body()
    documentation_text = req_str(body, "documentation_text")
    if factor["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a DRAFT factor can be documented",
        )
    if len(documentation_text.strip()) < 50:
        raise ApiError(
            ERR_FACTOR_DOCUMENTATION_INSUFFICIENT,
            422,
            "documentation_text must have a trimmed length of at least 50 characters",
        )
    factor["documentation_text"] = documentation_text
    factor["status"] = "DOCUMENTED"
    touch(factor)
    return success_response(public(factor), 200)


@bp.post("/cecl/qualitative-factors/<factorId>/approve")
def approve_factor(factorId):
    require_roles(["ChiefCreditOfficer"])
    get_body()
    factor = get_or_404(db.factors, factorId, "QualitativeFactor")
    if factor["status"] != "DOCUMENTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a DOCUMENTED factor can be approved",
        )
    factor["status"] = "APPROVED"
    touch(factor)
    return success_response(public(factor), 200)


@bp.post("/cecl/qualitative-factors/<factorId>/retire")
def retire_factor(factorId):
    require_roles(["ChiefCreditOfficer"])
    get_body()
    factor = get_or_404(db.factors, factorId, "QualitativeFactor")
    if factor["status"] != "APPROVED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only an APPROVED factor can be retired",
        )
    factor["status"] = "RETIRED"
    touch(factor)
    return success_response(public(factor), 200)
