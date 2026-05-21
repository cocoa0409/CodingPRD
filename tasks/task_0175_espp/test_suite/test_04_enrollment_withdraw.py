"""Enrollment lifecycle: create, rate change, withdrawal, ownership,
uniqueness, rate range.

References PRD §3.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    advance_clock_to,
    assert_enrollment,
    assert_status,
    assert_version_incremented_by,
    create_enrollment_payload,
    enroll_participant,
    make_participant_headers,
    new_participant_id,
    post_contribution,
    purchase_fmv_payload,
    run_sweep,
    setup_active_plan_with_open_period,
    setup_enrollment_with_contributions,
    setup_period_at_closed_state,
    TEST_USERS,
    update_enrollment_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# POST /offering-periods/{op}/enrollments
# ===========================================================================
class TestEnrollmentCreate:
    """PRD §3.3 enrollment-create rules."""

    def test_create_enrollment_records_participant_id_from_header(
        self, api,
    ):
        """PRD §3.3: "The system records the enrollment with
        `offering_period_id` set to the period in the URL,
        `participant_id` set to the caller's `X-User-ID`, the elected
        `contribution_rate_bp`, an initial `status` of `ACTIVE`, and an
        initial `ytd_accrual_cents` of 0."

        Claim: created enrollment carries participant_id == X-User-ID
        AND status==ACTIVE AND ytd_accrual_cents==0.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid = new_participant_id()
        resp = api.create_enrollment(
            op1["id"],
            create_enrollment_payload(contribution_rate_bp=1000),
            make_participant_headers(pid),
        )
        data = validate_success(resp, expected_status=201)
        assert_enrollment(data)
        assert data["participant_id"] == pid
        assert_status(data, "ACTIVE")
        assert data["ytd_accrual_cents"] == 0
        assert data["offering_period_id"] == op1["id"]

    @pytest.mark.parametrize("rate_bp", [0, -1, 1501, 5000])
    def test_invalid_contribution_rate_rejected(
        self, api, rate_bp,
    ):
        """PRD §3.3: "a positive integer no greater than the plan's
        `max_contribution_rate_bp` ceiling. A rate of zero or a rate
        above the plan ceiling is rejected with
        `ERR_CONTRIBUTION_RATE_OUT_OF_RANGE`."

        Claim: rate_bp 0 or > 1500 -> ERR_CONTRIBUTION_RATE_OUT_OF_RANGE.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid = new_participant_id()
        resp = api.create_enrollment(
            op1["id"],
            create_enrollment_payload(contribution_rate_bp=rate_bp),
            make_participant_headers(pid),
        )
        validate_error(
            resp, ApiErrorId.ERR_CONTRIBUTION_RATE_OUT_OF_RANGE.value,
        )

    def test_duplicate_enrollment_rejected(self, api):
        """PRD §3.3: "The combination of `offering_period_id` and
        `participant_id` is unique: a participant cannot hold two
        enrollments in the same period. Two simultaneous enrollments
        by the same participant in the same period serialize on this
        uniqueness invariant — exactly one wins and the loser receives
        `ERR_DUPLICATE_ENROLLMENT`."

        Claim: second enrollment by same participant -> 409
        ERR_DUPLICATE_ENROLLMENT.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid = new_participant_id()
        h = make_participant_headers(pid)
        first = api.create_enrollment(
            op1["id"],
            create_enrollment_payload(contribution_rate_bp=500),
            h,
        )
        validate_success(first, expected_status=201)
        # Second attempt by the same participant.
        second = api.create_enrollment(
            op1["id"],
            create_enrollment_payload(contribution_rate_bp=700),
            h,
        )
        validate_error(second, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value)

    def test_enroll_on_closed_period_rejected(
        self, api,
    ):
        """PRD §3.2: "From `CLOSED`, any subsequent attempt to create
        an enrollment referencing the period ... is rejected with
        `ERR_PERIOD_NOT_OPEN`."

        Claim: POST /offering-periods/{op-CLOSED}/enrollments ->
        ERR_PERIOD_NOT_OPEN.
        """
        plan, op_closed, _pid, _enr = setup_period_at_closed_state()
        assert op_closed["status"] == "CLOSED"
        pid = new_participant_id()
        resp = api.create_enrollment(
            op_closed["id"],
            create_enrollment_payload(contribution_rate_bp=500),
            make_participant_headers(pid),
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)


