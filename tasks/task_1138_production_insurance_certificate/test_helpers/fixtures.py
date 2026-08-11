"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch against a freshly
restarted server using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so a setup failure surfaces as a clear
"Setup failed" message rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BOOT_CLOCK_ISO
from .factories import (
    create_production_payload, create_policy_payload, create_cast_member_payload,
    create_cast_endorsement_payload, create_certificate_payload, create_claim_payload,
    create_clearance_item_payload, create_completion_bond_payload,
    create_travel_extension_payload, create_payroll_audit_payload,
)
from .test_users import TEST_USERS

BROKER = TEST_USERS["broker_headers"]
PM = TEST_USERS["production_manager_headers"]
UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
CC = TEST_USERS["clearance_counsel_headers"]
SU = TEST_USERS["surety_underwriter_headers"]
AUD = TEST_USERS["external_auditor_headers"]
OP = TEST_USERS["platform_operator_headers"]


def _setup_ok(res, what: str):
    assert res.status_code < 400, f"Setup failed ({what}): {res.status_code} {res.text}"
    return get_success_data(res)


# ─── Tier 0: logical clock ────────────────────────────

def set_logical_clock(to_iso8601: str = BOOT_CLOCK_ISO):
    """Drive the server logical clock (PRD §2.5). Returns the clock payload."""
    return _setup_ok(api_client.set_current_utc(to_iso8601, OP), "set_current_utc")


# ─── Tier 1: state progression ────────────────────────

def create_production(**overrides) -> dict:
    """Create a Production in DRAFT. Returns the production."""
    return _setup_ok(
        api_client.create_production(create_production_payload(**overrides), BROKER),
        "create_production")


def get_production_version(production_id: str) -> int:
    prod = _setup_ok(api_client.get_production(production_id, BROKER), "get_production")
    return prod["version"]


def bind_policy(production_id: str, policy_id: str) -> dict:
    """Bind a QUOTED policy with a fresh OCC version. Returns the bound policy."""
    version = get_production_version(production_id)
    return _setup_ok(
        api_client.bind_policy(production_id, policy_id,
                               {"expected_production_version": version}, BROKER),
        "bind_policy")


def create_and_bind_policy(production_id: str, **policy_overrides) -> dict:
    """Create a policy in QUOTED then bind it. Returns the bound policy."""
    policy = _setup_ok(
        api_client.create_policy(production_id, create_policy_payload(**policy_overrides),
                                 BROKER),
        "create_policy")
    return bind_policy(production_id, policy["id"])


def activate_production(production_id: str) -> dict:
    """Transition production DRAFT -> ACTIVE. Returns the activated production."""
    return _setup_ok(api_client.activate_production(production_id, BROKER),
                     "activate_production")


# ─── Tier 2: entity hierarchy ─────────────────────────

def setup_active_production_with_bound_policy(production_overrides=None,
                                              policy_overrides=None):
    """ACTIVE production with one BOUND policy (default COMMERCIAL + GL).

    Returns (production_refreshed, policy).
    """
    set_logical_clock()
    prod = create_production(**(production_overrides or {}))
    policy = create_and_bind_policy(prod["id"], **(policy_overrides or {}))
    prod = activate_production(prod["id"])
    return prod, policy


def add_cast_member(production_id: str, exam_outcome: str = None,
                    **cast_overrides) -> dict:
    """Add a cast member; optionally record an exam outcome. Returns the member."""
    member = _setup_ok(
        api_client.create_cast_member(production_id,
                                      create_cast_member_payload(**cast_overrides), PM),
        "create_cast_member")
    if exam_outcome is not None:
        member = _setup_ok(
            api_client.record_physical_exam(production_id, member["id"],
                                            {"outcome": exam_outcome}, UW),
            "record_physical_exam")
    return member


def create_draft_certificate(production_id: str, **cert_overrides) -> dict:
    """Create a certificate in DRAFT. Returns the certificate."""
    return _setup_ok(
        api_client.create_certificate(production_id,
                                      create_certificate_payload(**cert_overrides),
                                      BROKER),
        "create_certificate")


def issue_certificate(production_id: str, certificate_id: str) -> dict:
    """Issue a DRAFT certificate with a fresh OCC version. Returns it ISSUED."""
    version = get_production_version(production_id)
    return _setup_ok(
        api_client.issue_certificate(production_id, certificate_id,
                                     {"expected_production_version": version}, BROKER),
        "issue_certificate")


