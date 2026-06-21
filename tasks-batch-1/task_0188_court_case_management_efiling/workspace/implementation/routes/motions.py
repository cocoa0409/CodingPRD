"""Motions and orders."""
from flask import Blueprint, request

import db
import errors
from middleware import get_actor, require_role
from response import success
from services import domain, validate, cascade

bp = Blueprint("motions", __name__)

MOTION_TYPES = {"DISMISS", "SUMMARY_JUDGMENT", "CONTINUANCE", "COMPEL_DISCOVERY"}
RULINGS = {"GRANT", "DENY", "GRANT_IN_PART"}
RULING_TO_STATUS = {"GRANT": "GRANTED", "DENY": "DENIED", "GRANT_IN_PART": "GRANTED_IN_PART"}
RULING_TO_DISPOSITION = {"GRANT": "GRANT", "DENY": "DENY", "GRANT_IN_PART": "GRANT_IN_PART"}


@bp.post("/motions")
def create_motion():
    user_id, role = get_actor()
    require_role(role, {"Attorney"})
    data = validate.body(request)
    case_id = validate.require_str(data, "case_id")
    filing_id = validate.require_str(data, "filing_id")
    moving_party_id = validate.require_str(data, "moving_party_id")

    # Existence (priority 3) before remaining body validation (priority 4).
    case = domain.get_or_404(db.cases, case_id)
    filing = domain.get_or_404(db.filings, filing_id)
    party = domain.get_or_404(db.parties, moving_party_id)

    motion_type = validate.enum(data, "motion_type", MOTION_TYPES)
    opposed = validate.optional_bool(data, "opposed", default=False)

    # Same-case referential integrity (priority 5).
    if filing["case_id"] != case_id or party["case_id"] != case_id:
        raise errors.err(errors.ERR_CROSS_CASE_REFERENCE, "FK belongs to a different case")

    # Posture gate: RESTRICTED blocks new motion filing (priority 9).
    domain.refresh_case_derived(case)
    if case["posture"] == "RESTRICTED":
        raise errors.err(errors.ERR_CASE_RESTRICTED, "Case is restricted")

    rec = db.base_record()
    rec.update({
        "case_id": case_id,
        "filing_id": filing_id,
        "moving_party_id": moving_party_id,
        "motion_type": motion_type,
        "status": "FILED",
        "opposed": opposed,
        "hearing_id": None,
        "order_id": None,
    })
    db.motions[rec["id"]] = rec
    return success(domain._clean(rec), status=201)


@bp.get("/motions/<motion_id>")
def get_motion(motion_id):
    get_actor()
    rec = domain.get_or_404(db.motions, motion_id)
    return success(domain._clean(rec), status=200)


@bp.get("/motions")
def list_motions():
    get_actor()
    args = request.args
    items = list(db.motions.values())
    for field in ("case_id", "filing_id", "moving_party_id", "hearing_id", "order_id", "status"):
        val = args.get(field)
        if val is not None:
            items = [m for m in items if m.get(field) == val]
    window, pagination = domain.paginate(items, args)
    return success([domain._clean(m) for m in window], status=200, pagination=pagination)


@bp.post("/motions/<motion_id>/submit")
def submit_motion(motion_id):
    _, role = get_actor()
    require_role(role, {"Judge"})
    m = domain.get_or_404(db.motions, motion_id)
    if m["status"] != "FILED":
        raise errors.err(errors.ERR_INVALID_STATE, "Motion is not FILED")
    m["status"] = "UNDER_SUBMISSION"
    db.touch(m)
    return success(domain._clean(m), status=200)


@bp.post("/motions/<motion_id>/rule")
def rule_motion(motion_id):
    _, role = get_actor()
    require_role(role, {"Judge"})
    data = validate.body(request)
    m = domain.get_or_404(db.motions, motion_id)
    case = db.cases[m["case_id"]]

    ruling = validate.enum(data, "ruling", RULINGS)
    order_text = validate.require_str(data, "order_text")
    stays_case = validate.optional_bool(data, "stays_case", default=False)

    if m["status"] != "UNDER_SUBMISSION":
        raise errors.err(errors.ERR_INVALID_STATE, "Motion is not UNDER_SUBMISSION")

    domain.refresh_case_derived(case)
    if case["posture"] == "FROZEN":
        raise errors.err(errors.ERR_CASE_FROZEN, "Case is frozen")

    disposition = RULING_TO_DISPOSITION[ruling]
    # DENY forces stays_case false; it never stays the case.
    effective_stays = stays_case and disposition in ("GRANT", "GRANT_IN_PART")

    order = db.base_record()
    order.update({
        "case_id": case["id"],
        "motion_id": m["id"],
        "disposition": disposition,
        "text": order_text,
        "stays_case": effective_stays,
        "entered_at": _clock_iso(),
    })
    db.orders[order["id"]] = order

    m["status"] = RULING_TO_STATUS[ruling]
    m["order_id"] = order["id"]
    db.touch(m)

    if effective_stays and case["status"] == "OPEN":
        # Stay cascade: case OPEN->STAYED, vacate deadlines, posture FROZEN.
        cascade.stay_case(case)
    else:
        domain.bump_case(case)

    return success(domain._clean(m), status=200)


@bp.post("/motions/<motion_id>/withdraw")
def withdraw_motion(motion_id):
    user_id, role = get_actor()
    require_role(role, {"Attorney"})
    m = domain.get_or_404(db.motions, motion_id)
    if m["status"] != "FILED":
        raise errors.err(errors.ERR_INVALID_STATE, "Motion is not FILED")
    party = db.parties[m["moving_party_id"]]
    if party["attorney_user_id"] != user_id:
        raise errors.err(errors.ERR_NOT_MOVING_PARTY, "Not the moving party's counsel")

    m["status"] = "WITHDRAWN"
    # Cancel a linked SCHEDULED hearing (cascade).
    hearing_id = m.get("hearing_id")
    if hearing_id:
        hearing = db.hearings.get(hearing_id)
        if hearing and hearing["status"] == "SCHEDULED":
            hearing["status"] = "CANCELLED"
            db.touch(hearing)
    db.touch(m)
    return success(domain._clean(m), status=200)


def _clock_iso():
    dt = db.now_clock()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
