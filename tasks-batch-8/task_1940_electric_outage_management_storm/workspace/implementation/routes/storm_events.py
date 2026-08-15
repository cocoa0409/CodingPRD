"""StormEvent endpoints: declare/list/get/activate/begin_demobilization/close,
run_clustering, dispatch_next, cost-summary."""
from flask import Blueprint

from db import db, iso_ms
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE_TRANSITION, ERR_EVENT_NOT_ACTIVE,
    ERR_EVENT_HAS_OPEN_WORK, ERR_NO_ELIGIBLE_WORK, ERR_CREW_NOT_AVAILABLE,
    ERR_FATIGUE_LIMIT_EXCEEDED,
)
from services.core import (
    get_body, req_string, req_enum, paginate, new_common, bump,
    get_event, get_feeder, get_crew, get_outage,
    serialize_event, serialize_work_order, sort_created_asc,
    outage_priority_score, fatigue_projection,
    EVENT_TYPES, CLUSTER_WINDOW_MINUTES, TERMINAL_OUTAGE,
    create_etr_revision,
)
from db import parse_iso
from datetime import timedelta

bp = Blueprint("storm_events", __name__)


@bp.route("/om/storm-events", methods=["POST"])
def create_event():
    require_roles(["EmergencyDirector"])
    body = get_body()
    name = req_string(body, "event_name")
    etype = req_enum(body, "event_type", EVENT_TYPES)
    e = new_common()
    e.update({
        "event_name": name,
        "event_type": etype,
        "event_status": "DECLARED",
        "activated_at": None,
    })
    db.storm_events[e["id"]] = e
    return success_object(serialize_event(e), status=201)


@bp.route("/om/storm-events", methods=["GET"])
def list_events():
    require_roles(ALL_ROLES)
    from flask import request
    items = list(db.storm_events.values())
    status = request.args.get("event_status")
    if status is not None:
        items = [e for e in items if e["event_status"] == status]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_event(e) for e in page], limit, offset, total)


@bp.route("/om/storm-events/<eid>", methods=["GET"])
def get_one_event(eid):
    require_roles(ALL_ROLES)
    e = get_event(eid)
    return success_object(serialize_event(e))


@bp.route("/om/storm-events/<eid>/activate", methods=["POST"])
def activate_event(eid):
    require_roles(["EmergencyDirector"])
    e = get_event(eid)
    if e["event_status"] != "DECLARED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"StormEvent in {e['event_status']} cannot be activated")
    e["event_status"] = "ACTIVE"
    e["activated_at"] = iso_ms(db.now())
    bump(e)
    return success_object(serialize_event(e))


@bp.route("/om/storm-events/<eid>/begin_demobilization", methods=["POST"])
def begin_demobilization(eid):
    require_roles(["EmergencyDirector"])
    e = get_event(eid)
    if e["event_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"StormEvent in {e['event_status']} cannot begin demobilization")
    # Precondition set: no open outages / in-field MA crews / non-terminal
    # requisitions / un-released lodging blocks.
    for o in db.outages.values():
        if o["storm_event_id"] == eid and o["outage_status"] not in ("VERIFIED", "CANCELLED"):
            raise_err(ERR_EVENT_HAS_OPEN_WORK, "Open outages remain on the event")
    for c in db.mutual_aid_crews.values():
        if c["storm_event_id"] == eid and c["ma_status"] not in ("DEPARTED", "CANCELLED"):
            raise_err(ERR_EVENT_HAS_OPEN_WORK, "Mutual-aid crews still engaged")
    event_outage_ids = {o["id"] for o in db.outages.values() if o["storm_event_id"] == eid}
    event_wo_ids = {w["id"] for w in db.work_orders.values() if w["outage_id"] in event_outage_ids}
    for r in db.material_requisitions.values():
        if r["work_order_id"] in event_wo_ids and \
                r["requisition_status"] not in ("CONSUMED", "RETURNED", "CANCELLED"):
            raise_err(ERR_EVENT_HAS_OPEN_WORK, "Non-terminal material requisitions remain")
    for b in db.lodging_blocks.values():
        if b["storm_event_id"] == eid and b["block_status"] != "RELEASED":
            raise_err(ERR_EVENT_HAS_OPEN_WORK, "Un-released lodging blocks remain")
    e["event_status"] = "DEMOBILIZING"
    bump(e)
    return success_object(serialize_event(e))


@bp.route("/om/storm-events/<eid>/close", methods=["POST"])
def close_event(eid):
    require_roles(["EmergencyDirector"])
    e = get_event(eid)
    if e["event_status"] != "DEMOBILIZING":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"StormEvent in {e['event_status']} cannot be closed")
    event_outage_ids = {o["id"] for o in db.outages.values() if o["storm_event_id"] == eid}
    event_wo_ids = {w["id"] for w in db.work_orders.values() if w["outage_id"] in event_outage_ids}
    for so in db.switching_orders.values():
        if so["work_order_id"] in event_wo_ids and \
                so["so_status"] in ("DRAFT", "ISSUED", "APPROVED"):
            raise_err(ERR_EVENT_HAS_OPEN_WORK, "Non-terminal switching orders remain")
    e["event_status"] = "CLOSED"
    bump(e)
    return success_object(serialize_event(e))


