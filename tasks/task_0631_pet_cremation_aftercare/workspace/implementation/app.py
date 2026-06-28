"""Pet Cremation & Aftercare API — Flask entry point.

Validation precedence (PRD 2.10), applied per request:
  1. auth headers (ERR_UNAUTHENTICATED)
  2. role authorization (ERR_FORBIDDEN)
  3. existence of path resources + body FK targets (ERR_NOT_FOUND)
  4. request well-formedness (ERR_INVALID_REQUEST / pagination / window / viewing)
  5. ownership scope for entity-backed principals (ERR_FORBIDDEN)
  6+ endpoint-specific business rules (account billing -> OCC -> state -> safety
     -> capacity -> scheduling -> fiscal).

Storage is in-memory only; no entity is seeded at startup.
"""

import os

from flask import Flask, request

import errors
import models
import services
import validation as v
from clock import parse_iso8601
from db import store
from middleware import authenticate, require_role
from response import success, success_list, error

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return error(e.error_id, e.message, e.http_status)
    return error("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 422)


# ---------------------------------------------------------------------------
# Lookup helpers (existence — priority 3)
# ---------------------------------------------------------------------------
def get_or_404(collection, rid):
    obj = collection.get(rid)
    if obj is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return obj


# ---------------------------------------------------------------------------
# Ownership scope (priority 5)
# ---------------------------------------------------------------------------
def enforce_case_ownership(principal, case):
    if principal.role == "PetOwner":
        if case["owner_id"] != principal.user_id:
            raise errors.err(errors.ERR_FORBIDDEN, "Not your case")
    elif principal.role == "ClinicStaff":
        if case["clinic_id"] != principal.user_id:
            raise errors.err(errors.ERR_FORBIDDEN, "Not your clinic's case")


def enforce_invoice_ownership(principal, invoice):
    case = store.cases.get(invoice["case_id"])
    if principal.role == "PetOwner":
        if case is None or case["owner_id"] != principal.user_id:
            raise errors.err(errors.ERR_FORBIDDEN, "Not your invoice")
    elif principal.role == "ClinicStaff":
        if invoice["clinic_id"] != principal.user_id:
            raise errors.err(errors.ERR_FORBIDDEN, "Not your clinic's invoice")


# ---------------------------------------------------------------------------
# List sorting + pagination
# ---------------------------------------------------------------------------
def sorted_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


def list_response(items, serializer):
    limit, offset = v.parse_pagination()
    ordered = sorted_by_created(items)
    total = len(ordered)
    page = v.paginate(ordered, limit, offset)
    return success_list([serializer(x) for x in page], limit, offset, total)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    p = authenticate()
    require_role(p, {"CrematoryAdmin"})
    body = v.get_json_body()
    iso = body.get("to_iso8601")
    if not isinstance(iso, str) or not iso:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        parse_iso8601(iso)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601")
    store.clock.set(iso)
    return success({}, 200)


# ===========================================================================
# Clinic
# ===========================================================================
@app.route("/clinics", methods=["POST"])
def create_clinic():
    p = authenticate()
    require_role(p, {"CrematoryAdmin"})
    body = v.get_json_body()
    name = v.require_string(body, "name")
    account_code = v.require_string(body, "account_code")
    credit_limit = v.optional_int(body, "credit_limit_cents", default=models.DEFAULT_CREDIT_LIMIT_CENTS, minimum=0)
    c = models.make_clinic(name, account_code, credit_limit)
    return success(models.serialize_clinic(c), 201)


@app.route("/clinics/<rid>", methods=["GET"])
def get_clinic(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff"})
    c = get_or_404(store.clinics, rid)
    if p.role == "ClinicStaff" and c["id"] != p.user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "Not your clinic")
    return success(models.serialize_clinic(c), 200)


@app.route("/clinics", methods=["GET"])
def list_clinics():
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator"})
    account_status = request.args.get("account_status")
    items = list(store.clinics.values())
    if account_status:
        items = [c for c in items if c["account_status"] == account_status]
    return list_response(items, models.serialize_clinic)


@app.route("/clinics/<rid>/statement", methods=["GET"])
def clinic_statement(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "ClinicStaff"})
    c = get_or_404(store.clinics, rid)
    if p.role == "ClinicStaff" and c["id"] != p.user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "Not your clinic")
    basis = request.args.get("basis", "COMPLETION")
    if basis not in ("ACCRUAL", "COMPLETION"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "basis must be ACCRUAL or COMPLETION")
    balance = services.clinic_statement_balance(c, basis)
    return success({"clinic_id": c["id"], "basis": basis, "balance_cents": balance}, 200)


