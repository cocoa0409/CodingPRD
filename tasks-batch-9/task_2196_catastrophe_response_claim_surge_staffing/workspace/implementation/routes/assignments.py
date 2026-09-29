"""InspectionAssignment endpoints.  STRICT HALF-OPEN windows, zero buffer."""
from flask import Blueprint, request

import calc
import derive
import ops
import store
import sync
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing, require_open_posture
from store import clock_now, dec, sorted_rows, touch

bp = Blueprint("assignments", __name__)

MODES = ("FIELD", "DESK", "AERIAL")


def _window_conflict(adjuster_id, start, end):
    for a in store.assignments.values():
        if a["adjuster_id"] != adjuster_id:
            continue
        if a["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        # Zero buffer: exact adjacency is accepted.
        if start < a["window_end_utc"] and a["window_start_utc"] < end:
            return True
    return False


@bp.post("/inspection-assignments")
def create_assignment():
    begin()
    soft = validate.soft_body()
    # Existence: claim (5), adjuster (6), deployment (8).
    raw_claim = validate.raw_ref(soft, "claim_id")
    claim = validate.claim(raw_claim) if raw_claim is not None else None
    raw_adjuster = validate.raw_ref(soft, "adjuster_id")
    adjuster = validate.adjuster(raw_adjuster) if raw_adjuster is not None else None
    raw_deployment = validate.raw_ref(soft, "deployment_id")
    deployment = validate.deployment(raw_deployment) \
        if raw_deployment is not None else None

    payload = validate.body()
    if claim is None:
        validate.req_string(payload, "claim_id")
    mode = validate.req_enum(payload, "mode", MODES)
    start = validate.req_datetime(payload, "window_start_utc")
    end = validate.req_datetime(payload, "window_end_utc")
    # Position 16.
    validate.interval(start, end,
                      "window_end_utc must be strictly later than window_start_utc.")
    event = store.events.get(claim["event_id"])
    # Position 20.
    if event is not None:
        require_open_posture(event)

    explicit = adjuster is not None
    # Position 25 - STRICT HALF-OPEN conflict on the named adjuster.
    if explicit and _window_conflict(adjuster["id"], start, end):
        fail("ERR_ASSIGNMENT_WINDOW_CONFLICT")
    # Position 26 - CONTAINMENT inside the funding deployment.
    if deployment is not None:
        if not (deployment["window_start_utc"] <= start
                and end <= deployment["window_end_utc"]):
            fail("ERR_ASSIGNMENT_OUTSIDE_DEPLOYMENT")
    # Position 27 - licensing of the named adjuster.
    if explicit and event is not None \
            and adjuster["credential_status"] != "WAIVED" \
            and event["jurisdiction_state"] not in adjuster["licensed_states"]:
        fail("ERR_ADJUSTER_NOT_LICENSED_IN_STATE")
    # Position 29 - the mode must equal the claim's mode as computed now.
    # Pair C: this outranks the capacity check at position 32.
    current_mode = calc.inspection_mode(claim) if claim.get("triage_tier") is not None \
        else claim.get("inspection_mode")
    if mode != current_mode:
        fail("ERR_INSPECTION_MODE_MISMATCH")
    # Position 30 - the funding deployment must sit on the claim's event.
    if deployment is not None and deployment["event_id"] != claim["event_id"]:
        fail("ERR_EVENT_SCOPE_MISMATCH")
    # Position 32 - capacity of the named adjuster.
    if explicit and derive.adjuster_open_assignment_count(adjuster["id"]) \
            >= adjuster["max_open_claims"]:
        fail("ERR_ADJUSTER_AT_CAPACITY")

    if not explicit:
        # Position 35 - the ranked pool must not be empty.  The eligibility
        # filter is exactly the declared one: mode stands in for role_type.
        if event is None:
            fail("ERR_NO_ELIGIBLE_ADJUSTER")
        adjuster = ops.select_adjuster(event, mode, start, end)

    rec = store.base_record()
    rec.update({
        "claim_id": claim["id"],
        "adjuster_id": adjuster["id"],
        "deployment_id": None if deployment is None else deployment["id"],
        "mode": mode,
        "window_start_utc": start,
        "window_end_utc": end,
        "status": "SCHEDULED",
        "verified_damage_amount": None,
        "report_submitted_at_utc": None,
        "selection_reason": "EXPLICIT_ADJUSTER" if explicit else "SELECTOR_RANKED",
    })
    store.assignments[rec["id"]] = rec
    if claim["handling_status"] in ("TRIAGED", "REOPENED"):
        claim["handling_status"] = "INSPECTION_PENDING"
        touch(claim)
    if event is not None:
        touch(event)
    return created(derive.assignment_out(rec))


@bp.get("/inspection-assignments")
def list_assignments():
    begin()
    rows = list(store.assignments.values())
    for param, field in (("claim_id", "claim_id"), ("adjuster_id", "adjuster_id"),
                         ("deployment_id", "deployment_id"),
                         ("status", "status"), ("mode", "mode")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, derive.assignment_out)


@bp.get("/inspection-assignments/<assignment_id>")
def read_assignment(assignment_id):
    begin()
    return ok(derive.assignment_out(validate.assignment(assignment_id)))


def _require_owner(rec, user_id):
    """Ladder position 17 - entity-backed Adjuster identity."""
    if user_id != rec["adjuster_id"]:
        fail("ERR_NOT_ASSIGNED_ADJUSTER")


@bp.post("/inspection-assignments/<assignment_id>/start")
def start_assignment(assignment_id):
    user_id, _role = begin()
    rec = validate.assignment(assignment_id)
    _require_owner(rec, user_id)
    if rec["status"] != "SCHEDULED":
        fail("ERR_ASSIGNMENT_NOT_SCHEDULED")
    if clock_now() < rec["window_start_utc"]:
        fail("ERR_ASSIGNMENT_WINDOW_NOT_STARTED")
    adjuster = store.adjusters.get(rec["adjuster_id"])
    if adjuster is None \
            or adjuster["credential_status"] not in ("VALID", "EXPIRING", "WAIVED"):
        fail("ERR_ADJUSTER_CREDENTIAL_INVALID")
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    return ok(derive.assignment_out(rec))


@bp.post("/inspection-assignments/<assignment_id>/complete")
def complete_assignment(assignment_id):
    user_id, _role = begin()
    rec = validate.assignment(assignment_id)
    payload = validate.soft_body()
    raw = payload.get("verified_damage_amount")
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        fail("ERR_VERIFIED_AMOUNT_REQUIRED")
    amount = dec(raw)
    if amount < 0:
        fail("ERR_VERIFIED_AMOUNT_REQUIRED")
    _require_owner(rec, user_id)
    if rec["status"] != "IN_PROGRESS":
        fail("ERR_ASSIGNMENT_NOT_IN_PROGRESS")

    rec["status"] = "COMPLETED"
    rec["verified_damage_amount"] = amount
    rec["report_submitted_at_utc"] = clock_now()
    touch(rec)

    claim = store.claims.get(rec["claim_id"])
    if claim is not None:
        if claim["handling_status"] == "INSPECTION_PENDING":
            claim["handling_status"] = "INSPECTED"
        refreshed = derive.claim_verified_damage(claim["id"])
        if refreshed is not None:
            claim["verified_damage_amount"] = refreshed
            ops.revision_after_completion(
                claim, "Reserve revised to verified damage after inspection")
        touch(claim)
        event = store.events.get(claim["event_id"])
        if event is not None:
            touch(event)
    return ok(derive.assignment_out(rec))


@bp.post("/inspection-assignments/<assignment_id>/report-no-access")
def report_no_access(assignment_id):
    user_id, _role = begin()
    rec = validate.assignment(assignment_id)
    _require_owner(rec, user_id)
    if rec["status"] != "IN_PROGRESS":
        fail("ERR_ASSIGNMENT_NOT_IN_PROGRESS")

    rec["status"] = "NO_ACCESS"
    rec["report_submitted_at_utc"] = clock_now()
    touch(rec)
    claim = store.claims.get(rec["claim_id"])
    if claim is not None:
        claim["access_status"] = "INACCESSIBLE"
        if claim.get("triage_tier") is not None:
            claim["inspection_mode"] = calc.inspection_mode(claim)
        if claim["handling_status"] == "INSPECTION_PENDING":
            claim["handling_status"] = "INSPECTED"
        touch(claim)
    return ok(derive.assignment_out(rec))


@bp.post("/inspection-assignments/<assignment_id>/cancel")
def cancel_assignment(assignment_id):
    begin()
    rec = validate.assignment(assignment_id)
    if rec["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        fail("ERR_ASSIGNMENT_NOT_CANCELLABLE")
    rec["status"] = "CANCELLED"
    touch(rec)
    sync.regress_claim(rec["claim_id"])
    claim = store.claims.get(rec["claim_id"])
    if claim is not None:
        event = store.events.get(claim["event_id"])
        if event is not None:
            touch(event)
    return ok(derive.assignment_out(rec))
