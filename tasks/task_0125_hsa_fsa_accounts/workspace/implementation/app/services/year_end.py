"""Year-end / grace-period sweep logic (SCAFFOLD §3.6 + 3.7)."""
from __future__ import annotations

import datetime as _dt

from ..clock import to_date
from ..store import store
from .audit import emit_audit_event
from .caps import CARRYOVER_CAP_CENTS


def _bump_plan_year(py: dict) -> None:
    py["version"] += 1
    py["updated_at"] = store.clock.now()


def _recompute_provisional(py: dict) -> None:
    py["provisional_balance_cents"] = (
        py["contributions_ytd_cents"] + py["carryover_in_cents"]
        - py["claims_paid_ytd_cents"]
    )


def _compute_forfeiture_for_close(py: dict, account: dict) -> int:
    """Compute final forfeiture amount at close time per SCAFFOLD calc forfeiture_final."""
    if account["account_type"] == "HSA":
        return 0
    leftover = (py["contributions_ytd_cents"] + py["carryover_in_cents"]) - py["claims_paid_ytd_cents"]
    if leftover < 0:
        leftover = 0
    if account["account_type"] == "DEPENDENT_CARE_FSA":
        return leftover
    # HEALTH_FSA
    policy = account["year_end_policy"]
    if policy in ("NONE", "GRACE_PERIOD"):
        return leftover
    # CARRYOVER — handled separately (the actual carry-forward happens in apply-carryover);
    # at final close the residue beyond CARRYOVER_CAP is forfeited.
    carried = min(leftover, CARRYOVER_CAP_CENTS)
    return leftover - carried


def _carryover_eligible(py: dict) -> int:
    """Amount eligible to carry forward (capped at CARRYOVER_CAP_CENTS, floor 0)."""
    leftover = (py["contributions_ytd_cents"] + py["carryover_in_cents"]) - py["claims_paid_ytd_cents"]
    if leftover < 0:
        leftover = 0
    return min(leftover, CARRYOVER_CAP_CENTS)


def execute_year_end_close(*, as_of_date: _dt.datetime, ops_run_index: int) -> tuple[list[str], int]:
    """Run a YEAR_END_CLOSE sweep. Returns (affected_plan_year_ids, total_forfeited_cents)."""
    as_of_year = to_date(as_of_date).year
    affected_ids: list[str] = []
    total_forfeited = 0

    # Snapshot — iterate ACTIVE plan years with calendar_year < as_of_year, in ascending id.
    candidates = [
        py for py in store.plan_years.values()
        if py["status"] == "ACTIVE" and py["calendar_year"] < as_of_year
    ]
    candidates.sort(key=lambda r: r["id"])

    for py in candidates:
        account = store.accounts.get(py["account_id"])
        if account is None:
            continue
        atype = account["account_type"]
        policy = account["year_end_policy"]

        if atype == "HSA":
            # HSA -> CLOSED, forfeited = 0
            py["status"] = "CLOSED"
            py["forfeited_cents"] = 0
            _bump_plan_year(py)
            emit_audit_event(
                event_type="YEAR_END_FORFEITURE",
                subject_entity="PLAN_YEAR", subject_id=py["id"],
                account_id=account["id"], plan_year_id=py["id"],
                cents_delta=0, ops_run_index=ops_run_index,
            )
            affected_ids.append(py["id"])
            continue

        if atype == "HEALTH_FSA" and policy == "CARRYOVER":
            # -> CARRYOVER_PENDING. Apply carryover to successor if exists.
            carryover_amt = _carryover_eligible(py)
            py["status"] = "CARRYOVER_PENDING"
            _bump_plan_year(py)
            emit_audit_event(
                event_type="CARRYOVER_APPLIED",
                subject_entity="PLAN_YEAR", subject_id=py["id"],
                account_id=account["id"], plan_year_id=py["id"],
                cents_delta=carryover_amt, ops_run_index=ops_run_index,
            )
            successor = _find_plan_year(account["id"], py["calendar_year"] + 1)
            if successor is not None:
                successor["carryover_in_cents"] += carryover_amt
                _recompute_provisional(successor)
                _bump_plan_year(successor)
            affected_ids.append(py["id"])
            continue

        if policy == "GRACE_PERIOD" and atype in ("HEALTH_FSA", "DEPENDENT_CARE_FSA"):
            # Must be on/after Jan 1 of CY+1 (always true given as_of_year > calendar_year).
            py["status"] = "GRACE_PERIOD"
            py["grace_period_end_date"] = _dt.datetime(py["calendar_year"] + 1, 3, 15, 0, 0, 0, tzinfo=_dt.timezone.utc)
            _bump_plan_year(py)
            emit_audit_event(
                event_type="GRACE_PERIOD_STARTED",
                subject_entity="PLAN_YEAR", subject_id=py["id"],
                account_id=account["id"], plan_year_id=py["id"],
                cents_delta=0, ops_run_index=ops_run_index,
            )
            affected_ids.append(py["id"])
            continue

        # NONE policy (HEALTH_FSA or DEPENDENT_CARE_FSA) -> direct CLOSED with forfeiture
        forfeit = _compute_forfeiture_for_close(py, account)
        py["status"] = "CLOSED"
        py["forfeited_cents"] = forfeit
        _bump_plan_year(py)
        emit_audit_event(
            event_type="YEAR_END_FORFEITURE",
            subject_entity="PLAN_YEAR", subject_id=py["id"],
            account_id=account["id"], plan_year_id=py["id"],
            cents_delta=-forfeit, ops_run_index=ops_run_index,
        )
        total_forfeited += forfeit
        affected_ids.append(py["id"])

    return affected_ids, total_forfeited


