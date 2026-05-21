"""Vehicle routes: add / read / post telematics event (§3.1, §3.4)."""
from __future__ import annotations

import re

from flask import Blueprint

from ..auth import require_auth
from ..calculations import reconcile_telematics
from ..clock import iso_format, parse_iso
from ..common import as_int, as_string, bump, get_json_body, require_fields, stamp_new
from ..constants import VALID_BASE_JURISDICTIONS, VALID_VEHICLE_CLASSES
from ..errors import ApiError
from ..response import respond
from ..serializers import telematics_view, vehicle_view
from ..store import store


bp = Blueprint("vehicles", __name__, url_prefix="/vehicles")


_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


@bp.post("")
@require_auth("FleetManager")
def create_vehicle():
    body = get_json_body()
    require_fields(body, "vin", "vehicle_class", "model_year")
    vin = body["vin"]
    if not isinstance(vin, str) or not _VIN_RE.match(vin):
        raise ApiError("ERR_VALIDATION", "vin must be 17 chars [A-HJ-NPR-Z0-9]")
    vc = body["vehicle_class"]
    if vc not in VALID_VEHICLE_CLASSES:
        raise ApiError("ERR_VALIDATION", f"vehicle_class must be one of {sorted(VALID_VEHICLE_CLASSES)}")
    model_year = as_int(body["model_year"], "model_year", min_value=2000, max_value=2030)
    baseline = body.get("odometer_baseline_miles", 0)
    if baseline is None:
        baseline = 0
    baseline = as_int(baseline, "odometer_baseline_miles", min_value=0)

    with store.lock:
        for existing in store.vehicles.values():
            if existing.get("vin") == vin:
                raise ApiError("ERR_VALIDATION", "vin already exists")
        v = {
            "vin": vin,
            "vehicle_class": vc,
            "model_year": model_year,
            "odometer_baseline_miles": baseline,
            "odometer_current_miles": baseline,
            "vehicle_status": "AVAILABLE",
            "current_lease_id": None,
        }
        stamp_new(v)
        store.vehicles[v["id"]] = v
    return respond(vehicle_view(v), 201)


@bp.get("/<vehicle_id>")
@require_auth("FleetManager", "TaxAdmin", "ClaimAdjuster", "VendorOps")
def get_vehicle(vehicle_id: str):
    with store.lock:
        v = store.vehicles.get(vehicle_id)
        if v is None:
            raise ApiError("ERR_NOT_FOUND", "Vehicle not found")
        return respond(vehicle_view(v), 200)


@bp.post("/<vehicle_id>/telematics-events")
@require_auth("FleetManager", "VendorOps")
def post_telematics(vehicle_id: str):
    body = get_json_body()
    require_fields(body, "event_ts", "odometer_reading")
    try:
        event_ts = parse_iso(body["event_ts"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    reading = as_int(body["odometer_reading"], "odometer_reading", min_value=0)
    harsh = body.get("harsh_event_count", 0) or 0
    harsh = as_int(harsh, "harsh_event_count", min_value=0)
    fault_code = body.get("fault_code", "") or ""
    if not isinstance(fault_code, str):
        raise ApiError("ERR_VALIDATION", "fault_code must be a string")

    with store.lock:
        v = store.vehicles.get(vehicle_id)
        if v is None:
            raise ApiError("ERR_NOT_FOUND", "Vehicle not found")

        event = {
            "vehicle_id": vehicle_id,
            "event_ts": iso_format(event_ts),
            "odometer_reading": reading,
            "harsh_event_count": harsh,
            "fault_code": fault_code,
            "ingest_status": "ACCEPTED",
        }
        # Stamp id + created_at (immutable record — no version/updated_at per §2.4)
        stamp_new(event, with_common=False)

        ingest = reconcile_telematics(v, reading)
        event["ingest_status"] = ingest
        if ingest == "ACCEPTED":
            bump(v)

        store.telematics_events[event["id"]] = event
    return respond(telematics_view(event), 201)
