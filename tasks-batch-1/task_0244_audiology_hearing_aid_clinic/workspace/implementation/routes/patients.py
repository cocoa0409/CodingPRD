"""Patient endpoints + the patient-scoped reverse-reachability listings
(evaluations, orders, subscriptions, ledger)."""

from flask import Blueprint, request

from db import db
import serialize
import validate
from middleware import require_auth, require_role, require_ownership, get_json_body
from response import object_response, array_response
from services.domain import get_or_404
from services.listing import list_page

bp = Blueprint("patients", __name__)


@bp.post("/clinic/patients")
def create_patient():
    auth = require_auth()
    require_role(auth, {"ClinicAdmin", "BillingClerk"})
    body = get_json_body()
    full_name = validate.require_str(body, "full_name")
    date_of_birth = validate.require_date(body, "date_of_birth")
    insurer_name = validate.optional_str(body, "insurer_name")

    obj = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "insurer_name": insurer_name,
        "status": "ACTIVE",
    }
    db.stamp_create(obj)
    with db.lock:
        db.patients[obj["id"]] = obj
    return object_response(serialize.patient(obj), 201)


@bp.get("/clinic/patients/<pid>")
def get_patient(pid):
    auth = require_auth()
    require_role(auth, {"ClinicAdmin", "BillingClerk", "Audiologist", "Patient"})
    obj = get_or_404(db.patients, pid)
    # A Patient may only fetch their own record.
    require_ownership(auth, obj["id"])
    return object_response(serialize.patient(obj))


@bp.get("/clinic/patients")
def list_patients():
    auth = require_auth()
    require_role(auth, {"ClinicAdmin", "BillingClerk"})
    status = request.args.get("status")
    items = [p for p in db.patients.values() if status is None or p["status"] == status]
    page, limit, offset, total = list_page(request.args, items, serialize.patient)
    return array_response(page, limit, offset, total)


@bp.get("/clinic/patients/<pid>/evaluations")
def list_patient_evaluations(pid):
    auth = require_auth()
    require_role(auth, {"Audiologist", "BillingClerk", "ClinicAdmin"})
    get_or_404(db.patients, pid)
    status = request.args.get("status")
    items = [e for e in db.evaluations.values()
             if e["patient_id"] == pid and (status is None or e["status"] == status)]
    page, limit, offset, total = list_page(request.args, items, serialize.evaluation)
    return array_response(page, limit, offset, total)


@bp.get("/clinic/patients/<pid>/orders")
def list_patient_orders(pid):
    auth = require_auth()
    require_role(auth, {"Audiologist", "BillingClerk", "ClinicAdmin", "Patient"})
    patient = get_or_404(db.patients, pid)
    require_ownership(auth, patient["id"])
    status = request.args.get("status")
    items = [o for o in db.orders.values()
             if o["patient_id"] == pid and (status is None or o["status"] == status)]
    page, limit, offset, total = list_page(request.args, items, serialize.order)
    return array_response(page, limit, offset, total)


@bp.get("/clinic/patients/<pid>/subscriptions")
def list_patient_subscriptions(pid):
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin", "Patient"})
    patient = get_or_404(db.patients, pid)
    require_ownership(auth, patient["id"])
    status = request.args.get("status")
    items = [s for s in db.subscriptions.values()
             if s["patient_id"] == pid and (status is None or s["status"] == status)]
    page, limit, offset, total = list_page(request.args, items, serialize.subscription)
    return array_response(page, limit, offset, total)


@bp.get("/clinic/patients/<pid>/ledger")
def list_patient_ledger(pid):
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin", "Patient"})
    patient = get_or_404(db.patients, pid)
    require_ownership(auth, patient["id"])
    source_kind = request.args.get("source_kind")
    items = [e for e in db.ledger.values()
             if e["patient_id"] == pid and (source_kind is None or e["source_kind"] == source_kind)]
    page, limit, offset, total = list_page(request.args, items, serialize.ledger_entry)
    return array_response(page, limit, offset, total)
