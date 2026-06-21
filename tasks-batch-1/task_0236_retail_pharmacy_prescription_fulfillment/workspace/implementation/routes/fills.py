"""Fill fulfillment workflow + claim adjudication (PRD §3.4, §3.6, §3.8-§3.10)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from common import (
    get_body, require_field, opt_field, as_string, as_int,
    stamp_create, touch, get_pagination, paginate,
)
from clock import parse_iso, format_iso
from errors import err
from middleware import get_actor, require_roles
from response import object_response, array_response
from services import calc, domain

bp = Blueprint("fills", __name__)

ALL_ROLES = ["PharmacyAdmin", "Pharmacist", "Technician", "Cashier"]
CONTROLLED = {"CII", "CIII", "CIV", "CV"}
CANCELLABLE_STATES = {"ENTERED", "DUR_REVIEW", "ADJUDICATING", "PA_REFERRAL",
                      "READY_FILL", "WILL_CALL"}


def serialize_fill(f):
    return {
        "id": f["id"], "created_at": f["created_at"], "updated_at": f["updated_at"],
        "version": f["version"], "prescription_id": f["prescription_id"],
        "fill_sequence": f["fill_sequence"], "quantity_dispensed": f["quantity_dispensed"],
        "days_supply": f["days_supply"], "gross_amount_cents": f["gross_amount_cents"],
        "provisional_copay_cents": f["provisional_copay_cents"],
        "final_copay_cents": f["final_copay_cents"], "plan_paid_cents": f["plan_paid_cents"],
        "dur_severity": f["dur_severity"], "dur_override_by": f["dur_override_by"],
        "claim_status": f["claim_status"], "pickup_deadline_utc": f["pickup_deadline_utc"],
        "created_by": f.get("created_by"), "status": f["status"],
    }


def _get_fill_or_404(rid):
    fill = db.fills.get(rid)
    if fill is None:
        raise err("ERR_NOT_FOUND", "Fill not found")
    return fill


# ===========================================================================
# Create / list / get
# ===========================================================================


@bp.route("/fills", methods=["POST"])
def create_fill():
    uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin", "Technician"])
    body = get_body()
    prescription_id = as_string(require_field(body, "prescription_id"), "prescription_id")
    with db.LOCK:
        rx = db.prescriptions.get(prescription_id)
        if rx is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "prescription_id does not reference a prescription")
        # Prescription must be ACTIVE.
        if rx["status"] != "ACTIVE":
            raise err("ERR_PRESCRIPTION_NOT_ACTIVE", "Prescription is not ACTIVE")
        drug = db.drug_products[rx["drug_id"]]
        prescriber = db.prescribers[rx["prescriber_id"]]
        is_controlled = drug["dea_schedule"] in CONTROLLED
        # Re-check prescriber DEA standing for controlled drugs.
        if is_controlled:
            if not prescriber.get("dea_number") or not prescriber.get("dea_active"):
                raise err("ERR_PRESCRIBER_DEA_INVALID",
                          "Controlled fill requires an active DEA registration")
        # Determine fill_sequence (count of existing fills of this rx + 1).
        existing = [f for f in db.fills.values() if f["prescription_id"] == prescription_id]
        seq = len(existing) + 1
        # Refill (sequence > 1) requires refills_remaining > 0 at creation.
        if seq > 1:
            domain.recompute_refills_remaining(rx)
            if rx["refills_remaining"] <= 0:
                raise err("ERR_NO_REFILLS_REMAINING", "No refills remaining")
        gross = drug["unit_price_cents"] * rx["quantity_per_fill"]
        fill = {
            "prescription_id": prescription_id, "fill_sequence": seq,
            "quantity_dispensed": rx["quantity_per_fill"], "days_supply": rx["days_supply"],
            "gross_amount_cents": gross, "provisional_copay_cents": None,
            "final_copay_cents": None, "plan_paid_cents": None,
            "dur_severity": "NONE", "dur_override_by": None,
            "claim_status": "UNCLAIMED", "pickup_deadline_utc": None,
            "dispensed_utc": None, "created_by": uid, "status": "ENTERED",
        }
        stamp_create(fill)
        db.fills[fill["id"]] = fill
        domain.recompute_refills_remaining(rx)
    return object_response(serialize_fill(fill), 201)


@bp.route("/fills", methods=["GET"])
def list_fills():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    prescription_id = request.args.get("prescription_id")
    items = list(db.fills.values())
    if prescription_id is not None:
        items = [f for f in items if f["prescription_id"] == prescription_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_fill(f) for f in page], limit, offset, total)


@bp.route("/fills/<rid>", methods=["GET"])
def get_fill(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    fill = _get_fill_or_404(rid)
    return object_response(serialize_fill(fill), 200)


# ===========================================================================
# run-dur (ENTERED -> DUR_REVIEW or auto -> ADJUDICATING)
# ===========================================================================


@bp.route("/fills/<rid>/run-dur", methods=["POST"])
def run_dur(rid):
    _uid, role = get_actor()
    require_roles(role, ["Technician", "Pharmacist"])
    with db.LOCK:
        fill = _get_fill_or_404(rid)
        if fill["status"] != "ENTERED":
            raise err("ERR_FILL_NOT_ENTERED", "Fill is not in ENTERED")
        rx = db.prescriptions[fill["prescription_id"]]
        if rx["status"] != "ACTIVE":
            raise err("ERR_PRESCRIPTION_NOT_ACTIVE", "Prescription is not ACTIVE")
        drug = db.drug_products[rx["drug_id"]]
        if drug["status"] != "ACTIVE":
            raise err("ERR_DRUG_DISCONTINUED", "Drug product is discontinued")
        severity = domain.run_dur_screen(fill)
        if severity == "NONE":
            # Auto-advance straight through DUR_REVIEW to ADJUDICATING.
            fill["status"] = "ADJUDICATING"
        else:
            fill["status"] = "DUR_REVIEW"
        touch(fill)
    return object_response(serialize_fill(fill), 200)


# ===========================================================================
# override-dur (DUR_REVIEW -> ADJUDICATING)
# ===========================================================================


@bp.route("/fills/<rid>/override-dur", methods=["POST"])
def override_dur(rid):
    uid, role = get_actor()
    require_roles(role, ["Pharmacist"])
    body = get_body()
    override_reason = opt_field(body, "override_reason", None)
    with db.LOCK:
        fill = _get_fill_or_404(rid)
        if fill["status"] != "DUR_REVIEW":
            raise err("ERR_FILL_NOT_IN_DUR_REVIEW", "Fill is not in DUR_REVIEW")
        rx = db.prescriptions[fill["prescription_id"]]
        drug = db.drug_products[rx["drug_id"]]
        blocking = domain.unoverridden_blocking_alerts(fill["id"])
        # SEVERE present -> override_reason mandatory.
        has_severe = any(a["severity"] == "SEVERE" for a in blocking)
        if has_severe and (override_reason is None or
                           (isinstance(override_reason, str) and override_reason.strip() == "")):
            raise err("ERR_OVERRIDE_REASON_REQUIRED",
                      "override_reason is required to override a SEVERE alert")
        # Segregation of duties for CII drugs.
        if drug["dea_schedule"] == "CII" and uid == fill.get("created_by"):
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "Overriding pharmacist must differ from the creating technician")
        # On success: every MODERATE/SEVERE alert overridden; record dur_override_by.
        for a in domain.alerts_for_fill(fill["id"]):
            if a["severity"] in ("MODERATE", "SEVERE") and not a["overridden"]:
                a["overridden"] = True
                if override_reason is not None:
                    a["override_reason"] = override_reason
                touch(a)
        fill["dur_override_by"] = uid
        fill["status"] = "ADJUDICATING"
        touch(fill)
    return object_response(serialize_fill(fill), 200)


# ===========================================================================
# submit-claim (ADJUDICATING -> READY_FILL or PA_REFERRAL)
# ===========================================================================


@bp.route("/fills/<rid>/submit-claim", methods=["POST"])
def submit_claim(rid):
    _uid, role = get_actor()
    require_roles(role, ["Technician", "Pharmacist"])
    body = get_body()
    expected_version = require_field(body, "expected_prescription_version")
    expected_version = as_int(expected_version, "expected_prescription_version")
    with db.LOCK:
        fill = _get_fill_or_404(rid)
        rx = db.prescriptions[fill["prescription_id"]]
        drug = db.drug_products[rx["drug_id"]]
        patient = db.patients[rx["patient_id"]]
        is_controlled = drug["dea_schedule"] in CONTROLLED

        # State: fill must be ADJUDICATING, claim UNCLAIMED.
        if fill["status"] != "ADJUDICATING":
            raise err("ERR_FILL_NOT_ADJUDICATING", "Fill is not in ADJUDICATING")
        if fill["claim_status"] != "UNCLAIMED":
            raise err("ERR_CLAIM_ALREADY_OPEN", "Claim is already open")

        # OCC version guard (priority 5).
        if expected_version != rx["version"]:
            raise err("ERR_STALE_PRESCRIPTION_VERSION",
                      "expected_prescription_version is stale")

        # Un-overridden MODERATE/SEVERE DUR alerts block submission.
        if domain.unoverridden_blocking_alerts(fill["id"]):
            raise err("ERR_DUR_NOT_OVERRIDDEN",
                      "Un-overridden MODERATE/SEVERE DUR alerts present")

        plan = db.insurance_plans.get(patient["plan_id"]) if patient["plan_id"] else None

        # Insured patient: drug must be on the plan formulary (or PA-flagged).
        formulary_entry = None
        if plan is not None:
            formulary_entry = _find_formulary(plan["id"], drug["id"])
            drug_pa = drug["pa_required"]
            entry_pa = formulary_entry["requires_pa"] if formulary_entry else False
            controlled_pa = is_controlled and drug["dea_schedule"] == "CII" \
                and plan["requires_pa_for_controlled"]
            if formulary_entry is None and not (drug_pa or controlled_pa):
                raise err("ERR_DRUG_NOT_ON_FORMULARY",
                          "Drug is not on the patient's plan formulary")

        # Controlled drug: patient.controlled_status must be ELIGIBLE.
        if is_controlled and patient["controlled_status"] != "ELIGIBLE":
            raise err("ERR_PATIENT_CONTROLLED_LOCKED",
                      "Patient is locked for controlled dispensing")

        # Refill-too-soon edit.
        if rx["last_dispensed_utc"] is not None:
            threshold = plan["refill_too_soon_threshold_pct"] if plan else calc.DEFAULT_THRESHOLD_PCT
            required = calc.refill_required_days(rx["days_supply"], threshold)
            elapsed = calc.floor_days_between(rx["last_dispensed_utc"], db.current_utc())
            if elapsed < required:
                raise err("ERR_REFILL_TOO_SOON", "Refill submitted too soon")

        # PA-required determination.
        pa_required = False
        reason = None
        if drug["pa_required"]:
            pa_required = True
            reason = "DRUG_PA_REQUIRED"
        elif formulary_entry is not None and formulary_entry["requires_pa"]:
            pa_required = True
            reason = "PLAN_PA_REQUIRED"
        elif drug["dea_schedule"] == "CII" and plan is not None and plan["requires_pa_for_controlled"]:
            pa_required = True
            reason = "CONTROLLED_PA_REQUIRED"

        # An already-APPROVED PA for this fill suppresses re-referral.
        has_approved_pa = any(
            pa["fill_id"] == fill["id"] and pa["status"] == "APPROVED"
            for pa in db.prior_auth_requests.values()
        )

        if pa_required and not has_approved_pa:
            # Referral branch: ADJUDICATING -> PA_REFERRAL.
            cur = parse_iso(db.current_utc())
            pa = {
                "fill_id": fill["id"], "prescription_id": rx["id"], "reason": reason,
                "submitted_utc": db.current_utc(),
                "decided_utc": None,
                "expires_utc": format_iso(cur + timedelta(days=30)),
                "status": "PENDING",
            }
            stamp_create(pa)
            db.prior_auth_requests[pa["id"]] = pa
            fill["claim_status"] = "PA_PENDING"
            fill["status"] = "PA_REFERRAL"
            touch(fill)
            touch(rx)  # increment Prescription.version by 1
            return object_response(serialize_fill(fill), 200)

        # Pay branch: compute copays, claim PAID, fill READY_FILL.
        _compute_copays(fill, rx, drug, patient, plan, formulary_entry)
        fill["claim_status"] = "PAID"
        fill["status"] = "READY_FILL"
        touch(fill)
        touch(rx)  # increment Prescription.version by 1
    return object_response(serialize_fill(fill), 200)


def _find_formulary(plan_id, drug_id):
    for f in db.formulary_entries.values():
        if f["plan_id"] == plan_id and f["drug_id"] == drug_id:
            return f
    return None


def _compute_copays(fill, rx, drug, patient, plan, formulary_entry):
    if plan is None:
        # Cash patient: both copays == gross, plan_paid == 0.
        fill["provisional_copay_cents"] = fill["gross_amount_cents"]
        fill["final_copay_cents"] = fill["gross_amount_cents"]
        fill["plan_paid_cents"] = 0
        return
    allowed_per_unit = formulary_entry["allowed_amount_cents"]
    qty = fill["quantity_dispensed"]
    disp_fee = plan["dispensing_fee_cents"]
    pct = plan["copay_pct"]
    cmin = plan["copay_min_cents"]
    cmax = plan["copay_max_cents"]
    # Provisional: per-fill cap.
    fill["provisional_copay_cents"] = calc.provisional_copay(
        allowed_per_unit, qty, disp_fee, pct, cmin, cmax
    )
    # Final: chronological cumulative cap.
    prior_oop = _prior_out_of_pocket(patient, plan, fill)
    fc, plan_paid = calc.final_copay(
        allowed_per_unit, qty, disp_fee, pct, cmin, cmax, prior_oop
    )
    fill["final_copay_cents"] = fc
    fill["plan_paid_cents"] = plan_paid


def _prior_out_of_pocket(patient, plan, current_fill):
    """Sum final_copay_cents over the patient's earlier fills on the same plan,
    status != CANCELLED, excluding REVERSED claims, in created_at ASC order.
    """
    rows = []
    for f in db.fills.values():
        if f["id"] == current_fill["id"]:
            continue
        rx = db.prescriptions.get(f["prescription_id"])
        if rx is None or rx["patient_id"] != patient["id"]:
            continue
        # Same plan: patient's plan (the patient->plan binding).
        if patient["plan_id"] != plan["id"]:
            continue
        if f["status"] == "CANCELLED":
            continue
        if f["claim_status"] == "REVERSED":
            continue
        if f["final_copay_cents"] is None:
            continue
        rows.append(f)
    rows.sort(key=lambda x: (x["created_at"], x["id"]))
    return sum(f["final_copay_cents"] for f in rows)


# ===========================================================================
# reverse-claim (PAID -> REVERSED)
# ===========================================================================


@bp.route("/fills/<rid>/reverse-claim", methods=["POST"])
def reverse_claim(rid):
    _uid, role = get_actor()
    require_roles(role, ["Pharmacist"])
    with db.LOCK:
        fill = _get_fill_or_404(rid)
        if fill["claim_status"] != "PAID":
            raise err("ERR_CLAIM_NOT_PAID", "Claim is not PAID")
        if fill["status"] == "DISPENSED":
            raise err("ERR_FILL_ALREADY_DISPENSED", "Fill already dispensed")
        _do_reverse(fill)
        touch(fill)
    return object_response(serialize_fill(fill), 200)


def _do_reverse(fill):
    """Reverse a paid claim: claim_status REVERSED, plan_paid 0, refund payment.

    gross_amount_cents untouched; final_copay reverts to 0 (money conserved).
    """
    fill["claim_status"] = "REVERSED"
    fill["plan_paid_cents"] = 0
    fill["final_copay_cents"] = 0
    for pr in db.payment_records.values():
        if pr["fill_id"] == fill["id"] and not pr["refunded"]:
            pr["refunded"] = True
            touch(pr)


# ===========================================================================
# stage-will-call (READY_FILL -> WILL_CALL)
# ===========================================================================


@bp.route("/fills/<rid>/stage-will-call", methods=["POST"])
def stage_will_call(rid):
    _uid, role = get_actor()
    require_roles(role, ["Technician", "Pharmacist"])
    with db.LOCK:
        fill = _get_fill_or_404(rid)
        if fill["status"] != "READY_FILL":
            raise err("ERR_FILL_NOT_READY", "Fill is not in READY_FILL")
        if fill["claim_status"] != "PAID":
            raise err("ERR_CLAIM_NOT_PAID", "Claim is not PAID")
        cur = parse_iso(db.current_utc())
        fill["status"] = "WILL_CALL"
        fill["pickup_deadline_utc"] = format_iso(cur + timedelta(days=10))
        touch(fill)
    return object_response(serialize_fill(fill), 200)


# ===========================================================================
# dispense (WILL_CALL -> DISPENSED)
# ===========================================================================


@bp.route("/fills/<rid>/dispense", methods=["POST"])
def dispense(rid):
    uid, role = get_actor()
    require_roles(role, ["Pharmacist"])
    with db.LOCK:
        fill = _get_fill_or_404(rid)
        if fill["status"] != "WILL_CALL":
            raise err("ERR_FILL_NOT_WILL_CALL", "Fill is not in WILL_CALL")
        cur = parse_iso(db.current_utc())
        if cur > parse_iso(fill["pickup_deadline_utc"]):
            raise err("ERR_WILL_CALL_EXPIRED", "Will-call window expired")
        # Payment record matching final_copay_cents must exist.
        payment = None
        for pr in db.payment_records.values():
            if pr["fill_id"] == fill["id"] and not pr["refunded"] \
                    and pr["amount_cents"] == fill["final_copay_cents"]:
                payment = pr
                break
        if payment is None:
            raise err("ERR_PAYMENT_REQUIRED", "A matching payment record is required")
        rx = db.prescriptions[fill["prescription_id"]]
        drug = db.drug_products[rx["drug_id"]]
        patient = db.patients[rx["patient_id"]]
        # Segregation of duties for CII drugs.
        if drug["dea_schedule"] == "CII" and uid == fill.get("created_by"):
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "Dispensing pharmacist must differ from the creating technician")
        # Side effects: set DISPENSED first so committed PDMP count includes it.
        fill["status"] = "DISPENSED"
        fill["dispensed_utc"] = db.current_utc()  # logical anchor for PDMP lookback
        touch(fill)
        rx["last_dispensed_utc"] = db.current_utc()
        touch(rx)
        domain.recompute_refills_remaining(rx)
        # Bubble-up auto-EXHAUSTED.
        if rx["refills_remaining"] == 0 and rx["status"] == "ACTIVE":
            rx["status"] = "EXHAUSTED"
            touch(rx)
        # Controlled drug: regenerate PDMP report + posture cascade.
        if drug["dea_schedule"] in CONTROLLED:
            domain.generate_pdmp_report(patient, fill["id"], variant="committed")
    return object_response(serialize_fill(fill), 200)


# ===========================================================================
# cancel (non-terminal -> CANCELLED)
# ===========================================================================


@bp.route("/fills/<rid>/cancel", methods=["POST"])
def cancel_fill(rid):
    _uid, role = get_actor()
    require_roles(role, ["Pharmacist", "Technician"])
    with db.LOCK:
        fill = _get_fill_or_404(rid)
        if fill["status"] not in CANCELLABLE_STATES:
            raise err("ERR_FILL_NOT_CANCELLABLE", "Fill is in a terminal state")
        if fill["claim_status"] == "PAID":
            raise err("ERR_CLAIM_PAID_REVERSE_FIRST", "Reverse the paid claim first")
        fill["status"] = "CANCELLED"
        if fill["claim_status"] in ("SUBMITTED", "PA_PENDING"):
            fill["claim_status"] = "REVERSED"
        touch(fill)
        rx = db.prescriptions[fill["prescription_id"]]
        domain.recompute_refills_remaining(rx)
    return object_response(serialize_fill(fill), 200)


# ===========================================================================
# expire-will-call (WILL_CALL -> RETURNED_TO_STOCK)
# ===========================================================================


@bp.route("/fills/<rid>/expire-will-call", methods=["POST"])
def expire_will_call(rid):
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin"])
    with db.LOCK:
        fill = _get_fill_or_404(rid)
        cur = parse_iso(db.current_utc())
        if fill["status"] == "WILL_CALL" and \
                fill["pickup_deadline_utc"] is not None and \
                cur > parse_iso(fill["pickup_deadline_utc"]):
            fill["status"] = "RETURNED_TO_STOCK"
            fill["claim_status"] = "REVERSED"
            fill["plan_paid_cents"] = 0
            fill["final_copay_cents"] = 0
            for pr in db.payment_records.values():
                if pr["fill_id"] == fill["id"] and not pr["refunded"]:
                    pr["refunded"] = True
                    touch(pr)
            touch(fill)
            rx = db.prescriptions[fill["prescription_id"]]
            domain.recompute_refills_remaining(rx)
    return object_response(serialize_fill(fill), 200)
