"""Optimistic concurrency control and race-condition outcomes.

Covers PRD §2.7 OCC and PRD §3.4 / §3.9 race outcomes where PRD pins a
specific winner / error pair.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_enrollment,
    advance_clock_to,
    assert_exactly_one_succeeds,
    create_beneficiary,
    create_enrollment,
    create_enrollment_period,
    create_plan,
    mark_deceased,
    re_get_beneficiary,
    run_race,
    setup_clock_at,
    setup_two_pending_enrollments_same_period,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestVersionConflict:
    """PRD §2.7: ERR_VERSION_CONFLICT on stale version."""

    def test_mark_deceased_with_stale_version_rejected(
        self, api, admin_headers,
    ):
        """PRD §2.7: "when the client supplies a version value, the
        server compares it to the stored version of the target row;
        a mismatch is rejected with ERR_VERSION_CONFLICT and HTTP 409,
        and no write occurs."

        Claim: mark-deceased with stale version -> ERR_VERSION_CONFLICT.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        re_b = re_get_beneficiary(b["id"])
        current_version = re_b["version"]
        # Send a version one less than current.
        stale = max(1, current_version - 1)
        if stale == current_version:
            # First read after intake; bump by a no-op write isn't
            # available, so the only way to be 'stale' is to specify
            # version-1 explicitly. If current_version is 1 the
            # version-0 payload will trigger validation OR conflict;
            # implementations might reject as ERR_VALIDATION. Skip
            # in that edge case isn't allowed — assert one of the two.
            resp = api.mark_beneficiary_deceased(
                re_b["id"], {"version": 0}, admin_headers,
            )
            actual = validate_error_is_one_of(
                resp,
                [
                    ApiErrorId.ERR_VERSION_CONFLICT.value,
                    ApiErrorId.ERR_VALIDATION.value,
                ],
            )
            assert actual in (
                ApiErrorId.ERR_VERSION_CONFLICT.value,
                ApiErrorId.ERR_VALIDATION.value,
            )
        else:
            resp = api.mark_beneficiary_deceased(
                re_b["id"], {"version": stale}, admin_headers,
            )
            validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_omitted_version_skips_check(self, api, admin_headers):
        """PRD §2.7: "Omitting version from the body skips the check
        entirely."

        Claim: mark-deceased with no `version` field succeeds even when
        a stale value would have been rejected.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        # No version -> should succeed.
        resp = api.mark_beneficiary_deceased(b["id"], {},
                                             admin_headers)
        validate_success(resp)


class TestVersionIncrementOnMutation:
    """PRD §2.7: 'A successful mutation increments the row's version
    by one'."""

    def test_version_bumps_by_one_on_mutation(self, api, admin_headers):
        """PRD §2.7: "A successful mutation increments the row's
        version by one and refreshes updated_at to the current server
        time."

        Claim: after a successful mark-deceased, beneficiary.version
        increases by exactly one.
        """
        setup_clock_at(2026, 1, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        before = re_get_beneficiary(b["id"])
        mark_deceased(b["id"])
        after = re_get_beneficiary(b["id"])
        assert after["version"] == before["version"] + 1, (
            f"expected version {before['version'] + 1}, got "
            f"{after['version']}"
        )


class TestPeriodConsumptionRace:
    """PRD §3.9: 'Two activations citing the same EnrollmentPeriod
    serialise on EnrollmentPeriod.consumed_by_enrollment_id — exactly
    one binds the period, and the loser receives
    ERR_PERIOD_ALREADY_CONSUMED.'

    Note: PRD §3.9 names AEP periods as NOT consumed. Two activations
    against the SAME IEP period are the relevant race. For Part B
    plans this fixture builds two PENDING enrollments against one
    AEP — but AEP isn't consumed, so the race instead pins via
    ERR_DUPLICATE_PART_ENROLLMENT (PRD §3.9: "Two enrollments raced
    into the same (beneficiary_id, part_covered) pair serialise as
    first-writer-wins on the pair, and the loser receives
    ERR_DUPLICATE_PART_ENROLLMENT").

    The dual-activation-on-IEP race needs an IEP-period setup; we
    cover the AEP duplicate-part race here.
    """

    def test_duplicate_part_race_one_wins_one_fails(self, api):
        """PRD §3.9: "Two enrollments raced into the same
        (beneficiary_id, part_covered) pair serialise as
        first-writer-wins on the pair, and the loser receives
        ERR_DUPLICATE_PART_ENROLLMENT."

        Claim: two activates of two pending Part B enrollments for the
        same beneficiary -> exactly one succeeds; the loser receives
        ERR_DUPLICATE_PART_ENROLLMENT (HTTP 409).
        """
        from test_helpers import TEST_USERS
        (b, plan_a, plan_b, aep, pending_a, pending_b) = (
            setup_two_pending_enrollments_same_period(
                plan_type="PART_B", plan_year=2026,
            )
        )
        advance_clock_to("2025-10-25T00:00:00.000Z")
        results = run_race(
            lambda: api.activate_enrollment(
                pending_a["id"], {}, TEST_USERS["counselor_headers"],
            ),
            lambda: api.activate_enrollment(
                pending_b["id"], {}, TEST_USERS["counselor_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        # PRD §3.9 commits ERR_DUPLICATE_PART_ENROLLMENT as the loser
        # error_id for the (beneficiary_id, part_covered) race.
        body = loser.json()
        loser_err = body["data"]["error_id"]
        assert loser_err == ApiErrorId.ERR_DUPLICATE_PART_ENROLLMENT.value, (
            f"PRD §3.9 pins loser to ERR_DUPLICATE_PART_ENROLLMENT, "
            f"got {loser_err!r}"
        )
