"""Routes: GoodStandingCertificate request/issue/deny."""
from datetime import timedelta

from flask import Blueprint, request

import store
import services as svc
from errors import (
    ERR_INVALID_REQUEST, ERR_JURISDICTION_NOT_FOUND, ERR_CERTIFICATE_NOT_FOUND,
    ERR_ENTITY_ALREADY_DISSOLVED, ERR_POSTURE_NOT_GOOD_STANDING,
    ERR_CERTIFICATE_NOT_REQUESTED,
    raise_err,
)
from middleware import require_roles, get_body, ALL_ROLES
from response import ok_object, paginate, sort_records
from routes_entities import get_entity_or_404

bp = Blueprint("certificates", __name__)

CS = ["CorporateSecretary"]


@bp.route("/api/entities/<entityId>/certificate-requests", methods=["POST"])
def request_certificate(entityId):
    require_roles(CS)
    entity = get_entity_or_404(entityId)
    body = get_body()
    # Priority 3: body FK existence
    jurisdiction_id = body.get("jurisdiction_id")
    if jurisdiction_id is not None and jurisdiction_id not in store.jurisdictions:
        raise_err(ERR_JURISDICTION_NOT_FOUND)
    # Priority 4: schema
    if jurisdiction_id is None:
        raise_err(ERR_INVALID_REQUEST, "jurisdiction_id is required")
    speed = body.get("delivery_speed")
    if speed not in ("STANDARD", "EXPEDITED"):
        raise_err(ERR_INVALID_REQUEST, "delivery_speed is invalid")
    # Priority 5: parent not DISSOLVED
    if entity["status"] == "DISSOLVED":
        raise_err(ERR_ENTITY_ALREADY_DISSOLVED)
    # Priority 6: posture gate (freshly computed)
    svc.lazy_eval_entity(entity, auto_deny=False)
    if entity["compliance_posture"] != "GOOD_STANDING":
        raise_err(ERR_POSTURE_NOT_GOOD_STANDING,
                  "Entity compliance posture is not GOOD_STANDING")
    jurisdiction = store.jurisdictions[jurisdiction_id]
    rec = store.new_record()
    rec.update({
        "entity_id": entity["id"],
        "jurisdiction_id": jurisdiction_id,
        "delivery_speed": speed,
        "fee_cents": svc.calc_cert_fee(jurisdiction, speed),
        "requested_date": svc.fmt_date(store.today()),
        "issued_date": None,
        "valid_until": None,
        "denial_reason": None,
        "status": "REQUESTED",
    })
    store.certificates[rec["id"]] = rec
    return ok_object(svc.serialize(rec), 201)


@bp.route("/api/certificates", methods=["GET"])
def list_certificates():
    require_roles(ALL_ROLES)
    for c in list(store.certificates.values()):
        svc.apply_cert_expiry(c)
    records = sort_records(list(store.certificates.values()))
    for param, field in (("entity_id", "entity_id"), ("jurisdiction_id", "jurisdiction_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return paginate([svc.serialize(r) for r in records], request.args)


def get_cert_or_404(certificateId):
    rec = store.certificates.get(certificateId)
    if rec is None:
        raise_err(ERR_CERTIFICATE_NOT_FOUND)
    return rec


@bp.route("/api/certificates/<certificateId>", methods=["GET"])
def get_certificate(certificateId):
    require_roles(ALL_ROLES)
    rec = get_cert_or_404(certificateId)
    svc.apply_cert_expiry(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/certificates/<certificateId>/issue", methods=["POST"])
def issue_certificate(certificateId):
    require_roles(CS)
    rec = get_cert_or_404(certificateId)
    get_body()
    svc.apply_cert_expiry(rec)
    if rec["status"] != "REQUESTED":
        raise_err(ERR_CERTIFICATE_NOT_REQUESTED, "issue requires status == REQUESTED")
    entity = store.entities[rec["entity_id"]]
    svc.recompute_posture(entity, auto_deny=False)
    if entity["compliance_posture"] != "GOOD_STANDING":
        raise_err(ERR_POSTURE_NOT_GOOD_STANDING,
                  "Entity compliance posture is not GOOD_STANDING")
    today = store.today()
    rec["status"] = "ISSUED"
    rec["issued_date"] = svc.fmt_date(today)
    rec["valid_until"] = svc.fmt_date(today + timedelta(days=svc.CERT_VALID_DAYS))
    store.touch(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/certificates/<certificateId>/deny", methods=["POST"])
def deny_certificate(certificateId):
    require_roles(CS)
    rec = get_cert_or_404(certificateId)
    body = get_body()
    svc.apply_cert_expiry(rec)
    if rec["status"] != "REQUESTED":
        raise_err(ERR_CERTIFICATE_NOT_REQUESTED, "deny requires status == REQUESTED")
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise_err(ERR_INVALID_REQUEST, "reason is required")
    rec["status"] = "DENIED"
    rec["denial_reason"] = reason
    store.touch(rec)
    svc.append_event(rec["entity_id"], "CERTIFICATE_DENIED",
                     {"certificate_id": rec["id"]})
    return ok_object(svc.serialize(rec))
