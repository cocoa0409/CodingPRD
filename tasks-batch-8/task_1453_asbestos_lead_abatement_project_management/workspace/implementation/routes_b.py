"""Routes: notifications, containments, air tests, manifests, facilities,
relocation units and records."""
from datetime import timedelta
from decimal import Decimal

from flask import request

from core import (
    app, DB,
    ApiError,
    authenticate, require_roles,
    body, req_field, as_str, as_enum, as_int, as_num, as_dt,
    new_record, touch, get_rec,
    ok, paginate, by_created, now, q2, q3, q4,
    NOTIFICATION_TYPES, CONTAINMENT_CLASSES, AIR_PHASES, MANIFEST_STATUSES, HAZARDS,
    BAG_TARE_LBS, LBS_PER_TON, PRESSURE_MAX_INWG, CLEARANCE_PASS_F_CC,
    UNIT_CLEANING_BUFFER,
    containment_of_project, machine_count, manifest_fee, facility_tons,
    reoccupancy,
    sync_facility_tons, sync_project_ledger, sync_reoccupancy,
    serialize_notification, serialize_containment, serialize_air_test,
    serialize_manifest, serialize_facility, serialize_unit, serialize_relocation,
)


# ------------------------------------------------------------------ notifications
@app.post("/abatement/notifications")
def create_notification():
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    data = body()
    project_id = as_str(req_field(data, "project_id"), "project_id")
    notification_type = as_enum(
        req_field(data, "notification_type"), "notification_type", NOTIFICATION_TYPES
    )
    declared = as_num(
        req_field(data, "declared_acm_sq_ft"), "declared_acm_sq_ft", gt=Decimal("0")
    )
    expected_version = as_int(
        req_field(data, "expected_project_version"), "expected_project_version"
    )
    project = get_rec("projects", project_id)
    if expected_version != project["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_project_version does not match the project's current version",
        )
    if project["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Project is not ASSESSED")
    for n in DB["notifications"].values():
        if n["project_id"] == project_id and n["status"] in ("FILED", "ACKNOWLEDGED"):
            n["status"] = "SUPERSEDED"
            touch(n)
    waiting_days = 3 if notification_type == "EMERGENCY" else 10
    filed_at = now()
    rec = new_record(
        "notifications",
        {
            "project_id": project_id,
            "notification_type": notification_type,
            "declared_acm_sq_ft": q2(declared),
            "filed_at": filed_at,
            "waiting_days": waiting_days,
            "earliest_start_at": filed_at + timedelta(days=waiting_days),
            "status": "FILED",
            "acknowledged_at": None,
        },
    )
    touch(project)
    return ok(serialize_notification(rec), 201)


@app.get("/abatement/projects/<pid>/notifications")
def list_project_notifications(pid):
    authenticate()
    get_rec("projects", pid)
    items = [n for n in DB["notifications"].values() if n["project_id"] == pid]
    items.sort(key=lambda n: (n["filed_at"], n["created_at"], n["_seq"]), reverse=True)
    return paginate([serialize_notification(n) for n in items])


@app.post("/abatement/notifications/<nid>/acknowledge")
def acknowledge_notification(nid):
    _, role = authenticate()
    require_roles(role, "RegulatorClerk")
    notification = get_rec("notifications", nid)
    if notification["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Notification is not FILED")
    notification["status"] = "ACKNOWLEDGED"
    notification["acknowledged_at"] = now()
    touch(notification)
    return ok(serialize_notification(notification))


# ------------------------------------------------------------------ containments
@app.post("/abatement/containments")
def create_containment():
    _, role = authenticate()
    require_roles(role, "Supervisor")
    data = body()
    project_id = as_str(req_field(data, "project_id"), "project_id")
    volume = as_num(
        req_field(data, "work_area_volume_cuft"), "work_area_volume_cuft", gt=Decimal("0")
    )
    containment_class = as_enum(
        req_field(data, "containment_class"), "containment_class", CONTAINMENT_CLASSES
    )
    project = get_rec("projects", project_id)
    if project["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Project is not ASSESSED")
    if containment_of_project(project_id) is not None:
        raise ApiError(
            "ERR_CONTAINMENT_ALREADY_EXISTS", 409, "Project already has a containment"
        )
    ach, machines = machine_count(volume, containment_class)
    rec = new_record(
        "containments",
        {
            "project_id": project_id,
            "work_area_volume_cuft": volume,
            "containment_class": containment_class,
            "air_changes_per_hour": ach,
            "machines_required": machines,
            "last_pressure_reading_inwg": None,
            "verified_by_user_id": None,
            "last_verified_at": None,
            "status": "DESIGNED",
        },
    )
    return ok(serialize_containment(rec), 201)


