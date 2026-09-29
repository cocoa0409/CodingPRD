"""Sharing cases, upgrade orders and the logical clock."""

from datetime import timedelta

from flask import Blueprint

import serializers
from db import db, fmt_instant, parse_day, parse_instant
from errors import ApiError
from middleware import (ROLE_COMPLIANCE_OFFICER, ROLE_GATE_AGENT, ROLE_PASS_OFFICE_CLERK,
                        ROLE_PASSHOLDER, ROLE_PROGRAM_ADMIN, require)
from response import created_response, list_response, object_response
from services import calc, domain
from validate import field, pagination, query_enum, query_string, read_body

bp = Blueprint("compliance", __name__)

CASE_STATUSES = ("OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED", "APPEAL_PENDING")
DECISIONS = ("SUBSTANTIATED", "DISMISSED")
CREDIT_MODES = ("PAID_TO_DATE", "PRORATED_VALUE")
UPGRADE_STATUSES = ("QUOTED", "APPLIED", "REVERSED", "EXPIRED")

UPGRADE_PROGRAM_STATUSES = ("SALES_OPEN", "SEASON_ACTIVE", "RENEWAL_OPEN")

ALL_READ_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_PASS_OFFICE_CLERK,
    ROLE_GATE_AGENT,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PASSHOLDER,
)
MONEY_READ_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_PASS_OFFICE_CLERK,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PASSHOLDER,
)


# ------------------------------------------------------------- sharing cases
@bp.post("/sharing-cases")
def open_case():
    user_id, _role = require(ROLE_GATE_AGENT)
    body = read_body({
        "season_pass_id": field("string", required=True),
        "evidence_visit_ids": field("string_array", required=True),
        "note": field("string", required=True),
    })
    season_pass = domain.get_pass(body["season_pass_id"])
    visits = [domain.get_visit(visit_id) for visit_id in body["evidence_visit_ids"]]
    if not visits:
        raise ApiError("ERR_INVALID_EVIDENCE", "evidence_visit_ids must not be empty")
    for visit in visits:
        if visit["season_pass_id"] != season_pass["id"]:
            raise ApiError("ERR_INVALID_EVIDENCE", "evidence must cite visits of the cited pass")
    holder = domain.get_passholder(season_pass["passholder_id"])
    record = db.insert("sharing_cases", {
        "season_pass_id": season_pass["id"],
        "opened_by_user_id": user_id,
        "opened_by_role": "GATE_AGENT",
        "evidence_visit_ids": list(body["evidence_visit_ids"]),
        "note": body["note"],
        "case_status": "OPEN",
        "review_round": 0,
        "risk_score_at_open": holder["sharing_risk_score"],
        "decided_by_user_id": None,
        "decision_rationale": None,
        "revocation_forfeit_cents": None,
    })
    db.commit()
    return created_response(serializers.case_out(record))


@bp.get("/sharing-cases")
def list_cases():
    require(*ALL_READ_ROLES)
    limit, offset = pagination()
    season_pass_id = query_string("season_pass_id")
    case_status = query_enum("case_status", CASE_STATUSES)
    rows = db.rows("sharing_cases")
    if season_pass_id is not None:
        rows = [r for r in rows if r["season_pass_id"] == season_pass_id]
    if case_status is not None:
        rows = [r for r in rows if r["case_status"] == case_status]
    rows = sorted(rows, key=lambda r: r["created_at"])
    return list_response([serializers.case_out(r) for r in rows], limit, offset)


@bp.get("/sharing-cases/<case_id>")
def get_case(case_id):
    require(*ALL_READ_ROLES)
    return object_response(serializers.case_out(domain.get_case(case_id)))


@bp.post("/sharing-cases/<case_id>/review")
def review_case(case_id):
    require(ROLE_COMPLIANCE_OFFICER)
    read_body({})
    case = domain.get_case(case_id)
    if case["case_status"] not in ("OPEN", "APPEAL_PENDING"):
        raise ApiError("ERR_INVALID_CASE_STATE")
    case["case_status"] = "UNDER_REVIEW"
    case["review_round"] += 1
    db.commit()
    return object_response(serializers.case_out(case))


