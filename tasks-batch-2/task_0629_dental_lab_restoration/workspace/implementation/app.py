"""Dental Lab Restoration API — Flask entry point, routes, error handlers.

In-memory storage only; store starts empty on every boot (no seeding).
"""
import os

from flask import Flask, request

import clock
import db
import errors
import lookups
import response
import serialize
import validate
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import calculations as calc
from services import case_service, mill_service, route_service, warranty_service

app = Flask(__name__)
app.url_map.strict_slashes = False

# Enum domains (scaffold §1.1).
INTAKE_METHODS = {"RX_PAPER", "IMPRESSION", "INTRAORAL_SCAN"}
FAB_PROCESSES = {"MILLED", "PRINTED"}
RESTORATION_TYPES = {"CROWN", "BRIDGE", "DENTURE", "ALIGNER"}
REMAKE_REASONS = {"SHADE_MISMATCH", "POOR_FIT", "FRACTURE", "CONTACT_OPEN"}
VERDICTS = {"ACCEPT", "REVISE"}


# =====================================================================
# Error handling
# =====================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return response.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return response.error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return response.error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return response.error_response(e.error_id, e.message, e.http_status)
    return response.error_response("ERR_VALIDATION", str(e), 422)


# =====================================================================
# Helpers
# =====================================================================
def auth(allowed_roles):
    """Authenticate then authorize. Returns (user_id, role)."""
    user_id, role = authenticate()
    require_roles(role, allowed_roles)
    return user_id, role


def list_endpoint(items, serializer):
    limit, offset = parse_pagination()
    window, total = paginate(items, limit, offset)
    return response.array_response([serializer(r) for r in window], limit, offset, total)


# =====================================================================
# Logical clock (LabAdmin)
# =====================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    auth({"LabAdmin"})
    body = validate.get_body()
    dt = validate.require_datetime(body, "to_iso8601")
    clock.set_current(dt)
    return response.object_response({"current_utc": db.iso(clock.now())})


# =====================================================================
# Doctors
# =====================================================================
@app.route("/doctors", methods=["POST"])
def create_doctor():
    auth({"LabAdmin"})
    body = validate.get_body()
    full_name = validate.require_str(body, "full_name")
    practice_name = validate.require_str(body, "practice_name")
    email = validate.require_str(body, "email")

    doctor = db.stamp_create({
        "id": db.new_id(),
        "full_name": full_name,
        "practice_name": practice_name,
        "email": email,
        "completed_case_count": 0,
        "account_credit_cents": 0,
    })
    db.doctors[doctor["id"]] = doctor
    return response.object_response(serialize.doctor(doctor), 201)


@app.route("/doctors/<rid>", methods=["GET"])
def get_doctor(rid):
    auth({"LabAdmin", "Billing", "Doctor"})
    doctor = lookups.doctor(rid)
    return response.object_response(serialize.doctor(doctor))


@app.route("/doctors", methods=["GET"])
def list_doctors():
    auth({"LabAdmin", "Billing"})
    return list_endpoint(list(db.doctors.values()), serialize.doctor)


@app.route("/doctors/<rid>/cases", methods=["GET"])
def list_doctor_cases(rid):
    auth({"LabAdmin", "Billing", "Doctor"})
    lookups.doctor(rid)
    items = [c for c in db.cases.values() if c["doctor_id"] == rid]
    return list_endpoint(items, serialize.case)


# =====================================================================
# Materials
# =====================================================================
@app.route("/materials", methods=["POST"])
def create_material():
    auth({"LabAdmin"})
    body = validate.get_body()
    code = validate.require_str(body, "code")
    name = validate.require_str(body, "name")
    base_price = validate.require_int(body, "base_unit_price_cents", minimum=1)
    process = validate.require_enum(body, "fabrication_process", FAB_PROCESSES)
    is_active = validate.optional_bool(body, "is_active", True)

    material = db.stamp_create({
        "id": db.new_id(),
        "code": code,
        "name": name,
        "base_unit_price_cents": base_price,
        "fabrication_process": process,
        "is_active": is_active,
    })
    db.materials[material["id"]] = material
    return response.object_response(serialize.material(material), 201)


