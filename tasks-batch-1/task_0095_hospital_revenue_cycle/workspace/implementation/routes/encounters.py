"""Encounters, Charges, EligibilityChecks (PRD 3.3, 3.4)."""
from flask import Blueprint, request

import calculations
import clock
import db
import errors
import listing
import response
import services
import timeutil
import validate
from middleware import authenticate, require_role

bp = Blueprint("encounters", __name__)

READ_ROLES_ALL = {"Registrar", "BillingSpecialist", "Coder", "FinanceManager"}


# --------------------------------------------------------------------------
# Encounter
# --------------------------------------------------------------------------
@bp.route("/encounters", methods=["POST"])
def create_encounter():
    _, role = authenticate()
    require_role(role, {"Registrar"})
    body = validate.get_body()

    patient_id = body.get("patient_id")
    if patient_id is None:
        raise errors.invalid_request("patient_id is required.")
    if not isinstance(patient_id, str):
        raise errors.invalid_request("patient_id must be a string.")
    if patient_id not in db.patients:
        raise errors.reference_not_found("patient_id does not reference an existing patient.")

    policy_id = body.get("policy_id")
    if policy_id is not None:
        if not isinstance(policy_id, str):
            raise errors.invalid_request("policy_id must be a string.")
        if policy_id not in db.insurance_policies:
            raise errors.reference_not_found("policy_id does not reference an existing policy.")

    admission_raw = validate.require_str(body, "admission_at")
    timeutil.parse_iso(admission_raw, "admission_at")  # validate format

    rec = db.base_record(common_fields=True)
    rec.update({
        "patient_id": patient_id,
        "policy_id": policy_id,
        "admission_at": admission_raw,
        "discharge_at": None,
        "status": "REGISTERED",
        "total_charges_cents": 0,
        "patient_responsibility_cents": 0,
        "account_balance_cents": 0,
    })
    db.encounters[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/encounters/<eid>", methods=["GET"])
def get_encounter(eid):
    authenticate()
    rec = db.encounters.get(eid)
    if rec is None:
        raise errors.not_found()
    return response.object_response(rec, 200)


@bp.route("/encounters", methods=["GET"])
def list_encounters():
    authenticate()
    patient_id = request.args.get("patient_id")
    policy_id = request.args.get("policy_id")
    status = request.args.get("status")
    recs = list(db.encounters.values())
    if patient_id is not None:
        recs = [r for r in recs if r["patient_id"] == patient_id]
    if policy_id is not None:
        recs = [r for r in recs if r.get("policy_id") == policy_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


@bp.route("/encounters/<eid>/discharge", methods=["POST"])
def discharge_encounter(eid):
    _, role = authenticate()
    require_role(role, {"Registrar"})
    enc = db.encounters.get(eid)
    if enc is None:
        raise errors.not_found()
    # state gate: discharge defined only from ELIGIBILITY_VERIFIED
    if enc["status"] != "ELIGIBILITY_VERIFIED":
        raise errors.invalid_state("Discharge is only defined from ELIGIBILITY_VERIFIED status.")
    # requires at least one POSTED charge
    posted = [c for c in db.charges.values()
              if c["encounter_id"] == eid and c["status"] == "POSTED"]
    if not posted:
        raise errors.no_charges("The encounter has no POSTED charges.")

    enc["discharge_at"] = clock.now_iso()
    services.recompute_total_charges(enc)
    enc["status"] = "CHARGES_CAPTURED"
    db.touch(enc)
    return response.object_response(enc, 200)


# --------------------------------------------------------------------------
# EligibilityCheck
# --------------------------------------------------------------------------
@bp.route("/encounters/<eid>/eligibility-checks", methods=["POST"])
def create_eligibility_check(eid):
    _, role = authenticate()
    require_role(role, {"Registrar"})
    enc = db.encounters.get(eid)
    if enc is None:
        raise errors.not_found()
    # state gate: defined only from REGISTERED
    if enc["status"] != "REGISTERED":
        raise errors.invalid_state("Eligibility verification is only defined from REGISTERED status.")
    # business referential: encounter must have a policy attached
    if enc.get("policy_id") is None:
        raise errors.no_policy_on_encounter("The encounter has no policy attached.")
    policy = db.insurance_policies.get(enc["policy_id"])

    if policy is not None and policy["status"] == "ACTIVE":
        accum = _accumulator_for_policy(policy["id"])
        estimate = calculations.estimate_patient_responsibility(
            enc["total_charges_cents"], policy, accum
        )
        check = db.base_record(common_fields=True)
        check.update({
            "encounter_id": enc["id"],
            "policy_id": policy["id"],
            "result": "ELIGIBLE",
            "estimated_patient_responsibility_cents": estimate,
            "checked_at": clock.now_iso(),
        })
        db.eligibility_checks[check["id"]] = check
        enc["status"] = "ELIGIBILITY_VERIFIED"
        db.touch(enc)
        return response.object_response(check, 201)

    # policy not ACTIVE: record INELIGIBLE, encounter stays REGISTERED,
    # operation is rejected with ERR_POLICY_NOT_ACTIVE.
    check = db.base_record(common_fields=True)
    check.update({
        "encounter_id": enc["id"],
        "policy_id": enc["policy_id"],
        "result": "INELIGIBLE",
        "estimated_patient_responsibility_cents": 0,
        "checked_at": clock.now_iso(),
    })
    db.eligibility_checks[check["id"]] = check
    raise errors.policy_not_active("The referenced policy is not ACTIVE.")


def _accumulator_for_policy(policy_id):
    matches = [a for a in db.benefit_accumulators.values() if a["policy_id"] == policy_id]
    if not matches:
        # An ACTIVE policy always has an accumulator (created at verify); fall back
        # to a zeroed baseline if somehow absent.
        return {"deductible_met_cents": 0, "oop_met_cents": 0}
    return max(matches, key=lambda a: a["_seq"])


@bp.route("/encounters/<eid>/eligibility-checks", methods=["GET"])
def list_encounter_eligibility(eid):
    authenticate()
    if eid not in db.encounters:
        raise errors.not_found()
    recs = [c for c in db.eligibility_checks.values() if c["encounter_id"] == eid]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


@bp.route("/eligibility-checks/<cid>", methods=["GET"])
def get_eligibility(cid):
    authenticate()
    rec = db.eligibility_checks.get(cid)
    if rec is None:
        raise errors.not_found()
    return response.object_response(rec, 200)


@bp.route("/eligibility-checks", methods=["GET"])
def list_eligibility():
    authenticate()
    policy_id = request.args.get("policy_id")
    recs = list(db.eligibility_checks.values())
    if policy_id is not None:
        recs = [r for r in recs if r["policy_id"] == policy_id]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


# --------------------------------------------------------------------------
# Charge
# --------------------------------------------------------------------------
@bp.route("/encounters/<eid>/charges", methods=["POST"])
def create_charge(eid):
    _, role = authenticate()
    require_role(role, {"Registrar"})
    enc = db.encounters.get(eid)
    if enc is None:
        raise errors.not_found()
    body = validate.get_body()

    cpt_code = validate.require_str(body, "cpt_code")
    if len(cpt_code) != 5 or not cpt_code.isalnum():
        raise errors.invalid_request("cpt_code must be a 5-character alphanumeric code.")
    units = validate.require_int(body, "units")
    if units < 1:
        raise errors.invalid_request("units must be an integer >= 1.")
    unit_price_cents = validate.require_int(body, "unit_price_cents")
    if unit_price_cents < 0:
        raise errors.invalid_request("unit_price_cents must be an integer >= 0.")

    # business constraint: charge capture closes at discharge
    if enc["status"] not in ("REGISTERED", "ELIGIBILITY_VERIFIED"):
        raise errors.charges_closed("Charge capture is closed for this encounter.")

    rec = db.base_record(common_fields=True)
    rec.update({
        "encounter_id": eid,
        "cpt_code": cpt_code,
        "units": units,
        "unit_price_cents": unit_price_cents,
        "amount_cents": units * unit_price_cents,
        "status": "POSTED",
    })
    db.charges[rec["id"]] = rec
    services.recompute_total_charges(enc)
    return response.object_response(rec, 201)


@bp.route("/encounters/<eid>/charges", methods=["GET"])
def list_encounter_charges(eid):
    authenticate()
    if eid not in db.encounters:
        raise errors.not_found()
    recs = [c for c in db.charges.values() if c["encounter_id"] == eid]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


@bp.route("/charges/<cid>", methods=["GET"])
def get_charge(cid):
    authenticate()
    rec = db.charges.get(cid)
    if rec is None:
        raise errors.not_found()
    return response.object_response(rec, 200)


@bp.route("/charges/<cid>/void", methods=["POST"])
def void_charge(cid):
    _, role = authenticate()
    require_role(role, {"Registrar"})
    charge = db.charges.get(cid)
    if charge is None:
        raise errors.not_found()
    if charge["status"] != "POSTED":
        raise errors.invalid_state("Only a POSTED charge may be voided.")
    charge["status"] = "VOIDED"
    db.touch(charge)
    enc = db.encounters.get(charge["encounter_id"])
    if enc is not None:
        services.recompute_total_charges(enc)
    return response.object_response(charge, 200)
