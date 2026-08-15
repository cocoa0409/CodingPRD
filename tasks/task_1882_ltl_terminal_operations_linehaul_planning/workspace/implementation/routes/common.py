"""Shared helpers for route handlers: body parsing, FK resolution, field
validation, pagination, record factory, serializers."""
from datetime import timedelta

from flask import request

import db
from errors import (err_invalid_request, err_not_found,
                    err_reference_not_found)
from services.calculations import MIN_CONNECT_MINUTES
from services.timeutil import fmt_ts, parse_iso


# --- Request body / field validation (priority 20) --------------------------

def body_json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_field(body, field):
    value = body.get(field)
    if value is None:
        raise err_invalid_request("{} is required".format(field))
    return value


def as_int(body, field, minimum=None, maximum=None):
    value = req_field(body, field)
    if not _is_int(value):
        raise err_invalid_request("{} must be an integer".format(field))
    if minimum is not None and value < minimum:
        raise err_invalid_request("{} must be >= {}".format(field, minimum))
    if maximum is not None and value > maximum:
        raise err_invalid_request("{} must be <= {}".format(field, maximum))
    return value


def as_enum(body, field, allowed):
    value = req_field(body, field)
    if not isinstance(value, str) or value not in allowed:
        raise err_invalid_request(
            "{} must be one of {}".format(field, ", ".join(allowed)))
    return value


def as_str(body, field):
    value = req_field(body, field)
    if not isinstance(value, str) or not value:
        raise err_invalid_request("{} must be a non-empty string".format(field))
    return value


def as_datetime(body, field):
    value = req_field(body, field)
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        raise err_invalid_request("{} must be an ISO 8601 instant".format(field))


# --- Existence checks --------------------------------------------------------

def get_path(collection, value):
    """Path-id resolution (priority 3) -> ERR_NOT_FOUND."""
    rec = db.store[collection].get(value)
    if rec is None:
        raise err_not_found("{} id not found".format(collection))
    return rec


def resolve_fk(collection, value, field):
    """Body FK resolution (priority 4) -> ERR_REFERENCE_NOT_FOUND.
    A missing value is a field-validity failure (priority 20) instead."""
    if value is None:
        raise err_invalid_request("{} is required".format(field))
    rec = db.store[collection].get(value)
    if rec is None:
        raise err_reference_not_found("{} does not reference an existing entity".format(field))
    return rec


# --- Pagination (PRD section 2.3) ---------------------------------------------

