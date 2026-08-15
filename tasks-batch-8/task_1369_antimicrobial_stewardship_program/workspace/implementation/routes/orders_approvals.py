"""Routes: antibiotic orders, administrations, approval requests."""

from decimal import Decimal

from flask import Blueprint

import db
from errors import (
    err_approval_already_open,
    err_approval_not_pending,
    err_cross_facility,
    err_drug_suspended,
    err_duplicate_active_order,
    err_escalated_requires_director,
    err_invalid_request,
    err_not_found,
    err_not_request_owner,
    err_open_intervention_blocks_close,
    err_order_approval_not_pending,
    err_patient_discharged,
    err_practitioner_inactive,
    err_prescriber_suspended,
    err_renal_dose_exceeded,
    err_restricted_order_cap,
    err_restricted_requires_approval,
    err_self_approval_forbidden,
    err_allergy_blocks_order,
)
from middleware import ALL_ROLES, auth_context, require_role
from response import success_object
from services import core
from services.core import ALLERGY_BLOCKING_STATUSES
from services.listing import list_response
from services.serializers import serialize
from util import (
    body_json,
    new_id,
    parse_iso,
    require_enum,
    require_fields,
    require_int,
    require_string,
    to_number,
)

bp = Blueprint("orders_approvals", __name__)

ROUTES = {"IV", "PO", "IM"}
INDICATIONS = {"EMPIRIC", "CULTURE_DIRECTED", "PROPHYLAXIS"}
DECISIONS = {"APPROVED", "DENIED"}
TERMINAL_THERAPY = {"COMPLETED", "DISCONTINUED"}
CLOSABLE_THERAPY = {"ACTIVE", "REVIEW_REQUIRED", "DEESCALATED", "CONVERTED"}


def get_order_or_404(oid):
    order = db.antibiotic_orders.get(oid)
    if order is None:
        raise err_not_found("AntibioticOrder not found")
    return order


def get_approval_or_404(rid):
    req = db.approval_requests.get(rid)
    if req is None:
        raise err_not_found("ApprovalRequest not found")
    return req


def _require_active_practitioner(pid, label="practitioner"):
    prac = db.practitioners.get(pid)
    if prac is None:
        raise err_not_found(f"Practitioner not found: {label}")
    if not prac.get("is_active", True):
        raise err_practitioner_inactive()
    return prac


# --- Orders -------------------------------------------------------------------------


