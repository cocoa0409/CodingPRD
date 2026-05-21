"""Employee CRUD logic."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..audit import append_audit
from ..calculations import compute_section2_deadline, compute_reverification_deadline
from ..clock import format_datetime_ms, get_clock, parse_iso_date
from ..errors import (
    err_invalid_state,
    err_not_found,
    err_stem_extension_late,
    err_validation,
    err_version_conflict,
)
from ..store import get_store, new_id
from .onboarding_status import derive_onboarding_status
from .reverification import open_reverification_event


_VALID_CITIZENSHIP = {"US_CITIZEN", "NON_CITIZEN_NATIONAL", "LAWFUL_PERMANENT_RESIDENT", "ALIEN_AUTHORIZED"}
_VALID_VISA = {"F1_OPT", "F1_OPT_STEM", "H1B", "L1", "TN", "OTHER"}
_VALID_ONBOARDING_STATUS = {
    "PENDING_SECTION_1", "PENDING_SECTION_2", "EVERIFY_PENDING",
    "TNC_OPEN", "AUTHORIZED", "NOT_AUTHORIZED", "TERMINATED",
}


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _require(body: Optional[Dict[str, Any]], field: str) -> Any:
    if body is None or field not in body or body[field] is None:
        raise err_validation(f"Missing required field: {field}")
    return body[field]


def _validate_iso_date(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        raise err_validation(f"{field} must be ISO-8601 date YYYY-MM-DD.")
    try:
        parse_iso_date(value)
    except Exception:
        raise err_validation(f"{field} is not a valid date.")
    return value


def _validate_string(value: Any, field: str, *, min_len: int = 1, max_len: int = 200) -> str:
    if not isinstance(value, str):
        raise err_validation(f"{field} must be a string.")
    trimmed = value.strip()
    if len(trimmed) < min_len or len(trimmed) > max_len:
        raise err_validation(f"{field} length must be in [{min_len}, {max_len}] after trim.")
    return trimmed


def create_employee(body: Dict[str, Any], actor_user_id: str, actor_role: str) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object.")

    legal_name = _validate_string(_require(body, "legal_name"), "legal_name")
    date_of_birth = _validate_iso_date(_require(body, "date_of_birth"), "date_of_birth")
    ssn = _require(body, "ssn")
    if not isinstance(ssn, str) or not re.fullmatch(r"\d{9}", ssn):
        raise err_validation("ssn must be exactly 9 digits.")
    citizenship_status = _require(body, "citizenship_status")
    if citizenship_status not in _VALID_CITIZENSHIP:
        raise err_validation("citizenship_status invalid.")
    start_date = _validate_iso_date(_require(body, "start_date"), "start_date")

    work_auth_expiry = body.get("work_authorization_expiry")
    if work_auth_expiry is not None:
        _validate_iso_date(work_auth_expiry, "work_authorization_expiry")

    visa_class = body.get("visa_class")
    if visa_class is not None and visa_class not in _VALID_VISA:
        raise err_validation("visa_class invalid.")

    store = get_store()
    clock = get_clock()
    with store.lock:
        # ssn uniqueness across active employees
        existing_emp_id = store.ssn_index.get(ssn)
        if existing_emp_id is not None:
            existing = store.employees.get(existing_emp_id)
            if existing is not None and not existing.get("is_terminated"):
                raise err_validation("ssn must be unique across active employees.")

        now = clock.get()
        now_iso = format_datetime_ms(now)
        emp_id = new_id()
        row = {
            "id": emp_id,
            "legal_name": legal_name,
            "date_of_birth": date_of_birth,
            "ssn": ssn,
            "citizenship_status": citizenship_status,
            "work_authorization_expiry": work_auth_expiry,
            "visa_class": visa_class,
            "start_date": start_date,
            "section2_deadline": compute_section2_deadline(start_date),
            "is_terminated": False,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.employees[emp_id] = row
        store.ssn_index[ssn] = emp_id

        append_audit(
            subject_employee_id=emp_id,
            subject_entity="EMPLOYEE",
            subject_entity_id=emp_id,
            action="EMPLOYEE_CREATED",
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )

    return row


def get_employee(emp_id: str) -> Dict[str, Any]:
    store = get_store()
    emp = store.employees.get(emp_id)
    if emp is None:
        raise err_not_found("Employee not found.")
    return emp


def patch_employee(emp_id: str, body: Dict[str, Any], actor_user_id: str, actor_role: str) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object.")
    store = get_store()
    clock = get_clock()
    with store.lock:
        emp = store.employees.get(emp_id)
        if emp is None:
            raise err_not_found("Employee not found.")

        # OCC: if version supplied, must match.
        if "version" in body and body["version"] is not None:
            try:
                supplied = int(body["version"])
            except (TypeError, ValueError):
                raise err_validation("version must be an integer.")
            if supplied != emp["version"]:
                raise err_version_conflict()

        new_start_date = body.get("start_date")
        if new_start_date is not None:
            _validate_iso_date(new_start_date, "start_date")

        new_work_auth_expiry = body.get("work_authorization_expiry", "__unset__")
        if new_work_auth_expiry not in ("__unset__", None):
            _validate_iso_date(new_work_auth_expiry, "work_authorization_expiry")

        new_visa_class = body.get("visa_class", "__unset__")
        if new_visa_class not in ("__unset__", None) and new_visa_class not in _VALID_VISA:
            raise err_validation("visa_class invalid.")

        # Determine STEM transition
        stem_transition = (
            new_visa_class != "__unset__"
            and new_visa_class == "F1_OPT_STEM"
            and emp.get("visa_class") == "F1_OPT"
        )

        if stem_transition:
            # Locate the EAD I-766 LIST_A document used in the latest SECTION_2_DONE form.
            ead_expiry_date = _find_ead_expiry(emp)
            if ead_expiry_date is None:
                raise err_stem_extension_late("No EAD I-766 found to extend.")
            now_dt = clock.get()
            from ..clock import parse_iso_date as _pid
            if now_dt.date() > _pid(ead_expiry_date):
                raise err_stem_extension_late()

        # Apply changes
        if new_start_date is not None:
            emp["start_date"] = new_start_date
            emp["section2_deadline"] = compute_section2_deadline(new_start_date)
        if new_work_auth_expiry != "__unset__":
            emp["work_authorization_expiry"] = new_work_auth_expiry
        if new_visa_class != "__unset__":
            emp["visa_class"] = new_visa_class

        emp["version"] += 1
        now = clock.get()
        emp["updated_at"] = format_datetime_ms(now)

        append_audit(
            subject_employee_id=emp_id,
            subject_entity="EMPLOYEE",
            subject_entity_id=emp_id,
            action="EMPLOYEE_UPDATED",
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )

        # On STEM transition, recompute reverification_due on the latest SECTION_2_DONE form
        # and open a ReverificationEvent reason=OPT_TO_OPT_STEM_EXTENSION.
        if stem_transition:
            from ..calculations import compute_reverification_due
            triggering_form = _latest_section2_done_form(emp)
            if triggering_form is not None:
                docs_on_form = _docs_on_form(triggering_form)
                new_due = compute_reverification_due(emp, docs_on_form, stem_extended=True)
                triggering_form["reverification_due"] = new_due
                # Open a reverification event
                deadline = compute_reverification_deadline(
                    reason="OPT_TO_OPT_STEM_EXTENSION",
                    base_reverification_due=_find_ead_expiry(emp),
                    rehire_start_date=None,
                )
                open_reverification_event(
                    employee=emp,
                    triggering_form_id=triggering_form["id"],
                    reason="OPT_TO_OPT_STEM_EXTENSION",
                    resolution_deadline=deadline,
                    actor_role=actor_role,
                    actor_user_id=actor_user_id,
                )

    return emp


def list_employees(filters: Dict[str, Any]) -> list:
    store = get_store()
    items = list(store.employees.values())

    status_filter = filters.get("onboarding_status")
    if status_filter is not None:
        if status_filter not in _VALID_ONBOARDING_STATUS:
            # Treat unknown filter as no match — but still computed; just return []
            items = []
        else:
            items = [e for e in items if derive_onboarding_status(e) == status_filter]

    is_term = filters.get("is_terminated")
    if is_term is not None:
        # Accept booleans or string equivalents
        if isinstance(is_term, str):
            tf = is_term.lower() == "true"
        else:
            tf = bool(is_term)
        items = [e for e in items if bool(e.get("is_terminated")) == tf]

    items.sort(key=lambda e: (e.get("created_at"), e["_seq"]))
    return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _docs_on_form(form: dict) -> list:
    store = get_store()
    out = []
    for f in ("list_a_document_id", "list_b_document_id", "list_c_document_id"):
        did = form.get(f)
        if did:
            d = store.i9_documents.get(did)
            if d is not None:
                out.append(d)
    return out


def _latest_section2_done_form(employee: dict) -> Optional[dict]:
    store = get_store()
    forms = [
        f for f in store.i9_forms.values()
        if f["employee_id"] == employee["id"] and f["form_status"] == "SECTION_2_DONE"
    ]
    if not forms:
        return None
    forms.sort(key=lambda f: (-f["_seq"], f["id"]))
    return forms[0]


def _find_ead_expiry(employee: dict) -> Optional[str]:
    """Return the EAD I-766 document's expiration_date used on the latest SECTION_2_DONE form."""
    form = _latest_section2_done_form(employee)
    if form is None:
        return None
    store = get_store()
    list_a_id = form.get("list_a_document_id")
    if not list_a_id:
        return None
    doc = store.i9_documents.get(list_a_id)
    if doc is None:
        return None
    if doc.get("document_title") != "EAD I-766":
        return None
    return doc.get("expiration_date")


def terminate_employee(employee: dict, *, actor_role: str, actor_user_id: Optional[str]) -> None:
    """Mark an employee as terminated and append an audit event."""
    store = get_store()
    clock = get_clock()
    if employee.get("is_terminated"):
        return
    with store.lock:
        employee["is_terminated"] = True
        employee["version"] = employee.get("version", 1) + 1
        employee["updated_at"] = format_datetime_ms(clock.get())
        append_audit(
            subject_employee_id=employee["id"],
            subject_entity="EMPLOYEE",
            subject_entity_id=employee["id"],
            action="TERMINATE",
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )
