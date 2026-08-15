"""Routes: logical clock, projects, surveys, samples, workers, crew assignments."""
from decimal import Decimal

from core import (
    app, DB, CLOCK,
    ApiError,
    authenticate, require_roles,
    body, req_field, as_str, as_bool, as_enum, as_int, as_num, as_dt, opt_dt,
    new_record, touch, get_rec,
    ok, paginate, by_created, fmt_ts, now, q2, hours_between,
    WORK_TYPES, HAZARD_CLASSES, CERT_LEVELS, LAB_RESULTS,
    samples_of, survey_aggregates, sync_survey, sync_worker_hours, supervisor_coverage,
    latest_notification, containment_of_project, estimated_disposal_cost,
    reoccupancy, run_sweeps,
    serialize_project, serialize_survey, serialize_sample, serialize_worker,
    serialize_assignment,
)


# ------------------------------------------------------------------ health
@app.get("/")
def health():
    return ok({"service": "asbestos-lead-abatement", "status": "up"})


# ------------------------------------------------------------------ clock
@app.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    data = body()
    target = as_dt(req_field(data, "to_iso8601"), "to_iso8601")
    CLOCK["now"] = target
    run_sweeps()
    return ok({"current_utc": fmt_ts(CLOCK["now"])})


# ------------------------------------------------------------------ projects
@app.post("/abatement/projects")
def create_project():
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    data = body()
    name = as_str(req_field(data, "name"), "name")
    site_address = as_str(req_field(data, "site_address"), "site_address")
    work_type = as_enum(req_field(data, "work_type"), "work_type", WORK_TYPES)
    hazard_class = as_enum(req_field(data, "hazard_class"), "hazard_class", HAZARD_CLASSES)
    planned_start_raw = req_field(data, "planned_start")
    planned_start = as_dt(planned_start_raw, "planned_start")
    base_cost = as_int(
        req_field(data, "base_abatement_cost_cents"), "base_abatement_cost_cents", minimum=0
    )
    rec = new_record(
        "projects",
        {
            "name": name,
            "site_address": site_address,
            "work_type": work_type,
            "hazard_class": hazard_class,
            "planned_start": planned_start_raw,
            "_planned_start": planned_start,
            "base_abatement_cost_cents": base_cost,
            "status": "DRAFT",
            "total_acm_sq_ft": Decimal("0"),
            "estimated_disposal_cost_cents": 0,
            "manifested_weight_lbs": Decimal("0"),
            "final_disposal_cost_cents": 0,
            "insurance_surcharge_cents": 0,
            "total_project_cost_cents": 0,
            "reoccupancy_status": "BLOCKED",
        },
    )
    return ok(serialize_project(rec), 201)


@app.get("/abatement/projects/<pid>")
def get_project(pid):
    authenticate()
    project = get_rec("projects", pid)
    return ok(serialize_project(project))


@app.post("/abatement/projects/<pid>/start-abatement")
def start_abatement(pid):
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    project = get_rec("projects", pid)
    if project["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Project is not ASSESSED")
    notification = latest_notification(pid)
    if notification is None or notification["status"] != "ACKNOWLEDGED":
        raise ApiError(
            "ERR_NOTIFICATION_NOT_ACKNOWLEDGED",
            409,
            "Latest notification is not ACKNOWLEDGED",
        )
    if now() < notification["earliest_start_at"]:
        raise ApiError(
            "ERR_WAITING_PERIOD_NOT_ELAPSED",
            409,
            "The notification waiting period has not elapsed",
        )
    containment = containment_of_project(pid)
    if containment is None or containment["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Containment is not VERIFIED")
    if not supervisor_coverage(pid, now()):
        raise ApiError(
            "ERR_SUPERVISOR_COVERAGE_REQUIRED",
            409,
            "No SCHEDULED supervisor assignment covers the current time",
        )
    project["status"] = "IN_PROGRESS"
    touch(project)
    return ok(serialize_project(project))


@app.post("/abatement/projects/<pid>/suspend")
def suspend_project(pid):
    _, role = authenticate()
    require_roles(role, "ContractorAdmin", "Supervisor")
    project = get_rec("projects", pid)
    if project["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Project is not IN_PROGRESS")
    project["status"] = "SUSPENDED"
    touch(project)
    return ok(serialize_project(project))


@app.post("/abatement/projects/<pid>/resume")
def resume_project(pid):
    _, role = authenticate()
    require_roles(role, "ContractorAdmin", "Supervisor")
    project = get_rec("projects", pid)
    if project["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Project is not SUSPENDED")
    if not supervisor_coverage(pid, now()):
        raise ApiError(
            "ERR_SUPERVISOR_COVERAGE_REQUIRED",
            409,
            "No SCHEDULED supervisor assignment covers the current time",
        )
    project["status"] = "IN_PROGRESS"
    touch(project)
    return ok(serialize_project(project))


