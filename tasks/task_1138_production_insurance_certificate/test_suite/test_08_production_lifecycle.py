"""Production lifecycle: terminal lockdown, wrap gates, cancel/bond-claim
cascades, and the payroll-audit dispute loop (PRD §3.9, §3.7, §3.10)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_policy_payload, create_certificate_payload,
    create_cast_endorsement_payload,
    set_logical_clock, create_production, create_and_bind_policy,
    activate_production, setup_active_production_with_bound_policy,
    setup_production_with_issued_certificate, setup_cast_policy_bound,
    setup_bond_issued_production, setup_submitted_payroll_audit,
    add_cast_member, create_issued_endorsement, create_draft_certificate,
    issue_certificate, report_claim, get_bond,
    TEST_USERS,
)

BROKER = TEST_USERS["broker_headers"]
PM = TEST_USERS["production_manager_headers"]
UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
SU = TEST_USERS["surety_underwriter_headers"]
AUD = TEST_USERS["external_auditor_headers"]


# ─── Terminal wrap lockdown (corner) ──────────────────

def test_production_terminal_wrap_lockdown(api):
    """PRD §2.9 step 5: "On action endpoints, the target entity must currently
    sit in a valid source state for the requested transition; otherwise
    `ERR_INVALID_STATE` (409)."
    PRD §3.9: "Wrapping is the production's happy ending, performed by a
    `ProductionManager` as an `ACTIVE` → `WRAPPED` transition."

    Design: Corner/state_machines/production_terminal_wrap_lockdown
    """
    prod, policy = setup_active_production_with_bound_policy()
    wrapped = validate_success(api.wrap_production(prod["id"], PM), 200)
    assert wrapped["status"] == "WRAPPED"

    res_activate = api.activate_production(prod["id"], BROKER)
    validate_error(res_activate, "ERR_INVALID_STATE", expected_status=409)
    res_cancel = api.cancel_production(prod["id"], BROKER)
    validate_error(res_cancel, "ERR_INVALID_STATE", expected_status=409)


# ─── Draft certificates block wrap (corner) ───────────

def test_certificate_issue_with_open_draft_certificates_blocks_wrap(api):
    """PRD §3.9: "And no certificate may still sit in `DRAFT` — draft
    certificates must be issued or voided first — or the refusal is
    `ERR_DRAFT_CERTIFICATES_OPEN`."

    Design: Corner/errors/certificate_issue_with_open_draft_certificates_blocks_wrap
    """
    prod, policy = setup_active_production_with_bound_policy()
    create_draft_certificate(prod["id"], certificate_type="LOCATION",
                             additional_insured_name="DO Owner")
    res = api.wrap_production(prod["id"], PM)
    validate_error(res, "ERR_DRAFT_CERTIFICATES_OPEN", expected_status=422)


# ─── Production cancel cascade (difficulty) ───────────

def _setup_active_with_endorsement_and_issued_cert():
    """ACTIVE FEATURE production: GL + CAST BOUND, one ISSUED ESSENTIAL_ELEMENT
    endorsement, one ISSUED LOCATION certificate. Returns ids."""
    prod, cast_policy, members = setup_cast_policy_bound(
        cast_members=[{"role_tier": "PRINCIPAL", "essential_element": True,
                       "exam_outcome": "CLEARED", "weekly_salary_cents": 1000000}])
    gl_policy = create_and_bind_policy(prod["id"], coverage_line="GENERAL_LIABILITY")
    endo = create_issued_endorsement(prod["id"], members[0]["id"],
                                     cast_policy["id"], "ESSENTIAL_ELEMENT")
    prod = activate_production(prod["id"])
    cert = create_draft_certificate(
        prod["id"], certificate_type="LOCATION",
        additional_insured_name="Studio Owner LLC",
        location_start="2026-06-01T00:00:00Z", location_end="2026-06-30T00:00:00Z")
    cert = issue_certificate(prod["id"], cert["id"])
    return prod, gl_policy, cast_policy, endo, cert


def test_production_cancel_cascade_depth3(api):
    """PRD §3.9: "The cascade is then total: all policies in `BOUND`,
    `ENDORSED_PENDING`, or `ACTIVE` move to `CANCELLED`; all certificates in
    `DRAFT` or `ISSUED` move to `VOIDED`; all `ISSUED` cast endorsements move
    to `REVOKED`; the completion bond, unless it has been `CLAIMED`, moves to
    `LAPSED`; every travel extension in `REQUESTED`, `APPROVED`, or `ACTIVE`
    moves to `DENIED`; and posture is recomputed over the wreckage."
    PRD §3.4: "A `CANCELLED` production is always `SUSPENDED`."

    Design: Difficulty/transitive_cascade/production_cancel_cascade_depth3
    """
    prod, gl_policy, cast_policy, endo, cert = \
        _setup_active_with_endorsement_and_issued_cert()

    cancelled = validate_success(api.cancel_production(prod["id"], BROKER), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["coverage_posture"] == "SUSPENDED"

    gl_after = validate_success(api.get_policy(prod["id"], gl_policy["id"], BROKER), 200)
    cast_after = validate_success(
        api.get_policy(prod["id"], cast_policy["id"], BROKER), 200)
    endo_after = validate_success(
        api.get_cast_endorsement(prod["id"], endo["id"], UW), 200)
    cert_after = validate_success(
        api.get_certificate(prod["id"], cert["id"], BROKER), 200)
    assert gl_after["status"] == "CANCELLED"
    assert cast_after["status"] == "CANCELLED"
    assert endo_after["status"] == "REVOKED"
    assert cert_after["status"] == "VOIDED"


def test_production_cancel_from_draft_cancels_quoted_policies(api):
    """PRD §3.9: "Cancelling straight out of `DRAFT` carries no preconditions
    and a single consequence: every `QUOTED` policy moves to `CANCELLED`."
    PRD §3.4: "A `CANCELLED` production is always `SUSPENDED`."

    Design: Difficulty/transitive_cascade/production_cancel_cascade_depth3
    """
    set_logical_clock()
    prod = create_production()
    policy = validate_success(
        api.create_policy(prod["id"], create_policy_payload(), BROKER), 201)
    assert policy["status"] == "QUOTED"

    cancelled = validate_success(api.cancel_production(prod["id"], BROKER), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["coverage_posture"] == "SUSPENDED"
    policy_after = validate_success(api.get_policy(prod["id"], policy["id"], BROKER), 200)
    assert policy_after["status"] == "CANCELLED"


# ─── Bond claim cascade (difficulty) ──────────────────

def _setup_bond_claim_scenario():
    """Bond ISSUED production + one ISSUED certificate + one open claim whose
    loss reaches the bond's strike price. Returns (prod, policy, bond, cert)."""
    prod, policy, bond = setup_bond_issued_production(
        budget_cents=1000000000, bond_amount_cents=600000000)
    cert = create_draft_certificate(
        prod["id"], certificate_type="VENDOR",
        location_start="2026-06-01T00:00:00Z", location_end="2026-06-30T00:00:00Z")
    cert = issue_certificate(prod["id"], cert["id"])
    # strike_price_cents == bond_amount_cents; a claim at that exact loss
    # "reaches" the strike price.
    claim = report_claim(prod["id"], policy["id"],
                         loss_amount_cents=bond["strike_price_cents"])
    validate_success(api_client.acknowledge_claim(prod["id"], claim["id"], ADJ), 200)
    return prod, policy, bond, cert


