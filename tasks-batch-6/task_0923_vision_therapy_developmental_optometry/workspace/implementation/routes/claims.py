"""Claims: creation, submission, the two adjudication arms, appeal, correction."""

from flask import Blueprint, request

import calc
import config
import lookup
import serialize
from auth import authenticate
from envelope import created, ok, paginate, pagination
from errors import ApiError
from store import base_row, db, now_iso, ordered, parse_date, touch
from validate import filter_enum, json_body

bp = Blueprint("claims", __name__)
P = config.API_PREFIX


@bp.post(P + "/claims")
def create_claim():
    authenticate([config.ROLE_BILLING])
    b = json_body()
    patient_id = b.str_req("patient_id")
    coverage_id = b.str_req("coverage_id")
    b.enum_shape_req("service_class")
    service_date = b.date_req("service_date")
    expected_version = b.int_req("expected_coverage_version")
    session_id = b.str_opt("session_id")
    assessment_id = b.str_opt("assessment_id")
    service_class = b.enum_req("service_class", config.SERVICE_CLASSES)
    if service_class == "THERAPY_SESSION":
        if not session_id:
            raise ApiError("ERR_VALIDATION", "A THERAPY_SESSION claim requires session_id.")
        assessment_id = None
    else:
        if not assessment_id:
            raise ApiError("ERR_VALIDATION", "An EVALUATION claim requires assessment_id.")
        session_id = None

    lookup.patient_or_404(patient_id)                                      # rung 5
    coverage = lookup.coverage_or_404(coverage_id)                         # rung 6
    assessment = lookup.assessment_or_404(assessment_id) if assessment_id else None   # rung 7
    session = lookup.session_or_404(session_id) if session_id else None    # rung 9
    # Claim creation sits OUTSIDE the clinical write gate (PRD §2.8).
    if expected_version != coverage["version"]:                            # rung 13
        raise ApiError("ERR_STALE_VERSION")

    for existing in db.claims.values():                                    # rung 29
        if session_id and existing["session_id"] == session_id:
            raise ApiError("ERR_DUPLICATE_CLAIM")
        if assessment_id and existing["assessment_id"] == assessment_id:
            raise ApiError("ERR_DUPLICATE_CLAIM")

    if service_class == "THERAPY_SESSION":                                 # rung 30
        if session["billing_status"] != "BILLABLE":
            raise ApiError("ERR_SESSION_NOT_BILLABLE")
    else:
        if assessment["status"] != "SIGNED":
            raise ApiError("ERR_SESSION_NOT_BILLABLE")

    payer = db.payers.get(coverage["payer_id"])                            # rung 31
    if payer is not None and payer["payer_type"] == "VISION":
        field = ("last_paid_service_date_therapy" if service_class == "THERAPY_SESSION"
                 else "last_paid_service_date_evaluation")
        last_paid = coverage.get(field)
        if last_paid:
            months = calc.months_between(parse_date(last_paid), parse_date(service_date))
            if months < payer["frequency_limit_months"]:
                raise ApiError("ERR_VISION_FREQUENCY_LIMIT")

    if service_class == "THERAPY_SESSION":
        procedure_code = session["procedure_code"]
        units = session["billable_units"]
    else:
        procedure_code = "EVALUATION_ENCOUNTER"
        units = 1

    row = base_row()
    row.update({
        "patient_id": patient_id,
        "coverage_id": coverage_id,
        "session_id": session_id,
        "assessment_id": assessment_id,
        "service_class": service_class,
        "service_date": service_date,
        "procedure_code": procedure_code,
        "units": units,
        "billed_amount": calc.charge_amount(units, procedure_code),
        "allowed_amount": 0.0,
        "contractual_adjustment_amount": 0.0,
        "deductible_applied_amount": 0.0,
        "coinsurance_amount": 0.0,
        "plan_paid_amount": 0.0,
        "patient_responsibility_amount": 0.0,
        "denied_amount": 0.0,
        "adjudication_variant": None,
        "status": "DRAFT",
        "appeal_count": 0,
        "appeal_attempt_log_count": 0,
        "last_appeal_attempt_at": None,
        "correction_count": 0,
        "submitted_by_user_id": None,
        "denial_reason": None,
    })
    db.claims[row["id"]] = row

    if session is not None:
        session["billing_status"] = "CLAIMED"
        touch(session)
    touch(coverage)
    return created(serialize.claim(row))


