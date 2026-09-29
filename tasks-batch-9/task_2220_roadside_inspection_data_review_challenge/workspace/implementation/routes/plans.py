"""Coaching assignments, corrective action plans and their action items."""

from flask import Blueprint

from db import base_record, get_or_404, serialize, sorted_rows, store, touch
from errors import err
from middleware import ALL_ROLES, actor, scope, scope_rows
from response import created, ok
from routes.helpers import filtered, listing, rows_of
from services import cascade
from services.calc import CATEGORIES, COACHING_DUE_DAYS, num
from validation import (body, get_dt, get_enum, get_int, get_str, pagination,
                        q_enum, q_str)

bp = Blueprint("plans", __name__)

CURRICULA = ("UNSAFE_DRIVING_101", "HOS_ELD_REFRESH", "PRETRIP_INSPECTION",
             "CDL_COMPLIANCE")
COACHING_STATUSES = ("ASSIGNED", "IN_PROGRESS", "COMPLETED", "OVERDUE",
                     "WAIVED", "ESCALATED")
CAP_STATUSES = ("DRAFT", "SUBMITTED", "IN_REVIEW", "PENDING_DECISION",
                "ACCEPTED", "RETURNED", "SUPERSEDED")
ITEM_STATUSES = ("PROPOSED", "COMMITTED", "IMPLEMENTED", "VERIFIED",
                 "REJECTED_ITEM")
ITEM_ACTIONS = ("COMMIT", "IMPLEMENT", "VERIFY", "REJECT")
ACTION_ROLE = {
    "COMMIT": "CarrierAnalyst",
    "IMPLEMENT": "CarrierSafetyManager",
    "VERIFY": "FmcsaProgramAuditor",
    "REJECT": "FmcsaProgramAuditor",
}
ACTIVE_CAP_STATUSES = ("DRAFT", "SUBMITTED", "IN_REVIEW", "PENDING_DECISION")
ITEM_EDITABLE_CAP_STATUSES = ("DRAFT", "RETURNED", "SUBMITTED", "IN_REVIEW")
CAP_REQUIRED_FITNESS = ("CONDITIONAL", "UNSATISFACTORY")
FITNESS_UPGRADE = {
    "UNSATISFACTORY": "CONDITIONAL",
    "CONDITIONAL": "SATISFACTORY",
}


# ---------------------------------------------------------------------------
# coaching assignments
# ---------------------------------------------------------------------------

@bp.post("/coaching-assignments")
def create_assignment():
    act = actor("CarrierSafetyManager")
    b = body()
    driver_id = get_str(b, "driver_id")
    violation_id = get_str(b, "violation_id")
    curriculum_code = get_enum(b, "curriculum_code", CURRICULA)
    session_start = get_dt(b, "session_start")
    session_end = get_dt(b, "session_end")
    if session_end.dt <= session_start.dt:
        raise err("ERR_INVALID_REQUEST",
                  "'session_end' must be after 'session_start'.")
    driver = get_or_404(store.drivers, driver_id, "ERR_DRIVER_NOT_FOUND")
    violation = get_or_404(store.violations, violation_id,
                           "ERR_VIOLATION_NOT_FOUND")
    scope(act, driver["carrier_id"])
    if driver["employment_status"] != "ACTIVE":
        raise err("ERR_DRIVER_NOT_EMPLOYED",
                  "Coaching requires an actively employed driver.")
    if violation.get("driver_id") != driver["id"]:
        raise err("ERR_VIOLATION_NOT_ATTRIBUTED_TO_DRIVER",
                  "The violation is not attributed to this driver.")
    report = store.reports.get(violation["report_id"])
    if report is None or report["status"] != "SCORED":
        raise err("ERR_INVALID_REPORT_STATE",
                  "Coaching requires a SCORED inspection report.")
    code = store.violation_codes.get(violation["effective_violation_code_id"])
    if code is None or not code.get("driver_attributable"):
        raise err("ERR_CODE_NOT_DRIVER_ATTRIBUTABLE",
                  "The violation code is not driver attributable.")
    for existing in store.coaching.values():
        if existing["driver_id"] != driver["id"]:
            continue
        if existing["status"] not in cascade.OPEN_COACHING_STATUSES:
            continue
        if (existing["session_start"].dt < session_end.dt
                and session_start.dt < existing["session_end"].dt):
            raise err("ERR_COACHING_WINDOW_CONFLICT",
                      "The driver already has coaching in that window.")

    assignment = base_record()
    assignment.update({
        "carrier_id": driver["carrier_id"],
        "driver_id": driver["id"],
        "violation_id": violation["id"],
        "curriculum_code": curriculum_code,
        "session_start": session_start,
        "session_end": session_end,
        "due_at": session_end.plus_days(COACHING_DUE_DAYS),
        "status": "ASSIGNED",
        "started_at": None,
        "completed_at": None,
        "attestation_note": None,
        "waived_reason": None,
        "overdue_marked_run_id": None,
    })
    store.coaching[assignment["id"]] = assignment
    cascade.refresh_open_coaching(driver["id"], driver["carrier_id"])
    return created(serialize(assignment))


