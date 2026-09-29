"""Repair orders and warranty claims."""

from flask import Blueprint

import calc
import services as svc
from auth import (ADMIN, CARE_OPS, COMPLIANCE, PATIENT, REIMBURSEMENT, REPAIR_TECH,
                  authorize, require_owner)
from bodyspec import Body
from common import field, listed, patient_of_device
from errors import ApiError
from resp import created, ok
from store import bump, db, now, table_rows

bp = Blueprint("repair", __name__)

FAULTS = ("NO_SOUND", "INTERMITTENT", "BATTERY", "MOISTURE", "PHYSICAL_DAMAGE",
          "FIRMWARE_BRICK")
RESOLUTIONS = ("REPAIRED", "UNREPAIRABLE")
CLAIM_KINDS = ("LOSS", "DAMAGE", "DEFECT")
DECISIONS = ("REPLACE", "REPAIR", "DENY")
DENIAL_REASONS = ("WARRANTY_EXPIRED", "CLAIM_CAP_REACHED", "NOT_COVERED_FAULT",
                  "DEVICE_RETIRED")


def open_repair(device, fault_code):
    """Create a RepairOrder in KIT_REQUESTED with all denormalized fields."""
    order = db.device_orders.get(device.get("device_order_id"))
    patient_id = order.get("patient_id") if order else None
    plan = svc.plan_for_device(device)
    trial = svc.trial_for_order(order["id"]) if order else None
    if trial is not None:
        svc.touch_trial(trial)
    pauses = trial is not None and trial.get("status") in ("ACTIVE", "PAUSED")
    return svc.new_row(db.repair_orders, device_id=device["id"], patient_id=patient_id,
                       care_plan_subscription_id=plan["id"] if plan else None,
                       status="KIT_REQUESTED", fault_code=fault_code,
                       sla_days=svc.sla_days_for(plan), received_at=None, closed_at=None,
                       turnaround_days=0, sla_credit_cents=0, pauses_trial=pauses)


def _plan_of_repair(repair):
    return db.care_plan_subscriptions.get(repair.get("care_plan_subscription_id"))


# --------------------------------------------------------------- RepairOrder
@bp.post("/repair-orders")
def create_repair():
    actor = authorize(PATIENT, CARE_OPS)
    body = Body()
    device_id = body.string("device_id", min_len=1)
    fault = body.enum("fault_code", FAULTS)
    body.finish()
    device = svc.ref(db.devices, device_id)
    require_owner(actor, patient_of_device(device["id"]))
    return created(open_repair(device, fault))


@bp.get("/repair-orders")
def list_repairs():
    actor = authorize(PATIENT, REPAIR_TECH, CARE_OPS, REIMBURSEMENT, ADMIN)
    return listed(table_rows(db.repair_orders),
                  {"device_id": field("device_id"), "patient_id": field("patient_id"),
                   "care_plan_subscription_id": field("care_plan_subscription_id"),
                   "status": field("status")},
                  actor=actor)


@bp.get("/repair-orders/<repair_id>")
def get_repair(repair_id):
    actor = authorize(PATIENT, REPAIR_TECH, CARE_OPS, REIMBURSEMENT, ADMIN)
    repair = svc.find(db.repair_orders, repair_id)
    require_owner(actor, repair.get("patient_id"))
    return ok(repair)


@bp.post("/repair-orders/<repair_id>/send-kit")
def send_kit(repair_id):
    authorize(CARE_OPS)
    repair = svc.find(db.repair_orders, repair_id)
    svc.ensure_state(repair, "status", ("KIT_REQUESTED",), "repair_orders")
    device = db.devices.get(repair["device_id"])
    if device is None or device.get("status") != "WITH_PATIENT":
        raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    repair["status"] = "KIT_SENT"
    bump(repair)
    return ok(repair)


