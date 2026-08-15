"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so every test
starts against an empty database). Setup calls use the lenient validator so
failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_APPLICANT_ID
from .factories import (
    approve_cycle_payload,
    create_assignment_payload,
    create_comment_payload,
    create_cycle_payload,
    create_deferred_payload,
    create_engagement_payload,
    create_jurisdiction_payload,
    create_response_payload,
    create_reviewer_payload,
    make_license,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_chief_reviewer_headers,
    make_reviewer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# --- Single-entity creation -------------------------------------------------

def make_jurisdiction(**overrides) -> dict:
    """Register a jurisdiction. Returns the created jurisdiction."""
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), ADMIN))


def make_reviewer(name="Test Reviewer", state_code="CA", license_type="PE",
                  expires_on="2030-01-01", extra_licenses=None,
                  max_concurrent_assignments=None, **overrides) -> dict:
    """Register a reviewer holding a license for the given state."""
    licenses = [make_license(state_code, license_type, expires_on=expires_on)]
    if extra_licenses:
        licenses.extend(extra_licenses)
    payload = create_reviewer_payload(full_name=name, licenses=licenses, **overrides)
    if max_concurrent_assignments is not None:
        payload["max_concurrent_assignments"] = max_concurrent_assignments
    return get_success_data(api_client.create_reviewer(payload, ADMIN))


def make_engagement(jurisdiction, reviewer, applicant_id=DEFAULT_APPLICANT_ID,
                    **overrides) -> dict:
    """Register an engagement governed by the jurisdiction with the given
    reviewer of record. Returns the created engagement."""
    payload = create_engagement_payload(
        jurisdiction["id"], reviewer["id"], applicant_contact_id=applicant_id,
        **overrides)
    return get_success_data(api_client.create_engagement(payload, COORDINATOR))


def set_clock(to_iso8601: str) -> dict:
    """Advance the server's logical clock (PRD §2.8)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# --- Cycle / assignment -----------------------------------------------------

def open_cycle(engagement_id, documents_ref="s3://plan-set", as_applicant=False,
               applicant_id=DEFAULT_APPLICANT_ID) -> dict:
    """Open a review cycle on the engagement (PRD §3.3). Returns the cycle."""
    headers = (make_applicant_headers(applicant_id) if as_applicant
               else COORDINATOR)
    return get_success_data(api_client.create_cycle(
        create_cycle_payload(engagement_id, documents_ref=documents_ref), headers))


def assign_cycle(cycle, reviewer_id) -> dict:
    """Assign a reviewer to the cycle, threading the cycle's current version
    into the OCC field expected_cycle_version (PRD §2.9). Returns the
    created assignment."""
    payload = create_assignment_payload(cycle["id"], reviewer_id, cycle["version"])
    return get_success_data(api_client.create_assignment(payload, COORDINATOR))


def get_cycle(cycle_id) -> dict:
    return get_success_data(api_client.get_cycle(cycle_id, COORDINATOR))


def get_engagement(engagement_id) -> dict:
    return get_success_data(api_client.get_engagement(engagement_id, COORDINATOR))


def get_reviewer(reviewer_id) -> dict:
    return get_success_data(api_client.get_reviewer(reviewer_id, COORDINATOR))


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, COORDINATOR))


def get_comment(comment_id) -> dict:
    return get_success_data(api_client.get_comment(comment_id, COORDINATOR))


def get_deferred(deferred_id) -> dict:
    return get_success_data(api_client.get_deferred(deferred_id, COORDINATOR))


def get_record_for_engagement(engagement_id) -> dict:
    """Fetch the engagement's review record (at most one per engagement)."""
    rows = get_success_data(
        api_client.list_records(COORDINATOR, params={"engagement_id": engagement_id}))
    assert isinstance(rows, list) and len(rows) == 1, (
        f"Setup failed: expected exactly one record for engagement {engagement_id}, "
        f"got {rows}")
    return rows[0]


# --- Comments ---------------------------------------------------------------

def raise_comment(cycle_id, reviewer_id, **overrides) -> dict:
    """Assigned reviewer raises a deficiency comment on an IN_REVIEW cycle."""
    return get_success_data(api_client.create_comment(
        create_comment_payload(cycle_id, **overrides),
        make_reviewer_headers(reviewer_id)))


def issue_comments(cycle_id, reviewer_id) -> dict:
    return get_success_data(
        api_client.issue_comments(cycle_id, make_reviewer_headers(reviewer_id)))


def respond_to_comment(comment_id, applicant_id=DEFAULT_APPLICANT_ID,
                       response_text="Addressed in the attached revision") -> dict:
    return get_success_data(api_client.create_response(
        comment_id, create_response_payload(response_text=response_text),
        make_applicant_headers(applicant_id)))


def approve_cycle(cycle_id, reviewer_id) -> dict:
    return get_success_data(api_client.approve_cycle(
        cycle_id, approve_cycle_payload(), make_reviewer_headers(reviewer_id)))


# --- Deferred submittals ----------------------------------------------------