def setup_production_with_issued_certificate(cert_overrides=None, **kwargs):
    """ACTIVE production + BOUND GL policy + one ISSUED certificate.

    Returns (production, policy, certificate).
    """
    prod, policy = setup_active_production_with_bound_policy(**kwargs)
    cert = create_draft_certificate(prod["id"], **(cert_overrides or {}))
    cert = issue_certificate(prod["id"], cert["id"])
    prod = _setup_ok(api_client.get_production(prod["id"], BROKER), "get_production")
    return prod, policy, cert


# ─── Tier 3: claims lifecycle shortcuts ───────────────

def report_claim(production_id: str, policy_id: str, headers=None, **claim_overrides):
    """Report a claim (SUBMITTED). `headers` controls the submitter identity
    for segregation-of-duties scenarios. Returns the claim."""
    return _setup_ok(
        api_client.create_claim(production_id,
                                create_claim_payload(policy_id, **claim_overrides),
                                headers or PM),
        "create_claim")


def setup_claim_under_review(loss_amount_cents=500000, deductible_cents=100000,
                             claim_type="DAMAGE", submitter_headers=None,
                             acknowledge=True):
    """ACTIVE production + BOUND GL policy + claim walked to UNDER_REVIEW.

    Default claim: loss 500000 against deductible 100000 -> deductible_applied
    100000, carrier_payable 400000, reserve initialized at acknowledgement.
    Returns (production, policy, claim).
    """
    prod, policy = setup_active_production_with_bound_policy(
        policy_overrides={"deductible_cents": deductible_cents})
    claim = report_claim(prod["id"], policy["id"], headers=submitter_headers,
                         claim_type=claim_type, loss_amount_cents=loss_amount_cents)
    if acknowledge:
        claim = _setup_ok(api_client.acknowledge_claim(prod["id"], claim["id"], ADJ),
                          "acknowledge_claim")
    return prod, policy, claim


def list_claim_event_types(production_id: str, claim_id: str):
    """Return the ordered event_type list from the claim's event log."""
    res = api_client.list_claim_events(production_id, claim_id, ADJ)
    assert res.status_code == 200, f"Setup failed (list_claim_events): {res.text}"
    return [event["event_type"] for event in get_success_data(res)]


# ─── Tier 3: cast / endorsement shortcuts ─────────────

def setup_cast_policy_bound(cast_members=None, production_overrides=None,
                            policy_overrides=None):
    """DRAFT production with a BOUND CAST policy and the given cast roster.

    cast_members: list of kwargs dicts for add_cast_member (each may include
    an "exam_outcome" key). Members needing an exam for the CAST bind gate
    must come with exam_outcome CLEARED/CONDITIONAL.
    Returns (production, cast_policy, members).
    """
    set_logical_clock()
    prod = create_production(**(production_overrides or {"production_type": "FEATURE"}))
    members = []
    for spec in (cast_members or []):
        spec = dict(spec)
        outcome = spec.pop("exam_outcome", None)
        members.append(add_cast_member(prod["id"], exam_outcome=outcome, **spec))
    policy = create_and_bind_policy(
        prod["id"], **(policy_overrides or {"coverage_line": "CAST",
                                            "carrier_code": "CHUBB",
                                            "payroll_basis_cents": 100000000}))
    return prod, policy, members


def create_issued_endorsement(production_id: str, cast_member_id: str, policy_id: str,
                              endorsement_type: str) -> dict:
    """Create a DRAFT endorsement on a BOUND cast policy and issue it."""
    endo = _setup_ok(
        api_client.create_cast_endorsement(
            production_id,
            create_cast_endorsement_payload(cast_member_id, policy_id,
                                            endorsement_type=endorsement_type),
            UW),
        "create_cast_endorsement")
    return _setup_ok(
        api_client.issue_cast_endorsement(production_id, endo["id"], UW),
        "issue_cast_endorsement")


# ─── Tier 3: clearance shortcuts ──────────────────────

def create_clearance_item(production_id: str, **overrides) -> dict:
    return _setup_ok(
        api_client.create_clearance_item(production_id,
                                         create_clearance_item_payload(**overrides), CC),
        "create_clearance_item")


# ─── Tier 3: completion bond shortcuts ────────────────

def setup_bond_issued_production(budget_cents=1000000000, bond_amount_cents=600000000):
    """Production requiring a bond, walked to: GL BOUND, bond APPLIED ->
    UNDERWRITTEN -> ISSUED, production ACTIVE.

    Returns (production, gl_policy, bond).
    """
    set_logical_clock()
    prod = create_production(budget_cents=budget_cents, requires_completion_bond=True)
    policy = create_and_bind_policy(prod["id"])
    bond = _setup_ok(
        api_client.apply_completion_bond(
            prod["id"],
            create_completion_bond_payload(bond_amount_cents=bond_amount_cents), PM),
        "apply_completion_bond")
    bond = _setup_ok(api_client.underwrite_bond(prod["id"], SU), "underwrite_bond")
    bond = _setup_ok(api_client.issue_bond(prod["id"], SU), "issue_bond")
    prod = activate_production(prod["id"])
    return prod, policy, bond


