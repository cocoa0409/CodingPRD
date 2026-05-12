"""Owner onboarding, contact verification, and deposits (PRD §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_owner,
    create_owner_payload,
    deposit_payload,
    get_success_data,
    setup_owner_and_pet,
    top_up_deposit,
    validate_error,
    validate_success,
    verify_contact_payload,
    verify_owner_contact,
)


class TestOwnerCreation:
    def test_owner_created_unverified_zero_deposit(self, api, owner_service_headers):
        """PRD §3.1: 'The contact_verified flag defaults to false on
        creation, the verification_code_hash defaults to null, the
        verification_expires_at defaults to null, and the
        deposit_balance_cents defaults to 0.'"""
        res = api.create_owner(create_owner_payload(), owner_service_headers)
        data = validate_success(res, expected_status=201)
        assert_owner(data)
        assert data["contact_verified"] is False, (
            "Newly created owner must default contact_verified=false"
        )
        assert data["deposit_balance_cents"] == 0, (
            "Newly created owner must default deposit_balance_cents=0"
        )

    def test_owner_phone_unique_constraint(self, api, owner_service_headers):
        """PRD §3.1: 'a phone_e164 value matching the international E.164
        format ... and unique per owner.'"""
        first = create_owner_payload()
        first_res = api.create_owner(first, owner_service_headers)
        validate_success(first_res, expected_status=201)
        # Second creation reusing the phone should fail validation.
        dup = create_owner_payload(phone_e164=first["phone_e164"])
        res = api.create_owner(dup, owner_service_headers)
        validate_error(res, "ERR_VALIDATION_FAILED")

    def test_owner_email_unique_constraint(self, api, owner_service_headers):
        """PRD §3.1: 'an email (RFC-5322 lite, lowercased, unique per owner).'"""
        first = create_owner_payload()
        first_res = api.create_owner(first, owner_service_headers)
        validate_success(first_res, expected_status=201)
        dup = create_owner_payload(email=first["email"])
        res = api.create_owner(dup, owner_service_headers)
        validate_error(res, "ERR_VALIDATION_FAILED")


class TestContactVerification:
    def test_verification_flips_contact_verified_true(self, api, owner_service_headers):
        """PRD §3.1: 'On a successful match the system flips
        contact_verified to true, clears verification_code_hash to null,
        and clears verification_expires_at to null.'"""
        owner_res = api.create_owner(create_owner_payload(), owner_service_headers)
        owner = validate_success(owner_res, expected_status=201)
        assert owner["contact_verified"] is False
        # Drive issue + verify via fixture (uses lenient validators).
        verify_owner_contact(owner["id"])
        # Re-fetch to check the canonical state via the API.
        re_res = api.get_owner(owner["id"], owner_service_headers)
        re_data = validate_success(re_res)
        assert re_data["contact_verified"] is True, (
            "After successful verify-contact, contact_verified must be true"
        )


class TestDepositTopUp:
    def test_deposit_top_up_increments_balance(self, api, cashier_headers):
        """PRD §3.1: 'A Cashier may top up an owner's deposit balance
        by calling the deposit endpoint with an amount_cents value;
        the call increments deposit_balance_cents by that amount.'"""
        owner, _ = setup_owner_and_pet(deposit_cents=0)
        # Re-fetch to confirm zero baseline.
        before = get_success_data(
            api.get_owner(owner["id"], cashier_headers)
        )
        assert before["deposit_balance_cents"] == 0
        res = api.deposit(
            owner["id"], deposit_payload(amount_cents=12_345), cashier_headers,
        )
        after = validate_success(res)
        assert after["deposit_balance_cents"] == 12_345, (
            f"Expected balance 12345 after top-up of 12345, "
            f"got {after['deposit_balance_cents']}"
        )

    def test_deposit_two_top_ups_accumulate(self, api):
        """PRD §3.1: 'A Cashier may top up an owner's deposit balance
        by calling the deposit endpoint with an amount_cents value;
        the call increments deposit_balance_cents by that amount.'"""
        owner, _ = setup_owner_and_pet(deposit_cents=0)
        top_up_deposit(owner["id"], 1000)
        owner = top_up_deposit(owner["id"], 2500)
        assert owner["deposit_balance_cents"] == 3500
