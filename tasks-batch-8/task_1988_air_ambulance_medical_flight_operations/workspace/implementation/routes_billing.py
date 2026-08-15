"""Revenue cycle: insurance authorizations and invoices (PRD §3.8)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import services
from core import (
    ERR_APPEAL_LIMIT, ERR_DUPLICATE_INVOICE, ERR_INVALID_STATE,
    ERR_LEDGER_IMBALANCE, ERR_MEMBERSHIP_NOT_ELIGIBLE, ERR_MISSION_NOT_COMPLETED,
    ERR_PCR_NOT_APPROVED, ERR_TIMELY_FILING_EXPIRED, ERR_VALIDATION,
    db, fail, get_body, list_response, must_exist, now_dt, ok_object,
    parse_date, require_roles, stamp_new, touch, v_enum, v_int, v_num, v_str,
)
from serialize import ser_insurance_authorization, ser_invoice

bp = Blueprint("billing", __name__)

ALL_ROLES = ("OpsAdmin", "Dispatcher", "MedicalDirector", "FlightCrew",
             "BillingSpecialist", "QaReviewer")

AUTH_STATUSES = {"REQUESTED", "APPROVED", "PARTIAL", "DENIED", "APPEALED"}
CLAIM_STATUSES = {
    "DRAFT", "FINALIZED", "SUBMITTED", "PAID", "PARTIALLY_PAID",
    "DENIED", "APPEALED", "RESUBMITTED",
}
MEMBER_DIMS = {
    "UNEVALUATED", "MEMBER_PROTECTED", "NON_MEMBER",
    "WRITEOFF_POSTED", "BALANCE_BILLED",
}
PAYER_OUTCOMES = {"PAID", "PARTIALLY_PAID", "DENIED"}


# ---------------------------------------------------------------------------
# Insurance authorizations
# ---------------------------------------------------------------------------


@bp.route("/air-ambulance/insurance-authorizations", methods=["POST"])
def create_authorization():
    require_roles("BillingSpecialist")
    body = get_body()
    if body.get("mission_id") is not None:
        must_exist(db.missions, body["mission_id"], "Mission")
    rec = stamp_new({
        "mission_id": v_str(body, "mission_id"),
        "payer_name": v_str(body, "payer_name"),
        "policy_number": v_str(body, "policy_number"),
        "approved_amount_cents": None,
        "status": "REQUESTED",
    })
    db.insurance_authorizations[rec["id"]] = rec
    return ok_object(ser_insurance_authorization(rec), 201)


@bp.route("/air-ambulance/insurance-authorizations/<rid>", methods=["GET"])
def get_authorization(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.insurance_authorizations, rid, "InsuranceAuthorization")
    return ok_object(ser_insurance_authorization(rec))


@bp.route("/air-ambulance/insurance-authorizations", methods=["GET"])
def list_authorizations():
    require_roles(*ALL_ROLES)
    return list_response(
        db.insurance_authorizations.values(), ser_insurance_authorization,
        {"mission_id": "mission_id", "status": "status"},
    )


@bp.route("/air-ambulance/insurance-authorizations/<rid>", methods=["PUT"])
def update_authorization(rid):
    require_roles("BillingSpecialist")
    rec = must_exist(db.insurance_authorizations, rid, "InsuranceAuthorization")
    body = get_body()
    target = v_enum(body, "status", AUTH_STATUSES)
    approved_amount = None
    if target == "PARTIAL":
        # shape-level requirement: present and > 0
        approved_amount = v_int(body, "approved_amount_cents", minimum=1)
    elif body.get("approved_amount_cents") is not None:
        approved_amount = v_int(body, "approved_amount_cents")
    current = rec["status"]
    if target in {"APPROVED", "PARTIAL", "DENIED"}:
        if current not in {"REQUESTED", "APPEALED"}:
            fail(ERR_INVALID_STATE, 409,
                 "Authorization status %s cannot transition to %s" % (current, target))
    elif target == "APPEALED":
        if current != "DENIED":
            fail(ERR_INVALID_STATE, 409,
                 "Authorization status %s cannot transition to APPEALED" % current)
    else:  # REQUESTED has no inbound transition
        fail(ERR_INVALID_STATE, 409,
             "Authorization status %s cannot transition to %s" % (current, target))
    rec["status"] = target
    if approved_amount is not None:
        rec["approved_amount_cents"] = approved_amount
    touch(rec)
    return ok_object(ser_insurance_authorization(rec))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


def _compute_lines(mission, miles, provisional):
    aircraft = db.aircraft.get(mission["aircraft_id"])
    aircraft_class = aircraft["aircraft_class"] if aircraft else "ROTOR_WING"
    ground_count = calc.count_ground_legs(mission["id"], provisional)
    return calc.charge_lines(aircraft_class, mission["acuity_tier"], miles, ground_count)


@bp.route("/air-ambulance/invoices", methods=["POST"])
def create_invoice():
    require_roles("BillingSpecialist")
    body = get_body()
    if body.get("mission_id") is not None:
        must_exist(db.missions, body["mission_id"], "Mission")
    mission_id = v_str(body, "mission_id")
    mission = db.missions[mission_id]
    if any(i["mission_id"] == mission_id for i in db.invoices.values()):
        fail(ERR_DUPLICATE_INVOICE, 409, "An invoice already exists for this mission")
    miles = calc.provisional_miles(mission["estimated_loaded_miles"])
    lines = _compute_lines(mission, miles, provisional=True)
    rec = stamp_new({
        "mission_id": mission_id,
        "membership_id": None,
        "estimated_loaded_miles": mission["estimated_loaded_miles"],
        "actual_loaded_miles": None,
        "base_line_cents": lines["base_line_cents"],
        "mileage_line_cents": lines["mileage_line_cents"],
        "fuel_line_cents": lines["fuel_line_cents"],
        "acuity_line_cents": lines["acuity_line_cents"],
        "logistics_line_cents": lines["logistics_line_cents"],
        "ground_line_cents": lines["ground_line_cents"],
        "provisional_total_cents": lines["total_cents"],
        "final_total_cents": None,
        "insurer_paid_cents": 0,
        "contractual_adjustment_cents": 0,
        "member_writeoff_cents": 0,
        "patient_responsibility_cents": None,
        "appeal_count": 0,
        "claim_status": "DRAFT",
        "member_adjustment_status": "UNEVALUATED",
    })
    db.invoices[rec["id"]] = rec
    return ok_object(ser_invoice(rec), 201)


@bp.route("/air-ambulance/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.invoices, rid, "Invoice")
    return ok_object(ser_invoice(rec))


@bp.route("/air-ambulance/invoices", methods=["GET"])
def list_invoices():
    require_roles(*ALL_ROLES)
    return list_response(
        db.invoices.values(), ser_invoice,
        {"mission_id": "mission_id", "membership_id": "membership_id",
         "claim_status": "claim_status",
         "member_adjustment_status": "member_adjustment_status"},
    )


def _mission_of(invoice):
    return db.missions.get(invoice["mission_id"])


@bp.route("/air-ambulance/invoices/<rid>/finalize", methods=["POST"])
def finalize_invoice(rid):
    require_roles("BillingSpecialist")
    rec = must_exist(db.invoices, rid, "Invoice")
    body = get_body()
    actual_miles = v_num(body, "actual_loaded_miles", minimum=0, exclusive_min=True)
    if rec["claim_status"] != "DRAFT":
        fail(ERR_INVALID_STATE, 409,
             "Invoice claim_status %s cannot be finalized" % rec["claim_status"])
    mission = _mission_of(rec)
    if mission is None or mission["status"] != "COMPLETED":
        fail(ERR_MISSION_NOT_COMPLETED, 409, "Owning mission is not COMPLETED")
    lines = _compute_lines(mission, Decimal(str(actual_miles)), provisional=False)
    rec["actual_loaded_miles"] = actual_miles
    rec["base_line_cents"] = lines["base_line_cents"]
    rec["mileage_line_cents"] = lines["mileage_line_cents"]
    rec["fuel_line_cents"] = lines["fuel_line_cents"]
    rec["acuity_line_cents"] = lines["acuity_line_cents"]
    rec["logistics_line_cents"] = lines["logistics_line_cents"]
    rec["ground_line_cents"] = lines["ground_line_cents"]
    rec["final_total_cents"] = lines["total_cents"]
    # Member dimension evaluated for the first and only time at finalize.
    req = db.mission_requests.get(mission["mission_request_id"])
    completed_date = mission["_completed_dt"].date() if mission.get("_completed_dt") else None
    bound = None
    if req is not None and completed_date is not None:
        candidates = [
            m for m in db.memberships.values()
            if m["patient_id"] == req["patient_id"] and m["status"] == "ACTIVE"
        ]
        candidates.sort(key=lambda m: (m["_created_dt"], m["_seq"]))
        for m in candidates:
            eff = parse_date(m["effective_from"])
            if eff is not None and eff <= completed_date:
                bound = m
                break
    if bound is not None:
        rec["member_adjustment_status"] = "MEMBER_PROTECTED"
        rec["membership_id"] = bound["id"]
    else:
        rec["member_adjustment_status"] = "NON_MEMBER"
        rec["membership_id"] = None
    rec["claim_status"] = "FINALIZED"
    services.recompute_patient_responsibility(rec)
    touch(rec)
    return ok_object(ser_invoice(rec))


@bp.route("/air-ambulance/invoices/<rid>/submit", methods=["POST"])
def submit_invoice(rid):
    require_roles("BillingSpecialist")
    rec = must_exist(db.invoices, rid, "Invoice")
    get_body()
    current = rec["claim_status"]
    if current not in {"FINALIZED", "APPEALED"}:
        fail(ERR_INVALID_STATE, 409,
             "Invoice claim_status %s cannot be submitted" % current)
    mission = _mission_of(rec)
    # gates in order: clinical record first, then the filing deadline
    pcr = next((p for p in db.patient_care_reports.values()
                if p["mission_id"] == rec["mission_id"]), None)
    if pcr is None or pcr["status"] != "QA_APPROVED":
        fail(ERR_PCR_NOT_APPROVED, 422,
             "The mission's patient care report is not QA_APPROVED")
    completed_date = mission["_completed_dt"].date() if mission and mission.get("_completed_dt") else None
    if completed_date is None or now_dt().date() > completed_date + timedelta(days=90):
        fail(ERR_TIMELY_FILING_EXPIRED, 422,
             "Submission is later than 90 days after the completion date")
    rec["claim_status"] = "SUBMITTED" if current == "FINALIZED" else "RESUBMITTED"
    touch(rec)
    return ok_object(ser_invoice(rec))


@bp.route("/air-ambulance/invoices/<rid>/payer-response", methods=["POST"])
def payer_response(rid):
    require_roles("BillingSpecialist")
    rec = must_exist(db.invoices, rid, "Invoice")
    body = get_body()
    outcome = v_enum(body, "outcome", PAYER_OUTCOMES)
    paid = v_int(body, "paid_cents", minimum=0)
    adjustment = v_int(body, "contractual_adjustment_cents", minimum=0)
    if rec["claim_status"] not in {"SUBMITTED", "RESUBMITTED"}:
        fail(ERR_INVALID_STATE, 409,
             "Invoice claim_status %s cannot accept a payer response" % rec["claim_status"])
    if paid + adjustment > rec["final_total_cents"]:
        fail(ERR_LEDGER_IMBALANCE, 422,
             "paid_cents + contractual_adjustment_cents exceeds final_total_cents")
    rec["insurer_paid_cents"] = paid
    rec["contractual_adjustment_cents"] = adjustment
    services.recompute_patient_responsibility(rec)
    rec["claim_status"] = outcome
    if outcome in {"PAID", "PARTIALLY_PAID"} and rec["member_adjustment_status"] == "NON_MEMBER":
        rec["member_adjustment_status"] = "BALANCE_BILLED"
    touch(rec)
    return ok_object(ser_invoice(rec))


@bp.route("/air-ambulance/invoices/<rid>/appeal", methods=["POST"])
def appeal_invoice(rid):
    require_roles("BillingSpecialist")
    rec = must_exist(db.invoices, rid, "Invoice")
    get_body()
    if rec["claim_status"] != "DENIED":
        fail(ERR_INVALID_STATE, 409,
             "Invoice claim_status %s cannot be appealed" % rec["claim_status"])
    if rec["appeal_count"] >= 2:
        fail(ERR_APPEAL_LIMIT, 422, "At most two appeals are permitted per invoice")
    rec["appeal_count"] += 1
    # compensation: reverse the denied posting; the write-off is NOT reset
    rec["insurer_paid_cents"] = 0
    rec["contractual_adjustment_cents"] = 0
    services.recompute_patient_responsibility(rec)
    rec["claim_status"] = "APPEALED"
    touch(rec)
    return ok_object(ser_invoice(rec))


@bp.route("/air-ambulance/invoices/<rid>/member-writeoff", methods=["POST"])
def member_writeoff(rid):
    require_roles("BillingSpecialist")
    rec = must_exist(db.invoices, rid, "Invoice")
    get_body()
    # generic state guard (a payer response must have been posted) runs ahead
    # of the membership-eligibility business rule
    if rec["claim_status"] not in {"PAID", "PARTIALLY_PAID", "DENIED"}:
        fail(ERR_INVALID_STATE, 409,
             "Invoice claim_status %s has seen no payer response" % rec["claim_status"])
    if rec["member_adjustment_status"] != "MEMBER_PROTECTED":
        fail(ERR_MEMBERSHIP_NOT_ELIGIBLE, 422,
             "Member dimension is %s" % rec["member_adjustment_status"])
    rec["member_writeoff_cents"] = rec["patient_responsibility_cents"]
    rec["patient_responsibility_cents"] = 0
    rec["member_adjustment_status"] = "WRITEOFF_POSTED"
    touch(rec)
    return ok_object(ser_invoice(rec))