@app.route("/materials/<rid>", methods=["GET"])
def get_material(rid):
    auth({"LabAdmin", "LabTech", "Billing"})
    material = lookups.material(rid)
    return response.object_response(serialize.material(material))


@app.route("/materials", methods=["GET"])
def list_materials():
    auth({"LabAdmin", "LabTech", "Billing"})
    return list_endpoint(list(db.materials.values()), serialize.material)


@app.route("/materials/<rid>/restorations", methods=["GET"])
def list_material_restorations(rid):
    auth({"LabAdmin", "LabTech", "Billing"})
    lookups.material(rid)
    items = [r for r in db.restorations.values() if r["material_id"] == rid]
    return list_endpoint(items, serialize.restoration)


# =====================================================================
# Mill machines
# =====================================================================
@app.route("/mill-machines", methods=["POST"])
def create_mill_machine():
    auth({"LabAdmin", "Scheduler"})
    body = validate.get_body()
    name = validate.require_str(body, "name")
    capability = validate.require_enum(body, "capability", FAB_PROCESSES)

    machine = db.stamp_create({
        "id": db.new_id(),
        "name": name,
        "capability": capability,
        "status": "AVAILABLE",
    })
    db.mill_machines[machine["id"]] = machine
    return response.object_response(serialize.mill_machine(machine), 201)


@app.route("/mill-machines/<rid>", methods=["GET"])
def get_mill_machine(rid):
    auth({"LabAdmin", "Scheduler", "LabTech"})
    machine = lookups.mill_machine(rid)
    return response.object_response(serialize.mill_machine(machine))


@app.route("/mill-machines/<rid>/mill-jobs", methods=["GET"])
def list_machine_jobs(rid):
    auth({"LabAdmin", "Scheduler", "LabTech"})
    lookups.mill_machine(rid)
    items = lookups.machine_mill_jobs(rid)
    return list_endpoint(items, serialize.mill_job)


@app.route("/mill-machines/<rid>/maintenance", methods=["POST"])
def machine_maintenance(rid):
    auth({"Scheduler", "LabAdmin"})
    machine = lookups.mill_machine(rid)
    mill_service.machine_maintenance(machine)
    return response.object_response(serialize.mill_machine(machine))


@app.route("/mill-machines/<rid>/release", methods=["POST"])
def machine_release(rid):
    auth({"Scheduler", "LabAdmin"})
    machine = lookups.mill_machine(rid)
    mill_service.machine_release(machine)
    return response.object_response(serialize.mill_machine(machine))


# =====================================================================
# Courier routes
# =====================================================================
@app.route("/courier-routes", methods=["POST"])
def create_courier_route():
    auth({"LabAdmin", "Scheduler"})
    body = validate.get_body()
    label = validate.require_str(body, "label")
    service_date = validate.require_datetime(body, "service_date")
    max_stops = validate.require_int(body, "max_stops", minimum=1)
    buffer_minutes = validate.optional_int(body, "buffer_minutes", 30, minimum=0)

    route = db.stamp_create({
        "id": db.new_id(),
        "label": label,
        "service_date": service_date,
        "max_stops": max_stops,
        "buffer_minutes": buffer_minutes,
        "stop_count": 0,
    })
    db.courier_routes[route["id"]] = route
    return response.object_response(serialize.courier_route(route), 201)


@app.route("/courier-routes/<rid>", methods=["GET"])
def get_courier_route(rid):
    auth({"LabAdmin", "Scheduler"})
    route = lookups.courier_route(rid)
    return response.object_response(serialize.courier_route(route))


@app.route("/courier-routes/<rid>/route-stops", methods=["GET"])
def list_route_stops(rid):
    auth({"LabAdmin", "Scheduler"})
    lookups.courier_route(rid)
    items = lookups.route_stops_on_route(rid)
    return list_endpoint(items, serialize.route_stop)


