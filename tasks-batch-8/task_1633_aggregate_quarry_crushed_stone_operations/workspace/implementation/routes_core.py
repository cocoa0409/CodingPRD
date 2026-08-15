"""Routes: sites, benches, shot plans, muckpiles, product specs, stockpiles,
gradation tests, scales, calibrations, plant runs, clock."""

from decimal import Decimal

from flask import Blueprint

from core import (
    base_resource,
    body,
    list_response,
    logical_now,
    logical_now_iso,
    logical_today,
    ok_object,
    parse_pagination,
    require_roles,
    touch,
)
from db import db
from errors import (
    err_active_shot_plan,
    err_adjustment_below_reserved,
    err_bench_not_released,
    err_bench_sequence_violation,
    err_circuit_overlap,
    err_holes_incomplete,
    err_invalid_request,
    err_invalid_state,
    err_muckpile_depleted,
    err_not_found,
    err_outside_blast_window,
    err_output_imbalance,
    err_permit_acreage_exceeded,
    err_reversal_blocked,
    err_scale_not_certified,
    err_site_posture_blocked,
    err_sod_violation,
    err_spec_retired,
    err_stale_version,
    err_stockpile_capacity_exceeded,
    err_stockpile_exists,
    err_stockpile_not_empty,
    err_stockpile_quarantined,
    err_training_expired,
)
from services import (
    D,
    allocation_sweep,
    compute_quote,
    parse_iso_date,
    parse_iso_datetime,
    q,
    recompute_scale_certification,
    recompute_site,
    reevaluate_quarantine,
    refresh_stockpile,
    scale_usable,
    to_float,
)

bp = Blueprint("core_routes", __name__)

ALL_ROLES = [
    "QuarryAdmin",
    "SiteManager",
    "BlastForeman",
    "PlantOperator",
    "ScaleHouseOperator",
    "QCTechnician",
    "SalesAgent",
    "FinanceClerk",
    "SafetyOfficer",
]

ROCK_DENSITY = Decimal("1.6")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def req_field(data, name):
    if name not in data or data[name] is None:
        raise err_invalid_request(f"Missing required field: {name}")
    return data[name]


def req_string(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or v == "":
        raise err_invalid_request(f"Field {name} must be a non-empty string")
    return v


def req_number(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"Field {name} must be a number")
    return v


def req_positive(data, name):
    v = req_number(data, name)
    if D(v) <= 0:
        raise err_invalid_request(f"Field {name} must be > 0")
    return v


def req_nonnegative(data, name):
    v = req_number(data, name)
    if D(v) < 0:
        raise err_invalid_request(f"Field {name} must be >= 0")
    return v


def req_int(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {name} must be an integer")
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if v not in allowed:
        raise err_invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_bool(data, name):
    v = req_field(data, name)
    if not isinstance(v, bool):
        raise err_invalid_request(f"Field {name} must be a boolean")
    return v


def get_or_404(collection, rid):
    resource = collection.get(rid)
    if resource is None:
        raise err_not_found(f"Resource {rid} not found")
    return resource


def optional_number(data, name):
    if name not in data or data[name] is None:
        return None
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"Field {name} must be a number")
    return v


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(["QuarryAdmin"])
    data = body()
    to = req_field(data, "to_iso8601")
    dt = parse_iso_datetime(to)
    db.clock = dt
    now = db.clock
    iso = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return ok_object({"current_utc": iso}, 200)


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

@bp.route("/sites", methods=["POST"])
def create_site():
    require_roles(["QuarryAdmin"])
    data = body()
    name = req_string(data, "name")
    permitted = req_positive(data, "permitted_acres")
    rate = req_positive(data, "bond_rate_per_acre_usd")
    site = base_resource()
    site.update(
        {
            "name": name,
            "permitted_acres": permitted,
            "bond_rate_per_acre_usd": rate,
            "disturbed_acres": 0.0,
            "bond_required_usd": 0.0,
            "bond_posted_usd": 0.0,
            "bond_adequacy": "ADEQUATE",
            "posture": "OPERATING",
        }
    )
    db.sites[site["id"]] = site
    return ok_object(site, 201)


@bp.route("/sites", methods=["GET"])
def list_sites():
    require_roles(ALL_ROLES)
    return list_response(db.sites)


@bp.route("/sites/<sid>", methods=["GET"])
def get_site(sid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.sites, sid))


@bp.route("/sites/<sid>/recompute-posture", methods=["POST"])
def recompute_posture(sid):
    require_roles(["SiteManager", "SafetyOfficer"])
    site = get_or_404(db.sites, sid)
    return ok_object(recompute_site(site["id"]))


# ---------------------------------------------------------------------------
# Benches
# ---------------------------------------------------------------------------

@bp.route("/benches", methods=["POST"])
def create_bench():
    require_roles(["SiteManager"])
    data = body()
    site_id = req_string(data, "site_id")
    label = req_string(data, "bench_label")
    elevation = req_number(data, "elevation_ft")
    acreage = req_positive(data, "acreage")
    get_or_404(db.sites, site_id)
    bench = base_resource()
    bench.update(
        {
            "site_id": site_id,
            "bench_label": label,
            "elevation_ft": elevation,
            "acreage": acreage,
            "status": "PLANNED",
            "hold_reason": None,
        }
    )
    db.benches[bench["id"]] = bench
    return ok_object(bench, 201)