@bp.post("/repair-orders/<repair_id>/receive")
def receive_repair(repair_id):
    authorize(REPAIR_TECH)
    repair = svc.find(db.repair_orders, repair_id)
    svc.ensure_state(repair, "status", ("KIT_SENT",), "repair_orders")
    device = db.devices.get(repair["device_id"])
    if device is None or device.get("status") != "WITH_PATIENT":
        raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    trial = None
    order = db.device_orders.get(device.get("device_order_id"))
    if order is not None:
        trial = svc.trial_for_order(order["id"])
        if trial is not None:
            svc.touch_trial(trial)
    if repair.get("pauses_trial") and trial is not None and trial.get("status") == "ACTIVE":
        calc.check_pause_allowed(trial)
        intervals = list(trial.get("pause_intervals") or [])
        intervals.append({"pause_start_utc": now(), "pause_end_utc": None})
        trial["pause_intervals"] = intervals
        trial["status"] = "PAUSED"
        calc.trial_days_used(trial)
        bump(trial)
    repair["status"] = "RECEIVED"
    repair["received_at"] = now()
    repair["sla_days"] = svc.sla_days_for(_plan_of_repair(repair))
    bump(repair)
    device["status"] = "IN_REPAIR"
    bump(device)
    return ok(repair)


@bp.post("/repair-orders/<repair_id>/start")
def start_repair(repair_id):
    authorize(REPAIR_TECH)
    repair = svc.find(db.repair_orders, repair_id)
    svc.ensure_state(repair, "status", ("RECEIVED",), "repair_orders")
    repair["status"] = "IN_REPAIR"
    bump(repair)
    return ok(repair)


@bp.post("/repair-orders/<repair_id>/resolve")
def resolve_repair(repair_id):
    authorize(REPAIR_TECH)
    repair = svc.find(db.repair_orders, repair_id)
    body = Body()
    resolution = body.enum("resolution", RESOLUTIONS)
    body.finish()
    svc.ensure_state(repair, "status", ("IN_REPAIR",), "repair_orders")
    device = db.devices.get(repair["device_id"])
    if resolution == "REPAIRED":
        if repair.get("fault_code") == "PHYSICAL_DAMAGE" and not _deductible_paid(repair):
            raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
        repair["status"] = "REPAIRED"
        bump(repair)
        return ok(repair)
    repair["status"] = "UNREPAIRABLE"
    bump(repair)
    if device is not None:
        device["status"] = "REPLACED"
        bump(device)
    return ok(repair)


def _deductible_paid(repair):
    for claim in db.warranty_claims.values():
        if claim.get("device_id") != repair.get("device_id"):
            continue
        if int(claim.get("deductible_paid_cents") or 0) > 0:
            return True
    return False


@bp.post("/repair-orders/<repair_id>/return-to-patient")
def return_to_patient(repair_id):
    authorize(REPAIR_TECH)
    repair = svc.find(db.repair_orders, repair_id)
    svc.ensure_state(repair, "status", ("REPAIRED",), "repair_orders")
    svc.close_repair(repair, _plan_of_repair(repair))
    repair["status"] = "RETURNED_TO_PATIENT"
    bump(repair)
    device = db.devices.get(repair["device_id"])
    if device is not None:
        device["status"] = "WITH_PATIENT"
        bump(device)
    if repair.get("pauses_trial"):
        svc.resume_trial_after_repair(repair)
    return ok(repair)


@bp.post("/repair-orders/<repair_id>/escalate")
def escalate_repair(repair_id):
    authorize(REPAIR_TECH)
    repair = svc.find(db.repair_orders, repair_id)
    svc.ensure_state(repair, "status", ("UNREPAIRABLE",), "repair_orders")
    device = db.devices.get(repair["device_id"])
    expires = device.get("warranty_expires_at") if device else None
    if repair.get("fault_code") != "FIRMWARE_BRICK" and \
            (expires is None or expires <= now()):
        raise ApiError("ERR_WARRANTY_EXPIRED")
    svc.close_repair(repair, _plan_of_repair(repair))
    repair["status"] = "ESCALATED_TO_WARRANTY"
    bump(repair)
    if repair.get("pauses_trial"):
        svc.resume_trial_after_repair(repair)
    file_claim(device, "DEFECT", repair["id"])
    return ok(repair)


@bp.post("/repair-orders/<repair_id>/cancel")
def cancel_repair(repair_id):
    actor = authorize(PATIENT, CARE_OPS)
    repair = svc.find(db.repair_orders, repair_id)
    require_owner(actor, repair.get("patient_id"))
    Body().string("reason_note", required=False, min_len=1)
    allowed = ("KIT_REQUESTED",) if actor.is_patient else ("KIT_REQUESTED", "KIT_SENT")
    svc.ensure_state(repair, "status", allowed, "repair_orders")
    repair["status"] = "CANCELLED"
    bump(repair)
    return ok(repair)