# =====================================================================
# Cases
# =====================================================================
@app.route("/cases", methods=["POST"])
def create_case():
    auth({"LabAdmin", "LabTech", "Doctor"})
    body = validate.get_body()
    doctor_id = validate.require_str(body, "doctor_id")
    intake_method = validate.require_enum(body, "intake_method", INTAKE_METHODS)
    is_rush = validate.optional_bool(body, "is_rush", False)

    # Existence: doctor_id FK (PRD §2.5).
    lookups.doctor(doctor_id)

    case = db.stamp_create({
        "id": db.new_id(),
        "doctor_id": doctor_id,
        "intake_method": intake_method,
        "is_rush": is_rush,
        "status": "INTAKE",
        "scheduled_start_at": None,
        "promised_ready_at": None,
        "shipped_at": None,
        "sla_breached": False,
        "revision_count": 0,
        "billable_unit_count": 0,
    })
    db.cases[case["id"]] = case
    return response.object_response(serialize.case(case), 201)


@app.route("/cases/<rid>", methods=["GET"])
def get_case(rid):
    auth({"LabAdmin", "LabTech", "Doctor", "Billing", "Scheduler"})
    case = lookups.case(rid)
    return response.object_response(serialize.case(case))


@app.route("/cases", methods=["GET"])
def list_cases():
    auth({"LabAdmin", "LabTech", "Billing", "Scheduler"})
    return list_endpoint(list(db.cases.values()), serialize.case)


@app.route("/cases/<rid>/restorations", methods=["POST"])
def create_restoration(rid):
    auth({"LabAdmin", "LabTech"})
    case = lookups.case(rid)
    body = validate.get_body()
    material_id = validate.require_str(body, "material_id")
    restoration_type = validate.require_enum(body, "restoration_type", RESTORATION_TYPES)
    unit_count = validate.require_int(body, "unit_count", minimum=1)
    requested_shade = validate.require_str(body, "requested_shade")

    # Existence: material_id FK.
    material = lookups.material(material_id)

    # State: restorations added while case is in INTAKE (PRD §3.2).
    if case["status"] != "INTAKE":
        raise err(errors.ERR_INVALID_STATE, "Restorations may only be added to an INTAKE case.")

    # ERR_MATERIAL_INACTIVE (priority 8).
    if not material["is_active"]:
        raise err(errors.ERR_MATERIAL_INACTIVE, "Material is not active.")

    rest = db.stamp_create({
        "id": db.new_id(),
        "case_id": case["id"],
        "material_id": material_id,
        "restoration_type": restoration_type,
        "unit_count": unit_count,
        "requested_shade": requested_shade,
        "unit_price_cents": 0,
    })
    db.restorations[rest["id"]] = rest
    return response.object_response(serialize.restoration(rest), 201)


@app.route("/cases/<rid>/restorations", methods=["GET"])
def list_case_restorations(rid):
    auth({"LabAdmin", "LabTech", "Doctor", "Billing"})
    lookups.case(rid)
    items = lookups.case_restorations(rid)
    return list_endpoint(items, serialize.restoration)


@app.route("/restorations/<rid>", methods=["GET"])
def get_restoration(rid):
    auth({"LabAdmin", "LabTech", "Doctor", "Billing"})
    rest = lookups.restoration(rid)
    return response.object_response(serialize.restoration(rest))


@app.route("/restorations/<rid>/fabrication-units", methods=["GET"])
def list_restoration_units(rid):
    auth({"LabAdmin", "LabTech", "Doctor"})
    lookups.restoration(rid)
    items = lookups.restoration_units(rid)
    return list_endpoint(items, serialize.fabrication_unit)


@app.route("/restorations/<rid>/shade-records", methods=["GET"])
def list_restoration_shade_records(rid):
    auth({"LabAdmin", "LabTech", "Doctor"})
    lookups.restoration(rid)
    items = [s for s in db.shade_records.values() if s["restoration_id"] == rid]
    return list_endpoint(items, serialize.shade_record)


