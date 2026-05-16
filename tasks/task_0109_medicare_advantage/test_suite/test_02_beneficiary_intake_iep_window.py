"""Beneficiary intake and the seven-month IEP window.

Covers PRD §3.1: medicare_eligibility_date computation across three
pathways (ESRD / disability / age-65), iep_start_date /
iep_end_date derivation, IEP companion period creation, and the
PRE_ELIGIBLE initial status.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_months,
    advance_clock_to,
    assert_beneficiary,
    create_beneficiary,
    create_beneficiary_payload,
    first_of_month,
    get_iep_period,
    iso_date,
    iso_day_end_utc,
    parse_iso,
    random_medicare_id,
    re_get_beneficiary,
    setup_clock_at,
    validate_error,
    validate_success,
)
from datetime import date


class TestBeneficiaryIntakeAge65Pathway:
    """PRD §3.1 standard age-65 pathway."""

    def test_eligibility_date_is_first_of_month_dob_plus_65(self, api,
                                                            admin_headers):
        """PRD §3.1: "Otherwise (the standard age-65 pathway),
        eligibility begins on the first day of the month that contains
        date_of_birth plus sixty-five years."

        Claim: medicare_eligibility_date == first_of_month(dob + 65y).
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_beneficiary(
            create_beneficiary_payload(date_of_birth="1961-04-15"),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_beneficiary(data)
        # PRD §3.1: first day of month containing 1961-04-15 + 65y
        # = first_of_month(2026-04-15) = 2026-04-01.
        assert data["medicare_eligibility_date"].startswith(
            "2026-04-01"
        ), f"expected 2026-04-01, got {data['medicare_eligibility_date']}"

    def test_iep_start_is_three_months_before_eligibility(self, api,
                                                          admin_headers):
        """PRD §3.1: "iep_start_date is the first day of the month that
        falls three months before medicare_eligibility_date".

        Claim: iep_start_date == first_of_month(eligibility - 3
        months). For dob 1961-04-15, eligibility 2026-04-01, IEP starts
        2026-01-01.
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_beneficiary(
            create_beneficiary_payload(date_of_birth="1961-04-15"),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["iep_start_date"].startswith("2026-01-01"), (
            f"expected 2026-01-01, got {data['iep_start_date']}"
        )

    def test_iep_end_is_last_second_three_months_after_eligibility(
        self, api, admin_headers,
    ):
        """PRD §3.1: "iep_end_date is the last second of the month that
        falls three months after medicare_eligibility_date — i.e.,
        23:59:59 UTC on the final day of that month, inclusive."

        Claim: dob 1961-04-15 -> eligibility 2026-04-01 -> iep_end
        is last second of 2026-07 = 2026-07-31T23:59:59 UTC.
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_beneficiary(
            create_beneficiary_payload(date_of_birth="1961-04-15"),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["iep_end_date"].startswith("2026-07-31T23:59:59"), (
            f"expected 2026-07-31T23:59:59, got {data['iep_end_date']}"
        )


class TestBeneficiaryIntakeEsrdPathway:
    """PRD §3.1 ESRD pathway."""

    def test_esrd_makes_eligibility_birth_month(self, api, admin_headers):
        """PRD §3.1: "If has_esrd is true, the beneficiary is treated
        as immediately eligible from the first day of the month of
        their date_of_birth."

        Claim: with has_esrd=true, eligibility = first_of_month(dob).
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_beneficiary(
            create_beneficiary_payload(
                date_of_birth="1975-08-20", has_esrd=True,
            ),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        # PRD §3.1: first day of month of dob = 1975-08-01.
        assert data["medicare_eligibility_date"].startswith(
            "1975-08-01"
        ), (
            f"expected 1975-08-01, got "
            f"{data['medicare_eligibility_date']}"
        )


class TestBeneficiaryIntakeDisabilityPathway:
    """PRD §3.1 disability pathway."""

    def test_disability_eligibility_is_first_of_month_ssdi_plus_24(
        self, api, admin_headers,
    ):
        """PRD §3.1: "Otherwise, if has_disability is true and
        ssdi_start_date is set, eligibility begins on the first day of
        the month that contains ssdi_start_date plus twenty-four
        months."

        Claim: dob arbitrary, has_disability=true, ssdi_start_date
        2020-03-10 -> eligibility = first_of_month(2022-03-10) =
        2022-03-01.
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_beneficiary(
            create_beneficiary_payload(
                date_of_birth="1985-01-01",
                has_disability=True,
                ssdi_start_date="2020-03-10",
            ),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["medicare_eligibility_date"].startswith(
            "2022-03-01"
        ), (
            f"expected 2022-03-01, got "
            f"{data['medicare_eligibility_date']}"
        )


class TestBeneficiaryInitialStateAndIepPeriod:
    """PRD §3.1 initial lifecycle_status and IEP period auto-creation."""

    def test_initial_lifecycle_is_pre_eligible(self, api, admin_headers):
        """PRD §3.1: "The beneficiary themselves begins in
        lifecycle_status PRE_ELIGIBLE, and deceased_at is unset."

        Claim: new beneficiary has lifecycle_status=PRE_ELIGIBLE when
        intake happens before iep_start_date.
        """
        # Clock far before IEP window for a 1980 dob (eligibility 2045).
        setup_clock_at(2026, 1, 1)
        resp = api.create_beneficiary(
            create_beneficiary_payload(date_of_birth="1980-01-01"),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["lifecycle_status"] == "PRE_ELIGIBLE"

    def test_iep_period_created_on_intake(self, api, admin_headers):
        """PRD §3.1: "Intake also creates a companion EnrollmentPeriod
        row of period_type IEP whose window_start and window_end are
        precisely iep_start_date and iep_end_date. This period begins
        in SCHEDULED status."

        Claim: a companion IEP period exists after intake with status
        SCHEDULED and matching window dates.
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_beneficiary(
            create_beneficiary_payload(date_of_birth="1980-01-01"),
            admin_headers,
        )
        beneficiary = validate_success(resp, expected_status=201)
        period = get_iep_period(beneficiary["id"])
        assert period is not None, "expected an IEP EnrollmentPeriod row"
        assert period["period_type"] == "IEP"
        assert period["status"] == "SCHEDULED"
        assert period["window_start"].startswith(
            beneficiary["iep_start_date"][:10]
        )
        assert period["window_end"].startswith(
            beneficiary["iep_end_date"][:10]
        )


class TestBeneficiaryIntakeValidation:
    """PRD §3.1 input field validation."""

    def test_medicare_id_must_be_11_chars(self, api, admin_headers):
        """PRD §3.1: "The medicare_id is an externally issued Medicare
        Beneficiary Identifier, exactly eleven uppercase-alphanumeric
        characters, and must be unique across all beneficiaries".

        Claim: medicare_id of wrong length -> ERR_VALIDATION.
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_beneficiary(
            create_beneficiary_payload(medicare_id="SHORT"),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_state_code_must_be_two_letters(self, api, admin_headers):
        """PRD §3.1: "the state_code is the two-letter USPS
        abbreviation, used later for Medigap residency matching."

        Claim: state_code not 2 chars -> ERR_VALIDATION.
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_beneficiary(
            create_beneficiary_payload(state_code="CAL"),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
