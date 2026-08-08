"""Provider credentialing: the credential-safety-over-consent precedence, the
claim-submit credential gate, and the closed-interval activation overlap rule.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    make_service_provider_headers,
    setup_billing_context, setup_claim_with_verified_log,
    create_provider, create_credential,
    api_client,
)

MC = TEST_USERS["medicaid_coordinator_headers"]
BC = TEST_USERS["billing_coordinator_headers"]


def _create_log_attempt(ctx):
    return api_client.create_service_log({
        "iep_authorization_id": ctx["authorization"]["id"], "provider_id": ctx["provider"]["id"],
        "student_id": ctx["student"]["id"], "service_date": "2026-03-01",
        "start_time": "2026-03-01T09:00:00Z", "end_time": "2026-03-01T09:40:00Z",
        "delivered_minutes": 40}, make_service_provider_headers(ctx["provider"]["id"]))


# --- priority_pair_validation_conflict / credential_safety_beats_consent -----
def test_service_log_credential_error_outranks_consent_error(api):
    """PRD §3.4: "Creation runs a chain of business guards in this order: the
    delivering provider must have an ACTIVE credential whose closed window covers
    the service_date, else ERR_PROVIDER_NOT_CREDENTIALED (HTTP 422); the student
    must have a BILLING consent in status GRANTED, else ERR_CONSENT_NOT_GRANTED
    (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/service_log_credential_safety_beats_consent_referential
    """
    # Credential left PENDING (not active) AND consent left PENDING (not granted).
    ctx = setup_billing_context(cred_overrides={"activate": False}, grant_consent=False)
    validate_error(_create_log_attempt(ctx), ApiErrorId.ERR_PROVIDER_NOT_CREDENTIALED)


def test_service_log_consent_error_fires_once_credential_passes(api):
    """PRD §3.4: "the delivering provider must have an ACTIVE credential whose
    closed window covers the service_date, else ERR_PROVIDER_NOT_CREDENTIALED
    (HTTP 422); the student must have a BILLING consent in status GRANTED, else
    ERR_CONSENT_NOT_GRANTED (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/service_log_credential_safety_beats_consent_referential
    """
    # Credential ACTIVE (passes the higher-priority guard); consent still PENDING.
    ctx = setup_billing_context(grant_consent=False)
    validate_error(_create_log_attempt(ctx), ApiErrorId.ERR_CONSENT_NOT_GRANTED)


# --- cross_entity_state_dependency / claim_submit_requires_active_credential -
def test_submit_rejected_when_credential_suspended(api):
    """PRD §3.5: "for every attached log, the delivering provider must hold an
    ACTIVE credential whose closed window covers that log's service_date, else
    ERR_PROVIDER_NOT_CREDENTIALED (HTTP 422)".

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_active_credential
    """
    ctx = setup_claim_with_verified_log()
    get_success_data(api.suspend_credential(ctx["credential"]["id"], {"reason": "audit"}, MC))
    resp = api.submit_claim(ctx["claim"]["id"], BC)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_CREDENTIALED)
    assert get_success_data(api.get_claim(ctx["claim"]["id"], MC))["status"] == "DRAFT"


def test_submit_succeeds_after_credential_reinstated(api):
    """PRD §3.2: "a suspended credential may be reinstated by activating it again,
    which returns it to ACTIVE under the same non-overlap guard."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_active_credential
    """
    ctx = setup_claim_with_verified_log()
    get_success_data(api.suspend_credential(ctx["credential"]["id"], {"reason": "audit"}, MC))
    get_success_data(api.activate_credential(ctx["credential"]["id"], MC))
    submitted = validate_success(api.submit_claim(ctx["claim"]["id"], BC))
    assert submitted["status"] == "SUBMITTED"


# --- resource_temporal_overlap / provider_credential_closed_interval_overlap -
def test_credential_activation_touching_window_rejected(api):
    """PRD §3.2: "Two closed windows overlap when they share any point, so windows
    that merely touch at an endpoint are treated as overlapping; a violating
    activation is rejected with ERR_CREDENTIAL_PERIOD_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/provider_credential_closed_interval_overlap
    """
    provider = create_provider(discipline="PT")
    create_credential(provider["id"], activate=True, credential_type="STATE_LICENSE",
                      license_number="LA", effective_date="2026-01-01", expiration_date="2026-06-30")
    cred_b = create_credential(provider["id"], activate=False, credential_type="STATE_LICENSE",
                               license_number="LB", effective_date="2026-06-30", expiration_date="2026-12-31")
    resp = api.activate_credential(cred_b["id"], MC)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_PERIOD_OVERLAP)
    assert get_success_data(api.get_credential(cred_b["id"], MC))["status"] == "PENDING"


def test_credential_activation_disjoint_window_allowed(api):
    """PRD §3.2: "Activating a pending credential moves it to ACTIVE; activation is
    refused with ERR_INVALID_STATE if the credential is not currently PENDING or
    SUSPENDED. Activation carries an additional guard: it must not produce two
    ACTIVE credentials for the same provider_id and the same credential_type whose
    closed validity windows overlap."

    Design: Difficulty/resource_temporal_overlap/provider_credential_closed_interval_overlap
    """
    provider = create_provider(discipline="PT")
    create_credential(provider["id"], activate=True, credential_type="STATE_LICENSE",
                      license_number="LA", effective_date="2026-01-01", expiration_date="2026-06-30")
    cred_b = create_credential(provider["id"], activate=False, credential_type="STATE_LICENSE",
                               license_number="LB", effective_date="2026-07-01", expiration_date="2026-12-31")
    activated = validate_success(api.activate_credential(cred_b["id"], MC))
    assert activated["status"] == "ACTIVE"
