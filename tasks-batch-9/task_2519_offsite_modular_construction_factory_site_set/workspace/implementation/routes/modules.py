"""ModuleUnit endpoints — three parallel state dimensions on one row."""

from datetime import timedelta

from flask import Blueprint

import auth
import calc
import serialize
import services
import validate
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from store import base_row, db, now, sorted_rows, touch

bp = Blueprint("modules", __name__)

PAIR_ROLES = ("SINGLE", "PAIR_A", "PAIR_B")
SCOPE_OWNERS = ("FACTORY", "FIELD", "SHARED")
PRODUCTION_STATUSES = ("PLANNED", "SLOTTED", "IN_LINE", "LINE_COMPLETE")
QC_STATUSES = ("PENDING", "IN_PROGRESS", "HOLD", "CONDITIONAL_RELEASE", "RELEASED")
SITE_STATUSES = ("AT_FACTORY", "LOADED", "IN_TRANSIT", "DELIVERED", "SET", "CONNECTED")
ENVELOPE_CLASSES = ("STANDARD", "OVERWIDTH", "SUPERLOAD")


def _project_and_factory(module):
    project = db.projects.get(module["project_id"])
    factory = services.factory_of_project(project) if project else None
    return project, factory


def _require_line_running(factory):
    # rank 60
    if factory is None or factory["line_state"] != "RUNNING":
        raise ApiError(
            "ERR_FACTORY_LINE_NOT_RUNNING", "the plant's production line is not RUNNING"
        )


def _require_no_hold(module):
    # rank 65
    if module["qc_status"] == "HOLD":
        raise ApiError(
            "ERR_QC_HOLD_BLOCKS_OPERATION",
            "an agency hold blocks every downstream operation on this module",
        )


def _crane_gate(project, module, pick_radius_ft, rigging_weight_lb):
    """Ranks 61 and 62 — chart lookup, wind derate, integer utilisation gate."""
    capacity = calc.chart_capacity(project["crane_capacity_chart"], pick_radius_ft)
    if capacity is None:
        raise ApiError(
            "ERR_PICK_RADIUS_OFF_CHART",
            "no crane chart entry covers a radius of %s ft" % pick_radius_ft,
        )
    capacity = calc.derate(capacity, project["forecast_wind_gust_mph"])
    utilization, infeasible = calc.crane_check(
        capacity, module["gross_weight_lb"], rigging_weight_lb
    )
    if infeasible:
        raise ApiError(
            "ERR_CRANE_CAPACITY_EXCEEDED",
            "the pick exceeds %d%% of derated chart capacity" % calc.MAX_UTILIZATION_PCT,
        )
    return utilization


