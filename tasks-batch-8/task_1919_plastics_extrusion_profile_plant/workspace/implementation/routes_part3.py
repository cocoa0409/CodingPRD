"""Routes: line assignments, runs, SPC samples, bundles, purge events,
resin index points, and the logical clock."""
import re
from decimal import ROUND_FLOOR

from flask import request

from state import (
    D, ApiError, err_bad,
    customers, profiles, dies, lines, lots, formulations, batches,
    work_orders, assignments, runs, samples, bundles, purge_events,
    index_points, index_by_month, CLOCK,
    endpoint, list_result, get_body, Fields, require_exists,
    pagination, paginate, sort_created, mark, stamp_new, stamp_new_lean,
    parse_dt, ts_iso, ser_assignment, ser_run, ser_sample, ser_bundle,
    ser_purge, ser_index_point,
    COLOR_FAMILIES, ALL_ROLES,
)
from services import (
    wo_close_check, wo_revert_check, hold_run_system,
    purge_estimate, credit_die_for_run, build_cut_plan, evaluate_spc,
    restate_cascade,
)

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ============================ Line assignments =============================
@endpoint("/line-assignments", ["POST"], ["ProcessEngineer"])
def create_assignment(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("work_order_id")
    f.str_("die_id")
    f.str_("line_id")
    f.str_("planned_start")
    f.str_("planned_end")
    wo = die = line = None
    v = f.values.get("work_order_id")
    if isinstance(v, str):
        wo = require_exists(work_orders, v, "WorkOrder")
    v = f.values.get("die_id")
    if isinstance(v, str):
        die = require_exists(dies, v, "Die")
    v = f.values.get("line_id")
    if isinstance(v, str):
        line = require_exists(lines, v, "ExtrusionLine")
    # priority 6: assignments only against a CONFIRMED order
    if wo is not None and wo["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Assignments require a CONFIRMED work order")
    start = parse_dt(f.values.get("planned_start")) \
        if f.ok("planned_start") else None
    end = parse_dt(f.values.get("planned_end")) \
        if f.ok("planned_end") else None
    window_ok = start is not None and end is not None and end > start
    if start is not None and end is not None and end <= start:
        f.problems.append("planned_end")
    if wo is not None and die is not None and line is not None and \
            window_ok:
        # priority 17: half-open line schedule overlap
        for o in assignments.values():
            if o["line_id"] != line["id"] or \
                    o["status"] not in ("SCHEDULED", "ACTIVE"):
                continue
            if start < o["planned_end"] and end > o["planned_start"]:
                raise ApiError("ERR_LINE_SCHEDULE_CONFLICT", 409,
                               "Window overlaps another assignment on the "
                               "line")
        # priority 18: die buffer gap
        buffer_h = D(die["buffer_hours"])
        for o in assignments.values():
            if o["die_id"] != die["id"] or \
                    o["status"] not in ("SCHEDULED", "ACTIVE"):
                continue
            gap_secs = max(
                0.0,
                (start - o["planned_end"]).total_seconds(),
                (o["planned_start"] - end).total_seconds())
            if D(gap_secs) / D(3600) < buffer_h:
                raise ApiError("ERR_DIE_BUFFER_CONFLICT", 409,
                               "Gap to another die window below "
                               "buffer_hours")
    f.fail_if_problems()
    if wo is None or die is None or line is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource not found")
    asg = stamp_new({
        "work_order_id": wo["id"],
        "die_id": die["id"],
        "line_id": line["id"],
        "planned_start": start,
        "planned_end": end,
        "status": "SCHEDULED",
    })
    assignments[asg["id"]] = asg
    # system edge: first assignment moves the order CONFIRMED -> SCHEDULED
    if wo["status"] == "CONFIRMED":
        wo["status"] = "SCHEDULED"
        mark(wo)
    return ser_assignment(asg), 201


@endpoint("/line-assignments/<assignment_id>", ["GET"], ALL_ROLES)
def get_assignment(user_id, assignment_id):
    return ser_assignment(
        require_exists(assignments, assignment_id, "LineAssignment")), 200


@endpoint("/line-assignments", ["GET"], ALL_ROLES)
def list_assignments(user_id):
    limit, offset = pagination()
    items = sort_created(list(assignments.values()))
    for key in ("work_order_id", "die_id", "line_id"):
        v = request.args.get(key)
        if v:
            items = [a for a in items if a.get(key) == v]
    page, total = paginate(items, limit, offset)
    return list_result([ser_assignment(a) for a in page], limit, offset,
                       total)


@endpoint("/line-assignments/<assignment_id>/activate", ["POST"],
          ["ProcessEngineer"])
def activate_assignment(user_id, assignment_id):
    asg = require_exists(assignments, assignment_id, "LineAssignment")
    get_body()
    if asg["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Activate requires a SCHEDULED assignment")
    line = lines[asg["line_id"]]
    die = dies[asg["die_id"]]
    wo = work_orders[asg["work_order_id"]]
    # priority 8: line must be IDLE
    if line["status"] != "IDLE":
        raise ApiError("ERR_LINE_NOT_IDLE", 409,
                       "Line is %s" % line["status"])
    # priority 9: die must be QUALIFIED or IN_SERVICE
    if die["status"] not in ("QUALIFIED", "IN_SERVICE"):
        raise ApiError("ERR_DIE_NOT_RUNNABLE", 409,
                       "Die is %s" % die["status"])
    # priority 19: screw compatibility
    screw = D(line["screw_diameter_mm"])
    if not (D(die["min_screw_mm"]) <= screw <= D(die["max_screw_mm"])):
        raise ApiError("ERR_LINE_INCOMPATIBLE_DIE", 409,
                       "Line screw diameter outside die window")
    # priority 20: purge gate
    this_form = formulations[wo["formulation_id"]]
    ref = None
    for o in assignments.values():
        if o["line_id"] != line["id"] or o["status"] != "CLOSED":
            continue
        if o["planned_end"] > asg["planned_start"]:
            continue
        if ref is None:
            ref = o
            continue
        key_o = (o["planned_end"], o["created_at"], o.get("_seq", 0))
        key_r = (ref["planned_end"], ref["created_at"], ref.get("_seq", 0))
        if key_o > key_r:
            ref = o
    if ref is not None:
        prior_wo = work_orders[ref["work_order_id"]]
        prior_form = formulations[prior_wo["formulation_id"]]
        differs = prior_form["base_resin_type"] != \
            this_form["base_resin_type"] or \
            prior_form["color_family"] != this_form["color_family"]
        if differs:
            matched = any(
                p["line_id"] == line["id"] and
                p["from_resin_type"] == prior_form["base_resin_type"] and
                p["from_color_family"] == prior_form["color_family"] and
                p["to_resin_type"] == this_form["base_resin_type"] and
                p["to_color_family"] == this_form["color_family"] and
                p["created_at"] >= ref["updated_at"]
                for p in purge_events.values())
            if not matched:
                raise ApiError("ERR_PURGE_REQUIRED", 409,
                               "A matching purge event is required before "
                               "activation")
    asg["status"] = "ACTIVE"
    mark(asg)
    line["status"] = "SETUP"
    mark(line)
    if die["status"] == "QUALIFIED":
        die["status"] = "IN_SERVICE"
        mark(die)
    return ser_assignment(asg), 200


@endpoint("/line-assignments/<assignment_id>/close", ["POST"],
          ["ProcessEngineer"])
def close_assignment(user_id, assignment_id):
    asg = require_exists(assignments, assignment_id, "LineAssignment")
    get_body()
    if asg["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Close requires an ACTIVE assignment")
    if any(r["assignment_id"] == asg["id"] and
           r["status"] in ("RUNNING", "HOLD") for r in runs.values()):
        raise ApiError("ERR_RUN_IN_PROGRESS", 409,
                       "A run under this assignment is RUNNING or HOLD")
    asg["status"] = "CLOSED"
    mark(asg)
    line = lines[asg["line_id"]]
    if line["status"] == "RUNNING":
        line["status"] = "IDLE"
        mark(line)
    wo_close_check(work_orders[asg["work_order_id"]])
    return ser_assignment(asg), 200


@endpoint("/line-assignments/<assignment_id>/cancel", ["POST"],
          ["ProcessEngineer"])
def cancel_assignment(user_id, assignment_id):
    asg = require_exists(assignments, assignment_id, "LineAssignment")
    get_body()
    if asg["status"] not in ("SCHEDULED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cancel requires a SCHEDULED or ACTIVE assignment")
    if any(r["assignment_id"] == asg["id"] and
           r["status"] in ("RUNNING", "HOLD") for r in runs.values()):
        raise ApiError("ERR_RUN_IN_PROGRESS", 409,
                       "A run under this assignment is RUNNING or HOLD")
    was_active = asg["status"] == "ACTIVE"
    asg["status"] = "CANCELLED"
    mark(asg)
    if was_active:
        line = lines[asg["line_id"]]
        if line["status"] == "SETUP":
            line["status"] = "IDLE"
            mark(line)
    wo_revert_check(asg["work_order_id"])
    return ser_assignment(asg), 200


# ============================ Production runs ==============================
@endpoint("/runs", ["POST"], ["LineOperator"])
def create_run(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("assignment_id")
    f.str_("batch_id")
    f.num("line_speed_mpm", positive=True)
    asg = batch = None
    v = f.values.get("assignment_id")
    if isinstance(v, str):
        asg = require_exists(assignments, v, "LineAssignment")
    v = f.values.get("batch_id")
    if isinstance(v, str):
        batch = require_exists(batches, v, "BlendBatch")
    if asg is not None and asg["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Runs require an ACTIVE assignment")
    if batch is not None and batch["status"] != "QC_RELEASED":
        raise ApiError("ERR_MATERIAL_NOT_RELEASED", 409,
                       "Batch is not QC_RELEASED")
    if asg is not None and f.ok("line_speed_mpm"):
        prof = profiles[work_orders[asg["work_order_id"]]["profile_id"]]
        spd = f.values["line_speed_mpm"]
        if not (D(prof["min_line_speed_mpm"]) <= spd <=
                D(prof["max_line_speed_mpm"])):
            raise ApiError("ERR_LINE_SPEED_OUT_OF_RANGE", 400,
                           "line_speed_mpm outside the profile window")
    if asg is not None and batch is not None:
        wo = work_orders[asg["work_order_id"]]
        if batch["formulation_id"] != wo["formulation_id"]:
            raise ApiError("ERR_LOT_INCOMPATIBLE", 422,
                           "Batch formulation differs from the work "
                           "order's")
    f.fail_if_problems()
    if asg is None or batch is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource not found")
    run = stamp_new({
        "assignment_id": asg["id"],
        "batch_id": batch["id"],
        "line_speed_mpm": f.values["line_speed_mpm"],
        "status": "RUNNING",
        "hold_origin": None,
        "held_by_user_id": None,
        "samples_posted": 0,
        "good_length_mm": None,
        "good_weight_kg": None,
        "trim_scrap_kg": None,
        "regrind_lot_id": None,
        "remnant_mm": None,
    })
    runs[run["id"]] = run
    batch["status"] = "CONSUMED"
    mark(batch)
    line = lines[asg["line_id"]]
    if line["status"] == "SETUP":
        line["status"] = "RUNNING"
        mark(line)
    wo = work_orders[asg["work_order_id"]]
    if wo["status"] == "SCHEDULED":
        wo["status"] = "IN_PRODUCTION"
        mark(wo)
    return ser_run(run), 201


@endpoint("/runs/<run_id>", ["GET"], ALL_ROLES)
def get_run(user_id, run_id):
    return ser_run(require_exists(runs, run_id, "ProductionRun")), 200


@endpoint("/runs", ["GET"], ALL_ROLES)
def list_runs(user_id):
    limit, offset = pagination()
    items = sort_created(list(runs.values()))
    for key in ("assignment_id", "batch_id", "regrind_lot_id"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if r.get(key) == v]
    page, total = paginate(items, limit, offset)
    return list_result([ser_run(r) for r in page], limit, offset, total)


@endpoint("/runs/<run_id>/hold-status", ["POST"], ["QualityInspector"])
def run_hold_status(user_id, run_id):
    run = require_exists(runs, run_id, "ProductionRun")
    body = get_body()
    action = body.get("action")
    if not isinstance(action, str) or action not in ("HOLD", "RELEASE"):
        raise err_bad("action must be HOLD or RELEASE")
    # priority 5: SoD on releasing a MANUAL hold
    if action == "RELEASE" and run.get("hold_origin") == "MANUAL" and \
            user_id == run.get("held_by_user_id"):
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Releasing inspector must differ from the holder")
    if action == "HOLD":
        if run["status"] != "RUNNING":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "HOLD requires a RUNNING run")
        run["status"] = "HOLD"
        run["hold_origin"] = "MANUAL"
        run["held_by_user_id"] = user_id
        mark(run)
        asg = assignments[run["assignment_id"]]
        line = lines[asg["line_id"]]
        if line["status"] == "RUNNING":
            line["status"] = "DOWN"
            mark(line)
        from services import cancel_line_scheduled_assignments
        cancel_line_scheduled_assignments(line["id"])
        return ser_run(run), 200
    # RELEASE
    if run["status"] != "HOLD":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "RELEASE requires a HOLD run")
    run["status"] = "RUNNING"
    run["hold_origin"] = None
    run["held_by_user_id"] = None
    mark(run)
    asg = assignments[run["assignment_id"]]
    line = lines[asg["line_id"]]
    if line["status"] == "DOWN":
        line["status"] = "RUNNING"
        mark(line)
    return ser_run(run), 200


