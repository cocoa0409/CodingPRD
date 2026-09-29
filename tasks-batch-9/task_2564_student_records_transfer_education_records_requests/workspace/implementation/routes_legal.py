"""Legal demands, retention schedules and certified destruction (PRD 3.9)."""

from flask import Blueprint

import serialize
from common import (API_PREFIX, ROLE_COMPLIANCE_OFFICER, ROLE_LEGAL_AFFAIRS_OFFICER,
                    ROLE_RECORDS_OFFICER, ROLE_SYSTEM_ADMIN, STORE, add_calendar_days, base_row,
                    body, clock_now, err, optional_bool, query_value, require_enum, require_int,
                    require_role, require_string, require_subset, touch, user_id,
                    validation_error)
from derive import append_disclosure, recompute_file
from domain import (COMPONENT_TYPES, COMPONENT_TYPE_ORDER, DEMAND_TYPES, DESTRUCTION_METHODS,
                    NOTIFIED_PARTIES, OPEN_DEMAND_STATUSES, OPEN_REQUEST_STATUSES, WAIVER_BASES,
                    components_of_file, get_legal_demand, get_retention_schedule, get_student,
                    state_rule_for_student)
from response import created, ok, paginate

bp = Blueprint("legal", __name__)

DEMAND_READ_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_OFFICER, ROLE_COMPLIANCE_OFFICER,
                     ROLE_LEGAL_AFFAIRS_OFFICER]
RETENTION_READ_ROLES = DEMAND_READ_ROLES


# --------------------------------------------------------------------------- #
# Legal demands
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/students/<student_id>/legal-demands", methods=["POST"])
def create_legal_demand(student_id):
    get_student(student_id)
    require_role([ROLE_LEGAL_AFFAIRS_OFFICER])
    payload = body()
    demand_type = require_enum(payload, "demand_type", DEMAND_TYPES)
    issuing_authority = require_string(payload, "issuing_authority")
    case_reference = require_string(payload, "case_reference")
    scope = require_subset(payload, "production_scope", COMPONENT_TYPES, COMPONENT_TYPE_ORDER)
    waived = optional_bool(payload, "notification_waived", False)
    waiver_basis = payload.get("waiver_basis")
    if waiver_basis is not None and waiver_basis not in WAIVER_BASES:
        validation_error("Field 'waiver_basis' must be a supported basis.")

    if waived and waiver_basis is None:
        err("ERR_WAIVER_BASIS_REQUIRED", 400, "A waived demand must carry a waiver basis.")
    if not waived and waiver_basis is not None:
        err("ERR_WAIVER_BASIS_REQUIRED", 400,
            "A non-waived demand must not carry a waiver basis.")
    if waiver_basis == "GRAND_JURY_ORDER" and demand_type != "GRAND_JURY_SUBPOENA":
        err("ERR_WAIVER_BASIS_REQUIRED", 400,
            "GRAND_JURY_ORDER is only accepted with a grand jury subpoena.")
    if waiver_basis == "EX_PARTE_COURT_ORDER" and demand_type != "EX_PARTE_ORDER":
        err("ERR_WAIVER_BASIS_REQUIRED", 400,
            "EX_PARTE_COURT_ORDER is only accepted with an ex parte order.")

    row = base_row()
    row.update({
        "student_id": student_id,
        "demand_type": demand_type,
        "issuing_authority": issuing_authority,
        "case_reference": case_reference,
        "production_scope": scope,
        "notification_waived": waived,
        "waiver_basis": waiver_basis,
        "status": "RECEIVED",
        "received_at": clock_now(),
        "notified_party": None,
        "notification_sent_at": None,
        "production_allowed_at": None,
        "produced_at": None,
        "produced_page_count": None,
    })
    STORE.legal_demands[row["id"]] = row
    return created(serialize.legal_demand(row))


@bp.route(API_PREFIX + "/students/<student_id>/legal-demands", methods=["GET"])
def list_legal_demands(student_id):
    get_student(student_id)
    require_role(DEMAND_READ_ROLES)
    rows = [row for row in STORE.legal_demands.values() if row["student_id"] == student_id]
    for name in ("demand_type", "status"):
        value = query_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    return paginate(rows, serialize.legal_demand)


@bp.route(API_PREFIX + "/legal-demands/<demand_id>", methods=["GET"])
def get_one_legal_demand(demand_id):
    row = get_legal_demand(demand_id)
    require_role(DEMAND_READ_ROLES)
    return ok(serialize.legal_demand(row))


