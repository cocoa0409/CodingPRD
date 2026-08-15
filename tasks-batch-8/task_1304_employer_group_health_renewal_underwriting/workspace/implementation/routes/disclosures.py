"""Commission disclosure endpoints (PRD 3.9)."""
from flask import Blueprint

from db import store, touch, now_iso
from errors import (
    ApiError, not_found,
    ERR_DISCLOSURE_NOT_PENDING, ERR_DISCLOSURE_NOT_DISCLOSED,
    ERR_DISCLOSURE_NOT_REQUIRED, ERR_NOT_BROKER_OF_RECORD,
)
from middleware import auth
from response import ok, paginated, sorted_items
from serializers import disclosure_json

bp = Blueprint("disclosures", __name__)

READ_ROLES = ["Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"]


def get_disclosure_or_404(disc_id):
    disc = store.disclosures.get(disc_id)
    if disc is None:
        raise not_found("Commission disclosure does not exist")
    return disc


@bp.get("/underwriting-cases/<caseId>/commission-disclosures")
def list_disclosures(caseId):
    auth(READ_ROLES)
    if caseId not in store.cases:
        raise not_found("Underwriting case does not exist")
    items = [d for d in store.disclosures.values() if d["case_id"] == caseId]
    return paginated([disclosure_json(d) for d in sorted_items(items)])


@bp.get("/commission-disclosures/<discId>")
def get_disclosure(discId):
    auth(READ_ROLES)
    return ok(disclosure_json(get_disclosure_or_404(discId)))


@bp.post("/commission-disclosures/<discId>/disclose")
def disclose(discId):
    auth(["Underwriter"])
    disc = get_disclosure_or_404(discId)
    if disc["status"] != "PENDING":
        raise ApiError(ERR_DISCLOSURE_NOT_PENDING,
                       "Commission disclosure must be in PENDING status", 409)
    if not disc["requires_disclosure"]:
        raise ApiError(ERR_DISCLOSURE_NOT_REQUIRED,
                       "Commission disclosure is not required (below threshold)", 409)
    disc["status"] = "DISCLOSED"
    disc["disclosed_at"] = now_iso()
    touch(disc)
    return ok(disclosure_json(disc))


@bp.post("/commission-disclosures/<discId>/acknowledge")
def acknowledge(discId):
    uid, _ = auth(["Broker"])
    disc = get_disclosure_or_404(discId)
    if disc["status"] != "DISCLOSED":
        raise ApiError(ERR_DISCLOSURE_NOT_DISCLOSED,
                       "Commission disclosure must be in DISCLOSED status", 409)
    if disc["broker_id"] != uid:
        raise ApiError(ERR_NOT_BROKER_OF_RECORD,
                       "Acting broker is not the broker of record on this case", 403)
    disc["status"] = "ACKNOWLEDGED"
    touch(disc)
    return ok(disclosure_json(disc))
