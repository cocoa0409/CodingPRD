"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"setup failed" errors rather than confusing assertion failures. Each helper builds its
preconditions from scratch using only PRD-declared endpoints — the test harness restarts the
server (empty DB) before every test.

The dominant preamble across the design indices is the underwriting funnel:
  program -> principal -> indemnity GIA -> sign -> application -> submit -> approve -> bind -> issue
which yields an ACTIVE bond. The tiered helpers below capture progressively longer prefixes
of that funnel so individual tests only express their trigger and assertions.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_program_payload,
    create_principal_payload,
    create_indemnity_agreement_payload,
    create_application_payload,
    create_bond_payload,
    create_claim_payload,
    create_rider_payload,
    create_treaty_payload,
    create_cession_payload,
)
from .test_users import TEST_USERS

UW = TEST_USERS["underwriter_headers"]
SR = TEST_USERS["senior_underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]


# ─── Tier 1: Single-entity helpers ────────────────────────────────────────────

def create_program(**overrides):
    """SeniorUnderwriter creates an OPEN SuretyProgram. Returns the program."""
    res = api_client.create_program(create_program_payload(**overrides), SR)
    return get_success_data(res)


def create_suspended_program(**overrides):
    """Create a program then suspend it. Returns the SUSPENDED program."""
    prog = create_program(**overrides)
    res = api_client.suspend_program(prog["id"], SR)
    return get_success_data(res)


def create_treaty(**overrides):
    """SeniorUnderwriter creates an OPEN ReinsuranceTreaty. Returns the treaty."""
    res = api_client.create_treaty(create_treaty_payload(**overrides), SR)
    return get_success_data(res)


def create_closed_treaty(**overrides):
    """Create a treaty then close it. Returns the CLOSED treaty."""
    treaty = create_treaty(**overrides)
    res = api_client.close_treaty(treaty["id"], SR)
    return get_success_data(res)


def create_principal(**overrides):
    """Underwriter creates a Principal; credit_tier is derived. Returns the principal."""
    res = api_client.create_principal(create_principal_payload(**overrides), UW)
    return get_success_data(res)


def create_principal_with_indemnity(**overrides):
    """Create a principal and execute a 1-signature GIA so indemnity_on_file becomes true.
    Returns (principal, gia)."""
    prin = create_principal(**overrides)
    gia = get_success_data(
        api_client.create_indemnity_agreement(
            create_indemnity_agreement_payload(prin["id"]), UW
        )
    )
    gia = get_success_data(api_client.sign_indemnity_agreement(gia["id"], UW))
    return prin, gia


# ─── Tier 2: Application funnel ────────────────────────────────────────────────

def setup_draft_application(program=None, principal=None, app_overrides=None):
    """Program + principal-with-indemnity + a DRAFT application.
    Returns (program, principal, application)."""
    prog = program if program is not None else create_program()
    if principal is not None:
        prin = principal
    else:
        prin, _ = create_principal_with_indemnity()
    app = get_success_data(
        api_client.create_application(
            create_application_payload(prin["id"], prog["id"], **(app_overrides or {})), UW
        )
    )
    return prog, prin, app


def setup_submitted_application(program=None, principal=None, app_overrides=None):
    """Funnel through SUBMITTED (premium quoted). Returns (program, principal, application)."""
    prog, prin, app = setup_draft_application(program, principal, app_overrides)
    app = get_success_data(api_client.submit_application(app["id"], UW))
    return prog, prin, app


def setup_approved_application(program=None, principal=None, app_overrides=None):
    """Funnel through APPROVED (front-line, below referral threshold).
    Returns (program, principal, application)."""
    prog, prin, app = setup_submitted_application(program, principal, app_overrides)
    app = get_success_data(api_client.approve_application(app["id"], UW))
    return prog, prin, app


def setup_referred_application(program=None, principal=None, app_overrides=None):
    """Funnel through REFERRED. Returns (program, principal, application)."""
    prog, prin, app = setup_submitted_application(program, principal, app_overrides)
    app = get_success_data(api_client.refer_application(app["id"], UW))
    return prog, prin, app


# ─── Tier 3: Bond lifecycle ───────────────────────────────────────────────────

def setup_issued_bond(program=None, principal=None, app_overrides=None):
    """Bind an approved application into an ISSUED bond (not yet issued/active).
    Returns (program, principal, application, bond)."""
    prog, prin, app = setup_approved_application(program, principal, app_overrides)
    bond = get_success_data(
        api_client.create_bond(create_bond_payload(app["id"]), UW)
    )
    return prog, prin, app, bond


def setup_active_bond(program=None, principal=None, app_overrides=None):
    """Full funnel to an ACTIVE bond (issued, power-of-attorney stamped).
    Returns (program, principal, application, bond)."""
    prog, prin, app, bond = setup_issued_bond(program, principal, app_overrides)
    bond = get_success_data(api_client.issue_bond(bond["id"], UW))
    return prog, prin, app, bond


# ─── Tier 4: Claims on a bond ─────────────────────────────────────────────────

def setup_filed_claim(bond=None, program=None, claim_overrides=None):
    """An ACTIVE bond with one FILED claim. Returns (program, bond, claim)."""
    if bond is None:
        program, _, _, bond = setup_active_bond(program=program)
    claim = get_success_data(
        api_client.create_claim(
            create_claim_payload(bond["id"], **(claim_overrides or {})), CE
        )
    )
    return program, bond, claim


def setup_investigating_claim(bond=None, program=None, claim_overrides=None,
                              investigate_reserve=None):
    """An ACTIVE bond with one INVESTIGATING claim. Returns (program, bond, claim)."""
    program, bond, claim = setup_filed_claim(bond, program, claim_overrides)
    reserve = (
        investigate_reserve
        if investigate_reserve is not None
        else claim["reserve_cents"]
    )
    claim = get_success_data(
        api_client.investigate_claim(claim["id"], {"reserve_cents": reserve}, CE)
    )
    return program, bond, claim


# ─── Tier 5: Cessions and riders ──────────────────────────────────────────────

def setup_active_cession(bond=None, treaty=None, program=None,
                         app_overrides=None, treaty_overrides=None):
    """An ACTIVE bond with one ACTIVE cession to a treaty.
    Returns (program, bond, treaty, cession)."""
    if bond is None:
        program, _, _, bond = setup_active_bond(program=program, app_overrides=app_overrides)
    if treaty is None:
        treaty = create_treaty(**(treaty_overrides or {}))
    cession = get_success_data(
        api_client.create_cession(create_cession_payload(bond["id"], treaty["id"]), UW)
    )
    return program, bond, treaty, cession


def setup_draft_rider(bond=None, program=None, app_overrides=None, rider_overrides=None):
    """An ACTIVE bond with one DRAFT rider. Returns (program, bond, rider)."""
    if bond is None:
        program, _, _, bond = setup_active_bond(program=program, app_overrides=app_overrides)
    rider = get_success_data(
        api_client.create_rider(
            create_rider_payload(bond["id"], **(rider_overrides or {})), UW
        )
    )
    return program, bond, rider


def set_clock(to_iso8601):
    """Advance the server logical clock (SeniorUnderwriter-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, SR))