@bp.post("/sharing-cases/<case_id>/decide")
def decide_case(case_id):
    user_id, _role = require(ROLE_COMPLIANCE_OFFICER)
    body = read_body({
        "decision": field("enum", required=True, enum=DECISIONS),
        "rationale": field("string", required=True),
    })
    case = domain.get_case(case_id)
    if case["opened_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if case["case_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_CASE_STATE")
    season_pass = domain.get_pass(case["season_pass_id"])
    case["decided_by_user_id"] = user_id
    case["decision_rationale"] = body["rationale"]
    if body["decision"] == "SUBSTANTIATED":
        case["case_status"] = "SUBSTANTIATED"
        case["revocation_forfeit_cents"] = season_pass["paid_to_date_cents"]
        domain.revoke_pass(season_pass)
        holder = domain.get_passholder(season_pass["passholder_id"])
        holder_pass_ids = {p["id"] for p in domain.holder_passes(holder["id"])}
        substantiated = sum(
            1 for c in db.rows("sharing_cases")
            if c["season_pass_id"] in holder_pass_ids and c["case_status"] == "SUBSTANTIATED"
        )
        if substantiated >= 2:
            holder["status"] = "BANNED"
    else:
        compensate = case["review_round"] >= 2
        case["case_status"] = "DISMISSED"
        if compensate and season_pass["pass_status"] == "REVOKED":
            domain.restore_revoked_pass(season_pass)
    db.commit()
    return object_response(serializers.case_out(case))


@bp.post("/sharing-cases/<case_id>/appeal")
def appeal_case(case_id):
    user_id, _role = require(ROLE_PASSHOLDER)
    body = read_body({"statement": field("string", required=True)})
    case = domain.get_case(case_id)
    season_pass = domain.get_pass(case["season_pass_id"])
    if season_pass["passholder_id"] != user_id:
        raise ApiError("ERR_NOT_PASS_OWNER")
    if case["case_status"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_CASE_STATE")
    if case["review_round"] >= 2:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED")
    case["case_status"] = "APPEAL_PENDING"
    case["decision_rationale"] = body["statement"]
    db.commit()
    return object_response(serializers.case_out(case))


# ------------------------------------------------------------- upgrade orders
@bp.post("/upgrade-orders")
def quote_upgrade():
    require(ROLE_PASS_OFFICE_CLERK)
    body = read_body({
        "season_pass_id": field("string", required=True),
        "source_tier_id": field("string", required=True),
        "target_tier_id": field("string", required=True),
        "credit_mode": field("enum", required=True, enum=CREDIT_MODES),
    })
    source_tier = domain.get_tier(body["source_tier_id"])
    target_tier = domain.get_tier(body["target_tier_id"])
    season_pass = domain.get_pass(body["season_pass_id"])
    program = domain.get_program(season_pass["program_id"])
    if program["status"] not in UPGRADE_PROGRAM_STATUSES:
        raise ApiError("ERR_PROGRAM_STATUS_INVALID")
    if target_tier["status"] != "PUBLISHED":
        raise ApiError("ERR_TIER_NOT_PUBLISHED")
    if season_pass["pass_status"] != "ACTIVE":
        raise ApiError("ERR_PASS_NOT_ACTIVE")
    if (
        source_tier["program_id"] != season_pass["program_id"]
        or target_tier["program_id"] != season_pass["program_id"]
    ):
        raise ApiError("ERR_TIER_PROGRAM_MISMATCH")
    if (
        target_tier["base_price_cents"] <= source_tier["base_price_cents"]
        or source_tier["id"] != season_pass["tier_id"]
    ):
        raise ApiError("ERR_NOT_AN_UPGRADE")

    gross_delta = target_tier["base_price_cents"] - source_tier["base_price_cents"]
    if body["credit_mode"] == "PAID_TO_DATE":
        raw_credit = season_pass["paid_to_date_cents"]
    else:
        days = domain.program_park_days(season_pass["program_id"])
        today = db.today()
        future = [d for d in days if parse_day(d["calendar_date"]) >= today]
        ratio = calc.prorated_ratio(len(future), len(days))
        raw_credit = calc.floor_int(calc.dec(source_tier["base_price_cents"]) * ratio)
    credit, net_delta, admin_fee, total_due = calc.upgrade_settlement(gross_delta, raw_credit)
    quoted_at = db.now()
    record = db.insert("upgrade_orders", {
        "season_pass_id": season_pass["id"],
        "source_tier_id": source_tier["id"],
        "target_tier_id": target_tier["id"],
        "credit_mode": body["credit_mode"],
        "gross_delta_cents": gross_delta,
        "raw_credit_cents": raw_credit,
        "credit_cents": credit,
        "net_delta_cents": net_delta,
        "admin_fee_cents": admin_fee,
        "total_due_cents": total_due,
        "payment_amount_cents": None,
        "quoted_at": db.clock_echo,
        "quote_expires_at": fmt_instant(quoted_at + timedelta(days=calc.UPGRADE_QUOTE_TTL_DAYS)),
        "status": "QUOTED",
        "reverse_reason": None,
    })
    db.commit()
    return created_response(serializers.upgrade_out(record))


@bp.get("/upgrade-orders")
def list_upgrade_orders():
    require(*MONEY_READ_ROLES)
    limit, offset = pagination()
    season_pass_id = query_string("season_pass_id")
    source_tier_id = query_string("source_tier_id")
    target_tier_id = query_string("target_tier_id")
    status = query_enum("status", UPGRADE_STATUSES)
    rows = db.rows("upgrade_orders")
    if season_pass_id is not None:
        rows = [r for r in rows if r["season_pass_id"] == season_pass_id]
    if source_tier_id is not None:
        rows = [r for r in rows if r["source_tier_id"] == source_tier_id]
    if target_tier_id is not None:
        rows = [r for r in rows if r["target_tier_id"] == target_tier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: r["created_at"])
    return list_response([serializers.upgrade_out(r) for r in rows], limit, offset)


@bp.get("/upgrade-orders/<upgrade_order_id>")
def get_upgrade_order(upgrade_order_id):
    require(*MONEY_READ_ROLES)
    return object_response(serializers.upgrade_out(domain.get_upgrade_order(upgrade_order_id)))


@bp.post("/upgrade-orders/<upgrade_order_id>/apply")
def apply_upgrade(upgrade_order_id):
    require(ROLE_PASS_OFFICE_CLERK)
    body = read_body({"payment_amount_cents": field("integer", required=True)})
    order = domain.get_upgrade_order(upgrade_order_id)
    season_pass = domain.get_pass(order["season_pass_id"])
    if season_pass["pass_status"] != "ACTIVE":
        raise ApiError("ERR_PASS_NOT_ACTIVE")
    if order["status"] != "QUOTED" or season_pass["tier_id"] != order["source_tier_id"]:
        raise ApiError("ERR_UPGRADE_ORDER_NOT_ACTIONABLE")
    if body["payment_amount_cents"] != order["total_due_cents"]:
        raise ApiError("ERR_UPGRADE_PAYMENT_INSUFFICIENT")
    target_tier = domain.get_tier(order["target_tier_id"])

    order["status"] = "APPLIED"
    order["payment_amount_cents"] = body["payment_amount_cents"]
    season_pass["tier_id"] = target_tier["id"]
    season_pass["contract_value_cents"] = target_tier["base_price_cents"]
    season_pass["billed_total_cents"] += order["gross_delta_cents"] + order["admin_fee_cents"]
    season_pass["paid_to_date_cents"] += body["payment_amount_cents"]

    # Blockout exposure is re-derived from the new tier for all future days.
    today = db.today()
    for reservation in domain.pass_reservations(season_pass["id"]):
        if reservation["status"] != "CONFIRMED":
            continue
        park_day = db.park_days.get(reservation["park_day_id"])
        if park_day is None or parse_day(park_day["calendar_date"]) < today:
            continue
        if domain.has_active_blockout(target_tier["id"], park_day["id"]):
            reservation["status"] = "CANCELLED_BY_BLOCKOUT"
    db.commit()
    return object_response(serializers.upgrade_out(order))


@bp.post("/upgrade-orders/<upgrade_order_id>/reverse")
def reverse_upgrade(upgrade_order_id):
    require(ROLE_COMPLIANCE_OFFICER)
    body = read_body({"reason": field("string", required=True)})
    order = domain.get_upgrade_order(upgrade_order_id)
    season_pass = domain.get_pass(order["season_pass_id"])
    if order["status"] != "APPLIED" or season_pass["tier_id"] != order["target_tier_id"]:
        raise ApiError("ERR_UPGRADE_ORDER_NOT_ACTIONABLE")
    source_tier = domain.get_tier(order["source_tier_id"])
    order["status"] = "REVERSED"
    order["reverse_reason"] = body["reason"]
    season_pass["tier_id"] = source_tier["id"]
    season_pass["contract_value_cents"] = source_tier["base_price_cents"]
    season_pass["billed_total_cents"] -= order["gross_delta_cents"] + order["admin_fee_cents"]
    season_pass["paid_to_date_cents"] -= (order["payment_amount_cents"] or 0)
    db.commit()
    return object_response(serializers.upgrade_out(order))


# --------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    require(ROLE_PROGRAM_ADMIN)
    body = read_body({"to_iso8601": field("datetime", required=True)})
    moment = parse_instant(body["to_iso8601"])
    db.set_clock(moment, body["to_iso8601"])
    return object_response({"current_utc": body["to_iso8601"]})
