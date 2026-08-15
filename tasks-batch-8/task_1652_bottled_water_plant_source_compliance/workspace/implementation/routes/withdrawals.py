"""Withdrawal events: record (with optional supersede), list, read, void."""
from flask import Blueprint, request

from db import store, new_resource, touch, by_creation, logical_date
from errors import ApiError, err_invalid_state
from middleware import auth, ALL_ROLES
from response import ok_object, ok_list
from services import as_date, as_int, get_body, get_or_404, event_json, raise_shape

bp = Blueprint("withdrawals", __name__)

SM = ["SourceMonitor"]


def _provisional_sum(permit_id, date=None, ym=None, exclude_id=None):
    total = 0
    for e in store.withdrawal_events.values():
        if e["permit_id"] != permit_id or e["status"] not in ("RECORDED", "FINALIZED"):
            continue
        if exclude_id is not None and e["id"] == exclude_id:
            continue
        d = e["_date"]
        if date is not None and d != date:
            continue
        if ym is not None and (d.year, d.month) != ym:
            continue
        total += e["gallons"]
    return total


@bp.post("/api/permits/<permit_id>/withdrawal-events")
@auth(SM)
def create_event(permit_id):
    # Rung 3 — existence: path id, then body FK (supersedes_event_id).
    permit = get_or_404(store.permits, permit_id, "permit")
    body = get_body()
    target = None
    supersedes_id = body.get("supersedes_event_id")
    if supersedes_id is not None:
        if not isinstance(supersedes_id, str) or supersedes_id not in store.withdrawal_events:
            raise ApiError("ERR_NOT_FOUND", "supersedes_event_id does not reference an existing event", 404)
        target = store.withdrawal_events[supersedes_id]

    # Rung 4 — OCC on the permit (immediately after existence).
    expected, ok_exp = as_int(body.get("expected_permit_version"))
    if ok_exp and expected != permit["version"]:
        raise ApiError(
            "ERR_STALE_PERMIT_VERSION",
            "expected_permit_version does not match the permit's current version",
            412,
        )

    # Rung 5 — state: permit must be ACTIVE.
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE", "permit is not ACTIVE", 409)

    # Parse fields (validity tracked; malformed inputs are caught at rung 11).
    wdate, ok_date = as_date(body.get("withdrawal_date"))
    gallons, ok_gal = as_int(body.get("gallons"))
    m_start, ok_ms = as_int(body.get("meter_reading_start_gallons"))
    m_end, ok_me = as_int(body.get("meter_reading_end_gallons"))

    # Rung 7 — temporal rules.
    if ok_date:
        if wdate < permit["_valid_from"] or wdate > permit["_valid_to"]:
            raise ApiError(
                "ERR_WITHDRAWAL_DATE_OUT_OF_WINDOW",
                "withdrawal_date is outside the permit validity window",
                409,
            )
        if wdate > logical_date():
            raise ApiError(
                "ERR_FUTURE_WITHDRAWAL_DATE",
                "withdrawal_date is after the current logical date",
                409,
            )
        if target is not None and target["status"] == "FINALIZED":
            ym = (target["_date"].year, target["_date"].month)
            locked = any(
                r["plant_id"] == permit["plant_id"]
                and r["status"] == "PUBLISHED"
                and (r["period_year"], r["period_month"]) == ym
                for r in store.reports.values()
            )
            if locked:
                raise ApiError(
                    "ERR_REPORT_PERIOD_LOCKED",
                    "a PUBLISHED community report covers the superseded event's period",
                    409,
                )

    # Rung 8 — cross-reference integrity: supersede target validity.
    if target is not None and (target["status"] == "VOIDED" or target["permit_id"] != permit["id"]):
        raise ApiError(
            "ERR_SUPERSEDE_TARGET_INVALID",
            "supersede target is VOIDED or belongs to another permit",
            409,
        )

    # Rung 9 — capacity: provisional caps keyed on the new event's date,
    # excluding the supersede target; daily first, then monthly; equality OK.
    if ok_gal and ok_date:
        remaining_daily = permit["daily_cap_gallons"] - _provisional_sum(
            permit["id"], date=wdate, exclude_id=target["id"] if target else None
        )
        if gallons > remaining_daily:
            raise ApiError("ERR_DAILY_CAP_EXCEEDED", "daily cap would be exceeded", 409)
        remaining_monthly = permit["monthly_cap_gallons"] - _provisional_sum(
            permit["id"], ym=(wdate.year, wdate.month), exclude_id=target["id"] if target else None
        )
        if gallons > remaining_monthly:
            raise ApiError("ERR_MONTHLY_CAP_EXCEEDED", "monthly cap would be exceeded", 409)

    # Rung 10 — quantity accounting: the meter readings witness the volume.
    if ok_gal and ok_ms and ok_me:
        if m_end - m_start != gallons:
            raise ApiError(
                "ERR_METER_READING_MISMATCH",
                "meter_reading_end_gallons - meter_reading_start_gallons != gallons",
                422,
            )

    # Rung 11 — input shape.
    errs = []
    if not ok_date:
        errs.append("withdrawal_date must be a valid ISO date")
    if not ok_gal or gallons <= 0:
        errs.append("gallons must be a positive integer")
    if not ok_ms or m_start < 0:
        errs.append("meter_reading_start_gallons must be a non-negative integer")
    if not ok_me:
        errs.append("meter_reading_end_gallons must be an integer")
    if not ok_exp:
        errs.append("expected_permit_version is required")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        errs.append("supersedes_event_id must be a string")
    raise_shape(errs)

    # Effects: supersede target -> VOIDED; new event RECORDED; permit version +1.
    if target is not None:
        target["status"] = "VOIDED"
        touch(target)
    event = new_resource(
        {
            "permit_id": permit["id"],
            "withdrawal_date": body.get("withdrawal_date"),
            "gallons": gallons,
            "meter_reading_start_gallons": m_start,
            "meter_reading_end_gallons": m_end,
            "status": "RECORDED",
            "supersedes_event_id": supersedes_id,
            "finalized_at": None,
        }
    )
    event["_date"] = wdate
    store.withdrawal_events[event["id"]] = event
    touch(permit)
    return ok_object(event_json(event), 201)


