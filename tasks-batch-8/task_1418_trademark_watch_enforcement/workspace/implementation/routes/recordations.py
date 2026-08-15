"""CustomsRecordation endpoints (PRD 3.7)."""

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_RECORD_NOT_REGISTERED,
    ERR_RECORDATION_GAP_VIOLATION,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services import domain
from services.domain import ser_customs_recordation
from util import (
    get_payload, reject_unknown_fields, require_string, require_enum,
    optional_string, require_datetime, stamp_new, touch, fmt_business,
    parse_dt, add_days,
)
from routes.common import do_list

bp = Blueprint("customs_recordations", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
AUTHORITIES = ("US_CBP", "EU_TAXUD", "CN_GACC")
RECORD_STATES = ("REGISTERED", "MAINTENANCE_DUE")
BUFFER_GAP_DAYS = 30


# ---------------------------------------------------------------------------
# Nested create: POST /brand/trademark-records/{id}/customs-recordations
# ---------------------------------------------------------------------------

@bp.route("/brand/trademark-records/<record_id>/customs-recordations", methods=["POST"])
def create_recordation(record_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"customs_authority", "recordation_number", "term_start",
                                 "term_end", "supersedes_recordation_id"})
    customs_authority = require_enum(body, "customs_authority", AUTHORITIES)
    recordation_number = require_string(body, "recordation_number")
    term_start = require_datetime(body, "term_start")
    term_end = require_datetime(body, "term_end")
    supersedes_id = optional_string(body, "supersedes_recordation_id", default=None)
    record = db.trademark_records.get(record_id)
    if record is None:
        raise_error(ERR_NOT_FOUND, "TrademarkRecord not found")
    if supersedes_id is not None and supersedes_id not in db.customs_recordations:
        raise_error(ERR_NOT_FOUND, "Superseded CustomsRecordation not found")
    # The record must be REGISTERED or MAINTENANCE_DUE.
    if record["status"] not in RECORD_STATES:
        raise_error(ERR_RECORD_NOT_REGISTERED,
                    "Customs recordation requires a REGISTERED / MAINTENANCE_DUE record")
    if supersedes_id is None:
        # Buffer-gap rule: for the same record and authority, the new term_start
        # must be STRICTLY more than 30 days after every existing non-superseded
        # recordation's term_end (adjacency forbidden). Waived on supersede.
        for existing in db.customs_recordations.values():
            if existing["trademark_record_id"] != record["id"]:
                continue
            if existing["customs_authority"] != customs_authority:
                continue
            if existing["status"] == "RENEWED":
                continue  # superseded recordations are excluded
            if term_start <= add_days(parse_dt(existing["term_end"]), BUFFER_GAP_DAYS):
                raise_error(ERR_RECORDATION_GAP_VIOLATION,
                            "term_start must be strictly greater than existing term_end + 30 days")
    recordation = {
        "trademark_record_id": record["id"],
        "customs_authority": customs_authority,
        "recordation_number": recordation_number,
        "term_start": fmt_business(term_start),
        "term_end": fmt_business(term_end),
        "supersedes_recordation_id": supersedes_id,
        "status": "ACTIVE",
    }
    stamp_new(recordation)
    db.customs_recordations[recordation["id"]] = recordation
    if supersedes_id is not None:
        superseded = db.customs_recordations[supersedes_id]
        if superseded["status"] == "ACTIVE":
            superseded["status"] = "RENEWED"
            touch(superseded)
    return success(ser_customs_recordation(recordation), 201)


@bp.route("/brand/customs-recordations", methods=["GET"])
def list_recordations():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.customs_recordations.values(), ser_customs_recordation,
                   [("trademark_record_id", "trademark_record_id", None),
                    ("customs_authority", "customs_authority", None),
                    ("status", "status", None),
                    ("supersedes_recordation_id", "supersedes_recordation_id", None)],
                   user_id, role, "customs_recordation")


@bp.route("/brand/customs-recordations/<recordation_id>", methods=["GET"])
def get_recordation(recordation_id):
    user_id, role = require_roles(*READ_ROLES)
    recordation = db.customs_recordations.get(recordation_id)
    if recordation is None:
        raise_error(ERR_NOT_FOUND, "CustomsRecordation not found")
    enforce_client_scope(user_id, role,
                         domain.client_id_for_resource("customs_recordation", recordation))
    return success(ser_customs_recordation(recordation), 200)
