"""Legal holds, hold custodian assignments, hold scope items."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, new_id, touch, bump, now
from errors import err, not_found
from middleware import authenticate, body_json, ALL_ROLES
from response import success_object, success_list, success_empty, paginate
from serializers import hold_view, hold_custodian_view, hold_scope_item_view
from services.core import (
    derive_posture, adjust_stale_for_record, add_reminder_log,
    hold_assignments, hold_items)
from utils import check_str, check_str_list

bp = Blueprint("holds", __name__)


def _get_hold(holdId):
    hold = db.legal_holds.get(holdId)
    if hold is None:
        not_found("Legal hold not found")
    return hold


def _resolve_custodians(custodian_ids, program_id):
    """Existence then same-program checks for a custodian id list."""
    out = []
    for cid in custodian_ids:
        c = db.custodians.get(cid)
        if c is None:
            raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                      "Referenced custodian does not exist: %s" % cid)
        out.append(c)
    for c in out:
        if c["program_id"] != program_id:
            raise err("ERR_CROSS_PROGRAM_REFERENCE", 409,
                      "Custodian %s belongs to a different program" % c["id"])
    return out


def _resolve_records(record_ids, program_id, scope_statuses=None,
                     existing_items=None):
    """Existence, same-program, duplicate-scope, and destroyed checks for a
    record id list being scoped into a hold."""
    out = []
    for rid in record_ids:
        r = db.records.get(rid)
        if r is None:
            raise err("ERR_REFERENCED_RECORD_NOT_FOUND", 404,
                      "Referenced record does not exist: %s" % rid)
        out.append(r)
    for r in out:
        if r["program_id"] != program_id:
            raise err("ERR_CROSS_PROGRAM_REFERENCE", 409,
                      "Record %s belongs to a different program" % r["id"])
    # Duplicate scope records: within the incoming list, or already in the
    # hold's scope with a live (PENDING_ISSUANCE / ACTIVE) item.
    seen = set()
    for rid in record_ids:
        if rid in seen:
            raise err("ERR_DUPLICATE_SCOPE_RECORD", 409,
                      "Record %s is duplicated in the hold scope" % rid)
        seen.add(rid)
    if existing_items:
        live = {i["record_id"] for i in existing_items
                if i["status"] in ("PENDING_ISSUANCE", "ACTIVE")}
        for rid in record_ids:
            if rid in live:
                raise err("ERR_DUPLICATE_SCOPE_RECORD", 409,
                          "Record %s is already in the hold's scope" % rid)
    for r in out:
        if r["status"] == "DESTROYED":
            raise err("ERR_RECORD_ALREADY_DESTROYED", 409,
                      "Record %s has already been destroyed" % r["id"])
    return out


def _new_assignment(hold, custodian_id, status):
    a = {
        "id": new_id(),
        "hold_id": hold["id"],
        "custodian_id": custodian_id,
        "program_id": hold["program_id"],
        "ack_due_date": None,
        "acknowledged_at": None,
        "was_late": None,
        "reminder_count": 0,
        "last_reminder_at": None,
        "escalated_at": None,
        "status": status,
    }
    touch(a)
    db.hold_custodians[a["id"]] = a
    return a


def _new_scope_item(hold, record_id, status):
    i = {
        "id": new_id(),
        "hold_id": hold["id"],
        "record_id": record_id,
        "program_id": hold["program_id"],
        "added_at": now(),
        "activated_at": None,
        "released_at": None,
        "status": status,
    }
    touch(i)
    db.hold_scope_items[i["id"]] = i
    return i


def _activate_items_cascade(hold, items, records):
    """PENDING_ISSUANCE -> ACTIVE with per-record hold coverage, stale
    snapshot adjustments, and hold activity bookkeeping."""
    before = {r["id"]: derive_posture(r) for r in records}
    t = now()
    for i in items:
        i["status"] = "ACTIVE"
        i["activated_at"] = t
        bump(i)
    for r in records:
        bump(r)
        adjust_stale_for_record(r, before[r["id"]], derive_posture(r))


def _deactivate_items_cascade(hold, items, records):
    """ACTIVE -> EXCLUDED/RELEASED with the reverse cascade. Caller sets each
    item's terminal status."""
    before = {r["id"]: derive_posture(r) for r in records}
    return before


