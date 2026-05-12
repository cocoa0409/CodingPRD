"""Scholarship state-machine transitions, including cascades."""
import db
from clock import parse_iso, now
from errors import err
from services import calculations
from services.audit import emit_audit, emit_external_sync


ALL_STATUSES = ["DRAFT", "OPEN", "REVIEWING", "ANNOUNCED", "FINALIZED", "DISBURSED"]


# ---- Application transition primitive used by rank/realloc/objection ------

def transition_application(app: dict, new_status: str, *, actor_role=None, actor_id=None,
                            event_type: str = None, payload: dict = None,
                            external_sync: tuple = None) -> None:
    """Apply a state transition to an Application; bump version + emit audit/sync."""
    old = app.get("status")
    app["status"] = new_status
    db.stamp_update(app)
    if event_type is not None:
        emit_audit(event_type, "Application", app["id"],
                   payload if payload is not None else {"from": old, "to": new_status},
                   actor_role=actor_role, actor_id=actor_id)
    if external_sync is not None:
        kind, payload_ext = external_sync
        emit_external_sync(kind, app["scholarship_id"], application_id=app["id"], payload=payload_ext)


# ---- Scholarship transitions ----------------------------------------------

def scholarship_can_transition(scholarship: dict, to_status: str) -> bool:
    return _next_status(scholarship["status"]) == to_status


def _next_status(s: str) -> str:
    try:
        i = ALL_STATUSES.index(s)
    except ValueError:
        return None
    if i + 1 < len(ALL_STATUSES):
        return ALL_STATUSES[i + 1]
    return None


def can_advance_to_open(scholarship: dict):
    """Validate preconditions for DRAFT→OPEN (rubric weights, quota mismatch, window)."""
    rw = scholarship.get("rubric_weights") or {}
    weight_sum = sum(int(v) for v in rw.values())
    if weight_sum != 100:
        raise err("ERR_RUBRIC_WEIGHT_INVALID", "rubric_weights must sum to exactly 100")
    qslices = [q for q in db.quota_allocations.values() if q["scholarship_id"] == scholarship["id"]]
    init_sum = sum(q["initial_slots"] for q in qslices)
    if init_sum != scholarship["total_quota"]:
        raise err("ERR_QUOTA_MISMATCH", f"Sum of initial_slots ({init_sum}) != total_quota ({scholarship['total_quota']})")
    if now() < parse_iso(scholarship["application_window_start"]):
        raise err("ERR_WINDOW_NOT_OPEN", "now() < application_window_start")


def can_advance_to_reviewing(scholarship: dict):
    if now() < parse_iso(scholarship["application_window_end"]):
        raise err("ERR_WINDOW_NOT_CLOSED", "now() < application_window_end")


def can_advance_to_announced(scholarship: dict):
    # Every Application not in WITHDRAWN, DRAFT, DEPT_PRELIM_REJECTED must be REVIEW_COMPLETE.
    apps = [a for a in db.applications.values() if a["scholarship_id"] == scholarship["id"]]
    excluded = {"WITHDRAWN", "DRAFT", "DEPT_PRELIM_REJECTED"}
    for a in apps:
        if a["status"] in excluded:
            continue
        if a["status"] != "REVIEW_COMPLETE":
            raise err("ERR_REVIEW_NOT_COMPLETE",
                      f"Application {a['id']} status={a['status']} not REVIEW_COMPLETE")


def can_advance_to_finalized(scholarship: dict):
    if now() < parse_iso(scholarship["announcement_window_end"]):
        raise err("ERR_WINDOW_NOT_CLOSED", "now() < announcement_window_end")
    # No PENDING objection.
    for o in db.objections.values():
        app = db.applications.get(o.get("application_id"))
        if app is None or app["scholarship_id"] != scholarship["id"]:
            continue
        if o["status"] == "PENDING":
            raise err("ERR_OBJECTION_PENDING", "At least one PENDING Objection exists")


def can_advance_to_disbursed(scholarship: dict):
    plans = [p for p in db.disbursement_plans.values()
             if p["scholarship_id"] == scholarship["id"] and p["status"] == "EXECUTED"]
    if not plans:
        raise err("ERR_DISBURSEMENT_NOT_EXECUTED",
                  "No DisbursementPlan in EXECUTED state for this scholarship")


# ---- Execute the transition (preconditions assumed already validated) -----

