"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test. Helpers use
get_success_data() internally so setup failures surface as clear "Setup step
failed" errors rather than confusing downstream assertion failures.

Candidate identity threading: every ownership-gated Candidate call uses
make_candidate_headers(candidate["id"]) — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_candidate_headers,
)
from . import factories as f


# Convenience role-header shortcuts (opaque roles).
ADMIN = TEST_USERS["test_center_admin_headers"]
REVIEWER = TEST_USERS["accommodation_reviewer_headers"]
SCORE_OPS = TEST_USERS["score_ops_headers"]


# ─── Primitive creators ───────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the simulated clock (any role may; uses admin headers)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_center(**overrides) -> dict:
    return get_success_data(
        api_client.create_test_center(f.create_test_center_payload(**overrides), ADMIN)
    )


def create_session(center_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_test_session(f.create_test_session_payload(center_id, **overrides), ADMIN)
    )


def create_candidate(**overrides) -> dict:
    return get_success_data(
        api_client.create_candidate(f.create_candidate_payload(**overrides), TEST_USERS["candidate_headers"])
    )


def create_registration(session_id, candidate_id, expected_version, **overrides) -> dict:
    """Reserve a seat as the owning candidate. expected_version is the session
    version the client last observed (OCC token, PRD §2.9)."""
    return get_success_data(
        api_client.create_registration(
            f.create_registration_payload(session_id, candidate_id, expected_version, **overrides),
            make_candidate_headers(candidate_id),
        )
    )


def confirm_registration(reg_id, candidate_id) -> dict:
    return get_success_data(
        api_client.confirm_registration(reg_id, make_candidate_headers(candidate_id))
    )


def record_id_verification(reg_id, first_name, last_name, id_state_code) -> dict:
    return get_success_data(
        api_client.create_id_verification(
            reg_id,
            f.create_id_verification_payload(first_name, last_name, id_state_code),
            ADMIN,
        )
    )


def check_in(reg_id) -> dict:
    return get_success_data(api_client.check_in_registration(reg_id, ADMIN))


def record_score(reg_id, exam_type, section_scores) -> dict:
    return get_success_data(
        api_client.create_score_report(
            reg_id, f.create_score_report_payload(exam_type, section_scores), SCORE_OPS
        )
    )


def release_score(reg_id) -> dict:
    return get_success_data(api_client.release_score(reg_id, SCORE_OPS))


# ─── State-progression / lifecycle shortcuts ──────────────────────────────────

def setup_center_session_candidate(center_overrides=None, session_overrides=None,
                                   candidate_overrides=None, clock=None):
    """Most common base: one center, one candidate, one OPEN session.

    Returns (center, candidate, session). The session dict's current `version`
    is the OCC token for the first registration.
    """
    if clock is not None:
        set_clock(clock)
    center = create_center(**(center_overrides or {}))
    candidate = create_candidate(**(candidate_overrides or {}))
    session = create_session(center["id"], **(session_overrides or {}))
    return center, candidate, session


def create_reserved_registration(center_overrides=None, session_overrides=None,
                                 candidate_overrides=None, reg_overrides=None, clock=None):
    """Center + candidate + session + one RESERVED registration.

    Returns (center, candidate, session, registration).
    """
    center, candidate, session = setup_center_session_candidate(
        center_overrides, session_overrides, candidate_overrides, clock
    )
    reg = create_registration(
        session["id"], candidate["id"], session["version"], **(reg_overrides or {})
    )
    return center, candidate, session, reg


def create_confirmed_registration(center_overrides=None, session_overrides=None,
                                  candidate_overrides=None, reg_overrides=None, clock=None):
    """Center + candidate + session + a CONFIRMED registration.

    Returns (center, candidate, session, registration_after_confirm).
    """
    center, candidate, session, reg = create_reserved_registration(
        center_overrides, session_overrides, candidate_overrides, reg_overrides, clock
    )
    reg = confirm_registration(reg["id"], candidate["id"])
    return center, candidate, session, reg


def create_checked_in_registration(center_overrides=None, session_overrides=None,
                                   candidate_overrides=None, reg_overrides=None, clock=None):
    """Walk a STANDARD registration to CHECKED_IN with a MATCH IDVerification.

    Uses the candidate's legal name (same-state) so the verification matches.
    Returns (center, candidate, session, registration_after_check_in).
    """
    cand_over = dict(candidate_overrides or {})
    center, candidate, session, reg = create_confirmed_registration(
        center_overrides, session_overrides, cand_over, reg_overrides, clock
    )
    record_id_verification(
        reg["id"],
        candidate["legal_first_name"],
        candidate["legal_last_name"],
        candidate["id_document_state_code"],
    )
    reg = check_in(reg["id"])
    return center, candidate, session, reg


