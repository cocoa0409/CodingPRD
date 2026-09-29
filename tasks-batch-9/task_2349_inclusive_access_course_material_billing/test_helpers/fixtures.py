"""Scenario builders.

Every builder drives the API exactly as a client would — through the endpoints
of PRD §4 — because the server owns all derived state.  Setup calls use the
lenient ``get_success_data`` so a fixture failure surfaces as a setup error
rather than as a misleading assertion inside the test under exercise.

The vocabulary of the builders follows the PRD's own narrative order:

    term  →  agreement + title + pricing bands  →  activate
          →  section  →  adoption (draft → submitted → approved)
          →  flag for inclusive access
          →  students  →  enrollments
          →  post day-one charges

``setup_billed_section`` runs that whole chain and is the basis of most
scenarios; the primitives below let a test stop anywhere along it or branch.
"""

from typing import Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as payloads
from .test_users import (
    make_bursar_officer_headers,
    make_compliance_officer_headers,
    make_faculty_headers,
    make_program_admin_headers,
    make_registrar_headers,
    make_student_headers,
)

# A pricing band as (min_enrollment, max_enrollment, per_student_price_cents).
Band = Tuple[int, Optional[int], int]

DEFAULT_BANDS: Sequence[Band] = ((1, 2, 9000), (3, None, 7500))

DEFAULT_STUDENTS: Sequence[Tuple[str, str]] = (
    ("S-1001", "Ada Lin"),
    ("S-1002", "Ben Ortiz"),
    ("S-1003", "Cara Wu"),
    ("S-1004", "Dana Ek"),
)


# ── Logical clock ───────────────────────────────────────────────────────────

def set_clock(api, current_utc: str, headers=None) -> dict:
    """Move the logical clock (PRD §2.4)."""
    return get_success_data(
        api.set_clock(current_utc, headers or make_program_admin_headers())
    )


# ── Term ────────────────────────────────────────────────────────────────────

def create_term(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_term(payloads.term_payload(**overrides),
                        headers or make_program_admin_headers())
    )


def create_spring_term(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_term(payloads.spring_term_payload(**overrides),
                        headers or make_program_admin_headers())
    )


def open_term(api, term_id: str, headers=None) -> dict:
    return get_success_data(
        api.open_term(term_id, headers or make_program_admin_headers())
    )


def lock_term_billing(api, term_id: str, headers=None) -> dict:
    return get_success_data(
        api.lock_term_billing(term_id, headers or make_program_admin_headers())
    )


def read_term(api, term_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_term(term_id, headers or make_program_admin_headers())
    )


# ── Agreement, title, pricing bands ─────────────────────────────────────────

def create_agreement(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_agreement(payloads.agreement_payload(**overrides),
                             headers or make_program_admin_headers())
    )


def create_title(api, agreement_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_title(payloads.title_payload(agreement_id, **overrides),
                         headers or make_program_admin_headers())
    )


def add_pricing_band(api, title_id: str, band: Band, headers=None) -> dict:
    min_enrollment, max_enrollment, price = band
    return get_success_data(
        api.create_pricing_tier(
            title_id,
            payloads.pricing_tier_payload(
                min_enrollment=min_enrollment,
                max_enrollment=max_enrollment,
                per_student_price_cents=price,
            ),
            headers or make_program_admin_headers(),
        )
    )


def add_pricing_bands(api, title_id: str, bands: Iterable[Band],
                      headers=None) -> List[dict]:
    return [add_pricing_band(api, title_id, band, headers) for band in bands]


def activate_agreement(api, agreement_id: str, headers=None) -> dict:
    return get_success_data(
        api.activate_agreement(agreement_id, headers or make_program_admin_headers())
    )


def suspend_agreement(api, agreement_id: str, note: str = None, headers=None) -> dict:
    payload = payloads.suspend_payload() if note is None \
        else payloads.suspend_payload(suspend_reason_note=note)
    return get_success_data(
        api.suspend_agreement(agreement_id, payload,
                              headers or make_program_admin_headers())
    )


def withdraw_title(api, title_id: str, headers=None) -> dict:
    return get_success_data(
        api.withdraw_title(title_id, headers or make_program_admin_headers())
    )


def read_agreement(api, agreement_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_agreement(agreement_id, headers or make_program_admin_headers())
    )


def create_priced_title(api, agreement_id: str, bands: Iterable[Band] = DEFAULT_BANDS,
                        headers=None, **title_overrides) -> Tuple[dict, List[dict]]:
    """A title plus its pricing bands — the unit an agreement needs to activate."""
    title = create_title(api, agreement_id, headers, **title_overrides)
    tiers = add_pricing_bands(api, title["id"], bands, headers)
    return title, tiers


