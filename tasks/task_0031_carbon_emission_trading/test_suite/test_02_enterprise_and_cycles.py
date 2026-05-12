"""Enterprise creation, allocation-cycle creation, ratio bounds.

PRD references:
  - §3.1 Enterprise Onboarding and Cycle Setup
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_allocation_cycle,
    assert_enterprise,
    create_allocation_cycle_payload,
    create_enterprise,
    create_enterprise_payload,
    create_allocation_cycle,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 — Enterprise creation
# ===========================================================================
class TestEnterpriseCreation:
    def test_create_enterprise_starts_pending_with_zero_balances(
        self, api, regulator_headers
    ):
        """PRD §3.1: 'The newly-registered enterprise begins with
        account_status set to PENDING, with quota_balance,
        paid_quota_balance, and ccer_balance all initialized to zero.'

        Claim: account_status=PENDING and the three balances all start at 0.
        """
        res = api.create_enterprise(
            create_enterprise_payload(jurisdiction_code="JD_BETA",
                                      industry_code="STEEL"),
            regulator_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_enterprise(data)
        assert data["account_status"] == "PENDING"
        assert data["quota_balance"] == 0
        assert data["paid_quota_balance"] == 0
        assert data["ccer_balance"] == 0

    def test_create_enterprise_persists_jurisdiction_and_industry(
        self, api, regulator_headers
    ):
        """PRD §3.1: 'A regulator creates each enterprise with a payload
        containing legal_name, jurisdiction_code (one of JD_ALPHA, JD_BETA,
        or JD_GAMMA), industry_code (one of POWER, STEEL, CEMENT, CHEMICAL,
        or PETROCHEMICAL), and a contact_email used for objection-window
        and compliance notices.'

        Claim: created Enterprise echoes its jurisdiction_code and
        industry_code.
        """
        res = api.create_enterprise(
            create_enterprise_payload(
                jurisdiction_code="JD_GAMMA",
                industry_code="CEMENT",
            ),
            regulator_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["jurisdiction_code"] == "JD_GAMMA"
        assert data["industry_code"] == "CEMENT"


# ===========================================================================
# §3.1 — Cycle creation
# ===========================================================================
class TestAllocationCycleCreation:
    def test_create_cycle_status_is_draft(self, api, regulator_headers):
        """PRD §3.1: 'The cycle is created with its status field set to
        DRAFT and with publication_date and settlement_date initially null.'

        Claim: a newly-created AllocationCycle has status DRAFT and
        publication_date/settlement_date null.
        """
        res = api.create_allocation_cycle(
            create_allocation_cycle_payload(
                free_paid_ratio=0.50,
                ccer_cap_pct=0.10,
            ),
            regulator_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_allocation_cycle(data)
        assert data["status"] == "DRAFT"
        assert data.get("publication_date") is None
        assert data.get("settlement_date") is None


# ===========================================================================
# §3.1 — Ratio bounds (ERR_INVALID_RATIO)
# ===========================================================================
class TestRatioBounds:
    @pytest.mark.parametrize("ratio", [-0.01, 1.01, 1.5, -1.0])
    def test_free_paid_ratio_outside_zero_to_one_rejected(
        self, api, regulator_headers, ratio
    ):
        """PRD §3.1: 'The free-paid ratio must lie between 0.0 and 1.0
        inclusive, and the CCER cap must lie between 0.0 and 0.20 inclusive;
        values outside either range are rejected with ERR_INVALID_RATIO.'

        Claim: free_paid_ratio outside [0.0, 1.0] -> ERR_INVALID_RATIO.
        """
        payload = create_allocation_cycle_payload(
            free_paid_ratio=ratio,
            ccer_cap_pct=0.05,
        )
        res = api.create_allocation_cycle(payload, regulator_headers)
        validate_error(res, "ERR_INVALID_RATIO")

    @pytest.mark.parametrize("cap", [-0.01, 0.21, 1.0])
    def test_ccer_cap_outside_zero_to_point_two_rejected(
        self, api, regulator_headers, cap
    ):
        """PRD §3.1: 'The free-paid ratio must lie between 0.0 and 1.0
        inclusive, and the CCER cap must lie between 0.0 and 0.20 inclusive;
        values outside either range are rejected with ERR_INVALID_RATIO.'

        Claim: ccer_cap_pct outside [0.0, 0.20] -> ERR_INVALID_RATIO.
        """
        payload = create_allocation_cycle_payload(
            free_paid_ratio=0.80,
            ccer_cap_pct=cap,
        )
        res = api.create_allocation_cycle(payload, regulator_headers)
        validate_error(res, "ERR_INVALID_RATIO")

    @pytest.mark.parametrize("ratio", [0.0, 1.0])
    def test_free_paid_ratio_inclusive_bounds_accepted(
        self, api, regulator_headers, ratio
    ):
        """PRD §3.1: 'The free-paid ratio must lie between 0.0 and 1.0
        inclusive, and the CCER cap must lie between 0.0 and 0.20 inclusive;
        values outside either range are rejected with ERR_INVALID_RATIO.'

        Claim: free_paid_ratio at exactly 0.0 or 1.0 (inclusive boundary)
        is accepted.
        """
        payload = create_allocation_cycle_payload(
            free_paid_ratio=ratio,
            ccer_cap_pct=0.05,
        )
        res = api.create_allocation_cycle(payload, regulator_headers)
        validate_success(res, expected_status=201)

    @pytest.mark.parametrize("cap", [0.0, 0.20])
    def test_ccer_cap_inclusive_bounds_accepted(
        self, api, regulator_headers, cap
    ):
        """PRD §3.1: 'The CCER cap must lie between 0.0 and 0.20 inclusive'.

        Claim: ccer_cap_pct at exactly 0.0 or 0.20 (inclusive boundary)
        is accepted.
        """
        payload = create_allocation_cycle_payload(
            free_paid_ratio=0.80,
            ccer_cap_pct=cap,
        )
        res = api.create_allocation_cycle(payload, regulator_headers)
        validate_success(res, expected_status=201)
