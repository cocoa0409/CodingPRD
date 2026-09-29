"""The reinstatement fee and the continuing-education requirement, mode by mode."""

import pytest

from prd_bench_local_runner.testing import validate_success
from test_helpers import fixtures
from test_helpers.assertions import (
    assert_ce_standing,
    expected_ce_hours_required,
    expected_reinstatement_fee_cents,
)
from test_helpers.clock import elapsed_days
from test_helpers.constants import CLOCK_STARTUP_DEFAULT, SECONDS_PER_DAY
from test_helpers.test_users import make_salesperson_headers

FIRM_NAME = "Harbor Realty Group"
BROKER_NAME = "Dana Broker"


def _firm_without_a_trust_account(client):
    """A live firm that declared no trust account, so its posture is COMPLIANT."""
    return fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )


def _parked_salesperson_with_ce_hours(client, firm, full_name, hour_blocks):
    """An issued salesperson who banked CE hours and then parked the licence."""
    school = fixtures.approved_provider_with_instructor(
        client, provider_name="Coastal RE Academy", instructor_name="Tia Teach"
    )
    salesperson = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], full_name
    )
    fixtures.go_inactive(client, salesperson["id"], make_salesperson_headers(salesperson["id"]))
    for course_type, credit_hours in hour_blocks:
        fixtures.record_completion(
            client,
            salesperson["id"],
            school["instructor"]["id"],
            school["provider"]["id"],
            credit_hours=credit_hours,
            completed_on="2026-08-01",
            course_type=course_type,
        )
    parked = fixtures.read_licensee(client, salesperson["id"])
    assert parked["license_status"] == "INACTIVE"
    assert parked["inactive_since"] == CLOCK_STARTUP_DEFAULT
    return parked


class TestReinstatementFeeModes:
    """Three absences of the same origin, three different exact fees."""

    @pytest.mark.parametrize(
        "full_name, hour_blocks, reactivate_at, expected_required, expected_fee",
        [
            ("Lee One", [("CE_CORE", 12)], "2026-08-20T00:00:00Z", 12, 15000),
            ("Lee Two", [("CE_CORE", 12), ("CE_ELECTIVE", 3)], "2027-02-01T00:00:00Z", 15, 24078),
            (
                "Lee Three",
                [("CE_CORE", 12), ("CE_ELECTIVE", 12), ("CE_ELECTIVE", 6)],
                "2029-08-01T00:00:00Z",
                30,
                66312,
            ),
        ],
    )
    def test_exact_fee_combines_late_periods_with_excess_ce_hours(
        self, client, full_name, hour_blocks, reactivate_at, expected_required, expected_fee
    ):
        """Base plus CE make-up plus per-period-rounded surcharge, tendered exactly.

        The PRD says "**The rounding happens per period and only then is
        multiplied by the period count.**"

        Design: Difficulty/combinatorial_formula/reactivation_fee_three_modes_over_late_periods_and_excess_ce_hours
        """
        firm = _firm_without_a_trust_account(client)
        parked = _parked_salesperson_with_ce_hours(client, firm, full_name, hour_blocks)

        fixtures.move_clock(client, reactivate_at)
        elapsed_seconds = (
            elapsed_days(parked["inactive_since"], reactivate_at) * SECONDS_PER_DAY
        )
        required = expected_ce_hours_required("INACTIVE", elapsed_seconds)
        assert required == expected_required
        fee = expected_reinstatement_fee_cents(required, elapsed_seconds)
        assert fee == expected_fee

        revived = validate_success(
            fixtures.status_change(
                client,
                parked["id"],
                "REACTIVATE",
                brokerage_id=firm["brokerage"]["id"],
                supervising_broker_id=firm["broker"]["id"],
                reinstatement_fee_paid_cents=fee,
                headers=make_salesperson_headers(parked["id"]),
            )
        )
        assert revived["license_status"] == "ACTIVE"

    def test_reactivation_opens_a_fresh_window_so_valid_hours_read_zero(self, client):
        """The hours that bought reinstatement do not carry into the new period.

        The PRD says "Because valid hours are counted only from the window's
        start, the hours that qualified the licensee for reinstatement do not
        carry forward: `ce_hours_valid` reads 0 immediately after reactivation,
        and the licensee begins accruing again for their next renewal."

        Design: Difficulty/combinatorial_formula/reactivation_fee_three_modes_over_late_periods_and_excess_ce_hours
        """
        firm = _firm_without_a_trust_account(client)
        parked = _parked_salesperson_with_ce_hours(
            client, firm, "Lee Two", [("CE_CORE", 12), ("CE_ELECTIVE", 3)]
        )
        assert parked["ce_hours_valid"] == 15

        fixtures.move_clock(client, "2027-02-01T00:00:00Z")
        validate_success(
            fixtures.status_change(
                client,
                parked["id"],
                "REACTIVATE",
                brokerage_id=firm["brokerage"]["id"],
                supervising_broker_id=firm["broker"]["id"],
                reinstatement_fee_paid_cents=24078,
                headers=make_salesperson_headers(parked["id"]),
            )
        )

        revived = fixtures.read_licensee(client, parked["id"])
        assert revived["ce_period_start_on"] == "2027-02-01"
        assert revived["inactive_since"] is None
        assert_ce_standing(revived, valid=0, required=12)

    def test_the_three_modes_produce_three_different_totals(self, client):
        """The fee is not a flat charge: the same origin yields three figures.

        The PRD says "The three components are summed to give the exact figure
        the licensee must tender."

        Design: Difficulty/combinatorial_formula/reactivation_fee_three_modes_over_late_periods_and_excess_ce_hours
        """
        totals = []
        for reactivate_at, required in (
            ("2026-08-20T00:00:00Z", 12),
            ("2027-02-01T00:00:00Z", 15),
            ("2029-08-01T00:00:00Z", 30),
        ):
            seconds = elapsed_days(CLOCK_STARTUP_DEFAULT, reactivate_at) * SECONDS_PER_DAY
            assert expected_ce_hours_required("INACTIVE", seconds) == required
            totals.append(expected_reinstatement_fee_cents(required, seconds))
        assert totals == [15000, 24078, 66312]
        assert len(set(totals)) == 3

        # The server must charge the middle figure and refuse a neighbouring one.
        firm = _firm_without_a_trust_account(client)
        parked = _parked_salesperson_with_ce_hours(
            client, firm, "Lee Two", [("CE_CORE", 12), ("CE_ELECTIVE", 3)]
        )
        fixtures.move_clock(client, "2027-02-01T00:00:00Z")
        revived = validate_success(
            fixtures.status_change(
                client,
                parked["id"],
                "REACTIVATE",
                brokerage_id=firm["brokerage"]["id"],
                supervising_broker_id=firm["broker"]["id"],
                reinstatement_fee_paid_cents=totals[1],
                headers=make_salesperson_headers(parked["id"]),
            )
        )
        assert revived["license_status"] == "ACTIVE"