# ── Section ─────────────────────────────────────────────────────────────────

def create_section(api, term_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_section(payloads.section_payload(term_id, **overrides),
                           headers or make_registrar_headers())
    )


def read_section(api, section_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_section(section_id, headers or make_program_admin_headers())
    )


def section_version(api, section_id: str, headers=None) -> int:
    return read_section(api, section_id, headers)["version"]


def flag_section(api, section_id: str, headers=None) -> dict:
    return get_success_data(
        api.flag_section_inclusive_access(
            section_id, headers or make_program_admin_headers()
        )
    )


def read_billing_summary(api, section_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_section_billing_summary(
            section_id, headers or make_bursar_officer_headers()
        )
    )


# ── Adoption ────────────────────────────────────────────────────────────────

def create_adoption(api, section_id: str, title_id: str,
                    expected_section_version: Optional[int] = None,
                    instructor_user_id: str = "fac-1", **overrides) -> dict:
    """Author a DRAFT adoption as the section's own instructor."""
    if expected_section_version is None:
        expected_section_version = section_version(api, section_id)
    return get_success_data(
        api.create_adoption(
            payloads.adoption_payload(
                section_id, title_id, expected_section_version, **overrides
            ),
            make_faculty_headers(instructor_user_id),
        )
    )


def submit_adoption(api, adoption_id: str, instructor_user_id: str = "fac-1") -> dict:
    return get_success_data(
        api.submit_adoption(adoption_id, make_faculty_headers(instructor_user_id))
    )


def approve_adoption(api, adoption_id: str, approver_user_id: str = "pa-1") -> dict:
    return get_success_data(
        api.approve_adoption(adoption_id, make_program_admin_headers(approver_user_id))
    )


def read_adoption(api, adoption_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_adoption(adoption_id, headers or make_program_admin_headers())
    )


def create_approved_adoption(api, section_id: str, title_id: str,
                             expected_section_version: Optional[int] = None,
                             instructor_user_id: str = "fac-1",
                             approver_user_id: str = "pa-1", **overrides) -> dict:
    """Author, submit and approve one adoption; returns the approved resource."""
    adoption = create_adoption(
        api, section_id, title_id, expected_section_version,
        instructor_user_id=instructor_user_id, **overrides
    )
    submit_adoption(api, adoption["id"], instructor_user_id)
    return approve_adoption(api, adoption["id"], approver_user_id)


# ── Students and enrollments ────────────────────────────────────────────────

def create_student(api, external_id: str = "S-1001", full_name: str = "Ada Lin",
                   headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_student(
            payloads.student_payload(external_id, full_name, **overrides),
            headers or make_registrar_headers(),
        )
    )


def create_students(api, roster: Sequence[Tuple[str, str]],
                    headers=None) -> List[dict]:
    return [create_student(api, ext, name, headers) for ext, name in roster]


def read_student(api, student_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_student(student_id, headers or make_registrar_headers())
    )


def student_balance(api, student_id: str, headers=None) -> int:
    return read_student(api, student_id, headers)["bursar_balance_cents"]


def create_enrollment(api, section_id: str, student_id: str,
                      enrolled_on: str = "2026-08-24", headers=None,
                      **overrides) -> dict:
    return get_success_data(
        api.create_enrollment(
            payloads.enrollment_payload(section_id, student_id, enrolled_on,
                                        **overrides),
            headers or make_registrar_headers(),
        )
    )


def drop_enrollment(api, enrollment_id: str, dropped_on: str, headers=None) -> dict:
    return get_success_data(
        api.drop_enrollment(enrollment_id, payloads.drop_payload(dropped_on),
                            headers or make_registrar_headers())
    )


def read_enrollment(api, enrollment_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_enrollment(enrollment_id, headers or make_registrar_headers())
    )


# ── Charges and ledger ──────────────────────────────────────────────────────

def post_section_charges(api, section_id: str, headers=None) -> List[dict]:
    return get_success_data(
        api.post_section_charges(section_id, headers or make_bursar_officer_headers())
    )


def post_single_charge(api, enrollment_id: str, headers=None) -> dict:
    return get_success_data(
        api.post_enrollment_charge(
            enrollment_id, headers or make_bursar_officer_headers()
        )
    )


def read_charge(api, charge_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_charge(charge_id, headers or make_bursar_officer_headers())
    )


def read_charge_ledger(api, charge_id: str, headers=None) -> List[dict]:
    return get_success_data(
        api.list_charge_ledger_entries(
            charge_id, headers or make_bursar_officer_headers()
        )
    )


def read_student_ledger(api, student_id: str, headers=None) -> List[dict]:
    return get_success_data(
        api.list_student_ledger_entries(
            student_id, headers or make_bursar_officer_headers()
        )
    )


