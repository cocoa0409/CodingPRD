"""NightAuditRun: open / get / list / complete / abort (PRD §3.8).
Plus the availability read endpoint (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint

import calc
import db
import helpers as H
import serialize as S
from errors import err
from middleware import authenticate, require_role
from response import success, success_list

bp = Blueprint("audit", __name__)

ALL_ROLES = {"RevenueManager", "FrontDeskAgent", "NightAuditor", "Guest"}
RM_NA = {"RevenueManager", "NightAuditor"}


def _folio_for(reservation_id):
    for f in db.folios.values():
        if f["reservation_id"] == reservation_id:
            return f
    return None


def _post_night_audit_charge(folio, amount, description):
    inc = {
        "hotel_id": folio["hotel_id"],
        "folio_id": folio["id"],
        "kind": "CHARGE",
        "description": description,
        "amount_cents": amount,
        "posted_by_kind": "NIGHT_AUDIT",
        "status": "POSTED",
    }
    db.stamp_create(inc)
    db.incidentals[inc["id"]] = inc
    db.touch(folio)


# ----------------------------------------------------------------------------
# Open audit — PRD §3.8
# ----------------------------------------------------------------------------
@bp.route("/pms/night-audit-runs", methods=["POST"])
def open_audit():
    _, role = authenticate()
    require_role(role, {"NightAuditor"})
    body = H.get_json_body()
    H.require_fields(body, ["hotel_id", "expected_hotel_version"])
    hotel = H.resolve_fk(body, "hotel_id")
    expected = H.require_int(body, "expected_hotel_version")

    # Only one IN_PROGRESS run per hotel
    for n in db.night_audit_runs.values():
        if n["hotel_id"] == hotel["id"] and n["status"] == "IN_PROGRESS":
            raise err("ERR_AUDIT_ALREADY_RUNNING", "An audit is already IN_PROGRESS")

    if expected != hotel["version"]:
        raise err("ERR_STALE_VERSION", "expected_hotel_version does not match")

    run = {
        "hotel_id": hotel["id"],
        "business_date": hotel["current_business_date"],
        "epoch": None,
        "no_show_count": 0,
        "room_postings_count": 0,
        "washed_block_count": 0,
        "status": "IN_PROGRESS",
    }
    db.stamp_create(run)
    db.night_audit_runs[run["id"]] = run

    hotel["posture"] = "AUDIT_LOCK"
    db.touch(hotel)
    return success(S.night_audit_run_out(run), status=201)


@bp.route("/pms/night-audit-runs/<resource_id>", methods=["GET"])
def get_audit(resource_id):
    _, role = authenticate()
    require_role(role, RM_NA)
    run = H.get_or_404(db.night_audit_runs, resource_id)
    return success(S.night_audit_run_out(run), status=200)


@bp.route("/pms/night-audit-runs", methods=["GET"])
def list_audits():
    _, role = authenticate()
    require_role(role, RM_NA)
    items, limit, offset, total = H.filter_and_paginate(
        db.night_audit_runs,
        S.night_audit_run_out,
        {"hotel_id": H.qparam("hotel_id"), "status": H.qparam("status")},
    )
    return success_list(items, limit, offset, total)


# ----------------------------------------------------------------------------
# Complete audit — PRD §3.8 (atomic close)
# ----------------------------------------------------------------------------
@bp.route("/pms/night-audit-runs/<resource_id>/complete", methods=["POST"])
def complete_audit(resource_id):
    _, role = authenticate()
    require_role(role, {"NightAuditor"})
    run = H.get_or_404(db.night_audit_runs, resource_id)
    body = H.get_json_body()
    H.require_fields(body, ["expected_hotel_version"])
    expected = H.require_int(body, "expected_hotel_version")

    if run["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Audit run is not IN_PROGRESS")

    hotel = db.hotels[run["hotel_id"]]
    if expected != hotel["version"]:
        raise err("ERR_STALE_VERSION", "expected_hotel_version does not match")

    business_date = run["business_date"]

    # Completion blocked by a departing CHECKED_IN reservation with OPEN/DISPUTED folio.
    for rv in db.reservations.values():
        if rv["hotel_id"] != hotel["id"]:
            continue
        if rv["status"] == "CHECKED_IN" and rv["departure_date"] == business_date:
            folio = _folio_for(rv["id"])
            if folio is not None and folio["status"] in ("OPEN", "DISPUTED"):
                raise err("ERR_AUDIT_BLOCKED_OPEN_BALANCE", "Departing reservation has an open balance")

    # ---- Cascade 1: no-show sweep ----
    no_show_count = 0
    for rv in db.reservations.values():
        if rv["hotel_id"] != hotel["id"]:
            continue
        if rv["status"] == "CONFIRMED" and rv["arrival_date"] == business_date:
            rv["status"] = "NO_SHOW"
            db.touch(rv)
            no_show_count += 1
            # no-show charge per policy
            rate_plan = db.rate_plans[rv["rate_plan_id"]]
            room_type = db.room_types[rv["room_type_id"]]
            nightly = calc.nightly_rate(rate_plan, room_type)
            policy = rate_plan["no_show_policy"]
            if policy == "FIRST_NIGHT":
                charge = nightly
            elif policy == "FULL_STAY":
                charge = nightly * rv["nights"]
            else:
                charge = 0
            folio = _folio_for(rv["id"])
            if charge > 0 and folio is not None:
                _post_night_audit_charge(folio, charge, "No-show")
            # folio close
            if folio is not None and folio["status"] != "CLOSED":
                folio["status"] = "CLOSED"
                db.touch(folio)
            # group block pickup recompute (cascade)
            if rv["group_block_id"] is not None:
                db.touch(db.group_blocks[rv["group_block_id"]])

    # ---- Cascade 2: room-charge posting for each CHECKED_IN reservation ----
    room_postings_count = 0
    for rv in db.reservations.values():
        if rv["hotel_id"] != hotel["id"]:
            continue
        if rv["status"] == "CHECKED_IN":
            rate_plan = db.rate_plans[rv["rate_plan_id"]]
            effective_type = db.room_types[rv["effective_room_type_id"]]
            nightly = calc.nightly_rate(rate_plan, effective_type)
            folio = _folio_for(rv["id"])
            if folio is not None:
                _post_night_audit_charge(folio, nightly, "Room charge")
                room_postings_count += 1

    # ---- Cascade 3: clock advance ----
    new_date = (calc.parse_date(business_date) + timedelta(days=1)).isoformat()
    hotel["current_business_date"] = new_date
    hotel["audit_epoch"] = hotel["audit_epoch"] + 1
    hotel["posture"] = "OPEN"
    db.touch(hotel)

    # ---- Cascade 4: block wash ----
    washed_block_count = 0
    new_date_d = calc.parse_date(new_date)
    for gb in db.group_blocks.values():
        if gb["hotel_id"] != hotel["id"]:
            continue
        if gb["status"] == "OPEN" and calc.parse_date(gb["cutoff_date"]) < new_date_d:
            picked = calc.block_pickup(gb["id"])
            gb["washed_rooms"] = calc.block_washed(gb["blocked_rooms"], picked)
            gb["status"] = "WASHED"
            db.touch(gb)
            washed_block_count += 1

    run["no_show_count"] = no_show_count
    run["room_postings_count"] = room_postings_count
    run["washed_block_count"] = washed_block_count
    run["epoch"] = hotel["audit_epoch"]
    run["status"] = "COMPLETED"
    db.touch(run)
    return success(S.night_audit_run_out(run), status=200)


# ----------------------------------------------------------------------------
# Abort audit — PRD §3.8
# ----------------------------------------------------------------------------
@bp.route("/pms/night-audit-runs/<resource_id>/abort", methods=["POST"])
def abort_audit(resource_id):
    _, role = authenticate()
    require_role(role, {"NightAuditor"})
    run = H.get_or_404(db.night_audit_runs, resource_id)
    body = H.get_json_body()
    H.require_fields(body, ["expected_hotel_version"])
    expected = H.require_int(body, "expected_hotel_version")

    if run["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Audit run is not IN_PROGRESS")
    hotel = db.hotels[run["hotel_id"]]
    if expected != hotel["version"]:
        raise err("ERR_STALE_VERSION", "expected_hotel_version does not match")

    run["status"] = "ABORTED"
    db.touch(run)
    hotel["posture"] = "OPEN"
    db.touch(hotel)
    return success(S.night_audit_run_out(run), status=200)


# ----------------------------------------------------------------------------
# Availability read — PRD §3.3
# ----------------------------------------------------------------------------
@bp.route("/pms/availability", methods=["GET"])
def read_availability():
    _, role = authenticate()
    require_role(role, ALL_ROLES)

    room_type_id = H.qparam("room_type_id")
    start_date = H.qparam("start_date")
    end_date = H.qparam("end_date")
    hotel_id = H.qparam("hotel_id")

    if room_type_id is None:
        raise err("ERR_INVALID_REQUEST", "room_type_id is required")
    if calc.parse_date(start_date) is None:
        raise err("ERR_INVALID_REQUEST", "start_date must be a valid YYYY-MM-DD date")
    if calc.parse_date(end_date) is None:
        raise err("ERR_INVALID_REQUEST", "end_date must be a valid YYYY-MM-DD date")

    room_type = db.room_types.get(room_type_id)
    if room_type is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced room_type_id does not exist")

    hotel = None
    if hotel_id is not None:
        hotel = db.hotels.get(hotel_id)
        if hotel is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "Referenced hotel_id does not exist")
    else:
        hotel = db.hotels.get(room_type["hotel_id"])

    cells = []
    d = calc.parse_date(start_date)
    end = calc.parse_date(end_date)
    sellable = calc.sellable_count(hotel, room_type)
    while d < end:
        stay_date = d.isoformat()
        sold = calc.sold_count(room_type_id, stay_date)
        cell = {
            "hotel_id": hotel["id"] if hotel is not None else hotel_id,
            "room_type_id": room_type_id,
            "stay_date": stay_date,
            "sold_count": sold,
            "sellable_count": sellable,
        }
        db.stamp_create(cell)
        cells.append(S.availability_cell_out(cell))
        d = d + timedelta(days=1)

    limit, offset = H.parse_pagination()
    total = len(cells)
    page = cells[offset : offset + limit]
    return success_list(page, limit, offset, total)
