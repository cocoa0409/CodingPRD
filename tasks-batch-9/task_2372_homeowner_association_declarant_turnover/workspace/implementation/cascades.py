"""Shared side-effect / cascade machinery (PRD §2.8, §2.9).

Sibling rows are always processed in created_at ascending order and every row a
hop touches is a mutation of its own record.
"""
from decimal import Decimal

import calc
import clock
import util
from db import db, touch
from errors import ApiError


# ------------------------------------------------------- settlement lock (§2.8) ---
def require_not_settled_locked(association_id):
    case = calc.case_for_association(association_id)
    if case is not None and case["turnover_posture"] == "SETTLED_LOCKED":
        raise ApiError("ERR_TURNOVER_SETTLED_LOCKED")


# ------------------------------------------------- forecast staleness (§2.9) ---
def supersede_draft_schedules(association_id):
    for schedule in calc.schedules_of(association_id):
        if schedule["status"] == "DRAFT":
            schedule["status"] = "SUPERSEDED"
            touch(schedule)


def mark_forecast_stale(association):
    """Sets STALE, advances the association version, and supersedes DRAFT
    schedules as the caused hop."""
    association["budget_forecast_status"] = "STALE"
    touch(association)
    supersede_draft_schedules(association["id"])


# -------------------------------------- records transfer completeness (§3.5) ---
def recompute_records_completeness(case):
    if case is None:
        return
    new_pct = float(calc.records_completeness_pct(case["id"]))
    if case["records_transfer_completeness_pct"] != new_pct:
        case["records_transfer_completeness_pct"] = new_pct
        touch(case)


# ------------------------------------------- audit drift / settlement block ---
def refresh_issued_engagements(association):
    """Recompute the delta and finding_status of every ISSUED engagement, then
    latch settlement_blocked when any of them stands at EXCEPTION_NOTED."""
    exception_seen = False
    for engagement in calc.engagements_of(association["id"]):
        if engagement["status"] != "ISSUED":
            continue
        delta = calc.audit_delta(engagement, association)
        finding = "CLEAN" if delta == 0 else "EXCEPTION_NOTED"
        if (
            engagement["unreconciled_delta_cents"] != delta
            or engagement["finding_status"] != finding
        ):
            engagement["unreconciled_delta_cents"] = delta
            engagement["finding_status"] = finding
            touch(engagement)
        if finding == "EXCEPTION_NOTED":
            exception_seen = True
    if exception_seen:
        case = calc.case_for_association(association["id"])
        if case is not None and not case["settlement_blocked"]:
            case["settlement_blocked"] = True
            touch(case)


# --------------------------------------------------- seat ledger bubble-up ---
def apply_seat_ledger_and_bubble(case):
    calc.apply_seat_ledger(case)
    if (
        case["governance_status"] == "ELECTION_CALLED"
        and case["owner_elected_seats"] == case["owner_elected_seats_required"]
    ):
        case["governance_status"] = "ELECTION_HELD"
    elif (
        case["governance_status"] == "ELECTION_HELD"
        and case["owner_elected_seats"] < case["owner_elected_seats_required"]
    ):
        case["governance_status"] = "ELECTION_CALLED"
    calc.derive_posture(case)
    touch(case)


# ------------------------------------------------ declarant obligations (§3.2) ---
def has_overdue_unbuilt_amenity(association_id):
    now = clock.now()
    for component in calc.components_of(association_id):
        if component["category"] != "AMENITY":
            continue
        if component["build_status"] not in ("UNBUILT", "IN_PROGRESS"):
            continue
        promised = util.parse_dt(component["promised_completion_date"])
        if promised is not None and promised < now:
            return True
    return False


def has_cancellable_affiliated_contract(association_id):
    for contract in calc.contracts_of(association_id):
        if contract["developer_affiliated"] and contract["status"] == "CANCELLABLE":
            return True
    return False


def records_pct(case):
    return Decimal(str(case["records_transfer_completeness_pct"]))