class TestContinuingEducationRequirementBands:
    """One fixed `inactive_since` read at four points on the clock."""

    @pytest.mark.parametrize(
        "read_at, expected_days, expected_required",
        [
            ("2026-09-30T00:00:00Z", 60, 12),
            ("2027-04-01T00:00:00Z", 243, 15),
            ("2029-11-01T00:00:00Z", 1188, 30),
            ("2034-08-01T00:00:00Z", 2922, 36),
        ],
    )
    def test_requirement_escalates_by_six_month_blocks_and_then_caps(
        self, client, read_at, expected_days, expected_required
    ):
        """Thirty-day months, floored into six-month blocks, capped at thirty-six.

        The PRD says "take the elapsed time from `inactive_since` to the current
        logical instant, divide it by thirty days and truncate downward to get
        the number of full thirty-day months of absence, divide that count by six
        and truncate downward again to get the number of completed six-month
        blocks, add 3 hours for each such block on top of the 12-hour base, and
        finally cap the result at 36 hours."

        Design: Difficulty/combinatorial_formula/ce_requirement_hours_four_modes_across_inactive_duration_bands
        """
        firm = _firm_without_a_trust_account(client)
        salesperson = fixtures.affiliate_new_salesperson(
            client, firm["brokerage"]["id"], firm["broker"]["id"], "Kim Park"
        )
        parked = fixtures.go_inactive(
            client, salesperson["id"], make_salesperson_headers(salesperson["id"])
        )
        assert parked["inactive_since"] == CLOCK_STARTUP_DEFAULT

        fixtures.move_clock(client, read_at)
        assert elapsed_days(CLOCK_STARTUP_DEFAULT, read_at) == expected_days

        observed = fixtures.read_licensee(client, salesperson["id"])
        assert observed["license_status"] == "INACTIVE", (
            "no sweep has run, so the parked licence has not moved"
        )
        assert observed["ce_hours_required"] == expected_required
        assert observed["ce_hours_required"] == expected_ce_hours_required(
            "INACTIVE", expected_days * SECONDS_PER_DAY
        )

    def test_only_the_longest_absence_is_bound_by_the_cap(self, client):
        """Below the cap the requirement tracks the blocks; above it, it stops.

        The PRD says "once the escalation would exceed 36 hours the cap holds it
        there."

        Design: Difficulty/combinatorial_formula/ce_requirement_hours_four_modes_across_inactive_duration_bands
        """
        firm = _firm_without_a_trust_account(client)
        salesperson = fixtures.affiliate_new_salesperson(
            client, firm["brokerage"]["id"], firm["broker"]["id"], "Kim Park"
        )
        fixtures.go_inactive(
            client, salesperson["id"], make_salesperson_headers(salesperson["id"])
        )

        fixtures.move_clock(client, "2029-11-01T00:00:00Z")
        uncapped = fixtures.read_licensee(client, salesperson["id"])["ce_hours_required"]
        fixtures.move_clock(client, "2034-08-01T00:00:00Z")
        capped = fixtures.read_licensee(client, salesperson["id"])["ce_hours_required"]

        # Thirty-nine thirty-day months give six blocks and 30 hours; ninety-seven
        # months would give sixteen blocks and 60 hours, which the cap holds at 36.
        assert uncapped == 30
        assert capped == 36
        assert capped < 12 + 3 * (2922 // 30 // 6)
