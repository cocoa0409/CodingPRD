"""Routes: claims, death documents, beneficiary claims, payout elections."""

from datetime import timedelta

from flask import Blueprint, request

from domain import (
    ELECTION_WINDOW_DAYS,
    TERMINAL_CLAIM_STATES,
    bcs_of_claim,
    create_escheatment_case,
    designation_of,
    docs_complete,
    docs_of_claim,
    elections_of_claim,
    enter_legal_hold,
    reject_open_beneficiary_claims,
    release_hold_if_clear,
    run_allocation,
    ser_beneficiary_claim,
    ser_claim,
    ser_document,
    ser_election,
    share_of,
    statutory_interest,
    contestability_flag,
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

bp = Blueprint("claims", __name__)

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


def _get_claim_or_404(claim_id):
    c = db.claims.get(claim_id)
    if c is None:
        fail("ERR_CLAIM_NOT_FOUND", "Claim %s does not exist" % claim_id)
    return c


def _get_bc_or_404(bc_id):
    b = db.beneficiary_claims.get(bc_id)
    if b is None:
        fail("ERR_BENEFICIARY_CLAIM_NOT_FOUND", "BeneficiaryClaim %s does not exist" % bc_id)
    return b


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

@bp.post("/claims")
def create_claim():
    uid = auth("ClaimsExaminer")
    data = json_body()
    policy_id = req_string(data, "policy_id")
    date_of_death = req_date(data, "date_of_death")
    cause_of_death = opt_string(data, "cause_of_death")
    # existence
    p = db.policies.get(policy_id)
    if p is None:
        fail("ERR_POLICY_NOT_FOUND", "Policy %s does not exist" % policy_id)
    # temporal (priority 9): date_of_death within [issue_date, logical today]
    if date_of_death < p["issue_date"] or date_of_death > db.now.date():
        fail(
            "ERR_INVALID_DEATH_DATE",
            "date_of_death must be on or after the policy issue_date and not in the future",
        )
    # referential (priority 11): statute configured for the policy's state
    if p["state_code"] not in db.statutes:
        fail("ERR_STATUTE_NOT_CONFIGURED", "No StateStatute configured for %s" % p["state_code"])
    c = new_record()
    c.update(
        {
            "policy_id": p["id"],
            "state_code": p["state_code"],
            "date_of_death": date_of_death,
            "cause_of_death": cause_of_death,
            "notification_date": db.now.date(),
            "assigned_examiner_id": uid,
            "contestability_flag": contestability_flag(p, date_of_death),
            "proof_complete_date": None,
            "face_amount_cents": p["face_amount_cents"],
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
    return ok_object(ser_claim(c), 201)


@bp.get("/claims")
def list_claims():
    auth(*ALL_GET)
    items = list(db.claims.values())
    pid = _qs("policy_id")
    if pid is not None:
        items = [c for c in items if c["policy_id"] == pid]
    st = _qs("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    return list_response(items, ser_claim)


@bp.get("/claims/<claimId>")
def get_claim(claimId):
    auth(*ALL_GET)
    return ok_object(ser_claim(_get_claim_or_404(claimId)))


@bp.post("/claims/<claimId>/begin-review")
def begin_review(claimId):
    auth("ClaimsExaminer")
    c = _get_claim_or_404(claimId)
    if c["status"] != "NOTIFIED":
        fail("ERR_CLAIM_NOT_REVIEWABLE", "begin-review requires the claim to be NOTIFIED")
    # routing fork on contestability
    c["status"] = "CONTESTABILITY_REVIEW" if c["contestability_flag"] else "UNDER_REVIEW"
    touch(c)
    return ok_object(ser_claim(c))


@bp.post("/claims/<claimId>/approve")
def approve_claim(claimId):
    uid = auth("ClaimsApprover")
    c = _get_claim_or_404(claimId)
    # state (LEGAL_HOLD takes precedence over generic review-state errors)
    if c["status"] == "LEGAL_HOLD":
        fail("ERR_CLAIM_IN_LEGAL_HOLD", "Claim is in LEGAL_HOLD")
    if c["status"] not in ("UNDER_REVIEW", "CONTESTABILITY_REVIEW"):
        fail("ERR_CLAIM_NOT_UNDER_REVIEW", "approve requires UNDER_REVIEW or CONTESTABILITY_REVIEW")
    # segregation of duties
    if c["assigned_examiner_id"] is not None and uid == c["assigned_examiner_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION", "Approver must differ from the assigned examiner")
    # required proof set fully VERIFIED
    if not docs_complete(c):
        fail("ERR_REQUIRED_DOCS_INCOMPLETE", "The required proof-of-death set is not fully VERIFIED")
    # approve: stamp, quantify interest, fix the total
    c["status"] = "APPROVED"
    c["approved_at"] = db.now.date()
    c["accrued_interest_cents"] = statutory_interest(c, c["approved_at"])
    c["total_payable_cents"] = c["face_amount_cents"] + c["accrued_interest_cents"]
    # allocation waterfall over the VALIDATED pool
    pool = run_allocation(c, {"VALIDATED"}, promote_validated=True)
    if not pool:
        # proceeds unclaimed -> open a CLAIM_PROCEEDS escheatment case
        create_escheatment_case(c, "CLAIM_PROCEEDS", c["approved_at"], c["total_payable_cents"])
    touch(c)
    return ok_object(ser_claim(c))


@bp.post("/claims/<claimId>/deny")
def deny_claim(claimId):
    uid = auth("ClaimsApprover")
    data = json_body()
    denial_reason = req_string(data, "denial_reason")
    c = _get_claim_or_404(claimId)
    if c["status"] == "LEGAL_HOLD":
        fail("ERR_CLAIM_IN_LEGAL_HOLD", "Claim is in LEGAL_HOLD")
    if c["status"] not in ("UNDER_REVIEW", "CONTESTABILITY_REVIEW"):
        fail("ERR_CLAIM_NOT_UNDER_REVIEW", "deny requires UNDER_REVIEW or CONTESTABILITY_REVIEW")
    if c["assigned_examiner_id"] is not None and uid == c["assigned_examiner_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION", "Approver must differ from the assigned examiner")
    c["status"] = "DENIED"
    c["denial_reason"] = denial_reason
    reject_open_beneficiary_claims(c, "CLAIM_DENIED")
    touch(c)
    return ok_object(ser_claim(c))


@bp.post("/claims/<claimId>/rescind")
def rescind_claim(claimId):
    uid = auth("ClaimsApprover")
    data = json_body()
    rescission_reason = req_string(data, "rescission_reason")
    c = _get_claim_or_404(claimId)
    if c["status"] != "CONTESTABILITY_REVIEW":
        fail("ERR_CLAIM_NOT_IN_CONTESTABILITY_REVIEW", "rescind requires CONTESTABILITY_REVIEW")
    if c["assigned_examiner_id"] is not None and uid == c["assigned_examiner_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION", "Approver must differ from the assigned examiner")
    c["status"] = "RESCINDED"
    c["rescission_reason"] = rescission_reason
    reject_open_beneficiary_claims(c, "POLICY_RESCINDED")
    touch(c)
    return ok_object(ser_claim(c))


@bp.post("/claims/<claimId>/refer-interpleader")
def refer_interpleader(claimId):
    auth("LegalCounsel")
    data = json_body()
    court_reference = req_string(data, "court_reference")
    c = _get_claim_or_404(claimId)
    if c["status"] != "LEGAL_HOLD":
        fail("ERR_CLAIM_NOT_IN_LEGAL_HOLD", "refer-interpleader requires LEGAL_HOLD")
    c["court_reference"] = court_reference
    c["status"] = "INTERPLEADED"
    # interest accrual freezes as of the referral date
    c["accrued_interest_cents"] = statutory_interest(c, db.now.date())
    for b in bcs_of_claim(c["id"]):
        if b["status"] == "DISPUTED":
            b["status"] = "INTERPLEADED"
            touch(b)
    for e in elections_of_claim(c["id"]):
        if e["status"] in ("ELECTED", "CONFIRMED", "SUSPENDED"):
            e["status"] = "SUPERSEDED"
            touch(e)
    touch(c)
    return ok_object(ser_claim(c))


@bp.post("/claims/<claimId>/execute-payment")
def execute_payment(claimId):
    auth("ClaimsApprover")
    c = _get_claim_or_404(claimId)
    if c["status"] == "LEGAL_HOLD":
        fail("ERR_CLAIM_IN_LEGAL_HOLD", "Claim is in LEGAL_HOLD")
    if c["status"] != "APPROVED":
        fail("ERR_CLAIM_NOT_APPROVED", "execute-payment requires the claim to be APPROVED")
    # final statutory interest recompute as of the payment date, then re-run allocation
    c["accrued_interest_cents"] = statutory_interest(c, db.now.date())
    c["total_payable_cents"] = c["face_amount_cents"] + c["accrued_interest_cents"]
    run_allocation(c, {"VALIDATED", "PAYABLE", "PAID"}, promote_validated=True)
    touch(c)
    # there must be at least one PAYABLE beneficiary claim holding a CONFIRMED election
    payable = [b for b in bcs_of_claim(c["id"]) if b["status"] == "PAYABLE"]
    def _confirmed_election(b):
        conf = [e for e in db.elections.values() if e["beneficiary_claim_id"] == b["id"] and e["status"] == "CONFIRMED"]
        return sorted(conf, key=lambda e: (e["created_at"], e["id"]))[-1] if conf else None
    candidates = [(b, _confirmed_election(b)) for b in payable]
    candidates = [(b, e) for (b, e) in candidates if e is not None]
    if not candidates:
        fail("ERR_NO_PAYABLE_BENEFICIARIES", "No PAYABLE beneficiary claim holds a CONFIRMED election")
    candidates.sort(key=lambda be: (be[0]["created_at"], be[0]["id"]))
    for b, e in candidates:
        b["paid_amount_cents"] = b["allocated_amount_cents"]
        b["status"] = "PAID"
        if e["option"] == "RETAINED_ASSET_ACCOUNT":
            acc = new_record()
            acc.update(
                {
                    "claim_id": c["id"],
                    "beneficiary_claim_id": b["id"],
                    "deposited_cents": b["paid_amount_cents"],
                    "balance_cents": b["paid_amount_cents"],
                    "withdrawn_total_cents": 0,
                    "interest_paid_cents": 0,
                    "last_activity_at": db.now,
                    "status": "OPEN",
                }
            )
            db.accounts[acc["id"]] = acc
        touch(b)
    # bubble-up: every PAYABLE has reached PAID and proceeds fully distributed
    remaining = [b for b in bcs_of_claim(c["id"]) if b["status"] == "PAYABLE"]
    paid_sum = sum(b["paid_amount_cents"] or 0 for b in bcs_of_claim(c["id"]) if b["status"] == "PAID")
    if not remaining and paid_sum == c["total_payable_cents"]:
        c["status"] = "PAID"
        c["paid_at"] = db.now.date()
        touch(c)
    return ok_object(ser_claim(c))


# ---------------------------------------------------------------------------
# DeathDocument
# ---------------------------------------------------------------------------

DOC_TYPES = {"CERTIFIED_DEATH_CERTIFICATE", "ATTENDING_PHYSICIAN_STATEMENT", "FUNERAL_HOME_STATEMENT"}


@bp.post("/claims/<claimId>/documents")
def upload_document(claimId):
    uid = auth("ClaimsExaminer")
    data = json_body()
    doc_type = req_enum(data, "doc_type", DOC_TYPES)
    c = _get_claim_or_404(claimId)
    d = new_record()
    d.update(
        {
            "claim_id": c["id"],
            "doc_type": doc_type,
            "uploaded_by_id": uid,
            "review_result": "PENDING",
            "reviewed_by_id": None,
            "rejection_reason": None,
        }
    )
    db.documents[d["id"]] = d
    return ok_object(ser_document(d), 201)


@bp.get("/claims/<claimId>/documents")
def list_documents(claimId):
    auth(*ALL_GET)
    c = _get_claim_or_404(claimId)
    items = docs_of_claim(c["id"])
    rr = _qs("review_result")
    if rr is not None:
        items = [d for d in items if d["review_result"] == rr]
    dt = _qs("doc_type")
    if dt is not None:
        items = [d for d in items if d["doc_type"] == dt]
    return list_response(items, ser_document)


@bp.post("/claims/<claimId>/documents/<documentId>/review")
def review_document(claimId, documentId):
    uid = auth("ClaimsExaminer")
    data = json_body()
    review_result = req_enum(data, "review_result", {"VERIFIED", "REJECTED"})
    rejection_reason = opt_string(data, "rejection_reason")
    if review_result == "REJECTED" and not rejection_reason:
        fail("ERR_INVALID_REQUEST", "rejection_reason is required when review_result is REJECTED")
    c = _get_claim_or_404(claimId)
    d = next(
        (x for x in db.documents.values() if x["id"] == documentId and x["claim_id"] == c["id"]),
        None,
    )
    if d is None:
        fail("ERR_DOCUMENT_NOT_FOUND", "DeathDocument %s does not exist within the claim" % documentId)
    if d["review_result"] != "PENDING":
        fail("ERR_DOCUMENT_ALREADY_REVIEWED", "Document has already been reviewed")
    if uid == d["uploaded_by_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION", "Reviewer must differ from the uploader")
    d["review_result"] = review_result
    d["reviewed_by_id"] = uid
    d["rejection_reason"] = rejection_reason if review_result == "REJECTED" else None
    touch(d)
    # recompute proof_complete_date: the date the required set became fully VERIFIED
    complete = docs_complete(c)
    if complete and c["proof_complete_date"] is None:
        c["proof_complete_date"] = db.now.date()
        touch(c)
    elif not complete and c["proof_complete_date"] is not None:
        c["proof_complete_date"] = None
        touch(c)
    return ok_object(ser_document(d))


# ---------------------------------------------------------------------------
# BeneficiaryClaim
# ---------------------------------------------------------------------------

@bp.post("/claims/<claimId>/beneficiary-claims")
def file_beneficiary_claim(claimId):
    auth("ClaimsExaminer")
    data = json_body()
    claimant_name = req_string(data, "claimant_name")
    claimant_type = req_enum(data, "claimant_type", {"NAMED_BENEFICIARY", "ESTATE"})
    designation_id = opt_string(data, "designation_id")
    if claimant_type == "NAMED_BENEFICIARY" and designation_id is None:
        fail("ERR_INVALID_REQUEST", "designation_id is required for a NAMED_BENEFICIARY claimant")
    # existence, left to right
    c = _get_claim_or_404(claimId)
    designation = None
    if designation_id is not None:
        designation = db.designations.get(designation_id)
        if designation is None:
            fail("ERR_DESIGNATION_NOT_FOUND", "BeneficiaryDesignation %s does not exist" % designation_id)
    # state
    if c["status"] in TERMINAL_CLAIM_STATES:
        fail("ERR_CLAIM_NOT_FILEABLE", "Beneficiary claims cannot be filed on a terminal claim")
    if c["status"] == "LEGAL_HOLD":
        fail("ERR_CLAIM_IN_LEGAL_HOLD", "Claim is in LEGAL_HOLD")
    # referential: policy ownership is enforced at filing; the active-at-death
    # window is enforced at validation (filing itself is always accepted)
    if designation is not None:
        _check_designation_policy_match(designation, c)
    b = new_record()
    b.update(
        {
            "claim_id": c["id"],
            "designation_id": designation_id,
            "claimant_name": claimant_name,
            "claimant_type": claimant_type,
            "allocated_amount_cents": None,
            "paid_amount_cents": None,
            "rejection_reason": None,
            "status": "SUBMITTED",
        }
    )
    db.beneficiary_claims[b["id"]] = b
    # rival-dispute cascade: a rival on the same designation standing VALIDATED/PAYABLE
    # under a different claimant_name is cascaded to DISPUTED, and the claim is held.
    if designation_id is not None:
        rivals = [
            x
            for x in bcs_of_claim(c["id"])
            if x["id"] != b["id"]
            and x["designation_id"] == designation_id
            and x["status"] in ("VALIDATED", "PAYABLE")
            and x["claimant_name"] != claimant_name
        ]
        if rivals:
            for r in rivals:
                r["status"] = "DISPUTED"
                touch(r)
            enter_legal_hold(c)
    return ok_object(ser_beneficiary_claim(b), 201)


@bp.get("/claims/<claimId>/beneficiary-claims")
def list_beneficiary_claims_of_claim(claimId):
    auth(*ALL_GET)
    c = _get_claim_or_404(claimId)
    items = bcs_of_claim(c["id"])
    st = _qs("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    return list_response(items, ser_beneficiary_claim)


@bp.get("/beneficiary-claims")
def list_beneficiary_claims():
    auth(*ALL_GET)
    items = list(db.beneficiary_claims.values())
    cid = _qs("claim_id")
    if cid is not None:
        items = [b for b in items if b["claim_id"] == cid]
    did = _qs("designation_id")
    if did is not None:
        items = [b for b in items if b["designation_id"] == did]
    st = _qs("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    return list_response(items, ser_beneficiary_claim)


@bp.get("/beneficiary-claims/<beneficiaryClaimId>")
def get_beneficiary_claim(beneficiaryClaimId):
    auth(*ALL_GET)
    return ok_object(ser_beneficiary_claim(_get_bc_or_404(beneficiaryClaimId)))


def _check_designation_policy_match(designation, claim):
    if designation["policy_id"] != claim["policy_id"]:
        fail("ERR_DESIGNATION_POLICY_MISMATCH", "Designation belongs to a different policy than the claim")


def _check_designation_active_at_death(designation, claim):
    dod = claim["date_of_death"]
    if dod < designation["effective_date"]:
        fail("ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH", "Designation was not ACTIVE on the date of death")
    if designation["revoked_at"] is not None and not (dod < designation["revoked_at"].date()):
        fail("ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH", "Designation was not ACTIVE on the date of death")


@bp.post("/beneficiary-claims/<beneficiaryClaimId>/validate")
def validate_beneficiary_claim(beneficiaryClaimId):
    auth("ClaimsExaminer")
    b = _get_bc_or_404(beneficiaryClaimId)
    if b["status"] not in ("SUBMITTED", "DISPUTED"):
        fail("ERR_BENEFICIARY_CLAIM_INVALID_STATE", "validate requires SUBMITTED or DISPUTED")
    c = claim_of(b)
    if c["status"] in TERMINAL_CLAIM_STATES:
        fail("ERR_CLAIM_NOT_FILEABLE", "Validation requires a non-terminal claim")
    # (LEGAL_HOLD deliberately does NOT block validation — it is the dispute-resolution path)
    designation = designation_of(b)
    # structural: designation exclusivity
    if designation is not None:
        for x in bcs_of_claim(c["id"]):
            if (
                x["id"] != b["id"]
                and x["designation_id"] == designation["id"]
                and x["status"] in ("VALIDATED", "PAYABLE")
            ):
                fail("ERR_DESIGNATION_ALREADY_CLAIMED", "Another VALIDATED/PAYABLE claim holds this designation")
    # structural: aggregate capacity over VALIDATED + PAYABLE + candidate
    used = sum(
        share_of(x)
        for x in bcs_of_claim(c["id"])
        if x["status"] in ("VALIDATED", "PAYABLE")
    )
    if used + share_of(b) > 100:
        fail("ERR_ALLOCATION_CAPACITY_EXCEEDED", "Aggregate validated share capacity would exceed 100")
    # referential
    if designation is not None:
        _check_designation_policy_match(designation, c)
        _check_designation_active_at_death(designation, c)
    was_disputed = b["status"] == "DISPUTED"
    b["status"] = "VALIDATED"
    touch(b)
    if was_disputed:
        release_hold_if_clear(c)
    return ok_object(ser_beneficiary_claim(b))


@bp.post("/beneficiary-claims/<beneficiaryClaimId>/reject")
def reject_beneficiary_claim(beneficiaryClaimId):
    auth("ClaimsExaminer")
    data = json_body()
    rejection_reason = req_string(data, "rejection_reason")
    b = _get_bc_or_404(beneficiaryClaimId)
    if b["status"] not in ("SUBMITTED", "VALIDATED", "DISPUTED"):
        fail("ERR_BENEFICIARY_CLAIM_INVALID_STATE", "reject requires SUBMITTED, VALIDATED, or DISPUTED")
    was_disputed = b["status"] == "DISPUTED"
    b["status"] = "REJECTED"
    b["rejection_reason"] = rejection_reason
    touch(b)
    if was_disputed:
        release_hold_if_clear(claim_of(b))
    return ok_object(ser_beneficiary_claim(b))


@bp.post("/beneficiary-claims/<beneficiaryClaimId>/withdraw")
def withdraw_beneficiary_claim(beneficiaryClaimId):
    auth("ClaimsExaminer")
    b = _get_bc_or_404(beneficiaryClaimId)
    if b["status"] not in ("SUBMITTED", "DISPUTED"):
        fail("ERR_BENEFICIARY_CLAIM_INVALID_STATE", "withdraw requires SUBMITTED or DISPUTED")
    was_disputed = b["status"] == "DISPUTED"
    b["status"] = "WITHDRAWN"
    touch(b)
    if was_disputed:
        release_hold_if_clear(claim_of(b))
    return ok_object(ser_beneficiary_claim(b))


def claim_of(b):
    return db.claims[b["claim_id"]]


# ---------------------------------------------------------------------------
# PayoutElection
# ---------------------------------------------------------------------------

@bp.post("/beneficiary-claims/<beneficiaryClaimId>/elections")
def create_election(beneficiaryClaimId):
    auth("ClaimsExaminer")
    data = json_body()
    option = req_enum(data, "option", {"LUMP_SUM", "RETAINED_ASSET_ACCOUNT"})
    expected_claim_version = req_int(data, "expected_claim_version")
    b = _get_bc_or_404(beneficiaryClaimId)
    c = claim_of(b)
    # OCC
    if expected_claim_version != c["version"]:
        fail("ERR_STALE_CLAIM_VERSION", "expected_claim_version does not match the current claim version")
    # state
    if c["status"] == "LEGAL_HOLD":
        fail("ERR_CLAIM_IN_LEGAL_HOLD", "Claim is in LEGAL_HOLD")
    if b["status"] != "PAYABLE":
        fail("ERR_BENEFICIARY_CLAIM_NOT_PAYABLE", "Election requires the beneficiary claim to be PAYABLE")
    if c["status"] != "APPROVED":
        fail("ERR_CLAIM_NOT_APPROVED", "Election requires the claim to be APPROVED")
    # temporal: election window = claim.approved_at + 30 days
    if db.now.date() > c["approved_at"] + timedelta(days=ELECTION_WINDOW_DAYS):
        fail("ERR_ELECTION_WINDOW_CLOSED", "The election window has closed")
    # fiscal: retained-asset minimum
    if option == "RETAINED_ASSET_ACCOUNT":
        statute = db.statutes.get(c["state_code"])
        minimum = statute["raa_minimum_cents"] if statute else 0
        if (b["allocated_amount_cents"] or 0) < minimum:
            fail("ERR_BELOW_RAA_MINIMUM", "Allocated amount is below the statute's RAA minimum")
    # supersede the beneficiary's prior non-SUPERSEDED elections
    for e in db.elections.values():
        if e["beneficiary_claim_id"] == b["id"] and e["status"] in ("ELECTED", "CONFIRMED", "SUSPENDED"):
            e["status"] = "SUPERSEDED"
            touch(e)
    e = new_record()
    e.update(
        {
            "beneficiary_claim_id": b["id"],
            "option": option,
            "status": "ELECTED",
            "elected_at": db.now,
            "confirmed_at": None,
        }
    )
    db.elections[e["id"]] = e
    touch(c)  # election creation increments the claim's version
    return ok_object(ser_election(e), 201)


@bp.get("/beneficiary-claims/<beneficiaryClaimId>/elections")
def list_elections(beneficiaryClaimId):
    auth(*ALL_GET)
    b = _get_bc_or_404(beneficiaryClaimId)
    items = [e for e in db.elections.values() if e["beneficiary_claim_id"] == b["id"]]
    st = _qs("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    return list_response(items, ser_election)


@bp.post("/payout-elections/<electionId>/confirm")
def confirm_election(electionId):
    auth("ClaimsExaminer")
    e = db.elections.get(electionId)
    if e is None:
        fail("ERR_ELECTION_NOT_FOUND", "PayoutElection %s does not exist" % electionId)
    if e["status"] != "ELECTED":
        fail("ERR_ELECTION_NOT_CONFIRMABLE", "confirm requires the election to be ELECTED")
    b = db.beneficiary_claims[e["beneficiary_claim_id"]]
    c = db.claims[b["claim_id"]]
    if db.now.date() > c["approved_at"] + timedelta(days=ELECTION_WINDOW_DAYS):
        fail("ERR_ELECTION_WINDOW_CLOSED", "The election window has closed")
    e["status"] = "CONFIRMED"
    e["confirmed_at"] = db.now
    touch(e)
    return ok_object(ser_election(e))
