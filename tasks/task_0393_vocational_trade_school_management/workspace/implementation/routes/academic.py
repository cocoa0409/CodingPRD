"""Routes for AttendanceEntry and SapStanding (+ appeals)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_role, ALL_ROLES
from helpers import (
    get_json_body, serialize, stamp_new, bump, paginate, sorted_collection,
    find_or_404, as_int, as_number, as_enum,
)
from response import success
import services

bp = Blueprint("academic", __name__)


# ==========================================================================
# AttendanceEntry
# ==========================================================================
@bp.post("/v1/attendance-entries")
def post_attendance():
    require_role(["AcademicAdvisor"])
    body = get_json_body()
    agreement_id = body.get("agreement_id")
    if agreement_id is None or not isinstance(agreement_id, str) or agreement_id == "":
        raise err("ERR_INVALID_REQUEST", "Missing required field: agreement_id")
    # Existence (body id) checked before body well-formedness of other fields? Per
    # §2.5 existence precedes body validity; resolve agreement first.
    agreement = find_or_404(store.enrollment_agreements, agreement_id, "EnrollmentAgreement")

    term_index = as_int(body, "term_index", required=True, minimum=0)
    kind = as_enum(body, "kind", {"THEORY", "EXTERNSHIP"}, required=True)
    scheduled_hours = as_number(body, "scheduled_hours", required=True, exclusive_min=0)
    attended_hours = as_number(body, "attended_hours", required=True, minimum=0)
    if attended_hours > scheduled_hours:
        raise err("ERR_INVALID_REQUEST", "attended_hours must be <= scheduled_hours.")

    if agreement["status"] not in ("ENROLLED", "LEAVE_OF_ABSENCE"):
        raise err("ERR_AGREEMENT_NOT_ACTIVE",
                  "Agreement must be ENROLLED or LEAVE_OF_ABSENCE to post attendance.")

    entry = {
        "agreement_id": agreement_id,
        "term_index": term_index,
        "kind": kind,
        "scheduled_hours": scheduled_hours,
        "attended_hours": attended_hours,
        "status": "POSTED",
    }
    stamp_new(entry)
    store.attendance_entries[entry["id"]] = entry
    services.recompute_agreement(agreement)
    bump(agreement)
    return success(serialize(entry), 201)


@bp.get("/v1/attendance-entries")
def list_attendance():
    require_role(ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    kind = request.args.get("kind")

    def pred(e):
        if agreement_id and e["agreement_id"] != agreement_id:
            return False
        if status and e["status"] != status:
            return False
        if kind and e["kind"] != kind:
            return False
        return True

    items = sorted_collection(store.attendance_entries, predicate=pred)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/attendance-entries/<eid>")
def get_attendance(eid):
    require_role(ALL_ROLES)
    entry = find_or_404(store.attendance_entries, eid, "AttendanceEntry")
    return success(serialize(entry), 200)


@bp.post("/v1/attendance-entries/<eid>/excuse")
def excuse_attendance(eid):
    require_role(["AcademicAdvisor"])
    entry = find_or_404(store.attendance_entries, eid, "AttendanceEntry")
    if entry["status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "Attendance entry must be POSTED to excuse.")
    agreement = store.enrollment_agreements[entry["agreement_id"]]
    if agreement["status"] not in ("ENROLLED", "LEAVE_OF_ABSENCE"):
        raise err("ERR_AGREEMENT_NOT_ACTIVE",
                  "Agreement must be ENROLLED or LEAVE_OF_ABSENCE.")
    entry["status"] = "EXCUSED"
    entry["attended_hours"] = 0
    bump(entry)
    services.recompute_agreement(agreement)
    bump(agreement)
    return success(serialize(entry), 200)


@bp.post("/v1/attendance-entries/<eid>/void")
def void_attendance(eid):
    require_role(["AcademicAdvisor"])
    entry = find_or_404(store.attendance_entries, eid, "AttendanceEntry")
    if entry["status"] not in ("POSTED", "EXCUSED"):
        raise err("ERR_INVALID_STATE", "Attendance entry must be POSTED or EXCUSED to void.")
    agreement = store.enrollment_agreements[entry["agreement_id"]]
    if agreement["status"] not in ("ENROLLED", "LEAVE_OF_ABSENCE"):
        raise err("ERR_AGREEMENT_NOT_ACTIVE",
                  "Agreement must be ENROLLED or LEAVE_OF_ABSENCE.")
    entry["status"] = "VOIDED"
    bump(entry)
    services.recompute_agreement(agreement)
    bump(agreement)
    return success(serialize(entry), 200)


# ==========================================================================
# SapStanding
# ==========================================================================
@bp.post("/v1/sap-standings")
def create_sap():
    require_role(["AcademicAdvisor"])
    body = get_json_body()
    agreement_id = body.get("agreement_id")
    if agreement_id is None or not isinstance(agreement_id, str) or agreement_id == "":
        raise err("ERR_INVALID_REQUEST", "Missing required field: agreement_id")
    agreement = find_or_404(store.enrollment_agreements, agreement_id, "EnrollmentAgreement")
    checkpoint = as_int(body, "checkpoint_term_index", required=True, minimum=0)

    cohort = store.cohorts[agreement["cohort_id"]]
    program = store.programs[agreement["program_id"]]
    pace, att, standing = services.compute_sap(agreement, cohort, program, checkpoint)

    review = {
        "agreement_id": agreement_id,
        "checkpoint_term_index": checkpoint,
        "measured_pace_pct": pace,
        "measured_attendance_pct": att,
        "standing": standing,
        "appeal_status": "NONE",
    }
    stamp_new(review)
    store.sap_standings[review["id"]] = review

    # Mirror onto agreement; bump agreement version.
    agreement["sap_standing"] = standing
    services.recompute_agreement(agreement)
    bump(agreement)
    return success(serialize(review), 201)


@bp.get("/v1/sap-standings")
def list_sap():
    require_role(ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    standing = request.args.get("standing")

    def pred(e):
        if agreement_id and e["agreement_id"] != agreement_id:
            return False
        if standing and e["standing"] != standing:
            return False
        return True

    items = sorted_collection(store.sap_standings, predicate=pred)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/sap-standings/<sid>")
def get_sap(sid):
    require_role(ALL_ROLES)
    review = find_or_404(store.sap_standings, sid, "SapStanding")
    return success(serialize(review), 200)


@bp.post("/v1/sap-standings/<sid>/appeal")
def appeal_sap(sid):
    require_role(["AcademicAdvisor"])
    review = find_or_404(store.sap_standings, sid, "SapStanding")
    if review["appeal_status"] != "NONE":
        raise err("ERR_INVALID_STATE", "Appeal already filed or resolved.")
    if review["standing"] not in ("PROBATION", "DISMISSED"):
        raise err("ERR_SAP_NOT_APPEALABLE",
                  "Appeal allowed only on PROBATION or DISMISSED standing.")
    review["appeal_status"] = "APPEALED"
    bump(review)
    return success(serialize(review), 200)


@bp.post("/v1/sap-standings/<sid>/resolve-appeal")
def resolve_appeal(sid):
    require_role(["AcademicAdvisor"])
    review = find_or_404(store.sap_standings, sid, "SapStanding")
    body = get_json_body()
    if review["appeal_status"] != "APPEALED":
        # Body validity (decision) is checked at priority 4, before state (6).
        as_enum(body, "decision", {"GRANT", "DENY"}, required=True)
        raise err("ERR_INVALID_STATE", "Appeal must be APPEALED to resolve.")
    decision = as_enum(body, "decision", {"GRANT", "DENY"}, required=True)

    agreement = store.enrollment_agreements[review["agreement_id"]]
    latest = services.latest_sap_standing(review["agreement_id"])
    is_latest = latest is not None and latest["id"] == review["id"]

    if decision == "GRANT":
        review["appeal_status"] = "APPEAL_GRANTED"
        bump(review)
        if is_latest and review["standing"] == "DISMISSED":
            agreement["sap_standing"] = "PROBATION"
            services.recompute_agreement(agreement)
            bump(agreement)
    else:  # DENY
        review["appeal_status"] = "APPEAL_DENIED"
        bump(review)
        if is_latest and review["standing"] == "DISMISSED":
            # Cascade-withdraw the parent agreement.
            services.cascade_withdraw(agreement)
    return success(serialize(review), 200)