@app.get("/abatement/projects/<pid>/containments")
def list_project_containments(pid):
    authenticate()
    get_rec("projects", pid)
    items = [
        serialize_containment(c)
        for c in by_created(DB["containments"].values())
        if c["project_id"] == pid
    ]
    return paginate(items)


@app.post("/abatement/containments/<cid>/install")
def install_containment(cid):
    _, role = authenticate()
    require_roles(role, "Supervisor")
    containment = get_rec("containments", cid)
    if containment["status"] != "DESIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Containment is not DESIGNED")
    project = DB["projects"].get(containment["project_id"])
    if project is None or project["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Project is not ASSESSED")
    containment["status"] = "INSTALLED"
    touch(containment)
    return ok(serialize_containment(containment))


@app.post("/abatement/containments/<cid>/verify")
def verify_containment(cid):
    user_id, role = authenticate()
    require_roles(role, "Supervisor")
    data = body()
    pressure = as_num(
        req_field(data, "pressure_reading_inwg"), "pressure_reading_inwg"
    )
    containment = get_rec("containments", cid)
    if containment["status"] not in ("INSTALLED", "RECLEAN_REQUIRED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Containment is not INSTALLED or RECLEAN_REQUIRED",
        )
    if not pressure <= PRESSURE_MAX_INWG:
        raise ApiError(
            "ERR_PRESSURE_INSUFFICIENT",
            422,
            "pressure_reading_inwg must be at or below -0.020 inwg",
        )
    was_reclean = containment["status"] == "RECLEAN_REQUIRED"
    containment["last_pressure_reading_inwg"] = pressure
    containment["verified_by_user_id"] = user_id
    containment["last_verified_at"] = now()
    containment["status"] = "VERIFIED"
    touch(containment)
    project = DB["projects"].get(containment["project_id"])
    if project is not None:
        if was_reclean and project["status"] == "RECLEANING":
            project["status"] = "AWAITING_CLEARANCE"
            touch(project)
        sync_reoccupancy(project)
    return ok(serialize_containment(containment))


@app.post("/abatement/containments/<cid>/revise")
def revise_containment(cid):
    _, role = authenticate()
    require_roles(role, "Supervisor")
    data = body()
    expected_version = as_int(
        req_field(data, "expected_containment_version"), "expected_containment_version"
    )
    new_volume = None
    if "work_area_volume_cuft" in data and data["work_area_volume_cuft"] is not None:
        new_volume = as_num(
            data["work_area_volume_cuft"], "work_area_volume_cuft", gt=Decimal("0")
        )
    new_class = None
    if "containment_class" in data and data["containment_class"] is not None:
        new_class = as_enum(data["containment_class"], "containment_class", CONTAINMENT_CLASSES)
    containment = get_rec("containments", cid)
    if expected_version != containment["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_containment_version does not match the containment's current version",
        )
    if containment["status"] != "DESIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Containment is not DESIGNED")
    if new_volume is not None:
        containment["work_area_volume_cuft"] = new_volume
    if new_class is not None:
        containment["containment_class"] = new_class
    ach, machines = machine_count(
        containment["work_area_volume_cuft"], containment["containment_class"]
    )
    containment["air_changes_per_hour"] = ach
    containment["machines_required"] = machines
    touch(containment)
    return ok(serialize_containment(containment))


# ------------------------------------------------------------------ air tests
AIR_TEST_PHASE_GATES = {
    "BASELINE": ("ASSESSED",),
    "DAILY": ("IN_PROGRESS", "SUSPENDED", "RECLEANING"),
    "CLEARANCE": ("AWAITING_CLEARANCE",),
}


