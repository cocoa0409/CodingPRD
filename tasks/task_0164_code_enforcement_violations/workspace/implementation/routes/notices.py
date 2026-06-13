"""ViolationNotice endpoints: issue, get, list, contest (PRD §3.4, §3.8)."""

from datetime import timedelta

from flask import Blueprint, g, request

from clock import clock
from db import db, common_fields, touch
from errors import err
from middleware import require_roles
from response import success, list_success
from services import calc, domain, serialize
from services.constants import GRACE_CONTEST_DAYS, HEARING_BUFFER_DAYS
from services.helpers import (
    get_body,
    lookup,
    pagination_params,
    paginate,
    parse_iso,
    require_enum,
    resolve_ref,
    sort_by_created,
)

bp = Blueprint("notices", __name__)

VIOLATION_CLASSES = {"MINOR", "MAJOR", "HAZARD"}


@bp.post("/notices")
@require_roles("CodeOfficer")
def issue_notice():
    body = get_body()
    if "case_id" not in body or body["case_id"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: case_id")
    if "source_inspection_id" not in body or body["source_inspection_id"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: source_inspection_id")
    require_enum(body, "violation_class", VIOLATION_CLASSES)

    # FK resolution (PRD §2.8) before business rules.
    case = resolve_ref(db.cases, body["case_id"])
    inspection = resolve_ref(db.inspections, body["source_inspection_id"])

    # Substantiation: inspection on this same case with outcome VIOLATION_FOUND.
    if inspection["case_id"] != case["id"] or inspection["outcome"] != "VIOLATION_FOUND":
        raise err("ERR_NO_SUBSTANTIATION", "no substantiating VIOLATION_FOUND inspection on the case")

    # FeeSchedule must exist for violation_class.
    fs = domain.fee_schedule_for(body["violation_class"])
    if fs is None:
        raise err("ERR_FEE_SCHEDULE_MISSING", "no fee schedule for violation_class")

    now = clock.now()
    owner = domain.owner_for_case(case)
    owner_id = owner["id"] if owner else None

    # Freeze escalation multiplier from the owner's live tier at issuance.
    _, _, multiplier = calc.repeat_offender(owner_id, db, now, exclude_notice_id=None)

    deadline = now + timedelta(days=fs["cure_days"])

    record = common_fields()
    record.update({
        "case_id": case["id"],
        "owner_id": owner_id,
        "source_inspection_id": inspection["id"],
        "violation_class": body["violation_class"],
        "escalation_multiplier": multiplier,
        "effective_date": now,
        "compliance_deadline": deadline,
        "status": "ISSUED",
        "fine_total_cents": fs["base_fine_cents"],
        "days_overdue": 0,
    })
    db.notices[record["id"]] = record

    # Create the CITATION Fine sized by the base of the accrual formula.
    fine = common_fields()
    fine.update({
        "notice_id": record["id"],
        "source_kind": "CITATION",
        "assessed_cents": fs["base_fine_cents"],
        "settlement_status": "OPEN",
    })
    db.fines[fine["id"]] = fine

    # Recompute parent case (INTAKE -> ACTIVE), balance, bump version.
    domain.recompute_case(case)
    return success(serialize.notice_out(record), status=201)


@bp.get("/notices/<nid>")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "Registrant")
def get_notice(nid):
    notice = lookup(db.notices, nid)
    # Lazy ISSUED->OVERDUE + provisional fine recompute on read (PRD §3.6).
    domain.evaluate_notice(notice)
    return success(serialize.notice_out(notice), status=200)


@bp.get("/notices")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "Registrant")
def list_notices():
    limit, offset = pagination_params()
    items = list(db.notices.values())
    case_id = request.args.get("case_id")
    owner_id = request.args.get("owner_id")
    insp_id = request.args.get("source_inspection_id")
    if case_id is not None:
        items = [n for n in items if n["case_id"] == case_id]
    if owner_id is not None:
        items = [n for n in items if n["owner_id"] == owner_id]
    if insp_id is not None:
        items = [n for n in items if n["source_inspection_id"] == insp_id]
    items = sort_by_created(items)
    for n in items:
        domain.evaluate_notice(n)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.notice_out(n) for n in page], limit, offset, total)


@bp.post("/notices/<nid>/contest")
@require_roles("Registrant")
def contest_notice(nid):
    notice = lookup(db.notices, nid)
    body = get_body()
    if "scheduled_for" not in body or body["scheduled_for"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: scheduled_for")

    case = db.cases.get(notice["case_id"])
    prop = db.properties.get(case["property_id"]) if case else None

    # Registrant must own the case's property (PRD §2.1; priority 4 before state).
    if prop is None or prop["owner_id"] != g.user_id:
        raise err("ERR_NOT_NOTICE_OWNER", "registrant does not own the case's property")

    # Lazy OVERDUE evaluation so window/state checks are current.
    domain.evaluate_notice(notice)

    # State legality: contest defined from ISSUED and OVERDUE (PRD §3.8).
    if notice["status"] not in ("ISSUED", "OVERDUE"):
        raise err("ERR_INVALID_STATE", "notice cannot be contested from its current state")

    scheduled_for = parse_iso(body["scheduled_for"], "scheduled_for")
    now = clock.now()

    # Contest window (PRD §3.8).
    if notice["status"] == "ISSUED":
        if now > notice["compliance_deadline"]:
            raise err("ERR_CONTEST_WINDOW_CLOSED", "contest window has closed")
    else:  # OVERDUE
        grace_deadline = notice["compliance_deadline"] + timedelta(days=GRACE_CONTEST_DAYS)
        if now > grace_deadline:
            raise err("ERR_CONTEST_WINDOW_CLOSED", "contest window has closed")

    # Hearing buffer: scheduled_for must be >= HEARING_BUFFER_DAYS whole days, in
    # either direction, from any other active hearing on the same case (PRD §3.8).
    _check_hearing_buffer(case["id"], scheduled_for, exclude_hearing_id=None)

    # Pause accrual: freeze fine_total at provisional-as-of-contest instant.
    domain.freeze_fine(notice, now)
    notice["status"] = "CONTESTED"
    touch(notice)

    hearing = common_fields()
    hearing.update({
        "notice_id": notice["id"],
        "requested_by_user_id": g.user_id,
        "scheduled_for": scheduled_for,
        "status": "SCHEDULED",
        "continuance_count": 0,
    })
    db.hearings[hearing["id"]] = hearing

    # Recompute case (posture stays ACTIVE; balance unchanged but version bumps).
    domain.recompute_case(case)
    return success(serialize.hearing_out(hearing), status=201)


def _check_hearing_buffer(case_id, scheduled_for, exclude_hearing_id):
    """Reject scheduled_for within HEARING_BUFFER_DAYS whole days of another active
    hearing on the same case (PRD §3.8, §10b)."""
    case_notice_ids = {n["id"] for n in db.notices.values() if n["case_id"] == case_id}
    for h in db.hearings.values():
        if h["id"] == exclude_hearing_id:
            continue
        if h["notice_id"] not in case_notice_ids:
            continue
        if h["status"] not in ("SCHEDULED", "CONTINUED"):
            continue
        other = h["scheduled_for"]
        if other is None:
            continue
        gap_days = abs((scheduled_for - other).total_seconds()) // 86400
        if gap_days < HEARING_BUFFER_DAYS:
            raise err("ERR_HEARING_SLOT_CONFLICT", "hearing too close to another on the same case")
