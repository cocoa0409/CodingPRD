"""Extrusion lines, runs, gauge readings, regrind draws and film rolls."""

from flask import Blueprint, g

import config as C
from auth import ANY_ROLE, endpoint
from errors import ApiError
from num import D, ZERO, f, r
from response import object_response
from services import calc, cascade, refs
from store import serialize, store
from validation import (
    fetch,
    get_bool,
    get_datetime,
    get_enum,
    get_int,
    get_num,
    get_str,
    list_endpoint,
    parse_body,
    require_unique,
    resolve_fks,
)

bp = Blueprint("extrusion", __name__)


def ok(entity):
    return object_response(serialize(entity), 200)


def created(entity):
    return object_response(serialize(entity), 201)


# ========================================================= extrusion lines ==
@bp.post("/extrusion-lines")
@endpoint(["PlantAdmin"])
def create_line():
    body = parse_body(required=True)
    line_code = get_str(body, "line_code")
    process_type = get_enum(body, "process_type", C.PROCESS_TYPES)
    max_layers = get_int(body, "max_layers", ge=1)
    min_gauge = get_num(body, "min_gauge_micron")
    max_gauge = get_num(body, "max_gauge_micron")
    max_layflat = get_num(body, "max_layflat_mm")
    purge_buffer = get_int(body, "purge_buffer_minutes", required=False, default=45, ge=0)
    food_certified = get_bool(body, "food_contact_certified", default=False)

    require_unique(store.extrusion_lines, "line_code", line_code)

    line = store.new_common()
    line.update(
        {
            "line_code": line_code,
            "process_type": process_type,
            "max_layers": max_layers,
            "min_gauge_micron": min_gauge,
            "max_gauge_micron": max_gauge,
            "max_layflat_mm": max_layflat,
            "purge_buffer_minutes": purge_buffer,
            "food_contact_certified": food_certified,
            "posture": "OPEN",
            "incapable_run_count": 0,
            "active_hold_count": 0,
            "revoked_dossier_count": 0,
        }
    )
    store.extrusion_lines[line["id"]] = line
    return created(line)


@bp.get("/extrusion-lines/<line_id>")
@endpoint(ANY_ROLE)
def read_line(line_id):
    return ok(fetch("extrusion_line", line_id))


@bp.get("/extrusion-lines")
@endpoint(ANY_ROLE)
def list_lines():
    return list_endpoint(
        store.extrusion_lines, ("process_type", "posture", "food_contact_certified")
    )


@bp.post("/extrusion-lines/<line_id>/clear-capability-flags")
@endpoint(["QualityManager", "PlantAdmin"])
def clear_capability_flags(line_id):
    parse_body(required=False)
    line = fetch("extrusion_line", line_id)
    line["incapable_run_count"] = 0
    line["revoked_dossier_count"] = 0
    posture = calc.derive_posture(line)
    line["posture"] = posture
    store.touch(line)
    # Forward-only: already BLOCKED runs and QUARANTINED rolls are not restored.
    if posture == "FROZEN":
        cascade.freeze_cascade(line, "Line posture is FROZEN.")
    return ok(line)


# =========================================================== extrusion runs ==
def _check_window(line, recipe, start, end, exclude_run_id=None):
    if calc.has_window_conflict(line, recipe["id"], start, end, exclude_run_id):
        raise ApiError(
            "ERR_LINE_WINDOW_CONFLICT",
            "The requested window conflicts with another run occupying this line.",
        )
    if start < store.clock:
        raise ApiError(
            "ERR_WINDOW_IN_PAST", "scheduled_start is earlier than the current logical clock."
        )


