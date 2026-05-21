"""LeaveCase state-machine helpers, cascades, derived projections."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional

from ..audit import emit_audit
from ..clock import format_datetime_ms, get_clock, parse_iso_date
from ..common import strip_internal
from ..store import get_store, new_id
from . import calculations as calc


# ----- versioning / timestamp helpers -----


def bump_version(row: dict) -> None:
    if "version" in row:
        row["version"] = int(row["version"]) + 1
    row["updated_at"] = format_datetime_ms(get_clock().get())


def recompute_case_derived(case: dict) -> None:
    """Recompute hours_charged + job_restoration_status for a case (no version bump)."""
    store = get_store()
    employee = store.employees.get(case["employee_id"])
    if employee is None:
        return
    # hours_charged: sum APPROVED instance hours on this case
    total = 0
    for inst in store.leave_instances.values():
        if inst["leave_case_id"] == case["id"] and inst["instance_status"] == "APPROVED":
            total += int(inst["hours_used"])
    case["hours_charged"] = total
    if case["case_status"] == "DENIED":
        case["job_restoration_status"] = "NOT_APPLICABLE"
        return
    # Don't overwrite FORFEITED if already set by clock cascade
    score, status = calc.job_restoration_score_and_status(store, case, employee)
    # Forfeited from invoice cascade is sticky for non-DENIED cases
    if case.get("job_restoration_status") == "FORFEITED":
        return
    case["job_restoration_status"] = status


def view_case(case: dict) -> dict:
    """Project a case for API output: include hours_charged + job_restoration_status."""
    recompute_case_derived(case)
    out = strip_internal(case)
    return out


# ----- LeaveCase creation / lifecycle helpers -----


def compute_leave_year_anchor(leave_year_basis: str, requested_start_date_iso: str) -> str:
    d = parse_iso_date(requested_start_date_iso)
    if leave_year_basis == "CALENDAR":
        anchor = date(d.year, 1, 1)
    else:
        anchor = d
    # Anchor as midnight UTC, matching `datetime` field type
    return anchor.isoformat() + "T00:00:00.000Z"


def cert_deadline_iso(created_iso: str) -> str:
    """created_at + 15 calendar days."""
    # Parse the ISO timestamp and add 15 days
    from ..clock import parse_iso_datetime
    dt = parse_iso_datetime(created_iso)
    return format_datetime_ms(dt + timedelta(days=15))


# ----- approve / deny cascades -----


def approve_case(case: dict, actor_role: str) -> None:
    """Apply APPROVE-side effects (link 1, 2, 3)."""
    store = get_store()
    # 1. Promote PROPOSED instances to APPROVED
    for inst in store.leave_instances.values():
        if inst["leave_case_id"] == case["id"] and inst["instance_status"] == "PROPOSED":
            inst["instance_status"] = "APPROVED"

    # Recompute hours_charged
    total = 0
    for inst in store.leave_instances.values():
        if inst["leave_case_id"] == case["id"] and inst["instance_status"] == "APPROVED":
            total += int(inst["hours_used"])
    case["hours_charged"] = total
    case["case_status"] = "APPROVED"

    # 2. PFL link
    pfl_id = case.get("pfl_claim_id")
    employer = _employer_for_case(case)
    if (
        pfl_id
        and employer is not None
        and employer.get("state_pfl_program") == "STATE_PFL_8WEEK"
        and case["reason"] in {"FAMILY_SERIOUS_HEALTH", "BABY_BONDING"}
    ):
        claim = store.pfl_claims.get(pfl_id)
        if claim is not None:
            claim["claim_status"] = "PAYING"
            bump_version(claim)
            emit_audit(case["id"], "PFL_LINKED", actor_role, {"pfl_claim_id": pfl_id})

    # 3. Issue first benefit invoice
    issue_invoice_for_month_of(case, parse_iso_date(case["requested_start_date"]), actor_role)

    # Bump case version and timestamp once
    bump_version(case)
    emit_audit(case["id"], "CERTIFICATION_REVIEWED", actor_role, {"decision": "APPROVE"})


def deny_case(case: dict, actor_role: str) -> None:
    store = get_store()
    # Void instances
    for inst in store.leave_instances.values():
        if inst["leave_case_id"] == case["id"]:
            inst["instance_status"] = "VOIDED"
    case["hours_charged"] = 0
    case["case_status"] = "DENIED"
    case["job_restoration_status"] = "NOT_APPLICABLE"

    pfl_id = case.get("pfl_claim_id")
    if pfl_id:
        claim = store.pfl_claims.get(pfl_id)
        if claim is not None:
            claim["claim_status"] = "DENIED"
            bump_version(claim)
    bump_version(case)
    emit_audit(case["id"], "CERTIFICATION_REVIEWED", actor_role, {"decision": "DENY"})


def cancel_case(case: dict, actor_role: str) -> None:
    store = get_store()
    if case["case_status"] == "PENDING_CERTIFICATION":
        for inst in store.leave_instances.values():
            if inst["leave_case_id"] == case["id"]:
                inst["instance_status"] = "VOIDED"
        case["hours_charged"] = 0
    case["case_status"] = "CANCELLED"
    bump_version(case)


# ----- benefit invoice helpers -----


def issue_invoice_for_month_of(case: dict, day: date, actor_role: str) -> dict:
    """Create a BenefitInvoice for the calendar month containing `day`."""
    store = get_store()
    employer = _employer_for_case(case)
    if employer is None:
        return {}
    period_month = f"{day.year:04d}-{day.month:02d}"
    # Avoid duplicate invoice for the same case+period_month
    for inv in store.benefit_invoices.values():
        if inv["leave_case_id"] == case["id"] and inv["period_month"] == period_month:
            return inv
    amount = calc.benefit_invoice_amount(store, case, employer, day.year, day.month)
    now_iso = format_datetime_ms(get_clock().get())
    invoice = {
        "id": new_id(),
        "leave_case_id": case["id"],
        "period_month": period_month,
        "amount_due_cents": amount,
        "invoice_status": "ISSUED",
        "created_at": now_iso,
        "_seq": store.next_seq(),
    }
    store.benefit_invoices[invoice["id"]] = invoice
    emit_audit(
        case["id"],
        "BENEFIT_INVOICE_ISSUED",
        actor_role,
        {"invoice_id": invoice["id"], "period_month": period_month, "amount_due_cents": amount},
    )
    return invoice


def _employer_for_case(case: dict) -> Optional[dict]:
    store = get_store()
    employee = store.employees.get(case["employee_id"])
    if employee is None:
        return None
    return store.employers.get(employee["employer_id"])


# ----- clock-sweep ---


def clock_sweep() -> int:
    """Apply all time-gated transitions whose triggers are now due. Returns count of transitions fired."""
    store = get_store()
    clock = get_clock()
    now_dt = clock.get()
    now_date = now_dt.date()
    fired = 0

    # 1) APPROVED -> ACTIVE for cases whose requested_start_date <= now()
    for case in list(store.leave_cases.values()):
        if case["case_status"] != "APPROVED":
            continue
        req_start = parse_iso_date(case["requested_start_date"])
        if req_start <= now_date:
            case["case_status"] = "ACTIVE"
            employee = store.employees.get(case["employee_id"])
            if employee is not None and employee["employment_status"] != "TERMINATED":
                employee["employment_status"] = "ON_LEAVE"
                bump_version(employee)
            bump_version(case)
            fired += 1

    # 2) ACTIVE -> COMPLETED for cases whose expected_end_date <= now() w/ no PROPOSED instances
    for case in list(store.leave_cases.values()):
        if case["case_status"] != "ACTIVE":
            continue
        exp_end = parse_iso_date(case["expected_end_date"])
        if exp_end > now_date:
            continue
        # No PROPOSED instances remaining
        has_proposed = any(
            inst["leave_case_id"] == case["id"] and inst["instance_status"] == "PROPOSED"
            for inst in store.leave_instances.values()
        )
        if has_proposed:
            continue
        case["case_status"] = "COMPLETED"
        bump_version(case)
        fired += 1

    # 3) BenefitInvoice ISSUED -> GRACE for invoices >= 30 days old
    for inv in list(store.benefit_invoices.values()):
        if inv["invoice_status"] != "ISSUED":
            continue
        created_dt = _parse_iso(inv["created_at"])
        if (now_dt - created_dt).days >= 30:
            inv["invoice_status"] = "GRACE"
            fired += 1

    # 4) BenefitInvoice GRACE -> FORFEITED for invoices >= 45 days old; cascade case forfeit
    for inv in list(store.benefit_invoices.values()):
        if inv["invoice_status"] != "GRACE":
            continue
        created_dt = _parse_iso(inv["created_at"])
        if (now_dt - created_dt).days >= 45:
            inv["invoice_status"] = "FORFEITED"
            case = store.leave_cases.get(inv["leave_case_id"])
            if case is not None:
                case["job_restoration_status"] = "FORFEITED"
                bump_version(case)
                emit_audit(case["id"], "BENEFIT_INVOICE_FORFEITED", "system", {"invoice_id": inv["id"]})
                emit_audit(case["id"], "JOB_RESTORATION_FORFEITED", "system", {"invoice_id": inv["id"]})
            fired += 1

    # 5) Cert cure window: now() > cert_deadline + 7 days while certification_status == AWAITING_DOC or INSUFFICIENT
    for case in list(store.leave_cases.values()):
        if case["case_status"] != "PENDING_CERTIFICATION":
            continue
        deadline = _parse_iso(case["cert_deadline"])
        cure_end = deadline + timedelta(days=7)
        if now_dt > cure_end and case.get("certification_status") in {"AWAITING_DOC", "INSUFFICIENT"}:
            if case["certification_status"] != "INSUFFICIENT":
                case["certification_status"] = "INSUFFICIENT"
                bump_version(case)
                fired += 1

    # 6) Monthly benefit invoice issuance: for cases in APPROVED/ACTIVE, ensure a
    #    BenefitInvoice exists for each calendar month covered up to now().
    for case in list(store.leave_cases.values()):
        if case["case_status"] not in {"APPROVED", "ACTIVE"}:
            continue
        req_start = parse_iso_date(case["requested_start_date"])
        # Walk month by month from req_start's month through now()'s month (or expected_end_date if earlier)
        exp_end = parse_iso_date(case["expected_end_date"])
        end_walk = min(now_date, exp_end)
        cursor = date(req_start.year, req_start.month, 1)
        end_month_first = date(end_walk.year, end_walk.month, 1)
        while cursor <= end_month_first:
            period_str = f"{cursor.year:04d}-{cursor.month:02d}"
            exists = any(
                inv["leave_case_id"] == case["id"] and inv["period_month"] == period_str
                for inv in store.benefit_invoices.values()
            )
            if not exists:
                issue_invoice_for_month_of(case, cursor, "system")
                fired += 1
            # advance one month
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)

    return fired


def _parse_iso(iso: str) -> datetime:
    from ..clock import parse_iso_datetime
    return parse_iso_datetime(iso)
