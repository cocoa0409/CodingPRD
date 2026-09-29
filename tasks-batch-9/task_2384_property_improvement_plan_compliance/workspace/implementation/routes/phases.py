"""RenovationPhase scheduling, the closure calendar and key inventory (PRD 3.5)."""

from fractions import Fraction

import calc
import domain
import guards
import repo
import validation as v
from errors import ApiError
from middleware import ANY_ROLE, FRANCHISEE_OWNER
from routing import route

LIVE_PHASE_STATUSES = ("PLANNED", "ACTIVE")


def _ooo_ratio(prop, extra_rooms):
    if not prop["room_count"]:
        return Fraction(0)
    return Fraction(prop["rooms_out_of_service_current"] + extra_rooms, prop["room_count"])


def _check_ooo_cap(prop, extra_rooms):
    if _ooo_ratio(prop, extra_rooms) > calc.MAX_OOO_PCT:
        raise ApiError(
            "ERR_OOO_CAP_EXCEEDED",
            "no more than a quarter of the property's keys may be out of service",
        )


def _displacement(phase, prop):
    return calc.displacement_impact(
        phase["rooms_out_of_service"],
        calc.parse_date(phase["start_date"]),
        calc.parse_date(phase["end_date"]),
        prop["room_count"],
        prop["adr_baseline_cents"],
        prop["occupancy_baseline_pct"],
    )


@route("/pip/renovation-phases", ["POST"], (FRANCHISEE_OWNER,))
def create_phase():
    body = v.body_json()
    plan = guards.resolve_body_fk(body, "plan_id", "plans")

    v.require(
        body,
        "plan_id",
        "phase_number",
        "start_date",
        "end_date",
        "rooms_out_of_service",
    )
    phase_number = v.get_int(body, "phase_number", minimum=1)
    start_raw = v.get_str(body, "start_date", min_len=1)
    end_raw = v.get_str(body, "end_date", min_len=1)
    rooms = v.get_int(body, "rooms_out_of_service", minimum=1)

    start = calc.parse_date(start_raw)
    end = calc.parse_date(end_raw)
    if start is None or end is None or end < start:
        raise ApiError(
            "ERR_INVALID_DATE_RANGE",
            "end_date must be a valid ISO date no earlier than start_date",
        )

    siblings = domain.phases_of_plan(plan["id"])
    for other in siblings:
        if other["status"] != "CANCELLED" and other["phase_number"] == phase_number:
            raise ApiError(
                "ERR_PHASE_NUMBER_DUPLICATE",
                "phase_number %d is already used by a live phase of this plan"
                % phase_number,
            )

    prop = domain.property_of_plan(plan)
    guards.require_franchise_not_terminated(prop)

    # band 6
    _check_ooo_cap(prop, rooms)

    # band 7 — the closure calendar carries a two-day end-side changeover buffer.
    for other in siblings:
        if other["status"] not in LIVE_PHASE_STATUSES:
            continue
        other_start = calc.parse_date(other["start_date"])
        other_end = calc.parse_date(other["end_date"])
        if other_start is None or other_end is None:
            continue
        if start <= calc.add_days(
            other_end, calc.CHANGEOVER_BUFFER_DAYS
        ) and other_start <= calc.add_days(end, calc.CHANGEOVER_BUFFER_DAYS):
            raise ApiError(
                "ERR_PHASE_WINDOW_CONFLICT",
                "the closure window collides with phase %d of the same plan"
                % other["phase_number"],
            )

    horizon = plan["back_of_house_deadline_date"]
    if horizon and end > calc.parse_date(horizon):
        raise ApiError(
            "ERR_PHASE_OUTSIDE_PLAN_HORIZON",
            "end_date may not fall after the plan's back-of-house deadline",
        )

    # band 8
    guards.require_owner(prop)

    row = repo.new_row(
        {
            "plan_id": plan["id"],
            "phase_number": phase_number,
            "start_date": start_raw,
            "end_date": end_raw,
            "rooms_out_of_service": rooms,
            "status": "PLANNED",
            "displacement_revenue_impact_cents": 0,
            "ooo_pct_at_activation": None,
        }
    )
    row["displacement_revenue_impact_cents"] = _displacement(row, prop)[
        "displacement_impact_cents"
    ]
    repo.insert("phases", row)
    return repo.single(row, 201)


@route("/pip/renovation-phases/<row_id>", ["GET"], ANY_ROLE)
def get_phase(row_id):
    return repo.single(repo.must_find("phases", row_id))


@route("/pip/renovation-phases", ["GET"], ANY_ROLE)
def list_phases():
    limit, offset = v.pagination()
    rows = repo.rows("phases")
    for field in ("plan_id", "status"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)


@route("/pip/renovation-phases/<row_id>/activate", ["POST"], (FRANCHISEE_OWNER,))
def activate_phase(row_id):
    phase = repo.must_find("phases", row_id)
    plan = repo.find("plans", phase["plan_id"])
    prop = domain.property_of_plan(plan)

    if phase["status"] != "PLANNED":
        raise ApiError(
            "ERR_PHASE_NOT_ACTIVATABLE", "only a PLANNED phase may be activated"
        )
    guards.require_execution_window(plan)

    # band 6 — re-evaluated against the property's then-current position.
    _check_ooo_cap(prop, phase["rooms_out_of_service"])

    # band 8
    guards.require_owner(prop)

    phase["status"] = "ACTIVE"
    phase["displacement_revenue_impact_cents"] = _displacement(phase, prop)[
        "displacement_impact_cents"
    ]
    own_ratio = (
        Fraction(0)
        if not prop["room_count"]
        else Fraction(phase["rooms_out_of_service"], prop["room_count"])
    )
    phase["ooo_pct_at_activation"] = calc.as_number(own_ratio, 4)
    repo.touch(phase)

    repo.touch(prop)
    domain.recompute_property(prop)
    return repo.single(phase)


@route("/pip/renovation-phases/<row_id>/close-out", ["POST"], (FRANCHISEE_OWNER,))
def close_out_phase(row_id):
    phase = repo.must_find("phases", row_id)
    plan = repo.find("plans", phase["plan_id"])
    prop = domain.property_of_plan(plan)

    if phase["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PHASE_NOT_CLOSEABLE", "only an ACTIVE phase may be closed out"
        )

    # band 6
    for item in domain.plan_items(plan["id"]):
        if item["room_impacting"] and item["status"] == "IN_PROGRESS":
            raise ApiError(
                "ERR_ROOM_WORK_STILL_IN_PROGRESS",
                "room-impacting work of this plan is still in progress",
            )

    # band 8
    guards.require_owner(prop)

    phase["status"] = "CLOSED_OUT"
    repo.touch(phase)

    for booking in domain.bookings_of_phase(phase["id"]):
        if booking["status"] == "BOOKED":
            booking["status"] = "COMPLETED"
            repo.touch(booking)

    repo.touch(prop)
    domain.recompute_property(prop)
    return repo.single(phase)