@bp.get("/coaching-assignments")
def list_assignments():
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.coaching), [
        ("driver_id", q_str("driver_id")),
        ("violation_id", q_str("violation_id")),
        ("carrier_id", q_str("carrier_id")),
        ("status", q_enum("status", COACHING_STATUSES)),
        ("overdue_marked_run_id", q_str("overdue_marked_run_id")),
    ])
    rows = scope_rows(act, rows, "carrier_id")
    return listing(rows, limit, offset)


@bp.get("/coaching-assignments/<assignment_id>")
def get_assignment(assignment_id):
    act = actor(*ALL_ROLES)
    assignment = get_or_404(store.coaching, assignment_id, "ERR_COACHING_NOT_FOUND")
    scope(act, assignment["carrier_id"])
    return ok(serialize(assignment))


@bp.post("/coaching-assignments/<assignment_id>/start")
def start_assignment(assignment_id):
    act = actor("CarrierSafetyManager")
    assignment = get_or_404(store.coaching, assignment_id, "ERR_COACHING_NOT_FOUND")
    scope(act, assignment["carrier_id"])
    if assignment["status"] not in ("ASSIGNED", "OVERDUE"):
        raise err("ERR_INVALID_COACHING_STATE",
                  "Only an ASSIGNED or OVERDUE assignment can be started.")
    driver = store.drivers.get(assignment["driver_id"])
    if driver is None or driver["employment_status"] != "ACTIVE":
        raise err("ERR_DRIVER_NOT_EMPLOYED",
                  "Coaching requires an actively employed driver.")
    assignment["status"] = "IN_PROGRESS"
    assignment["started_at"] = store.now_ts()
    touch(assignment)
    cascade.refresh_open_coaching(assignment["driver_id"],
                                 assignment["carrier_id"])
    return ok(serialize(assignment))


@bp.post("/coaching-assignments/<assignment_id>/complete")
def complete_assignment(assignment_id):
    act = actor("CarrierSafetyManager")
    b = body()
    attestation_note = get_str(b, "attestation_note", max_len=2000)
    assignment = get_or_404(store.coaching, assignment_id, "ERR_COACHING_NOT_FOUND")
    scope(act, assignment["carrier_id"])
    if assignment["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_COACHING_STATE",
                  "Only an IN_PROGRESS assignment can be completed.")
    assignment["status"] = "COMPLETED"
    assignment["completed_at"] = store.now_ts()
    assignment["attestation_note"] = attestation_note
    touch(assignment)
    cascade.refresh_open_coaching(assignment["driver_id"],
                                 assignment["carrier_id"])
    return ok(serialize(assignment))


