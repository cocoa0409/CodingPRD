"""Derive Employee.onboarding_status per SCAFFOLD §1.3 derive_onboarding_status."""
from __future__ import annotations

from typing import Optional

from ..store import get_store


def derive_onboarding_status(employee: dict) -> str:
    if employee.get("is_terminated"):
        return "TERMINATED"

    store = get_store()
    emp_id = employee["id"]

    # Latest non-terminal form: created_at desc, ties broken by id asc.
    forms = [
        f for f in store.i9_forms.values()
        if f["employee_id"] == emp_id and f["form_status"] not in ("SUPERSEDED", "VOIDED")
    ]
    forms.sort(key=lambda f: (-f["_seq"], f["id"]))
    latest_form = forms[0] if forms else None

    # Latest non-closed case.
    cases = [
        c for c in store.everify_cases.values()
        if c["employee_id"] == emp_id and c["case_status"] not in ("CLOSED_AUTHORIZED", "CLOSED_NOT_AUTHORIZED")
    ]
    cases.sort(key=lambda c: (-c["_seq"], c["id"]))
    latest_case = cases[0] if cases else None

    if latest_form is None or latest_form["form_status"] == "DRAFT":
        return "PENDING_SECTION_1"
    if latest_form["form_status"] == "SECTION_1_DONE":
        return "PENDING_SECTION_2"

    # Section 2 done — examine cases.
    if latest_case is not None:
        if latest_case["case_status"] == "TNC":
            return "TNC_OPEN"
        if latest_case["case_status"] in ("PENDING", "EMPLOYMENT_AUTHORIZED", "FNC", "DRAFT"):
            return "EVERIFY_PENDING"

    # No non-closed case; look at most recent CLOSED_* case to decide.
    closed_cases = [
        c for c in store.everify_cases.values()
        if c["employee_id"] == emp_id and c["case_status"] in ("CLOSED_AUTHORIZED", "CLOSED_NOT_AUTHORIZED")
    ]
    closed_cases.sort(key=lambda c: (-c["_seq"], c["id"]))
    if closed_cases:
        latest_closed = closed_cases[0]
        if latest_closed.get("final_disposition") == "AUTHORIZED":
            return "AUTHORIZED"
        return "NOT_AUTHORIZED"
    # Section 2 done but no case opened or closed yet.
    return "EVERIFY_PENDING"
