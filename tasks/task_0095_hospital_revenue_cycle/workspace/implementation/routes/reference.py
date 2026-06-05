"""Payers, Patients, InsurancePolicies, BenefitAccumulators, and the test
clock (PRD 3.1, 3.2, 3.12)."""
from flask import Blueprint

import clock
import db
import errors
import listing
import response
import timeutil
import validate
from middleware import authenticate, require_role

bp = Blueprint("reference", __name__)

PAYER_TYPES = {"COMMERCIAL", "MEDICARE", "MEDICAID", "SELF_PAY"}
FINANCIAL_CLASSES = {"INSURED", "SELF_PAY", "CHARITY"}
POLICY_STATUSES = {"UNVERIFIED", "ACTIVE", "TERMINATED"}


# --------------------------------------------------------------------------
# Payer
# --------------------------------------------------------------------------
@bp.route("/payers", methods=["POST"])
def create_payer():
    _, role = authenticate()
    require_role(role, {"Registrar", "BillingSpecialist"})
    body = validate.get_body()

    name = validate.require_str(body, "name", max_len=120)
    payer_type = validate.require_enum(body, "payer_type", PAYER_TYPES)
    timely_filing_days = validate.optional_int(body, "timely_filing_days", 90)
    validate.range_check(timely_filing_days, "timely_filing_days", 1, 365)
    appeal_window_days = validate.optional_int(body, "appeal_window_days", 30)
    validate.range_check(appeal_window_days, "appeal_window_days", 1, 180)
    active = validate.optional_bool(body, "active", True)

    rec = db.base_record(common_fields=True)
    rec.update({
        "name": name,
        "payer_type": payer_type,
        "timely_filing_days": timely_filing_days,
        "appeal_window_days": appeal_window_days,
        "active": active,
    })
    db.payers[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/payers/<pid>", methods=["GET"])
def get_payer(pid):
    authenticate()
    rec = db.payers.get(pid)
    if rec is None:
        raise errors.not_found()
    return response.object_response(rec, 200)


# --------------------------------------------------------------------------
# Patient
# --------------------------------------------------------------------------
@bp.route("/patients", methods=["POST"])
def create_patient():
    _, role = authenticate()
    require_role(role, {"Registrar"})
    body = validate.get_body()

    full_name = validate.require_str(body, "full_name", max_len=120)
    dob_raw = validate.require_str(body, "date_of_birth")
    dob = timeutil.parse_date(dob_raw, "date_of_birth")
    # must lie in the past
    if dob >= clock.now().date():
        raise errors.invalid_request("date_of_birth must be a past date.")
    financial_class = validate.optional_enum(body, "financial_class", FINANCIAL_CLASSES, "INSURED")

    rec = db.base_record(common_fields=True)
    rec.update({
        "full_name": full_name,
        "date_of_birth": dob_raw,
        "financial_class": financial_class,
    })
    db.patients[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    authenticate()
    rec = db.patients.get(pid)
    if rec is None:
        raise errors.not_found()
    return response.object_response(rec, 200)


# --------------------------------------------------------------------------
# InsurancePolicy
# --------------------------------------------------------------------------
@bp.route("/insurance-policies", methods=["POST"])
def create_policy():
    _, role = authenticate()
    require_role(role, {"Registrar"})
    body = validate.get_body()

    # FK existence (priority 4) before body validation (priority 5)? PRD 2.7
    # orders body-FK resolution (404) ahead of body field validation (400/422).
    patient_id = body.get("patient_id")
    payer_id = body.get("payer_id")
    if not isinstance(patient_id, str) or not isinstance(payer_id, str):
        # type/missing handled as invalid request after FK gate cannot resolve;
        # but a non-string FK cannot reference anything -> treat as reference miss
        # only when present-but-unresolved. Missing/typed wrong -> invalid request.
        if patient_id is None or payer_id is None:
            raise errors.invalid_request("patient_id and payer_id are required.")
        raise errors.invalid_request("patient_id and payer_id must be strings.")
    if patient_id not in db.patients:
        raise errors.reference_not_found("patient_id does not reference an existing patient.")
    if payer_id not in db.payers:
        raise errors.reference_not_found("payer_id does not reference an existing payer.")

    member_number = validate.require_str(body, "member_number")
    plan_year = validate.require_int(body, "plan_year")
    validate.range_check(plan_year, "plan_year", 2000, 2100)
    deductible_cents = validate.require_int(body, "deductible_cents")
    if deductible_cents < 0:
        raise errors.validation_out_of_range("deductible_cents must be >= 0.")
    coinsurance_pct = validate.require_number(body, "coinsurance_pct")
    if coinsurance_pct < 0.0 or coinsurance_pct > 1.0:
        raise errors.validation_out_of_range("coinsurance_pct must be between 0.0 and 1.0.")
    oop_max_cents = validate.require_int(body, "oop_max_cents")
    if oop_max_cents < deductible_cents:
        raise errors.validation_out_of_range("oop_max_cents must be >= deductible_cents.")

    rec = db.base_record(common_fields=True)
    rec.update({
        "patient_id": patient_id,
        "payer_id": payer_id,
        "member_number": member_number,
        "plan_year": plan_year,
        "deductible_cents": deductible_cents,
        "coinsurance_pct": coinsurance_pct,
        "oop_max_cents": oop_max_cents,
        "status": "UNVERIFIED",
    })
    db.insurance_policies[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/insurance-policies/<pid>", methods=["GET"])
def get_policy(pid):
    authenticate()
    rec = db.insurance_policies.get(pid)
    if rec is None:
        raise errors.not_found()
    return response.object_response(rec, 200)


@bp.route("/insurance-policies", methods=["GET"])
def list_policies():
    authenticate()
    from flask import request
    patient_id = request.args.get("patient_id")
    payer_id = request.args.get("payer_id")
    recs = list(db.insurance_policies.values())
    if patient_id is not None:
        recs = [r for r in recs if r["patient_id"] == patient_id]
    if payer_id is not None:
        recs = [r for r in recs if r["payer_id"] == payer_id]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


@bp.route("/insurance-policies/<pid>/verify", methods=["POST"])
def verify_policy(pid):
    _, role = authenticate()
    require_role(role, {"Registrar"})
    policy = db.insurance_policies.get(pid)
    if policy is None:
        raise errors.not_found()
    # state gate (priority 6): defined only from UNVERIFIED
    if policy["status"] != "UNVERIFIED":
        raise errors.invalid_state("Policy verification is only defined from UNVERIFIED status.")
    # business safety: referenced payer must be active
    payer = db.payers.get(policy["payer_id"])
    if payer is None or not payer["active"]:
        raise errors.payer_inactive("The policy's payer is not active.")

    policy["status"] = "ACTIVE"
    db.touch(policy)

    accum = db.base_record(common_fields=True)
    accum.update({
        "policy_id": policy["id"],
        "plan_year": policy["plan_year"],
        "deductible_met_cents": 0,
        "oop_met_cents": 0,
    })
    db.benefit_accumulators[accum["id"]] = accum
    return response.object_response(policy, 200)


@bp.route("/insurance-policies/<pid>/terminate", methods=["POST"])
def terminate_policy(pid):
    _, role = authenticate()
    require_role(role, {"Registrar"})
    policy = db.insurance_policies.get(pid)
    if policy is None:
        raise errors.not_found()
    if policy["status"] != "ACTIVE":
        raise errors.invalid_state("Policy termination is only defined from ACTIVE status.")
    # no encounter referencing this policy may be in a status other than CLOSED
    for enc in db.encounters.values():
        if enc.get("policy_id") == policy["id"] and enc["status"] != "CLOSED":
            raise errors.policy_in_use("An open encounter references this policy.")
    policy["status"] = "TERMINATED"
    db.touch(policy)
    return response.object_response(policy, 200)


# --------------------------------------------------------------------------
# BenefitAccumulator
# --------------------------------------------------------------------------
@bp.route("/benefit-accumulators/<aid>", methods=["GET"])
def get_accumulator(aid):
    authenticate()
    rec = db.benefit_accumulators.get(aid)
    if rec is None:
        raise errors.not_found()
    return response.object_response(rec, 200)


@bp.route("/benefit-accumulators", methods=["GET"])
def list_accumulators():
    authenticate()
    from flask import request
    policy_id = request.args.get("policy_id")
    recs = list(db.benefit_accumulators.values())
    if policy_id is not None:
        recs = [r for r in recs if r["policy_id"] == policy_id]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


# --------------------------------------------------------------------------
# Test clock
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()  # any of the four roles may set it
    body = validate.get_body()
    to_iso = validate.require_str(body, "to_iso8601")
    dt = timeutil.parse_iso(to_iso, "to_iso8601")
    clock.set_current_utc(dt)
    return response.empty_response(200)
