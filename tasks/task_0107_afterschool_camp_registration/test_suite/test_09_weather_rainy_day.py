"""Weather posture and rainy-day reroute.

Tests cover PRD §3.8 (SessionDay state machine, rainy_day_used /
outdoor_headcount derivation, persisted-order pool consumption, weather
transition error handling).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    confirm_enrollment,
    create_enrollment,
    get_session_days,
    re_get_enrollment,
    set_weather,
    setup_authorized_child,
    setup_family_with_primary_guardian,
    setup_open_session,
    setup_n_families_each_with_authorized_child,
    validate_error,
    validate_success,
)


def _seed_confirmed_attendees(session, count: int):
    """Build `count` independent families/children/enrollments and
    confirm each in week_index 0 to drive confirmed_attendees_for_day.
    """
    actors = setup_n_families_each_with_authorized_child(
        n=count, reference_date=session["reference_date"],
    )
    confirmed = []
    for _f, _g, child in actors:
        e = create_enrollment(child=child, session=session)
        c = confirm_enrollment(enrollment=e)
        confirmed.append(c)
    return confirmed


def _find_session_day(api, session, week_index: int = 0):
    """Locate the first SessionDay for the given week_index from the
    session payload."""
    days = get_session_days(session=session)
    for d in days:
        if d.get("week_index") == week_index:
            return d
    raise AssertionError(
        f"Setup failed: could not find SessionDay for week_index="
        f"{week_index} on session {session['id']}; days={days!r}"
    )


# ===========================================================================
# Weather lifecycle
# ===========================================================================
class TestWeatherTransitions:
    def test_normal_to_rainy_succeeds(self, api):
        """PRD §3.8: "When a day transitions from NORMAL to RAINY,
        the system computes a reroute as a side-effect."
        PRD §3.8: "Setting the weather to RAINY or CLOSED is only
        permitted when the day_date is at or after the current
        calendar date on the logical clock".

        Claim: setting NORMAL→RAINY on a future day's SessionDay
        succeeds and updates weather_status to RAINY.
        """
        session = setup_open_session(
            rainy_day_pool_per_week=5, weekly_capacity=10,
        )
        day = _find_session_day(api, session)
        result = set_weather(session_day=day, weather_status="RAINY")
        assert result["weather_status"] == "RAINY"

    def test_invalid_transition_rejected(self, api):
        """PRD §3.8: "Transitions RAINY → CLOSED, CLOSED → RAINY, and
        any attempt that does not match one of the four legal pairs
        are rejected with ERR_INVALID_STATE."

        Claim: NORMAL→NORMAL (or any non-legal pair) is rejected.
        """
        session = setup_open_session(
            rainy_day_pool_per_week=5, weekly_capacity=10,
        )
        day = _find_session_day(api, session)
        # NORMAL→NORMAL is not among the four legal pairs.
        from test_helpers import set_weather_payload
        res = api.set_weather(
            day["id"], set_weather_payload(weather_status="NORMAL"),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Rainy-day reroute math
# ===========================================================================
class TestRainyDayReroute:
    def test_pool_persisted_order_chronological_assertion(self, api):
        """PRD §3.8: "The pool is therefore consumed in the order in
        which days were marked RAINY, not in chronological day-date
        order — if the later day in a week was set RAINY first and an
        earlier day is set RAINY afterward, the pool already used by
        the later day still counts against the earlier day's
        allocation, because the computation reads currently persisted
        state at the moment of the transition."

        Claim: with rainy_day_pool_per_week=5, 8 CONFIRMED attendees
        for week_index=0, and the later day set RAINY first:
          - later day: rainy_day_used=5, outdoor_headcount=3
          - earlier day set RAINY second: rainy_day_used=0,
            outdoor_headcount=8 (pool already exhausted)
        and the later day's rainy_day_used remains 5 (no reallocation).
        """
        session = setup_open_session(
            rainy_day_pool_per_week=5, weekly_capacity=10,
        )
        days = get_session_days(session=session)
        week0_days = sorted(
            (d for d in days if d.get("week_index") == 0),
            key=lambda d: d["day_date"],
        )
        assert len(week0_days) >= 2, (
            "PRD §3.3: opening a session materializes a SessionDay row "
            "for every business day in every ISO week — week 0 must "
            "yield at least 2 SessionDay rows for this test to express "
            "the persisted-order pool-consumption rule."
        )
        day_earlier, day_later = week0_days[0], week0_days[1]
        _seed_confirmed_attendees(session, count=8)
        # 1) Later day RAINY FIRST.
        late = set_weather(
            session_day=day_later, weather_status="RAINY",
        )
        assert late["rainy_day_used"] == 5
        assert late["outdoor_headcount"] == 3
        # 2) Earlier day RAINY SECOND — pool already used.
        early = set_weather(
            session_day=day_earlier, weather_status="RAINY",
        )
        assert early["rainy_day_used"] == 0
        assert early["outdoor_headcount"] == 8
        # 3) Later day unchanged — no retroactive reallocation.
        from prd_bench_local_runner.testing import get_success_data
        later_after = get_success_data(
            api.get_session_day(
                day_later["id"], TEST_USERS["admin_headers"],
            ),
        )
        assert later_after["rainy_day_used"] == 5

    def test_rainy_back_to_normal_resets_used(self, api):
        """PRD §3.8: "When a RAINY day reverts to NORMAL,
        rainy_day_used is set to zero and outdoor_headcount is set
        to confirmed_attendees_for_day."

        Claim: after setting RAINY→NORMAL, rainy_day_used==0 and
        outdoor_headcount==confirmed_attendees_for_day.
        """
        session = setup_open_session(
            rainy_day_pool_per_week=5, weekly_capacity=10,
        )
        day = _find_session_day(api, session)
        _seed_confirmed_attendees(session, count=3)
        rainy = set_weather(session_day=day, weather_status="RAINY")
        normal = set_weather(session_day=day, weather_status="NORMAL")
        assert normal["rainy_day_used"] == 0
        assert normal["outdoor_headcount"] == 3

    def test_closed_zeros_both_counters(self, api):
        """PRD §3.8: "When a day transitions from NORMAL to CLOSED,
        both outdoor_headcount and rainy_day_used are set to zero on
        that day."

        Claim: NORMAL→CLOSED sets rainy_day_used=0 and
        outdoor_headcount=0.
        """
        session = setup_open_session(
            rainy_day_pool_per_week=5, weekly_capacity=10,
        )
        day = _find_session_day(api, session)
        _seed_confirmed_attendees(session, count=3)
        closed = set_weather(session_day=day, weather_status="CLOSED")
        assert closed["rainy_day_used"] == 0
        assert closed["outdoor_headcount"] == 0
