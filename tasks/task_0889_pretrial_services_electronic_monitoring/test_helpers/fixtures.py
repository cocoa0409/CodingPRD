"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"setup failed" errors rather than confusing assertion failures. Every helper builds
its preconditions from scratch — the server starts against an empty database before
each test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_defendant_payload, create_assessment_payload, create_release_order_payload,
    create_em_device_payload, create_em_enrollment_payload, create_curfew_window_payload,
    create_testing_site_payload, create_drug_test_payload,
)
from .test_users import (
    TEST_USERS, make_intake_headers, make_judicial_headers, make_supervising_headers,
)

INTAKE = TEST_USERS["intake_headers"]
SUPERVISING = TEST_USERS["supervising_headers"]
JUDICIAL = TEST_USERS["judicial_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server logical clock (ProgramAdmin-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: single-entity creation ────────────────────────────────────────

def create_defendant(**overrides) -> dict:
    """Create a PRETRIAL_PENDING defendant."""
    return get_success_data(
        api_client.create_defendant(create_defendant_payload(**overrides), INTAKE))


def create_device(total_units: int = 1, **overrides) -> dict:
    return get_success_data(
        api_client.create_em_device(
            create_em_device_payload(total_units=total_units, **overrides), ADMIN))


def create_site(slot_capacity: int = 5, **overrides) -> dict:
    return get_success_data(
        api_client.create_testing_site(
            create_testing_site_payload(slot_capacity=slot_capacity, **overrides), ADMIN))


# ─── Tier 2: assessment lifecycle ───────────────────────────────────────────

def create_draft_assessment(defendant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_assessment(
            create_assessment_payload(defendant_id, **overrides), INTAKE))


def create_submitted_assessment(defendant_id: str, submitter_id: str = "u_intake",
                                **overrides) -> dict:
    """DRAFT -> SUBMITTED, submitted by `submitter_id`. Returns the SUBMITTED assessment."""
    a = create_draft_assessment(defendant_id, **overrides)
    return get_success_data(
        api_client.transition_assessment(a["id"], "SUBMITTED",
                                        make_intake_headers(submitter_id)))


def create_approved_assessment(defendant_id: str, submitter_id: str = "u_intake",
                               approver_id: str = "u_judge", **overrides) -> dict:
    """DRAFT -> SUBMITTED -> APPROVED (distinct actors). Returns the APPROVED assessment."""
    a = create_submitted_assessment(defendant_id, submitter_id=submitter_id, **overrides)
    return get_success_data(
        api_client.transition_assessment(a["id"], "APPROVED",
                                        make_judicial_headers(approver_id)))


# ─── Tier 3: release + activation ───────────────────────────────────────────

def activate_defendant(ordered_conditions=None, decision: str = "RELEASE",
                       assessment_overrides=None, defendant_overrides=None) -> dict:
    """Create a defendant, approve an assessment, propose + order a RELEASE order.

    Returns {"defendant": <fresh, ACTIVE>, "assessment", "release_order"}.
    """
    if ordered_conditions is None:
        ordered_conditions = ["CHECK_IN"]
    defendant = create_defendant(**(defendant_overrides or {}))
    assessment = create_approved_assessment(defendant["id"], **(assessment_overrides or {}))
    order = get_success_data(api_client.create_release_order(
        create_release_order_payload(defendant["id"], assessment["id"],
                                     decision=decision,
                                     ordered_conditions=ordered_conditions), JUDICIAL))
    order = get_success_data(
        api_client.transition_release_order(order["id"], "ORDERED", JUDICIAL))
    fresh = get_success_data(api_client.get_defendant(defendant["id"], JUDICIAL))
    return {"defendant": fresh, "assessment": assessment, "release_order": order}


def create_pending_enrollment(defendant_id: str, device_id: str) -> dict:
    return get_success_data(
        api_client.create_em_enrollment(
            create_em_enrollment_payload(defendant_id, device_id), SUPERVISING))


def setup_active_enrollment(ordered_conditions=None, total_units: int = 1) -> dict:
    """Active, GPS-ordered defendant + device pool + ACTIVE enrollment.

    Returns {"defendant", "device" (fresh), "enrollment" (fresh, ACTIVE)}.
    """
    if ordered_conditions is None:
        ordered_conditions = ["GPS_MONITORING"]
    ctx = activate_defendant(ordered_conditions=ordered_conditions)
    device = create_device(total_units=total_units)
    enrollment = create_pending_enrollment(ctx["defendant"]["id"], device["id"])
    get_success_data(
        api_client.transition_em_enrollment(enrollment["id"], "ACTIVE", SUPERVISING))
    fresh_enr = get_success_data(api_client.get_em_enrollment(enrollment["id"], SUPERVISING))
    fresh_dev = get_success_data(api_client.get_em_device(device["id"], SUPERVISING))
    return {"defendant": ctx["defendant"], "device": fresh_dev, "enrollment": fresh_enr}


def add_curfew_window(enrollment_id: str, day_of_week: int, start_minute: int,
                      end_minute: int) -> dict:
    """Fetch the enrollment's current version, then add a curfew window (OCC-guarded)."""
    enr = get_success_data(api_client.get_em_enrollment(enrollment_id, SUPERVISING))
    return get_success_data(api_client.create_curfew_window(
        enrollment_id,
        create_curfew_window_payload(enr["version"], day_of_week, start_minute, end_minute),
        SUPERVISING))


def setup_enrollment_with_curfew(day_of_week: int = 0, start_minute: int = 1200,
                                 end_minute: int = 1320) -> dict:
    """Active enrollment carrying a single curfew window. Returns the setup_active_enrollment
    dict plus {"curfew_window"}."""
    ctx = setup_active_enrollment(ordered_conditions=["GPS_MONITORING", "CURFEW"])
    window = add_curfew_window(ctx["enrollment"]["id"], day_of_week, start_minute, end_minute)
    ctx["curfew_window"] = window
    return ctx


# ─── Tier 4: drug tests ─────────────────────────────────────────────────────

def setup_drug_testing_defendant(slot_capacity: int = 5) -> dict:
    """Active defendant with DRUG_TESTING ordered + a testing site.

    Returns {"defendant", "site"}.
    """
    ctx = activate_defendant(ordered_conditions=["DRUG_TESTING"])
    site = create_site(slot_capacity=slot_capacity)
    return {"defendant": ctx["defendant"], "site": site}


def schedule_drug_test(defendant_id: str, site_id: str,
                       slot_start: str = "2026-06-05T10:00:00Z", **overrides) -> dict:
    return get_success_data(api_client.create_drug_test(
        create_drug_test_payload(defendant_id, site_id, slot_start=slot_start, **overrides),
        SUPERVISING))


# ─── Tier 5: violations ─────────────────────────────────────────────────────

def create_reported_violation(defendant_id: str, violation_type: str = "OTHER",
                              severity: str = "MODERATE",
                              reporter_id: str = "u_sup") -> dict:
    """File a violation in REPORTED status, reported by `reporter_id`."""
    from .factories import create_violation_payload
    return get_success_data(api_client.create_violation(
        create_violation_payload(defendant_id, violation_type, severity),
        make_supervising_headers(reporter_id)))


def create_under_review_violation(defendant_id: str, violation_type: str = "OTHER",
                                  severity: str = "MODERATE", reporter_id: str = "u_sup",
                                  reviewer_id: str = "u_judge") -> dict:
    """File a violation and move it REPORTED -> UNDER_REVIEW. Returns the UNDER_REVIEW row."""
    v = create_reported_violation(defendant_id, violation_type, severity, reporter_id)
    return get_success_data(api_client.transition_violation(
        v["id"], "UNDER_REVIEW", make_judicial_headers(reviewer_id)))
