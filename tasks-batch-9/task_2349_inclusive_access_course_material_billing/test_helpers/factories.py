"""Request-payload factories.

Each factory returns only the client-supplied input fields of its endpoint —
never a computed or server-minted field, because PRD §2.11 rejects unknown
fields outright.  Every factory accepts ``**overrides`` so a test can perturb
exactly one field, and ``None`` sentinels are stripped so an override of
``None`` can also *remove* an optional field.
"""

from typing import Any, Dict, Optional

_REMOVE = object()


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    # ``_REMOVE`` deletes a field wherever it came from.  Some factories expose a
    # payload field as a named parameter (``enrolled_on``, ``min_enrollment``, …),
    # so the sentinel can arrive in ``base`` rather than in ``overrides``.
    return {key: value for key, value in payload.items() if value is not _REMOVE}


REMOVE = _REMOVE


# ── Academic term ───────────────────────────────────────────────────────────

def term_payload(**overrides) -> Dict[str, Any]:
    """The Fall 2026 calendar used throughout the billing scenarios."""
    return _merge(
        {
            "code": "FA26",
            "name": "Fall 2026",
            "term_start_date": "2026-08-24",
            "term_end_date": "2026-12-11",
            "instructional_days": 75,
            "census_date": "2026-09-08",
            "add_drop_deadline": "2026-09-04",
            "late_registration_cutoff_date": "2026-09-18",
            "adoption_deadline_date": "2026-07-15",
            "disclosure_deadline_date": "2027-01-15",
            "opt_out_window_days": 14,
        },
        overrides,
    )


def spring_term_payload(**overrides) -> Dict[str, Any]:
    """A second, non-overlapping term calendar (Spring 2027)."""
    return _merge(
        {
            "code": "SP27",
            "name": "Spring 2027",
            "term_start_date": "2027-01-11",
            "term_end_date": "2027-04-30",
            "instructional_days": 72,
            "census_date": "2027-01-29",
            "add_drop_deadline": "2027-01-25",
            "late_registration_cutoff_date": "2027-02-05",
            "adoption_deadline_date": "2026-12-01",
            "disclosure_deadline_date": "2027-06-15",
            "opt_out_window_days": 14,
        },
        overrides,
    )


# ── Publisher agreement ─────────────────────────────────────────────────────

def agreement_payload(**overrides) -> Dict[str, Any]:
    """Agreement PUB-A: 5% admin fee, 12% bookstore margin, 60% list cap."""
    return _merge(
        {
            "publisher_name": "Northgate Academic",
            "agreement_code": "PUB-A",
            "effective_from": "2026-07-01",
            "effective_to": "2027-01-01",
            "admin_fee_pct": 0.05,
            "bookstore_margin_pct": 0.12,
            "price_floor_cents": 2500,
            "rebate_threshold_cents": 16500,
            "rebate_pct": 0.03,
            "max_list_price_pct": 0.60,
        },
        overrides,
    )


# ── Course material title and pricing tier ──────────────────────────────────

def title_payload(agreement_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "agreement_id": agreement_id,
            "isbn": "978-0-11-000001-0",
            "title": "Principles of Economics",
            "list_price_cents": 18000,
            "format": "DIGITAL",
        },
        overrides,
    )


def pricing_tier_payload(min_enrollment: int = 1,
                         max_enrollment: Optional[int] = 2,
                         per_student_price_cents: int = 9000,
                         **overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "min_enrollment": min_enrollment,
        "per_student_price_cents": per_student_price_cents,
    }
    if max_enrollment is not None:
        base["max_enrollment"] = max_enrollment
    return _merge(base, overrides)


# ── Course section ──────────────────────────────────────────────────────────

def section_payload(term_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "term_id": term_id,
            "subject_code": "ECON",
            "catalog_number": "101",
            "section_number": "001",
            "instructor_user_id": "fac-1",
            "max_concurrent_titles": 2,
        },
        overrides,
    )


# ── Adoption ────────────────────────────────────────────────────────────────

def adoption_payload(section_id: str, title_id: str, expected_section_version: int,
                     **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "section_id": section_id,
            "title_id": title_id,
            "access_start_date": "2026-08-24",
            "access_end_date": "2026-12-12",
            "expected_section_version": expected_section_version,
        },
        overrides,
    )


# ── Student and enrollment ──────────────────────────────────────────────────

def student_payload(external_id: str = "S-1001",
                    full_name: str = "Ada Lin",
                    **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "external_id": external_id,
            "full_name": full_name,
            "email": f"{external_id.lower()}@campus.edu",
            "program_code": "BA-ECON",
        },
        overrides,
    )


def enrollment_payload(section_id: str, student_id: str,
                       enrolled_on: str = "2026-08-24", **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "section_id": section_id,
            "student_id": student_id,
            "enrolled_on": enrolled_on,
        },
        overrides,
    )


def drop_payload(dropped_on: str, **overrides) -> Dict[str, Any]:
    return _merge({"dropped_on": dropped_on}, overrides)


# ── Opt-out request ─────────────────────────────────────────────────────────

def opt_out_request_payload(charge_id: str, reason_code: str = "OWNS_COPY",
                            **overrides) -> Dict[str, Any]:
    return _merge({"charge_id": charge_id, "reason_code": reason_code}, overrides)


def opt_out_resubmit_payload(reason_code: str = "COST", **overrides) -> Dict[str, Any]:
    return _merge({"reason_code": reason_code}, overrides)


def opt_out_denial_payload(denial_note: str = "Course pack already includes the text.",
                           **overrides) -> Dict[str, Any]:
    return _merge({"denial_note": denial_note}, overrides)


# ── Reconciliation run ──────────────────────────────────────────────────────

def reconciliation_run_payload(agreement_id: str, term_id: str,
                               expected_agreement_version: int,
                               publisher_reported_count: int = 0,
                               publisher_reported_amount_cents: int = 0,
                               method: str = "ENROLLMENT_SNAPSHOT",
                               **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "agreement_id": agreement_id,
            "term_id": term_id,
            "method": method,
            "publisher_reported_count": publisher_reported_count,
            "publisher_reported_amount_cents": publisher_reported_amount_cents,
            "expected_agreement_version": expected_agreement_version,
        },
        overrides,
    )


def dispute_payload(dispute_note: str = "Publisher invoice overstates the headcount.",
                    **overrides) -> Dict[str, Any]:
    return _merge({"dispute_note": dispute_note}, overrides)


# ── Disclosure report ───────────────────────────────────────────────────────

def disclosure_report_payload(term_id: str, reporting_state_code: str = "CA",
                              **overrides) -> Dict[str, Any]:
    return _merge(
        {"term_id": term_id, "reporting_state_code": reporting_state_code}, overrides
    )


def amend_payload(amendment_note: str = "Restating after a late refund.",
                  **overrides) -> Dict[str, Any]:
    return _merge({"amendment_note": amendment_note}, overrides)


# ── Agreement suspension ────────────────────────────────────────────────────

def suspend_payload(suspend_reason_note: str = "Publisher breached the delivery SLA.",
                    **overrides) -> Dict[str, Any]:
    return _merge({"suspend_reason_note": suspend_reason_note}, overrides)


def change_request_payload(change_note: str = "Please confirm the access window.",
                           **overrides) -> Dict[str, Any]:
    return _merge({"change_note": change_note}, overrides)
