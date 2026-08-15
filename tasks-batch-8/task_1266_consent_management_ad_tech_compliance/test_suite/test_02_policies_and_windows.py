"""Jurisdiction policy lifecycle and half-open coverage-window rules."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_property, create_active_policy,
    create_property_payload, create_jurisdiction_policy_payload,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
VM = TEST_USERS["vendor_manager_headers"]
ANY = TEST_USERS["any_headers"]


def test_policy_window_adjacency_activated():
    """PRD section 3.1: "Adjacency is explicitly permitted — a successor policy
    whose `effective_from` equals the predecessor's `effective_to` activates
    cleanly, while a start even one day earlier collides and is rejected with
    `ERR_POLICY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_window_half_open_adjacency_allowed
    """
    prop = create_property(name="Window Site", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(
        prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_IN_REQUIRED",
        min_consent_age=16, retention_days=30, gpc_honored=False,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z",
    )
    pol_b = get_success_data(
        api_client_create_policy(prop["id"], effective_from="2026-06-01T00:00:00Z",
                                 effective_to="2027-01-01T00:00:00Z")
    )
    from test_helpers import api_client
    res = api_client.update_jurisdiction_policy(pol_b["id"], {"status": "ACTIVE"}, ADMIN)
    activated = validate_success(res, 200)
    assert activated["status"] == "ACTIVE", (
        "effective_from 2026-06-01 == A.effective_to: half-open adjacency is not an overlap"
    )


def api_client_create_policy(prop_id, effective_from, effective_to):
    from test_helpers import api_client
    return api_client.create_jurisdiction_policy(
        create_jurisdiction_policy_payload(
            prop_id, jurisdiction_code="US-CA", banner_regime="OPT_IN_REQUIRED",
            min_consent_age=16, retention_days=30, gpc_honored=False,
            effective_from=effective_from, effective_to=effective_to,
        ),
        ADMIN,
    )


def test_policy_window_one_day_overlap_rejected():
    """PRD section 3.1: "Adjacency is explicitly permitted — a successor policy
    whose `effective_from` equals the predecessor's `effective_to` activates
    cleanly, while a start even one day earlier collides and is rejected with
    `ERR_POLICY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_window_half_open_adjacency_allowed
    """
    prop = create_property(name="Window Site", sale_share_designation="NO_SALE_NO_SHARE")
    create_active_policy(
        prop["id"], jurisdiction_code="US-CA", banner_regime="OPT_IN_REQUIRED",
        min_consent_age=16, retention_days=30, gpc_honored=False,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z",
    )
    pol_c = get_success_data(
        api_client_create_policy(prop["id"], effective_from="2026-05-31T00:00:00Z",
                                 effective_to="2026-12-01T00:00:00Z")
    )
    from test_helpers import api_client
    res = api_client.update_jurisdiction_policy(pol_c["id"], {"status": "ACTIVE"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP)


def test_policy_retire_from_draft_rejected(api):
    """PRD section 3.1: "a `PrivacyAdmin` activates it and later retires it
    through status updates (`DRAFT → ACTIVE → RETIRED`, each step via the policy
    update operation; attempting `RETIRED` directly from `DRAFT` fails with
    `ERR_POLICY_INVALID_TRANSITION`)."

    Design: Corner/state_machines/policy_retire_from_draft_rejected
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    pol = get_success_data(
        api.create_jurisdiction_policy(
            create_jurisdiction_policy_payload(prop["id"]), ADMIN
        )
    )
    res = api.update_jurisdiction_policy(pol["id"], {"status": "RETIRED"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_POLICY_INVALID_TRANSITION)


def test_vendor_manager_cannot_activate_policy(api):
    """PRD section 2.1: "an attempt to perform an action outside the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."
    PRD section 4: "PUT | `/v1/jurisdiction-policies/{id}` | Transition status or
    amend retention | PrivacyAdmin".

    Design: Corner/rbac/vendor_manager_cannot_activate_policy
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    pol = get_success_data(
        api.create_jurisdiction_policy(
            create_jurisdiction_policy_payload(prop["id"]), ADMIN
        )
    )
    res = api.update_jurisdiction_policy(pol["id"], {"status": "ACTIVE"}, VM)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_policy_get_not_found_returns_404(api):
    """PRD section 2.8: "Existence — every identifier referenced by the path or
    body must exist, checked left to right, surfacing the resource-specific
    not-found error (`ERR_PROPERTY_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, ...)."

    Design: Corner/errors/policy_get_not_found_returns_404
    """
    res = api.get_jurisdiction_policy(NON_EXISTENT_UUID, ANY)
    validate_error(res, ApiErrorId.ERR_POLICY_NOT_FOUND)
