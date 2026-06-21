"""Claim lifecycle: draft, get, list, adjudicate, payments, deny, void,
submit, carrier-ack. Parallel financial + submission dimensions."""
from flask import Blueprint, request

import clock
import errors
import helpers
import response
import serialize
from db import db, new_id, stamp_create, touch
from middleware import require_roles
from services import benefit, claim_calc, patient_balance

bp = Blueprint("claims", __name__)

ACK_OUTCOMES = {"ACCEPTED", "REJECTED"}


def _medical_eligible(encounter, patient):
    """A MEDICAL route requires medical_insurance_on_file and chief code 'H...'."""
    if not patient.get("medical_insurance_on_file"):
        return False
    code = encounter.get("chief_complaint_code") or ""
    return code.startswith("H")


@bp.post("/claims")
@require_roles("Biller")
def create_claim():
    body = helpers.get_json_body()
    encounter_id = helpers.require_str(body, "encounter_id")

    # body FK existence (priority 4)
    encounter = db.encounters.get(encounter_id)
    if encounter is None:
        raise errors.reference_not_found("encounter_id references no Encounter")

    eligibility_id = helpers.require_str(body, "eligibility_id", required=False)
    elig = None
    if eligibility_id is not None:
        elig = db.eligibilities.get(eligibility_id)
        if elig is None:
            raise errors.reference_not_found(
                "eligibility_id references no Eligibility")

    # state legality (priority 6): encounter must be FINALIZED
    if encounter["status"] != "FINALIZED":
        raise errors.invalid_state("Encounter must be FINALIZED to draft a claim")

    billing_route = "ROUTINE" if encounter["encounter_type"] == "ROUTINE_VISION" else "MEDICAL"

    patient = db.patients.get(encounter["patient_id"])

    # medical billing eligibility (priority 12) for MEDICAL route
    if billing_route == "MEDICAL":
        if not _medical_eligible(encounter, patient):
            raise errors.medical_billing_ineligible(
                "Medical billing requires medical_insurance_on_file and an 'H' code")

    record = {
        "id": new_id(),
        "encounter_id": encounter_id,
        "eligibility_id": eligibility_id,
        "patient_id": encounter["patient_id"],
        "billing_route": billing_route,
        "billed_amount_cents": 0,
        "plan_paid_cents": 0,
        "patient_responsibility_cents": 0,
        "settled_cents": 0,
        "claim_status": "DRAFT",
        "submission_status": "UNSUBMITTED",
    }
    stamp_create(record)
    db.claims[record["id"]] = record
    return response.object_response(serialize.claim(record), 201)


@bp.get("/claims/<claim_id>")
@require_roles("FrontDesk", "Biller")
def get_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")
    return response.object_response(serialize.claim(record), 200)


@bp.get("/claims")
@require_roles("FrontDesk", "Biller")
def list_claims():
    limit, offset = helpers.parse_pagination()
    encounter_id = request.args.get("encounter_id")
    eligibility_id = request.args.get("eligibility_id")
    claim_status = request.args.get("claim_status")
    records = list(db.claims.values())
    if encounter_id is not None:
        records = [r for r in records if r["encounter_id"] == encounter_id]
    if eligibility_id is not None:
        records = [r for r in records if r.get("eligibility_id") == eligibility_id]
    if claim_status is not None:
        records = [r for r in records if r["claim_status"] == claim_status]
    page, total = helpers.paginate(records, limit, offset)
    return response.array_response(
        [serialize.claim(r) for r in page], limit, offset, total, 200)


@bp.post("/claims/<claim_id>/adjudicate")
@require_roles("Biller")
def adjudicate_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")

    # state legality (priority 6)
    if record["claim_status"] != "DRAFT":
        raise errors.invalid_state("Claim must be DRAFT to adjudicate")

    encounter = db.encounters.get(record["encounter_id"])
    patient = db.patients.get(record["patient_id"])

    if record["billing_route"] == "MEDICAL":
        # re-check medical eligibility at adjudication
        if not _medical_eligible(encounter, patient):
            raise errors.medical_billing_ineligible(
                "Medical billing requires medical_insurance_on_file and an 'H' code")
        billed, plan_paid, patient_resp = claim_calc.adjudicate_medical(
            encounter["exam_fee_cents"], encounter["refraction_fee_cents"])
    else:
        # ROUTINE: eligibility must be in-period and exam_benefit_available
        elig = db.eligibilities.get(record["eligibility_id"]) if record.get("eligibility_id") else None
        if elig is None:
            raise errors.benefit_period_closed("Routine claim has no eligibility")
        if not benefit.is_in_period(elig, clock.current_date()):
            raise errors.benefit_period_closed("Eligibility is not in-period")
        if not elig["exam_benefit_available"]:
            raise errors.benefit_period_closed("Exam benefit is no longer available")
        billed, plan_paid, patient_resp = claim_calc.adjudicate_routine(
            encounter["exam_fee_cents"], encounter["refraction_fee_cents"],
            elig["exam_copay_cents"])

    record["billed_amount_cents"] = billed
    record["plan_paid_cents"] = plan_paid
    record["patient_responsibility_cents"] = patient_resp
    record["claim_status"] = "ADJUDICATED"
    touch(record)

    # ROUTINE: consume exam benefit
    if record["billing_route"] == "ROUTINE":
        elig = db.eligibilities.get(record["eligibility_id"])
        elig["exam_benefit_available"] = False
        exam_pool = benefit.pool_of_type(elig["id"], "EXAM")
        if exam_pool is not None:
            exam_pool["consumed_cents"] = exam_pool["allotted_cents"]
            benefit.recompute_pool_remaining(exam_pool)
            touch(exam_pool)
        touch(elig)

    patient_balance.recompute_for_patient(record["patient_id"])
    return response.object_response(serialize.claim(record), 200)


