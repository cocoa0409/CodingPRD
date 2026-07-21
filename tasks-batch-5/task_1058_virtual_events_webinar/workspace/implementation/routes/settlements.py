"""Settlement and billing: two invoice kinds, OCC and segregation of duties."""

from flask import Blueprint, g

import calc
import db
from auth import authorize
from db import S
from errors import ApiError
from response import ok, ok_list
from validate import (
    body, get_event, get_settlement, get_sponsor, guard_state, pagination,
    paginate, qs, req_int, req_str,
)

bp = Blueprint("settlements", __name__)

SETTLEMENT_TERMINAL = ("PAID", "VOID")


@bp.route("/api/events/<event_id>/settlements", methods=["POST"])
def create_event_settlement(event_id):
    authorize("FinanceAdmin")
    event = get_event(event_id)
    b = body()
    expected_event_version = req_int(b, "expected_event_version")

    # 9. the stale-version check
    if expected_event_version != int(event.get("version", 1)):
        raise ApiError("ERR_STALE_EVENT_VERSION")

    # 15. settlement uniqueness - a DRAFT one is superseded, not an obstacle
    for existing in S.settlements.values():
        if (
            existing.get("event_id") == event["id"]
            and existing.get("subject_type") == "EVENT"
            and existing.get("state") in ("ISSUED", "PAID")
        ):
            raise ApiError("ERR_SETTLEMENT_EXISTS")

    for existing in db.sort_rows(list(S.settlements.values())):
        if (
            existing.get("event_id") == event["id"]
            and existing.get("subject_type") == "EVENT"
            and existing.get("state") == "DRAFT"
        ):
            existing["state"] = "VOID"
            db.touch(existing)

    totals = calc.event_settlement_total(event)

    row = db.new_row({
        "event_id": event["id"],
        "sponsor_id": None,
        "subject_type": "EVENT",
        "state": "DRAFT",
        "issued_by_user_id": None,
        "paid_by_user_id": None,
    })
    row.update(totals)
    S.settlements[row["id"]] = row

    db.touch(event)
    return ok(db.serialize(row), 201)


@bp.route("/api/sponsors/<sponsor_id>/settlements", methods=["POST"])
def create_sponsor_settlement(sponsor_id):
    authorize("FinanceAdmin")
    sponsor = get_sponsor(sponsor_id)

    totals = calc.sponsor_settlement_lines(sponsor)

    row = db.new_row({
        "event_id": sponsor.get("event_id"),
        "sponsor_id": sponsor["id"],
        "subject_type": "SPONSOR",
        "state": "DRAFT",
        "issued_by_user_id": None,
        "paid_by_user_id": None,
    })
    row.update(totals)
    S.settlements[row["id"]] = row
    return ok(db.serialize(row), 201)


@bp.route("/api/settlements", methods=["GET"])
def list_settlements():
    authorize("FinanceAdmin", "PlatformAdmin", "Organizer")
    limit, offset = pagination()
    event_id = qs("event_id")
    sponsor_id = qs("sponsor_id")
    subject_type = qs("subject_type")
    state = qs("state")
    rows = [
        r for r in S.settlements.values()
        if (event_id is None or r.get("event_id") == event_id)
        and (sponsor_id is None or r.get("sponsor_id") == sponsor_id)
        and (subject_type is None or r.get("subject_type") == subject_type)
        and (state is None or r.get("state") == state)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/settlements/<settlement_id>", methods=["GET"])
def read_settlement(settlement_id):
    authorize("FinanceAdmin", "PlatformAdmin", "Organizer")
    return ok(db.serialize(get_settlement(settlement_id)))


@bp.route("/api/settlements/<settlement_id>/issue", methods=["POST"])
def issue_settlement(settlement_id):
    authorize("FinanceAdmin")
    row = get_settlement(settlement_id)
    guard_state(row, ("DRAFT",), SETTLEMENT_TERMINAL)

    event = S.events.get(row.get("event_id"))
    if row.get("subject_type") == "EVENT":
        if event is None or event.get("state") != "ENDED":
            raise ApiError("ERR_INVALID_STATE")

    row["state"] = "ISSUED"
    row["issued_by_user_id"] = g.user_id
    db.touch(row)

    if row.get("subject_type") == "EVENT" and event is not None:
        event["state"] = "SETTLED"
        db.touch(event)

    return ok(db.serialize(row))


@bp.route("/api/settlements/<settlement_id>/pay", methods=["POST"])
def pay_settlement(settlement_id):
    authorize("FinanceAdmin")
    row = get_settlement(settlement_id)
    b = body()
    paid_amount_cents = req_int(b, "paid_amount_cents")

    guard_state(row, ("ISSUED",), SETTLEMENT_TERMINAL)

    # 12. safety rule: segregation of duties
    if g.user_id == row.get("issued_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # 16. fiscal rule
    if paid_amount_cents != int(row.get("total_cents", 0)):
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")

    row["state"] = "PAID"
    row["paid_by_user_id"] = g.user_id
    db.touch(row)
    return ok(db.serialize(row))


@bp.route("/api/settlements/<settlement_id>/void", methods=["POST"])
def void_settlement(settlement_id):
    authorize("FinanceAdmin")
    row = get_settlement(settlement_id)
    b = body()
    req_str(b, "reason")
    guard_state(row, ("DRAFT", "ISSUED"), SETTLEMENT_TERMINAL)
    row["state"] = "VOID"
    db.touch(row)
    return ok(db.serialize(row))
