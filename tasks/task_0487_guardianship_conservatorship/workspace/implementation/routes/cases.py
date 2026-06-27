"""GuardianshipCase routes: create, read/list, open/close review, terminate, restore."""

from flask import Blueprint, request

from db import db, stamp_create, stamp_update
from errors import err
from middleware import get_identity, require_role
from response import object_response, array_response
from validators import (
    ALL_ROLES,
    get_json_body,
    require_enum,
    require_string,
    parse_pagination,
    paginate,
)
from services import (
    resolve_path,
    resolve_ref,
    recompute_posture,
    recompute_case_posture_only,
    touch_case,
    expenditures_for_case,
    accountings_for_case,
    reviews_for_case,
    run_revoke_close_cascade,
)

bp = Blueprint("cases", __name__)


@bp.route("/gc/cases", methods=["POST"])
def create_case():
    _, role = get_identity()
    require_role(role, ["Petitioner", "CourtClerk"])
    body = get_json_body()
    # FK resolution (priority 4) before request well-formedness (priority 5)?
    # PRD §3.9: ERR_REFERENCE_NOT_FOUND (4) precedes ERR_INVALID_REQUEST (5).
    # But missing protected_person_id is a required-field error. We resolve the FK
    # only once present and string-typed; absence/bad-type is ERR_INVALID_REQUEST.
    person_id = require_string(body, "protected_person_id")
    case_type = require_enum(body, "case_type", {"GUARDIANSHIP", "CONSERVATORSHIP", "PLENARY"})
    person = resolve_ref(db.protected_persons, person_id)

    # One-active-case uniqueness (priority 10): person.active_case_id already set.
    if person.get("active_case_id"):
        raise err("ERR_PERSON_HAS_ACTIVE_CASE", "Protected person already has an active case")

    requires_bond = case_type in ("CONSERVATORSHIP", "PLENARY")
    record = {
        "protected_person_id": person_id,
        "case_type": case_type,
        "status": "DRAFT",
        "protection_posture": "GREEN",
        "requires_bond": requires_bond,
        "next_accounting_due_iso": None,
        "overdue_accounting_count": 0,
    }
    stamp_create(record)
    with db.lock:
        db.cases[record["id"]] = record
        person["active_case_id"] = record["id"]
        stamp_update(person)
    return object_response(record, 201)


@bp.route("/gc/cases/<cid>", methods=["GET"])
def get_case(cid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    case = resolve_path(db.cases, cid)
    # Posture and overdue counts are re-derived against the clock on read.
    recompute_case_posture_only(case)
    return object_response(case, 200)


@bp.route("/gc/cases", methods=["GET"])
def list_cases():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.cases.values())
    person_id = request.args.get("protected_person_id")
    if person_id is not None:
        items = [c for c in items if c["protected_person_id"] == person_id]
    for c in items:
        recompute_case_posture_only(c)
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/cases/<cid>/open-review", methods=["POST"])
def open_review(cid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    case = resolve_path(db.cases, cid)
    if case["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Case must be ACTIVE to open a review")
    case["status"] = "UNDER_REVIEW"
    touch_case(case)
    return object_response(case, 200)


@bp.route("/gc/cases/<cid>/close-review", methods=["POST"])
def close_review(cid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    case = resolve_path(db.cases, cid)
    if case["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Case must be UNDER_REVIEW to close a review")
    # No CourtReview on this case may remain SCHEDULED or HELD.
    if any(r["status"] in ("SCHEDULED", "HELD") for r in reviews_for_case(cid)):
        raise err("ERR_OPEN_REVIEW_PENDING", "An open review remains on this case")
    case["status"] = "ACTIVE"
    touch_case(case)
    return object_response(case, 200)


def _check_terminate_guards(case):
    # No Expenditure in PENDING_COURT or APPROVED.
    if any(e["status"] in ("PENDING_COURT", "APPROVED") for e in expenditures_for_case(case["id"])):
        raise err("ERR_PENDING_EXPENDITURES", "Pending or approved expenditures outstanding")
    # If any AccountingReport exists, the one with greatest period_year is APPROVED.
    reports = accountings_for_case(case["id"])
    if reports:
        latest = max(reports, key=lambda a: a["period_year"])
        if latest["status"] != "APPROVED":
            raise err("ERR_ACCOUNTING_OUTSTANDING", "Latest accounting is not APPROVED")


@bp.route("/gc/cases/<cid>/terminate", methods=["POST"])
def terminate_case(cid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    case = resolve_path(db.cases, cid)
    if case["status"] not in ("ACTIVE", "UNDER_REVIEW"):
        raise err("ERR_INVALID_STATE", "Case must be ACTIVE or UNDER_REVIEW to terminate")
    _check_terminate_guards(case)

    case["status"] = "TERMINATED"
    run_revoke_close_cascade(case)
    person = db.protected_persons.get(case["protected_person_id"])
    if person is not None:
        person["active_case_id"] = None
        # capacity_status unchanged (remains ADJUDICATED_INCAPACITATED).
        stamp_update(person)
    touch_case(case)
    return object_response(case, 200)


@bp.route("/gc/cases/<cid>/restore", methods=["POST"])
def restore_case(cid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    case = resolve_path(db.cases, cid)
    if case["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Case must be UNDER_REVIEW to restore")
    # A CourtReview on this case has outcome == ACCEPTED and status == CLOSED.
    has_accepted_closed = any(
        r["outcome"] == "ACCEPTED" and r["status"] == "CLOSED"
        for r in reviews_for_case(cid)
    )
    if not has_accepted_closed:
        raise err("ERR_RESTORATION_NOT_REVIEWED", "No ACCEPTED, CLOSED restoration review")
    # No Expenditure in PENDING_COURT or APPROVED.
    if any(e["status"] in ("PENDING_COURT", "APPROVED") for e in expenditures_for_case(cid)):
        raise err("ERR_PENDING_EXPENDITURES", "Pending or approved expenditures outstanding")

    case["status"] = "RESTORED"
    run_revoke_close_cascade(case)
    person = db.protected_persons.get(case["protected_person_id"])
    if person is not None:
        person["active_case_id"] = None
        person["capacity_status"] = "RESTORED"
        stamp_update(person)
    touch_case(case)
    return object_response(case, 200)