@bp.get(P + "/claims/<id>")
def get_claim(id):
    authenticate(config.READ_ROLES)
    return ok(serialize.claim(lookup.claim_or_404(id)))


@bp.get(P + "/claims")
def list_claims():
    authenticate(config.READ_ROLES)
    limit, offset = pagination(request.args)
    status = filter_enum(request.args, "status", config.CLAIM_STATUSES)
    patient_id = request.args.get("patient_id")
    coverage_id = request.args.get("coverage_id")
    session_id = request.args.get("session_id")
    assessment_id = request.args.get("assessment_id")

    def match(row):
        if patient_id and row["patient_id"] != patient_id:
            return False
        if coverage_id and row["coverage_id"] != coverage_id:
            return False
        if session_id and row["session_id"] != session_id:
            return False
        if assessment_id and row["assessment_id"] != assessment_id:
            return False
        if status and row["status"] != status:
            return False
        return True

    return paginate(ordered(db.claims, match), limit, offset, serialize.claim)


@bp.post(P + "/claims/<id>/submit")
def submit_claim(id):
    caller = authenticate([config.ROLE_BILLING])
    json_body()
    claim = lookup.claim_or_404(id)                                        # rung 10
    if claim["status"] != "DRAFT":                                         # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT claim may be submitted.")
    coverage = db.coverages.get(claim["coverage_id"])
    if coverage is None or coverage["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The coverage behind this claim is not ACTIVE.")

    claim["status"] = "SUBMITTED"
    claim["submitted_by_user_id"] = caller.user_id
    touch(claim)
    return ok(serialize.claim(claim))


def _adjudicate_amounts(claim, coverage, payer, outcome):
    """The seven-step waterfall; every step rounds half-up to 2 dp before the
    next one consumes it."""
    D = calc.D
    billed = D(claim["billed_amount"])
    if payer["payer_type"] == "MEDICAL":
        if claim["procedure_code"] == "TIMED_THERAPEUTIC_ACTIVITY":
            per_unit = D(payer["allowed_amount_timed_unit"])
        elif claim["procedure_code"] == "FLAT_ORTHOPTIC_TRAINING":
            per_unit = D(payer["allowed_amount_flat_session"])
        else:
            per_unit = D(payer["allowed_amount_evaluation"])
        allowed = calc.r2(D(claim["units"]) * per_unit)
        contractual = calc.r2(billed - allowed)
        if contractual < D(0):
            contractual = D("0.00")
        remaining_deductible = calc.r2(D(coverage["deductible_total"]) - D(coverage["deductible_met"]))
        deductible = allowed if allowed < remaining_deductible else remaining_deductible
        if deductible < D(0):
            deductible = D("0.00")
        post = calc.r2(allowed - deductible)
        coinsurance = calc.r2(post * D(payer["coinsurance_rate"]))
        plan_paid = calc.r2(post - coinsurance)
        patient_resp = calc.r2(deductible + coinsurance)
        variant = "MEDICAL"
    else:
        remaining_allowance = calc.r2(D(coverage["vision_allowance_remaining"]))
        billed_r = calc.r2(billed)
        allowed = billed_r if billed_r < remaining_allowance else remaining_allowance
        contractual = D("0.00")
        deductible = D("0.00")
        coinsurance = D("0.00")
        plan_paid = allowed
        patient_resp = calc.r2(billed - allowed)
        variant = "VISION"

    denied = D("0.00")
    if outcome == "DENIED":
        denied = allowed
        plan_paid = D("0.00")
        patient_resp = D("0.00")
        contractual = calc.r2(billed - allowed)

    claim["allowed_amount"] = float(allowed)
    claim["contractual_adjustment_amount"] = float(contractual)
    claim["deductible_applied_amount"] = float(deductible)
    claim["coinsurance_amount"] = float(coinsurance)
    claim["plan_paid_amount"] = float(plan_paid)
    claim["patient_responsibility_amount"] = float(patient_resp)
    claim["denied_amount"] = float(denied)
    claim["adjudication_variant"] = variant
    return variant