def execute_grace_period_expiry(*, as_of_date: _dt.datetime, ops_run_index: int) -> tuple[list[str], int]:
    """Run a GRACE_PERIOD_EXPIRY sweep.

    Closes:
      - GRACE_PERIOD plan years whose grace_period_end_date < as_of_date.
      - CARRYOVER_PENDING plan years whose deadline (Dec 31 of CY+1) has passed.
    """
    affected_ids: list[str] = []
    total_forfeited = 0

    candidates_grace = [
        py for py in store.plan_years.values()
        if py["status"] == "GRACE_PERIOD"
        and py.get("grace_period_end_date") is not None
        and py["grace_period_end_date"] < as_of_date
    ]
    candidates_carry = [
        py for py in store.plan_years.values()
        if py["status"] == "CARRYOVER_PENDING"
        and to_date(as_of_date) >= _dt.date(py["calendar_year"] + 1, 12, 31)
    ]
    candidates = candidates_grace + candidates_carry
    candidates.sort(key=lambda r: r["id"])

    for py in candidates:
        account = store.accounts.get(py["account_id"])
        if account is None:
            continue
        forfeit = _compute_forfeiture_for_close(py, account)
        py["status"] = "CLOSED"
        py["forfeited_cents"] = forfeit
        _bump_plan_year(py)
        emit_audit_event(
            event_type="YEAR_END_FORFEITURE",
            subject_entity="PLAN_YEAR", subject_id=py["id"],
            account_id=account["id"], plan_year_id=py["id"],
            cents_delta=-forfeit, ops_run_index=ops_run_index,
        )
        total_forfeited += forfeit
        affected_ids.append(py["id"])

    return affected_ids, total_forfeited


def apply_pending_carryover_to_successor(*, predecessor: dict, successor: dict) -> None:
    """When a successor PlanYear is opened, if predecessor is CARRYOVER_PENDING, move the
    eligible carryover and close the predecessor (per PRD §3.6 and §3.2)."""
    eligible = _carryover_eligible(predecessor)
    successor["carryover_in_cents"] += eligible
    _recompute_provisional(successor)
    # Predecessor closes with forfeited = max(0, leftover - applied_carryover)
    leftover = (predecessor["contributions_ytd_cents"] + predecessor["carryover_in_cents"]) - predecessor["claims_paid_ytd_cents"]
    if leftover < 0:
        leftover = 0
    forfeit = max(0, leftover - eligible)
    predecessor["status"] = "CLOSED"
    predecessor["forfeited_cents"] = forfeit
    _bump_plan_year(predecessor)
    emit_audit_event(
        event_type="YEAR_END_FORFEITURE",
        subject_entity="PLAN_YEAR", subject_id=predecessor["id"],
        account_id=predecessor["account_id"], plan_year_id=predecessor["id"],
        cents_delta=-forfeit, ops_run_index=None,
    )


# ----- helpers ----- #

def _find_plan_year(account_id: str, calendar_year: int) -> dict | None:
    for py in store.plan_years.values():
        if py["account_id"] == account_id and py["calendar_year"] == calendar_year:
            return py
    return None
