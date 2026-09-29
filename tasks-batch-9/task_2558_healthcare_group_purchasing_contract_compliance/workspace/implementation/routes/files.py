"""Distributor files and purchase lines (PRD section 3.7)."""

from flask import Blueprint

from db import db, ordered
from enums import CLASSIFICATIONS, FILE_STATUSES, REJECT_REASONS
from errors import ApiError
from middleware import ALL_ROLES, COMPLIANCE_ANALYST, DISTRIBUTOR_AGENT, authenticate
from response import list_response, object_response
from services.calc import half_open_overlap
from services.ledger import load_file, reverse_file, validate_file
from services.lookup import get_file, get_purchase_line, resolve_body_fks
from validation import (
    bad,
    body_json,
    field_date,
    field_int,
    field_list,
    field_string,
    paginate,
    pagination,
    query_enum,
    query_string,
)

files_bp = Blueprint("files", __name__)

# A file already rejected or reversed no longer blocks a fresh submission.
OVERLAP_IGNORED_STATUSES = ("REJECTED", "REVERSED")


def _wrap(entry, label, name):
    """Present one nested line field under its dotted path for error messages."""
    return {"%s.%s" % (label, name): entry.get(name)}, "%s.%s" % (label, name)


def _parse_lines(body):
    raw = field_list(body, "lines", min_len=1)
    entries = []
    for index, entry in enumerate(raw):
        label = "lines[%d]" % index
        if not isinstance(entry, dict):
            raise bad("Field '%s' must be an object." % label)
        holder, key = _wrap(entry, label, "member_item_number")
        member_item_number = field_string(holder, key, 1, 40)
        holder, key = _wrap(entry, label, "quantity_units")
        quantity_units = field_int(holder, key, minimum=0)
        holder, key = _wrap(entry, label, "unit_price_paid_cents")
        unit_price_paid_cents = field_int(holder, key, minimum=0)
        holder, key = _wrap(entry, label, "purchase_date")
        purchase_date = field_date(holder, key)
        entries.append(
            {
                "member_item_number": member_item_number,
                "quantity_units": quantity_units,
                "unit_price_paid_cents": unit_price_paid_cents,
                "purchase_date": purchase_date,
            }
        )
    return entries


@files_bp.route("/gpo/distributor-files", methods=["POST"])
def create_distributor_file():
    authenticate((DISTRIBUTOR_AGENT,))
    body = body_json()
    resolved = resolve_body_fks(body, ("contract_id", "member_id"))
    contract = resolved["contract_id"]
    member = resolved["member_id"]
    if contract is None:
        raise bad("Field 'contract_id' is required.")
    if member is None:
        raise bad("Field 'member_id' is required.")

    distributor_code = field_string(body, "distributor_code", 1, 40)
    period_start = field_date(body, "period_start")
    period_end = field_date(body, "period_end")
    lines = _parse_lines(body)

    if member["status"] != "ACTIVE":
        raise ApiError(
            "ERR_MEMBER_NOT_ACTIVE", "A suspended member cannot receive purchase files."
        )
    if contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE", "Files can only be submitted against an ACTIVE contract."
        )
    if period_end <= period_start:
        raise ApiError(
            "ERR_EFFECTIVE_WINDOW_INVALID", "period_end must be strictly after period_start."
        )
    for existing in db.files.values():
        if existing["member_id"] != member["id"]:
            continue
        if existing["contract_id"] != contract["id"]:
            continue
        if existing["distributor_code"] != distributor_code:
            continue
        if existing["status"] in OVERLAP_IGNORED_STATUSES:
            continue
        if half_open_overlap(
            period_start, period_end, existing["period_start"], existing["period_end"]
        ):
            raise ApiError(
                "ERR_FILE_PERIOD_OVERLAP",
                "This distributor already has a live file overlapping that period.",
            )

    row = db.new_row()
    row.update(
        {
            "member_id": member["id"],
            "contract_id": contract["id"],
            "distributor_code": distributor_code,
            "period_start": period_start,
            "period_end": period_end,
            "status": "RECEIVED",
            "line_count": len(lines),
            "accepted_line_count": 0,
            "rejected_line_count": 0,
            "loaded_at": None,
            "reverse_note": None,
        }
    )
    db.files[row["id"]] = row
    for entry in lines:
        line = db.new_row(versioned=False)
        line.update(
            {
                "distributor_file_id": row["id"],
                "member_item_number": entry["member_item_number"],
                "quantity_units": entry["quantity_units"],
                "unit_price_paid_cents": entry["unit_price_paid_cents"],
                "purchase_date": entry["purchase_date"],
                "extended_cost_cents": entry["quantity_units"]
                * entry["unit_price_paid_cents"],
                "contract_units": 0,
                "matched_vendor_item_number": None,
                "classification": "UNCLASSIFIED",
                "reject_reason": "NONE",
            }
        )
        db.purchase_lines[line["id"]] = line
    return object_response(row, 201)


