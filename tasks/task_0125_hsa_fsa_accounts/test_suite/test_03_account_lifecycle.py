"""Account opening, freeze, unfreeze, and close — PRD §3.1.

Coverage targets:
- Account creation enforces account_type / coverage_tier / year_end_policy
  combination rules.
- Newly opened account is OPEN with closed_at == null.
- Freeze transitions OPEN -> FROZEN (audit + version increment).
- Unfreeze transitions FROZEN -> OPEN.
- Close requires no open plan years and no pending claims.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_account,
    create_account_holder,
    create_account_payload,
    freeze_account,
    iso_datetime_utc,
    setup_active_plan_year,
    setup_holder_and_account,
    setup_submitted_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Account creation — PRD §3.1
# ===========================================================================
class TestAccountOpen:

    def test_open_hsa_self_only(self, api, plan_admin_headers):
        """PRD §3.1: "For an HSA, coverage_tier must be supplied as
        either SELF_ONLY or FAMILY".

        Claim: HSA SELF_ONLY opens and persists coverage_tier.
        """
        holder = create_account_holder()
        payload = create_account_payload(
            account_holder_id=holder["id"],
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
        )
        resp = api.create_account(payload, plan_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_account(data)
        assert data["account_type"] == "HSA"
        assert data["coverage_tier"] == "SELF_ONLY"
        assert data["year_end_policy"] == "NONE"
        assert data["status"] == "OPEN"
        assert data["closed_at"] is None
        assert data["version"] == 1

    def test_open_hsa_family(self, api, plan_admin_headers):
        """PRD §3.1: "For an HSA, coverage_tier must be supplied as
        either SELF_ONLY or FAMILY".

        Claim: HSA FAMILY accepted.
        """
        holder = create_account_holder()
        payload = create_account_payload(
            account_holder_id=holder["id"],
            account_type="HSA", coverage_tier="FAMILY",
            year_end_policy="NONE",
        )
        resp = api.create_account(payload, plan_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["coverage_tier"] == "FAMILY"

    @pytest.mark.parametrize(
        "year_end_policy", ["GRACE_PERIOD", "CARRYOVER", "NONE"],
    )
    def test_open_health_fsa_each_policy(self, api, plan_admin_headers,
                                         year_end_policy):
        """PRD §3.1: "for HEALTH_FSA it may be GRACE_PERIOD, CARRYOVER,
        or NONE".

        Claim: HEALTH_FSA accepts all three year_end_policy values.
        """
        holder = create_account_holder()
        payload = create_account_payload(
            account_holder_id=holder["id"],
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy=year_end_policy,
        )
        resp = api.create_account(payload, plan_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["year_end_policy"] == year_end_policy
        assert data["coverage_tier"] is None

    @pytest.mark.parametrize(
        "year_end_policy", ["GRACE_PERIOD", "NONE"],
    )
    def test_open_dcfsa_each_allowed_policy(self, api, plan_admin_headers,
                                            year_end_policy):
        """PRD §3.1: "for DEPENDENT_CARE_FSA it may be GRACE_PERIOD or
        NONE (Dependent Care never permits carryover)."

        Claim: DCFSA accepts GRACE_PERIOD and NONE.
        """
        holder = create_account_holder()
        payload = create_account_payload(
            account_holder_id=holder["id"],
            account_type="DEPENDENT_CARE_FSA", coverage_tier=None,
            year_end_policy=year_end_policy,
        )
        resp = api.create_account(payload, plan_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["account_type"] == "DEPENDENT_CARE_FSA"
        assert data["year_end_policy"] == year_end_policy

    def test_dcfsa_carryover_policy_rejected(self, api, plan_admin_headers):
        """PRD §3.1: "for DEPENDENT_CARE_FSA it may be GRACE_PERIOD or
        NONE (Dependent Care never permits carryover)."

        Claim: DCFSA with year_end_policy CARRYOVER -> ERR_BAD_REQUEST.
        """
        holder = create_account_holder()
        payload = create_account_payload(
            account_holder_id=holder["id"],
            account_type="DEPENDENT_CARE_FSA", coverage_tier=None,
            year_end_policy="CARRYOVER",
        )
        resp = api.create_account(payload, plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_hsa_non_none_policy_rejected(self, api, plan_admin_headers):
        """PRD §3.1: "for HSA it must be NONE".

        Claim: HSA with year_end_policy != NONE -> ERR_BAD_REQUEST.
        """
        holder = create_account_holder()
        payload = create_account_payload(
            account_holder_id=holder["id"],
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="GRACE_PERIOD",
        )
        resp = api.create_account(payload, plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)


# ===========================================================================
# Freeze / Unfreeze — PRD §3.1
# ===========================================================================
class TestFreezeUnfreeze:

    def test_freeze_account_transitions_to_frozen(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "Freezing transitions Account.status to FROZEN,
        refreshes updated_at, increments version, and writes an
        ACCOUNT_FROZEN audit event with cents_delta 0."

        Claim: freeze sets status to FROZEN and increments version.
        """
        _, acct = setup_holder_and_account()
        prev_version = acct["version"]
        resp = api.freeze_account(acct["id"], plan_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "FROZEN"
        assert data["version"] == prev_version + 1

    def test_freeze_already_frozen_account_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "A PlanAdministrator may freeze, unfreeze, or
        close an OPEN (or FROZEN) account. Freezing transitions
        Account.status to FROZEN".
        PRD §2.10: "the state of the target resource is checked
        against the requested transition (ERR_INVALID_STATE)".

        Claim: freezing a FROZEN account -> ERR_INVALID_STATE.
        """
        _, acct = setup_holder_and_account()
        freeze_account(acct["id"])
        resp = api.freeze_account(acct["id"], plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_unfreeze_account_transitions_to_open(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "Unfreezing transitions FROZEN back to OPEN".

        Claim: unfreeze sets status to OPEN.
        """
        _, acct = setup_holder_and_account()
        freeze_account(acct["id"])
        resp = api.unfreeze_account(acct["id"], plan_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "OPEN"

    def test_unfreeze_open_account_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "Unfreezing transitions FROZEN back to OPEN".
        PRD §2.10: "the state of the target resource is checked
        against the requested transition (ERR_INVALID_STATE)".

        Claim: unfreezing an OPEN (not FROZEN) account ->
        ERR_INVALID_STATE.
        """
        _, acct = setup_holder_and_account()
        resp = api.unfreeze_account(acct["id"], plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_frozen_account_rejects_new_plan_year(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "Frozen accounts reject every operation requiring
        an open account with ERR_ACCOUNT_NOT_OPEN: creation of plan
        years, contributions, claim creation, and claim submission."

        Claim: POST /accounts/{id}/plan-years on a frozen account ->
        ERR_ACCOUNT_NOT_OPEN.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, acct = setup_holder_and_account()
        freeze_account(acct["id"])
        resp = api.create_plan_year(
            acct["id"], {"calendar_year": 2025}, plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN.value)


# ===========================================================================
# Close — PRD §3.1
# ===========================================================================
class TestClose:

    def test_close_account_with_no_plan_years_succeeds(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "Closing an account is permitted only if no
        PlanYear is in ACTIVE, GRACE_PERIOD, or CARRYOVER_PENDING
        status ... on success, Account.status transitions to CLOSED,
        closed_at is set to the current clock value".

        Claim: closing a freshly opened account with no plan year ->
        status CLOSED + closed_at set.
        """
        _, acct = setup_holder_and_account()
        resp = api.close_account(acct["id"], plan_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CLOSED"
        assert isinstance(data["closed_at"], str), (
            f"closed_at must be set on close, got {data['closed_at']!r}"
        )

    def test_close_account_with_active_plan_year_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "Closing an account is permitted only if no
        PlanYear is in ACTIVE, GRACE_PERIOD, or CARRYOVER_PENDING
        status (otherwise rejected with ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR)".

        Claim: close with an ACTIVE plan year ->
        ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR.
        """
        _, acct, _ = setup_active_plan_year()
        resp = api.close_account(acct["id"], plan_admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR.value,
        )

    def test_close_account_with_submitted_claim_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "no Claim is in SUBMITTED or APPROVED status
        (otherwise rejected with ERR_ACCOUNT_HAS_PENDING_CLAIMS)".
        PRD §3.1 also rejects close with an open plan year as
        ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR.

        Claim: close with a SUBMITTED claim AND an ACTIVE plan year
        is rejected. Because both blockers are present and PRD does
        not pin a precedence between the two, the test accepts either
        ERR_ACCOUNT_HAS_PENDING_CLAIMS or
        ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR.
        """
        from test_helpers import validate_error_is_one_of

        _holder, _acct, _py, _qe, _claim = setup_submitted_claim()
        resp = api.close_account(_acct["id"], plan_admin_headers)
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_ACCOUNT_HAS_PENDING_CLAIMS.value,
            ApiErrorId.ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR.value,
        ])

    def test_close_account_idempotency_terminal(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "CLOSED is terminal — there is no transition back."

        Claim: closing a CLOSED account -> ERR_INVALID_STATE.
        """
        _, acct = setup_holder_and_account()
        api.close_account(acct["id"], plan_admin_headers)
        resp = api.close_account(acct["id"], plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
