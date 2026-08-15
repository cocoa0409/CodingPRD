"""Leak endpoints (PRD §3.5, §3.7): report, regrade, schedule-repair,
verify-clear, plus regrade-event and repair-order navigation."""
from flask import g, request

from db import STORE, make_entity, now, serialize, touch
from errors import bad_request, err
from middleware import (body, parse_pagination, req_bool, req_enum, req_int,
                        req_num, req_str, require_roles)
from response import list_response, success
from services import (EXCAVATION_METHODS, FIELDS, MAX_REGRADE_COUNT,
                      PRIORITY_BY_GRADE, compute_grade, get_or_404,
                      refresh_segment, repair_due, sorted_all,
                      stale_current_snapshots)
from . import bp

LEAK_READ_ROLES = ("IntegrityAnalyst", "ComplianceOfficer", "FieldTechnician",
                   "DispatchCoordinator")
GRADES = ["G1", "G2", "G3"]
REPAIR_METHODS = ["CLAMP", "WRAP", "CUT_AND_REPLACE", "ABANDON_SEGMENT",
                  "INSERT_LINER"]


def ser(leak):
    return serialize(leak, FIELDS["leaks"])


@bp.post("/leaks")
@require_roles("FieldTechnician")
def create_leak():
    d = body()
    segment_id = req_str(d, "segment_id")
    run_id = req_str(d, "survey_run_id")
    conc = req_num(d, "concentration_ppm")
    dist = d.get("distance_to_building_feet")
    if dist is not None and (isinstance(dist, bool)
                             or not isinstance(dist, (int, float))):
        raise bad_request("distance_to_building_feet must be a number or null")
    lel = req_num(d, "bar_hole_reading_pct_lel")
    if not (0 <= lel <= 100):
        raise bad_request("bar_hole_reading_pct_lel must be between 0 and 100")
    migration = req_bool(d, "is_migration_evidence")
    seg = get_or_404("pipe_segments", segment_id)
    get_or_404("survey_runs", run_id)
    if isinstance(conc, float):
        from decimal import Decimal, ROUND_HALF_UP
        conc = int(Decimal(str(conc)).quantize(Decimal("1"),
                                               rounding=ROUND_HALF_UP))
    discovered = now()
    grade = compute_grade(conc, dist, lel, migration,
                          seg["is_high_consequence_area"])
    leak = make_entity()
    leak.update({
        "segment_id": segment_id, "survey_run_id": run_id,
        "discovered_at": discovered, "concentration_ppm": conc,
        "distance_to_building_feet": dist, "bar_hole_reading_pct_lel": lel,
        "is_migration_evidence": migration, "grade": grade,
        "repair_due_at": repair_due(discovered, grade), "regrade_count": 0,
        "status": "OPEN", "_verified_at": None,
    })
    STORE["leaks"][leak["id"]] = leak
    refresh_segment(seg)
    stale_current_snapshots()
    return success(ser(leak), code=201)


@bp.get("/leaks")
@require_roles(*LEAK_READ_ROLES)
def list_leaks():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    grade = request.args.get("grade")
    segment_id = request.args.get("segment_id")
    items = sorted_all("leaks")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if grade is not None:
        items = [l for l in items if l["grade"] == grade]
    if segment_id is not None:
        items = [l for l in items if l["segment_id"] == segment_id]
    return list_response(items, ser, limit, offset)


@bp.get("/leaks/<lid>")
@require_roles(*LEAK_READ_ROLES)
def get_leak(lid):
    return success(ser(get_or_404("leaks", lid)))


@bp.get("/leaks/<lid>/regrade-events")
@require_roles("IntegrityAnalyst", "ComplianceOfficer", "FieldTechnician")
def leak_regrade_events(lid):
    get_or_404("leaks", lid)
    limit, offset = parse_pagination()
    items = [e for e in sorted_all("regrade_events") if e["leak_id"] == lid]
    return list_response(items,
                         lambda e: serialize(e, FIELDS["regrade_events"]),
                         limit, offset)


@bp.get("/leaks/<lid>/repair-orders")
@require_roles("IntegrityAnalyst", "DispatchCoordinator", "ComplianceOfficer")
def leak_repair_orders(lid):
    get_or_404("leaks", lid)
    limit, offset = parse_pagination()
    ds = request.args.get("dispatch_status")
    items = [o for o in sorted_all("repair_orders") if o["leak_id"] == lid]
    if ds is not None:
        items = [o for o in items if o["dispatch_status"] == ds]
    return list_response(items,
                         lambda o: serialize(o, FIELDS["repair_orders"]),
                         limit, offset)


