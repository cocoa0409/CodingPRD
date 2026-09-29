from decimal import Decimal

from flask import Blueprint

import auth
import common
import response
import shape
import store
from errors import err
from shape import D, q

bp = Blueprint("rolls", __name__)
ZERO = Decimal("0")
WRAP_SPECS = ["KRAFT_ONLY", "POLY_COATED", "STRETCH_HOOD"]


def _machine_of(run):
    return store.get("paper_machines", run["machine_id"])


@bp.post("/production-runs/<rid>/roll-sets")
def create_roll_set(rid):
    auth.require_roles("MachineOperator")
    run = common.need("production_runs", rid, "ERR_RUN_NOT_FOUND")
    data = shape.body()
    shape.reject_unexpected_version(data)
    slit = shape.get_int(data, "slit_width_mm", minimum=400, maximum=2800)
    diameter = shape.get_int(data, "diameter_mm", minimum=800, maximum=1800)
    roll_count = shape.get_int(data, "roll_count", minimum=1, maximum=40)
    net_tons = shape.get_num(data, "net_tons", exclusive_min=0, places=3)
    wrap = shape.get_enum(data, "wrap_spec", WRAP_SPECS, required=False, default=None)
    if run["run_status"] != "RUNNING":
        raise err("ERR_RUN_INVALID_STATE", "run is not RUNNING")
    machine = _machine_of(run)
    if slit > int(machine["wire_width_mm"]):
        raise err("ERR_WIDTH_EXCEEDS_DECKLE", "slit width exceeds the machine's wire width")
    row = {
        "production_run_id": run["id"],
        "slit_width_mm": slit,
        "diameter_mm": diameter,
        "roll_count": roll_count,
        "net_tons": net_tons,
        "wrap_spec": wrap,
        "allocated_order_id": None,
        "rewind_count": 0,
        "quarantine_reason": None,
        "status": "WOUND",
    }
    store.insert("roll_sets", row)
    common.recompute_run_produced(run)
    store.touch("production_runs", run)
    return response.ok(common.view(row), 201)


@bp.get("/roll-sets/<sid>")
def get_roll_set(sid):
    auth.require_roles("MachineOperator", "MillPlanner", "QualityLab", "Customer")
    return response.ok(common.view(common.need("roll_sets", sid, "ERR_ROLL_SET_NOT_FOUND")))


@bp.get("/roll-sets")
def list_roll_sets():
    auth.require_roles("MachineOperator", "MillPlanner", "QualityLab", "Customer")
    limit, offset = shape.pagination()
    rows = common.filtered("roll_sets", {
        "production_run_id": "production_run_id",
        "allocated_order_id": "allocated_order_id",
        "status": "status",
    })
    if auth.role() == "Customer":
        mine = {o["id"] for o in store.all_rows("customer_orders")
                if o["customer_id"] == auth.user_id()}
        rows = [r for r in rows if r.get("allocated_order_id") in mine]
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


def _need_set(sid):
    return common.need("roll_sets", sid, "ERR_ROLL_SET_NOT_FOUND")