# ---------------------------------------------------------------------------
# create / read / list
# ---------------------------------------------------------------------------
@bp.post("/modular/modules")
@auth.endpoint("FactoryProductionManager")
def create_module():
    data = validate.body(optional=False)
    project_id = validate.field_id(data, "project_id")
    design_package_id = validate.field_id(data, "design_package_id")
    module_code = validate.field_str(data, "module_code")
    set_sequence_index = validate.field_int(data, "set_sequence_index", minimum=1)
    width_in = validate.field_int(data, "width_in", minimum=1)
    length_in = validate.field_int(data, "length_in", minimum=1)
    height_in = validate.field_int(data, "height_in", minimum=1)
    gross_weight_lb = validate.field_int(data, "gross_weight_lb", minimum=1)
    pair_role = validate.field_enum(
        data, "pair_role", PAIR_ROLES, required=False, default="SINGLE"
    )
    pair_group_code = validate.field_str(data, "pair_group_code", required=False)
    connection_scope_owner = validate.field_enum(
        data, "connection_scope_owner", SCOPE_OWNERS, required=False, default="FIELD"
    )

    # rank 5 — body foreign keys in declared order
    project = services.get_project(project_id)
    package = services.get_package(design_package_id)

    # rank 6 — the plant may only build its own projects
    auth.own_factory_of(project)

    # rank 74 — module_code and set_sequence_index are unique per project
    for sibling in services.modules_of_project(project_id):
        if sibling["module_code"] == module_code:
            raise ApiError(
                "ERR_DUPLICATE_MODULE_CODE",
                "module_code %s already exists on this project" % module_code,
            )
        if sibling["set_sequence_index"] == set_sequence_index:
            raise ApiError(
                "ERR_DUPLICATE_MODULE_CODE",
                "set_sequence_index %s already exists on this project"
                % set_sequence_index,
            )

    # rank 88 — the design package must belong to the same project
    if package["project_id"] != project_id:
        raise ApiError(
            "ERR_CROSS_AGGREGATE_MISMATCH",
            "the design package belongs to a different project",
        )

    row = base_row()
    row.update(
        {
            "project_id": project_id,
            "design_package_id": design_package_id,
            "shipment_id": None,
            "module_code": module_code,
            "pair_role": pair_role,
            "pair_group_code": pair_group_code,
            "set_sequence_index": set_sequence_index,
            "width_in": width_in,
            "length_in": length_in,
            "height_in": height_in,
            "gross_weight_lb": gross_weight_lb,
            "envelope_class": calc.envelope_class(width_in, height_in, gross_weight_lb),
            "production_status": "PLANNED",
            "qc_status": "PENDING",
            "site_status": "AT_FACTORY",
            "station_index": 0,
            "line_slot_start": None,
            "line_slot_end": None,
            "line_slot_minutes": 0,
            "pick_window_start": None,
            "pick_window_end": None,
            "pick_radius_ft": None,
            "rigging_weight_lb": None,
            "crane_utilization_pct": None,
            "connection_scope_owner": connection_scope_owner,
            "set_at": None,
            "connected_at": None,
            "exposure_open_hours": calc.rhu(0, 2),
            "wip_earned_cents": 0,
            "defect_count_factory": 0,
            "defect_count_field": 0,
        }
    )
    db.modules[row["id"]] = row
    return created(serialize.module(row))


@bp.get("/modular/modules/<module_id>")
@auth.endpoint(
    "ProgramAdmin",
    "FactoryProductionManager",
    "SiteSuperintendent",
    "ThirdPartyInspector",
    "TransportCoordinator",
    "LenderDrawAdministrator",
    "WarrantyAdjudicator",
)
def read_module(module_id):
    row = services.get_module(module_id)
    services.refresh_exposure(row)
    return ok(serialize.module(row))


@bp.get("/modular/modules")
@auth.endpoint(
    "ProgramAdmin",
    "FactoryProductionManager",
    "SiteSuperintendent",
    "ThirdPartyInspector",
    "TransportCoordinator",
    "LenderDrawAdministrator",
    "WarrantyAdjudicator",
)
def list_modules():
    project_id = validate.field_str_query("project_id")
    design_package_id = validate.field_str_query("design_package_id")
    shipment_id = validate.field_str_query("shipment_id")
    production_status = validate.enum_query("production_status", PRODUCTION_STATUSES)
    qc_status = validate.enum_query("qc_status", QC_STATUSES)
    site_status = validate.enum_query("site_status", SITE_STATUSES)
    envelope_class = validate.enum_query("envelope_class", ENVELOPE_CLASSES)

    rows = sorted_rows(list(db.modules.values()))
    for row in rows:
        services.refresh_exposure(row)
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if design_package_id is not None:
        rows = [r for r in rows if r["design_package_id"] == design_package_id]
    if shipment_id is not None:
        rows = [r for r in rows if r["shipment_id"] == shipment_id]
    if production_status is not None:
        rows = [r for r in rows if r["production_status"] == production_status]
    if qc_status is not None:
        rows = [r for r in rows if r["qc_status"] == qc_status]
    if site_status is not None:
        rows = [r for r in rows if r["site_status"] == site_status]
    if envelope_class is not None:
        rows = [r for r in rows if r["envelope_class"] == envelope_class]
    page, meta = paginate(rows)
    return ok_list([serialize.module(r) for r in page], meta)