# ------------------------------------------------------------- WarrantyClaim
def file_claim(device, kind, originating_repair_order_id=None):
    patient_id = patient_of_device(device["id"]) if device else None
    return svc.new_row(db.warranty_claims, device_id=device["id"], patient_id=patient_id,
                       originating_repair_order_id=originating_repair_order_id,
                       claim_kind=kind, status="FILED", device_age_months=0,
                       claim_ordinal=0, deductible_cents=0, deductible_paid_cents=0,
                       replacement_device_id=None, denial_reason=None, triaged_at=None)


@bp.post("/warranty-claims")
def create_claim():
    actor = authorize(PATIENT, CARE_OPS)
    body = Body()
    device_id = body.string("device_id", min_len=1)
    kind = body.enum("claim_kind", CLAIM_KINDS)
    repair_id = body.string("originating_repair_order_id", required=False, min_len=1)
    body.finish()
    device = svc.ref(db.devices, device_id)
    if repair_id is not None:
        svc.ref(db.repair_orders, repair_id)
    require_owner(actor, patient_of_device(device["id"]))
    return created(file_claim(device, kind, repair_id))


@bp.get("/warranty-claims")
def list_claims():
    actor = authorize(PATIENT, REPAIR_TECH, CARE_OPS, COMPLIANCE, ADMIN)
    return listed(table_rows(db.warranty_claims),
                  {"device_id": field("device_id"), "patient_id": field("patient_id"),
                   "originating_repair_order_id": field("originating_repair_order_id"),
                   "replacement_device_id": field("replacement_device_id"),
                   "status": field("status"), "claim_kind": field("claim_kind")},
                  actor=actor)


@bp.get("/warranty-claims/<claim_id>")
def get_claim(claim_id):
    actor = authorize(PATIENT, REPAIR_TECH, CARE_OPS, COMPLIANCE, ADMIN)
    claim = svc.find(db.warranty_claims, claim_id)
    require_owner(actor, claim.get("patient_id"))
    return ok(claim)


@bp.post("/warranty-claims/<claim_id>/triage")
def triage_claim(claim_id):
    authorize(REPAIR_TECH)
    claim = svc.find(db.warranty_claims, claim_id)
    svc.ensure_state(claim, "status", ("FILED",), "warranty_claims")
    device = db.devices.get(claim["device_id"])
    if device is None or device.get("status") == "RETIRED":
        raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    claim["claim_ordinal"] = _claim_ordinal(claim)
    age, deductible = calc.warranty_deductible(claim, device)
    claim["device_age_months"] = age
    claim["deductible_cents"] = deductible
    claim["triaged_at"] = now()
    claim["status"] = "TRIAGED"
    bump(claim)
    device["age_months_at_last_claim"] = age
    bump(device)
    return ok(claim)


def _claim_ordinal(claim):
    prior = 0
    for other in db.warranty_claims.values():
        if other["id"] == claim["id"] or other.get("device_id") != claim.get("device_id"):
            continue
        if other.get("status") in ("APPROVED_REPLACEMENT", "APPROVED_REPAIR", "FULFILLED"):
            prior += 1
    return prior + 1


