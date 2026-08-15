"""Routes: clock, state statutes, policies, beneficiary designations."""

from flask import Blueprint

import domain
from domain import (
    create_escheatment_case,
    run_sweep,
    ser_designation,
    ser_policy,
    ser_statute,
)
from helpers import (
    auth,
    fail,
    fmt_clock,
    json_body,
    list_response,
    new_record,
    ok_object,
    opt_int,
    opt_string,
    parse_date,
    parse_datetime_iso,
    req_date,
    req_enum,
    req_int,
    req_share_percent,
    req_string,
    touch,
)
from store import db

bp = Blueprint("core", __name__)

ALL_GET = (
    "ClaimsExaminer",
    "ClaimsApprover",
    "PolicyAdministrator",
    "LegalCounsel",
    "ComplianceOfficer",
    "SystemAdmin",
)


# ---------------------------------------------------------------------------
# Clock (test-driving)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("SystemAdmin")
    data = json_body()
    to = data.get("to_iso8601")
    if to is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 is required")
    db.now = parse_datetime_iso(to)
    run_sweep()
    return ok_object({"current_utc": fmt_clock(db.now)})


# ---------------------------------------------------------------------------
# StateStatute
# ---------------------------------------------------------------------------

@bp.post("/state-statutes")
def create_statute():
    auth("ComplianceOfficer")
    data = json_body()
    state_code = req_string(data, "state_code")
    annual_interest_rate_bp = req_int(data, "annual_interest_rate_bp")
    interest_basis = req_enum(data, "interest_basis", {"DATE_OF_DEATH", "PROOF_OF_LOSS_COMPLETE"})
    grace_days = req_int(data, "grace_days")
    payment_deadline_days = req_int(data, "payment_deadline_days")
    dormancy_years = req_int(data, "dormancy_years")
    raa_minimum_cents = req_int(data, "raa_minimum_cents")
    raa_annual_interest_rate_bp = req_int(data, "raa_annual_interest_rate_bp")
    if state_code in db.statutes:
        existing = db.statutes[state_code]
        identical = all(
            existing[k] == v
            for k, v in {
                "annual_interest_rate_bp": annual_interest_rate_bp,
                "interest_basis": interest_basis,
                "grace_days": grace_days,
                "payment_deadline_days": payment_deadline_days,
                "dormancy_years": dormancy_years,
                "raa_minimum_cents": raa_minimum_cents,
                "raa_annual_interest_rate_bp": raa_annual_interest_rate_bp,
            }.items()
        )
        if identical:
            # Idempotent re-configuration with the same rulebook.
            return ok_object(ser_statute(existing), 201)
        fail("ERR_STATUTE_ALREADY_EXISTS", "A statute is already configured for %s" % state_code)
    s = {"id": new_record()["id"], "created_at": db.now}
    s.update(
        {
            "state_code": state_code,
            "annual_interest_rate_bp": annual_interest_rate_bp,
            "interest_basis": interest_basis,
            "grace_days": grace_days,
            "payment_deadline_days": payment_deadline_days,
            "dormancy_years": dormancy_years,
            "raa_minimum_cents": raa_minimum_cents,
            "raa_annual_interest_rate_bp": raa_annual_interest_rate_bp,
        }
    )
    db.statutes[state_code] = s
    return ok_object(ser_statute(s), 201)


@bp.get("/state-statutes")
def list_statutes():
    auth(*ALL_GET)
    items = list(db.statutes.values())
    sc = _qs("state_code")
    if sc is not None:
        items = [s for s in items if s["state_code"] == sc]
    return list_response(items, ser_statute)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@bp.post("/policies")
def create_policy():
    auth("PolicyAdministrator")
    data = json_body()
    policy_number = req_string(data, "policy_number")
    insured_name = req_string(data, "insured_name")
    insured_dob = req_date(data, "insured_dob")
    insured_ssn_last4 = opt_string(data, "insured_ssn_last4")
    insured_zip = opt_string(data, "insured_zip")
    state_code = req_string(data, "state_code")
    face_amount_cents = req_int(data, "face_amount_cents", positive=True)
    issue_date = req_date(data, "issue_date")
    contestability_months = opt_int(data, "contestability_months")
    if contestability_months is None:
        contestability_months = 24
    if any(p["policy_number"] == policy_number for p in db.policies.values()):
        fail("ERR_INVALID_REQUEST", "policy_number must be unique across all policies")
    p = new_record()
    p.update(
        {
            "policy_number": policy_number,
            "insured_name": insured_name,
            "insured_dob": insured_dob,
            "insured_ssn_last4": insured_ssn_last4,
            "insured_zip": insured_zip,
            "state_code": state_code,
            "face_amount_cents": face_amount_cents,
            "issue_date": issue_date,
            "contestability_months": contestability_months,
            "lapse_date": None,
            "status": "ACTIVE",
        }
    )
    db.policies[p["id"]] = p
    return ok_object(ser_policy(p), 201)


