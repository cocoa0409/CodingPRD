"""e-Filing review cycle."""
from flask import Blueprint, request

import db
import errors
from middleware import get_actor, require_role
from response import success
from services import domain, validate, calc

bp = Blueprint("filings", __name__)

DOC_TYPES = {"COMPLAINT", "ANSWER", "MOTION", "EXHIBIT", "PROOF_OF_SERVICE"}


@bp.post("/filings")
def create_filing():
    _, role = get_actor()
    require_role(role, {"Attorney"})
    data = validate.body(request)
    case_id = validate.require_str(data, "case_id")
    filed_by_party_id = validate.require_str(data, "filed_by_party_id")
    resubmits_filing_id = data.get("resubmits_filing_id")

    # Existence (priority 3) before remaining body validation (priority 4).
    case = domain.get_or_404(db.cases, case_id)
    domain.get_or_404(db.parties, filed_by_party_id)
    resubmit_target = None
    if resubmits_filing_id is not None:
        resubmit_target = domain.get_or_404(db.filings, resubmits_filing_id)

    document_type = validate.enum(data, "document_type", DOC_TYPES)
    title = validate.require_str(data, "title")

    if resubmit_target is not None:
        if resubmit_target["status"] != "REJECTED":
            raise errors.err(
                errors.ERR_RESUBMIT_TARGET_NOT_REJECTED,
                "resubmits_filing_id must point at a REJECTED filing",
            )

    court = db.courts[case["court_id"]]
    fee_cents = court["filing_fee_cents"] if document_type == "COMPLAINT" else 0
    fee_status = "ASSESSED" if fee_cents > 0 else "NONE"

    rec = db.base_record()
    rec.update({
        "case_id": case_id,
        "filed_by_party_id": filed_by_party_id,
        "document_type": document_type,
        "title": title,
        "status": "SUBMITTED",
        "rejection_reason": None,
        "fee_cents": fee_cents,
        "fee_status": fee_status,
        "resubmits_filing_id": resubmits_filing_id,
        "accepted_at": None,
    })
    db.filings[rec["id"]] = rec
    return success(domain._clean(rec), status=201)


@bp.get("/filings/<filing_id>")
def get_filing(filing_id):
    get_actor()
    rec = domain.get_or_404(db.filings, filing_id)
    return success(domain._clean(rec), status=200)


@bp.get("/filings")
def list_filings():
    get_actor()
    args = request.args
    items = list(db.filings.values())
    for field in ("case_id", "filed_by_party_id", "resubmits_filing_id", "status"):
        val = args.get(field)
        if val is not None:
            items = [f for f in items if f.get(field) == val]
    window, pagination = domain.paginate(items, args)
    return success([domain._clean(f) for f in window], status=200, pagination=pagination)


@bp.post("/filings/<filing_id>/claim-review")
def claim_review(filing_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    f = domain.get_or_404(db.filings, filing_id)
    if f["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Filing is not SUBMITTED")
    f["status"] = "UNDER_REVIEW"
    db.touch(f)
    return success(domain._clean(f), status=200)


def _satisfy_resubmission_deadline(filing):
    """If this accepted filing resubmits a lineage that maps to a MISSED/PENDING
    deadline, mark that deadline SATISFIED (cascade)."""
    target_id = filing.get("resubmits_filing_id")
    if not target_id:
        return
    # Collect the lineage of REJECTED filings this resubmission chains from.
    lineage = set()
    cur = target_id
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        lineage.add(cur)
        prev = db.filings.get(cur)
        cur = prev.get("resubmits_filing_id") if prev else None

    for d in domain.deadlines_for_case(filing["case_id"]):
        if d["status"] not in ("MISSED", "PENDING"):
            continue
        if d.get("satisfied_by_filing_id") in lineage:
            _do_satisfy(d, filing)
            return
        # Deadlines satisfied/missed by a filing in the lineage: also match
        # the response deadline mapped via satisfied_by_filing_id link absence.
    # Fall back: a RESPONSE deadline tied to the original filing is unusual;
    # the primary mapping is satisfied_by_filing_id above.


def _do_satisfy(deadline, filing):
    deadline["status"] = "SATISFIED"
    deadline["satisfied_by_filing_id"] = filing["id"]
    db.touch(deadline)


@bp.post("/filings/<filing_id>/accept")
def accept_filing(filing_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    f = domain.get_or_404(db.filings, filing_id)
    case = db.cases[f["case_id"]]

    if f["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Filing is not UNDER_REVIEW")

    domain.refresh_case_derived(case)
    if case["posture"] == "FROZEN":
        raise errors.err(errors.ERR_CASE_FROZEN, "Case is frozen")

    is_complaint = f["document_type"] == "COMPLAINT"

    # Statute-of-limitations bar for complaints (priority 11, before fee bar).
    if is_complaint:
        clock = db.now_clock()
        for d in domain.deadlines_for_case(case["id"]):
            if d["deadline_type"] == "STATUTE_OF_LIMITATIONS":
                due = calc.parse_dt(d["due_date"])
                if clock > due:
                    raise errors.err(errors.ERR_STATUTE_EXPIRED, "Statute of limitations has expired")

    # Unpaid-fee bar for complaints (priority 12).
    if is_complaint and f["fee_cents"] > 0 and f["fee_status"] not in ("PAID", "WAIVED"):
        raise errors.err(errors.ERR_FILING_FEE_UNPAID, "Filing fee is unpaid")

    f["status"] = "ACCEPTED"
    f["accepted_at"] = _clock_iso()

    # Resubmission-driven deadline satisfaction.
    _satisfy_resubmission_deadline(f)

    db.touch(f)
    domain.bump_case(case)
    return success(domain._clean(f), status=200)


@bp.post("/filings/<filing_id>/reject")
def reject_filing(filing_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    data = validate.body(request)
    f = domain.get_or_404(db.filings, filing_id)
    case = db.cases[f["case_id"]]

    if f["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Filing is not UNDER_REVIEW")

    reason = data.get("rejection_reason")
    if not reason or not isinstance(reason, str):
        raise errors.err(errors.ERR_REJECTION_REASON_REQUIRED, "rejection_reason is required")

    f["status"] = "REJECTED"
    f["rejection_reason"] = reason
    fee_released = False
    if f["fee_status"] == "ASSESSED":
        f["fee_status"] = "NONE"
        fee_released = True
    db.touch(f)
    if fee_released:
        domain.bump_case(case)
    return success(domain._clean(f), status=200)


@bp.post("/filings/<filing_id>/pay-fee")
def pay_fee(filing_id):
    _, role = get_actor()
    require_role(role, {"Attorney", "Clerk"})
    f = domain.get_or_404(db.filings, filing_id)
    case = db.cases[f["case_id"]]
    if f["fee_status"] != "ASSESSED":
        raise errors.err(errors.ERR_INVALID_STATE, "Fee is not ASSESSED")
    f["fee_status"] = "PAID"
    db.touch(f)
    domain.bump_case(case)
    return success(domain._clean(f), status=200)


def _clock_iso():
    dt = db.now_clock()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