@bp.post("/extrusion-runs")
@endpoint(["ExtrusionOperator", "PlantAdmin"])
def create_run():
    body = parse_body(required=True)
    run_code = get_str(body, "run_code")
    line_id = get_str(body, "line_id")
    blend_recipe_id = get_str(body, "blend_recipe_id")
    raw_start, start = get_datetime(body, "scheduled_start")
    raw_end, end = get_datetime(body, "scheduled_end")
    target_output_kg = get_num(body, "target_output_kg", gt=0)
    if not end > start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'scheduled_end' must be strictly after 'scheduled_start'."
        )

    resolved = resolve_fks({"blend_recipe_id": blend_recipe_id, "line_id": line_id})
    recipe = resolved["blend_recipe_id"]
    line = resolved["line_id"]
    require_unique(store.extrusion_runs, "run_code", run_code)

    product = refs.product_of_recipe(recipe)
    food = bool(product["food_contact_required"])

    if recipe["status"] != "APPROVED":
        raise ApiError(
            "ERR_RECIPE_NOT_APPROVED", "Only an APPROVED recipe may be pinned onto a line."
        )
    if line["posture"] == "FROZEN":
        raise ApiError("ERR_LINE_POSTURE_FROZEN", "The line's posture is FROZEN.")
    if food and line["posture"] == "RESTRICTED":
        raise ApiError(
            "ERR_LINE_POSTURE_RESTRICTED",
            "A RESTRICTED line does not accept food-contact work.",
        )
    if food and not line["food_contact_certified"]:
        raise ApiError(
            "ERR_LINE_NOT_FOOD_CERTIFIED",
            "A food-contact product requires a food_contact_certified line.",
        )

    if (
        recipe["layer_count"] > line["max_layers"]
        or recipe["process_type"] != line["process_type"]
        or D(product["target_gauge_micron"]) < D(line["min_gauge_micron"])
        or D(product["target_gauge_micron"]) > D(line["max_gauge_micron"])
        or D(product["layflat_width_mm"]) > D(line["max_layflat_mm"])
    ):
        raise ApiError(
            "ERR_LINE_CAPABILITY_MISMATCH",
            "The line cannot physically run this recipe and product.",
        )

    _check_window(line, recipe, start, end)

    run = store.new_common()
    run.update(
        {
            "run_code": run_code,
            "line_id": line_id,
            "blend_recipe_id": blend_recipe_id,
            "scheduled_start": raw_start,
            "scheduled_end": raw_end,
            "_scheduled_start": start,
            "_scheduled_end": end,
            "target_output_kg": target_output_kg,
            "status": "SCHEDULED",
            "hold_count": 0,
            "hold_reason": None,
            "gauge_readings": [],
            "gauge_sample_count": 0,
            "gauge_mean_micron": None,
            "gauge_sd_micron": None,
            "gauge_cv_pct": None,
            "gauge_capability_index": None,
            "gauge_capability_state": "INSUFFICIENT_DATA",
            "layflat_deviation_max_mm": None,
            "bubble_instability_events": 0,
            "gross_output_kg": None,
            "scrap_kg": None,
            "net_good_kg": None,
            "regrind_consumed_kg": 0.0,
            "regrind_actual_pct": None,
            "pcr_mass_kg": None,
            "actual_recycled_content_pct": None,
            "recipe_pin_released": False,
        }
    )
    store.extrusion_runs[run["id"]] = run
    cascade.repin_recipe(recipe)
    return created(run)


@bp.get("/extrusion-runs/<run_id>")
@endpoint(ANY_ROLE)
def read_run(run_id):
    return ok(fetch("extrusion_run", run_id))


@bp.get("/extrusion-runs")
@endpoint(ANY_ROLE)
def list_runs():
    return list_endpoint(
        store.extrusion_runs, ("line_id", "blend_recipe_id", "status", "gauge_capability_state")
    )


@bp.patch("/extrusion-runs/<run_id>/reschedule")
@endpoint(["ExtrusionOperator", "PlantAdmin"])
def reschedule_run(run_id):
    body = parse_body(required=True)
    raw_start, start = get_datetime(body, "scheduled_start")
    raw_end, end = get_datetime(body, "scheduled_end")
    if not end > start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'scheduled_end' must be strictly after 'scheduled_start'."
        )
    run = fetch("extrusion_run", run_id)
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_STATE_INVALID", "Only a SCHEDULED run may be rescheduled.")

    line = refs.line_of_run(run)
    recipe = refs.recipe_of_run(run)
    _check_window(line, recipe, start, end, exclude_run_id=run["id"])

    run["scheduled_start"] = raw_start
    run["scheduled_end"] = raw_end
    run["_scheduled_start"] = start
    run["_scheduled_end"] = end
    store.touch(run)
    return ok(run)


@bp.post("/extrusion-runs/<run_id>/start")
@endpoint(["ExtrusionOperator"])
def start_run(run_id):
    parse_body(required=False)
    run = fetch("extrusion_run", run_id)
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_STATE_INVALID", "Only a SCHEDULED run may be started.")

    line = refs.line_of_run(run)
    recipe = refs.recipe_of_run(run)
    product = refs.product_of_recipe(recipe)

    if line["posture"] == "FROZEN":
        raise ApiError("ERR_LINE_POSTURE_FROZEN", "The line's posture is FROZEN.")
    if recipe["status"] != "APPROVED":
        raise ApiError("ERR_RECIPE_NOT_APPROVED", "The pinned recipe is no longer APPROVED.")
    if product["food_contact_required"] and not line["food_contact_certified"]:
        raise ApiError(
            "ERR_LINE_NOT_FOOD_CERTIFIED",
            "A food-contact product requires a food_contact_certified line.",
        )
    if store.clock < run["_scheduled_start"]:
        raise ApiError(
            "ERR_RUN_NOT_YET_STARTABLE",
            "The logical clock has not yet reached this run's scheduled_start.",
        )

    run["status"] = "RUNNING"
    store.touch(run)
    cascade.rederive_line_posture(line)
    return ok(run)


