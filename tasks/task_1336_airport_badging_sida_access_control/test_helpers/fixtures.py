"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a fresh server/database). Helpers use the
lenient get_success_data() validator so a setup failure surfaces as a clear
"Setup failed" error naming the step, not a confusing assertion failure.

Identity threading: SponsorSignatory calls are always made with
make_sponsor_signatory_headers(sponsor_id) — never the shared constant —
because applicant/application creation and withdrawal are ownership-gated.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import REQUIRED_COURSES
from .factories import (
    create_applicant_payload,
    create_application_payload,
    create_audit_cycle_payload,
    create_sponsor_payload,
    create_violation_payload,
    grant_escort_privilege_payload,
    issue_badge_payload,
    record_chrc_payload,
    record_sta_payload,
    replace_badge_payload,
    set_clock_payload,
    training_completion_payload,
)
from .test_users import (
    TEST_USERS,
    make_badging_officer_headers,
    make_security_manager_headers,
    make_sponsor_signatory_headers,
)

# Role aliases for opaque roles (canonical shared constants).
BO = TEST_USERS["badging_officer_headers"]
SM = TEST_USERS["security_manager_headers"]
AUD = TEST_USERS["auditor_headers"]
ACS = TEST_USERS["access_control_headers"]


def _ok(step, resp):
    data = get_success_data(resp)
    if not isinstance(data, dict) or resp.status_code >= 400:
        raise AssertionError(
            f"Setup failed at {step}: HTTP {resp.status_code} -> {resp.text[:400]}")
    return data


# --- Tier 1/2: sponsors, applicants, applications ----------------------------

def create_sponsor(name="AeroFuel", sponsor_code="AF", active_badge_quota=5):
    """Register an ACTIVE sponsor. Returns the sponsor dict."""
    resp = api_client.create_sponsor(
        create_sponsor_payload(name=name, sponsor_code=sponsor_code,
                               active_badge_quota=active_badge_quota),
        SM,
    )
    return _ok("create_sponsor", resp)


def create_applicant(sponsor_id, full_name="Ana Rios", date_of_birth="1990-01-01",
                     government_id_number="G1001"):
    """Register an applicant under `sponsor_id` (ownership-gated)."""
    resp = api_client.create_applicant(
        create_applicant_payload(
            sponsor_id, full_name=full_name, date_of_birth=date_of_birth,
            government_id_number=government_id_number),
        make_sponsor_signatory_headers(sponsor_id),
    )
    return _ok("create_applicant", resp)


def open_application(applicant_id, sponsor_id, badge_class="STERILE"):
    """Open a SUBMITTED application for `applicant_id` (ownership-gated)."""
    resp = api_client.create_application(
        create_application_payload(applicant_id, badge_class=badge_class),
        make_sponsor_signatory_headers(sponsor_id),
    )
    return _ok("open_application", resp)


def record_chrc_pass(application_id, fingerprint_submitted_at="2026-08-01T00:00:00Z"):
    """Record a CHRC PASS; the application moves to STA_PENDING."""
    resp = api_client.record_chrc(
        application_id,
        record_chrc_payload("PASS",
                            fingerprint_submitted_at=fingerprint_submitted_at),
        BO,
    )
    return _ok("record_chrc_pass", resp)


def record_chrc_fail(application_id, fingerprint_submitted_at="2026-08-01T00:00:00Z"):
    """Record a CHRC FAIL; the application terminates DENIED (CHRC_FAILED)."""
    resp = api_client.record_chrc(
        application_id,
        record_chrc_payload("FAIL",
                            fingerprint_submitted_at=fingerprint_submitted_at),
        BO,
    )
    return _ok("record_chrc_fail", resp)


def record_sta_cleared(application_id):
    """Record STA CLEARED; the application moves toward READY."""
    resp = api_client.record_sta_result(application_id, record_sta_payload("CLEARED"), BO)
    return _ok("record_sta_cleared", resp)


def record_training(applicant_id, course_code, completed_at="2026-06-01T00:00:00Z"):
    """Record a training completion; expires_at is server-computed."""
    resp = api_client.create_training_completion(
        training_completion_payload(applicant_id, course_code,
                                    completed_at=completed_at),
        BO,
    )
    return _ok("record_training", resp)


def record_required_trainings(applicant_id, badge_class,
                              completed_at="2026-06-01T00:00:00Z"):
    """Record one completion for every course the badge class requires."""
    return [
        record_training(applicant_id, course, completed_at=completed_at)
        for course in REQUIRED_COURSES[badge_class]
    ]


def issue_badge(application_id, badge_number):
    """Issue a badge for a READY application. Returns the Badge dict."""
    resp = api_client.issue_badge(application_id, issue_badge_payload(badge_number), BO)
    return _ok("issue_badge", resp)


