"""Origination credit claim endpoints."""
from flask import Blueprint

from db import D, clock_date, new_entity, parse_date, store, touch
from errors import ApiError
from middleware import authorize
from response import created, listing, ok
from routes.common import READ_ALL, by_created, filtered, find_claim, find_cycle, find_matter
from routes.matters import create_allocation
from services import calculations as calc
from services.engine import (commit, interval_sum_exceeds_ceiling, matter_allocations,
                             originating_intervals)
from validation import (bad, field_decimal, field_enum, field_int, field_str, get_body,
                        pagination, query_enum, query_str)

bp = Blueprint("claims", __name__)

READ_ROLES = ["CycleAdmin", "CreditArbiter", "CommitteeMember", "Partner", "AuditObserver"]
DECISIONS = ["ALLOCATE", "SPLIT", "REJECT", "REMAND"]


@bp.post("/comp/credit-claims")
def create_claim():
    user_id, _ = authorize(["Partner"])
    body = get_body()
    cycle_id = field_str(body, "cycle_id")
    matter_id = field_str(body, "matter_id")
    claim_basis = field_enum(body, "claim_basis", calc.CLAIM_BASES)
    requested_pct = field_decimal(body, "requested_pct", 2, low="0.01", high="100.00")
    narrative = field_str(body, "narrative")

    find_cycle(cycle_id)
    find_matter(matter_id)

    for claim in store.claims.values():
        if (claim["cycle_id"] == cycle_id and claim["matter_id"] == matter_id
                and claim["claimant_partner_id"] == user_id):
            raise ApiError("ERR_DUPLICATE_CLAIM")

    claim = new_entity({
        "cycle_id": cycle_id,
        "matter_id": matter_id,
        "claimant_partner_id": user_id,
        "disputing_partner_id": None,
        "resolved_prior_originator_id": None,
        "claim_basis": claim_basis,
        "requested_pct": requested_pct,
        "contested_pct": None,
        "approved_pct": None,
        "counterparty_pct": None,
        "narrative": narrative,
        "dispute_grounds": None,
        "remand_reason": None,
        "state": "DRAFT",
        "revision_count": 0,
        "remand_count": 0,
    })
    store.claims[claim["id"]] = claim
    return created(commit(claim))


@bp.get("/comp/credit-claims/<claim_id>")
def read_claim(claim_id):
    authorize(READ_ROLES)
    return ok(find_claim(claim_id))


@bp.get("/comp/credit-claims")
def list_claims():
    authorize(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "cycle_id": query_str("cycle_id"),
        "matter_id": query_str("matter_id"),
        "claimant_partner_id": query_str("claimant_partner_id"),
        "disputing_partner_id": query_str("disputing_partner_id"),
        "resolved_prior_originator_id": query_str("resolved_prior_originator_id"),
        "state": query_enum("state", calc.CLAIM_STATES),
    }
    rows = by_created(filtered(store.claims.values(), filters))
    return listing(rows, limit, offset)