@bp.post("/extrusion-runs/<run_id>/gauge-readings")
@endpoint(["ExtrusionOperator"])
def append_gauge_reading(run_id):
    body = parse_body(required=True)
    thickness = get_num(body, "thickness_micron", gt=0)
    layflat = get_num(body, "layflat_mm", required=False, default=None)
    bubble = get_num(body, "bubble_deviation_mm", required=False, default=0.0)

    run = fetch("extrusion_run", run_id)
    if run["status"] not in ("RUNNING", "HELD"):
        raise ApiError(
            "ERR_RUN_STATE_INVALID", "Gauge samples may only be logged on a RUNNING or HELD run."
        )

    product = refs.product_of_run(run)
    if layflat is None:
        layflat = product["layflat_width_mm"]

    run["gauge_readings"].append(
        {
            "seq": len(run["gauge_readings"]) + 1,
            "thickness_micron": thickness,
            "layflat_mm": layflat,
            "bubble_deviation_mm": bubble,
            "recorded_at": store.clock_iso(),
        }
    )
    calc.recompute_gauge(run)
    store.touch(run)
    return created(run)


@bp.post("/extrusion-runs/<run_id>/hold")
@endpoint(["ExtrusionOperator"])
def hold_run(run_id):
    body = parse_body(required=True)
    hold_reason = get_str(body, "hold_reason")
    run = fetch("extrusion_run", run_id)
    if run["status"] != "RUNNING":
        raise ApiError("ERR_RUN_STATE_INVALID", "Only a RUNNING run may be held.")
    run["status"] = "HELD"
    run["hold_count"] = int(run["hold_count"]) + 1
    run["hold_reason"] = hold_reason
    store.touch(run)
    cascade.rederive_line_posture(refs.line_of_run(run))
    return ok(run)


@bp.post("/extrusion-runs/<run_id>/resume")
@endpoint(["ExtrusionOperator"])
def resume_run(run_id):
    parse_body(required=False)
    run = fetch("extrusion_run", run_id)
    if run["status"] != "HELD":
        raise ApiError("ERR_RUN_STATE_INVALID", "Only a HELD run may be resumed.")
    line = refs.line_of_run(run)
    if line["posture"] == "FROZEN":
        raise ApiError("ERR_LINE_POSTURE_FROZEN", "The line's posture is FROZEN.")
    if int(run["hold_count"]) > C.MAX_RUN_HOLDS:
        raise ApiError(
            "ERR_RUN_HOLD_LIMIT_EXCEEDED",
            "This run has been held more than %d times and may no longer be resumed."
            % C.MAX_RUN_HOLDS,
        )
    run["status"] = "RUNNING"
    run["hold_reason"] = None
    store.touch(run)
    cascade.rederive_line_posture(line)
    return ok(run)