def set_clock(to_iso8601, headers=None):
    """Advance the logical clock; sweeps all time-driven transitions."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), headers or BO)
    return _ok("set_clock", resp)


def get_application(application_id):
    resp = api_client.get_application(application_id, BO)
    return _ok("get_application", resp)


def get_badge(badge_id):
    resp = api_client.get_badge(badge_id, BO)
    return _ok("get_badge", resp)


def get_sponsor(sponsor_id):
    resp = api_client.get_sponsor(sponsor_id, SM)
    return _ok("get_sponsor", resp)


# --- Tier 3: full issuance pipeline -------------------------------------------

def setup_ready_application(sponsor_id, applicant_id, badge_class="STERILE",
                            completed_at="2026-06-01T00:00:00Z",
                            fingerprint_submitted_at="2026-08-01T00:00:00Z"):
    """Open an application, CHRC PASS, STA CLEARED, then record every required
    course. STA is recorded BEFORE training so the application provably rests
    at PENDING_REQUIREMENTS until the coursework lands.

    Returns (application_dict_after_training, [completion_dicts]).
    """
    app = open_application(applicant_id, sponsor_id, badge_class=badge_class)
    record_chrc_pass(app["id"], fingerprint_submitted_at=fingerprint_submitted_at)
    record_sta_cleared(app["id"])
    completions = record_required_trainings(applicant_id, badge_class,
                                            completed_at=completed_at)
    return get_application(app["id"]), completions


def setup_issued_badge(sponsor_code="AF", sponsor_name="AeroFuel", quota=5,
                       full_name="Ana Rios", date_of_birth="1990-01-01",
                       government_id_number="G1001", badge_class="STERILE",
                       completed_at="2026-06-01T00:00:00Z", badge_number="B100"):
    """Sponsor -> applicant -> READY application -> issued ACTIVE badge.

    Returns a dict with keys: sponsor, applicant, application, badge,
    completions.
    """
    sponsor = create_sponsor(name=sponsor_name, sponsor_code=sponsor_code,
                             active_badge_quota=quota)
    applicant = create_applicant(sponsor["id"], full_name=full_name,
                                 date_of_birth=date_of_birth,
                                 government_id_number=government_id_number)
    app, completions = setup_ready_application(
        sponsor["id"], applicant["id"], badge_class=badge_class,
        completed_at=completed_at)
    badge = issue_badge(app["id"], badge_number)
    return {
        "sponsor": sponsor,
        "applicant": applicant,
        "application": app,
        "badge": badge,
        "completions": completions,
    }


def add_applicant_with_ready_application(sponsor, full_name, government_id_number,
                                         badge_class="STERILE",
                                         completed_at="2026-06-01T00:00:00Z",
                                         date_of_birth="1990-01-01",
                                         fingerprint_submitted_at="2026-08-01T00:00:00Z"):
    """Add another applicant + READY application under an existing sponsor."""
    applicant = create_applicant(sponsor["id"], full_name=full_name,
                                 date_of_birth=date_of_birth,
                                 government_id_number=government_id_number)
    app, completions = setup_ready_application(
        sponsor["id"], applicant["id"], badge_class=badge_class,
        completed_at=completed_at,
        fingerprint_submitted_at=fingerprint_submitted_at)
    return {"applicant": applicant, "application": app, "completions": completions}


# --- Tier 3: badge lifecycle shortcuts -----------------------------------------

def suspend_badge(badge_id, manager_id="mgr-1", reason="investigation"):
    """Manually suspend an ACTIVE badge as the given SecurityManager."""
    resp = api_client.suspend_badge(badge_id, {"reason": reason},
                                    make_security_manager_headers(manager_id))
    return _ok("suspend_badge", resp)


def grant_escort_privilege(badge_id, expected_badge_version, max_escortees=3,
                           manager_id="mgr-1"):
    """Grant an escort privilege on an ACTIVE badge (OCC-guarded)."""
    resp = api_client.grant_escort_privilege(
        badge_id,
        grant_escort_privilege_payload(max_escortees, expected_badge_version),
        make_security_manager_headers(manager_id),
    )
    return _ok("grant_escort_privilege", resp)


def report_lost(badge_id, sponsor_id=None, report_type="LOST"):
    """Report a badge lost/stolen — by the owning signatory when sponsor_id is
    given, otherwise by a BadgingOfficer."""
    if sponsor_id is not None:
        headers = make_sponsor_signatory_headers(sponsor_id)
    else:
        headers = BO
    resp = api_client.report_lost(badge_id, {"report_type": report_type}, headers)
    return _ok("report_lost", resp)


def revoke_badge(badge_id, reason="terminated", manager_id="mgr-1"):
    resp = api_client.revoke_badge(badge_id, {"reason": reason},
                                   make_security_manager_headers(manager_id))
    return _ok("revoke_badge", resp)


def mark_returned(badge_id):
    resp = api_client.mark_returned(badge_id, BO)
    return _ok("mark_returned", resp)


def replace_badge(badge_id, badge_number):
    resp = api_client.replace_badge(badge_id, replace_badge_payload(badge_number), BO)
    return _ok("replace_badge", resp)


# --- Tier 4: violation accumulation --------------------------------------------

def record_violation(badge_id, violation_type, occurred_at="2026-08-02T00:00:00Z",
                     officer_id="off-1"):
    resp = api_client.create_violation(
        create_violation_payload(badge_id, violation_type, occurred_at=occurred_at),
        make_badging_officer_headers(officer_id),
    )
    return _ok("record_violation", resp)


def sustain_violation(violation_id, manager_id="mgr-1"):
    resp = api_client.sustain_violation(violation_id,
                                        make_security_manager_headers(manager_id))
    return _ok("sustain_violation", resp)


def dismiss_violation(violation_id, manager_id="mgr-2"):
    resp = api_client.dismiss_violation(violation_id,
                                        make_security_manager_headers(manager_id))
    return _ok("dismiss_violation", resp)


# --- Tier 5: audit cycles -------------------------------------------------------

def open_audit_cycle(window_start, window_end):
    resp = api_client.create_audit_cycle(
        create_audit_cycle_payload(window_start, window_end), AUD)
    return _ok("open_audit_cycle", resp)


def get_audit_cycle(audit_cycle_id):
    resp = api_client.get_audit_cycle(audit_cycle_id, AUD)
    return _ok("get_audit_cycle", resp)


def close_audit_cycle(audit_cycle_id):
    resp = api_client.close_audit_cycle(audit_cycle_id, AUD)
    return _ok("close_audit_cycle", resp)