@app.route("/fabrication-units/<rid>", methods=["GET"])
def get_fabrication_unit(rid):
    auth({"LabAdmin", "LabTech", "Doctor"})
    unit = lookups.fabrication_unit(rid)
    return response.object_response(serialize.fabrication_unit(unit))


@app.route("/fabrication-units/<rid>/remakes", methods=["GET"])
def list_unit_remakes(rid):
    auth({"LabAdmin", "LabTech", "Doctor"})
    lookups.fabrication_unit(rid)
    items = [u for u in db.fabrication_units.values() if u["remade_from_unit_id"] == rid]
    return list_endpoint(items, serialize.fabrication_unit)


@app.route("/fabrication-units/<rid>/remake-requests", methods=["GET"])
def list_unit_remake_requests(rid):
    auth({"LabAdmin", "LabTech", "Doctor"})
    lookups.fabrication_unit(rid)
    items = [r for r in db.remake_requests.values() if r["fabrication_unit_id"] == rid]
    return list_endpoint(items, serialize.remake_request)


@app.route("/fabrication-units/<rid>/mill-jobs", methods=["GET"])
def list_unit_mill_jobs(rid):
    auth({"LabAdmin", "Scheduler", "LabTech"})
    lookups.fabrication_unit(rid)
    items = lookups.unit_mill_jobs(rid)
    return list_endpoint(items, serialize.mill_job)


@app.route("/cases/<rid>/submit", methods=["POST"])
def case_submit(rid):
    auth({"LabTech", "LabAdmin"})
    case = lookups.case(rid)
    case_service.submit(case)
    return response.object_response(serialize.case(case))


@app.route("/cases/<rid>/start-fabrication", methods=["POST"])
def case_start_fabrication(rid):
    auth({"LabTech", "LabAdmin"})
    case = lookups.case(rid)
    case_service.start_fabrication(case)
    return response.object_response(serialize.case(case))


@app.route("/cases/<rid>/ready-tryin", methods=["POST"])
def case_ready_tryin(rid):
    auth({"LabTech", "LabAdmin"})
    case = lookups.case(rid)
    case_service.ready_tryin(case)
    return response.object_response(serialize.case(case))


@app.route("/cases/<rid>/tryin-verdict", methods=["POST"])
def case_tryin_verdict(rid):
    user_id, role = auth({"Doctor"})
    case = lookups.case(rid)

    # ERR_NOT_CASE_OWNER (priority 3): for Doctor-owned ops, X-User-ID == case.doctor_id.
    # Ownership precedes existence-of-body-FKs but follows path existence (PRD §2.9).
    if case["doctor_id"] != user_id:
        raise err(errors.ERR_NOT_CASE_OWNER, "Doctor is not the case owner.")

    body = validate.get_body()
    verdict = validate.require_enum(body, "verdict", VERDICTS)
    expected_case_version = validate.require_int(body, "expected_case_version")
    revise_ids = body.get("revise_restoration_ids")
    if revise_ids is not None:
        if not isinstance(revise_ids, list) or not all(isinstance(x, str) for x in revise_ids):
            raise err(errors.ERR_INVALID_REQUEST, "revise_restoration_ids must be a list of strings.")
        # Existence of flagged restorations (FK in body, resolved left-to-right).
        for r_id in revise_ids:
            rest = db.restorations.get(r_id)
            if rest is None:
                raise err(errors.ERR_NOT_FOUND, "Flagged restoration not found.")

    case_service.tryin_verdict(case, verdict, expected_case_version, revise_ids)
    return response.object_response(serialize.case(case))


@app.route("/cases/<rid>/confirm-delivery", methods=["POST"])
def case_confirm_delivery(rid):
    auth({"Scheduler", "LabAdmin"})
    case = lookups.case(rid)
    case_service.confirm_delivery(case)
    return response.object_response(serialize.case(case))


