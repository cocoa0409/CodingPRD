"""AwardPackage endpoints (PRD 3.6): shell, build, notify, accept, decline,
lock, revision requests, and package-scoped sub-resource listings."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_DUPLICATE,
    ERR_PARENT_STATE_BLOCKS, ERR_PREREQUISITE_MISSING, ERR_STALE_PACKAGE_VERSION,
    ERR_OVERAWARD_UNRESOLVED, ERR_REVISION_ALREADY_PENDING,
)
from middleware import authorized, check_student_owns
from response import success_object
from routes.helpers import list_response
from services.core import (
    new_record, public, touch, current_isir, recompute_package_totals,
    recompute_aggregates,
)
from services.packaging import (
    build_package, overaward_gate_blocks_acceptance, run_overaward_detection,
)
from util import CLOCK
from validate import (
    get_body, req_str, req_int, require_path_resource, require_body_ref,
    deferred_body_ref,
)

bp = Blueprint("packages", __name__)

OFFICER = ["AidOfficer"]
STUDENT = ["Student"]
ALL_READ = ["AidDirector", "AidOfficer", "Student"]
REVISION_REASONS = ("CHANGE_ENROLLMENT", "CHANGE_CIRCUMSTANCE", "APPEAL_AMOUNT",
                    "DECLINE_LOAN_ONLY")


def _package_lines(package_id):
    lines = [l for l in db.award_lines.values() if l["package_id"] == package_id]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return lines


@bp.post("/award-packages")
def create_package():
    authorized(OFFICER)
    body = get_body()
    # Rung 4: body foreign keys (absent keys defer to the rung-9 shape check).
    student = deferred_body_ref("students", body, "student_id")
    aid_year = deferred_body_ref("aid_years", body, "aid_year_id")
    # Rung 9: shape.
    req_str(body, "student_id")
    req_str(body, "aid_year_id")
    # Rung 11: at most one AwardPackage per (student_id, aid_year_id).
    for pkg in db.award_packages.values():
        if pkg["student_id"] == student["id"] and pkg["aid_year_id"] == aid_year["id"]:
            raise_error(ERR_DUPLICATE,
                        "an award package already exists for this student and aid year")
    rec = new_record("award_packages", {
        "student_id": student["id"],
        "aid_year_id": aid_year["id"],
        "coa_used_cents": 0,
        "efc_used_cents": 0,
        "need_cents": 0,
        "total_offered_cents": 0,
        "total_accepted_cents": 0,
        "gift_aid_cents": 0,
        "status": "DRAFT",
        "needs_repack": False,
        "version_locked_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/award-packages")
def list_packages():
    authorized(["AidDirector", "AidOfficer"])
    return list_response("award_packages", {
        "student_id": request.args.get("student_id"),
        "aid_year_id": request.args.get("aid_year_id"),
        "status": request.args.get("status"),
    })


@bp.get("/award-packages/<rid>")
def get_package(rid):
    caller = authorized(ALL_READ)
    rec = require_path_resource("award_packages", rid)
    check_student_owns(caller, rec["student_id"])
    return success_object(public(rec))


@bp.post("/award-packages/<rid>/build")
def build(rid):
    authorized(OFFICER)
    pkg = require_path_resource("award_packages", rid)
    # Rung 5: state-machine legality.
    if pkg["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    f"package is {pkg['status']}, expected DRAFT")
    # Rung 6: the aid year must be OPEN for a packaging build.
    ay = db.aid_years.get(pkg["aid_year_id"])
    if ay is None or ay["status"] != "OPEN":
        raise_error(ERR_PARENT_STATE_BLOCKS,
                    "packaging build requires the aid year to be OPEN")
    # Rung 13: a current ISIR record must exist for the student and aid year.
    isir = current_isir(pkg["student_id"], pkg["aid_year_id"])
    if isir is None:
        raise_error(ERR_PREREQUISITE_MISSING,
                    "no current ISIR record for this student and aid year")
    student = db.students.get(pkg["student_id"])
    build_package(pkg, student, ay, isir)
    return success_object(public(pkg))


@bp.post("/award-packages/<rid>/notify")
def notify(rid):
    authorized(OFFICER)
    pkg = require_path_resource("award_packages", rid)
    if pkg["status"] != "PACKAGED":
        raise_error(ERR_INVALID_STATE,
                    f"package is {pkg['status']}, expected PACKAGED")
    lines = _package_lines(pkg["id"])
    if not any(l["status"] == "OFFERED" for l in lines):
        raise_error(ERR_INVALID_STATE,
                    "at least one child line must be OFFERED to notify")
    pkg["status"] = "NOTIFIED"
    touch(pkg)
    _fire_notification(pkg)
    return success_object(public(pkg))


def _fire_notification(pkg):
    """Creates an AwardNotification in DRAFT and immediately fires it to SENT,
    stamping sent_at from the logical clock and freezing the offered total."""
    max_seq = 0
    for n in db.award_notifications.values():
        if n["package_id"] == pkg["id"]:
            max_seq = max(max_seq, n["notification_seq"])
    return new_record("award_notifications", {
        "package_id": pkg["id"],
        "notification_seq": max_seq + 1,
        "status": "SENT",
        "sent_at": CLOCK.now_iso(),
        "snapshot_total_offered_cents": pkg["total_offered_cents"],
    })


@bp.post("/award-packages/<rid>/accept")
def accept(rid):
    caller = authorized(STUDENT)
    pkg = require_path_resource("award_packages", rid)
    body = get_body()
    # Rung 4: line references carried in the body must resolve.
    raw_acceptances = body.get("line_acceptances")
    referenced = []
    if isinstance(raw_acceptances, list):
        for entry in raw_acceptances:
            if isinstance(entry, dict) and isinstance(entry.get("award_line_id"), str):
                referenced.append(entry["award_line_id"])
    for line_id in referenced:
        require_body_ref("award_lines", line_id, "award_line_id")
    # Rung 5: state legality.
    if pkg["status"] != "NOTIFIED":
        raise_error(ERR_INVALID_STATE,
                    f"package is {pkg['status']}, expected NOTIFIED")
    # Rung 8: ownership.
    check_student_owns(caller, pkg["student_id"])
    # Rung 9: shape — a per-line set of amounts, each within [0, offered].
    if not isinstance(raw_acceptances, list) or not raw_acceptances:
        raise_error(ERR_INVALID_REQUEST,
                    "line_acceptances must be a non-empty array")
    amounts = {}
    for entry in raw_acceptances:
        if not isinstance(entry, dict):
            raise_error(ERR_INVALID_REQUEST, "line_acceptances entries must be objects")
        line_id = entry.get("award_line_id")
        if not isinstance(line_id, str) or not line_id:
            raise_error(ERR_INVALID_REQUEST, "line_acceptances entry missing award_line_id")
        amount = entry.get("accept_cents")
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise_error(ERR_INVALID_REQUEST,
                        "line_acceptances entry accept_cents must be an integer")
        line = db.award_lines[line_id]
        if line["package_id"] != pkg["id"]:
            raise_error(ERR_INVALID_REQUEST,
                        "line_acceptances references a line of another package")
        if amount < 0 or amount > line["offered_cents"]:
            raise_error(ERR_INVALID_REQUEST,
                        "accept_cents must lie between zero and the line's "
                        "offered_cents inclusive")
        if line_id in amounts:
            raise_error(ERR_INVALID_REQUEST,
                        "line_acceptances contains a duplicate award_line_id")
        amounts[line_id] = amount

    lines = _package_lines(pkg["id"])
    offered_lines = [l for l in lines if l["status"] == "OFFERED"]
    for line in offered_lines:
        if line["id"] not in amounts:
            raise_error(ERR_INVALID_REQUEST,
                        "line_acceptances must name every OFFERED line of the package")

    # Rung 16: over-award gate at acceptance.
    if overaward_gate_blocks_acceptance(pkg):
        raise_error(ERR_OVERAWARD_UNRESOLVED,
                    "an unresolved over-award case still exceeds the cost of "
                    "attendance; the student must wait for resolution")

    # --- apply per-line acceptance ------------------------------------------
    for line in offered_lines:
        amount = amounts[line["id"]]
        if amount == line["offered_cents"]:
            line["status"] = "ACCEPTED"
            line["accepted_cents"] = amount
        elif amount == 0:
            line["status"] = "DECLINED"
            line["accepted_cents"] = 0
        else:
            line["status"] = "PARTIALLY_ACCEPTED"
            line["accepted_cents"] = amount
        touch(line)

    all_full = all(amounts[l["id"]] == l["offered_cents"] for l in offered_lines)
    pkg["status"] = "ACCEPTED" if all_full else "PARTIALLY_ACCEPTED"
    touch(pkg)
    recompute_package_totals(pkg)
    recompute_aggregates(pkg["aid_year_id"])
    # Detection runs on the new totals (PRD 3.8: on every acceptance transition).
    run_overaward_detection(pkg["student_id"], pkg["aid_year_id"])
    return success_object(public(pkg))


@bp.post("/award-packages/<rid>/decline")
def decline(rid):
    caller = authorized(STUDENT)
    pkg = require_path_resource("award_packages", rid)
    if pkg["status"] != "NOTIFIED":
        raise_error(ERR_INVALID_STATE,
                    f"package is {pkg['status']}, expected NOTIFIED")
    check_student_owns(caller, pkg["student_id"])
    for line in _package_lines(pkg["id"]):
        if line["status"] == "OFFERED":
            line["status"] = "DECLINED"
            line["accepted_cents"] = 0
            touch(line)
    pkg["status"] = "DECLINED"
    touch(pkg)
    recompute_package_totals(pkg)
    recompute_aggregates(pkg["aid_year_id"])
    return success_object(public(pkg))


@bp.post("/award-packages/<rid>/lock")
def lock(rid):
    authorized(OFFICER)
    pkg = require_path_resource("award_packages", rid)
    if pkg["status"] not in ("ACCEPTED", "PARTIALLY_ACCEPTED"):
        raise_error(ERR_INVALID_STATE,
                    f"package is {pkg['status']}, expected ACCEPTED or "
                    f"PARTIALLY_ACCEPTED")
    body = get_body()
    expected = req_int(body, "expected_package_version")
    # Rung 14: optimistic concurrency (PRD 2.9).
    if expected != pkg["version"]:
        raise_error(ERR_STALE_PACKAGE_VERSION,
                    "expected_package_version does not match the package's current "
                    "version")
    pkg["status"] = "LOCKED"
    pkg["version_locked_at"] = CLOCK.now_iso()
    touch(pkg)
    return success_object(public(pkg))


@bp.post("/award-packages/<rid>/revision-requests")
def file_revision_request(rid):
    caller = authorized(STUDENT)
    pkg = require_path_resource("award_packages", rid)
    # A package in REVISION_REQUESTED always has a request in flight (they are
    # set together); the one-in-flight guard carries its specific error id
    # (PRD 3.6: "a new filing fails with ERR_REVISION_ALREADY_PENDING").
    pending = any(
        req_rec["package_id"] == pkg["id"]
        and req_rec["status"] in ("SUBMITTED", "UNDER_REVIEW")
        for req_rec in db.revision_requests.values())
    if pkg["status"] == "REVISION_REQUESTED" and pending:
        raise_error(ERR_REVISION_ALREADY_PENDING,
                    "a revision request for this package is already in flight")
    if pkg["status"] != "NOTIFIED":
        raise_error(ERR_INVALID_STATE,
                    f"package is {pkg['status']}, expected NOTIFIED")
    check_student_owns(caller, pkg["student_id"])
    body = get_body()
    reason = req_str(body, "reason")
    if reason not in REVISION_REASONS:
        raise_error(ERR_INVALID_REQUEST, f"invalid revision reason: {reason}")
    if pending:
        raise_error(ERR_REVISION_ALREADY_PENDING,
                    "a revision request for this package is already in flight")
    rec = new_record("revision_requests", {
        "package_id": pkg["id"],
        "reason": reason,
        "requested_by_role": caller.role,
        "status": "SUBMITTED",
        "decision_notes": None,
    })
    pkg["status"] = "REVISION_REQUESTED"
    touch(pkg)
    return success_object(public(rec), status=201)


# ---------------------------------------------------------------------------
# Package-scoped sub-resource listings
# ---------------------------------------------------------------------------

@bp.get("/award-packages/<rid>/award-lines")
def package_lines(rid):
    caller = authorized(ALL_READ)
    pkg = require_path_resource("award_packages", rid)
    check_student_owns(caller, pkg["student_id"])
    return list_response("award_lines", {"package_id": rid})


@bp.get("/award-packages/<rid>/notifications")
def package_notifications(rid):
    caller = authorized(ALL_READ)
    pkg = require_path_resource("award_packages", rid)
    check_student_owns(caller, pkg["student_id"])
    return list_response("award_notifications", {"package_id": rid})


@bp.get("/award-packages/<rid>/revision-requests")
def package_revision_requests(rid):
    caller = authorized(ALL_READ)
    pkg = require_path_resource("award_packages", rid)
    check_student_owns(caller, pkg["student_id"])
    return list_response("revision_requests", {"package_id": rid})