@files_bp.route("/gpo/distributor-files/<file_id>", methods=["GET"])
def read_distributor_file(file_id):
    authenticate(ALL_ROLES)
    return object_response(get_file(file_id))


@files_bp.route("/gpo/distributor-files", methods=["GET"])
def list_distributor_files():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    member_id = query_string("member_id")
    contract_id = query_string("contract_id")
    distributor_code = query_string("distributor_code")
    status = query_enum("status", FILE_STATUSES)
    rows = [
        row
        for row in ordered(db.files.values())
        if (member_id is None or row["member_id"] == member_id)
        and (contract_id is None or row["contract_id"] == contract_id)
        and (distributor_code is None or row["distributor_code"] == distributor_code)
        and (status is None or row["status"] == status)
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@files_bp.route("/gpo/distributor-files/<file_id>/validate", methods=["POST"])
def validate_distributor_file(file_id):
    authenticate((DISTRIBUTOR_AGENT,))
    distributor_file = get_file(file_id)
    if distributor_file["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_FILE_STATE", "Only a RECEIVED file can be validated.")
    validate_file(distributor_file)
    return object_response(distributor_file)


@files_bp.route("/gpo/distributor-files/<file_id>/load", methods=["POST"])
def load_distributor_file(file_id):
    authenticate((COMPLIANCE_ANALYST,))
    distributor_file = get_file(file_id)
    if distributor_file["status"] != "VALIDATING":
        raise ApiError("ERR_INVALID_FILE_STATE", "Only a VALIDATING file can be loaded.")
    load_file(distributor_file)
    return object_response(distributor_file)


@files_bp.route("/gpo/distributor-files/<file_id>/reverse", methods=["POST"])
def reverse_distributor_file(file_id):
    authenticate((COMPLIANCE_ANALYST,))
    distributor_file = get_file(file_id)
    body = body_json()
    reason = field_string(body, "reason", 0, None, required=False, default=None)
    if distributor_file["status"] not in ("LOADED", "PARTIALLY_LOADED"):
        raise ApiError(
            "ERR_INVALID_FILE_STATE",
            "Only a LOADED or PARTIALLY_LOADED file can be reversed.",
        )
    reverse_file(distributor_file, reason)
    return object_response(distributor_file)


@files_bp.route("/gpo/purchase-lines", methods=["GET"])
def list_purchase_lines():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    distributor_file_id = query_string("distributor_file_id")
    classification = query_enum("classification", CLASSIFICATIONS)
    reject_reason = query_enum("reject_reason", REJECT_REASONS)
    rows = [
        row
        for row in ordered(db.purchase_lines.values())
        if (distributor_file_id is None or row["distributor_file_id"] == distributor_file_id)
        and (classification is None or row["classification"] == classification)
        and (reject_reason is None or row["reject_reason"] == reject_reason)
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@files_bp.route("/gpo/purchase-lines/<purchase_line_id>", methods=["GET"])
def read_purchase_line(purchase_line_id):
    authenticate(ALL_ROLES)
    return object_response(get_purchase_line(purchase_line_id))
