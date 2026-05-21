"""EVerifyCase service: submit, deliver result, TNC decision, close, sweep."""
from __future__ import annotations

from typing import Any, Dict, Optional

from flask import request

from ..audit import append_audit
from ..calculations import compute_tnc_contest_deadline
from ..clock import format_datetime_ms, get_clock, parse_iso_datetime
from ..errors import (
    err_case_already_open,
    err_everify_submission_late,
    err_forbidden,
    err_invalid_state,
    err_not_found,
    err_reference_not_found,
    err_tnc_deadline_passed,
    err_validation,
    err_version_conflict,
)
from ..store import get_store, new_id


_TERMINAL_CLOSED = {"CLOSED_AUTHORIZED", "CLOSED_NOT_AUTHORIZED"}


def _get_employee_or_404(emp_id: str) -> Dict[str, Any]:
    emp = get_store().employees.get(emp_id)
    if emp is None:
        raise err_not_found("Employee not found.")
    return emp


def _get_case_or_404(case_id: str) -> Dict[str, Any]:
    c = get_store().everify_cases.get(case_id)
    if c is None:
        raise err_not_found("EVerifyCase not found.")
    return c


# ---------------------------------------------------------------------------
# Submit case (with idempotency)
# ---------------------------------------------------------------------------

def submit_case(emp_id: str, body: Dict[str, Any], actor_user_id: str, actor_role: str) -> tuple:
    """Returns (case_row, is_replay).

    is_replay=True when the request matched an existing (employee_id, idempotency_key)
    and the original case row is returned.
    """
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object.")
    store = get_store()
    clock = get_clock()
    with store.lock:
        emp = _get_employee_or_404(emp_id)

        # Idempotency-Key may come from header or body for safety; PRD says header,
        # but scaffold endpoint input lists "idempotency_key" — accept either.
        header_key = request.headers.get("Idempotency-Key") if request else None
        body_key = body.get("idempotency_key")
        idempotency_key = header_key or body_key
        if not idempotency_key or not isinstance(idempotency_key, str):
            raise err_validation("Idempotency-Key is required.")

        # Idempotent replay
        existing_id = store.idempotency_index.get((emp_id, idempotency_key))
        if existing_id is not None:
            existing = store.everify_cases.get(existing_id)
            if existing is not None:
                return existing, True

        i9_form_id = body.get("i9_form_id")
        if not i9_form_id:
            raise err_validation("i9_form_id is required.")
        form = store.i9_forms.get(i9_form_id)
        if form is None:
            raise err_reference_not_found("i9_form_id does not resolve.")
        if form["employee_id"] != emp_id:
            raise err_reference_not_found("i9_form_id does not belong to employee.")

        if form["form_status"] != "SECTION_2_DONE":
            raise err_invalid_state("Linked form must be SECTION_2_DONE.")

        # Reject if another non-closed case exists
        for c in store.everify_cases.values():
            if c["employee_id"] == emp_id and c["case_status"] not in _TERMINAL_CLOSED:
                raise err_case_already_open()

        # Optional enforce_deadline for the 3-working-day window
        enforce_deadline = bool(body.get("enforce_deadline", False))
        if enforce_deadline:
            sec2_iso = form.get("section2_completed_at")
            if sec2_iso:
                sec2_dt = parse_iso_datetime(sec2_iso)
                limit_date = clock.add_federal_working_days(sec2_dt.date(), 3)
                # End of limit date 23:59:59.999
                from datetime import datetime, timezone
                limit_dt = datetime(
                    limit_date.year, limit_date.month, limit_date.day,
                    23, 59, 59, 999_000, tzinfo=timezone.utc,
                )
                if clock.get() > limit_dt:
                    raise err_everify_submission_late()

        now = clock.get()
        now_iso = format_datetime_ms(now)
        case_id = new_id()
        row = {
            "id": case_id,
            "employee_id": emp_id,
            "i9_form_id": i9_form_id,
            "idempotency_key": idempotency_key,
            "submitted_at": now_iso,
            "case_status": "PENDING",
            "tnc_kind": None,
            "tnc_opened_at": None,
            "tnc_contest_deadline": None,
            "tnc_employee_decision": None,
            "final_disposition": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.everify_cases[case_id] = row
        store.idempotency_index[(emp_id, idempotency_key)] = case_id

        append_audit(
            subject_employee_id=emp_id,
            subject_entity="EVERIFY_CASE",
            subject_entity_id=case_id,
            action="EVERIFY_SUBMIT",
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )
    return row, False


# ---------------------------------------------------------------------------
# Deliver result (system)
# ---------------------------------------------------------------------------

def deliver_result(case_id: str, body: Dict[str, Any], actor_user_id: str, actor_role: str) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object.")
    store = get_store()
    clock = get_clock()
    with store.lock:
        case = _get_case_or_404(case_id)
        if case["case_status"] != "PENDING":
            raise err_invalid_state("Case must be PENDING to receive an outcome.")

        result = body.get("result")
        if result not in ("EMPLOYMENT_AUTHORIZED", "TNC", "FNC"):
            raise err_validation("result must be EMPLOYMENT_AUTHORIZED, TNC, or FNC.")

        now = clock.get()
        now_iso = format_datetime_ms(now)
        case["updated_at"] = now_iso
        case["version"] += 1

        if result == "EMPLOYMENT_AUTHORIZED":
            case["case_status"] = "EMPLOYMENT_AUTHORIZED"
            append_audit(
                subject_employee_id=case["employee_id"],
                subject_entity="EVERIFY_CASE",
                subject_entity_id=case_id,
                action="CASE_AUTHORIZED",
                actor_role="System",
                actor_user_id=actor_user_id,
            )
        elif result == "TNC":
            tnc_kind = body.get("tnc_kind")
            if tnc_kind not in ("SSA", "DHS"):
                raise err_validation("tnc_kind must be SSA or DHS.")
            case["case_status"] = "TNC"
            case["tnc_kind"] = tnc_kind
            case["tnc_opened_at"] = now_iso
            case["tnc_contest_deadline"] = compute_tnc_contest_deadline(now)
            append_audit(
                subject_employee_id=case["employee_id"],
                subject_entity="EVERIFY_CASE",
                subject_entity_id=case_id,
                action="TNC_OPENED",
                actor_role="System",
                actor_user_id=actor_user_id,
            )
        elif result == "FNC":
            case["case_status"] = "FNC"
            append_audit(
                subject_employee_id=case["employee_id"],
                subject_entity="EVERIFY_CASE",
                subject_entity_id=case_id,
                action="FNC_RECEIVED",
                actor_role="System",
                actor_user_id=actor_user_id,
            )
    return case


# ---------------------------------------------------------------------------
# TNC decision (employee)
# ---------------------------------------------------------------------------

def tnc_decision(case_id: str, body: Dict[str, Any], actor_user_id: str, actor_role: str) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object.")
    store = get_store()
    clock = get_clock()
    with store.lock:
        case = _get_case_or_404(case_id)
        emp = store.employees.get(case["employee_id"])
        # Ownership check — must be the owning employee
        if actor_user_id != case["employee_id"]:
            raise err_forbidden("Only the owning employee may submit a TNC decision.")
        # State check
        if case["case_status"] != "TNC":
            raise err_invalid_state("Case must be in TNC to submit a decision.")

        decision = body.get("decision")
        if decision not in ("CONTEST", "NO_CONTEST"):
            raise err_validation("decision must be CONTEST or NO_CONTEST.")

        # Deadline check (priority 10)
        deadline_iso = case.get("tnc_contest_deadline")
        if deadline_iso:
            deadline_dt = parse_iso_datetime(deadline_iso)
            if clock.get() > deadline_dt:
                raise err_tnc_deadline_passed()

        now = clock.get()
        now_iso = format_datetime_ms(now)
        case["updated_at"] = now_iso
        case["version"] += 1
        case["tnc_employee_decision"] = decision

        if decision == "CONTEST":
            case["case_status"] = "PENDING"
            append_audit(
                subject_employee_id=case["employee_id"],
                subject_entity="EVERIFY_CASE",
                subject_entity_id=case_id,
                action="TNC_CONTESTED",
                actor_role=actor_role,
                actor_user_id=actor_user_id,
            )
        else:  # NO_CONTEST
            case["case_status"] = "CLOSED_NOT_AUTHORIZED"
            case["final_disposition"] = "NOT_AUTHORIZED"
            append_audit(
                subject_employee_id=case["employee_id"],
                subject_entity="EVERIFY_CASE",
                subject_entity_id=case_id,
                action="CASE_CLOSED",
                actor_role=actor_role,
                actor_user_id=actor_user_id,
            )
            # Cascade terminate
            from .employees import terminate_employee
            if emp is not None:
                terminate_employee(emp, actor_role=actor_role, actor_user_id=actor_user_id)

    return case


# ---------------------------------------------------------------------------
# Close case (employer rep)
# ---------------------------------------------------------------------------

def close_case(case_id: str, actor_user_id: str, actor_role: str) -> Dict[str, Any]:
    store = get_store()
    clock = get_clock()
    with store.lock:
        case = _get_case_or_404(case_id)
        status = case["case_status"]
        if status not in ("EMPLOYMENT_AUTHORIZED", "FNC"):
            raise err_invalid_state("Case must be EMPLOYMENT_AUTHORIZED or FNC to close.")

        now_iso = format_datetime_ms(clock.get())
        case["updated_at"] = now_iso
        case["version"] += 1

        if status == "EMPLOYMENT_AUTHORIZED":
            case["case_status"] = "CLOSED_AUTHORIZED"
            case["final_disposition"] = "AUTHORIZED"
            append_audit(
                subject_employee_id=case["employee_id"],
                subject_entity="EVERIFY_CASE",
                subject_entity_id=case_id,
                action="CASE_CLOSED",
                actor_role=actor_role,
                actor_user_id=actor_user_id,
            )
        else:  # FNC
            case["case_status"] = "CLOSED_NOT_AUTHORIZED"
            case["final_disposition"] = "NOT_AUTHORIZED"
            append_audit(
                subject_employee_id=case["employee_id"],
                subject_entity="EVERIFY_CASE",
                subject_entity_id=case_id,
                action="CASE_CLOSED",
                actor_role=actor_role,
                actor_user_id=actor_user_id,
            )
            # Cascade terminate
            from .employees import terminate_employee
            emp = store.employees.get(case["employee_id"])
            if emp is not None:
                terminate_employee(emp, actor_role=actor_role, actor_user_id=actor_user_id)

    return case


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def run_sweep(actor_user_id: str, actor_role: str) -> None:
    """Close lapsed TNCs and expire overdue ReverificationEvents, with cascades."""
    store = get_store()
    clock = get_clock()
    now = clock.get()
    with store.lock:
        # Pass 1: lapsed TNCs
        for case in list(store.everify_cases.values()):
            if case["case_status"] != "TNC":
                continue
            if case.get("tnc_employee_decision") is not None:
                continue
            deadline_iso = case.get("tnc_contest_deadline")
            if deadline_iso is None:
                continue
            deadline_dt = parse_iso_datetime(deadline_iso)
            if now > deadline_dt:
                case["case_status"] = "CLOSED_NOT_AUTHORIZED"
                case["final_disposition"] = "NOT_AUTHORIZED"
                case["version"] += 1
                case["updated_at"] = format_datetime_ms(now)
                append_audit(
                    subject_employee_id=case["employee_id"],
                    subject_entity="EVERIFY_CASE",
                    subject_entity_id=case["id"],
                    action="TNC_DEADLINE_LAPSED",
                    actor_role="System",
                    actor_user_id=actor_user_id,
                )
                append_audit(
                    subject_employee_id=case["employee_id"],
                    subject_entity="EVERIFY_CASE",
                    subject_entity_id=case["id"],
                    action="CASE_CLOSED",
                    actor_role="System",
                    actor_user_id=actor_user_id,
                )
                emp = store.employees.get(case["employee_id"])
                if emp is not None:
                    from .employees import terminate_employee
                    terminate_employee(emp, actor_role="System", actor_user_id=actor_user_id)

        # Pass 2: expired ReverificationEvents
        for evt in list(store.reverification_events.values()):
            if evt["status"] != "OPEN":
                continue
            if evt.get("resolved_at") is not None:
                continue
            deadline_iso = evt.get("resolution_deadline")
            if deadline_iso is None:
                continue
            deadline_dt = parse_iso_datetime(deadline_iso)
            if now > deadline_dt:
                evt["status"] = "EXPIRED"
                append_audit(
                    subject_employee_id=evt["employee_id"],
                    subject_entity="REVERIFICATION_EVENT",
                    subject_entity_id=evt["id"],
                    action="REVERIFY_EXPIRED",
                    actor_role="System",
                    actor_user_id=actor_user_id,
                )
                emp = store.employees.get(evt["employee_id"])
                if emp is not None:
                    from .employees import terminate_employee
                    terminate_employee(emp, actor_role="System", actor_user_id=actor_user_id)