@bp.route("/benches", methods=["GET"])
def list_benches():
    require_roles(ALL_ROLES)
    filters = {
        "site_id": _qs("site_id"),
        "status": _qs("status"),
    }
    return list_response(db.benches, filters)


def _qs(name):
    from flask import request

    return request.args.get(name)


@bp.route("/benches/<bid>", methods=["GET"])
def get_bench(bid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.benches, bid))


@bp.route("/benches/<bid>/release", methods=["POST"])
def release_bench(bid):
    require_roles(["SiteManager"])
    bench = get_or_404(db.benches, bid)
    if bench["status"] != "PLANNED":
        raise err_invalid_state("Only a PLANNED bench can be released")
    site = db.sites[bench["site_id"]]
    # Posture gate: OPERATING only
    if site["posture"] != "OPERATING":
        raise err_site_posture_blocked("Bench release requires posture OPERATING")
    # Top-down sequence
    for other in db.benches.values():
        if other["site_id"] != site["id"] or other["id"] == bench["id"]:
            continue
        if D(other["elevation_ft"]) > D(bench["elevation_ft"]) and other["status"] not in (
            "MINED_OUT",
            "RECLAMATION_IN_PROGRESS",
            "RECLAIMED",
        ):
            raise err_bench_sequence_violation(
                "Higher-elevation benches must be mined out first"
            )
    # Permit headroom
    if D(site["disturbed_acres"]) + D(bench["acreage"]) > D(site["permitted_acres"]):
        raise err_permit_acreage_exceeded("Release would exceed permitted acres")
    bench["status"] = "RELEASED"
    touch(bench)
    recompute_site(site["id"])
    return ok_object(bench)


@bp.route("/benches/<bid>/hold", methods=["POST"])
def hold_bench(bid):
    require_roles(["SiteManager"])
    data = body()
    reason = req_string(data, "reason")
    bench = get_or_404(db.benches, bid)
    if bench["status"] != "RELEASED":
        raise err_invalid_state("Only a RELEASED bench can be held")
    bench["status"] = "ON_HOLD"
    bench["hold_reason"] = reason
    touch(bench)
    return ok_object(bench)


def _resume_bench(bench):
    bench["status"] = "RELEASED"
    bench["hold_reason"] = None
    touch(bench)
    for plan in db.shot_plans.values():
        if plan["bench_id"] == bench["id"] and plan["status"] == "ON_HOLD":
            plan["status"] = plan.get("hold_return_state") or "APPROVED"
            plan["hold_return_state"] = None
            touch(plan)


@bp.route("/benches/<bid>/resume", methods=["POST"])
def resume_bench(bid):
    require_roles(["SiteManager"])
    bench = get_or_404(db.benches, bid)
    if bench["status"] != "ON_HOLD":
        raise err_invalid_state("Only an ON_HOLD bench can be resumed")
    site = db.sites[bench["site_id"]]
    if site["posture"] == "SUSPENDED":
        raise err_site_posture_blocked("Cannot resume while site is SUSPENDED")
    _resume_bench(bench)
    return ok_object(bench)


@bp.route("/benches/<bid>/mark-mined-out", methods=["POST"])
def mark_mined_out(bid):
    require_roles(["SiteManager"])
    bench = get_or_404(db.benches, bid)
    if bench["status"] != "RELEASED":
        raise err_invalid_state("Only a RELEASED bench can be marked mined out")
    for plan in db.shot_plans.values():
        if plan["bench_id"] == bench["id"] and plan["status"] in (
            "APPROVED",
            "DRILLING",
            "DRILLED",
            "LOADED",
            "ON_HOLD",
        ):
            raise err_active_shot_plan("Bench has live shot plans")
    bench["status"] = "MINED_OUT"
    touch(bench)
    recompute_site(bench["site_id"])
    return ok_object(bench)


@bp.route("/benches/<bid>/start-reclamation", methods=["POST"])
def start_reclamation(bid):
    require_roles(["SiteManager"])
    bench = get_or_404(db.benches, bid)
    if bench["status"] != "MINED_OUT":
        raise err_invalid_state("Only a MINED_OUT bench can start reclamation")
    site = db.sites[bench["site_id"]]
    if site["posture"] == "SUSPENDED":
        raise err_site_posture_blocked("Site is SUSPENDED")
    bench["status"] = "RECLAMATION_IN_PROGRESS"
    touch(bench)
    recompute_site(bench["site_id"])
    return ok_object(bench)


@bp.route("/benches/<bid>/complete-reclamation", methods=["POST"])
def complete_reclamation(bid):
    require_roles(["SiteManager"])
    bench = get_or_404(db.benches, bid)
    if bench["status"] != "RECLAMATION_IN_PROGRESS":
        raise err_invalid_state("Only RECLAMATION_IN_PROGRESS can complete")
    site = db.sites[bench["site_id"]]
    # Guard evaluates against PRE-transition posture.
    if site["posture"] == "SUSPENDED":
        raise err_site_posture_blocked("Site is SUSPENDED")
    bench["status"] = "RECLAIMED"
    touch(bench)
    recompute_site(bench["site_id"])
    return ok_object(bench)


# ---------------------------------------------------------------------------
# Shot plans
# ---------------------------------------------------------------------------

