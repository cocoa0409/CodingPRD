"""Case endpoints (registration + lifecycle transitions)."""

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import calculations, posture


bp = Blueprint("cases", __name__)


VALID_CASE_TYPES = {"CIVIL", "CRIMINAL", "ADMINISTRATIVE", "ARBITRATION"}
TYPE_CODE = {
    "CIVIL": "CIV",
    "CRIMINAL": "CRM",
    "ADMINISTRATIVE": "ADM",
    "ARBITRATION": "ARB",
}


def _assign_case_number(case_type):
    year = clock.now().year
    type_code = TYPE_CODE[case_type]
    seq = db.next_case_seq(year, type_code)
    return f"{year}-{type_code}-{seq:06d}"


def _ensure_not_archived(case):
    if case["status"] == "ARCHIVED":
        errors.raise_error(errors.ERR_CASE_ARCHIVED, "Case is archived.")


@bp.route("/cases", methods=["POST"])
@auth_required("PartnerLawyer", "IntakeClerk")
def register_case():
    body = helpers.get_json_body()
    case_type = helpers.require_enum(body, "case_type", VALID_CASE_TYPES)
    title = helpers.require_str(body, "title", min_len=1, max_len=200)
    if "claim_amount_cents" not in body:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "Missing required field 'claim_amount_cents'.")
    claim_amount = body["claim_amount_cents"]
    if isinstance(claim_amount, bool) or not isinstance(claim_amount, int) or claim_amount < 0:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "claim_amount_cents must be a non-negative integer.")

    lead_lawyer_id = helpers.require_str(body, "lead_lawyer_id")
    client_identity_hash = helpers.require_str(body, "client_identity_hash", min_len=1)
    opposing_identity_hash = helpers.require_str(body, "opposing_identity_hash", min_len=1)
    intake_document_id = helpers.require_str(body, "intake_document_id", min_len=1)

    # Priority 4: body-FK existence check
    lead_lawyer = db.lawyers.get(lead_lawyer_id)
    if lead_lawyer is None:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Lawyer {lead_lawyer_id} not found.")

    # Priority 5: lead_lawyer.client_history must NOT contain opposing_identity_hash
    if opposing_identity_hash in (lead_lawyer.get("client_history") or []):
        errors.raise_error(
            errors.ERR_CONFLICT_OF_INTEREST,
            "Lead lawyer has prior representation of the opposing party.",
        )

    # Priority 6: client_identity_hash != opposing_identity_hash
    if client_identity_hash == opposing_identity_hash:
        errors.raise_error(
            errors.ERR_CONFLICT_OF_INTEREST,
            "Client and opposing identity hashes must differ.",
        )

    # Priority 21: claim amount sanity
    if case_type in {"CRIMINAL", "ADMINISTRATIVE"}:
        if claim_amount != 0:
            errors.raise_error(
                errors.ERR_CLAIM_AMOUNT_INVALID,
                "claim_amount_cents must be 0 for CRIMINAL/ADMINISTRATIVE.",
            )
    else:
        if claim_amount <= 0:
            errors.raise_error(
                errors.ERR_CLAIM_AMOUNT_INVALID,
                "claim_amount_cents must be > 0 for CIVIL/ARBITRATION.",
            )

    # Lead lawyer must be ACTIVE for assignment.
    if lead_lawyer.get("status") != "ACTIVE":
        errors.raise_error(
            errors.ERR_VALIDATION_FAILED,
            "Lead lawyer must reference a Lawyer with status=ACTIVE.",
        )

    case_number = _assign_case_number(case_type)
    cid = db.new_id()
    common = helpers.common_create()
    case = {
        "id": cid,
        "case_number": case_number,
        "case_type": case_type,
        "title": title,
        "claim_amount_cents": int(claim_amount),
        "lead_lawyer_id": lead_lawyer_id,
        "status": "INTAKE",
        "posture": "OPEN",
        "client_identity_hash": client_identity_hash,
        "opposing_identity_hash": opposing_identity_hash,
        "intake_document_id": intake_document_id,
        "closed_at": None,
        "settlement_total_cents": None,
        **common,
    }
    db.cases[cid] = case
    return response.created(serializers.case_dict(case))


