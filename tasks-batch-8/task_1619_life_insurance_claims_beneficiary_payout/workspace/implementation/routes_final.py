"""Routes: retained asset accounts, death master matches, escheatment cases."""

from flask import Blueprint, request

from domain import (
    bcs_of_claim,
    contestability_flag,
    dmf_match_score,
    elections_of_claim,
    has_non_terminal_claim,
    raa_final_yield,
    ser_account,
    ser_case,
    ser_match,
)
from helpers import (
    auth,
    fail,
    json_body,
    list_response,
    new_record,
    ok_object,
    opt_string,
    req_date,
    req_enum,
    req_int,
    req_string,
    touch,
)
from store import db

bp = Blueprint("final", __name__)

ALL_GET = (
    "ClaimsExaminer",
    "ClaimsApprover",
    "PolicyAdministrator",
    "LegalCounsel",
    "ComplianceOfficer",
    "SystemAdmin",
)


def _qs(name):
    v = request.args.get(name)
    return v if v is not None else None


# ---------------------------------------------------------------------------
# RetainedAssetAccount
# ---------------------------------------------------------------------------

@bp.get("/retained-asset-accounts")
def list_accounts():
    auth(*ALL_GET)
    items = list(db.accounts.values())
    cid = _qs("claim_id")
    if cid is not None:
        items = [a for a in items if a["claim_id"] == cid]
    bid = _qs("beneficiary_claim_id")
    if bid is not None:
        items = [a for a in items if a["beneficiary_claim_id"] == bid]
    st = _qs("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    return list_response(items, ser_account)


@bp.get("/retained-asset-accounts/<accountId>")
def get_account(accountId):
    auth(*ALL_GET)
    a = db.accounts.get(accountId)
    if a is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "RetainedAssetAccount %s does not exist" % accountId)
    return ok_object(ser_account(a))


@bp.post("/retained-asset-accounts/<accountId>/withdrawals")
def withdraw(accountId):
    auth("ClaimsApprover")
    data = json_body()
    amount_cents = req_int(data, "amount_cents", positive=True)
    a = db.accounts.get(accountId)
    if a is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "RetainedAssetAccount %s does not exist" % accountId)
    if a["status"] not in ("OPEN", "DORMANT"):
        fail("ERR_ACCOUNT_NOT_WITHDRAWABLE", "Withdrawal requires the account to be OPEN or DORMANT")
    if amount_cents > a["balance_cents"]:
        fail("ERR_INSUFFICIENT_ACCOUNT_BALANCE", "Withdrawal amount exceeds the account balance")
    closing_balance = a["balance_cents"]
    a["balance_cents"] -= amount_cents
    a["withdrawn_total_cents"] += amount_cents
    a["last_activity_at"] = db.now
    if a["status"] == "DORMANT":
        # owner activity reactivates and auto-resolves the open case
        a["status"] = "OPEN"
        for case in db.cases.values():
            if case["account_id"] == a["id"] and case["status"] in ("MONITORING", "DUE_DILIGENCE"):
                case["status"] = "RESOLVED"
                case["resolution_note"] = "OWNER_ACTIVITY"
                touch(case)
    if a["balance_cents"] == 0:
        # closure: final compound yield on the closing balance, paid with the final withdrawal
        a["interest_paid_cents"] = raa_final_yield(a, closing_balance, db.now.date())
        a["status"] = "CLOSED"
    touch(a)
    return ok_object(ser_account(a))


# ---------------------------------------------------------------------------
# DeathMasterMatch
# ---------------------------------------------------------------------------

AUTO_CONFIRM = 85
MANUAL_REVIEW_FLOOR = 60


