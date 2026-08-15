"""TrademarkRecord endpoints (PRD 3.2)."""

from flask import Blueprint

import db
from errors import raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_roles, enforce_client_scope
from response import success
from services.domain import (
    ser_trademark_record, calendar_roll_forward, OPPOSITION_WINDOW_DAYS,
)
from util import (
    get_payload, reject_unknown_fields, require_string, require_enum,
    require_nice_classes, require_datetime, stamp_new, touch, fmt_business,
    add_years, add_months,
)
from routes.common import do_list

bp = Blueprint("trademark_records", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
MARK_TYPES = ("WORD", "DESIGN", "COMPOSITE")


@bp.route("/brand/trademark-records", methods=["POST"])
def create_record():
    user_id, role = require_roles("Paralegal", "ClientContact")
    body = get_payload()
    reject_unknown_fields(body, {"client_id", "mark_text", "mark_type", "jurisdiction",
                                 "nice_classes", "application_number"})
    client_id = require_string(body, "client_id")
    mark_text = require_string(body, "mark_text")
    mark_type = require_enum(body, "mark_type", MARK_TYPES)
    jurisdiction = require_string(body, "jurisdiction")
    nice_classes = require_nice_classes(body, "nice_classes", require_nonempty=True)
    application_number = require_string(body, "application_number")
    # ClientContact may only register marks for its own client_id (PRD 3.2).
    enforce_client_scope(user_id, role, client_id)
    if client_id not in db.clients:
        raise_error(ERR_NOT_FOUND, "Client not found")
    record = {
        "client_id": client_id,
        "mark_text": mark_text,
        "mark_type": mark_type,
        "jurisdiction": jurisdiction,
        "nice_classes": list(nice_classes),
        "application_number": application_number,
        "status": "APPLICATION_PENDING",
        "publication_date": None,
        "registration_date": None,
        "opposition_due_at": None,
        "maintenance_window_open": None,
        "maintenance_window_close": None,
        "maintenance_grace_close": None,
    }
    stamp_new(record)
    db.trademark_records[record["id"]] = record
    return success(ser_trademark_record(record), 201)


@bp.route("/brand/trademark-records", methods=["GET"])
def list_records():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.trademark_records.values(), ser_trademark_record,
                   [("client_id", "client_id", None), ("status", "status", None)],
                   user_id, role, "trademark_record")


@bp.route("/brand/trademark-records/<record_id>", methods=["GET"])
def get_record(record_id):
    user_id, role = require_roles(*READ_ROLES)
    record = db.trademark_records.get(record_id)
    if record is None:
        raise_error(ERR_NOT_FOUND, "TrademarkRecord not found")
    enforce_client_scope(user_id, role, record["client_id"])
    return success(ser_trademark_record(record), 200)


@bp.route("/brand/trademark-records/<record_id>/publish", methods=["POST"])
def publish_record(record_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"publication_date"})
    publication_date = require_datetime(body, "publication_date")
    record = db.trademark_records.get(record_id)
    if record is None:
        raise_error(ERR_NOT_FOUND, "TrademarkRecord not found")
    if record["status"] != "APPLICATION_PENDING":
        raise_error(ERR_INVALID_STATE, "publish is declared only from APPLICATION_PENDING")
    record["publication_date"] = fmt_business(publication_date)
    # opposition_due_at = publication + 30 calendar days, rolled forward past
    # Saturday/Sunday (CALENDAR_ROLL_FORWARD).
    record["opposition_due_at"] = fmt_business(
        calendar_roll_forward(publication_date, OPPOSITION_WINDOW_DAYS))
    record["status"] = "PUBLISHED"
    touch(record)
    return success(ser_trademark_record(record), 200)


@bp.route("/brand/trademark-records/<record_id>/register", methods=["POST"])
def register_record(record_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"registration_date"})
    registration_date = require_datetime(body, "registration_date")
    record = db.trademark_records.get(record_id)
    if record is None:
        raise_error(ERR_NOT_FOUND, "TrademarkRecord not found")
    if record["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "register is declared only from PUBLISHED")
    # Maintenance horizons: +5 years open, +6 years close, +6 months grace.
    window_open = add_years(registration_date, 5)
    window_close = add_years(registration_date, 6)
    grace_close = add_months(window_close, 6)
    record["registration_date"] = fmt_business(registration_date)
    record["maintenance_window_open"] = fmt_business(window_open)
    record["maintenance_window_close"] = fmt_business(window_close)
    record["maintenance_grace_close"] = fmt_business(grace_close)
    record["status"] = "REGISTERED"
    touch(record)
    return success(ser_trademark_record(record), 200)