def create_scored_registration(section_scores, exam_type="SAT", **kwargs):
    """CHECKED_IN registration with a recorded ScoreReport (score_status SCORED).

    Returns (center, candidate, session, registration_after_score, score_report).
    """
    center, candidate, session, reg = create_checked_in_registration(**kwargs)
    sr = record_score(reg["id"], exam_type, section_scores)
    reg = get_success_data(api_client.get_registration(reg["id"], TEST_USERS["candidate_headers"]))
    return center, candidate, session, reg, sr


def create_released_registration(section_scores, exam_type="SAT", **kwargs):
    """CHECKED_IN + SCORED + RELEASED registration.

    Returns (center, candidate, session, registration_after_release, score_report).
    """
    center, candidate, session, reg, sr = create_scored_registration(section_scores, exam_type, **kwargs)
    reg = release_score(reg["id"])
    sr = get_success_data(
        api_client.get_score_report(sr["id"], TEST_USERS["candidate_headers"])
    )
    return center, candidate, session, reg, sr


# ─── Accommodation lifecycle ──────────────────────────────────────────────────

def create_accommodation_under_review(accommodation_type, basis="PLAN_504",
                                      center_overrides=None, session_overrides=None,
                                      reg_overrides=None, clock=None):
    """504-eligible candidate + RESERVED registration + accommodation request
    driven to UNDER_REVIEW.

    Returns (center, candidate, session, registration, accommodation_request).
    """
    center, candidate, session, reg = create_reserved_registration(
        center_overrides, session_overrides,
        candidate_overrides={"has_active_504_iep": True}, reg_overrides=reg_overrides, clock=clock,
    )
    acc = get_success_data(
        api_client.create_accommodation_request(
            f.create_accommodation_request_payload(
                candidate["id"], reg["id"], accommodation_type, basis
            ),
            make_candidate_headers(candidate["id"]),
        )
    )
    acc = get_success_data(api_client.begin_review_accommodation(acc["id"], REVIEWER))
    return center, candidate, session, reg, acc


def create_approved_accommodation(accommodation_type, basis="PLAN_504", **kwargs):
    """Accommodation request driven all the way to APPROVED (registration bound,
    seat_kind flipped to ACCOMMODATED).

    Returns (center, candidate, session, registration_after_bind, accommodation_request).
    """
    center, candidate, session, reg, acc = create_accommodation_under_review(
        accommodation_type, basis, **kwargs
    )
    acc = get_success_data(api_client.approve_accommodation(acc["id"], REVIEWER))
    reg = get_success_data(
        api_client.get_registration(reg["id"], make_candidate_headers(candidate["id"]))
    )
    return center, candidate, session, reg, acc


# ─── Standby / promotion targeting ────────────────────────────────────────────

def create_full_session_with_one_confirmed(center_overrides=None, session_overrides=None,
                                           clock=None):
    """A capacity-controlled session with exactly one CONFIRMED registration
    holding the standard seat. Defaults capacity to 1 so the pool is full.

    Returns (center, holder_candidate, session, holder_registration).
    """
    c_over = dict(center_overrides or {})
    c_over.setdefault("room_capacity_standard", 1)
    c_over.setdefault("room_capacity_accommodated", 1)
    c_over.setdefault("name", "Tiny Center")
    c_over.setdefault("state_code", "NY")
    s_over = dict(session_overrides or {})
    if clock is not None:
        set_clock(clock)
    center = create_center(**c_over)
    holder = create_candidate(legal_first_name="Holder", legal_last_name="One",
                              date_of_birth="2008-01-01", home_state_code="NY",
                              id_document_state_code="NY")
    session = create_session(center["id"], **s_over)
    reg = create_registration(session["id"], holder["id"], session["version"])
    reg = confirm_registration(reg["id"], holder["id"])
    return center, holder, session, reg


def add_standby_entry(session_id, candidate, priority_tier):
    """Create a WAITING standby entry for an existing candidate on a session."""
    return get_success_data(
        api_client.create_standby_entry(
            f.create_standby_entry_payload(session_id, candidate["id"], priority_tier),
            make_candidate_headers(candidate["id"]),
        )
    )


def make_alt_candidate(first, last, state="NY"):
    return create_candidate(legal_first_name=first, legal_last_name=last,
                            date_of_birth="2008-02-02", home_state_code=state,
                            id_document_state_code=state)
