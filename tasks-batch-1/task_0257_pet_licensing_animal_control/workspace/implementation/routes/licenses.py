"""License endpoints (PRD §3.2-§3.5, §4)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import authenticate, require_owner_match, require_role
from response import array_response, object_response
from services import license as lic_svc
from services.core import stamp_create
from services.reqs import (body, paginate, parse_pagination, require_enum,
                          require_fields)
from services.views import license_view, tag_view

bp = Blueprint("licenses", __name__)

ALL_ROLES = {"Owner", "LicensingClerk", "AnimalControlOfficer"}
KINDS = {"INDIVIDUAL", "KENNEL"}
TERMS = {1, 3}


@bp.route("/licenses", methods=["POST"])
def create_license():
    _, role = authenticate()
    require_role(role, {"Owner", "LicensingClerk"})
    data = body()
    require_fields(data, ["owner_id", "pet_id", "license_kind", "term_years"])
    require_enum(data["license_kind"], KINDS, "license_kind")
    term = data["term_years"]
    if isinstance(term, bool) or term not in TERMS:
        raise err("ERR_INVALID_REQUEST", "term_years must be 1 or 3.")
    kennel_id = data.get("kennel_id")

    # existence: owner, pet, kennel (when supplied), left to right
    if db.owners.get(data["owner_id"]) is None:
        raise err("ERR_NOT_FOUND", "Owner not found.")
    if db.pets.get(data["pet_id"]) is None:
        raise err("ERR_NOT_FOUND", "Pet not found.")
    if kennel_id is not None and db.kennels.get(kennel_id) is None:
        raise err("ERR_NOT_FOUND", "Kennel not found.")

    # license-kind coherence at creation (PRD §3.2 — same rule as at submit)
    if data["license_kind"] == "INDIVIDUAL":
        if kennel_id is not None:
            raise err("ERR_LICENSE_KIND_MISMATCH", "INDIVIDUAL requires kennel_id null.")
    else:  # KENNEL
        if kennel_id is None:
            raise err("ERR_LICENSE_KIND_MISMATCH", "KENNEL requires kennel_id set.")
        kennel = db.kennels.get(kennel_id)
        if kennel["status"] != "OPEN":
            raise err("ERR_LICENSE_KIND_MISMATCH", "KENNEL requires an OPEN kennel.")

    license_rec = {
        "owner_id": data["owner_id"],
        "pet_id": data["pet_id"],
        "kennel_id": kennel_id,
        "license_kind": data["license_kind"],
        "term_years": term,
        "vaccination_record_id": None,
        "status": "DRAFT",
        "provisional_fee_cents": 0,
        "final_fee_cents": 0,
        "late_penalty_cents": 0,
        "penalty_paid": False,
        "issued_on": None,
        "expires_on": None,
        "tag_serial": None,
    }
    stamp_create(license_rec)
    db.licenses[license_rec["id"]] = license_rec
    return object_response(license_view(license_rec), status=201)


@bp.route("/licenses/<license_id>", methods=["GET"])
def get_license(license_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    lic = db.licenses.get(license_id)
    if lic is None:
        raise err("ERR_NOT_FOUND", "License not found.")
    return object_response(license_view(lic))


@bp.route("/licenses", methods=["GET"])
def list_licenses():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.licenses.values())
    for field in ("owner_id", "pet_id", "kennel_id", "vaccination_record_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [l for l in items if l.get(field) == val]
    page, total = paginate(items, limit, offset)
    return array_response([license_view(l) for l in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# transition helpers
# --------------------------------------------------------------------------- #
def _load(license_id):
    lic = db.licenses.get(license_id)
    if lic is None:
        raise err("ERR_NOT_FOUND", "License not found.")
    return lic


@bp.route("/licenses/<license_id>/submit", methods=["POST"])
def submit(license_id):
    user_id, role = authenticate()
    require_role(role, {"Owner"})
    lic = _load(license_id)
    require_owner_match(role, user_id, lic["owner_id"])
    lic_svc.submit(lic)
    return object_response(license_view(lic))


@bp.route("/licenses/<license_id>/start-review", methods=["POST"])
def start_review(license_id):
    _, role = authenticate()
    require_role(role, {"LicensingClerk"})
    lic = _load(license_id)
    lic_svc.start_review(lic)
    return object_response(license_view(lic))


@bp.route("/licenses/<license_id>/request-vaccination-proof", methods=["POST"])
def request_vaccination_proof(license_id):
    _, role = authenticate()
    require_role(role, {"LicensingClerk"})
    lic = _load(license_id)
    lic_svc.request_vaccination_proof(lic)
    return object_response(license_view(lic))


@bp.route("/licenses/<license_id>/attach-vaccination", methods=["POST"])
def attach_vaccination(license_id):
    user_id, role = authenticate()
    require_role(role, {"Owner"})
    lic = _load(license_id)
    require_owner_match(role, user_id, lic["owner_id"])
    data = body()
    require_fields(data, ["vaccination_record_id"])
    lic_svc.attach_vaccination(lic, data["vaccination_record_id"])
    return object_response(license_view(lic))


@bp.route("/licenses/<license_id>/approve", methods=["POST"])
def approve(license_id):
    _, role = authenticate()
    require_role(role, {"LicensingClerk"})
    lic = _load(license_id)
    lic_svc.approve(lic)
    return object_response(license_view(lic))


@bp.route("/licenses/<license_id>/reject", methods=["POST"])
def reject(license_id):
    _, role = authenticate()
    require_role(role, {"LicensingClerk"})
    lic = _load(license_id)
    lic_svc.reject(lic)
    return object_response(license_view(lic))


@bp.route("/licenses/<license_id>/issue-tag", methods=["POST"])
def issue_tag(license_id):
    _, role = authenticate()
    require_role(role, {"LicensingClerk"})
    lic = _load(license_id)
    lic_svc.issue_tag(lic)
    return object_response(license_view(lic))


@bp.route("/licenses/<license_id>/renew", methods=["POST"])
def renew(license_id):
    user_id, role = authenticate()
    require_role(role, {"Owner"})
    lic = _load(license_id)
    require_owner_match(role, user_id, lic["owner_id"])
    data = body()
    pay = data.get("pay_penalty_cents")
    lic_svc.renew(lic, pay)
    return object_response(license_view(lic))


@bp.route("/licenses/<license_id>/pay-penalty", methods=["POST"])
def pay_penalty(license_id):
    user_id, role = authenticate()
    require_role(role, {"Owner"})
    lic = _load(license_id)
    require_owner_match(role, user_id, lic["owner_id"])
    data = body()
    require_fields(data, ["pay_penalty_cents"])
    lic_svc.pay_penalty(lic, data["pay_penalty_cents"])
    return object_response(license_view(lic))


@bp.route("/licenses/<license_id>/revoke", methods=["POST"])
def revoke(license_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    lic = _load(license_id)
    lic_svc.revoke(lic)
    return object_response(license_view(lic))


@bp.route("/licenses/<license_id>/tags", methods=["GET"])
def list_tags(license_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.licenses.get(license_id) is None:
        raise err("ERR_NOT_FOUND", "License not found.")
    limit, offset = parse_pagination()
    items = [t for t in db.tags.values() if t["license_id"] == license_id]
    page, total = paginate(items, limit, offset)
    return array_response([tag_view(t) for t in page], limit, offset, total)