@app.post("/abatement/projects/<pid>/complete-work")
def complete_work(pid):
    _, role = authenticate()
    require_roles(role, "Supervisor")
    project = get_rec("projects", pid)
    if project["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Project is not IN_PROGRESS")
    for m in DB["manifests"].values():
        if m["project_id"] == pid and m["status"] == "DRAFT":
            raise ApiError(
                "ERR_MANIFESTS_OUTSTANDING",
                409,
                "Project has manifests still in DRAFT",
            )
    project["status"] = "AWAITING_CLEARANCE"
    touch(project)
    return ok(serialize_project(project))


@app.post("/abatement/projects/<pid>/close")
def close_project(pid):
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    project = get_rec("projects", pid)
    if project["status"] != "AWAITING_CLEARANCE":
        raise ApiError("ERR_INVALID_STATE", 409, "Project is not AWAITING_CLEARANCE")
    if reoccupancy(project) != "OPEN":
        raise ApiError("ERR_REOCCUPANCY_BLOCKED", 409, "Re-occupancy gate is not OPEN")
    for r in DB["relocations"].values():
        if r["project_id"] == pid and r["status"] != "RETURNED":
            raise ApiError(
                "ERR_REOCCUPANCY_BLOCKED",
                409,
                "Project has relocation records not yet RETURNED",
            )
    for m in DB["manifests"].values():
        if m["project_id"] == pid and m["status"] not in ("CONFIRMED", "VOIDED"):
            raise ApiError(
                "ERR_MANIFESTS_OUTSTANDING",
                409,
                "Project has manifests not in CONFIRMED or VOIDED",
            )
    project["status"] = "CLOSED"
    touch(project)
    return ok(serialize_project(project))


# ------------------------------------------------------------------ surveys
@app.post("/abatement/surveys")
def create_survey():
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    data = body()
    project_id = as_str(req_field(data, "project_id"), "project_id")
    surveyor_name = as_str(req_field(data, "surveyor_name"), "surveyor_name")
    survey_date_raw = req_field(data, "survey_date")
    survey_date = as_dt(survey_date_raw, "survey_date")
    project = get_rec("projects", project_id)
    if project["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Project is not DRAFT")
    for s in DB["surveys"].values():
        if s["project_id"] == project_id:
            raise ApiError(
                "ERR_SURVEY_ALREADY_EXISTS", 409, "Project already has a survey"
            )
    rec = new_record(
        "surveys",
        {
            "project_id": project_id,
            "surveyor_name": surveyor_name,
            "survey_date": survey_date_raw,
            "_survey_date": survey_date,
            "status": "DRAFT",
            "acm_sq_ft_provisional": Decimal("0"),
            "acm_sq_ft_final": Decimal("0"),
            "friable_acm_sq_ft_final": Decimal("0"),
        },
    )
    return ok(serialize_survey(rec), 201)


@app.get("/abatement/surveys/<sid>")
def get_survey(sid):
    authenticate()
    survey = get_rec("surveys", sid)
    return ok(serialize_survey(survey))


@app.get("/abatement/projects/<pid>/surveys")
def list_project_surveys(pid):
    authenticate()
    get_rec("projects", pid)
    items = [serialize_survey(s) for s in by_created(DB["surveys"].values()) if s["project_id"] == pid]
    return paginate(items)


@app.post("/abatement/surveys/<sid>/submit")
def submit_survey(sid):
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    survey = get_rec("surveys", sid)
    if survey["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Survey is not DRAFT")
    if len(samples_of(sid)) == 0:
        raise ApiError("ERR_VALIDATION", 400, "Survey has no samples")
    survey["status"] = "IN_LAB"
    touch(survey)
    return ok(serialize_survey(survey))


@app.post("/abatement/surveys/<sid>/finalize")
def finalize_survey(sid):
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    survey = get_rec("surveys", sid)
    if survey["status"] != "IN_LAB":
        raise ApiError("ERR_INVALID_STATE", 409, "Survey is not IN_LAB")
    for s in samples_of(sid):
        if s["status"] != "REPORTED":
            raise ApiError(
                "ERR_SAMPLES_STILL_PENDING",
                409,
                "Survey has samples still PENDING",
            )
    survey["status"] = "FINALIZED"
    touch(survey)
    project = DB["projects"].get(survey["project_id"])
    if project is not None and project["status"] == "DRAFT":
        _, final, _ = survey_aggregates(sid)
        project["status"] = "ASSESSED"
        project["total_acm_sq_ft"] = final
        project["estimated_disposal_cost_cents"] = estimated_disposal_cost(final)
        touch(project)
    return ok(serialize_survey(survey))


