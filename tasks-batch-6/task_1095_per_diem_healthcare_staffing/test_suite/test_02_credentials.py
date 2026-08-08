"""Credential lifecycle: verify / reject / expire / renew, and the cross-entity
dependency where a claim is blocked because the clinician's licence is not yet
VERIFIED.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_clinician_headers,
    fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _setup_pending_credential_shift():
    """Facility requiring RN_LICENSE + rate card + ACTIVE clinician holding an
    unverified RN_LICENSE + one OPEN shift. Returns (fac_id, cl_id, cred, sh_id)."""
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Oak Hollow")
    fx.add_rate_card(fac["id"], base_pay_rate_cents_per_hour=7500)
    cl = fx.new_clinician(full_name="Nia Fowler", email="nia.fowler@example.com", specialty="RN")
    cred = fx.add_credential(cl["id"], expires_on="2027-01-01T00:00:00Z")
    order = fx.new_order(fac["id"])
    shift = fx.add_shift(order["id"], fac["id"])
    return fac["id"], cl["id"], cred, shift["id"]


def test_verify_from_rejected_returns_credential_not_pending(api):
    """PRD 3.2: "Verifying or rejecting a credential that is not in
    `PENDING_VERIFICATION` (and not, per the renewal case below, in `EXPIRED`) is
    refused with `ERR_CREDENTIAL_NOT_PENDING`."

    Design: Corner/state_machines/verify_credential_from_rejected_returns_credential_not_pending
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    cl = fx.new_clinician(full_name="Vic Alarcon", email="vic.alarcon@example.com", specialty="RN")
    cred = fx.add_credential(cl["id"])
    rejected = validate_success(
        api.verify_credential(
            cred["id"], {"decision": "REJECTED", "note": "licence number does not match the state registry"}, OFFICER
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    resp = api.verify_credential(cred["id"], {"decision": "VERIFIED"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_PENDING.value, 409)
    after = validate_success(api.list_credentials(cl["id"], OFFICER), 200)
    assert after[0]["status"] == "REJECTED"
    assert after[0]["verified_at"] is None


def test_credential_expires_then_renews_back_to_verified(api):
    """PRD 3.2: "Whenever a credential is read or consulted during a compliance check
    and the current clock instant is at or after its `expires_on`, it is lazily moved
    `VERIFIED → EXPIRED`, setting `status` to `EXPIRED` and bumping `version`."
    PRD 3.2: "a `ComplianceOfficer` verifying it with a decision of `VERIFIED` and a
    supplied `expires_on` strictly after the current instant moves it
    `EXPIRED → VERIFIED`, updating `expires_on`, `verified_at`, and
    `verified_by_user_id` and bumping `version`."

    Design: Corner/state_machines/credential_expires_then_renews_back_to_verified
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    cl = fx.new_clinician(full_name="Wren Baptista", email="wren.baptista@example.com", specialty="RN")
    cred = fx.add_credential(cl["id"], expires_on="2026-07-01T00:00:00Z")
    verified = validate_success(api.verify_credential(cred["id"], {"decision": "VERIFIED"}, OFFICER), 200)
    assert verified["status"] == "VERIFIED"
    assert verified["verified_at"] == "2026-06-01T00:00:00.000Z"

    fx.set_clock("2026-07-02T00:00:00Z")
    listed = validate_success(api.list_credentials(cl["id"], OFFICER), 200)
    assert listed[0]["status"] == "EXPIRED"

    renewed = validate_success(
        api.verify_credential(
            cred["id"], {"decision": "VERIFIED", "expires_on": "2027-07-01T00:00:00Z", "note": "renewal on file"}, OFFICER
        ),
        200,
    )
    assert renewed["status"] == "VERIFIED"
    assert renewed["verified_at"] == "2026-07-02T00:00:00.000Z"
    # expires_on is a client-supplied input; PRD's 3-fractional-digit render rule
    # (§2) is scoped to server-stamped fields (created_at, verified_at, ...) and
    # does not enumerate expires_on, so the impl echoes the supplied value verbatim.
    assert renewed["expires_on"] == "2027-07-01T00:00:00Z"


def test_claim_blocked_by_unverified_credential_returns_credential_missing(api):
    """PRD 3.4: "the clinician must hold, for every credential type in the facility's
    `required_credential_types`, a credential of that type in `VERIFIED` status, or
    the claim fails with `ERR_CREDENTIAL_MISSING`".

    Design: Difficulty/cross_entity_state_dependency/claim_blocked_by_unverified_credential
    """
    fac_id, cl_id, cred, sh_id = _setup_pending_credential_shift()
    assert cred["status"] == "PENDING_VERIFICATION"
    clinician = validate_success(api.get_clinician(cl_id, ADMIN), 200)
    assert clinician["status"] == "ACTIVE"

    resp = api.create_claim(sh_id, {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    err = validate_error(resp, ApiErrorId.ERR_CREDENTIAL_MISSING.value, 422)
    assert err["error_id"] != ApiErrorId.ERR_CREDENTIAL_EXPIRED.value


def test_claim_blocked_by_unverified_credential_creates_no_claim(api):
    """PRD 3.4: "the clinician must hold, for every credential type in the facility's
    `required_credential_types`, a credential of that type in `VERIFIED` status, or
    the claim fails with `ERR_CREDENTIAL_MISSING`".

    Design: Difficulty/cross_entity_state_dependency/claim_blocked_by_unverified_credential
    """
    fac_id, cl_id, cred, sh_id = _setup_pending_credential_shift()
    resp = api.create_claim(sh_id, {"clinician_id": cl_id}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_MISSING.value, 422)

    shift = validate_success(api.get_shift(sh_id, make_clinician_headers(cl_id)), 200)
    assert shift["claim_count"] == 0
    claims, meta = validate_paginated(api.list_claims(make_clinician_headers(cl_id), params={"clinician_id": cl_id}))
    assert meta["total_count"] == 0
