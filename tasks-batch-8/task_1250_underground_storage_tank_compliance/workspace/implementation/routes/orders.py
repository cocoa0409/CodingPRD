"""ServiceOrder lifecycle: create/quote, schedule, edit (OCC), start, results,
certify, return-for-correction, cancel (PRD 3.3, 3.4, 3.5)."""
from flask import Blueprint

from authz import (
    COMPLIANCE_REVIEWER, CONTRACTOR_ADMIN, READ_ROLES, TECHNICIAN, require_roles,
)
from calc import (
    COMPONENT_SERVICE_TYPES, ENDORSEMENT_FOR_SERVICE, TANK_STABILIZATION_HOURS,
    TIGHTNESS_SERVICE_TYPES, compute_quote_total, determine_outcome,
    recompute_posture,
)
from cascades import close_tank_cascade, create_deficiency, create_release_event
from db import store
from errors import (
    component_mismatch, deficiency_link_invalid, deficiency_not_found,
    endorsement_missing, invalid_request, invalid_window, not_resource_owner,
    order_not_cancellable, order_not_editable, order_not_found,
    order_not_in_progress, order_not_requested, order_not_scheduled,
    order_not_under_review, outside_service_window, self_certification,
    stale_version, tank_facility_mismatch, tank_not_in_service,
    tank_stabilization_window, technician_double_booked, technician_not_found,
)
from respond import success
from routes.components import get_component_or_404
from routes.facilities import get_facility_or_404
from routes.tanks import get_tank_or_404
from routes.technicians import get_technician_or_404
from serialize import ser_order
from store_ops import (
    check_closed, get_or_404, json_body, new_common_fields, new_id, opt_str,
    opt_version, paginate, qparam, req_field, req_instant, req_list, req_str,
    sorted_by_creation, touch,
)
from timeutil import hours

bp = Blueprint("service_orders", __name__)

SERVICE_TYPES = ["TANK_TIGHTNESS", "LINE_TIGHTNESS", "LLD_FUNCTION", "CP_SURVEY",
                 "SPILL_OVERFILL_INSPECTION"]

# Readings schemas per service type (PRD 3.4; ERR_INVALID_REQUEST on mismatch).
READINGS_SCHEMAS = {
    "TANK_TIGHTNESS": {"leak_rate_gph": "number"},
    "LINE_TIGHTNESS": {"leak_rate_gph": "number"},
    "LLD_FUNCTION": {"detects_simulated_leak": "bool"},
    "SPILL_OVERFILL_INSPECTION": {
        "visual_cracks_found": "bool",
        "drain_test_hold_minutes": "number",
        "overfill_activates_pct": "number",
    },
    "CP_SURVEY": {
        "instant_off_mv": "int",
        "polarized_mv": "int",
        "native_mv": "int",
        "valid_contact": "bool",
        "criterion": ("INSTANT_OFF", "POLARIZATION_SHIFT"),
    },
}


def get_order_or_404(order_id):
    return get_or_404(store.service_orders, order_id, order_not_found)


def _validate_line_items(data, name="line_items"):
    items = req_list(data, name)
    for line in items:
        if not isinstance(line, dict):
            raise invalid_request("Each %s entry must be an object" % name)
        check_closed(line, {"description", "qty", "unit_price_cents"})
        req_str(line, "description")
        qty = req_field(line, "qty")
        if isinstance(qty, bool) or not isinstance(qty, (int, float)):
            raise invalid_request("Field qty must be a number")
        price = req_field(line, "unit_price_cents")
        if isinstance(price, bool) or not isinstance(price, int):
            raise invalid_request("Field unit_price_cents must be an integer")
    return items