# ------------------------------------------------------------------ samples
@app.post("/abatement/samples")
def create_sample():
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    data = body()
    survey_id = as_str(req_field(data, "survey_id"), "survey_id")
    material = as_str(req_field(data, "material"), "material")
    location_desc = as_str(req_field(data, "location_desc"), "location_desc")
    quantity = as_num(req_field(data, "quantity_sq_ft"), "quantity_sq_ft", gt=Decimal("0"))
    friable = as_bool(req_field(data, "friable"), "friable")
    lead_ppm = None
    if "lead_ppm" in data and data["lead_ppm"] is not None:
        lead_ppm = as_num(data["lead_ppm"], "lead_ppm", ge=Decimal("0"))
    survey = get_rec("surveys", survey_id)
    if survey["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Survey is not DRAFT")
    rec = new_record(
        "samples",
        {
            "survey_id": survey_id,
            "material": material,
            "location_desc": location_desc,
            "quantity_sq_ft": q2(quantity),
            "friable": friable,
            "lab_result": "PENDING",
            "asbestos_pct": None,
            "lead_ppm": lead_ppm,
            "status": "PENDING",
        },
    )
    sync_survey(survey)
    return ok(serialize_sample(rec), 201)


@app.get("/abatement/surveys/<sid>/samples")
def list_survey_samples(sid):
    authenticate()
    get_rec("surveys", sid)
    items = [serialize_sample(s) for s in by_created(DB["samples"].values()) if s["survey_id"] == sid]
    return paginate(items)


@app.post("/abatement/samples/<sid>/result")
def record_sample_result(sid):
    user_id, role = authenticate()
    require_roles(role, "IndustrialHygienist")
    data = body()
    lab_result = as_enum(req_field(data, "lab_result"), "lab_result", LAB_RESULTS)
    asbestos_pct = None
    if "asbestos_pct" in data and data["asbestos_pct"] is not None:
        asbestos_pct = as_num(data["asbestos_pct"], "asbestos_pct")
        if not (Decimal("1") <= asbestos_pct <= Decimal("100")):
            raise ApiError(
                "ERR_VALIDATION", 400, "asbestos_pct must be between 1 and 100"
            )
    if lab_result == "POSITIVE" and asbestos_pct is None:
        raise ApiError(
            "ERR_VALIDATION", 400, "asbestos_pct is required when lab_result is POSITIVE"
        )
    lead_ppm = None
    lead_ppm_provided = False
    if "lead_ppm" in data and data["lead_ppm"] is not None:
        lead_ppm = as_num(data["lead_ppm"], "lead_ppm", ge=Decimal("0"))
        lead_ppm_provided = True
    sample = get_rec("samples", sid)
    if sample["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Sample is not PENDING")
    survey = DB["surveys"][sample["survey_id"]]
    if survey["status"] != "IN_LAB":
        raise ApiError("ERR_INVALID_STATE", 409, "Survey is not IN_LAB")
    sample["lab_result"] = lab_result
    if asbestos_pct is not None:
        sample["asbestos_pct"] = asbestos_pct
    if lead_ppm_provided:
        sample["lead_ppm"] = lead_ppm
    sample["status"] = "REPORTED"
    touch(sample)
    sync_survey(survey)
    return ok(serialize_sample(sample))


# ------------------------------------------------------------------ workers
@app.post("/abatement/workers")
def create_worker():
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    data = body()
    full_name = as_str(req_field(data, "full_name"), "full_name")
    cert_level = as_enum(
        req_field(data, "certification_level"), "certification_level", CERT_LEVELS
    )
    cert_raw = req_field(data, "cert_expires_at")
    cert = as_dt(cert_raw, "cert_expires_at")
    med_raw = req_field(data, "medical_clearance_expires_at")
    med = as_dt(med_raw, "medical_clearance_expires_at")
    resp_raw = req_field(data, "respirator_fit_expires_at")
    resp = as_dt(resp_raw, "respirator_fit_expires_at")
    rec = new_record(
        "workers",
        {
            "full_name": full_name,
            "certification_level": cert_level,
            "cert_expires_at": cert_raw,
            "_cert_expires_at": cert,
            "medical_clearance_expires_at": med_raw,
            "_medical_clearance_expires_at": med,
            "respirator_fit_expires_at": resp_raw,
            "_respirator_fit_expires_at": resp,
            "status": "ACTIVE",
            "assigned_scheduled_hours": Decimal("0"),
        },
    )
    return ok(serialize_worker(rec), 201)


@app.get("/abatement/workers/<wid>")
def get_worker(wid):
    authenticate()
    worker = get_rec("workers", wid)
    return ok(serialize_worker(worker))


