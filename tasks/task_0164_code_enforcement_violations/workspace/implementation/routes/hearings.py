"""Hearing endpoints: get, list, decide, continue, reschedule (PRD §3.8, §3.9)."""

from flask import Blueprint

from clock import clock
from db import db, touch
from errors import err
from middleware import require_roles
from response import success, list_success
from services import domain, serialize
from services.constants import MAX_CONTINUANCES
from services.helpers import (
    get_body,
    lookup,
    pagination_params,
    paginate,
    parse_iso,
    require_enum,
    sort_by_created,
)

bp = Blueprint("hearings", __name__)

DECISIONS = {"UPHELD", "DISMISSED"}


@bp.get("/hearings/<hid>")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "HearingOfficer", "Registrant")
def get_hearing(hid):
    record = lookup(db.hearings, hid)
    return success(serialize.hearing_out(record), status=200)


@bp.get("/notices/<nid>/hearings")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "HearingOfficer", "Registrant")
def list_notice_hearings(nid):
    lookup(db.notices, nid)
    limit, offset = pagination_params()
    items = [h for h in db.hearings.values() if h["notice_id"] == nid]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.hearing_out(h) for h in page], limit, offset, total)


@bp.post("/hearings/<hid>/decide")
@require_roles("HearingOfficer")
def decide_hearing(hid):
    hearing = lookup(db.hearings, hid)
    body = get_body()
    require_enum(body, "decision", DECISIONS)

    if hearing["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "hearing is not SCHEDULED")

    now = clock.now()
    # Ripeness: may decide only at/after scheduled_for (PRD §3.8).
    if hearing["scheduled_for"] is not None and now < hearing["scheduled_for"]:
        raise err("ERR_HEARING_NOT_RIPE", "hearing is not yet ripe")

    notice = db.notices.get(hearing["notice_id"])
    decision = body["decision"]

    if decision == "UPHELD":
        hearing["status"] = "HELD_UPHELD"
        touch(hearing)
        if notice is not None and notice["status"] == "CONTESTED":
            # Accrual resumes: settlement variant bridging the contest, as-of decision.
            total = domain.freeze_fine(notice, now)
            notice["status"] = "UPHELD"
            touch(notice)
            # CITATION Fine.assessed_cents := frozen total; stays OPEN.
            for f in domain.fines_for_notice(notice["id"]):
                if f["source_kind"] == "CITATION":
                    f["assessed_cents"] = total
                    touch(f)
            case = db.cases.get(notice["case_id"])
            if case is not None:
                domain.recompute_case(case)
    else:  # DISMISSED
        hearing["status"] = "HELD_DISMISSED"
        touch(hearing)
        if notice is not None and notice["status"] == "CONTESTED":
            notice["status"] = "DISMISSED"
            notice["fine_total_cents"] = 0
            notice["days_overdue"] = 0
            touch(notice)
            # CITATION Fine -> WAIVED (debit removed from outstanding).
            for f in domain.fines_for_notice(notice["id"]):
                if f["source_kind"] == "CITATION" and f["settlement_status"] == "OPEN":
                    f["settlement_status"] = "WAIVED"
                    touch(f)
            case = db.cases.get(notice["case_id"])
            if case is not None:
                domain.recompute_case(case)

    return success(serialize.hearing_out(hearing), status=200)


@bp.post("/hearings/<hid>/continue")
@require_roles("HearingOfficer")
def continue_hearing(hid):
    hearing = lookup(db.hearings, hid)
    if hearing["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "hearing is not SCHEDULED")
    if hearing["continuance_count"] >= MAX_CONTINUANCES:
        raise err("ERR_CONTINUANCE_LIMIT", "continuance limit reached")
    hearing["status"] = "CONTINUED"
    hearing["continuance_count"] += 1
    touch(hearing)
    return success(serialize.hearing_out(hearing), status=200)


@bp.post("/hearings/<hid>/reschedule")
@require_roles("HearingOfficer")
def reschedule_hearing(hid):
    hearing = lookup(db.hearings, hid)
    body = get_body()
    if "scheduled_for" not in body or body["scheduled_for"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: scheduled_for")

    if hearing["status"] != "CONTINUED":
        raise err("ERR_INVALID_STATE", "hearing is not CONTINUED")

    scheduled_for = parse_iso(body["scheduled_for"], "scheduled_for")
    now = clock.now()
    # Reschedule target must be >= current clock (PRD §3.8).
    if scheduled_for < now:
        raise err("ERR_HEARING_NOT_RIPE", "reschedule target is in the past")

    # Honor the hearing buffer against other active hearings on the same case.
    notice = db.notices.get(hearing["notice_id"])
    if notice is not None:
        from routes.notices import _check_hearing_buffer
        _check_hearing_buffer(notice["case_id"], scheduled_for, exclude_hearing_id=hearing["id"])

    hearing["status"] = "SCHEDULED"
    hearing["scheduled_for"] = scheduled_for
    touch(hearing)
    return success(serialize.hearing_out(hearing), status=200)
