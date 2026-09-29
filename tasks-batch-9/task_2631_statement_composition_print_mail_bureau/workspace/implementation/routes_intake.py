"""Data files, statement records and paperless enrollments."""
from flask import Blueprint

import calc
import domain
from core import (
    ALL_ROLES, DB, ROLE_CLIENT_LIAISON, ROLE_COMPOSITION_OPERATOR, base_row, fail, filter_value,
    json_body, now, opt_int, opt_str, paginate, pagination, req_enum, req_int, req_str,
    require_auth, respond, respond_list, serialize, sorted_rows, touch,
)

bp = Blueprint("intake", __name__)


# --------------------------------------------------------------------------- data files
@bp.route("/bureau/data-files", methods=["POST"])
def data_file_create():
    require_auth((ROLE_CLIENT_LIAISON,))
    body = json_body()
    client_id = req_str(body, "client_id")
    file_name = req_str(body, "file_name", 1, 120)
    format_spec_code = req_enum(body, "format_spec_code", calc.FORMAT_SPEC_CODES)
    declared_record_count = req_int(body, "declared_record_count", 0, None)
    declared_total = req_int(body, "declared_control_total_cents", 0, None)
    client = domain.client_or_404(client_id)
    if client["status"] == "SUSPENDED":
        fail("ERR_CLIENT_SUSPENDED", "client is SUSPENDED and may not lodge data files")
    row = base_row()
    row.update({
        "client_id": client_id,
        "file_name": file_name,
        "format_spec_code": format_spec_code,
        "declared_record_count": declared_record_count,
        "declared_control_total_cents": declared_total,
        "actual_record_count": 0,
        "actual_control_total_cents": 0,
        "record_count_variance": 0,
        "control_total_variance_cents": 0,
        "control_total_variance_bp": 0,
        "format_error_count": 0,
        "amendment_count": 0,
        "status": "RECEIVED",
        "received_at": now(),
        "accepted_at": None,
    })
    DB.files[row["id"]] = row
    return respond(serialize(row), 201)


@bp.route("/bureau/data-files/<file_id>", methods=["GET"])
def data_file_read(file_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.file_or_404(file_id)), 200)


@bp.route("/bureau/data-files/<file_id>/validate-format", methods=["POST"])
def data_file_validate_format(file_id):
    require_auth((ROLE_COMPOSITION_OPERATOR,))
    json_body()
    row = domain.file_or_404(file_id)
    if row["status"] != "RECEIVED":
        fail("ERR_FILE_INVALID_STATE", "format validation requires a RECEIVED data file")
    records = domain.records_in_order(file_id)
    if not records:
        fail("ERR_FILE_EMPTY", "the data file carries no statement records")
    errors = 0
    for record in records:
        valid = calc.record_format_valid(record, row["format_spec_code"])
        domain.apply_changes(record, {"format_valid": valid})
        if not valid:
            errors += 1
    row["format_error_count"] = errors
    if errors > 0:
        touch(row)
        fail("ERR_FILE_FORMAT_ERRORS", "%d attached records failed the format predicate" % errors)
    row["status"] = "FORMAT_VALIDATED"
    touch(row)
    return respond(serialize(row), 200)


@bp.route("/bureau/data-files/<file_id>/control-check", methods=["POST"])
def data_file_control_check(file_id):
    require_auth((ROLE_COMPOSITION_OPERATOR,))
    json_body()
    row = domain.file_or_404(file_id)
    if row["status"] != "FORMAT_VALIDATED":
        fail("ERR_FILE_INVALID_STATE", "control reconciliation requires a FORMAT_VALIDATED data file")
    records = domain.records_of_file(file_id)
    actual_count = len(records)
    actual_total = sum(r["statement_amount_cents"] for r in records)
    row["actual_record_count"] = actual_count
    row["actual_control_total_cents"] = actual_total
    row["record_count_variance"] = actual_count - row["declared_record_count"]
    row["control_total_variance_cents"] = actual_total - row["declared_control_total_cents"]
    row["control_total_variance_bp"] = calc.control_total_variance_bp(
        row["control_total_variance_cents"], row["declared_control_total_cents"]
    )
    client = DB.clients.get(row["client_id"])
    tolerance = client["control_total_tolerance_bp"] if client else 0
    if row["record_count_variance"] == 0 and row["control_total_variance_bp"] <= tolerance:
        row["status"] = "ACCEPTED"
        row["accepted_at"] = now()
    else:
        row["status"] = "HELD_VARIANCE"
    touch(row)
    return respond(serialize(row), 200)


