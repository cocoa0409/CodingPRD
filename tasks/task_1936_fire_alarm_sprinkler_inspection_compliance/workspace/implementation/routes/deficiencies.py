"""Deficiency endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, ALL_ROLES,
    ROLE_CONTRACTOR_ADMIN, ROLE_FIRE_MARSHAL, ROLE_TECHNICIAN,
)
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_str, req_enum
from errors import (
    invalid_state, cross_reference_mismatch, event_not_completed,
    segregation_of_duties, critical_not_waivable, deficiency_not_extensible,
)
from services.core import (
    base_record, public, touch,
    get_event, get_deficiency, ref_device,
    contractor_of_event, property_of_event,
    require_contractor_active, require_property_active,
)
from services import calc

bp = Blueprint("deficiencies", __name__)

CLASSIFICATIONS = {"CRITICAL", "NONCRITICAL"}


@bp.route("/fire-compliance/inspection-events/<eid>/deficiencies", methods=["POST"])
def create_deficiency(eid):
    require_roles([ROLE_TECHNICIAN])
    ev = get_event(eid)
    body = get_body()
    check_unknown_fields(body, {"device_id", "classification"})
    device_id = req_str(body, "device_id")
    dev = ref_device(device_id)
    prop = property_of_event(ev)
    con = contractor_of_event(ev)
    require_contractor_active(con)
    require_property_active(prop)
    # findings are recorded during or after an inspection
    if ev["status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise invalid_state("Event has not been started or is terminally closed")
    classification = req_enum(body, "classification", CLASSIFICATIONS)
    # cross-aggregate integrity (15): device must belong to the event's system
    if dev["system_id"] != ev["system_id"]:
        raise cross_reference_mismatch("device_id does not belong to the event's system")

    rec = base_record()
    deadline = None
    if ev["status"] == "COMPLETED" and ev["completed_at"] is not None:
        deadline = ev["completed_at"].date() + timedelta(
            days=calc.correction_window_days(classification))
    rec.update({
        "event_id": ev["id"],
        "device_id": dev["id"],
        "classification": classification,
        "correction_deadline": deadline,
        "extension_used": False,
        "late_fee_cents": 0,
        "corrected_at": None,
        "status": "OPEN",
        "_attested_by": None,
    })
    store.deficiencies[rec["id"]] = rec
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/inspection-events/<eid>/deficiencies", methods=["GET"])
def list_deficiencies_of_event(eid):
    require_roles(ALL_ROLES)
    ev = get_event(eid)
    rows = [d for d in store.deficiencies.values() if d["event_id"] == ev["id"]]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/deficiencies/<did>", methods=["GET"])
def fetch_deficiency(did):
    require_roles(ALL_ROLES)
    return success_object(public(get_deficiency(did)))


@bp.route("/fire-compliance/deficiencies", methods=["GET"])
def list_deficiencies_cross():
    require_roles(ALL_ROLES)
    event_id = request.args.get("event_id")
    device_id = request.args.get("device_id")
    status = request.args.get("status")
    rows = list(store.deficiencies.values())
    if event_id is not None:
        rows = [d for d in rows if d["event_id"] == event_id]
    if device_id is not None:
        rows = [d for d in rows if d["device_id"] == device_id]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/deficiencies/<did>/attest-correction", methods=["POST"])
def attest_correction(did):
    _, user_id = require_roles([ROLE_CONTRACTOR_ADMIN])
    d = get_deficiency(did)
    if d["status"] != "OPEN":
        raise invalid_state("Deficiency is not OPEN")
    ev = store.events.get(d["event_id"])
    con = contractor_of_event(ev) if ev else None
    require_contractor_active(con)
    if ev is None or ev["status"] != "COMPLETED":
        raise event_not_completed("Parent event is not COMPLETED")

    now = store.now()
    d["corrected_at"] = now
    d["late_fee_cents"] = calc.deficiency_late_fee_cents(d, now.date())
    d["status"] = "CORRECTED"
    d["_attested_by"] = user_id
    touch(d)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(d))


@bp.route("/fire-compliance/deficiencies/<did>/verify", methods=["POST"])
def verify_correction(did):
    _, user_id = require_roles([ROLE_FIRE_MARSHAL])
    d = get_deficiency(did)
    if d["status"] != "CORRECTED":
        raise invalid_state("Deficiency is not CORRECTED")
    # segregation of duties (19): verifier must differ from the attester
    if d.get("_attested_by") is not None and d["_attested_by"] == user_id:
        raise segregation_of_duties("Verifying marshal must differ from the attesting actor")
    d["status"] = "VERIFIED"
    touch(d)
    ev = store.events.get(d["event_id"])
    con = contractor_of_event(ev) if ev else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(d))


@bp.route("/fire-compliance/deficiencies/<did>/reject-correction", methods=["POST"])
def reject_correction(did):
    require_roles([ROLE_FIRE_MARSHAL])
    d = get_deficiency(did)
    if d["status"] != "CORRECTED":
        raise invalid_state("Deficiency is not CORRECTED")
    d["status"] = "OPEN"
    d["corrected_at"] = None
    # late-fee accrual resumes against the ORIGINAL correction_deadline (no reset)
    d["late_fee_cents"] = calc.deficiency_late_fee_cents(d, store.today())
    d["_attested_by"] = None
    touch(d)
    ev = store.events.get(d["event_id"])
    con = contractor_of_event(ev) if ev else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(d))


@bp.route("/fire-compliance/deficiencies/<did>/waive", methods=["POST"])
def waive_deficiency(did):
    require_roles([ROLE_FIRE_MARSHAL])
    d = get_deficiency(did)
    if d["status"] != "OPEN":
        raise invalid_state("Deficiency is not OPEN")
    # critical-waiver bar (9)
    if d["classification"] == "CRITICAL":
        raise critical_not_waivable("A CRITICAL deficiency is never waivable")
    d["status"] = "WAIVED"
    d["late_fee_cents"] = 0
    touch(d)
    ev = store.events.get(d["event_id"])
    con = contractor_of_event(ev) if ev else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(d))


@bp.route("/fire-compliance/deficiencies/<did>/extend-deadline", methods=["POST"])
def extend_deadline(did):
    require_roles([ROLE_FIRE_MARSHAL])
    d = get_deficiency(did)
    # extension eligibility (20): OPEN, NONCRITICAL, never before extended
    if d["status"] != "OPEN" or d["classification"] != "NONCRITICAL" or d["extension_used"]:
        raise deficiency_not_extensible(
            "Only an OPEN NONCRITICAL deficiency never before extended may be extended")
    if d["correction_deadline"] is not None:
        d["correction_deadline"] = d["correction_deadline"] + timedelta(
            days=calc.DEFICIENCY_EXTENSION_DAYS)
    d["extension_used"] = True
    touch(d)
    ev = store.events.get(d["event_id"])
    con = contractor_of_event(ev) if ev else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(d))
