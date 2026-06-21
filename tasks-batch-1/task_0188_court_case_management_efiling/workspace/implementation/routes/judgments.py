"""Judgments and post-judgment interest."""
from flask import Blueprint, request

import db
import errors
from middleware import get_actor, require_role
from response import success
from services import domain, validate, calc, cascade

bp = Blueprint("judgments", __name__)

JUDGMENT_TYPES = {"DEFAULT", "SUMMARY", "TRIAL", "DISMISSAL"}


@bp.post("/judgments")
def create_judgment():
    _, role = get_actor()
    require_role(role, {"Judge"})
    data = validate.body(request)
    case_id = validate.require_str(data, "case_id")
    prevailing_party_id = data.get("prevailing_party_id")

    # Existence (priority 3) before remaining body validation (priority 4).
    case = domain.get_or_404(db.cases, case_id)
    party = None
    if prevailing_party_id is not None:
        party = domain.get_or_404(db.parties, prevailing_party_id)

    judgment_type = validate.enum(data, "judgment_type", JUDGMENT_TYPES)
    principal_cents = validate.non_negative_int(data, "principal_cents", required=False, default=0)
    interest_rate_bps = validate.non_negative_int(data, "interest_rate_bps", required=False, default=0)
    validate.require(data, "expected_case_version")
    expected_case_version = data["expected_case_version"]
    if not isinstance(expected_case_version, int) or isinstance(expected_case_version, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_case_version must be an integer")

    # Same-case referential integrity (priority 5).
    if party is not None and party["case_id"] != case_id:
        raise errors.err(errors.ERR_CROSS_CASE_REFERENCE, "prevailing_party belongs to a different case")

    # OCC check (priority 6) before state checks.
    if expected_case_version != case["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale case version")

    # State check (priority 7).
    if case["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Case is not OPEN")

    # Business: no pending motions.
    for m in domain.motions_for_case(case_id):
        if m["status"] in ("FILED", "UNDER_SUBMISSION"):
            raise errors.err(errors.ERR_PENDING_MOTIONS, "Case has pending motions")

    rec = db.base_record()
    rec.update({
        "case_id": case_id,
        "judgment_type": judgment_type,
        "prevailing_party_id": prevailing_party_id,
        "principal_cents": principal_cents,
        "interest_rate_bps": interest_rate_bps,
        "entered_at": _clock_iso(),
        "status": "ENTERED",
    })
    db.judgments[rec["id"]] = rec

    # Case OPEN -> JUDGMENT_ENTERED.
    case["status"] = "JUDGMENT_ENTERED"

    # Side effect: create an APPEAL deadline anchored on JUDGMENT_ENTERED.
    court = db.courts[case["court_id"]]
    interval = court["appeal_window_days"]
    anchor_iso = rec["entered_at"]
    dl = db.base_record()
    dl.update({
        "case_id": case_id,
        "deadline_type": "APPEAL",
        "anchor_event": "JUDGMENT_ENTERED",
        "anchor_date": anchor_iso,
        "interval_days": interval,
        "counting_mode": "CALENDAR",
        "due_date": calc.due_date_calc(anchor_iso, interval, "CALENDAR", court),
        "status": "PENDING",
        "parent_deadline_id": None,
        "satisfied_by_filing_id": None,
    })
    db.deadlines[dl["id"]] = dl

    domain.bump_case(case)
    return success(domain.serialize_judgment(rec), status=201)


@bp.get("/judgments/<judgment_id>")
def get_judgment(judgment_id):
    get_actor()
    rec = domain.get_or_404(db.judgments, judgment_id)
    return success(domain.serialize_judgment(rec), status=200)


@bp.get("/judgments")
def list_judgments():
    get_actor()
    args = request.args
    items = list(db.judgments.values())
    for field in ("case_id", "prevailing_party_id", "status"):
        val = args.get(field)
        if val is not None:
            items = [j for j in items if j.get(field) == val]
    window, pagination = domain.paginate(items, args)
    return success([domain.serialize_judgment(j) for j in window], status=200, pagination=pagination)


@bp.post("/judgments/<judgment_id>/satisfy")
def satisfy_judgment(judgment_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    j = domain.get_or_404(db.judgments, judgment_id)
    if j["status"] != "ENTERED":
        raise errors.err(errors.ERR_INVALID_STATE, "Judgment is not ENTERED")
    j["status"] = "SATISFIED"
    db.touch(j)
    return success(domain.serialize_judgment(j), status=200)


@bp.post("/judgments/<judgment_id>/vacate")
def vacate_judgment(judgment_id):
    _, role = get_actor()
    require_role(role, {"Judge"})
    j = domain.get_or_404(db.judgments, judgment_id)
    case = db.cases[j["case_id"]]
    if j["status"] != "ENTERED":
        raise errors.err(errors.ERR_INVALID_STATE, "Judgment is not ENTERED")
    if case["status"] != "JUDGMENT_ENTERED":
        raise errors.err(errors.ERR_INVALID_STATE, "Cannot vacate once case is on appeal")

    j["status"] = "VACATED"
    db.touch(j)
    # Reverse case to OPEN; vacate APPEAL deadlines still PENDING.
    case["status"] = "OPEN"
    cascade.vacate_pending_deadlines(case, deadline_type="APPEAL")
    domain.bump_case(case)
    return success(domain.serialize_judgment(j), status=200)


def _clock_iso():
    dt = db.now_clock()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