@app.route("/cases/<rid>/cancel", methods=["POST"])
def case_cancel(rid):
    user_id, role = auth({"Doctor", "LabAdmin"})
    case = lookups.case(rid)

    # ERR_NOT_CASE_OWNER (priority 3): Doctor must own the case. LabAdmin exempt.
    if role == "Doctor" and case["doctor_id"] != user_id:
        raise err(errors.ERR_NOT_CASE_OWNER, "Doctor is not the case owner.")

    case_service.cancel(case)
    return response.object_response(serialize.case(case))


@app.route("/cases/<rid>/invoice", methods=["GET"])
def get_case_invoice(rid):
    auth({"LabAdmin", "Billing", "Doctor"})
    lookups.case(rid)
    items = [i for i in db.invoices.values() if i["case_id"] == rid]
    return list_endpoint(items, serialize.invoice)


@app.route("/cases/<rid>/credit-memos", methods=["GET"])
def list_case_credit_memos(rid):
    auth({"LabAdmin", "Billing", "Doctor"})
    lookups.case(rid)
    items = [m for m in db.credit_memos.values() if m["case_id"] == rid]
    return list_endpoint(items, serialize.credit_memo)


@app.route("/cases/<rid>/remake-requests", methods=["GET"])
def list_case_remake_requests(rid):
    auth({"LabAdmin", "LabTech", "Doctor"})
    lookups.case(rid)
    items = [r for r in db.remake_requests.values() if r["case_id"] == rid]
    return list_endpoint(items, serialize.remake_request)


@app.route("/cases/<rid>/route-stops", methods=["GET"])
def list_case_route_stops(rid):
    auth({"LabAdmin", "Scheduler", "Doctor"})
    lookups.case(rid)
    items = lookups.case_route_stops(rid)
    return list_endpoint(items, serialize.route_stop)


@app.route("/cases/<rid>/remake-requests", methods=["POST"])
def create_remake_request(rid):
    user_id, role = auth({"Doctor", "LabAdmin"})
    case = lookups.case(rid)

    # Doctor-owned warranty request: X-User-ID must equal case.doctor_id (PRD §2.1).
    if role == "Doctor" and case["doctor_id"] != user_id:
        raise err(errors.ERR_NOT_CASE_OWNER, "Doctor is not the case owner.")

    body = validate.get_body()
    fabrication_unit_id = validate.require_str(body, "fabrication_unit_id")
    reason = validate.require_enum(body, "reason", REMAKE_REASONS)

    unit = lookups.fabrication_unit(fabrication_unit_id)
    req = warranty_service.open_remake(case, unit, reason)
    return response.object_response(serialize.remake_request(req), 201)


# =====================================================================
# Mill jobs
# =====================================================================
@app.route("/mill-jobs", methods=["POST"])
def create_mill_job():
    auth({"Scheduler", "LabTech", "LabAdmin"})
    body = validate.get_body()
    fabrication_unit_id = validate.require_str(body, "fabrication_unit_id")
    mill_machine_id = validate.require_str(body, "mill_machine_id")
    start_at = validate.require_datetime(body, "start_at")
    duration_minutes = validate.require_int(body, "duration_minutes", minimum=1)

    # Existence FKs left-to-right.
    unit = lookups.fabrication_unit(fabrication_unit_id)
    machine = lookups.mill_machine(mill_machine_id)

    job = mill_service.create_mill_job(unit, machine, start_at, duration_minutes)
    return response.object_response(serialize.mill_job(job), 201)


@app.route("/mill-jobs/<rid>", methods=["GET"])
def get_mill_job(rid):
    auth({"LabAdmin", "Scheduler", "LabTech"})
    job = lookups.mill_job(rid)
    return response.object_response(serialize.mill_job(job))


@app.route("/mill-jobs/<rid>/start", methods=["POST"])
def mill_job_start(rid):
    auth({"Scheduler", "LabAdmin"})
    job = lookups.mill_job(rid)
    body = validate.get_body()
    expected_machine_version = validate.require_int(body, "expected_machine_version")
    mill_service.start_job(job, expected_machine_version)
    return response.object_response(serialize.mill_job(job))