@bp.post("/extrusion-runs/<run_id>/regrind-reincorporations")
@endpoint(["ExtrusionOperator"])
def draw_regrind(run_id):
    body = parse_body(required=True)
    pool_id = get_str(body, "pool_id")
    kg = get_num(body, "kg", gt=0)
    expected_version = get_int(body, "expected_regrind_pool_version")

    run = fetch("extrusion_run", run_id)
    pool = resolve_fks({"pool_id": pool_id})["pool_id"]

    if expected_version != pool["version"]:
        raise ApiError(
            "ERR_STALE_POOL_VERSION",
            "expected_regrind_pool_version %s does not match the pool's current version %s."
            % (expected_version, pool["version"]),
        )
    if run["status"] not in ("RUNNING", "HELD"):
        raise ApiError(
            "ERR_RUN_STATE_INVALID", "Regrind may only be drawn into a RUNNING or HELD run."
        )

    recipe = refs.recipe_of_run(run)
    product = refs.product_of_recipe(recipe)
    if product["food_contact_required"] and pool["food_contact_status"] != "FOOD_CONTACT_ELIGIBLE":
        raise ApiError(
            "ERR_FOOD_CONTACT_POOL_INELIGIBLE",
            "A food-contact product may not draw from a NON_FOOD_ONLY pool.",
        )
    if pool["polymer_family"] != recipe["dominant_polymer_family"]:
        raise ApiError(
            "ERR_FOOD_CONTACT_POOL_INELIGIBLE",
            "The pool's polymer_family differs from the recipe's dominant_polymer_family.",
        )

    available = D(pool["available_kg"])
    if D(kg) > available:
        raise ApiError(
            "ERR_REGRIND_INSUFFICIENT",
            "The pool holds only %s kg available." % pool["available_kg"],
        )

    consumed = D(run["regrind_consumed_kg"] or 0)
    budget = D(run["target_output_kg"]) * D(recipe["regrind_cap_pct"]) / D(100)
    if r(consumed + D(kg), 3) > budget:
        raise ApiError(
            "ERR_REGRIND_BUDGET_EXCEEDED",
            "This draw would push cumulative regrind consumption past the run's regrind budget.",
        )

    pcr_kg = r(D(kg) * D(pool["embedded_pcr_pct"]) / D(100), 3)
    row = cascade.book_transaction(
        pool,
        direction="OUT",
        origin_kind="REINCORPORATION",
        kg=kg,
        pcr_kg=pcr_kg,
        extrusion_run_id=run["id"],
    )
    calc.recompute_run_regrind(run)
    store.touch(run)
    return created(row)


@bp.post("/extrusion-runs/<run_id>/complete")
@endpoint(["ExtrusionOperator"])
def complete_run(run_id):
    body = parse_body(required=True)
    gross_output_kg = get_num(body, "gross_output_kg", ge=0)
    scrap_kg = get_num(body, "scrap_kg", ge=0)

    run = fetch("extrusion_run", run_id)
    if run["status"] != "RUNNING":
        raise ApiError("ERR_RUN_STATE_INVALID", "Only a RUNNING run may be completed.")

    recipe = refs.recipe_of_run(run)
    product = refs.product_of_recipe(recipe)
    line = refs.line_of_run(run)

    if len(run["gauge_readings"]) < C.MIN_GAUGE_SAMPLES:
        raise ApiError(
            "ERR_INSUFFICIENT_GAUGE_DATA",
            "At least %d gauge samples are required to close a run." % C.MIN_GAUGE_SAMPLES,
        )
    if D(scrap_kg) > D(gross_output_kg):
        raise ApiError("ERR_SCRAP_EXCEEDS_OUTPUT", "scrap_kg may not exceed gross_output_kg.")

    pool = refs.eligible_pool(
        recipe["dominant_polymer_family"], bool(product["food_contact_required"])
    )
    if D(scrap_kg) > 0 and pool is None:
        raise ApiError(
            "ERR_NO_ELIGIBLE_REGRIND_POOL",
            "No regrind pool matches this recipe's polymer family and the product's food-contact status.",
        )

    calc.recompute_gauge(run)
    run["gross_output_kg"] = gross_output_kg
    run["scrap_kg"] = scrap_kg
    actual, scrap_pcr = calc.run_mass_balance(run, gross_output_kg, scrap_kg)
    run["status"] = "COMPLETED"
    run["recipe_pin_released"] = True
    store.touch(run)

    cascade.propagate_recycled_content(run)

    if D(scrap_kg) > 0 and pool is not None:
        cascade.book_transaction(
            pool,
            direction="IN",
            origin_kind="EXTRUSION_SCRAP",
            kg=scrap_kg,
            pcr_kg=scrap_pcr,
            extrusion_run_id=run["id"],
        )

    cascade.release_recipe_pin(recipe)

    incapable = 1 if run["gauge_capability_state"] == "INCAPABLE" else 0
    cascade.rederive_line_posture(
        line,
        "Line posture became FROZEN after run %s closed." % run["run_code"],
        incapable_delta=incapable,
    )
    return ok(run)


