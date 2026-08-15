"""ClassCertificate endpoints."""

from flask import Blueprint, request

import db
import errors
import util
from middleware import require_roles
from response import success_object, success_list, now_iso
from services import domain

bp = Blueprint("class_certificates", __name__)

READ_ROLES = ("LoftManager", "Sailmaker", "Measurer", "Rigger", "Customer")
CERT_CLASSES = ("J70", "J105", "TP52", "ORC", "PHRF")


@bp.post("/lofts/boats/<boatId>/class-certificates")
def create_cert(boatId):
    require_roles("Measurer")
    boat = domain.get_boat_or_404(boatId)
    body = util.get_body()
    measurement_sheet_id = util.as_string(util.require_field(body, "measurement_sheet_id"), "measurement_sheet_id")
    racing_class = util.as_enum(util.require_field(body, "racing_class"), "racing_class", CERT_CLASSES)
    sheet = db.measurement_sheets.get(measurement_sheet_id)
    if (
        boat["racing_class"] == "NONE"
        or racing_class != boat["racing_class"]
        or sheet is None
        or sheet["sheet_status"] != "FROZEN"
    ):
        raise errors.class_mismatch()
    cert = util.stamp_new({
        "boat_id": boat["id"],
        "measurement_sheet_id": measurement_sheet_id,
        "racing_class": racing_class,
        "issued_at": now_iso(),
        "cert_status": "ACTIVE",
    })
    db.class_certificates[cert["id"]] = cert
    return success_object(domain.serialize(cert), 201)


@bp.get("/lofts/boats/<boatId>/class-certificates")
def list_boat_certs(boatId):
    require_roles(*READ_ROLES)
    domain.get_boat_or_404(boatId)
    limit, offset = util.pagination_params()
    items = [c for c in db.class_certificates.values() if c["boat_id"] == boatId]
    items = util.filter_exact(items, "cert_status", request.args.get("cert_status"))
    items = util.sort_by_created(items)
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(c) for c in page], limit, offset, total)


@bp.get("/lofts/class-certificates")
def list_certs():
    require_roles(*READ_ROLES)
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.class_certificates.values()))
    items = util.filter_exact(items, "boat_id", request.args.get("boat_id"))
    items = util.filter_exact(items, "measurement_sheet_id", request.args.get("measurement_sheet_id"))
    items = util.filter_exact(items, "cert_status", request.args.get("cert_status"))
    items = util.filter_exact(items, "racing_class", request.args.get("racing_class"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(c) for c in page], limit, offset, total)


@bp.get("/lofts/class-certificates/<certId>")
def get_cert(certId):
    require_roles(*READ_ROLES)
    cert = domain.get_cert_or_404(certId)
    return success_object(domain.serialize(cert))
