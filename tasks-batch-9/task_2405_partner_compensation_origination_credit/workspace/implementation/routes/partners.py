"""Partner endpoints, departure notice and capital contributions."""
from flask import Blueprint

from db import D, clock_date, new_entity, parse_date, store, touch
from errors import ApiError
from middleware import authorize
from response import created, listing, ok
from routes.common import READ_ALL, by_created, filtered, find_partner
from services import calculations as calc
from services.engine import commit
from validation import (bad, field_bool, field_date, field_int, field_str, get_body,
                        pagination, query_bool, query_enum)

bp = Blueprint("partners", __name__)


@bp.post("/comp/partners")
def create_partner():
    authorize(["CycleAdmin"])
    body = get_body()
    full_name = field_str(body, "full_name", min_len=1, max_len=120)
    practice_group = field_str(body, "practice_group")
    if practice_group not in calc.PRACTICE_GROUPS:
        bad()
    compensation_model = field_str(body, "compensation_model")
    if compensation_model not in calc.COMPENSATION_MODELS:
        bad()
    lockstep_step = field_int(body, "lockstep_step", required=False, low=0, high=12, default=0)
    admission_year = field_int(body, "admission_year", low=1950, high=2100)
    is_committee_member = field_bool(body, "is_committee_member", required=False, default=False)
    is_credit_arbiter = field_bool(body, "is_credit_arbiter", required=False, default=False)
    evaluation_required = field_bool(body, "evaluation_required", required=False, default=True)
    opening_capital = field_int(body, "opening_capital_cents", required=False, low=0, default=0)
    target_capital = field_int(body, "target_capital_cents", required=False, low=0, default=0)

    if compensation_model == "LOCKSTEP":
        if lockstep_step < 1:
            bad()
    elif lockstep_step != 0:
        bad()

    partner = new_entity({
        "full_name": full_name,
        "practice_group": practice_group,
        "compensation_model": compensation_model,
        "lockstep_step": lockstep_step,
        "admission_year": admission_year,
        "is_committee_member": is_committee_member,
        "is_credit_arbiter": is_credit_arbiter,
        "evaluation_required": evaluation_required,
        "status": "ACTIVE",
        "departure_effective_on": None,
        "opening_capital_cents": opening_capital,
        "target_capital_cents": target_capital,
        "capital_account_balance_cents": opening_capital,
        "ytd_draw_paid_cents": 0,
        "verified_billable_hours": D("0.00"),
        "non_billable_points": D("0.00"),
        "credited_collection_provisional_cents": 0,
        "credited_collection_final_cents": 0,
        "normalized_credit_index_provisional": D("0.000000"),
        "normalized_credit_index_final": D("0.000000"),
        "blended_realization_pct": D("0.0000"),
        "weighted_profitability_points": D("0.0000"),
        "formula_score_provisional": D("0.0000"),
        "formula_score_final": D("0.0000"),
        "committee_points": D("0.00"),
        "responsible_matter_count": 0,
        "_voluntary_capital_cents": 0,
    })
    store.partners[partner["id"]] = partner
    return created(commit(partner))


@bp.get("/comp/partners/<partner_id>")
def read_partner(partner_id):
    authorize(READ_ALL)
    return ok(find_partner(partner_id))


@bp.get("/comp/partners")
def list_partners():
    authorize(["CycleAdmin", "CommitteeMember", "CreditArbiter", "AuditObserver"])
    limit, offset = pagination()
    filters = {
        "compensation_model": query_enum("compensation_model", calc.COMPENSATION_MODELS),
        "status": query_enum("status", calc.PARTNER_STATES),
        "practice_group": query_enum("practice_group", calc.PRACTICE_GROUPS),
        "is_committee_member": query_bool("is_committee_member"),
    }
    rows = by_created(filtered(store.partners.values(), filters))
    return listing(rows, limit, offset)


@bp.post("/comp/partners/<partner_id>/notice-of-departure")
def notice_of_departure(partner_id):
    authorize(["CycleAdmin"])
    body = get_body()
    effective_on = field_date(body, "departure_effective_on")
    if parse_date(effective_on) < clock_date():
        bad()
    partner = find_partner(partner_id)
    if partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_NOT_DEPARTING")

    partner["status"] = "NOTICE_GIVEN"
    partner["departure_effective_on"] = effective_on
    touch(partner)

    originated = []
    for allocation in store.allocations.values():
        if (allocation["partner_id"] != partner_id
                or allocation["credit_role"] != "ORIGINATING"
                or allocation["state"] != "ACTIVE"):
            continue
        matter = store.matters.get(allocation["matter_id"])
        if matter is None or matter["state"] != "OPEN":
            continue
        originated.append((matter, allocation))
    originated.sort(key=lambda pair: (pair[0]["opened_on"], pair[0]["_seq"]))
    for matter, allocation in originated:
        transition = new_entity({
            "departing_partner_id": partner_id,
            "successor_partner_id": None,
            "matter_id": matter["id"],
            "transferred_pct": allocation["credit_pct"],
            "prior_credit_pct": allocation["credit_pct"],
            "state": "PROPOSED",
            "effective_on": None,
            "void_reason": None,
        })
        store.transitions[transition["id"]] = transition

    return ok(commit(partner))


@bp.post("/comp/partners/<partner_id>/capital-contribution")
def capital_contribution(partner_id):
    authorize(["CycleAdmin"])
    body = get_body()
    amount = field_int(body, "amount_cents", low=0)
    expected = field_int(body, "expected_partner_version")
    partner = find_partner(partner_id)
    if expected != partner["version"]:
        raise ApiError("ERR_STALE_VERSION")
    partner["_voluntary_capital_cents"] += amount
    touch(partner)
    return ok(commit(partner))


@bp.get("/comp/partners/<partner_id>/credit-allocations")
def list_partner_allocations(partner_id):
    authorize(READ_ALL)
    limit, offset = pagination()
    filters = {
        "credit_role": query_enum("credit_role", calc.CREDIT_ROLES),
        "state": query_enum("state", calc.ALLOCATION_STATES),
    }
    find_partner(partner_id)
    rows = [a for a in store.allocations.values() if a["partner_id"] == partner_id]
    rows = by_created(filtered(rows, filters))
    return listing(rows, limit, offset)
