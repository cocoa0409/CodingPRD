"""Credit transition endpoints (effectuate / void) and the departure promotion."""
from flask import Blueprint

from db import D, parse_date, store, touch
from errors import ApiError
from middleware import authorize
from response import listing, ok
from routes.common import (by_created, filtered, find_partner, find_transition)
from routes.matters import create_allocation
from services import calculations as calc
from services.engine import (commit, interval_sum_exceeds_ceiling, matter_allocations,
                             originating_intervals)
from validation import (bad, field_date, field_int, field_str, get_body, pagination,
                        query_enum, query_str)

bp = Blueprint("transitions", __name__)

READ_ROLES = ["CycleAdmin", "CreditArbiter", "Partner", "AuditObserver"]


@bp.get("/comp/credit-transitions/<transition_id>")
def read_transition(transition_id):
    authorize(READ_ROLES)
    return ok(find_transition(transition_id))


@bp.get("/comp/credit-transitions")
def list_transitions():
    authorize(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "departing_partner_id": query_str("departing_partner_id"),
        "successor_partner_id": query_str("successor_partner_id"),
        "matter_id": query_str("matter_id"),
        "state": query_enum("state", calc.TRANSITION_STATES),
    }
    rows = by_created(filtered(store.transitions.values(), filters))
    return listing(rows, limit, offset)


def _originating_row(matter_id, partner_id, states):
    for allocation in matter_allocations(matter_id, states=states):
        if (allocation["credit_role"] == "ORIGINATING"
                and allocation["partner_id"] == partner_id):
            return allocation
    return None


def _responsible_row(matter_id, partner_id, states):
    for allocation in matter_allocations(matter_id, states=states):
        if (allocation["credit_role"] == "RESPONSIBLE"
                and allocation["partner_id"] == partner_id):
            return allocation
    return None


@bp.post("/comp/credit-transitions/<transition_id>/effectuate")
def effectuate(transition_id):
    authorize(["CycleAdmin"])
    body = get_body()
    successor_id = field_str(body, "successor_partner_id")
    effective_on = field_date(body, "effective_on")
    expected = field_int(body, "expected_matter_version")

    transition = find_transition(transition_id)
    successor = find_partner(successor_id)

    if transition["state"] != "PROPOSED":
        raise ApiError("ERR_TRANSITION_NOT_PENDING")

    departing = store.partners[transition["departing_partner_id"]]
    if departing["status"] != "NOTICE_GIVEN":
        raise ApiError("ERR_PARTNER_NOT_DEPARTING")
    if successor["status"] != "ACTIVE" or successor["id"] == departing["id"]:
        raise ApiError("ERR_SUCCESSOR_NOT_ELIGIBLE")

    matter = store.matters[transition["matter_id"]]
    if expected != matter["version"]:
        raise ApiError("ERR_STALE_VERSION")

    departing_alloc = _originating_row(matter["id"], departing["id"], ("ACTIVE",))
    baseline = departing_alloc["credit_from"] if departing_alloc else matter["opened_on"]
    if parse_date(effective_on) <= parse_date(baseline):
        bad()

    extra = [(effective_on, None, transition["transferred_pct"])]
    skip = ()
    if departing_alloc is not None:
        skip = (departing_alloc["id"],)
        extra.append((departing_alloc["credit_from"], effective_on,
                      departing_alloc["credit_pct"]))
    if interval_sum_exceeds_ceiling(originating_intervals(matter["id"], extra=extra,
                                                          skip_ids=skip)):
        raise ApiError("ERR_CREDIT_INTERVAL_OVERSUBSCRIBED")

    transition["successor_partner_id"] = successor_id
    transition["effective_on"] = effective_on
    transition["state"] = "EFFECTIVE"

    if departing_alloc is not None:
        departing_alloc["state"] = "TRANSFERRED"
        departing_alloc["credit_through"] = effective_on
        touch(departing_alloc)
        transition["_departing_alloc_id"] = departing_alloc["id"]

    successor_alloc = create_allocation(matter, successor_id, "ORIGINATING",
                                       transition["transferred_pct"], "TRANSITION",
                                       effective_on)
    transition["_successor_alloc_id"] = successor_alloc["id"]

    matter["prior_responsible_attorney_id"] = matter["responsible_attorney_id"]
    if matter["responsible_attorney_id"] == departing["id"]:
        matter["responsible_attorney_id"] = successor_id
        departing_resp = _responsible_row(matter["id"], departing["id"], ("ACTIVE",))
        if departing_resp is not None:
            departing_resp["state"] = "SUPERSEDED"
            departing_resp["credit_through"] = effective_on
            touch(departing_resp)
            transition["_departing_resp_alloc_id"] = departing_resp["id"]
        successor_resp = create_allocation(matter, successor_id, "RESPONSIBLE",
                                           D("100.00"), "TRANSITION", effective_on)
        transition["_successor_resp_alloc_id"] = successor_resp["id"]

    touch(matter)
    touch(transition)
    _maybe_depart(departing)
    return ok(commit(transition))


@bp.post("/comp/credit-transitions/<transition_id>/void")
def void(transition_id):
    authorize(["CycleAdmin"])
    body = get_body()
    void_reason = field_str(body, "void_reason")
    expected = field_int(body, "expected_matter_version")

    transition = find_transition(transition_id)
    if transition["state"] not in ("PROPOSED", "EFFECTIVE"):
        raise ApiError("ERR_TRANSITION_NOT_VOIDABLE")
    matter = store.matters[transition["matter_id"]]
    if expected != matter["version"]:
        raise ApiError("ERR_STALE_VERSION")

    if transition["state"] == "EFFECTIVE":
        effective_on = transition["effective_on"]
        for key in ("_successor_alloc_id", "_successor_resp_alloc_id"):
            allocation = store.allocations.get(transition.get(key))
            if allocation is None:
                continue
            allocation["state"] = "SUPERSEDED"
            allocation["credit_through"] = effective_on
            touch(allocation)
        departing_alloc = store.allocations.get(transition.get("_departing_alloc_id"))
        if departing_alloc is not None:
            departing_alloc["state"] = "ACTIVE"
            departing_alloc["credit_pct"] = transition["prior_credit_pct"]
            departing_alloc["credit_through"] = None
            touch(departing_alloc)
        departing_resp = store.allocations.get(transition.get("_departing_resp_alloc_id"))
        if departing_resp is not None:
            departing_resp["state"] = "ACTIVE"
            departing_resp["credit_through"] = None
            touch(departing_resp)
        if matter["prior_responsible_attorney_id"] is not None:
            matter["responsible_attorney_id"] = matter["prior_responsible_attorney_id"]
            matter["prior_responsible_attorney_id"] = None

    transition["void_reason"] = void_reason
    transition["state"] = "VOIDED"
    touch(matter)
    touch(transition)
    _maybe_depart(store.partners.get(transition["departing_partner_id"]))
    return ok(commit(transition))


def _maybe_depart(partner):
    """NOTICE_GIVEN -> DEPARTED once no transition of this partner is PROPOSED."""
    if partner is None or partner["status"] != "NOTICE_GIVEN":
        return
    for transition in store.transitions.values():
        if (transition["departing_partner_id"] == partner["id"]
                and transition["state"] == "PROPOSED"):
            return
    partner["status"] = "DEPARTED"
    touch(partner)