# ---------------------------------------------------------------------------
# corrective action plans
# ---------------------------------------------------------------------------

def items_of(cap_id):
    return sorted_rows([i for i in store.cap_items.values()
                        if i["cap_id"] == cap_id])


def rollup_cap(cap):
    before = cascade.snap(cap, ("item_count", "committed_item_count",
                                "verified_item_count", "completion_pct"))
    rows = items_of(cap["id"])
    counted = [i for i in rows if i["status"] != "REJECTED_ITEM"]
    committed = [i for i in rows
                 if i["status"] in ("COMMITTED", "IMPLEMENTED", "VERIFIED")]
    verified = [i for i in rows if i["status"] == "VERIFIED"]
    denominator = len(counted) if len(counted) > 0 else 1
    cap["item_count"] = len(counted)
    cap["committed_item_count"] = len(committed)
    cap["verified_item_count"] = len(verified)
    cap["completion_pct"] = num(100.0 * len(verified) / denominator, 1)
    cascade.finish(cap, before)


def evaluate_join(cap):
    if cap["status"] != "IN_REVIEW":
        return
    if cap.get("safety_review_outcome") != "CLEARED":
        return
    if cap.get("data_review_outcome") != "CLEARED":
        return
    if cap.get("completion_pct") != 100.0:
        return
    cap["status"] = "PENDING_DECISION"
    touch(cap)


@bp.post("/corrective-action-plans")
def create_cap():
    act = actor("CarrierAnalyst")
    b = body()
    carrier_id = get_str(b, "carrier_id")
    expected_carrier_version = get_int(b, "expected_carrier_version", minimum=0)
    narrative = get_str(b, "narrative", max_len=4000)
    carrier = get_or_404(store.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")
    scope(act, carrier["id"])
    if expected_carrier_version != carrier["version"]:
        raise err("ERR_STALE_CARRIER_VERSION",
                  "The carrier has advanced since it was read.")
    for existing in store.caps.values():
        if (existing["carrier_id"] == carrier["id"]
                and existing["status"] in ACTIVE_CAP_STATUSES):
            raise err("ERR_ACTIVE_CAP_EXISTS",
                      "The carrier already holds an active corrective action plan.")
    if carrier["safety_fitness_status"] not in CAP_REQUIRED_FITNESS:
        raise err("ERR_CAP_NOT_REQUIRED",
                  "A corrective action plan is not required for this carrier.")
    returned = [c for c in sorted_rows(list(store.caps.values()))
                if c["carrier_id"] == carrier["id"] and c["status"] == "RETURNED"]
    superseded = returned[-1] if returned else None

    cap = base_record()
    cap.update({
        "carrier_id": carrier["id"],
        "superseded_cap_id": superseded["id"] if superseded else None,
        "narrative": narrative,
        "status": "DRAFT",
        "triggering_fitness_status": carrier["safety_fitness_status"],
        "safety_review_outcome": None,
        "safety_review_user_id": None,
        "data_review_outcome": None,
        "data_review_user_id": None,
        "item_count": 0,
        "committed_item_count": 0,
        "verified_item_count": 0,
        "completion_pct": 0.0,
        "decision": None,
        "decided_by_user_id": None,
        "decided_at": None,
    })
    store.caps[cap["id"]] = cap
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
    touch(carrier)
    return created(serialize(cap))


@bp.get("/corrective-action-plans")
def list_caps():
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.caps), [
        ("carrier_id", q_str("carrier_id")),
        ("status", q_enum("status", CAP_STATUSES)),
        ("superseded_cap_id", q_str("superseded_cap_id")),
    ])
    rows = scope_rows(act, rows, "carrier_id")
    return listing(rows, limit, offset)


@bp.get("/corrective-action-plans/<cap_id>")
def get_cap(cap_id):
    act = actor(*ALL_ROLES)
    cap = get_or_404(store.caps, cap_id, "ERR_CAP_NOT_FOUND")
    scope(act, cap["carrier_id"])
    return ok(serialize(cap))


