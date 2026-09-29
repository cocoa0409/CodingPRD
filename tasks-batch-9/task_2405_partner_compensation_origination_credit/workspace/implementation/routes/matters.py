"""Matter endpoints, financial postings and matter status machine."""
from flask import Blueprint

from db import D, clock_date, new_entity, store, touch
from errors import ApiError
from middleware import authorize
from response import created, listing, ok
from routes.common import (READ_ALL, by_created, filtered, find_allocation, find_matter,
                           find_partner)
from services import calculations as calc
from services.engine import commit, matter_allocations
from validation import (bad, field_date, field_enum, field_int, field_str, get_body,
                        pagination, query_enum, query_str)

bp = Blueprint("matters", __name__)


@bp.post("/comp/matters")
def create_matter():
    authorize(["CycleAdmin"])
    body = get_body()
    client_key = field_str(body, "client_key", min_len=1, max_len=64)
    client_display_name = field_str(body, "client_display_name")
    matter_type = field_enum(body, "matter_type", calc.MATTER_TYPES)
    practice_group = field_enum(body, "practice_group", calc.PRACTICE_GROUPS)
    opened_on = field_date(body, "opened_on")
    billing_attorney_id = field_str(body, "billing_attorney_id")
    responsible_attorney_id = field_str(body, "responsible_attorney_id")

    find_partner(billing_attorney_id)
    find_partner(responsible_attorney_id)

    first_for_client = not any(
        m["client_key"] == client_key and m["state"] != "WRITTEN_OFF"
        for m in store.matters.values())

    matter = new_entity({
        "client_key": client_key,
        "client_display_name": client_display_name,
        "matter_type": matter_type,
        "practice_group": practice_group,
        "opened_on": opened_on,
        "state": "OPEN",
        "billing_attorney_id": billing_attorney_id,
        "responsible_attorney_id": responsible_attorney_id,
        "prior_responsible_attorney_id": None,
        "billed_cents": 0,
        "collected_cents": 0,
        "direct_cost_cents": 0,
        "realization_pct": D("0.0000"),
        "profitability_index_contribution": D("0.0000"),
        "profitability_index_fully_loaded": D("0.0000"),
        "verified_billable_hours": D("0.00"),
        "origination_pct_assigned": D("0.00"),
        "is_first_matter_for_client": first_for_client,
        "written_off_reason": None,
    })
    store.matters[matter["id"]] = matter

    for role, partner_id in (("BILLING", billing_attorney_id),
                             ("RESPONSIBLE", responsible_attorney_id)):
        create_allocation(matter, partner_id, role, D("100.00"), "DEFAULT_BILLING",
                          opened_on)

    return created(commit(matter))


def create_allocation(matter, partner_id, credit_role, credit_pct, source, credit_from,
                      credit_through=None):
    allocation = new_entity({
        "matter_id": matter["id"],
        "partner_id": partner_id,
        "credit_role": credit_role,
        "credit_pct": credit_pct,
        "source": source,
        "credit_from": credit_from,
        "credit_through": credit_through,
        "state": "ACTIVE",
        "credited_collection_provisional_cents": 0,
        "credited_collection_final_cents": 0,
    })
    store.allocations[allocation["id"]] = allocation
    return allocation


@bp.get("/comp/matters/<matter_id>")
def read_matter(matter_id):
    authorize(READ_ALL)
    return ok(find_matter(matter_id))


@bp.get("/comp/matters")
def list_matters():
    authorize(READ_ALL)
    limit, offset = pagination()
    filters = {
        "client_key": query_str("client_key"),
        "billing_attorney_id": query_str("billing_attorney_id"),
        "responsible_attorney_id": query_str("responsible_attorney_id"),
        "prior_responsible_attorney_id": query_str("prior_responsible_attorney_id"),
        "state": query_enum("state", calc.MATTER_STATES),
        "matter_type": query_enum("matter_type", calc.MATTER_TYPES),
    }
    rows = filtered(store.matters.values(), filters)
    rows.sort(key=lambda m: (m["opened_on"], m["_seq"]))
    return listing(rows, limit, offset)


@bp.post("/comp/matters/<matter_id>/financials")
def post_financials(matter_id):
    authorize(["CycleAdmin"])
    body = get_body()
    billed_delta = field_int(body, "billed_delta_cents")
    collected_delta = field_int(body, "collected_delta_cents")
    cost_delta = field_int(body, "direct_cost_delta_cents")
    expected = field_int(body, "expected_matter_version")
    matter = find_matter(matter_id)
    if (matter["billed_cents"] + billed_delta < 0
            or matter["collected_cents"] + collected_delta < 0
            or matter["direct_cost_cents"] + cost_delta < 0):
        bad()
    if matter["state"] != "OPEN":
        raise ApiError("ERR_MATTER_NOT_OPEN")
    if expected != matter["version"]:
        raise ApiError("ERR_STALE_VERSION")
    matter["billed_cents"] += billed_delta
    matter["collected_cents"] += collected_delta
    matter["direct_cost_cents"] += cost_delta
    touch(matter)
    return ok(commit(matter))


@bp.post("/comp/matters/<matter_id>/status")
def change_status(matter_id):
    authorize(["CycleAdmin"])
    body = get_body()
    target = field_enum(body, "target_state", calc.MATTER_STATES)
    written_off_reason = field_str(body, "written_off_reason", required=False)
    if target == "WRITTEN_OFF" and not written_off_reason:
        bad()
    matter = find_matter(matter_id)
    current = matter["state"]
    if (current, target) not in {("OPEN", "CLOSED"), ("CLOSED", "OPEN"),
                                 ("OPEN", "WRITTEN_OFF")}:
        raise ApiError("ERR_MATTER_NOT_OPEN")

    if (current, target) == ("CLOSED", "OPEN"):
        anchor = calc.anchor_cycle()
        if anchor is not None:
            for award in store.awards.values():
                if (award["cycle_id"] == anchor["id"]
                        and award["payment_state"] in ("TRUED_UP", "SETTLED")):
                    raise ApiError("ERR_AWARD_NOT_DRAWABLE")

    if target == "WRITTEN_OFF":
        matter["written_off_reason"] = written_off_reason
        today = clock_date().isoformat()
        for allocation in matter_allocations(matter["id"], states=("ACTIVE",)):
            allocation["state"] = "SUPERSEDED"
            allocation["credit_through"] = today
            touch(allocation)

    matter["state"] = target
    touch(matter)
    return ok(commit(matter))


@bp.get("/comp/matters/<matter_id>/credit-allocations")
def list_matter_allocations(matter_id):
    authorize(READ_ALL)
    limit, offset = pagination()
    filters = {
        "credit_role": query_enum("credit_role", calc.CREDIT_ROLES),
        "state": query_enum("state", calc.ALLOCATION_STATES),
    }
    find_matter(matter_id)
    rows = [a for a in store.allocations.values() if a["matter_id"] == matter_id]
    rows = by_created(filtered(rows, filters))
    return listing(rows, limit, offset)


@bp.get("/comp/credit-allocations/<allocation_id>")
def read_allocation(allocation_id):
    authorize(READ_ALL)
    return ok(find_allocation(allocation_id))
