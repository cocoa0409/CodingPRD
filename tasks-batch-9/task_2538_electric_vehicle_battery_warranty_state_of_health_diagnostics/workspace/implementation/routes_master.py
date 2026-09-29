"""Programs, vehicles, service centers, technicians, packs, modules, snapshots, clock."""
from flask import Blueprint, request

import calc
import cascade
from common import (API_PREFIX, ApiError, D, R_ADMIN, R_GATEWAY, READ_ROLES,
                    READ_ROLES_GW, auth, by_created, db, get_body, invalid, iso,
                    must, fk, new_record, event_record, now, ok, ok_list, opt_bool,
                    opt_dec, opt_dt, opt_enum, opt_id, opt_int, opt_str, page,
                    pagination, present, refresh_technician, req_dec, req_dt,
                    req_enum, req_int, req_str, rhu, touch, pack_modules,
                    vehicle_snapshots, center_technicians)

bp = Blueprint("master", __name__, url_prefix=API_PREFIX)

CERT_LEVELS = ("L1", "L2", "L3")
PACK_TYPES = ("NEW", "REMANUFACTURED")


def _filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def _bool_arg(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise invalid("%s must be a boolean." % name)


# =========================================================== warranty programs
def _retention_schedule(body, coverage_months, coverage_miles):
    if not present(body, "retention_schedule"):
        rows = [
            {"through_months": 48, "through_miles": 50000, "min_retention_pct": D("80.00")},
            {"through_months": 96, "through_miles": 100000, "min_retention_pct": D("70.00")},
        ]
    else:
        raw = body["retention_schedule"]
        if not isinstance(raw, list) or len(raw) < 1 or len(raw) > 4:
            raise invalid("retention_schedule must hold between one and four rows.")
        rows = []
        for item in raw:
            if not isinstance(item, dict):
                raise invalid("retention_schedule rows must be objects.")
            months = req_int(item, "through_months", minimum=0)
            miles = req_int(item, "through_miles", minimum=0)
            pct = req_dec(item, "min_retention_pct", 2, minimum="50.00", maximum="95.00")
            rows.append({"through_months": months, "through_miles": miles,
                         "min_retention_pct": pct})
    rows.sort(key=lambda r: r["through_months"])
    last = rows[-1]
    if last["through_months"] != coverage_months or last["through_miles"] != coverage_miles:
        raise invalid("The final retention_schedule row must close on coverage_months "
                      "and coverage_miles.")
    return rows


@bp.route("/warranty-programs", methods=["POST"])
def create_program():
    auth((R_ADMIN,))
    body = get_body()
    name = req_str(body, "name")
    coverage_months = opt_int(body, "coverage_months", 96, minimum=60, maximum=144)
    coverage_miles = opt_int(body, "coverage_miles", 100000, minimum=50000, maximum=200000)
    schedule = _retention_schedule(body, coverage_months, coverage_miles)
    record = new_record()
    record.update({
        "name": name,
        "coverage_months": coverage_months,
        "coverage_miles": coverage_miles,
        "retention_schedule": schedule,
        "pack_replacement_retention_pct": opt_dec(body, "pack_replacement_retention_pct", 2, D("60.00"), minimum=0, maximum=100),
        "module_replacement_cap": opt_int(body, "module_replacement_cap", 3, minimum=0),
        "goodwill_months": opt_int(body, "goodwill_months", 12, minimum=0),
        "goodwill_miles": opt_int(body, "goodwill_miles", 15000, minimum=0),
        "diagnostic_fee_cents": opt_int(body, "diagnostic_fee_cents", 12000, minimum=0),
        "module_unit_price_cents": opt_int(body, "module_unit_price_cents", 145000, minimum=0),
        "pack_price_new_cents": opt_int(body, "pack_price_new_cents", 1420000, minimum=0),
        "pack_price_reman_cents": opt_int(body, "pack_price_reman_cents", 890000, minimum=0),
        "labor_hours_module": opt_dec(body, "labor_hours_module", 2, D("3.25"), minimum=0),
        "labor_hours_pack": opt_dec(body, "labor_hours_pack", 2, D("6.50"), minimum=0),
        "surcharge_un3480_cents": opt_int(body, "surcharge_un3480_cents", 4000, minimum=0),
        "surcharge_un3481_cents": opt_int(body, "surcharge_un3481_cents", 2500, minimum=0),
        "surcharge_un3536_cents": opt_int(body, "surcharge_un3536_cents", 18000, minimum=0),
        "snapshot_min_count": opt_int(body, "snapshot_min_count", 3, minimum=1),
        "snapshot_window_size": opt_int(body, "snapshot_window_size", 5, minimum=1),
        "snapshot_freshness_days": opt_int(body, "snapshot_freshness_days", 30, minimum=1),
        "cell_delta_pack_threshold_mv": opt_int(body, "cell_delta_pack_threshold_mv", 250, minimum=0),
        "info_request_limit": opt_int(body, "info_request_limit", 2, minimum=0),
        "reman_min_soh_pct": opt_dec(body, "reman_min_soh_pct", 2, D("85.00"), minimum=0, maximum=100),
        "allow_new_pack_substitution": opt_bool(body, "allow_new_pack_substitution", False),
        "liability_cap_cents": opt_int(body, "liability_cap_cents", 50000000, minimum=0),
        "lab_tolerance_pct": opt_dec(body, "lab_tolerance_pct", 2, D("2.00"), minimum=0),
        "dispute_window_days": opt_int(body, "dispute_window_days", 30, minimum=0),
        "accrued_liability_cents": 0,
        "reman_available_count": 0,
        "reman_stock_state": "DEPLETED",
    })
    db.programs[record["id"]] = record
    # Seed the two mirrors from current state without counting as a mutation:
    # a freshly created program reads 0 / DEPLETED on an empty store.
    count = len([p for p in db.packs.values()
                 if p["pack_type"] == "REMANUFACTURED" and p["status"] == "STOCK"])
    record["reman_available_count"] = count
    record["reman_stock_state"] = "DEPLETED" if count == 0 else "AVAILABLE"
    return ok(record, 201)


@bp.route("/warranty-programs/<program_id>", methods=["GET"])
def get_program(program_id):
    auth(READ_ROLES)
    return ok(must("programs", program_id))


# ==================================================================== vehicles
VIN_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


@bp.route("/vehicles", methods=["POST"])
def create_vehicle():
    auth((R_ADMIN,))
    body = get_body()
    vin = req_str(body, "vin")
    if len(vin) != 17 or any(ch not in VIN_ALLOWED for ch in vin):
        raise invalid("vin must be exactly 17 uppercase alphanumeric characters.")
    program_id = req_str(body, "warranty_program_id")
    in_service_date = req_dt(body, "in_service_date")
    model_code = opt_str(body, "model_code", "MX-90")
    region_code = opt_str(body, "region_code", "US-WEST")
    email = opt_str(body, "owner_contact_email", "owner@example.com")
    odometer = opt_int(body, "odometer_miles", 0, minimum=0)
    fk("programs", program_id)
    if in_service_date > now():
        raise invalid("in_service_date must not be later than the current logical clock.")
    for existing in db.vehicles.values():
        if existing["vin"] == vin:
            raise ApiError("ERR_DUPLICATE_VIN", 409, "vin %s is already registered." % vin)
    record = new_record()
    record.update({
        "vin": vin,
        "model_code": model_code,
        "region_code": region_code,
        "warranty_program_id": program_id,
        "in_service_date": in_service_date,
        "owner_contact_email": email,
        # PRD 3.1: an `odometer_miles` figure may be supplied at registration, but the
        # field is thereafter derived from VALID snapshots and "reads 0 while the
        # vehicle has no valid snapshot at all".
        "odometer_miles": 0,
        "installed_pack_id": None,
        "warranty_hold": False,
        "status": "ACTIVE",
    })
    db.vehicles[record["id"]] = record
    return ok(record, 201)


@bp.route("/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    auth(READ_ROLES)
    return ok(must("vehicles", vehicle_id))


@bp.route("/vehicles", methods=["GET"])
def list_vehicles():
    auth(READ_ROLES)
    limit, offset = pagination()
    rows = by_created(list(db.vehicles.values()))
    rows = _filter_eq(rows, "warranty_program_id", request.args.get("warranty_program_id"))
    rows = _filter_eq(rows, "status", request.args.get("status"))
    rows = _filter_eq(rows, "model_code", request.args.get("model_code"))
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# ============================================================= service centers
@bp.route("/service-centers", methods=["POST"])
def create_center():
    auth((R_ADMIN,))
    body = get_body()
    record = new_record()
    record.update({
        "name": req_str(body, "name"),
        "region_code": opt_str(body, "region_code", "US-WEST"),
        "hv_certification_level": opt_enum(body, "hv_certification_level", CERT_LEVELS, "L3"),
        "has_pack_lift": opt_bool(body, "has_pack_lift", False),
        "insulation_tester_cal_due_at": opt_dt(body, "insulation_tester_cal_due_at")
        or _default_dt("2027-01-01T00:00:00Z"),
        "hv_bay_count": opt_int(body, "hv_bay_count", 2, minimum=1, maximum=6),
        "labor_rate_cents_per_hour": opt_int(body, "labor_rate_cents_per_hour", 18333, minimum=0),
        "status": "ACTIVE",
        "open_hazmat_holds": 0,
        "rejected_shipment_count": 0,
        "late_notification_count": 0,
        "compliance_score": 100,
    })
    db.centers[record["id"]] = record
    return ok(record, 201)


def _default_dt(text):
    from common import parse_dt
    return parse_dt(text)


@bp.route("/service-centers/<center_id>", methods=["GET"])
def get_center(center_id):
    auth(READ_ROLES)
    return ok(must("centers", center_id))


@bp.route("/service-centers", methods=["GET"])
def list_centers():
    auth(READ_ROLES)
    limit, offset = pagination()
    rows = by_created(list(db.centers.values()))
    rows = _filter_eq(rows, "region_code", request.args.get("region_code"))
    rows = _filter_eq(rows, "status", request.args.get("status"))
    rows = _filter_eq(rows, "hv_certification_level",
                      request.args.get("hv_certification_level"))
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# ================================================================= technicians
@bp.route("/service-centers/<center_id>/technicians", methods=["POST"])
def create_technician(center_id):
    auth((R_ADMIN,))
    body = get_body()
    full_name = req_str(body, "full_name")
    level = opt_enum(body, "hv_cert_level", CERT_LEVELS, "L3")
    expires = opt_dt(body, "cert_expires_at") or _default_dt("2027-06-01T00:00:00Z")
    must("centers", center_id)
    record = new_record()
    record.update({
        "service_center_id": center_id,
        "full_name": full_name,
        "hv_cert_level": level,
        "cert_expires_at": expires,
        "status": "ACTIVE",
        "last_hv_window_end_at": None,
    })
    refresh_technician(record)
    db.technicians[record["id"]] = record
    return ok(record, 201)


@bp.route("/service-centers/<center_id>/technicians", methods=["GET"])
def list_technicians(center_id):
    auth(READ_ROLES)
    limit, offset = pagination()
    must("centers", center_id)
    rows = center_technicians(center_id)
    for tech in rows:
        refresh_technician(tech)
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# =============================================================== battery packs
@bp.route("/battery-packs", methods=["POST"])
def create_pack():
    auth((R_ADMIN,))
    body = get_body()
    serial = req_str(body, "serial_number")
    pack_type = opt_enum(body, "pack_type", PACK_TYPES, "NEW")
    nominal = opt_dec(body, "nominal_capacity_kwh", 3, D("80.000"), exclusive_min=0)
    module_count = opt_int(body, "module_count", 16, minimum=8, maximum=24)
    gross = opt_dec(body, "gross_weight_kg", 3, D("483.296"), minimum=0)
    stock_region = opt_str(body, "stock_region_code", "US-WEST")
    refurb = opt_dec(body, "refurb_soh_pct", 2, None, minimum=0, maximum=100)
    if pack_type == "REMANUFACTURED" and refurb is None:
        raise invalid("refurb_soh_pct is required for a REMANUFACTURED pack.")
    if pack_type == "NEW" and refurb is not None:
        raise invalid("refurb_soh_pct must be absent for a NEW pack.")
    reman_count = opt_int(body, "remanufacture_count", 0, minimum=0)
    installed_vehicle_id = opt_id(body, "installed_vehicle_id")
    superseded_pack_id = opt_id(body, "superseded_pack_id")
    vehicle = fk("vehicles", installed_vehicle_id)
    fk("packs", superseded_pack_id)
    for existing in db.packs.values():
        if existing["serial_number"] == serial:
            raise ApiError("ERR_DUPLICATE_PACK_SERIAL", 409,
                           "serial_number %s is already registered." % serial)
    if vehicle is not None and vehicle["installed_pack_id"] is not None:
        raise ApiError("ERR_VEHICLE_ALREADY_HAS_PACK", 409,
                       "Vehicle %s already carries an installed pack." % vehicle["id"])
    record = new_record()
    record.update({
        "serial_number": serial,
        "pack_type": pack_type,
        "nominal_capacity_kwh": nominal,
        "module_count": module_count,
        "gross_weight_kg": gross,
        "stock_region_code": stock_region,
        "refurb_soh_pct": refurb,
        "remanufacture_count": reman_count,
        "installed_vehicle_id": installed_vehicle_id,
        "superseded_pack_id": superseded_pack_id,
        "status": "IN_SERVICE" if vehicle is not None else "STOCK",
        "hazmat_classification": None,
        "damaged_defective": False,
        "module_replacements_to_date": 0,
        "faulted_module_count": 0,
    })
    db.packs[record["id"]] = record
    per_module = rhu(D(nominal) / D(module_count), 3)
    for position in range(1, module_count + 1):
        module = new_record()
        module.update({
            "pack_id": record["id"],
            "position_index": position,
            "module_capacity_kwh": per_module,
            "status": "HEALTHY",
            "cell_delta_mv": 0,
            "thermal_runaway_flag": False,
            "replaced_at": None,
        })
        db.modules[module["id"]] = module
    if vehicle is not None:
        vehicle["installed_pack_id"] = record["id"]
        record["_last_vehicle_id"] = vehicle["id"]
        touch(vehicle)
    if pack_type == "REMANUFACTURED" and record["status"] == "STOCK":
        cascade.refresh_reman_stock()
    return ok(record, 201)


@bp.route("/battery-packs/<pack_id>", methods=["GET"])
def get_pack(pack_id):
    auth(READ_ROLES)
    return ok(must("packs", pack_id))


@bp.route("/battery-packs", methods=["GET"])
def list_packs():
    auth(READ_ROLES)
    limit, offset = pagination()
    rows = by_created(list(db.packs.values()))
    rows = _filter_eq(rows, "installed_vehicle_id", request.args.get("installed_vehicle_id"))
    rows = _filter_eq(rows, "superseded_pack_id", request.args.get("superseded_pack_id"))
    rows = _filter_eq(rows, "status", request.args.get("status"))
    rows = _filter_eq(rows, "pack_type", request.args.get("pack_type"))
    rows = _filter_eq(rows, "stock_region_code", request.args.get("stock_region_code"))
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/battery-packs/<pack_id>/modules", methods=["GET"])
def list_modules(pack_id):
    auth(READ_ROLES)
    limit, offset = pagination()
    must("packs", pack_id)
    rows = pack_modules(pack_id)
    rows = _filter_eq(rows, "status", request.args.get("status"))
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# ========================================================= telematics ingest
@bp.route("/vehicles/<vehicle_id>/telematics-snapshots", methods=["POST"])
def create_snapshot(vehicle_id):
    auth((R_GATEWAY,))
    body = get_body()
    captured_at = req_dt(body, "captured_at")
    odometer = req_int(body, "odometer_miles", minimum=0)
    reported = req_dec(body, "reported_capacity_kwh", 3)
    charge_cycles = opt_int(body, "charge_cycles", 400, minimum=0)
    max_delta = opt_int(body, "max_cell_delta_mv", 40, minimum=0)
    # PRD 2.5 declares no decimal scale for `coolant_temp_c`, and PRD 3.2 turns on
    # "anything even fractionally above 35.0", so the reading is not quantized.
    coolant = opt_dec(body, "coolant_temp_c", None, D("20.0"))
    dcfc = opt_int(body, "dcfc_session_count", 0, minimum=0)
    vehicle = must("vehicles", vehicle_id)
    pack = db.packs.get(vehicle["installed_pack_id"]) if vehicle["installed_pack_id"] else None
    flag = calc.snapshot_validity(vehicle, pack, captured_at, odometer, reported)
    record = event_record()
    record.update({
        "vehicle_id": vehicle_id,
        "captured_at": captured_at,
        "odometer_miles": odometer,
        "reported_capacity_kwh": reported,
        "charge_cycles": charge_cycles,
        "max_cell_delta_mv": max_delta,
        "coolant_temp_c": coolant,
        "dcfc_session_count": dcfc,
        "validity_flag": flag,
        "corrected_capacity_kwh": calc.corrected_capacity(reported, coolant),
    })
    db.snapshots[record["id"]] = record
    if flag == "VALID":
        derived = calc.derive_vehicle_odometer(vehicle_id)
        if derived != vehicle["odometer_miles"]:
            # PRD 2.4: recomputing a derived field counts as a mutation, so the
            # vehicle's `updated_at` refreshes and its `version` increments -- which
            # is exactly what PRD 2.6 relies on to stale an assessment writer's token.
            vehicle["odometer_miles"] = derived
            touch(vehicle)
    return ok(record, 201)


@bp.route("/vehicles/<vehicle_id>/telematics-snapshots", methods=["GET"])
def list_snapshots(vehicle_id):
    auth(READ_ROLES_GW)
    limit, offset = pagination()
    must("vehicles", vehicle_id)
    rows = vehicle_snapshots(vehicle_id)
    rows = _filter_eq(rows, "validity_flag", request.args.get("validity_flag"))
    rows = sorted(rows, key=lambda s: (s["captured_at"], s["_seq"]), reverse=True)
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# ================================================================ logical clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth((R_ADMIN,))
    body = get_body()
    current_utc = req_dt(body, "current_utc")
    if current_utc < db.clock:
        raise ApiError("ERR_CLOCK_REWIND_FORBIDDEN", 409,
                       "The logical clock never rewinds.")
    db.clock = current_utc
    return ok({}, 200)
