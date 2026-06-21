"""Composite setup helpers.

These encapsulate the multi-step preambles that the test claims require so that
each test focuses on its trigger + assertions, not plumbing. Every test runs
against a freshly-restarted, empty server, so each fixture builds all of its
preconditions from scratch using only PRD-declared endpoints.

All setup calls go through get_success_data() (lenient 2xx validator), so a
broken precondition surfaces as a clear "Setup step failed" error rather than a
confusing downstream assertion failure.

Identity threading: any ownership-gated Licensee/Provider call uses the actual
entity id via make_licensee_headers / make_provider_headers — never the shared
TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_licensee_headers,
    make_provider_headers,
    make_board_admin_headers,
)
from .constants import ADMIN_INITIATOR_ID, AUDITOR_ID
from . import factories as F

ADMIN = TEST_USERS["board_admin_headers"]
ADMIN_INITIATOR = TEST_USERS["admin_initiator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

CLOCK_START = "2026-01-01T00:00:00Z"
DEFAULT_CYCLE_START = "2026-01-01T00:00:00Z"
DEFAULT_COMPLETED_AT = "2026-02-01T00:00:00Z"
DEFAULT_ACCREDITED_UNTIL = "2030-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: clock + primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers=ADMIN):
    return get_success_data(api_client.set_clock(to_iso8601, headers))


def create_board(clock=CLOCK_START, with_requirements=True,
                 ethics_min=4.0, substance_min=2.0, **board_overrides):
    """Set the clock and create a board, optionally with ETHICS/SUBSTANCE
    requirements. Returns the board dict."""
    if clock is not None:
        set_clock(clock)
    payload = F.create_license_board_payload(**board_overrides)
    board = get_success_data(api_client.create_license_board(payload, ADMIN))
    if with_requirements:
        if ethics_min is not None:
            get_success_data(api_client.create_requirement(
                board["id"], F.create_requirement_payload("ETHICS", ethics_min), ADMIN))
        if substance_min is not None:
            get_success_data(api_client.create_requirement(
                board["id"], F.create_requirement_payload("SUBSTANCE", substance_min), ADMIN))
    return board


def create_accredited_provider(board_id, accredited_until=DEFAULT_ACCREDITED_UNTIL):
    """Register a provider and accredit it. Returns the accredited provider dict."""
    provider = get_success_data(api_client.create_provider(
        F.create_provider_payload(board_id), ADMIN))
    accredited = get_success_data(api_client.accredit_provider(
        provider["id"], F.accredit_provider_payload(accredited_until), ADMIN))
    return accredited


def create_course(provider_id, category, credit_hours, title=None):
    title = title or f"{category[:1]}{credit_hours}"
    return get_success_data(api_client.create_course(
        F.create_course_payload(provider_id, category, credit_hours, title=title), ADMIN))


def create_licensee(board_id, **overrides):
    return get_success_data(api_client.create_licensee(
        F.create_licensee_payload(board_id, **overrides), ADMIN))


def open_cycle(licensee_id, board_id, cycle_start=DEFAULT_CYCLE_START, **overrides):
    """Open a renewal cycle as the owning licensee (ownership-threaded)."""
    payload = F.create_renewal_cycle_payload(licensee_id, board_id, cycle_start, **overrides)
    return get_success_data(api_client.create_renewal_cycle(
        payload, make_licensee_headers(licensee_id)))


def log_completion(licensee_id, course_id, cycle_id, completed_at=DEFAULT_COMPLETED_AT):
    """Submit a completion as the owning licensee (ownership-threaded)."""
    payload = F.create_completion_payload(licensee_id, course_id, cycle_id, completed_at)
    return get_success_data(api_client.create_completion(
        payload, make_licensee_headers(licensee_id)))


def verify_completion(completion_id):
    return get_success_data(api_client.verify_completion(completion_id, ADMIN))


def log_and_verify(licensee_id, course_id, cycle_id, completed_at=DEFAULT_COMPLETED_AT):
    comp = log_completion(licensee_id, course_id, cycle_id, completed_at)
    verify_completion(comp["id"])
    return comp


# ---------------------------------------------------------------------------
# Tier 1/2: standard board + provider + licensee + cycle setups
# ---------------------------------------------------------------------------
def setup_board_provider_licensee_cycle(
        ethics_min=4.0, substance_min=2.0, total_required_hours=30.0,
        with_requirements=True, with_provider=True,
        board_overrides=None, cycle_start=DEFAULT_CYCLE_START):
    """Active board (+ETHICS/SUBSTANCE reqs), an accredited provider, a licensee,
    and an OPEN cycle. Returns a dict with keys:
      board, provider (or None), licensee, cycle.
    """
    board_overrides = board_overrides or {}
    board_overrides.setdefault("total_required_hours", total_required_hours)
    board = create_board(with_requirements=with_requirements,
                         ethics_min=ethics_min, substance_min=substance_min,
                         **board_overrides)
    provider = create_accredited_provider(board["id"]) if with_provider else None
    licensee = create_licensee(board["id"])
    cycle = open_cycle(licensee["id"], board["id"], cycle_start)
    return {"board": board, "provider": provider, "licensee": licensee, "cycle": cycle}


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting — reach REQUIREMENTS_MET
# ---------------------------------------------------------------------------
def setup_requirements_met_cycle(
        ethics_hours=4.0, substance_hours=2.0, general_hours=24.0,
        ethics_min=4.0, substance_min=2.0, total_required_hours=30.0,
        carryover_cap_hours=10.0):
    """Build a board+provider+licensee+cycle and verify one completion per
    category so that the cycle reaches REQUIREMENTS_MET (final == sum). Returns
    a dict: board, provider, licensee, cycle (re-fetched), courses, completions.

    Categories with a None hours value are skipped (used to leave a deficit).
    """
    base = setup_board_provider_licensee_cycle(
        ethics_min=ethics_min, substance_min=substance_min,
        total_required_hours=total_required_hours,
        board_overrides={"carryover_cap_hours": carryover_cap_hours})
    board, provider, licensee, cycle = (
        base["board"], base["provider"], base["licensee"], base["cycle"])

    courses = {}
    completions = {}
    for category, hours in (("ETHICS", ethics_hours),
                            ("SUBSTANCE", substance_hours),
                            ("GENERAL", general_hours)):
        if hours is None:
            continue
        course = create_course(provider["id"], category, hours)
        courses[category] = course
        comp = log_and_verify(licensee["id"], course["id"], cycle["id"])
        completions[category] = comp

    cycle = get_success_data(api_client.get_renewal_cycle(cycle["id"], ADMIN))
    return {
        "board": board, "provider": provider, "licensee": licensee,
        "cycle": cycle, "courses": courses, "completions": completions,
    }


# ---------------------------------------------------------------------------
# Tier 5: audit lifecycle shortcuts
# ---------------------------------------------------------------------------
def initiate_audit(cycle_id, initiator_headers=None):
    """Initiate an audit against a cycle using the dedicated initiating admin
    identity (so a separate auditor can later decide it). Returns the audit."""
    headers = initiator_headers or ADMIN_INITIATOR
    return get_success_data(api_client.create_audit(
        F.create_audit_payload(cycle_id), headers))


def setup_audit_under_review(attested_hours, final_hours=30.0,
                             ethics_hours=4.0, substance_hours=2.0, general_hours=24.0):
    """Reach REQUIREMENTS_MET, initiate an audit (admin-initiator), request
    attestation, and have the licensee attest `attested_hours` — leaving the
    audit in UNDER_REVIEW. Returns a dict: board, provider, licensee, cycle,
    audit, attestation.
    """
    met = setup_requirements_met_cycle(
        ethics_hours=ethics_hours, substance_hours=substance_hours,
        general_hours=general_hours)
    licensee, cycle = met["licensee"], met["cycle"]

    audit = initiate_audit(cycle["id"], ADMIN_INITIATOR)
    get_success_data(api_client.request_attestation(audit["id"], ADMIN_INITIATOR))
    attestation = get_success_data(api_client.submit_attestation(
        audit["id"], F.submit_attestation_payload(attested_hours),
        make_licensee_headers(licensee["id"])))

    audit = get_success_data(api_client.get_audit(audit["id"], ADMIN))
    return {
        "board": met["board"], "provider": met["provider"], "licensee": licensee,
        "cycle": cycle, "audit": audit, "attestation": attestation,
        "courses": met["courses"], "completions": met["completions"],
    }


def setup_audit_decided(decision, attested_hours, final_hours=30.0,
                        decide_clock=None, auditor_headers=AUDITOR):
    """Drive a cycle to REQUIREMENTS_MET, run the attestation handshake, and have
    the auditor decide the audit (PASS/FAIL). Optionally advance the clock just
    before the decision (for cooldown/closed_at scenarios). Returns a dict:
    board, provider, licensee, cycle (re-fetched), audit (re-fetched).
    """
    setup = setup_audit_under_review(attested_hours, final_hours=final_hours)
    licensee, cycle, audit = setup["licensee"], setup["cycle"], setup["audit"]

    if decide_clock is not None:
        set_clock(decide_clock)
    get_success_data(api_client.decide_audit(
        audit["id"], F.decide_audit_payload(decision), auditor_headers))

    audit = get_success_data(api_client.get_audit(audit["id"], ADMIN))
    cycle = get_success_data(api_client.get_renewal_cycle(cycle["id"], ADMIN))
    return {
        "board": setup["board"], "provider": setup["provider"], "licensee": licensee,
        "cycle": cycle, "audit": audit,
    }


# ---------------------------------------------------------------------------
# Reciprocity setups
# ---------------------------------------------------------------------------
def request_reciprocity(licensee_id, cycle_id, category, credit_hours,
                        source_jurisdiction_code="NY"):
    """Request a reciprocity grant as the owning licensee (ownership-threaded)."""
    payload = F.create_reciprocity_grant_payload(
        licensee_id, cycle_id, source_jurisdiction_code, category, credit_hours)
    return get_success_data(api_client.create_reciprocity_grant(
        payload, make_licensee_headers(licensee_id)))