def _finish_deactivate(before, records):
    for r in records:
        bump(r)
        adjust_stale_for_record(r, before[r["id"]], derive_posture(r))


# ---------------------------------------------------------------------------
# Legal Holds
# ---------------------------------------------------------------------------
@bp.route("/ig/legal-holds", methods=["POST"])
def create_hold():
    uid, _ = authenticate(["LegalCounsel"])
    body = body_json()
    program_id = check_str(body, "program_id")
    matter_ref = check_str(body, "matter_ref")
    title = check_str(body, "title")
    reason = check_str(body, "reason")
    custodian_ids = check_str_list(body, "custodian_ids")
    record_ids = check_str_list(body, "record_ids")
    if len(custodian_ids) == 0 or len(record_ids) == 0:
        raise err("ERR_EMPTY_COLLECTION", 400,
                  "custodian_ids and record_ids must both be non-empty")
    if program_id not in db.programs:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    custodians = _resolve_custodians(custodian_ids, program_id)
    records = _resolve_records(record_ids, program_id)
    # Uniqueness: matter_ref per program among DRAFT/ISSUED holds
    for h in db.legal_holds.values():
        if (h["program_id"] == program_id and h["matter_ref"] == matter_ref
                and h["status"] in ("DRAFT", "ISSUED")):
            raise err("ERR_DUPLICATE_MATTER_REF", 409,
                      "matter_ref is already used by a DRAFT or ISSUED hold "
                      "in the program")
    if len(set(custodian_ids)) != len(custodian_ids):
        raise err("ERR_DUPLICATE_CUSTODIAN", 409,
                  "A custodian may not appear twice on one hold")
    hold = {
        "id": new_id(),
        "program_id": program_id,
        "matter_ref": matter_ref,
        "title": title,
        "reason": reason,
        "created_by_user_id": uid,
        "issued_at": None,
        "released_at": None,
        "release_reason": None,
        "last_activity_at": None,
        "status": "DRAFT",
    }
    touch(hold)
    db.legal_holds[hold["id"]] = hold
    for cid in custodian_ids:
        _new_assignment(hold, cid, "AWAITING_ISSUANCE")
    for rid in record_ids:
        _new_scope_item(hold, rid, "PENDING_ISSUANCE")
    return success_object(hold_view(hold), 201)


@bp.route("/ig/legal-holds", methods=["GET"])
def list_holds():
    authenticate(ALL_ROLES)
    items = list(db.legal_holds.values())
    a = request.args
    pid = a.get("program_id")
    if pid is not None:
        items = [h for h in items if h["program_id"] == pid]
    st = a.get("status")
    if st is not None:
        items = [h for h in items if h["status"] == st]
    cid = a.get("custodian_id")
    if cid is not None:
        hold_ids = {x["hold_id"] for x in db.hold_custodians.values()
                    if x["custodian_id"] == cid}
        items = [h for h in items if h["id"] in hold_ids]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([hold_view(h) for h in window], limit, offset, total)


@bp.route("/ig/legal-holds/<holdId>", methods=["GET"])
def get_hold(holdId):
    authenticate(ALL_ROLES)
    return success_object(hold_view(_get_hold(holdId)))


