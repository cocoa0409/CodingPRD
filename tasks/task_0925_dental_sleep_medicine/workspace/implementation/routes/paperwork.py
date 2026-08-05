"""Standard written orders and prior authorisations."""

from flask import Blueprint, request

import calc
import domain
import validation as v
from access import (actor, body_refs, gate_frozen, in_scope, new_row, path_row,
                    require_identity, require_scope, touch)
from envelope import created, ok
from errors import fail
from serializers import dump
from store import DB, add_days, clock_date, day_span

bp = Blueprint("paperwork", __name__)


# ---------------------------------------------------------- written orders

@bp.post("/written-orders")
def create_written_order():
    uid, role = actor(["SleepPhysician"])
    body = v.read_body()
    refs = body_refs(body, ["patient_id", "ordering_physician_id"])
    gate_frozen(refs["patient_id"])
    if body.get("ordering_physician_id") is not None and body["ordering_physician_id"] != uid:
        fail("ERR_NOT_CARE_TEAM", "A physician may only issue an order naming himself.")
    if refs["patient_id"] is not None:
        require_scope(role, uid, refs["patient_id"]["id"])
    fields = [
        v.S("patient_id", required=True),
        v.S("ordering_physician_id", required=True),
        v.S("item_hcpcs", required=True, enum=v.ENUM_HCPCS),
        v.D("order_date", required=True),
        v.D("f2f_encounter_date", required=True),
        v.I("expected_patient_version", required=True),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    order_date = v.date_of(body, "order_date")
    f2f_encounter_date = v.date_of(body, "f2f_encounter_date")
    if f2f_encounter_date > order_date:
        fail("ERR_VALIDATION", "f2f_encounter_date may not follow order_date.")
    patient = refs["patient_id"]
    if body["expected_patient_version"] != patient["version"]:
        fail("ERR_STALE_VERSION", "expected_patient_version does not match the patient's version.")
    physician = refs["ordering_physician_id"]
    if physician["provider_type"] != "SLEEP_PHYSICIAN" or physician["status"] != "ACTIVE":
        fail("ERR_PROVIDER_TYPE_MISMATCH", "ordering_physician_id must be an ACTIVE SLEEP_PHYSICIAN.")

    for older in list(DB["written_orders"].values()):
        if older["patient_id"] != patient["id"] or older["item_hcpcs"] != body["item_hcpcs"]:
            continue
        if older["status"] == "DRAFT":
            older["status"] = "SUPERSEDED"
            touch(older)
        elif older["status"] == "SIGNED":
            referenced = any(a.get("written_order_id") == older["id"]
                             for a in DB["appliances"].values())
            if not referenced:
                older["status"] = "SUPERSEDED"
                touch(older)

    touch(patient)
    row = new_row("written_orders", {
        "patient_id": patient["id"],
        "ordering_physician_id": body["ordering_physician_id"],
        "item_hcpcs": body["item_hcpcs"],
        "order_date": order_date,
        "f2f_encounter_date": f2f_encounter_date,
        "signed_on": None,
        "f2f_age_days": day_span(f2f_encounter_date, order_date),
        "status": "DRAFT",
    })
    return created(dump("written_order", row))


@bp.get("/written-orders/<written_order_id>")
def read_written_order(written_order_id):
    uid, role = actor(["SleepPhysician", "Dentist", "BillingSpecialist", "PlatformAdmin"])
    row = path_row("written_order_id", written_order_id)
    require_scope(role, uid, row["patient_id"])
    return ok(dump("written_order", row))


@bp.get("/written-orders")
def list_written_orders():
    uid, role = actor(["SleepPhysician", "Dentist", "BillingSpecialist", "PlatformAdmin"])
    limit, offset = v.pagination()
    filters = {
        "patient_id": request.args.get("patient_id"),
        "ordering_physician_id": request.args.get("ordering_physician_id"),
        "status": request.args.get("status"),
    }
    return domain.paginate("written_order", "written_orders", filters, limit, offset,
                           lambda r: in_scope(role, uid, r["patient_id"]))


@bp.post("/written-orders/<written_order_id>/sign")
def sign_written_order(written_order_id):
    uid, role = actor(["SleepPhysician"])
    order = path_row("written_order_id", written_order_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(order["patient_id"]))
    require_identity(uid, order["ordering_physician_id"])
    fields = [v.D("signed_on", required=True)]
    v.rung7(body, fields)
    v.rung8(body, fields)
    signed_on = v.date_of(body, "signed_on")
    if signed_on < order["order_date"]:
        fail("ERR_VALIDATION", "signed_on may not precede order_date.")
    if order["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT order may be signed.")
    order["signed_on"] = signed_on
    order["status"] = "SIGNED"
    touch(order)
    return ok(dump("written_order", order))


# ------------------------------------------------------ prior authorisations

@bp.post("/prior-auths")
def create_prior_auth():
    uid, role = actor(["BillingSpecialist"])
    body = v.read_body()
    refs = body_refs(body, ["patient_id", "payer_id", "referral_id"])
    gate_frozen(refs["patient_id"])
    fields = [
        v.S("patient_id", required=True),
        v.S("payer_id", required=True),
        v.S("referral_id", required=True),
        v.S("requested_hcpcs", required=True, enum=v.ENUM_HCPCS),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    referral = refs["referral_id"]
    if referral["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "The referral must be ACCEPTED.")
    domain.rung18_diagnosis_currency(referral)
    patient = refs["patient_id"]
    payer = refs["payer_id"]
    if payer["id"] != patient["medical_payer_id"] or payer["payer_kind"] != "MEDICAL":
        fail("ERR_DENTAL_PAYER_ROUTING", "Oral appliance therapy is a medical benefit.")
    row = new_row("prior_auths", {
        "patient_id": patient["id"],
        "payer_id": payer["id"],
        "referral_id": referral["id"],
        "requested_hcpcs": body["requested_hcpcs"],
        "submitted_on": clock_date(),
        "decided_on": None,
        "approval_valid_until": None,
        "denial_reason": None,
        "appeal_attempts": 0,
        "status": "SUBMITTED",
    })
    return created(dump("prior_auth", row))


@bp.get("/prior-auths/<prior_auth_id>")
def read_prior_auth(prior_auth_id):
    uid, role = actor(["BillingSpecialist", "PlatformAdmin", "Dentist"])
    row = path_row("prior_auth_id", prior_auth_id)
    require_scope(role, uid, row["patient_id"])
    return ok(dump("prior_auth", row))


@bp.get("/prior-auths")
def list_prior_auths():
    uid, role = actor(["BillingSpecialist", "PlatformAdmin", "Dentist"])
    limit, offset = v.pagination()
    filters = {
        "patient_id": request.args.get("patient_id"),
        "payer_id": request.args.get("payer_id"),
        "referral_id": request.args.get("referral_id"),
        "status": request.args.get("status"),
    }
    return domain.paginate("prior_auth", "prior_auths", filters, limit, offset,
                           lambda r: in_scope(role, uid, r["patient_id"]))


@bp.post("/prior-auths/<prior_auth_id>/decision")
def decide_prior_auth(prior_auth_id):
    uid, role = actor(["PlatformAdmin"])
    auth = path_row("prior_auth_id", prior_auth_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(auth["patient_id"]))
    fields = [
        v.S("decision", required=True, enum=v.ENUM_PA_DECISION),
        v.S("denial_reason", enum=v.ENUM_DENIAL_REASON),
        v.D("decided_on"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    decided_on = v.date_of(body, "decided_on")
    if body["decision"] == "DENIED" and body.get("denial_reason") is None:
        fail("ERR_VALIDATION", "denial_reason is required on a denial.")
    if auth["status"] not in ("SUBMITTED", "APPEALED"):
        fail("ERR_INVALID_STATE", "Only a SUBMITTED or APPEALED authorisation may be decided.")

    payer = DB["payers"].get(auth["payer_id"])
    effective = decided_on if decided_on is not None else clock_date()
    auth["decided_on"] = effective
    if body["decision"] == "APPROVED":
        auth["status"] = "APPROVED"
        auth["approval_valid_until"] = add_days(effective, calc.PA_VALIDITY_DAYS)
    else:
        auth["denial_reason"] = body["denial_reason"]
        limit = payer["appeal_limit"] if payer else 0
        auth["status"] = "DENIED_FINAL" if auth["appeal_attempts"] >= limit else "DENIED"
    touch(auth)
    return ok(dump("prior_auth", auth))


@bp.post("/prior-auths/<prior_auth_id>/appeal")
def appeal_prior_auth(prior_auth_id):
    uid, role = actor(["BillingSpecialist"])
    auth = path_row("prior_auth_id", prior_auth_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(auth["patient_id"]))
    fields = [v.S("narrative", required=True)]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if auth["status"] not in ("DENIED", "DENIED_FINAL"):
        fail("ERR_INVALID_STATE", "Only a denied authorisation may be appealed.")
    payer = DB["payers"].get(auth["payer_id"])
    limit = payer["appeal_limit"] if payer else 0
    if auth["appeal_attempts"] >= limit:
        fail("ERR_APPEAL_LIMIT_REACHED", "The payer's appeal limit has been reached.")
    auth["appeal_attempts"] = auth["appeal_attempts"] + 1
    auth["status"] = "APPEALED"
    touch(auth)
    return ok(dump("prior_auth", auth))