def _powder_factor(plan):
    estimated = D(plan["estimated_tons"])
    if estimated == 0:
        return None
    if plan.get("loaded_explosive_lbs") is not None:
        load = D(plan["loaded_explosive_lbs"])
    else:
        load = D(plan["hole_count"]) * D(plan["explosive_per_hole_lbs"])
    return to_float(q(load / estimated, 2))


@bp.route("/shot-plans", methods=["POST"])
def create_shot_plan():
    require_roles(["BlastForeman"])
    data = body()
    bench_id = req_string(data, "bench_id")
    hole_count = req_int(data, "hole_count")
    if hole_count < 1:
        raise err_invalid_request("hole_count must be >= 1")
    burden = req_positive(data, "burden_ft")
    spacing = req_positive(data, "spacing_ft")
    depth = req_positive(data, "hole_depth_ft")
    explosive = req_positive(data, "explosive_per_hole_lbs")
    get_or_404(db.benches, bench_id)
    volume_yd3 = (
        D(hole_count) * D(burden) * D(spacing) * D(depth) / Decimal(27)
    )
    estimated = q(volume_yd3 * ROCK_DENSITY, 1)
    plan = base_resource()
    plan.update(
        {
            "bench_id": bench_id,
            "hole_count": hole_count,
            "burden_ft": burden,
            "spacing_ft": spacing,
            "hole_depth_ft": depth,
            "explosive_per_hole_lbs": explosive,
            "drilled_hole_count": 0,
            "loaded_explosive_lbs": None,
            "estimated_tons": to_float(estimated),
            "powder_factor": None,
            "status": "DRAFT",
            "hold_return_state": None,
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "fired_at": None,
        }
    )
    plan["powder_factor"] = _powder_factor(plan)
    db.shot_plans[plan["id"]] = plan
    return ok_object(plan, 201)


@bp.route("/shot-plans", methods=["GET"])
def list_shot_plans():
    require_roles(ALL_ROLES)
    filters = {"bench_id": _qs("bench_id"), "status": _qs("status")}
    return list_response(db.shot_plans, filters)


@bp.route("/shot-plans/<pid>", methods=["GET"])
def get_shot_plan(pid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.shot_plans, pid))


def _plan_and_bench(pid):
    plan = get_or_404(db.shot_plans, pid)
    bench = db.benches[plan["bench_id"]]
    site = db.sites[bench["site_id"]]
    return plan, bench, site


@bp.route("/shot-plans/<pid>/submit", methods=["POST"])
def submit_plan(pid):
    user_id, _ = require_roles(["BlastForeman"])
    plan = get_or_404(db.shot_plans, pid)
    if plan["status"] != "DRAFT":
        raise err_invalid_state("Only DRAFT plans can be submitted")
    plan["status"] = "SUBMITTED"
    plan["submitted_by_user_id"] = user_id
    touch(plan)
    return ok_object(plan)


@bp.route("/shot-plans/<pid>/approve", methods=["POST"])
def approve_plan(pid):
    user_id, _ = require_roles(["SiteManager"])
    plan, bench, site = _plan_and_bench(pid)
    if plan["status"] != "SUBMITTED":
        raise err_invalid_state("Only SUBMITTED plans can be approved")
    if bench["status"] != "RELEASED":
        raise err_bench_not_released("Bench must be RELEASED")
    if site["posture"] not in ("OPERATING", "RESTRICTED"):
        raise err_site_posture_blocked("Site is SUSPENDED")
    if user_id == plan.get("submitted_by_user_id"):
        raise err_sod_violation("Approver must differ from submitter")
    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = user_id
    touch(plan)
    return ok_object(plan)


@bp.route("/shot-plans/<pid>/start-drilling", methods=["POST"])
def start_drilling(pid):
    require_roles(["BlastForeman"])
    plan, bench, site = _plan_and_bench(pid)
    if plan["status"] != "APPROVED":
        raise err_invalid_state("Only APPROVED plans can start drilling")
    if bench["status"] != "RELEASED":
        raise err_bench_not_released("Bench must be RELEASED")
    if site["posture"] not in ("OPERATING", "RESTRICTED"):
        raise err_site_posture_blocked("Site is SUSPENDED")
    plan["status"] = "DRILLING"
    touch(plan)
    return ok_object(plan)


@bp.route("/shot-plans/<pid>/complete-drilling", methods=["POST"])
def complete_drilling(pid):
    require_roles(["BlastForeman"])
    data = body()
    drilled = req_int(data, "drilled_hole_count")
    plan, bench, site = _plan_and_bench(pid)
    if plan["status"] != "DRILLING":
        raise err_invalid_state("Only DRILLING plans can complete drilling")
    if bench["status"] != "RELEASED":
        raise err_bench_not_released("Bench must be RELEASED")
    if drilled < plan["hole_count"]:
        raise err_holes_incomplete("drilled_hole_count below design hole_count")
    plan["drilled_hole_count"] = drilled
    plan["status"] = "DRILLED"
    touch(plan)
    return ok_object(plan)


@bp.route("/shot-plans/<pid>/redrill", methods=["POST"])
def redrill(pid):
    require_roles(["BlastForeman"])
    plan, bench, site = _plan_and_bench(pid)
    if plan["status"] != "DRILLED":
        raise err_invalid_state("Only DRILLED plans can be redrilled")
    if bench["status"] != "RELEASED":
        raise err_bench_not_released("Bench must be RELEASED")
    if site["posture"] == "SUSPENDED":
        raise err_site_posture_blocked("Site is SUSPENDED")
    plan["status"] = "DRILLING"
    plan["drilled_hole_count"] = 0
    touch(plan)
    return ok_object(plan)