@bp.route("/om/storm-events/<eid>/run_clustering", methods=["POST"])
def run_clustering(eid):
    require_roles(["Dispatcher"])
    e = get_event(eid)
    body = get_body()
    feeder_id = req_string(body, "feeder_id")
    feeder = get_feeder(feeder_id)
    # Event posture gate
    if e["event_status"] != "ACTIVE":
        raise_err(ERR_EVENT_NOT_ACTIVE, "Clustering requires the event to be ACTIVE")

    # Candidates: UNCLUSTERED signals on this feeder of the three clusterable types.
    candidates = [
        s for s in db.trouble_signals.values()
        if s["feeder_id"] == feeder_id
        and s["disposition"] == "UNCLUSTERED"
        and s["signal_type"] in ("METER_LAST_GASP", "CUSTOMER_CALL", "SCADA_TRIP")
    ]
    if not candidates:
        return success_object({"promoted": False, "outage_id": None, "clustered_signal_count": 0})

    # Sort by occurred_at ASC, tie-break created_at ASC (never id).
    candidates.sort(key=lambda s: (parse_iso(s["occurred_at"]), parse_iso(s["created_at"]), s["_mono"]))
    anchor = candidates[0]
    anchor_t = parse_iso(anchor["occurred_at"])
    window_end = anchor_t + timedelta(minutes=CLUSTER_WINDOW_MINUTES)
    group = [s for s in candidates
             if anchor_t <= parse_iso(s["occurred_at"]) <= window_end]

    n_last_gasp = sum(1 for s in group if s["signal_type"] == "METER_LAST_GASP")
    n_call = sum(1 for s in group if s["signal_type"] == "CUSTOMER_CALL")
    n_scada = sum(1 for s in group if s["signal_type"] == "SCADA_TRIP")

    promote = (n_scada >= 1
               or n_last_gasp >= feeder["cluster_signal_threshold"]
               or n_call >= feeder["cluster_call_threshold"])

    if not promote:
        return success_object({"promoted": False, "outage_id": None, "clustered_signal_count": 0})

    # Promote: create SUSPECTED outage; move group signals to CLUSTERED.
    o = new_common()
    o.update({
        "storm_event_id": eid,
        "feeder_id": feeder_id,
        "parent_outage_id": None,
        "outage_status": "SUSPECTED",
        "cause_code": None,
        "customers_affected": None,
        "confirmed_at": None,
        "current_etr": None,
        "restoration_reported_at": None,
        "merged_into_outage_id": None,
    })
    db.outages[o["id"]] = o
    for s in group:
        s["disposition"] = "CLUSTERED"
        s["outage_id"] = o["id"]
    return success_object({
        "promoted": True,
        "outage_id": o["id"],
        "clustered_signal_count": len(group),
    })


@bp.route("/om/storm-events/<eid>/dispatch_next", methods=["POST"])
def dispatch_next(eid):
    require_roles(["Dispatcher"])
    e = get_event(eid)
    body = get_body()
    crew_id = req_string(body, "crew_id")
    crew = get_crew(crew_id)

    # Eligible set: READY work orders, required_crew_type == crew.crew_type,
    # outage on this event and not VERIFIED/CANCELLED.
    eligible = []
    for wo in db.work_orders.values():
        if wo["execution_status"] != "READY":
            continue
        if wo["required_crew_type"] != crew["crew_type"]:
            continue
        outage = db.outages.get(wo["outage_id"])
        if outage is None or outage["storm_event_id"] != eid:
            continue
        if outage["outage_status"] in TERMINAL_OUTAGE:
            continue
        eligible.append(wo)

    if not eligible:
        raise_err(ERR_NO_ELIGIBLE_WORK, "No eligible READY work order for this crew on this event")

    # Rank: outage priority_score DESC; tie-break work order created_at ASC.
    eligible.sort(key=lambda w: (
        -outage_priority_score(db.outages[w["outage_id"]]),
        parse_iso(w["created_at"]),
        w["_mono"],
    ))
    wo = eligible[0]
    outage = db.outages[wo["outage_id"]]

    # Assign exactly as a manual assignment: crew availability + fatigue check.
    if crew["crew_status"] != "AVAILABLE":
        raise_err(ERR_CREW_NOT_AVAILABLE, "Crew is not AVAILABLE")
    projected = fatigue_projection(crew, outage)
    if projected > 960:
        raise_err(ERR_FATIGUE_LIMIT_EXCEEDED,
                  f"Fatigue projection {projected} exceeds 960 minutes")

    wo["assigned_crew_id"] = crew["id"]
    wo["assigned_mutual_aid_crew_id"] = None
    wo["execution_status"] = "DISPATCHED"
    bump(wo)
    crew["crew_status"] = "EN_ROUTE"
    bump(crew)
    return success_object(serialize_work_order(wo))


@bp.route("/om/storm-events/<eid>/cost-summary", methods=["GET"])
def cost_summary(eid):
    require_roles(ALL_ROLES)
    e = get_event(eid)
    from services.core import event_cost_totals
    return success_object(event_cost_totals(e["id"]))