@bp.post("/corrective-action-plans/<cap_id>/action-items")
def create_cap_item(cap_id):
    act = actor("CarrierAnalyst")
    b = body()
    basic_category = get_enum(b, "basic_category", CATEGORIES)
    description = get_str(b, "description", max_len=2000)
    target_completion_date = get_dt(b, "target_completion_date")
    cap = get_or_404(store.caps, cap_id, "ERR_CAP_NOT_FOUND")
    scope(act, cap["carrier_id"])
    if cap["status"] not in ITEM_EDITABLE_CAP_STATUSES:
        raise err("ERR_INVALID_CAP_STATE",
                  "Action items cannot be added to this plan any more.")
    item = base_record()
    item.update({
        "cap_id": cap["id"],
        "basic_category": basic_category,
        "description": description,
        "target_completion_date": target_completion_date,
        "status": "PROPOSED",
        "rejection_note": None,
        "verified_by_user_id": None,
    })
    store.cap_items[item["id"]] = item
    rollup_cap(cap)
    return created(serialize(item))


@bp.get("/corrective-action-plans/<cap_id>/action-items")
def list_cap_items(cap_id):
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    cap = get_or_404(store.caps, cap_id, "ERR_CAP_NOT_FOUND")
    scope(act, cap["carrier_id"])
    return listing(items_of(cap["id"]), limit, offset)


@bp.post("/cap-action-items/<item_id>/status")
def set_item_status(item_id):
    act = actor("CarrierAnalyst", "CarrierSafetyManager", "FmcsaProgramAuditor")
    b = body()
    action = get_enum(b, "action", ITEM_ACTIONS)
    note = get_str(b, "note", required=False, max_len=2000)
    if act.role != ACTION_ROLE[action]:
        raise err("ERR_ROLE_NOT_PERMITTED",
                  "The acting role may not perform this action.")
    item = get_or_404(store.cap_items, item_id, "ERR_CAP_ITEM_NOT_FOUND")
    cap = store.caps.get(item["cap_id"])
    scope(act, cap["carrier_id"] if cap else None)

    if action == "COMMIT":
        if item["status"] not in ("PROPOSED", "REJECTED_ITEM"):
            raise err("ERR_INVALID_CAP_ITEM_STATE",
                      "Only a PROPOSED or REJECTED_ITEM item can be committed.")
        if cap is None or cap["status"] not in ITEM_EDITABLE_CAP_STATUSES:
            raise err("ERR_INVALID_CAP_STATE",
                      "The plan does not accept item commitments.")
        item["status"] = "COMMITTED"
    elif action == "IMPLEMENT":
        if item["status"] != "COMMITTED":
            raise err("ERR_INVALID_CAP_ITEM_STATE",
                      "Only a COMMITTED item can be implemented.")
        item["status"] = "IMPLEMENTED"
    elif action == "VERIFY":
        if item["status"] != "IMPLEMENTED":
            raise err("ERR_INVALID_CAP_ITEM_STATE",
                      "Only an IMPLEMENTED item can be verified.")
        item["status"] = "VERIFIED"
        item["verified_by_user_id"] = act.user_id
    else:  # REJECT
        if item["status"] not in ("COMMITTED", "IMPLEMENTED"):
            raise err("ERR_INVALID_CAP_ITEM_STATE",
                      "Only a COMMITTED or IMPLEMENTED item can be rejected.")
        item["status"] = "REJECTED_ITEM"
        item["rejection_note"] = note
    touch(item)
    if cap is not None:
        rollup_cap(cap)
        evaluate_join(cap)
    return ok(serialize(item))


