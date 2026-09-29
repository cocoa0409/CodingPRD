"""Site surface: zones, phased cutover windows and commissioning ramp steps."""

from flask import Blueprint

from auth import ALL_ROLES, authenticate
from errors import ApiError, bad_request
from lookups import get_lot, get_project, get_window, get_zone
from response import list_response, object_response
from serializers import commissioning_ramp_out, cutover_window_out, site_zone_out
from services import calculations as calc
from services.scheduling import protected_shift_collision, zone_window_overlap
from store import (
    iso,
    new_record,
    now,
    ordered,
    store,
    touch,
    zones_of,
)
from validate import (
    body,
    pagination,
    paginate,
    query_filter,
    req_datetime,
    req_int,
    req_int_enum,
    req_str,
)

bp = Blueprint("site", __name__)


@bp.post("/site-zones")
def create_site_zone():
    authenticate(("SiteManager",))
    data = body()

    project_id = req_str(data, "project_id")
    zone_code = req_str(data, "zone_code")
    throughput_share_bps = req_int(data, "throughput_share_bps", minimum=1, maximum=10000)
    shift_start = req_int(data, "protected_shift_start_minute", minimum=0, maximum=1439)
    shift_end = req_int(data, "protected_shift_end_minute", minimum=1, maximum=1440)
    if shift_end <= shift_start:
        raise bad_request(
            "Field 'protected_shift_end_minute' must be strictly greater than "
            "'protected_shift_start_minute'."
        )
    buffer_minutes = req_int(data, "buffer_minutes", minimum=0)

    project = get_project(project_id)

    zone = new_record()
    zone.update(
        {
            "project_id": project["id"],
            "zone_code": zone_code,
            "throughput_share_bps": throughput_share_bps,
            "protected_shift_start_minute": shift_start,
            "protected_shift_end_minute": shift_end,
            "buffer_minutes": buffer_minutes,
            "ops_status": "LIVE_LEGACY",
        }
    )
    store.site_zones[zone["id"]] = zone
    touch(project)
    return object_response(site_zone_out(zone), 201)


@bp.post("/cutover-windows")
def create_cutover_window():
    authenticate(("SiteManager",))
    data = body()

    project_id = req_str(data, "project_id")
    site_zone_id = req_str(data, "site_zone_id")
    fabrication_lot_id = req_str(data, "fabrication_lot_id")
    start_raw, start_dt = req_datetime(data, "start_utc")
    end_raw, end_dt = req_datetime(data, "end_utc")
    if end_dt <= start_dt:
        raise bad_request("Field 'end_utc' must be strictly after 'start_utc'.")

    project = get_project(project_id)
    zone = get_zone(site_zone_id)
    lot = get_lot(fabrication_lot_id)

    # Band 11 - the customer's continuing operations.
    if protected_shift_collision(zone, start_dt, end_dt):
        raise ApiError(
            "ERR_PROTECTED_SHIFT_COLLISION",
            "The requested window intersects the protected operating shift of zone %s."
            % zone["zone_code"],
        )

    # Band 12 - buffered separation between live windows of the same zone.
    if zone_window_overlap(zone, start_dt, end_dt):
        raise ApiError(
            "ERR_ZONE_WINDOW_OVERLAP",
            "The requested window collides with a live window on zone %s once both sides are "
            "padded by %d buffer minutes." % (zone["zone_code"], zone["buffer_minutes"]),
        )

    # Band 13 - cross-aggregate coherence.
    if zone["project_id"] != project["id"] or lot["project_id"] != project["id"]:
        raise ApiError(
            "ERR_CROSS_PROJECT_REFERENCE",
            "The zone and the lot must both belong to the project the request names.",
        )

    window = new_record()
    window.update(
        {
            "project_id": project["id"],
            "site_zone_id": zone["id"],
            "fabrication_lot_id": lot["id"],
            "start_utc": start_raw,
            "end_utc": end_raw,
            "_start_dt": start_dt,
            "_end_dt": end_dt,
            "status": "SCHEDULED",
            "abort_reason": None,
            "started_at": None,
            "closed_at": None,
        }
    )
    store.cutover_windows[window["id"]] = window
    touch(project)
    return object_response(cutover_window_out(window), 201)


@bp.get("/cutover-windows/<window_id>")
def read_cutover_window(window_id):
    authenticate(ALL_ROLES)
    window = get_window(window_id)
    return object_response(cutover_window_out(window))


