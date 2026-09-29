"""Community registration, standards amendment, sweeps, and the logical clock."""

from flask import Blueprint

from db import base_fields, db, iso, iso_now, plus_days, sort_rows, to_dt, touch
from errors import fail
from middleware import ALL_ROLES, require
from response import object_response, raw_response
from services import calc, engine
from validation import (body, lookup, opt_int, opt_num, req_dt, req_int,
                       req_state_code, req_str)

bp = Blueprint("communities", __name__)


@bp.post("/communities")
def create_community():
    require("StateNfipCoordinator")
    data = body()
    name = req_str(data, "name")
    state_code = req_state_code(data, "state_code")
    cid_number = req_str(data, "cid_number")
    freeboard = opt_num(data, "freeboard_ft", default=calc.D("1.0"),
                        minimum=0, maximum=6, max_decimals=2)
    years = opt_int(data, "cumulative_period_years", default=10, minimum=0, maximum=25)

    if any(c["cid_number"] == cid_number for c in db.communities.values()):
        fail("ERR_DUPLICATE_CID_NUMBER")

    row = base_fields()
    row.update({
        "name": name,
        "state_code": state_code,
        "cid_number": cid_number,
        "freeboard_ft": freeboard,
        "cumulative_period_years": years,
        "standards_adopted_at": iso_now(),
        "sanction_risk_points": 0,
        "compliance_posture": "GOOD_STANDING",
        "crs_credit_points_claimed": 0,
        "crs_credit_points_verified": 0,
        "crs_class": calc.WORST_CRS_CLASS,
    })
    db.communities[row["id"]] = row
    return object_response(row, 201)


@bp.get("/communities/<community_id>")
def read_community(community_id):
    require(*ALL_ROLES)
    return object_response(lookup("community", community_id))


@bp.patch("/communities/<community_id>")
def amend_community(community_id):
    require("FloodplainAdministrator")
    community = lookup("community", community_id)
    data = body()
    freeboard = opt_num(data, "freeboard_ft", minimum=0, maximum=6, max_decimals=2)
    years = opt_int(data, "cumulative_period_years", minimum=0, maximum=25)

    if freeboard is not None:
        community["freeboard_ft"] = freeboard
    if years is not None:
        community["cumulative_period_years"] = years
    community["standards_adopted_at"] = iso_now()

    for standard in sort_rows(engine.standards_of(community_id)):
        if standard["documentation_status"] != "VERIFIED":
            continue
        ceiling = engine.max_points_for(standard, community)
        moved = standard["max_points_allowed"] != ceiling
        standard["max_points_allowed"] = ceiling
        if ceiling < standard["verified_points"]:
            engine.expire_standard(standard, community)
        elif moved:
            touch(standard)

    engine.recompute_verified(community)
    community["crs_class"] = engine.crs_class_for(
        community["crs_credit_points_verified"], community)
    touch(community)
    return object_response(community)


@bp.get("/communities/<community_id>/compliance-summary")
def compliance_summary(community_id):
    require("StateNfipCoordinator", "FloodplainAdministrator")
    community = lookup("community", community_id)
    breakdown = engine.sanction_breakdown(community)
    return raw_response({
        "community_id": community["id"],
        "sanction_risk_points": community["sanction_risk_points"],
        "compliance_posture": community["compliance_posture"],
        "counted_violation_count": breakdown["counted_violation_count"],
        "defaulted_order_count": breakdown["defaulted_order_count"],
        "a510_credit_applied": breakdown["credit"],
        "crs_class": community["crs_class"],
        "crs_credit_points_claimed": community["crs_credit_points_claimed"],
        "crs_credit_points_verified": community["crs_credit_points_verified"],
        "freeboard_ft": float(community["freeboard_ft"]),
        "cumulative_period_years": community["cumulative_period_years"],
    })


@bp.post("/communities/<community_id>/inspection-sweep")
def inspection_sweep(community_id):
    require("FloodplainAdministrator")
    community = lookup("community", community_id)
    data = body()
    declaration_code = req_str(data, "declaration_code")
    event_date = req_dt(data, "event_date")
    window_days = req_int(data, "inspection_window_days", minimum=0)
    deadline_at = plus_days(event_date, window_days)

    # Step 18 — sweep interval geometry precedes the uniqueness family.
    window_start = plus_days(event_date, -calc.SWEEP_BUFFER_DAYS)
    window_end = plus_days(deadline_at, calc.SWEEP_BUFFER_DAYS)
    for sweep in db.sweeps:
        if sweep["community_id"] != community_id:
            continue
        if window_start <= to_dt(sweep["deadline_at"]) and to_dt(sweep["disaster_event_date"]) <= window_end:
            fail("ERR_SWEEP_WINDOW_CONFLICT")
    for sweep in db.sweeps:
        if sweep["community_id"] == community_id and sweep["declaration_code"] == declaration_code:
            fail("ERR_DUPLICATE_DECLARATION_CODE")

    eligible = []
    for prop in engine.props_of_community(community_id):
        panel = db.firm_panels.get(prop["firm_panel_id"])
        if panel is None or panel["status"] != "EFFECTIVE":
            continue
        if panel["flood_zone"] not in ("A", "AE", "AO", "VE"):
            continue
        eligible.extend(engine.structures_of_property(prop["id"]))

    created = []
    for structure in sort_rows(eligible):
        row = base_fields()
        row.update({
            "structure_id": structure["id"],
            "declaration_code": declaration_code,
            "disaster_event_date": iso(event_date),
            "deadline_at": iso(deadline_at),
            "status": "SCHEDULED",
            "damage_cost_usd": None,
            "claim_paid_amount_usd": calc.money(0),
            "market_value_at_inspection_usd": None,
            "damage_ratio_pct": None,
            "assessed_at": None,
            "finalized_at": None,
        })
        db.inspections[row["id"]] = row
        created.append(row)

    db.sweeps.append({
        "community_id": community["id"],
        "declaration_code": declaration_code,
        "disaster_event_date": iso(event_date),
        "inspection_window_days": window_days,
        "deadline_at": iso(deadline_at),
    })

    return raw_response({
        "declaration_code": declaration_code,
        "event_date": iso(event_date),
        "deadline_at": iso(deadline_at),
        "inspections_created": len(created),
        "inspection_ids": [r["id"] for r in created],
    }, 201)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require("StateNfipCoordinator", "FloodplainAdministrator")
    data = body()
    target = req_dt(data, "to_iso8601")
    if target < db.clock:
        fail("ERR_CLOCK_NOT_MONOTONIC")
    previous = db.clock
    db.clock = target
    return raw_response({"current_utc": iso(target), "previous_utc": iso(previous)})
