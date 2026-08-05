"""Safe-Deposit & Private-Vault Service API — Flask application."""
import os
from functools import partial
from datetime import timedelta

from flask import Flask, request

import store
import logic
from store import (
    DB, clock_now_iso, clock_now_date, clock_now, set_clock, parse_iso, to_date,
    iso, add_months,
)
from helpers import (
    ApiError, ok, ok_list, error_response, authenticate, require_role,
    parse_pagination, paginate, get_body, make_record, touch, public,
    get_or_404, fk_or_404, sorted_records,
    err_unauth, err_forbidden, err_not_found, err_invalid_request, err_validation,
    err_state,
)

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc)


@app.errorhandler(404)
def handle_404(_e):
    return error_response(err_not_found("Route not found"))


@app.errorhandler(405)
def handle_405(_e):
    return error_response(err_forbidden("Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc)
    return error_response(ApiError("ERR_INTERNAL", 500, str(exc)))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def require_present(body, *names):
    for n in names:
        if body.get(n) is None:
            raise err_invalid_request(f"Missing required field: {n}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err_invalid_request(f"Invalid {field}: {value}")


def require_int(body, field, positive=False, nonneg=False):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_invalid_request(f"{field} must be an integer")
    if positive and v <= 0:
        raise err_invalid_request(f"{field} must be > 0")
    if nonneg and v < 0:
        raise err_invalid_request(f"{field} must be >= 0")
    return v


def check_renter_ownership(role, uid, rental):
    if role == "Renter" and rental["renter_id"] != uid:
        raise err_forbidden("Renter may only act on their own rentals")


def apply_filters(records, fields):
    out = records
    for f in fields:
        val = request.args.get(f)
        if val is not None:
            out = [r for r in out if str(r.get(f)) == val]
    return out


# ---------------------------------------------------------------------------
# Generic read endpoints (all GET operations are role "Any")
# ---------------------------------------------------------------------------
def get_one(collection, rid):
    authenticate()
    rec = get_or_404(collection, rid)
    return ok(public(rec))


def list_entities(collection, filter_fields, rid=None):
    authenticate()
    records = sorted_records(collection)
    records = apply_filters(records, filter_fields)
    page, limit, offset, total = paginate(records)
    return ok_list([public(r) for r in page], limit, offset, total)


READ_SPECS = [
    ("branches", "branches", ["status"]),
    ("box-types", "box_types", ["size_class"]),
    ("boxes", "boxes", ["branch_id", "box_type_id", "status"]),
    ("renters", "renters", ["kyc_status", "standing"]),
    ("rentals", "rentals", ["box_id", "renter_id", "status"]),
    ("invoices", "invoices", ["rental_id", "status"]),
    ("payments", "payments", ["rental_id", "invoice_id"]),
    ("access-grants", "access_grants", ["rental_id", "grantee_renter_id", "status"]),
    ("access-appointments", "access_appointments",
        ["box_id", "rental_id", "branch_id", "grant_id", "status"]),
    ("access-events", "access_events", ["appointment_id", "box_id", "rental_id"]),
    ("inventory-items", "inventory_items", ["rental_id", "status"]),
    ("drilling-orders", "drilling_orders", ["box_id", "rental_id", "status"]),
    ("compliance-cases", "compliance_cases", ["renter_id", "rental_id", "status"]),
]

for _path, _coll, _filters in READ_SPECS:
    app.add_url_rule(
        f"/vault/{_path}/<rid>", endpoint=f"get_{_coll}",
        view_func=partial(get_one, _coll), methods=["GET"],
    )
    app.add_url_rule(
        f"/vault/{_path}", endpoint=f"list_{_coll}",
        view_func=partial(list_entities, _coll, _filters), methods=["GET"],
    )


def create_and_store(collection, fields, common=True):
    rec = make_record(fields, common=common)
    DB[collection][rec["id"]] = rec
    return rec


# ===========================================================================
# Branches
# ===========================================================================
@app.post("/vault/branches")
def create_branch():
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    body = get_body()
    require_present(body, "name", "code", "viewing_room_capacity")
    cap = require_int(body, "viewing_room_capacity")
    if cap < 1:
        raise err_invalid_request("viewing_room_capacity must be >= 1")
    rec = create_and_store("branches", {
        "name": body["name"], "code": body["code"],
        "viewing_room_capacity": cap, "status": "OPEN",
    })
    return ok(public(rec), 201)


# ===========================================================================
# Box types
# ===========================================================================
@app.post("/vault/box-types")
def create_box_type():
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    body = get_body()
    require_present(body, "size_class", "annual_rate_cents", "height_mm", "width_mm", "depth_mm")
    require_enum(body["size_class"], {"SMALL", "MEDIUM", "LARGE", "JUMBO"}, "size_class")
    rate = require_int(body, "annual_rate_cents", positive=True)
    for dim in ("height_mm", "width_mm", "depth_mm"):
        require_int(body, dim)
    rec = create_and_store("box_types", {
        "size_class": body["size_class"], "annual_rate_cents": rate,
        "height_mm": body["height_mm"], "width_mm": body["width_mm"],
        "depth_mm": body["depth_mm"],
    })
    return ok(public(rec), 201)


# ===========================================================================
# Boxes
# ===========================================================================
@app.post("/vault/boxes")
def create_box():
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    body = get_body()
    # existence of provided FKs (left to right)
    if body.get("branch_id") is not None:
        fk_or_404("branches", body["branch_id"])
    if body.get("box_type_id") is not None:
        fk_or_404("box_types", body["box_type_id"])
    require_present(body, "branch_id", "box_type_id", "box_number")
    rec = create_and_store("boxes", {
        "branch_id": body["branch_id"], "box_type_id": body["box_type_id"],
        "box_number": body["box_number"], "status": "AVAILABLE",
    })
    return ok(public(rec), 201)


@app.post("/vault/boxes/<rid>/decommission")
def decommission_box(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    box = get_or_404("boxes", rid)
    if box["status"] != "AVAILABLE":
        raise ApiError("ERR_BOX_NOT_AVAILABLE", 409, "Box is not AVAILABLE")
    box["status"] = "OUT_OF_SERVICE"
    touch(box)
    return ok(public(box))


@app.post("/vault/boxes/<rid>/return-to-service")
def return_box_to_service(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    box = get_or_404("boxes", rid)
    if box["status"] != "DRILLED":
        raise err_state("Box is not DRILLED")
    for r in DB["rentals"].values():
        if r["box_id"] == box["id"] and r["status"] in ("ACTIVE", "PAST_DUE", "DELINQUENT", "SURRENDER_PENDING"):
            raise err_state("An active rental still references this box")
    box["status"] = "AVAILABLE"
    touch(box)
    return ok(public(box))


# ===========================================================================
# Renters
# ===========================================================================
@app.post("/vault/renters")
def create_renter():
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin", "BillingClerk"})
    body = get_body()
    require_present(body, "full_name", "email", "gov_id_ref", "date_of_birth")
    rec = create_and_store("renters", {
        "full_name": body["full_name"], "email": body["email"],
        "gov_id_ref": body["gov_id_ref"], "date_of_birth": body["date_of_birth"],
        "kyc_status": "PENDING", "standing": "GOOD", "is_deceased": False,
    })
    return ok(public(rec), 201)


@app.post("/vault/renters/<rid>/verify-kyc")
def verify_kyc(rid):
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    renter = get_or_404("renters", rid)
    body = get_body()
    if renter["kyc_status"] != "PENDING":
        raise err_state("KYC decision already recorded")
    decision = body.get("decision")
    if decision is not None and str(decision).upper() in ("REJECT", "REJECTED"):
        renter["kyc_status"] = "REJECTED"
    else:
        renter["kyc_status"] = "VERIFIED"
    touch(renter)
    return ok(public(renter))


# ===========================================================================
# Compliance cases
# ===========================================================================
@app.post("/vault/compliance-cases")
def create_compliance_case():
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    body = get_body()
    if body.get("renter_id") is not None:
        fk_or_404("renters", body["renter_id"])
    if body.get("rental_id") is not None:
        fk_or_404("rentals", body["rental_id"])
    require_present(body, "renter_id", "case_type")
    require_enum(body["case_type"], {"KYC", "SANCTIONS", "SAR", "CTR"}, "case_type")
    severity = body.get("severity", "STANDARD")
    require_enum(severity, {"STANDARD", "HOLD"}, "severity")
    rec = create_and_store("compliance_cases", {
        "renter_id": body["renter_id"], "rental_id": body.get("rental_id"),
        "case_type": body["case_type"], "severity": severity,
        "opened_on": clock_now_iso(), "resolved_on": None, "status": "OPEN",
    })
    if severity == "HOLD":
        renter = DB["renters"][body["renter_id"]]
        renter["standing"] = "FROZEN"
        touch(renter)
    return ok(public(rec), 201)


@app.post("/vault/compliance-cases/<rid>/escalate")
def escalate_case(rid):
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    case = get_or_404("compliance_cases", rid)
    if case["status"] != "OPEN":
        raise err_state("Case is not OPEN")
    case["status"] = "ESCALATED"
    touch(case)
    return ok(public(case))


@app.post("/vault/compliance-cases/<rid>/clear")
def clear_case(rid):
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    case = get_or_404("compliance_cases", rid)
    if case["status"] not in ("OPEN", "ESCALATED"):
        raise err_state("Case cannot be cleared")
    case["status"] = "CLEARED"
    case["resolved_on"] = clock_now_iso()
    touch(case)
    renter = DB["renters"].get(case["renter_id"])
    if renter:
        prev = renter["standing"]
        logic.refresh_standing(renter)
        if renter["standing"] != prev:
            touch(renter)
    return ok(public(case))


# ===========================================================================
# System utilities
# ===========================================================================
@app.post("/vault/_clock/set_current_utc")
def set_clock_endpoint():
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    body = get_body()
    require_present(body, "to_iso8601")
    dt = parse_iso(body["to_iso8601"])
    if dt is None:
        raise err_invalid_request("Invalid to_iso8601")
    set_clock(dt)
    return ok({"current_utc": clock_now_iso()})


@app.post("/vault/_billing/run_cycle")
def run_cycle_endpoint():
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    result = logic.run_billing_cycle()
    return ok(result)


# ===========================================================================
# Rentals
# ===========================================================================
@app.post("/vault/rentals")
def create_rental():
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin", "BillingClerk"})
    body = get_body()
    if body.get("box_id") is not None:
        box = fk_or_404("boxes", body["box_id"])
    else:
        box = None
    if body.get("renter_id") is not None:
        fk_or_404("renters", body["renter_id"])
    require_present(body, "box_id", "renter_id")
    box = DB["boxes"][body["box_id"]]
    term = body.get("plan_term_months", 12)
    if term is None:
        term = 12
    if not isinstance(term, int) or isinstance(term, bool) or term < 1:
        raise err_invalid_request("plan_term_months must be an integer >= 1")
    declared = body.get("declared_contents_value_cents", 0)
    if declared is None:
        declared = 0
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 0:
        raise err_invalid_request("declared_contents_value_cents must be a non-negative integer")
    box_type = DB["box_types"].get(box["box_type_id"])
    annual = box_type["annual_rate_cents"] if box_type else 0
    rec = create_and_store("rentals", {
        "box_id": body["box_id"], "renter_id": body["renter_id"],
        "plan_term_months": term,
        "annual_rate_cents": annual,
        "autopay_enabled": bool(body.get("autopay_enabled", False)),
        "autopay_source_ref": body.get("autopay_source_ref"),
        "insurance_rider_enabled": bool(body.get("insurance_rider_enabled", False)),
        "declared_contents_value_cents": declared,
        "start_date": None,
        "balance_due_cents": 0,
        "paid_through_date": None,
        "delinquent_since": None,
        "surrender_requested_at": None,
        "provisional_refund_cents": None,
        "final_refund_cents": None,
        "status": "PENDING",
    })
    return ok(public(rec), 201)


@app.post("/vault/rentals/<rid>/activate")
def activate_rental(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin", "BillingClerk"})
    rental = get_or_404("rentals", rid)
    renter = DB["renters"].get(rental["renter_id"])
    # 5. compliance/identity safety
    if not renter or renter["kyc_status"] != "VERIFIED":
        raise ApiError("ERR_KYC_NOT_VERIFIED", 409, "Renter KYC is not VERIFIED")
    if renter["standing"] != "GOOD" or logic.has_open_hold(renter["id"]):
        raise ApiError("ERR_COMPLIANCE_HOLD", 409, "Renter has an open compliance hold")
    # 6. state
    if rental["status"] != "PENDING":
        raise err_state("Rental is not PENDING")
    box = DB["boxes"].get(rental["box_id"])
    if not box or box["status"] != "AVAILABLE":
        raise ApiError("ERR_BOX_NOT_AVAILABLE", 409, "Box is not AVAILABLE")
    # transition
    rental["status"] = "ACTIVE"
    rental["start_date"] = clock_now_iso()
    box["status"] = "RENTED"
    touch(box)
    logic.issue_first_invoice(rental)
    logic.recompute_balance(rental)
    touch(rental)
    return ok(public(rental))


@app.post("/vault/rentals/<rid>/adjust-plan")
def adjust_plan(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    rental = get_or_404("rentals", rid)
    body = get_body()
    require_present(body, "expected_rental_version")
    if "plan_term_months" in body and body["plan_term_months"] is not None:
        t = body["plan_term_months"]
        if not isinstance(t, int) or isinstance(t, bool) or t < 1:
            raise err_invalid_request("plan_term_months must be an integer >= 1")
    # 11. optimistic concurrency (last)
    if body["expected_rental_version"] != rental["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_rental_version does not match")
    if "plan_term_months" in body and body["plan_term_months"] is not None:
        rental["plan_term_months"] = body["plan_term_months"]
    if "autopay_enabled" in body and body["autopay_enabled"] is not None:
        rental["autopay_enabled"] = bool(body["autopay_enabled"])
    if "autopay_source_ref" in body:
        rental["autopay_source_ref"] = body["autopay_source_ref"]
    touch(rental)
    return ok(public(rental))


@app.post("/vault/rentals/<rid>/request-surrender")
def request_surrender(rid):
    uid, role = authenticate()
    require_role(role, {"Renter", "VaultAdmin"})
    rental = get_or_404("rentals", rid)
    check_renter_ownership(role, uid, rental)
    if rental["status"] != "ACTIVE":
        raise err_state("Rental is not ACTIVE")
    rental["status"] = "SURRENDER_PENDING"
    rental["surrender_requested_at"] = clock_now_iso()
    rental["provisional_refund_cents"] = logic.compute_provisional_refund(rental)
    touch(rental)
    return ok(public(rental))


@app.post("/vault/rentals/<rid>/close")
def close_rental(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    rental = get_or_404("rentals", rid)
    if rental["status"] != "SURRENDER_PENDING":
        raise err_state("Rental is not SURRENDER_PENDING")
    logic.recompute_balance(rental)
    if rental["balance_due_cents"] != 0:
        raise ApiError("ERR_OUTSTANDING_BALANCE", 409, "Rental has an outstanding balance")
    for appt in DB["access_appointments"].values():
        if appt["rental_id"] == rental["id"] and appt["status"] in ("BOOKED", "CHECKED_IN"):
            raise ApiError("ERR_APPOINTMENT_ACTIVE", 409, "Rental has an active appointment")
    rental["status"] = "CLOSED"
    rental["final_refund_cents"] = logic.compute_final_refund(rental)
    box = DB["boxes"].get(rental["box_id"])
    if box:
        box["status"] = "AVAILABLE"
        touch(box)
    for grant in DB["access_grants"].values():
        if grant["rental_id"] == rental["id"] and grant["status"] in ("ACTIVE", "SUSPENDED"):
            grant["status"] = "REVOKED"
            touch(grant)
    for item in DB["inventory_items"].values():
        if item["rental_id"] == rental["id"] and item["status"] != "RELEASED":
            item["status"] = "RELEASED"
            touch(item)
    touch(rental)
    return ok(public(rental))


# ===========================================================================
# Invoices
# ===========================================================================
@app.post("/vault/invoices")
def create_invoice():
    _uid, role = authenticate()
    require_role(role, {"BillingClerk", "VaultAdmin"})
    body = get_body()
    if body.get("rental_id") is not None:
        fk_or_404("rentals", body["rental_id"])
    require_present(body, "rental_id", "period_start", "period_end")
    rental = DB["rentals"][body["rental_id"]]
    base = logic.base_rent_for_period(rental, body["period_start"], body["period_end"])
    inv = make_record({
        "rental_id": rental["id"],
        "period_start": body["period_start"], "period_end": body["period_end"],
        "base_rent_cents": 0, "insurance_rider_cents": 0,
        "precious_metal_surcharge_cents": 0, "late_fee_cents": 0,
        "total_cents": 0, "amount_paid_cents": 0,
        "due_date": None, "issued_on": clock_now_iso(), "status": "OPEN",
    })
    inv["due_date"] = iso(parse_iso(inv["issued_on"]) + timedelta(days=logic.INVOICE_DUE_DAYS))
    logic.compute_invoice_charges(rental, inv, base)
    DB["invoices"][inv["id"]] = inv
    logic.recompute_balance(rental)
    touch(rental)
    return ok(public(inv), 201)


@app.post("/vault/invoices/<rid>/void")
def void_invoice(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    inv = get_or_404("invoices", rid)
    if inv["status"] != "OPEN":
        raise err_state("Invoice is not OPEN")
    if inv["amount_paid_cents"] > 0:
        raise ApiError("ERR_INVOICE_HAS_PAYMENTS", 409, "Invoice has applied payments")
    inv["status"] = "VOID"
    touch(inv)
    rental = DB["rentals"].get(inv["rental_id"])
    if rental:
        logic.recompute_balance(rental)
        touch(rental)
    return ok(public(inv))


@app.post("/vault/invoices/<rid>/write-off")
def write_off_invoice(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    inv = get_or_404("invoices", rid)
    if inv["status"] != "OPEN":
        raise err_state("Invoice is not OPEN")
    inv["status"] = "WRITTEN_OFF"
    touch(inv)
    rental = DB["rentals"].get(inv["rental_id"])
    if rental:
        logic.recompute_balance(rental)
        touch(rental)
    return ok(public(inv))


# ===========================================================================
# Payments
# ===========================================================================
@app.post("/vault/payments")
def create_payment():
    uid, role = authenticate()
    require_role(role, {"BillingClerk", "Renter"})
    body = get_body()
    if body.get("rental_id") is not None:
        rental = fk_or_404("rentals", body["rental_id"])
    else:
        rental = None
    if body.get("invoice_id") is not None:
        fk_or_404("invoices", body["invoice_id"])
    require_present(body, "rental_id", "amount_cents", "method")
    rental = DB["rentals"][body["rental_id"]]
    check_renter_ownership(role, uid, rental)
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise err_invalid_request("amount_cents must be an integer > 0")
    require_enum(body["method"], {"AUTOPAY", "CARD", "CASH", "CHECK", "WIRE"}, "method")
    rec = create_and_store("payments", {
        "rental_id": rental["id"], "invoice_id": body.get("invoice_id"),
        "amount_cents": amount, "method": body["method"],
        "applied_cents": 0, "cleared_on": None, "status": "INITIATED",
        "_allocations": [],
    })
    return ok(public(rec), 201)


@app.post("/vault/payments/<rid>/clear")
def clear_payment(rid):
    _uid, role = authenticate()
    require_role(role, {"BillingClerk", "VaultAdmin"})
    payment = get_or_404("payments", rid)
    if payment["status"] != "INITIATED":
        raise err_state("Payment is not INITIATED")
    rental = DB["rentals"].get(payment["rental_id"])
    _allocate_payment(payment, rental)
    payment["cleared_on"] = clock_now_iso()
    payment["status"] = "CLEARED"
    touch(payment)
    if rental:
        logic.recompute_balance(rental)
        before = rental["status"]
        logic.cure_if_zero(rental)
        if rental["status"] == before:
            touch(rental)
    return ok(public(payment))


def _allocate_payment(payment, rental):
    amount = payment["amount_cents"]
    remaining = amount
    applied = 0
    allocations = []
    if payment.get("invoice_id"):
        inv = DB["invoices"].get(payment["invoice_id"])
        targets = [inv] if inv else []
    else:
        targets = sorted(
            [i for i in logic.rental_invoices(rental) if i["status"] == "OPEN"],
            key=lambda x: x["_seq"],
        ) if rental else []
    targeted = bool(payment.get("invoice_id"))
    for inv in targets:
        if remaining <= 0:
            break
        if inv["status"] != "OPEN":
            continue
        need = inv["total_cents"] - inv["amount_paid_cents"]
        take = remaining if targeted else (min(remaining, need) if need > 0 else 0)
        if take <= 0:
            continue
        inv["amount_paid_cents"] += take
        remaining -= take
        applied += take
        if inv["amount_paid_cents"] >= inv["total_cents"]:
            inv["status"] = "PAID"
        allocations.append({"invoice_id": inv["id"], "amount": take})
        touch(inv)
    payment["applied_cents"] = applied
    payment["_allocations"] = allocations


@app.post("/vault/payments/<rid>/fail")
def fail_payment(rid):
    _uid, role = authenticate()
    require_role(role, {"BillingClerk", "VaultAdmin"})
    payment = get_or_404("payments", rid)
    if payment["status"] != "INITIATED":
        raise err_state("Payment is not INITIATED")
    payment["status"] = "FAILED"
    touch(payment)
    return ok(public(payment))


@app.post("/vault/payments/<rid>/reverse")
def reverse_payment(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    payment = get_or_404("payments", rid)
    if payment["status"] != "CLEARED":
        raise err_state("Payment is not CLEARED")
    for alloc in payment.get("_allocations", []):
        inv = DB["invoices"].get(alloc["invoice_id"])
        if not inv:
            continue
        inv["amount_paid_cents"] -= alloc["amount"]
        if inv["amount_paid_cents"] < 0:
            inv["amount_paid_cents"] = 0
        if inv["status"] == "PAID" and inv["amount_paid_cents"] < inv["total_cents"]:
            inv["status"] = "OPEN"
        touch(inv)
    payment["applied_cents"] = 0
    payment["_allocations"] = []
    payment["status"] = "REVERSED"
    touch(payment)
    rental = DB["rentals"].get(payment["rental_id"])
    if rental:
        logic.recompute_balance(rental)
        touch(rental)
    return ok(public(payment))


# ===========================================================================
# Access grants
# ===========================================================================
@app.post("/vault/access-grants")
def create_access_grant():
    uid, role = authenticate()
    require_role(role, {"Renter", "VaultAdmin"})
    body = get_body()
    if body.get("rental_id") is not None:
        rental = fk_or_404("rentals", body["rental_id"])
    else:
        rental = None
    if body.get("grantee_renter_id") is not None:
        fk_or_404("renters", body["grantee_renter_id"])
    require_present(body, "rental_id", "grant_type", "grantee_name")
    rental = DB["rentals"][body["rental_id"]]
    check_renter_ownership(role, uid, rental)
    require_enum(body["grant_type"], {"CO_RENTER", "DEPUTY", "BENEFICIARY"}, "grant_type")
    dcr = body.get("dual_control_required", True)
    rec = create_and_store("access_grants", {
        "rental_id": rental["id"],
        "grantee_renter_id": body.get("grantee_renter_id"),
        "grant_type": body["grant_type"],
        "grantee_name": body["grantee_name"],
        "grantee_gov_id_ref": body.get("grantee_gov_id_ref"),
        "dual_control_required": bool(dcr) if dcr is not None else True,
        "requires_death_certificate": body["grant_type"] == "BENEFICIARY",
        "death_certificate_ref": None,
        "status": "PENDING",
    })
    return ok(public(rec), 201)


@app.post("/vault/access-grants/<rid>/activate")
def activate_grant(rid):
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer", "VaultAdmin"})
    grant = get_or_404("access_grants", rid)
    body = get_body()
    if grant["status"] != "PENDING":
        raise err_state("Grant is not PENDING")
    rental = DB["rentals"].get(grant["rental_id"])
    if not rental or rental["status"] not in ("ACTIVE", "PAST_DUE", "DELINQUENT"):
        raise err_state("Rental is not in an activatable state")
    if grant["grant_type"] == "BENEFICIARY":
        cert = body.get("death_certificate_ref")
        if not cert:
            raise ApiError("ERR_DEATH_CERTIFICATE_REQUIRED", 409, "Death certificate required")
        grant["death_certificate_ref"] = cert
        renter = DB["renters"].get(rental["renter_id"])
        if renter:
            renter["is_deceased"] = True
            touch(renter)
    grant["status"] = "ACTIVE"
    touch(grant)
    return ok(public(grant))


@app.post("/vault/access-grants/<rid>/suspend")
def suspend_grant(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin", "ComplianceOfficer"})
    grant = get_or_404("access_grants", rid)
    if grant["status"] != "ACTIVE":
        raise err_state("Grant is not ACTIVE")
    grant["status"] = "SUSPENDED"
    touch(grant)
    return ok(public(grant))


@app.post("/vault/access-grants/<rid>/resume")
def resume_grant(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin", "ComplianceOfficer"})
    grant = get_or_404("access_grants", rid)
    if grant["status"] != "SUSPENDED":
        raise err_state("Grant is not SUSPENDED")
    grant["status"] = "ACTIVE"
    touch(grant)
    return ok(public(grant))


@app.post("/vault/access-grants/<rid>/revoke")
def revoke_grant(rid):
    uid, role = authenticate()
    require_role(role, {"Renter", "VaultAdmin"})
    grant = get_or_404("access_grants", rid)
    rental = DB["rentals"].get(grant["rental_id"])
    if rental:
        check_renter_ownership(role, uid, rental)
    if grant["status"] not in ("ACTIVE", "SUSPENDED", "PENDING"):
        raise err_state("Grant cannot be revoked")
    grant["status"] = "REVOKED"
    touch(grant)
    return ok(public(grant))


# ===========================================================================
# Access appointments
# ===========================================================================
@app.post("/vault/access-appointments")
def create_appointment():
    uid, role = authenticate()
    require_role(role, {"Renter", "VaultOfficer"})
    body = get_body()
    if body.get("box_id") is not None:
        box = fk_or_404("boxes", body["box_id"])
    else:
        box = None
    if body.get("rental_id") is not None:
        rental = fk_or_404("rentals", body["rental_id"])
    else:
        rental = None
    grant = None
    if body.get("grant_id") is not None:
        grant = fk_or_404("access_grants", body["grant_id"])
    require_present(body, "box_id", "rental_id", "scheduled_start", "scheduled_end")
    box = DB["boxes"][body["box_id"]]
    rental = DB["rentals"][body["rental_id"]]
    check_renter_ownership(role, uid, rental)
    start_dt = parse_iso(body["scheduled_start"])
    end_dt = parse_iso(body["scheduled_end"])
    if start_dt is None or end_dt is None:
        raise err_invalid_request("Invalid schedule window")
    branch = DB["branches"].get(box["branch_id"])
    # 6. state: branch must be OPEN
    if branch and branch["status"] != "OPEN":
        raise err_state("Branch is CLOSED")
    # 7. temporal sanity
    if not (end_dt > start_dt and start_dt >= clock_now()):
        raise ApiError("ERR_APPOINTMENT_IN_PAST", 409, "Appointment window not in the future")
    # 8. overlap then capacity
    if logic.check_box_overlap(box["id"], start_dt, end_dt):
        raise ApiError("ERR_APPOINTMENT_OVERLAP", 409, "Appointment overlaps another on this box")
    count = logic.room_occupancy_count(box["branch_id"], start_dt, end_dt)
    cap = branch["viewing_room_capacity"] if branch else 0
    if count + 1 > cap:
        raise ApiError("ERR_ROOM_CAPACITY_EXCEEDED", 409, "Viewing room capacity exceeded")
    # 9. referential: grant belongs to same rental
    if grant is not None and grant["rental_id"] != rental["id"]:
        raise ApiError("ERR_GRANT_RENTAL_MISMATCH", 409, "Grant does not belong to this rental")
    rec = create_and_store("access_appointments", {
        "box_id": box["id"], "rental_id": rental["id"],
        "branch_id": box["branch_id"], "grant_id": body.get("grant_id"),
        "scheduled_start": body["scheduled_start"], "scheduled_end": body["scheduled_end"],
        "status": "BOOKED",
    })
    return ok(public(rec), 201)


@app.post("/vault/access-appointments/<rid>/check-in")
def check_in_appointment(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultOfficer"})
    appt = get_or_404("access_appointments", rid)
    rental = DB["rentals"].get(appt["rental_id"])
    # 5. compliance safety-first
    if rental and logic.has_open_hold(rental["renter_id"]):
        raise ApiError("ERR_COMPLIANCE_HOLD", 409, "Renter has an open compliance hold")
    # 6. state
    if appt["status"] != "BOOKED":
        raise err_state("Appointment is not BOOKED")
    if not rental or rental["status"] not in ("ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_RENTAL_NOT_ACCESSIBLE", 409, "Rental is not accessible")
    appt["status"] = "CHECKED_IN"
    touch(appt)
    return ok(public(appt))


@app.post("/vault/access-appointments/<rid>/complete")
def complete_appointment(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultOfficer"})
    appt = get_or_404("access_appointments", rid)
    if appt["status"] != "CHECKED_IN":
        raise err_state("Appointment is not CHECKED_IN")
    appt["status"] = "COMPLETED"
    touch(appt)
    return ok(public(appt))


@app.post("/vault/access-appointments/<rid>/cancel")
def cancel_appointment(rid):
    uid, role = authenticate()
    require_role(role, {"Renter", "VaultOfficer"})
    appt = get_or_404("access_appointments", rid)
    rental = DB["rentals"].get(appt["rental_id"])
    if rental:
        check_renter_ownership(role, uid, rental)
    if appt["status"] != "BOOKED":
        raise err_state("Appointment is not BOOKED")
    appt["status"] = "CANCELLED"
    touch(appt)
    return ok(public(appt))


@app.post("/vault/access-appointments/<rid>/no-show")
def no_show_appointment(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultOfficer"})
    appt = get_or_404("access_appointments", rid)
    if appt["status"] != "BOOKED":
        raise err_state("Appointment is not BOOKED")
    end_dt = parse_iso(appt["scheduled_end"])
    if clock_now() < end_dt:
        raise err_state("Appointment window has not yet ended")
    appt["status"] = "NO_SHOW"
    touch(appt)
    return ok(public(appt))


# ===========================================================================
# Access events (append-only)
# ===========================================================================
@app.post("/vault/access-events")
def create_access_event():
    _uid, role = authenticate()
    require_role(role, {"VaultOfficer"})
    body = get_body()
    if body.get("appointment_id") is not None:
        fk_or_404("access_appointments", body["appointment_id"])
    if body.get("box_id") is not None:
        fk_or_404("boxes", body["box_id"])
    if body.get("rental_id") is not None:
        fk_or_404("rentals", body["rental_id"])
    require_present(body, "appointment_id", "box_id", "rental_id", "event_type",
                    "primary_accessor_ref", "dual_control_officer_ref", "witness_count")
    require_enum(body["event_type"], {"ENTRY", "EXIT"}, "event_type")
    wc = body.get("witness_count")
    if not isinstance(wc, int) or isinstance(wc, bool) or wc < 1:
        raise err_invalid_request("witness_count must be an integer >= 1")
    # dual control (business safety)
    if body["dual_control_officer_ref"] == body["primary_accessor_ref"] or wc < logic.REQUIRED_WITNESSES:
        raise ApiError("ERR_DUAL_CONTROL_REQUIRED", 409, "Dual control requirement not met")
    rec = make_record({
        "appointment_id": body["appointment_id"], "box_id": body["box_id"],
        "rental_id": body["rental_id"], "event_type": body["event_type"],
        "occurred_at": clock_now_iso(),
        "primary_accessor_ref": body["primary_accessor_ref"],
        "dual_control_officer_ref": body["dual_control_officer_ref"],
        "witness_count": wc,
    }, common=False)
    DB["access_events"][rec["id"]] = rec
    return ok(public(rec), 201)


# ===========================================================================
# Inventory items
# ===========================================================================
@app.post("/vault/inventory-items")
def create_inventory_item():
    uid, role = authenticate()
    require_role(role, {"Renter", "VaultOfficer"})
    body = get_body()
    if body.get("rental_id") is not None:
        rental = fk_or_404("rentals", body["rental_id"])
    else:
        rental = None
    require_present(body, "rental_id", "description", "category", "declared_value_cents")
    rental = DB["rentals"][body["rental_id"]]
    check_renter_ownership(role, uid, rental)
    require_enum(body["category"], {"PRECIOUS_METAL", "JEWELRY", "DOCUMENT", "OTHER"}, "category")
    dv = body.get("declared_value_cents")
    if not isinstance(dv, int) or isinstance(dv, bool) or dv <= 0:
        raise err_invalid_request("declared_value_cents must be an integer > 0")
    metal_type = body.get("metal_type")
    weight = body.get("weight_grams")
    purity = body.get("purity")
    if body["category"] == "PRECIOUS_METAL":
        if metal_type is None or weight is None or purity is None:
            raise err_invalid_request("PRECIOUS_METAL requires metal_type, weight_grams, purity")
        require_enum(metal_type, {"GOLD", "SILVER", "PLATINUM"}, "metal_type")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            raise err_invalid_request("weight_grams must be a positive number")
        if not isinstance(purity, (int, float)) or isinstance(purity, bool) or not (0 < purity <= 1):
            raise err_invalid_request("purity must be in (0, 1]")
    else:
        metal_type = None
        weight = None
        purity = None
    rec = create_and_store("inventory_items", {
        "rental_id": rental["id"], "description": body["description"],
        "category": body["category"], "metal_type": metal_type,
        "weight_grams": weight, "purity": purity,
        "declared_value_cents": dv, "appraised_value_cents": None,
        "status": "DECLARED",
    })
    return ok(public(rec), 201)


@app.post("/vault/inventory-items/<rid>/appraise")
def appraise_item(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultOfficer", "ComplianceOfficer"})
    item = get_or_404("inventory_items", rid)
    body = get_body()
    if item["status"] != "DECLARED":
        raise err_state("Item is not DECLARED")
    if body.get("appraised_value_cents") is not None:
        item["appraised_value_cents"] = body["appraised_value_cents"]
    elif body.get("spot_price_per_gram_cents") is not None and item["weight_grams"] is not None \
            and item["purity"] is not None:
        item["appraised_value_cents"] = store.rhu(
            store.D(item["weight_grams"]) * store.D(item["purity"]) * store.D(body["spot_price_per_gram_cents"])
        )
    item["status"] = "APPRAISED"
    touch(item)
    return ok(public(item))


@app.post("/vault/inventory-items/<rid>/insure")
def insure_item(rid):
    _uid, role = authenticate()
    require_role(role, {"BillingClerk", "VaultAdmin"})
    item = get_or_404("inventory_items", rid)
    if item["status"] != "APPRAISED":
        raise err_state("Item is not APPRAISED")
    item["status"] = "INSURED"
    touch(item)
    return ok(public(item))


# ===========================================================================
# Drilling orders
# ===========================================================================
@app.post("/vault/drilling-orders")
def create_drilling_order():
    uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    body = get_body()
    if body.get("box_id") is not None:
        fk_or_404("boxes", body["box_id"])
    if body.get("rental_id") is not None:
        fk_or_404("rentals", body["rental_id"])
    require_present(body, "box_id", "rental_id", "reason")
    require_enum(body["reason"], {"ABANDONMENT", "DELINQUENCY", "LOST_KEY", "COURT_ORDER"}, "reason")
    fee = body.get("drilling_fee_cents", 15000)
    if fee is None:
        fee = 15000
    if not isinstance(fee, int) or isinstance(fee, bool) or fee < 0:
        raise err_invalid_request("drilling_fee_cents must be a non-negative integer")
    rental = DB["rentals"][body["rental_id"]]
    if body["reason"] in ("ABANDONMENT", "DELINQUENCY") and rental["status"] != "DELINQUENT":
        raise ApiError("ERR_DRILL_NOT_ELIGIBLE", 409, "Box/rental not eligible for drilling")
    rec = create_and_store("drilling_orders", {
        "box_id": body["box_id"], "rental_id": body["rental_id"],
        "reason": body["reason"], "requested_by_ref": uid,
        "approved_by_ref": None, "scheduled_at": None, "drilled_at": None,
        "drilling_fee_cents": fee, "proceeds_cents": 0,
        "proceeds_to_arrears_cents": None, "proceeds_to_drilling_cents": None,
        "proceeds_to_admin_cents": None, "proceeds_to_escrow_cents": None,
        "status": "REQUESTED",
    })
    return ok(public(rec), 201)


@app.post("/vault/drilling-orders/<rid>/approve")
def approve_drilling_order(rid):
    uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    order = get_or_404("drilling_orders", rid)
    if uid == order["requested_by_ref"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Approver must differ from requester")
    if order["status"] != "REQUESTED":
        raise err_state("Order is not REQUESTED")
    order["status"] = "APPROVED"
    order["approved_by_ref"] = uid
    touch(order)
    return ok(public(order))


@app.post("/vault/drilling-orders/<rid>/schedule")
def schedule_drilling_order(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    order = get_or_404("drilling_orders", rid)
    body = get_body()
    require_present(body, "scheduled_at")
    if order["status"] != "APPROVED":
        raise err_state("Order is not APPROVED")
    order["status"] = "SCHEDULED"
    order["scheduled_at"] = body["scheduled_at"]
    box = DB["boxes"].get(order["box_id"])
    if box and box["status"] == "DELINQUENT":
        box["status"] = "DRILL_PENDING"
        touch(box)
    touch(order)
    return ok(public(order))


@app.post("/vault/drilling-orders/<rid>/complete")
def complete_drilling_order(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin"})
    order = get_or_404("drilling_orders", rid)
    body = get_body()
    if order["status"] != "SCHEDULED":
        raise err_state("Order is not SCHEDULED")
    proceeds = body.get("proceeds_cents", 0)
    if proceeds is None:
        proceeds = 0
    if not isinstance(proceeds, int) or isinstance(proceeds, bool) or proceeds < 0:
        raise err_invalid_request("proceeds_cents must be a non-negative integer")
    order["proceeds_cents"] = proceeds
    rental = DB["rentals"].get(order["rental_id"])
    if rental:
        logic.recompute_balance(rental)
    order["status"] = "DRILLED"
    order["drilled_at"] = clock_now_iso()
    logic.compute_waterfall(order, rental if rental else {"balance_due_cents": 0})
    touch(order)
    box = DB["boxes"].get(order["box_id"])
    if box and box["status"] == "DRILL_PENDING":
        box["status"] = "DRILLED"
        touch(box)
    if rental and rental["status"] == "DELINQUENT":
        rental["status"] = "ABANDONED"
        touch(rental)
        for grant in DB["access_grants"].values():
            if grant["rental_id"] == rental["id"] and grant["status"] in ("ACTIVE", "SUSPENDED"):
                grant["status"] = "REVOKED"
                touch(grant)
    return ok(public(order))


@app.post("/vault/drilling-orders/<rid>/cancel")
def cancel_drilling_order(rid):
    _uid, role = authenticate()
    require_role(role, {"VaultAdmin", "ComplianceOfficer"})
    order = get_or_404("drilling_orders", rid)
    if order["status"] not in ("REQUESTED", "APPROVED", "SCHEDULED"):
        raise err_state("Order cannot be cancelled")
    was_scheduled = order["status"] == "SCHEDULED"
    order["status"] = "CANCELLED"
    touch(order)
    if was_scheduled:
        box = DB["boxes"].get(order["box_id"])
        if box and box["status"] == "DRILL_PENDING":
            box["status"] = "DELINQUENT"
            touch(box)
    return ok(public(order))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
