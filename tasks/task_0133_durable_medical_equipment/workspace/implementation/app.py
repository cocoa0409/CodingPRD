"""Durable Medical Equipment (DME) REST API.

Entry point: registers all routes, error handlers, and runs the Flask server
in the foreground bound to 0.0.0.0:$PORT. Storage is in-memory only (db.py);
state is wiped on every fresh process boot.
"""
import os

from flask import Flask

import clock
import db
import serialize
from calc import (
    AUTH_VALIDITY_DAYS,
    RENTAL_CAP_MONTHS,
    RESUPPLY_WINDOW_DAYS,
    modifier_adjusted_monthly,
    purchase_allowed_amount,
)
from common import (
    add_days,
    add_months,
    get_body,
    paginate,
    parse_iso8601,
    parse_iso_date,
    parse_pagination,
    require_auth,
    require_role,
    to_iso8601,
    whole_days_between,
)
from errors import ApiError, err
from ledger import (
    order_cycles,
    recompute_rental_progress,
    recompute_total_allowed,
)
from response import array_response, error_response, object_response

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % e)


# ---------------------------------------------------------------------------
# Lookup helpers (existence -> ERR_NOT_FOUND 404)
# ---------------------------------------------------------------------------
def find_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Body-field validation helpers (ERR_INVALID_REQUEST 400)
# ---------------------------------------------------------------------------
def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s is required and must be a non-empty string" % field)
    return v


def require_int(body, field, lo=None, hi=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s is required and must be an integer" % field)
    if lo is not None and v < lo:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, lo))
    if hi is not None and v > hi:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (field, hi))
    return v


def require_enum(body, field, choices):
    v = body.get(field)
    if not isinstance(v, str) or v not in choices:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(choices)))
    return v


def optional_enum(body, field, choices, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str) or v not in choices:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(choices)))
    return v


def optional_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return v


def require_iso8601(body, field):
    raw = body.get(field)
    dt = parse_iso8601(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 datetime" % field)
    return dt


def require_iso_date(body, field):
    raw = body.get(field)
    d = parse_iso_date(raw)
    if d is None:
        raise err("ERR_INVALID_REQUEST", "Field %s must be a YYYY-MM-DD date" % field)
    return d


# ---------------------------------------------------------------------------
# Generic list helper
# ---------------------------------------------------------------------------
def list_response(collection, serializer, filters):
    limit, offset = parse_pagination()
    records = []
    for rec in collection.values():
        keep = True
        for key, val in filters.items():
            if val is not None and rec.get(key) != val:
                keep = False
                break
        if keep:
            records.append(rec)
    page, total, has_more = paginate(records, limit, offset)
    return array_response([serializer(r) for r in page], limit, offset, total, has_more)


# ===========================================================================
# Clock (PlatformAdmin) — PRD 2.5
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    dt = require_iso8601(body, "to_iso8601")
    clock.set_now(dt)
    return object_response({"now_utc": to_iso8601(dt)})


# ===========================================================================
# Patient — PRD 3.1
# ===========================================================================
@app.route("/patients", methods=["POST"])
def create_patient():
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    full_name = require_str(body, "full_name")
    medicare_id = require_str(body, "medicare_id")
    require_iso_date(body, "date_of_birth")
    date_of_birth = body["date_of_birth"]
    address_state = require_str(body, "address_state")
    # Uniqueness (priority 16) after well-formedness.
    for p in db.patients.values():
        if p["medicare_id"] == medicare_id:
            raise err("ERR_DUPLICATE_VALUE", "medicare_id already exists")
    rec = {
        "full_name": full_name,
        "medicare_id": medicare_id,
        "date_of_birth": date_of_birth,
        "address_state": address_state,
    }
    db.init_common(rec)
    db.patients[rec["id"]] = rec
    return object_response(serialize.patient(rec), 201)


@app.route("/patients/<rid>", methods=["GET"])
def get_patient(rid):
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "SupplierUser"})
    rec = find_or_404(db.patients, rid)
    return object_response(serialize.patient(rec))


# ===========================================================================
# Supplier — PRD 3.1
# ===========================================================================
@app.route("/suppliers", methods=["POST"])
def create_supplier():
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    name = require_str(body, "name")
    ptan = require_str(body, "ptan")
    accreditation_active = optional_bool(body, "accreditation_active", True)
    for s in db.suppliers.values():
        if s["ptan"] == ptan:
            raise err("ERR_DUPLICATE_VALUE", "ptan already exists")
    rec = {"name": name, "ptan": ptan, "accreditation_active": accreditation_active}
    db.init_common(rec)
    db.suppliers[rec["id"]] = rec
    return object_response(serialize.supplier(rec), 201)