@app.post("/abatement/air-tests")
def create_air_test():
    _, role = authenticate()
    require_roles(role, "Supervisor", "IndustrialHygienist")
    data = body()
    project_id = as_str(req_field(data, "project_id"), "project_id")
    phase = as_enum(req_field(data, "phase"), "phase", AIR_PHASES)
    collected_raw = req_field(data, "collected_at")
    collected = as_dt(collected_raw, "collected_at")
    if phase == "CLEARANCE" and role != "IndustrialHygienist":
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE",
            403,
            "Only an IndustrialHygienist may collect a CLEARANCE air test",
        )
    project = get_rec("projects", project_id)
    if project["status"] not in AIR_TEST_PHASE_GATES[phase]:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Project status does not permit a {phase} air test",
        )
    rec = new_record(
        "air_tests",
        {
            "project_id": project_id,
            "phase": phase,
            "collected_at": collected_raw,
            "_collected_at": collected,
            "result_f_cc": None,
            "outcome": "NA",
            "result_recorded_by_user_id": None,
            "status": "COLLECTED",
        },
    )
    return ok(serialize_air_test(rec), 201)


@app.get("/abatement/projects/<pid>/air-tests")
def list_project_air_tests(pid):
    authenticate()
    get_rec("projects", pid)
    phase_filter = None
    raw_phase = request.args.get("phase")
    if raw_phase is not None:
        if raw_phase not in AIR_PHASES:
            raise ApiError("ERR_VALIDATION", 400, "phase filter is not a valid phase")
        phase_filter = raw_phase
    items = [
        t
        for t in by_created(DB["air_tests"].values())
        if t["project_id"] == pid and (phase_filter is None or t["phase"] == phase_filter)
    ]
    return paginate([serialize_air_test(t) for t in items])


@app.post("/abatement/air-tests/<tid>/result")
def record_air_test_result(tid):
    user_id, role = authenticate()
    require_roles(role, "IndustrialHygienist")
    data = body()
    result = as_num(req_field(data, "result_f_cc"), "result_f_cc", ge=Decimal("0"))
    test = get_rec("air_tests", tid)
    if test["status"] != "COLLECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Air test is not COLLECTED")
    project = DB["projects"].get(test["project_id"])
    if test["phase"] == "CLEARANCE":
        containment = containment_of_project(test["project_id"])
        if containment is not None and containment["verified_by_user_id"] == user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                409,
                "The hygienist recording a CLEARANCE result must differ from the containment verifier",
            )
    test["result_f_cc"] = result
    if test["phase"] == "CLEARANCE":
        test["outcome"] = "PASS" if q3(result) < CLEARANCE_PASS_F_CC else "FAIL"
    else:
        test["outcome"] = "NA"
    test["result_recorded_by_user_id"] = user_id
    test["status"] = "REPORTED"
    touch(test)
    if test["phase"] == "CLEARANCE" and test["outcome"] == "FAIL":
        containment = containment_of_project(test["project_id"])
        if containment is not None and containment["status"] == "VERIFIED":
            containment["status"] = "RECLEAN_REQUIRED"
            touch(containment)
        if project is not None and project["status"] == "AWAITING_CLEARANCE":
            project["status"] = "RECLEANING"
            touch(project)
            for r in DB["relocations"].values():
                if r["project_id"] == project["id"] and r["status"] == "HOUSED":
                    r["status"] = "EXTENDED"
                    r["extension_count"] += 1
                    touch(r)
    if test["phase"] == "CLEARANCE" and project is not None:
        sync_reoccupancy(project)
    return ok(serialize_air_test(test))


# ------------------------------------------------------------------ manifests
@app.post("/abatement/manifests")
def create_manifest():
    _, role = authenticate()
    require_roles(role, "Supervisor")
    data = body()
    project_id = as_str(req_field(data, "project_id"), "project_id")
    facility_id = as_str(req_field(data, "facility_id"), "facility_id")
    bags_count = as_int(req_field(data, "bags_count"), "bags_count", minimum=1)
    gross = as_num(req_field(data, "gross_weight_lbs"), "gross_weight_lbs", gt=Decimal("0"))
    project = get_rec("projects", project_id)
    get_rec("facilities", facility_id)
    if project["status"] not in ("IN_PROGRESS", "RECLEANING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Project is not IN_PROGRESS or RECLEANING",
        )
    net = q2(gross) - Decimal(bags_count) * BAG_TARE_LBS
    net = q2(net)
    if net <= 0:
        raise ApiError(
            "ERR_MANIFEST_WEIGHT_INVALID",
            422,
            "net_weight_lbs must be strictly positive",
        )
    net_tons = q4(net / LBS_PER_TON)
    rec = new_record(
        "manifests",
        {
            "project_id": project_id,
            "facility_id": facility_id,
            "bags_count": bags_count,
            "gross_weight_lbs": q2(gross),
            "net_weight_lbs": net,
            "net_tons": net_tons,
            "fee_cents": None,
            "sealed_by_user_id": None,
            "delivered_at": None,
            "reject_reason": None,
            "status": "DRAFT",
        },
    )
    return ok(serialize_manifest(rec), 201)


