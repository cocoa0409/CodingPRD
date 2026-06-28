"""Therapists & certifications (PRD §3.1)."""
import re

from flask import Blueprint

import clock
import db
import helpers as h
import response
import util
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import authenticate, require_role

bp = Blueprint("therapists", __name__)

LICENSE_RE = re.compile(r"^LMT-\d{6}$")


def license_status(therapist):
    """ACTIVE while license_expiry strictly after clock; else LICENSE_EXPIRED."""
    expiry = util.parse_iso(therapist["license_expiry"])
    if expiry > clock.now():
        return "ACTIVE"
    return "LICENSE_EXPIRED"


def cert_status(cert):
    """ACTIVE while clock strictly before cert_expiry; else EXPIRED."""
    expiry = util.parse_iso(cert["cert_expiry"])
    if clock.now() < expiry:
        return "ACTIVE"
    return "EXPIRED"


def serialize_therapist(t):
    out = h.public(t)
    out["license_status"] = license_status(t)
    return out


def serialize_cert(c):
    out = h.public(c)
    out["cert_status"] = cert_status(c)
    return out


@bp.post("/practice/therapists")
def create_therapist():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    body = h.get_body()

    full_name = h.as_str(h.require(body, "full_name"), "full_name")
    license_number = h.as_str(h.require(body, "license_number"), "license_number")
    if not LICENSE_RE.match(license_number):
        raise ApiError(*ERR_INVALID_REQUEST, message="license_number must match LMT-NNNNNN")
    license_expiry = util.parse_iso(h.require(body, "license_expiry"))

    commission_scheme = h.opt(body, "commission_scheme", "TIERED")
    h.enum(commission_scheme, "commission_scheme", {"FLAT", "TIERED"})
    flat_commission_pct = h.opt(body, "flat_commission_pct", None)
    if flat_commission_pct is None:
        flat_frac = h.as_fraction_pct(0.40, "flat_commission_pct")
    else:
        flat_frac = h.as_fraction_pct(flat_commission_pct, "flat_commission_pct")

    # license_number unique across all therapists
    for t in db.therapists.values():
        if t["license_number"] == license_number:
            raise ApiError(*ERR_INVALID_REQUEST, message="license_number not unique")

    ent = h.new_entity({
        "full_name": full_name,
        "license_number": license_number,
        "license_expiry": util.iso_format(license_expiry),
        "commission_scheme": commission_scheme,
        "flat_commission_pct": float(flat_frac),
        "mtd_service_revenue_cents": 0,
        "accrued_commission_cents": 0,
    })
    # keep exact fraction for computations
    ent["_flat_frac"] = flat_frac
    db.therapists[ent["id"]] = ent
    return response.success(serialize_therapist(ent), status=201)


@bp.get("/practice/therapists")
def list_therapists():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk"})
    limit, offset = h.get_pagination()
    items = list(db.therapists.values())
    page, total = h.paginate(items, limit, offset)
    return response.list_success([serialize_therapist(t) for t in page], limit, offset, total)


@bp.get("/practice/therapists/<id>")
def get_therapist(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Therapist"})
    ent = h.resolve(db.therapists, id)
    return response.success(serialize_therapist(ent))


@bp.post("/practice/therapists/<id>/reset-commission")
def reset_commission(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    ent = h.resolve(db.therapists, id)
    ent["mtd_service_revenue_cents"] = 0
    ent["accrued_commission_cents"] = 0
    h.touch(ent)
    return response.success(serialize_therapist(ent))


# --- Certifications ---

@bp.post("/practice/certifications")
def create_certification():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    body = h.get_body()

    therapist_id = h.as_str(h.require(body, "therapist_id"), "therapist_id")
    h.resolve(db.therapists, therapist_id)
    modality_code = h.as_str(h.require(body, "modality_code"), "modality_code")
    cert_expiry = util.parse_iso(h.require(body, "cert_expiry"))

    # modality_code must equal the code of a non-archived modality
    match = None
    for m in db.modalities.values():
        if m["code"] == modality_code and not m["archived"]:
            match = m
            break
    if match is None:
        raise ApiError(*ERR_INVALID_REQUEST, message="modality_code not found among non-archived modalities")

    ent = h.new_entity({
        "therapist_id": therapist_id,
        "modality_code": modality_code,
        "cert_expiry": util.iso_format(cert_expiry),
    })
    db.certifications[ent["id"]] = ent
    return response.success(serialize_cert(ent), status=201)


@bp.get("/practice/certifications")
def list_certifications():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk"})
    limit, offset = h.get_pagination()
    from flask import request
    therapist_id = request.args.get("therapist_id")
    items = list(db.certifications.values())
    if therapist_id is not None:
        items = [c for c in items if c["therapist_id"] == therapist_id]
    page, total = h.paginate(items, limit, offset)
    return response.list_success([serialize_cert(c) for c in page], limit, offset, total)


@bp.get("/practice/certifications/<id>")
def get_certification(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk"})
    ent = h.resolve(db.certifications, id)
    return response.success(serialize_cert(ent))