@bp.get("/api/permits/<permit_id>/withdrawal-events")
@auth(ALL_ROLES)
def list_permit_events(permit_id):
    get_or_404(store.permits, permit_id, "permit")
    items = [e for e in store.withdrawal_events.values() if e["permit_id"] == permit_id]
    return ok_list([event_json(e) for e in by_creation(items)])


@bp.get("/api/withdrawal-events")
@auth(ALL_ROLES)
def list_events():
    items = list(store.withdrawal_events.values())
    permit_id = request.args.get("permit_id")
    supersedes = request.args.get("supersedes_event_id")
    status = request.args.get("status")
    if permit_id is not None:
        items = [e for e in items if e["permit_id"] == permit_id]
    if supersedes is not None:
        items = [e for e in items if e.get("supersedes_event_id") == supersedes]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return ok_list([event_json(e) for e in by_creation(items)])


@bp.get("/api/withdrawal-events/<event_id>")
@auth(ALL_ROLES)
def get_event(event_id):
    event = get_or_404(store.withdrawal_events, event_id, "withdrawal event")
    return ok_object(event_json(event))


@bp.post("/api/withdrawal-events/<event_id>/void")
@auth(SM)
def void_event(event_id):
    event = get_or_404(store.withdrawal_events, event_id, "withdrawal event")
    if event["status"] == "FINALIZED":
        raise ApiError(
            "ERR_EVENT_ALREADY_FINALIZED",
            "finalized events must be corrected via supersede",
            409,
        )
    if event["status"] != "RECORDED":
        raise err_invalid_state("only a RECORDED event can be voided")
    event["status"] = "VOIDED"
    touch(event)
    permit = store.permits.get(event["permit_id"])
    if permit is not None:
        touch(permit)
    return ok_object(event_json(event))
