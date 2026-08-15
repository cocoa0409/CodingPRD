"""ComplianceFiling endpoints."""
from flask import Blueprint, request

import clock
from db import db
from errors import validation, ApiError, ERR_FILING_INVALID_STATE
from middleware import require_roles, require_read
from response import success_object, success_list
from serializers import filing_view
from services.core import make_record, touch, require_exists, get_pagination, paginate
from util import fmt_ts, parse_date

bp = Blueprint("filings", __name__)

FILING_KINDS = {"INSURANCE_COI", "REGISTRATION", "OPS_SPECS_AMENDMENT"}
OUTCOMES = {"ACCEPTED", "REJECTED"}


@bp.route("/filings", methods=["POST"])
def create_filing():
    require_roles("ComplianceOfficer")
    body = request.get_json(silent=True) or {}

    aircraft_id = body.get("aircraft_id")
    if aircraft_id is not None:
        require_exists(db.aircraft, aircraft_id, "aircraft_id does not resolve")
    if not isinstance(aircraft_id, str) or not aircraft_id:
        raise validation("aircraft_id is required")

    filing_kind = body.get("filing_kind")
    if filing_kind not in FILING_KINDS:
        raise validation("filing_kind is not a valid enum value")

    authority = body.get("authority")
    if not isinstance(authority, str) or not authority:
        raise validation("authority is required")
    reference_no = body.get("reference_no")
    if not isinstance(reference_no, str) or not reference_no:
        raise validation("reference_no is required")

    valid_until = body.get("valid_until")
    parse_date(valid_until, "valid_until")

    rec = make_record({
        "aircraft_id": aircraft_id,
        "filing_kind": filing_kind,
        "authority": authority,
        "reference_no": reference_no,
        "valid_until": valid_until,
        "filed_at": None,
        "decision_notes": None,
        "handed_over_at": None,
        "status": "DRAFT",
    })
    db.filings[rec["id"]] = rec
    return success_object(filing_view(rec), 201)


@bp.route("/filings/<filing_id>", methods=["GET"])
def get_filing(filing_id):
    require_read()
    rec = require_exists(db.filings, filing_id)
    return success_object(filing_view(rec))


@bp.route("/aircraft/<aircraft_id>/filings", methods=["GET"])
def list_filings(aircraft_id):
    require_read()
    require_exists(db.aircraft, aircraft_id)
    limit, offset = get_pagination(request.args)
    records = [f for f in db.filings.values() if f["aircraft_id"] == aircraft_id]
    page, total = paginate(records, limit, offset)
    return success_list([filing_view(r) for r in page], limit, offset, total)


@bp.route("/filings/<filing_id>/file", methods=["POST"])
def file_filing(filing_id):
    require_roles("ComplianceOfficer")
    rec = require_exists(db.filings, filing_id)
    body = request.get_json(silent=True) or {}

    if "reference_no" in body and body["reference_no"] is not None:
        if not isinstance(body["reference_no"], str) or not body["reference_no"]:
            raise validation("reference_no must be a non-empty string")
    if "valid_until" in body and body["valid_until"] is not None:
        parse_date(body["valid_until"], "valid_until")

    if rec["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_FILING_INVALID_STATE,
                       "Filing must be in DRAFT or REJECTED", 409)

    if "reference_no" in body and body["reference_no"] is not None:
        rec["reference_no"] = body["reference_no"]
    if "valid_until" in body and body["valid_until"] is not None:
        rec["valid_until"] = body["valid_until"]
    rec["filed_at"] = fmt_ts(clock.now())
    rec["status"] = "FILED"
    touch(rec, bump_version=True)
    return success_object(filing_view(rec))


@bp.route("/filings/<filing_id>/record-decision", methods=["POST"])
def record_decision(filing_id):
    require_roles("ComplianceOfficer")
    rec = require_exists(db.filings, filing_id)
    body = request.get_json(silent=True) or {}

    outcome = body.get("outcome")
    if outcome not in OUTCOMES:
        raise validation("outcome must be ACCEPTED or REJECTED")

    if rec["status"] != "FILED":
        raise ApiError(ERR_FILING_INVALID_STATE, "Filing must be in FILED", 409)

    rec["status"] = outcome
    rec["decision_notes"] = body.get("notes")
    touch(rec, bump_version=True)
    return success_object(filing_view(rec))