@bp.route(API_PREFIX + "/legal-demands/<demand_id>/notifications", methods=["POST"])
def notify_family(demand_id):
    row = get_legal_demand(demand_id)
    require_role([ROLE_LEGAL_AFFAIRS_OFFICER])
    payload = body()
    party = require_enum(payload, "notified_party", NOTIFIED_PARTIES)

    if row["status"] == "PRODUCED":
        err("ERR_DEMAND_ALREADY_PRODUCED", 409, "The demand has already been produced.")
    if row["status"] != "RECEIVED":
        err("ERR_DEMAND_NOT_RECEIVED", 409, "The demand is no longer awaiting notification.")
    if row["notification_waived"]:
        err("ERR_NOTIFICATION_WAIVED", 409, "Notification is waived for this demand.")

    now = clock_now()
    student = STORE.students.get(row["student_id"])
    rule = state_rule_for_student(student) if student is not None else None
    wait_days = int(rule["notification_wait_days"]) if rule else 0
    row["notified_party"] = party
    row["notification_sent_at"] = now
    row["production_allowed_at"] = add_calendar_days(now, wait_days)
    row["status"] = "NOTIFIED"
    touch(row)
    return ok(serialize.legal_demand(row))


@bp.route(API_PREFIX + "/legal-demands/<demand_id>/production", methods=["POST"])
def produce_demand(demand_id):
    row = get_legal_demand(demand_id)
    require_role([ROLE_LEGAL_AFFAIRS_OFFICER])
    payload = body()
    page_count = require_int(payload, "produced_page_count", 0)

    if row["status"] == "PRODUCED":
        err("ERR_DEMAND_ALREADY_PRODUCED", 409, "The demand has already been produced.")

    now = clock_now()
    if row["status"] == "NOTIFIED":
        if row["production_allowed_at"] is not None and now < row["production_allowed_at"]:
            err("ERR_NOTIFICATION_WAIT_NOT_ELAPSED", 409,
                "The statutory notification waiting period has not elapsed.")
    else:
        if not (row["notification_waived"] and row["waiver_basis"] is not None):
            err("ERR_NOTIFICATION_REQUIRED", 422,
                "The family must be notified before records are produced.")

    row["status"] = "PRODUCED"
    row["produced_at"] = now
    row["produced_page_count"] = page_count
    touch(row)

    append_disclosure(
        student_id=row["student_id"],
        disclosure_type="LEGAL_DEMAND",
        source_type="LEGAL_DEMAND",
        source_id=row["id"],
        recipient_name=row["issuing_authority"],
        disclosed_categories=row["production_scope"],
        page_count=page_count,
        logged_by_user_id=user_id(),
        legitimate_interest_note=row["case_reference"],
    )
    return ok(serialize.legal_demand(row))


# --------------------------------------------------------------------------- #
# Retention schedules and destruction
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/retention-schedules/<schedule_id>", methods=["GET"])
def get_one_schedule(schedule_id):
    row = get_retention_schedule(schedule_id)
    require_role(RETENTION_READ_ROLES)
    return ok(serialize.retention_schedule(row))


@bp.route(API_PREFIX + "/retention-schedules/<schedule_id>/destruction", methods=["POST"])
def destroy_records(schedule_id):
    row = get_retention_schedule(schedule_id)
    require_role([ROLE_COMPLIANCE_OFFICER])
    payload = body()
    method = require_enum(payload, "destruction_method", DESTRUCTION_METHODS)
    note = require_string(payload, "certification_note")

    if row["status"] == "DESTROYED":
        err("ERR_ALREADY_DESTROYED", 409, "The file has already been destroyed.")
    if row["status"] != "DESTRUCTION_ELIGIBLE":
        err("ERR_RETENTION_NOT_ELIGIBLE", 409,
            "The schedule has not been promoted to destruction eligibility.")

    file_row = STORE.cumulative_files.get(row["cumulative_file_id"])
    student_id = file_row["student_id"] if file_row is not None else None
    for request_row in STORE.records_requests.values():
        if request_row["student_id"] == student_id and request_row["status"] in OPEN_REQUEST_STATUSES:
            err("ERR_DESTRUCTION_HOLD_ACTIVE", 409, "An open records request holds this file.")
    for demand in STORE.legal_demands.values():
        if demand["student_id"] == student_id and demand["status"] in OPEN_DEMAND_STATUSES:
            err("ERR_DESTRUCTION_HOLD_ACTIVE", 409, "A litigation hold is active on this file.")

    row["status"] = "DESTROYED"
    row["destroyed_at"] = clock_now()
    row["destruction_method"] = method
    row["certification_note"] = note
    touch(row)

    if file_row is not None:
        for component in components_of_file(file_row["id"]):
            if int(component["page_count"]) != 0 or int(component["redacted_page_count"]) != 0:
                component["page_count"] = 0
                component["redacted_page_count"] = 0
                component["disclosable_page_count"] = 0
                touch(component)
        recompute_file(file_row)
    return ok(serialize.retention_schedule(row))
