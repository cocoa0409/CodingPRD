"""Routes: code violations, municipal registrations, daily operational sweep."""

from flask import Blueprint, request

from auth import get_auth, require_role, ANY_ROLE
from db import store, new_entity, bump, public, clock_date
from errors import raise_err
from response import ok, ok_list
from services import (
    recompute_property_score, registration_overlaps, has_active_registration,
    refresh_accrued_fine, compute_accrued_fine, run_daily_sweep,
)
from util import (
    get_body, req_str, req_amount, req_enum, req_date, get_or_404,
    parse_pagination, paginate, sort_created, parse_date_str, VIOLATION_CLASSES,
)

bp = Blueprint("muni", __name__)


# ---- Ops: daily sweep -----------------------------------------------------------

@bp.post("/preservation/ops/run-daily-sweep")
def daily_sweep():
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    get_body()
    result = run_daily_sweep()
    return ok(result)


# ---- CodeViolation ---------------------------------------------------------------

@bp.post("/preservation/code-violations")
def create_violation():
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    b = get_body()
    property_id = b.get("property_id")
    if property_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: property_id")
    if not isinstance(property_id, str):
        raise_err("ERR_INVALID_REQUEST", "property_id must be a string")
    prop = get_or_404(store.properties, property_id, "Property")

    citation_number = req_str(b, "citation_number")
    violation_class = req_enum(b, "violation_class", VIOLATION_CLASSES)
    daily_fine_cents = req_amount(b, "daily_fine_cents")
    fine_cap_cents = req_amount(b, "fine_cap_cents")
    cure_deadline = req_date(b, "cure_deadline")

    # Referential (tier 7): citation number unique within the property's municipality.
    for v in store.violations.values():
        other_prop = store.properties.get(v["property_id"])
        if (
            other_prop is not None
            and other_prop["municipality_code"] == prop["municipality_code"]
            and v["citation_number"] == citation_number
        ):
            raise_err("ERR_CITATION_NOT_UNIQUE", "citation_number already used in this municipality")

    v = new_entity({
        "property_id": prop["id"],
        "citation_number": citation_number,
        "violation_class": violation_class,
        "daily_fine_cents": daily_fine_cents,
        "fine_cap_cents": fine_cap_cents,
        "cure_deadline": cure_deadline,
        "accrued_fine_cents": 0,
        "cure_work_order_id": None,
        "status": "OPEN",
    })
    store.violations[v["id"]] = v
    recompute_property_score(prop)
    return ok(public(v), status=201)


@bp.get("/preservation/code-violations/<violationId>")
def get_violation(violationId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    v = get_or_404(store.violations, violationId, "CodeViolation")
    refresh_accrued_fine(v)
    return ok(public(v))


@bp.get("/preservation/code-violations")
def list_violations():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.violations.values())
    for field in ("property_id", "cure_work_order_id", "status"):
        f = request.args.get(field)
        if f is not None:
            items = [v for v in items if v.get(field) == f]
    items = sort_created(items)
    for v in items:
        refresh_accrued_fine(v)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.post("/preservation/code-violations/<violationId>/start-cure")
