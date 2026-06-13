"""Additional-insured endorsements, certificates of insurance, their issuance gating,
and the supersede/void -> revoke cascades.

Covers Difficulty queue instances for the endorsement-supersede cascade, the AI-COI
active-endorsement dependency, and the half-open AI-effective-date window; plus Corner
queue instances for computed scope, issue idempotency, and filtered endorsement listing.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_endorsement,
    factories, fixtures,
)

UW = TEST_USERS["underwriter_headers"]


# ===========================================================================
# Difficulty/transitive_cascade/endorsement_supersede_cascades_coi_revocation
# ===========================================================================
def test_newer_endorsement_supersedes_and_revokes_issued_coi(api):
    """PRD §3.4: "If an `ACTIVE` endorsement already exists for the same `certificate_holder_id`
    on the same policy, creating the newer one moves the prior one from `ACTIVE` to `SUPERSEDED`,
    and any `ISSUED` certificate pointing at the superseded endorsement is revoked."

    Design: Difficulty/transitive_cascade/endorsement_supersede_cascades_coi_revocation
    """
    insurer, insured, holder, policy, endo1, cert = \
        fixtures.setup_in_force_with_issued_ai_cert()
    # Create a newer ACTIVE endorsement for the same holder on the same policy.
    endo2 = validate_success(api.create_endorsement(
        factories.create_endorsement_payload(policy["id"], holder["id"],
                                              form_number="CG2037",
                                              ai_effective_date="2026-03-01T00:00:00.000Z"), UW), 201)
    assert endo2["status"] == "ACTIVE"
    prior = validate_success(api.get_endorsement(endo1["id"], UW), 200)
    assert prior["status"] == "SUPERSEDED"
    coi = validate_success(api.get_certificate(cert["id"], UW), 200)
    assert coi["status"] == "REVOKED"


def test_void_endorsement_revokes_issued_coi(api):
    """PRD §3.4: "An `Underwriter` may also explicitly void an endorsement, moving it from
    `ACTIVE` to `VOID`; voiding likewise revokes any `ISSUED` certificate that points at it."

    Design: Difficulty/transitive_cascade/endorsement_supersede_cascades_coi_revocation
    """
    insurer, insured, holder, policy, endo1, cert = \
        fixtures.setup_in_force_with_issued_ai_cert()
    voided = validate_success(api.void_endorsement(endo1["id"], UW), 200)
    assert voided["status"] == "VOID"
    coi = validate_success(api.get_certificate(cert["id"], UW), 200)
    assert coi["status"] == "REVOKED"


# ===========================================================================
# Difficulty/cross_entity_state_dependency/ai_coi_issue_requires_active_endorsement
# ===========================================================================
def test_issue_ai_coi_after_endorsement_voided_rejected(api):
    """PRD §3.4: "if `names_as_additional_insured` is true, the certificate must reference,
    through its `additional_insured_endorsement_id`, an endorsement that is currently `ACTIVE`
    and whose `certificate_holder_id` equals the certificate's own `certificate_holder_id`; if no
    such active matching endorsement backs the assertion, issuance is rejected with
    `ERR_AI_ENDORSEMENT_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/ai_coi_issue_requires_active_endorsement
    """
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    holder = fixtures.create_certificate_holder(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-0013")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    endo1 = fixtures.create_endorsement(policy["id"], holder["id"], form_number="CG2010",
                                        ai_effective_date="2026-02-01T00:00:00.000Z")
    cert = fixtures.create_certificate(policy["id"], holder["id"],
                                       additional_insured_endorsement_id=endo1["id"],
                                       names_as_additional_insured=True)
    validate_success(api.void_endorsement(endo1["id"], UW), 200)
    # The DRAFT COI still references the now-VOID endorsement.
    resp = api.issue_certificate(cert["id"], UW)
    validate_error(resp, ApiErrorId.ERR_AI_ENDORSEMENT_MISSING.value, 409)
    after = validate_success(api.get_certificate(cert["id"], UW), 200)
    assert after["status"] == "DRAFT"


def test_issue_ai_coi_without_any_endorsement_rejected(api):
    """PRD §3.4: "if no such active matching endorsement backs the assertion, issuance is
    rejected with `ERR_AI_ENDORSEMENT_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/ai_coi_issue_requires_active_endorsement
    """
    # A COI asserting AI but with a null additional_insured_endorsement_id (no backing
    # endorsement at all). The policy is HEALTHY and IN_FORCE so the only failing gate is the
    # AI-endorsement requirement.
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    holder = fixtures.create_certificate_holder(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-AI-NULL")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    cert = fixtures.create_certificate(policy["id"], holder["id"],
                                       names_as_additional_insured=True)
    resp = api.issue_certificate(cert["id"], UW)
    validate_error(resp, ApiErrorId.ERR_AI_ENDORSEMENT_MISSING.value, 409)
    after = validate_success(api.get_certificate(cert["id"], UW), 200)
    assert after["status"] == "DRAFT"


# ===========================================================================
# Difficulty/resource_temporal_overlap/ai_endorsement_effective_date_half_open_policy_window
# ===========================================================================
def test_ai_effective_date_at_expiration_upper_bound_rejected(api):
    """PRD §3.4: "The `ai_effective_date` must fall within the policy period, at or after the
    `effective_date` and strictly before the `expiration_date`; otherwise the request is rejected
    with `ERR_AI_DATE_OUTSIDE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/ai_endorsement_effective_date_half_open_policy_window
    """
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    holder = fixtures.create_certificate_holder(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-0015")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    # ai_effective_date == expiration_date 2027-01-01 (the exclusive upper bound) -> rejected.
    resp = api.create_endorsement(
        factories.create_endorsement_payload(policy["id"], holder["id"], form_number="CG2010",
                                              ai_effective_date="2027-01-01T00:00:00.000Z"), UW)
    validate_error(resp, ApiErrorId.ERR_AI_DATE_OUTSIDE_PERIOD.value, 422)


def test_ai_effective_date_before_effective_lower_bound_rejected(api):
    """PRD §3.4: "The `ai_effective_date` must fall within the policy period, at or after the
    `effective_date` and strictly before the `expiration_date`; otherwise the request is rejected
    with `ERR_AI_DATE_OUTSIDE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/ai_endorsement_effective_date_half_open_policy_window
    """
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    holder = fixtures.create_certificate_holder(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-AI-LOW")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    # ai_effective_date 2025-12-31 is before the effective_date 2026-01-01 -> rejected.
    resp = api.create_endorsement(
        factories.create_endorsement_payload(policy["id"], holder["id"], form_number="CG2010",
                                              ai_effective_date="2025-12-31T00:00:00.000Z"), UW)
    validate_error(resp, ApiErrorId.ERR_AI_DATE_OUTSIDE_PERIOD.value, 422)


# ===========================================================================
# Corner/entities/endorsement_scope_computed_from_form_number
# ===========================================================================
def test_endorsement_scope_computed_from_form_number(api):
    """PRD §3.4: "The `form_number` is one of `CG2010` (ongoing operations), `CG2037` (completed
    operations), or `CG2010_2037` (both); from it the system derives the endorsement's `scope` —
    `ONGOING_OPS`, `COMPLETED_OPS`, or `BOTH` respectively."

    Design: Corner/entities/endorsement_scope_computed_from_form_number
    """
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    holder = fixtures.create_certificate_holder(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-C03")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    endo = validate_success(api.create_endorsement(
        factories.create_endorsement_payload(policy["id"], holder["id"], form_number="CG2037",
                                              ai_effective_date="2026-02-01T00:00:00.000Z"), UW), 201)
    assert_endorsement(endo)
    assert endo["scope"] == "COMPLETED_OPS"


# ===========================================================================
# Corner/state_machines/issue_certificate_twice_returns_invalid_state
# ===========================================================================
def test_issue_certificate_twice_returns_invalid_state(api):
    """PRD §3.4: "Issuing a certificate moves it from `DRAFT` to `ISSUED` and freezes a snapshot
    of the policy's coverage onto it."
    PRD §2.11: "Only then is the target resource's state checked to confirm the requested
    transition is legal from its current state (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/issue_certificate_twice_returns_invalid_state
    """
    insurer, insured, holder, policy, cert = \
        fixtures.setup_in_force_with_informational_issued_cert()
    resp = api.issue_certificate(cert["id"], UW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_certificate(cert["id"], UW), 200)
    assert after["status"] == "ISSUED"


# ===========================================================================
# Corner/endpoints/list_endorsements_filtered_by_certificate_holder_id
# ===========================================================================
def test_list_endorsements_filtered_by_certificate_holder_id(api):
    """PRD §3.9: "list endpoints filterable by the relevant foreign keys".

    Design: Corner/endpoints/list_endorsements_filtered_by_certificate_holder_id
    """
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    holder = fixtures.create_certificate_holder(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-C28")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    fixtures.create_endorsement(policy["id"], holder["id"], form_number="CG2010",
                                ai_effective_date="2026-02-01T00:00:00.000Z")
    data, meta = validate_paginated(
        api.list_endorsements(UW, params={"certificate_holder_id": holder["id"]}))
    assert len(data) == 1
    assert all(e["certificate_holder_id"] == holder["id"] for e in data)