@bp.route("/shot-plans/<pid>/load", methods=["POST"])
def load_plan(pid):
    require_roles(["BlastForeman"])
    data = body()
    loaded = req_positive(data, "loaded_explosive_lbs")
    plan, bench, site = _plan_and_bench(pid)
    if plan["status"] != "DRILLED":
        raise err_invalid_state("Only DRILLED plans can be loaded")
    if bench["status"] != "RELEASED":
        raise err_bench_not_released("Bench must be RELEASED")
    plan["loaded_explosive_lbs"] = loaded
    plan["powder_factor"] = _powder_factor(plan)
    plan["status"] = "LOADED"
    touch(plan)
    return ok_object(plan)


@bp.route("/shot-plans/<pid>/fire", methods=["POST"])
def fire_plan(pid):
    user_id, _ = require_roles(["BlastForeman"])
    plan, bench, site = _plan_and_bench(pid)
    if plan["status"] != "LOADED":
        raise err_invalid_state("Only LOADED plans can be fired")
    if bench["status"] != "RELEASED":
        raise err_bench_not_released("Bench must be RELEASED")
    if site["posture"] != "OPERATING":
        raise err_site_posture_blocked("Firing requires posture OPERATING")
    # Training gate: current TASK_TRAINING record for X-User-ID
    today = logical_today()
    trained = False
    for rec in db.training_records.values():
        if (
            rec["miner_user_id"] == user_id
            and rec["course_type"] == "TASK_TRAINING"
            and parse_iso_date(rec["expires_on"]) >= today
        ):
            trained = True
            break
    if not trained:
        raise err_training_expired("No current TASK_TRAINING record for firing user")
    hour = logical_now().hour
    if not (8 <= hour < 17):
        raise err_outside_blast_window("Outside the 08:00-17:00 UTC blasting window")
    plan["status"] = "FIRED"
    plan["fired_at"] = logical_now_iso()
    touch(plan)
    # Create the muckpile 1:1
    pile = base_resource()
    pile.update(
        {
            "shot_plan_id": plan["id"],
            "estimated_tons": plan["estimated_tons"],
            "actual_fed_tons": 0.0,
            "remaining_tons": plan["estimated_tons"],
            "status": "OPEN",
        }
    )
    db.muckpiles[pile["id"]] = pile
    return ok_object(plan)


@bp.route("/shot-plans/<pid>/cancel", methods=["POST"])
def cancel_plan(pid):
    require_roles(["BlastForeman"])
    plan = get_or_404(db.shot_plans, pid)
    if plan["status"] not in ("DRAFT", "SUBMITTED", "APPROVED"):
        raise err_invalid_state("Plan cannot be cancelled from its state")
    plan["status"] = "CANCELLED"
    touch(plan)
    return ok_object(plan)


# ---------------------------------------------------------------------------
# Muckpiles
# ---------------------------------------------------------------------------

@bp.route("/muckpiles", methods=["GET"])
def list_muckpiles():
    require_roles(ALL_ROLES)
    filters = {"shot_plan_id": _qs("shot_plan_id"), "status": _qs("status")}
    return list_response(db.muckpiles, filters)


@bp.route("/muckpiles/<mid>", methods=["GET"])
def get_muckpile(mid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.muckpiles, mid))


# ---------------------------------------------------------------------------
# Product specs
# ---------------------------------------------------------------------------

@bp.route("/product-specs", methods=["POST"])
def create_spec():
    require_roles(["QuarryAdmin"])
    data = body()
    code = req_string(data, "spec_code")
    category = req_enum(data, "category", {"COARSE", "FINE", "RIPRAP"})
    bands = req_field(data, "gradation_bands")
    if not isinstance(bands, list) or len(bands) < 1:
        raise err_invalid_request("gradation_bands must be a non-empty array")
    for band in bands:
        if not isinstance(band, dict):
            raise err_invalid_request("Each gradation band must be an object")
        sieve = band.get("sieve")
        if not isinstance(sieve, str) or sieve == "":
            raise err_invalid_request("Each band requires a sieve name")
        mn, mx = band.get("min_pct"), band.get("max_pct")
        if isinstance(mn, bool) or isinstance(mx, bool) or not isinstance(
            mn, (int, float)
        ) or not isinstance(mx, (int, float)):
            raise err_invalid_request("Band min_pct/max_pct must be numbers")
        if D(mn) > D(mx):
            raise err_invalid_request("min_pct must be <= max_pct")
    price = req_positive(data, "base_price_per_ton")
    for other in db.product_specs.values():
        if other["spec_code"] == code:
            raise err_invalid_request("spec_code must be unique")
    spec = base_resource()
    spec.update(
        {
            "spec_code": code,
            "category": category,
            "gradation_bands": bands,
            "base_price_per_ton": price,
            "status": "ACTIVE",
        }
    )
    db.product_specs[spec["id"]] = spec
    return ok_object(spec, 201)


@bp.route("/product-specs", methods=["GET"])
def list_specs():
    require_roles(ALL_ROLES)
    return list_response(db.product_specs, {"status": _qs("status")})


@bp.route("/product-specs/<sid>", methods=["GET"])
def get_spec(sid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.product_specs, sid))