@bp.route("/stewardship/antibiotic-orders", methods=["POST"])
def create_order():
    _, role = auth_context()
    require_role(role, {"AttendingPhysician"})
    payload = body_json()
    require_fields(
        payload,
        [
            "patient_case_id",
            "antimicrobial_id",
            "prescriber_id",
            "route",
            "dose_mg",
            "frequency_per_day",
            "indication",
        ],
    )
    # Input shape
    route = require_enum(payload, "route", ROUTES)
    dose_mg = require_int(payload, "dose_mg", minimum=1)
    frequency = require_int(payload, "frequency_per_day", minimum=1, maximum=4)
    indication = require_enum(payload, "indication", INDICATIONS)
    # Existence (body FK order as listed in the endpoint input table)
    patient = db.patient_cases.get(payload["patient_case_id"])
    if patient is None:
        raise err_not_found("PatientCase not found")
    drug = db.antimicrobials.get(payload["antimicrobial_id"])
    if drug is None:
        raise err_not_found("Antimicrobial not found")
    prescriber = db.practitioners.get(payload["prescriber_id"])
    if prescriber is None:
        raise err_not_found("Practitioner not found")
    # Referenced-state cascade (PRD 2.8 stage 4)
    if not prescriber.get("is_active", True):
        raise err_practitioner_inactive()
    if patient["status"] != "ADMITTED":
        raise err_patient_discharged()
    if drug["formulary_status"] != "ACTIVE":
        raise err_drug_suspended()
    # Clinical safety gates (stage 5): allergy first, then renal.
    if drug["is_penicillin_class"]:
        for a in db.allergy_assessments.values():
            if a["patient_case_id"] == patient["id"] and a["status"] in ALLERGY_BLOCKING_STATUSES:
                raise err_allergy_blocks_order()
    if patient["renal_function_crcl"] < 30 and dose_mg * frequency > 4000:
        raise err_renal_dose_exceeded()
    # Referential integrity (stage 7): one hospital for patient/drug/prescriber.
    if not (
        patient["hospital_id"] == drug["hospital_id"] == prescriber["hospital_id"]
    ):
        raise err_cross_facility()
    # Business constraints (stage 8)
    for other in db.antibiotic_orders.values():
        if (
            other["patient_case_id"] == patient["id"]
            and other["antimicrobial_id"] == drug["id"]
            and other["therapy_status"] not in TERMINAL_THERAPY
        ):
            raise err_duplicate_active_order()
    if drug["is_restricted"]:
        concurrent = 0
        for other in db.antibiotic_orders.values():
            if other["patient_case_id"] != patient["id"]:
                continue
            other_drug = db.antimicrobials.get(other["antimicrobial_id"])
            if other_drug is None or not other_drug["is_restricted"]:
                continue
            if (
                other["approval_status"] in ("PENDING", "APPROVED")
                and other["therapy_status"] not in TERMINAL_THERAPY
            ):
                concurrent += 1
        if concurrent >= 2:
            raise err_restricted_order_cap()
    # Threshold/standing (stage 9)
    if drug["is_restricted"] and prescriber.get("stewardship_standing") == "SUSPENDED":
        raise err_prescriber_suspended()

    hospital = db.hospitals.get(patient["hospital_id"])
    order = {
        "id": new_id(),
        "patient_case_id": patient["id"],
        "antimicrobial_id": drug["id"],
        "prescriber_id": prescriber["id"],
        "route": route,
        "dose_mg": dose_mg,
        "frequency_per_day": frequency,
        "indication": indication,
        "cumulative_iv_hours": 0,
        "administered_doses": 0,
        "dot_calendar": 0,
        "dot_dose": Decimal("0.00"),
        "stopped_at": None,
        "_hospital_id": patient["hospital_id"],
    }
    if drug["is_restricted"]:
        order["approval_status"] = "PENDING"
        order["therapy_status"] = "AWAITING_APPROVAL"
        order["started_at"] = None
    else:
        order["approval_status"] = "NOT_REQUIRED"
        order["therapy_status"] = "ACTIVE"
        order["started_at"] = core.clock_iso(hospital)
    core.stamp_new(order)
    db.antibiotic_orders[order["id"]] = order
    db.administration_events[order["id"]] = []
    return success_object(serialize(order), status=201)


@bp.route("/stewardship/antibiotic-orders/<oid>", methods=["GET"])
def get_order(oid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_order_or_404(oid)))


@bp.route("/stewardship/antibiotic-orders", methods=["GET"])
def list_orders():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(
        db.antibiotic_orders.values(),
        ["patient_case_id", "antimicrobial_id", "prescriber_id", "therapy_status", "approval_status"],
    )


@bp.route("/stewardship/antibiotic-orders/<oid>/administrations", methods=["POST"])
def record_administration(oid):
    _, role = auth_context()
    require_role(role, {"AttendingPhysician", "IDPharmacist"})
    order = get_order_or_404(oid)
    patient = db.patient_cases.get(order["patient_case_id"])
    if patient is not None and patient["status"] != "ADMITTED":
        raise err_patient_discharged()
    payload = body_json()
    require_fields(payload, ["administered_at"])
    administered_at = parse_iso(payload["administered_at"], "administered_at")
    drug = db.antimicrobials.get(order["antimicrobial_id"])
    if drug is not None and drug["is_restricted"] and order["approval_status"] != "APPROVED":
        raise err_restricted_requires_approval()
    if order["therapy_status"] in TERMINAL_THERAPY or order["therapy_status"] == "AWAITING_APPROVAL":
        raise err_invalid_request("Order is not in a therapy state that accepts administrations")
    db.administration_events.setdefault(order["id"], []).append(administered_at)
    if order["route"] == "IV":
        order["cumulative_iv_hours"] += 24 // order["frequency_per_day"]
    core.recompute_order_dot(order)
    hospital = db.hospitals.get(order["_hospital_id"])
    core.touch(order)
    if hospital is not None:
        core.maybe_flag_review_required(order, hospital)
    return success_object(
        {
            "administered_doses": order["administered_doses"],
            "cumulative_iv_hours": order["cumulative_iv_hours"],
            "dot_calendar": order["dot_calendar"],
            "dot_dose": to_number(order["dot_dose"]),
        },
        status=201,
    )