@app.route("/suppliers/<rid>", methods=["GET"])
def get_supplier(rid):
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "SupplierUser"})
    rec = find_or_404(db.suppliers, rid)
    return object_response(serialize.supplier(rec))


@app.route("/suppliers/<rid>", methods=["PATCH"])
def patch_supplier(rid):
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    rec = find_or_404(db.suppliers, rid)
    body = get_body()
    changed = False
    if "accreditation_active" in body and body.get("accreditation_active") is not None:
        v = body.get("accreditation_active")
        if not isinstance(v, bool):
            raise err("ERR_INVALID_REQUEST", "accreditation_active must be a boolean")
        if rec["accreditation_active"] != v:
            rec["accreditation_active"] = v
            changed = True
    if changed:
        db.touch(rec)
    return object_response(serialize.supplier(rec))


# ===========================================================================
# HCPCSItem — PRD 3.1
# ===========================================================================
BILLING_CATEGORIES = {"CAPPED_RENTAL", "INEXPENSIVE_ROUTINE", "PURCHASE_ONLY", "OXYGEN"}


@app.route("/hcpcs-items", methods=["POST"])
def create_hcpcs_item():
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    hcpcs_code = require_str(body, "hcpcs_code")
    description = require_str(body, "description")
    billing_category = require_enum(body, "billing_category", BILLING_CATEGORIES)
    purchase_price_cents = require_int(body, "purchase_price_cents", lo=0)
    monthly_rental_cents = require_int(body, "monthly_rental_cents", lo=0)
    requires_cmn = optional_bool(body, "requires_cmn", False)
    requires_prior_auth = optional_bool(body, "requires_prior_auth", False)
    is_cpap = optional_bool(body, "is_cpap", False)
    for h in db.hcpcs_items.values():
        if h["hcpcs_code"] == hcpcs_code:
            raise err("ERR_DUPLICATE_VALUE", "hcpcs_code already exists")
    rec = {
        "hcpcs_code": hcpcs_code,
        "description": description,
        "billing_category": billing_category,
        "purchase_price_cents": purchase_price_cents,
        "monthly_rental_cents": monthly_rental_cents,
        "requires_cmn": requires_cmn,
        "requires_prior_auth": requires_prior_auth,
        "is_cpap": is_cpap,
    }
    db.init_common(rec)
    db.hcpcs_items[rec["id"]] = rec
    return object_response(serialize.hcpcs_item(rec), 201)


@app.route("/hcpcs-items/<rid>", methods=["GET"])
def get_hcpcs_item(rid):
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "SupplierUser"})
    rec = find_or_404(db.hcpcs_items, rid)
    return object_response(serialize.hcpcs_item(rec))


# ===========================================================================
# DMEOrder — PRD 3.2, 3.6, 3.7, 3.8
# ===========================================================================
ACQUISITION_TYPES = {"RENTAL", "PURCHASE"}
MODIFIERS = {"NONE", "NU", "KX"}


@app.route("/dme-orders", methods=["POST"])
def create_dme_order():
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    body = get_body()

    # Existence (404) of provided FK targets first, left-to-right:
    # patient, supplier, item. A missing field surfaces as ERR_INVALID_REQUEST
    # in the well-formedness pass below.
    if isinstance(body.get("patient_id"), str):
        find_or_404(db.patients, body["patient_id"])
    if isinstance(body.get("supplier_id"), str):
        find_or_404(db.suppliers, body["supplier_id"])
    if isinstance(body.get("hcpcs_item_id"), str):
        find_or_404(db.hcpcs_items, body["hcpcs_item_id"])

    # Business constraint: acquisition_type matches billing_category (priority 11).
    # Requires the item to exist; evaluated before generic well-formedness for the
    # acquisition_type-vs-category relation.
    patient_id = require_str(body, "patient_id")
    supplier_id = require_str(body, "supplier_id")
    hcpcs_item_id = require_str(body, "hcpcs_item_id")
    acquisition_type = require_enum(body, "acquisition_type", ACQUISITION_TYPES)
    modifier = optional_enum(body, "modifier", MODIFIERS, "NONE")
    ordered_at = require_iso8601(body, "ordered_at_utc")

    item = db.hcpcs_items[hcpcs_item_id]
    cat = item["billing_category"]
    if cat in ("CAPPED_RENTAL", "OXYGEN", "INEXPENSIVE_ROUTINE"):
        if acquisition_type != "RENTAL":
            raise err("ERR_ACQUISITION_TYPE_MISMATCH", "%s items must be RENTAL" % cat)
    elif cat == "PURCHASE_ONLY":
        if acquisition_type != "PURCHASE":
            raise err("ERR_ACQUISITION_TYPE_MISMATCH", "PURCHASE_ONLY items must be PURCHASE")

    rec = {
        "patient_id": patient_id,
        "supplier_id": supplier_id,
        "hcpcs_item_id": hcpcs_item_id,
        "acquisition_type": acquisition_type,
        "modifier": modifier,
        "ordered_at_utc": to_iso8601(ordered_at),
        "rental_months_billed": 0,
        "cap_reached": False,
        "total_allowed_cents": 0,
        "status": "DRAFT",
    }
    db.init_common(rec)
    db.dme_orders[rec["id"]] = rec
    return object_response(serialize.dme_order(rec), 201)