@bp.route("/product-specs/<sid>/retire", methods=["POST"])
def retire_spec(sid):
    require_roles(["QuarryAdmin"])
    spec = get_or_404(db.product_specs, sid)
    if spec["status"] != "ACTIVE":
        raise err_invalid_state("Only ACTIVE specs can be retired")
    spec["status"] = "RETIRED"
    touch(spec)
    return ok_object(spec)


# ---------------------------------------------------------------------------
# Stockpiles
# ---------------------------------------------------------------------------

@bp.route("/stockpiles", methods=["POST"])
def create_stockpile():
    require_roles(["SiteManager"])
    data = body()
    site_id = req_string(data, "site_id")
    spec_id = req_string(data, "product_spec_id")
    capacity = req_positive(data, "capacity_tons")
    get_or_404(db.sites, site_id)
    get_or_404(db.product_specs, spec_id)
    for other in db.stockpiles.values():
        if other["site_id"] == site_id and other["product_spec_id"] == spec_id:
            raise err_stockpile_exists("Stockpile already exists for site+spec")
    pile = base_resource()
    pile.update(
        {
            "site_id": site_id,
            "product_spec_id": spec_id,
            "capacity_tons": capacity,
            "on_hand_tons": 0.0,
            "reserved_tons": 0.0,
            "available_tons": 0.0,
            "status": "OPEN",
        }
    )
    db.stockpiles[pile["id"]] = pile
    return ok_object(pile, 201)


@bp.route("/stockpiles", methods=["GET"])
def list_stockpiles():
    require_roles(ALL_ROLES)
    filters = {
        "site_id": _qs("site_id"),
        "product_spec_id": _qs("product_spec_id"),
        "status": _qs("status"),
    }
    return list_response(db.stockpiles, filters)


@bp.route("/stockpiles/<sid>", methods=["GET"])
def get_stockpile(sid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.stockpiles, sid))


@bp.route("/stockpiles/<sid>/adjustments", methods=["POST"])
def adjust_stockpile(sid):
    require_roles(["SiteManager"])
    pile = get_or_404(db.stockpiles, sid)
    if pile["status"] == "CLOSED":
        raise err_invalid_state("CLOSED stockpile cannot be adjusted")
    data = body()
    delta = req_number(data, "delta_tons")
    reason = req_string(data, "reason")
    expected = req_field(data, "expected_stockpile_version")
    new_on_hand = D(pile["on_hand_tons"]) + D(delta)
    if new_on_hand < 0:
        raise err_adjustment_below_reserved("Adjustment would drive on-hand below zero")
    if new_on_hand < D(pile["reserved_tons"]):
        raise err_adjustment_below_reserved(
            "Adjustment would drop on_hand below reserved"
        )
    if new_on_hand > D(pile["capacity_tons"]):
        raise err_stockpile_capacity_exceeded("Adjustment exceeds capacity")
    # OCC evaluated last (tier 12)
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_stockpile_version must be an integer")
    if expected != pile["version"]:
        raise err_stale_version("Stale stockpile version")
    pile["on_hand_tons"] = to_float(q(new_on_hand, 3))
    refresh_stockpile(pile)
    touch(pile)
    if D(delta) > 0 and pile["status"] == "OPEN":
        allocation_sweep(pile)
    refresh_stockpile(pile)
    return ok_object(pile)


@bp.route("/stockpiles/<sid>/close", methods=["POST"])
def close_stockpile(sid):
    require_roles(["SiteManager"])
    pile = get_or_404(db.stockpiles, sid)
    if pile["status"] == "CLOSED":
        raise err_invalid_state("Stockpile already CLOSED")
    refresh_stockpile(pile)
    if D(pile["on_hand_tons"]) != 0 or D(pile["reserved_tons"]) != 0:
        raise err_stockpile_not_empty("Stockpile must be empty to close")
    pile["status"] = "CLOSED"
    touch(pile)
    return ok_object(pile)


# ---------------------------------------------------------------------------
# Gradation tests
# ---------------------------------------------------------------------------

@bp.route("/gradation-tests", methods=["POST"])
def create_gradation_test():
    user_id, _ = require_roles(["QCTechnician"])
    data = body()
    stockpile_id = req_string(data, "stockpile_id")
    sampled_at = req_field(data, "sampled_at")
    sieve_results = req_field(data, "sieve_results")
    # Type-shape validation of sieve_results before existence (tier 3)
    if not isinstance(sieve_results, list):
        raise err_invalid_request("sieve_results must be an array")
    for entry in sieve_results:
        if not isinstance(entry, dict):
            raise err_invalid_request("Each sieve result must be an object")
        if not isinstance(entry.get("sieve"), str) or entry.get("sieve") == "":
            raise err_invalid_request("Each sieve result requires a sieve name")
        pct = entry.get("pct_passing")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            raise err_invalid_request("pct_passing must be a number")
    parse_iso_datetime(sampled_at)  # validate timestamp shape
    pile = get_or_404(db.stockpiles, stockpile_id)
    spec = db.product_specs[pile["product_spec_id"]]
    band_sieves = {b["sieve"] for b in spec["gradation_bands"]}
    result_sieves = [e["sieve"] for e in sieve_results]
    if len(result_sieves) != len(set(result_sieves)) or set(result_sieves) != band_sieves:
        raise err_invalid_request(
            "sieve_results must cover exactly the spec's band sieves"
        )
    # Compute result (inclusive bounds)
    by_sieve = {e["sieve"]: e["pct_passing"] for e in sieve_results}
    passed = True
    for band in spec["gradation_bands"]:
        pct = D(by_sieve[band["sieve"]])
        if pct < D(band["min_pct"]) or pct > D(band["max_pct"]):
            passed = False
            break
    test = base_resource()
    test.update(
        {
            "stockpile_id": stockpile_id,
            "sampled_at": sampled_at,
            "sieve_results": sieve_results,
            "result": "PASS" if passed else "FAIL",
            "status": "REPORTED",
            "reported_by_user_id": user_id,
            "confirmed_by_user_id": None,
        }
    )
    db.gradation_tests[test["id"]] = test
    return ok_object(test, 201)