@bp.route("/cases/<cid>", methods=["GET"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer", "IntakeClerk")
def read_case(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    return response.ok(serializers.case_dict(case))


@bp.route("/cases", methods=["GET"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer", "IntakeClerk")
def list_cases():
    limit, offset = helpers.parse_pagination()
    args = request.args
    items = list(db.cases.values())

    if args.get("status"):
        items = [c for c in items if c["status"] == args["status"]]
    if args.get("case_type"):
        items = [c for c in items if c["case_type"] == args["case_type"]]
    if args.get("lead_lawyer_id"):
        items = [c for c in items if c["lead_lawyer_id"] == args["lead_lawyer_id"]]

    items.sort(key=lambda c: c["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok(
        [serializers.case_dict(c) for c in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/cases/<cid>/activate", methods=["POST"])
@auth_required("PartnerLawyer")
def activate_case(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(case, body.get("version"))

    if case["status"] != "INTAKE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Case must be in INTAKE to activate.")

    has_plaintiff = any(
        p["case_id"] == cid and p["party_role"] == "PLAINTIFF" for p in db.parties.values()
    )
    has_defendant = any(
        p["case_id"] == cid and p["party_role"] == "DEFENDANT" for p in db.parties.values()
    )
    if not has_plaintiff or not has_defendant:
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Case must have at least one PLAINTIFF and one DEFENDANT party to activate.",
        )

    lead_lawyer = db.lawyers.get(case["lead_lawyer_id"])
    if lead_lawyer is None or lead_lawyer.get("status") != "ACTIVE":
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Lead lawyer must be ACTIVE to activate the case.",
        )

    # Re-verify recorded conflict-of-interest still holds (defensive).
    if case["opposing_identity_hash"] in (lead_lawyer.get("client_history") or []):
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Conflict-of-interest re-check failed at activation.",
        )

    case["status"] = "ACTIVE"
    helpers.bump(case)
    posture.recompute(case)
    return response.ok(serializers.case_dict(case))


@bp.route("/cases/<cid>/hold", methods=["POST"])
@auth_required("PartnerLawyer")
def hold_case(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(case, body.get("version"))

    if case["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Case must be ACTIVE to hold.")
    if case["posture"] not in {"OPEN", "RESTRICTED"}:
        errors.raise_error(errors.ERR_INVALID_STATE, "Case posture must be OPEN or RESTRICTED.")

    # Cascade: cancel all SCHEDULED hearings.
    for h in db.hearings.values():
        if h["case_id"] == cid and h["status"] == "SCHEDULED":
            h["status"] = "CANCELLED"
            helpers.bump(h)

    case["status"] = "ON_HOLD"
    helpers.bump(case)
    posture.recompute(case)
    return response.ok(serializers.case_dict(case))


@bp.route("/cases/<cid>/resume", methods=["POST"])
@auth_required("PartnerLawyer")
def resume_case(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(case, body.get("version"))

    if case["status"] != "ON_HOLD":
        errors.raise_error(errors.ERR_INVALID_STATE, "Case must be ON_HOLD to resume.")

    case["status"] = "ACTIVE"
    helpers.bump(case)
    posture.recompute(case)
    return response.ok(serializers.case_dict(case))


@bp.route("/cases/<cid>/await-settlement", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer")
def await_settlement(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(case, body.get("version"))

    if case["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Case must be ACTIVE to move to AWAITING_SETTLEMENT.")
    if case["posture"] != "OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE, "Case posture must be OPEN.")

    # All hearings must be COMPLETED or CANCELLED (none SCHEDULED or RESCHEDULED).
    for h in db.hearings.values():
        if h["case_id"] != cid:
            continue
        if h["status"] not in {"COMPLETED", "CANCELLED", "RESCHEDULED"}:
            errors.raise_error(
                errors.ERR_INVALID_STATE,
                "All hearings must be COMPLETED or CANCELLED.",
            )

    # Cascade: lock all SIGNED_OFF drafts.
    for d in db.document_drafts.values():
        if d["case_id"] == cid and d["status"] == "SIGNED_OFF":
            d["status"] = "LOCKED"
            helpers.bump(d)

    case["status"] = "AWAITING_SETTLEMENT"
    helpers.bump(case)
    posture.recompute(case)
    return response.ok(serializers.case_dict(case))


@bp.route("/cases/<cid>/close", methods=["POST"])
@auth_required("PartnerLawyer")
def close_case(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(case, body.get("version"))

    if case["status"] != "AWAITING_SETTLEMENT":
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Case must be AWAITING_SETTLEMENT to close.",
        )

    case_bills = [b for b in db.bills.values() if b["case_id"] == cid]
    finalized_bills = [b for b in case_bills if b["status"] in {"PAID", "SETTLED"}]
    if len(finalized_bills) != 1:
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Exactly one Bill must exist in PAID or SETTLED status.",
        )

    for ev in db.evidence_rows.values():
        if ev["case_id"] != cid:
            continue
        if ev["status"] not in {"SUBMITTED", "EXCLUDED", "REBUTTED"}:
            errors.raise_error(
                errors.ERR_INVALID_STATE,
                "All evidence must be SUBMITTED, EXCLUDED, or REBUTTED before close.",
            )

    closing_bill = finalized_bills[0]

    # Cascade: dismiss every OPEN rebuttal on this case.
    case_evidence_ids = {e["id"] for e in db.evidence_rows.values() if e["case_id"] == cid}
    for r in db.evidence_rebuttals.values():
        if r["evidence_id"] in case_evidence_ids and r["status"] == "OPEN":
            r["status"] = "DISMISSED"

    # Cascade: retire every non-terminal draft.
    for d in db.document_drafts.values():
        if d["case_id"] != cid:
            continue
        if d["status"] in {"DRAFTING", "IN_REVIEW", "REVISING"}:
            d["status"] = "RETIRED"
            helpers.bump(d)

    # Stamp closed_at and compute settlement total.
    case["closed_at"] = clock.now()
    case["settlement_total_cents"] = calculations.compute_final_settlement(case, closing_bill)
    case["status"] = "CLOSED"
    helpers.bump(case)
    posture.recompute(case)
    return response.ok(serializers.case_dict(case))
