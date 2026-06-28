"""Program endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_OPEN_BATCH_EXISTS,
)
from middleware import get_user_context, require_role
from response import object_response
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_int,
    require_number,
    optional_bool,
    stamp_create,
    touch,
    serialize,
    find_or_404,
)

bp = Blueprint("programs", __name__)

# Program configuration defaults (PRD §3.1 / scaffold §1.1).
PROGRAM_DEFAULTS = {
    "match_ratio": 0.5,
    "tiered_matching_enabled": False,
    "tier_1_ceiling_cents": 50000,
    "tier_1_rate": 1.0,
    "tier_2_rate": 0.5,
    "annual_match_cap_cents": 100000,
    "dfd_rate_cents_per_hour": 1500,
    "dfd_annual_cap_cents": 25000,
    "roundup_enabled": False,
    "processing_fee_tier_threshold_cents": 5000,
    "processing_fee_low_rate": 0.02,
    "processing_fee_high_rate": 0.03,
    "disbursement_admin_fee_rate": 0.025,
}

_NUMBER_FIELDS = {
    "match_ratio", "tier_1_rate", "tier_2_rate", "processing_fee_low_rate",
    "processing_fee_high_rate", "disbursement_admin_fee_rate",
}
_INT_FIELDS = {
    "tier_1_ceiling_cents", "annual_match_cap_cents", "dfd_rate_cents_per_hour",
    "dfd_annual_cap_cents", "processing_fee_tier_threshold_cents",
}
_BOOL_FIELDS = {"tiered_matching_enabled", "roundup_enabled"}


@bp.route("/programs", methods=["POST"])
def create_program():
    _uid, role = get_user_context()
    require_role(role, {"ProgramManager"})
    body = get_json_body()
    require_fields(body, ["name", "tax_year"])
    name = require_string(body, "name")
    tax_year = require_int(body, "tax_year")

    rec = {
        "name": name,
        "tax_year": tax_year,
    }
    for field, default in PROGRAM_DEFAULTS.items():
        if field in body and body[field] is not None:
            if field in _NUMBER_FIELDS:
                val = require_number(body, field)
            elif field in _INT_FIELDS:
                val = require_int(body, field)
            elif field in _BOOL_FIELDS:
                val = optional_bool(body, field, default)
            else:
                val = body[field]
            rec[field] = val
        else:
            rec[field] = default

    # match_ratio constraint 0 <= match_ratio <= 4.0 (PRD §3.1)
    if not (0 <= rec["match_ratio"] <= 4.0):
        raise err(("ERR_INVALID_REQUEST", 422), "match_ratio must be between 0 and 4.0 inclusive")

    rec["status"] = "DRAFT"
    stamp_create(rec)
    db.programs[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    rec = find_or_404(db.programs, program_id)
    return object_response(serialize(rec), 200)


@bp.route("/programs/<program_id>/activate", methods=["POST"])
def activate_program(program_id):
    _uid, role = get_user_context()
    require_role(role, {"ProgramManager"})
    rec = find_or_404(db.programs, program_id)
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Program must be DRAFT to activate")
    rec["status"] = "ACTIVE"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/programs/<program_id>/close", methods=["POST"])
def close_program(program_id):
    _uid, role = get_user_context()
    require_role(role, {"ProgramManager"})
    rec = find_or_404(db.programs, program_id)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Program must be ACTIVE to close")
    # No DisbursementBatch under this program in {OPEN, LOCKED}.
    for b in db.disbursement_batches.values():
        if b["program_id"] == program_id and b["status"] in ("OPEN", "LOCKED"):
            raise err(ERR_OPEN_BATCH_EXISTS,
                      "Cannot close a program with an OPEN or LOCKED disbursement batch")
    rec["status"] = "CLOSED"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/programs/<program_id>/impact-report", methods=["GET"])
def impact_report(program_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager"})
    find_or_404(db.programs, program_id)

    # total donated: settled donations' base_amount_cents
    total_donated = 0
    donor_ids = set()
    for d in db.donations.values():
        if d["program_id"] != program_id:
            continue
        if d["status"] == "SETTLED":
            total_donated += d["base_amount_cents"]
            donor_ids.add(d["employee_id"])

    # total matched: SETTLED matching gifts' matched_amount_cents
    total_matched = 0
    for m in db.matching_gifts.values():
        if m["program_id"] != program_id:
            continue
        if m["status"] == "SETTLED":
            total_matched += m["matched_amount_cents"]

    # total dollars-for-doers: SETTLED volunteer logs' grant_amount_cents
    total_dfd = 0
    for log in db.volunteer_logs.values():
        if log["program_id"] != program_id:
            continue
        if log["status"] == "SETTLED":
            total_dfd += log["grant_amount_cents"]

    # total net disbursed: SETTLED grants' net_amount_cents; distinct charities
    total_disbursed_net = 0
    charity_ids = set()
    for g in db.grants.values():
        if g["program_id"] != program_id:
            continue
        if g["status"] == "SETTLED":
            total_disbursed_net += g["net_amount_cents"]
            charity_ids.add(g["charity_id"])

    report = {
        "total_donated_cents": total_donated,
        "total_matched_cents": total_matched,
        "total_dfd_cents": total_dfd,
        "total_disbursed_net_cents": total_disbursed_net,
        "charity_count": len(charity_ids),
        "donor_count": len(donor_ids),
    }
    return object_response(report, 200)