# ===========================================================================
# PetOwner
# ===========================================================================
@app.route("/petowners", methods=["POST"])
def create_petowner():
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff"})
    body = v.get_json_body()
    full_name = v.require_string(body, "full_name")
    email = v.require_string(body, "email")
    phone = v.require_string(body, "phone")
    o = models.make_petowner(full_name, email, phone)
    return success(models.serialize_petowner(o), 201)


@app.route("/petowners/<rid>", methods=["GET"])
def get_petowner(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"})
    o = get_or_404(store.petowners, rid)
    if p.role == "PetOwner" and o["id"] != p.user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "Not your record")
    return success(models.serialize_petowner(o), 200)


# ===========================================================================
# Cooler
# ===========================================================================
@app.route("/coolers", methods=["POST"])
def create_cooler():
    p = authenticate()
    require_role(p, {"CrematoryAdmin"})
    body = v.get_json_body()
    label = v.require_string(body, "label")
    total_capacity = v.require_int(body, "total_capacity", minimum=1)
    c = models.make_cooler(label, total_capacity)
    return success(models.serialize_cooler(c), 201)


@app.route("/coolers/<rid>", methods=["GET"])
def get_cooler(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator"})
    c = get_or_404(store.coolers, rid)
    return success(models.serialize_cooler(c), 200)


@app.route("/coolers", methods=["GET"])
def list_coolers():
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator"})
    status = request.args.get("status")
    items = list(store.coolers.values())
    if status:
        items = [c for c in items if models.serialize_cooler(c)["status"] == status]
    return list_response(items, models.serialize_cooler)


# ===========================================================================
# Retort
# ===========================================================================
@app.route("/retorts", methods=["POST"])
def create_retort():
    p = authenticate()
    require_role(p, {"CrematoryAdmin"})
    body = v.get_json_body()
    label = v.require_string(body, "label")
    max_load = v.require_int(body, "max_load_lbs", minimum=1)
    r = models.make_retort(label, max_load)
    return success(models.serialize_retort(r), 201)


@app.route("/retorts/<rid>", methods=["GET"])
def get_retort(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator"})
    r = get_or_404(store.retorts, rid)
    return success(models.serialize_retort(r), 200)


# ===========================================================================
# CremationBatch
# ===========================================================================
@app.route("/batches", methods=["POST"])
def create_batch():
    p = authenticate()
    require_role(p, {"CrematoryOperator", "CrematoryAdmin"})
    body = v.get_json_body()
    retort_id = v.require_string(body, "retort_id")
    service_type = v.require_enum(body, "service_type", {"PRIVATE", "COMMUNAL"})
    scheduled_start = v.require_string(body, "scheduled_start")
    scheduled_end = v.require_string(body, "scheduled_end")
    # FK existence (priority 3)
    get_or_404(store.retorts, retort_id)
    # window validity (priority 4)
    try:
        start_dt = parse_iso8601(scheduled_start)
        end_dt = parse_iso8601(scheduled_end)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "scheduled_start/end must be ISO 8601")
    if end_dt <= start_dt:
        raise errors.err(errors.ERR_SCHEDULE_WINDOW_INVALID, "scheduled_end must be after scheduled_start")
    b = models.make_batch(retort_id, service_type, scheduled_start, scheduled_end)
    return success(models.serialize_batch(b), 201)


@app.route("/batches/<rid>", methods=["GET"])
def get_batch(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator"})
    b = get_or_404(store.batches, rid)
    return success(models.serialize_batch(b), 200)


@app.route("/batches", methods=["GET"])
def list_batches():
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator"})
    retort_id = request.args.get("retort_id")
    status = request.args.get("status")
    service_type = request.args.get("service_type")
    items = list(store.batches.values())
    if retort_id:
        items = [b for b in items if b["retort_id"] == retort_id]
    if status:
        items = [b for b in items if b["status"] == status]
    if service_type:
        items = [b for b in items if b["service_type"] == service_type]
    return list_response(items, models.serialize_batch)


@app.route("/batches/<rid>/cases", methods=["GET"])
def list_batch_cases(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator"})
    get_or_404(store.batches, rid)
    items = [c for c in store.cases.values() if c.get("batch_id") == rid]
    return list_response(items, models.serialize_case)


@app.route("/batches/<rid>/assign-case", methods=["POST"])
def assign_case(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    b = get_or_404(store.batches, rid)
    body = v.get_json_body()
    case_id = v.require_string(body, "case_id")
    case = get_or_404(store.cases, case_id)
    services.batch_assign_case(b, case)
    return success(models.serialize_batch(b), 200)


@app.route("/batches/<rid>/load", methods=["POST"])
def load_batch(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    b = get_or_404(store.batches, rid)
    services.batch_load(b)
    return success(models.serialize_batch(b), 200)


@app.route("/batches/<rid>/fire", methods=["POST"])
def fire_batch(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    b = get_or_404(store.batches, rid)
    services.batch_fire(b)
    return success(models.serialize_batch(b), 200)


@app.route("/batches/<rid>/complete", methods=["POST"])
def complete_batch(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    b = get_or_404(store.batches, rid)
    services.batch_complete(b)
    return success(models.serialize_batch(b), 200)


@app.route("/batches/<rid>/reconcile", methods=["POST"])
def reconcile_batch(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin"})
    b = get_or_404(store.batches, rid)
    services.batch_reconcile(b)
    return success(models.serialize_batch(b), 200)


# ===========================================================================
# Case
# ===========================================================================
@app.route("/cases", methods=["POST"])
def create_case():
    p = authenticate()
    require_role(p, {"CrematoryOperator", "ClinicStaff"})
    body = v.get_json_body()
    owner_id = v.require_string(body, "owner_id")
    pet_name = v.require_string(body, "pet_name")
    species = v.require_enum(body, "species", {"DOG", "CAT", "OTHER"})
    weight_lbs = v.require_int(body, "weight_lbs", minimum=1)
    service_type = v.require_enum(body, "service_type", {"PRIVATE", "COMMUNAL"})
    expedited = v.require_bool(body, "expedited", default=False)
    pickup_kind = v.require_enum(body, "pickup_kind", {"CLINIC", "HOME"})
    bill_to = v.require_enum(body, "bill_to", {"CLINIC_ACCOUNT", "OWNER"})
    clinic_id = v.optional_string(body, "clinic_id", default=None)

    # FK existence (priority 3)
    get_or_404(store.petowners, owner_id)
    if clinic_id is not None:
        get_or_404(store.clinics, clinic_id)

    # Ownership scope (priority 5): ClinicStaff may only intake for own clinic.
    if p.role == "ClinicStaff":
        if clinic_id != p.user_id:
            raise errors.err(errors.ERR_FORBIDDEN, "ClinicStaff may only submit intakes for own clinic")

    # Account-billing prerequisite (priority 6)
    if bill_to == "CLINIC_ACCOUNT" and clinic_id is None:
        raise errors.err(errors.ERR_CLINIC_REQUIRED_FOR_ACCOUNT_BILLING, "CLINIC_ACCOUNT billing requires clinic_id")

    case = models.make_case(clinic_id, owner_id, pet_name, species, weight_lbs,
                            service_type, expedited, pickup_kind, bill_to)
    services.case_create_intake(case)
    return success(models.serialize_case(case), 201)


@app.route("/cases/<rid>", methods=["GET"])
def get_case(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"})
    case = get_or_404(store.cases, rid)
    enforce_case_ownership(p, case)
    return success(models.serialize_case(case), 200)


@app.route("/cases", methods=["GET"])
def list_cases():
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"})
    items = list(store.cases.values())
    # ownership-scoped narrowing for entity-backed principals
    if p.role == "PetOwner":
        items = [c for c in items if c["owner_id"] == p.user_id]
    elif p.role == "ClinicStaff":
        items = [c for c in items if c["clinic_id"] == p.user_id]
    for key, field in (("clinic_id", "clinic_id"), ("owner_id", "owner_id"),
                       ("batch_id", "batch_id"), ("cooler_id", "cooler_id"),
                       ("custody_status", "custody_status"), ("billing_status", "billing_status")):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    return list_response(items, models.serialize_case)


@app.route("/cases/<rid>/transport-legs", methods=["POST"])
def create_transport_leg(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    case = get_or_404(store.cases, rid)
    body = v.get_json_body()
    origin_kind = v.require_enum(body, "origin_kind", {"CLINIC", "HOME"})
    origin_label = v.require_string(body, "origin_label")
    driver_name = v.require_string(body, "driver_name")
    leg = services.case_transition_transport(case, origin_kind, origin_label, driver_name)
    return success(models.serialize_transport_leg(leg), 201)


@app.route("/cases/<rid>/transport-legs", methods=["GET"])
def list_transport_legs(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator"})
    get_or_404(store.cases, rid)
    items = [t for t in store.transport_legs.values() if t["case_id"] == rid]
    return list_response(items, models.serialize_transport_leg)


@app.route("/transport-legs/<rid>", methods=["PATCH"])
def patch_transport_leg(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    leg = get_or_404(store.transport_legs, rid)
    body = v.get_json_body()
    target = v.require_enum(body, "status", {"EN_ROUTE", "ARRIVED", "CANCELLED", "ASSIGNED"})
    services.transport_leg_transition(leg, target)
    return success(models.serialize_transport_leg(leg), 200)


@app.route("/transport-legs/<rid>", methods=["GET"])
def get_transport_leg(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator"})
    leg = get_or_404(store.transport_legs, rid)
    return success(models.serialize_transport_leg(leg), 200)


@app.route("/cases/<rid>/custody-events", methods=["GET"])
def list_custody_events(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"})
    case = get_or_404(store.cases, rid)
    enforce_case_ownership(p, case)
    items = [e for e in store.custody_events.values() if e["case_id"] == rid]
    # custody events are listed in seq order
    limit, offset = v.parse_pagination()
    ordered = sorted(items, key=lambda e: e["seq"])
    total = len(ordered)
    page = v.paginate(ordered, limit, offset)
    return success_list([models.serialize_custody_event(e) for e in page], limit, offset, total)


@app.route("/cases/<rid>/receive", methods=["POST"])
def receive_case(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    case = get_or_404(store.cases, rid)
    services.case_receive(case)
    return success(models.serialize_case(case), 200)


@app.route("/cases/<rid>/store", methods=["POST"])
def store_case(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    case = get_or_404(store.cases, rid)
    body = v.get_json_body()
    cooler_id = v.require_string(body, "cooler_id")
    cooler = get_or_404(store.coolers, cooler_id)
    services.case_store(case, cooler)
    return success(models.serialize_case(case), 200)


@app.route("/cases/<rid>/ready-return", methods=["POST"])
def ready_return_case(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    case = get_or_404(store.cases, rid)
    body = v.get_json_body()
    return_method = v.require_enum(body, "return_method",
                                   {"PICKUP_AT_FACILITY", "COURIER_TO_CLINIC", "COURIER_TO_HOME"})
    destination_label = v.require_string(body, "destination_label")
    services.case_ready_return(case, return_method, destination_label)
    return success(models.serialize_case(case), 200)


@app.route("/cases/<rid>/finalize-return", methods=["POST"])
def finalize_return_case(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    case = get_or_404(store.cases, rid)
    services.case_finalize_return(case)
    return success(models.serialize_case(case), 200)


@app.route("/cases/<rid>/cancel", methods=["POST"])
def cancel_case(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator", "CrematoryAdmin"})
    case = get_or_404(store.cases, rid)
    services.case_cancel(case)
    return success(models.serialize_case(case), 200)


@app.route("/cases/<rid>/invoices", methods=["POST"])
def create_invoice(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin"})
    case = get_or_404(store.cases, rid)
    body = v.get_json_body()
    expected_case_version = v.require_int(body, "expected_case_version")
    invoice = services.issue_invoice(case, expected_case_version)
    return success(models.serialize_invoice(invoice), 201)


@app.route("/cases/<rid>/invoices", methods=["GET"])
def list_case_invoices(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"})
    case = get_or_404(store.cases, rid)
    enforce_case_ownership(p, case)
    items = [i for i in store.invoices.values() if i["case_id"] == rid]
    return list_response(items, models.serialize_invoice)


# ===========================================================================
# KeepsakeOrder
# ===========================================================================
@app.route("/cases/<rid>/keepsake-orders", methods=["POST"])
def create_keepsake(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator", "ClinicStaff"})
    case = get_or_404(store.cases, rid)
    if p.role == "ClinicStaff":
        enforce_case_ownership(p, case)
    body = v.get_json_body()
    item_type = v.require_enum(body, "item_type",
                               {"PAW_PRINT", "CLAY_IMPRESSION", "FUR_CLIPPING", "URN", "PENDANT"})
    k = models.make_keepsake_order(case["id"], item_type)
    return success(models.serialize_keepsake_order(k), 201)


@app.route("/cases/<rid>/keepsake-orders", methods=["GET"])
def list_keepsakes(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"})
    case = get_or_404(store.cases, rid)
    enforce_case_ownership(p, case)
    items = [k for k in store.keepsake_orders.values() if k["case_id"] == rid]
    return list_response(items, models.serialize_keepsake_order)


@app.route("/keepsake-orders/<rid>", methods=["PATCH"])
def patch_keepsake(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    k = get_or_404(store.keepsake_orders, rid)
    body = v.get_json_body()
    target = v.require_enum(body, "status", {"IN_PRODUCTION", "READY", "CANCELLED", "ORDERED"})
    services.keepsake_transition(k, target)
    return success(models.serialize_keepsake_order(k), 200)


# ===========================================================================
# CertificateRecord
# ===========================================================================
@app.route("/cases/<rid>/certificates", methods=["GET"])
def list_certificates(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"})
    case = get_or_404(store.cases, rid)
    enforce_case_ownership(p, case)
    items = [c for c in store.certificates.values() if c["case_id"] == rid]
    return list_response(items, models.serialize_certificate)


# ===========================================================================
# ReturnRoute
# ===========================================================================
@app.route("/cases/<rid>/return-routes", methods=["GET"])
def list_return_routes(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"})
    case = get_or_404(store.cases, rid)
    enforce_case_ownership(p, case)
    items = [r for r in store.return_routes.values() if r["case_id"] == rid]
    return list_response(items, models.serialize_return_route)


@app.route("/return-routes/<rid>/dispatch", methods=["POST"])
def dispatch_route(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    route = get_or_404(store.return_routes, rid)
    services.return_route_dispatch(route)
    return success(models.serialize_return_route(route), 200)


@app.route("/return-routes/<rid>/cancel", methods=["POST"])
def cancel_route(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    route = get_or_404(store.return_routes, rid)
    services.return_route_cancel(route)
    return success(models.serialize_return_route(route), 200)


# ===========================================================================
# MemorialAddon
# ===========================================================================
@app.route("/cases/<rid>/memorial-addons", methods=["POST"])
def create_memorial(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator", "ClinicStaff"})
    case = get_or_404(store.cases, rid)
    if p.role == "ClinicStaff":
        enforce_case_ownership(p, case)
    body = v.get_json_body()
    addon_type = v.require_enum(body, "addon_type",
                                {"ONLINE_MEMORIAL", "VIEWING_SESSION", "TRIBUTE_VIDEO"})
    viewing_room_code = None
    viewing_start = None
    viewing_end = None
    if addon_type == "VIEWING_SESSION":
        viewing_room_code = body.get("viewing_room_code")
        viewing_start = body.get("viewing_start")
        viewing_end = body.get("viewing_end")
        if (not isinstance(viewing_room_code, str) or not viewing_room_code
                or not isinstance(viewing_start, str) or not viewing_start
                or not isinstance(viewing_end, str) or not viewing_end):
            raise errors.err(errors.ERR_VIEWING_FIELDS_REQUIRED, "Viewing session fields required")
        try:
            start_dt = parse_iso8601(viewing_start)
            end_dt = parse_iso8601(viewing_end)
        except Exception:
            raise errors.err(errors.ERR_VIEWING_FIELDS_REQUIRED, "viewing_start/end must be ISO 8601")
        if end_dt <= start_dt:
            raise errors.err(errors.ERR_VIEWING_FIELDS_REQUIRED, "viewing_end must be after viewing_start")
        # room scheduling (priority 12)
        services.check_viewing_room_conflict(viewing_room_code, viewing_start, viewing_end)
    m = models.make_memorial_addon(case["id"], addon_type, viewing_room_code, viewing_start, viewing_end)
    return success(models.serialize_memorial_addon(m), 201)


@app.route("/cases/<rid>/memorial-addons", methods=["GET"])
def list_memorials(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"})
    case = get_or_404(store.cases, rid)
    enforce_case_ownership(p, case)
    items = [m for m in store.memorial_addons.values() if m["case_id"] == rid]
    return list_response(items, models.serialize_memorial_addon)


@app.route("/memorial-addons/<rid>", methods=["PATCH"])
def patch_memorial(rid):
    p = authenticate()
    require_role(p, {"CrematoryOperator"})
    m = get_or_404(store.memorial_addons, rid)
    body = v.get_json_body()
    target = v.require_enum(body, "status", {"FULFILLED", "CANCELLED", "BOOKED"})
    services.memorial_transition(m, target)
    return success(models.serialize_memorial_addon(m), 200)


# ===========================================================================
# Invoice
# ===========================================================================
@app.route("/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"})
    inv = get_or_404(store.invoices, rid)
    enforce_invoice_ownership(p, inv)
    return success(models.serialize_invoice(inv), 200)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff"})
    items = list(store.invoices.values())
    if p.role == "ClinicStaff":
        items = [i for i in items if i["clinic_id"] == p.user_id]
    case_id = request.args.get("case_id")
    clinic_id = request.args.get("clinic_id")
    status = request.args.get("status")
    if case_id:
        items = [i for i in items if i["case_id"] == case_id]
    if clinic_id:
        items = [i for i in items if i["clinic_id"] == clinic_id]
    if status:
        items = [i for i in items if i["status"] == status]
    return list_response(items, models.serialize_invoice)


@app.route("/invoices/<rid>/pay", methods=["POST"])
def pay_invoice(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin", "PetOwner"})
    inv = get_or_404(store.invoices, rid)
    if p.role == "PetOwner":
        enforce_invoice_ownership(p, inv)
    services.invoice_pay(inv)
    return success(models.serialize_invoice(inv), 200)


@app.route("/invoices/<rid>/void", methods=["POST"])
def void_invoice(rid):
    p = authenticate()
    require_role(p, {"CrematoryAdmin"})
    inv = get_or_404(store.invoices, rid)
    services.invoice_void(inv)
    return success(models.serialize_invoice(inv), 200)


def _serve():
    """Serve via waitress (production WSGI), falling back to Flask's dev server.

    Under per-test-server isolation the process is killed and re-launched before
    every test, 8 rounds concurrently. The freshly-spawned process can briefly
    find the port still held by the just-killed predecessor; we set SO_REUSEADDR
    and retry the bind for a short window so a transient "address in use" does not
    crash the boot into a "server exited prematurely" restart failure.
    """
    import socket
    import time

    port = int(os.environ.get("PORT", "10000"))

    try:
        from waitress import serve as waitress_serve
    except Exception:
        # Last-resort fallback: Flask's threaded dev server.
        app.run(host="0.0.0.0", port=port, threaded=True)
        return

    # Bind the listening socket OURSELVES (SO_REUSEADDR), retrying on transient
    # "address in use" while the SIGKILLed predecessor's socket is released.
    # Holding the bound socket closes the TOCTOU gap a probe-then-rebind leaves,
    # then hand it straight to waitress so the server is reachable immediately.
    deadline = time.time() + 12.0
    last_err = None
    sock = None
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            s.listen(128)
            s.setblocking(False)
            sock = s
            break
        except OSError as e:
            last_err = e
            s.close()
            time.sleep(0.05)
    if sock is None:
        raise SystemExit(f"Could not bind port {port}: {last_err}")
    waitress_serve(app, sockets=[sock], threads=8)


if __name__ == "__main__":
    _serve()