# ===========================================================================
# PATCH /enrollments/{id} — rate change + OCC
# ===========================================================================
class TestEnrollmentEdit:
    """PRD §3.3 rate-change + §2.10 OCC."""

    def test_patch_changes_rate_and_bumps_version(self, api):
        """PRD §3.3: "A participant may change their elected rate while
        the parent offering period is still `OPEN` and the enrollment
        is still `ACTIVE`. The patch accepts a new `contribution_rate_bp`
        ... and an optional `version` for optimistic concurrency."
        PRD §2.10: version increments by one on every mutation.

        Claim: PATCH new rate -> 200, contribution_rate_bp updated,
        version+1.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enrollment = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=500,
        )
        h = make_participant_headers(pid)
        resp = api.update_enrollment(
            enrollment["id"],
            update_enrollment_payload(
                contribution_rate_bp=1000, version=enrollment["version"],
            ),
            h,
        )
        data = validate_success(resp)
        assert data["contribution_rate_bp"] == 1000
        assert_version_incremented_by(enrollment, data, 1)

    def test_patch_on_withdrawn_enrollment_rejected(self, api):
        """PRD §3.3: "A patch against an enrollment whose status has
        already moved to `WITHDRAWN` or `COMPLETED` is rejected with
        `ERR_INVALID_ENROLLMENT_STATE`."

        Claim: PATCH after withdraw -> ERR_INVALID_ENROLLMENT_STATE.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enrollment = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=500,
        )
        h = make_participant_headers(pid)
        w = api.withdraw_enrollment(enrollment["id"], h)
        validate_success(w)
        # Now PATCH should fail.
        resp = api.update_enrollment(
            enrollment["id"],
            update_enrollment_payload(
                contribution_rate_bp=1000,
                version=enrollment["version"] + 1,
            ),
            h,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENROLLMENT_STATE.value)


# ===========================================================================
# POST /enrollments/{id}/withdraw — PRD §3.3
# ===========================================================================
class TestEnrollmentWithdraw:

    def test_withdraw_owner_succeeds_and_refunds_posted(self, api):
        """PRD §3.3: "Withdrawal moves an enrollment from `ACTIVE` to
        `WITHDRAWN`. The operation is allowed only to the owning
        `Participant` ... As a side effect, every `Contribution` on
        the enrollment whose status is currently `POSTED` is flipped
        to `REFUNDED`."

        Claim: withdraw -> enrollment.status==WITHDRAWN AND every prior
        POSTED contribution now has status==REFUNDED.
        """
        plan, op1, pid, enrollment = setup_enrollment_with_contributions(
            grant_date_fmv_cents=1000,
            contribution_amount_cents=1500,
            contribution_rate_bp=1500,
        )
        # Add a second contribution.
        post_contribution(
            enrollment_id=enrollment["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=10_000,
        )
        h = make_participant_headers(pid)
        w = api.withdraw_enrollment(enrollment["id"], h)
        data = validate_success(w)
        assert_status(data, "WITHDRAWN")
        # Every contribution should now be REFUNDED (no longer POSTED).
        clist = api.list_contributions(
            enrollment["id"], TEST_USERS["plan_admin_headers"],
            params={"limit": 100, "offset": 0},
        )
        items = clist.json()["data"]
        assert len(items) >= 2
        for c in items:
            assert c["status"] == "REFUNDED", (
                f"After withdraw, every prior POSTED contribution "
                f"must be REFUNDED; got {c['status']!r}"
            )

    def test_withdraw_by_non_owner_rejected(self, api):
        """PRD §3.3: "The operation is allowed only to the owning
        `Participant` (`X-User-ID` must equal the enrollment's
        `participant_id`, otherwise `ERR_NOT_OWNER`)."

        Claim: withdraw with X-User-ID != enrollment.participant_id ->
        ERR_NOT_OWNER.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enrollment = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=500,
        )
        attacker = new_participant_id()
        resp = api.withdraw_enrollment(
            enrollment["id"], make_participant_headers(attacker),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)