def register_deferred(engagement_id, applicant_id=DEFAULT_APPLICANT_ID,
                      **overrides) -> dict:
    return get_success_data(api_client.create_deferred(
        create_deferred_payload(engagement_id, **overrides),
        make_applicant_headers(applicant_id)))


def submit_deferred(deferred_id, documents_ref="s3://deferred-docs",
                    applicant_id=DEFAULT_APPLICANT_ID) -> dict:
    return get_success_data(api_client.submit_deferred(
        deferred_id, {"documents_ref": documents_ref},
        make_applicant_headers(applicant_id)))


def approve_deferred(deferred_id, reviewer_id) -> dict:
    return get_success_data(
        api_client.approve_deferred(deferred_id, make_reviewer_headers(reviewer_id)))


# --- Composite scenario builders --------------------------------------------

def setup_registered_engagement(jur_overrides=None, eng_overrides=None,
                                rev_overrides=None, applicant_id=DEFAULT_APPLICANT_ID):
    """Jurisdiction + reviewer + engagement (REGISTERED). Returns a bundle."""
    jur = make_jurisdiction(**(jur_overrides or {}))
    rev_kwargs = {"state_code": jur["state_code"]}
    rev_kwargs.update(rev_overrides or {})
    rev = make_reviewer(**rev_kwargs)
    eng = make_engagement(jur, rev, applicant_id=applicant_id,
                          **(eng_overrides or {}))
    return {"jurisdiction": jur, "reviewer": rev, "engagement": eng,
            "applicant_id": applicant_id}


def setup_in_review_cycle(jur_overrides=None, eng_overrides=None,
                          rev_overrides=None, applicant_id=DEFAULT_APPLICANT_ID):
    """Bundle + one cycle walked OPEN -> IN_REVIEW with an ACTIVE assignment."""
    bundle = setup_registered_engagement(jur_overrides, eng_overrides,
                                         rev_overrides, applicant_id)
    cycle = open_cycle(bundle["engagement"]["id"])
    assignment = assign_cycle(cycle, bundle["reviewer"]["id"])
    bundle["cycle"] = get_cycle(cycle["id"])
    bundle["assignment"] = assignment
    return bundle


def setup_comments_issued(comment_overrides=None, jur_overrides=None,
                          eng_overrides=None, rev_overrides=None,
                          applicant_id=DEFAULT_APPLICANT_ID):
    """Bundle + one comment raised and the letter issued: cycle is
    COMMENTS_ISSUED with the comment still OPEN."""
    bundle = setup_in_review_cycle(jur_overrides, eng_overrides, rev_overrides,
                                   applicant_id)
    comment = raise_comment(bundle["cycle"]["id"], bundle["reviewer"]["id"],
                            **(comment_overrides or {}))
    issue_comments(bundle["cycle"]["id"], bundle["reviewer"]["id"])
    bundle["comment"] = comment
    bundle["cycle"] = get_cycle(bundle["cycle"]["id"])
    return bundle


def setup_approved_engagement(jur_overrides=None, eng_overrides=None,
                              rev_overrides=None, applicant_id=DEFAULT_APPLICANT_ID):
    """Bundle + one clean-approved cycle: engagement APPROVED, DRAFT record."""
    bundle = setup_in_review_cycle(jur_overrides, eng_overrides, rev_overrides,
                                   applicant_id)
    approve_cycle(bundle["cycle"]["id"], bundle["reviewer"]["id"])
    bundle["cycle"] = get_cycle(bundle["cycle"]["id"])
    bundle["engagement"] = get_engagement(bundle["engagement"]["id"])
    bundle["record"] = get_record_for_engagement(bundle["engagement"]["id"])
    return bundle


def setup_sealed_record(jur_overrides=None, eng_overrides=None,
                        rev_overrides=None, applicant_id=DEFAULT_APPLICANT_ID):
    """Bundle + record SEALED (engagement APPROVED, no deferred items)."""
    bundle = setup_approved_engagement(jur_overrides, eng_overrides,
                                       rev_overrides, applicant_id)
    get_success_data(api_client.seal_record(
        bundle["record"]["id"],
        make_reviewer_headers(bundle["reviewer"]["id"])))
    bundle["record"] = get_success_data(
        api_client.get_record(bundle["record"]["id"], COORDINATOR))
    bundle["engagement"] = get_engagement(bundle["engagement"]["id"])
    return bundle


def make_chief(state_code="CA", name="Chief Reviewer",
               license_type="SE", **overrides) -> dict:
    """Register a second reviewer entity to act with the ChiefReviewer role
    (waiver authority; must differ from the engagement's reviewer of record)."""
    return make_reviewer(name=name, state_code=state_code,
                         license_type=license_type, **overrides)


def chief_headers(chief_id) -> dict:
    return make_chief_reviewer_headers(chief_id)


def reviewer_headers(reviewer_id) -> dict:
    return make_reviewer_headers(reviewer_id)


def applicant_headers(applicant_id=DEFAULT_APPLICANT_ID) -> dict:
    return make_applicant_headers(applicant_id)
