"""I9Form lifecycle service."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from ..audit import append_audit
from ..calculations import (
    compute_reverification_deadline,
    compute_reverification_due,
    compute_section2_deadline,
)
from ..clock import format_datetime_ms, get_clock, parse_iso_date, parse_iso_datetime
from ..errors import (
    err_document_category_mismatch,
    err_document_expired,
    err_document_list_rule,
    err_duplicate_initial_form,
    err_forbidden,
    err_form_already_signed,
    err_invalid_form_lineage,
    err_invalid_state,
    err_not_found,
    err_reference_not_found,
    err_section2_deadline_missed,
    err_segregation_of_duties,
    err_validation,
    err_version_conflict,
)
from ..store import get_store, new_id
from .reverification import (
    find_open_event_for_form,
    open_reverification_event,
    resolve_event,
)


_VALID_FORM_KIND = {"INITIAL", "REVERIFICATION", "REHIRE"}
_VALID_FORM_STATUS = {"DRAFT", "SECTION_1_DONE", "SECTION_2_DONE", "SUPERSEDED", "VOIDED"}


def _get_employee_or_404(emp_id: str) -> Dict[str, Any]:
    emp = get_store().employees.get(emp_id)
    if emp is None:
        raise err_not_found("Employee not found.")
    return emp


def _get_form_or_404(form_id: str) -> Dict[str, Any]:
    f = get_store().i9_forms.get(form_id)
    if f is None:
        raise err_not_found("I9Form not found.")
    return f


# ---------------------------------------------------------------------------
# Create form
# ---------------------------------------------------------------------------

def create_form(emp_id: str, body: Dict[str, Any], actor_user_id: str, actor_role: str) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object.")
    store = get_store()
    clock = get_clock()
    with store.lock:
        emp = _get_employee_or_404(emp_id)

        form_kind = body.get("form_kind")
        if form_kind not in _VALID_FORM_KIND:
            raise err_validation("form_kind must be one of INITIAL, REVERIFICATION, REHIRE.")

        supersedes_form_id = body.get("supersedes_form_id")

        if form_kind == "INITIAL":
            if supersedes_form_id is not None:
                # An INITIAL form must not link to a predecessor.
                raise err_invalid_form_lineage("INITIAL forms must not specify supersedes_form_id.")
            # Duplicate-initial check
            for f in store.i9_forms.values():
                if (
                    f["employee_id"] == emp_id
                    and f["form_kind"] == "INITIAL"
                    and f["form_status"] not in ("VOIDED",)
                ):
                    raise err_duplicate_initial_form()
        else:
            # REVERIFICATION or REHIRE require predecessor
            if not supersedes_form_id:
                raise err_invalid_form_lineage(f"{form_kind} requires supersedes_form_id.")
            predecessor = store.i9_forms.get(supersedes_form_id)
            if predecessor is None:
                raise err_reference_not_found("supersedes_form_id does not resolve.")
            if predecessor["employee_id"] != emp_id:
                raise err_invalid_form_lineage("Predecessor belongs to a different employee.")
            if predecessor["form_status"] != "SECTION_2_DONE":
                raise err_invalid_form_lineage("Predecessor must be SECTION_2_DONE.")
            if form_kind == "REHIRE":
                # Predecessor's section2_completed_at must be within 3 years of new start_date.
                pred_sec2 = predecessor.get("section2_completed_at")
                if pred_sec2 is None:
                    raise err_invalid_form_lineage("Predecessor lacks section2_completed_at.")
                pred_dt = parse_iso_datetime(pred_sec2)
                start_date_iso = emp["start_date"]
                start_dt = parse_iso_date(start_date_iso)
                # 3 years window: pred section2_completed_at >= start_date - 3 years
                # i.e., pred date no earlier than start_date - 1095 days approx.
                # Use month arithmetic with replace year - 3, fall back when needed.
                try:
                    threshold = start_dt.replace(year=start_dt.year - 3)
                except ValueError:
                    # Leap day fallback
                    threshold = start_dt.replace(year=start_dt.year - 3, day=28)
                if pred_dt.date() < threshold:
                    raise err_invalid_form_lineage("Predecessor section2 outside 3-year window for REHIRE.")

        now_iso = format_datetime_ms(clock.get())
        form_id = new_id()
        row = {
            "id": form_id,
            "employee_id": emp_id,
            "form_kind": form_kind,
            "supersedes_form_id": supersedes_form_id,
            "section1_completed_at": None,
            "section1_attested_by_user_id": None,
            "section2_completed_at": None,
            "section2_completed_by_user_id": None,
            "list_a_document_id": None,
            "list_b_document_id": None,
            "list_c_document_id": None,
            "form_status": "DRAFT",
            "reverification_due": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.i9_forms[form_id] = row
        append_audit(
            subject_employee_id=emp_id,
            subject_entity="I9_FORM",
            subject_entity_id=form_id,
            action="FORM_CREATED",
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )
    return row


# ---------------------------------------------------------------------------
# List forms
# ---------------------------------------------------------------------------

def list_forms(emp_id: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    store = get_store()
    if emp_id not in store.employees:
        raise err_not_found("Employee not found.")
    items = [f for f in store.i9_forms.values() if f["employee_id"] == emp_id]
    if filters.get("form_status") is not None:
        items = [f for f in items if f["form_status"] == filters["form_status"]]
    if filters.get("form_kind") is not None:
        items = [f for f in items if f["form_kind"] == filters["form_kind"]]
    items.sort(key=lambda f: (f["created_at"], f["_seq"]))
    return items


# ---------------------------------------------------------------------------
# Section 1 attestation
# ---------------------------------------------------------------------------

def section1_attest(emp_id: str, form_id: str, body: Dict[str, Any], actor_user_id: str, actor_role: str) -> Dict[str, Any]:
    if not isinstance(body, dict):
        body = {}
    store = get_store()
    clock = get_clock()
    with store.lock:
        emp = _get_employee_or_404(emp_id)
        form = _get_form_or_404(form_id)
        if form["employee_id"] != emp_id:
            raise err_not_found("I9Form not found for this employee.")

        # Ownership check — Employee role: X-User-ID must equal employee.id.
        if actor_user_id != emp["id"]:
            raise err_forbidden("Section 1 must be attested by the owning employee.")

        # OCC
        if "version" in body and body["version"] is not None:
            try:
                supplied = int(body["version"])
            except (TypeError, ValueError):
                raise err_validation("version must be an integer.")
            if supplied != form["version"]:
                raise err_version_conflict()

        # State preconditions
        if form["form_status"] != "DRAFT":
            raise err_invalid_state("Form must be DRAFT to attest Section 1.")

        if emp.get("is_terminated"):
            raise err_invalid_state("Employee is terminated.")

        if form["form_kind"] == "REVERIFICATION":
            pred_id = form.get("supersedes_form_id")
            pred = store.i9_forms.get(pred_id) if pred_id else None
            if pred is None or pred["employee_id"] != emp_id or pred["form_status"] != "SECTION_2_DONE":
                raise err_invalid_form_lineage("REVERIFICATION predecessor invalid.")

        now = clock.get()
        now_iso = format_datetime_ms(now)
        form["section1_completed_at"] = now_iso
        form["section1_attested_by_user_id"] = actor_user_id
        form["form_status"] = "SECTION_1_DONE"
        form["version"] += 1
        form["updated_at"] = now_iso

        # Recompute Employee.section2_deadline
        emp["section2_deadline"] = compute_section2_deadline(emp["start_date"])

        append_audit(
            subject_employee_id=emp_id,
            subject_entity="I9_FORM",
            subject_entity_id=form_id,
            action="SECTION_1_ATTEST",
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )
    return form


# ---------------------------------------------------------------------------
# Section 2 sign
# ---------------------------------------------------------------------------

def section2_sign(emp_id: str, form_id: str, body: Dict[str, Any], actor_user_id: str, actor_role: str) -> Dict[str, Any]:
    if not isinstance(body, dict):
        body = {}
    store = get_store()
    clock = get_clock()
    with store.lock:
        emp = _get_employee_or_404(emp_id)
        form = _get_form_or_404(form_id)
        if form["employee_id"] != emp_id:
            raise err_not_found("I9Form not found for this employee.")

        # Body FK refs validated first (priority 4)
        list_a = body.get("list_a_document_id")
        list_b = body.get("list_b_document_id")
        list_c = body.get("list_c_document_id")

        # Resolve and verify referenced docs exist
        for did in (list_a, list_b, list_c):
            if did is not None and did not in store.i9_documents:
                raise err_reference_not_found("Referenced I9Document not found.")

        # State precondition (priority 5). PRD §2.9: any form not in
        # SECTION_1_DONE state surfaces ERR_INVALID_STATE. The
        # ERR_FORM_ALREADY_SIGNED code is reserved for the concurrent-race
        # winner described in PRD §2.10 (two simultaneous EmployerRep
        # signings serialized on form_status).
        if form["form_status"] != "SECTION_1_DONE":
            raise err_invalid_state("Form must be SECTION_1_DONE to sign Section 2.")

        # OCC
        if "version" in body and body["version"] is not None:
            try:
                supplied = int(body["version"])
            except (TypeError, ValueError):
                raise err_validation("version must be an integer.")
            if supplied != form["version"]:
                raise err_version_conflict()

        # Segregation of duties (priority 6)
        s1_attester = form.get("section1_attested_by_user_id")
        if s1_attester is not None and actor_user_id == s1_attester:
            raise err_segregation_of_duties()

        # Document list rule (priority 7) — exactly LIST_A alone OR (LIST_B AND LIST_C)
        a_present = list_a is not None
        b_present = list_b is not None
        c_present = list_c is not None
        if a_present and (b_present or c_present):
            raise err_document_list_rule()
        if not a_present and not (b_present and c_present):
            raise err_document_list_rule()

        # Document category match + employee ownership (priority 8)
        doc_a = store.i9_documents.get(list_a) if list_a else None
        doc_b = store.i9_documents.get(list_b) if list_b else None
        doc_c = store.i9_documents.get(list_c) if list_c else None
        for doc, expected_cat in (
            (doc_a, "LIST_A"),
            (doc_b, "LIST_B"),
            (doc_c, "LIST_C"),
        ):
            if doc is None:
                continue
            if doc["category"] != expected_cat:
                raise err_document_category_mismatch()
            if doc["employee_id"] != emp_id:
                raise err_document_category_mismatch()

        # Document expiration (priority 9)
        now = clock.get()
        today = now.date()
        for doc in (doc_a, doc_b, doc_c):
            if doc is None:
                continue
            exp = doc.get("expiration_date")
            if exp is None:
                continue
            exp_date = parse_iso_date(exp)
            if exp_date < today:
                # Receipt carve-out: valid if receipt=true and receipt_resolution_due > today (strict)
                if doc.get("receipt") and doc.get("receipt_resolution_due"):
                    rrd = parse_iso_date(doc["receipt_resolution_due"])
                    if rrd > today:
                        continue
                raise err_document_expired()

        # Section 2 deadline enforcement (priority 11) — only when enforce_deadline=true
        enforce_deadline = bool(body.get("enforce_deadline", False))
        deadline_iso = emp.get("section2_deadline")
        late = False
        if deadline_iso is not None:
            deadline_dt = parse_iso_datetime(deadline_iso)
            if now > deadline_dt:
                if enforce_deadline:
                    raise err_section2_deadline_missed()
                late = True

        # Apply state transition
        now_iso = format_datetime_ms(now)
        form["section2_completed_at"] = now_iso
        form["section2_completed_by_user_id"] = actor_user_id
        form["list_a_document_id"] = list_a
        form["list_b_document_id"] = list_b
        form["list_c_document_id"] = list_c
        form["form_status"] = "SECTION_2_DONE"
        form["version"] += 1
        form["updated_at"] = now_iso

        # Compute reverification_due
        docs_on_form = [d for d in (doc_a, doc_b, doc_c) if d is not None]
        new_due = compute_reverification_due(emp, docs_on_form, stem_extended=False)
        form["reverification_due"] = new_due

        # Audit Section 2 sign
        append_audit(
            subject_employee_id=emp_id,
            subject_entity="I9_FORM",
            subject_entity_id=form_id,
            action="SECTION_2_SIGN",
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )
        if late:
            append_audit(
                subject_employee_id=emp_id,
                subject_entity="I9_FORM",
                subject_entity_id=form_id,
                action="SECTION_2_LATE",
                actor_role=actor_role,
                actor_user_id=actor_user_id,
            )

        # Maybe open a ReverificationEvent (reason=WORK_AUTH_EXPIRY) — when there is
        # a non-null reverification_due driven by an ALIEN_AUTHORIZED or specific
        # LIST_A doc title, or LIST_C doc with expiration_date.
        if _should_open_workauth_reverification(emp, doc_a, doc_b, doc_c) and new_due is not None:
            deadline = compute_reverification_deadline(
                reason="WORK_AUTH_EXPIRY",
                base_reverification_due=new_due,
                rehire_start_date=None,
            )
            open_reverification_event(
                employee=emp,
                triggering_form_id=form_id,
                reason="WORK_AUTH_EXPIRY",
                resolution_deadline=deadline,
                actor_role=actor_role,
                actor_user_id=actor_user_id,
            )

        # Cascade: supersede predecessor (if any) + resolve linked reverification event
        predecessor_id = form.get("supersedes_form_id")
        if predecessor_id:
            predecessor = store.i9_forms.get(predecessor_id)
            if predecessor is not None and predecessor["form_status"] == "SECTION_2_DONE":
                predecessor["form_status"] = "SUPERSEDED"
                predecessor["version"] += 1
                predecessor["updated_at"] = now_iso
                append_audit(
                    subject_employee_id=emp_id,
                    subject_entity="I9_FORM",
                    subject_entity_id=predecessor["id"],
                    action="FORM_SUPERSEDED",
                    actor_role="System",
                    actor_user_id=None,
                )
                # Resolve any open reverification event for the predecessor
                evt = find_open_event_for_form(predecessor_id)
                if evt is not None:
                    resolve_event(evt, form, actor_role="System", actor_user_id=None)

    return form


def _should_open_workauth_reverification(emp: dict, doc_a, doc_b, doc_c) -> bool:
    """Per scaffold: open WORK_AUTH_EXPIRY event when:
       - Form has a LIST_A doc whose title is in {'EAD I-766','I-94','Foreign Passport with I-94'}, OR
       - Employee.citizenship_status == ALIEN_AUTHORIZED and work_authorization_expiry is not null.
    """
    if doc_a is not None and doc_a.get("document_title") in (
        "EAD I-766", "I-94", "Foreign Passport with I-94"
    ):
        return True
    if emp.get("citizenship_status") == "ALIEN_AUTHORIZED" and emp.get("work_authorization_expiry"):
        return True
    return False


# ---------------------------------------------------------------------------
# Void form
# ---------------------------------------------------------------------------

def void_form(form_id: str, body: Dict[str, Any], actor_user_id: str, actor_role: str) -> Dict[str, Any]:
    if not isinstance(body, dict):
        body = {}
    store = get_store()
    clock = get_clock()
    with store.lock:
        form = _get_form_or_404(form_id)

        # OCC
        if "version" in body and body["version"] is not None:
            try:
                supplied = int(body["version"])
            except (TypeError, ValueError):
                raise err_validation("version must be an integer.")
            if supplied != form["version"]:
                raise err_version_conflict()

        status = form["form_status"]
        if status not in ("DRAFT", "SECTION_1_DONE"):
            raise err_invalid_state("Form may only be voided in DRAFT or SECTION_1_DONE.")

        if status == "SECTION_1_DONE":
            # Must have no EVerifyCase against this form
            for c in store.everify_cases.values():
                if c["i9_form_id"] == form_id:
                    raise err_invalid_state("Cannot void a form with an E-Verify case.")

        form["form_status"] = "VOIDED"
        form["version"] += 1
        now_iso = format_datetime_ms(clock.get())
        form["updated_at"] = now_iso

        append_audit(
            subject_employee_id=form["employee_id"],
            subject_entity="I9_FORM",
            subject_entity_id=form_id,
            action="FORM_VOIDED",
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )
    return form
