"""Claim lifecycle: submit, adjudicate, deny, correct, appeal, void; ClaimLine
listing (PRD 3.7, 3.8, 3.9)."""
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

bp = Blueprint("claims", __name__)

DENIAL_REASONS = {"CODING_ERROR", "NOT_COVERED", "TIMELY_FILING", "DUPLICATE"}
ADJUDICABLE_FROM = {"SUBMITTED", "CORRECTED", "APPEALED"}


def _accumulator_for_policy(policy_id):
    matches = [a for a in db.benefit_accumulators.values() if a["policy_id"] == policy_id]
    if not matches:
        return None
    return max(matches, key=lambda a: a["_seq"])


# --------------------------------------------------------------------------
# Submit a claim
# --------------------------------------------------------------------------
@bp.route("/encounters/<eid>/claims", methods=["POST"])
def submit_claim(eid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    enc = db.encounters.get(eid)
    if enc is None:
        raise errors.not_found()
    body = validate.get_body()

    # body FK: payer_id must exist
    payer_id = body.get("payer_id")
    if payer_id is None:
        raise errors.invalid_request("payer_id is required.")
    if not isinstance(payer_id, str):
        raise errors.invalid_request("payer_id must be a string.")
    if payer_id not in db.payers:
        raise errors.reference_not_found("payer_id does not reference an existing payer.")

    # body validation: expected_encounter_version present and typed
    if "expected_encounter_version" not in body:
        raise errors.invalid_request("expected_encounter_version is required.")
    expected_version = body["expected_encounter_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise errors.invalid_request("expected_encounter_version must be an integer.")

    # state gate (priority 6): claim submission requires the encounter to be CODED
    if enc["status"] != "CODED":
        raise errors.coding_not_cleared("The encounter's coding has not been cleared (encounter not CODED).")

    # business referential: encounter must have insurance attached
    if enc.get("policy_id") is None:
        raise errors.no_policy_on_encounter("The encounter has no policy attached.")

    # business safety: payer must be active
    payer = db.payers[payer_id]
    if not payer["active"]:
        raise errors.payer_inactive("The payer is not accepting claims.")

    # business temporal: timely filing measured from discharge_at
    discharge_at = enc.get("discharge_at")
    if discharge_at is not None:
        elapsed = timeutil.days_between(clock.now(), timeutil.parse_iso(discharge_at))
        if elapsed > payer["timely_filing_days"]:
            raise errors.timely_filing_exceeded("The claim is past the payer's timely filing window.")

    # business fiscal: OCC against the encounter version
    if expected_version != enc["version"]:
        raise errors.stale_encounter_version()

    rec = db.base_record(common_fields=True)
    rec.update({
        "encounter_id": eid,
        "policy_id": enc["policy_id"],
        "payer_id": payer_id,
        "billed_amount_cents": enc["total_charges_cents"],
        "allowed_amount_cents": None,
        "status": "SUBMITTED",
        "denial_reason": None,
        "submitted_at": clock.now_iso(),
        "patient_responsibility_cents": 0,
    })
    db.claims[rec["id"]] = rec
    # submission advances the encounter version by 1
    db.touch(enc)
    return response.object_response(rec, 201)


@bp.route("/encounters/<eid>/claims", methods=["GET"])
def list_encounter_claims(eid):
    authenticate()
    if eid not in db.encounters:
        raise errors.not_found()
    recs = [c for c in db.claims.values() if c["encounter_id"] == eid]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


@bp.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    authenticate()
    rec = db.claims.get(cid)
    if rec is None:
        raise errors.not_found()
    return response.object_response(rec, 200)


@bp.route("/claims", methods=["GET"])
def list_claims():
    authenticate()
    policy_id = request.args.get("policy_id")
    payer_id = request.args.get("payer_id")
    status = request.args.get("status")
    recs = list(db.claims.values())
    if policy_id is not None:
        recs = [r for r in recs if r["policy_id"] == policy_id]
    if payer_id is not None:
        recs = [r for r in recs if r["payer_id"] == payer_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


# --------------------------------------------------------------------------
# Adjudicate
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    claim = db.claims.get(cid)
    if claim is None:
        raise errors.not_found()
    body = validate.get_body()

    # body validation
    allowed = validate.require_int(body, "allowed_amount_cents")
    if allowed < 0:
        raise errors.invalid_request("allowed_amount_cents must be >= 0.")
    claim_lines = body.get("claim_lines")
    if not isinstance(claim_lines, list) or len(claim_lines) == 0:
        raise errors.invalid_request("claim_lines must be a non-empty list.")
    parsed_lines = []
    for line in claim_lines:
        if not isinstance(line, dict):
            raise errors.invalid_request("each claim line must be an object.")
        cpt = line.get("cpt_code")
        if not isinstance(cpt, str) or len(cpt) != 5 or not cpt.isalnum():
            raise errors.invalid_request("each claim line cpt_code must be a 5-character alphanumeric code.")
        la = line.get("line_allowed_cents")
        if not isinstance(la, int) or isinstance(la, bool) or la < 0:
            raise errors.invalid_request("each claim line line_allowed_cents must be an integer >= 0.")
        parsed_lines.append({"cpt_code": cpt, "line_allowed_cents": la})

    # state gate
    if claim["status"] not in ADJUDICABLE_FROM:
        raise errors.invalid_state("Adjudication is only defined from SUBMITTED, CORRECTED, or APPEALED status.")

    # business constraint: lines must sum exactly to allowed_amount_cents
    if sum(l["line_allowed_cents"] for l in parsed_lines) != allowed:
        raise errors.claim_lines_mismatch("Claim lines do not sum to allowed_amount_cents.")

    enc = db.encounters.get(claim["encounter_id"])
    policy = db.insurance_policies.get(claim["policy_id"])
    accum = _accumulator_for_policy(claim["policy_id"])
    if accum is None:
        accum = {"deductible_met_cents": 0, "oop_met_cents": 0}

    patient_resp, deductible_applied = calculations.final_patient_responsibility(allowed, policy, accum)

    # record allowed and create claim lines (with derived line_paid_cents)
    claim["allowed_amount_cents"] = allowed
    _create_claim_lines(claim, parsed_lines, allowed, patient_resp)
    claim["patient_responsibility_cents"] = patient_resp

    # advance the accumulator by the patient-applied portions (never past limits)
    if accum is not None and "id" in accum:
        accum["deductible_met_cents"] = min(
            policy["deductible_cents"], accum["deductible_met_cents"] + deductible_applied
        )
        accum["oop_met_cents"] = min(
            policy["oop_max_cents"], accum["oop_met_cents"] + patient_resp
        )
        db.touch(accum)

    if patient_resp == 0:
        claim["status"] = "PAID"
        # cascade: encounter CODED -> BILLED with patient_responsibility = 0
        _cascade_to_billed(enc, 0)
    else:
        claim["status"] = "PARTIALLY_PAID"
        _cascade_to_billed(enc, patient_resp)
        _issue_statement(enc)
    db.touch(claim)
    return response.object_response(claim, 200)


def _create_claim_lines(claim, parsed_lines, allowed, patient_resp):
    """Create ClaimLine rows. line_paid_cents = line_allowed_cents minus that
    line's share of patient responsibility. Patient responsibility is allocated
    across lines proportionally to line_allowed_cents, with the rounding
    remainder assigned to the last line so the shares sum to patient_resp."""
    n = len(parsed_lines)
    shares = [0] * n
    if patient_resp > 0 and allowed > 0:
        allocated = 0
        for i, line in enumerate(parsed_lines):
            if i < n - 1:
                share = (patient_resp * line["line_allowed_cents"]) // allowed
                shares[i] = share
                allocated += share
            else:
                shares[i] = patient_resp - allocated
    for i, line in enumerate(parsed_lines):
        rec = db.base_record(common_fields=True)
        rec.update({
            "claim_id": claim["id"],
            "cpt_code": line["cpt_code"],
            "line_allowed_cents": line["line_allowed_cents"],
            "line_paid_cents": line["line_allowed_cents"] - shares[i],
        })
        db.claim_lines[rec["id"]] = rec


def _cascade_to_billed(enc, patient_resp):
    """Advance the encounter CODED -> BILLED, set patient_responsibility, and
    recompute account_balance. Fires only from CODED (PRD 2.9)."""
    if enc is None or enc["status"] != "CODED":
        return
    enc["patient_responsibility_cents"] = patient_resp
    services.recompute_account_balance(enc)
    enc["status"] = "BILLED"
    db.touch(enc)


def _issue_statement(enc):
    """Create a PatientStatement (status ISSUED) for the encounter (PRD 3.10)."""
    stmt = db.base_record(common_fields=True)
    stmt.update({
        "encounter_id": enc["id"],
        "amount_due_cents": enc["patient_responsibility_cents"],
        "amount_paid_cents": 0,
        "written_off_cents": 0,
        "status": "ISSUED",
        "issued_at": clock.now_iso(),
    })
    db.patient_statements[stmt["id"]] = stmt
    return stmt


# --------------------------------------------------------------------------
# Deny
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    claim = db.claims.get(cid)
    if claim is None:
        raise errors.not_found()
    body = validate.get_body()
    denial_reason = validate.require_enum(body, "denial_reason", DENIAL_REASONS)

    if claim["status"] not in ADJUDICABLE_FROM:
        raise errors.invalid_state("Denial is only defined from SUBMITTED, CORRECTED, or APPEALED status.")

    enc = db.encounters.get(claim["encounter_id"])
    claim["denial_reason"] = denial_reason
    claim["status"] = "DENIED"
    # cascade: encounter CODED -> BILLED with full balance billed to patient
    if enc is not None and enc["status"] == "CODED":
        enc["patient_responsibility_cents"] = enc["total_charges_cents"]
        services.recompute_account_balance(enc)
        enc["status"] = "BILLED"
        db.touch(enc)
        _issue_statement(enc)
    db.touch(claim)
    return response.object_response(claim, 200)


# --------------------------------------------------------------------------
# Correct
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/correct", methods=["POST"])
def correct_claim(cid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    claim = db.claims.get(cid)
    if claim is None:
        raise errors.not_found()
    if claim["status"] != "DENIED":
        raise errors.invalid_state("Correction is only defined from DENIED status.")
    if claim["denial_reason"] != "CODING_ERROR":
        raise errors.not_correctable("Only a CODING_ERROR denial may be corrected.")

    claim["status"] = "CORRECTED"
    _reverse_denial_cascade(claim)
    db.touch(claim)
    return response.object_response(claim, 200)


# --------------------------------------------------------------------------
# Appeal
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/appeal", methods=["POST"])
def appeal_claim(cid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    claim = db.claims.get(cid)
    if claim is None:
        raise errors.not_found()
    if claim["status"] != "DENIED":
        raise errors.invalid_state("Appeal is only defined from DENIED status.")
    if claim["denial_reason"] not in ("NOT_COVERED", "TIMELY_FILING"):
        raise errors.not_appealable("Only NOT_COVERED or TIMELY_FILING denials may be appealed.")

    # appeal window measured from submitted_at
    payer = db.payers.get(claim["payer_id"])
    if payer is not None and claim.get("submitted_at"):
        elapsed = timeutil.days_between(clock.now(), timeutil.parse_iso(claim["submitted_at"]))
        if elapsed > payer["appeal_window_days"]:
            raise errors.appeal_window_closed("The appeal window has closed.")

    claim["status"] = "APPEALED"
    _reverse_denial_cascade(claim)
    db.touch(claim)
    return response.object_response(claim, 200)


def _reverse_denial_cascade(claim):
    """Reverse the denial statement and revert the encounter (PRD 3.9):
    set statement.amount_due_cents = 0 and status = PAID; revert encounter
    BILLED -> CODED with account_balance_cents recomputed to 0."""
    enc = db.encounters.get(claim["encounter_id"])
    stmt = services.statement_for_encounter(claim["encounter_id"])
    if stmt is not None and stmt["status"] not in ("PAID", "WRITTEN_OFF"):
        stmt["amount_due_cents"] = 0
        stmt["status"] = "PAID"
        db.touch(stmt)
    if enc is not None and enc["status"] == "BILLED":
        enc["status"] = "CODED"
        enc["patient_responsibility_cents"] = 0
        enc["account_balance_cents"] = 0
        db.touch(enc)


# --------------------------------------------------------------------------
# Void
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    claim = db.claims.get(cid)
    if claim is None:
        raise errors.not_found()
    # void defined from SUBMITTED, or from a DENIED claim whose reason is DUPLICATE
    if claim["status"] == "SUBMITTED":
        pass
    elif claim["status"] == "DENIED" and claim.get("denial_reason") == "DUPLICATE":
        pass
    else:
        raise errors.invalid_state("Void is only defined from SUBMITTED, or a DUPLICATE-denied claim.")
    claim["status"] = "VOID"
    db.touch(claim)
    return response.object_response(claim, 200)


# --------------------------------------------------------------------------
# ClaimLine listing
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/lines", methods=["GET"])
def list_claim_lines(cid):
    authenticate()
    if cid not in db.claims:
        raise errors.not_found()
    recs = [l for l in db.claim_lines.values() if l["claim_id"] == cid]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)