@bp.route("/bureau/data-files/<file_id>/amend-control-totals", methods=["POST"])
def data_file_amend(file_id):
    require_auth((ROLE_CLIENT_LIAISON,))
    body = json_body()
    declared_count = opt_int(body, "declared_record_count", 0, None)
    declared_total = opt_int(body, "declared_control_total_cents", 0, None)
    row = domain.file_or_404(file_id)
    if row["status"] != "HELD_VARIANCE":
        fail("ERR_FILE_INVALID_STATE", "an amendment requires a HELD_VARIANCE data file")
    changed = False
    if declared_count is not None and declared_count != row["declared_record_count"]:
        changed = True
    if declared_total is not None and declared_total != row["declared_control_total_cents"]:
        changed = True
    if not changed:
        fail("ERR_AMENDMENT_NO_CHANGE", "the amendment must move a declared control figure")
    if declared_count is not None:
        row["declared_record_count"] = declared_count
    if declared_total is not None:
        row["declared_control_total_cents"] = declared_total
    row["amendment_count"] = row["amendment_count"] + 1
    row["format_error_count"] = 0
    for record in domain.records_in_order(file_id):
        domain.apply_changes(record, {"format_valid": False})
    row["record_count_variance"] = row["actual_record_count"] - row["declared_record_count"]
    row["control_total_variance_cents"] = (
        row["actual_control_total_cents"] - row["declared_control_total_cents"]
    )
    row["control_total_variance_bp"] = calc.control_total_variance_bp(
        row["control_total_variance_cents"], row["declared_control_total_cents"]
    )
    row["status"] = "RECEIVED"
    touch(row)
    return respond(serialize(row), 200)


@bp.route("/bureau/data-files/<file_id>/statement-records", methods=["GET"])
def data_file_records(file_id):
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    hygiene_status = filter_value("hygiene_status", calc.HYGIENE_STATUSES)
    delivery_channel = filter_value("delivery_channel", calc.DELIVERY_CHANNELS)
    domain.file_or_404(file_id)
    rows = domain.records_of_file(file_id)
    if hygiene_status is not None:
        rows = [r for r in rows if r["hygiene_status"] == hygiene_status]
    if delivery_channel is not None:
        rows = [r for r in rows if r["delivery_channel"] == delivery_channel]
    rows = sorted_rows(rows, lambda r: (r["sequence_no"],))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