@app.post("/abatement/workers/<wid>/recertify")
def recertify_worker(wid):
    _, role = authenticate()
    require_roles(role, "ContractorAdmin")
    data = body()
    updates = {}
    for field in (
        "cert_expires_at",
        "medical_clearance_expires_at",
        "respirator_fit_expires_at",
    ):
        parsed = opt_dt(data, field)
        if parsed is not None:
            updates[field] = parsed
    worker = get_rec("workers", wid)
    if worker["status"] != "LAPSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Worker is not LAPSED")
    for field, (raw, parsed) in updates.items():
        worker[field] = raw
        worker["_" + field] = parsed
    current = now()
    if not (
        worker["_cert_expires_at"] > current
        and worker["_medical_clearance_expires_at"] > current
        and worker["_respirator_fit_expires_at"] > current
    ):
        raise ApiError(
            "ERR_WORKER_NOT_FIT",
            422,
            "All three expiry fields must be strictly in the future",
        )
    worker["status"] = "ACTIVE"
    touch(worker)
    for a in DB["assignments"].values():
        if (
            a["worker_id"] == wid
            and a["status"] == "SUSPENDED"
            and a["_end_at"] > current
        ):
            a["status"] = "SCHEDULED"
            touch(a)
    sync_worker_hours(worker)
    return ok(serialize_worker(worker))


# ------------------------------------------------------------------ crew assignments
ASSIGNMENT_PROJECT_STATES = ("ASSESSED", "IN_PROGRESS", "SUSPENDED", "RECLEANING")


@app.post("/abatement/assignments")
def create_assignment():
    _, role = authenticate()
    require_roles(role, "ContractorAdmin", "Supervisor")
    data = body()
    project_id = as_str(req_field(data, "project_id"), "project_id")
    worker_id = as_str(req_field(data, "worker_id"), "worker_id")
    role_on_site = as_enum(req_field(data, "role_on_site"), "role_on_site", CERT_LEVELS)
    start_raw = req_field(data, "start_at")
    start = as_dt(start_raw, "start_at")
    end_raw = req_field(data, "end_at")
    end = as_dt(end_raw, "end_at")
    project = get_rec("projects", project_id)
    worker = get_rec("workers", worker_id)
    if project["status"] not in ASSIGNMENT_PROJECT_STATES:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Project status does not permit crew assignment"
        )
    if (
        worker["status"] != "ACTIVE"
        or not worker["_cert_expires_at"] > start
        or not worker["_medical_clearance_expires_at"] > start
        or not worker["_respirator_fit_expires_at"] > start
    ):
        raise ApiError(
            "ERR_WORKER_NOT_FIT",
            422,
            "Worker is not ACTIVE or an expiry does not fall strictly after start_at",
        )
    if role_on_site == "SUPERVISOR" and worker["certification_level"] != "SUPERVISOR":
        raise ApiError(
            "ERR_CERTIFICATION_MISMATCH",
            422,
            "role_on_site SUPERVISOR requires certification_level SUPERVISOR",
        )
    if not end > start:
        raise ApiError(
            "ERR_INVALID_WINDOW", 422, "end_at must be strictly after start_at"
        )
    for existing in DB["assignments"].values():
        if (
            existing["worker_id"] == worker_id
            and existing["status"] == "SCHEDULED"
            and existing["_start_at"] < end
            and start < existing["_end_at"]
        ):
            raise ApiError(
                "ERR_ASSIGNMENT_OVERLAP",
                409,
                "Worker already has a SCHEDULED assignment overlapping this window",
            )
    rec = new_record(
        "assignments",
        {
            "project_id": project_id,
            "worker_id": worker_id,
            "role_on_site": role_on_site,
            "start_at": start_raw,
            "_start_at": start,
            "end_at": end_raw,
            "_end_at": end,
            "scheduled_hours": hours_between(start, end),
            "status": "SCHEDULED",
        },
    )
    sync_worker_hours(worker)
    return ok(serialize_assignment(rec), 201)


@app.get("/abatement/projects/<pid>/assignments")
def list_project_assignments(pid):
    authenticate()
    get_rec("projects", pid)
    items = [
        serialize_assignment(a)
        for a in by_created(DB["assignments"].values())
        if a["project_id"] == pid
    ]
    return paginate(items)


@app.get("/abatement/workers/<wid>/assignments")
def list_worker_assignments(wid):
    authenticate()
    get_rec("workers", wid)
    items = [
        serialize_assignment(a)
        for a in by_created(DB["assignments"].values())
        if a["worker_id"] == wid
    ]
    return paginate(items)


@app.post("/abatement/assignments/<aid>/cancel")
def cancel_assignment(aid):
    _, role = authenticate()
    require_roles(role, "ContractorAdmin", "Supervisor")
    assignment = get_rec("assignments", aid)
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment is not SCHEDULED")
    assignment["status"] = "CANCELLED"
    touch(assignment)
    worker = DB["workers"].get(assignment["worker_id"])
    if worker is not None:
        sync_worker_hours(worker)
    return ok(serialize_assignment(assignment))