def test_bond_claim_cascade_depth2(api):
    """PRD §3.7: "A surety may claim against the bond — `ISSUED` → `CLAIMED` —
    but only while the production has at least one open claim (status
    `SUBMITTED`, `UNDER_REVIEW`, or `ADJUSTED`) whose `loss_amount_cents`
    reaches the bond's `strike_price_cents`; claiming the bond cancels every
    policy on the production, voids every certificate, and recomputes posture."

    Design: Difficulty/transitive_cascade/bond_claim_cascade_depth2
    """
    prod, policy, bond, cert = _setup_bond_claim_scenario()

    claimed = validate_success(api.claim_bond(prod["id"], SU), 200)
    assert claimed["status"] == "CLAIMED"

    policy_after = validate_success(api.get_policy(prod["id"], policy["id"], BROKER), 200)
    cert_after = validate_success(api.get_certificate(prod["id"], cert["id"], BROKER), 200)
    assert policy_after["status"] == "CANCELLED"
    assert cert_after["status"] == "VOIDED"

    prod_after = validate_success(api.get_production(prod["id"], BROKER), 200)
    assert prod_after["coverage_posture"] == "RESTRICTED"


def test_bond_claim_posture_reasons_bond_not_issued(api):
    """PRD §3.4: "and `BOND_NOT_ISSUED` when a required bond has not reached
    `ISSUED`."
    PRD §3.4: "so does a required completion bond that is not yet `ISSUED`."
    PRD §3.7: "claiming the bond cancels every policy on the production, voids
    every certificate, and recomputes posture."

    After the claim the bond sits in CLAIMED — not ISSUED — so the recomputed
    posture is RESTRICTED and names BOND_NOT_ISSUED.

    Design: Difficulty/transitive_cascade/bond_claim_cascade_depth2
    """
    prod, policy, bond, cert = _setup_bond_claim_scenario()
    validate_success(api.claim_bond(prod["id"], SU), 200)

    prod_after = validate_success(api.get_production(prod["id"], BROKER), 200)
    assert prod_after["coverage_posture"] == "RESTRICTED"
    assert "BOND_NOT_ISSUED" in prod_after["posture_reasons"]


