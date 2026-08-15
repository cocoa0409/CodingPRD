"""Shared domain machinery: transition parsing, cascades, common gates."""

from __future__ import annotations

from datetime import timedelta

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_FORBIDDEN,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
)
from services import calculations as calc


# ---------------------------------------------------------------------------
# Transition envelope helpers
# ---------------------------------------------------------------------------

def parse_to(body: dict, valid_states: set[str]) -> str:
    """`to` must be present, a string, and a member of the entity's status
    enum (schema category: invalid enum member -> 400)."""
    to = body.get("to")
    if to is None or not isinstance(to, str) or to == "":
        raise_err(ERR_INVALID_REQUEST, "Missing required field: to")
    if to not in valid_states:
        raise_err(ERR_INVALID_REQUEST, f"Field to must be one of {sorted(valid_states)}")
    return to


def check_transition_owner(to: str, owners: dict[str, set[str]], role: str) -> None:
    """The caller's role must own the requested `to` transition per the state
    machine's actor (priority 2). System-only targets have no owning role."""
    allowed = owners.get(to, set())
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, f"Role {role} does not own transition to={to}")


def check_terminal(entity: dict, terminal_states: set[str], to: str,
                   declared: dict[str, set[str]]) -> None:
    """Terminal guard. A terminal state rejects every further transition with
    ERR_ALREADY_TERMINAL — except a transition the state machine still declares
    from it (DamageReport CHARGED -> WAIVED compensation is declared despite
    CHARGED being listed terminal; the PRD's compensation flow wins)."""
    if entity["status"] in terminal_states and to not in declared.get(entity["status"], set()):
        raise_err(ERR_ALREADY_TERMINAL, f"Resource is in terminal state {entity['status']}")


def check_declared(entity: dict, to: str, declared: dict[str, set[str]]) -> None:
    allowed = declared.get(entity["status"], set())
    if to not in allowed:
        raise_err(
            ERR_INVALID_STATE,
            f"Transition to={to} is not declared from state {entity['status']}",
        )


# ---------------------------------------------------------------------------
# Production cancel cascade (PRD 3.2)
# ---------------------------------------------------------------------------

def cancel_cascade(production: dict) -> None:
    pid = production["id"]

    # (1) crew calls DRAFT/PUBLISHED/CONFIRMED -> CANCELLED; their assignments
    # in ASSIGNED/CONFIRMED/WORKED -> CANCELLED
    for call in db.crew_calls.values():
        if call["production_id"] != pid:
            continue
        if call["status"] in ("DRAFT", "PUBLISHED", "CONFIRMED"):
            call["status"] = "CANCELLED"
            db.touch(call)
            for asg in db.crew_assignments.values():
                if asg["crew_call_id"] == call["id"] and asg["status"] in (
                    "ASSIGNED",
                    "CONFIRMED",
                    "WORKED",
                ):
                    asg["status"] = "CANCELLED"
                    db.touch(asg)

    # (3) rigging points in RESERVED/UNDER_REVIEW/REJECTED/APPROVED -> RELEASED,
    # recomputing each affected plot's total_factored_load_kg
    affected_plots: set[str] = set()
    for plot in db.plots.values():
        if plot["production_id"] != pid:
            continue
        for point in db.rigging_points.values():
            if point["plot_id"] == plot["id"] and point["status"] in (
                "RESERVED",
                "UNDER_REVIEW",
                "REJECTED",
                "APPROVED",
            ):
                point["status"] = "RELEASED"
                db.touch(point)
                affected_plots.add(plot["id"])
    for plot_id in affected_plots:
        calc.recompute_plot_total(db.plots[plot_id])

    # (4) pull list entries in REQUESTED/RESERVED/PREPPED -> CANCELLED; freed
    # assets (RESERVED/PREPPED) -> AVAILABLE, then waitlist promotion scan
    freed_assets: list[dict] = []
    for entry in db.pull_list_entries.values():
        if entry["production_id"] != pid:
            continue
        if entry["status"] in ("REQUESTED", "RESERVED", "PREPPED"):
            was_holding = entry["status"] in ("RESERVED", "PREPPED")
            entry["status"] = "CANCELLED"
            db.touch(entry)
            if was_holding:
                asset = db.assets.get(entry["asset_id"])
                if asset is not None and asset["status"] in ("RESERVED", "PREPPED"):
                    asset["status"] = "AVAILABLE"
                    db.touch(asset)
                    freed_assets.append(asset)
    for asset in freed_assets:
        if asset["status"] == "AVAILABLE":
            calc.run_waitlist_promotion(asset)

    # (5) load schedules PLANNED/CONFIRMED/AUTHORIZED -> CANCELLED
    for schedule in db.load_schedules.values():
        if schedule["production_id"] == pid and schedule["status"] in (
            "PLANNED",
            "CONFIRMED",
            "AUTHORIZED",
        ):
            schedule["status"] = "CANCELLED"
            db.touch(schedule)

    # (6) inspections SCHEDULED/IN_PROGRESS/FAILED -> CANCELLED
    for insp in db.inspections.values():
        if insp["production_id"] == pid and insp["status"] in (
            "SCHEDULED",
            "IN_PROGRESS",
            "FAILED",
        ):
            insp["status"] = "CANCELLED"
            db.touch(insp)


# ---------------------------------------------------------------------------
# Interval helpers
# ---------------------------------------------------------------------------

def closed_windows_intersect(a_start, a_end, b_start, b_end) -> bool:
    """Closed-interval intersection: touching endpoints count."""
    return a_start <= b_end and b_start <= a_end


def half_open_windows_intersect(a_start, a_end, b_start, b_end) -> bool:
    """Half-open [start, end) intersection: touching endpoints allowed."""
    return a_start < b_end and b_start < a_end


def hours_between(later, earlier) -> float:
    return (later - earlier).total_seconds() / 3600.0


def minus_hours(dt, hours) -> "object":
    return dt - timedelta(hours=float(hours))
