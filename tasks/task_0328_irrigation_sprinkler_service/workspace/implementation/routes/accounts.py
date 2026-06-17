"""Customer, Technician, Property routes (PRD §3.1)."""
from flask import Blueprint

from db import db, LOCK, stamp_new, touch
import domain
import lookups
from domain import serialize
from listing import list_response
from middleware import get_auth, require_role
from response import success
from validation import get_body, require_str, require_int, require_number, optional_bool

bp = Blueprint("accounts", __name__)


# ---------------- Customer ----------------
@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        body = get_body()
        company_name = require_str(body, "company_name")
        contact_email = require_str(body, "contact_email")
        billing_zip = require_str(body, "billing_zip")
        rec = {
            "company_name": company_name,
            "contact_email": contact_email,
            "billing_zip": billing_zip,
            "status": "ACTIVE",
        }
        stamp_new(rec)
        db.customers[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer"})
    with LOCK:
        rec = lookups.get_customer(cid)
        return success(serialize(rec), status=200)


@bp.route("/customers", methods=["GET"])
def list_customers():
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        return list_response(list(db.customers.values()))


@bp.route("/customers/<cid>/suspend", methods=["POST"])
def suspend_customer(cid):
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        rec = lookups.get_customer(cid)
        rec["status"] = "SUSPENDED"
        touch(rec)
        return success(serialize(rec), status=200)


# ---------------- Technician ----------------
@bp.route("/technicians", methods=["POST"])
def create_technician():
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        body = get_body()
        full_name = require_str(body, "full_name")
        shift_start = require_int(body, "shift_start_sec", minimum=0, maximum=86399)
        shift_end = require_int(body, "shift_end_sec", minimum=0, maximum=86399)
        if shift_end <= shift_start:
            from errors import fail
            import errors
            fail(errors.ERR_INVALID_REQUEST, "shift_end_sec must be > shift_start_sec")
        backflow_certified = optional_bool(body, "backflow_certified", default=False)
        rec = {
            "full_name": full_name,
            "shift_start_sec": shift_start,
            "shift_end_sec": shift_end,
            "backflow_certified": backflow_certified,
            "status": "AVAILABLE",
        }
        stamp_new(rec)
        db.technicians[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/technicians/<tid>", methods=["GET"])
def get_technician(tid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Technician", "BackflowTester"})
    with LOCK:
        rec = lookups.get_technician(tid)
        return success(serialize(rec), status=200)


@bp.route("/technicians", methods=["GET"])
def list_technicians():
    from flask import request
    import errors
    from errors import fail
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        rows = list(db.technicians.values())
        cert = request.args.get("backflow_certified")
        if cert is not None:
            if cert.lower() in ("true", "1"):
                want = True
            elif cert.lower() in ("false", "0"):
                want = False
            else:
                fail(errors.ERR_INVALID_REQUEST, "backflow_certified must be a boolean")
            rows = [t for t in rows if t["backflow_certified"] == want]
        return list_response(rows)


# ---------------- Property ----------------
@bp.route("/properties", methods=["POST"])
def create_property():
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        body = get_body()
        customer_id = require_str(body, "customer_id")
        # existence (priority 3) — FK resolved left-to-right
        lookups.get_customer(customer_id)
        site_address = require_str(body, "site_address")
        lat = require_number(body, "lat")
        lng = require_number(body, "lng")
        rec = {
            "customer_id": customer_id,
            "site_address": site_address,
            "lat": lat,
            "lng": lng,
            "status": "ACTIVE",
            "compliance_status": "NON_COMPLIANT",
        }
        stamp_new(rec)
        db.properties[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer"})
    with LOCK:
        rec = lookups.get_property(pid)
        return success(serialize(rec), status=200)


@bp.route("/properties", methods=["GET"])
def list_properties():
    from flask import request
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer"})
    with LOCK:
        rows = list(db.properties.values())
        customer_id = request.args.get("customer_id")
        if customer_id is not None:
            rows = [p for p in rows if p["customer_id"] == customer_id]
        return list_response(rows)