def _list_manifests(items):
    raw_status = request.args.get("status")
    if raw_status is not None:
        if raw_status not in MANIFEST_STATUSES:
            raise ApiError("ERR_VALIDATION", 400, "status filter is not a valid manifest status")
        items = [m for m in items if m["status"] == raw_status]
    return paginate([serialize_manifest(m) for m in by_created(items)])


@app.get("/abatement/projects/<pid>/manifests")
def list_project_manifests(pid):
    authenticate()
    get_rec("projects", pid)
    items = [m for m in DB["manifests"].values() if m["project_id"] == pid]
    return _list_manifests(items)


@app.get("/abatement/facilities/<fid>/manifests")
def list_facility_manifests(fid):
    authenticate()
    get_rec("facilities", fid)
    items = [m for m in DB["manifests"].values() if m["facility_id"] == fid]
    return _list_manifests(items)


@app.post("/abatement/manifests/<mid>/seal")
def seal_manifest(mid):
    user_id, role = authenticate()
    require_roles(role, "Supervisor")
    manifest = get_rec("manifests", mid)
    if manifest["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Manifest is not DRAFT")
    project = DB["projects"].get(manifest["project_id"])
    if project is None or project["status"] not in ("IN_PROGRESS", "RECLEANING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Project is not IN_PROGRESS or RECLEANING",
        )
    containment = containment_of_project(manifest["project_id"])
    if containment is None or containment["status"] not in ("VERIFIED", "RECLEAN_REQUIRED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Containment is not VERIFIED or RECLEAN_REQUIRED",
        )
    manifest["fee_cents"] = manifest_fee(manifest["net_tons"])
    manifest["sealed_by_user_id"] = user_id
    manifest["status"] = "SEALED"
    touch(manifest)
    sync_project_ledger(project)
    return ok(serialize_manifest(manifest))


@app.post("/abatement/manifests/<mid>/ship")
def ship_manifest(mid):
    _, role = authenticate()
    require_roles(role, "Supervisor")
    manifest = get_rec("manifests", mid)
    if manifest["status"] != "SEALED":
        raise ApiError("ERR_INVALID_STATE", 409, "Manifest is not SEALED")
    manifest["status"] = "IN_TRANSIT"
    touch(manifest)
    return ok(serialize_manifest(manifest))


def _facility_ownership(manifest, user_id):
    if manifest["facility_id"] != user_id:
        raise ApiError(
            "ERR_FACILITY_MISMATCH",
            403,
            "X-User-ID does not match the manifest's facility_id",
        )


@app.post("/abatement/manifests/<mid>/deliver")
def deliver_manifest(mid):
    user_id, role = authenticate()
    require_roles(role, "FacilityOperator")
    manifest = get_rec("manifests", mid)
    _facility_ownership(manifest, user_id)
    if manifest["status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", 409, "Manifest is not IN_TRANSIT")
    facility = DB["facilities"].get(manifest["facility_id"])
    if facility is None or facility["status"] != "APPROVED":
        raise ApiError("ERR_FACILITY_NOT_APPROVED", 409, "Facility is not APPROVED")
    project = DB["projects"].get(manifest["project_id"])
    accepted = set(facility["accepted_hazards"])
    hazard = project["hazard_class"] if project is not None else None
    if hazard == "MIXED":
        if not {"ASBESTOS", "LEAD"} <= accepted:
            raise ApiError(
                "ERR_FACILITY_HAZARD_MISMATCH",
                422,
                "Facility does not accept both ASBESTOS and LEAD",
            )
    elif hazard not in accepted:
        raise ApiError(
            "ERR_FACILITY_HAZARD_MISMATCH",
            422,
            "Facility does not accept the project's hazard class",
        )
    if facility_tons(facility["id"]) + manifest["net_tons"] > facility["monthly_capacity_tons"]:
        raise ApiError(
            "ERR_FACILITY_CAPACITY_EXCEEDED",
            422,
            "Facility monthly capacity would be exceeded",
        )
    manifest["delivered_at"] = now()
    manifest["status"] = "DELIVERED"
    touch(manifest)
    sync_facility_tons(facility)
    return ok(serialize_manifest(manifest))


