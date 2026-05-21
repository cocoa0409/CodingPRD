"""Claimant, Employer, and WageRecord CRUD — PRD §3.1.

Tests the identity setup primitives — registration of claimants and
employers, plus immutable wage-record filing.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_claimant,
    assert_employer,
    assert_wage_record,
    create_claimant,
    create_claimant_payload,
    create_employer,
    create_employer_payload,
    create_wage_record_payload,
    validate_error,
    validate_success,
)


class TestClaimantCreation:

    def test_self_registration_succeeds(self, api):
        """PRD §3.1: "Self-registration is permitted to the Claimant
        role for the claimant-creation endpoint; the SystemAdmin role
        may also create claimants."
        """
        resp = api.create_claimant(
            create_claimant_payload(),
            TEST_USERS["claimant_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_claimant(data)

    def test_admin_can_create_claimant(self, api):
        """PRD §3.1: "the SystemAdmin role may also create claimants."
        """
        resp = api.create_claimant(
            create_claimant_payload(),
            TEST_USERS["system_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_claimant(data)

    def test_initial_lifetime_overpayment_balance_zero(self, api):
        """PRD §3.1: "The newly created Claimant is returned with
        lifetime_overpayment_balance_cents initialised to 0."
        """
        claimant = create_claimant()
        assert claimant["lifetime_overpayment_balance_cents"] == 0, (
            f"expected lifetime_overpayment_balance_cents == 0, "
            f"got {claimant['lifetime_overpayment_balance_cents']}"
        )

    @pytest.mark.parametrize("bad_ssn", ["12", "12345", "abcd", ""])
    def test_invalid_ssn_last4_rejected(self, api, bad_ssn):
        """PRD §3.1: "ssn_last4 (exactly four digits, used only for
        identification)."
        """
        resp = api.create_claimant(
            create_claimant_payload(ssn_last4=bad_ssn),
            TEST_USERS["system_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)

    @pytest.mark.parametrize("bad_state", ["ca", "USA", "X1", ""])
    def test_invalid_state_residence_rejected(self, api, bad_state):
        """PRD §3.1: "state_residence (a two-letter US state code
        matching the pattern of two uppercase letters)."
        """
        resp = api.create_claimant(
            create_claimant_payload(state_residence=bad_state),
            TEST_USERS["system_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_missing_required_full_name_rejected(self, api):
        """PRD §3.1: "A claimant identity is created with a payload
        supplying ssn_last4 (exactly four digits, used only for
        identification), full_name, state_residence (a two-letter US
        state code matching the pattern of two uppercase letters), and
        date_of_birth (an ISO 8601 calendar date)."
        """
        payload = create_claimant_payload()
        payload.pop("full_name", None)
        resp = api.create_claimant(
            payload, TEST_USERS["system_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)


class TestEmployerRegistration:

    def test_admin_can_register_employer(self, api):
        """PRD §3.1: "Employer registration is admin-only."
        """
        resp = api.create_employer(
            create_employer_payload(),
            TEST_USERS["system_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_employer(data)

    def test_reserve_basis_must_be_positive(self, api):
        """PRD §3.1: "reserve_ratio_basis_cents (the long-run reserve
        dollars in the employer's account; must be strictly greater
        than zero)."
        """
        resp = api.create_employer(
            create_employer_payload(reserve_ratio_basis_cents=0),
            TEST_USERS["system_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_initial_experience_rate_floor_tier(self, api):
        """PRD §3.1: "On creation, the employer's experience_rate_bps
        is initialised from the experience-rate calculation against
        zero active charges — effectively the tier corresponding to
        the raw reserve ratio."

        With reserve_ratio_basis_cents=1_000_000 and
        taxable_payroll_cents=10_000_000, the reserve_ratio is exactly
        0.10 which lands at the floor tier per the §3.3 tier table.
        """
        emp = create_employer(
            reserve_ratio_basis_cents=1_000_000,
            taxable_payroll_cents=10_000_000,
        )
        # PRD §3.3: "a reserve ratio of at least 0.10 yields the 1.00%
        # floor of 100 basis points".
        assert emp["experience_rate_bps"] == 100, (
            f"expected 100 bps for ratio=0.10, "
            f"got {emp['experience_rate_bps']}"
        )

    def test_experience_rate_bounded_by_ceiling(self, api):
        """PRD §3.1: "The persisted experience_rate_bps is bounded
        between the 1.00% floor (100 basis points) and the 5.40%
        ceiling (540 basis points)."
        """
        emp = create_employer(
            reserve_ratio_basis_cents=1,  # near-zero
            taxable_payroll_cents=10_000_000,
        )
        # ratio ~= 0.0000001 -> >= 0.00 -> 460 bps (not floor)
        assert 100 <= emp["experience_rate_bps"] <= 540


class TestWageRecord:

    def test_admin_can_file_wage_record(self, api):
        """PRD §3.1: "Quarterly wage records are admin-filed and
        immutable once written."
        """
        claimant = create_claimant()
        employer = create_employer()
        resp = api.create_wage_record(
            claimant["id"],
            create_wage_record_payload(
                employer_id=employer["id"],
                quarter_year=2024,
                quarter_index=1,
                wages_cents=500_000,
            ),
            TEST_USERS["system_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_wage_record(data)

    @pytest.mark.parametrize("bad_q", [0, 5, -1])
    def test_invalid_quarter_index_rejected(self, api, bad_q):
        """PRD §3.1: "quarter_index (1 for January–March through 4 for
        October–December)."
        """
        claimant = create_claimant()
        employer = create_employer()
        resp = api.create_wage_record(
            claimant["id"],
            create_wage_record_payload(
                employer_id=employer["id"],
                quarter_year=2024,
                quarter_index=bad_q,
                wages_cents=500_000,
            ),
            TEST_USERS["system_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_negative_wages_rejected(self, api):
        """PRD §3.1: "wages_cents (zero or positive)."
        """
        claimant = create_claimant()
        employer = create_employer()
        resp = api.create_wage_record(
            claimant["id"],
            create_wage_record_payload(
                employer_id=employer["id"],
                quarter_year=2024,
                quarter_index=1,
                wages_cents=-100,
            ),
            TEST_USERS["system_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)
