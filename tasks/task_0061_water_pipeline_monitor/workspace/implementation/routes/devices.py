"""Device CRUD + activation/decommission + reading ingest."""
from flask import Blueprint, request

from db import alerts, devices, investigations, lock, public, readings, stamp_create, stamp_update
from errors import err
from middleware import get_json_body, get_pagination, require_auth
from response import success, success_list
from services.common import (
    active_topology_id,
    check_occ,
    find_node_in_version,
    get_device,
    get_network,
)
from services.readings import ingest_reading


bp = Blueprint("devices", __name__)


VALID_PROTOCOLS = {"NB_IOT", "LORA", "WIRED"}
VALID_SENSOR_KINDS = {"PRESSURE", "FLOW", "METER"}


def _validate_device_config(polling_interval_s, vmin, vmax):
    if polling_interval_s is None:
        raise err("ERR_DEVICE_CONFIG_INVALID", "polling_interval_s is required")
    try:
        ps = int(polling_interval_s)
    except (TypeError, ValueError):
        raise err("ERR_DEVICE_CONFIG_INVALID", "polling_interval_s must be integer")
    if ps < 30 or ps > 3600:
        raise err("ERR_DEVICE_CONFIG_INVALID", "polling_interval_s out of range")
    if vmin is None or vmax is None:
        raise err("ERR_DEVICE_CONFIG_INVALID", "valid_range_min/max are required")
    try:
        vmin_f = float(vmin)
        vmax_f = float(vmax)
    except (TypeError, ValueError):
        raise err("ERR_DEVICE_CONFIG_INVALID", "valid_range_min/max must be numbers")
    if vmin_f >= vmax_f:
        raise err("ERR_DEVICE_CONFIG_INVALID", "valid_range_min must be < valid_range_max")
    return ps, vmin_f, vmax_f


@bp.post("/networks/<network_id>/devices")
@require_auth(roles={"ControlOperator"})
def create_device(network_id):
    n = get_network(network_id)
    body = get_json_body()
    device_code = body.get("device_code")
    if not device_code or not isinstance(device_code, str):
        raise err("ERR_BAD_REQUEST", "device_code is required")
    protocol = body.get("protocol")
    if protocol not in VALID_PROTOCOLS:
        raise err("ERR_BAD_REQUEST", "protocol invalid")
    sensor_kind = body.get("sensor_kind")
    if sensor_kind not in VALID_SENSOR_KINDS:
        raise err("ERR_BAD_REQUEST", "sensor_kind invalid")
    ps, vmin_f, vmax_f = _validate_device_config(
        body.get("polling_interval_s"),
        body.get("valid_range_min"),
        body.get("valid_range_max"),
    )
    for d in devices.values():
        if d.get("network_id") == network_id and d.get("device_code") == device_code:
            raise err("ERR_BAD_REQUEST", "device_code already exists in this network")
    with lock():
        d = {
            "network_id": network_id,
            "device_code": device_code,
            "mounted_on_node_code": body.get("mounted_on_node_code"),
            "protocol": protocol,
            "sensor_kind": sensor_kind,
            "polling_interval_s": ps,
            "valid_range_min": vmin_f,
            "valid_range_max": vmax_f,
            "status": "PROVISIONED",
            "last_reading_at": None,
            "last_reading_value": None,
            "missed_polls_consecutive": 0,
        }
        # Optional billing-related fields for METER devices
        if "billed_flag" in body:
            d["billed_flag"] = bool(body["billed_flag"])
        if "authorized" in body:
            d["authorized"] = bool(body["authorized"])
        stamp_create(d)
        devices[d["id"]] = d
        return success(public(d), 201)


@bp.get("/networks/<network_id>/devices/<device_id>")
@require_auth(roles={"ControlOperator", "MaintenanceSupervisor", "Auditor"})
def get_device_endpoint(network_id, device_id):
    d = get_device(network_id, device_id)
    return success(public(d))


@bp.patch("/networks/<network_id>/devices/<device_id>")
@require_auth(roles={"ControlOperator"})
def patch_device(network_id, device_id):
    d = get_device(network_id, device_id)
    body = get_json_body()
    # OCC
    check_occ(d, body)
    new_ps = body.get("polling_interval_s", d.get("polling_interval_s"))
    new_vmin = body.get("valid_range_min", d.get("valid_range_min"))
    new_vmax = body.get("valid_range_max", d.get("valid_range_max"))
    # Only re-validate when at least one of these fields was supplied
    if (
        "polling_interval_s" in body
        or "valid_range_min" in body
        or "valid_range_max" in body
    ):
        ps, vmin_f, vmax_f = _validate_device_config(new_ps, new_vmin, new_vmax)
    else:
        ps = d.get("polling_interval_s")
        vmin_f = d.get("valid_range_min")
        vmax_f = d.get("valid_range_max")
    with lock():
        d["polling_interval_s"] = ps
        d["valid_range_min"] = vmin_f
        d["valid_range_max"] = vmax_f
        if "mounted_on_node_code" in body:
            d["mounted_on_node_code"] = body["mounted_on_node_code"]
        if "billed_flag" in body:
            d["billed_flag"] = bool(body["billed_flag"])
        if "authorized" in body:
            d["authorized"] = bool(body["authorized"])
        stamp_update(d)
        return success(public(d))


