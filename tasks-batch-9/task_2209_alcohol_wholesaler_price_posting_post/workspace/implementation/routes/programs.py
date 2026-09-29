"""State programs, wholesalers and licensee users (PRD section 3.1)."""

from flask import Blueprint

import calc
from auth import ALL_ROLES, ROLE_COMPLIANCE_OFFICER, authenticate
from envelope import object_response
from serialize import out
from store import bump_if_changed, db, new_record, snapshot
from validators import (
    Field,
    collection_response,
    must_find,
    query_enum,
    validate_body,
)

bp = Blueprint("programs", __name__)

LICENSE_STATUSES = ("ACTIVE", "SUSPENDED")
USER_ROLES = ("FILING_AGENT", "CERTIFYING_OFFICER", "DUAL_ROLE")

PROGRAM_FIELDS = [
    Field("state_code", "string"),
    Field("program_name", "string"),
    Field("posting_deadline_day", "int", required=False, default=10, minimum=1, maximum=28),
    Field("hold_window_days", "int", required=False, default=3, minimum=1),
    Field("correction_window_days", "int", required=False, default=15, minimum=1),
    Field("combo_cooldown_days", "int", required=False, default=7, minimum=0),
    Field("quantity_discount_allowed", "bool", required=False, default=True),
    Field("combination_sale_allowed", "bool", required=False, default=True),
    Field(
        "max_quantity_discount_pct",
        "number",
        required=False,
        default=0.15,
        minimum=0,
        maximum=1,
    ),
    Field(
        "max_promotional_allowance_pct",
        "number",
        required=False,
        default=0.05,
        minimum=0,
        maximum=1,
    ),
    Field(
        "depletion_allowance_per_case_cents",
        "int",
        required=False,
        default=150,
        minimum=0,
    ),
    Field("late_filing_penalty_cents", "int", required=False, default=250000, minimum=0),
    Field(
        "repeat_correction_penalty_cents", "int", required=False, default=100000, minimum=0
    ),
    Field(
        "frivolous_amendment_penalty_cents",
        "int",
        required=False,
        default=75000,
        minimum=0,
    ),
    Field(
        "off_posted_penalty_rate_pct",
        "number",
        required=False,
        default=0.40,
        minimum=0,
        maximum=1,
    ),
    Field("max_corrections_per_schedule", "int", required=False, default=2, minimum=1),
]


# ---------------------------------------------------------------------------
# state programs
# ---------------------------------------------------------------------------
@bp.post("/state-programs")
def create_state_program():
    authenticate([ROLE_COMPLIANCE_OFFICER])
    values = validate_body(PROGRAM_FIELDS)
    record = new_record(dict(values))
    db.state_programs[record["id"]] = record
    return object_response(out(record), 201)


@bp.get("/state-programs/<record_id>")
def get_state_program(record_id):
    authenticate(ALL_ROLES)
    record = must_find("state_program", record_id)
    return object_response(out(record))


@bp.get("/state-programs")
def list_state_programs():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.state_programs.values()), {"state_code": None}, out
    )


# ---------------------------------------------------------------------------
# wholesalers
# ---------------------------------------------------------------------------
def _new_wholesaler(values):
    return new_record(
        {
            "license_number": values["license_number"],
            "legal_name": values["legal_name"],
            "state_program_id": values["state_program_id"],
            "license_status": values["license_status"],
            "late_filing_penalty_accrued_cents": 0,
            "correction_penalty_accrued_cents": 0,
            "amendment_penalty_accrued_cents": 0,
            "assessed_penalty_cents": 0,
            "penalty_exposure_cents": 0,
            "late_filing_count": 0,
            "frivolous_amendment_count": 0,
            "off_posted_violation_count": 0,
            "open_audit_count": 0,
        }
    )


@bp.post("/wholesalers")
def create_wholesaler():
    authenticate([ROLE_COMPLIANCE_OFFICER])
    values = validate_body(
        [
            Field("license_number", "string"),
            Field("legal_name", "string"),
            Field("state_program_id", "string"),
            Field(
                "license_status",
                "string",
                required=False,
                default="ACTIVE",
                enum=LICENSE_STATUSES,
            ),
        ]
    )
    must_find("state_program", values["state_program_id"])
    record = _new_wholesaler(values)
    db.wholesalers[record["id"]] = record
    return object_response(out(record), 201)


@bp.post("/wholesalers/<record_id>/license-status")
def set_license_status(record_id):
    authenticate([ROLE_COMPLIANCE_OFFICER])
    wholesaler = must_find("wholesaler", record_id)
    values = validate_body(
        [Field("license_status", "string", enum=LICENSE_STATUSES)]
    )
    before = snapshot(wholesaler)
    wholesaler["license_status"] = values["license_status"]
    bump_if_changed(wholesaler, before)
    return object_response(out(wholesaler))


@bp.get("/wholesalers/<record_id>")
def get_wholesaler(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("wholesaler", record_id)))


@bp.get("/wholesalers")
def list_wholesalers():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.wholesalers.values()),
        {"state_program_id": None, "license_status": LICENSE_STATUSES},
        out,
    )


@bp.get("/wholesalers/<record_id>/penalty-exposure")
def wholesaler_penalty_exposure(record_id):
    authenticate(ALL_ROLES)
    wholesaler = must_find("wholesaler", record_id)
    variant = query_enum(
        "variant", ("assessed_exposure", "provisional_exposure"), "assessed_exposure"
    )
    accrued = calc.accrued_exposure(wholesaler)
    provisional = (
        calc.provisional_exposure(wholesaler) if variant == "provisional_exposure" else 0
    )
    return object_response(
        {
            "wholesaler_id": wholesaler["id"],
            "variant": variant,
            "accrued_cents": accrued,
            "provisional_cents": provisional,
            "exposure_cents": accrued + provisional,
        }
    )


# ---------------------------------------------------------------------------
# licensee users
# ---------------------------------------------------------------------------
@bp.post("/licensee-users")
def create_licensee_user():
    authenticate([ROLE_COMPLIANCE_OFFICER])
    values = validate_body(
        [
            Field("wholesaler_id", "string"),
            Field("full_name", "string"),
            Field("user_role", "string", enum=USER_ROLES),
            Field("is_active", "bool", required=False, default=True),
        ]
    )
    must_find("wholesaler", values["wholesaler_id"])
    record = new_record(dict(values))
    db.licensee_users[record["id"]] = record
    return object_response(out(record), 201)


@bp.get("/licensee-users/<record_id>")
def get_licensee_user(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("licensee_user", record_id)))


@bp.get("/licensee-users")
def list_licensee_users():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.licensee_users.values()),
        {"wholesaler_id": None, "user_role": USER_ROLES},
        out,
    )