@bp.post("/policies/<policyId>/death-master-matches")
def create_match(policyId):
    auth("ComplianceOfficer")
    data = json_body()
    deceased_name = req_string(data, "deceased_name")
    deceased_dob = req_date(data, "deceased_dob")
    deceased_death_date = req_date(data, "deceased_death_date")
    deceased_ssn_last4 = opt_string(data, "deceased_ssn_last4")
    deceased_zip = opt_string(data, "deceased_zip")
    p = db.policies.get(policyId)
    if p is None:
        fail("ERR_POLICY_NOT_FOUND", "Policy %s does not exist" % policyId)
    rec = {
        "deceased_name": deceased_name,
        "deceased_dob": deceased_dob.isoformat(),
        "deceased_death_date": deceased_death_date.isoformat(),
        "deceased_ssn_last4": deceased_ssn_last4,
        "deceased_zip": deceased_zip,
    }
    score = dmf_match_score(
        {
            "insured_name": p["insured_name"],
            "insured_dob": p["insured_dob"].isoformat(),
            "insured_ssn_last4": p["insured_ssn_last4"],
            "insured_zip": p["insured_zip"],
        },
        rec,
    )
    if score >= AUTO_CONFIRM:
        status = "CONFIRMED"
    elif score >= MANUAL_REVIEW_FLOOR:
        status = "PENDING_REVIEW"
    else:
        status = "FALSE_POSITIVE"
    m = new_record()
    m.update(
        {
            "policy_id": p["id"],
            "deceased_name": deceased_name,
            "deceased_dob": deceased_dob,
            "deceased_death_date": deceased_death_date,
            "deceased_ssn_last4": deceased_ssn_last4,
            "deceased_zip": deceased_zip,
            "match_score": score,
            "generated_claim_id": None,
            "status": status,
        }
    )
    db.matches[m["id"]] = m
    if status == "CONFIRMED":
        _maybe_generate_claim(p, m)
    return ok_object(ser_match(m), 201)


def _maybe_generate_claim(policy, match):
    """Confirmation (automatic or manual) proactively creates a claim when the
    policy has no non-terminal claim."""
    if has_non_terminal_claim(policy["id"]):
        return
    c = new_record()
    c.update(
        {
            "policy_id": policy["id"],
            "state_code": policy["state_code"],
            "date_of_death": match["deceased_death_date"],
            "cause_of_death": None,
            "notification_date": db.now.date(),
            "assigned_examiner_id": None,
            "contestability_flag": contestability_flag(policy, match["deceased_death_date"]),
            "proof_complete_date": None,
            "face_amount_cents": policy["face_amount_cents"],
            "accrued_interest_cents": 0,
            "total_payable_cents": None,
            "hold_return_state": None,
            "approved_at": None,
            "paid_at": None,
            "denial_reason": None,
            "rescission_reason": None,
            "court_reference": None,
            "status": "NOTIFIED",
        }
    )
    db.claims[c["id"]] = c
    match["generated_claim_id"] = c["id"]


@bp.get("/policies/<policyId>/death-master-matches")
def list_matches(policyId):
    auth(*ALL_GET)
    p = db.policies.get(policyId)
    if p is None:
        fail("ERR_POLICY_NOT_FOUND", "Policy %s does not exist" % policyId)
    items = [m for m in db.matches.values() if m["policy_id"] == p["id"]]
    st = _qs("status")
    if st is not None:
        items = [m for m in items if m["status"] == st]
    return list_response(items, ser_match)


@bp.post("/death-master-matches/<matchId>/review")
def review_match(matchId):
    auth("ComplianceOfficer")
    data = json_body()
    review_outcome = req_enum(data, "review_outcome", {"CONFIRMED", "FALSE_POSITIVE"})
    m = db.matches.get(matchId)
    if m is None:
        fail("ERR_MATCH_NOT_FOUND", "DeathMasterMatch %s does not exist" % matchId)
    if m["status"] != "PENDING_REVIEW":
        fail("ERR_MATCH_NOT_PENDING_REVIEW", "Manual review requires the match to be PENDING_REVIEW")
    m["status"] = review_outcome
    touch(m)
    if review_outcome == "CONFIRMED":
        p = db.policies.get(m["policy_id"])
        if p is not None:
            _maybe_generate_claim(p, m)
    return ok_object(ser_match(m))