@bp.get("/cutover-windows")
def list_cutover_windows():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    project_id = query_filter("project_id")
    site_zone_id = query_filter("site_zone_id")
    fabrication_lot_id = query_filter("fabrication_lot_id")
    status = query_filter("status")

    records = ordered(list(store.cutover_windows.values()))
    if project_id is not None:
        records = [r for r in records if r["project_id"] == project_id]
    if site_zone_id is not None:
        records = [r for r in records if r["site_zone_id"] == site_zone_id]
    if fabrication_lot_id is not None:
        records = [r for r in records if r["fabrication_lot_id"] == fabrication_lot_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return list_response([cutover_window_out(r) for r in page], limit, offset, total)


def _require_in_progress(window):
    if window["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_WINDOW_INVALID_STATE",
            "The window must be IN_PROGRESS; it is %s." % window["status"],
        )


@bp.post("/cutover-windows/<window_id>/start")
def start_cutover_window(window_id):
    authenticate(("SiteManager",))
    window = get_window(window_id)

    # Band 8 - the window's own state comes before every relative's state.
    if window["status"] == "BLOCKED_STALE_DESIGN":
        raise ApiError(
            "ERR_WINDOW_BLOCKED_STALE_DESIGN",
            "The window is blocked because the design baseline moved; re-simulate first.",
        )
    if window["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_WINDOW_INVALID_STATE",
            "The window must be SCHEDULED; it is %s." % window["status"],
        )

    project = get_project(window["project_id"])
    lot = get_lot(window["fabrication_lot_id"])
    zone = get_zone(window["site_zone_id"])

    if lot["status"] != "FAT_PASSED":
        raise ApiError(
            "ERR_LOT_NOT_FAT_PASSED",
            "The installed lot must have passed factory acceptance; it is %s." % lot["status"],
        )
    if zone["ops_status"] != "LIVE_LEGACY":
        raise ApiError(
            "ERR_ZONE_NOT_READY",
            "The zone must still be on the legacy system; it is %s." % zone["ops_status"],
        )

    instant = now()
    if not (window["_start_dt"] <= instant < window["_end_dt"]):
        raise ApiError(
            "ERR_WINDOW_NOT_DUE",
            "The logical clock is outside the window's appointment interval.",
        )

    # Band 14 - the facility must be fully partitioned first.
    share_total = sum(z["throughput_share_bps"] for z in zones_of(project["id"]))
    if share_total != 10000:
        raise ApiError(
            "ERR_ZONE_SHARE_INCOMPLETE",
            "Site zone shares total %d basis points; exactly 10000 is required." % share_total,
        )

    window["status"] = "IN_PROGRESS"
    window["started_at"] = iso(instant)
    touch(window)

    zone["ops_status"] = "CUTOVER_IN_PROGRESS"
    touch(zone)

    share = zone["throughput_share_bps"]
    project["legacy_share_bps"] -= share
    project["in_transition_share_bps"] += share
    if project["delivery_status"] == "IN_FABRICATION":
        project["delivery_status"] = "CUTOVER"
    touch(project)

    return object_response(cutover_window_out(window))


@bp.post("/cutover-windows/<window_id>/complete")
def complete_cutover_window(window_id):
    authenticate(("SiteManager",))
    window = get_window(window_id)
    _require_in_progress(window)

    project = get_project(window["project_id"])
    zone = get_zone(window["site_zone_id"])
    lot = get_lot(window["fabrication_lot_id"])

    window["status"] = "COMPLETED"
    window["closed_at"] = iso(now())
    touch(window)

    zone["ops_status"] = "CUTOVER_COMPLETE"
    touch(zone)

    share = zone["throughput_share_bps"]
    project["in_transition_share_bps"] -= share
    project["cutover_share_bps"] += share

    if lot["status"] == "FAT_PASSED":
        lot["status"] = "INSTALLED"
        touch(lot)

    zones = zones_of(project["id"])
    if (
        project["delivery_status"] == "CUTOVER"
        and zones
        and all(z["ops_status"] == "CUTOVER_COMPLETE" for z in zones)
    ):
        project["delivery_status"] = "COMMISSIONING"
    touch(project)

    return object_response(cutover_window_out(window))


@bp.post("/cutover-windows/<window_id>/abort")
def abort_cutover_window(window_id):
    authenticate(("SiteManager",))
    window = get_window(window_id)
    data = body()
    abort_reason = req_str(data, "abort_reason")

    _require_in_progress(window)

    project = get_project(window["project_id"])
    zone = get_zone(window["site_zone_id"])

    window["status"] = "ABORTED"
    window["abort_reason"] = abort_reason
    window["closed_at"] = iso(now())
    touch(window)

    zone["ops_status"] = "LIVE_LEGACY"
    touch(zone)

    share = zone["throughput_share_bps"]
    project["in_transition_share_bps"] -= share
    project["legacy_share_bps"] += share
    touch(project)

    return object_response(cutover_window_out(window))


@bp.post("/commissioning-ramps")
def create_commissioning_ramp():
    user_id, _role = authenticate(("SiteManager",))
    data = body()

    project_id = req_str(data, "project_id")
    step_pct = req_int_enum(data, "step_pct", calc.RAMP_STEPS)
    measured_cph = req_int(data, "measured_cph", minimum=0)
    sustained_minutes = req_int(data, "sustained_minutes", minimum=0)

    project = get_project(project_id)

    # Band 8 - state admissibility, then the ramp's own sequencing rule.
    if project["delivery_status"] != "COMMISSIONING":
        raise ApiError(
            "ERR_PROJECT_NOT_COMMISSIONING",
            "Ramp steps may only be recorded while delivery_status is COMMISSIONING.",
        )
    if not calc.ramp_sequence_satisfied(project, step_pct):
        raise ApiError(
            "ERR_RAMP_SEQUENCE_VIOLATION",
            "Every lower ramp step must already carry a PASS verdict before step %d." % step_pct,
        )

    target, minimum, verdict = calc.ramp_evaluation(
        project, step_pct, measured_cph, sustained_minutes
    )

    ramp = new_record(versioned=False)
    ramp.update(
        {
            "project_id": project["id"],
            "step_pct": step_pct,
            "measured_cph": measured_cph,
            "sustained_minutes": sustained_minutes,
            "target_cph": target,
            "min_sustained_minutes": minimum,
            "verdict": verdict,
            "recorded_by_user_id": user_id,
        }
    )
    store.commissioning_ramps[ramp["id"]] = ramp

    project["acceptance_ready"] = calc.acceptance_ready(project)
    touch(project)

    return object_response(commissioning_ramp_out(ramp), 201)