@bp.route("/stewardship/antibiotic-orders/<oid>/complete", methods=["POST"])
def complete_order(oid):
    _, role = auth_context()
    require_role(role, {"AttendingPhysician"})
    order = get_order_or_404(oid)
    patient = db.patient_cases.get(order["patient_case_id"])
    if patient is not None and patient["status"] != "ADMITTED":
        raise err_patient_discharged()
    for itv in db.audit_interventions.values():
        if itv["antibiotic_order_id"] == order["id"] and itv["recommendation_status"] in (
            "RECOMMENDED",
            "APPEALED",
        ):
            raise err_open_intervention_blocks_close()
    if order["therapy_status"] not in CLOSABLE_THERAPY:
        raise err_invalid_request("Order is not in a completable therapy state")
    hospital = db.hospitals.get(order["_hospital_id"])
    order["therapy_status"] = "COMPLETED"
    order["stopped_at"] = core.clock_iso(hospital)
    core.recompute_order_dot(order)
    core.touch(order)
    return success_object(serialize(order))


@bp.route("/stewardship/antibiotic-orders/<oid>/discontinue", methods=["POST"])
def discontinue_order(oid):
    _, role = auth_context()
    require_role(role, {"AttendingPhysician", "IDPharmacist"})
    order = get_order_or_404(oid)
    patient = db.patient_cases.get(order["patient_case_id"])
    if patient is not None and patient["status"] != "ADMITTED":
        raise err_patient_discharged()
    if order["therapy_status"] not in CLOSABLE_THERAPY:
        raise err_invalid_request("Order is not in a discontinuable therapy state")
    hospital = db.hospitals.get(order["_hospital_id"])
    order["therapy_status"] = "DISCONTINUED"
    order["stopped_at"] = core.clock_iso(hospital)
    core.cascade_order_closed(order, hospital, stopped=False)
    core.recompute_order_dot(order)
    core.touch(order)
    return success_object(serialize(order))


# --- Approval requests -----------------------------------------------------------------


@bp.route("/stewardship/approval-requests", methods=["POST"])
def create_approval_request():
    _, role = auth_context()
    require_role(role, {"AttendingPhysician", "IDPharmacist"})
    payload = body_json()
    require_fields(payload, ["antibiotic_order_id", "requester_id", "justification"])
    justification = require_string(payload, "justification", min_len=20)
    order = db.antibiotic_orders.get(payload["antibiotic_order_id"])
    if order is None:
        raise err_not_found("AntibioticOrder not found")
    requester = _require_active_practitioner(payload["requester_id"], "requester")
    if order["approval_status"] != "PENDING":
        raise err_order_approval_not_pending()
    for other in db.approval_requests.values():
        if other["antibiotic_order_id"] == order["id"] and other["status"] in (
            "SUBMITTED",
            "ESCALATED",
        ):
            raise err_approval_already_open()
    hospital = db.hospitals.get(order["_hospital_id"])
    req = {
        "id": new_id(),
        "antibiotic_order_id": order["id"],
        "requester_id": requester["id"],
        "justification": justification,
        "submitted_at": core.clock_iso(hospital),
        "decided_at": None,
        "decided_by_id": None,
        "escalation_reason": None,
        "status": "SUBMITTED",
        "_hospital_id": order["_hospital_id"],
    }
    core.stamp_new(req)
    db.approval_requests[req["id"]] = req
    return success_object(serialize(req), status=201)


