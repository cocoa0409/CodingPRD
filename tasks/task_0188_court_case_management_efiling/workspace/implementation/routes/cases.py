"""Case docket lifecycle."""
from flask import Blueprint, request

import db
import errors
from middleware import get_actor, require_role
from response import success
from services import domain, validate, calc, cascade

bp = Blueprint("cases", __name__)

CASE_TYPES = {"CONTRACT", "TORT", "PROPERTY", "FAMILY"}


def _mint_case_number(court, year):
    """case_number_sequence: per-court, per-year monotonic counter."""
    same = [
        c for c in db.cases.values()
        if c["court_id"] == court["id"] and c.get("_mint_year") == year
    ]
    seq = len(same) + 1
    return "%s-%04d-CV-%06d" % (court["jurisdiction_code"], year, seq), seq


@bp.post("/cases")
def create_case():
    _, role = get_actor()
    require_role(role, {"Clerk"})
    data = validate.body(request)
    court_id = validate.require_str(data, "court_id")
    # Existence (priority 3) before remaining body validation (priority 4).
    court = domain.get_or_404(db.courts, court_id)
    caption = validate.require_str(data, "caption")
    case_type = validate.enum(data, "case_type", CASE_TYPES)

    year = db.now_clock().year
    case_number, _seq = _mint_case_number(court, year)

    rec = db.base_record()
    rec.update({
        "court_id": court_id,
        "case_number": case_number,
        "caption": caption,
        "case_type": case_type,
        "status": "DRAFT",
        "posture": "ACTIVE",
        "open_deadline_count": 0,
        "total_fees_assessed_cents": 0,
        "total_fees_paid_cents": 0,
        "_mint_year": year,
    })
    db.cases[rec["id"]] = rec
    return success(domain.serialize_case(rec), status=201)


@bp.get("/cases/<case_id>")
def get_case(case_id):
    get_actor()
    rec = domain.get_or_404(db.cases, case_id)
    return success(domain.serialize_case(rec), status=200)


@bp.get("/cases")
def list_cases():
    get_actor()
    args = request.args
    items = list(db.cases.values())
    court_id = args.get("court_id")
    if court_id is not None:
        items = [c for c in items if c["court_id"] == court_id]
    status = args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    window, pagination = domain.paginate(items, args)
    return success([domain.serialize_case(c) for c in window], status=200, pagination=pagination)


@bp.post("/cases/<case_id>/open")
def open_case(case_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    case = domain.get_or_404(db.cases, case_id)
    if case["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Case is not DRAFT")

    parties = domain.parties_for_case(case_id)
    has_plaintiff = any(p["role"] == "PLAINTIFF" for p in parties)
    has_defendant = any(p["role"] == "DEFENDANT" for p in parties)
    if not (has_plaintiff and has_defendant):
        raise errors.err(errors.ERR_CASE_MISSING_PARTIES, "Case requires a plaintiff and a defendant")

    has_complaint = any(
        f["status"] == "ACCEPTED" and f["document_type"] == "COMPLAINT"
        for f in domain.filings_for_case(case_id)
    )
    if not has_complaint:
        raise errors.err(errors.ERR_NO_ACCEPTED_COMPLAINT, "Case requires an accepted complaint")

    case["status"] = "OPEN"

    # Side effect: create a STATUTE_OF_LIMITATIONS deadline anchored on CASE_OPENED.
    court = db.courts[case["court_id"]]
    anchor = db.now_clock()
    anchor_iso = anchor.strftime("%Y-%m-%dT%H:%M:%S.") + f"{anchor.microsecond // 1000:03d}Z"
    interval_days = 0
    dl = db.base_record()
    dl.update({
        "case_id": case_id,
        "deadline_type": "STATUTE_OF_LIMITATIONS",
        "anchor_event": "CASE_OPENED",
        "anchor_date": anchor_iso,
        "interval_days": interval_days,
        "counting_mode": "CALENDAR",
        "due_date": calc.due_date_calc(anchor_iso, interval_days, "CALENDAR", court),
        "status": "PENDING",
        "parent_deadline_id": None,
        "satisfied_by_filing_id": None,
    })
    db.deadlines[dl["id"]] = dl

    domain.bump_case(case)
    return success(domain.serialize_case(case), status=200)


@bp.post("/cases/<case_id>/lift-stay")
def lift_stay(case_id):
    _, role = get_actor()
    require_role(role, {"Judge"})
    case = domain.get_or_404(db.cases, case_id)
    if case["status"] != "STAYED":
        raise errors.err(errors.ERR_INVALID_STATE, "Case is not STAYED")
    case["status"] = "OPEN"
    domain.bump_case(case)
    return success(domain.serialize_case(case), status=200)


@bp.post("/cases/<case_id>/close")
def close_case(case_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    case = domain.get_or_404(db.cases, case_id)

    if case["status"] == "JUDGMENT_ENTERED":
        clock = db.now_clock()
        for d in domain.deadlines_for_case(case_id):
            if d["status"] == "PENDING" and d["deadline_type"] == "APPEAL":
                due = calc.parse_dt(d["due_date"])
                if due >= clock:
                    raise errors.err(errors.ERR_APPEAL_WINDOW_OPEN, "Appeal window still open")
    elif case["status"] == "ON_APPEAL":
        for a in domain.appeals_for_case(case_id):
            if a["status"] not in ("TRANSMITTED", "DISMISSED"):
                raise errors.err(errors.ERR_APPEAL_NOT_TRANSMITTED, "An appeal is not yet transmitted")
    else:
        raise errors.err(errors.ERR_INVALID_STATE, "Case cannot be closed from its current state")

    case["status"] = "CLOSED"
    cascade.vacate_pending_deadlines(case)
    domain.bump_case(case)
    return success(domain.serialize_case(case), status=200)
