"""Equipment ledger endpoints: stations, arrays, strings, modules, inverters, transformers."""
from __future__ import annotations

from flask import Blueprint, current_app, request

from pv_ops.auth import require_roles
from pv_ops.errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_UNIQUE_VIOLATION,
    ERR_VALIDATION,
)
from pv_ops.responses import created, listed, success
from pv_ops.services import serializers
from pv_ops.services.cascades import (
    recompute_array_string_count,
    recompute_station_operational_status,
    recompute_string_rated_dc,
)
from pv_ops.store import paginate
from pv_ops.utils import (
    fmt_dt,
    get_body,
    opt_bool,
    opt_str,
    opt_enum,
    opt_number,
    opt_int,
    parse_dt,
    parse_pagination,
    require_enum,
    require_int,
    require_list,
    require_number,
    require_str,
)


bp = Blueprint("equipment", __name__)


# ---- Stations ----
@bp.route("/pv-ops/stations", methods=["POST"])
@require_roles("PlatformAdmin")
def create_station():
    body = get_body()
    name = require_str(body, "name", min_len=1, max_len=120)
    installed = require_number(body, "installed_capacity_kw", ge=0.000001, le=1_000_000.0)
    ac = require_number(body, "ac_capacity_kw", ge=0.000001)
    if ac > installed * 1.2:
        raise APIError(ERR_VALIDATION, 422, "ac_capacity_kw exceeds installed_capacity_kw * 1.2")
    commissioning = parse_dt(body.get("commissioning_date"), "commissioning_date")
    lat = require_number(body, "latitude", ge=-90.0, le=90.0)
    lng = require_number(body, "longitude", ge=-180.0, le=180.0)
    grid_company = require_str(body, "grid_company")
    fit = require_number(body, "feed_in_tariff_cny_per_kwh", ge=0.0)
    market_enabled = opt_bool(body, "market_trading_enabled", default=False)

    store = current_app.extensions["store"]
    with store.lock:
        for s in store.stations.values():
            if s.get("name", "").lower() == name.lower():
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Station name already exists")
        row = {
            "name": name,
            "installed_capacity_kw": float(round(installed, 3)),
            "ac_capacity_kw": float(ac),
            "commissioning_date": fmt_dt(commissioning),
            "latitude": float(lat),
            "longitude": float(lng),
            "grid_company": grid_company,
            "feed_in_tariff_cny_per_kwh": float(round(fit, 4)),
            "market_trading_enabled": market_enabled,
            "operational_status": "OPERATIONAL",
            "lifecycle_state": "ACTIVE",
        }
        store.insert_common(row)
        store.stations[row["id"]] = row
        return created(serializers.station_view(row))


@bp.route("/pv-ops/stations", methods=["GET"])
@require_roles("PlatformAdmin", "O&MEngineer", "FinanceOfficer", "FieldOperator")
def list_stations():
    store = current_app.extensions["store"]
    limit, offset = parse_pagination(request.args)
    lifecycle = request.args.get("lifecycle_state")
    with store.lock:
        rows = list(store.stations.values())
        if lifecycle:
            rows = [r for r in rows if r.get("lifecycle_state") == lifecycle]
        rows.sort(key=lambda r: r["created_at"])
        page, total, has_more = paginate(rows, limit, offset)
        return listed(
            [serializers.station_view(r) for r in page],
            limit=limit,
            offset=offset,
            total_count=total,
            has_more=has_more,
        )


@bp.route("/pv-ops/stations/<station_id>", methods=["GET"])
@require_roles("PlatformAdmin", "O&MEngineer", "FinanceOfficer", "FieldOperator")
def get_station(station_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        row = store.stations.get(station_id)
        if not row:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        return success(serializers.station_view(row))


# ---- Arrays ----
@bp.route("/pv-ops/stations/<station_id>/arrays", methods=["POST"])
@require_roles("PlatformAdmin")
def create_array(station_id: str):
    body = get_body()
    code = require_str(body, "code", min_len=1, max_len=32)
    tilt = require_number(body, "tilt_angle_deg", ge=0.0, le=90.0)
    azimuth = require_number(body, "azimuth_deg", ge=0.0, le=360.0)
    store = current_app.extensions["store"]
    with store.lock:
        if station_id not in store.stations:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        for a in store.arrays.values():
            if a.get("station_id") == station_id and a.get("code") == code:
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Array code already exists in station")
        row = {
            "station_id": station_id,
            "code": code,
            "tilt_angle_deg": float(tilt),
            "azimuth_deg": float(azimuth),
            "string_count": 0,
        }
        store.insert_common(row)
        store.arrays[row["id"]] = row
        return created(serializers.array_view(row))


# ---- Strings (PVString) ----
@bp.route("/pv-ops/arrays/<array_id>/strings", methods=["POST"])
@require_roles("PlatformAdmin")
def create_string(array_id: str):
    body = get_body()
    code = require_str(body, "code")
    module_count = require_int(body, "module_count", ge=1, le=40)
    inverter_id = require_str(body, "inverter_id")
    combiner_box_id = opt_str(body, "combiner_box_id")
    store = current_app.extensions["store"]
    with store.lock:
        array = store.arrays.get(array_id)
        if not array:
            raise APIError(ERR_NOT_FOUND, 404, "Array not found")
        inverter = store.inverters.get(inverter_id)
        if not inverter:
            raise APIError(ERR_NOT_FOUND, 404, "Inverter not found")
        if combiner_box_id is not None:
            cb = store.inverters.get(combiner_box_id)
            if not cb:
                raise APIError(ERR_NOT_FOUND, 404, "Combiner box not found")
        for s in store.strings.values():
            if s.get("array_id") == array_id and s.get("code") == code:
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "String code already exists")
        row = {
            "array_id": array_id,
            "code": code,
            "module_count": module_count,
            "inverter_id": inverter_id,
            "combiner_box_id": combiner_box_id,
            "rated_dc_power_kw": 0.0,
        }
        store.insert_common(row)
        store.strings[row["id"]] = row
        recompute_array_string_count(store, array)
        store.bump(array)
        return created(serializers.pvstring_view(row))