@bp.post(P + "/claims/<id>/adjudicate")
def adjudicate_claim(id):
    authenticate([config.ROLE_BILLING])
    b = json_body()
    b.enum_shape_req("outcome")                                            # rung 3
    denial_reason = b.str_opt("denial_reason")
    outcome = b.enum_req("outcome", config.ADJUDICATION_OUTCOMES)          # rung 4
    claim = lookup.claim_or_404(id)                                        # rung 10

    status = claim["status"]                                               # rung 14
    legal = ((status == "SUBMITTED" and outcome in ("ACCEPTED", "REJECTED"))
             or (status == "ACCEPTED" and outcome in ("PAID", "DENIED")))
    if not legal:
        raise ApiError("ERR_INVALID_STATE",
                       "That adjudication outcome is not declared from the claim's current state.")

    if outcome in ("ACCEPTED", "REJECTED"):
        claim["status"] = outcome
        if outcome == "REJECTED":
            claim["denial_reason"] = denial_reason
        touch(claim)
        return ok(serialize.claim(claim))

    coverage = db.coverages.get(claim["coverage_id"])
    payer = db.payers.get(coverage["payer_id"]) if coverage else None
    variant = _adjudicate_amounts(claim, coverage, payer, outcome)
    claim["status"] = outcome
    if outcome == "DENIED":
        claim["denial_reason"] = denial_reason
    elif denial_reason is not None:
        claim["denial_reason"] = denial_reason
    touch(claim)

    if outcome == "PAID":
        if variant == "MEDICAL":
            coverage["deductible_met"] = calc.f2(
                calc.D(coverage["deductible_met"]) + calc.D(claim["deductible_applied_amount"]))
        else:
            coverage["vision_allowance_used"] = calc.f2(
                calc.D(coverage["vision_allowance_used"]) + calc.D(claim["plan_paid_amount"]))
            coverage["vision_allowance_remaining"] = calc.f2(
                calc.D(coverage["vision_allowance_remaining"]) - calc.D(claim["plan_paid_amount"]))
            field = ("last_paid_service_date_therapy"
                     if claim["service_class"] == "THERAPY_SESSION"
                     else "last_paid_service_date_evaluation")
            coverage[field] = claim["service_date"]
        touch(coverage)
        session = db.sessions.get(claim["session_id"]) if claim["session_id"] else None
        if session is not None:
            session["billing_status"] = "SETTLED"
            touch(session)
    return ok(serialize.claim(claim))


@bp.post(P + "/claims/<id>/appeal")
def appeal_claim(id):
    authenticate([config.ROLE_BILLING])
    b = json_body()
    b.str_opt("appeal_reason")
    claim = lookup.claim_or_404(id)                                        # rung 10
    if claim["status"] != "DENIED":                                        # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a DENIED claim may be appealed.")

    # rung 36 is MUTATE-THEN-REJECT: the three bookkeeping writes commit first.
    claim["appeal_attempt_log_count"] += 1
    claim["last_appeal_attempt_at"] = now_iso()
    touch(claim)
    if claim["appeal_count"] >= config.MAX_APPEAL_ATTEMPTS:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED")

    claim["appeal_count"] += 1
    claim["status"] = "SUBMITTED"
    touch(claim)
    return ok(serialize.claim(claim))


@bp.post(P + "/claims/<id>/correct")
def correct_claim(id):
    caller = authenticate([config.ROLE_BILLING])
    b = json_body()
    b.str_opt("correction_reason")
    corrected_units = b.int_opt("corrected_units", non_negative=True)
    claim = lookup.claim_or_404(id)                                        # rung 10
    # OUTSIDE the clinical write gate (PRD §2.8).
    if claim["status"] not in ("REJECTED", "DENIED"):                      # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a REJECTED or DENIED claim may be corrected.")
    if caller.user_id == claim["submitted_by_user_id"]:                    # rung 17
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    claim["status"] = "DRAFT"
    claim["correction_count"] += 1
    if corrected_units is not None:
        claim["units"] = corrected_units
        claim["billed_amount"] = calc.charge_amount(corrected_units, claim["procedure_code"])
    touch(claim)
    return ok(serialize.claim(claim))
