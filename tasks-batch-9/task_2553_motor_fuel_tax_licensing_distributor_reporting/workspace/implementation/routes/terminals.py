"""Terminals and exemption certificates (PRD 3.3)."""

from flask import Blueprint

import db
import helpers
import middleware
import response
import shape
from errors import ApiError
from middleware import (AUDIT_MANAGER, FIELD_INSPECTOR, LICENSEE_AGENT,
                        LICENSING_OFFICER, RETURNS_EXAMINER, TAX_SUPERVISOR)
from services import calc, derive

bp = Blueprint("terminals", __name__, url_prefix="/mft")


@bp.post("/terminals")
def register_terminal():
    middleware.require(LICENSING_OFFICER)
    body = shape.body()
    tcn = shape.req_pattern(body, "terminal_control_number", shape.TCN_RE)
    name = shape.req_str(body, "name")
    state_code = shape.req_pattern(body, "state_code", shape.STATE_RE)

    for existing in db.terminals.values():
        if existing["terminal_control_number"] == tcn:
            raise ApiError("ERR_DUPLICATE_TCN")

    row = db.base_row()
    row.update({
        "terminal_control_number": tcn,
        "name": name,
        "state_code": state_code,
    })
    db.terminals[row["id"]] = row
    return response.object_response(derive.terminal_json(row), 201)


@bp.get("/terminals/<terminal_id>")
def read_terminal(terminal_id):
    middleware.require(LICENSING_OFFICER, RETURNS_EXAMINER, TAX_SUPERVISOR,
                       AUDIT_MANAGER, FIELD_INSPECTOR, LICENSEE_AGENT)
    row = helpers.find("terminal", terminal_id)
    return response.object_response(derive.terminal_json(row))


@bp.get("/terminals")
def list_terminals():
    middleware.require(LICENSING_OFFICER, RETURNS_EXAMINER, TAX_SUPERVISOR,
                       AUDIT_MANAGER, LICENSEE_AGENT)
    rows = db.ordered(db.terminals)
    rows = helpers.filter_by(rows, {"state_code": "state_code"})
    return response.list_response(rows, derive.terminal_json)


@bp.post("/exemption-certificates")
def issue_certificate():
    middleware.require(LICENSING_OFFICER)
    body = shape.body()
    purchaser_id = shape.req_id(body, "purchaser_licensee_id")
    exemption_type = shape.req_enum(body, "exemption_type", calc.EXEMPTION_TYPES)
    document_number = shape.req_str(body, "document_number")
    valid_from = shape.req_date(body, "valid_from")
    valid_to = shape.req_date(body, "valid_to")

    helpers.body_licensee(purchaser_id)

    # Closed windows: sharing a single endpoint date is already a collision.
    for existing in db.ordered(db.certificates):
        if (existing["purchaser_licensee_id"] == purchaser_id
                and existing["exemption_type"] == exemption_type
                and existing["status"] == "ACTIVE"
                and valid_from <= existing["valid_to"]
                and existing["valid_from"] <= valid_to):
            raise ApiError("ERR_CERTIFICATE_PERIOD_OVERLAP")

    if valid_from > valid_to:
        raise ApiError("ERR_DATE_RANGE_INVALID")

    for existing in db.certificates.values():
        if existing["document_number"] == document_number:
            raise ApiError("ERR_DUPLICATE_CERTIFICATE_NUMBER")

    row = db.base_row()
    row.update({
        "purchaser_licensee_id": purchaser_id,
        "exemption_type": exemption_type,
        "document_number": document_number,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": "ACTIVE",
    })
    db.certificates[row["id"]] = row
    return response.object_response(derive.certificate_json(row), 201)


@bp.get("/exemption-certificates/<certificate_id>")
def read_certificate(certificate_id):
    middleware.require(LICENSING_OFFICER, RETURNS_EXAMINER, TAX_SUPERVISOR,
                       AUDIT_MANAGER, FIELD_INSPECTOR, LICENSEE_AGENT)
    row = helpers.find("certificate", certificate_id)
    return response.object_response(derive.certificate_json(row))


@bp.get("/exemption-certificates")
def list_certificates():
    middleware.require(LICENSING_OFFICER, RETURNS_EXAMINER, TAX_SUPERVISOR,
                       AUDIT_MANAGER, LICENSEE_AGENT)
    rows = db.ordered(db.certificates)
    rows = helpers.filter_by(rows, {
        "purchaser_licensee_id": "purchaser_licensee_id",
        "exemption_type": "exemption_type",
        "status": "status",
    })
    return response.list_response(rows, derive.certificate_json)


@bp.post("/exemption-certificates/<certificate_id>/revoke")
def revoke_certificate(certificate_id):
    middleware.require(LICENSING_OFFICER)
    peeked = helpers.maybe("certificate", certificate_id)
    body = shape.body()
    shape.req_str(body, "reason")
    row = helpers.ensure("certificate", peeked)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_CERTIFICATE_NOT_ACTIVE")
    row["status"] = "REVOKED"
    db.touch(row)
    return response.object_response(derive.certificate_json(row))
