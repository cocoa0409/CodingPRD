"""The exact edges: a severity band that flips on 0.01 and a settlement of zero.

A tier-2 asset under a single regime carries bonuses of exactly 0.50, which puts
a partner-facing base score of 8.50 precisely on the inclusive CRITICAL floor of
9.00 and a base score of 8.49 precisely one hundredth below it. Revocation has
its own zero edge: revoking at the instant the assignment's interval opens holds
access for no time at all, so the rounding-up rule must yield 0 hours rather
than the 1 it produces a single second later.
"""

from test_helpers import (
    advance_clock,
    assert_alert_raised,
    assert_asset_posture,
    assert_exact_int,
    assert_hour_ledger,
    assert_instant_equals,
    assert_no_alert_raised,
    assert_risk_ledger,
    assert_severity,
    build_scenario,
    factories,
    report_finding,
    success_data,
)
from test_helpers.constants import INTERVAL_START, T_BEFORE_ASSIGNMENT, T_FIELDWORK_DAY

# One second past the interval's opening instant, where ceil() starts charging.
T_ONE_SECOND_INTO_THE_INTERVAL = "2026-09-07T09:00:01Z"

# 2026-09-08T10:00:00Z plus the 240-minute partner acknowledgement window.
PARTNER_ACK_DEADLINE = "2026-09-08T14:00:00Z"


def _partner_portal_fieldwork(client):
    """Fieldwork under way on a tier-2 SOC2 portal, whose bonuses total 0.50."""
    scenario = build_scenario(
        client,
        asset=factories.partner_portal_asset_payload(),
        scope_item={
            "justification": "Partner portal annual test",
            "requested_engagement_hours": 60,
        },
        roe={"allowed_techniques": ["AUTHZ_BYPASS", "SQLI"]},
        target={"technique_allowlist": ["AUTHZ_BYPASS"]},
    )
    advance_clock(client, T_FIELDWORK_DAY)
    return scenario


def _findings_on_either_side_of_the_boundary(client):
    """Report 8.50 and 8.49 partner findings, which rate 9.00 and 8.99."""
    scenario = _partner_portal_fieldwork(client)
    at_boundary = report_finding(
        client,
        scenario,
        title="Session fixation on partner SSO handoff",
        reproduction_steps="1. Capture the handoff token 2. Replay it after logout",
        business_impact_narrative=(
            "Partner sessions can be hijacked for the token lifetime"
        ),
        technical_base_score=8.5,
        exposure_class="PARTNER",
        root_cause_theme="ACCESS_CONTROL",
    )
    below_boundary = report_finding(
        client,
        scenario,
        title="Session token accepted after password change",
        reproduction_steps="1. Change the password 2. Replay the previous token",
        business_impact_narrative=(
            "Revoked credentials keep working until the token expires"
        ),
        technical_base_score=8.49,
        exposure_class="PARTNER",
        root_cause_theme="ACCESS_CONTROL",
    )
    return scenario, at_boundary, below_boundary