def pagination_args():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit, 10)
        except (ValueError, TypeError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset, 10)
        except (ValueError, TypeError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be a non-negative integer")
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (insertion order breaks ties), then slice."""
    limit, offset = pagination_args()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total, limit, offset


# --- Record factory / mutation -------------------------------------------------

def new_record(fields, common=True):
    now = db.now()
    rec = {"id": db.new_id(), "created_at": now, "_seq": db.next_seq()}
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and increment version by exactly 1 (PRD section 2.4)."""
    rec["updated_at"] = db.now()
    rec["version"] += 1


# --- Shared lookups --------------------------------------------------------------

def find_prior_leg(leg):
    """The same-trailer leg with relay_sequence one less; CANCELLED legs are
    excluded from relay-chain reasoning."""
    target = leg["relay_sequence"] - 1
    candidates = [
        l for l in db.store["linehaul_legs"].values()
        if l["trailer_id"] == leg["trailer_id"]
        and l["relay_sequence"] == target
        and l["status"] != "CANCELLED"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda l: (l["created_at"], l["_seq"]))


def leg_provisional_eta(leg):
    """Forward-looking ETA (calculation relay_feasibility_and_eta)."""
    if leg["status"] in ("EN_ROUTE", "ARRIVED") and leg["actual_departure_utc"] is not None:
        delta = leg["actual_departure_utc"] - leg["planned_departure_utc"]
        delay_min = int(delta.total_seconds() / 60)  # whole minutes, truncated toward zero
        if delay_min < 0:
            delay_min = 0
        return leg["planned_arrival_utc"] + timedelta(minutes=delay_min)
    if leg["status"] == "PLANNED" and leg["relay_sequence"] > 1:
        prior = find_prior_leg(leg)
        if prior is not None and prior["status"] == "EN_ROUTE":
            prior_eta = leg_provisional_eta(prior)
            shortfall = (prior_eta + timedelta(minutes=MIN_CONNECT_MINUTES)) - leg["planned_departure_utc"]
            if shortfall.total_seconds() > 0:
                return leg["planned_arrival_utc"] + shortfall
    return leg["planned_arrival_utc"]


def active_entries_for_trailer(trailer_id):
    return [
        e for e in db.store["manifest_entries"].values()
        if e["trailer_id"] == trailer_id and e["status"] == "ACTIVE"
    ]


def recompute_trailer_ledger(trailer):
    """loaded_* and utilization_pct derive from ACTIVE manifest entries only."""
    from services.calculations import shipment_cube_cuft, utilization_pct
    entries = active_entries_for_trailer(trailer["id"])
    loaded_w = 0
    loaded_c = 0
    for e in entries:
        s = db.store["shipments"][e["shipment_id"]]
        loaded_w += s["chargeable_weight_lbs"]
        loaded_c += shipment_cube_cuft(s["length_in"], s["width_in"], s["height_in"])
    trailer["loaded_weight_lbs"] = loaded_w
    trailer["loaded_cube_cuft"] = loaded_c
    trailer["utilization_pct"] = utilization_pct(
        loaded_w, trailer["max_weight_lbs"], loaded_c, trailer["max_cube_cuft"])


def check_route_completion(route):
    """A DISPATCHED route completes by exhaustion once every stop sits in
    {PICKED_UP, SKIPPED}. A RECALLED route stays RECALLED."""
    if route["status"] != "DISPATCHED":
        return
    stops = [s for s in db.store["pickup_stops"].values() if s["route_id"] == route["id"]]
    if stops and all(s["status"] in ("PICKED_UP", "SKIPPED") for s in stops):
        route["status"] = "COMPLETED"
        touch(route)


def refresh_osd_hold(shipment):
    """osd_hold is true while any linked case is OPEN or UNDER_REVIEW."""
    hold = any(
        c["shipment_id"] == shipment["id"] and c["status"] in ("OPEN", "UNDER_REVIEW")
        for c in db.store["osd_cases"].values()
    )
    if shipment["osd_hold"] != hold:
        shipment["osd_hold"] = hold
        touch(shipment)


# --- Serializers ------------------------------------------------------------------

def ser_terminal(t):
    return {
        "id": t["id"], "code": t["code"], "name": t["name"],
        "dock_doors": t["dock_doors"], "timezone": t["timezone"],
        "status": t["status"],
        "created_at": fmt_ts(t["created_at"]), "updated_at": fmt_ts(t["updated_at"]),
        "version": t["version"],
    }


def ser_shipment(s):
    return {
        "id": s["id"], "pro_number": s["pro_number"],
        "origin_terminal_id": s["origin_terminal_id"],
        "destination_terminal_id": s["destination_terminal_id"],
        "nmfc_class": s["nmfc_class"],
        "actual_weight_lbs": s["actual_weight_lbs"],
        "length_in": s["length_in"], "width_in": s["width_in"], "height_in": s["height_in"],
        "accessorial_codes": list(s["accessorial_codes"]),
        "service_standard": s["service_standard"],
        "chargeable_weight_lbs": s["chargeable_weight_lbs"],
        "dim_weight_lbs": s["dim_weight_lbs"],
        "rated_amount_cents": s["rated_amount_cents"],
        "billed_amount_cents": s["billed_amount_cents"],
        "rating_status": s["rating_status"],
        "handling_status": s["handling_status"],
        "osd_hold": s["osd_hold"],
        "tendered_at_utc": fmt_ts(s["tendered_at_utc"]),
        "committed_delivery_utc": fmt_ts(s["committed_delivery_utc"]),
        "delivered_at_utc": fmt_ts(s["delivered_at_utc"]),
        "created_at": fmt_ts(s["created_at"]), "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_route(r):
    return {
        "id": r["id"], "terminal_id": r["terminal_id"], "route_date": r["route_date"],
        "driver_id": r["driver_id"],
        "shift_start_minute": r["shift_start_minute"],
        "shift_end_minute": r["shift_end_minute"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]), "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_stop(s):
    return {
        "id": s["id"], "route_id": s["route_id"], "shipment_id": s["shipment_id"],
        "stop_sequence": s["stop_sequence"],
        "planned_arrival_minute": s["planned_arrival_minute"],
        "status": s["status"],
        "created_at": fmt_ts(s["created_at"]), "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_door(d):
    return {
        "id": d["id"], "terminal_id": d["terminal_id"],
        "door_number": d["door_number"], "door_kind": d["door_kind"],
        "status": d["status"],
        "created_at": fmt_ts(d["created_at"]), "updated_at": fmt_ts(d["updated_at"]),
        "version": d["version"],
    }


def ser_batch(b):
    return {
        "id": b["id"], "terminal_id": b["terminal_id"],
        "inbound_door_id": b["inbound_door_id"],
        "destination_terminal_id": b["destination_terminal_id"],
        "status": b["status"],
        "created_at": fmt_ts(b["created_at"]), "updated_at": fmt_ts(b["updated_at"]),
        "version": b["version"],
    }


def ser_trailer(t):
    return {
        "id": t["id"], "terminal_id": t["terminal_id"],
        "destination_terminal_id": t["destination_terminal_id"],
        "outbound_door_id": t["outbound_door_id"],
        "max_weight_lbs": t["max_weight_lbs"], "max_cube_cuft": t["max_cube_cuft"],
        "loaded_weight_lbs": t["loaded_weight_lbs"],
        "loaded_cube_cuft": t["loaded_cube_cuft"],
        "utilization_pct": float(t["utilization_pct"]),
        "posture": t["posture"],
        "created_at": fmt_ts(t["created_at"]), "updated_at": fmt_ts(t["updated_at"]),
        "version": t["version"],
    }


def ser_entry(e):
    return {
        "id": e["id"], "trailer_id": e["trailer_id"], "shipment_id": e["shipment_id"],
        "load_position": e["load_position"], "status": e["status"],
        "created_at": fmt_ts(e["created_at"]), "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_leg(l):
    return {
        "id": l["id"],
        "origin_terminal_id": l["origin_terminal_id"],
        "destination_terminal_id": l["destination_terminal_id"],
        "trailer_id": l["trailer_id"],
        "planned_departure_utc": fmt_ts(l["planned_departure_utc"]),
        "planned_arrival_utc": fmt_ts(l["planned_arrival_utc"]),
        "actual_departure_utc": fmt_ts(l["actual_departure_utc"]),
        "actual_arrival_utc": fmt_ts(l["actual_arrival_utc"]),
        "provisional_eta_utc": fmt_ts(leg_provisional_eta(l)),
        "relay_sequence": l["relay_sequence"], "status": l["status"],
        "created_at": fmt_ts(l["created_at"]), "updated_at": fmt_ts(l["updated_at"]),
        "version": l["version"],
    }


def ser_scan(s):
    return {
        "id": s["id"], "shipment_id": s["shipment_id"],
        "measured_length_in": s["measured_length_in"],
        "measured_width_in": s["measured_width_in"],
        "measured_height_in": s["measured_height_in"],
        "measured_weight_lbs": s["measured_weight_lbs"],
        "scanned_by": s["scanned_by"],
        "created_at": fmt_ts(s["created_at"]),
    }


def ser_inspection(i):
    return {
        "id": i["id"], "shipment_id": i["shipment_id"], "scan_id": i["scan_id"],
        "claimed_nmfc_class": i["claimed_nmfc_class"],
        "outcome": i["outcome"], "adjustment_cents": i["adjustment_cents"],
        "created_at": fmt_ts(i["created_at"]), "updated_at": fmt_ts(i["updated_at"]),
        "version": i["version"],
    }


def ser_case(c):
    return {
        "id": c["id"], "shipment_id": c["shipment_id"], "case_kind": c["case_kind"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "item_amounts_cents": list(c["item_amounts_cents"]),
        "awarded_amount_cents": c["awarded_amount_cents"],
        "status": c["status"],
        "created_at": fmt_ts(c["created_at"]), "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def ser_report(r):
    return {
        "id": r["id"], "terminal_id": r["terminal_id"], "report_date": r["report_date"],
        "window_start_utc": fmt_ts(r["window_start_utc"]),
        "window_end_utc": fmt_ts(r["window_end_utc"]),
        "shipments_due": r["shipments_due"],
        "shipments_on_time": r["shipments_on_time"],
        "on_time_pct": float(r["on_time_pct"]),
        "service_level_met": r["service_level_met"],
        "created_at": fmt_ts(r["created_at"]),
    }