# ── Opt-out lifecycle ───────────────────────────────────────────────────────

def file_opt_out(api, charge_id: str, student_id: str,
                 reason_code: str = "OWNS_COPY") -> dict:
    return get_success_data(
        api.create_opt_out_request(
            payloads.opt_out_request_payload(charge_id, reason_code),
            make_student_headers(student_id),
        )
    )


def grant_opt_out(api, request_id: str, headers=None) -> dict:
    return get_success_data(
        api.grant_opt_out_request(request_id, headers or make_bursar_officer_headers())
    )


def deny_opt_out(api, request_id: str, denial_note: str = None, headers=None) -> dict:
    payload = payloads.opt_out_denial_payload() if denial_note is None \
        else payloads.opt_out_denial_payload(denial_note=denial_note)
    return get_success_data(
        api.deny_opt_out_request(request_id, payload,
                                 headers or make_bursar_officer_headers())
    )


def rescind_opt_out(api, request_id: str, student_id: str) -> dict:
    return get_success_data(
        api.rescind_opt_out_request(request_id, make_student_headers(student_id))
    )


def resubmit_opt_out(api, request_id: str, student_id: str,
                     reason_code: str = "COST") -> dict:
    return get_success_data(
        api.resubmit_opt_out_request(
            request_id, payloads.opt_out_resubmit_payload(reason_code),
            make_student_headers(student_id),
        )
    )


def read_opt_out(api, request_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_opt_out_request(request_id, headers or make_bursar_officer_headers())
    )


# ── Reconciliation and settlement ───────────────────────────────────────────

def create_reconciliation_run(api, agreement_id: str, term_id: str,
                              expected_agreement_version: Optional[int] = None,
                              publisher_reported_count: int = 0,
                              publisher_reported_amount_cents: int = 0,
                              method: str = "ENROLLMENT_SNAPSHOT",
                              headers=None, **overrides) -> dict:
    if expected_agreement_version is None:
        expected_agreement_version = read_agreement(api, agreement_id)["version"]
    return get_success_data(
        api.create_reconciliation_run(
            payloads.reconciliation_run_payload(
                agreement_id, term_id, expected_agreement_version,
                publisher_reported_count, publisher_reported_amount_cents,
                method, **overrides,
            ),
            headers or make_program_admin_headers(),
        )
    )


def dispute_run(api, run_id: str, dispute_note: str = None, headers=None) -> dict:
    payload = payloads.dispute_payload() if dispute_note is None \
        else payloads.dispute_payload(dispute_note=dispute_note)
    return get_success_data(
        api.dispute_reconciliation_run(run_id, payload,
                                       headers or make_program_admin_headers())
    )


def settle_run(api, run_id: str, headers=None) -> dict:
    return get_success_data(
        api.settle_reconciliation_run(run_id, headers or make_program_admin_headers())
    )


def read_run(api, run_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_reconciliation_run(run_id, headers or make_program_admin_headers())
    )


# ── Disclosure compliance ───────────────────────────────────────────────────

def create_disclosure_report(api, term_id: str, reporting_state_code: str = "CA",
                             headers=None) -> dict:
    return get_success_data(
        api.create_disclosure_report(
            payloads.disclosure_report_payload(term_id, reporting_state_code),
            headers or make_compliance_officer_headers(),
        )
    )


def certify_report(api, report_id: str, headers=None) -> dict:
    return get_success_data(
        api.certify_disclosure_report(
            report_id, headers or make_compliance_officer_headers()
        )
    )


def amend_report(api, report_id: str, amendment_note: str = None, headers=None) -> dict:
    payload = payloads.amend_payload() if amendment_note is None \
        else payloads.amend_payload(amendment_note=amendment_note)
    return get_success_data(
        api.amend_disclosure_report(report_id, payload,
                                    headers or make_compliance_officer_headers())
    )


def read_report(api, report_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_disclosure_report(report_id, headers or make_compliance_officer_headers())
    )


# ── Composite scenarios ─────────────────────────────────────────────────────

def setup_catalog(api, *, setup_clock: Optional[str] = "2026-07-05T00:00:00Z",
                  term_overrides: Optional[dict] = None,
                  open_term_now: bool = True,
                  spring_term: bool = False,
                  agreement_overrides: Optional[dict] = None,
                  title_overrides: Optional[dict] = None,
                  bands: Sequence[Band] = DEFAULT_BANDS,
                  activate_now: bool = True) -> dict:
    """Clock, term, agreement, one priced title, and optionally an active agreement."""
    if setup_clock:
        set_clock(api, setup_clock)

    maker = create_spring_term if spring_term else create_term
    term = maker(api, **(term_overrides or {}))
    if open_term_now:
        open_term(api, term["id"])

    agreement = create_agreement(api, **(agreement_overrides or {}))
    title, tiers = create_priced_title(
        api, agreement["id"], bands, **(title_overrides or {})
    )
    if activate_now:
        agreement = activate_agreement(api, agreement["id"])

    return {
        "term": term,
        "term_id": term["id"],
        "agreement": agreement,
        "agreement_id": agreement["id"],
        "agreement_version": agreement["version"],
        "title": title,
        "title_id": title["id"],
        "tiers": tiers,
    }


