"""Patient portal lifecycle, role-based access control, uniqueness errors, and
list endpoints (pagination + reverse-reachability filtering).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_provider_headers, make_patient_headers,
    TEST_USERS,
    create_provider,
    create_patient,
    create_cpt_code,
    create_visit,
    create_coded_visit,
    create_portal_account,
    create_active_portal_account,
)

FD = TEST_USERS["frontdesk_headers"]
BILLER = TEST_USERS["biller_headers"]


# ─── Queue B: state_machines / portal_active_suspend_reinstate_cycle ───

def test_portal_suspend_then_reinstate_cycle(api):
    """PRD §3.9: "A suspended account can be reinstated, moving from `SUSPENDED` back to
    `ACTIVE` and resetting `failed_login_count` to 0 — the suspend-and-reinstate pair
    forms a cycle."

    Design: Corner/state_machines/portal_active_suspend_reinstate_cycle
    """
    patient, account = create_active_portal_account()
    validate_success(api.suspend_portal_account(account["id"], FD), 200)
    reinstated = validate_success(api.reinstate_portal_account(account["id"], FD), 200)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["failed_login_count"] == 0


# ─── Queue B: state_machines / portal_wrong_token_auto_suspends_at_threshold ───

def test_portal_three_wrong_tokens_auto_suspend(api):
    """PRD §3.9: "When the supplied token does not match, the `failed_login_count` is
    incremented; if that increment brings the count to the lockout threshold of 3, the
    account auto-suspends, moving from `INVITED` to `SUSPENDED`."

    Design: Corner/state_machines/portal_wrong_token_auto_suspends_at_threshold
    """
    patient = create_patient()
    account, _token = create_portal_account(patient["id"])
    pat_hdr = make_patient_headers(patient["id"])
    api.activate_portal_account(account["id"], {"activation_token": "WRONG-1"}, pat_hdr)
    api.activate_portal_account(account["id"], {"activation_token": "WRONG-2"}, pat_hdr)
    third = validate_success(
        api.activate_portal_account(account["id"], {"activation_token": "WRONG-3"}, pat_hdr), 200
    )
    assert third["status"] == "SUSPENDED"
    assert third["failed_login_count"] == 3


# ─── Queue B: rbac / patient_cannot_create_visit_forbidden ───

def test_patient_cannot_create_visit(api):
    """PRD §2.1: "When a role is authenticated but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/patient_cannot_create_visit_forbidden
    """
    provider = create_provider()
    patient = create_patient()
    pat_hdr = make_patient_headers(patient["id"])
    res = api.create_visit({
        "patient_id": patient["id"], "provider_id": provider["id"],
        "visit_type": "CONSULTATION",
        "scheduled_start": "2026-06-01T09:00:00Z", "scheduled_end": "2026-06-01T09:30:00Z",
    }, pat_hdr)
    validate_error(res, "ERR_FORBIDDEN")


# ─── Queue B: rbac / provider_cannot_finalize_visit_forbidden ───

def test_provider_cannot_finalize_visit(api):
    """PRD §3.6: "Finalizing a visit is a `Biller` action permitted only when the visit
    is `CODED`, transitioning the visit from `CODED` to `FINALIZED`."

    Design: Corner/rbac/provider_cannot_finalize_visit_forbidden
    """
    provider, patient, cpt, visit = create_coded_visit(
        cpt_overrides={"category": "EM", "base_fee_cents": 8000, "requires_em_level": True},
        charge_overrides={"units": 1, "em_level": 3},
    )
    prov_hdr = make_provider_headers(provider["id"])
    res = api.finalize_visit(visit["id"], prov_hdr)
    validate_error(res, "ERR_FORBIDDEN")


# ─── Queue B: rbac / provider_start_visit_not_owner_returns_403 ───

def test_provider_start_visit_not_owner(api):
    """PRD §2.1: "only the provider whose `id` equals a visit's `provider_id` may start
    or code that visit."
    PRD §2.1: "A violation of an entity-backed ownership check — an authenticated and
    role-permitted actor who is nonetheless not the owner or authorized provider of the
    target resource — is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/provider_start_visit_not_owner_returns_403
    """
    provider_a = create_provider()
    provider_b = create_provider()
    patient = create_patient()
    visit = create_visit(patient["id"], provider_a["id"])
    validate_success(api.check_in_visit(visit["id"], FD), 200)
    # Provider B (not the rendering provider) attempts to start.
    res = api.start_visit(visit["id"], make_provider_headers(provider_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ─── Queue B: rbac / missing_auth_headers_returns_401 ───

def test_missing_auth_headers(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    res = api.list_patients({})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Queue B: errors / duplicate_npi_returns_409 ───

def test_duplicate_npi(api):
    """PRD §3.1: "it must be unique across all providers, and a duplicate is rejected
    with `ERR_DUPLICATE_NPI`."

    Design: Corner/errors/duplicate_npi_returns_409
    """
    validate_success(api.create_provider(
        {"npi": "2000000050", "full_name": "Dr AE", "specialty": "FAMILY_MEDICINE"}, FD), 201)
    res = api.create_provider(
        {"npi": "2000000050", "full_name": "Dr AF", "specialty": "FAMILY_MEDICINE"}, FD)
    validate_error(res, "ERR_DUPLICATE_NPI")


# ─── Queue B: errors / duplicate_cpt_code_returns_409 ───

def test_duplicate_cpt_code(api):
    """PRD §3.3: "The `code` must be exactly 5 characters and unique across all codes; a
    duplicate is rejected with `ERR_DUPLICATE_CPT_CODE`."

    Design: Corner/errors/duplicate_cpt_code_returns_409
    """
    validate_success(api.create_cpt_code(
        {"code": "DUP01", "short_description": "First", "category": "EM", "base_fee_cents": 5000}, BILLER), 201)
    res = api.create_cpt_code(
        {"code": "DUP01", "short_description": "Second", "category": "EM", "base_fee_cents": 6000}, BILLER)
    validate_error(res, "ERR_DUPLICATE_CPT_CODE")


# ─── Queue B: errors / duplicate_portal_account_returns_409 ───

def test_duplicate_portal_account(api):
    """PRD §3.9: "A patient may have only one portal account, so the `patient_id` must
    be unique across portal accounts, and the `login_email` must likewise be unique; a
    violation of either uniqueness rule is rejected with `ERR_DUPLICATE_PORTAL_ACCOUNT`."

    Design: Corner/errors/duplicate_portal_account_returns_409
    """
    patient = create_patient()
    validate_success(api.create_portal_account(
        {"patient_id": patient["id"], "login_email": "dup1@example.com"}, FD), 201)
    res = api.create_portal_account(
        {"patient_id": patient["id"], "login_email": "dup2@example.com"}, FD)
    validate_error(res, "ERR_DUPLICATE_PORTAL_ACCOUNT")


# ─── Queue B: endpoints / list_patients_pagination_envelope ───

def test_list_patients_pagination_envelope(api):
    """PRD §2.3: "`total_count` reflects the size of the full filtered collection before
    the page window is applied, and `has_more` is true when records remain beyond the
    current page."

    Design: Corner/endpoints/list_patients_pagination_envelope
    """
    create_patient(first_name="List", last_name="One")
    create_patient(first_name="List", last_name="Two", sex="F")
    data, meta = validate_paginated(api.list_patients(FD, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Queue B: endpoints / filter_visits_by_provider_id_reverse_reachability ───

def test_filter_visits_by_provider_id(api):
    """PRD §2.3: "Every list-based response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope. `total_count` reflects the size of
    the full filtered collection before the page window is applied."

    Design: Corner/endpoints/filter_visits_by_provider_id_reverse_reachability
    """
    provider = create_provider()
    patient = create_patient()
    visit = create_visit(patient["id"], provider["id"])
    data, meta = validate_paginated(api.list_visits(FD, params={"provider_id": provider["id"]}))
    assert meta["total_count"] == 1
    assert any(v["id"] == visit["id"] for v in data), (
        "the provider's visit must appear in the provider-filtered list"
    )
