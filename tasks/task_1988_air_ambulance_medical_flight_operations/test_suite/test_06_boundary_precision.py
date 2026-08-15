"""Boundary precision: X-1 / X / X+1 around numeric thresholds (weather
visibility, rolling duty minutes, membership effective-date equality)."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    close_shift,
    create_base,
    create_crew_member,
    create_crew_shift,
    get_success_data,
    post_weather,
    set_clock,
    setup_member_protected_submitted_invoice,
    setup_planning_mission,
    validate_error,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


class TestWeatherVisibilityExactlyAtMinimum:
    def _setup(self):
        ctx = setup_planning_mission(
            transport_class="EMERGENCY_SCENE", origin_facility="Mile 9 US-60"
        )
        return ctx, ctx["roster"]["PILOT"], ctx["mission"]

    def test_visibility_exactly_at_minimum_passes_no_go_and_lands_marginal(self):
        """PRD §3.4: "The required visibility is 1.0 statute mile for a
        rotor-wing by day ... The decision is `NO_GO` when any of the following
        holds: ... or the visibility is strictly below the required visibility.
        Otherwise the decision is `MARGINAL` when any of the following holds:
        ... the visibility is strictly below the required visibility plus
        one-half statute mile ..."
        PRD §3.4: "The boundaries are pinned: a ceiling exactly equal to the
        requirement passes, as does visibility exactly equal to the requirement;
        a ceiling exactly 1.2 times the requirement is `GO`, not `MARGINAL`; and
        a crosswind exactly equal to the maximum passes, because the violation
        test is strict."

        Design: Difficulty/boundary_precision_check/weather_visibility_exactly_at_minimum
        """
        ctx, pilot, mission = self._setup()
        # ROTOR_WING DAY FLAT: 1.0 == required -> not NO_GO; 1.0 < 1.0+0.5 -> MARGINAL.
        wa = post_weather(mission["id"], mission["version"], pilot,
                          ceiling_ft=2000, visibility_sm=1.0, wind_kt=10)
        assert wa["decision"] == "MARGINAL", (
            f"Visibility exactly at the 1.0 minimum must escape NO_GO and land in the "
            f"MARGINAL band, got {wa['decision']}"
        )

    def test_visibility_one_tenth_below_minimum_is_no_go(self):
        """PRD §3.4: "The decision is `NO_GO` when any of the following holds:
        the `precip` is `ICE`; the crosswind strictly exceeds the maximum; the
        ceiling is strictly below the required ceiling; or the visibility is
        strictly below the required visibility."
        PRD §3.4: "The boundaries are pinned: a ceiling exactly equal to the
        requirement passes, as does visibility exactly equal to the requirement;
        a ceiling exactly 1.2 times the requirement is `GO`, not `MARGINAL`; and
        a crosswind exactly equal to the maximum passes, because the violation
        test is strict."

        Design: Difficulty/boundary_precision_check/weather_visibility_exactly_at_minimum
        """
        ctx, pilot, mission = self._setup()
        wa = post_weather(mission["id"], mission["version"], pilot,
                          ceiling_ft=2000, visibility_sm=0.9, wind_kt=10)
        assert wa["decision"] == "NO_GO", (
            f"Visibility 0.9 is strictly below the 1.0 minimum, got {wa['decision']}"
        )
        refreshed = get_success_data(api_client.get_mission(mission["id"], DISP))
        assert refreshed["last_weather_decision"] == "NO_GO"


class TestDutyMinutesExactly840Allowed:
    def _setup_member_with_600_min_shift(self):
        set_clock("2026-08-01T00:00:00Z")
        base = create_base(name="Base Omicron", region="NW-US")
        pilot = create_crew_member(base["id"], "Dana Duty", "PILOT")
        shift1 = create_crew_shift(pilot["id"], "2026-08-01T00:00:00Z", "2026-08-01T10:00:00Z")
        set_clock("2026-08-01T10:00:00Z")
        close_shift(shift1["id"])
        return pilot

    def test_projection_841_rejected(self):
        """PRD §3.1: "A projection of 840 minutes (fourteen hours) or less
        passes; 841 or more is rejected with `ERR_DUTY_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/duty_minutes_exactly_840_allowed
        """
        pilot = self._setup_member_with_600_min_shift()
        # Candidate 20:00 -> 00:01 (241 min): rolling window [00:01, 00:01+24h] still
        # counts all 600 minutes of the closed shift; 600 + 241 = 841 > 840.
        resp = api_client.create_crew_shift(
            {
                "crew_member_id": pilot["id"],
                "planned_start_iso": "2026-08-01T20:00:00Z",
                "planned_end_iso": "2026-08-02T00:01:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_DUTY_LIMIT_EXCEEDED)

    def test_projection_exactly_840_accepted(self):
        """PRD §3.1: "A projection of 840 minutes (fourteen hours) or less
        passes; 841 or more is rejected with `ERR_DUTY_LIMIT_EXCEEDED`."
        PRD §3.1: "A gap of exactly 600 minutes passes; anything less is
        rejected with `ERR_INSUFFICIENT_REST`."

        Design: Difficulty/boundary_precision_check/duty_minutes_exactly_840_allowed
        """
        pilot = self._setup_member_with_600_min_shift()
        # Candidate 20:00 -> 00:00 (240 min): 600 + 240 = 840 exactly (<= inclusive).
        # Rest gap 20:00 - 10:00 = 600 minutes exactly (>= inclusive).
        shift2 = create_crew_shift(pilot["id"], "2026-08-01T20:00:00Z", "2026-08-02T00:00:00Z")
        assert shift2["planned_minutes"] == 240, (
            f"Expected 240 planned minutes, got {shift2['planned_minutes']}"
        )
        assert shift2["status"] == "OPEN"


class TestMembershipEffectiveDateEquality:
    def test_effective_from_equal_to_completion_date_is_member_protected(self):
        """PRD §3.2: "the subscription is born `ACTIVE`, and it covers
        transports completed on or after `effective_from`."
        PRD §3.8: "if a membership subscription exists for the mission's patient
        with status `ACTIVE` and an `effective_from` on or before the date of
        the mission's `completed_at`, the invoice is `MEMBER_PROTECTED` and
        `membership_id` is bound to that subscription; otherwise it is
        `NON_MEMBER`."

        Design: Difficulty/boundary_precision_check/membership_effective_date_equality
        """
        ctx, invoice, _, membership = setup_member_protected_submitted_invoice(
            membership_effective_from="2026-08-03",
            planned_launch_iso="2026-08-03T06:00:00Z",
            completion_clock="2026-08-03T07:30:00Z",
        )
        # effective_from 2026-08-03 <= completion date 2026-08-03, equality inclusive.
        assert invoice["member_adjustment_status"] == "MEMBER_PROTECTED", (
            f"Equality is inclusive: expected MEMBER_PROTECTED, got "
            f"{invoice['member_adjustment_status']}"
        )
        assert invoice["membership_id"] == membership["id"]
        # FIXED_WING BLS, actual 0.5 mi: 950,000 + round(0.5*4500)=2,250
        # + round(2,250*0.07)=158 = 952,408.
        # (this ctx used the default ROTOR_WING; see the FIXED_WING variant below)

    def test_fixed_wing_member_finalize_total_and_binding(self):
        """PRD §3.8: "the `base_line_cents` liftoff fee is 1,800,000 cents (an
        $18,000.00 base) for a `ROTOR_WING` tail and 950,000 cents ($9,500.00)
        for a `FIXED_WING` tail, keyed on the class of the assigned aircraft."
        PRD §3.8: "the invoice is `MEMBER_PROTECTED` and `membership_id` is
        bound to that subscription; otherwise it is `NON_MEMBER`."

        Design: Difficulty/boundary_precision_check/membership_effective_date_equality
        """
        ctx, invoice, _, membership = setup_member_protected_submitted_invoice(
            membership_effective_from="2026-08-03",
            aircraft_class="FIXED_WING",
            planned_launch_iso="2026-08-03T06:00:00Z",
            completion_clock="2026-08-03T07:30:00Z",
        )
        assert invoice["final_total_cents"] == 952408, (
            f"Expected FIXED_WING BLS final 952408, got {invoice['final_total_cents']}"
        )
        assert invoice["member_adjustment_status"] == "MEMBER_PROTECTED"
        assert invoice["membership_id"] == membership["id"]