def add_section(api, catalog: dict, *, section_overrides: Optional[dict] = None,
                title_id: Optional[str] = None,
                instructor_user_id: Optional[str] = None,
                approver_user_id: str = "pa-1",
                adoption_overrides: Optional[dict] = None,
                approve_adoption_now: bool = True,
                flag_now: bool = True) -> dict:
    """A section on the catalog's term, carrying an approved adoption if asked."""
    overrides = dict(section_overrides or {})
    if instructor_user_id is not None:
        overrides["instructor_user_id"] = instructor_user_id
    instructor = overrides.get("instructor_user_id", "fac-1")

    section = create_section(api, catalog["term_id"], **overrides)
    adoption = None
    if approve_adoption_now:
        adoption = create_approved_adoption(
            api, section["id"], title_id or catalog["title_id"],
            section["version"], instructor_user_id=instructor,
            approver_user_id=approver_user_id, **(adoption_overrides or {})
        )
        if flag_now:
            section = flag_section(api, section["id"])

    return {
        "section": section,
        "section_id": section["id"],
        "section_version": section["version"],
        "instructor_user_id": instructor,
        "adoption": adoption,
        "adoption_id": adoption["id"] if adoption else None,
    }


def enroll_roster(api, section_id: str,
                  roster: Sequence[Tuple[str, str]] = DEFAULT_STUDENTS[:2], *,
                  enroll_clock: Optional[str] = "2026-08-24T08:00:00Z",
                  enrolled_on: str = "2026-08-24") -> dict:
    """Create the students, then enroll each one in ``section_id``."""
    students = create_students(api, roster)
    if enroll_clock:
        set_clock(api, enroll_clock)
    enrollments = [
        create_enrollment(api, section_id, student["id"], enrolled_on)
        for student in students
    ]
    return {
        "students": students,
        "student_ids": [student["id"] for student in students],
        "enrollments": enrollments,
        "enrollment_ids": [enrollment["id"] for enrollment in enrollments],
    }


def setup_billed_section(api, *, setup_clock: Optional[str] = "2026-07-05T00:00:00Z",
                         term_overrides: Optional[dict] = None,
                         spring_term: bool = False,
                         agreement_overrides: Optional[dict] = None,
                         title_overrides: Optional[dict] = None,
                         bands: Sequence[Band] = DEFAULT_BANDS,
                         section_overrides: Optional[dict] = None,
                         instructor_user_id: Optional[str] = None,
                         approver_user_id: str = "pa-1",
                         adoption_overrides: Optional[dict] = None,
                         roster: Sequence[Tuple[str, str]] = DEFAULT_STUDENTS[:2],
                         enroll_clock: Optional[str] = "2026-08-24T08:00:00Z",
                         enrolled_on: str = "2026-08-24",
                         post_clock: Optional[str] = "2026-08-24T09:00:00Z",
                         post_charges_now: bool = True) -> dict:
    """The full day-one chain: catalog, flagged section, roster and posted charges."""
    scenario = setup_catalog(
        api, setup_clock=setup_clock, term_overrides=term_overrides,
        spring_term=spring_term, agreement_overrides=agreement_overrides,
        title_overrides=title_overrides, bands=bands,
    )
    scenario.update(add_section(
        api, scenario, section_overrides=section_overrides,
        instructor_user_id=instructor_user_id, approver_user_id=approver_user_id,
        adoption_overrides=adoption_overrides,
    ))
    scenario.update(enroll_roster(
        api, scenario["section_id"], roster,
        enroll_clock=enroll_clock, enrolled_on=enrolled_on,
    ))

    charges: List[dict] = []
    if post_charges_now:
        if post_clock:
            set_clock(api, post_clock)
        charges = post_section_charges(api, scenario["section_id"])
    scenario["charges"] = charges
    scenario["charge_ids"] = [charge["id"] for charge in charges]

    # Refresh the derived section and agreement views after posting.
    scenario["section"] = read_section(api, scenario["section_id"])
    scenario["section_version"] = scenario["section"]["version"]
    scenario["agreement"] = read_agreement(api, scenario["agreement_id"])
    scenario["agreement_version"] = scenario["agreement"]["version"]
    return scenario
