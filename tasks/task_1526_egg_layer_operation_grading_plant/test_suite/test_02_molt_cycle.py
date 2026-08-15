"""Flock molt cycle: induce/resume boundaries and the completed-molt cap."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_flock,
    set_clock,
    setup_laying_flock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import FARM_MANAGER

MOLT_AGE_CLOCK = "2027-03-01T00:00:00Z"  # placement 2026-01-05 + 420 days = 60 weeks
MOLT_AGE_MINUS_ONE_CLOCK = "2027-02-28T00:00:00Z"  # 419 days = 59 weeks


def _aged_laying_flock(api, clock_iso):
    return setup_laying_flock(
        clock_iso=clock_iso,
        flock_overrides={"initial_hen_count": 800, "pullet_cost_cents": 336000},
    )


class TestMoltCycle:
    def test_molt_cycle_returns_to_laying_then_second_molt_rejected(self, api):
        """PRD §3.2: "A `FarmManager` may induce a molt in a `LAYING` flock,
        moving it to `MOLT_REST`, only when three conditions hold: the flock's
        `age_weeks` is at least 60 — exactly 60 is eligible — else
        `ERR_MOLT_AGE_INELIGIBLE` (HTTP 422); its `molt_count` is still below
        the hard cap of 1 completed molt, else `ERR_MOLT_LIMIT_REACHED`
        (HTTP 422); and its `quarantine_status` is `CLEAR`, else
        `ERR_UNRESOLVED_POSITIVE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/flock_molt_cycle_returns_to_laying_then_caps
        """
        ctx = _aged_laying_flock(api, MOLT_AGE_CLOCK)
        flock_id = ctx["flock"]["id"]

        rested = validate_success(api.induce_molt(flock_id, FARM_MANAGER))
        assert rested["status"] == "MOLT_REST"

        set_clock("2027-03-15T00:00:00Z")
        resumed = validate_success(api.resume_lay(flock_id, FARM_MANAGER))
        assert resumed["status"] == "LAYING", "the molt loop must cycle back to LAYING"

        resp = api.induce_molt(flock_id, FARM_MANAGER)
        validate_error(resp, ApiErrorId.ERR_MOLT_LIMIT_REACHED)
        assert get_flock(flock_id)["status"] == "LAYING", (
            "a failed second induce-molt must not move the flock"
        )

    def test_molt_cycle_lay_cycle_second_after_resume(self, api):
        """PRD §3.2: "Resuming increments `molt_count` by 1, sets `lay_cycle`
        to `SECOND` (so the lay curve thereafter applies the 0.85 post-molt
        factor), and increments the flock's `version` by 1."

        Design: Difficulty/non_linear_state_machine/flock_molt_cycle_returns_to_laying_then_caps
        """
        ctx = _aged_laying_flock(api, MOLT_AGE_CLOCK)
        flock_id = ctx["flock"]["id"]

        validate_success(api.induce_molt(flock_id, FARM_MANAGER))
        set_clock("2027-03-15T00:00:00Z")
        resumed = validate_success(api.resume_lay(flock_id, FARM_MANAGER))
        assert resumed["lay_cycle"] == "SECOND", (
            f"one completed molt must flip lay_cycle to SECOND, got "
            f"{resumed['lay_cycle']}"
        )
        assert resumed["molt_count"] == 1
        assert resumed["status"] == "LAYING"


class TestMoltBoundary:
    def test_molt_eligibility_rejected_at_59_weeks(self, api):
        """PRD §3.2: "A `FarmManager` may induce a molt in a `LAYING` flock,
        moving it to `MOLT_REST`, only when three conditions hold: the flock's
        `age_weeks` is at least 60 — exactly 60 is eligible — else
        `ERR_MOLT_AGE_INELIGIBLE` (HTTP 422)"

        Design: Difficulty/boundary_precision_check/molt_eligibility_at_exactly_60_weeks
        """
        ctx = _aged_laying_flock(api, MOLT_AGE_MINUS_ONE_CLOCK)
        flock_id = ctx["flock"]["id"]
        assert ctx["flock"]["age_weeks"] == 59

        resp = api.induce_molt(flock_id, FARM_MANAGER)
        validate_error(resp, ApiErrorId.ERR_MOLT_AGE_INELIGIBLE)
        flock = get_flock(flock_id)
        assert flock["status"] == "LAYING"
        assert flock["molt_count"] == 0

    def test_molt_eligibility_succeeds_at_exactly_60_weeks(self, api):
        """PRD §3.2: "A `FarmManager` may induce a molt in a `LAYING` flock,
        moving it to `MOLT_REST`, only when three conditions hold: the flock's
        `age_weeks` is at least 60 — exactly 60 is eligible — else
        `ERR_MOLT_AGE_INELIGIBLE` (HTTP 422)"
        PRD §3.2: "Inducing the molt stamps `molt_started_date` to the clock
        date, drops `current_lay_rate_pct` to 0.00 for the duration of the
        rest, and increments the flock's `version` by 1."

        Design: Difficulty/boundary_precision_check/molt_eligibility_at_exactly_60_weeks
        """
        ctx = _aged_laying_flock(api, MOLT_AGE_CLOCK)
        flock_id = ctx["flock"]["id"]
        assert ctx["flock"]["age_weeks"] == 60

        rested = validate_success(api.induce_molt(flock_id, FARM_MANAGER))
        assert rested["status"] == "MOLT_REST"
        assert rested["molt_started_date"][:10] == "2027-03-01", (
            f"molt_started_date must stamp the clock date 2027-03-01, got "
            f"{rested['molt_started_date']!r}"
        )
        assert rested["current_lay_rate_pct"] == pytest.approx(0.00)


class TestMoltRestDuration:
    def test_resume_lay_before_14_rest_days_rejected(self, api):
        """PRD §3.2: "Returning from molt rest is the mirror action: a
        `FarmManager` resumes lay, moving the flock from `MOLT_REST` back to
        `LAYING`, only once the clock date is at least 14 days after
        `molt_started_date`; an earlier attempt is rejected with
        `ERR_MOLT_REST_TOO_SHORT` (HTTP 422)."

        Design: Corner/validations/resume_lay_before_14_rest_days_rejected
        """
        ctx = _aged_laying_flock(api, MOLT_AGE_CLOCK)
        flock_id = ctx["flock"]["id"]
        validate_success(api.induce_molt(flock_id, FARM_MANAGER))

        set_clock("2027-03-10T00:00:00Z")  # 9 days into the rest
        resp = api.resume_lay(flock_id, FARM_MANAGER)
        validate_error(resp, ApiErrorId.ERR_MOLT_REST_TOO_SHORT)

        flock = get_flock(flock_id)
        assert flock["status"] == "MOLT_REST"
        assert flock["molt_count"] == 0
