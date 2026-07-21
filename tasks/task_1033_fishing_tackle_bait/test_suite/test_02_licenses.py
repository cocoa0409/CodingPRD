"""Fishing-license issuance: computed fields, compliance checks, voiding, and
the safety-over-referential validation-precedence rule."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_resident_license_computes_price_and_valid_to(api):
    """PRD 3.3: "sets `price_cents` to the fixed price for the license type — 5200 for `RESIDENT_ANNUAL`, 12000 for `NONRESIDENT_ANNUAL`, 1500 for `ONE_DAY`, and 2600 for `SENIOR` — regardless of any client-supplied value".
    PRD 3.3: "the system computes `valid_to` as `valid_from` plus the license duration for the type — 365 days for `RESIDENT_ANNUAL`, `NONRESIDENT_ANNUAL`, and `SENIOR`, and 1 day for `ONE_DAY".

    Design: Corner/entities/entity_license_computed_price_and_valid_to
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    customer = fixtures.create_customer(name="Lic Holder", email="lh@x.com",
                                        state_code="CA", birth_date="1980-01-01")
    resp = api.create_license(
        {"customer_id": customer["id"], "license_type": "RESIDENT_ANNUAL",
         "state_code": "CA", "valid_from": "2026-07-01T00:00:00Z"},
        CLERK,
    )
    data = validate_success(resp, expected_status=201)
    assert data["price_cents"] == 5200
    assert data["valid_to"].startswith("2027-07-01T00:00:00"), (
        f"valid_to should be valid_from + 365 days, got {data['valid_to']}"
    )
    assert data["status"] == "ACTIVE", "now is within [valid_from, valid_to)"


def test_license_age_below_minimum_rejected(api):
    """PRD 3.3: "the holder's age in whole years, computed from the holder's `birth_date` against the logical clock, must be at least the minimum age for the requested `license_type` — 16 for `RESIDENT_ANNUAL`, `NONRESIDENT_ANNUAL`, and `ONE_DAY`, and 65 for `SENIOR`; if it does not, issuance is rejected with `ERR_LICENSE_AGE_RESTRICTION` (HTTP 422)."

    Design: Corner/validations/val_license_age_restriction_on_issue
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    customer = fixtures.create_customer(name="Kid Angler", email="k@x.com",
                                        state_code="CA", birth_date="2015-01-01")
    resp = api.create_license(
        {"customer_id": customer["id"], "license_type": "RESIDENT_ANNUAL",
         "state_code": "CA", "valid_from": "2026-07-01T00:00:00Z"},
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_AGE_RESTRICTION.value)


def test_voiding_already_void_license_rejected(api):
    """PRD 3.3: "Attempting to void a license that is already `VOID` is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/sm_license_double_void_returns_invalid_state
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    customer = fixtures.create_customer(name="VL Cust", email="vl@x.com",
                                        state_code="CA", birth_date="1980-01-01")
    lic = fixtures.create_license(customer["id"], license_type="RESIDENT_ANNUAL",
                                  state_code="CA", valid_from="2026-07-01T00:00:00Z")
    first = validate_success(api.void_license(lic["id"], MANAGER))
    assert first["status"] == "VOID", "first void must succeed"

    resp = api.void_license(lic["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_clerk_cannot_void_license(api):
    """PRD 2.1: "When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_clerk_cannot_void_license
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    customer = fixtures.create_customer(name="Void Deny", email="vd@x.com",
                                        state_code="CA", birth_date="1980-01-01")
    lic = fixtures.create_license(customer["id"], license_type="RESIDENT_ANNUAL",
                                  state_code="CA", valid_from="2026-07-01T00:00:00Z")
    resp = api.void_license(lic["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# --- Difficulty: priority_pair_validation_conflict / safety_beats_referential_on_license ---

def _setup_customer_with_active_resident_license(api):
    fixtures.set_clock("2026-07-01T00:00:00Z")
    customer = fixtures.create_customer(name="Angler I", email="i@x.com",
                                        state_code="CA", birth_date="1980-01-01")
    lic1 = fixtures.create_license(customer["id"], license_type="RESIDENT_ANNUAL",
                                   state_code="CA", valid_from="2026-07-01T00:00:00Z")
    return customer, lic1


def test_first_resident_license_is_active(api):
    """PRD 2.5: "ACTIVE` when now is at or after `valid_from` and strictly before `valid_to". The first license must be ACTIVE so that a subsequent duplicate
    would also violate the uniqueness rule.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_license
    """
    _customer, lic1 = _setup_customer_with_active_resident_license(api)
    assert lic1["status"] == "ACTIVE"


def test_state_mismatch_precedes_duplicate_license(api):
    """PRD 3.3: "Second, for a `RESIDENT_ANNUAL` or `SENIOR` license, the issuing `state_code` must equal the holder `Customer`'s `state_code`; a mismatch is rejected with `ERR_LICENSE_STATE_MISMATCH` (HTTP 422)."
    PRD 3.3: "Only after both compliance checks pass does the uniqueness check apply: a customer may not hold two `ACTIVE` licenses of the same `license_type`, and an attempt to issue a duplicate is rejected with `ERR_DUPLICATE_LICENSE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_license
    """
    customer, _lic1 = _setup_customer_with_active_resident_license(api)
    # Second RESIDENT_ANNUAL: duplicate (same type, active) AND state mismatch (NV != CA).
    resp = api.create_license(
        {"customer_id": customer["id"], "license_type": "RESIDENT_ANNUAL",
         "state_code": "NV", "valid_from": "2026-07-01T00:00:00Z"},
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_STATE_MISMATCH.value)
