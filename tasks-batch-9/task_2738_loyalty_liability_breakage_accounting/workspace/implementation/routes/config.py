"""StateExpiryRule, Cohort and Member endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import lookup
import serialize
from auth import (ROLE_CONTROLLER, ROLE_LOYALTY_ACCOUNTANT, ROLE_MEMBER,
                  ROLE_PROGRAM_ADMIN, authorize, require_member_owns)
from errors import ApiError
from response import created, ok, paginate
from util import clock
from validate import (bad, field_bool, field_code, field_datetime, field_enum,
                      field_int, field_ref, field_string, json_body)

bp = Blueprint("config", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)
TIERS = ("BASE", "SILVER", "GOLD", "PLATINUM")


def duplicate_code():
    return ApiError("ERR_DUPLICATE_CODE", 409)


# --- StateExpiryRule --------------------------------------------------------

@bp.route("/state-expiry-rules", methods=["POST"])
def create_state_expiry_rule():
    authorize(ROLE_PROGRAM_ADMIN)
    body = json_body()
    program_id = field_ref(body, "program_id")
    state_code = field_code(body, "state_code", 2)
    expiry_permitted = field_bool(body, "expiry_permitted")
    min_dormancy_days = field_int(body, "min_dormancy_days", minimum=0, maximum=3650)
    escheatment_required = field_bool(body, "escheatment_required")
    escheat_rate_bp = field_int(body, "escheat_rate_bp", required=False,
                                default=10000, minimum=0, maximum=10000)
    lookup.program(program_id)
    for rule in db.store.state_expiry_rules.values():
        if rule["program_id"] == program_id and rule["state_code"] == state_code:
            raise duplicate_code()
    rec = db.new_record(db.store.state_expiry_rules, {
        "program_id": program_id,
        "state_code": state_code,
        "expiry_permitted": expiry_permitted,
        "min_dormancy_days": min_dormancy_days,
        "escheatment_required": escheatment_required,
        "escheat_rate_bp": escheat_rate_bp,
    })
    return created(serialize.state_expiry_rule(rec))


@bp.route("/state-expiry-rules", methods=["GET"])
def list_state_expiry_rules():
    authorize(*READ_ROLES)
    rows = lookup.filtered(db.rows(db.store.state_expiry_rules),
                           "program_id", "state_code", "expiry_permitted")
    return paginate(rows, serialize.state_expiry_rule)


@bp.route("/state-expiry-rules/<rule_id>", methods=["GET"])
def read_state_expiry_rule(rule_id):
    authorize(*READ_ROLES)
    return ok(serialize.state_expiry_rule(lookup.state_expiry_rule(rule_id)))


# --- Cohort -----------------------------------------------------------------

@bp.route("/cohorts", methods=["POST"])
def create_cohort():
    authorize(ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT)
    body = json_body()
    program_id = field_ref(body, "program_id")
    cohort_code = field_string(body, "cohort_code", max_length=32)
    start = field_datetime(body, "enrollment_start_date")
    end = field_datetime(body, "enrollment_end_date")
    observed = field_int(body, "observed_redemption_rate_bp", minimum=0, maximum=10000)
    sample_size = field_int(body, "sample_size", minimum=1)
    adjustment = field_int(body, "program_change_adjustment_bp", required=False,
                           default=0, minimum=-5000, maximum=5000)
    if not end > start:
        raise bad("enrollment_end_date must fall strictly after enrollment_start_date.")
    lookup.program(program_id)
    for cohort in db.store.cohorts.values():
        if cohort["program_id"] == program_id and cohort["cohort_code"] == cohort_code:
            raise duplicate_code()
    rec = db.new_record(db.store.cohorts, {
        "program_id": program_id,
        "cohort_code": cohort_code,
        "enrollment_start_date": start,
        "enrollment_end_date": end,
        "observed_redemption_rate_bp": observed,
        "sample_size": sample_size,
        "program_change_adjustment_bp": adjustment,
    })
    return created(serialize.cohort(rec))


@bp.route("/cohorts", methods=["GET"])
def list_cohorts():
    authorize(*READ_ROLES)
    rows = lookup.filtered(db.rows(db.store.cohorts), "program_id", "cohort_code")
    return paginate(rows, serialize.cohort)


@bp.route("/cohorts/<cohort_id>", methods=["GET"])
def read_cohort(cohort_id):
    authorize(*READ_ROLES)
    return ok(serialize.cohort(lookup.cohort(cohort_id)))


# --- Member -----------------------------------------------------------------

@bp.route("/members", methods=["POST"])
def create_member():
    authorize(ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT)
    body = json_body()
    program_id = field_ref(body, "program_id")
    cohort_id = field_ref(body, "cohort_id")
    external_ref = field_string(body, "external_member_ref", max_length=64)
    state_code = field_code(body, "state_code", 2)
    tier = field_enum(body, "tier", TIERS, required=False, default="BASE")
    lookup.program(program_id)
    cohort = lookup.cohort(cohort_id)
    if cohort["program_id"] != program_id:
        raise ApiError("ERR_COHORT_PROGRAM_MISMATCH", 409)
    for member in db.store.members.values():
        if (member["program_id"] == program_id
                and member["external_member_ref"] == external_ref):
            raise duplicate_code()
    now = clock.now()
    rec = db.new_record(db.store.members, {
        "program_id": program_id,
        "cohort_id": cohort_id,
        "external_member_ref": external_ref,
        "state_code": state_code,
        "tier": tier,
        "status": "ACTIVE",
        "enrolled_at": now,
        "last_activity_at": now,
    })
    return created(serialize.member(rec))


@bp.route("/members", methods=["GET"])
def list_members():
    authorize(*READ_ROLES)
    rows = lookup.filtered(db.rows(db.store.members), "program_id", "cohort_id",
                           "status", "state_code", "tier")
    return paginate(rows, serialize.member)


@bp.route("/members/<member_id>", methods=["GET"])
def read_member(member_id):
    user_id, role = authorize(*READ_ROLES, ROLE_MEMBER)
    member = lookup.member(member_id)
    require_member_owns(user_id, role, member["id"])
    return ok(serialize.member(member))