@bp.route("/gradation-tests", methods=["GET"])
def list_gradation_tests():
    require_roles(ALL_ROLES)
    filters = {"stockpile_id": _qs("stockpile_id"), "status": _qs("status")}
    return list_response(db.gradation_tests, filters)


@bp.route("/gradation-tests/<tid>", methods=["GET"])
def get_gradation_test(tid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.gradation_tests, tid))


@bp.route("/gradation-tests/<tid>/confirm", methods=["POST"])
def confirm_gradation_test(tid):
    user_id, _ = require_roles(["QCTechnician"])
    test = get_or_404(db.gradation_tests, tid)
    if test["status"] != "REPORTED":
        raise err_invalid_state("Only REPORTED tests can be confirmed")
    pile = db.stockpiles[test["stockpile_id"]]
    if pile["status"] == "CLOSED":
        raise err_invalid_state("Stockpile is CLOSED")
    if user_id == test["reported_by_user_id"]:
        raise err_sod_violation("Confirmer must differ from reporter")
    test["status"] = "CONFIRMED"
    test["confirmed_by_user_id"] = user_id
    touch(test)
    reevaluate_quarantine(pile)
    return ok_object(test)


@bp.route("/gradation-tests/<tid>/void", methods=["POST"])
def void_gradation_test(tid):
    require_roles(["QCTechnician"])
    test = get_or_404(db.gradation_tests, tid)
    if test["status"] == "VOIDED":
        raise err_invalid_state("Test already VOIDED")
    test["status"] = "VOIDED"
    touch(test)
    pile = db.stockpiles[test["stockpile_id"]]
    reevaluate_quarantine(pile)
    return ok_object(test)


# ---------------------------------------------------------------------------
# Scales and calibrations
# ---------------------------------------------------------------------------

@bp.route("/scales", methods=["POST"])
def create_scale():
    require_roles(["QuarryAdmin"])
    data = body()
    site_id = req_string(data, "site_id")
    code = req_string(data, "scale_code")
    stype = req_enum(data, "scale_type", {"TRUCK", "BELT"})
    get_or_404(db.sites, site_id)
    for other in db.scales.values():
        if other["site_id"] == site_id and other["scale_code"] == code:
            raise err_invalid_request("scale_code must be unique within the site")
    scale = base_resource()
    scale.update(
        {
            "site_id": site_id,
            "scale_code": code,
            "scale_type": stype,
            "status": "OUT_OF_SERVICE",
            "certified_through": None,
        }
    )
    db.scales[scale["id"]] = scale
    return ok_object(scale, 201)


@bp.route("/scales", methods=["GET"])
def list_scales():
    require_roles(ALL_ROLES)
    filters = {
        "site_id": _qs("site_id"),
        "scale_type": _qs("scale_type"),
        "status": _qs("status"),
    }
    return list_response(db.scales, filters)


@bp.route("/scales/<sid>", methods=["GET"])
def get_scale(sid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.scales, sid))


@bp.route("/scale-calibrations", methods=["POST"])
def create_calibration():
    require_roles(["QuarryAdmin"])
    data = body()
    scale_id = req_string(data, "scale_id")
    calibrated_on = req_string(data, "calibrated_on")
    parse_iso_date(calibrated_on)
    as_found = req_number(data, "as_found_error_pct")
    as_left = req_number(data, "as_left_error_pct")
    scale = get_or_404(db.scales, scale_id)
    result = "PASS" if abs(D(as_left)) <= Decimal("0.25") else "FAIL"
    cal = base_resource()
    cal.update(
        {
            "scale_id": scale_id,
            "calibrated_on": calibrated_on,
            "as_found_error_pct": as_found,
            "as_left_error_pct": as_left,
            "result": result,
            "status": "RECORDED",
        }
    )
    db.scale_calibrations[cal["id"]] = cal
    recompute_scale_certification(scale)
    return ok_object(cal, 201)


@bp.route("/scale-calibrations", methods=["GET"])
def list_calibrations():
    require_roles(ALL_ROLES)
    filters = {"scale_id": _qs("scale_id"), "status": _qs("status")}
    return list_response(db.scale_calibrations, filters)


@bp.route("/scale-calibrations/<cid>", methods=["GET"])
def get_calibration(cid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.scale_calibrations, cid))


@bp.route("/scale-calibrations/<cid>/void", methods=["POST"])
def void_calibration(cid):
    require_roles(["QuarryAdmin"])
    cal = get_or_404(db.scale_calibrations, cid)
    if cal["status"] != "RECORDED":
        raise err_invalid_state("Only RECORDED calibrations can be voided")
    cal["status"] = "VOIDED"
    touch(cal)
    scale = db.scales[cal["scale_id"]]
    recompute_scale_certification(scale)
    return ok_object(cal)