@app.route("/mill-jobs/<rid>/complete", methods=["POST"])
def mill_job_complete(rid):
    auth({"Scheduler", "LabAdmin"})
    job = lookups.mill_job(rid)
    mill_service.complete_job(job)
    return response.object_response(serialize.mill_job(job))


@app.route("/mill-jobs/<rid>/cancel", methods=["POST"])
def mill_job_cancel(rid):
    auth({"Scheduler", "LabAdmin"})
    job = lookups.mill_job(rid)
    mill_service.cancel_job(job)
    return response.object_response(serialize.mill_job(job))


# =====================================================================
# Route stops
# =====================================================================
@app.route("/route-stops", methods=["POST"])
def create_route_stop():
    auth({"Scheduler", "LabAdmin"})
    body = validate.get_body()
    courier_route_id = validate.require_str(body, "courier_route_id")
    case_id = validate.require_str(body, "case_id")
    window_start_at = validate.require_datetime(body, "window_start_at")
    window_minutes = validate.require_int(body, "window_minutes", minimum=1)

    route = lookups.courier_route(courier_route_id)
    case = lookups.case(case_id)

    stop = route_service.create_route_stop(route, case, window_start_at, window_minutes)
    return response.object_response(serialize.route_stop(stop), 201)


@app.route("/route-stops/<rid>", methods=["GET"])
def get_route_stop(rid):
    auth({"LabAdmin", "Scheduler"})
    stop = lookups.route_stop(rid)
    return response.object_response(serialize.route_stop(stop))


@app.route("/route-stops/<rid>/complete", methods=["POST"])
def route_stop_complete(rid):
    auth({"Scheduler", "LabAdmin"})
    stop = lookups.route_stop(rid)
    route_service.complete_stop(stop)
    return response.object_response(serialize.route_stop(stop))


# =====================================================================
# Invoices
# =====================================================================
@app.route("/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    auth({"LabAdmin", "Billing", "Doctor"})
    inv = lookups.invoice(rid)
    return response.object_response(serialize.invoice(inv))


@app.route("/invoices/<rid>/credit-memos", methods=["GET"])
def list_invoice_credit_memos(rid):
    auth({"LabAdmin", "Billing", "Doctor"})
    lookups.invoice(rid)
    items = [m for m in db.credit_memos.values() if m["invoice_id"] == rid]
    return list_endpoint(items, serialize.credit_memo)


@app.route("/invoices/<rid>/pay", methods=["POST"])
def invoice_pay(rid):
    auth({"Billing", "LabAdmin"})
    inv = lookups.invoice(rid)
    warranty_service.pay_invoice(inv)
    return response.object_response(serialize.invoice(inv))


# =====================================================================
# Remake requests
# =====================================================================
@app.route("/remake-requests/<rid>", methods=["GET"])
def get_remake_request(rid):
    auth({"LabAdmin", "LabTech", "Doctor"})
    req = lookups.remake_request(rid)
    return response.object_response(serialize.remake_request(req))


@app.route("/remake-requests/<rid>/approve", methods=["POST"])
def remake_approve(rid):
    auth({"LabAdmin"})
    req = lookups.remake_request(rid)
    warranty_service.approve_remake(req)
    return response.object_response(serialize.remake_request(req))


@app.route("/remake-requests/<rid>/deny", methods=["POST"])
def remake_deny(rid):
    auth({"LabAdmin"})
    req = lookups.remake_request(rid)
    warranty_service.deny_remake(req)
    return response.object_response(serialize.remake_request(req))


# =====================================================================
# Credit memos
# =====================================================================
@app.route("/credit-memos/<rid>", methods=["GET"])
def get_credit_memo(rid):
    auth({"LabAdmin", "Billing", "Doctor"})
    memo = lookups.credit_memo(rid)
    return response.object_response(serialize.credit_memo(memo))


@app.route("/credit-memos/<rid>/void", methods=["POST"])
def credit_memo_void(rid):
    auth({"Billing", "LabAdmin"})
    memo = lookups.credit_memo(rid)
    warranty_service.void_credit_memo(memo)
    return response.object_response(serialize.credit_memo(memo))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
