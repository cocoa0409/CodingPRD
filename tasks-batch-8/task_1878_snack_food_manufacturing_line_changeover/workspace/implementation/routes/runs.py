from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import require, ALL_ROLES
from domain import (changeover_requirement, cases_unrouted, dump_run, get_line,
                    get_product, get_run, giveaway_figures, line_current_profile,
                    margin_actual, margin_standard, margin_per_case, oil_for_line,
                    last_oil_price, run_checks, frying_accrual, MAX_REJECT_RATIO)
from errors import ApiError
from store import STORE, new_entity, touch, sort_key
from util import (body, ok, paginate, req_str, req_num, req_int, req_enum,
                  parse_dt, iso, D)

bp = Blueprint("runs", __name__)


def _find_product_for(run):
    return STORE.products.get(run["product_id"])


@bp.post("/snack-mfg/production-runs")
def create_run():
    require(["PlantManager"])
    data = body()
    # tier 3: body FK existence (canonical order line_id then product_id)
    line_id = data.get("line_id")
    product_id = data.get("product_id")
    line = get_line(STORE, line_id) if isinstance(line_id, str) else None
    product = get_product(STORE, product_id) if isinstance(product_id, str) else None
    # tier 5: shape
    if line is None:
        req_str(data, "line_id")  # raises when absent/blank
        raise ApiError("ERR_LINE_NOT_FOUND", 404, "line not found")
    if product is None:
        req_str(data, "product_id")
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
    try:
        sched_start = parse_dt(data.get("scheduled_start"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "scheduled_start must be ISO 8601")
    try:
        sched_end = parse_dt(data.get("scheduled_end"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "scheduled_end must be ISO 8601")
    if not (sched_end > sched_start):
        raise ApiError("ERR_VALIDATION", 400, "scheduled_end must be strictly after scheduled_start")
    lbs_planned = req_num(data, "lbs_planned", gt=0)
    cases_planned = req_int(data, "cases_planned", ge=1)
    expected_line_version = req_int(data, "expected_line_version")
    # tier 6: OCC on the line version
    if expected_line_version != line["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "line version has advanced since observation")
    # tier 8: half-open overlap + cleaning buffer against sibling runs
    siblings = [r for r in STORE.runs.values()
                if r["line_id"] == line["id"] and r["execution_status"] != "CANCELLED"]
    for s in siblings:
        s_start, s_end = s["_sched_start_dt"], s["_sched_end_dt"]
        if sched_start < s_end and s_start < sched_end:
            raise ApiError("ERR_SCHEDULE_OVERLAP", 409, "run interval overlaps a sibling run")
    preceding = [s for s in siblings if s["_sched_end_dt"] <= sched_start]
    if preceding:
        pred = max(preceding, key=lambda s: (s["_sched_end_dt"], s["_seq"]))
        pred_product = STORE.products.get(pred["product_id"])
        if pred_product is not None:
            level = changeover_requirement(pred_product["allergen_profile"],
                                           pred_product["flavor_group"],
                                           product["allergen_profile"], product["flavor_group"])
            if level != "NONE":
                minutes = (line["cleaning_minutes_full_wash"] if level == "FULL_WASH"
                           else line["cleaning_minutes_dry"])
                if sched_start < pred["_sched_end_dt"] + timedelta(minutes=minutes):
                    raise ApiError("ERR_SCHEDULE_OVERLAP", 409,
                                   "allergen cleaning buffer violated against preceding run")
    following = [s for s in siblings if s["_sched_start_dt"] >= sched_end]
    if following:
        succ = min(following, key=lambda s: (s["_sched_start_dt"], s["_seq"]))
        succ_product = STORE.products.get(succ["product_id"])
        if succ_product is not None:
            level = changeover_requirement(product["allergen_profile"], product["flavor_group"],
                                           succ_product["allergen_profile"],
                                           succ_product["flavor_group"])
            if level != "NONE":
                minutes = (line["cleaning_minutes_full_wash"] if level == "FULL_WASH"
                           else line["cleaning_minutes_dry"])
                if succ["_sched_start_dt"] < sched_end + timedelta(minutes=minutes):
                    raise ApiError("ERR_SCHEDULE_OVERLAP", 409,
                                   "allergen cleaning buffer violated against following run")
    # tier 9: process compatibility
    ptype = product["process_type"]
    if (ptype == "FRYER" and line["line_type"] not in ("FRYER", "BOTH")) or \
       (ptype == "OVEN" and line["line_type"] not in ("OVEN", "BOTH")):
        raise ApiError("ERR_PROCESS_LINE_MISMATCH", 422,
                       "product process_type not servable by this line")
    # create the run
    run = new_entity(STORE)
    run.update({
        "line_id": line["id"], "product_id": product["id"],
        "scheduled_start": iso(sched_start), "scheduled_end": iso(sched_end),
        "_sched_start_dt": sched_start, "_sched_end_dt": sched_end,
        "lbs_planned": lbs_planned, "cases_planned": cases_planned,
        "execution_status": "SCHEDULED", "quality_status": "PENDING",
        "started_at": None, "completed_at": None, "_started_dt": None, "_completed_dt": None,
        "lbs_produced": None, "cases_produced": None, "rejected_cases": None,
        "seasoning_actual_pct": None, "accepted_cases": 0,
        "hold_placed_by_user_id": None, "locked_oil_price_cents_per_gal": None,
        "margin_standard_cents": None, "margin_actual_cents": None,
    })
    STORE.runs[run["id"]] = run
    # auto-create a REQUIRED changeover when the matrix demands one
    from_allergens, from_flavor = line_current_profile(STORE, line)
    level = changeover_requirement(from_allergens, from_flavor,
                                   product["allergen_profile"], product["flavor_group"])
    if level != "NONE":
        open_existing = [c for c in STORE.changeovers.values()
                         if c["line_id"] == line["id"] and c["to_product_id"] == product["id"]
                         and (c["status"] in ("REQUIRED", "CLEANING", "SWAB_PENDING")
                              or (c["status"] == "VALIDATED" and c["consumed_by_run_id"] is None))]
        if not open_existing:
            _create_changeover(STORE, line, product)
    touch(STORE, line)
    return ok(STORE, dump_run(STORE, run), status=201)


def _create_changeover(store, line, product):
    """Create a REQUIRED changeover; supersedes still-REQUIRED changeovers on the line."""
    from_allergens, from_flavor = line_current_profile(store, line)
    level = changeover_requirement(from_allergens, from_flavor,
                                   product["allergen_profile"], product["flavor_group"])
    for c in list(store.changeovers.values()):
        if c["line_id"] == line["id"] and c["status"] == "REQUIRED":
            c["status"] = "CANCELLED"
            touch(store, c)
    ch = new_entity(store)
    ch.update({
        "line_id": line["id"], "to_product_id": product["id"],
        "from_allergen_profile": list(from_allergens),
        "to_allergen_profile": list(product["allergen_profile"]),
        "from_flavor_group": from_flavor, "to_flavor_group": product["flavor_group"],
        "required_level": level, "status": "REQUIRED",
        "cleaned_by_user_id": None, "swab_result": None, "swab_attempts": 0,
        "validated_by_user_id": None, "validated_at": None, "_validated_dt": None,
        "consumed_by_run_id": None,
    })
    store.changeovers[ch["id"]] = ch
    return ch


@bp.get("/snack-mfg/production-runs/<rid>")
def get_run_ep(rid):
    require(ALL_ROLES)
    run = get_run(STORE, rid)
    return ok(STORE, dump_run(STORE, run))


@bp.get("/snack-mfg/production-runs")
def list_runs():
    require(ALL_ROLES)
    items = list(STORE.runs.values())
    line_id = request.args.get("line_id")
    product_id = request.args.get("product_id")
    execution_status = request.args.get("execution_status")
    if line_id is not None:
        items = [r for r in items if r["line_id"] == line_id]
    if product_id is not None:
        items = [r for r in items if r["product_id"] == product_id]
    if execution_status is not None:
        items = [r for r in items if r["execution_status"] == execution_status]
    items.sort(key=sort_key)
    page, meta = paginate([dump_run(STORE, r) for r in items])
    return ok(STORE, page, response_type="array", pagination=meta)


def _get_run_for_action(rid):
    return get_run(STORE, rid)


def _run_terminal_guard(run):
    if run["execution_status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "run is in a terminal state")


@bp.post("/snack-mfg/production-runs/<rid>/start")
def start_run(rid):
    uid, _ = require(["LineOperator"])
    run = _get_run_for_action(rid)
    # tier 6: state
    _run_terminal_guard(run)
    if run["execution_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "run is not SCHEDULED")
    for s in STORE.runs.values():
        if (s["line_id"] == run["line_id"] and s["id"] != run["id"]
                and s["execution_status"] == "RUNNING"):
            raise ApiError("ERR_INVALID_STATE", 409, "another run is RUNNING on this line")
    line = get_line(STORE, run["line_id"])
    product = _find_product_for(run)
    # tier 7: allergen safety gate (recomputed against the CURRENT line profile)
    from_allergens, from_flavor = line_current_profile(STORE, line)
    level = changeover_requirement(from_allergens, from_flavor,
                                   product["allergen_profile"], product["flavor_group"])
    now = STORE.clock
    if level == "NONE":
        # a NONE-level REQUIRED changeover is consumed implicitly when referenced
        cands = [c for c in STORE.changeovers.values()
                 if c["line_id"] == run["line_id"] and c["to_product_id"] == run["product_id"]
                 and c["status"] == "REQUIRED" and c["required_level"] == "NONE"]
        if cands:
            ch = min(cands, key=lambda c: c["_seq"])
            ch["status"] = "APPLIED"
            ch["consumed_by_run_id"] = run["id"]
            touch(STORE, ch)
    else:
        matching = [c for c in STORE.changeovers.values()
                    if c["line_id"] == run["line_id"] and c["to_product_id"] == run["product_id"]
                    and c["status"] == "VALIDATED" and c["consumed_by_run_id"] is None]
        fresh = [c for c in matching
                 if now - c["_validated_dt"] <= timedelta(hours=48)]
        if fresh:
            ch = min(fresh, key=lambda c: c["_seq"])
            ch["status"] = "APPLIED"
            ch["consumed_by_run_id"] = run["id"]
            touch(STORE, ch)
        elif matching:
            raise ApiError("ERR_CLEANING_VALIDATION_STALE", 422,
                           "matching validated changeover is more than 48h old")
        else:
            raise ApiError("ERR_ALLERGEN_CHANGEOVER_REQUIRED", 422,
                           "no fresh validated changeover for this line/product")
    # tier 7: oil safety gate
    oil = oil_for_line(STORE, run["line_id"])
    if oil is None or oil["state"] != "ACTIVE":
        raise ApiError("ERR_OIL_QUALITY_HOLD", 422, "fryer oil is not ACTIVE")
    # tier 8: start window
    if now < run["_sched_start_dt"]:
        raise ApiError("ERR_START_BEFORE_WINDOW", 422, "logical clock is before scheduled_start")
    # side effects
    run["execution_status"] = "RUNNING"
    run["started_at"] = iso(now)
    run["_started_dt"] = now
    locked = last_oil_price(STORE, oil)
    if locked is None:
        locked = product["standard_oil_price_cents_per_gal"]
    run["locked_oil_price_cents_per_gal"] = locked
    run["margin_standard_cents"] = margin_standard(run, product, locked)
    touch(STORE, run)
    return ok(STORE, dump_run(STORE, run))


@bp.post("/snack-mfg/production-runs/<rid>/place-hold")
def place_hold(rid):
    uid, _ = require(["LineOperator"])
    run = _get_run_for_action(rid)
    _run_terminal_guard(run)
    if run["execution_status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "run is not RUNNING")
    run["execution_status"] = "HELD"
    run["hold_placed_by_user_id"] = uid
    touch(STORE, run)
    return ok(STORE, dump_run(STORE, run))


@bp.post("/snack-mfg/production-runs/<rid>/release-hold")
def release_hold(rid):
    uid, _ = require(["QualityTechnician"])
    run = _get_run_for_action(rid)
    _run_terminal_guard(run)
    if run["execution_status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "run is not HELD")
    oil = oil_for_line(STORE, run["line_id"])
    if oil is None or oil["state"] != "ACTIVE":
        raise ApiError("ERR_OIL_QUALITY_HOLD", 422, "fryer oil is not ACTIVE")
    if run["hold_placed_by_user_id"] is not None and uid == run["hold_placed_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403, "hold releaser must differ from holder")
    run["execution_status"] = "RUNNING"
    run["hold_placed_by_user_id"] = None
    touch(STORE, run)
    return ok(STORE, dump_run(STORE, run))


@bp.post("/snack-mfg/production-runs/<rid>/complete")
def complete_run(rid):
    uid, _ = require(["LineOperator"])
    run = _get_run_for_action(rid)
    data = body()
    # tier 5: shape (before state per validation priority)
    lbs_produced = req_num(data, "lbs_produced")
    cases_produced = req_int(data, "cases_produced")
    rejected_cases = req_int(data, "rejected_cases")
    seasoning_actual = req_num(data, "seasoning_actual_pct")
    # tier 6: state
    _run_terminal_guard(run)
    if run["execution_status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "run is not RUNNING")
    # tier 9: at least one weight check
    checks = run_checks(STORE, run)
    if not checks:
        raise ApiError("ERR_NO_WEIGHT_CHECKS", 422, "run has no recorded weight checks")
    product = _find_product_for(run)
    line = get_line(STORE, run["line_id"])
    now = STORE.clock
    # transition + accepted cases
    run["execution_status"] = "COMPLETED"
    run["completed_at"] = iso(now)
    run["_completed_dt"] = now
    run["lbs_produced"] = lbs_produced
    run["cases_produced"] = cases_produced
    run["rejected_cases"] = rejected_cases
    run["seasoning_actual_pct"] = seasoning_actual
    run["accepted_cases"] = cases_produced - rejected_cases
    # residual frying accrual at temp factor 1.0
    oil = oil_for_line(STORE, run["line_id"])
    residual = lbs_produced - sum(D(c["lbs_fried_since_last_check"]) for c in checks)
    if oil is not None and residual != 0:
        frying_accrual(STORE, oil, residual, Decimal("1.0"))
    # compliance evaluation
    provisional, final, ratio, ratio_raw, mean_all = giveaway_figures(STORE, run, product)
    declared = D(product["declared_net_weight_g"])
    qhold = False
    if ratio_raw is not None and ratio_raw > MAX_REJECT_RATIO:
        qhold = True
    if mean_all is not None and mean_all < declared:
        qhold = True
    if final is not None and final > D(product["giveaway_max_pct"]):
        qhold = True
    if abs(D(seasoning_actual) - D(product["seasoning_target_pct"])) > Decimal("0.5"):
        qhold = True
    run["quality_status"] = "QHOLD" if qhold else "PENDING"
    # actual margin
    run["margin_actual_cents"] = margin_actual(STORE, run, product)
    # line profile rewrite (derived on read) + line version bump
    touch(STORE, line)
    # over-reservation cascade
    while cases_unrouted(STORE, run) < 0:
        planned = [dc for dc in STORE.cases.values()
                   if dc["run_id"] == run["id"] and dc["status"] == "PLANNED"]
        if not planned:
            break
        newest = max(planned, key=lambda d: (d["created_at"], d["_seq"]))
        newest["status"] = "CANCELLED"
        newest["cancelled_reason"] = "OVER_RESERVED"
        touch(STORE, newest)
    touch(STORE, run)
    return ok(STORE, dump_run(STORE, run))


@bp.post("/snack-mfg/production-runs/<rid>/cancel")
def cancel_run(rid):
    require(["PlantManager"])
    run = _get_run_for_action(rid)
    _run_terminal_guard(run)
    if run["execution_status"] not in ("SCHEDULED", "HELD"):
        raise ApiError("ERR_INVALID_STATE", 409, "only SCHEDULED or HELD runs can be cancelled")
    run["execution_status"] = "CANCELLED"
    for dc in STORE.cases.values():
        if dc["run_id"] == run["id"] and dc["status"] == "PLANNED":
            dc["status"] = "CANCELLED"
            dc["cancelled_reason"] = "RUN_CANCELLED"
            touch(STORE, dc)
    for c in STORE.changeovers.values():
        if (c["line_id"] == run["line_id"] and c["to_product_id"] == run["product_id"]
                and c["status"] == "REQUIRED"):
            c["status"] = "CANCELLED"
            touch(STORE, c)
    touch(STORE, run)
    return ok(STORE, dump_run(STORE, run))


@bp.post("/snack-mfg/production-runs/<rid>/quality-disposition")
def quality_disposition(rid):
    uid, _ = require(["QualityTechnician"])
    run = _get_run_for_action(rid)
    data = body()
    disposition = req_enum(data, "disposition", {"PASS", "REJECT"})
    if run["execution_status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "run is terminal")
    if run["execution_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "run is not COMPLETED")
    if run["quality_status"] in ("PASSED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "quality disposition is terminal")
    run["quality_status"] = "PASSED" if disposition == "PASS" else "REJECTED"
    if disposition == "REJECT":
        for sh in STORE.shipments.values():
            if (sh["run_id"] == run["id"]
                    and sh["status"] in ("DRAFT", "DSD_PLANNED", "WAREHOUSE_PLANNED")):
                sh["status"] = "CANCELLED"
                touch(STORE, sh)
        for dc in STORE.cases.values():
            if dc["run_id"] == run["id"] and dc["status"] == "PLANNED":
                dc["status"] = "CANCELLED"
                dc["cancelled_reason"] = "RUN_REJECTED"
                touch(STORE, dc)
    touch(STORE, run)
    return ok(STORE, dump_run(STORE, run))


@bp.get("/snack-mfg/production-runs/<rid>/cost-summary")
def cost_summary(rid):
    require(["PlantManager", "QualityTechnician"])
    run = _get_run_for_action(rid)
    product = _find_product_for(run)
    provisional, final, ratio, _, _ = giveaway_figures(STORE, run, product)
    data = {
        "margin_standard_cents": run["margin_standard_cents"],
        "margin_actual_cents": run["margin_actual_cents"],
        "margin_actual_per_case_cents": margin_per_case(run),
        "giveaway_provisional_pct": (float(provisional) if provisional is not None else None),
        "giveaway_final_pct": (float(final) if final is not None else None),
        "accepted_cases": run["accepted_cases"],
        "reject_ratio": (float(ratio) if ratio is not None else None),
    }
    return ok(STORE, data)
