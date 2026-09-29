"""Clock, clients, templates, insert stock, press lines, entry facilities, DR site."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
from core import (
    ALL_ROLES, CLOCK, DB, ROLE_BUREAU_ADMIN, ROLE_CLIENT_LIAISON, ROLE_POSTAGE_CONTROLLER,
    acting_user, base_row, fail, filter_value, invalid, iso, json_body, now, opt_bool, opt_dt,
    opt_enum, opt_int, opt_str, opt_str_list, paginate, pagination, req_bool, req_dt, req_enum,
    req_int, req_str, req_str_list, require_auth, respond, respond_list, serialize, sorted_rows,
    touch,
)

bp = Blueprint("ref", __name__)


# --------------------------------------------------------------------------- logical clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    require_auth(ALL_ROLES)
    body = json_body()
    instant = req_dt(body, "current_utc")
    CLOCK.set(instant)
    return respond({}, 200)


# --------------------------------------------------------------------------- clients
def client_view(row):
    return serialize(row)


@bp.route("/bureau/clients", methods=["POST"])
def client_create():
    require_auth((ROLE_BUREAU_ADMIN,))
    body = json_body()
    client_code = req_str(body, "client_code", 3, 10, calc.CLIENT_CODE_PATTERN)
    name = req_str(body, "name", 1, 120)
    turnaround = opt_int(body, "sla_turnaround_hours", 1, 336, 48)
    penalty_rate = opt_int(body, "sla_penalty_rate_cents_per_hour", 0, None, 2500)
    penalty_cap = opt_int(body, "sla_penalty_cap_cents", 0, None, 500000)
    dr_required = opt_bool(body, "dr_readiness_required", True)
    tolerance = opt_int(body, "control_total_tolerance_bp", 0, 10000, 5)
    status = opt_enum(body, "status", calc.CLIENT_STATUSES, "ACTIVE")
    for row in DB.clients.values():
        if row["client_code"] == client_code:
            fail("ERR_DUPLICATE_CODE", "client_code %s already exists" % client_code)
    row = base_row()
    row.update({
        "client_code": client_code,
        "name": name,
        "sla_turnaround_hours": turnaround,
        "sla_penalty_rate_cents_per_hour": penalty_rate,
        "sla_penalty_cap_cents": penalty_cap,
        "dr_readiness_required": dr_required,
        "control_total_tolerance_bp": tolerance,
        "status": status,
        "postage_deposited_cents": 0,
        "postage_committed_cents": 0,
        "postage_escrow_available_cents": 0,
        "paperless_sync_epoch": 0,
        "pending_address_feedback_count": 0,
        "address_feedback_batch_count": 0,
    })
    DB.clients[row["id"]] = row
    return respond(client_view(row), 201)


@bp.route("/bureau/clients/<client_id>", methods=["GET"])
def client_read(client_id):
    require_auth(ALL_ROLES)
    row = domain.client_or_404(client_id)
    return respond(client_view(row), 200)


@bp.route("/bureau/clients", methods=["GET"])
def client_list():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    status = filter_value("status", calc.CLIENT_STATUSES)
    rows = [r for r in DB.clients.values() if status is None or r["status"] == status]
    rows = sorted_rows(rows, lambda r: (r["client_code"],))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.route("/bureau/clients/<client_id>", methods=["PATCH"])
def client_amend(client_id):
    require_auth((ROLE_BUREAU_ADMIN,))
    body = json_body()
    name = opt_str(body, "name", 1, 120)
    turnaround = opt_int(body, "sla_turnaround_hours", 1, 336)
    penalty_rate = opt_int(body, "sla_penalty_rate_cents_per_hour", 0, None)
    penalty_cap = opt_int(body, "sla_penalty_cap_cents", 0, None)
    dr_required = opt_bool(body, "dr_readiness_required")
    tolerance = opt_int(body, "control_total_tolerance_bp", 0, 10000)
    status = opt_enum(body, "status", calc.CLIENT_STATUSES)
    row = domain.client_or_404(client_id)
    if name is not None:
        row["name"] = name
    if turnaround is not None:
        row["sla_turnaround_hours"] = turnaround
    if penalty_rate is not None:
        row["sla_penalty_rate_cents_per_hour"] = penalty_rate
    if penalty_cap is not None:
        row["sla_penalty_cap_cents"] = penalty_cap
    if dr_required is not None:
        row["dr_readiness_required"] = dr_required
    if tolerance is not None:
        row["control_total_tolerance_bp"] = tolerance
    if status is not None:
        row["status"] = status
    touch(row)
    return respond(client_view(row), 200)


@bp.route("/bureau/clients/<client_id>/postage-deposits", methods=["POST"])
def client_postage_deposit(client_id):
    require_auth((ROLE_POSTAGE_CONTROLLER,))
    body = json_body()
    amount = req_int(body, "amount_cents", 0, None)
    opt_str(body, "reference")
    row = domain.client_or_404(client_id)
    if row["status"] == "SUSPENDED":
        fail("ERR_CLIENT_SUSPENDED", "client is SUSPENDED and may not take postage deposits")
    row["postage_deposited_cents"] = row["postage_deposited_cents"] + amount
    row["postage_escrow_available_cents"] = row["postage_escrow_available_cents"] + amount
    touch(row)
    return respond(client_view(row), 200)


@bp.route("/bureau/clients/<client_id>/paperless-sync", methods=["POST"])
def client_paperless_sync(client_id):
    require_auth((ROLE_CLIENT_LIAISON,))
    body = json_body()
    refs = req_str_list(body, "confirm_pending_account_refs")
    row = domain.client_or_404(client_id)
    row["paperless_sync_epoch"] = row["paperless_sync_epoch"] + 1
    touch(row)
    epoch = row["paperless_sync_epoch"]
    confirmed = set(refs)
    rows = sorted_rows(domain.enrollments_of_client(client_id), lambda e: (e["account_ref"],))
    for enrollment in rows:
        if enrollment["status"] == "PENDING" and enrollment["account_ref"] in confirmed:
            enrollment["status"] = "ENROLLED"
            enrollment["enrolled_epoch"] = epoch
            enrollment["confirmed_at"] = now()
            enrollment["suppression_effective"] = True
            touch(enrollment)
    return respond(client_view(row), 200)


@bp.route("/bureau/clients/<client_id>/address-feedback", methods=["POST"])
def client_address_feedback(client_id):
    require_auth((ROLE_CLIENT_LIAISON,))
    body = json_body()
    opt_str(body, "note")
    client = domain.client_or_404(client_id)
    pending = []
    for ret in DB.returns.values():
        if ret["disposition"] not in ("ADDRESS_UPDATED", "UNRESOLVED"):
            continue
        owner = domain.client_of_return(ret)
        if owner is None:
            continue
        if owner["id"] != client_id:
            continue
        pending.append(ret)
    if not pending:
        fail("ERR_NO_PENDING_FEEDBACK", "client has no classified undeliverable returns to release")
    seq = client["address_feedback_batch_count"] + 1
    stamp = now()
    for ret in sorted_rows(pending, lambda r: (r["created_at"],)):
        ret["disposition"] = "FEEDBACK_SENT"
        ret["feedback_sent_at"] = stamp
        ret["feedback_batch_seq"] = seq
        touch(ret)
        piece = DB.pieces.get(ret["mail_piece_id"])
        record = DB.records.get(piece["statement_record_id"]) if piece else None
        if record is not None:
            domain.apply_changes(record, {"address_update_pending": False})
    client["address_feedback_batch_count"] = seq
    client["pending_address_feedback_count"] = 0
    touch(client)
    return respond(client_view(client), 200)


@bp.route("/bureau/clients/<client_id>/composition-templates", methods=["GET"])
def client_templates(client_id):
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    status = filter_value("status", calc.TEMPLATE_STATUSES)
    domain.client_or_404(client_id)
    rows = [t for t in DB.templates.values() if t["client_id"] == client_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    rows = sorted_rows(rows, lambda t: (t["template_code"], t["version_no"]))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.route("/bureau/clients/<client_id>/data-files", methods=["GET"])
def client_data_files(client_id):
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    status = filter_value("status", calc.FILE_STATUSES)
    domain.client_or_404(client_id)
    rows = [f for f in DB.files.values() if f["client_id"] == client_id]
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    rows = sorted_rows(rows, lambda f: (f["created_at"],))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.route("/bureau/clients/<client_id>/paperless-enrollments", methods=["GET"])
def client_enrollments(client_id):
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    status = filter_value("status", calc.ENROLLMENT_STATUSES)
    domain.client_or_404(client_id)
    rows = domain.enrollments_of_client(client_id)
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows = sorted_rows(rows, lambda e: (e["account_ref"],))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


# --------------------------------------------------------------------------- composition templates
def _parse_variable_content_rules(body):
    if "variable_content_rules" not in body or body["variable_content_rules"] is None:
        return []
    value = body["variable_content_rules"]
    if not isinstance(value, list):
        invalid("field 'variable_content_rules' must be an array")
    out = []
    seen = set()
    for entry in value:
        if not isinstance(entry, dict):
            invalid("each variable content rule must be an object")
        for member in ("rule_code", "threshold_amount_cents", "add_sheets", "required_insert_code"):
            if member not in entry:
                invalid("variable content rule is missing member '%s'" % member)
        rule_code = entry["rule_code"]
        if not isinstance(rule_code, str) or rule_code == "":
            invalid("variable content rule 'rule_code' must be a non-empty string")
        threshold = entry["threshold_amount_cents"]
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
            invalid("variable content rule 'threshold_amount_cents' must be a non-negative integer")
        add_sheets = entry["add_sheets"]
        if isinstance(add_sheets, bool) or not isinstance(add_sheets, int) or add_sheets < 0:
            invalid("variable content rule 'add_sheets' must be a non-negative integer")
        required_code = entry["required_insert_code"]
        if required_code is not None and not isinstance(required_code, str):
            invalid("variable content rule 'required_insert_code' must be a string or null")
        if rule_code in seen:
            invalid("variable content rule 'rule_code' values must be unique")
        seen.add(rule_code)
        out.append({
            "rule_code": rule_code,
            "threshold_amount_cents": threshold,
            "add_sheets": add_sheets,
            "required_insert_code": required_code,
        })
    return out


def template_insert_codes(template):
    codes = list(template.get("required_insert_codes") or [])
    for rule in template.get("variable_content_rules") or []:
        if rule.get("required_insert_code") is not None:
            codes.append(rule["required_insert_code"])
    ordered = []
    for code in codes:
        if code not in ordered:
            ordered.append(code)
    return ordered


@bp.route("/bureau/composition-templates", methods=["POST"])
def template_create():
    require_auth((ROLE_BUREAU_ADMIN,))
    body = json_body()
    client_id = req_str(body, "client_id")
    template_code = req_str(body, "template_code", 1, 30)
    version_no = req_int(body, "version_no", 1, None)
    duplex_required = req_bool(body, "duplex_required")
    sheets_per_document = req_int(body, "sheets_per_document", 1, 200)
    color_pages = opt_int(body, "color_pages_per_document", 0, None, 0)
    mail_class_preference = opt_enum(body, "mail_class_preference", calc.MAIL_CLASS_PREFERENCES, "FIRST_CLASS")
    required_insert_codes = opt_str_list(body, "required_insert_codes", allow_duplicates=False, default=[])
    rules = _parse_variable_content_rules(body)
    domain.client_or_404(client_id)
    for row in DB.templates.values():
        if (row["client_id"] == client_id and row["template_code"] == template_code
                and row["version_no"] == version_no):
            fail("ERR_DUPLICATE_CODE", "template version already exists for this client")
    row = base_row()
    row.update({
        "client_id": client_id,
        "template_code": template_code,
        "version_no": version_no,
        "status": "DRAFT",
        "duplex_required": duplex_required,
        "sheets_per_document": sheets_per_document,
        "color_pages_per_document": color_pages,
        "mail_class_preference": mail_class_preference,
        "required_insert_codes": list(required_insert_codes),
        "variable_content_rules": rules,
        "activated_at": None,
        "retired_at": None,
    })
    known = domain.insert_by_code()
    for code in template_insert_codes(row):
        if code not in known:
            fail("ERR_INSERT_CODE_UNKNOWN", "insert code %s does not exist" % code)
    DB.templates[row["id"]] = row
    return respond(serialize(row), 201)


@bp.route("/bureau/composition-templates/<template_id>", methods=["GET"])
def template_read(template_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.template_or_404(template_id)), 200)


@bp.route("/bureau/composition-templates/<template_id>/activate", methods=["POST"])
def template_activate(template_id):
    require_auth((ROLE_BUREAU_ADMIN,))
    json_body()
    row = domain.template_or_404(template_id)
    siblings = [
        t for t in DB.templates.values()
        if t["client_id"] == row["client_id"] and t["template_code"] == row["template_code"]
        and t["id"] != row["id"]
    ]
    if row["status"] != "DRAFT":
        fail("ERR_TEMPLATE_INVALID_STATE", "only a DRAFT template version may be activated")
    for sibling in siblings:
        if sibling["status"] == "ACTIVE" and sibling["version_no"] > row["version_no"]:
            fail("ERR_TEMPLATE_INVALID_STATE", "a higher version is already ACTIVE in this family")
    row["status"] = "ACTIVE"
    row["activated_at"] = now()
    touch(row)
    for sibling in sorted_rows(siblings, lambda t: (t["version_no"],)):
        if sibling["status"] == "ACTIVE" and sibling["version_no"] < row["version_no"]:
            sibling["status"] = "RETIRED"
            sibling["retired_at"] = now()
            touch(sibling)
    return respond(serialize(row), 200)


# --------------------------------------------------------------------------- insert stock
@bp.route("/bureau/insert-stocks", methods=["POST"])
def insert_create():
    require_auth((ROLE_BUREAU_ADMIN,))
    body = json_body()
    insert_code = req_str(body, "insert_code", 1, 30)
    description = req_str(body, "description")
    jurisdiction_code = req_str(body, "jurisdiction_code")
    effective_from = req_dt(body, "effective_from")
    effective_to = opt_dt(body, "effective_to")
    sheets_per_insert = opt_int(body, "sheets_per_insert", 1, None, 1)
    received_count = req_int(body, "received_count", 0, None)
    status = opt_enum(body, "status", calc.INSERT_STATUSES, "ACTIVE")
    for row in DB.inserts.values():
        if row["insert_code"] == insert_code:
            fail("ERR_DUPLICATE_CODE", "insert_code %s already exists" % insert_code)
    row = base_row()
    row.update({
        "insert_code": insert_code,
        "description": description,
        "jurisdiction_code": jurisdiction_code,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "sheets_per_insert": sheets_per_insert,
        "received_count": received_count,
        "on_hand_count": received_count,
        "reserved_count": 0,
        "consumed_count": 0,
        "status": status,
    })
    DB.inserts[row["id"]] = row
    return respond(serialize(row), 201)


@bp.route("/bureau/insert-stocks/<insert_id>", methods=["GET"])
def insert_read(insert_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.find(DB.inserts, insert_id, "ERR_INSERT_STOCK_NOT_FOUND")), 200)


@bp.route("/bureau/insert-stocks", methods=["GET"])
def insert_list():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    status = filter_value("status", calc.INSERT_STATUSES)
    jurisdiction = filter_value("jurisdiction_code")
    rows = list(DB.inserts.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if jurisdiction is not None:
        rows = [r for r in rows if r["jurisdiction_code"] == jurisdiction]
    rows = sorted_rows(rows, lambda r: (r["insert_code"],))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


# --------------------------------------------------------------------------- press lines
@bp.route("/bureau/press-lines", methods=["POST"])
def press_line_create():
    require_auth((ROLE_BUREAU_ADMIN,))
    body = json_body()
    line_code = req_str(body, "line_code", 1, 20)
    capabilities = req_str_list(body, "capabilities", allow_duplicates=False)
    if not capabilities:
        invalid("field 'capabilities' must not be empty")
    for cap in capabilities:
        if cap not in calc.PRESS_CAPABILITIES:
            invalid("field 'capabilities' entries must be one of DUPLEX, COLOR, INSERT")
    sheets_per_hour = req_int(body, "sheets_per_hour", 1, None)
    daily_sheet_capacity = req_int(body, "daily_sheet_capacity", 1, None)
    changeover = opt_int(body, "changeover_buffer_minutes", 0, 480, 30)
    status = opt_enum(body, "status", calc.PRESS_LINE_STATUSES, "AVAILABLE")
    for row in DB.lines.values():
        if row["line_code"] == line_code:
            fail("ERR_DUPLICATE_CODE", "line_code %s already exists" % line_code)
    row = base_row()
    row.update({
        "line_code": line_code,
        "capabilities": list(capabilities),
        "sheets_per_hour": sheets_per_hour,
        "changeover_buffer_minutes": changeover,
        "daily_sheet_capacity": daily_sheet_capacity,
        "committed_sheet_count": 0,
        "utilization_bp": 0,
        "status": status,
    })
    DB.lines[row["id"]] = row
    return respond(serialize(row), 201)


@bp.route("/bureau/press-lines/<line_id>", methods=["GET"])
def press_line_read(line_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.line_or_404(line_id)), 200)


@bp.route("/bureau/press-lines", methods=["GET"])
def press_line_list():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    status = filter_value("status", calc.PRESS_LINE_STATUSES)
    rows = list(DB.lines.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows, lambda r: (r["line_code"],))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


# --------------------------------------------------------------------------- entry facilities
@bp.route("/bureau/entry-facilities", methods=["POST"])
def facility_create():
    require_auth((ROLE_BUREAU_ADMIN,))
    body = json_body()
    facility_code = req_str(body, "facility_code", 1, 20)
    facility_type = req_enum(body, "facility_type", calc.FACILITY_TYPES)
    tray_capacity = req_int(body, "tray_capacity_per_window", 1, None)
    discount_first = req_int(body, "discount_bp_first_class", 0, 10000)
    discount_marketing = req_int(body, "discount_bp_marketing", 0, 10000)
    status = opt_enum(body, "status", calc.FACILITY_STATUSES, "OPEN")
    for row in DB.facilities.values():
        if row["facility_code"] == facility_code:
            fail("ERR_DUPLICATE_CODE", "facility_code %s already exists" % facility_code)
    row = base_row()
    row.update({
        "facility_code": facility_code,
        "facility_type": facility_type,
        "tray_capacity_per_window": tray_capacity,
        "discount_bp_first_class": discount_first,
        "discount_bp_marketing": discount_marketing,
        "committed_tray_count": 0,
        "status": status,
    })
    DB.facilities[row["id"]] = row
    return respond(serialize(row), 201)


@bp.route("/bureau/entry-facilities/<facility_id>", methods=["GET"])
def facility_read(facility_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.facility_or_404(facility_id)), 200)


# --------------------------------------------------------------------------- DR site
def drsite_view(row):
    status, valid_until = calc.dr_readiness(row)
    row["readiness_status"] = status
    row["readiness_valid_until"] = valid_until
    return serialize(row)


@bp.route("/bureau/dr-sites", methods=["POST"])
def drsite_create():
    require_auth((ROLE_BUREAU_ADMIN,))
    body = json_body()
    site_code = req_str(body, "site_code", 1, None)
    lag = req_int(body, "replication_lag_minutes", 0, None)
    if DB.drsites:
        fail("ERR_DR_SITE_ALREADY_EXISTS", "a disaster-recovery site already exists")
    row = base_row()
    row.update({
        "site_code": site_code,
        "replication_lag_minutes": lag,
        "last_drill_at": None,
        "last_drill_result": "NONE",
        "drill_count": 0,
        "readiness_status": "UNTESTED",
        "readiness_valid_until": None,
    })
    DB.drsites[row["id"]] = row
    return respond(drsite_view(row), 201)


@bp.route("/bureau/dr-sites/<site_id>", methods=["GET"])
def drsite_read(site_id):
    require_auth(ALL_ROLES)
    return respond(drsite_view(domain.drsite_or_404(site_id)), 200)


@bp.route("/bureau/dr-sites/<site_id>/drills", methods=["POST"])
def drsite_drill(site_id):
    require_auth((ROLE_BUREAU_ADMIN,))
    body = json_body()
    result = req_enum(body, "result", calc.DRILL_RESULTS)
    row = domain.drsite_or_404(site_id)
    row["last_drill_at"] = now()
    row["last_drill_result"] = result
    row["drill_count"] = row["drill_count"] + 1
    touch(row)
    return respond(drsite_view(row), 200)


@bp.route("/bureau/dr-sites/<site_id>", methods=["PATCH"])
def drsite_patch(site_id):
    require_auth((ROLE_BUREAU_ADMIN,))
    body = json_body()
    lag = req_int(body, "replication_lag_minutes", 0, None)
    row = domain.drsite_or_404(site_id)
    row["replication_lag_minutes"] = lag
    touch(row)
    return respond(drsite_view(row), 200)