@bp.post("/warranty-claims/<claim_id>/decide")
def decide_claim(claim_id):
    authorize(COMPLIANCE)
    claim = svc.find(db.warranty_claims, claim_id)
    body = Body()
    decision = body.enum("decision", DECISIONS)
    denial_reason = body.enum("denial_reason", DENIAL_REASONS, required=False)
    body.finish()
    svc.ensure_state(claim, "status", ("TRIAGED",), "warranty_claims")
    device = db.devices.get(claim["device_id"])
    kind = claim["claim_kind"]
    expires = device.get("warranty_expires_at") if device else None
    warranty_live = expires is not None and expires > now()

    if decision == "DENY":
        if denial_reason is None:
            raise ApiError("ERR_VALIDATION", "denial_reason is required on a denial")
        claim["denial_reason"] = denial_reason
        claim["status"] = "DENIED"
        bump(claim)
        return ok(claim)

    if decision == "REPLACE":
        if kind in ("LOSS", "DAMAGE"):
            policy = _policy_for_claim(claim)
            cap = int((policy or {}).get("max_loss_damage_claims") or 0)
            if int(device.get("loss_damage_claims_approved") or 0) >= cap:
                raise ApiError("ERR_CLAIM_CAP_REACHED")
        if not warranty_live and kind != "LOSS":
            raise ApiError("ERR_WARRANTY_EXPIRED")
        replacement = svc.new_row(
            db.devices, serial_number="RPL-%s" % db.next_seq(),
            device_order_id=device.get("device_order_id"), model=device.get("model"),
            firmware_version="4.0.0", status="IN_STOCK", shipped_at=None,
            warranty_expires_at=None, age_months_at_last_claim=0,
            loss_damage_claims_approved=0, replaced_by_device_id=None)
        device["replaced_by_device_id"] = replacement["id"]
        device["status"] = "LOST" if kind == "LOSS" else "REPLACED"
        bump(device)
        claim["replacement_device_id"] = replacement["id"]
        claim["status"] = "APPROVED_REPLACEMENT"
        bump(claim)
        svc.cancel_rollouts_for_device(device["id"])
        return ok(claim)

    # decision == REPAIR
    if kind not in ("DEFECT", "DAMAGE"):
        raise ApiError("ERR_INVALID_STATE", "claim_kind is not covered by a repair decision")
    if not warranty_live:
        raise ApiError("ERR_WARRANTY_EXPIRED")
    fault = "PHYSICAL_DAMAGE" if kind == "DAMAGE" else None
    origin = db.repair_orders.get(claim.get("originating_repair_order_id"))
    if fault is None:
        fault = (origin or {}).get("fault_code") or "INTERMITTENT"
    repair = open_repair(device, fault)
    claim["status"] = "APPROVED_REPAIR"
    claim["_created_repair_order_id"] = repair["id"]
    bump(claim)
    return ok(claim)


def _policy_for_claim(claim):
    patient = db.patients.get(claim.get("patient_id"))
    if patient is None:
        return None
    return svc.policy_of(patient)


@bp.post("/warranty-claims/<claim_id>/pay-deductible")
def pay_deductible(claim_id):
    actor = authorize(PATIENT)
    claim = svc.find(db.warranty_claims, claim_id)
    require_owner(actor, claim.get("patient_id"))
    body = Body()
    amount = body.integer("amount_cents", minimum=1)
    body.finish()
    if claim["status"] in ("FULFILLED", "DENIED", "WITHDRAWN"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    claim["deductible_paid_cents"] = int(claim.get("deductible_paid_cents") or 0) + amount
    bump(claim)
    return ok(claim)


@bp.post("/warranty-claims/<claim_id>/fulfill")
def fulfill_claim(claim_id):
    authorize(CARE_OPS)
    claim = svc.find(db.warranty_claims, claim_id)
    svc.ensure_state(claim, "status", ("APPROVED_REPLACEMENT", "APPROVED_REPAIR"),
                     "warranty_claims")
    if int(claim.get("deductible_paid_cents") or 0) != int(claim.get("deductible_cents") or 0):
        raise ApiError("ERR_DEDUCTIBLE_UNPAID")
    device = db.devices.get(claim["device_id"])
    if claim["status"] == "APPROVED_REPAIR":
        repair = db.repair_orders.get(claim.get("_created_repair_order_id"))
        if repair is None or repair.get("status") != "RETURNED_TO_PATIENT":
            raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
        claim["status"] = "FULFILLED"
        bump(claim)
        if device is not None:
            svc.recompute_loss_damage_claims(device)
            bump(device)
        return ok(claim)
    claim["status"] = "FULFILLED"
    bump(claim)
    replacement = db.devices.get(claim.get("replacement_device_id"))
    if replacement is not None:
        replacement["status"] = "WITH_PATIENT"
        replacement["shipped_at"] = now()
        replacement["warranty_expires_at"] = (device or {}).get("warranty_expires_at")
        bump(replacement)
    if device is not None:
        svc.recompute_loss_damage_claims(device)
        bump(device)
    return ok(claim)


@bp.post("/warranty-claims/<claim_id>/withdraw")
def withdraw_claim(claim_id):
    actor = authorize(PATIENT)
    claim = svc.find(db.warranty_claims, claim_id)
    require_owner(actor, claim.get("patient_id"))
    svc.ensure_state(claim, "status", ("FILED",), "warranty_claims")
    claim["status"] = "WITHDRAWN"
    bump(claim)
    return ok(claim)