def _validate_readings(service_type, readings):
    if not isinstance(readings, dict):
        raise invalid_request("readings must be an object")
    schema = READINGS_SCHEMAS[service_type]
    check_closed(readings, set(schema))
    for key, kind in schema.items():
        if key not in readings or readings[key] is None:
            raise invalid_request("readings is missing required field: %s" % key)
        v = readings[key]
        if kind == "bool":
            if not isinstance(v, bool):
                raise invalid_request("readings.%s must be a boolean" % key)
        elif kind == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                raise invalid_request("readings.%s must be an integer" % key)
        elif kind == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise invalid_request("readings.%s must be a number" % key)
        else:  # enum tuple
            if v not in kind:
                raise invalid_request("readings.%s must be one of %s" % (key, ", ".join(kind)))
    return readings


def _check_component_rules(service_type, component_id, tank_system_id):
    """Priority 17: component presence/type/tank alignment per service_type."""
    if service_type in TIGHTNESS_SERVICE_TYPES:
        if component_id is not None:
            raise component_mismatch("Tightness orders must carry no component_id")
        return None
    # component-level service types
    if component_id is None:
        raise component_mismatch("%s requires a component_id" % service_type)
    comp = get_component_or_404(component_id)
    if comp["tank_system_id"] != tank_system_id:
        raise component_mismatch("component_id does not belong to the order's tank")
    if comp["component_type"] not in COMPONENT_SERVICE_TYPES[service_type]:
        raise component_mismatch("component_type does not match service_type")
    return comp


def _check_deficiency_link(linked_deficiency_id, tank_system_id):
    if linked_deficiency_id is None:
        return None
    d = store.deficiencies.get(linked_deficiency_id)
    if d is None:
        raise deficiency_not_found()
    if d["tank_system_id"] != tank_system_id:
        raise deficiency_link_invalid("linked deficiency belongs to a different tank")
    if d["status"] not in ("OPEN", "CORRECTION_ORDERED", "CORRECTED"):
        raise deficiency_link_invalid("linked deficiency status must be OPEN, CORRECTION_ORDERED, or CORRECTED")
    return d


def _check_endorsement(technician, service_type):
    """Priority 7: technician must be active and hold the mapped endorsement."""
    required = ENDORSEMENT_FOR_SERVICE[service_type]
    if not technician["active"] or required not in technician["endorsements"]:
        raise endorsement_missing()


def _check_window(window_start, window_end):
    """Priority 11: window_end strictly after window_start."""
    if not (window_end > window_start):
        raise invalid_window()


