"""TimestampNotarization routes."""
from flask import Blueprint, g

import db
from clock import iso, now
from errors import err
from middleware import require_auth
from response import success
from services.lookup import get_evidence, get_notarization
from services.validation import get_body, require_enum, require_str


bp = Blueprint("notarizations", __name__)

VALID_PROVIDERS = {"RFC3161_TSA_A", "RFC3161_TSA_B", "NOTARY_OFFICE"}


def _public(n: dict) -> dict:
    return {
        "id": n["id"],
        "evidence_id": n["evidence_id"],
        "tsa_provider": n["tsa_provider"],
        "notary_office_id": n.get("notary_office_id"),
        "trusted_time": n.get("trusted_time"),
        "tsa_token": n.get("tsa_token"),
        "created_at": n["created_at"],
    }


def _can_read(n: dict) -> bool:
    if g.user_role in ("PlatformAdmin", "JudicialOfficer", "NotaryOfficer"):
        return True
    if g.user_role == "Customer":
        ev = db.evidences.get(n["evidence_id"])
        return ev is not None and ev["customer_id"] == g.user_id
    return False


@bp.route("/timestamp-notarizations", methods=["POST"])
@require_auth(roles={"Customer", "NotaryOfficer"})
def create_notarization():
    body = get_body()
    evidence_id = require_str(body, "evidence_id")
    tsa_provider = require_enum(body, "tsa_provider", VALID_PROVIDERS)
    notary_office_id = body.get("notary_office_id")

    ev = get_evidence(evidence_id)

    if g.user_role == "Customer" and g.user_id != ev["customer_id"]:
        raise err("ERR_PERMISSION_DENIED",
                  "Customer X-User-ID does not match evidence's customer_id")

    if tsa_provider == "NOTARY_OFFICE":
        if not isinstance(notary_office_id, str) or not notary_office_id:
            raise err("ERR_VALIDATION_FAILED",
                      "notary_office_id is required when tsa_provider is NOTARY_OFFICE")
    else:
        if notary_office_id is not None:
            raise err("ERR_VALIDATION_FAILED",
                      "notary_office_id must be null when tsa_provider is not NOTARY_OFFICE")

    # Uniqueness on evidence_id
    for existing in db.timestamp_notarizations.values():
        if existing["evidence_id"] == evidence_id:
            raise err("ERR_INVALID_STATE",
                      "TimestampNotarization already exists for this evidence")

    n = {
        "evidence_id": evidence_id,
        "tsa_provider": tsa_provider,
        "notary_office_id": notary_office_id,
        "trusted_time": iso(now()),
        "tsa_token": "tsatok_" + ev["file_hash"][:16],
    }
    db.stamp_create(n, common_fields=False)
    db.timestamp_notarizations[n["id"]] = n
    return success(_public(n), 201)


@bp.route("/timestamp-notarizations/<n_id>", methods=["GET"])
@require_auth(roles={"Customer", "NotaryOfficer", "JudicialOfficer", "PlatformAdmin"})
def read_notarization(n_id):
    n = get_notarization(n_id)
    if not _can_read(n):
        raise err("ERR_PERMISSION_DENIED", "Cannot read this notarization")
    return success(_public(n), 200)


@bp.route("/timestamp-notarizations/<n_id>/verify", methods=["POST"])
@require_auth(roles={"Customer", "JudicialOfficer", "PlatformAdmin"})
def verify_notarization(n_id):
    n = get_notarization(n_id)
    if g.user_role == "Customer":
        ev = db.evidences.get(n["evidence_id"])
        if ev is None or ev["customer_id"] != g.user_id:
            raise err("ERR_PERMISSION_DENIED", "Cannot verify this notarization")
    return success(_public(n), 200)