@bp.route("/stewardship/approval-requests/<rid>", methods=["GET"])
def get_approval_request(rid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_approval_or_404(rid)))


@bp.route("/stewardship/approval-requests", methods=["GET"])
def list_approval_requests():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(
        db.approval_requests.values(),
        ["antibiotic_order_id", "requester_id", "decided_by_id", "status"],
    )


@bp.route("/stewardship/approval-requests/<rid>/decide", methods=["POST"])
def decide_approval(rid):
    _, role = auth_context()
    require_role(role, {"IDPharmacist", "StewardshipDirector"})
    req = get_approval_or_404(rid)
    payload = body_json()
    require_fields(payload, ["decision", "decider_id"])
    decision = payload["decision"]
    if decision not in DECISIONS:
        raise err_invalid_request("decision must be APPROVED or DENIED")
    _require_active_practitioner(payload["decider_id"], "decider")
    if req["status"] not in ("SUBMITTED", "ESCALATED"):
        raise err_approval_not_pending()
    if req["status"] == "ESCALATED" and role != "StewardshipDirector":
        raise err_escalated_requires_director()
    if payload["decider_id"] == req["requester_id"]:
        raise err_self_approval_forbidden()
    order = db.antibiotic_orders.get(req["antibiotic_order_id"])
    if order is None:
        raise err_not_found("AntibioticOrder not found")
    if order["approval_status"] != "PENDING":
        raise err_order_approval_not_pending()
    hospital = db.hospitals.get(order["_hospital_id"])
    req["status"] = decision
    req["decided_at"] = core.clock_iso(hospital)
    req["decided_by_id"] = payload["decider_id"]
    core.touch(req)
    if decision == "APPROVED":
        order["approval_status"] = "APPROVED"
        if order["therapy_status"] == "AWAITING_APPROVAL":
            order["therapy_status"] = "ACTIVE"
            order["started_at"] = core.clock_iso(hospital)
    else:
        order["approval_status"] = "DENIED"
        if order["therapy_status"] == "AWAITING_APPROVAL":
            order["therapy_status"] = "DISCONTINUED"
            order["stopped_at"] = core.clock_iso(hospital)
            core.cascade_order_closed(order, hospital, stopped=False)
    core.touch(order)
    return success_object(serialize(req))


@bp.route("/stewardship/approval-requests/<rid>/escalate", methods=["POST"])
def escalate_approval(rid):
    _, role = auth_context()
    require_role(role, {"IDPharmacist"})
    req = get_approval_or_404(rid)
    if req["status"] != "SUBMITTED":
        raise err_approval_not_pending()
    payload = body_json()
    reason = payload.get("escalation_reason")
    if not isinstance(reason, str) or len(reason) < 10:
        raise err_invalid_request("escalation_reason must be at least 10 characters")
    req["status"] = "ESCALATED"
    req["escalation_reason"] = reason
    core.touch(req)
    return success_object(serialize(req))


@bp.route("/stewardship/approval-requests/<rid>/withdraw", methods=["POST"])
def withdraw_approval(rid):
    _, role = auth_context()
    require_role(role, {"AttendingPhysician", "IDPharmacist"})
    req = get_approval_or_404(rid)
    payload = body_json()
    require_fields(payload, ["withdrawer_id"])
    _require_active_practitioner(payload["withdrawer_id"], "withdrawer")
    if req["status"] != "SUBMITTED":
        raise err_approval_not_pending()
    if payload["withdrawer_id"] != req["requester_id"]:
        raise err_not_request_owner()
    req["status"] = "WITHDRAWN"
    core.touch(req)
    order = db.antibiotic_orders.get(req["antibiotic_order_id"])
    if order is not None:
        hospital = db.hospitals.get(order["_hospital_id"])
        order["approval_status"] = "NOT_REQUIRED"
        if order["therapy_status"] == "AWAITING_APPROVAL":
            order["therapy_status"] = "DISCONTINUED"
            order["stopped_at"] = core.clock_iso(hospital)
            core.cascade_order_closed(order, hospital, stopped=False)
        core.touch(order)
    return success_object(serialize(req))
