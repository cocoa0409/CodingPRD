"""Franchisee accounts, properties and contractors (PRD section 3.1, 3.9)."""

from flask import g

import calc
import domain
import guards
import repo
import validation as v
from errors import ApiError
from middleware import ANY_ROLE, BRAND_INSPECTOR, BRAND_MANAGER, FRANCHISEE_OWNER
from response import object_response
from routing import route

STANDINGS = ("GOOD", "WATCH", "DEFAULT", "TERMINATED_PORTFOLIO")
POSTURES = ("COMPLIANT", "AT_RISK", "IN_DEFAULT", "TERMINATED")


# --------------------------------------------------------------------------
# FranchiseeAccount
# --------------------------------------------------------------------------
@route("/pip/franchisee-accounts", ["POST"], (BRAND_MANAGER,))
def create_franchisee():
    body = v.body_json()
    v.require(body, "legal_name", "contact_email")
    legal_name = v.get_str(body, "legal_name", min_len=1, max_len=200)
    contact_email = v.get_str(body, "contact_email", min_len=1, max_len=200)
    if "@" not in contact_email:
        raise ApiError("ERR_VALIDATION", "contact_email must contain @")

    row = repo.new_row(
        {
            "legal_name": legal_name,
            "contact_email": contact_email,
            "portfolio_property_count": 0,
            "standing": "GOOD",
        }
    )
    repo.insert("franchisees", row)
    return repo.single(row, 201)


@route("/pip/franchisee-accounts/<row_id>", ["GET"], ANY_ROLE)
def get_franchisee(row_id):
    return repo.single(repo.must_find("franchisees", row_id))


@route("/pip/franchisee-accounts", ["GET"], (BRAND_MANAGER, BRAND_INSPECTOR))
def list_franchisees():
    limit, offset = v.pagination()
    rows = repo.rows("franchisees")
    standing = v.query_str("standing")
    if standing is not None:
        rows = [r for r in rows if r["standing"] == standing]
    return repo.page(rows, limit, offset)


# --------------------------------------------------------------------------
# Property
# --------------------------------------------------------------------------
@route("/pip/properties", ["POST"], (BRAND_MANAGER,))
def create_property():
    body = v.body_json()
    franchisee = guards.resolve_body_fk(body, "franchisee_id", "franchisees")

    v.require(
        body,
        "franchisee_id",
        "brand_code",
        "name",
        "room_count",
        "adr_baseline_cents",
        "occupancy_baseline_pct",
        "reserve_balance_cents",
        "minimum_retention_cents",
    )
    brand_code = v.get_str(body, "brand_code", min_len=1, max_len=20)
    name = v.get_str(body, "name", min_len=1, max_len=200)
    room_count = v.get_int(body, "room_count", minimum=1)
    adr = v.get_int(body, "adr_baseline_cents", minimum=0)
    occupancy = v.get_number(body, "occupancy_baseline_pct", minimum=0, maximum=1)
    reserve_balance = v.get_int(body, "reserve_balance_cents", minimum=0)
    retention = v.get_int(body, "minimum_retention_cents", minimum=0)

    row = repo.new_row(
        {
            "franchisee_id": franchisee["id"],
            "brand_code": brand_code,
            "name": name,
            "room_count": room_count,
            "adr_baseline_cents": adr,
            "occupancy_baseline_pct": occupancy,
            "reserve_balance_cents": reserve_balance,
            "minimum_retention_cents": retention,
            "reserve_contributed_total_cents": 0,
            "initial_reserve_balance_cents": reserve_balance,
            "rooms_out_of_service_current": 0,
            "franchise_agreement_status": "ACTIVE",
            "compliance_risk_score": 100,
            "compliance_posture": "COMPLIANT",
            "open_plan_count": 0,
            "_terminated": False,
        }
    )
    repo.insert("properties", row)
    domain.recompute_franchisee(franchisee["id"])
    return repo.single(row, 201)


@route("/pip/properties/<row_id>", ["GET"], ANY_ROLE)
def get_property(row_id):
    return repo.single(repo.must_find("properties", row_id))


@route("/pip/properties", ["GET"], ANY_ROLE)
def list_properties():
    limit, offset = v.pagination()
    rows = repo.rows("properties")
    franchisee_id = v.query_str("franchisee_id")
    if franchisee_id is not None:
        rows = [r for r in rows if r["franchisee_id"] == franchisee_id]
    posture = v.query_str("compliance_posture")
    if posture is not None:
        rows = [r for r in rows if r["compliance_posture"] == posture]
    return repo.page(rows, limit, offset)


