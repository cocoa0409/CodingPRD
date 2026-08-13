"""Exemption certificates and bonded movements."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from errors import raise_err
from store import DB
from auth import (
    require_roles, ALL_READ_ROLES, body_dict, req_str, req_int, opt_int, req_enum,
    req_dt, opt_str, new_entity, touch, get_or_404, public, paginate,
)
from response import success_object, success_list
from utiltime import fmt_dt, now_dt
import services

bp = Blueprint("compliance", __name__)

CERT_FIELDS = ["registration_id", "product_class_id", "customer_reference",
               "certificate_type", "valid_from", "valid_to", "status"]
MOVEMENT_FIELDS = ["registration_id", "bond_id", "product_class_id", "quantity_units",
                   "origin_facility", "destination_facility", "transit_deadline_days",
                   "dispatched_at", "received_at", "quantity_received_units",
                   "defaulted_quantity_units", "status"]


def ser_cert(c):
    return public(c, CERT_FIELDS)


def ser_movement(m):
    return public(m, MOVEMENT_FIELDS)


# ------------------------------------------------------------------ certificates
@bp.post("/exemption-certificates")
def create_certificate():
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body = body_dict()
    registration_id = req_str(body, "registration_id")
    product_class_id = opt_str(body, "product_class_id")
    customer_reference = req_str(body, "customer_reference")
    certificate_type = req_enum(body, "certificate_type", {"RESALE", "GOVERNMENT", "EXPORT"})
    valid_from = req_dt(body, "valid_from")
    valid_to = req_dt(body, "valid_to")
    if valid_to < valid_from:
        raise_err(errors.ERR_INVALID_REQUEST, "valid_to precedes valid_from")
    get_or_404(DB.registrations, registration_id, "Registration")
    if product_class_id is not None:
        get_or_404(DB.product_classes, product_class_id, "ProductClass")
    # Closed windows per (registration, customer_reference, product_class-or-null)
    # must keep a >= 1-day gap from any PENDING_VERIFICATION/ACTIVE certificate;
    # touching windows are rejected.
    one_day = timedelta(days=1)
    for c in DB.certificates.values():
        if c["registration_id"] != registration_id:
            continue
        if c["customer_reference"] != customer_reference:
            continue
        if c["product_class_id"] != product_class_id:
            continue
        if c["status"] not in ("PENDING_VERIFICATION", "ACTIVE"):
            continue
        if valid_from <= c["_valid_to"] + one_day and c["_valid_from"] <= valid_to + one_day:
            raise_err(errors.ERR_CERTIFICATE_WINDOW_OVERLAP,
                      "Certificate window touches or overlaps an existing certificate")
    cert = new_entity({
        "registration_id": registration_id,
        "product_class_id": product_class_id,
        "customer_reference": customer_reference,
        "certificate_type": certificate_type,
        "valid_from": fmt_dt(valid_from),
        "valid_to": fmt_dt(valid_to),
        "status": "PENDING_VERIFICATION",
        "_valid_from": valid_from,
        "_valid_to": valid_to,
    })
    DB.certificates[cert["id"]] = cert
    return success_object(ser_cert(cert), 201)


@bp.get("/exemption-certificates/<cid>")
def get_certificate(cid):
    require_roles(ALL_READ_ROLES)
    cert = get_or_404(DB.certificates, cid, "ExemptionCertificate")
    return success_object(ser_cert(cert))


@bp.get("/exemption-certificates")
def list_certificates():
    require_roles(ALL_READ_ROLES)
    items = list(DB.certificates.values())
    for param in ("registration_id", "product_class_id", "status", "certificate_type"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    data, limit, offset, total = paginate(items, ser_cert)
    return success_list(data, limit, offset, total)


@bp.post("/exemption-certificates/<cid>/verify")
def verify_certificate(cid):
    require_roles(["TaxReviewer", "ComplianceAdmin"])
    body_dict(require=False)
    cert = get_or_404(DB.certificates, cid, "ExemptionCertificate")
    if cert["status"] != "PENDING_VERIFICATION":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Certificate in status {cert['status']} cannot be verified")
    cert["status"] = "ACTIVE"
    touch(cert)
    return success_object(ser_cert(cert))


@bp.post("/exemption-certificates/<cid>/revoke")
def revoke_certificate(cid):
    require_roles(["TaxReviewer", "ComplianceAdmin"])
    body_dict(require=False)
    cert = get_or_404(DB.certificates, cid, "ExemptionCertificate")
    if cert["status"] == "PENDING_VERIFICATION":
        cert["status"] = "REJECTED"
    elif cert["status"] == "ACTIVE":
        cert["status"] = "REVOKED"
    else:
        raise_err(errors.ERR_INVALID_STATE,
                  f"Certificate in status {cert['status']} cannot be revoked")
    touch(cert)
    return success_object(ser_cert(cert))


# ------------------------------------------------------------------ bonded movements
@bp.post("/bonded-movements")
def create_movement():
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body = body_dict()
    registration_id = req_str(body, "registration_id")
    bond_id = req_str(body, "bond_id")
    product_class_id = req_str(body, "product_class_id")
    quantity_units = req_int(body, "quantity_units", minimum=1)
    origin_facility = req_str(body, "origin_facility")
    destination_facility = req_str(body, "destination_facility")
    transit_deadline_days = opt_int(body, "transit_deadline_days", default=30, minimum=1)
    reg = get_or_404(DB.registrations, registration_id, "Registration")
    bond = get_or_404(DB.bonds, bond_id, "Bond")
    get_or_404(DB.product_classes, product_class_id, "ProductClass")
    if reg["status"] != "ACTIVE":
        raise_err(errors.ERR_REG_NOT_ACTIVE,
                  "Registration must be ACTIVE to document a bonded movement")
    if bond["registration_id"] != registration_id:
        raise_err(errors.ERR_CROSS_REGISTRANT,
                  "Bond belongs to a different registration")
    movement = new_entity({
        "registration_id": registration_id,
        "bond_id": bond_id,
        "product_class_id": product_class_id,
        "quantity_units": quantity_units,
        "origin_facility": origin_facility,
        "destination_facility": destination_facility,
        "transit_deadline_days": transit_deadline_days,
        "dispatched_at": None,
        "received_at": None,
        "quantity_received_units": None,
        "defaulted_quantity_units": 0,
        "status": "INITIATED",
        "_dispatched_dt": None,
        "_defaulted_at": None,
    })
    DB.movements[movement["id"]] = movement
    return success_object(ser_movement(movement), 201)


@bp.get("/bonded-movements/<mid>")
def get_movement(mid):
    require_roles(ALL_READ_ROLES)
    m = get_or_404(DB.movements, mid, "BondedMovement")
    return success_object(ser_movement(m))


@bp.get("/bonded-movements")
def list_movements():
    require_roles(ALL_READ_ROLES)
    items = list(DB.movements.values())
    for param in ("registration_id", "bond_id", "product_class_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [m for m in items if m.get(param) == v]
    data, limit, offset, total = paginate(items, ser_movement)
    return success_list(data, limit, offset, total)


@bp.post("/bonded-movements/<mid>/dispatch")
def dispatch_movement(mid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body_dict(require=False)
    m = get_or_404(DB.movements, mid, "BondedMovement")
    if m["status"] != "INITIATED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Movement in status {m['status']} cannot be dispatched")
    reg = DB.registrations[m["registration_id"]]
    if reg["status"] != "ACTIVE":
        raise_err(errors.ERR_REG_NOT_ACTIVE,
                  "Registration must be ACTIVE to dispatch a movement")
    bond = DB.bonds[m["bond_id"]]
    if bond["status"] != "ACTIVE":
        raise_err(errors.ERR_MOVEMENT_NOT_LINKABLE,
                  "The linked bond is not ACTIVE")
    m["status"] = "IN_TRANSIT"
    m["dispatched_at"] = fmt_dt(now_dt())
    m["_dispatched_dt"] = now_dt()
    touch(m)
    return success_object(ser_movement(m))


@bp.post("/bonded-movements/<mid>/receive")
def receive_movement(mid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body = body_dict()
    qty = req_int(body, "quantity_received_units", minimum=0)
    m = get_or_404(DB.movements, mid, "BondedMovement")
    if m["status"] != "IN_TRANSIT":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Movement in status {m['status']} cannot be received")
    if qty > m["quantity_units"]:
        raise_err(errors.ERR_MOVEMENT_QUANTITY_EXCEEDS,
                  "quantity_received_units exceeds the shipped quantity")
    m["status"] = "RECEIVED"
    m["quantity_received_units"] = qty
    m["received_at"] = fmt_dt(now_dt())
    touch(m)
    return success_object(ser_movement(m))


@bp.post("/bonded-movements/<mid>/discharge")
def discharge_movement(mid):
    require_roles(["TaxReviewer", "ComplianceAdmin"])
    body_dict(require=False)
    m = get_or_404(DB.movements, mid, "BondedMovement")
    if m["status"] != "RECEIVED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Movement in status {m['status']} cannot be discharged")
    if m["quantity_received_units"] != m["quantity_units"]:
        raise_err(errors.ERR_INVALID_STATE,
                  "Discharge requires exact quantity reconciliation; default the shortfall first")
    m["status"] = "DISCHARGED"
    touch(m)
    return success_object(ser_movement(m))


@bp.post("/bonded-movements/<mid>/default")
def default_movement(mid):
    require_roles(["ComplianceAdmin"])
    body_dict(require=False)
    m = get_or_404(DB.movements, mid, "BondedMovement")
    if m["status"] == "IN_TRANSIT":
        defaulted_qty = m["quantity_units"]
        m["status"] = "DEFAULTED"
    elif m["status"] == "RECEIVED":
        if not (m["quantity_received_units"] < m["quantity_units"]):
            raise_err(errors.ERR_INVALID_STATE,
                      "No shortfall to default: received quantity equals shipped quantity")
        defaulted_qty = m["quantity_units"] - m["quantity_received_units"]
        m["status"] = "PARTIAL_DEFAULT"
    else:
        raise_err(errors.ERR_INVALID_STATE,
                  f"Movement in status {m['status']} cannot be defaulted")
    m["defaulted_quantity_units"] = defaulted_qty
    m["_defaulted_at"] = now_dt()
    touch(m)
    services.run_default_cascade(m, defaulted_qty, now_dt())
    return success_object(ser_movement(m))
