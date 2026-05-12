"""Judicial package routes."""
from flask import Blueprint, g

import db
from clock import now, parse_iso
from errors import err
from middleware import require_auth
from response import success
from services import lifecycle
from services.lookup import (
    certificate_for_evidence, get_evidence, get_judicial_package,
    notarization_for_evidence,
)
from services.validation import get_body, maybe_check_version, require_enum, require_str


bp = Blueprint("judicial", __name__)

VALID_AUTHORITIES = {
    "COURT_BJ", "COURT_SH", "COURT_GZ", "COURT_SZ", "PROCURATORATE", "ARBITRATION",
}


def _public(p: dict) -> dict:
    return {
        "id": p["id"],
        "evidence_id": p["evidence_id"],
        "case_number": p["case_number"],
        "party_info": p["party_info"],
        "authority_code": p["authority_code"],
        "include_original_data": p["include_original_data"],
        "status": p["status"],
        "official_seal_id": p.get("official_seal_id"),
        "delivered_at": p.get("delivered_at"),
        "surcharge_cents": p.get("surcharge_cents"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/judicial-packages", methods=["POST"])
@require_auth(roles={"JudicialOfficer"})
def create_pkg():
    body = get_body()
    evidence_id = require_str(body, "evidence_id")
    case_number = require_str(body, "case_number", max_len=64)
    party_info = body.get("party_info")
    authority_code = require_enum(body, "authority_code", VALID_AUTHORITIES)
    include_original_data = bool(body.get("include_original_data", False))

    if not isinstance(party_info, dict):
        raise err("ERR_VALIDATION_FAILED", "party_info must be a JSON object")

    ev = get_evidence(evidence_id)

    # Priority 15: Evidence expiry blocks prep
    if ev.get("expires_at"):
        try:
            exp_dt = parse_iso(ev["expires_at"])
            if now() >= exp_dt:
                raise err("ERR_EVIDENCE_EXPIRED",
                          "Evidence has expired; cannot prepare judicial package")
        except ValueError:
            pass
    if ev["status"] == "EXPIRED":
        raise err("ERR_EVIDENCE_EXPIRED",
                  "Evidence is EXPIRED; cannot prepare judicial package")

    pkg = {
        "evidence_id": evidence_id,
        "case_number": case_number,
        "party_info": party_info,
        "authority_code": authority_code,
        "include_original_data": include_original_data,
        "status": "DRAFT",
        "official_seal_id": None,
        "delivered_at": None,
        "surcharge_cents": None,
    }
    db.stamp_create(pkg, common_fields=True)
    db.judicial_packages[pkg["id"]] = pkg
    return success(_public(pkg), 201)


@bp.route("/judicial-packages/<p_id>", methods=["GET"])
@require_auth(roles={"JudicialOfficer", "PlatformAdmin"})
def read_pkg(p_id):
    pkg = get_judicial_package(p_id)
    return success(_public(pkg), 200)


@bp.route("/judicial-packages/<p_id>/seal", methods=["POST"])
@require_auth(roles={"JudicialOfficer"})
def seal_pkg(p_id):
    body = get_body()
    pkg = get_judicial_package(p_id)
    maybe_check_version(body, pkg)
    lifecycle.judicial_seal(pkg)
    return success(_public(pkg), 200)


@bp.route("/judicial-packages/<p_id>/deliver", methods=["POST"])
@require_auth(roles={"JudicialOfficer"})
def deliver_pkg(p_id):
    body = get_body()
    pkg = get_judicial_package(p_id)
    maybe_check_version(body, pkg)
    lifecycle.judicial_deliver(pkg)
    return success(_public(pkg), 200)