def do_open(scholarship: dict, *, actor_role, actor_id):
    scholarship["status"] = "OPEN"
    db.stamp_update(scholarship)
    # No audit event at this transition per scaffold.


def do_reviewing(scholarship: dict, *, actor_role, actor_id):
    # Cascade: every DRAFT application → WITHDRAWN with audit emit.
    for a in list(db.applications.values()):
        if a["scholarship_id"] == scholarship["id"] and a["status"] == "DRAFT":
            transition_application(a, "WITHDRAWN",
                                   actor_role="system", actor_id="system",
                                   event_type="APPLICATION_WITHDRAWN",
                                   payload={"from": "DRAFT", "to": "WITHDRAWN", "cause": "WINDOW_CLOSED"})
    # Dynamic quota adjustment.
    calculations.dynamic_quota_adjustment(scholarship["id"])
    scholarship["status"] = "REVIEWING"
    db.stamp_update(scholarship)


def do_announced(scholarship: dict, *, actor_role, actor_id):
    # Rank-and-award.
    def on_transition(app, new_status):
        transition_application(app, new_status, actor_role="system", actor_id="system",
                               event_type=None)

    calculations.rank_and_award(scholarship["id"], on_transition)
    calculations.unfilled_quota_reallocation(scholarship["id"], on_transition)
    scholarship["status"] = "ANNOUNCED"
    db.stamp_update(scholarship)
    # External sync: one ACADEMIC_AFFAIRS_FINALIZED, then IM_NOTIFY_* per app.
    emit_external_sync("ACADEMIC_AFFAIRS_FINALIZED", scholarship["id"],
                       application_id=None,
                       payload={"scholarship_id": scholarship["id"]})
    for a in db.applications.values():
        if a["scholarship_id"] != scholarship["id"]:
            continue
        if a["status"] == "AWARDED":
            emit_external_sync("IM_NOTIFY_AWARD", scholarship["id"],
                               application_id=a["id"],
                               payload={"application_id": a["id"], "status": "AWARDED"})
        elif a["status"] == "NOT_AWARDED":
            emit_external_sync("IM_NOTIFY_REJECT", scholarship["id"],
                               application_id=a["id"],
                               payload={"application_id": a["id"], "status": "NOT_AWARDED"})
    emit_audit("FINALIZED", "Scholarship", scholarship["id"],
               {"from": "REVIEWING", "to": "ANNOUNCED"},
               actor_role=actor_role, actor_id=actor_id)


def do_finalized(scholarship: dict, *, actor_role, actor_id):
    scholarship["status"] = "FINALIZED"
    db.stamp_update(scholarship)


def do_disbursed(scholarship: dict, *, actor_role, actor_id):
    # Cascade: every AWARDED app → DISBURSED + audit + external sync.
    for a in list(db.applications.values()):
        if a["scholarship_id"] == scholarship["id"] and a["status"] == "AWARDED":
            transition_application(a, "DISBURSED",
                                   actor_role="system", actor_id="system",
                                   event_type=None,
                                   external_sync=("FINANCE_DISBURSED",
                                                  {"application_id": a["id"], "scholarship_id": scholarship["id"]}))
    # Archive the EXECUTED plan(s).
    for p in db.disbursement_plans.values():
        if p["scholarship_id"] == scholarship["id"] and p["status"] == "EXECUTED":
            p["status"] = "ARCHIVED"
            db.stamp_update(p)
    scholarship["status"] = "DISBURSED"
    db.stamp_update(scholarship)


# ---- Entry point: advance to a target status -------------------------------

ADVANCERS = {
    "OPEN":       (can_advance_to_open,       do_open),
    "REVIEWING":  (can_advance_to_reviewing,  do_reviewing),
    "ANNOUNCED":  (can_advance_to_announced,  do_announced),
    "FINALIZED":  (can_advance_to_finalized,  do_finalized),
    "DISBURSED":  (can_advance_to_disbursed,  do_disbursed),
}


def transition_scholarship(scholarship: dict, to_status: str, *, actor_role, actor_id):
    """Drive Scholarship status forward by one step. Validation must happen before this call."""
    advancer = ADVANCERS.get(to_status)
    if advancer is None:
        raise err("ERR_INVALID_STATE", f"Cannot transition to {to_status}")
    check_fn, do_fn = advancer
    check_fn(scholarship)
    do_fn(scholarship, actor_role=actor_role, actor_id=actor_id)