@app.post("/abatement/manifests/<mid>/confirm")
def confirm_manifest(mid):
    user_id, role = authenticate()
    require_roles(role, "FacilityOperator")
    manifest = get_rec("manifests", mid)
    _facility_ownership(manifest, user_id)
    if manifest["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Manifest is not DELIVERED")
    manifest["status"] = "CONFIRMED"
    touch(manifest)
    project = DB["projects"].get(manifest["project_id"])
    if project is not None:
        sync_project_ledger(project, rollup=True)
    return ok(serialize_manifest(manifest))


@app.post("/abatement/manifests/<mid>/reject")
def reject_manifest(mid):
    user_id, role = authenticate()
    require_roles(role, "FacilityOperator")
    data = body()
    reason = as_str(req_field(data, "reason"), "reason")
    manifest = get_rec("manifests", mid)
    _facility_ownership(manifest, user_id)
    if manifest["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Manifest is not DELIVERED")
    manifest["reject_reason"] = reason
    manifest["status"] = "REJECTED"
    touch(manifest)
    facility = DB["facilities"].get(manifest["facility_id"])
    if facility is not None:
        sync_facility_tons(facility)
    project = DB["projects"].get(manifest["project_id"])
    if project is not None:
        sync_project_ledger(project)
    return ok(serialize_manifest(manifest))


@app.post("/abatement/manifests/<mid>/void")
def void_manifest(mid):
    _, role = authenticate()
    require_roles(role, "Supervisor", "ContractorAdmin")
    manifest = get_rec("manifests", mid)
    if manifest["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Manifest is not DRAFT or REJECTED"
        )
    manifest["status"] = "VOIDED"
    touch(manifest)
    project = DB["projects"].get(manifest["project_id"])
    if project is not None:
        sync_project_ledger(project)
    return ok(serialize_manifest(manifest))


# ------------------------------------------------------------------ facilities
@app.post("/abatement/facilities")
def create_facility():
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    data = body()
    name = as_str(req_field(data, "name"), "name")
    epa_id = as_str(req_field(data, "epa_id"), "epa_id")
    hazards_raw = req_field(data, "accepted_hazards")
    if not isinstance(hazards_raw, list) or len(hazards_raw) == 0:
        raise ApiError(
            "ERR_VALIDATION", 400, "accepted_hazards must be a non-empty array"
        )
    for member in hazards_raw:
        if member not in HAZARDS:
            raise ApiError(
                "ERR_VALIDATION",
                400,
                "accepted_hazards members must be ASBESTOS or LEAD",
            )
    capacity = as_num(
        req_field(data, "monthly_capacity_tons"), "monthly_capacity_tons", gt=Decimal("0")
    )
    rec = new_record(
        "facilities",
        {
            "name": name,
            "epa_id": epa_id,
            "accepted_hazards": list(hazards_raw),
            "monthly_capacity_tons": capacity,
            "delivered_tons_current_month": Decimal("0"),
            "status": "APPROVED",
        },
    )
    return ok(serialize_facility(rec), 201)


@app.get("/abatement/facilities/<fid>")
def get_facility(fid):
    authenticate()
    facility = get_rec("facilities", fid)
    return ok(serialize_facility(facility))


@app.post("/abatement/facilities/<fid>/suspend")
def suspend_facility(fid):
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    facility = get_rec("facilities", fid)
    if facility["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Facility is not APPROVED")
    facility["status"] = "SUSPENDED"
    touch(facility)
    for m in list(DB["manifests"].values()):
        if m["facility_id"] == fid and m["status"] == "IN_TRANSIT":
            m["status"] = "REJECTED"
            m["reject_reason"] = "FACILITY_SUSPENDED"
            touch(m)
            project = DB["projects"].get(m["project_id"])
            if project is not None:
                sync_project_ledger(project)
    sync_facility_tons(facility)
    return ok(serialize_facility(facility))


