"""Vendor (sutler row) endpoints: apply, list, read, approve, contract, revoke, settle."""

from flask import Blueprint, request

import db
import serializers
from errors import fail
from middleware import authenticate, get_event, get_vendor, own_vendor_scope
from response import success
from services import cascades
from services.common import new_record, paginate, touch
from services.derived import sorted_all
from services.pricing import vendor_booth_fee
from util import body, req_int, req_str

bp = Blueprint("vendors", __name__)


@bp.post("/events/<event_id>/vendors")
def apply_vendor(event_id):
    uid, _ = authenticate(["Vendor"], creation=True)
    ev = get_event(event_id)
    if ev["event_posture"] not in ("REGISTRATION_OPEN", "PUBLISHED"):
        fail("ERR_INVALID_EVENT_POSTURE", "vendor applications require REGISTRATION_OPEN or PUBLISHED")
    data = body(request)
    business_name = req_str(data, "business_name")
    wares = req_str(data, "wares_description")
    frontage = req_int(data, "frontage_feet", minimum=1)
    days = req_int(data, "requested_days", minimum=1)
    rec = new_record()
    rec.update(
        event_id=ev["id"],
        # Bootstrap anchor: caller's X-User-ID, else the vendor's own id.
        owner_user_id=uid if uid else rec["id"],
        business_name=business_name,
        wares_description=wares,
        frontage_feet=frontage,
        requested_days=days,
        status="APPLIED",
        provisional_fee_cents=None,
        final_fee_cents=None,
        fee_paid_cents=0,
        insurance_cert_ref=None,
        insurance_uploaded_at=None,
        balance_due_cents=None,
    )
    db.vendors[rec["id"]] = rec
    return success(serializers.vendor(rec), 201)


@bp.get("/events/<event_id>/vendors")
def list_vendors(event_id):
    authenticate(["EventOrganizer", "SafetyOfficer"])
    ev = get_event(event_id)
    items = sorted_all(v for v in db.vendors.values() if v["event_id"] == ev["id"])
    page, meta = paginate(items)
    return success([serializers.vendor(v) for v in page], 200, pagination=meta)


@bp.get("/vendors/<vendor_id>")
def read_vendor(vendor_id):
    uid, role = authenticate(["Vendor", "EventOrganizer"])
    v = get_vendor(vendor_id)
    if role == "Vendor":
        own_vendor_scope(uid, v)
    return success(serializers.vendor(v), 200)


@bp.post("/vendors/<vendor_id>/approve")
def approve_vendor(vendor_id):
    authenticate(["EventOrganizer"])
    v = get_vendor(vendor_id)
    if v["status"] != "APPLIED":
        fail("ERR_INVALID_VENDOR_STATUS", "only an APPLIED vendor can be approved")
    ev = db.events[v["event_id"]]
    v["provisional_fee_cents"] = vendor_booth_fee(ev, v, final_variant=False)
    v["status"] = "APPROVED"
    touch(v)
    return success(serializers.vendor(v), 200)


@bp.post("/vendors/<vendor_id>/contract")
def contract_vendor(vendor_id):
    uid, _ = authenticate(["Vendor"])
    v = get_vendor(vendor_id)
    own_vendor_scope(uid, v)
    ev = db.events[v["event_id"]]
    if ev["event_posture"] not in ("REGISTRATION_OPEN", "PUBLISHED"):
        fail("ERR_INVALID_EVENT_POSTURE", "contracting requires REGISTRATION_OPEN or PUBLISHED")
    if v["status"] != "APPROVED":
        fail("ERR_INVALID_VENDOR_STATUS", "only an APPROVED vendor can contract")
    data = body(request)
    cert_ref = req_str(data, "insurance_cert_ref")
    payment = req_int(data, "fee_payment_cents", minimum=0)
    v["insurance_cert_ref"] = cert_ref
    v["insurance_uploaded_at"] = db.now()
    v["fee_paid_cents"] += payment
    v["status"] = "CONTRACTED"
    touch(v)
    return success(serializers.vendor(v), 200)


@bp.post("/vendors/<vendor_id>/revoke")
def revoke_vendor(vendor_id):
    authenticate(["EventOrganizer", "SafetyOfficer"])
    v = get_vendor(vendor_id)
    if v["status"] not in ("APPLIED", "APPROVED", "CONTRACTED"):
        fail("ERR_INVALID_VENDOR_STATUS", f"vendor in {v['status']} cannot be revoked")
    cascades.revoke_vendor(v)
    return success(serializers.vendor(v), 200)


@bp.post("/vendors/<vendor_id>/settle")
def settle_vendor(vendor_id):
    authenticate(["EventOrganizer"])
    v = get_vendor(vendor_id)
    ev = db.events[v["event_id"]]
    if ev["event_posture"] != "COMPLETED":
        fail("ERR_INVALID_EVENT_POSTURE", "settlement requires a COMPLETED event")
    if v["status"] != "CONTRACTED":
        fail("ERR_INVALID_VENDOR_STATUS", "only a CONTRACTED vendor can be settled")
    # A SIGNED LANDOWNER_USE agreement must be in force at settlement time.
    now = db.now()
    in_force = any(
        a["event_id"] == ev["id"]
        and a["agreement_type"] == "LANDOWNER_USE"
        and a["status"] == "SIGNED"
        and a["effective_from"] <= now <= a["effective_until"]
        for a in db.agreements.values()
    )
    if not in_force:
        fail("ERR_AGREEMENT_NOT_IN_FORCE", "no SIGNED LANDOWNER_USE agreement is in force")
    if v["fee_paid_cents"] < (v["provisional_fee_cents"] or 0):
        fail("ERR_VENDOR_BALANCE_OUTSTANDING", "fee_paid_cents is below the provisional fee")
    v["final_fee_cents"] = vendor_booth_fee(ev, v, final_variant=True)
    v["balance_due_cents"] = v["final_fee_cents"] - v["fee_paid_cents"]
    v["status"] = "SETTLED"
    touch(v)
    return success(serializers.vendor(v), 200)
