"""CourtEvent endpoints (PRD §3.7)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

from config import (
    COURT_DURATION_MAX,
    COURT_DURATION_MIN,
    COURT_EVENT_TYPES,
    ROLE_ATTORNEY,
    ROLE_MANAGING_PARTNER,
    ROLE_PARALEGAL,
)
from db import store
from errors import raise_error
from middleware import require_auth
from response import list_success, no_content, success
from routes._helpers import (
    get_json_body,
    get_pagination_args,
    paginate,
    require_field,
)
from services.calculations import (
    attorney_calendar_conflict,
    courtroom_conflict,
    is_sol_expired,
)
from services.case_engine import (
    assert_case_not_closed,
    check_version_match,
    find_active_demand_letter,
    find_existing_complaint_filed,
    get_case_or_404,
    has_any_defendant_offer,
    now,
    touch,
)
from services.serializers import court_event_to_dict
from utils import new_uuid, parse_iso_date, parse_iso_datetime


bp = Blueprint("court_events", __name__)

ALL_ROLES = [ROLE_PARALEGAL, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER]
RW_ROLES = [ROLE_ATTORNEY, ROLE_PARALEGAL]


def _get_event_or_404(cid: str, eid: str) -> dict:
    get_case_or_404(cid)
    event = store.court_events.get(eid)
    if not event or event["case_id"] != cid:
        raise_error("ERR_NOT_FOUND", f"CourtEvent {eid} not found on case {cid}.")
    return event


def _attorney_event_pool(assigned_attorney_id: str, exclude_event_id: str | None) -> list:
    if not assigned_attorney_id:
        return []
    pool = []
    for ev in store.court_events.values():
        if ev["id"] == exclude_event_id:
            continue
        if ev["status"] not in ("SCHEDULED", "CONTINUED"):
            continue
        case = store.cases.get(ev["case_id"])
        if not case:
            continue
        if case.get("assigned_attorney_id") == assigned_attorney_id:
            pool.append(ev)
    return pool


def _courtroom_event_pool(courtroom: str, exclude_event_id: str | None) -> list:
    if not courtroom:
        return []
    pool = []
    for ev in store.court_events.values():
        if ev["id"] == exclude_event_id:
            continue
        if ev["status"] not in ("SCHEDULED", "CONTINUED"):
            continue
        if ev.get("courtroom") == courtroom:
            pool.append(ev)
    return pool


@bp.post("/pi-cases/<cid>/court-events")
@require_auth(RW_ROLES)
def create_event(cid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    assert_case_not_closed(case_row)

    event_type = require_field(body, "event_type")
    if event_type not in COURT_EVENT_TYPES:
        raise_error("ERR_VALIDATION", f"Invalid event_type {event_type}.")

    sched_raw = require_field(body, "scheduled_at")
    sched = parse_iso_datetime(sched_raw)
    if sched is None:
        raise_error("ERR_VALIDATION", "scheduled_at must be ISO 8601 timestamp.")

    if "duration_minutes" not in body:
        raise_error("ERR_VALIDATION", "duration_minutes is required.")
    dur = body["duration_minutes"]
    if not isinstance(dur, int) or isinstance(dur, bool):
        raise_error("ERR_VALIDATION", "duration_minutes must be integer.")
    if dur < COURT_DURATION_MIN or dur > COURT_DURATION_MAX:
        raise_error(
            "ERR_VALIDATION",
            f"duration_minutes must be in [{COURT_DURATION_MIN}, {COURT_DURATION_MAX}].",
        )

    courtroom = body.get("courtroom")
    if courtroom is not None and not isinstance(courtroom, str):
        raise_error("ERR_VALIDATION", "courtroom must be a string or null.")

    # Safety rules run before temporal rules (PRD §2.8). SoL expiry is a
    # safety rule that blocks every state-advancing mutation on the case
    # (PRD §2.10).
    if is_sol_expired(case_row, now()):
        raise_error(
            "ERR_STATUTE_OF_LIMITATIONS_EXPIRED",
            "Case is out of statute.",
        )

    # Time-sanity bounds: scheduled_at strictly after incident_date and
    # strictly before sol_deadline + 5 years.
    incident_date = parse_iso_date(case_row["incident_date"])
    if incident_date is None:
        raise_error("ERR_INVALID_STATE", "Case has no incident_date.")
    incident_dt = datetime(
        incident_date.year, incident_date.month, incident_date.day,
        tzinfo=timezone.utc,
    )
    if sched <= incident_dt:
        raise_error(
            "ERR_COURT_EVENT_TIME_INVALID",
            "scheduled_at must be strictly after Case.incident_date.",
        )

    sol_date = parse_iso_date(case_row["sol_deadline"])
    if sol_date is not None:
        sol_plus_5 = sol_date.replace(year=sol_date.year + 5)
        upper_dt = datetime(
            sol_plus_5.year, sol_plus_5.month, sol_plus_5.day,
            tzinfo=timezone.utc,
        )
        if sched >= upper_dt:
            raise_error(
                "ERR_COURT_EVENT_TIME_INVALID",
                "scheduled_at must be strictly before sol_deadline + 5 years.",
            )

    # Attorney-calendar conflict (priority 70).
    other_atty_events = _attorney_event_pool(
        case_row.get("assigned_attorney_id"), exclude_event_id=None,
    )
    if attorney_calendar_conflict(sched, dur, other_atty_events):
        raise_error(
            "ERR_ATTORNEY_CALENDAR_CONFLICT",
            "Attorney calendar conflict with another event (15-minute buffer).",
        )

    # Courtroom conflict (priority 71).
    other_room_events = _courtroom_event_pool(courtroom, exclude_event_id=None)
    if courtroom_conflict(sched, dur, courtroom, other_room_events):
        raise_error(
            "ERR_COURTROOM_DOUBLE_BOOKED",
            "Courtroom is already booked at that time (no buffer).",
        )

    with store.lock:
        row = {
            "id": new_uuid(),
            "case_id": cid,
            "created_at": now(),
            "updated_at": now(),
            "version": 1,
            "event_type": event_type,
            "scheduled_at": sched,
            "duration_minutes": int(dur),
            "courtroom": courtroom,
            "status": "SCHEDULED",
            "award_amount_cents": None,
        }
        store.court_events[row["id"]] = row

        # Litigation entry: first COMPLAINT_FILED on the case.
        if event_type == "COMPLAINT_FILED":
            existing = find_existing_complaint_filed(cid)
            # `existing` is this very event since we just inserted; filter it.
            if existing and existing["id"] != row["id"]:
                pass  # not the first — no cascade
            else:
                if case_row["status"] == "DEMAND_SENT":
                    # Cascade requires: response_due_at has passed AND no
                    # defendant offer exists.
                    letter = find_active_demand_letter(cid)
                    if (
                        not has_any_defendant_offer(cid)
                        and letter
                        and letter["status"] == "SENT"
                        and letter.get("response_due_at") is not None
                        and now() >= letter["response_due_at"]
                    ):
                        letter["status"] = "SUPERSEDED"
                        touch(letter)
                        case_row["filed_in_court"] = True
                        case_row["status"] = "LITIGATION"
                        touch(case_row)
                elif case_row["status"] == "NEGOTIATING":
                    # Must have at least one offer (any round) AND SoL still valid.
                    case_offers = [
                        o for o in store.settlement_offers.values()
                        if o["case_id"] == cid
                    ]
                    if case_offers and not is_sol_expired(case_row, now()):
                        # Withdraw all PENDING offers.
                        for o in case_offers:
                            if o["status"] == "PENDING":
                                o["status"] = "WITHDRAWN"
                                touch(o)
                        case_row["filed_in_court"] = True
                        case_row["status"] = "LITIGATION"
                        touch(case_row)

    return success(court_event_to_dict(row), 201)


@bp.patch("/pi-cases/<cid>/court-events/<eid>")
@require_auth([ROLE_ATTORNEY])
def patch_event(cid, eid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    event = _get_event_or_404(cid, eid)
    assert_case_not_closed(case_row)

    if "status" not in body:
        raise_error("ERR_VALIDATION", "status is required.")
    new_status = body["status"]
    if new_status not in ("COMPLETED", "CONTINUED"):
        raise_error("ERR_VALIDATION", "status must be COMPLETED or CONTINUED.")

    check_version_match(event, body.get("version"))

    if event["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", f"Event must be SCHEDULED (was {event['status']}).")

    if new_status == "COMPLETED":
        # now() >= scheduled_at
        if now() < event["scheduled_at"]:
            raise_error(
                "ERR_INVALID_STATE",
                "Event cannot be COMPLETED before its scheduled_at.",
            )

        award_amount = body.get("award_amount_cents")
        if event["event_type"] == "JUDGMENT" and award_amount is not None:
            if not isinstance(award_amount, int) or isinstance(award_amount, bool) or award_amount <= 0:
                raise_error("ERR_VALIDATION", "award_amount_cents must be positive integer.")

        with store.lock:
            event["status"] = "COMPLETED"
            if event["event_type"] == "JUDGMENT" and isinstance(award_amount, int) and award_amount > 0:
                event["award_amount_cents"] = int(award_amount)
                # Case must currently be LITIGATION.
                if case_row["status"] == "LITIGATION":
                    case_row["gross_settlement_cents"] = int(award_amount)
                    case_row["status"] = "TRIAL_AWARDED"
                    touch(case_row)
            touch(event)

    else:  # CONTINUED
        if "scheduled_at" not in body:
            raise_error("ERR_VALIDATION", "scheduled_at is required for CONTINUED.")
        new_sched = parse_iso_datetime(body["scheduled_at"])
        if new_sched is None:
            raise_error("ERR_VALIDATION", "scheduled_at must be ISO 8601 timestamp.")
        if new_sched <= event["scheduled_at"]:
            raise_error("ERR_INVALID_STATE", "New scheduled_at must be strictly later.")

        with store.lock:
            event["scheduled_at"] = new_sched
            event["status"] = "CONTINUED"
            touch(event)

    return success(court_event_to_dict(event), 200)


@bp.delete("/pi-cases/<cid>/court-events/<eid>")
@require_auth([ROLE_ATTORNEY])
def delete_event(cid, eid):
    case_row = get_case_or_404(cid)
    event = _get_event_or_404(cid, eid)
    assert_case_not_closed(case_row)

    if event["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", f"Event must be SCHEDULED (was {event['status']}).")

    with store.lock:
        event["status"] = "CANCELED"
        touch(event)

    return no_content()


@bp.get("/pi-cases/<cid>/court-events")
@require_auth(ALL_ROLES)
def list_events(cid):
    get_case_or_404(cid)
    limit, offset = get_pagination_args()
    status_filter = request.args.get("status")
    type_filter = request.args.get("event_type")

    rows = [ev for ev in store.court_events.values() if ev["case_id"] == cid]
    if status_filter:
        rows = [ev for ev in rows if ev["status"] == status_filter]
    if type_filter:
        rows = [ev for ev in rows if ev["event_type"] == type_filter]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return list_success([court_event_to_dict(r) for r in page], limit, offset, total)