# ---------------------------------------------------------------------------
# EscheatmentCase
# ---------------------------------------------------------------------------

@bp.get("/escheatment-cases")
def list_cases():
    auth(*ALL_GET)
    items = list(db.cases.values())
    cid = _qs("claim_id")
    if cid is not None:
        items = [c for c in items if c["claim_id"] == cid]
    aid = _qs("account_id")
    if aid is not None:
        items = [c for c in items if c["account_id"] == aid]
    st = _qs("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    sty = _qs("subject_type")
    if sty is not None:
        items = [c for c in items if c["subject_type"] == sty]
    return list_response(items, ser_case)


@bp.get("/escheatment-cases/<caseId>")
def get_case(caseId):
    auth(*ALL_GET)
    c = db.cases.get(caseId)
    if c is None:
        fail("ERR_CASE_NOT_FOUND", "EscheatmentCase %s does not exist" % caseId)
    return ok_object(ser_case(c))


@bp.post("/escheatment-cases/<caseId>/resolve")
def resolve_case(caseId):
    auth("ComplianceOfficer")
    data = json_body()
    resolution_note = opt_string(data, "resolution_note")
    c = db.cases.get(caseId)
    if c is None:
        fail("ERR_CASE_NOT_FOUND", "EscheatmentCase %s does not exist" % caseId)
    if c["status"] not in ("MONITORING", "DUE_DILIGENCE"):
        fail("ERR_CASE_NOT_ACTIONABLE", "resolve requires MONITORING or DUE_DILIGENCE")
    c["status"] = "RESOLVED"
    c["resolution_note"] = resolution_note
    if c["subject_type"] == "RETAINED_ASSET_ACCOUNT" and c["account_id"]:
        a = db.accounts.get(c["account_id"])
        if a is not None and a["status"] == "DORMANT":
            a["status"] = "OPEN"
            a["last_activity_at"] = db.now
            touch(a)
    touch(c)
    return ok_object(ser_case(c))


@bp.post("/escheatment-cases/<caseId>/escheat")
def escheat_case(caseId):
    auth("ComplianceOfficer")
    c = db.cases.get(caseId)
    if c is None:
        fail("ERR_CASE_NOT_FOUND", "EscheatmentCase %s does not exist" % caseId)
    if c["status"] != "DUE_DILIGENCE":
        fail("ERR_CASE_NOT_ACTIONABLE", "escheat requires DUE_DILIGENCE")
    if db.now.date() < c["escheat_due_date"]:
        fail("ERR_ESCHEATMENT_NOT_DUE", "Escheatment is not yet due")
    if c["subject_type"] == "CLAIM_PROCEEDS":
        claim = db.claims.get(c["claim_id"])
        if claim is not None:
            paid_sum = sum(
                b["paid_amount_cents"] or 0
                for b in bcs_of_claim(claim["id"])
                if b["status"] == "PAID"
            )
            c["amount_cents"] = (claim["total_payable_cents"] or 0) - paid_sum
            claim["status"] = "ESCHEATED"
            for b in bcs_of_claim(claim["id"]):
                if b["status"] in ("VALIDATED", "PAYABLE"):
                    b["status"] = "ESCHEATED"
                    touch(b)
            for e in elections_of_claim(claim["id"]):
                if e["status"] in ("ELECTED", "CONFIRMED", "SUSPENDED"):
                    e["status"] = "SUPERSEDED"
                    touch(e)
            touch(claim)
    else:  # RETAINED_ASSET_ACCOUNT
        a = db.accounts.get(c["account_id"])
        if a is not None:
            interest = raa_final_yield(a, a["balance_cents"], db.now.date())
            a["interest_paid_cents"] = interest
            c["amount_cents"] = a["balance_cents"] + interest
            a["status"] = "ESCHEATED"
            touch(a)
    c["status"] = "ESCHEATED"
    touch(c)
    return ok_object(ser_case(c))