# ---------------------------------------------------------------------------
# production dimension
# ---------------------------------------------------------------------------
@bp.post("/modular/modules/<module_id>/schedule-line-slot")
@auth.endpoint("FactoryProductionManager")
def schedule_line_slot(module_id):
    data = validate.body(optional=False)
    line_slot_start = validate.field_dt(data, "line_slot_start")

    module = services.get_module(module_id)
    project, factory = _project_and_factory(module)
    auth.own_factory_of(project)

    # rank 44
    if module["production_status"] != "PLANNED":
        raise ApiError(
            "ERR_MODULE_NOT_PLANNED",
            "production_status %s cannot claim a takt window"
            % module["production_status"],
        )
    _require_line_running(factory)
    _require_no_hold(module)

    # rank 68 — aggregate interval capacity over the whole plant
    concurrent = 0
    for other in services.modules_of_factory(factory["id"]):
        if other["id"] == module["id"]:
            continue
        if other["production_status"] not in ("SLOTTED", "IN_LINE"):
            continue
        start = other["line_slot_start"]
        end = other["line_slot_end"]
        if start is None or end is None:
            continue
        if start <= line_slot_start < end:  # half-open [start, end)
            concurrent += 1
    if concurrent >= factory["parallel_station_capacity"]:
        raise ApiError(
            "ERR_LINE_CAPACITY_EXCEEDED",
            "the line already holds %d concurrent modules at that instant" % concurrent,
        )

    # rank 76
    if line_slot_start < now():
        raise ApiError(
            "ERR_LINE_SLOT_IN_PAST", "line_slot_start is before the current clock instant"
        )

    # rank 77 — the literal, non-wrapping shift window
    minute_of_day = line_slot_start.hour * 60 + line_slot_start.minute
    shift_start = factory["shift_start_minute_of_day"]
    shift_end = shift_start + factory["shift_minutes_per_day"]
    if not (shift_start <= minute_of_day < shift_end):
        raise ApiError(
            "ERR_LINE_SLOT_OUTSIDE_SHIFT",
            "line_slot_start is outside the plant's productive shift window",
        )

    # rank 83
    if services.live_plan_review(project["id"]) is None:
        raise ApiError(
            "ERR_PLAN_REVIEW_PREREQUISITE",
            "the state modular program plan review is not approved and live",
        )

    takt = calc.effective_takt(factory["takt_minutes"], concurrent)
    minutes = factory["station_count"] * takt
    module["production_status"] = "SLOTTED"
    module["line_slot_start"] = line_slot_start
    module["line_slot_minutes"] = minutes
    module["line_slot_end"] = line_slot_start + timedelta(minutes=minutes)
    factory["committed_line_minutes"] += minutes
    touch(factory)
    services.recompute_wip(module)
    services.refresh_project(project)
    touch(module)
    return ok(serialize.module(module))


@bp.post("/modular/modules/<module_id>/release-line-slot")
@auth.endpoint("FactoryProductionManager")
def release_line_slot(module_id):
    data = validate.body()
    validate.field_str(data, "reason", required=False, allow_blank=True)

    module = services.get_module(module_id)
    project, factory = _project_and_factory(module)
    auth.own_factory_of(project)

    # rank 45
    if module["production_status"] != "SLOTTED":
        raise ApiError(
            "ERR_MODULE_NOT_SLOTTED",
            "production_status %s holds no takt window" % module["production_status"],
        )

    if services.release_slot(module, factory):
        touch(factory)
    module["production_status"] = "PLANNED"
    module["line_slot_start"] = None
    module["line_slot_end"] = None
    module["line_slot_minutes"] = 0
    services.recompute_wip(module)
    touch(module)
    services.refresh_project(project)
    touch(project)
    return ok(serialize.module(module))


@bp.post("/modular/modules/<module_id>/advance-station")
@auth.endpoint("FactoryProductionManager")
def advance_station(module_id):
    data = validate.body()
    stations_advanced = validate.field_int(
        data, "stations_advanced", required=False, default=1, minimum=1
    )

    module = services.get_module(module_id)
    project, factory = _project_and_factory(module)
    auth.own_factory_of(project)

    # rank 46
    if module["production_status"] not in ("SLOTTED", "IN_LINE"):
        raise ApiError(
            "ERR_MODULE_NOT_ON_LINE",
            "production_status %s is not on the line" % module["production_status"],
        )
    _require_line_running(factory)
    _require_no_hold(module)

    came_from_slotted = module["production_status"] == "SLOTTED"
    station_count = factory["station_count"]
    target = module["station_index"] + stations_advanced

    terminating = target >= station_count
    if terminating:
        module["station_index"] = station_count
        module["production_status"] = "LINE_COMPLETE"
        # the line is released; the [start, end) interval stays on the row as history
        if services.release_slot(module, factory):
            touch(factory)
    else:
        module["station_index"] = target
        module["production_status"] = "IN_LINE"

    services.recompute_wip(module)
    # only an intermediate or terminating advance refreshes the DRAFT draw basis
    if terminating or not came_from_slotted:
        services.recompute_draft_draws(project)
    touch(module)
    services.refresh_project(project)
    if came_from_slotted:
        touch(project)
    return ok(serialize.module(module))


