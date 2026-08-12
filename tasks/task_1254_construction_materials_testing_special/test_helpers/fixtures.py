"""Composite setup helpers for the construction materials testing test suite.

These encapsulate the multi-step API sequences needed to put the system into a
testable state (approved SSI revisions, certified technicians, dispatched
assignments, recorded results, NCRs, daily reports, letter readiness). All
setup calls use the lenient get_success_data() validator so a failed
precondition surfaces as a clear "Setup step failed" error.

Identity threading: Technician is the only entity-backed role. Every helper
that performs a Technician-gated call (field tests, lab samples, completion,
daily reports, NCR verification, discrepancies) builds per-instance headers
via make_technician_headers() from the actual Technician id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CERT_FAR_EXPIRY, DEFAULT_FC_PSI, DEFAULT_WORK_DATE
from .factories import (
    append_certification_payload,
    approve_decision_payload,
    certification_entry,
    create_assignment_payload,
    create_daily_report_payload,
    create_discrepancy_payload,
    create_field_test_payload,
    create_lab_payload,
    create_lab_sample_payload,
    create_project_payload,
    create_ssi_revision_payload,
    create_technician_payload,
    concrete_scope_item,
    record_break_payload,
    respond_discrepancy_payload,
    schedule_break_payload,
    set_clock_payload,
    soil_scope_item,
    submit_correction_payload,
    verify_ncr_payload,
    void_letter_payload,
)
from .test_users import TEST_USERS, make_technician_headers

ADMIN = TEST_USERS["agency_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
ENGINEER = TEST_USERS["engineer_of_record_headers"]
LAB_ANALYST = TEST_USERS["lab_analyst_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]
BUILDING_OFFICIAL = TEST_USERS["building_official_headers"]


def tech_headers(technician_id: str) -> dict:
    return make_technician_headers(technician_id)


# ---------------------------------------------------------------------------
# Tier 0: clock + single-resource creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (AgencyAdmin-only). Returns {current_utc}."""
    return get_success_data(api_client.set_current_utc(set_clock_payload(to_iso8601), ADMIN))


def create_project(**overrides) -> dict:
    return get_success_data(api_client.create_project(create_project_payload(**overrides), ADMIN))


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, PM))


def create_lab(**overrides) -> dict:
    return get_success_data(api_client.create_lab(create_lab_payload(**overrides), ADMIN))


def create_technician(certifications=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_technician(create_technician_payload(certifications, **overrides), ADMIN)
    )


def append_certification(technician_id: str, method: str, level: int,
                         expires_at: str = CERT_FAR_EXPIRY) -> dict:
    return get_success_data(
        api_client.append_certification(
            technician_id, append_certification_payload(method, level, expires_at), ADMIN
        )
    )


