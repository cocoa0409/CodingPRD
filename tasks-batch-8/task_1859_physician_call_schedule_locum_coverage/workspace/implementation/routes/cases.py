"""Credentialing cases: list/get/complete-item/fail/expire (PRD §3.5).

The fifth completed item clears the case and fires the locum auto-fill cascade
in one atomic step: requisition CREDENTIALING -> READY -> FILLED, assignment
created (origin LOCUM_FILL), slot OPEN -> ASSIGNED, gap RESOLVED, reserve update
under the fiscal gate.
"""
from flask import Blueprint

import db
import validation as V
from db import store
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import domain as D

bp = Blueprint("cases", __name__)

ALL = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]
OFFICER = ["CredentialingOfficer"]
ACTIVE_CASE_STATUSES = ("INITIATED", "IN_PROGRESS")


def get_case_or_404(case_id):
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "CredentialingCase id does not exist")
    return case


def _reopen_requisition(case):
    """Case FAILED/EXPIRED: requisition CREDENTIALING -> OPEN, candidate cleared;
    the gap stays REQUISITIONED (deliberate asymmetry, PRD §3.5)."""
    req = store.requisitions.get(case["requisition_id"])
    if req is not None and req["status"] == "CREDENTIALING":
        req["status"] = "OPEN"
        req["candidate_physician_id"] = None
        db.touch(req)


@bp.route("/api/credentialing-cases", methods=["GET"])
def list_cases():
    require_roles(ALL)
    rows = list(store.cases.values())
    rows = paginate.filter(rows, "requisition_id")
    rows = paginate.filter(rows, "locum_physician_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.route("/api/credentialing-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    require_roles(ALL)
    return ok(get_case_or_404(case_id))


@bp.route("/api/credentialing-cases/<case_id>/complete-item", methods=["POST"])
def complete_item(case_id):
    require_roles(OFFICER)
    body = V.json_body()
    item = V.req_enum(body, "item", D.CREDENTIAL_ITEMS)
    case = get_case_or_404(case_id)
    if case["status"] not in ACTIVE_CASE_STATUSES:
        raise ApiError("ERR_CASE_NOT_ACTIVE", 409,
                       "complete-item requires the case INITIATED or IN_PROGRESS")
    # Level 8: privileges_granting requires license_verification completed first.
    if item == "privileges_granting" \
            and case["items"]["license_verification"]["completed_at"] is None:
        raise ApiError("ERR_PREREQUISITE_ITEM_INCOMPLETE", 409,
                       "privileges_granting requires license_verification completed first")
    # Level 9: now <= clear_by (equality allowed).
    now = db.now_logical()
    if now > case["clear_by"]:
        raise ApiError("ERR_CREDENTIALING_DEADLINE_PASSED", 409,
                       "complete-item after clear_by")
    # Level 10: item not already completed.
    if case["items"][item]["completed_at"] is not None:
        raise ApiError("ERR_ITEM_ALREADY_COMPLETED", 409,
                       "Credentialing checklist item already completed")
    is_final = all(
        c["completed_at"] is not None for name, c in case["items"].items() if name != item)
    req = store.requisitions.get(case["requisition_id"])
    if is_final and req is not None:
        # Fiscal gate (priority 11) on the auto-fill assignment's projected pay.
        gap = store.gaps.get(req["gap_id"])
        slot = store.slots.get(gap["slot_id"]) if gap else None
        program = store.programs.get(req["program_id"])
        candidate = store.physicians.get(case["locum_physician_id"])
        projected = D.compute_projected_pay(program, slot, candidate)
        D.check_payroll_budget(program, projected)
    # Apply the completion.
    case["items"][item]["completed_at"] = now
    if not is_final:
        case["status"] = "IN_PROGRESS"
        db.touch(case)
        return ok(case)
    # Fifth item: CLEARED (hop 1) with the locum auto-fill cascade (hops 2-5).
    case["status"] = "CLEARED"
    db.touch(case)
    if req is not None and req["status"] == "CREDENTIALING":
        gap = store.gaps.get(req["gap_id"])
        slot = store.slots.get(gap["slot_id"]) if gap else None
        program = store.programs.get(req["program_id"])
        candidate = store.physicians.get(case["locum_physician_id"])
        # Hop 2: requisition CREDENTIALING -> READY -> FILLED (READY transient).
        req["status"] = "FILLED"
        db.touch(req)
        # Hops 3-5: assignment created, slot -> ASSIGNED, gap -> RESOLVED, reserve.
        D.create_assignment(program, slot, candidate, "LOCUM_FILL",
                            source_requisition_id=req["id"])
    return ok(case)


@bp.route("/api/credentialing-cases/<case_id>/fail", methods=["POST"])
def fail_case(case_id):
    require_roles(OFFICER)
    body = V.json_body()
    V.req_str(body, "reason")
    case = get_case_or_404(case_id)
    if case["status"] not in ACTIVE_CASE_STATUSES:
        raise ApiError("ERR_CASE_NOT_ACTIVE", 409,
                       "fail requires the case INITIATED or IN_PROGRESS")
    case["status"] = "FAILED"
    db.touch(case)
    _reopen_requisition(case)
    return ok(case)


@bp.route("/api/credentialing-cases/<case_id>/expire", methods=["POST"])
def expire_case(case_id):
    require_roles(OFFICER)
    V.json_body()
    case = get_case_or_404(case_id)
    if case["status"] not in ACTIVE_CASE_STATUSES:
        raise ApiError("ERR_CASE_NOT_ACTIVE", 409,
                       "expire requires the case INITIATED or IN_PROGRESS")
    # Level 9: now must be strictly past clear_by.
    if not (db.now_logical() > case["clear_by"]):
        raise ApiError("ERR_CREDENTIALING_NOT_EXPIRED", 409,
                       "expire called while now <= clear_by")
    case["status"] = "EXPIRED"
    db.touch(case)
    _reopen_requisition(case)
    return ok(case)
