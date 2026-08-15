"""Seasonal windows and the build projection (PRD §3.4) plus post-season
markdown (PRD §3.8)."""
from flask import Blueprint, request

from db import new_id, now, parse_dt, stamp_new, store, touch
from errors import ApiError
from middleware import ALL_ROLES, auth, body, is_int, is_num, paginate, require_fields
from response import success_list, success_object
from serializers import window_json
from services.pricing import markdown_unit_price

windows_bp = Blueprint("windows", __name__)


def get_window_or_404(wid):
    w = store.seasonal_windows.get(wid)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", "Seasonal window not found: %s" % wid)
    return w


@windows_bp.route("/seasonal-windows", methods=["POST"])
def create_window():
    auth(("ProductionPlanner",))
    b = body()
    # Request shape (ERR_INVALID_REQUEST).
    require_fields(b, ["season_code", "build_start", "build_end", "ship_start", "ship_end",
                       "target_units", "markdown_tiers"])
    if not isinstance(b["season_code"], str) or not b["season_code"]:
        raise ApiError("ERR_INVALID_REQUEST", "season_code is required and must be a non-empty string.")
    dates = {}
    for f in ("build_start", "build_end", "ship_start", "ship_end"):
        d = parse_dt(b[f])
        if d is None:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 datetime." % f)
        dates[f] = d
    if not is_int(b["target_units"]) or b["target_units"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "target_units must be an integer > 0.")
    tiers = b["markdown_tiers"]
    if not isinstance(tiers, list):
        raise ApiError("ERR_INVALID_REQUEST", "markdown_tiers must be an array.")
    prev_offset = None
    for t in tiers:
        if not isinstance(t, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each markdown tier must be an object.")
        dom = t.get("day_offset_min")
        dp = t.get("discount_pct")
        if not is_int(dom) or dom < 0:
            raise ApiError("ERR_INVALID_REQUEST", "day_offset_min must be an integer >= 0.")
        if not is_num(dp) or not (0 <= dp < 1):
            raise ApiError("ERR_INVALID_REQUEST", "discount_pct must be a number in [0, 1).")
        # Tiers must be sorted by ascending day_offset_min with no duplicates.
        if prev_offset is not None and dom <= prev_offset:
            raise ApiError("ERR_INVALID_REQUEST",
                           "markdown_tiers must be sorted by ascending day_offset_min with unique offsets.")
        prev_offset = dom
    # Structural (PRD §3.4 order): internal date order first ...
    if not (dates["build_start"] <= dates["build_end"] <= dates["ship_start"] <= dates["ship_end"]):
        raise ApiError("ERR_WINDOW_DATE_ORDER",
                       "Window dates must satisfy build_start <= build_end <= ship_start <= ship_end.")
    # ... then the closed-interval ship-overlap check per season_code.
    for w in store.seasonal_windows.values():
        if w["season_code"] != b["season_code"]:
            continue
        # Closed interval: touching endpoints count as overlap.
        if dates["ship_start"] <= w["ship_end"] and w["ship_start"] <= dates["ship_end"]:
            raise ApiError("ERR_WINDOW_OVERLAP",
                           "The ship interval intersects an existing window with the same season_code.")
    w = {
        "id": new_id(),
        "season_code": b["season_code"],
        "build_start": dates["build_start"],
        "build_end": dates["build_end"],
        "ship_start": dates["ship_start"],
        "ship_end": dates["ship_end"],
        "target_units": b["target_units"],
        "markdown_tiers": [{"day_offset_min": t["day_offset_min"], "discount_pct": t["discount_pct"]}
                           for t in tiers],
        "confirmed_build_units": 0,
        "projected_build_units": 0,
        "coverage_pct": 0.0,
        "shortfall": True,
        "status": "DRAFT",
    }
    stamp_new(w)
    store.seasonal_windows[w["id"]] = w
    return success_object(window_json(w), 201)


@windows_bp.route("/seasonal-windows", methods=["GET"])
def list_windows():
    auth(ALL_ROLES)
    items = list(store.seasonal_windows.values())
    f = request.args.get("status")
    if f is not None:
        items = [w for w in items if w["status"] == f]
    f = request.args.get("season_code")
    if f is not None:
        items = [w for w in items if w["season_code"] == f]
    items.sort(key=lambda w: w["created_at"])
    page, meta = paginate(items)
    return success_list([window_json(w) for w in page], meta)


@windows_bp.route("/seasonal-windows/<wid>", methods=["GET"])
def get_window(wid):
    auth(ALL_ROLES)
    return success_object(window_json(get_window_or_404(wid)))


@windows_bp.route("/seasonal-windows/<wid>/publish", methods=["POST"])
def publish_window(wid):
    auth(("PlantManager",))
    w = get_window_or_404(wid)
    if w["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT window can be published.")
    w["status"] = "PUBLISHED"
    touch(w)
    return success_object(window_json(w))


@windows_bp.route("/seasonal-windows/<wid>/close", methods=["POST"])
def close_window(wid):
    auth(("PlantManager",))
    w = get_window_or_404(wid)
    if w["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", "Only a PUBLISHED window can be closed.")
    # Close requires the logical clock's date to be strictly after ship_end.
    if now().date() <= w["ship_end"].date():
        raise ApiError("ERR_PREMATURE_CLOSE",
                       "The window cannot be closed until the clock is strictly past ship_end.")
    w["status"] = "CLOSED"
    touch(w)
    return success_object(window_json(w))


@windows_bp.route("/seasonal-windows/<wid>/apply-markdown", methods=["POST"])
def apply_markdown(wid):
    auth(("PlantManager",))
    w = get_window_or_404(wid)
    if w["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "Markdown can only be applied to a CLOSED window.")
    # Whole-day difference between the logical clock's UTC date and ship_end.
    days_after = (now().date() - w["ship_end"].date()).days
    # The applicable discount is the largest among tiers whose day_offset_min
    # has been reached; zero when no tier qualifies.
    discount = 0
    for t in w["markdown_tiers"]:
        if days_after >= t["day_offset_min"] and t["discount_pct"] > discount:
            discount = t["discount_pct"]
    updated = 0
    for lot in store.lots.values():
        run = store.production_runs.get(lot["run_id"])
        if run is None or run["window_id"] != w["id"]:
            continue
        if lot["status"] != "ACTIVE":
            continue
        product = store.products[lot["product_id"]]
        if product["product_type"] != "SEASONAL":
            continue
        lot["unit_price_cents"] = markdown_unit_price(product["base_price_cents"], discount)
        touch(lot)
        updated += 1
    return success_object({
        "updated_lot_count": updated,
        "discount_pct": float(discount),
        "days_after_season_end": days_after,
    })