@bp.post("/comp/credit-claims/<claim_id>/submit")
def submit_claim(claim_id):
    user_id, _ = authorize(["Partner"])
    claim = find_claim(claim_id)
    if user_id != claim["claimant_partner_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if claim["state"] != "DRAFT":
        raise ApiError("ERR_CLAIM_NOT_IN_DRAFT")
    cycle = store.cycles[claim["cycle_id"]]
    if cycle["state"] != "OPEN_INTAKE":
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED")
    if clock_date() > parse_date(cycle["claim_deadline_on"]):
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED")
    _check_client_history(claim)
    claim["state"] = "SUBMITTED"
    touch(claim)
    return ok(commit(claim))


def _siblings(matter):
    return [m for m in store.matters.values()
            if m["client_key"] == matter["client_key"]
            and m["id"] != matter["id"]
            and m["state"] != "WRITTEN_OFF"]


def _check_client_history(claim):
    matter = store.matters[claim["matter_id"]]
    siblings = _siblings(matter)
    basis = claim["claim_basis"]
    if basis == "NEW_CLIENT":
        if siblings:
            raise ApiError("ERR_CLIENT_NOT_NEW")
        return
    if not siblings:
        raise ApiError("ERR_CLIENT_NOT_NEW")
    if basis == "CROSS_SELL":
        earliest = min(siblings, key=lambda m: (m["opened_on"], m["_seq"]))
        if matter["practice_group"] == earliest["practice_group"]:
            raise ApiError("ERR_CLIENT_NOT_NEW")


@bp.post("/comp/credit-claims/<claim_id>/dispute")
def dispute_claim(claim_id):
    user_id, _ = authorize(["Partner"])
    body = get_body()
    contested_pct = field_decimal(body, "contested_pct", 2, low="0.00", high="100.00")
    dispute_grounds = field_str(body, "dispute_grounds")
    claim = find_claim(claim_id)
    if claim["state"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_DISPUTABLE")
    cycle = store.cycles[claim["cycle_id"]]
    if cycle["state"] != "OPEN_INTAKE":
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED")
    if user_id == claim["claimant_partner_id"]:
        raise ApiError("ERR_DISPUTER_IS_CLAIMANT")
    claim["disputing_partner_id"] = user_id
    claim["contested_pct"] = contested_pct
    claim["dispute_grounds"] = dispute_grounds
    claim["state"] = "DISPUTED"
    touch(claim)
    return ok(commit(claim))


@bp.post("/comp/credit-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    user_id, _ = authorize(["CreditArbiter"])
    body = get_body()
    decision = field_enum(body, "decision", DECISIONS)
    approved_pct = field_decimal(body, "approved_pct", 2, required=False,
                                 low="0.00", high="100.00")
    counterparty_pct = field_decimal(body, "counterparty_pct", 2, required=False,
                                     low="0.00", high="100.00")
    remand_reason = field_str(body, "remand_reason", required=False)
    expected = field_int(body, "expected_matter_version")
    if decision in ("ALLOCATE", "SPLIT") and approved_pct is None:
        bad()
    if decision == "SPLIT" and counterparty_pct is None:
        bad()

    claim = find_claim(claim_id)
    matter = store.matters[claim["matter_id"]]

    # rung 9: state of the acted-on row
    if claim["state"] not in ("SUBMITTED", "DISPUTED"):
        raise ApiError("ERR_CLAIM_NOT_ADJUDICABLE")
    if decision in ("SPLIT", "REMAND") and claim["state"] != "DISPUTED":
        raise ApiError("ERR_CLAIM_NOT_ADJUDICABLE")
    if decision == "REMAND" and claim["remand_count"] >= calc.MAX_REMANDS:
        raise ApiError("ERR_CLAIM_NOT_ADJUDICABLE")

    # rung 11: stale parent version
    if expected != matter["version"]:
        raise ApiError("ERR_STALE_VERSION")

    # rung 13: segregation of duties
    if user_id in (claim["claimant_partner_id"], claim["disputing_partner_id"],
                   matter["billing_attorney_id"], matter["responsible_attorney_id"]):
        raise ApiError("ERR_ARBITER_CONFLICT")

    if decision == "ALLOCATE":
        _allocate(claim, matter, approved_pct)
    elif decision == "SPLIT":
        _split(claim, matter, approved_pct, counterparty_pct)
    elif decision == "REJECT":
        _reject(claim, matter)
    else:
        _remand(claim, matter, remand_reason)

    touch(claim)
    touch(matter)
    return ok(commit(claim))


def _guard_interval(matter, new_rows):
    rows = originating_intervals(matter["id"], extra=new_rows)
    if interval_sum_exceeds_ceiling(rows):
        raise ApiError("ERR_CREDIT_INTERVAL_OVERSUBSCRIBED")


def _allocate(claim, matter, approved_pct):
    claimant_pct, counterparty_pct, prior = calc.sharing_convention(
        matter, claim["claim_basis"], approved_pct, claim["claimant_partner_id"])
    new_rows = []
    if claimant_pct > 0:
        new_rows.append((matter["opened_on"], None, claimant_pct))
    if prior is not None and counterparty_pct > 0:
        new_rows.append((matter["opened_on"], None, counterparty_pct))
    _guard_interval(matter, new_rows)

    claim["approved_pct"] = approved_pct
    claim["resolved_prior_originator_id"] = prior
    claim["state"] = "ALLOCATED"
    if claimant_pct > 0:
        create_allocation(matter, claim["claimant_partner_id"], "ORIGINATING",
                          claimant_pct, "CLAIM_ALLOCATED", matter["opened_on"])
    if prior is not None and counterparty_pct > 0:
        create_allocation(matter, prior, "ORIGINATING", counterparty_pct,
                          "SHARING_CONVENTION", matter["opened_on"])


def _split(claim, matter, approved_pct, counterparty_pct):
    if approved_pct + counterparty_pct > D("100.00"):
        raise ApiError("ERR_CREDIT_INTERVAL_OVERSUBSCRIBED")
    new_rows = []
    if approved_pct > 0:
        new_rows.append((matter["opened_on"], None, approved_pct))
    if counterparty_pct > 0:
        new_rows.append((matter["opened_on"], None, counterparty_pct))
    _guard_interval(matter, new_rows)

    claim["approved_pct"] = approved_pct
    claim["counterparty_pct"] = counterparty_pct
    claim["state"] = "ALLOCATED"
    if approved_pct > 0:
        create_allocation(matter, claim["claimant_partner_id"], "ORIGINATING",
                          approved_pct, "CLAIM_ALLOCATED", matter["opened_on"])
    if counterparty_pct > 0 and claim["disputing_partner_id"] is not None:
        create_allocation(matter, claim["disputing_partner_id"], "ORIGINATING",
                          counterparty_pct, "SHARING_CONVENTION", matter["opened_on"])


def _reject(claim, matter):
    claim["approved_pct"] = D("0.00")
    claim["state"] = "REJECTED"
    existing = [a for a in matter_allocations(matter["id"])
                if a["credit_role"] == "ORIGINATING"]
    if not existing:
        create_allocation(matter, matter["billing_attorney_id"], "ORIGINATING",
                          D("100.00"), "DEFAULT_BILLING", matter["opened_on"])


def _remand(claim, matter, remand_reason):
    claim["disputing_partner_id"] = None
    claim["contested_pct"] = None
    claim["dispute_grounds"] = None
    claim["remand_reason"] = remand_reason
    claim["revision_count"] += 1
    claim["remand_count"] += 1
    claim["state"] = "DRAFT"