# ─── Payroll audit dispute/resubmit cycle (difficulty) ───

def test_payroll_audit_dispute_resubmit_cycle(api):
    """PRD §3.10: "A `ProductionManager` who disputes the figures moves a
    `SUBMITTED` audit to `DISPUTED`, and the auditor resubmits a disputed audit
    back to `SUBMITTED` with corrected figures."

    Design: Difficulty/non_linear_state_machine/payroll_audit_dispute_resubmit_cycle
    """
    prod, policy, audit = setup_submitted_payroll_audit()
    assert audit["status"] == "SUBMITTED"

    d1 = validate_success(
        api.dispute_payroll_audit(prod["id"], policy["id"], audit["id"], PM), 200)
    assert d1["status"] == "DISPUTED"
    s2 = validate_success(
        api.submit_payroll_audit(prod["id"], policy["id"], audit["id"], AUD), 200)
    assert s2["status"] == "SUBMITTED"
    d2 = validate_success(
        api.dispute_payroll_audit(prod["id"], policy["id"], audit["id"], PM), 200)
    assert d2["status"] == "DISPUTED"


def test_payroll_audit_single_dispute_and_resubmit(api):
    """PRD §3.10: "A `ProductionManager` who disputes the figures moves a
    `SUBMITTED` audit to `DISPUTED`, and the auditor resubmits a disputed audit
    back to `SUBMITTED` with corrected figures."
    PRD §3.10: "Submission — by the `ExternalAuditor` — moves `SCHEDULED` →
    `SUBMITTED`, requiring the reported payroll to be zero or more and the
    period end to fall strictly after the period start."

    Design: Difficulty/non_linear_state_machine/payroll_audit_dispute_resubmit_cycle
    """
    prod, policy, audit = setup_submitted_payroll_audit()
    disputed = validate_success(
        api.dispute_payroll_audit(prod["id"], policy["id"], audit["id"], PM), 200)
    assert disputed["status"] == "DISPUTED"

    resubmitted = validate_success(
        api.submit_payroll_audit(prod["id"], policy["id"], audit["id"], AUD), 200)
    assert resubmitted["status"] == "SUBMITTED"

    persisted = validate_success(
        api.get_payroll_audit(prod["id"], policy["id"], audit["id"], AUD), 200)
    assert persisted["status"] == "SUBMITTED"
