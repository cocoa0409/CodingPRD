"""Contract lifecycle endpoints."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CONTRACT_NOT_YET_STARTED,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import (
    authenticate,
    district_ownership,
    get_or_404,
    read_scoping,
    require_roles,
)
from services.coverage import terminate_contract_cascade
from validation import (
    get_body,
    opt_int,
    paginate,
    pagination_params,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("contracts", __name__)

READ_ROLES = {"SystemAdmin", "DistrictAdmin", "ContractorOps", "FinanceClerk"}
TERMINAL = ("EXPIRED", "TERMINATED", "WITHDRAWN", "LOST")
AMENDABLE = (
    "daily_rate_per_bus_cents",
    "fuel_base_price_cents",
    "fuel_escalation_trigger_pct",
    "fuel_escalation_share_pct",
    "monthly_cap_cents",
    "shortage_penalty_flat_cents",
    "shortage_penalty_per_student_minute_cents",
)


def check_transition(rec, allowed_from):
    if rec["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Contract is in a terminal state")
    if rec["status"] not in allowed_from:
        raise_err(
            ERR_INVALID_STATE,
            "Contract in state %s cannot perform this transition" % rec["status"],
        )


@bp.route("/busops/contracts", methods=["POST"])
def create_contract():
    body = get_body()
    district_id = req_str(body, "district_id")
    bid_reference = req_str(body, "bid_reference")
    daily_rate = req_int(body, "daily_rate_per_bus_cents", minimum=0)
    school_days = req_int(body, "school_days_per_year", minimum=0)
    fuel_base = req_int(body, "fuel_base_price_cents", minimum=0)
    trigger_pct = opt_int(body, "fuel_escalation_trigger_pct", default=5, minimum=0)
    share_pct = opt_int(body, "fuel_escalation_share_pct", default=80, minimum=0)
    penalty_mode = req_enum(body, "penalty_mode", ("FLAT_PER_ROUTE", "PER_STUDENT_MINUTE"))
    flat = req_int(body, "shortage_penalty_flat_cents", minimum=0)
    per_min = req_int(body, "shortage_penalty_per_student_minute_cents", minimum=0)
    assumed = req_int(body, "assumed_minutes_per_missed_route", minimum=0)
    cap = req_int(body, "monthly_cap_cents", minimum=0)
    hourly = req_int(body, "charter_hourly_rate_cents", minimum=0)
    per_mile = req_int(body, "charter_per_mile_cents", minimum=0)
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    get_or_404("districts", district_id, "District")

    rec = {
        "id": db.new_id(),
        "district_id": district_id,
        "bid_reference": bid_reference,
        "daily_rate_per_bus_cents": daily_rate,
        "school_days_per_year": school_days,
        "fuel_base_price_cents": fuel_base,
        "fuel_escalation_trigger_pct": trigger_pct,
        "fuel_escalation_share_pct": share_pct,
        "penalty_mode": penalty_mode,
        "shortage_penalty_flat_cents": flat,
        "shortage_penalty_per_student_minute_cents": per_min,
        "assumed_minutes_per_missed_route": assumed,
        "monthly_cap_cents": cap,
        "charter_hourly_rate_cents": hourly,
        "charter_per_mile_cents": per_mile,
        "start_date": start_date,
        "end_date": end_date,
        "status": "DRAFT_BID",
        "amendment_seq": 0,
        "_district_ref": district_id,
    }
    db.stamp_new(rec)
    db.STORES["contracts"][rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.route("/busops/contracts", methods=["GET"])
def list_contracts():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    items = list(db.all_of("contracts"))
    district_id = request.args.get("district_id")
    status = request.args.get("status")
    if district_id is not None:
        items = [c for c in items if c["district_id"] == district_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/contracts/<rid>", methods=["GET"])
def get_contract(rid):
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    rec = get_or_404("contracts", rid, "Contract")
    err = read_scoping(actor, rec)
    if err:
        raise err
    return success_object(db.public(rec))


@bp.route("/busops/contracts/<rid>/submit", methods=["POST"])
def submit_contract(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    rec = get_or_404("contracts", rid, "Contract")
    check_transition(rec, ("DRAFT_BID",))
    rec["status"] = "SUBMITTED"
    db.touch(rec)
    return success_object(db.public(rec))


@bp.route("/busops/contracts/<rid>/award", methods=["POST"])
def award_contract(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin"})
    rec = get_or_404("contracts", rid, "Contract")
    district_ownership(actor, rec["district_id"])
    check_transition(rec, ("SUBMITTED",))
    rec["status"] = "AWARDED"
    db.touch(rec)
    return success_object(db.public(rec))


@bp.route("/busops/contracts/<rid>/mark-lost", methods=["POST"])
def mark_lost_contract(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin"})
    rec = get_or_404("contracts", rid, "Contract")
    district_ownership(actor, rec["district_id"])
    check_transition(rec, ("SUBMITTED",))
    rec["status"] = "LOST"
    db.touch(rec)
    return success_object(db.public(rec))


@bp.route("/busops/contracts/<rid>/withdraw", methods=["POST"])
def withdraw_contract(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    rec = get_or_404("contracts", rid, "Contract")
    check_transition(rec, ("SUBMITTED",))
    rec["status"] = "WITHDRAWN"
    db.touch(rec)
    return success_object(db.public(rec))


@bp.route("/busops/contracts/<rid>/activate", methods=["POST"])
def activate_contract(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    rec = get_or_404("contracts", rid, "Contract")
    check_transition(rec, ("AWARDED",))
    start = db.parse_date(rec["start_date"])
    if start is not None and db.clock_date() < start:
        raise_err(
            ERR_CONTRACT_NOT_YET_STARTED,
            "Activation requires logical clock date >= contract.start_date",
        )
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return success_object(db.public(rec))


@bp.route("/busops/contracts/<rid>/terminate", methods=["POST"])
def terminate_contract(rid):
    body = get_body()
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin"})
    rec = get_or_404("contracts", rid, "Contract")
    district_ownership(actor, rec["district_id"])
    check_transition(rec, ("ACTIVE",))
    rec["status"] = "TERMINATED"
    db.touch(rec)
    terminate_contract_cascade(rec)
    return success_object(db.public(rec))


@bp.route("/busops/contracts/<rid>/amendments", methods=["POST"])
def amend_contract(rid):
    body = get_body()
    expected = req_int(body, "expected_contract_version")
    updates = {}
    for field in AMENDABLE:
        if field in body and body[field] is not None:
            updates[field] = req_int(body, field, minimum=0)
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin"})
    rec = get_or_404("contracts", rid, "Contract")
    district_ownership(actor, rec["district_id"])
    if expected != rec["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_contract_version does not match the contract's current version",
        )
    check_transition(rec, ("AWARDED", "ACTIVE"))
    for field, value in updates.items():
        rec[field] = value
    rec["amendment_seq"] += 1
    db.touch(rec)
    return success_object(db.public(rec))
