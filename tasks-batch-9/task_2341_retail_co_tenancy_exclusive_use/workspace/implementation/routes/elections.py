"""Remedy elections: pricing, the approval fork and the consummation join."""
from flask import Blueprint

import engine
import validate as v
from crud import apply_filters, base, paginate, resolve, strip
from db import store
from errors import ApiError
from middleware import (LIST_READ_ROLES, SINGLE_READ_ROLES, authorize,
                        tenant_scope_lease)
from response import created, listing, ok
from util import D, add_days, as_date, fmt_date, fmt_dt, parse_dt

bp = Blueprint("elections", __name__)

ELECTION_KINDS = ("RENT_REDUCTION", "TERMINATION", "SUBSTITUTE_RENT")

PERMITTED = {
    "RENT_REDUCTION_ONLY": ("RENT_REDUCTION",),
    "TERMINATION_ONLY": ("TERMINATION",),
    "RENT_REDUCTION_THEN_TERMINATION": ("RENT_REDUCTION", "TERMINATION"),
}


def get_election(election_id):
    return resolve(store.elections, election_id, "ERR_ELECTION_NOT_FOUND")


@bp.post("/leases/<lease_id>/remedy-elections")
def create_election(lease_id):
    role, user_id = authorize(["TenantRep"])
    body = v.body()
    election_kind = v.req_enum(body, "election_kind", ELECTION_KINDS)
    from_date = v.req_date(body, "window_from_date")
    through_date = v.req_date(body, "window_through_date")
    expected_version = v.req_int(body, "expected_lease_version", minimum=0)
    condition_id = v.opt_id(body, "condition_id")
    source_notice_id = v.opt_id(body, "source_notice_id")
    if (condition_id is None) == (source_notice_id is None):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Exactly one of condition_id or source_notice_id is required")

    lease = resolve(store.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    cond = None
    notice = None
    if condition_id is not None:
        cond = resolve(store.conditions, condition_id, "ERR_CONDITION_NOT_FOUND")
    if source_notice_id is not None:
        notice = resolve(store.notices, source_notice_id, "ERR_NOTICE_NOT_FOUND")

    tenant_scope_lease(role, user_id, lease)

    if cond is not None:
        benefited = store.leases.get(cond["lease_id"])
        if benefited is None or benefited["center_id"] != lease["center_id"]:
            raise ApiError("ERR_CENTER_SCOPE_MISMATCH")
    if notice is not None:
        violating = store.leases.get(notice["violating_lease_id"])
        if violating is None or violating["center_id"] != lease["center_id"]:
            raise ApiError("ERR_CENTER_SCOPE_MISMATCH")

    if expected_version != lease["version"]:
        raise ApiError("ERR_STALE_LEASE_VERSION")

    # rung 11 outranks rung 16 (pinned collision)
    if lease["remedy_status"] not in ("ELIGIBLE", "REMEDY_ACTIVE"):
        raise ApiError("ERR_REMEDY_NOT_ELIGIBLE")

    if cond is not None:
        if election_kind not in PERMITTED.get(cond["remedy_type"], ()):
            raise ApiError("ERR_REMEDY_KIND_NOT_PERMITTED")
    elif election_kind == "SUBSTITUTE_RENT" and cond is not None:
        raise ApiError("ERR_REMEDY_KIND_NOT_PERMITTED")

    if as_date(through_date) <= as_date(from_date):
        raise ApiError("ERR_ABATEMENT_WINDOW_INVALID")
    if cond is not None and cond.get("breach_detected_at"):
        breach_date = parse_dt(cond["breach_detected_at"]).date()
        if as_date(from_date) < breach_date:
            raise ApiError("ERR_ABATEMENT_WINDOW_INVALID")

    pricing = engine.price_election(lease, cond, notice is not None)

    election = base(engine.stamp())
    election.update({
        "lease_id": lease["id"],
        "condition_id": condition_id,
        "source_notice_id": source_notice_id,
        "election_kind": election_kind,
        "window_from_date": from_date,
        "window_through_date": through_date,
        "elected_at": engine.stamp(),
        "shortfall_pct_at_election": pricing["shortfall_pct_at_election"],
        "anchor_bonus_applied": pricing["anchor_bonus_applied"],
        "reduction_pct": pricing["reduction_pct"],
        "reduced_rent_monthly_cents": pricing["reduced_rent_monthly_cents"],
        "termination_effective_date": None,
        "abated_to_date_cents": 0,
        "status": "ELECTED",
        "approved_by_user_id": None,
        "approved_at": None,
    })

    # a new election supersedes any prior merely-ELECTED election of the lease
    for other in engine.elections_of_lease(lease["id"]):
        if other["status"] == "ELECTED":
            other["status"] = "RESCINDED"
            other["abated_to_date_cents"] = 0
            engine.touch(other)

    store.elections[election["id"]] = election
    return created(strip(election))


@bp.get("/remedy-elections/<election_id>")
def read_election(election_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(get_election(election_id)))


@bp.get("/remedy-elections")
def list_elections():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    records = engine._ordered(list(store.elections.values()))
    records = apply_filters(records, [
        ("lease_id", v.filter_value("lease_id")),
        ("condition_id", v.filter_value("condition_id")),
        ("source_notice_id", v.filter_value("source_notice_id")),
        ("election_kind", v.filter_value("election_kind")),
        ("status", v.filter_value("status")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


def _overlaps_half_open(a_from, a_through, b_from, b_through):
    return a_from < b_through and b_from < a_through


@bp.post("/remedy-elections/<election_id>/approve")
def approve(election_id):
    role, user_id = authorize(["AssetManager"])
    v.body()
    election = get_election(election_id)
    lease = resolve(store.leases, election["lease_id"], "ERR_LEASE_NOT_FOUND")
    cond = store.conditions.get(election.get("condition_id")) \
        if election.get("condition_id") else None

    if election["status"] != "ELECTED":
        raise ApiError("ERR_ELECTION_STATE_INVALID")
    if lease["remedy_status"] not in ("ELIGIBLE", "REMEDY_ACTIVE"):
        raise ApiError("ERR_LEASE_STATE_INVALID")

    terminating = election["election_kind"] == "TERMINATION"
    if terminating and cond is not None \
            and cond["remedy_type"] not in ("RENT_REDUCTION_THEN_TERMINATION",
                                            "TERMINATION_ONLY"):
        raise ApiError("ERR_REMEDY_KIND_NOT_PERMITTED")

    window_from = as_date(election["window_from_date"])
    window_through = as_date(election["window_through_date"])

    # rung 20 outranks rung 21 (pinned collision)
    if window_through <= window_from:
        raise ApiError("ERR_ABATEMENT_WINDOW_INVALID")
    if cond is not None and cond.get("breach_detected_at"):
        if window_from < parse_dt(cond["breach_detected_at"]).date():
            raise ApiError("ERR_ABATEMENT_WINDOW_INVALID")
    if not terminating:
        if window_from < as_date(lease["commencement_date"]) \
                or window_through > as_date(lease["expiration_date"]):
            raise ApiError("ERR_ABATEMENT_WINDOW_INVALID")

        stacked = D(election["reduction_pct"])
        for other in engine.elections_of_lease(lease["id"]):
            if other["id"] == election["id"] or other["status"] != "REDUCTION_ACTIVE":
                continue
            if _overlaps_half_open(window_from, window_through,
                                   as_date(other["window_from_date"]),
                                   as_date(other["window_through_date"])):
                stacked += D(other["reduction_pct"])
        if stacked > D(100):
            raise ApiError("ERR_ABATEMENT_STACK_EXCEEDED")

    termination_effective_date = None
    if terminating:
        termination_effective_date = fmt_date(
            add_days(window_from, engine.TERMINATION_NOTICE_DAYS))
        if cond is not None:
            if cond["consecutive_breach_days"] < cond["cure_period_days"]:
                raise ApiError("ERR_CURE_PERIOD_NOT_EXPIRED")
            if cond.get("breach_detected_at"):
                earliest = add_days(parse_dt(cond["breach_detected_at"]).date(),
                                    cond["cure_period_days"])
                if as_date(termination_effective_date) < earliest:
                    raise ApiError("ERR_CURE_PERIOD_NOT_EXPIRED")

    election["approved_by_user_id"] = user_id
    election["approved_at"] = engine.stamp()
    center = engine.center_of_lease(lease)

    if terminating:
        election["status"] = "TERMINATION_SCHEDULED"
        election["termination_effective_date"] = termination_effective_date
        engine.touch(election)
        lease["remedy_status"] = "TERMINATION_PENDING"
        engine.touch_lease(lease)
    else:
        election["status"] = "REDUCTION_ACTIVE"
        engine.touch(election)
        lease["remedy_status"] = "REMEDY_ACTIVE"
        engine.recompute_lease_money(lease)
        engine.touch_lease(lease)

    if center is not None:
        engine.bump_center(center)
    return ok(strip(election))


@bp.post("/remedy-elections/<election_id>/rescind")
def rescind(election_id):
    role, user_id = authorize(["AssetManager", "TenantRep"])
    body = v.body()
    v.opt_str(body, "rescission_reason_code")
    election = get_election(election_id)
    lease = resolve(store.leases, election["lease_id"], "ERR_LEASE_NOT_FOUND")
    tenant_scope_lease(role, user_id, lease)

    previous = election["status"]
    if previous not in ("ELECTED", "REDUCTION_ACTIVE", "TERMINATION_SCHEDULED"):
        raise ApiError("ERR_ELECTION_STATE_INVALID")

    election["status"] = "RESCINDED"
    election["abated_to_date_cents"] = 0
    election.pop("_accrual_frozen_date", None)
    engine.touch(election)

    if previous == "REDUCTION_ACTIVE":
        engine.recompute_lease_money(lease)
        if lease["remedy_status"] == "REMEDY_ACTIVE":
            remaining = [e for e in engine.elections_of_lease(lease["id"])
                         if e["status"] == "REDUCTION_ACTIVE"]
            if not remaining:
                if engine.has_breached_condition(lease):
                    lease["remedy_status"] = "ELIGIBLE"
                else:
                    lease["remedy_status"] = "NONE"
                    lease["remedy_eligible_at"] = None
        engine.touch_lease(lease)
    elif previous == "TERMINATION_SCHEDULED":
        if lease["remedy_status"] == "TERMINATION_PENDING":
            lease["remedy_status"] = "ELIGIBLE"
        engine.recompute_lease_money(lease)
        engine.touch_lease(lease)

    center = engine.center_of_lease(lease)
    if center is not None:
        engine.bump_center(center)
    return ok(strip(election))


@bp.post("/remedy-elections/<election_id>/consummate")
def consummate(election_id):
    authorize(["AssetManager"])
    v.body()
    election = get_election(election_id)
    lease = resolve(store.leases, election["lease_id"], "ERR_LEASE_NOT_FOUND")
    center = engine.center_of_lease(lease)
    day = engine.today()

    if election["status"] == "REDUCTION_ACTIVE":
        if as_date(election["window_through_date"]) > day:
            raise ApiError("ERR_ELECTION_STATE_INVALID",
                           "The abatement window has not closed yet")
        engine.consummate_reduction(election, lease)
    elif election["status"] == "TERMINATION_SCHEDULED":
        if not election.get("termination_effective_date") \
                or as_date(election["termination_effective_date"]) > day:
            raise ApiError("ERR_ELECTION_STATE_INVALID",
                           "The termination effective date has not arrived yet")
        engine.consummate_termination(election, lease)
    else:
        raise ApiError("ERR_ELECTION_STATE_INVALID")

    if center is not None:
        engine.bump_center(center)
    return ok(strip(election))