@endpoint("/runs/<run_id>/complete", ["POST"], ["LineOperator"])
def complete_run(user_id, run_id):
    run = require_exists(runs, run_id, "ProductionRun")
    body = get_body()
    f = Fields(body)
    f.int_("good_length_mm", min_v=0)
    f.num("good_weight_kg", nonnegative=True)
    f.num("trim_scrap_kg", nonnegative=True)
    if run["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Complete requires a RUNNING run")
    asg = assignments[run["assignment_id"]]
    wo = work_orders[asg["work_order_id"]]
    prof = profiles[wo["profile_id"]]
    if f.ok("good_length_mm"):
        good_m = D(f.values["good_length_mm"]) / 1000
        need = int((good_m / D(prof["sample_every_m"])).to_integral_value(
            rounding=ROUND_FLOOR))
        if run["samples_posted"] < need:
            raise ApiError("ERR_SPC_SAMPLE_QUOTA", 422,
                           "SPC sample quota not met")
    f.fail_if_problems()
    # record outputs
    run["good_length_mm"] = f.values["good_length_mm"]
    run["good_weight_kg"] = f.values["good_weight_kg"]
    run["trim_scrap_kg"] = f.values["trim_scrap_kg"]
    # cut plan
    plan, remnant = build_cut_plan(run, wo)
    run["remnant_mm"] = remnant
    for row in plan:
        b = stamp_new_lean(row)
        bundles[b["id"]] = b
    # material recovery: spawn in-house regrind lot from trim scrap
    if D(f.values["trim_scrap_kg"]) > 0:
        form = formulations[wo["formulation_id"]]
        lot = stamp_new({
            "lot_kind": "REGRIND",
            "resin_type": form["base_resin_type"],
            "color_family": form["color_family"],
            "received_kg": f.values["trim_scrap_kg"],
            "supplier_lot_ref": "INHOUSE-" + run["id"],
            "consumed_kg": D(0),
            "available_kg": f.values["trim_scrap_kg"],
            "status": "QC_PASSED",
        })
        lots[lot["id"]] = lot
        run["regrind_lot_id"] = lot["id"]
    # tooling amortization credit
    credit_die_for_run(dies[asg["die_id"]], run)
    # bubble-up: produced length and close check
    wo["produced_good_length_m"] = D(wo["produced_good_length_m"]) + \
        D(run["good_length_mm"]) / 1000
    mark(wo)
    wo_close_check(wo)
    run["status"] = "COMPLETED"
    mark(run)
    return ser_run(run), 200