def start_cure(violationId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    v = get_or_404(store.violations, violationId, "CodeViolation")
    b = get_body()
    work_order_id = b.get("work_order_id")
    wo = None
    if work_order_id is not None:
        if not isinstance(work_order_id, str):
            raise_err("ERR_INVALID_REQUEST", "work_order_id must be a string")
        wo = get_or_404(store.work_orders, work_order_id, "WorkOrder")
    if work_order_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: work_order_id")
    if wo["order_type"] != "CODE_CURE" or wo["status"] not in ("ISSUED", "ASSIGNED", "IN_PROGRESS"):
        raise_err("ERR_INVALID_REQUEST", "work_order_id must reference a CODE_CURE work order in ISSUED, ASSIGNED, or IN_PROGRESS")

    if v["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Violation is not OPEN")

    # Referential gate ranks above the temporal gate (PRD section 2.7).
    prop = store.properties.get(v["property_id"])
    if prop is None or not has_active_registration(prop, clock_date()):
        raise_err("ERR_REGISTRATION_REQUIRED", "An ACTIVE municipal registration is required to start a cure")
    if clock_date() > parse_date_str(v["cure_deadline"], "cure_deadline"):
        raise_err("ERR_CURE_DEADLINE_PASSED", "The cure deadline has passed")

    v["cure_work_order_id"] = work_order_id
    v["status"] = "CURE_IN_PROGRESS"
    bump(v)
    return ok(public(v))


@bp.post("/preservation/code-violations/<violationId>/submit-cure")
def submit_cure(violationId):
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    v = get_or_404(store.violations, violationId, "CodeViolation")
    get_body()
    if v["status"] != "CURE_IN_PROGRESS":
        raise_err("ERR_INVALID_STATE", "Violation is not CURE_IN_PROGRESS")
    wo = store.work_orders.get(v.get("cure_work_order_id") or "")
    if wo is None or wo["status"] != "COMPLETED":
        raise_err("ERR_CURE_WORK_INCOMPLETE", "Linked cure work order is not COMPLETED")
    v["status"] = "CURE_SUBMITTED"
    bump(v)
    return ok(public(v))


@bp.post("/preservation/code-violations/<violationId>/verify")
def verify_violation(violationId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    v = get_or_404(store.violations, violationId, "CodeViolation")
    get_body()
    if v["status"] != "CURE_SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Violation is not CURE_SUBMITTED")
    # Freeze the accrued fine at its current value.
    v["accrued_fine_cents"] = compute_accrued_fine(v)
    v["status"] = "VERIFIED_CLOSED"
    bump(v)
    prop = store.properties.get(v["property_id"])
    if prop is not None:
        recompute_property_score(prop)
    return ok(public(v))


@bp.post("/preservation/code-violations/<violationId>/reject-cure")
def reject_cure(violationId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    v = get_or_404(store.violations, violationId, "CodeViolation")
    b = get_body()
    req_str(b, "reason")
    if v["status"] != "CURE_SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Violation is not CURE_SUBMITTED")
    v["status"] = "CURE_IN_PROGRESS"
    bump(v)
    return ok(public(v))


# ---- MunicipalRegistration ---------------------------------------------------------

@bp.post("/preservation/registrations")
def create_registration():
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    b = get_body()
    property_id = b.get("property_id")
    if property_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: property_id")
    if not isinstance(property_id, str):
        raise_err("ERR_INVALID_REQUEST", "property_id must be a string")
    prop = get_or_404(store.properties, property_id, "Property")

    municipality_code = req_str(b, "municipality_code")
    registration_number = req_str(b, "registration_number")
    fee_cents = req_amount(b, "fee_cents")
    valid_from = req_date(b, "valid_from")
    valid_to = req_date(b, "valid_to")

    # Referential (tier 7): registration number unique within the municipality.
    for r in store.registrations.values():
        if r["municipality_code"] == municipality_code and r["registration_number"] == registration_number:
            raise_err("ERR_REGISTRATION_NUMBER_NOT_UNIQUE", "registration_number already used in this municipality")

    reg = new_entity({
        "property_id": prop["id"],
        "municipality_code": municipality_code,
        "registration_number": registration_number,
        "fee_cents": fee_cents,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "renewal_count": 0,
        "status": "PENDING",
    })
    store.registrations[reg["id"]] = reg
    return ok(public(reg), status=201)


@bp.get("/preservation/registrations/<registrationId>")
def get_registration(registrationId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    reg = get_or_404(store.registrations, registrationId, "MunicipalRegistration")
    return ok(public(reg))


@bp.get("/preservation/registrations")
def list_registrations():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.registrations.values())
    for field in ("property_id", "municipality_code", "status"):
        f = request.args.get(field)
        if f is not None:
            items = [r for r in items if r.get(field) == f]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.post("/preservation/registrations/<registrationId>/activate")
def activate_registration(registrationId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    reg = get_or_404(store.registrations, registrationId, "MunicipalRegistration")
    get_body()
    if reg["status"] != "PENDING":
        raise_err("ERR_INVALID_STATE", "Registration is not PENDING")
    if registration_overlaps(reg):
        raise_err("ERR_REGISTRATION_OVERLAP", "Window overlaps an ACTIVE registration for this property and municipality")
    reg["status"] = "ACTIVE"
    bump(reg)
    prop = store.properties.get(reg["property_id"])
    if prop is not None:
        recompute_property_score(prop)
    return ok(public(reg))


@bp.post("/preservation/registrations/<registrationId>/renew")
def renew_registration(registrationId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    reg = get_or_404(store.registrations, registrationId, "MunicipalRegistration")
    b = get_body()
    new_valid_to = req_date(b, "new_valid_to")

    if reg["status"] == "ACTIVE":
        if parse_date_str(new_valid_to, "new_valid_to") <= parse_date_str(reg["valid_to"], "valid_to"):
            raise_err("ERR_INVALID_REQUEST", "new_valid_to must be after the current valid_to")
        reg["valid_to"] = new_valid_to
        reg["renewal_count"] += 1
        bump(reg)
    elif reg["status"] == "EXPIRED":
        today = clock_date()
        if parse_date_str(new_valid_to, "new_valid_to") <= today:
            raise_err("ERR_INVALID_REQUEST", "new_valid_to must be after the clock date")
        reg["valid_from"] = today.isoformat()
        reg["valid_to"] = new_valid_to
        reg["renewal_count"] += 1
        reg["status"] = "ACTIVE"
        bump(reg)
        prop = store.properties.get(reg["property_id"])
        if prop is not None:
            recompute_property_score(prop)
    else:
        raise_err("ERR_INVALID_STATE", "Registration is not ACTIVE or EXPIRED")
    return ok(public(reg))


@bp.post("/preservation/registrations/<registrationId>/release")
def release_registration(registrationId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    reg = get_or_404(store.registrations, registrationId, "MunicipalRegistration")
    get_body()
    if reg["status"] not in ("ACTIVE", "EXPIRED"):
        raise_err("ERR_INVALID_STATE", "Registration is not ACTIVE or EXPIRED")
    was_active = reg["status"] == "ACTIVE"
    reg["status"] = "RELEASED"
    bump(reg)
    if was_active:
        prop = store.properties.get(reg["property_id"])
        if prop is not None:
            recompute_property_score(prop)
    return ok(public(reg))