def get_bond(production_id: str):
    """Read the production's bond (array of zero or one). Returns bond or None."""
    res = api_client.get_completion_bond(production_id, SU)
    assert res.status_code == 200, f"Setup failed (get_completion_bond): {res.text}"
    bonds = get_success_data(res)
    return bonds[0] if bonds else None


# ─── Tier 3: foreign travel shortcuts ─────────────────

def setup_travel_ready_production(production_overrides=None):
    """ACTIVE production with BOUND GENERAL_LIABILITY and FOREIGN_TRAVEL policies.

    Returns (production, gl_policy, ft_policy).
    """
    set_logical_clock()
    prod = create_production(**(production_overrides or {}))
    gl = create_and_bind_policy(prod["id"], coverage_line="GENERAL_LIABILITY")
    ft = create_and_bind_policy(prod["id"], coverage_line="FOREIGN_TRAVEL",
                                carrier_code="TRAVELERS", payroll_basis_cents=5000000)
    prod = activate_production(prod["id"])
    return prod, gl, ft


def request_travel_extension(production_id: str, **overrides) -> dict:
    return _setup_ok(
        api_client.create_travel_extension(production_id,
                                           create_travel_extension_payload(**overrides),
                                           PM),
        "create_travel_extension")


# ─── Tier 3: payroll audit / premium shortcuts ────────

def setup_submitted_payroll_audit(production_overrides=None, policy_overrides=None,
                                  audit_overrides=None):
    """ACTIVE production + BOUND policy + audit walked SCHEDULED -> SUBMITTED.

    Returns (production, policy, audit).
    """
    prod, policy = setup_active_production_with_bound_policy(
        production_overrides=production_overrides, policy_overrides=policy_overrides)
    audit = _setup_ok(
        api_client.create_payroll_audit(prod["id"], policy["id"],
                                        create_payroll_audit_payload(
                                            **(audit_overrides or {})), AUD),
        "create_payroll_audit")
    audit = _setup_ok(
        api_client.submit_payroll_audit(prod["id"], policy["id"], audit["id"], AUD),
        "submit_payroll_audit")
    return prod, policy, audit


def setup_cast_policy_active_for_audit(reported_payroll_cents=120000000,
                                       payroll_basis_cents=100000000):
    """CAST policy made ACTIVE via clock advance, with a SUBMITTED audit on it.

    Roster: one STUNT (not endorsement-required) and one PRINCIPAL essential
    element, both exams CLEARED so the CAST bind gate passes. The clock is
    advanced past the policy effective_date so the BOUND policy auto-activates
    (PRD §2.5), which payroll-audit posting requires.

    Returns (production, cast_policy, audit).
    """
    set_logical_clock()
    prod = create_production(production_type="FEATURE", budget_cents=500000000)
    stunt = add_cast_member(prod["id"], exam_outcome="CLEARED",
                            role_tier="STUNT", essential_element=False)
    principal = add_cast_member(prod["id"], exam_outcome="CLEARED",
                                role_tier="PRINCIPAL", essential_element=True,
                                weekly_salary_cents=800000)
    policy = _setup_ok(
        api_client.create_policy(
            prod["id"],
            create_policy_payload(coverage_line="CAST", carrier_code="CHUBB",
                                  effective_date="2026-05-15T00:00:00Z",
                                  payroll_basis_cents=payroll_basis_cents),
            BROKER),
        "create_policy")
    policy = bind_policy(prod["id"], policy["id"])
    # Advance past effective_date so the policy auto-activates BOUND -> ACTIVE.
    set_logical_clock("2026-06-01T00:00:00Z")
    policy = _setup_ok(api_client.get_policy(prod["id"], policy["id"], BROKER),
                       "get_policy")
    audit = _setup_ok(
        api_client.create_payroll_audit(
            prod["id"], policy["id"],
            create_payroll_audit_payload(
                audit_period_start="2026-05-15T00:00:00Z",
                audit_period_end="2026-11-30T00:00:00Z",
                reported_payroll_cents=reported_payroll_cents),
            AUD),
        "create_payroll_audit")
    audit = _setup_ok(
        api_client.submit_payroll_audit(prod["id"], policy["id"], audit["id"], AUD),
        "submit_payroll_audit")
    return prod, policy, audit