class TestSeverityBandFlipsAtNinePointZeroZero:
    """0.01 of base score decides the band, the points and whether an alert exists."""

    def test_a_score_of_exactly_nine_is_already_critical(self, client):
        """8.50 * 1.00 + 0.30 + 0.20 is 9.00, and the CRITICAL floor is inclusive.

        PRD: "To that product the server adds a criticality bonus taken from the asset's tier: 0.50 for tier 1, 0.30 for tier 2, 0.10 for tier 3 and nothing at all for tier 4."
        PRD: "It then adds a regulatory bonus of 0.20 for each compliance regime the asset carries, capped at 0.60 however many regimes there are — so three or more regimes all yield the same 0.60."
        PRD: "`severity_band` is `CRITICAL` when `severity_score` is at least 9.00, otherwise `HIGH` when it is at least 7.00, otherwise `MEDIUM` when it is at least 4.00, and otherwise `LOW`."
        PRD: "And `immediate_action_required` is true exactly when the band is `CRITICAL`."

        Design: Difficulty/boundary_precision_check/severity_band_flips_critical_at_exactly_nine_point_zero_zero
        """
        _scenario, at_boundary, _below = _findings_on_either_side_of_the_boundary(client)

        assert round(float(at_boundary["severity_score"]), 2) == 9.00, (
            f"severity_score: expected exactly 9.00, got {at_boundary['severity_score']}"
        )
        assert round(float(at_boundary["severity_score"]), 2) != 8.99, (
            "the boundary case must not land one hundredth low"
        )
        assert_severity(at_boundary, band="CRITICAL", points=40, immediate=True)

    def test_one_hundredth_below_the_boundary_stays_high(self, client):
        """8.49 * 1.00 + 0.30 + 0.20 is 8.99, which is short of CRITICAL by 0.01.

        PRD: "`severity_band` is `CRITICAL` when `severity_score` is at least 9.00, otherwise `HIGH` when it is at least 7.00, otherwise `MEDIUM` when it is at least 4.00, and otherwise `LOW`."
        PRD: "`severity_points` is the band's conserved ledger weight: 40 points for `CRITICAL`, 20 for `HIGH`, 8 for `MEDIUM` and 2 for `LOW`."

        Design: Difficulty/boundary_precision_check/severity_band_flips_critical_at_exactly_nine_point_zero_zero
        """
        _scenario, _at_boundary, below = _findings_on_either_side_of_the_boundary(client)

        assert round(float(below["severity_score"]), 2) == 8.99, (
            f"severity_score: expected exactly 8.99, got {below['severity_score']}"
        )
        assert round(float(below["severity_score"]), 2) != 9.00, (
            "one hundredth below the floor must not be rounded up onto it"
        )
        assert_severity(below, band="HIGH", points=20, immediate=False)

    def test_only_the_critical_side_of_the_boundary_raises_an_alert(self, client):
        """The same 0.01 decides whether an alert row exists at all.

        PRD: "Its `ack_deadline_at` is `raised_at` advanced by a window that depends on the finding's `exposure_class`: an internet-facing critical finding must be acknowledged within one hour, that is 60 minutes, while a partner-facing or internal critical finding is allowed four hours, that is 240 minutes."
        PRD: "No alert is ever created for a finding whose band is not `CRITICAL`, and every `CRITICAL` finding has exactly one."

        Design: Difficulty/boundary_precision_check/severity_band_flips_critical_at_exactly_nine_point_zero_zero
        """
        _scenario, at_boundary, below = _findings_on_either_side_of_the_boundary(client)

        alert = assert_alert_raised(
            client,
            at_boundary["id"],
            ack_deadline_at=PARTNER_ACK_DEADLINE,
            state="RAISED",
            escalation_level=1,
        )
        assert_instant_equals(alert["raised_at"], at_boundary["discovered_at"], "raised_at")
        assert_no_alert_raised(client, below["id"])

    def test_the_two_bands_contribute_forty_and_twenty_points(self, client):
        """A CRITICAL and a HIGH finding carry 60 open points between them.

        PRD: "Its points are added to the plan's `total_risk_points` and to its `open_risk_points`."
        PRD: "Its asset's `open_finding_count` is incremented, and for a `CRITICAL` finding `open_critical_finding_count` is incremented too, which may drive the asset's posture from `MONITORED` or `CLEARED` to `ELEVATED` as described in §3.1."

        Design: Difficulty/boundary_precision_check/severity_band_flips_critical_at_exactly_nine_point_zero_zero
        """
        scenario, _at_boundary, _below = _findings_on_either_side_of_the_boundary(client)

        plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_risk_ledger(plan, total=60, open_points=60, closed=0, accepted=0, duplicate=0)

        asset = success_data(client.get_asset(scenario["asset_id"]))
        assert_asset_posture(
            asset, exposure_state="ELEVATED", open_findings=2, open_critical=1
        )


def _provisioned_assignment(client):
    """A 40-hour LEAD grant provisioned an hour before its interval opens."""
    return build_scenario(client, stage="provisioned")


