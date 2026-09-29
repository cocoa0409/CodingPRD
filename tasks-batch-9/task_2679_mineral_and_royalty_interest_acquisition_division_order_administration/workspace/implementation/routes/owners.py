"""Owners of record and the annual tax statement (PRD 3.2, 3.9)."""

from flask import Blueprint, request

import calc
import guards
import response
import serializers
from db import db, stamp_new, touch
from errors import ApiError
from guards import (authorize, body, get_owner, opt_bool, opt_enum, opt_str,
                    pagination, paginate, req_enum, req_str)

bp = Blueprint("owners", __name__)

CONTACT_STATUSES = ("LOCATED", "UNLOCATABLE", "DECEASED_ESTATE_OPEN")


@bp.route("/royalty-owners", methods=["POST"])
def create_owner():
    authorize("DivisionOrderAdmin")
    payload = body()
    legal_name = req_str(payload, "legal_name")
    state_code = req_enum(payload, "state_code", guards.STATE_CODES)
    mailing_address = req_str(payload, "mailing_address")
    contact_status = opt_enum(payload, "contact_status", CONTACT_STATUSES, default="LOCATED")
    tax_id_on_file = opt_bool(payload, "tax_id_on_file", default=False)

    row = {
        "legal_name": legal_name,
        "state_code": state_code,
        "contact_status": contact_status,
        "tax_id_on_file": tax_id_on_file,
        "mailing_address": mailing_address,
    }
    stamp_new(row)
    db.royalty_owners[row["id"]] = row
    return response.created(serializers.owner_out(row))


@bp.route("/royalty-owners/<owner_id>", methods=["GET"])
def read_owner(owner_id):
    authorize("TitleAnalyst", "AcquisitionManager", "DivisionOrderAdmin", "RoyaltyOwner")
    row = get_owner(owner_id)
    return response.ok(serializers.owner_out(row))


@bp.route("/royalty-owners", methods=["GET"])
def list_owners():
    authorize("AcquisitionManager", "DivisionOrderAdmin")
    limit, offset = pagination()
    contact_status = request.args.get("contact_status")
    state_code = request.args.get("state_code")
    rows = list(db.royalty_owners.values())
    if contact_status is not None:
        rows = [r for r in rows if r["contact_status"] == contact_status]
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.owner_out(r) for r in page], limit, offset, total)


@bp.route("/royalty-owners/<owner_id>", methods=["PATCH"])
def update_owner(owner_id):
    authorize("DivisionOrderAdmin")
    row = get_owner(owner_id)
    payload = body()
    contact_status = opt_enum(payload, "contact_status", CONTACT_STATUSES)
    tax_id_on_file = opt_bool(payload, "tax_id_on_file")
    mailing_address = opt_str(payload, "mailing_address")

    if contact_status is not None:
        row["contact_status"] = contact_status
    if tax_id_on_file is not None:
        row["tax_id_on_file"] = tax_id_on_file
    if mailing_address is not None:
        row["mailing_address"] = mailing_address
    touch(row)
    return response.ok(serializers.owner_out(row))


@bp.route("/royalty-owners/<owner_id>/tax-statement", methods=["GET"])
def owner_tax_statement(owner_id):
    authorize("DivisionOrderAdmin", "RoyaltyOwner")
    row = get_owner(owner_id)
    raw = request.args.get("tax_year")
    if raw is None or raw == "":
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'tax_year' is required.")
    try:
        tax_year = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'tax_year' must be an integer.")
    if tax_year < 1 or tax_year > 9999:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'tax_year' is out of range.")
    stmt = calc.owner_tax_statement(row["id"], tax_year)
    return response.ok(serializers.tax_statement_out(stmt))