# ============================ SPC samples ==================================
@endpoint("/spc-samples", ["POST"], ["LineOperator"])
def create_sample(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("run_id")
    f.str_("dimension_name")
    f.num_array("measurements")
    run = None
    v = f.values.get("run_id")
    if isinstance(v, str):
        run = require_exists(runs, v, "ProductionRun")
    if run is not None and run["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Samples require a RUNNING run")
    if run is not None:
        asg = assignments[run["assignment_id"]]
        wo = work_orders[asg["work_order_id"]]
        prof = profiles[wo["profile_id"]]
        if f.ok("dimension_name"):
            dim = next((d for d in prof["critical_dimensions"]
                        if isinstance(d, dict) and
                        d.get("name") == f.values["dimension_name"]), None)
            if dim is None:
                raise ApiError("ERR_UNKNOWN_DIMENSION", 400,
                               "dimension_name not in the profile's "
                               "critical_dimensions")
        if f.ok("measurements"):
            if len(f.values["measurements"]) != prof["spc_subgroup_size"]:
                raise ApiError("ERR_SPC_SUBGROUP_SIZE", 400,
                               "measurements length must equal "
                               "spc_subgroup_size")
    f.fail_if_problems()
    if run is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ProductionRun not found")
    xbar, rng, ooc, violations = evaluate_spc(dim, f.values["measurements"])
    sample = stamp_new_lean({
        "run_id": run["id"],
        "dimension_name": f.values["dimension_name"],
        "measurements": body["measurements"],
        "xbar_mm": xbar,
        "range_mm": rng,
        "ooc": ooc,
        "spec_violations": violations,
    })
    samples[sample["id"]] = sample
    run["samples_posted"] += 1
    mark(run)
    if ooc:
        hold_run_system(run)
    return ser_sample(sample), 201


@endpoint("/runs/<run_id>/spc-samples", ["GET"], ALL_ROLES)
def list_run_samples(user_id, run_id):
    require_exists(runs, run_id, "ProductionRun")
    limit, offset = pagination()
    items = sort_created([s for s in samples.values()
                          if s["run_id"] == run_id])
    page, total = paginate(items, limit, offset)
    return list_result([ser_sample(s) for s in page], limit, offset, total)


# ============================ Cut bundles ==================================
@endpoint("/runs/<run_id>/bundles", ["GET"], ALL_ROLES)
def list_run_bundles(user_id, run_id):
    require_exists(runs, run_id, "ProductionRun")
    limit, offset = pagination()
    items = sorted([b for b in bundles.values() if b["run_id"] == run_id],
                   key=lambda b: b["bundle_seq"])
    page, total = paginate(items, limit, offset)
    return list_result([ser_bundle(b) for b in page], limit, offset, total)


# ============================ Purge events =================================
@endpoint("/purge-events", ["POST"], ["LineOperator"])
def create_purge(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("line_id")
    f.str_("from_resin_type")
    f.str_("to_resin_type")
    f.enum("from_color_family", sorted(COLOR_FAMILIES))
    f.enum("to_color_family", sorted(COLOR_FAMILIES))
    f.enum("purge_grade", ["STANDARD", "HIGH_EFFICIENCY"])
    line = None
    v = f.values.get("line_id")
    if isinstance(v, str):
        line = require_exists(lines, v, "ExtrusionLine")
    f.fail_if_problems()
    if line is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ExtrusionLine not found")
    tclass, scrap = purge_estimate(
        line, f.values["from_resin_type"], f.values["to_resin_type"],
        f.values["from_color_family"], f.values["to_color_family"],
        f.values["purge_grade"])
    ev = stamp_new_lean({
        "line_id": line["id"],
        "from_resin_type": f.values["from_resin_type"],
        "to_resin_type": f.values["to_resin_type"],
        "from_color_family": f.values["from_color_family"],
        "to_color_family": f.values["to_color_family"],
        "purge_grade": f.values["purge_grade"],
        "transition_class": tclass,
        "scrap_kg": scrap,
    })
    purge_events[ev["id"]] = ev
    return ser_purge(ev), 201


@endpoint("/lines/<line_id>/purge-events", ["GET"], ALL_ROLES)
def list_line_purges(user_id, line_id):
    require_exists(lines, line_id, "ExtrusionLine")
    limit, offset = pagination()
    items = sort_created([p for p in purge_events.values()
                          if p["line_id"] == line_id])
    page, total = paginate(items, limit, offset)
    return list_result([ser_purge(p) for p in page], limit, offset, total)


# ============================ Resin index points ===========================
@endpoint("/resin-index-points", ["POST"], ["PlantManager"])
def create_index_point(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("month")
    f.num("index_cents_per_kg", nonnegative=True)
    month = f.values.get("month")
    if isinstance(month, str) and not MONTH_RE.match(month):
        f.problems.append("month")
        month = None
    # priority 24: one point per month
    if month is not None and month in index_by_month:
        raise ApiError("ERR_INDEX_MONTH_EXISTS", 409,
                       "Month %s already has an index point" % month)
    f.fail_if_problems()
    pt = stamp_new({
        "month": month,
        "index_cents_per_kg": f.values["index_cents_per_kg"],
    })
    index_points[pt["id"]] = pt
    index_by_month[month] = pt["id"]
    return ser_index_point(pt), 201


@endpoint("/resin-index-points/<month>", ["GET"], ALL_ROLES)
def get_index_point(user_id, month):
    pid = index_by_month.get(month)
    if pid is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ResinIndexPoint not found")
    return ser_index_point(index_points[pid]), 200


@endpoint("/resin-index-points/<month>/restate", ["POST"], ["PlantManager"])
def restate_index_point(user_id, month):
    pid = index_by_month.get(month)
    if pid is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ResinIndexPoint not found")
    pt = index_points[pid]
    body = get_body()
    f = Fields(body)
    f.num("index_cents_per_kg", nonnegative=True)
    occ_missing = False
    ev = body.get("expected_index_point_version")
    if ev is None or not (isinstance(ev, int) and not isinstance(ev, bool)):
        occ_missing = True
    elif ev != pt["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_index_point_version does not match current "
                       "version")
    f.fail_if_problems()
    if occ_missing:
        raise err_bad("expected_index_point_version is required")
    pt["index_cents_per_kg"] = f.values["index_cents_per_kg"]
    mark(pt)
    restate_cascade(month)
    return ser_index_point(pt), 200


# ============================ Logical clock ================================
@endpoint("/_clock/set_current_utc", ["POST"], ["PlantManager"])
def set_clock(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("to_iso8601")
    dt = parse_dt(f.values.get("to_iso8601")) \
        if f.ok("to_iso8601") else None
    if f.ok("to_iso8601") and dt is None:
        f.problems.append("to_iso8601")
    f.fail_if_problems()
    CLOCK["now"] = dt
    return {"current_utc": ts_iso(dt)}, 200