# ---------------------------------------------------------------------------
# site dimension
# ---------------------------------------------------------------------------
@bp.post("/modular/modules/<module_id>/schedule-pick")
@auth.endpoint("SiteSuperintendent")
def schedule_pick(module_id):
    data = validate.body(optional=False)
    pick_window_start = validate.field_dt(data, "pick_window_start")
    pick_window_end = validate.field_dt(data, "pick_window_end")
    pick_radius_ft = validate.field_int(data, "pick_radius_ft", minimum=0)
    rigging_weight_lb = validate.field_int(data, "rigging_weight_lb", minimum=0)

    module = services.get_module(module_id)
    project = db.projects.get(module["project_id"])
    auth.own_project(project)

    # rank 47
    if module["site_status"] not in ("AT_FACTORY", "LOADED", "IN_TRANSIT", "DELIVERED"):
        raise ApiError(
            "ERR_MODULE_NOT_READY_TO_SET",
            "site_status %s cannot be scheduled for a pick" % module["site_status"],
        )

    # ranks 61 and 62
    utilization = _crane_gate(project, module, pick_radius_ft, rigging_weight_lb)

    # rank 69 — crane window exclusivity; touching endpoints count as overlap
    buffer = timedelta(minutes=project["crane_rigging_buffer_minutes"])
    requested_start = pick_window_start - buffer
    requested_end = pick_window_end + buffer
    for other in services.modules_of_project(project["id"]):
        if other["id"] == module["id"]:
            continue
        if other["site_status"] == "CONNECTED":
            continue
        if other["pick_window_start"] is None or other["pick_window_end"] is None:
            continue
        other_start = other["pick_window_start"] - buffer
        other_end = other["pick_window_end"] + buffer
        if requested_start <= other_end and other_start <= requested_end:
            raise ApiError(
                "ERR_CRANE_WINDOW_CONFLICT",
                "the buffered pick window overlaps module %s" % other["module_code"],
            )

    # rank 78
    if pick_window_end <= pick_window_start or pick_window_start < now():
        raise ApiError(
            "ERR_PICK_WINDOW_INVALID",
            "the pick window must be non-empty and start at or after the clock instant",
        )

    module["pick_window_start"] = pick_window_start
    module["pick_window_end"] = pick_window_end
    module["pick_radius_ft"] = pick_radius_ft
    module["rigging_weight_lb"] = rigging_weight_lb
    module["crane_utilization_pct"] = utilization
    touch(module)
    return ok(serialize.module(module))