@route("/pip/properties/<row_id>", ["PATCH"], (BRAND_MANAGER,))
def patch_property(row_id):
    prop = repo.must_find("properties", row_id)
    body = v.body_json()

    if v.present(body, "adr_baseline_cents"):
        prop["adr_baseline_cents"] = v.get_int(body, "adr_baseline_cents", minimum=0)
    if v.present(body, "occupancy_baseline_pct"):
        prop["occupancy_baseline_pct"] = v.get_number(
            body, "occupancy_baseline_pct", minimum=0, maximum=1
        )
    if v.present(body, "minimum_retention_cents"):
        prop["minimum_retention_cents"] = v.get_int(
            body, "minimum_retention_cents", minimum=0
        )
    if v.present(body, "room_count"):
        prop["room_count"] = v.get_int(body, "room_count", minimum=1)

    repo.touch(prop)
    domain.recompute_property(prop)
    return repo.single(prop)


@route("/pip/properties/<row_id>/reserve-contributions", ["POST"], (FRANCHISEE_OWNER,))
def credit_reserve_contribution(row_id):
    prop = repo.must_find("properties", row_id)
    body = v.body_json()
    v.require(body, "amount_cents")
    amount = v.get_int(body, "amount_cents", minimum=1)

    guards.require_owner(prop)

    prop["reserve_balance_cents"] += amount
    prop["reserve_contributed_total_cents"] += amount
    repo.touch(prop)
    domain.recompute_property(prop)
    return repo.single(prop)


@route("/pip/properties/<row_id>/risk-summary", ["GET"], ANY_ROLE)
def property_risk_summary(row_id):
    prop = repo.must_find("properties", row_id)
    breakdown = domain.risk_breakdown(prop)
    snapshot_score = breakdown["snapshot_score"]
    projected_score = breakdown["projected_score"]
    data = {
        "property_id": prop["id"],
        "snapshot_score": snapshot_score,
        "snapshot_posture": domain.derive_posture(prop, snapshot_score),
        "projected_score": projected_score,
        "projected_posture": domain.derive_posture(prop, projected_score),
        "projection_horizon_days": calc.PROJECTION_HORIZON_DAYS,
        "overdue_life_safety_count": breakdown["snapshot_counts"]["LIFE_SAFETY"],
        "overdue_guest_facing_count": breakdown["snapshot_counts"]["GUEST_FACING"],
        "overdue_back_of_house_count": breakdown["snapshot_counts"]["BACK_OF_HOUSE"],
        "projected_life_safety_count": breakdown["projected_counts"]["LIFE_SAFETY"],
        "projected_guest_facing_count": breakdown["projected_counts"]["GUEST_FACING"],
        "projected_back_of_house_count": breakdown["projected_counts"]["BACK_OF_HOUSE"],
        "funding_gap_cents": breakdown["funding_gap_cents"],
        "funding_gap_penalty": breakdown["funding_gap_penalty"],
        "open_major_defect_count": breakdown["open_major_defect_count"],
        "open_critical_defect_count": breakdown["open_critical_defect_count"],
        "open_plan_count": breakdown["open_plan_count"],
    }
    return object_response(data)


# --------------------------------------------------------------------------
# Contractor
# --------------------------------------------------------------------------
@route("/pip/contractors", ["POST"], (BRAND_MANAGER,))
def create_contractor():
    body = v.body_json()
    v.require(body, "name", "trade")
    name = v.get_str(body, "name", min_len=1, max_len=200)
    trade = v.get_enum(body, "trade", calc.TRADES)
    brand_approved = v.get_bool(body, "brand_approved", required=False, default=False)
    max_concurrent = v.get_int(
        body, "max_concurrent_bookings", required=False, minimum=1, default=1
    )

    row = repo.new_row(
        {
            "name": name,
            "trade": trade,
            "brand_approved": brand_approved,
            "max_concurrent_bookings": max_concurrent,
        }
    )
    repo.insert("contractors", row)
    return repo.single(row, 201)


@route("/pip/contractors/<row_id>", ["GET"], ANY_ROLE)
def get_contractor(row_id):
    return repo.single(repo.must_find("contractors", row_id))


@route("/pip/contractors", ["GET"], ANY_ROLE)
def list_contractors():
    limit, offset = v.pagination()
    rows = repo.rows("contractors")
    trade = v.query_str("trade")
    if trade is not None:
        rows = [r for r in rows if r["trade"] == trade]
    brand_approved = v.query_bool("brand_approved")
    if brand_approved is not None:
        if brand_approved == "__unresolvable__":
            rows = []
        else:
            rows = [r for r in rows if r["brand_approved"] is brand_approved]
    return repo.page(rows, limit, offset)
