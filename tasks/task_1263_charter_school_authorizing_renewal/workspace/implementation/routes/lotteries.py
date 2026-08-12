"""Enrollment lotteries, entries, preference verification (PRD §3.4)."""
from flask import Blueprint

import db
import errors
from errors import raise_error
from middleware import (
    ALL_ROLES,
    body,
    check_operator_owns,
    require_field,
    require_int,
    require_non_empty_string,
    require_roles,
)
from response import success_object
from routes.common import get_or_404, paginate

bp = Blueprint("lotteries", __name__)

PREFERENCE_CODES = {"SIBLING", "DISTRICT_RESIDENT", "STAFF_CHILD"}
PREFERENCE_WEIGHT = 10


@bp.post("/authorizer/schools/<id>/lotteries")
def create_lottery(id):
    require_roles(["AuthorizerStaff"])
    school = get_or_404("schools", id)
    if school["status"] not in ("PRE_OPENING", "OPEN"):
        raise_error(errors.ERR_SCHOOL_NOT_OPEN, "Lottery creation requires PRE_OPENING or OPEN school")
    data = body()
    academic_year = require_int(data, "academic_year")
    capacity = require_int(data, "capacity")
    if capacity < 0:
        raise_error(errors.ERR_INVALID_REQUEST, "capacity must be >= 0")
    for lot in db.all_records("lotteries"):
        if lot["school_id"] == id and lot["academic_year"] == academic_year:
            raise_error(errors.ERR_DUPLICATE_RECORD, "Duplicate (school, academic_year) lottery")
    record = db.stamp_new({
        "school_id": id,
        "academic_year": academic_year,
        "capacity": capacity,
        "status": "DRAFT",
    })
    db.insert("lotteries", record)
    return success_object(record, 201)


@bp.get("/authorizer/schools/<id>/lotteries")
def list_school_lotteries(id):
    require_roles(ALL_ROLES)
    get_or_404("schools", id)
    records = [l for l in db.all_records("lotteries") if l["school_id"] == id]
    return paginate(records)


@bp.get("/authorizer/lotteries/<id>")
def get_lottery(id):
    require_roles(ALL_ROLES)
    return success_object(get_or_404("lotteries", id))


@bp.post("/authorizer/lotteries/<id>/open")
def open_lottery(id):
    require_roles(["AuthorizerStaff"])
    lottery = get_or_404("lotteries", id)
    if lottery["status"] != "DRAFT":
        raise_error(errors.ERR_LOTTERY_INVALID_STATE, "Lottery is not DRAFT")
    school = db.get("schools", lottery["school_id"])
    if school is None or school["status"] != "OPEN":
        raise_error(errors.ERR_SCHOOL_NOT_OPEN, "School must be OPEN to open the lottery")
    lottery["status"] = "OPEN"
    db.touch(lottery)
    return success_object(lottery)


@bp.post("/authorizer/lotteries/<id>/entries")
def add_entry(id):
    user_id, role = require_roles(["SchoolOperator"])
    lottery = get_or_404("lotteries", id)
    check_operator_owns(user_id, role, lottery["school_id"])
    if lottery["status"] != "OPEN":
        raise_error(errors.ERR_LOTTERY_INVALID_STATE, "Entries may be added only while OPEN")
    data = body()
    student_ref = require_non_empty_string(data, "student_ref")
    grade_level = require_non_empty_string(data, "grade_level")
    preference_codes = data.get("preference_codes")
    if preference_codes is None:
        preference_codes = []
    if not isinstance(preference_codes, list) or not all(
        isinstance(c, str) for c in preference_codes
    ):
        raise_error(errors.ERR_INVALID_REQUEST, "preference_codes must be an array of codes")
    for code in preference_codes:
        if code not in PREFERENCE_CODES:
            raise_error(errors.ERR_INVALID_REQUEST, f"Unknown preference code: {code}")
    record = db.stamp_new({
        "lottery_id": id,
        "student_ref": student_ref,
        "grade_level": grade_level,
        "preference_codes": list(preference_codes),
        "preference_status": "VERIFIED" if len(preference_codes) == 0 else "PENDING",
        "preference_verified_by": None,
        "outcome": "ENTERED",
        "rank_position": None,
    })
    db.insert("lottery_entries", record)
    return success_object(record, 201)


@bp.get("/authorizer/lotteries/<id>/entries")
def list_entries(id):
    require_roles(ALL_ROLES)
    get_or_404("lotteries", id)
    records = [e for e in db.all_records("lottery_entries") if e["lottery_id"] == id]
    return paginate(records)