@bp.post("/roll-sets/<sid>/wrap")
def wrap_set(sid):
    auth.require_roles("MachineOperator")
    rs = _need_set(sid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    wrap = shape.get_enum(data, "wrap_spec", WRAP_SPECS)
    if rs["status"] != "WOUND":
        raise err("ERR_ROLL_SET_INVALID_STATE", "roll set is not WOUND")
    run = store.get("production_runs", rs["production_run_id"])
    if run["run_status"] != "COMPLETED":
        raise err("ERR_RUN_NOT_CERTIFIED", "producing run is not COMPLETED")
    machine = _machine_of(run)
    if int(rs["slit_width_mm"]) > int(machine["wire_width_mm"]):
        raise err("ERR_WIDTH_EXCEEDS_DECKLE", "slit width exceeds the machine's wire width")
    rs["wrap_spec"] = wrap
    rs["status"] = "WRAPPED"
    store.touch("roll_sets", rs)
    return response.ok(common.view(rs))


@bp.post("/roll-sets/<sid>/allocate")
def allocate_set(sid):
    auth.require_roles("MillPlanner")
    rs = _need_set(sid)
    data = shape.body()
    order_id = shape.get_str(data, "order_id")
    expected = shape.get_version(data, "expected_order_version")
    order = store.get("customer_orders", order_id)
    if order is None:
        raise err("ERR_LINK_TARGET_NOT_FOUND", "order_id does not resolve")
    if rs["status"] != "WRAPPED":
        raise err("ERR_ROLL_SET_INVALID_STATE", "roll set is not WRAPPED")
    run = store.get("production_runs", rs["production_run_id"])
    if run["quality_status"] != "CERTIFIED":
        raise err("ERR_RUN_NOT_CERTIFIED", "producing run quality axis is not CERTIFIED")
    if order["status"] not in ("IN_PRODUCTION", "PARTIALLY_ALLOCATED"):
        raise err("ERR_ORDER_INVALID_STATE", "order is not IN_PRODUCTION or PARTIALLY_ALLOCATED")
    if order["product_code"] != run["product_code"]:
        raise err("ERR_PRODUCT_MISMATCH", "order product differs from the run's product")
    if expected != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION", "expected_order_version is stale")
    if int(rs["slit_width_mm"]) != int(order["roll_width_mm"]):
        raise err("ERR_ROLL_SPEC_MISMATCH", "slit width does not equal the order's roll width")
    if int(rs["diameter_mm"]) > int(order["roll_diameter_mm"]):
        raise err("ERR_ROLL_SPEC_MISMATCH", "diameter exceeds the order's roll diameter")
    if rs["wrap_spec"] != order["wrap_spec"]:
        raise err("ERR_ROLL_SPEC_MISMATCH", "wrap spec does not match the order")
    rs["allocated_order_id"] = order["id"]
    rs["status"] = "ALLOCATED"
    store.touch("roll_sets", rs)
    common.advance_order_on_allocation(order)
    return response.ok(common.view(rs))


@bp.post("/roll-sets/<sid>/quarantine")
def quarantine_set(sid):
    auth.require_roles("QualityLab")
    rs = _need_set(sid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    reason = shape.get_enum(data, "quarantine_reason",
                            ["SPEC_MISMATCH", "RUN_HELD", "PERMIT_EXCEEDANCE"])
    if rs["status"] not in ("WOUND", "WRAPPED"):
        raise err("ERR_ROLL_SET_INVALID_STATE", "roll set is not WOUND or WRAPPED")
    rs["status"] = "QUARANTINED"
    rs["quarantine_reason"] = reason
    store.touch("roll_sets", rs)
    run = store.get("production_runs", rs["production_run_id"])
    if run is not None:
        common.recompute_run_produced(run)
        store.touch("production_runs", run)
    return response.ok(common.view(rs))


@bp.post("/roll-sets/<sid>/rewind")
def rewind_set(sid):
    auth.require_roles("MachineOperator")
    rs = _need_set(sid)
    shape.reject_unexpected_version(shape.body())
    if rs["status"] != "QUARANTINED":
        raise err("ERR_ROLL_SET_INVALID_STATE", "roll set is not QUARANTINED")
    if int(rs["rewind_count"]) >= 2:
        raise err("ERR_REWIND_LIMIT", "rewind limit reached")
    rs["rewind_count"] = int(rs["rewind_count"]) + 1
    rs["status"] = "REWOUND"
    store.touch("roll_sets", rs)
    run = store.get("production_runs", rs["production_run_id"])
    if run is not None:
        common.recompute_run_produced(run)
        store.touch("production_runs", run)
    return response.ok(common.view(rs))


@bp.post("/roll-sets/<sid>/rewind-complete")
def rewind_complete(sid):
    auth.require_roles("MachineOperator")
    rs = _need_set(sid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    slit = shape.get_int(data, "slit_width_mm", minimum=400, maximum=2800)
    diameter = shape.get_int(data, "diameter_mm", minimum=800, maximum=1800)
    roll_count = shape.get_int(data, "roll_count", minimum=1, maximum=40)
    net_tons = shape.get_num(data, "net_tons", exclusive_min=0, places=3)
    if rs["status"] != "REWOUND":
        raise err("ERR_ROLL_SET_INVALID_STATE", "roll set is not REWOUND")
    previous = D(rs["net_tons"])
    if D(net_tons) > previous:
        raise err("ERR_INVALID_WINDOW", "rewind net_tons exceeds the pre-rewind net_tons")
    run = store.get("production_runs", rs["production_run_id"])
    machine = _machine_of(run)
    if slit > int(machine["wire_width_mm"]):
        raise err("ERR_WIDTH_EXCEEDS_DECKLE", "slit width exceeds the machine's wire width")
    rs["slit_width_mm"] = slit
    rs["diameter_mm"] = diameter
    rs["roll_count"] = roll_count
    rs["net_tons"] = net_tons
    rs["quarantine_reason"] = None
    rs["status"] = "WOUND"
    store.touch("roll_sets", rs)
    lost = q(previous - D(net_tons), 3)
    if lost > ZERO:
        common.append_reject("MACHINE_BROKE", run["id"], lost)
    common.recompute_run_produced(run)
    store.touch("production_runs", run)
    return response.ok(common.view(rs))


@bp.post("/roll-sets/<sid>/scrap")
def scrap_set(sid):
    auth.require_roles("MillPlanner")
    rs = _need_set(sid)
    shape.reject_unexpected_version(shape.body())
    if rs["status"] not in ("QUARANTINED", "REWOUND"):
        raise err("ERR_ROLL_SET_INVALID_STATE", "roll set is not QUARANTINED or REWOUND")
    rs["status"] = "SCRAPPED"
    store.touch("roll_sets", rs)
    run = store.get("production_runs", rs["production_run_id"])
    common.append_reject("MACHINE_BROKE", run["id"], rs["net_tons"])
    common.recompute_run_produced(run)
    store.touch("production_runs", run)
    return response.ok(common.view(rs))
