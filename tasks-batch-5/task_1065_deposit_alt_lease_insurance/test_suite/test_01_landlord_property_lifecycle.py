"""Landlord/Property onboarding: not-found errors, defaults, auth/RBAC gates, and the
Property re-enrollment cooldown buffer (PRD §3.1)."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    assert_property, ApiErrorId, make_landlord_headers, make_compliance_officer_headers,
    create_landlord, create_property, create_state_compliance_rule,
    activate_property, terminate_property, advance_clock,
    create_property_payload, create_state_compliance_rule_payload,
)


def test_landlord_get_not_found(api, compliance_officer_headers):
    """PRD §2.5: "Each not-found condition carries its own error identifier: an unresolvable
    landlord yields `ERR_LANDLORD_NOT_FOUND`, a renter yields `ERR_RENTER_NOT_FOUND`, a property
    yields `ERR_PROPERTY_NOT_FOUND`, a renter enrollment yields `ERR_RENTER_ENROLLMENT_NOT_FOUND`,
    a policy yields `ERR_POLICY_NOT_FOUND`, an invoice yields `ERR_INVOICE_NOT_FOUND`, a claim
    yields `ERR_CLAIM_NOT_FOUND`, a payout yields `ERR_PAYOUT_NOT_FOUND`, a subrogation case yields
    `ERR_SUBROGATION_CASE_NOT_FOUND`, and a recovery payment yields
    `ERR_RECOVERY_PAYMENT_NOT_FOUND` — all at HTTP 404."

    Design: Corner/entities/landlord_get_not_found
    """
    res = api.get_landlord(NON_EXISTENT_UUID, compliance_officer_headers)
    validate_error(res, ApiErrorId.ERR_LANDLORD_NOT_FOUND, expected_status=404)


def test_property_get_not_found(api, compliance_officer_headers):
    """PRD §2.5: "Each not-found condition carries its own error identifier: an unresolvable
    landlord yields `ERR_LANDLORD_NOT_FOUND`, a renter yields `ERR_RENTER_NOT_FOUND`, a property
    yields `ERR_PROPERTY_NOT_FOUND`, a renter enrollment yields `ERR_RENTER_ENROLLMENT_NOT_FOUND`,
    a policy yields `ERR_POLICY_NOT_FOUND`, an invoice yields `ERR_INVOICE_NOT_FOUND`, a claim
    yields `ERR_CLAIM_NOT_FOUND`, a payout yields `ERR_PAYOUT_NOT_FOUND`, a subrogation case yields
    `ERR_SUBROGATION_CASE_NOT_FOUND`, and a recovery payment yields
    `ERR_RECOVERY_PAYMENT_NOT_FOUND` — all at HTTP 404."

    Design: Corner/entities/property_get_not_found
    """
    res = api.get_property(NON_EXISTENT_UUID, compliance_officer_headers)
    validate_error(res, ApiErrorId.ERR_PROPERTY_NOT_FOUND, expected_status=404)


def test_property_creation_defaults_pending_review_and_zero_claims(api):
    """PRD §3.1: "A newly listed property starts in `PENDING_REVIEW` with
    `total_paid_claims_cents` initialized to zero, and cannot receive renter applications until a
    `ComplianceOfficer` activates it."

    Design: Corner/entities/property_creation_defaults_pending_review_and_zero_claims
    """
    landlord = create_landlord()
    res = api.create_property(create_property_payload(landlord["id"]), make_landlord_headers(landlord["id"]))
    prop = validate_success(res, 201)
    assert_property(prop)
    assert prop["program_status"] == "PENDING_REVIEW"
    assert prop["total_paid_claims_cents"] == 0


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` value that is
    not one of the roles enumerated below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    res = api.get_property(NON_EXISTENT_UUID, {})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_renter_role_cannot_configure_state_compliance_rules(api, renter_headers):
    """PRD §2.1: "A request from an authenticated caller whose role is not permitted to perform
    the specific operation being attempted is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 endpoint table: `POST /state-compliance-rules` is authorized only for `ComplianceOfficer`.

    Design: Corner/validations/renter_role_cannot_configure_state_compliance_rules
    """
    res = api.create_state_compliance_rule(
        create_state_compliance_rule_payload("OR"), renter_headers
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_property_reactivation_before_cooldown_buffer_rejected(api):
    """PRD §3.1: "Termination is not necessarily permanent: a `TERMINATED` property can be
    re-activated with another `ACTIVATE` action, but only once a cooling-off period has fully
    elapsed." "Attempting to reactivate before the buffer has elapsed is rejected with
    `ERR_REENROLLMENT_COOLDOWN_ACTIVE` (HTTP 409); a successful reactivation clears
    `terminated_at` back to null."

    Design: Difficulty/resource_temporal_overlap/property_reenrollment_before_cooldown_buffer_elapses
    """
    landlord = create_landlord()
    prop = create_property(landlord, state_code="CA")
    create_state_compliance_rule("CA", cooling_off_buffer_days=30)
    prop = activate_property(prop["id"])
    advance_clock("2026-09-01T00:00:00Z")
    prop = terminate_property(prop["id"])
    assert prop["program_status"] == "TERMINATED"

    res = api.update_property_program_status(
        prop["id"], {"action": "ACTIVATE"}, make_compliance_officer_headers()
    )
    validate_error(res, ApiErrorId.ERR_REENROLLMENT_COOLDOWN_ACTIVE, expected_status=409)
    after = validate_success(api.get_property(prop["id"], make_compliance_officer_headers()), 200)
    assert after["program_status"] == "TERMINATED"


def test_property_reactivation_exactly_at_cooldown_buffer_succeeds(api):
    """PRD §3.1: "That period is state-specific — it is the `cooling_off_buffer_days` value from
    the `StateComplianceRule` governing the property's `state_code` — and re-activation is
    measured from `terminated_at`: the current clock time must be at or after `terminated_at`
    plus that many days." "a successful reactivation clears `terminated_at` back to null."

    Design: Difficulty/resource_temporal_overlap/property_reenrollment_before_cooldown_buffer_elapses
    """
    landlord = create_landlord()
    prop = create_property(landlord, state_code="CA")
    create_state_compliance_rule("CA", cooling_off_buffer_days=30)
    prop = activate_property(prop["id"])
    advance_clock("2026-09-01T00:00:00Z")
    prop = terminate_property(prop["id"])

    advance_clock("2026-10-01T00:00:00Z")  # exactly 30 days after terminated_at
    res = api.update_property_program_status(
        prop["id"], {"action": "ACTIVATE"}, make_compliance_officer_headers()
    )
    reactivated = validate_success(res, 200)
    assert reactivated["program_status"] == "ACTIVE"
    assert reactivated["terminated_at"] is None
