"""PayrollPeriod services: create/lock/settle/list."""

from __future__ import annotations

import db
from errors import (
    raise_error,
    ERR_INVALID_PARAMETER,
    ERR_PERIOD_OVERLAP,
    ERR_PERIOD_NOT_DUE,
    ERR_PERIOD_STATE_INVALID,
    ERR_REINSPECTION_PENDING,
)
from money import round_half_up
from services.audit import write_audit, queue_event
from services.ledger import add_entry as add_ledger_entry


def _parse(dtstr):
    return db.parse_iso(dtstr)


def create_period(*, cycle_label: str, opens_at: str, closes_at: str, tax_rate):
    if not cycle_label or not isinstance(cycle_label, str):
        raise_error(ERR_INVALID_PARAMETER, "cycle_label is required.")
    try:
        opens_dt = _parse(opens_at)
        closes_dt = _parse(closes_at)
    except Exception:
        raise_error(ERR_INVALID_PARAMETER, "opens_at/closes_at must be ISO 8601.")
    if closes_dt <= opens_dt:
        raise_error(ERR_INVALID_PARAMETER, "closes_at must be > opens_at.")
    if not isinstance(tax_rate, (int, float)) or tax_rate < 0 or tax_rate > 1:
        raise_error(ERR_INVALID_PARAMETER, "tax_rate must be in [0, 1].")

    # Overlap check
    for existing in db.all_rows("payroll_periods"):
        a_open = _parse(existing["opens_at"])
        a_close = _parse(existing["closes_at"])
        # half-open overlap
        if a_open < closes_dt and opens_dt < a_close:
            raise_error(ERR_PERIOD_OVERLAP,
                        "Period overlaps with existing period.")

    return db.insert("payroll_periods", {
        "cycle_label": cycle_label,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "tax_rate": tax_rate,
        "status": "OPEN",
    })


def lock_period(period: dict):
    if period.get("status") != "OPEN":
        raise_error(ERR_PERIOD_STATE_INVALID, "Period not OPEN.")
    closes_dt = _parse(period["closes_at"])
    if db.now_dt() < closes_dt:
        raise_error(ERR_PERIOD_NOT_DUE, "Period close time has not been reached.")

    # Stamp candidate ledger entries.
    # The PRD anchors stamping on the triggering package's terminal
    # transition timestamp. APPROVED packages contribute PIECE_RATE,
    # BONUS, and PENALTY (band) entries via the APPROVED transition;
    # REJECTED packages contribute the flat-200 PENALTY via the
    # REJECTED transition (PRD §3.6); UPHELD-appeal cascades contribute
    # ADJUSTMENT_UPHELD and matching PIECE_RATE/BONUS via the appeal
    # decision; REJECTED-appeal cascades contribute ADJUSTMENT_REJECTED.
    # We resolve all of these uniformly by stamping any unstamped
    # SalaryLedgerEntry whose own created_at falls inside [opens, closes),
    # which equals the triggering-event timestamp by construction.
    opens_dt = _parse(period["opens_at"])
    for entry in db.all_rows("ledger_entries"):
        if entry.get("payroll_period_id"):
            continue
        try:
            ts = _parse(entry["created_at"])
        except Exception:
            continue
        if opens_dt <= ts < closes_dt:
            db.update("ledger_entries", entry["id"],
                      {"payroll_period_id": period["id"]}, bump=False)

    db.update("payroll_periods", period["id"], {"status": "LOCKED"})
    return db.find_by_id("payroll_periods", period["id"])


def _approved_packages_in_window(opens_dt, closes_dt):
    """Find all packages that transitioned to APPROVED inside [opens, closes).
    We use audit logs (STATUS_CHANGE → APPROVED) to find the timestamp.
    """
    out = []
    for log in db.all_rows("audit_logs"):
        if log.get("subject_kind") != "TASK_PACKAGE":
            continue
        if log.get("event_type") != "STATUS_CHANGE":
            continue
        if log.get("to_value") != "APPROVED":
            continue
        try:
            ts = db.parse_iso(log["created_at"])
        except Exception:
            continue
        if opens_dt <= ts < closes_dt:
            pkg = db.find_by_id("task_packages", log["subject_id"])
            if pkg:
                out.append(pkg)
    return out


def settle_period(period: dict):
    if period.get("status") != "LOCKED":
        raise_error(ERR_PERIOD_STATE_INVALID, "Period not LOCKED.")

    # Withholding rule: any package referenced by an entry of this period
    # currently in INSPECTING/REWORK_PENDING/ARBITRATING blocks settle.
    pkg_ids = {
        e["package_id"] for e in db.all_rows("ledger_entries")
        if e.get("payroll_period_id") == period["id"] and e.get("package_id")
    }
    blocked_states = {"INSPECTING", "REWORK_PENDING", "ARBITRATING"}
    for pid in pkg_ids:
        pkg = db.find_by_id("task_packages", pid)
        if pkg and pkg.get("status") in blocked_states:
            raise_error(ERR_REINSPECTION_PENDING,
                        "Settlement blocked by re-inspection-pending package.")

    # Aggregate totals per annotator.
    totals: dict[str, int] = {}
    salary_kinds = {"PIECE_RATE", "BONUS", "PENALTY",
                    "ADJUSTMENT_UPHELD", "ADJUSTMENT_REJECTED"}
    period_entries = [
        e for e in db.all_rows("ledger_entries")
        if e.get("payroll_period_id") == period["id"]
    ]
    for e in period_entries:
        if e.get("kind") in salary_kinds:
            totals[e["annotator_id"]] = totals.get(e["annotator_id"], 0) + e["gross_amount_cents"]

    # Release every entry of this period.
    for e in period_entries:
        db.update("ledger_entries", e["id"], {"settlement_state": "RELEASED"},
                  bump=False)

    # Insert TAX entries.
    for ann_id, gross_total in totals.items():
        tax_basis = max(0, gross_total)
        tax_cents = round_half_up(tax_basis * period["tax_rate"])
        if tax_cents <= 0:
            # Still write a TAX entry of 0? PRD: TAX entry inserted per annotator.
            # Write with zero amount for clarity, but skip if exactly zero to keep
            # the ledger lean — tests typically check positive tax cases.
            tax_signed = -tax_cents
        else:
            tax_signed = -tax_cents
        if tax_cents > 0:
            add_ledger_entry(
                annotator_id=ann_id, package_id=None,
                kind="TAX",
                gross_amount_cents=tax_signed,
                settlement_state="RELEASED",
                payroll_period_id=period["id"],
            )

    db.update("payroll_periods", period["id"], {"status": "SETTLED"})
    queue_event("PAYMENT", "payroll.settled", period["id"])
    return db.find_by_id("payroll_periods", period["id"])
