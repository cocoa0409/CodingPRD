"""Entity creation defaults, required-field / range validation, duplicates, auth.

Queue B (Corner) translations: entities, errors, validations, rbac, consistency_model.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_facility, assert_unit, assert_ledger_entry,
    create_facility_payload, create_unit_payload, create_tenant_payload,
    create_lease_payload,
    TEST_USERS, make_tenant_headers,
    setup_base, setup_activated, create_facility, create_unit, create_tenant, set_clock,
)

FM = TEST_USERS["facility_manager_headers"]
LIEN = TEST_USERS["lien_administrator_headers"]


def test_create_facility_applies_defaults_and_zero_count(api):
    """PRD §3.1: "Four pricing and dunning parameters may be supplied or left to
    default: `climate_premium_pct`, ... which defaults to 0.20 ...; `lien_default_days`,
    ... which defaults to 90 ...; `late_fee_grace_days`, ... which defaults to 5 ...;
    and `late_fee_cents`, ... which defaults to 2000 ...."
    PRD §3.1: "A facility also exposes `occupied_unit_count`, which is initialized to
    zero at creation."

    Design: Corner/entities/create_facility_returns_defaults_and_zero_count
    """
    resp = api.create_facility({"name": "FC", "state_code": "CA"}, FM)
    data = validate_success(resp, 201)
    assert_facility(data)
    assert data["climate_premium_pct"] == 0.20
    assert data["lien_default_days"] == 90
    assert data["late_fee_grace_days"] == 5
    assert data["late_fee_cents"] == 2000
    assert data["occupied_unit_count"] == 0
    assert data["version"] == 1


def test_create_unit_defaults_climate_false_available(api):
    """PRD §3.1: "A unit may optionally be flagged `climate_controlled`, which defaults
    to false."
    PRD §3.1: "A newly created unit starts with `status` equal to `AVAILABLE` and
    `current_lease_id` of null."

    Design: Corner/entities/create_unit_defaults_climate_false_and_available
    """
    fac = create_facility(name="FU", state_code="CA")
    resp = api.create_unit(
        {"facility_id": fac["id"], "unit_number": "Z-1",
         "size_class": "SIZE_5X5", "monthly_rate_cents": 5000}, FM)
    data = validate_success(resp, 201)
    assert_unit(data)
    assert data["climate_controlled"] is False
    assert data["status"] == "AVAILABLE"
    assert data["current_lease_id"] is None


def test_get_lease_not_found_returns_404(api):
    """PRD §2.8: "any referenced facility, unit, tenant, lease, invoice, policy, auction
    proceeding, or transfer order that does not exist yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_lease_not_found_returns_404
    """
    resp = api.get_lease("00000000-0000-4000-8000-000000000000", FM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_unit_missing_rate_rejected(api):
    """PRD §3.1: "a `monthly_rate_cents` base street rate that must be greater than zero."
    PRD §2.8: "Request well-formedness is checked fourth: missing required fields, bad
    enum values, and out-of-range numbers ... give `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_unit_missing_required_field_rejected
    """
    fac = create_facility(name="FR", state_code="CA")
    resp = api.create_unit(
        {"facility_id": fac["id"], "unit_number": "Z-2", "size_class": "SIZE_5X5"}, FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_lease_billing_day_out_of_range_rejected(api):
    """PRD §3.2: "the `billing_day` — the day of month, from 1 through 28, on which a
    monthly invoice is generated."
    PRD §2.8: "a `billing_day` outside 1 through 28 ... give `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/entities/create_lease_billing_day_out_of_range_rejected
    """
    fac = create_facility(name="FB", state_code="CA")
    unit = create_unit(fac["id"], unit_number="Z-3", size_class="SIZE_5X5",
                       monthly_rate_cents=5000)
    ten = create_tenant(email="rb@x.com", full_name="R B", state_code="CA")
    set_clock("2026-04-01T00:00:00Z")
    resp = api.create_lease(
        create_lease_payload(unit["id"], ten["id"], billing_day=31), FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_ledger_entry_immutable_no_version_field(api):
    """PRD §2.4: "A ledger entry is immutable once written and therefore carries only
    `id` and `created_at` — it has no `updated_at` and no `version`. There is no endpoint
    that mutates a ledger entry after creation."
    PRD §3.3: "A `CHARGE` ledger entry is appended for that first invoice's total."

    Design: Corner/entities/ledgerentry_immutable_no_version_field
    """
    # Climate unit @ 10000, 0.20 premium, no insurance -> first full-month invoice 12000.
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    resp = api.list_ledger_entries(FM, params={"lease_id": ctx["lease"]["id"]})
    entries, _ = validate_paginated(resp)
    charges = [e for e in entries if e["entry_type"] == "CHARGE"]
    assert len(charges) == 1, f"expected one CHARGE, got {entries}"
    e0 = charges[0]
    assert_ledger_entry(e0)
    assert e0["amount_cents"] == 12000
    assert "version" not in e0, "LedgerEntry must not carry a version field"
    assert "updated_at" not in e0, "LedgerEntry must not carry an updated_at field"


def test_duplicate_unit_number_within_facility_rejected(api):
    """PRD §3.1: "Attempting to create a second unit with a `unit_number` already used
    in the same facility is rejected with `ERR_DUPLICATE_UNIT_NUMBER` (HTTP 409)."

    Design: Corner/errors/duplicate_unit_number_within_facility
    """
    fac = create_facility(name="FX1", state_code="CA")
    create_unit(fac["id"], unit_number="DUP", size_class="SIZE_5X5",
                monthly_rate_cents=5000)
    resp = api.create_unit(
        {"facility_id": fac["id"], "unit_number": "DUP",
         "size_class": "SIZE_10X10", "monthly_rate_cents": 10000}, FM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER.value)


def test_duplicate_tenant_email_rejected(api):
    """PRD §3.2: "Registering with an email already on file is rejected with
    `ERR_DUPLICATE_EMAIL` (HTTP 409)."

    Design: Corner/errors/duplicate_tenant_email_rejected
    """
    api.create_tenant({"email": "dup@x.com", "full_name": "First", "state_code": "CA"}, FM)
    resp = api.create_tenant(
        {"email": "dup@x.com", "full_name": "Second", "state_code": "CA"}, FM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "If either header is missing or carries an unrecognized value, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_header_rejected
    """
    # No X-User-ID / X-User-Role headers at all.
    resp = api.create_facility({"name": "NoAuth", "state_code": "CA"}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_immediate_balance_visibility_after_activate(api):
    """PRD §3.3: "A `CHARGE` ledger entry is appended for that first invoice's total,
    and the lease's `balance_cents` is set to that first invoice total."

    Design: Corner/consistency_model/immediate_visibility_of_balance_after_activate
    """
    # Climate unit @ 10000, 0.20 premium, activate on billing_day -> full-month 12000.
    ctx = setup_base(unit_overrides={"climate_controlled": True, "monthly_rate_cents": 10000})
    resp = api.activate_lease(ctx["lease"]["id"], FM)
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE"
    assert data["balance_cents"] == 12000
