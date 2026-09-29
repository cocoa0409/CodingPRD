"""Transport permits, corridor legs and escort reservations (PRD 3.4, 3.5)."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
from envelope import object_response
from errors import fail
from guards import (
    ANY_ROLE,
    actor_id,
    apply_filters,
    filters,
    lookup,
    lookup_ref,
    roles,
    validate,
)
from routes_partners import list_response
from store import base_row, db, mark, parse_instant

bp = Blueprint("transport", __name__)


# ---------------------------------------------------------------------------
# TransportPermit
# ---------------------------------------------------------------------------
@bp.post("/installations/permits")
@roles("PermitDesk")
def create_permit():
    body = validate(
        [
            {"name": "section_id", "type": "string", "required": True},
            {"name": "state_code", "type": "state_code", "required": True},
            {
                "name": "planned_leg_count",
                "type": "integer",
                "required": True,
                "min": 1,
                "max": 6,
            },
            {"name": "expected_section_version", "type": "integer", "required": True},
            {"name": "night_move", "type": "boolean", "required": False},
        ]
    )
    section = lookup_ref("sections", body["section_id"], "ERR_SECTION_NOT_FOUND")
    if body["expected_section_version"] != section["version"]:
        fail("ERR_STALE_SECTION_VERSION")

    row = base_row()
    row.update(
        {
            "section_id": section["id"],
            "state_code": body["state_code"],
            "night_move": bool(body.get("night_move", False)),
            "planned_leg_count": body["planned_leg_count"],
            "permit_class": None,
            "escort_count_required": None,
            "pilot_car_required": None,
            "provisional_fee_cents": None,
            "final_fee_cents": None,
            "paid_amount_cents": 0,
            "valid_until_date": None,
            "status": "REQUESTED",
        }
    )
    matrix, fee = domain.provisional_evaluation(row, section)
    row["permit_class"] = matrix["permit_class"]
    row["escort_count_required"] = matrix["escort_count_required"]
    row["pilot_car_required"] = matrix["pilot_car_required"]
    row["provisional_fee_cents"] = fee

    # Supersede any earlier permit for the same (section_id, state_code).
    for other in domain.permits_of_section(section["id"]):
        if other["state_code"] != row["state_code"]:
            continue
        if other["status"] in ("REQUESTED", "FEE_PAID"):
            other["status"] = "SUPERSEDED"
            mark(other)

    db.permits[row["id"]] = row
    mark(section)
    domain.recompute_posture(domain.order_of_section(section))
    return object_response(domain.pub_permit(row), 201)


@bp.get("/installations/permits/<row_id>")
@roles(*ANY_ROLE)
def read_permit(row_id):
    row = lookup("permits", row_id, "ERR_PERMIT_NOT_FOUND")
    return object_response(domain.pub_permit(row))


@bp.get("/installations/permits")
@roles(*ANY_ROLE)
def list_permits():
    active = filters(
        {
            "section_id": None,
            "state_code": None,
            "status": ["REQUESTED", "FEE_PAID", "ISSUED", "REVOKED", "SUPERSEDED"],
        }
    )
    rows = apply_filters(list(db.permits.values()), active)
    return list_response(rows, domain.pub_permit)


@bp.post("/installations/permits/<row_id>/pay-fee")
@roles("TransportManager")
def pay_permit_fee(row_id):
    body = validate([{"name": "amount_cents", "type": "integer", "required": True}])
    permit = lookup("permits", row_id, "ERR_PERMIT_NOT_FOUND")
    if permit["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE")
    permit["paid_amount_cents"] = int(permit["paid_amount_cents"]) + int(
        body["amount_cents"]
    )
    if permit["paid_amount_cents"] >= int(permit["provisional_fee_cents"]):
        permit["status"] = "FEE_PAID"
    mark(permit)
    return object_response(domain.pub_permit(permit))


@bp.post("/installations/permits/<row_id>/issue")
@roles("PermitDesk")
def issue_permit(row_id):
    permit = lookup("permits", row_id, "ERR_PERMIT_NOT_FOUND")
    if permit["status"] != "FEE_PAID":
        fail("ERR_INVALID_STATE")
    section = domain.section_of_permit(permit)
    matrix, fee = domain.final_evaluation(permit, section)
    # PRD 3.4: issuance re-runs both calculations and overwrites these four
    # fields, and only then enforces the two gates in their fixed order.
    permit["permit_class"] = matrix["permit_class"]
    permit["escort_count_required"] = matrix["escort_count_required"]
    permit["pilot_car_required"] = matrix["pilot_car_required"]
    permit["final_fee_cents"] = fee
    mark(permit)

    escorts, pilot_cars = domain.issue_escort_counts(permit["id"])
    if escorts < matrix["escort_count_required"]:
        fail("ERR_PERMIT_ESCORT_SHORTFALL")
    if matrix["pilot_car_required"] and pilot_cars < 1:
        fail("ERR_PERMIT_ESCORT_SHORTFALL")
    if int(permit["paid_amount_cents"]) < fee:
        fail("ERR_PERMIT_FEE_UNPAID")

    permit["status"] = "ISSUED"
    permit["valid_until_date"] = (
        db.clock_date() + timedelta(days=calc.PERMIT_VALID_DAYS)
    ).isoformat()
    if section["transit_status"] in ("PERMIT_PENDING", "PERMIT_REVOKED_HOLD"):
        section["transit_status"] = "DISPATCH_READY"
        mark(section)
    domain.recompute_posture(domain.order_of_section(section))
    return object_response(domain.pub_permit(permit))


@bp.post("/installations/permits/<row_id>/revoke")
@roles("PermitDesk")
def revoke_permit(row_id):
    validate([{"name": "reason_code", "type": "string", "required": True}])
    permit = lookup("permits", row_id, "ERR_PERMIT_NOT_FOUND")
    if permit["status"] != "ISSUED":
        fail("ERR_INVALID_STATE")

    # Cascade link 1
    permit["status"] = "REVOKED"
    mark(permit)

    # Cascade links 2 + 3 + 4
    crews = {}
    for leg in domain.legs_of_permit(permit["id"]):
        if leg["status"] != "SCHEDULED":
            continue
        leg["status"] = "CANCELLED"
        mark(leg)
        for assignment in domain.assignments_of_leg(leg["id"]):
            if assignment["status"] != "RESERVED":
                continue
            assignment["status"] = "RELEASED"
            mark(assignment)
            crew = db.escort_crews.get(assignment["escort_crew_id"])
            if crew is not None:
                crews[crew["id"]] = crew
    for crew in crews.values():
        domain.recompute_crew_minutes(crew)

    # Cascade link 5
    section = domain.section_of_permit(permit)
    if section is not None and not domain.section_has_issued_permit(section["id"]):
        if section["transit_status"] in ("DISPATCH_READY", "IN_TRANSIT"):
            section["transit_status"] = "PERMIT_REVOKED_HOLD"
            mark(section)
    domain.recompute_posture(domain.order_of_section(section))
    return object_response(domain.pub_permit(permit))


# ---------------------------------------------------------------------------
# RouteLeg
# ---------------------------------------------------------------------------
@bp.post("/installations/route-legs")
@roles("TransportManager", "PermitDesk")
def create_route_leg():
    body = validate(
        [
            {"name": "permit_id", "type": "string", "required": True},
            {"name": "hauler_id", "type": "string", "required": True},
            {
                "name": "sequence_no",
                "type": "integer",
                "required": True,
                "min": 1,
                "max": 6,
            },
            {"name": "corridor_id", "type": "string", "required": True},
            {"name": "state_code", "type": "state_code", "required": True},
            {"name": "window_start", "type": "datetime", "required": True},
            {"name": "window_end", "type": "datetime", "required": True},
        ]
    )
    # PRD 3.5 declares window_end strictly after window_start as a field
    # constraint on the leg; ERR_INVALID_WINDOW is scoped to escort
    # reservations and set jobs only, so this is a priority-3 shape failure.
    if parse_instant(body["window_end"]) <= parse_instant(body["window_start"]):
        fail("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")

    permit = lookup_ref("permits", body["permit_id"], "ERR_PERMIT_NOT_FOUND")
    hauler = lookup_ref("haulers", body["hauler_id"], "ERR_HAULER_NOT_FOUND")
    if hauler["status"] == "SUSPENDED":
        fail("ERR_HAULER_SUSPENDED")
    if body["state_code"] != permit["state_code"]:
        fail("ERR_LEG_PERMIT_MISMATCH")
    for other in domain.legs_of_permit(permit["id"]):
        if other["sequence_no"] == body["sequence_no"]:
            fail("ERR_DUPLICATE_LEG_SEQUENCE")

    row = base_row()
    row.update(
        {
            "permit_id": permit["id"],
            "hauler_id": hauler["id"],
            "sequence_no": body["sequence_no"],
            "corridor_id": body["corridor_id"],
            "state_code": body["state_code"],
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "status": "SCHEDULED",
        }
    )
    db.route_legs[row["id"]] = row
    mark(permit)
    return object_response(domain.pub_leg(row), 201)


@bp.get("/installations/route-legs/<row_id>")
@roles(*ANY_ROLE)
def read_route_leg(row_id):
    row = lookup("route_legs", row_id, "ERR_ROUTE_LEG_NOT_FOUND")
    return object_response(domain.pub_leg(row))


@bp.get("/installations/route-legs")
@roles(*ANY_ROLE)
def list_route_legs():
    active = filters(
        {
            "permit_id": None,
            "hauler_id": None,
            "status": [
                "SCHEDULED",
                "IN_TRANSIT",
                "ARRIVED",
                "CANCELLED",
                "HAULER_HOLD",
            ],
        }
    )
    rows = apply_filters(list(db.route_legs.values()), active)
    return list_response(rows, domain.pub_leg)


@bp.post("/installations/route-legs/<row_id>/depart")
@roles("TransportManager")
def depart_route_leg(row_id):
    leg = lookup("route_legs", row_id, "ERR_ROUTE_LEG_NOT_FOUND")
    if actor_id() != leg["hauler_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    permit = db.permits.get(leg["permit_id"])
    if leg["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    if permit is None or permit["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "The leg's transport permit is not ISSUED.")
    for assignment in domain.assignments_of_leg(leg["id"]):
        if assignment["status"] != "RESERVED":
            continue
        crew = db.escort_crews.get(assignment["escort_crew_id"])
        if crew is not None and crew["status"] != "AVAILABLE":
            fail("ERR_ESCORT_CREW_OVERBOOKED")
    hauler = db.haulers.get(leg["hauler_id"])
    if hauler is not None and hauler["status"] != "ACTIVE":
        fail("ERR_HAULER_SUSPENDED")

    leg["status"] = "IN_TRANSIT"
    mark(leg)
    section = domain.section_of_permit(permit)
    if section is not None and section["transit_status"] == "DISPATCH_READY":
        section["transit_status"] = "IN_TRANSIT"
        mark(section)
    domain.recompute_posture(domain.order_of_section(section))
    return object_response(domain.pub_leg(leg))


@bp.post("/installations/route-legs/<row_id>/arrive")
@roles("TransportManager")
def arrive_route_leg(row_id):
    leg = lookup("route_legs", row_id, "ERR_ROUTE_LEG_NOT_FOUND")
    if actor_id() != leg["hauler_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if leg["status"] != "IN_TRANSIT":
        fail("ERR_INVALID_STATE")

    leg["status"] = "ARRIVED"
    mark(leg)
    crews = {}
    for assignment in domain.assignments_of_leg(leg["id"]):
        if assignment["status"] != "RESERVED":
            continue
        assignment["status"] = "COMPLETED"
        mark(assignment)
        crew = db.escort_crews.get(assignment["escort_crew_id"])
        if crew is not None:
            crews[crew["id"]] = crew
    for crew in crews.values():
        domain.recompute_crew_minutes(crew)

    permit = db.permits.get(leg["permit_id"])
    section = domain.section_of_permit(permit)
    highest = None
    for other in domain.legs_of_permit(leg["permit_id"]):
        if other["status"] not in domain.FINAL_LEG_STATES:
            continue
        if highest is None or other["sequence_no"] > highest:
            highest = other["sequence_no"]
    if (
        section is not None
        and highest is not None
        and leg["sequence_no"] == highest
        and section["transit_status"] == "IN_TRANSIT"
    ):
        section["transit_status"] = "DELIVERED"
        mark(section)
    domain.recompute_posture(domain.order_of_section(section))
    return object_response(domain.pub_leg(leg))


# ---------------------------------------------------------------------------
# EscortAssignment
# ---------------------------------------------------------------------------
@bp.post("/installations/escort-assignments")
@roles("TransportManager")
def create_escort_assignment():
    body = validate(
        [
            {"name": "route_leg_id", "type": "string", "required": True},
            {"name": "escort_crew_id", "type": "string", "required": True},
            {
                "name": "role",
                "type": "enum",
                "required": True,
                "values": ["ESCORT", "PILOT_CAR"],
            },
            {"name": "window_start", "type": "datetime", "required": True},
            {"name": "window_end", "type": "datetime", "required": True},
        ]
    )
    leg = lookup_ref("route_legs", body["route_leg_id"], "ERR_ROUTE_LEG_NOT_FOUND")
    crew = lookup_ref(
        "escort_crews", body["escort_crew_id"], "ERR_ESCORT_CREW_NOT_FOUND"
    )

    permit = db.permits.get(leg["permit_id"])
    permit_class = permit["permit_class"] if permit is not None else "STANDARD"
    if not domain.endorsement_covers(crew["endorsement_class"], permit_class):
        fail("ERR_ESCORT_ENDORSEMENT_MISSING")
    if crew["status"] != "AVAILABLE":
        fail("ERR_ESCORT_CREW_OVERBOOKED")

    start = parse_instant(body["window_start"])
    end = parse_instant(body["window_end"])
    leg_start = parse_instant(leg["window_start"])
    leg_end = parse_instant(leg["window_end"])
    if end <= start or start < leg_start or end > leg_end:
        fail("ERR_INVALID_WINDOW")
    if domain.escort_window_conflict(crew, start, end):
        fail("ERR_ESCORT_WINDOW_CONFLICT")

    row = base_row()
    row.update(
        {
            "route_leg_id": leg["id"],
            "escort_crew_id": crew["id"],
            "role": body["role"],
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "reserved_minutes": calc.reservation_minutes(start, end),
            "status": "RESERVED",
        }
    )
    db.escort_assignments[row["id"]] = row
    domain.recompute_crew_minutes(crew)
    return object_response(domain.pub_assignment(row), 201)


@bp.get("/installations/escort-assignments/<row_id>")
@roles(*ANY_ROLE)
def read_escort_assignment(row_id):
    row = lookup("escort_assignments", row_id, "ERR_ESCORT_ASSIGNMENT_NOT_FOUND")
    return object_response(domain.pub_assignment(row))


@bp.get("/installations/escort-assignments")
@roles(*ANY_ROLE)
def list_escort_assignments():
    active = filters(
        {
            "route_leg_id": None,
            "escort_crew_id": None,
            "status": ["RESERVED", "RELEASED", "COMPLETED"],
        }
    )
    rows = apply_filters(list(db.escort_assignments.values()), active)
    return list_response(rows, domain.pub_assignment)


@bp.post("/installations/escort-assignments/<row_id>/release")
@roles("TransportManager")
def release_escort_assignment(row_id):
    assignment = lookup(
        "escort_assignments", row_id, "ERR_ESCORT_ASSIGNMENT_NOT_FOUND"
    )
    leg = db.route_legs.get(assignment["route_leg_id"])
    if leg is None or actor_id() != leg["hauler_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if assignment["status"] != "RESERVED":
        fail("ERR_INVALID_STATE")
    if leg["status"] not in ("SCHEDULED", "CANCELLED", "HAULER_HOLD"):
        fail("ERR_INVALID_STATE")

    assignment["status"] = "RELEASED"
    mark(assignment)
    crew = db.escort_crews.get(assignment["escort_crew_id"])
    domain.recompute_crew_minutes(crew)
    return object_response(domain.pub_assignment(assignment))