# =============================================================== film rolls ==
@bp.post("/film-rolls")
@endpoint(["ExtrusionOperator"])
def create_roll():
    body = parse_body(required=True)
    extrusion_run_id = get_str(body, "extrusion_run_id")
    roll_number = get_int(body, "roll_number", gt=0)
    net_kg = get_num(body, "net_kg", gt=0)
    layflat = get_num(body, "layflat_mm", required=False, default=None)
    gauge_avg = get_num(body, "gauge_micron_avg", required=False, default=None)

    run = resolve_fks({"extrusion_run_id": extrusion_run_id})["extrusion_run_id"]
    for existing in store.film_rolls.values():
        if existing["extrusion_run_id"] == run["id"] and existing["roll_number"] == roll_number:
            raise ApiError(
                "ERR_DUPLICATE_CODE",
                "roll_number %s is already used within this run." % roll_number,
            )

    product = refs.product_of_run(run)
    if layflat is None:
        layflat = product["layflat_width_mm"]
    if gauge_avg is None:
        gauge_avg = product["target_gauge_micron"]

    roll = store.new_common()
    roll.update(
        {
            "extrusion_run_id": run["id"],
            "roll_number": roll_number,
            "net_kg": net_kg,
            "layflat_mm": layflat,
            "gauge_micron_avg": gauge_avg,
            "status": "WOUND",
            "actual_recycled_content_pct": run.get("actual_recycled_content_pct"),
            "release_blocked_reason": None,
        }
    )
    store.film_rolls[roll["id"]] = roll
    return created(roll)


@bp.get("/film-rolls/<roll_id>")
@endpoint(ANY_ROLE)
def read_roll(roll_id):
    return ok(fetch("film_roll", roll_id))


@bp.get("/film-rolls")
@endpoint(ANY_ROLE)
def list_rolls():
    return list_endpoint(store.film_rolls, ("extrusion_run_id", "status"))


@bp.post("/film-rolls/<roll_id>/release")
@endpoint(["QualityManager"])
def release_roll(roll_id):
    parse_body(required=False)
    roll = fetch("film_roll", roll_id)
    if roll["status"] != "WOUND":
        raise ApiError("ERR_ROLL_STATE_INVALID", "Only a WOUND roll may be released.")

    run = refs.run_of_roll(roll)
    line = refs.line_of_run(run) if run else None
    product = refs.product_of_run(run) if run else None

    if run is None or run["status"] != "COMPLETED":
        raise ApiError("ERR_RUN_STATE_INVALID", "The producing run must be COMPLETED.")
    if line is not None and line["posture"] == "FROZEN":
        raise ApiError("ERR_LINE_POSTURE_FROZEN", "The producing line's posture is FROZEN.")
    if run["gauge_capability_state"] not in ("CAPABLE", "MARGINAL"):
        raise ApiError(
            "ERR_GAUGE_CAPABILITY_INSUFFICIENT",
            "The producing run's gauge capability is %s." % run["gauge_capability_state"],
        )
    if abs(D(roll["layflat_mm"]) - D(product["layflat_width_mm"])) > C.LAYFLAT_TOLERANCE_MM:
        raise ApiError(
            "ERR_LAYFLAT_OUT_OF_TOLERANCE",
            "The roll's layflat deviates from the product target by more than %s mm."
            % C.LAYFLAT_TOLERANCE_MM,
        )

    roll["status"] = "RELEASED"
    roll["release_blocked_reason"] = None
    store.touch(roll)
    return ok(roll)


@bp.post("/film-rolls/<roll_id>/scrap")
@endpoint(["QualityManager"])
def scrap_roll(roll_id):
    body = parse_body(required=False)
    pool_id = get_str(body, "pool_id", required=False, default=None)
    roll = fetch("film_roll", roll_id)
    pool = resolve_fks({"pool_id": pool_id})["pool_id"] if pool_id else None

    if roll["status"] not in ("WOUND", "QUARANTINED"):
        raise ApiError(
            "ERR_ROLL_STATE_INVALID", "Only a WOUND or QUARANTINED roll may be scrapped."
        )

    if pool is None:
        run = refs.run_of_roll(roll)
        recipe = refs.recipe_of_run(run) if run else None
        product = refs.product_of_recipe(recipe) if recipe else None
        pool = refs.eligible_pool(
            recipe["dominant_polymer_family"] if recipe else None,
            bool(product["food_contact_required"]) if product else False,
        )
        if pool is None:
            raise ApiError(
                "ERR_NO_ELIGIBLE_REGRIND_POOL",
                "No regrind pool matches this roll's polymer family and food-contact status.",
            )

    content = roll.get("actual_recycled_content_pct")
    pcr_kg = r(D(roll["net_kg"]) * D(content) / D(100), 3) if content is not None else ZERO
    cascade.book_transaction(
        pool,
        direction="IN",
        origin_kind="ROLL_SCRAP",
        kg=roll["net_kg"],
        pcr_kg=pcr_kg,
        origin_ref_id=roll["id"],
    )
    roll["status"] = "SCRAPPED"
    store.touch(roll)
    return ok(roll)