@bp.post("/modular/modules/<module_id>/execute-set")
@auth.endpoint("SiteSuperintendent")
def execute_set(module_id):
    data = validate.body()
    validate.field_str(data, "set_note", required=False, allow_blank=True)

    module = services.get_module(module_id)
    project = db.projects.get(module["project_id"])
    auth.own_project(project)

    # rank 47
    if module["site_status"] != "DELIVERED":
        raise ApiError(
            "ERR_MODULE_NOT_READY_TO_SET",
            "site_status %s is not DELIVERED" % module["site_status"],
        )

    # ranks 61 and 62 — re-checked against the CURRENT forecast
    utilization = _crane_gate(
        project, module, module["pick_radius_ft"], module["rigging_weight_lb"] or 0
    )

    # rank 63 — no already-open module may be over its exposure limit
    for other in services.modules_of_project(project["id"]):
        if other["site_status"] != "SET" or other["connected_at"] is not None:
            continue
        if calc.dec(services.refresh_exposure(other)) > calc.dec(
            project["weather_exposure_limit_hours"]
        ):
            raise ApiError(
                "ERR_WEATHER_EXPOSURE_LIMIT",
                "module %s has been open past the exposure limit" % other["module_code"],
            )

    # rank 64 — the dual permit posture
    services.refresh_project(project)
    if project["permit_posture"] not in ("SET_CLEARED", "OCCUPANCY_CLEARED"):
        raise ApiError(
            "ERR_SET_NOT_PERMITTED",
            "permit_posture %s does not release the set" % project["permit_posture"],
        )

    _require_no_hold(module)

    # rank 67 — set-order discipline
    policy = project["set_sequence_policy"]
    if module["set_sequence_index"] != project["modules_set_count"] + 1:
        raise ApiError(
            "ERR_SET_SEQUENCE_VIOLATION",
            "set_sequence_index %s is not next in the crane order"
            % module["set_sequence_index"],
        )
    if policy == "PAIRED_FIRST" and module["pair_role"] == "PAIR_B":
        sibling_set = False
        for other in services.modules_of_project(project["id"]):
            if other["id"] == module["id"]:
                continue
            if other["pair_group_code"] != module["pair_group_code"]:
                continue
            if other["pair_role"] == "PAIR_A" and other["site_status"] in (
                "SET",
                "CONNECTED",
            ):
                sibling_set = True
        if not sibling_set:
            raise ApiError(
                "ERR_SET_SEQUENCE_VIOLATION",
                "PAIR_B may not be set before its PAIR_A sibling",
            )

    # rank 85 — the module must be built to the pinned revision
    plan_review = services.live_plan_review(project["id"])
    pinned = plan_review["pinned_package_id"] if plan_review else None
    if module["design_package_id"] != pinned:
        raise ApiError(
            "ERR_PINNED_PACKAGE_MISMATCH",
            "the module was detailed against a revision that is not the pinned one",
        )

    module["site_status"] = "SET"
    module["set_at"] = now()
    module["crane_utilization_pct"] = utilization
    services.refresh_exposure(module)
    touch(module)
    services.refresh_project(project)
    touch(project)
    return ok(serialize.module(module))


@bp.post("/modular/modules/<module_id>/close-connections")
@auth.endpoint("SiteSuperintendent")
def close_connections(module_id):
    data = validate.body(optional=False)
    field_scope_signed_off = validate.field_bool(data, "field_scope_signed_off")
    connection_scope_owner = validate.field_enum(
        data, "connection_scope_owner", SCOPE_OWNERS, required=False
    )
    validate.field_str(data, "connected_note", required=False, allow_blank=True)

    module = services.get_module(module_id)
    project = db.projects.get(module["project_id"])
    auth.own_project(project)

    # rank 48
    if module["site_status"] != "SET":
        raise ApiError(
            "ERR_MODULE_NOT_SET",
            "site_status %s is not SET" % module["site_status"],
        )

    # rank 63 — the disjunction: still inside the limit OR the sky is dry
    exposure = calc.dec(services.refresh_exposure(module))
    limit = calc.dec(project["weather_exposure_limit_hours"])
    precip = calc.dec(project["forecast_precip_probability_pct"])
    if not (exposure < limit or precip < calc.dec(calc.WEATHER_PRECIP_RELIEF_PCT)):
        raise ApiError(
            "ERR_WEATHER_EXPOSURE_LIMIT",
            "the module has been open past its exposure limit under wet weather",
        )

    _require_no_hold(module)

    # rank 67 — a mated pair is closed in only once both halves are landed
    if module["pair_role"] != "SINGLE":
        for other in services.modules_of_project(project["id"]):
            if other["id"] == module["id"]:
                continue
            if other["pair_group_code"] != module["pair_group_code"]:
                continue
            if other["site_status"] not in ("SET", "CONNECTED"):
                raise ApiError(
                    "ERR_SET_SEQUENCE_VIOLATION",
                    "the mated module %s is not landed yet" % other["module_code"],
                )

    # rank 93
    if field_scope_signed_off is not True:
        raise ApiError(
            "ERR_FIELD_SCOPE_NOT_SIGNED_OFF",
            "the adjoining site-built scope has not been signed off",
        )

    if connection_scope_owner is not None:
        module["connection_scope_owner"] = connection_scope_owner
    module["site_status"] = "CONNECTED"
    module["connected_at"] = now()
    services.refresh_exposure(module)
    touch(module)

    # the warranty allocation on this module is frozen
    for claim in services.claims_of_module(module["id"]):
        if claim["status"] == "ADJUDICATED":
            claim["status"] = "CLOSED"
            touch(claim)

    services.refresh_project(project)
    touch(project)
    return ok(serialize.module(module))
