"""Contribution record endpoints."""
from datetime import timedelta

from flask import Blueprint

from db import D, new_entity, now_iso, parse_date, rhu_int, store, touch
from errors import ApiError
from middleware import authorize
from response import created, listing, ok
from routes.common import (by_created, filtered, find_cycle, find_matter, find_partner,
                           find_record)
from routes.matters import create_allocation
from services import calculations as calc
from services.engine import commit, matter_allocations
from validation import (bad, field_date, field_decimal, field_enum, field_int, field_str,
                        get_body, pagination, query_bool, query_enum, query_str)

bp = Blueprint("contributions", __name__)

READ_ROLES = ["CycleAdmin", "CommitteeMember", "Partner", "AuditObserver"]


@bp.post("/comp/contribution-records")
def create_record():
    user_id, role = authorize(["CycleAdmin", "Partner"])
    body = get_body()
    partner_id = field_str(body, "partner_id")
    cycle_id = field_str(body, "cycle_id")
    matter_id = field_str(body, "matter_id", required=False)
    kind = field_enum(body, "kind", calc.RECORD_KINDS)
    category = field_enum(body, "category", calc.RECORD_CATEGORIES)
    hours = field_decimal(body, "hours", 2, low=0)
    standard_rate = field_int(body, "standard_rate_cents", required=False, low=0, default=0)
    period_start = field_date(body, "service_period_start")
    period_end = field_date(body, "service_period_end")

    if kind == "BILLABLE":
        if matter_id is None:
            bad()
        if category != "CLIENT_WORK":
            bad()
        if standard_rate <= 0:
            bad()
    else:
        if matter_id is not None:
            bad()
        if category == "CLIENT_WORK":
            bad()
        if standard_rate != 0:
            bad()
    if parse_date(period_end) < parse_date(period_start):
        bad()

    find_partner(partner_id)
    find_cycle(cycle_id)
    matter = find_matter(matter_id) if matter_id is not None else None

    if role == "Partner" and partner_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if kind == "BILLABLE" and matter["state"] != "OPEN":
        raise ApiError("ERR_MATTER_NOT_OPEN")

    if kind == "NON_BILLABLE":
        _check_service_period_buffer(partner_id, category, period_start, period_end)

    record = new_entity({
        "partner_id": partner_id,
        "cycle_id": cycle_id,
        "matter_id": matter_id,
        "kind": kind,
        "category": category,
        "hours": hours,
        "standard_rate_cents": standard_rate,
        "service_period_start": period_start,
        "service_period_end": period_end,
        "verified": False,
        "verified_at": None,
        "standard_value_cents": rhu_int(hours * D(standard_rate)) if kind == "BILLABLE" else 0,
    })
    store.records[record["id"]] = record
    return created(commit(record))


def _check_service_period_buffer(partner_id, category, period_start, period_end):
    new_start = parse_date(period_start)
    new_end = parse_date(period_end)
    gap = timedelta(days=calc.SERVICE_PERIOD_BUFFER_DAYS + 2)
    for record in store.records.values():
        if (record["partner_id"] != partner_id
                or record["kind"] != "NON_BILLABLE"
                or record["category"] != category):
            continue
        old_start = parse_date(record["service_period_start"])
        old_end = parse_date(record["service_period_end"])
        if new_start - old_end >= gap or old_start - new_end >= gap:
            continue
        raise ApiError("ERR_SERVICE_PERIOD_BUFFER_VIOLATION")


@bp.get("/comp/contribution-records/<record_id>")
def read_record(record_id):
    authorize(READ_ROLES)
    return ok(find_record(record_id))


@bp.get("/comp/contribution-records")
def list_records():
    authorize(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "partner_id": query_str("partner_id"),
        "cycle_id": query_str("cycle_id"),
        "matter_id": query_str("matter_id"),
        "kind": query_enum("kind", calc.RECORD_KINDS),
        "category": query_enum("category", calc.RECORD_CATEGORIES),
        "verified": query_bool("verified"),
    }
    rows = filtered(store.records.values(), filters)
    rows.sort(key=lambda r: (r["service_period_start"], r["_seq"]))
    return listing(rows, limit, offset)


@bp.post("/comp/contribution-records/<record_id>/verify")
def verify_record(record_id):
    authorize(["CycleAdmin"])
    record = find_record(record_id)
    if record["verified"]:
        raise ApiError("ERR_RECORD_ALREADY_VERIFIED")
    record["verified"] = True
    record["verified_at"] = now_iso()
    touch(record)

    if record["kind"] == "BILLABLE":
        matter = store.matters.get(record["matter_id"])
        if matter is not None:
            existing = [a for a in matter_allocations(matter["id"])
                        if a["credit_role"] == "WORKING"
                        and a["partner_id"] == record["partner_id"]]
            if not existing:
                create_allocation(matter, record["partner_id"], "WORKING", D("0.00"),
                                  "WORKING_DERIVED", matter["opened_on"])
    return ok(commit(record))