# ---------------------------------------------------------------------------
# Plant runs
# ---------------------------------------------------------------------------

DESIGN_PCT = {
    "PRIMARY": {"COARSE": Decimal("65.0"), "FINE": Decimal("35.0"), "RIPRAP": Decimal("50.0")},
    "SECONDARY": {"COARSE": Decimal("55.0"), "FINE": Decimal("45.0"), "RIPRAP": Decimal("60.0")},
}


@bp.route("/plant-runs", methods=["POST"])
def create_plant_run():
    require_roles(["PlantOperator"])
    data = body()
    site_id = req_string(data, "site_id")
    muckpile_id = req_string(data, "muckpile_id")
    belt_scale_id = req_string(data, "belt_scale_id")
    circuit = req_enum(data, "circuit_line", {"PRIMARY", "SECONDARY"})
    get_or_404(db.sites, site_id)
    get_or_404(db.muckpiles, muckpile_id)
    get_or_404(db.scales, belt_scale_id)
    run = base_resource()
    run.update(
        {
            "site_id": site_id,
            "muckpile_id": muckpile_id,
            "belt_scale_id": belt_scale_id,
            "circuit_line": circuit,
            "started_at": None,
            "ended_at": None,
            "run_hours": None,
            "input_tons": None,
            "reconciled_input_tons": None,
            "outputs": [],
            "yield_summary": None,
            "production_status": "SCHEDULED",
            "reconciliation_status": "UNRECONCILED",
        }
    )
    db.plant_runs[run["id"]] = run
    return ok_object(run, 201)


@bp.route("/plant-runs", methods=["GET"])
def list_plant_runs():
    require_roles(ALL_ROLES)
    filters = {
        "site_id": _qs("site_id"),
        "muckpile_id": _qs("muckpile_id"),
        "belt_scale_id": _qs("belt_scale_id"),
        "circuit_line": _qs("circuit_line"),
        "production_status": _qs("production_status"),
    }
    return list_response(db.plant_runs, filters)


@bp.route("/plant-runs/<rid>", methods=["GET"])
def get_plant_run(rid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.plant_runs, rid))


@bp.route("/plant-runs/<rid>/start", methods=["POST"])
def start_plant_run(rid):
    require_roles(["PlantOperator"])
    run = get_or_404(db.plant_runs, rid)
    if run["production_status"] != "SCHEDULED":
        raise err_invalid_state("Only SCHEDULED runs can start")
    site = db.sites[run["site_id"]]
    if site["posture"] == "SUSPENDED":
        raise err_site_posture_blocked("Site is SUSPENDED")
    pile = db.muckpiles[run["muckpile_id"]]
    if pile["status"] != "OPEN":
        raise err_muckpile_depleted("Muckpile is not OPEN")
    scale = db.scales[run["belt_scale_id"]]
    if not scale_usable(scale):
        raise err_scale_not_certified("Belt scale not certified or out of date")
    now = logical_now()
    from datetime import timedelta

    for other in db.plant_runs.values():
        if other["id"] == run["id"]:
            continue
        if other["site_id"] != run["site_id"] or other["circuit_line"] != run["circuit_line"]:
            continue
        if other["production_status"] == "RUNNING":
            raise err_circuit_overlap("Another run is RUNNING on this circuit")
        if other["production_status"] == "COMPLETED" and other.get("ended_at"):
            ended = parse_iso_datetime(other["ended_at"])
            if ended + timedelta(minutes=30) > now:
                raise err_circuit_overlap("Circuit in 30-minute cooldown")
    run["production_status"] = "RUNNING"
    run["started_at"] = logical_now_iso()
    touch(run)
    return ok_object(run)


