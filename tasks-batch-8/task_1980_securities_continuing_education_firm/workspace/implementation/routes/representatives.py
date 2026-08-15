"""Representatives: register / list / get / terminate."""

from decimal import Decimal

from flask import Blueprint, request

from db import store, base_record
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_DUPLICATE_CRD_NUMBER,
                    ERR_REGISTRATION_TERMINATED)
from middleware import require_roles, actor, json_body, require_fields
from response import success, paginate
from services import get_or_404, by_seq, terminate_representative
from util import to_decimal, require_str, require_enum, view

bp = Blueprint("representatives", __name__)

ROLE_TIERS = ("RR", "PRINCIPAL")


@bp.post("/representatives")
@require_roles("TrainingAdmin")
def create_representative():
    body = json_body()
    # Shape first (no path ids / body FKs to resolve for this endpoint).
    require_fields(body, "crd_number", "full_name", "email", "role_tier",
                   "insurance_licensed", "resident_state_code")
    crd_number = require_str(body["crd_number"], "crd_number")
    full_name = require_str(body["full_name"], "full_name")
    email = require_str(body["email"], "email")
    role_tier = require_enum(body["role_tier"], "role_tier", ROLE_TIERS)
    if not isinstance(body["insurance_licensed"], bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'insurance_licensed' must be a boolean")
    insurance_licensed = body["insurance_licensed"]
    resident_state_code = require_str(body["resident_state_code"],
                                      "resident_state_code")
    prior = body.get("prior_year_excess_hours")
    if prior is None:
        prior = Decimal("0")
    else:
        prior = to_decimal(prior, "prior_year_excess_hours")
        if prior < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Field 'prior_year_excess_hours' must be >= 0")
    # Uniqueness: crd_number across all representatives.
    for r in store.representatives.values():
        if r["crd_number"] == crd_number:
            raise ApiError(ERR_DUPLICATE_CRD_NUMBER, 409,
                           "crd_number '%s' is already registered" % crd_number)
    rec = base_record()
    rec.update({
        "crd_number": crd_number,
        "full_name": full_name,
        "email": email,
        "role_tier": role_tier,
        "insurance_licensed": insurance_licensed,
        "resident_state_code": resident_state_code,
        "prior_year_excess_hours": prior,
        "registration_status": "ACTIVE",
    })
    store.representatives[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/representatives")
@require_roles("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")
def list_representatives():
    items = by_seq(store.representatives.values())
    status = request.args.get("registration_status")
    if status is not None:
        items = [r for r in items if r["registration_status"] == status]
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    page, pagination = paginate(items)
    return success([view(r) for r in page], is_list=True, pagination=pagination)


@bp.get("/representatives/<repId>")
@require_roles("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")
def get_representative(repId):
    rec = get_or_404(store.representatives, repId, "Representative")
    return success(view(rec))


@bp.post("/representatives/<repId>/terminate")
@require_roles("ComplianceOfficer")
def terminate_representative_route(repId):
    rec = get_or_404(store.representatives, repId, "Representative")
    if rec["registration_status"] == "TERMINATED":
        raise ApiError(ERR_REGISTRATION_TERMINATED, 409,
                       "Representative is already TERMINATED")
    terminate_representative(rec, actor())
    return success(view(rec))