def _check_double_booking(technician_id, window_start, window_end, exclude_order_id):
    """Priority 12: half-open [start, end) overlap; adjacency allowed."""
    for o in store.service_orders.values():
        if o["id"] == exclude_order_id:
            continue
        if o["technician_id"] != technician_id:
            continue
        if o["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if o["window_start"] is None:
            continue
        if window_start < o["window_end"] and o["window_start"] < window_end:
            raise technician_double_booked()


def _check_stabilization(order, window_start, window_end):
    """Priority 13: two TANK_TIGHTNESS orders on one tank need >= 8h between a
    prior window_end and the new window_start (and symmetrically); exactly 8h
    is allowed."""
    if order["service_type"] != "TANK_TIGHTNESS":
        return
    buf = hours(TANK_STABILIZATION_HOURS)
    for o in store.service_orders.values():
        if o["id"] == order["id"]:
            continue
        if o["tank_system_id"] != order["tank_system_id"]:
            continue
        if o["service_type"] != "TANK_TIGHTNESS":
            continue
        if o["status"] not in ("SCHEDULED", "IN_PROGRESS", "CERTIFIED"):
            continue
        if o["window_start"] is None:
            continue
        separated = (o["window_end"] + buf <= window_start) or (o["window_start"] >= window_end + buf)
        if not separated:
            raise tank_stabilization_window()


@bp.route("/service-orders", methods=["POST"])
def create_order():
    require_roles([CONTRACTOR_ADMIN])
    data = json_body()
    check_closed(data, {"facility_id", "tank_system_id", "component_id",
                        "linked_deficiency_id", "service_type", "line_items"})
    facility_id = req_str(data, "facility_id")
    tank_system_id = req_str(data, "tank_system_id")
    service_type = req_field(data, "service_type")
    if service_type not in SERVICE_TYPES:
        raise invalid_request("Field service_type must be one of %s" % ", ".join(SERVICE_TYPES))
    line_items = _validate_line_items(data)
    component_id = opt_str(data, "component_id")
    linked_deficiency_id = opt_str(data, "linked_deficiency_id")

    # Priority 4: body FK existence, left-to-right.
    get_facility_or_404(facility_id)
    tank = get_tank_or_404(tank_system_id)
    if component_id is not None:
        get_component_or_404(component_id)
    if linked_deficiency_id is not None and linked_deficiency_id not in store.deficiencies:
        raise deficiency_not_found()

    # Priority 17: cross-referential alignment.
    if tank["facility_id"] != facility_id:
        raise tank_facility_mismatch()
    _check_component_rules(service_type, component_id, tank_system_id)
    _check_deficiency_link(linked_deficiency_id, tank_system_id)

    o = {
        "id": new_id(),
        "_seq": next(store.seq),
        "facility_id": facility_id,
        "tank_system_id": tank_system_id,
        "component_id": component_id,
        "service_type": service_type,
        "technician_id": None,
        "window_start": None,
        "window_end": None,
        "line_items": line_items,
        "quote_total_cents": compute_quote_total(line_items),
        "result_outcome": "NONE",
        "performed_by_technician_id": None,
        "certified_by_technician_id": None,
        "linked_deficiency_id": linked_deficiency_id,
        "status": "REQUESTED",
    }
    o.update(new_common_fields())
    store.service_orders[o["id"]] = o
    return success(ser_order(o), status=201)


@bp.route("/service-orders", methods=["GET"])
def list_orders():
    require_roles(READ_ROLES)
    items = store.service_orders.values()
    for f in ("facility_id", "tank_system_id", "component_id", "technician_id",
              "linked_deficiency_id", "performed_by_technician_id",
              "certified_by_technician_id", "status"):
        v = qparam(f)
        if v is not None:
            items = [o for o in items if o[f] == v]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_order(o) for o in page], response_type="array", pagination=pagination)


