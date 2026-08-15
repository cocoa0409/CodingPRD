"""Authorization endpoints: request, list, decide (SoD + necessity), appeal."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_AUTH_ALREADY_COVERED,
    ERR_INVALID_REQUEST,
    ERR_MEDICAL_NECESSITY_CONFLICT,
    ERR_SOD,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, authenticate
from response import ok_list, ok_object
from services import case_authorizations, sync_case
from util import (
    base_record,
    get_body,
    opt_date,
    paginate,
    req_bool,
    req_enum,
    req_str,
    serialize,
    touch,
)

bp = Blueprint("authorizations", __name__)


def get_auth_or_404(aid):
    rec = db.authorizations.get(aid)
    if rec is None:
        raise not_found("authorization not found")
    return rec


@bp.post("/clearance/cases/<cid>/authorizations")
def create_authorization(cid):
    uid, _ = authenticate(["UtilizationReviewer"])
    case = db.cases.get(cid)
    if case is None:
        raise not_found("case not found")
    b = get_body()
    payer_code = req_str(b, "payer_code")
    cpt_codes = b.get("cpt_codes")
    if not isinstance(cpt_codes, list) or len(cpt_codes) == 0:
        raise ApiError(ERR_INVALID_REQUEST, "cpt_codes must be a non-empty array", 400)
    for c in cpt_codes:
        if not isinstance(c, str):
            raise ApiError(ERR_INVALID_REQUEST, "each cpt_codes entry must be a string", 400)
    # refuse duplication: any requested cpt already covered by an APPROVED,
    # non-expired authorization whose closed window contains service_date
    requested = set(cpt_codes)
    for a in case_authorizations(cid):
        if a["status"] != "APPROVED" or a["valid_from"] is None:
            continue
        if a["valid_from"] <= case["service_date"] <= a["valid_to"]:
            if requested.intersection(a["cpt_codes"]):
                raise ApiError(ERR_AUTH_ALREADY_COVERED,
                               "a requested CPT is already covered by an APPROVED authorization", 409)
    rec = base_record()
    rec.update({
        "case_id": cid,
        "payer_code": payer_code,
        "cpt_codes": list(cpt_codes),
        "status": "REQUESTED",
        "medical_necessity_met": None,
        "auth_number": None,
        "valid_from": None,
        "valid_to": None,
        "requested_by_user_id": uid,
        "decided_by_user_id": None,
    })
    db.authorizations[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/clearance/cases/<cid>/authorizations")
def list_authorizations(cid):
    authenticate(ALL_ROLES)
    if cid not in db.cases:
        raise not_found("case not found")
    page, meta = paginate(case_authorizations(cid))
    return ok_list([serialize(a) for a in page], meta)


@bp.post("/clearance/authorizations/<aid>/decide")
def decide_authorization(aid):
    uid, _ = authenticate(["UtilizationReviewer"])
    auth = get_auth_or_404(aid)
    b = get_body()
    decision = req_enum(b, "decision", ("APPROVED", "DENIED"))
    medical_necessity_met = req_bool(b, "medical_necessity_met")
    valid_from = None
    valid_to = None
    if decision == "APPROVED":
        valid_from = opt_date(b, "valid_from")
        valid_to = opt_date(b, "valid_to")
        if valid_from is None or valid_to is None:
            raise ApiError(ERR_INVALID_REQUEST,
                           "valid_from and valid_to are required for APPROVED", 400)
        if valid_to < valid_from:
            raise ApiError(ERR_INVALID_REQUEST, "valid_to must be >= valid_from", 400)
    else:
        # tolerate (and ignore) dates supplied on a denial only if well-formed
        if b.get("valid_from") is not None:
            opt_date(b, "valid_from")
        if b.get("valid_to") is not None:
            opt_date(b, "valid_to")
    # state legality
    if auth["status"] not in ("REQUESTED", "APPEALED"):
        raise invalid_state("authorization cannot be decided from its current state")
    # segregation of duties before the medical-necessity consistency rule
    if uid == auth["requested_by_user_id"]:
        raise ApiError(ERR_SOD, "the deciding reviewer must differ from the requester", 403)
    # medical-necessity consistency
    if decision == "APPROVED" and medical_necessity_met is not True:
        raise ApiError(ERR_MEDICAL_NECESSITY_CONFLICT,
                       "APPROVED requires medical_necessity_met=true", 422)
    if decision == "DENIED" and medical_necessity_met is not False:
        raise ApiError(ERR_MEDICAL_NECESSITY_CONFLICT,
                       "DENIED requires medical_necessity_met=false", 422)

    auth["medical_necessity_met"] = medical_necessity_met
    auth["decided_by_user_id"] = uid
    if decision == "APPROVED":
        auth["status"] = "APPROVED"
        auth["auth_number"] = db.mint_auth_number()
        auth["valid_from"] = valid_from
        auth["valid_to"] = valid_to
    else:
        auth["status"] = "DENIED" if auth["status"] == "REQUESTED" else "DENIED_FINAL"
    touch(auth)
    sync_case(db.cases[auth["case_id"]])
    return ok_object(serialize(auth))


@bp.post("/clearance/authorizations/<aid>/appeal")
def appeal_authorization(aid):
    authenticate(["UtilizationReviewer"])
    auth = get_auth_or_404(aid)
    if auth["status"] != "DENIED":
        raise invalid_state("only a DENIED authorization can be appealed")
    auth["status"] = "APPEALED"
    touch(auth)
    return ok_object(serialize(auth))
