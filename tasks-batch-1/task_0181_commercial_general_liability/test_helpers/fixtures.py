"""Composite setup helpers for the CGL platform.

Each test runs against a fresh, empty database (the harness restarts the server
before every test), so every fixture builds its preconditions from scratch using
only PRD-declared endpoints. Setup steps use get_success_data() (lenient 2xx
validator) so a broken precondition surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories

ADMIN = TEST_USERS["insurer_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
AUD = TEST_USERS["premium_auditor_headers"]

CLOCK_MID = "2026-06-01T00:00:00.000Z"          # inside the standard [2026-01-01, 2027-01-01) period
CLOCK_PAST_EXPIRY = "2027-01-02T00:00:00.000Z"  # past the standard expiration


# ---------------------------------------------------------------------------
# Tier 1: base carrier setup
# ---------------------------------------------------------------------------
def create_insurer(**overrides) -> dict:
    resp = api_client.create_insurer(factories.create_insurer_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_insured(insurer_id, **overrides) -> dict:
    resp = api_client.create_insured(factories.create_insured_payload(insurer_id, **overrides), UW)
    return get_success_data(resp)


def create_certificate_holder(insurer_id, **overrides) -> dict:
    resp = api_client.create_certificate_holder(
        factories.create_certificate_holder_payload(insurer_id, **overrides), UW)
    return get_success_data(resp)


def create_carrier_with_insured(**insured_overrides):
    """Returns (insurer, insured)."""
    insurer = create_insurer()
    insured = create_insured(insurer["id"], **insured_overrides)
    return insurer, insured


def create_carrier_with_insured_and_holder():
    """Returns (insurer, insured, holder)."""
    insurer = create_insurer()
    insured = create_insured(insurer["id"])
    holder = create_certificate_holder(insurer["id"])
    return insurer, insured, holder


# ---------------------------------------------------------------------------
# Tier 1: policy state progression
# ---------------------------------------------------------------------------
def create_draft_policy(insurer_id, insured_id, policy_number="CGL-0001", **overrides) -> dict:
    resp = api_client.create_policy(
        factories.create_policy_payload(insurer_id, insured_id, policy_number, **overrides), UW)
    return get_success_data(resp)


def bind_policy(policy_id) -> dict:
    return get_success_data(api_client.bind_policy(policy_id, UW))


def activate_policy(policy_id) -> dict:
    return get_success_data(api_client.activate_policy(policy_id, UW))


def create_bound_policy(insurer_id=None, insured_id=None, policy_number="CGL-0001", **overrides):
    """Carrier + insured + DRAFT policy bound to BOUND. Returns (insurer, insured, policy)."""
    if insurer_id is None:
        insurer = create_insurer()
        insurer_id = insurer["id"]
    else:
        insurer = None
    if insured_id is None:
        insured = create_insured(insurer_id)
        insured_id = insured["id"]
    else:
        insured = None
    policy = create_draft_policy(insurer_id, insured_id, policy_number, **overrides)
    bind_policy(policy["id"])
    policy = get_success_data(api_client.get_policy(policy["id"], UW))
    return insurer, insured, policy


def create_in_force_policy(clock_to=CLOCK_MID, policy_number="CGL-0001", **overrides):
    """Carrier + insured + policy bound and activated to IN_FORCE, with the insurer
    clock advanced to `clock_to` (default mid-period). Returns (insurer, insured, policy)."""
    insurer = create_insurer()
    insured = create_insured(insurer["id"])
    policy = create_draft_policy(insurer["id"], insured["id"], policy_number, **overrides)
    bind_policy(policy["id"])
    activate_policy(policy["id"])
    if clock_to is not None:
        get_success_data(api_client.advance_clock(insurer["id"], {"to_iso8601": clock_to}, ADMIN))
    policy = get_success_data(api_client.get_policy(policy["id"], UW))
    return insurer, insured, policy


def create_expired_policy(policy_number="CGL-0001", **overrides):
    """Carrier + insured + policy taken all the way to EXPIRED (clock advanced past
    expiration). Returns (insurer, insured, policy)."""
    insurer = create_insurer_with_overrides(**_pop_insurer_overrides(overrides))
    insured = create_insured(insurer["id"])
    policy = create_draft_policy(insurer["id"], insured["id"], policy_number, **overrides)
    bind_policy(policy["id"])
    activate_policy(policy["id"])
    get_success_data(api_client.advance_clock(
        insurer["id"], {"to_iso8601": CLOCK_PAST_EXPIRY}, ADMIN))
    policy = get_success_data(api_client.get_policy(policy["id"], UW))
    return insurer, insured, policy


def _pop_insurer_overrides(overrides: dict) -> dict:
    """Pull insurer-specific kwargs out of a policy-overrides dict."""
    ins = {}
    if "audit_waiver_threshold_cents" in overrides:
        ins["audit_waiver_threshold_cents"] = overrides.pop("audit_waiver_threshold_cents")
    return ins


def create_insurer_with_overrides(**overrides) -> dict:
    return create_insurer(**overrides)


# ---------------------------------------------------------------------------
# Tier 2/3: claims and the OCC handshake
# ---------------------------------------------------------------------------
def current_policy_version(policy_id) -> int:
    return get_success_data(api_client.get_policy(policy_id, ADJ))["version"]


def open_claim(policy_id, **overrides) -> dict:
    resp = api_client.create_claim(factories.create_claim_payload(policy_id, **overrides), ADJ)
    return get_success_data(resp)


def post_first_reserve(claim_id, amount_cents) -> dict:
    """Opening RESERVE_SET — no expected_policy_version (PRD §2.8 exception)."""
    resp = api_client.post_transaction(
        claim_id, factories.create_transaction_payload("RESERVE_SET", amount_cents), ADJ)
    return get_success_data(resp)


def post_transaction_occ(policy_id, claim_id, txn_type, amount_cents, **extra) -> dict:
    """Post a non-opening transaction with the current policy version pinned (OCC handshake)."""
    version = current_policy_version(policy_id)
    payload = factories.create_transaction_payload(
        txn_type, amount_cents, expected_policy_version=version, **extra)
    return get_success_data(api_client.post_transaction(claim_id, payload, ADJ))


def create_reserved_claim(policy_id, amount_cents=5000000, **claim_overrides):
    """Open a claim and post its opening RESERVE_SET -> RESERVED. Returns the claim dict
    (re-fetched after the reserve)."""
    claim = open_claim(policy_id, **claim_overrides)
    post_first_reserve(claim["id"], amount_cents)
    return get_success_data(api_client.get_claim(claim["id"], ADJ))


def setup_in_force_with_reserved_claim(reserve_cents=5000000, claim_overrides=None, **policy_overrides):
    """IN_FORCE policy (clock mid-period) + one RESERVED claim.
    Returns (insurer, insured, policy, claim)."""
    insurer, insured, policy = create_in_force_policy(**policy_overrides)
    claim = create_reserved_claim(policy["id"], reserve_cents, **(claim_overrides or {}))
    return insurer, insured, policy, claim


# ---------------------------------------------------------------------------
# Tier 4: posture targeting
# ---------------------------------------------------------------------------
def setup_exhausted_policy():
    """IN_FORCE OCCURRENCE policy driven to posture EXHAUSTED: two GENERAL $1M claims
    (general agg 0) and one PRODUCTS $1M claim (products agg 0). Returns
    (insurer, insured, policy, [claim1, claim2, claim3])."""
    insurer, insured, policy = create_in_force_policy(clock_to=CLOCK_MID)
    pid = policy["id"]
    c1 = open_claim(pid, claimant_name="G1", loss_type="BODILY_INJURY",
                    occurrence_date="2026-03-01T00:00:00.000Z", reported_date="2026-03-02T00:00:00.000Z")
    post_first_reserve(c1["id"], 100000000)
    c2 = open_claim(pid, claimant_name="G2", loss_type="PROPERTY_DAMAGE",
                    occurrence_date="2026-03-03T00:00:00.000Z", reported_date="2026-03-04T00:00:00.000Z")
    post_transaction_occ(pid, c2["id"], "RESERVE_SET", 100000000)
    c3 = open_claim(pid, claimant_name="P1", loss_type="PRODUCTS_COMPLETED_OPS",
                    occurrence_date="2026-03-05T00:00:00.000Z", reported_date="2026-03-06T00:00:00.000Z")
    post_transaction_occ(pid, c3["id"], "RESERVE_SET", 100000000)
    policy = get_success_data(api_client.get_policy(pid, UW))
    return insurer, insured, policy, [c1, c2, c3]


# ---------------------------------------------------------------------------
# Tier 2: endorsements + certificates
# ---------------------------------------------------------------------------
def create_endorsement(policy_id, holder_id, **overrides) -> dict:
    resp = api_client.create_endorsement(
        factories.create_endorsement_payload(policy_id, holder_id, **overrides), UW)
    return get_success_data(resp)


def create_certificate(policy_id, holder_id, **overrides) -> dict:
    resp = api_client.create_certificate(
        factories.create_certificate_payload(policy_id, holder_id, **overrides), UW)
    return get_success_data(resp)


def issue_certificate(certificate_id) -> dict:
    return get_success_data(api_client.issue_certificate(certificate_id, UW))


def setup_in_force_with_issued_ai_cert():
    """IN_FORCE OCCURRENCE policy + holder + ACTIVE endorsement + AI COI ISSUED against it.
    Returns (insurer, insured, holder, policy, endorsement, certificate)."""
    insurer = create_insurer()
    insured = create_insured(insurer["id"])
    holder = create_certificate_holder(insurer["id"])
    policy = create_draft_policy(insurer["id"], insured["id"], "CGL-0001")
    bind_policy(policy["id"])
    activate_policy(policy["id"])
    endo = create_endorsement(policy["id"], holder["id"], form_number="CG2010",
                              ai_effective_date="2026-02-01T00:00:00.000Z")
    cert = create_certificate(policy["id"], holder["id"],
                              additional_insured_endorsement_id=endo["id"],
                              names_as_additional_insured=True)
    issue_certificate(cert["id"])
    policy = get_success_data(api_client.get_policy(policy["id"], UW))
    cert = get_success_data(api_client.get_certificate(cert["id"], UW))
    return insurer, insured, holder, policy, endo, cert


def setup_in_force_with_informational_issued_cert():
    """IN_FORCE OCCURRENCE policy + holder + informational COI ISSUED.
    Returns (insurer, insured, holder, policy, certificate)."""
    insurer = create_insurer()
    insured = create_insured(insurer["id"])
    holder = create_certificate_holder(insurer["id"])
    policy = create_draft_policy(insurer["id"], insured["id"], "CGL-0001")
    bind_policy(policy["id"])
    activate_policy(policy["id"])
    cert = create_certificate(policy["id"], holder["id"])
    issue_certificate(cert["id"])
    cert = get_success_data(api_client.get_certificate(cert["id"], UW))
    return insurer, insured, holder, policy, cert


# ---------------------------------------------------------------------------
# Tier 5: premium audit lifecycle
# ---------------------------------------------------------------------------
def schedule_audit(policy_id, audit_basis="PAYROLL") -> dict:
    resp = api_client.create_audit(factories.create_audit_payload(policy_id, audit_basis), AUD)
    return get_success_data(resp)


def add_exposure_record(audit_id, class_code="91560", basis_amount_units=1000000) -> dict:
    resp = api_client.create_exposure_record(
        audit_id, factories.create_exposure_record_payload(class_code, basis_amount_units), AUD)
    return get_success_data(resp)


def setup_completed_audit(exposure_units=1500000, waiver_threshold=None):
    """EXPIRED OCCURRENCE policy + audit started, one ExposureRecord, COMPLETED.
    Returns (insurer, insured, policy, audit)."""
    ins_overrides = {}
    if waiver_threshold is not None:
        ins_overrides["audit_waiver_threshold_cents"] = waiver_threshold
    insurer = create_insurer(**ins_overrides)
    insured = create_insured(insurer["id"])
    policy = create_draft_policy(insurer["id"], insured["id"], "CGL-0001")
    bind_policy(policy["id"])
    activate_policy(policy["id"])
    get_success_data(api_client.advance_clock(
        insurer["id"], {"to_iso8601": CLOCK_PAST_EXPIRY}, ADMIN))
    audit = schedule_audit(policy["id"], "PAYROLL")
    get_success_data(api_client.start_audit(audit["id"], AUD))
    add_exposure_record(audit["id"], "91560", exposure_units)
    audit = get_success_data(api_client.complete_audit(audit["id"], AUD))
    # Re-fetch the policy so callers see post-bind computed fields
    # (estimated_premium_cents, audited_premium_cents, aggregates, posture, version).
    policy = get_success_data(api_client.get_policy(policy["id"], UW))
    return insurer, insured, policy, audit


def setup_disputed_audit(exposure_units=1500000):
    """EXPIRED policy + audit COMPLETED then DISPUTED by admin.
    Returns (insurer, insured, policy, audit)."""
    insurer, insured, policy, audit = setup_completed_audit(exposure_units)
    audit = get_success_data(api_client.dispute_audit(audit["id"], ADMIN))
    return insurer, insured, policy, audit