class TestRevocationAtTheIntervalStartSettlesNothing:
    """Zero elapsed hours must round to zero, not to the first whole hour."""

    def test_provisioning_stamps_the_instant_and_reserves_the_hours(self, client):
        """The grant opens at 08:00 with all forty hours reserved and none consumed.

        PRD: "On success the assignment moves `REQUESTED` → `PROVISIONED`, `provisioned_at` is stamped with the current instant, the tester's `active_assignment_count` is incremented, and the tester's `availability_state` moves `AVAILABLE` → `ASSIGNED` (a tester already at `ASSIGNED` stays there, since the state reflects "holds at least one live grant" rather than a count)."
        PRD: "Its `requested_hours` are added to the engagement's `hours_reserved`, `hours_available` is recomputed as the allocation minus reserved minus consumed, and the engagement's `version` advances."

        Design: Difficulty/boundary_precision_check/revocation_exactly_at_interval_start_settles_zero_hours
        """
        scenario = _provisioned_assignment(client)

        assignment = scenario["assignment"]
        assert assignment["access_state"] == "PROVISIONED", (
            f"access_state: expected PROVISIONED, got {assignment['access_state']}"
        )
        assert_instant_equals(
            assignment["provisioned_at"], T_BEFORE_ASSIGNMENT, "provisioned_at"
        )
        assert_hour_ledger(
            scenario["engagement"], allocated=80, reserved=40, consumed=0, available=40
        )

    def test_revoking_exactly_at_the_interval_start_settles_zero_hours(self, client):
        """Baseline and effective end coincide, so ceil() is handed exactly zero.

        PRD: "The baseline is the later of the assignment's `interval_start` and its `provisioned_at`; the effective end is the earlier of its `revoked_at` and its `interval_end`; the elapsed duration is the effective end minus the baseline expressed in hours, floored at 0 so a revocation that lands before the baseline yields nothing."
        PRD: "That elapsed figure is rounded **up** to the next whole hour, and `settled_hours` is the smaller of that rounded figure and the assignment's `requested_hours` — a tester can never consume more hours than were reserved for them, however long the interval ran."

        Design: Difficulty/boundary_precision_check/revocation_exactly_at_interval_start_settles_zero_hours
        """
        scenario = _provisioned_assignment(client)
        advance_clock(client, INTERVAL_START)

        revoked = success_data(client.set_access(scenario["assignment_id"], "REVOKE"))

        assert revoked["access_state"] == "REVOKED", (
            f"access_state: expected REVOKED, got {revoked['access_state']}"
        )
        assert_instant_equals(revoked["revoked_at"], INTERVAL_START, "revoked_at")
        assert_exact_int(revoked["settled_hours"], 0, "settled_hours")

    def test_the_ledger_returns_to_its_untouched_shape(self, client):
        """Nothing reserved, nothing consumed, and the whole allocation free again.

        PRD: "The ledger is then updated in a fixed order on the parent engagement: `hours_reserved` is reduced by the assignment's `requested_hours`, `hours_consumed` is increased by the freshly computed `settled_hours`, and `hours_available` is recomputed as `hours_allocated` minus the new `hours_reserved` minus the new `hours_consumed`."
        PRD: "The tester's `active_assignment_count` is then decremented, and when it reaches 0 the tester's `availability_state` moves `ASSIGNED` → `AVAILABLE`."

        Design: Difficulty/boundary_precision_check/revocation_exactly_at_interval_start_settles_zero_hours
        """
        scenario = _provisioned_assignment(client)
        advance_clock(client, INTERVAL_START)
        success_data(client.set_access(scenario["assignment_id"], "REVOKE"))

        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(engagement, allocated=80, reserved=0, consumed=0, available=80)

        tester = success_data(client.get_tester(scenario["tester_id"]))
        assert_exact_int(tester["active_assignment_count"], 0, "active_assignment_count")
        assert tester["availability_state"] == "AVAILABLE", (
            f"availability_state: expected AVAILABLE, got {tester['availability_state']}"
        )

    def test_one_second_later_the_same_revocation_settles_a_whole_hour(self, client):
        """Zero is a boundary value and not an approximation of a short interval.

        PRD: "That elapsed figure is rounded **up** to the next whole hour, and `settled_hours` is the smaller of that rounded figure and the assignment's `requested_hours` — a tester can never consume more hours than were reserved for them, however long the interval ran."
        PRD: "The ledger is then updated in a fixed order on the parent engagement: `hours_reserved` is reduced by the assignment's `requested_hours`, `hours_consumed` is increased by the freshly computed `settled_hours`, and `hours_available` is recomputed as `hours_allocated` minus the new `hours_reserved` minus the new `hours_consumed`."

        Design: Difficulty/boundary_precision_check/revocation_exactly_at_interval_start_settles_zero_hours
        """
        scenario = _provisioned_assignment(client)
        advance_clock(client, T_ONE_SECOND_INTO_THE_INTERVAL)

        revoked = success_data(client.set_access(scenario["assignment_id"], "REVOKE"))

        assert_exact_int(revoked["settled_hours"], 1, "settled_hours")
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(engagement, allocated=80, reserved=0, consumed=1, available=79)