# ------------------------------------------------------------------ relocation units & records
@app.post("/abatement/relocation-units")
def create_unit():
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    data = body()
    unit_label = as_str(req_field(data, "unit_label"), "unit_label")
    capacity = as_int(req_field(data, "capacity_persons"), "capacity_persons", minimum=1)
    rec = new_record(
        "units",
        {
            "unit_label": unit_label,
            "capacity_persons": capacity,
            "status": "AVAILABLE",
            "cleaning_until": None,
        },
    )
    return ok(serialize_unit(rec), 201)


@app.get("/abatement/relocation-units/<uid>")
def get_unit(uid):
    authenticate()
    unit = get_rec("units", uid)
    return ok(serialize_unit(unit))


@app.post("/abatement/relocations")
def create_relocation():
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    data = body()
    project_id = as_str(req_field(data, "project_id"), "project_id")
    unit_id = as_str(req_field(data, "unit_id"), "unit_id")
    household_name = as_str(req_field(data, "household_name"), "household_name")
    persons = as_int(req_field(data, "persons"), "persons", minimum=1)
    move_out_raw = req_field(data, "move_out_at")
    move_out = as_dt(move_out_raw, "move_out_at")
    project = get_rec("projects", project_id)
    unit = get_rec("units", unit_id)
    if project["status"] not in ("ASSESSED", "IN_PROGRESS"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Project is not ASSESSED or IN_PROGRESS",
        )
    unit_available = unit["status"] == "AVAILABLE" or (
        unit["status"] == "CLEANING"
        and unit["cleaning_until"] is not None
        and move_out >= unit["cleaning_until"]
    )
    active_record = any(
        r["unit_id"] == unit_id and r["status"] in ("HOUSED", "EXTENDED")
        for r in DB["relocations"].values()
    )
    if not unit_available or active_record:
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", 409, "Relocation unit is not available")
    if persons > unit["capacity_persons"]:
        raise ApiError(
            "ERR_UNIT_CAPACITY_EXCEEDED",
            422,
            "persons exceeds the unit's capacity",
        )
    rec = new_record(
        "relocations",
        {
            "project_id": project_id,
            "unit_id": unit_id,
            "household_name": household_name,
            "persons": persons,
            "move_out_at": move_out_raw,
            "_move_out_at": move_out,
            "returned_at": None,
            "extension_count": 0,
            "status": "HOUSED",
        },
    )
    unit["status"] = "OCCUPIED"
    touch(unit)
    return ok(serialize_relocation(rec), 201)


@app.get("/abatement/projects/<pid>/relocations")
def list_project_relocations(pid):
    authenticate()
    get_rec("projects", pid)
    items = [
        serialize_relocation(r)
        for r in by_created(DB["relocations"].values())
        if r["project_id"] == pid
    ]
    return paginate(items)


@app.get("/abatement/relocation-units/<uid>/relocations")
def list_unit_relocations(uid):
    authenticate()
    get_rec("units", uid)
    items = [
        serialize_relocation(r)
        for r in by_created(DB["relocations"].values())
        if r["unit_id"] == uid
    ]
    return paginate(items)


@app.post("/abatement/relocations/<rid>/return")
def return_relocation(rid):
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    record = get_rec("relocations", rid)
    if record["status"] not in ("HOUSED", "EXTENDED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Relocation record is not HOUSED or EXTENDED"
        )
    project = DB["projects"].get(record["project_id"])
    if project is None or reoccupancy(project) != "OPEN":
        raise ApiError(
            "ERR_REOCCUPANCY_BLOCKED", 409, "Project re-occupancy gate is not OPEN"
        )
    returned = now()
    record["returned_at"] = returned
    record["status"] = "RETURNED"
    touch(record)
    unit = DB["units"].get(record["unit_id"])
    if unit is not None and unit["status"] == "OCCUPIED":
        unit["status"] = "CLEANING"
        unit["cleaning_until"] = returned + UNIT_CLEANING_BUFFER
        touch(unit)
    return ok(serialize_relocation(record))