@app.route("/dme-orders/<rid>", methods=["GET"])
def get_dme_order(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer", "PlatformAdmin"})
    rec = find_or_404(db.dme_orders, rid)
    return object_response(serialize.dme_order(rec))


@app.route("/dme-orders", methods=["GET"])
def list_dme_orders():
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer", "PlatformAdmin"})
    from flask import request
    filters = {
        "patient_id": request.args.get("patient_id"),
        "supplier_id": request.args.get("supplier_id"),
        "hcpcs_item_id": request.args.get("hcpcs_item_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.dme_orders, serialize.dme_order, filters)


@app.route("/dme-orders/<rid>/rental-quote", methods=["GET"])
def rental_quote(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    order = find_or_404(db.dme_orders, rid)
    item = db.hcpcs_items[order["hcpcs_item_id"]]
    monthly = modifier_adjusted_monthly(item, order)
    provisional = RENTAL_CAP_MONTHS * monthly
    return object_response(
        {
            "provisional_total_cents": provisional,
            "monthly_allowed_cents": monthly,
            "cap_months": RENTAL_CAP_MONTHS,
        }
    )


@app.route("/dme-orders/<rid>/mark-ready", methods=["POST"])
def mark_ready(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    order = find_or_404(db.dme_orders, rid)
    # State (409): must be DRAFT.
    if order["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Order must be DRAFT to mark ready")
    item = db.hcpcs_items[order["hcpcs_item_id"]]
    supplier = db.suppliers[order["supplier_id"]]

    # Business gates in catalog order: CMN, then prior auth, then accreditation.
    if item["requires_cmn"]:
        has_active = any(
            c["order_id"] == order["id"] and c["status"] == "ACTIVE"
            for c in db.cmns.values()
        )
        if not has_active:
            raise err("ERR_CMN_REQUIRED", "An ACTIVE CMN is required to mark ready")

    if item["requires_prior_auth"]:
        now = clock.now()
        ok = False
        for pa in db.prior_authorizations.values():
            if pa["order_id"] != order["id"]:
                continue
            if pa["status"] != "APPROVED":
                continue
            exp = parse_iso8601(pa["expires_at_utc"]) if pa["expires_at_utc"] else None
            # Approved authorization valid only while expires_at_utc strictly after now.
            if exp is not None and exp > now:
                ok = True
                break
        if not ok:
            raise err("ERR_PRIOR_AUTH_REQUIRED", "An APPROVED, unexpired prior authorization is required")

    if not supplier["accreditation_active"]:
        raise err("ERR_SUPPLIER_NOT_ACCREDITED", "Fulfilling supplier is not accredited")

    order["status"] = "READY_FOR_DELIVERY"
    db.touch(order)
    return object_response(serialize.dme_order(order))


@app.route("/dme-orders/<rid>/activate-billing", methods=["POST"])
def activate_billing(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    order = find_or_404(db.dme_orders, rid)
    if order["status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "Order must be DELIVERED to activate billing")
    # Require at least one CONFIRMED delivery with pod_received == true.
    has_pod = any(
        d["order_id"] == order["id"] and d["status"] == "CONFIRMED" and d["pod_received"]
        for d in db.deliveries.values()
    )
    if not has_pod:
        raise err("ERR_NO_PROOF_OF_DELIVERY", "A CONFIRMED delivery with proof of delivery is required")

    order["status"] = "ACTIVE"
    item = db.hcpcs_items[order["hcpcs_item_id"]]
    if order["acquisition_type"] == "PURCHASE":
        amount = purchase_allowed_amount(item, order)
        cl = {
            "order_id": order["id"],
            "rental_cycle_id": None,
            "audit_id": None,
            "line_type": "PURCHASE",
            "allowed_amount_cents": amount,
            "status": "POSTED",
        }
        db.init_common(cl)
        db.claim_lines[cl["id"]] = cl
        recompute_total_allowed(order)
    db.touch(order)
    return object_response(serialize.dme_order(order))


@app.route("/dme-orders/<rid>/rental-cycles", methods=["POST"])
def post_rental_cycle(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    order = find_or_404(db.dme_orders, rid)
    item = db.hcpcs_items[order["hcpcs_item_id"]]

    # Cap check FIRST (priority 8 before generic state check, PRD 3.7).
    if order["cap_reached"]:
        raise err("ERR_RENTAL_CAP_REACHED", "Rental cap reached; equipment is beneficiary-owned")
    # Generic state (409): order must be ACTIVE.
    if order["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Order must be ACTIVE to post a rental cycle")

    body = get_body()
    existing = order_cycles(order["id"])
    max_index = max((c["cycle_index"] for c in existing), default=0)
    cycle_index = max_index + 1

    if "period_start_utc" in body and body.get("period_start_utc") is not None:
        period_start = require_iso8601(body, "period_start_utc")
    else:
        anchor = parse_iso8601(order["ordered_at_utc"])
        period_start = add_months(anchor, cycle_index - 1)
    period_end = add_months(period_start, 1)

    # Overlap check (priority 9): half-open [start, end); shared boundary allowed.
    for c in existing:
        cs = parse_iso8601(c["period_start_utc"])
        ce = parse_iso8601(c["period_end_utc"])
        if period_start < ce and cs < period_end:
            raise err("ERR_CYCLE_OVERLAP", "New cycle period overlaps an existing cycle")

    amount = modifier_adjusted_monthly(item, order)

    cycle = {
        "order_id": order["id"],
        "cycle_index": cycle_index,
        "period_start_utc": to_iso8601(period_start),
        "period_end_utc": to_iso8601(period_end),
        "billed_amount_cents": amount,
        "status": "BILLED",
    }
    db.init_common(cycle)
    db.rental_cycles[cycle["id"]] = cycle

    cl = {
        "order_id": order["id"],
        "rental_cycle_id": cycle["id"],
        "audit_id": None,
        "line_type": "RENTAL_MONTH",
        "allowed_amount_cents": amount,
        "status": "POSTED",
    }
    db.init_common(cl)
    db.claim_lines[cl["id"]] = cl

    recompute_rental_progress(order, item)
    recompute_total_allowed(order)

    # Cap-conversion cascade (PRD 3.7): cap reached on CAPPED_RENTAL -> CONVERTED_TO_PURCHASE.
    if item["billing_category"] == "CAPPED_RENTAL" and order["rental_months_billed"] >= RENTAL_CAP_MONTHS:
        order["cap_reached"] = True
        if order["status"] == "ACTIVE":
            order["status"] = "CONVERTED_TO_PURCHASE"
    db.touch(order)

    return object_response(serialize.rental_cycle(cycle), 201)


@app.route("/dme-orders/<rid>/close", methods=["POST"])
def close_order(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    order = find_or_404(db.dme_orders, rid)
    if order["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Order must be ACTIVE to close")
    order["status"] = "CLOSED"
    db.touch(order)
    return object_response(serialize.dme_order(order))


@app.route("/dme-orders/<rid>/cancel", methods=["POST"])
def cancel_order(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    order = find_or_404(db.dme_orders, rid)
    if order["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Order must be DRAFT to cancel")
    order["status"] = "CANCELLED"
    db.touch(order)
    # Cleanup cascades: revoke DRAFT/ACTIVE CMNs; cancel SCHEDULED deliveries.
    for c in db.cmns.values():
        if c["order_id"] == order["id"] and c["status"] in ("DRAFT", "ACTIVE"):
            c["status"] = "REVOKED"
            db.touch(c)
    for d in db.deliveries.values():
        if d["order_id"] == order["id"] and d["status"] == "SCHEDULED":
            d["status"] = "CANCELLED"
            db.touch(d)
    return object_response(serialize.dme_order(order))


# ===========================================================================
# CMN — PRD 3.3
# ===========================================================================
@app.route("/cmns", methods=["POST"])
def create_cmn():
    _uid, role = require_auth()
    require_role(role, {"PhysicianUser"})
    body = get_body()
    if isinstance(body.get("order_id"), str):
        find_or_404(db.dme_orders, body["order_id"])
    order_id = require_str(body, "order_id")
    physician_npi = require_str(body, "physician_npi")
    length_of_need_months = require_int(body, "length_of_need_months", lo=1, hi=99)
    require_iso_date(body, "signed_date")
    signed_date = body["signed_date"]
    rec = {
        "order_id": order_id,
        "physician_npi": physician_npi,
        "length_of_need_months": length_of_need_months,
        "signed_date": signed_date,
        "superseded_by_id": None,
        "status": "DRAFT",
    }
    db.init_common(rec)
    db.cmns[rec["id"]] = rec
    return object_response(serialize.cmn(rec), 201)


@app.route("/cmns/<rid>", methods=["GET"])
def get_cmn(rid):
    _uid, role = require_auth()
    require_role(role, {"PhysicianUser", "SupplierUser", "PayerReviewer"})
    rec = find_or_404(db.cmns, rid)
    return object_response(serialize.cmn(rec))


@app.route("/cmns", methods=["GET"])
def list_cmns():
    _uid, role = require_auth()
    require_role(role, {"PhysicianUser", "SupplierUser", "PayerReviewer"})
    from flask import request
    filters = {
        "order_id": request.args.get("order_id"),
        "superseded_by_id": request.args.get("superseded_by_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.cmns, serialize.cmn, filters)


@app.route("/cmns/<rid>/activate", methods=["POST"])
def activate_cmn(rid):
    _uid, role = require_auth()
    require_role(role, {"PhysicianUser"})
    cmn_rec = find_or_404(db.cmns, rid)
    # Order FK existence (the CMN always carries a valid order_id from create).
    order = db.dme_orders.get(cmn_rec["order_id"])
    if order is None:
        raise err("ERR_NOT_FOUND", "Order not found")

    # State (409): CMN must be DRAFT.
    if cmn_rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "CMN must be DRAFT to activate")

    body = get_body()

    # signed_date check (priority 13) BEFORE the OCC version check (priority 14).
    signed = parse_iso_date(cmn_rec["signed_date"])
    ordered_dt = parse_iso8601(order["ordered_at_utc"])
    if signed is None or ordered_dt is None or signed > ordered_dt.date():
        raise err("ERR_CMN_SIGNED_AFTER_ORDER", "CMN signed_date is after the order date")

    # OCC: expected_order_version must match order.version (priority 14).
    expected = body.get("expected_order_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_order_version is required and must be an integer")
    if expected != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION", "expected_order_version does not match the order's version")

    # Supersede cascade: prior ACTIVE CMN on this order -> SUPERSEDED.
    for c in db.cmns.values():
        if c["order_id"] == order["id"] and c["status"] == "ACTIVE" and c["id"] != cmn_rec["id"]:
            c["superseded_by_id"] = cmn_rec["id"]
            c["status"] = "SUPERSEDED"
            db.touch(c)

    cmn_rec["status"] = "ACTIVE"
    db.touch(cmn_rec)
    # Increment order version by 1.
    db.touch(order)
    return object_response(serialize.cmn(cmn_rec))


@app.route("/cmns/<rid>/revoke", methods=["POST"])
def revoke_cmn(rid):
    _uid, role = require_auth()
    require_role(role, {"PhysicianUser"})
    cmn_rec = find_or_404(db.cmns, rid)
    if cmn_rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "CMN must be ACTIVE to revoke")
    cmn_rec["status"] = "REVOKED"
    db.touch(cmn_rec)
    return object_response(serialize.cmn(cmn_rec))


# ===========================================================================
# PriorAuthorization — PRD 3.4
# ===========================================================================
@app.route("/prior-authorizations", methods=["POST"])
def create_prior_auth():
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    body = get_body()
    if isinstance(body.get("order_id"), str):
        find_or_404(db.dme_orders, body["order_id"])
    order_id = require_str(body, "order_id")
    payer_reference = require_str(body, "payer_reference")
    rec = {
        "order_id": order_id,
        "payer_reference": payer_reference,
        "decision_reason": None,
        "status": "PENDING",
        "expires_at_utc": None,
    }
    db.init_common(rec)
    db.prior_authorizations[rec["id"]] = rec
    return object_response(serialize.prior_authorization(rec), 201)


@app.route("/prior-authorizations/<rid>", methods=["GET"])
def get_prior_auth(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    rec = find_or_404(db.prior_authorizations, rid)
    return object_response(serialize.prior_authorization(rec))


@app.route("/prior-authorizations", methods=["GET"])
def list_prior_auths():
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    from flask import request
    filters = {
        "order_id": request.args.get("order_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.prior_authorizations, serialize.prior_authorization, filters)


@app.route("/prior-authorizations/<rid>/approve", methods=["POST"])
def approve_prior_auth(rid):
    _uid, role = require_auth()
    require_role(role, {"PayerReviewer"})
    rec = find_or_404(db.prior_authorizations, rid)
    if rec["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Prior authorization must be PENDING")
    body = get_body()
    reason = body.get("decision_reason")
    if reason is not None and not isinstance(reason, str):
        raise err("ERR_INVALID_REQUEST", "decision_reason must be a string")
    rec["status"] = "APPROVED"
    rec["decision_reason"] = reason
    rec["expires_at_utc"] = to_iso8601(add_days(clock.now(), AUTH_VALIDITY_DAYS))
    db.touch(rec)
    return object_response(serialize.prior_authorization(rec))


@app.route("/prior-authorizations/<rid>/deny", methods=["POST"])
def deny_prior_auth(rid):
    _uid, role = require_auth()
    require_role(role, {"PayerReviewer"})
    rec = find_or_404(db.prior_authorizations, rid)
    if rec["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Prior authorization must be PENDING")
    body = get_body()
    reason = body.get("decision_reason")
    if reason is not None and not isinstance(reason, str):
        raise err("ERR_INVALID_REQUEST", "decision_reason must be a string")
    rec["status"] = "DENIED"
    rec["decision_reason"] = reason
    db.touch(rec)
    return object_response(serialize.prior_authorization(rec))


# ===========================================================================
# Delivery — PRD 3.5
# ===========================================================================
@app.route("/deliveries", methods=["POST"])
def create_delivery():
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    body = get_body()
    if isinstance(body.get("order_id"), str):
        find_or_404(db.dme_orders, body["order_id"])
    order_id = require_str(body, "order_id")
    scheduled_for = require_iso8601(body, "scheduled_for_utc")
    pod_signature_name = body.get("pod_signature_name")
    if pod_signature_name is not None and not isinstance(pod_signature_name, str):
        raise err("ERR_INVALID_REQUEST", "pod_signature_name must be a string")
    rec = {
        "order_id": order_id,
        "scheduled_for_utc": to_iso8601(scheduled_for),
        "delivered_at_utc": None,
        "pod_signature_name": pod_signature_name,
        "pod_received": False,
        "status": "SCHEDULED",
    }
    db.init_common(rec)
    db.deliveries[rec["id"]] = rec
    return object_response(serialize.delivery(rec), 201)


@app.route("/deliveries/<rid>", methods=["GET"])
def get_delivery(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    rec = find_or_404(db.deliveries, rid)
    return object_response(serialize.delivery(rec))


@app.route("/deliveries", methods=["GET"])
def list_deliveries():
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    from flask import request
    filters = {
        "order_id": request.args.get("order_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.deliveries, serialize.delivery, filters)


@app.route("/deliveries/<rid>/confirm", methods=["POST"])
def confirm_delivery(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    rec = find_or_404(db.deliveries, rid)
    order = db.dme_orders.get(rec["order_id"])
    if order is None:
        raise err("ERR_NOT_FOUND", "Order not found")
    # State (409): delivery must be SCHEDULED.
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Delivery must be SCHEDULED to confirm")
    # Cross-entity state (409): order must be READY_FOR_DELIVERY.
    if order["status"] != "READY_FOR_DELIVERY":
        raise err("ERR_INVALID_STATE", "Order must be READY_FOR_DELIVERY to confirm delivery")
    body = get_body()
    pod = body.get("pod_signature_name")
    if not isinstance(pod, str) or pod == "":
        raise err("ERR_POD_SIGNATURE_REQUIRED", "A non-empty pod_signature_name is required to confirm")
    rec["status"] = "CONFIRMED"
    rec["pod_signature_name"] = pod
    rec["pod_received"] = True
    rec["delivered_at_utc"] = to_iso8601(clock.now())
    db.touch(rec)
    # Bubble-up: order READY_FOR_DELIVERY -> DELIVERED.
    order["status"] = "DELIVERED"
    db.touch(order)
    return object_response(serialize.delivery(rec))


@app.route("/deliveries/<rid>/fail", methods=["POST"])
def fail_delivery(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    rec = find_or_404(db.deliveries, rid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Delivery must be SCHEDULED to fail")
    rec["status"] = "FAILED"
    db.touch(rec)
    return object_response(serialize.delivery(rec))


@app.route("/deliveries/<rid>/cancel", methods=["POST"])
def cancel_delivery(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    rec = find_or_404(db.deliveries, rid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Delivery must be SCHEDULED to cancel")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return object_response(serialize.delivery(rec))


# ===========================================================================
# RentalBillingCycle — PRD 3.7
# ===========================================================================
@app.route("/rental-cycles/<rid>", methods=["GET"])
def get_rental_cycle(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    rec = find_or_404(db.rental_cycles, rid)
    return object_response(serialize.rental_cycle(rec))


@app.route("/rental-cycles", methods=["GET"])
def list_rental_cycles():
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    from flask import request
    filters = {
        "order_id": request.args.get("order_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.rental_cycles, serialize.rental_cycle, filters)


@app.route("/rental-cycles/<rid>/mark-paid", methods=["POST"])
def mark_paid(rid):
    _uid, role = require_auth()
    require_role(role, {"PayerReviewer"})
    cycle = find_or_404(db.rental_cycles, rid)
    if cycle["status"] != "BILLED":
        raise err("ERR_INVALID_STATE", "Cycle must be BILLED to mark paid")
    cycle["status"] = "PAID"
    db.touch(cycle)
    # Linked claim line POSTED -> SETTLED.
    for cl in db.claim_lines.values():
        if cl["rental_cycle_id"] == cycle["id"] and cl["status"] == "POSTED":
            cl["status"] = "SETTLED"
            db.touch(cl)
    # rental_months_billed recompute is unchanged (PAID counts the same as BILLED).
    return object_response(serialize.rental_cycle(cycle))


# ===========================================================================
# ClaimLine — PRD 3.9
# ===========================================================================
@app.route("/claim-lines/<rid>", methods=["GET"])
def get_claim_line(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    rec = find_or_404(db.claim_lines, rid)
    return object_response(serialize.claim_line(rec))


@app.route("/claim-lines", methods=["GET"])
def list_claim_lines():
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    from flask import request
    filters = {
        "order_id": request.args.get("order_id"),
        "rental_cycle_id": request.args.get("rental_cycle_id"),
        "audit_id": request.args.get("audit_id"),
        "line_type": request.args.get("line_type"),
        "status": request.args.get("status"),
    }
    return list_response(db.claim_lines, serialize.claim_line, filters)


# ===========================================================================
# CPAPResupplyOrder — PRD 3.10
# ===========================================================================
SUPPLY_KINDS = {"MASK", "TUBING", "FILTER", "HEADGEAR"}


@app.route("/cpap-resupply-orders", methods=["POST"])
def create_cpap_resupply():
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    body = get_body()
    if isinstance(body.get("order_id"), str):
        find_or_404(db.dme_orders, body["order_id"])
    order_id = require_str(body, "order_id")
    order = db.dme_orders[order_id]
    item = db.hcpcs_items[order["hcpcs_item_id"]]
    # Business constraint (priority 12): parent order's item must be is_cpap.
    if not item["is_cpap"]:
        raise err("ERR_NOT_A_CPAP_ORDER", "CPAP resupply requires a CPAP order")
    supply_kind = require_enum(body, "supply_kind", SUPPLY_KINDS)
    quantity = require_int(body, "quantity", lo=1, hi=12)
    rec = {
        "order_id": order_id,
        "supply_kind": supply_kind,
        "requested_at_utc": to_iso8601(clock.now()),
        "quantity": quantity,
        "status": "REQUESTED",
    }
    db.init_common(rec)
    db.cpap_resupply_orders[rec["id"]] = rec
    return object_response(serialize.cpap_resupply_order(rec), 201)


@app.route("/cpap-resupply-orders/<rid>", methods=["GET"])
def get_cpap_resupply(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    rec = find_or_404(db.cpap_resupply_orders, rid)
    return object_response(serialize.cpap_resupply_order(rec))


@app.route("/cpap-resupply-orders", methods=["GET"])
def list_cpap_resupplies():
    _uid, role = require_auth()
    require_role(role, {"SupplierUser", "PayerReviewer"})
    from flask import request
    filters = {
        "order_id": request.args.get("order_id"),
        "supply_kind": request.args.get("supply_kind"),
        "status": request.args.get("status"),
    }
    return list_response(db.cpap_resupply_orders, serialize.cpap_resupply_order, filters)


@app.route("/cpap-resupply-orders/<rid>/ship", methods=["POST"])
def ship_cpap_resupply(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    rec = find_or_404(db.cpap_resupply_orders, rid)
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Resupply must be REQUESTED to ship")
    # Eligibility window: prior SHIPPED of same kind on same order, by latest
    # requested_at_utc DESC, tie-break created_at ASC.
    this_req = parse_iso8601(rec["requested_at_utc"])
    candidates = [
        r
        for r in db.cpap_resupply_orders.values()
        if r["order_id"] == rec["order_id"]
        and r["supply_kind"] == rec["supply_kind"]
        and r["status"] == "SHIPPED"
        and r["id"] != rec["id"]
    ]
    if candidates:
        # latest requested_at_utc; tie-break earliest created_at.
        candidates.sort(key=lambda r: (parse_iso8601(r["requested_at_utc"]), ), reverse=True)
        latest_req = parse_iso8601(candidates[0]["requested_at_utc"])
        # If multiple share the same requested_at, pick earliest created_at among them.
        tied = [c for c in candidates if parse_iso8601(c["requested_at_utc"]) == latest_req]
        tied.sort(key=lambda r: r["created_at"])
        prior = tied[0]
        prior_req = parse_iso8601(prior["requested_at_utc"])
        gap_days = whole_days_between(prior_req, this_req)
        if gap_days < RESUPPLY_WINDOW_DAYS:
            raise err("ERR_RESUPPLY_TOO_SOON", "Resupply is within the 90-day window")
    rec["status"] = "SHIPPED"
    db.touch(rec)
    return object_response(serialize.cpap_resupply_order(rec))


@app.route("/cpap-resupply-orders/<rid>/deny", methods=["POST"])
def deny_cpap_resupply(rid):
    _uid, role = require_auth()
    require_role(role, {"SupplierUser"})
    rec = find_or_404(db.cpap_resupply_orders, rid)
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Resupply must be REQUESTED to deny")
    rec["status"] = "DENIED"
    db.touch(rec)
    return object_response(serialize.cpap_resupply_order(rec))


# ===========================================================================
# Audit — PRD 3.11
# ===========================================================================
REASON_CODES = {"NO_VALID_CMN", "NO_PROOF_OF_DELIVERY", "OVERBILLED_PAST_CAP", "NO_PRIOR_AUTH"}


@app.route("/audits", methods=["POST"])
def create_audit():
    _uid, role = require_auth()
    require_role(role, {"PayerReviewer"})
    body = get_body()
    if isinstance(body.get("order_id"), str):
        find_or_404(db.dme_orders, body["order_id"])
    order_id = require_str(body, "order_id")
    reason_code = require_enum(body, "reason_code", REASON_CODES)
    rec = {
        "order_id": order_id,
        "reason_code": reason_code,
        "recouped_total_cents": 0,
        "recouped_cycle_count": 0,
        "status": "OPEN",
    }
    db.init_common(rec)
    db.audits[rec["id"]] = rec
    return object_response(serialize.audit(rec), 201)


@app.route("/audits/<rid>", methods=["GET"])
def get_audit(rid):
    _uid, role = require_auth()
    require_role(role, {"PayerReviewer", "SupplierUser"})
    rec = find_or_404(db.audits, rid)
    return object_response(serialize.audit(rec))


@app.route("/audits", methods=["GET"])
def list_audits():
    _uid, role = require_auth()
    require_role(role, {"PayerReviewer", "SupplierUser"})
    from flask import request
    filters = {
        "order_id": request.args.get("order_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.audits, serialize.audit, filters)


@app.route("/audits/<rid>/uphold", methods=["POST"])
def uphold_audit(rid):
    _uid, role = require_auth()
    require_role(role, {"PayerReviewer"})
    audit = find_or_404(db.audits, rid)
    if audit["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Audit must be OPEN to uphold")
    order = db.dme_orders.get(audit["order_id"])
    if order is None:
        raise err("ERR_NOT_FOUND", "Order not found")

    # Recoupment basis by reason_code:
    #   NO_PROOF_OF_DELIVERY -> only PAID cycles
    #   else (OVERBILLED_PAST_CAP / NO_VALID_CMN / NO_PRIOR_AUTH) -> BILLED + PAID
    if audit["reason_code"] == "NO_PROOF_OF_DELIVERY":
        target_statuses = {"PAID"}
    else:
        target_statuses = {"BILLED", "PAID"}

    cycles = [
        c for c in order_cycles(order["id"]) if c["status"] in target_statuses
    ]
    cycles.sort(key=lambda c: c["cycle_index"])

    from common import round_half_up

    recouped_total = 0
    recouped_count = 0
    for cycle in cycles:
        # Move cycle -> RECOUPED.
        cycle["status"] = "RECOUPED"
        db.touch(cycle)
        # Per-cycle rounded amount (already whole cents, but round per spec).
        rounded = round_half_up(cycle["billed_amount_cents"])
        recouped_total += rounded
        recouped_count += 1
        # Create a RECOUPMENT claim line (negative) tied to this audit.
        rec_cl = {
            "order_id": order["id"],
            "rental_cycle_id": cycle["id"],
            "audit_id": audit["id"],
            "line_type": "RECOUPMENT",
            "allowed_amount_cents": -rounded,
            "status": "POSTED",
        }
        db.init_common(rec_cl)
        db.claim_lines[rec_cl["id"]] = rec_cl
        # Void the cycle's original linked claim line(s).
        for cl in db.claim_lines.values():
            if (
                cl["rental_cycle_id"] == cycle["id"]
                and cl["line_type"] == "RENTAL_MONTH"
                and cl["status"] != "VOID"
            ):
                cl["status"] = "VOID"
                db.touch(cl)

    audit["status"] = "UPHELD"
    audit["recouped_total_cents"] = recouped_total
    audit["recouped_cycle_count"] = recouped_count
    db.touch(audit)

    # Recompute order ledger after the cascade (PRD 3.11 recomputes
    # total_allowed_cents only; rental_months_billed/cap_reached are not
    # re-derived on uphold — the cap conversion is permanent once reached).
    recompute_total_allowed(order)
    db.touch(order)

    return object_response(serialize.audit(audit))


@app.route("/audits/<rid>/dismiss", methods=["POST"])
def dismiss_audit(rid):
    _uid, role = require_auth()
    require_role(role, {"PayerReviewer"})
    audit = find_or_404(db.audits, rid)
    if audit["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Audit must be OPEN to dismiss")
    audit["status"] = "DISMISSED"
    db.touch(audit)
    return object_response(serialize.audit(audit))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
