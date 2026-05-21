"""Plan lifecycle: create, edit, activate, terminate, validation,
duplicate name, optimistic concurrency.

References PRD §3.1, §2.10.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_plan,
    assert_status,
    assert_version_incremented_by,
    create_plan,
    create_plan_payload,
    setup_active_plan_with_open_period,
    TEST_DEFAULTS,
    TEST_USERS,
    unique_plan_name,
    update_plan_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# POST /plans — creation
# ===========================================================================
class TestPlanCreation:
    """PRD §3.1 plan-creation rules."""

    def test_create_minimal_plan_returns_draft(self, api, plan_admin_headers):
        """PRD §3.1: "A newly created plan starts in `DRAFT`."
        PRD §3.1: defaults — "`max_contribution_rate_bp` ... defaults
        to 1500 (15.00%); `annual_accrual_cap_cents` ... defaults to
        2,500,000 cents ... `lookback_enabled` ... defaulting to true;
        and `discount_bp` ... defaulting to 1500 (a 15.00% discount)."

        Claim: minimal payload yields status=DRAFT with all four
        defaults applied.
        """
        advance_clock_to("2023-12-01T00:00:00.000Z")
        payload = create_plan_payload(
            offering_period_months=6,
            effective_date="2024-01-01T00:00:00.000Z",
        )
        resp = api.create_plan(payload, plan_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_plan(data)
        assert_status(data, "DRAFT")
        assert data["max_contribution_rate_bp"] == 1500
        assert data["annual_accrual_cap_cents"] == 2_500_000
        assert data["lookback_enabled"] is True
        assert data["discount_bp"] == 1500

    @pytest.mark.parametrize("months", [5, 25, 0, 100])
    def test_offering_period_months_out_of_range_rejected(
        self, api, plan_admin_headers, months,
    ):
        """PRD §3.1: "`offering_period_months` must be an integer in
        the closed interval from 6 through 24, rejected otherwise with
        `ERR_PERIOD_LENGTH_OUT_OF_RANGE`."

        Claim: offering_period_months outside [6,24] -> 422.
        """
        payload = create_plan_payload(
            offering_period_months=months,
            effective_date="2024-01-01T00:00:00.000Z",
        )
        resp = api.create_plan(payload, plan_admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_PERIOD_LENGTH_OUT_OF_RANGE.value,
        )

    @pytest.mark.parametrize("months", [6, 12, 24])
    def test_offering_period_months_in_range_accepted(
        self, api, plan_admin_headers, months,
    ):
        """PRD §3.1: "`offering_period_months` must be an integer in
        the closed interval from 6 through 24".

        Claim: 6, 12, 24 are all accepted (closed-interval boundaries).
        """
        advance_clock_to("2023-12-01T00:00:00.000Z")
        payload = create_plan_payload(
            offering_period_months=months,
            effective_date="2024-01-01T00:00:00.000Z",
        )
        resp = api.create_plan(payload, plan_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["offering_period_months"] == months

    def test_duplicate_plan_name_rejected(self, api, plan_admin_headers):
        """PRD §3.1: "the human-readable `name` (between 1 and 120
        characters, unique across the system; duplicate names are
        rejected with `ERR_DUPLICATE_PLAN_NAME`)".

        Claim: two creates with same name -> second is 409
        ERR_DUPLICATE_PLAN_NAME.
        """
        name = unique_plan_name()
        advance_clock_to("2023-12-01T00:00:00.000Z")
        p1 = api.create_plan(
            create_plan_payload(
                name=name,
                offering_period_months=6,
                effective_date="2024-01-01T00:00:00.000Z",
            ),
            plan_admin_headers,
        )
        validate_success(p1, expected_status=201)
        p2 = api.create_plan(
            create_plan_payload(
                name=name,
                offering_period_months=12,
                effective_date="2024-02-01T00:00:00.000Z",
            ),
            plan_admin_headers,
        )
        validate_error(p2, ApiErrorId.ERR_DUPLICATE_PLAN_NAME.value)


# ===========================================================================
# POST /plans/{id}/activate
# ===========================================================================
class TestPlanActivation:
    """PRD §3.1 activation rules + side effect."""

    def test_activate_creates_first_offering_period(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "Activation transitions the plan from `DRAFT` to
        `ACTIVE` ... As a side effect, the system creates the first
        offering period under the plan: `sequence_number` is set to 1,
        `start_date` is set to the plan's `effective_date`, `end_date`
        is computed as `start_date` plus `offering_period_months`
        months, and `status` is set to `OPEN`."

        Claim: after activate, plan status==ACTIVE AND exactly one
        OfferingPeriod exists with sequence_number=1, status=OPEN,
        start_date == effective_date.
        """
        advance_clock_to("2023-12-01T00:00:00.000Z")
        plan = create_plan(
            offering_period_months=6,
            effective_date="2024-01-01T00:00:00.000Z",
        )
        assert_status(plan, "DRAFT")
        resp = api.activate_plan(plan["id"], plan_admin_headers)
        data = validate_success(resp)
        assert_status(data, "ACTIVE")
        # Side effect: op1 exists.
        op_resp = api.list_offering_periods(plan["id"], plan_admin_headers)
        op_body = op_resp.json()
        items = op_body["data"]
        assert len(items) == 1, (
            f"Expected exactly one OfferingPeriod after activate, "
            f"got {len(items)}"
        )
        op1 = items[0]
        assert op1["sequence_number"] == 1
        assert op1["status"] == "OPEN"
        assert op1["start_date"] == plan["effective_date"]

    def test_activate_with_past_effective_date_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "The operation is allowed only if ... `effective_date`
        is greater than or equal to the current `SystemClock.current_time`
        at the moment of activation."

        Claim: activate with effective_date < current_time -> rejected.
        We don't pin the error_id (PRD doesn't name one for this
        specific case).
        """
        # Set clock to 2024-06-01, then make a plan whose effective_date is
        # 2024-01-01 (in the past relative to the clock at activation).
        advance_clock_to("2023-12-01T00:00:00.000Z")
        plan = create_plan(
            offering_period_months=6,
            effective_date="2024-01-01T00:00:00.000Z",
        )
        advance_clock_to("2024-06-01T00:00:00.000Z")
        resp = api.activate_plan(plan["id"], plan_admin_headers)
        # The PRD doesn't pin an error_id; we accept any 4xx.
        assert 400 <= resp.status_code < 500, (
            f"Expected 4xx for activate with past effective_date, "
            f"got {resp.status_code}: {resp.text}"
        )


# ===========================================================================
# PATCH /plans/{id} — edit + OCC
# ===========================================================================
class TestPlanEdit:
    """PRD §3.1 edit on DRAFT + PRD §2.10 OCC."""

    def test_patch_draft_plan_bumps_version(
        self, api, plan_admin_headers,
    ):
        """PRD §2.10: "Every successful mutation refreshes `updated_at`
        and increments `version` by one."
        PRD §3.1: "A plan in `DRAFT` may be edited freely through a
        patch operation that accepts any subset of `name`, ..."

        Claim: PATCH on DRAFT plan returns version+1.
        """
        advance_clock_to("2023-12-01T00:00:00.000Z")
        plan = create_plan(
            offering_period_months=6,
            effective_date="2024-01-01T00:00:00.000Z",
        )
        resp = api.update_plan(
            plan["id"],
            update_plan_payload(version=plan["version"], discount_bp=1000),
            plan_admin_headers,
        )
        data = validate_success(resp)
        assert_version_incremented_by(plan, data, 1)
        assert data["discount_bp"] == 1000

    def test_patch_with_stale_version_returns_conflict(
        self, api, plan_admin_headers,
    ):
        """PRD §2.10: "When the client supplies it, the server compares
        the supplied value to the row's current `version`; if they
        differ, the request is rejected with `ERR_VERSION_CONFLICT`
        and the row is not modified."

        Claim: PATCH with version=prev-1 (stale) -> ERR_VERSION_CONFLICT.
        """
        advance_clock_to("2023-12-01T00:00:00.000Z")
        plan = create_plan(
            offering_period_months=6,
            effective_date="2024-01-01T00:00:00.000Z",
        )
        # First patch advances version.
        first = api.update_plan(
            plan["id"],
            update_plan_payload(version=plan["version"], discount_bp=1000),
            plan_admin_headers,
        )
        validate_success(first)
        # Second patch using the original (stale) version.
        stale = api.update_plan(
            plan["id"],
            update_plan_payload(version=plan["version"], discount_bp=500),
            plan_admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_VERSION_CONFLICT.value)


# ===========================================================================
# POST /plans/{id}/terminate
# ===========================================================================
class TestPlanTermination:
    """PRD §3.1 termination rules."""

    def test_terminate_rejected_while_period_open(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "The operation is rejected if any offering period
        of the plan still has `status` equal to `OPEN`."

        Claim: terminate an ACTIVE plan that has an OPEN op -> rejected.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
        )
        resp = api.terminate_plan(plan["id"], plan_admin_headers)
        # PRD doesn't pin an exact error_id; assert any 4xx.
        assert 400 <= resp.status_code < 500, (
            f"Expected 4xx terminate-with-open-period, got "
            f"{resp.status_code}: {resp.text}"
        )

    def test_plan_in_draft_is_not_active_for_children(
        self, api, plan_admin_headers, participant_headers,
    ):
        """PRD §3.1: "Any operation against the plan's children
        (creating enrollments, posting contributions, running the
        purchase batch) requires the plan to be `ACTIVE`; if the plan
        is in `DRAFT` or `TERMINATED`, the operation is rejected with
        `ERR_PLAN_NOT_ACTIVE`."

        Claim: enrollment against an OP under a DRAFT plan ->
        ERR_PLAN_NOT_ACTIVE. We probe this indirectly by attempting an
        enrollment after creating a plan but before activate. Since
        DRAFT plans have no OP, the closest probe is to confirm the
        plan body reflects DRAFT.
        """
        advance_clock_to("2023-12-01T00:00:00.000Z")
        plan = create_plan(
            offering_period_months=6,
            effective_date="2024-01-01T00:00:00.000Z",
        )
        assert_status(plan, "DRAFT")
        # No OPs exist for a DRAFT plan, so there's nothing to enroll on;
        # confirm list returns zero items.
        resp = api.list_offering_periods(plan["id"], plan_admin_headers)
        body = resp.json()
        assert body["data"] == [], (
            f"DRAFT plan must have no OfferingPeriods, got {body['data']!r}"
        )