def deactivate_technician(technician_id: str) -> dict:
    return get_success_data(api_client.deactivate_technician(technician_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: SSI revision lifecycle (draft -> submit -> approve, OCC-threaded)
# ---------------------------------------------------------------------------

def create_ssi_revision(project_id: str, scope_items, specified_fc_psi=DEFAULT_FC_PSI,
                        acceptance_method_concrete=None) -> dict:
    return get_success_data(
        api_client.create_ssi_revision(
            project_id,
            create_ssi_revision_payload(scope_items, specified_fc_psi, acceptance_method_concrete),
            PM,
        )
    )


def submit_revision(ssi_id: str) -> dict:
    return get_success_data(api_client.submit_ssi_revision(ssi_id, PM))


def approve_revision(ssi_id: str, project_id: str, decision="APPROVE") -> dict:
    """Engineer decision on a SUBMITTED revision. Re-reads the parent project so
    expected_project_version is always current (PRD §2.7 OCC guard)."""
    version = get_project(project_id)["version"]
    return get_success_data(
        api_client.approve_ssi_revision(
            ssi_id, approve_decision_payload(decision, version), ENGINEER
        )
    )


def get_revision(ssi_id: str) -> dict:
    return get_success_data(api_client.get_ssi_revision(ssi_id, PM))


def get_scope_items(ssi_id: str) -> list:
    """Scope items of a revision in creation order."""
    return get_success_data(api_client.list_scope_items(ssi_id, PM))


def setup_approved_project(scope_items, *, fc=DEFAULT_FC_PSI, acceptance=None,
                           project_overrides=None) -> dict:
    """Project + one revision walked to APPROVED.

    Returns {"project", "ssi", "scope_items"}: project is re-read after
    approval; scope_items is the creation-ordered list from the revision.
    """
    project = create_project(**(project_overrides or {}))
    ssi = create_ssi_revision(project["id"], scope_items, fc, acceptance)
    submit_revision(ssi["id"])
    approve_revision(ssi["id"], project["id"])
    return {
        "project": get_project(project["id"]),
        "ssi": get_revision(ssi["id"]),
        "scope_items": get_scope_items(ssi["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 2: assignments and field results
# ---------------------------------------------------------------------------

def create_assignment(project_id: str, scope_item_id: str, technician_id: str,
                      work_date=DEFAULT_WORK_DATE, start_time="09:00",
                      end_time="10:00") -> dict:
    return get_success_data(
        api_client.create_assignment(
            create_assignment_payload(
                project_id, scope_item_id, technician_id, work_date, start_time, end_time
            ),
            PM,
        )
    )


def get_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, PM))


def dispatch_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.dispatch_assignment(assignment_id, PM))


def cancel_assignment(assignment_id: str, requeue=None) -> dict:
    payload = {} if requeue is None else {"requeue": requeue}
    return get_success_data(api_client.cancel_assignment(assignment_id, payload, PM))


def complete_assignment(assignment_id: str, technician_id: str, note="done") -> dict:
    return get_success_data(
        api_client.complete_assignment(
            assignment_id, {"completion_note": note}, tech_headers(technician_id)
        )
    )


def setup_dispatched_assignment(*, item=None, work_date=DEFAULT_WORK_DATE,
                                start_time="09:00", end_time="10:00",
                                fc=DEFAULT_FC_PSI, acceptance=None,
                                cert_level=2, cert_expires=CERT_FAR_EXPIRY,
                                project_overrides=None) -> dict:
    """Approved single-item project + certified technician + one DISPATCHED
    assignment. The technician's certification method is derived from the
    scope item's test_method. Returns the project ctx plus "technician" and
    "assignment" (re-read after dispatch)."""
    item = item or soil_scope_item()
    ctx = setup_approved_project([item], fc=fc, acceptance=acceptance,
                                 project_overrides=project_overrides)
    tech = create_technician(certifications=[
        certification_entry(item["test_method"], level=cert_level, expires_at=cert_expires)
    ])
    asg = create_assignment(ctx["project"]["id"], ctx["scope_items"][0]["id"],
                            tech["id"], work_date, start_time, end_time)
    dispatch_assignment(asg["id"])
    return {**ctx, "technician": tech, "assignment": get_assignment(asg["id"])}


def record_soil_test(assignment_id: str, technician_id: str, density_pcf: float) -> dict:
    return get_success_data(
        api_client.create_field_test(
            create_field_test_payload(assignment_id, {"field_dry_density_pcf": density_pcf}),
            tech_headers(technician_id),
        )
    )


def record_weld_test(assignment_id: str, technician_id: str, defect_count: int) -> dict:
    return get_success_data(
        api_client.create_field_test(
            create_field_test_payload(assignment_id, {"defect_count": defect_count}),
            tech_headers(technician_id),
        )
    )


def record_bolt_test(assignment_id: str, technician_id: str, bolts_tested: int,
                     bolts_passed: int) -> dict:
    return get_success_data(
        api_client.create_field_test(
            create_field_test_payload(
                assignment_id, {"bolts_tested": bolts_tested, "bolts_passed": bolts_passed}
            ),
            tech_headers(technician_id),
        )
    )


def submit_daily_report(project_id: str, technician_id: str, report_date: str,
                        assignment_ids, summary="daily field report") -> dict:
    return get_success_data(
        api_client.create_daily_report(
            create_daily_report_payload(project_id, report_date, assignment_ids, summary),
            tech_headers(technician_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: laboratory sample chain (cast -> schedule -> break / discard)
# ---------------------------------------------------------------------------

def cast_sample(assignment_id: str, technician_id: str, lab_id: str,
                cast_at: str, age_days: int) -> dict:
    return get_success_data(
        api_client.create_lab_sample(
            create_lab_sample_payload(assignment_id, lab_id, cast_at, age_days),
            tech_headers(technician_id),
        )
    )


def schedule_sample_break(sample_id: str, break_scheduled_date: str) -> dict:
    return get_success_data(
        api_client.schedule_break(sample_id, schedule_break_payload(break_scheduled_date), LAB_ANALYST)
    )


def record_sample_break(sample_id: str, broken_at: str, strengths) -> dict:
    return get_success_data(
        api_client.record_break(sample_id, record_break_payload(broken_at, strengths), LAB_ANALYST)
    )


def discard_sample(sample_id: str) -> dict:
    return get_success_data(api_client.discard_lab_sample(sample_id, LAB_ANALYST))


def get_lab_sample(sample_id: str) -> dict:
    return get_success_data(api_client.get_lab_sample(sample_id, PM))


def setup_concrete_assignment(*, fc=DEFAULT_FC_PSI, acceptance=None,
                              required_count=3, work_date="2026-04-01",
                              lab_capacity=10, item_overrides=None,
                              project_overrides=None) -> dict:
    """Approved concrete-strength project + lab + certified technician + one
    DISPATCHED assignment. Returns the project ctx plus "lab", "technician",
    and "assignment"."""
    item = concrete_scope_item(required_count=required_count, **(item_overrides or {}))
    ctx = setup_approved_project([item], fc=fc, acceptance=acceptance,
                                 project_overrides=project_overrides)
    lab = create_lab(daily_break_capacity=lab_capacity)
    tech = create_technician(certifications=[
        certification_entry("CONCRETE_STRENGTH", level=2, expires_at=CERT_FAR_EXPIRY)
    ])
    asg = create_assignment(ctx["project"]["id"], ctx["scope_items"][0]["id"],
                            tech["id"], work_date, "08:00", "09:00")
    dispatch_assignment(asg["id"])
    return {**ctx, "lab": lab, "technician": tech, "assignment": get_assignment(asg["id"])}


# ---------------------------------------------------------------------------
# Tier 4: nonconformance chains
# ---------------------------------------------------------------------------

def list_project_ncrs(project_id: str, params=None) -> list:
    return get_success_data(api_client.list_project_ncrs(project_id, PM, params=params))


def submit_ncr_correction(ncr_id: str, note="correction submitted") -> dict:
    return get_success_data(
        api_client.submit_correction(ncr_id, submit_correction_payload(note), CONTRACTOR)
    )


def verify_ncr(ncr_id: str, technician_id: str, outcome: str,
               evidence_field_test_id=None) -> dict:
    return get_success_data(
        api_client.verify_ncr(
            ncr_id, verify_ncr_payload(outcome, evidence_field_test_id=evidence_field_test_id),
            tech_headers(technician_id),
        )
    )


def setup_open_soil_ncr(*, density=117.0, project_overrides=None) -> dict:
    """Dispatched soil assignment whose NONCONFORMING test auto-created one
    MAJOR NCR (performer t1). Adds a second certification-free technician as
    the eligible verifier. Returns the dispatch ctx plus "field_test", "ncr",
    and "verifier"."""
    ctx = setup_dispatched_assignment(project_overrides=project_overrides)
    ft = record_soil_test(ctx["assignment"]["id"], ctx["technician"]["id"], density)
    ncr = list_project_ncrs(ctx["project"]["id"])[0]
    verifier = create_technician()
    return {**ctx, "field_test": ft, "ncr": ncr, "verifier": verifier}


def setup_minor_ncr_twice_rejected() -> dict:
    """The escalation scenario: a 28-day sample broken 25 hours late (past the
    24-hour tolerance) with conforming strength, so exactly one MINOR
    out-of-tolerance NCR exists; two submit-correction / REJECTED cycles leave
    it OPEN with rejection_count 2. Clock is left at 2026-05-30T09:00:00Z (the
    detection instant). Returns the concrete ctx plus "sample", "ncr",
    "verifier"."""
    ctx = setup_concrete_assignment(fc=4000, required_count=1, work_date="2026-05-01")
    tech_id = ctx["technician"]["id"]
    sample = cast_sample(ctx["assignment"]["id"], tech_id, ctx["lab"]["id"],
                         "2026-05-01T08:00:00Z", 28)
    schedule_sample_break(sample["id"], "2026-05-29")
    set_clock("2026-05-30T09:00:00Z")
    record_sample_break(sample["id"], "2026-05-30T09:00:00Z", [5000])
    ncr = list_project_ncrs(ctx["project"]["id"])[0]
    verifier = create_technician()
    for note in ("fix attempt 1", "fix attempt 2"):
        submit_ncr_correction(ncr["id"], note)
        verify_ncr(ncr["id"], verifier["id"], "REJECTED")
    refreshed = [n for n in list_project_ncrs(ctx["project"]["id"]) if n["id"] == ncr["id"]][0]
    return {**ctx, "sample": sample, "ncr": refreshed, "verifier": verifier}


# ---------------------------------------------------------------------------
# Tier 5: letter readiness and the final compliance letter
# ---------------------------------------------------------------------------

def setup_ready_for_letter(*, project_overrides=None) -> dict:
    """Full chain to a READY_FOR_LETTER project: one soil scope item
    (required_count 1) satisfied by a conforming test, the assignment
    COMPLETED, and a daily report covering it. Returns the dispatch ctx plus
    "field_test" and "daily_report"."""
    ctx = setup_dispatched_assignment(project_overrides=project_overrides)
    tech_id = ctx["technician"]["id"]
    ft = record_soil_test(ctx["assignment"]["id"], tech_id, 118.0)
    complete_assignment(ctx["assignment"]["id"], tech_id)
    report = submit_daily_report(ctx["project"]["id"], tech_id,
                                 ctx["assignment"]["work_date"],
                                 [ctx["assignment"]["id"]])
    return {**ctx, "field_test": ft, "daily_report": report}


def issue_letter(project_id: str) -> dict:
    return get_success_data(api_client.issue_letter(project_id, PM))


def void_letter(project_id: str, reason: str) -> dict:
    return get_success_data(api_client.void_letter(project_id, void_letter_payload(reason),
                                                   BUILDING_OFFICIAL))


# ---------------------------------------------------------------------------
# Discrepancy tickets
# ---------------------------------------------------------------------------

def raise_discrepancy(project_id: str, technician_id: str, routed_to="CONTRACTOR",
                      subject="embed plate mismatch",
                      description="drawings show 4 studs, field has 3",
                      scope_item_id=None) -> dict:
    return get_success_data(
        api_client.create_discrepancy(
            create_discrepancy_payload(project_id, subject, description, routed_to, scope_item_id),
            tech_headers(technician_id),
        )
    )


def respond_to_discrepancy(ticket_id: str, response_text: str, headers) -> dict:
    return get_success_data(
        api_client.respond_discrepancy(ticket_id, respond_discrepancy_payload(response_text), headers)
    )