@bp.route("/plant-runs/<rid>/complete", methods=["POST"])
def complete_plant_run(rid):
    require_roles(["PlantOperator"])
    run = get_or_404(db.plant_runs, rid)
    if run["production_status"] != "RUNNING":
        raise err_invalid_state("Only RUNNING runs can complete")
    data = body()
    input_tons = req_positive(data, "input_tons")
    outputs = req_field(data, "outputs")
    if not isinstance(outputs, list):
        raise err_invalid_request("outputs must be an array")
    for row in outputs:
        if not isinstance(row, dict):
            raise err_invalid_request("Each output row must be an object")
        if not isinstance(row.get("stockpile_id"), str):
            raise err_invalid_request("Each output requires stockpile_id")
        if not isinstance(row.get("product_spec_id"), str):
            raise err_invalid_request("Each output requires product_spec_id")
        tons = row.get("tons")
        if isinstance(tons, bool) or not isinstance(tons, (int, float)):
            raise err_invalid_request("Each output requires numeric tons")
    total_out = sum(D(row["tons"]) for row in outputs)
    inp = D(input_tons)
    if inp != 0:
        if abs(total_out - inp) / inp > Decimal("0.03"):
            raise err_output_imbalance("Outputs diverge from input by more than 3%")
    pile = db.muckpiles[run["muckpile_id"]]
    if inp > D(pile["remaining_tons"]):
        raise err_muckpile_depleted("input_tons exceeds remaining muckpile tons")
    # Validate output rows against stockpiles (existence of FK ids first)
    for row in outputs:
        get_or_404(db.stockpiles, row["stockpile_id"])
        get_or_404(db.product_specs, row["product_spec_id"])
    for row in outputs:
        sp = db.stockpiles[row["stockpile_id"]]
        if sp["site_id"] != run["site_id"] or sp["product_spec_id"] != row["product_spec_id"]:
            raise err_invalid_request(
                "Output stockpile must belong to the run's site and match its spec"
            )
        if sp["status"] != "OPEN":
            raise err_stockpile_quarantined("Output stockpile is not OPEN")
        spec = db.product_specs[row["product_spec_id"]]
        if spec["status"] != "ACTIVE":
            raise err_spec_retired("Output spec is RETIRED")
        if D(sp["on_hand_tons"]) + D(row["tons"]) > D(sp["capacity_tons"]):
            raise err_stockpile_capacity_exceeded("Stockpile capacity exceeded")
    # Commit
    now = logical_now()
    run["ended_at"] = logical_now_iso()
    started = parse_iso_datetime(run["started_at"])
    hours = Decimal(str((now - started).total_seconds())) / Decimal(3600)
    run["run_hours"] = to_float(q(hours, 2))
    run["input_tons"] = input_tons
    run["outputs"] = [
        {
            "stockpile_id": row["stockpile_id"],
            "product_spec_id": row["product_spec_id"],
            "tons": row["tons"],
        }
        for row in outputs
    ]
    run["production_status"] = "COMPLETED"
    # Yield summary
    summary = {}
    for row in outputs:
        spec = db.product_specs[row["product_spec_id"]]
        measured = q(Decimal(100) * D(row["tons"]) / inp, 1)
        design = DESIGN_PCT[run["circuit_line"]][spec["category"]]
        variance = q(measured - design, 1)
        summary[spec["spec_code"]] = {
            "measured_pct": to_float(measured),
            "design_pct": to_float(design),
            "variance_pts": to_float(variance),
        }
    run["yield_summary"] = summary
    touch(run)
    # Cascade: muckpile debit
    pile["actual_fed_tons"] = to_float(q(D(pile["actual_fed_tons"]) + inp, 1))
    pile["remaining_tons"] = to_float(q(D(pile["remaining_tons"]) - inp, 1))
    if D(pile["remaining_tons"]) == 0:
        pile["status"] = "DEPLETED"
    touch(pile)
    # Cascade: stockpile credits + allocation sweeps
    credited = []
    for row in outputs:
        sp = db.stockpiles[row["stockpile_id"]]
        sp["on_hand_tons"] = to_float(q(D(sp["on_hand_tons"]) + D(row["tons"]), 3))
        refresh_stockpile(sp)
        touch(sp)
        credited.append(sp)
    for sp in credited:
        allocation_sweep(sp)
    return ok_object(run)


@bp.route("/plant-runs/<rid>/reconcile", methods=["POST"])
def reconcile_plant_run(rid):
    require_roles(["PlantOperator"])
    run = get_or_404(db.plant_runs, rid)
    data = body()
    recon = req_number(data, "reconciled_input_tons")
    if run["production_status"] != "COMPLETED":
        raise err_invalid_state("Only COMPLETED runs can be reconciled")
    if run["reconciliation_status"] == "RECONCILED":
        raise err_invalid_state("Run already RECONCILED")
    inp = D(run["input_tons"])
    within = inp != 0 and abs(D(recon) - inp) / inp <= Decimal("0.02")
    run["reconciled_input_tons"] = recon
    run["reconciliation_status"] = "RECONCILED" if within else "DISPUTED"
    touch(run)
    return ok_object(run)


@bp.route("/plant-runs/<rid>/void", methods=["POST"])
def void_plant_run(rid):
    require_roles(["PlantOperator"])
    run = get_or_404(db.plant_runs, rid)
    if run["production_status"] != "COMPLETED":
        raise err_invalid_state("Only COMPLETED runs can be voided")
    if run["reconciliation_status"] != "UNRECONCILED":
        raise err_invalid_state("Reconciled or disputed runs cannot be voided")
    # Reversal absorbability across all outputs before committing
    for row in run["outputs"]:
        sp = db.stockpiles[row["stockpile_id"]]
        if D(sp["on_hand_tons"]) < D(row["tons"]):
            raise err_reversal_blocked("Credited tons already shipped")
    for row in run["outputs"]:
        sp = db.stockpiles[row["stockpile_id"]]
        sp["on_hand_tons"] = to_float(q(D(sp["on_hand_tons"]) - D(row["tons"]), 3))
        refresh_stockpile(sp)
        touch(sp)
    pile = db.muckpiles[run["muckpile_id"]]
    inp = D(run["input_tons"])
    pile["remaining_tons"] = to_float(q(D(pile["remaining_tons"]) + inp, 1))
    pile["actual_fed_tons"] = to_float(q(D(pile["actual_fed_tons"]) - inp, 1))
    if pile["status"] == "DEPLETED" and D(pile["remaining_tons"]) > 0:
        pile["status"] = "OPEN"
    touch(pile)
    run["production_status"] = "VOIDED"
    touch(run)
    return ok_object(run)


@bp.route("/plant-runs/<rid>/cancel", methods=["POST"])
def cancel_plant_run(rid):
    require_roles(["PlantOperator"])
    run = get_or_404(db.plant_runs, rid)
    if run["production_status"] != "SCHEDULED":
        raise err_invalid_state("Only SCHEDULED runs can be cancelled")
    run["production_status"] = "CANCELLED"
    touch(run)
    return ok_object(run)