@bp.post("/claims/<claim_id>/payments")
@require_roles("Biller")
def apply_payment(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")

    body = helpers.get_json_body()
    amount = helpers.require_int(body, "amount_cents")

    # state legality (priority 6): must be ADJUDICATED or SETTLED_PARTIAL
    if record["claim_status"] not in ("ADJUDICATED", "SETTLED_PARTIAL"):
        raise errors.invalid_state(
            "Claim must be ADJUDICATED or SETTLED_PARTIAL to take a payment")

    remaining = record["patient_responsibility_cents"] - record["settled_cents"]
    # payment amount must be > 0 and <= remaining (priority 15)
    if amount <= 0 or amount > remaining:
        raise errors.payment_exceeds_balance(
            "Payment must be > 0 and not exceed the remaining balance")

    record["settled_cents"] += amount
    if record["settled_cents"] >= record["patient_responsibility_cents"]:
        record["settled_cents"] = record["patient_responsibility_cents"]
        record["claim_status"] = "SETTLED"
    else:
        record["claim_status"] = "SETTLED_PARTIAL"
    touch(record)

    patient_balance.recompute_for_patient(record["patient_id"])
    return response.object_response(serialize.claim(record), 200)


@bp.post("/claims/<claim_id>/deny")
@require_roles("Biller")
def deny_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")
    helpers.get_json_body()  # optional reason
    if record["claim_status"] != "DRAFT":
        raise errors.invalid_state("Claim must be DRAFT to deny")
    record["claim_status"] = "DENIED"
    touch(record)
    return response.object_response(serialize.claim(record), 200)


@bp.post("/claims/<claim_id>/void")
@require_roles("Biller")
def void_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")
    if record["claim_status"] != "ADJUDICATED" or record["settled_cents"] != 0:
        raise errors.invalid_state(
            "Claim must be ADJUDICATED with no payment to void")

    record["claim_status"] = "VOIDED"
    touch(record)

    # ROUTINE: restore exam benefit (compensating step)
    if record["billing_route"] == "ROUTINE" and record.get("eligibility_id"):
        elig = db.eligibilities.get(record["eligibility_id"])
        if elig is not None:
            elig["exam_benefit_available"] = True
            exam_pool = benefit.pool_of_type(elig["id"], "EXAM")
            if exam_pool is not None:
                exam_pool["consumed_cents"] = 0
                benefit.recompute_pool_remaining(exam_pool)
                touch(exam_pool)
            touch(elig)

    patient_balance.recompute_for_patient(record["patient_id"])
    return response.object_response(serialize.claim(record), 200)


@bp.post("/claims/<claim_id>/submit")
@require_roles("Biller")
def submit_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")
    # claim_status in {ADJUDICATED, SETTLED_PARTIAL, SETTLED} and
    # submission_status == UNSUBMITTED
    if (record["claim_status"] not in ("ADJUDICATED", "SETTLED_PARTIAL", "SETTLED")
            or record["submission_status"] != "UNSUBMITTED"):
        raise errors.invalid_state("Claim is not in a submittable state")
    record["submission_status"] = "SUBMITTED"
    touch(record)
    return response.object_response(serialize.claim(record), 200)


@bp.post("/claims/<claim_id>/carrier-ack")
@require_roles("Biller")
def carrier_ack(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")
    body = helpers.get_json_body()
    outcome = helpers.require_enum(body, "outcome", ACK_OUTCOMES)
    if record["submission_status"] != "SUBMITTED":
        raise errors.invalid_state("Claim must be SUBMITTED to record an ack")
    record["submission_status"] = "ACCEPTED" if outcome == "ACCEPTED" else "REJECTED"
    touch(record)
    return response.object_response(serialize.claim(record), 200)