# --------------------------------------------------------------------------- statement records
@bp.route("/bureau/statement-records", methods=["POST"])
def statement_record_create():
    require_auth((ROLE_CLIENT_LIAISON,))
    body = json_body()
    data_file_id = req_str(body, "data_file_id")
    account_ref = req_str(body, "account_ref", 1, 40)
    sequence_no = req_int(body, "sequence_no", 1, None)
    amount = req_int(body, "statement_amount_cents")
    address_line1 = req_str(body, "address_line1")
    city = req_str(body, "city")
    region_code = req_str(body, "region_code")
    postal_code = req_str(body, "postal_code")
    plus4 = opt_str(body, "postal_code_plus4")
    data_file = domain.file_or_404(data_file_id)
    for existing in domain.records_of_file(data_file_id):
        if existing["sequence_no"] == sequence_no:
            fail("ERR_DUPLICATE_CODE", "sequence_no %d already attached to this file" % sequence_no)
        if existing["account_ref"] == account_ref:
            fail("ERR_DUPLICATE_CODE", "account_ref %s already attached to this file" % account_ref)
    client = DB.clients.get(data_file["client_id"])
    if client is not None and client["status"] == "SUSPENDED":
        fail("ERR_CLIENT_SUSPENDED", "client is SUSPENDED and may not receive statement records")
    if data_file["status"] != "RECEIVED":
        fail("ERR_FILE_INVALID_STATE", "records may only be attached to a RECEIVED data file")
    row = base_row()
    row.update({
        "data_file_id": data_file_id,
        "account_ref": account_ref,
        "sequence_no": sequence_no,
        "statement_amount_cents": amount,
        "address_line1": address_line1,
        "city": city,
        "region_code": region_code,
        "postal_code": postal_code,
        "postal_code_plus4": plus4,
        "format_valid": False,
        "hygiene_status": "PENDING",
        "hygiene_confidence": None,
        "delivery_channel": "PENDING",
        "computed_sheet_count": None,
        "computed_insert_codes": None,
        "address_update_pending": False,
    })
    DB.records[row["id"]] = row
    return respond(serialize(row), 201)


@bp.route("/bureau/statement-records/<record_id>", methods=["GET"])
def statement_record_read(record_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.record_or_404(record_id)), 200)


# --------------------------------------------------------------------------- paperless enrollments
@bp.route("/bureau/paperless-enrollments", methods=["POST"])
def enrollment_create():
    require_auth((ROLE_CLIENT_LIAISON,))
    body = json_body()
    client_id = req_str(body, "client_id")
    account_ref = req_str(body, "account_ref", 1, 40)
    channel = req_enum(body, "channel", calc.ENROLLMENT_CHANNELS)
    domain.client_or_404(client_id)
    existing = None
    for row in domain.enrollments_of_client(client_id):
        if row["account_ref"] == account_ref:
            existing = row
            break
    if existing is not None:
        if existing["status"] != "REVOKED":
            fail("ERR_DUPLICATE_CODE", "an active enrollment already exists for this account_ref")
        existing["status"] = "PENDING"
        existing["channel"] = channel
        existing["enrolled_epoch"] = None
        existing["revoked_epoch"] = None
        existing["confirmed_at"] = None
        existing["revoked_at"] = None
        existing["suppression_effective"] = False
        touch(existing)
        return respond(serialize(existing), 201)
    row = base_row()
    row.update({
        "client_id": client_id,
        "account_ref": account_ref,
        "channel": channel,
        "status": "PENDING",
        "enrolled_epoch": None,
        "revoked_epoch": None,
        "suppression_effective": False,
        "confirmed_at": None,
        "revoked_at": None,
    })
    DB.enrollments[row["id"]] = row
    return respond(serialize(row), 201)


@bp.route("/bureau/paperless-enrollments/<enrollment_id>", methods=["GET"])
def enrollment_read(enrollment_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.enrollment_or_404(enrollment_id)), 200)


@bp.route("/bureau/paperless-enrollments/<enrollment_id>/revoke", methods=["POST"])
def enrollment_revoke(enrollment_id):
    require_auth((ROLE_CLIENT_LIAISON,))
    json_body()
    row = domain.enrollment_or_404(enrollment_id)
    if row["status"] not in ("PENDING", "ENROLLED"):
        fail("ERR_ENROLLMENT_INVALID_STATE", "only a PENDING or ENROLLED enrollment may be revoked")
    client = DB.clients.get(row["client_id"])
    row["status"] = "REVOKED"
    row["revoked_epoch"] = client["paperless_sync_epoch"] if client else None
    row["revoked_at"] = now()
    row["suppression_effective"] = False
    touch(row)
    return respond(serialize(row), 200)