@bp.route("/ig/legal-holds/<holdId>/issue", methods=["POST"])
def issue_hold(holdId):
    authenticate(["LegalCounsel"])
    hold = _get_hold(holdId)
    if hold["status"] != "DRAFT":
        raise err("ERR_HOLD_INVALID_STATE", 409,
                  "Only a DRAFT hold can be issued")
    items = [i for i in hold_items(hold["id"]) if i["status"] == "PENDING_ISSUANCE"]
    assigns = [a for a in hold_assignments(hold["id"])
               if a["status"] == "AWAITING_ISSUANCE"]
    if not items or not assigns:
        raise err("ERR_EMPTY_HOLD_SCOPE", 409,
                  "Issuing a hold requires at least one PENDING_ISSUANCE "
                  "scope item and one AWAITING_ISSUANCE custodian")
    program = db.programs[hold["program_id"]]
    t = now()
    hold["status"] = "ISSUED"
    hold["issued_at"] = t
    hold["last_activity_at"] = t
    bump(hold)
    records = [db.records[i["record_id"]] for i in items]
    _activate_items_cascade(hold, items, records)
    for a in assigns:
        a["status"] = "PENDING"
        a["ack_due_date"] = t + timedelta(days=program["ack_deadline_days"])
        bump(a)
        add_reminder_log(hold, a, "ISSUED_NOTICE", 0)
    return success_object(hold_view(hold))


@bp.route("/ig/legal-holds/<holdId>/cancel", methods=["POST"])
def cancel_hold(holdId):
    authenticate(["LegalCounsel"])
    hold = _get_hold(holdId)
    if hold["status"] != "DRAFT":
        raise err("ERR_HOLD_INVALID_STATE", 409,
                  "Only a DRAFT hold can be cancelled")
    hold["status"] = "CANCELLED"
    bump(hold)
    for i in hold_items(hold["id"]):
        if i["status"] == "PENDING_ISSUANCE":
            i["status"] = "CANCELLED"
            bump(i)
    for a in hold_assignments(hold["id"]):
        if a["status"] == "AWAITING_ISSUANCE":
            a["status"] = "CANCELLED"
            bump(a)
            add_reminder_log(hold, a, "CANCEL_NOTICE", 0)
    return success_object(hold_view(hold))


@bp.route("/ig/legal-holds/<holdId>/release", methods=["POST"])
def release_hold(holdId):
    authenticate(["LegalCounsel"])
    hold = _get_hold(holdId)
    body = body_json()
    release_reason = check_str(body, "release_reason")
    expected = body.get("expected_legal_hold_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", 400,
                  "Missing required field: expected_legal_hold_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", 400,
                  "expected_legal_hold_version must be an integer")
    if len(release_reason) < 10:
        raise err("ERR_JUSTIFICATION_TOO_SHORT", 400,
                  "release_reason must be at least 10 characters")
    # OCC before domain state checks
    if expected != hold["version"]:
        raise err("ERR_STALE_VERSION", 412,
                  "expected_legal_hold_version does not match the hold's "
                  "current version")
    if hold["status"] != "ISSUED":
        raise err("ERR_HOLD_INVALID_STATE", 409,
                  "Only an ISSUED hold can be released")
    assigns = hold_assignments(hold["id"])
    if any(a["status"] != "ACKNOWLEDGED" for a in assigns):
        raise err("ERR_HOLD_HAS_UNACKNOWLEDGED_CUSTODIANS", 409,
                  "All custodian assignments must be ACKNOWLEDGED before "
                  "release")
    t = now()
    items = [i for i in hold_items(hold["id"]) if i["status"] == "ACTIVE"]
    records = [db.records[i["record_id"]] for i in items]
    before = _deactivate_items_cascade(hold, items, records)
    for i in items:
        i["status"] = "RELEASED"
        i["released_at"] = t
        bump(i)
    _finish_deactivate(before, records)
    for a in assigns:
        a["status"] = "RELEASED"
        bump(a)
        add_reminder_log(hold, a, "RELEASE_NOTICE", 0)
    hold["status"] = "RELEASED"
    hold["released_at"] = t
    hold["release_reason"] = release_reason
    bump(hold)
    return success_object(hold_view(hold))


