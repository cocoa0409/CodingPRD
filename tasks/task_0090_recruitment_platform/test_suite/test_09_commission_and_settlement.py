"""Headhunter commission calculation, settlement sweep, and clawback
(PRD §3.6 cascade, §3.7 cascade, §3.8)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    BPS_DENOMINATOR,
    DEFAULT_TAX_WITHHOLDING_PCT_BPS,
    FIRST_SLICE_CAP_CENTS,
    SETTLEMENT_HOLDBACK_DAYS,
    TEST_EPOCH,
    advance_clock_by,
    advance_clock_to,
    assert_commission_record,
    assert_commission_settlement_invariant,
    create_headhunter_contract,
    create_offer,
    iso_utc,
    make_candidate_headers,
    make_finance_approver_headers,
    make_headhunter_headers,
    make_hiring_manager_headers,
    make_hr_approver_headers,
    make_hr_user_headers,
    accept_offer_payload,
    rescind_offer_payload,
    reset_clock_to_epoch,
    run_settlement_sweep,
    setup_accepted_offer,
    setup_application_at_interview_passed,
    setup_issued_offer,
    submit_offer_for_approval,
    validate_error,
    validate_success,
)


def _round_half_up(value: float) -> int:
    """PRD §2.8 'round half up to the nearest integer cent'.

    Python's built-in round() uses banker's rounding for ties; we
    implement the PRD's half-up convention explicitly.
    """
    import math
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


# ===========================================================================
# Commission accrual at OFFER_ACCEPTED (PRD §3.6, §3.8)
# ===========================================================================
class TestCommissionAccrualOnAccept:

    def test_success_fee_gross_calculation(self, api, platform_admin_headers):
        """PRD §3.8: "The success-fee component is split into two slices
        on the base salary so that per-tier rounding is well-defined. The
        first slice is the smaller of the offer's `base_salary_cents` and
        the cap of 10,000,000 cents (which equals 100,000.00 monetary
        units), multiplied by `success_fee_pct_bps`, divided by 10,000."

        Claim: a SUCCESS_FEE contract with base 5,000,000 and
        success_fee_pct_bps=2500 yields gross_commission_cents = 1,250,000.
        """
        reset_clock_to_epoch()
        # Build the lifecycle with a HEADHUNTER channel application.
        # First create the company.
        from test_helpers import bind_hr_user, create_verified_company
        company, hm_hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"],
            fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2500,
            trigger_event="OFFER_ACCEPTED",
            tax_withholding_pct_bps=1500,
            clawback_window_days=90,
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000,
            sign_on_bonus_cents=0,
            source_channel="HEADHUNTER",
            headhunter_contract=contract,
        )
        # List commission records for the contract.
        resp = api.list_commission_records(
            platform_admin_headers,
            params={"headhunter_contract_id": contract["id"]},
        )
        records = validate_success(resp, expected_status=200)
        assert len(records) == 1, (
            f"Expected exactly one CommissionRecord for the contract; "
            f"got {len(records)}"
        )
        record = records[0]
        assert_commission_record(record)
        # gross = 5,000,000 * 2500 / 10000 = 1,250,000
        assert record["gross_commission_cents"] == 1_250_000
        # tax = round_half_up(1_250_000 * 1500 / 10000) = 187_500
        assert record["tax_withheld_cents"] == 187_500
        # While ACCRUED, projected net_settlement_cents = gross - tax = 1_062_500
        assert record["settlement_status"] == "ACCRUED"
        assert record["net_settlement_cents"] == 1_062_500

    def test_no_commission_when_source_channel_is_not_headhunter(
        self, api, platform_admin_headers,
    ):
        """PRD §3.6: "if the application's `source_channel` is
        `HEADHUNTER` and the originating `HeadhunterContract.trigger_event`
        is `OFFER_ACCEPTED`, a `CommissionRecord` is created..."

        Claim: a DIRECT-channel acceptance produces no CommissionRecord.
        """
        bag = setup_accepted_offer(source_channel="DIRECT")
        resp = api.list_commission_records(platform_admin_headers, params={})
        records = validate_success(resp, expected_status=200)
        # No CommissionRecord should exist for a DIRECT-channel application.
        for r in records:
            assert r["application_id"] != bag["application"]["id"], (
                "No commission should accrue on a DIRECT-channel "
                "offer acceptance"
            )


# ===========================================================================
# Settlement sweep (PRD §3.8)
# ===========================================================================
class TestSettlementSweep:

    def test_sweep_after_holdback_advances_to_settled(self, api, platform_admin_headers):
        """PRD §3.8: "Settlement runs on a deferred sweep. The platform
        exposes an admin-only test-driving capability that runs the
        settlement sweep: each `CommissionRecord` in `ACCRUED` status
        whose age (current instant minus the record's `created_at`) is
        at least thirty days, and against which no clawback condition is
        active, transitions to `SETTLED`. The sweep sets `settled_at` to
        the current instant and computes `net_settlement_cents` as
        `gross_commission_cents` minus `tax_withheld_cents`..."

        Claim: a CommissionRecord at least 30 days old transitions to
        SETTLED on sweep, with net = gross - tax.
        """
        reset_clock_to_epoch()
        from test_helpers import create_verified_company
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2500, trigger_event="OFFER_ACCEPTED",
            tax_withholding_pct_bps=1500,
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000, sign_on_bonus_cents=0,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        record_id = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )[0]["id"]
        # Advance to TEST_EPOCH + 31 days. The commission record was created
        # during setup_accepted_offer (clock ~ TEST_EPOCH + 2h), so its age
        # at TEST_EPOCH + 31 days is ~30d 22h — strictly >= 30 days.
        advance_clock_by((SETTLEMENT_HOLDBACK_DAYS + 1) * 24 * 3600)
        run_settlement_sweep()
        record = validate_success(
            api.get_commission_record(record_id, platform_admin_headers),
            expected_status=200,
        )
        assert record["settlement_status"] == "SETTLED"
        assert record["net_settlement_cents"] == 1_062_500
        assert record["settled_at"] is not None
        assert_commission_settlement_invariant(record)

    def test_sweep_before_holdback_leaves_record_accrued(self, api, platform_admin_headers):
        """PRD §3.8: "each `CommissionRecord` in `ACCRUED` status whose
        age (current instant minus the record's `created_at`) is at
        least thirty days... transitions to `SETTLED`."

        Claim: a CommissionRecord younger than 30 days remains ACCRUED
        after the sweep.
        """
        reset_clock_to_epoch()
        from test_helpers import create_verified_company
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2500, trigger_event="OFFER_ACCEPTED",
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000, sign_on_bonus_cents=0,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        record_id = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )[0]["id"]
        # Sweep before 30 days have elapsed.
        advance_clock_by(SETTLEMENT_HOLDBACK_DAYS * 24 * 3600 - 1)
        run_settlement_sweep()
        record = validate_success(
            api.get_commission_record(record_id, platform_admin_headers),
            expected_status=200,
        )
        assert record["settlement_status"] == "ACCRUED"


# ===========================================================================
# Clawback on rescind from ACCEPTED (PRD §3.6)
# ===========================================================================
class TestClawbackOnRescind:

    def test_rescind_accepted_flips_commission_to_clawed_back(self, api, platform_admin_headers):
        """PRD §3.6: "A rescission from `ACCEPTED` runs a second-link
        cascade: if a `CommissionRecord` already exists for this
        application with `settlement_status` `ACCRUED` and `trigger_kind`
        `OFFER_ACCEPTED`, that record flips to `CLAWED_BACK`, its
        `clawback_amount_cents` is set to `gross_commission_cents` minus
        `tax_withheld_cents`, and `net_settlement_cents` is set to zero."

        Claim: rescind from ACCEPTED flips the related CommissionRecord
        to CLAWED_BACK with clawback_amount_cents = gross - tax and
        net_settlement_cents == 0.
        """
        reset_clock_to_epoch()
        from test_helpers import create_verified_company
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2500, trigger_event="OFFER_ACCEPTED",
            tax_withholding_pct_bps=1500,
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000, sign_on_bonus_cents=0,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        record_id = validate_success(
            api.list_commission_records(
                platform_admin_headers,
                params={"headhunter_contract_id": contract["id"]},
            ),
            expected_status=200,
        )[0]["id"]
        # Rescind the accepted offer (no onboarding yet).
        api.rescind_offer(
            bag["offer"]["id"], rescind_offer_payload("BUSINESS_NEED"),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        record = validate_success(
            api.get_commission_record(record_id, platform_admin_headers),
            expected_status=200,
        )
        assert record["settlement_status"] == "CLAWED_BACK"
        # gross - tax = 1,250,000 - 187,500 = 1,062,500
        assert record["clawback_amount_cents"] == 1_062_500
        assert record["net_settlement_cents"] == 0
        assert_commission_settlement_invariant(record)


# ===========================================================================
# Headhunter ownership on commission read (PRD §3.8)
# ===========================================================================
class TestHeadhunterOwnership:

    def test_headhunter_can_read_own_commission_record(self, api):
        """PRD §3.8: "A `HeadhunterUser` reading commission records may
        see only those rows whose `headhunter_contract_id` equals their
        `X-User-ID`..."

        Claim: a HeadhunterUser whose X-User-ID equals
        HeadhunterContract.id can read commission records under that
        contract.
        """
        reset_clock_to_epoch()
        from test_helpers import create_verified_company
        company, _hr = create_verified_company(verification_tier="PREMIUM")
        contract = create_headhunter_contract(
            company_id=company["id"], fee_model="SUCCESS_FEE",
            success_fee_pct_bps=2500, trigger_event="OFFER_ACCEPTED",
        )
        bag = setup_accepted_offer(
            base_salary_cents=5_000_000, sign_on_bonus_cents=0,
            source_channel="HEADHUNTER", headhunter_contract=contract,
        )
        resp = api.list_commission_records(
            make_headhunter_headers(contract["id"]),
            params={},
        )
        records = validate_success(resp, expected_status=200)
        # All visible records must belong to this contract.
        for r in records:
            assert r["headhunter_contract_id"] == contract["id"], (
                "HeadhunterUser must only see commission records for "
                "their own contract"
            )
        assert len(records) >= 1