# ---- Modules ----
@bp.route("/pv-ops/strings/<string_id>/modules", methods=["POST"])
@require_roles("PlatformAdmin")
def create_module(string_id: str):
    body = get_body()
    serial = require_str(body, "serial_no")
    wp = require_number(body, "wp_rating", ge=0.000001, le=1000.0)
    manufacturer = require_str(body, "manufacturer")
    warranty_supplier_id = require_str(body, "warranty_supplier_id")
    warranty_until = parse_dt(body.get("warranty_until"), "warranty_until")
    store = current_app.extensions["store"]
    with store.lock:
        pvstring = store.strings.get(string_id)
        if not pvstring:
            raise APIError(ERR_NOT_FOUND, 404, "String not found")
        if warranty_supplier_id not in store.suppliers:
            raise APIError(ERR_NOT_FOUND, 404, "Supplier not found")
        for m in store.modules.values():
            if m.get("serial_no") == serial:
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Module serial_no must be unique")
        row = {
            "string_id": string_id,
            "serial_no": serial,
            "wp_rating": float(wp),
            "manufacturer": manufacturer,
            "warranty_supplier_id": warranty_supplier_id,
            "warranty_until": fmt_dt(warranty_until),
            "lifecycle_state": "INSTALLED",
        }
        store.insert_common(row)
        store.modules[row["id"]] = row
        recompute_string_rated_dc(store, pvstring)
        store.bump(pvstring)
        return created(serializers.module_view(row))


# ---- Inverters / Combiner boxes ----
@bp.route("/pv-ops/inverters", methods=["POST"])
@require_roles("PlatformAdmin")
def create_inverter():
    body = get_body()
    station_id = require_str(body, "station_id")
    array_id = opt_str(body, "array_id")
    role = require_enum(body, "role", {"INVERTER", "COMBINER_BOX"})
    model = require_str(body, "model")
    vendor = require_str(body, "vendor")
    serial = require_str(body, "serial_no")
    rated = require_number(body, "rated_ac_power_kw", ge=0.0)
    warranty_supplier_id = require_str(body, "warranty_supplier_id")
    warranty_until = parse_dt(body.get("warranty_until"), "warranty_until")
    store = current_app.extensions["store"]
    with store.lock:
        station = store.stations.get(station_id)
        if not station:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        if array_id is not None and array_id not in store.arrays:
            raise APIError(ERR_NOT_FOUND, 404, "Array not found")
        if warranty_supplier_id not in store.suppliers:
            raise APIError(ERR_NOT_FOUND, 404, "Supplier not found")
        for inv in store.inverters.values():
            if inv.get("serial_no") == serial:
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Inverter serial_no must be unique")
        row = {
            "station_id": station_id,
            "array_id": array_id,
            "role": role,
            "model": model,
            "vendor": vendor,
            "serial_no": serial,
            "rated_ac_power_kw": float(rated),
            "warranty_supplier_id": warranty_supplier_id,
            "warranty_until": fmt_dt(warranty_until),
            "lifecycle_state": "OPERATING",
        }
        store.insert_common(row)
        store.inverters[row["id"]] = row
        # New inverter affects station status
        recompute_station_operational_status(store, station)
        return created(serializers.inverter_view(row))


@bp.route("/pv-ops/inverters/<inverter_id>", methods=["GET"])
@require_roles("PlatformAdmin", "O&MEngineer", "FieldOperator")
def get_inverter(inverter_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        inv = store.inverters.get(inverter_id)
        if not inv:
            raise APIError(ERR_NOT_FOUND, 404, "Inverter not found")
        return success(serializers.inverter_view(inv))


# ---- Transformers ----
@bp.route("/pv-ops/stations/<station_id>/transformers", methods=["POST"])
@require_roles("PlatformAdmin")
def create_transformer(station_id: str):
    body = get_body()
    code = require_str(body, "code")
    rated_kva = require_number(body, "rated_capacity_kva", ge=0.000001)
    primary = require_number(body, "primary_voltage_kv")
    secondary = require_number(body, "secondary_voltage_kv")
    gcpn = require_str(body, "grid_connection_point_no")
    warranty_supplier_id = require_str(body, "warranty_supplier_id")
    warranty_until = parse_dt(body.get("warranty_until"), "warranty_until")
    store = current_app.extensions["store"]
    with store.lock:
        if station_id not in store.stations:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        if warranty_supplier_id not in store.suppliers:
            raise APIError(ERR_NOT_FOUND, 404, "Supplier not found")
        for t in store.transformers.values():
            if t.get("station_id") == station_id and t.get("code") == code:
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Transformer code must be unique per station")
            if t.get("grid_connection_point_no") == gcpn:
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "grid_connection_point_no must be unique")
        row = {
            "station_id": station_id,
            "code": code,
            "rated_capacity_kva": float(rated_kva),
            "primary_voltage_kv": float(primary),
            "secondary_voltage_kv": float(secondary),
            "grid_connection_point_no": gcpn,
            "warranty_supplier_id": warranty_supplier_id,
            "warranty_until": fmt_dt(warranty_until),
        }
        store.insert_common(row)
        store.transformers[row["id"]] = row
        return created(serializers.transformer_view(row))