@bp.post("/leaks/<lid>/regrade")
@require_roles("FieldTechnician")
def regrade_leak(lid):
    leak = get_or_404("leaks", lid)
    d = body()
    new_grade = req_enum(d, "new_grade", GRADES)
    reason = req_str(d, "reason")
    if leak["status"] != "OPEN":
        raise err("ERR_LEAK_NOT_OPEN", "Leak.status != OPEN", 409)
    if leak["regrade_count"] >= MAX_REGRADE_COUNT:
        raise err("ERR_REGRADE_LIMIT_EXCEEDED",
                  "Leak.regrade_count has reached 3", 422)
    if new_grade == leak["grade"]:
        raise err("ERR_REGRADE_SAME_GRADE",
                  "new_grade equals current grade", 422)
    old_grade = leak["grade"]
    event = make_entity()
    event.update({"leak_id": leak["id"], "previous_grade": old_grade,
                  "new_grade": new_grade, "reason": reason,
                  "performed_by_user_id": g.user_id, "triggered_at": now()})
    STORE["regrade_events"][event["id"]] = event
    leak["grade"] = new_grade
    leak["repair_due_at"] = repair_due(leak["discovered_at"], new_grade)
    leak["regrade_count"] += 1
    touch(leak)
    seg = STORE["pipe_segments"].get(leak["segment_id"])
    if seg is not None:
        refresh_segment(seg)
    stale_current_snapshots()
    return success(ser(leak))


@bp.post("/leaks/<lid>/schedule-repair")
@require_roles("DispatchCoordinator")
def schedule_repair(lid):
    leak = get_or_404("leaks", lid)
    d = body()
    method = req_enum(d, "repair_method", REPAIR_METHODS)
    expected = req_int(d, "expected_leak_version")
    if leak["status"] != "OPEN":
        raise err("ERR_LEAK_NOT_OPEN", "Leak.status != OPEN", 409)
    seg = STORE["pipe_segments"].get(leak["segment_id"])
    if seg is None or seg["status"] != "ACTIVE":
        raise err("ERR_SEGMENT_NOT_ACTIVE", "PipeSegment.status != ACTIVE", 409)
    if expected != leak["version"]:
        raise err("ERR_STALE_LEAK_VERSION",
                  "expected_leak_version mismatches Leak.version", 412)
    order = make_entity()
    order.update({
        "leak_id": leak["id"], "priority": PRIORITY_BY_GRADE[leak["grade"]],
        "crew_id": None, "dispatched_at": None, "repair_method": method,
        "dispatch_status": "PENDING_DISPATCH",
        "excavation_permit_status": ("PERMIT_REQUIRED"
                                     if method in EXCAVATION_METHODS
                                     else "NOT_REQUIRED"),
        "completed_at": None, "verified_by_officer_id": None,
    })
    STORE["repair_orders"][order["id"]] = order
    leak["status"] = "REPAIR_SCHEDULED"
    touch(leak)
    return success(serialize(order, FIELDS["repair_orders"]), code=201)


@bp.post("/leaks/<lid>/verify-clear")
@require_roles("ComplianceOfficer")
def verify_clear(lid):
    leak = get_or_404("leaks", lid)
    if leak["status"] != "REPAIRED_PENDING_VERIFICATION":
        raise err("ERR_LEAK_NOT_PENDING_VERIFICATION",
                  "Leak.status != REPAIRED_PENDING_VERIFICATION", 409)
    origin_run = STORE["survey_runs"].get(leak["survey_run_id"])
    if origin_run is not None and origin_run["technician_id"] == g.user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Verifying officer must differ from the originating "
                  "survey technician", 422)
    completed = [o for o in STORE["repair_orders"].values()
                 if o["leak_id"] == lid and o["completed_at"] is not None]
    completed_at = (max(o["completed_at"] for o in completed)
                    if completed else None)
    found = False
    for run in STORE["survey_runs"].values():
        if run["status"] != "ACCEPTED":
            continue
        if any(l["survey_run_id"] == run["id"] for l in STORE["leaks"].values()):
            continue  # not leak-free
        covered = any(a["route_id"] == run["route_id"]
                      and a["segment_id"] == leak["segment_id"]
                      and a["status"] == "COVERED"
                      for a in STORE["route_segment_assignments"].values())
        if not covered:
            continue
        if completed_at is not None and run["created_at"] < completed_at:
            continue  # must be post-repair
        found = True
        break
    if not found:
        raise err("ERR_NO_POST_REPAIR_SURVEY",
                  "No ACCEPTED post-repair SurveyRun with a leak-free finding "
                  "exists for the segment", 422)
    leak["status"] = "VERIFIED_CLEARED"
    leak["_verified_at"] = now()
    touch(leak)
    if completed:
        order = max(completed, key=lambda o: o["completed_at"])
        order["verified_by_officer_id"] = g.user_id
        touch(order)
    seg = STORE["pipe_segments"].get(leak["segment_id"])
    if seg is not None:
        refresh_segment(seg, recompute_risk=True)
    stale_current_snapshots()
    return success(ser(leak))