@bp.get("/policies")
def list_policies():
    auth(*ALL_GET)
    items = list(db.policies.values())
    st = _qs("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    sc = _qs("state_code")
    if sc is not None:
        items = [p for p in items if p["state_code"] == sc]
    return list_response(items, ser_policy)


@bp.get("/policies/<policyId>")
def get_policy(policyId):
    auth(*ALL_GET)
    p = db.policies.get(policyId)
    if p is None:
        fail("ERR_POLICY_NOT_FOUND", "Policy %s does not exist" % policyId)
    return ok_object(ser_policy(p))


@bp.post("/policies/<policyId>/lapse")
def lapse_policy(policyId):
    auth("PolicyAdministrator")
    p = db.policies.get(policyId)
    if p is None:
        fail("ERR_POLICY_NOT_FOUND", "Policy %s does not exist" % policyId)
    if p["status"] != "ACTIVE":
        fail("ERR_POLICY_NOT_ACTIVE", "Lapse requires the policy to be ACTIVE")
    p["status"] = "LAPSED"
    p["lapse_date"] = db.now.date()
    touch(p)
    return ok_object(ser_policy(p))


# ---------------------------------------------------------------------------
# BeneficiaryDesignation
# ---------------------------------------------------------------------------

@bp.post("/policies/<policyId>/beneficiary-designations")
def create_designation(policyId):
    auth("PolicyAdministrator")
    data = json_body()
    beneficiary_name = req_string(data, "beneficiary_name")
    beneficiary_type = req_enum(data, "beneficiary_type", {"PRIMARY", "CONTINGENT"})
    share_percent = req_share_percent(data)
    effective_date = req_date(data, "effective_date")
    expected_policy_version = req_int(data, "expected_policy_version")
    # existence
    p = db.policies.get(policyId)
    if p is None:
        fail("ERR_POLICY_NOT_FOUND", "Policy %s does not exist" % policyId)
    # OCC
    if expected_policy_version != p["version"]:
        fail("ERR_STALE_POLICY_VERSION", "expected_policy_version does not match the current policy version")
    # state
    if p["status"] != "ACTIVE":
        fail("ERR_POLICY_NOT_ACTIVE", "Adding a designation requires the policy to be ACTIVE")
    # temporal freeze
    if any(c["policy_id"] == p["id"] for c in db.claims.values()):
        fail("ERR_DESIGNATION_FROZEN_AFTER_CLAIM", "A claim exists on this policy; designations are frozen")
    # structural: window overlap (same policy, type, name; half-open windows; adjacency allowed)
    for d in db.designations.values():
        if (
            d["policy_id"] == p["id"]
            and d["beneficiary_type"] == beneficiary_type
            and d["beneficiary_name"] == beneficiary_name
        ):
            end = d["revoked_at"].date() if d["revoked_at"] else None
            if end is None or end > effective_date:
                fail(
                    "ERR_DESIGNATION_WINDOW_OVERLAP",
                    "An overlapping ACTIVE designation window exists for this beneficiary",
                )
    # structural: share capacity over ACTIVE same-type designations
    total = sum(
        _share_decimal(d["share_percent"])
        for d in db.designations.values()
        if d["policy_id"] == p["id"] and d["beneficiary_type"] == beneficiary_type and d["status"] == "ACTIVE"
    )
    if total + _share_decimal(share_percent) > 100:
        fail("ERR_SHARE_TOTAL_EXCEEDED", "Sum of ACTIVE same-type shares would exceed 100")
    d = new_record()
    d.update(
        {
            "policy_id": p["id"],
            "beneficiary_name": beneficiary_name,
            "beneficiary_type": beneficiary_type,
            "share_percent": share_percent,
            "effective_date": effective_date,
            "revoked_at": None,
            "status": "ACTIVE",
        }
    )
    db.designations[d["id"]] = d
    touch(p)  # beneficiary structure change bumps Policy.version
    return ok_object(ser_designation(d), 201)


@bp.get("/policies/<policyId>/beneficiary-designations")
def list_designations(policyId):
    auth(*ALL_GET)
    p = db.policies.get(policyId)
    if p is None:
        fail("ERR_POLICY_NOT_FOUND", "Policy %s does not exist" % policyId)
    items = [d for d in db.designations.values() if d["policy_id"] == p["id"]]
    st = _qs("status")
    if st is not None:
        items = [d for d in items if d["status"] == st]
    bt = _qs("beneficiary_type")
    if bt is not None:
        items = [d for d in items if d["beneficiary_type"] == bt]
    return list_response(items, ser_designation)


@bp.post("/beneficiary-designations/<designationId>/revoke")
def revoke_designation(designationId):
    auth("PolicyAdministrator")
    d = db.designations.get(designationId)
    if d is None:
        fail("ERR_DESIGNATION_NOT_FOUND", "BeneficiaryDesignation %s does not exist" % designationId)
    if d["status"] != "ACTIVE":
        fail("ERR_DESIGNATION_ALREADY_REVOKED", "Designation is not ACTIVE")
    p = db.policies.get(d["policy_id"])
    if any(c["policy_id"] == d["policy_id"] for c in db.claims.values()):
        fail("ERR_DESIGNATION_FROZEN_AFTER_CLAIM", "A claim exists on this policy; designations are frozen")
    d["status"] = "REVOKED"
    d["revoked_at"] = db.now
    touch(d)
    if p is not None:
        touch(p)  # beneficiary structure change bumps Policy.version
    return ok_object(ser_designation(d))


# ---------------------------------------------------------------------------
# small local helpers
# ---------------------------------------------------------------------------

def _qs(name):
    from flask import request

    v = request.args.get(name)
    return v if v is not None else None


def _share_decimal(v):
    from decimal import Decimal

    return Decimal(str(v))