@bp.post("/authorizer/lottery-entries/<id>/verify-preference")
def verify_preference(id):
    user_id, _role = require_roles(["AuthorizerStaff"])
    entry = get_or_404("lottery_entries", id)
    if entry["preference_status"] != "PENDING":
        raise_error(errors.ERR_ENTRY_INVALID_STATE, "Preference claim is not PENDING")
    data = body()
    outcome = require_non_empty_string(data, "outcome")
    if outcome not in ("VERIFIED", "REJECTED"):
        raise_error(errors.ERR_INVALID_REQUEST, "outcome must be VERIFIED or REJECTED")
    entry["preference_status"] = outcome
    entry["preference_verified_by"] = user_id
    db.touch(entry)
    return success_object(entry)


@bp.post("/authorizer/lotteries/<id>/seal")
def seal_lottery(id):
    require_roles(["AuthorizerStaff"])
    lottery = get_or_404("lotteries", id)
    if lottery["status"] != "OPEN":
        raise_error(errors.ERR_LOTTERY_INVALID_STATE, "Lottery is not OPEN")
    pending = [
        e for e in db.all_records("lottery_entries")
        if e["lottery_id"] == id and e["preference_status"] == "PENDING"
    ]
    if pending:
        raise_error(errors.ERR_UNVERIFIED_PREFERENCE_ENTRIES, "One or more entries still PENDING preference verification")
    lottery["status"] = "SEALED"
    db.touch(lottery)
    return success_object(lottery)


@bp.post("/authorizer/lotteries/<id>/execute")
def execute_lottery(id):
    require_roles(["AuthorizerStaff"])
    lottery = get_or_404("lotteries", id)
    if lottery["status"] != "SEALED":
        raise_error(errors.ERR_LOTTERY_INVALID_STATE, "Lottery is not SEALED")
    entries = [e for e in db.all_records("lottery_entries") if e["lottery_id"] == id and e["outcome"] == "ENTERED"]

    def weight(e):
        return PREFERENCE_WEIGHT if (e["preference_status"] == "VERIFIED" and len(e["preference_codes"]) > 0) else 0

    ordered = sorted(entries, key=lambda e: (-weight(e), e["created_at"], e["student_ref"]))
    capacity = lottery["capacity"]
    for idx, entry in enumerate(ordered, start=1):
        entry["rank_position"] = idx
        entry["outcome"] = "OFFERED" if idx <= capacity else "WAITLISTED"
        db.touch(entry)
    lottery["status"] = "EXECUTED"
    db.touch(lottery)
    return success_object(lottery)


@bp.post("/authorizer/lottery-entries/<id>/decline")
def decline_entry(id):
    user_id, role = require_roles(["SchoolOperator"])
    entry = get_or_404("lottery_entries", id)
    lottery = db.get("lotteries", entry["lottery_id"])
    owning_school_id = lottery["school_id"] if lottery else None
    check_operator_owns(user_id, role, owning_school_id)
    if entry["outcome"] != "OFFERED":
        raise_error(errors.ERR_ENTRY_INVALID_STATE, "Entry is not OFFERED")
    entry["outcome"] = "DECLINED"
    db.touch(entry)
    # Promotion: smallest-rank WAITLISTED entry -> OFFERED (compensating action).
    waitlisted = [
        e for e in db.all_records("lottery_entries")
        if e["lottery_id"] == entry["lottery_id"] and e["outcome"] == "WAITLISTED"
    ]
    if waitlisted:
        promoted = min(waitlisted, key=lambda e: e["rank_position"])
        promoted["outcome"] = "OFFERED"
        db.touch(promoted)
    return success_object(entry)


@bp.post("/authorizer/lotteries/<id>/certify")
def certify_lottery(id):
    require_roles(["AuthorizerStaff"])
    lottery = get_or_404("lotteries", id)
    if lottery["status"] != "EXECUTED":
        raise_error(errors.ERR_LOTTERY_INVALID_STATE, "Lottery is not EXECUTED")
    data = body()
    audit_outcome = require_non_empty_string(data, "audit_outcome")
    if audit_outcome not in ("CERTIFIED", "AUDIT_FAILED"):
        raise_error(errors.ERR_INVALID_REQUEST, "audit_outcome must be CERTIFIED or AUDIT_FAILED")
    lottery["status"] = audit_outcome
    db.touch(lottery)
    return success_object(lottery)