@bp.route("/ig/legal-holds/<holdId>/scope-items", methods=["POST"])
def expand_scope(holdId):
    authenticate(["LegalCounsel"])
    hold = _get_hold(holdId)
    body = body_json()
    record_ids = check_str_list(body, "record_ids")
    if len(record_ids) == 0:
        raise err("ERR_EMPTY_COLLECTION", 400,
                  "record_ids must be a non-empty collection")
    records = _resolve_records(record_ids, hold["program_id"],
                               existing_items=hold_items(hold["id"]))
    if hold["status"] not in ("DRAFT", "ISSUED"):
        raise err("ERR_HOLD_INVALID_STATE", 409,
                  "Scope edits require a DRAFT or ISSUED hold")
    created = []
    if hold["status"] == "DRAFT":
        for rid in record_ids:
            created.append(_new_scope_item(hold, rid, "PENDING_ISSUANCE"))
    else:  # ISSUED: immediately ACTIVE with full cascade
        t = now()
        before = {r["id"]: derive_posture(r) for r in records}
        for rid in record_ids:
            i = _new_scope_item(hold, rid, "ACTIVE")
            i["activated_at"] = t
            created.append(i)
        for r in records:
            bump(r)
            adjust_stale_for_record(r, before[r["id"]], derive_posture(r))
        hold["last_activity_at"] = t
        bump(hold)
    return success_list([hold_scope_item_view(i) for i in created],
                        len(created), 0, len(created), status=201)


@bp.route("/ig/legal-holds/<holdId>/scope-items/<itemId>", methods=["DELETE"])
def exclude_scope_item(holdId, itemId):
    authenticate(["LegalCounsel"])
    hold = _get_hold(holdId)
    item = db.hold_scope_items.get(itemId)
    if item is None:
        not_found("Hold scope item not found")
    if item["hold_id"] != hold["id"]:
        not_found("Hold scope item not found under the named hold")
    t = now()
    if hold["status"] == "DRAFT":
        if item["status"] != "PENDING_ISSUANCE":
            raise err("ERR_HOLD_INVALID_STATE", 409,
                      "Only a PENDING_ISSUANCE item can be removed from a "
                      "DRAFT hold")
        item["status"] = "CANCELLED"
        bump(item)
    elif hold["status"] == "ISSUED":
        if item["status"] != "ACTIVE":
            raise err("ERR_HOLD_INVALID_STATE", 409,
                      "Only an ACTIVE scope item can be excluded")
        rec = db.records[item["record_id"]]
        before = {rec["id"]: derive_posture(rec)}
        item["status"] = "EXCLUDED"
        item["released_at"] = t
        bump(item)
        bump(rec)
        adjust_stale_for_record(rec, before[rec["id"]], derive_posture(rec))
        hold["last_activity_at"] = t
        bump(hold)
    else:
        raise err("ERR_HOLD_INVALID_STATE", 409,
                  "Scope edits require a DRAFT or ISSUED hold")
    return success_empty(204)


@bp.route("/ig/legal-holds/<holdId>/custodians", methods=["POST"])
def add_custodians(holdId):
    authenticate(["LegalCounsel"])
    hold = _get_hold(holdId)
    body = body_json()
    custodian_ids = check_str_list(body, "custodian_ids")
    if len(custodian_ids) == 0:
        raise err("ERR_EMPTY_COLLECTION", 400,
                  "custodian_ids must be a non-empty collection")
    custodians = _resolve_custodians(custodian_ids, hold["program_id"])
    if hold["status"] not in ("DRAFT", "ISSUED"):
        raise err("ERR_HOLD_INVALID_STATE", 409,
                  "Custodian edits require a DRAFT or ISSUED hold")
    existing = {a["custodian_id"] for a in hold_assignments(hold["id"])}
    if len(set(custodian_ids)) != len(custodian_ids):
        raise err("ERR_DUPLICATE_CUSTODIAN", 409,
                  "A custodian may not appear twice on one hold")
    for cid in custodian_ids:
        if cid in existing:
            raise err("ERR_DUPLICATE_CUSTODIAN", 409,
                      "Custodian %s is already assigned to the hold" % cid)
    program = db.programs[hold["program_id"]]
    t = now()
    created = []
    if hold["status"] == "DRAFT":
        for cid in custodian_ids:
            created.append(_new_assignment(hold, cid, "AWAITING_ISSUANCE"))
    else:  # ISSUED: assignments start PENDING immediately
        for cid in custodian_ids:
            a = _new_assignment(hold, cid, "PENDING")
            a["ack_due_date"] = t + timedelta(days=program["ack_deadline_days"])
            created.append(a)
        hold["last_activity_at"] = t
        bump(hold)
    return success_list([hold_custodian_view(a) for a in created],
                        len(created), 0, len(created), status=201)


