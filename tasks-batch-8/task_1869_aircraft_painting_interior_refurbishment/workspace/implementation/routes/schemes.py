"""PaintScheme endpoints (cyclic DRAFT->SUBMITTED->APPROVED/REJECTED->DRAFT)."""
from flask import Blueprint, request

from db import STORE
from domain import (new_entity, bump, bump_program, get_or_404, by_created,
                    serialize_scheme)
from errors import (ApiError, ref_integrity, invalid_state,
                    ERR_FORBIDDEN_OWNERSHIP, ERR_STALE_PROGRAM_VERSION,
                    ERR_SCHEME_PHASE_TOO_ADVANCED)
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("schemes", __name__)

APPROVABLE_PHASES = ("QUOTED", "BOOKED", "INDUCTED", "SURFACE_REVIEW")


def _ownership_check(user_id, prog):
    if user_id != prog["customer_id"]:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "X-User-ID does not match the program's customer_id")


@bp.post("/paint-schemes")
def create_scheme():
    auth("DesignLead")
    data = get_body(required=True)
    program_id = field(data, "program_id", "str")
    drawing_ref = field(data, "drawing_ref", "str")
    painted_area_sqft = field(data, "painted_area_sqft", "int")
    coat_count = field(data, "coat_count", "int")
    stripe_pct = field(data, "stripe_pct", "num", required=False, default=0)
    if stripe_pct < 0 or stripe_pct > 1:
        from errors import bad_request
        raise bad_request("stripe_pct must be within 0..1")
    if program_id not in STORE.programs:
        raise ref_integrity("program_id does not reference an existing program")
    scheme = new_entity()
    scheme.update({
        "program_id": program_id,
        "drawing_ref": drawing_ref,
        "painted_area_sqft": painted_area_sqft,
        "coat_count": coat_count,
        "stripe_pct": stripe_pct,
        "status": "DRAFT",
        "superseded_by_id": None,
    })
    STORE.paint_schemes[scheme["id"]] = scheme
    return success(serialize_scheme(scheme), status=201)


@bp.get("/paint-schemes/<sid>")
def get_scheme(sid):
    auth()
    scheme = get_or_404(STORE.paint_schemes, sid, "PaintScheme")
    return success(serialize_scheme(scheme))


@bp.get("/paint-schemes")
def list_schemes():
    auth()
    items = by_created(list(STORE.paint_schemes.values()))
    for key in ("program_id", "superseded_by_id", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [s for s in items if s[key] == value]
    return paginate(items, serialize_scheme)


@bp.post("/paint-schemes/<sid>/submit")
def submit_scheme(sid):
    auth("DesignLead")
    scheme = get_or_404(STORE.paint_schemes, sid, "PaintScheme")
    if scheme["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT scheme can be submitted")
    scheme["status"] = "SUBMITTED"
    bump(scheme)
    return success(serialize_scheme(scheme))


@bp.post("/paint-schemes/<sid>/approve")
def approve_scheme(sid):
    user_id, _ = auth("CustomerRep")
    data = get_body(required=True)
    expected = field(data, "expected_program_version", "int")
    scheme = get_or_404(STORE.paint_schemes, sid, "PaintScheme")
    prog = STORE.programs[scheme["program_id"]]
    _ownership_check(user_id, prog)
    if expected != prog["version"]:
        raise ApiError(ERR_STALE_PROGRAM_VERSION, 412,
                       "expected_program_version does not match the program version")
    if scheme["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED scheme can be approved")
    if prog["status"] not in APPROVABLE_PHASES:
        raise ApiError(ERR_SCHEME_PHASE_TOO_ADVANCED, 409,
                       "Scheme approval is only possible through SURFACE_REVIEW")
    # Supersede the previously approved scheme (compensating pair).
    for other in STORE.paint_schemes.values():
        if (other["program_id"] == prog["id"] and other["status"] == "APPROVED"
                and other["id"] != scheme["id"]):
            other["status"] = "SUPERSEDED"
            other["superseded_by_id"] = scheme["id"]
            bump(other)
    scheme["status"] = "APPROVED"
    bump(scheme)
    prog["approved_scheme_id"] = scheme["id"]
    bump_program(prog)
    return success(serialize_scheme(scheme))


@bp.post("/paint-schemes/<sid>/reject")
def reject_scheme(sid):
    user_id, _ = auth("CustomerRep")
    scheme = get_or_404(STORE.paint_schemes, sid, "PaintScheme")
    prog = STORE.programs[scheme["program_id"]]
    _ownership_check(user_id, prog)
    if scheme["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED scheme can be rejected")
    scheme["status"] = "REJECTED"
    bump(scheme)
    return success(serialize_scheme(scheme))


@bp.post("/paint-schemes/<sid>/revise")
def revise_scheme(sid):
    auth("DesignLead")
    scheme = get_or_404(STORE.paint_schemes, sid, "PaintScheme")
    if scheme["status"] != "REJECTED":
        raise invalid_state("Only a REJECTED scheme can be revised")
    scheme["status"] = "DRAFT"
    bump(scheme)
    return success(serialize_scheme(scheme))
