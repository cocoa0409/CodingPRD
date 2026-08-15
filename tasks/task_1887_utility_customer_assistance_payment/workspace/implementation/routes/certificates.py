"""MedicalCertificate endpoints (PRD §3.6, calc: certificate_window_arithmetic)."""

from flask import Blueprint

import db
from errors import (not_found, ApiError, ERR_INVALID_STATE,
                    ERR_CERTIFICATE_NOT_RENEWABLE, ERR_RENEWAL_LIMIT_REACHED,
                    ERR_CERTIFICATE_WINDOW_OVERLAP)
from middleware import authenticate, check_ownership
from response import success_object, success_list
from serializers import certificate as ser_cert
from services.common import touch_account
from services.protection import recompute as protection_recompute
from validate import (get_body, validate_shape, parse_pagination, parse_filters,
                      paginate, sort_by_creation)

bp = Blueprint("certificates", __name__)

CONDITION_CLASSES = {"LIFE_THREATENING", "SERIOUS"}
CERT_STATUSES = {"ACTIVE", "EXPIRED", "REVOKED"}
CERT_WINDOW_DAYS = 30
MAX_RENEWALS = 2
GET_ROLES = ["Customer", "CustomerServiceRep", "ProgramAdmin"]
LIST_ROLES = ["CustomerServiceRep", "ProgramAdmin"]


def get_cert_or_404(certificate_id):
    c = db.certificates.get(certificate_id)
    if c is None:
        raise not_found("Medical certificate not found")
    return c


def _gate_and_maybe_bump(account):
    """Protection-gate recompute after a certificate event; the account bumps
    only when the recomputation actually changed protection_status (§2.10)."""
    if protection_recompute(account):
        touch_account(account)


@bp.route("/assistance/medical-certificates", methods=["POST"])
def create_certificate():
    authenticate(["CustomerServiceRep"])
    body = validate_shape(get_body(allow_empty=False), [
        ("account_id", "string", True, None),
        ("physician_name", "string", True, None),
        ("physician_license_number", "string", True, None),
        ("condition_class", "enum", True, CONDITION_CLASSES),
        ("effective_from", "datetime", True, None),
    ])
    account = db.accounts.get(body["account_id"])
    if account is None:
        raise not_found("Account not found")
    new_from = db.parse_datetime(body["effective_from"]).date()
    new_to = db.add_days(new_from, CERT_WINDOW_DAYS)
    for c in db.certificates.values():
        if c["account_id"] != account["id"] or c["status"] != "ACTIVE":
            continue
        # half-open overlap: new.from < existing.to AND existing.from < new.to
        if new_from < c["effective_to"] and c["effective_from"] < new_to:
            raise ApiError(ERR_CERTIFICATE_WINDOW_OVERLAP, 422,
                           "Window overlaps an existing ACTIVE certificate")
    cert = {
        "id": db.new_id(),
        "account_id": account["id"],
        "physician_name": body["physician_name"],
        "physician_license_number": body["physician_license_number"],
        "condition_class": body["condition_class"],
        "effective_from": new_from,
        "effective_to": new_to,
        "renewal_count": 0,
        "status": "ACTIVE",
    }
    db.stamp_common(cert)
    db.certificates[cert["id"]] = cert
    _gate_and_maybe_bump(account)
    return success_object(ser_cert(cert), status=201)


@bp.route("/assistance/medical-certificates/<certificate_id>", methods=["GET"])
def get_certificate(certificate_id):
    actor = authenticate(GET_ROLES)
    c = db.certificates.get(certificate_id)
    if c is not None:
        check_ownership(actor, c["account_id"])
    if c is None:
        raise not_found("Medical certificate not found")
    return success_object(ser_cert(c))


@bp.route("/assistance/medical-certificates", methods=["GET"])
def list_certificates():
    authenticate(LIST_ROLES)
    limit, offset = parse_pagination()
    filters = parse_filters({"account_id": "str", "status": CERT_STATUSES})
    items = sort_by_creation(db.certificates.values())
    if "account_id" in filters:
        items = [x for x in items if x["account_id"] == filters["account_id"]]
    if "status" in filters:
        items = [x for x in items if x["status"] == filters["status"]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_cert(x) for x in page], limit, offset, total)


@bp.route("/assistance/medical-certificates/<certificate_id>/renew", methods=["POST"])
def renew(certificate_id):
    authenticate(["CustomerServiceRep"])
    c = get_cert_or_404(certificate_id)
    # state check precedes the renewal-limit check (PRD §3.6)
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_CERTIFICATE_NOT_RENEWABLE, 409,
                       "Renew requires certificate status ACTIVE")
    if c["renewal_count"] >= MAX_RENEWALS:
        raise ApiError(ERR_RENEWAL_LIMIT_REACHED, 422,
                       "Certificate has already been renewed twice")
    c["effective_to"] = db.add_days(c["effective_to"], CERT_WINDOW_DAYS)
    c["renewal_count"] += 1
    db.touch(c)
    account = db.accounts.get(c["account_id"])
    if account is not None:
        _gate_and_maybe_bump(account)
    return success_object(ser_cert(c))


@bp.route("/assistance/medical-certificates/<certificate_id>/revoke", methods=["POST"])
def revoke(certificate_id):
    authenticate(["ProgramAdmin"])
    c = get_cert_or_404(certificate_id)
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Revoke requires certificate status ACTIVE")
    c["status"] = "REVOKED"
    db.touch(c)
    account = db.accounts.get(c["account_id"])
    if account is not None:
        _gate_and_maybe_bump(account)
    return success_object(ser_cert(c))