# ---------------------------------------------------------------------------
# Hold custodian assignments (read + acknowledge)
# ---------------------------------------------------------------------------
@bp.route("/ig/hold-custodians", methods=["GET"])
def list_hold_custodians():
    authenticate(ALL_ROLES)
    items = list(db.hold_custodians.values())
    a = request.args
    for f in ("hold_id", "custodian_id", "status", "program_id"):
        v = a.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([hold_custodian_view(x) for x in window],
                        limit, offset, total)


@bp.route("/ig/hold-custodians/<assignmentId>", methods=["GET"])
def get_hold_custodian(assignmentId):
    authenticate(ALL_ROLES)
    a = db.hold_custodians.get(assignmentId)
    if a is None:
        not_found("Hold custodian assignment not found")
    return success_object(hold_custodian_view(a))


@bp.route("/ig/hold-custodians/<assignmentId>/acknowledge", methods=["POST"])
def acknowledge_assignment(assignmentId):
    uid, _ = authenticate(["Custodian"])
    a = db.hold_custodians.get(assignmentId)
    if a is None:
        not_found("Hold custodian assignment not found")
    if a["status"] not in ("PENDING", "ESCALATED"):
        raise err("ERR_ASSIGNMENT_NOT_ACKNOWLEDGEABLE", 409,
                  "Assignment is not in PENDING or ESCALATED")
    if uid != a["custodian_id"]:
        raise err("ERR_NOT_CUSTODIAN_OF_ASSIGNMENT", 403,
                  "X-User-ID must equal the assignment's custodian_id")
    hold = db.legal_holds[a["hold_id"]]
    program = db.programs[hold["program_id"]]
    t = now()
    # ack_sla_evaluation: STRICT measures against the original due date;
    # REMINDER_ADJUSTED extends the deadline by one reminder interval per
    # reminder already sent. Late comparator is strict >.
    effective_due = a["ack_due_date"]
    if program["ack_sla_mode"] == "REMINDER_ADJUSTED":
        effective_due = effective_due + timedelta(
            days=a["reminder_count"] * program["reminder_interval_days"])
    was_late = t > effective_due
    a["status"] = "ACKNOWLEDGED"
    a["acknowledged_at"] = t
    a["was_late"] = was_late
    bump(a)
    hold["last_activity_at"] = t
    bump(hold)
    return success_object(hold_custodian_view(a))


# ---------------------------------------------------------------------------
# Hold scope items (read)
# ---------------------------------------------------------------------------
@bp.route("/ig/hold-scope-items", methods=["GET"])
def list_scope_items():
    authenticate(ALL_ROLES)
    items = list(db.hold_scope_items.values())
    a = request.args
    for f in ("hold_id", "record_id", "status", "program_id"):
        v = a.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([hold_scope_item_view(x) for x in window],
                        limit, offset, total)


@bp.route("/ig/hold-scope-items/<itemId>", methods=["GET"])
def get_scope_item(itemId):
    authenticate(ALL_ROLES)
    i = db.hold_scope_items.get(itemId)
    if i is None:
        not_found("Hold scope item not found")
    return success_object(hold_scope_item_view(i))