@bp.route("/service-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    require_roles(READ_ROLES)
    return success(ser_order(get_order_or_404(order_id)))


@bp.route("/service-orders/<order_id>/schedule", methods=["POST"])
def schedule_order(order_id):
    require_roles([CONTRACTOR_ADMIN])
    data = json_body()
    check_closed(data, {"technician_id", "window_start", "window_end"})
    technician_id = req_str(data, "technician_id")
    window_start = req_instant(data, "window_start")
    window_end = req_instant(data, "window_end")

    o = get_order_or_404(order_id)
    tech = get_technician_or_404(technician_id)
    # Priority 5: order from-state, then tank state.
    if o["status"] != "REQUESTED":
        raise order_not_requested()
    tank = get_tank_or_404(o["tank_system_id"])
    if tank["status"] != "IN_SERVICE":
        raise tank_not_in_service("Schedule requires tank status IN_SERVICE")
    # Priorities 7, 11, 12, 13 in order.
    _check_endorsement(tech, o["service_type"])
    _check_window(window_start, window_end)
    _check_double_booking(technician_id, window_start, window_end, o["id"])
    _check_stabilization(o, window_start, window_end)

    o["technician_id"] = technician_id
    o["window_start"] = window_start
    o["window_end"] = window_end
    o["status"] = "SCHEDULED"
    touch(o)
    # Scheduling a linked re-test advances a CORRECTED deficiency.
    d = store.deficiencies.get(o["linked_deficiency_id"] or "")
    if d is not None and d["status"] == "CORRECTED":
        d["status"] = "RE_TEST_SCHEDULED"
        touch(d)
    return success(ser_order(o))


@bp.route("/service-orders/<order_id>", methods=["PUT"])
def update_order(order_id):
    require_roles([CONTRACTOR_ADMIN])
    data = json_body()
    check_closed(data, {"expected_service_order_version", "line_items",
                        "window_start", "window_end", "technician_id"})
    expected = opt_version(data, "expected_service_order_version")

    o = get_order_or_404(order_id)
    # Priority 5: editable state (checked before OCC, per PRD 2.7).
    if o["status"] not in ("REQUESTED", "SCHEDULED"):
        raise order_not_editable()

    new_technician = None
    if "technician_id" in data and data["technician_id"] is not None:
        new_technician = req_str(data, "technician_id")
        get_technician_or_404(new_technician)  # priority 4: body FK existence
    new_start = None
    new_end = None
    if "window_start" in data and data["window_start"] is not None:
        new_start = req_instant(data, "window_start")
    if "window_end" in data and data["window_end"] is not None:
        new_end = req_instant(data, "window_end")
    new_lines = None
    if "line_items" in data and data["line_items"] is not None:
        new_lines = _validate_line_items(data)

    # On a SCHEDULED order, changing window or technician re-runs the
    # endorsement / overlap / buffer / window-validity checks against the
    # merged new values (PRD 3.3).
    if o["status"] == "SCHEDULED" and (new_technician is not None
                                       or new_start is not None or new_end is not None):
        merged_tech = new_technician if new_technician is not None else o["technician_id"]
        merged_start = new_start if new_start is not None else o["window_start"]
        merged_end = new_end if new_end is not None else o["window_end"]
        tech = get_technician_or_404(merged_tech)
        _check_endorsement(tech, o["service_type"])
        _check_window(merged_start, merged_end)
        _check_double_booking(merged_tech, merged_start, merged_end, o["id"])
        _check_stabilization(o, merged_start, merged_end)

    # Priority 19: optimistic concurrency.
    if expected != o["version"]:
        raise stale_version()

    if new_lines is not None:
        o["line_items"] = new_lines
        o["quote_total_cents"] = compute_quote_total(new_lines)
    if new_technician is not None:
        o["technician_id"] = new_technician
    if new_start is not None:
        o["window_start"] = new_start
    if new_end is not None:
        o["window_end"] = new_end
    touch(o)
    return success(ser_order(o))


@bp.route("/service-orders/<order_id>/start", methods=["POST"])
def start_order(order_id):
    uid, _ = require_roles([TECHNICIAN])
    data = json_body()
    check_closed(data, set())
    o = get_order_or_404(order_id)
    if o["status"] != "SCHEDULED":
        raise order_not_scheduled()
    # Technician ownership: only the assigned technician may start.
    if uid != o["technician_id"]:
        raise not_resource_owner("Caller is not the order's assigned technician")
    # Priority 14: window containment, both bounds inclusive.
    if not (o["window_start"] <= store.clock <= o["window_end"]):
        raise outside_service_window()
    o["performed_by_technician_id"] = uid
    o["status"] = "IN_PROGRESS"
    touch(o)
    return success(ser_order(o))


@bp.route("/service-orders/<order_id>/results", methods=["POST"])
def record_results(order_id):
    uid, _ = require_roles([TECHNICIAN])
    data = json_body()
    check_closed(data, {"readings"})
    o = get_order_or_404(order_id)
    if o["status"] != "IN_PROGRESS":
        raise order_not_in_progress()
    if uid != o["performed_by_technician_id"]:
        raise not_resource_owner("Caller is not the order's performing technician")
    readings = _validate_readings(o["service_type"], req_field(data, "readings"))

    outcome = determine_outcome(o["service_type"], readings)
    r = {
        "id": new_id(),
        "_seq": next(store.seq),
        "service_order_id": o["id"],
        "readings": readings,
        "outcome": outcome,
        "recorded_at": store.clock,
        "created_at": store.clock,
    }
    store.result_records[r["id"]] = r
    o["result_outcome"] = outcome
    o["status"] = "UNDER_REVIEW"
    touch(o)

    # FAIL cascades. Suppression rule: an order carrying linked_deficiency_id
    # creates no new deficiency and no release event on FAIL — the linked
    # deficiency loops at certify time instead.
    if outcome == "FAIL" and not o["linked_deficiency_id"]:
        tank = get_tank_or_404(o["tank_system_id"])
        if o["service_type"] in TIGHTNESS_SERVICE_TYPES:
            d = create_deficiency(
                facility_id=o["facility_id"], tank_system_id=o["tank_system_id"],
                component_id=None, source_service_order_id=o["id"],
                origin="TEST_FAILURE", period_month=None, severity="CRITICAL",
                description="%s test failed on service order %s" % (o["service_type"], o["id"]))
            create_release_event(
                facility_id=o["facility_id"], tank_system_id=o["tank_system_id"],
                discovered_at=store.clock,
                source_description="Suspected release from failed %s on service order %s"
                                   % (o["service_type"], o["id"]))
            # The new CRITICAL deficiency drives the tank into temporary
            # closure, cancelling its pending orders.
            if tank["status"] == "IN_SERVICE":
                close_tank_cascade(tank, "TEMPORARILY_CLOSED")
        else:
            create_deficiency(
                facility_id=o["facility_id"], tank_system_id=o["tank_system_id"],
                component_id=o["component_id"], source_service_order_id=o["id"],
                origin="TEST_FAILURE", period_month=None, severity="MAJOR",
                description="%s test failed on service order %s" % (o["service_type"], o["id"]))
    if outcome == "FAIL":
        recompute_posture(get_facility_or_404(o["facility_id"]))
    return success(ser_order(o))


@bp.route("/service-orders/<order_id>/certify", methods=["POST"])
def certify_order(order_id):
    uid, _ = require_roles([COMPLIANCE_REVIEWER])
    data = json_body()
    check_closed(data, set())
    o = get_order_or_404(order_id)
    # Priority 5 (state) precedes priority 6 (segregation of duties).
    if o["status"] != "UNDER_REVIEW":
        raise order_not_under_review()
    if uid == o["performed_by_technician_id"]:
        raise self_certification()
    o["certified_by_technician_id"] = uid
    o["status"] = "CERTIFIED"
    touch(o)
    # Linked re-test resolution.
    d = store.deficiencies.get(o["linked_deficiency_id"] or "")
    if d is not None and d["status"] == "RE_TEST_SCHEDULED":
        if o["result_outcome"] == "PASS":
            d["status"] = "VERIFIED_CLOSED"
            d["verified_by_service_order_id"] = o["id"]
            touch(d)
            if d["component_id"]:
                comp = store.components.get(d["component_id"])
                if comp is not None and comp["status"] == "DEFICIENT":
                    comp["status"] = "IN_SERVICE"
                    touch(comp)
            recompute_posture(get_facility_or_404(o["facility_id"]))
        elif o["result_outcome"] == "FAIL":
            d["status"] = "CORRECTION_ORDERED"
            touch(d)
            recompute_posture(get_facility_or_404(o["facility_id"]))
        # INCONCLUSIVE: the deficiency stays RE_TEST_SCHEDULED.
    return success(ser_order(o))


@bp.route("/service-orders/<order_id>/return-for-correction", methods=["POST"])
def return_for_correction(order_id):
    require_roles([COMPLIANCE_REVIEWER])
    data = json_body()
    check_closed(data, set())
    o = get_order_or_404(order_id)
    if o["status"] != "UNDER_REVIEW":
        raise order_not_under_review()
    # result_outcome stays as recorded; prior ResultRecords remain immutable.
    o["status"] = "IN_PROGRESS"
    touch(o)
    return success(ser_order(o))


@bp.route("/service-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    require_roles([CONTRACTOR_ADMIN])
    data = json_body()
    check_closed(data, set())
    o = get_order_or_404(order_id)
    if o["status"] not in ("REQUESTED", "SCHEDULED"):
        raise order_not_cancellable()
    o["status"] = "CANCELLED"
    touch(o)
    d = store.deficiencies.get(o["linked_deficiency_id"] or "")
    if d is not None and d["status"] == "RE_TEST_SCHEDULED":
        d["status"] = "CORRECTED"
        touch(d)
    return success(ser_order(o))
