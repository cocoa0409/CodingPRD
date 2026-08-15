"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch via the public API —
the test harness restarts the server before every test, so no state carries
over. Fixtures use get_success_data() so setup failures surface as clear
"Setup failed" errors rather than assertion failures deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .factories import (
    create_assignment_payload,
    create_attest_payload,
    create_blackout_payload,
    create_complete_payload,
    create_content_payload,
    create_enrollment_payload,
    create_license_payload,
    create_needs_analysis_payload,
    create_plan_payload,
    create_product_payload,
    create_reject_payload,
    create_representative_payload,
    create_session_payload,
    create_void_payload,
)
from .test_users import TEST_USERS, make_rep_headers

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_DEFAULT):
    """Set the server logical clock (PRD §2.4). Returns response data."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, OFFICER))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation & state progression
# ---------------------------------------------------------------------------

def create_rep(**overrides):
    """Create an ACTIVE representative. Returns the Representative dict."""
    return get_success_data(
        api_client.create_representative(create_representative_payload(**overrides), ADMIN))


def create_draft_content(author_headers=None, **overrides):
    """Create content in DRAFT. author_headers pins author_user_id (SoD anchor)."""
    return get_success_data(
        api_client.create_content(
            create_content_payload(**overrides), author_headers or ADMIN))


def create_approved_content(author_headers=None, **overrides):
    """Create content and walk DRAFT -> PENDING_APPROVAL -> APPROVED.

    The approver is always a ComplianceOfficer distinct from the author.
    Returns the APPROVED TrainingContent dict.
    """
    author_headers = author_headers or ADMIN
    content = create_draft_content(author_headers=author_headers, **overrides)
    get_success_data(api_client.submit_content(content["id"], author_headers))
    return get_success_data(api_client.approve_content(content["id"], OFFICER))


def create_session_for_content(content_id, **overrides):
    """Schedule a SCHEDULED session for APPROVED content. Returns CourseSession."""
    return get_success_data(
        api_client.create_session(create_session_payload(content_id, **overrides), ADMIN))


def create_enrollment(rep_id, content_id=None, session_id=None):
    """Create an ENROLLED enrollment. Exactly one of content_id/session_id."""
    payload = create_enrollment_payload(rep_id)
    if content_id is not None:
        payload["content_id"] = content_id
    if session_id is not None:
        payload["session_id"] = session_id
    return get_success_data(api_client.create_enrollment(payload, ADMIN))


def start_enrollment(enrollment_id, rep_id):
    """RegisteredRep starts own enrollment (ownership-gated)."""
    return get_success_data(
        api_client.start_enrollment(enrollment_id, make_rep_headers(rep_id)))


def complete_enrollment(enrollment_id, rep_id, score=90):
    """RegisteredRep completes own enrollment with a score."""
    return get_success_data(
        api_client.complete_enrollment(
            enrollment_id, create_complete_payload(score), make_rep_headers(rep_id)))


def create_assignment(rep_id, **overrides):
    """Create an ASSIGNED regulatory assignment. Returns the assignment."""
    return get_success_data(
        api_client.create_regulatory_assignment(
            create_assignment_payload(rep_id, **overrides), ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchies
# ---------------------------------------------------------------------------

def create_plan(rep_id, expected_representative_version, **overrides):
    """Create a NEEDS_ANALYSIS plan (OCC on Representative.version)."""
    return get_success_data(
        api_client.create_firm_element_plan(
            create_plan_payload(rep_id, expected_representative_version, **overrides),
            ADMIN))


def create_plan_with_needs_analysis(rep_id, expected_representative_version,
                                    **overrides):
    """Create plan + record needs analysis. Returns the plan dict."""
    plan = create_plan(rep_id, expected_representative_version, **overrides)
    return get_success_data(
        api_client.record_needs_analysis(
            plan["id"], create_needs_analysis_payload(), ADMIN))


def create_published_plan(rep_id, expected_representative_version, **overrides):
    """Create plan -> needs analysis -> publish. Returns the published plan."""
    plan = create_plan_with_needs_analysis(
        rep_id, expected_representative_version, **overrides)
    return get_success_data(api_client.publish_plan(plan["id"], ADMIN))


def setup_rep_with_published_plan(plan_year=2026, rep_overrides=None):
    """ACTIVE rep + published plan for plan_year. Returns (rep, plan)."""
    rep = create_rep(**(rep_overrides or {}))
    plan = create_published_plan(rep["id"], rep["version"], plan_year=plan_year)
    return rep, plan


def get_pending_attestation(plan_id):
    """Fetch the single PENDING attestation created by plan publish."""
    data, _meta = _list_attestations(plan_id)
    assert len(data) == 1, f"expected exactly one attestation for plan, got {len(data)}"
    return data[0]


def _list_attestations(plan_id):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(
        api_client.list_attestations(ADMIN, params={"plan_id": plan_id}))


def setup_closed_plan_with_attestation(plan_year=2026, rep_overrides=None,
                                       content_hours=13.0):
    """Full firm-element lifecycle: rep -> published plan -> FE completion ->
    close -> attestation ATTESTED by the rep.

    Returns (rep, plan, attestation, enrollment, content).
    Default: RR rep, excess 0 -> required_hours 12; one 13.0h course closes it.
    """
    rep, plan = setup_rep_with_published_plan(
        plan_year=plan_year, rep_overrides=rep_overrides)
    content = create_approved_content(
        ce_category="FIRM_ELEMENT", credit_hours=content_hours)
    attestation = get_pending_attestation(plan["id"])
    enrollment = create_enrollment(rep["id"], content_id=content["id"])
    start_enrollment(enrollment["id"], rep["id"])
    complete_enrollment(enrollment["id"], rep["id"], score=95)
    get_success_data(api_client.close_plan(plan["id"], ADMIN))
    get_success_data(
        api_client.attest(
            attestation["id"], create_attest_payload(), make_rep_headers(rep["id"])))
    return rep, plan, attestation, enrollment, content


def setup_launched_product(content_overrides=None, product_overrides=None):
    """APPROVED PRODUCT content + launched ProductOffering. Returns (content, product)."""
    content = create_approved_content(
        ce_category="PRODUCT", **(content_overrides or {}))
    product = get_success_data(
        api_client.create_product(
            create_product_payload(content["id"], **(product_overrides or {})),
            OFFICER))
    product = get_success_data(api_client.launch_product(product["id"], OFFICER))
    return content, product


def get_certification_for(rep_id, product_id):
    """Fetch the single certification row for (rep, product) via the list endpoint."""
    from prd_bench_local_runner.testing import validate_paginated
    data, _meta = validate_paginated(
        api_client.list_product_certifications(
            OFFICER, params={"rep_id": rep_id, "product_id": product_id}))
    assert len(data) >= 1, f"no certification found for rep {rep_id} / product {product_id}"
    return data[0]


def setup_certified_rep(product_overrides=None, content_overrides=None):
    """ACTIVE rep holding a CERTIFIED product certification.

    Returns (rep, content, product, certification, enrollment).
    """
    rep = create_rep()
    content, product = setup_launched_product(
        content_overrides=content_overrides, product_overrides=product_overrides)
    enrollment = create_enrollment(rep["id"], content_id=content["id"])
    start_enrollment(enrollment["id"], rep["id"])
    complete_enrollment(enrollment["id"], rep["id"], score=90)
    cert = get_certification_for(rep["id"], product["id"])
    assert cert["cert_status"] == "CERTIFIED", (
        f"Setup failed: cert status {cert['cert_status']!r}, expected CERTIFIED")
    return rep, content, product, cert, enrollment


# ---------------------------------------------------------------------------
# Tier 3: lapse / sweep scenarios
# ---------------------------------------------------------------------------

def setup_lapsed_rep(past_lapse_clock="2026-12-30T00:00:00Z", cycle_year=2026):
    """Rep with an open assignment created at the default clock, then clock
    advanced past lapse_after and the sweep run: assignment LAPSED, rep
    INACTIVE_CE. Returns (rep, assignment).
    """
    set_clock(CLOCK_DEFAULT)
    rep = create_rep()
    assignment = create_assignment(rep["id"], cycle_year=cycle_year)
    set_clock(past_lapse_clock)
    get_success_data(api_client.run_enforcement_sweep(OFFICER))
    return rep, assignment


def setup_lapsed_rep_with_certified_product(past_lapse_clock="2026-12-30T00:00:00Z"):
    """Rep holding a CERTIFIED product certification, then lapsed by sweep:
    assignment LAPSED, rep INACTIVE_CE, cert SUSPENDED (REGISTRATION_INACTIVE).
    Returns (rep, content, product, cert, assignment).
    """
    set_clock(CLOCK_DEFAULT)
    rep, content, product, cert, _enr = setup_certified_rep()
    assignment = create_assignment(rep["id"])
    set_clock(past_lapse_clock)
    get_success_data(api_client.run_enforcement_sweep(OFFICER))
    return rep, content, product, cert, assignment


# ---------------------------------------------------------------------------
# Tier 4: state CE licenses
# ---------------------------------------------------------------------------

def create_license(rep_id, **overrides):
    """Create an ACTIVE state CE license. Returns the license dict."""
    return get_success_data(
        api_client.create_state_ce_license(create_license_payload(rep_id, **overrides), ADMIN))


def create_blackout(**overrides):
    """Declare a blackout window. Returns the window dict."""
    return get_success_data(
        api_client.create_blackout_window(create_blackout_payload(**overrides), OFFICER))


def complete_state_insurance_course(rep, license_id=None, credit_hours=4.0,
                                    score=90, code=None):
    """Create APPROVED STATE_INSURANCE content and complete an enrollment in it
    for the rep. Returns (content, enrollment). The license's counters recompute
    as a completion side effect (PRD §3.8).
    """
    overrides = {"ce_category": "STATE_INSURANCE", "credit_hours": credit_hours}
    if code:
        overrides["code"] = code
    content = create_approved_content(**overrides)
    enrollment = create_enrollment(rep["id"], content_id=content["id"])
    start_enrollment(enrollment["id"], rep["id"])
    complete_enrollment(enrollment["id"], rep["id"], score=score)
    return content, enrollment


# ---------------------------------------------------------------------------
# Tier 5: misc composites
# ---------------------------------------------------------------------------

def create_instructor_led_setup(capacity=10, room_name=None, **session_overrides):
    """INSTRUCTOR_LED APPROVED content + SCHEDULED session.
    Returns (content, session).
    """
    content = create_approved_content(delivery_format="INSTRUCTOR_LED",
                                      credit_hours=2.0)
    kwargs = dict(session_overrides)
    if room_name is not None:
        kwargs["room_name"] = room_name
    kwargs["capacity"] = capacity
    session = create_session_for_content(content["id"], **kwargs)
    return content, session


def void_enrollment(enrollment_id, **overrides):
    """ComplianceOfficer voids a COMPLETED enrollment (justification >= 10 chars)."""
    return get_success_data(
        api_client.void_enrollment(enrollment_id, create_void_payload(**overrides),
                                   OFFICER))


def reject_content(content_id, officer_headers=None, **overrides):
    """ComplianceOfficer rejects PENDING_APPROVAL content with a reason."""
    return get_success_data(
        api_client.reject_content(content_id, create_reject_payload(**overrides),
                                  officer_headers or OFFICER))
