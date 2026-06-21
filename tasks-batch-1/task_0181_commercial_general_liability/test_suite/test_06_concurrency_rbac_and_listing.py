"""Optimistic concurrency on the policy version, RBAC peer-role isolation, the auth
gate, validation precedence (auth over state), and filtered listing.

Covers Difficulty queue instances for the auth-beats-state precedence pair; plus Corner
queue instances for the two OCC stale-version rejections, role denials, the missing-auth
gate, and a filtered claims list.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    factories, fixtures,
)
from test_helpers import make_certificate_holder_headers

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
AUD = TEST_USERS["premium_auditor_headers"]


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_on_audit_dispute
# ===========================================================================
def test_forbidden_role_beats_invalid_state_on_audit_dispute(api):
    """PRD §2.11: "Authentication comes first: a missing or malformed user context
    (`ERR_MISSING_USER_CONTEXT`) is detected before anything else, then role authorization
    (`ERR_FORBIDDEN_FOR_ROLE`). ... Only then is the target resource's state checked to confirm
    the requested transition is legal from its current state (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_on_audit_dispute
    """
    # SCHEDULED audit (wrong state for dispute) dispute-attempted by an Underwriter (dispute is
    # InsurerAdmin-only). Role authorization outranks the state check -> 403, not 409.
    insurer, insured, policy = fixtures.create_expired_policy(policy_number="CGL-0008")
    audit = fixtures.schedule_audit(policy["id"], "PAYROLL")  # SCHEDULED
    resp = api.dispute_audit(audit["id"], UW)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)
    after = validate_success(api.get_audit(audit["id"], AUD), 200)
    assert after["status"] == "SCHEDULED"


def test_forbidden_role_beats_invalid_state_on_audit_start(api):
    """PRD §2.11: "then role authorization (`ERR_FORBIDDEN_FOR_ROLE`). ... Only then is the
    target resource's state checked to confirm the requested transition is legal from its current
    state (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_on_audit_dispute
    """
    # A COMPLETED audit (start would be an illegal transition) start-attempted by an Underwriter
    # (start is PremiumAuditor-only). Role check outranks state check -> 403, not 409.
    insurer, insured, policy, audit = fixtures.setup_completed_audit(exposure_units=1500000)
    resp = api.start_audit(audit["id"], UW)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)
    after = validate_success(api.get_audit(audit["id"], AUD), 200)
    assert after["status"] == "COMPLETED"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/stale_policy_version_negative_on_claim_transaction
# ===========================================================================
def test_stale_policy_version_on_claim_transaction_rejected(api):
    """PRD §2.8: "a transaction must carry `expected_policy_version` equal to the policy's current
    `version` at the moment it is posted. If a prior transaction — on this claim or any sibling
    claim under the same policy — has since eroded an aggregate and advanced the policy's
    `version`, the adjuster's view of remaining room is stale and the post is rejected with
    `ERR_STALE_POLICY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_policy_version_negative_on_claim_transaction
    """
    insurer, insured, policy = fixtures.create_in_force_policy(
        policy_number="CGL-C32",
        each_occurrence_limit_cents=1000000000,
        general_aggregate_limit_cents=2000000000,
        products_aggregate_limit_cents=1000000000)
    claim = fixtures.open_claim(policy["id"], claimant_name="W",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 10000000)
    pv_stale = fixtures.current_policy_version(policy["id"])
    # First post with pv_stale succeeds and advances the version.
    validate_success(api.post_transaction(
        claim["id"],
        factories.create_transaction_payload("RESERVE_SET", 20000000, expected_policy_version=pv_stale),
        ADJ), 201)
    # Re-supplying the now-stale version fails.
    resp = api.post_transaction(
        claim["id"],
        factories.create_transaction_payload("RESERVE_SET", 30000000, expected_policy_version=pv_stale),
        ADJ)
    validate_error(resp, ApiErrorId.ERR_STALE_POLICY_VERSION.value, 412)
    after = validate_success(api.get_claim(claim["id"], ADJ), 200)
    # Only the first two reserves applied: 10000000 + 20000000.
    assert after["incurred_cents"] == 30000000


# ===========================================================================
# Corner/cross_cutting_complexity_layers/stale_policy_version_on_audit_finalize
# ===========================================================================
def test_stale_policy_version_on_audit_finalize_rejected(api):
    """PRD §2.8: "it must carry `expected_policy_version` matching the policy's current `version`.
    If a late claim transaction has advanced the policy's `version` since the auditor computed the
    net adjustment, the figure was computed against a policy state that no longer holds, and the
    finalize is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_policy_version_on_audit_finalize
    """
    insurer, insured, policy, audit = fixtures.setup_completed_audit(exposure_units=1500000)
    pv = fixtures.current_policy_version(policy["id"])
    # Supply a version one less than current to force a deterministic mismatch.
    resp = api.finalize_audit(audit["id"], {"expected_policy_version": pv - 1}, AUD)
    validate_error(resp, ApiErrorId.ERR_STALE_POLICY_VERSION.value, 412)
    after = validate_success(api.get_audit(audit["id"], AUD), 200)
    assert after["status"] == "COMPLETED"
    pol = validate_success(api.get_policy(policy["id"], UW), 200)
    assert pol["status"] == "EXPIRED"


# ===========================================================================
# Corner/rbac/claims_adjuster_cannot_create_policy
# ===========================================================================
def test_claims_adjuster_cannot_create_policy(api):
    """PRD §4 endpoint table: "POST `/policies` | Create a draft policy | Underwriter".
    PRD §2.1: "When a well-identified user invokes an operation their role is not permitted to
    perform, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/claims_adjuster_cannot_create_policy
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    resp = api.create_policy(
        factories.create_policy_payload(insurer["id"], insured["id"], "CGL-C29"), ADJ)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)


# ===========================================================================
# Corner/rbac/underwriter_cannot_post_claim_transaction
# ===========================================================================
def test_underwriter_cannot_post_claim_transaction(api):
    """PRD §4 endpoint table: "POST `/claims/{claimId}/transactions` | Post a financial
    transaction on a claim | ClaimsAdjuster".
    PRD §2.1: "When a well-identified user invokes an operation their role is not permitted to
    perform, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/underwriter_cannot_post_claim_transaction
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-C30")
    claim = fixtures.open_claim(policy["id"], claimant_name="V",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    resp = api.post_transaction(
        claim["id"], factories.create_transaction_payload("RESERVE_SET", 5000000), UW)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)
    after = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after["status"] == "OPEN"


# ===========================================================================
# Corner/rbac/certificate_holder_cannot_issue_certificate
# ===========================================================================
def test_certificate_holder_cannot_issue_certificate(api):
    """PRD §2.1: "The `CertificateHolder` is a third party with read-only reach into the data
    relevant to its certificates."
    PRD §4 endpoint table: "POST `/certificates/{certificateId}/issue` | Issue (snapshot) a
    certificate | Underwriter".

    Design: Corner/rbac/certificate_holder_cannot_issue_certificate
    """
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    holder = fixtures.create_certificate_holder(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-C31")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    cert = fixtures.create_certificate(policy["id"], holder["id"])
    # Acting CertificateHolder identity is the holder's own id (entity-backed role).
    resp = api.issue_certificate(cert["id"], make_certificate_holder_headers(holder["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)
    after = validate_success(api.get_certificate(cert["id"], UW), 200)
    assert after["status"] == "DRAFT"


# ===========================================================================
# Corner/rbac/missing_user_context_header_rejected
# ===========================================================================
def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one, is rejected with
    `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    insurer = fixtures.create_insurer()
    resp = api.get_insurer(insurer["id"], {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value, 401)


# ===========================================================================
# Corner/endpoints/list_claims_filtered_by_policy_id
# ===========================================================================
def test_list_claims_filtered_by_policy_id(api):
    """PRD §3.9: "list endpoints filterable by the relevant foreign keys".
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope."

    Design: Corner/endpoints/list_claims_filtered_by_policy_id
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-C27")
    fixtures.open_claim(policy["id"], claimant_name="U1", loss_type="BODILY_INJURY",
                        occurrence_date="2026-03-01T00:00:00.000Z",
                        reported_date="2026-03-02T00:00:00.000Z")
    fixtures.open_claim(policy["id"], claimant_name="U2", loss_type="PROPERTY_DAMAGE",
                        occurrence_date="2026-03-03T00:00:00.000Z",
                        reported_date="2026-03-04T00:00:00.000Z")
    data, meta = validate_paginated(api.list_claims(ADJ, params={"policy_id": policy["id"]}))
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert all(c["policy_id"] == policy["id"] for c in data)
