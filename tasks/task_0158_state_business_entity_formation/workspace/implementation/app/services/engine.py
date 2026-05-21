"""Engine: state transitions, derived compliance status, cascading sweeps."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from ..store import store
from ..timeutil import anniversary_one_year_after, march_first_of, now as clock_now
from ..util import new_uuid
from .calculations import (
    authorized_shares_base_tax,
    assumed_par_value_base_tax,
    compute_boi_penalty,
    compute_late_fee_cents,
    compute_total_due,
)


# ---- Helpers ---------------------------------------------------------------------

def touch(row: dict[str, Any], *, ts: datetime | None = None) -> None:
    """Bump updated_at and version (if present)."""
    if ts is None:
        ts = clock_now()
    row["updated_at"] = ts
    if "version" in row:
        row["version"] = int(row.get("version", 0)) + 1


def emit_event(business_entity_id: str, event_type: str, payload: dict[str, Any] | None = None, *,
               occurred_at: datetime | None = None) -> dict[str, Any]:
    occurred_at = occurred_at or clock_now()
    row = {
        "id": new_uuid(),
        "created_at": occurred_at,
        "business_entity_id": business_entity_id,
        "event_type": event_type,
        "payload": payload or {},
        "occurred_at": occurred_at,
    }
    store.compliance_events[row["id"]] = row
    return row


# ---- Active / latest BOI helpers -------------------------------------------------

def active_ownerships_for(entity_id: str, *, at: datetime | None = None) -> list[dict[str, Any]]:
    at = at or clock_now()
    out = []
    for row in store.boi_ownerships.values():
        if row.get("business_entity_id") != entity_id:
            continue
        terminated_at = row.get("terminated_at")
        if terminated_at is None or terminated_at > at:
            out.append(row)
    return out


def ownerships_active_at(entity_id: str, instant: datetime) -> list[dict[str, Any]]:
    """Snapshot semantics: row was active at the given instant."""
    out = []
    for row in store.boi_ownerships.values():
        if row.get("business_entity_id") != entity_id:
            continue
        effective_at = row.get("effective_at")
        if effective_at is None or effective_at > instant:
            continue
        terminated_at = row.get("terminated_at")
        if terminated_at is not None and terminated_at <= instant:
            continue
        out.append(row)
    return out


def latest_boi_report_for(entity_id: str) -> dict[str, Any] | None:
    candidates = [r for r in store.boi_reports.values() if r.get("business_entity_id") == entity_id]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.get("created_at"))


def latest_current_or_corrected_report(entity_id: str) -> dict[str, Any] | None:
    candidates = [
        r for r in store.boi_reports.values()
        if r.get("business_entity_id") == entity_id and r.get("status") in ("CURRENT", "CORRECTED")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.get("filed_at") or r.get("created_at"))


def has_existing_initial_or_active_report(entity_id: str) -> bool:
    """True iff some BOIReport for the entity is in status in {FILED, CURRENT, STALE, CORRECTED}."""
    for r in store.boi_reports.values():
        if r.get("business_entity_id") != entity_id:
            continue
        if r.get("status") in ("FILED", "CURRENT", "STALE", "CORRECTED"):
            return True
    return False


# ---- Business tax base computation -----------------------------------------------

def compute_base_tax(entity: dict[str, Any], method: str) -> int:
    et = entity.get("entity_type")
    if method == "FLAT":
        return 30000
    if method == "AUTHORIZED_SHARES":
        return authorized_shares_base_tax(int(entity.get("authorized_shares") or 0))
    if method == "ASSUMED_PAR_VALUE":
        return assumed_par_value_base_tax(
            int(entity.get("total_gross_assets_cents") or 0),
            int(entity.get("total_issued_shares") or 0),
            int(entity.get("authorized_shares") or 0),
        )
    raise ValueError(f"Unknown calculation method: {method}")


# ---- Operating agreement hash ----------------------------------------------------

def make_template_hash(template_code: str, template_version: str) -> str:
    payload = f"{template_code}:{template_version}".encode()
    return hashlib.sha256(payload).hexdigest()


# ---- Derived compliance status ---------------------------------------------------

def _derive_compliance_status(entity_id: str, *, at: datetime | None = None) -> str:
    """Recompute the derived compliance_status for an ACTIVE entity."""
    at = at or clock_now()
    entity = store.business_entities.get(entity_id)
    if not entity:
        return None  # type: ignore[return-value]

    open_tax_overdue = False
    open_tax_delinquent = False
    for assessment in store.tax_assessments.values():
        if assessment.get("business_entity_id") != entity_id:
            continue
        status = assessment.get("status")
        if status == "DELINQUENT":
            open_tax_delinquent = True
        elif status == "OVERDUE":
            open_tax_overdue = True

    next_due = entity.get("next_annual_report_due_date")
    missing_report = False
    if next_due is not None and at > next_due:
        due_year = next_due.year
        accepted_for_due_year = any(
            r.get("business_entity_id") == entity_id
            and r.get("status") == "ACCEPTED"
            and r.get("report_year", 0) >= due_year
            for r in store.annual_reports.values()
        )
        missing_report = not accepted_for_due_year

    boi_stale = any(
        r.get("business_entity_id") == entity_id and r.get("status") == "STALE"
        for r in store.boi_reports.values()
    )

    if open_tax_delinquent:
        return "DELINQUENT"
    if open_tax_overdue or missing_report or boi_stale:
        return "NOT_IN_GOOD_STANDING"
    return "GOOD_STANDING"


def recompute_compliance_status(entity_id: str, *, at: datetime | None = None) -> None:
    at = at or clock_now()
    entity = store.business_entities.get(entity_id)
    if not entity:
        return
    if entity.get("formation_status") != "ACTIVE":
        # While not ACTIVE the compliance_status is null and not derived.
        return
    new_status = _derive_compliance_status(entity_id, at=at)
    old_status = entity.get("compliance_status")
    if new_status != old_status:
        entity["compliance_status"] = new_status
        touch(entity, ts=at)
        emit_event(entity_id, "COMPLIANCE_STATUS_CHANGED", {"from": old_status, "to": new_status}, occurred_at=at)
        if new_status == "DELINQUENT":
            # Stamp the time-of-flip so administrative dissolution can measure 60 days.
            store.delinquent_since[entity_id] = at
        elif old_status == "DELINQUENT":
            # Cleared delinquency — forget the prior anchor.
            store.delinquent_since.pop(entity_id, None)


# ---- Cascades --------------------------------------------------------------------

def cascade_foreign_qualifications_on_dissolution(entity_id: str, *, admin: bool, at: datetime) -> None:
    target_status = "REVOKED" if admin else "WITHDRAWN"
    cause = "ADMIN_DISSOLVED" if admin else "WITHDRAWN"
    for fq in list(store.foreign_qualifications.values()):
        if fq.get("business_entity_id") != entity_id:
            continue
        if fq.get("status") != "QUALIFIED":
            continue
        fq["status"] = target_status
        if admin:
            fq["revoked_at"] = at
        touch(fq, ts=at)
        emit_event(entity_id, "FOREIGN_REVOKED", {"cause": cause, "foreign_qualification_id": fq["id"]}, occurred_at=at)


# ---- Sweep -----------------------------------------------------------------------

def run_sweep(*, at: datetime | None = None) -> dict[str, Any]:
    """Apply every overdue-tax, BOI-stale, and dissolution-eligible transition.

    Returns a dict of transition counts for observability.
    """
    at = at or clock_now()
    transitions = {
        "tax_overdue": 0,
        "tax_delinquent": 0,
        "boi_stale": 0,
    }

    # 1) Tax assessments: ASSESSED -> OVERDUE -> DELINQUENT
    for assessment in list(store.tax_assessments.values()):
        status = assessment.get("status")
        if status in ("PAID",):
            continue
        due_date = assessment["due_date"]
        if status == "ASSESSED" and at > due_date:
            assessment["status"] = "OVERDUE"
            assessment["late_fee_cents"] = compute_late_fee_cents("OVERDUE", at, due_date, int(assessment["base_tax_cents"]))
            entity = store.business_entities.get(assessment["business_entity_id"])
            credit = int(entity.get("credit_balance_cents", 0)) if entity else 0
            pre_credit = int(assessment["base_tax_cents"]) + int(assessment["late_fee_cents"])
            applied = min(credit, pre_credit)
            assessment["total_due_cents"] = pre_credit - applied
            touch(assessment, ts=at)
            emit_event(assessment["business_entity_id"], "TAX_OVERDUE", {"assessment_id": assessment["id"]}, occurred_at=at)
            transitions["tax_overdue"] += 1
            status = "OVERDUE"
        if status == "OVERDUE" and at > (due_date + timedelta(days=90)):
            assessment["status"] = "DELINQUENT"
            assessment["late_fee_cents"] = compute_late_fee_cents("DELINQUENT", at, due_date, int(assessment["base_tax_cents"]))
            entity = store.business_entities.get(assessment["business_entity_id"])
            credit = int(entity.get("credit_balance_cents", 0)) if entity else 0
            pre_credit = int(assessment["base_tax_cents"]) + int(assessment["late_fee_cents"])
            applied = min(credit, pre_credit)
            assessment["total_due_cents"] = pre_credit - applied
            touch(assessment, ts=at)
            emit_event(assessment["business_entity_id"], "TAX_DELINQUENT", {"assessment_id": assessment["id"]}, occurred_at=at)
            transitions["tax_delinquent"] += 1

    # 1b) Refresh late_fee_cents on every OVERDUE/DELINQUENT row (no status flip) so that
    # subsequent GETs see the current monthly accrual at the swept clock instant.
    for assessment in store.tax_assessments.values():
        status = assessment.get("status")
        if status not in ("OVERDUE", "DELINQUENT"):
            continue
        assessment["late_fee_cents"] = compute_late_fee_cents(status, at, assessment["due_date"], int(assessment["base_tax_cents"]))
        entity = store.business_entities.get(assessment["business_entity_id"])
        credit = int(entity.get("credit_balance_cents", 0)) if entity else 0
        pre_credit = int(assessment["base_tax_cents"]) + int(assessment["late_fee_cents"])
        applied = min(credit, pre_credit)
        assessment["total_due_cents"] = pre_credit - applied

    # 2) BOI reports: CURRENT -> STALE when ownership change exceeded 30 days
    for entity_id, change_at in list(store.ownership_change_at.items()):
        if at < change_at + timedelta(days=30):
            continue
        report = latest_boi_report_for(entity_id)
        if report is None:
            store.ownership_change_at.pop(entity_id, None)
            continue
        if report.get("status") != "CURRENT":
            # Already STALE, CORRECTED, etc. Clear the timer.
            store.ownership_change_at.pop(entity_id, None)
            continue
        report["status"] = "STALE"
        report["stale_at"] = change_at + timedelta(days=30)
        eff_days, penalty = compute_boi_penalty(report["stale_at"], at)
        report["penalty_cents"] = penalty
        touch(report, ts=at)
        emit_event(entity_id, "BOI_STALE", {"report_id": report["id"]}, occurred_at=at)
        transitions["boi_stale"] += 1
        store.ownership_change_at.pop(entity_id, None)

    # 2b) Refresh penalty for any STALE reports (cap-first)
    for report in store.boi_reports.values():
        if report.get("status") != "STALE":
            continue
        eff_days, penalty = compute_boi_penalty(report["stale_at"], at)
        report["penalty_cents"] = penalty

    # 3) Recompute compliance_status for every ACTIVE entity.
    for entity in store.business_entities.values():
        if entity.get("formation_status") == "ACTIVE":
            recompute_compliance_status(entity["id"], at=at)

    return {
        "now": at,
        "transitions_applied": transitions,
    }