@bp.post("/networks/<network_id>/devices/<device_id>/activate")
@require_auth(roles={"ControlOperator"})
def activate_device(network_id, device_id):
    n = get_network(network_id)
    d = get_device(network_id, device_id)
    if d.get("status") != "PROVISIONED":
        raise err("ERR_INVALID_STATE", "device is not PROVISIONED")
    # Re-validate config
    _validate_device_config(d.get("polling_interval_s"), d.get("valid_range_min"), d.get("valid_range_max"))
    av = active_topology_id(n)
    nc = d.get("mounted_on_node_code")
    if not nc or not av or not find_node_in_version(av, nc):
        raise err("ERR_DEVICE_UNMOUNTED", "mounted_on_node_code missing in active topology")
    with lock():
        d["status"] = "ACTIVE"
        stamp_update(d)
        return success(public(d))


@bp.post("/networks/<network_id>/devices/<device_id>/decommission")
@require_auth(roles={"ControlOperator"})
def decommission_device(network_id, device_id):
    d = get_device(network_id, device_id)
    cur = d.get("status")
    if cur not in ("ACTIVE", "OFFLINE"):
        raise err("ERR_INVALID_STATE", "device cannot be decommissioned")
    if cur == "ACTIVE":
        for a in alerts.values():
            if (
                a.get("trigger_device_id") == device_id
                and a.get("status") in ("OPEN", "ACKNOWLEDGED")
            ):
                raise err("ERR_INVALID_STATE", "open/acknowledged alert exists for this device")
    with lock():
        d["status"] = "DECOMMISSIONED"
        stamp_update(d)
        if cur == "ACTIVE":
            # Cascade: non-terminal LeakInvestigations whose alert.trigger_device_id == this
            # and whose status in {OPEN, NARROWED} -> FALSE_POSITIVE.
            for inv in investigations.values():
                a = alerts.get(inv.get("alert_id") or "")
                if not a or a.get("trigger_device_id") != device_id:
                    continue
                if inv.get("status") in ("OPEN", "NARROWED"):
                    inv["status"] = "FALSE_POSITIVE"
                    stamp_update(inv)
        return success(public(d))


@bp.post("/networks/<network_id>/devices/<device_id>/readings")
@require_auth(roles={"ControlOperator"})
def post_reading(network_id, device_id):
    n = get_network(network_id)
    d = get_device(network_id, device_id)
    if d.get("status") == "DECOMMISSIONED":
        raise err("ERR_INVALID_STATE", "device is decommissioned")
    body = get_json_body()
    strict_mode_param = request.args.get("strict_mode")
    strict_mode = str(strict_mode_param).lower() == "true" if strict_mode_param else False
    with lock():
        row, status, replay_err = ingest_reading(n, d, body, strict_mode)
        if replay_err == "ERR_DUPLICATE_READING":
            # PRD §3.4 idempotency: HTTP 200, the response surfaces the existing
            # reading as data and signals the replay via ERR_DUPLICATE_READING.
            # Per PRD §2.2 the error envelope's id lives under `data.error_id`,
            # so embed the replay signal there alongside the original reading.
            from flask import jsonify
            from response import _meta_base
            meta = _meta_base()
            data_payload = dict(public(row))
            data_payload["error_id"] = "ERR_DUPLICATE_READING"
            body_out = {
                "meta": meta,
                "response_type": "object",
                "data": data_payload,
            }
            return jsonify(body_out), 200
        return success(public(row), status)


@bp.get("/networks/<network_id>/devices/<device_id>/readings")
@require_auth(roles={"ControlOperator", "Auditor"})
def list_readings(network_id, device_id):
    d = get_device(network_id, device_id)
    tier_filter = request.args.get("archive_tier")
    limit, offset = get_pagination()
    rows = [r for r in readings.values() if r.get("device_id") == device_id]
    if tier_filter:
        rows = [r for r in rows if r.get("archive_tier") == tier_filter]
    rows.sort(key=lambda r: r.get("created_at") or "")
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)