@bp.post("/corrective-action-plans/<cap_id>/submit")
def submit_cap(cap_id):
    act = actor("CarrierSafetyManager")
    cap = get_or_404(store.caps, cap_id, "ERR_CAP_NOT_FOUND")
    scope(act, cap["carrier_id"])
    if cap["status"] not in ("DRAFT", "RETURNED"):
        raise err("ERR_INVALID_CAP_STATE",
                  "Only a DRAFT or RETURNED plan can be submitted.")
    carrier = store.carriers.get(cap["carrier_id"])
    if carrier is None or carrier["safety_fitness_status"] not in CAP_REQUIRED_FITNESS:
        raise err("ERR_CAP_NOT_REQUIRED",
                  "A corrective action plan is not required for this carrier.")
    rollup_cap(cap)
    if cap["item_count"] < 1 or cap["committed_item_count"] != cap["item_count"]:
        raise err("ERR_CAP_ITEMS_INCOMPLETE",
                  "Every action item must be committed before submission.")
    cap["status"] = "SUBMITTED"
    cap["safety_review_outcome"] = None
    cap["safety_review_user_id"] = None
    cap["data_review_outcome"] = None
    cap["data_review_user_id"] = None
    touch(cap)
    return ok(serialize(cap))


@bp.post("/corrective-action-plans/<cap_id>/reviews")
def review_cap(cap_id):
    act = actor("FmcsaProgramAuditor")
    b = body()
    branch = get_enum(b, "branch", ("SAFETY", "DATA"))
    outcome = get_enum(b, "outcome", ("CLEARED", "DEFICIENT"))
    get_str(b, "note", required=False, max_len=2000)
    cap = get_or_404(store.caps, cap_id, "ERR_CAP_NOT_FOUND")
    if cap["status"] not in ("SUBMITTED", "IN_REVIEW"):
        raise err("ERR_INVALID_CAP_STATE",
                  "The plan is not awaiting branch reviews.")
    own_outcome = "safety_review_outcome" if branch == "SAFETY" \
        else "data_review_outcome"
    own_user = "safety_review_user_id" if branch == "SAFETY" \
        else "data_review_user_id"
    other_user = "data_review_user_id" if branch == "SAFETY" \
        else "safety_review_user_id"
    if cap.get(other_user) == act.user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The other review branch was recorded by this user.")
    if cap.get(own_outcome) is not None:
        raise err("ERR_REVIEW_BRANCH_ALREADY_RECORDED",
                  "This review branch has already been recorded.")
    cap[own_outcome] = outcome
    cap[own_user] = act.user_id
    if outcome == "DEFICIENT":
        cap["status"] = "RETURNED"
        touch(cap)
        return ok(serialize(cap))
    cap["status"] = "IN_REVIEW"
    touch(cap)
    evaluate_join(cap)
    return ok(serialize(cap))


@bp.post("/corrective-action-plans/<cap_id>/decision")
def decide_cap(cap_id):
    act = actor("FmcsaProgramAuditor")
    b = body()
    decision = get_enum(b, "decision", ("ACCEPT", "RETURN"))
    get_str(b, "note", required=False, max_len=2000)
    cap = get_or_404(store.caps, cap_id, "ERR_CAP_NOT_FOUND")
    if cap["status"] != "PENDING_DECISION":
        raise err("ERR_INVALID_CAP_STATE",
                  "Only a plan awaiting decision can be decided.")
    carrier = store.carriers.get(cap["carrier_id"])
    if (carrier is not None
            and carrier.get("fitness_determined_by_user_id") == act.user_id):
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The auditor who issued the fitness determination may not "
                  "decide this plan.")
    cap["decision"] = decision
    cap["decided_by_user_id"] = act.user_id
    cap["decided_at"] = store.now_ts()
    if decision == "ACCEPT":
        cap["status"] = "ACCEPTED"
        if carrier is not None:
            upgraded = FITNESS_UPGRADE.get(carrier["safety_fitness_status"])
            if upgraded is not None:
                carrier["safety_fitness_status"] = upgraded
                touch(carrier)
    else:
        cap["status"] = "RETURNED"
    touch(cap)
    return ok(serialize(cap))
