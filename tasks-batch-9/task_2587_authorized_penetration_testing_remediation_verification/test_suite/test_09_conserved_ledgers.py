"""Round trips that must leave the programme's two ledgers exactly as they were.

The plan's risk-point ledger and the engagement's hour ledger are both stated as
conserved quantities: total points always equal open plus closed plus accepted
plus duplicate, and allocated hours always equal reserved plus consumed plus
available. Each is exercised here through a compensating pair of operations —
two risk acceptances and their two revocations, and two revocations that settle
hours by two different code paths — with the invariant checked at every snapshot.
"""

from test_helpers import (
    advance_clock,
    assert_asset_posture,
    assert_exact_int,
    assert_hour_ledger,
    assert_instant_equals,
    assert_risk_ledger,
    build_scenario,
    compliance_officer_headers,
    created_data,
    engagement_version,
    factories,
    report_finding,
    success_data,
)
from test_helpers.constants import T_FIELDWORK_DAY

ACCEPT_THE_MEDIUM = (
    "Debug handler disabled by compensating control; residual risk accepted by the CISO"
)
ACCEPT_THE_CRITICAL = (
    "Refund path frozen at the gateway; residual risk accepted for this quarter"
)
REVOKE_THE_CRITICAL = "CISO withdrew the acceptance after the board review"
REVOKE_THE_MEDIUM = "Compensating control removed"


def _two_findings_on_the_payments_api(client):
    """A CRITICAL 40-point finding and a MEDIUM 8-point finding on the same asset."""
    scenario = build_scenario(
        client,
        roe={"allowed_techniques": ["AUTHZ_BYPASS", "SQLI"]},
        target={"technique_allowlist": ["AUTHZ_BYPASS"]},
    )
    advance_clock(client, T_FIELDWORK_DAY)
    critical = report_finding(client, scenario)
    medium = report_finding(client, scenario, secondary=True)
    return scenario, critical, medium


def _triage(client, finding_id, action, note):
    """Risk acceptance and its revocation are ComplianceOfficer decisions."""
    return success_data(
        client.triage_finding(
            finding_id,
            factories.triage_payload(action, note=note),
            headers=compliance_officer_headers(),
        )
    )


def _plan(client, plan_id):
    return success_data(client.get_test_plan(plan_id))


def _asset(client, asset_id):
    return success_data(client.get_asset(asset_id))


class TestRiskAcceptanceRoundTripConservesRiskPoints:
    """Forty-eight points change buckets four times and never change total."""

    def test_the_baseline_ledger_holds_forty_eight_open_points(self, client):
        """Two rated findings put 40 and 8 points into the open bucket and nowhere else.

        PRD: "`severity_points` is the band's conserved ledger weight: 40 points for `CRITICAL`, 20 for `HIGH`, 8 for `MEDIUM` and 2 for `LOW`."
        PRD: "Its points are added to the plan's `total_risk_points` and to its `open_risk_points`."

        Design: Difficulty/compensating_invariant/risk_acceptance_round_trip_conserves_plan_risk_points
        """
        scenario, critical, medium = _two_findings_on_the_payments_api(client)

        assert_exact_int(critical["severity_points"], 40, "critical severity_points")
        assert_exact_int(medium["severity_points"], 8, "medium severity_points")
        assert_risk_ledger(
            _plan(client, scenario["plan_id"]),
            total=48, open_points=48, closed=0, accepted=0, duplicate=0,
        )

    def test_accepting_the_medium_finding_moves_eight_points_across(self, client):
        """The total is untouched; only which bucket holds the eight points changes.

        PRD: "The ledger subtracts the finding's points from `open_risk_points` and adds them to `accepted_risk_points`, again leaving the total untouched."
        PRD: "Two of the four actions are reserved: risk acceptance and its revocation may be performed only by a `ComplianceOfficer`, because accepting residual risk is an assurance decision rather than a programme-management one."

        Design: Difficulty/compensating_invariant/risk_acceptance_round_trip_conserves_plan_risk_points
        """
        scenario, _critical, medium = _two_findings_on_the_payments_api(client)

        accepted = _triage(client, medium["id"], "RISK_ACCEPT", ACCEPT_THE_MEDIUM)

        assert accepted["status"] == "RISK_ACCEPTED", (
            f"finding status: expected RISK_ACCEPTED, got {accepted['status']}"
        )
        assert_risk_ledger(
            _plan(client, scenario["plan_id"]), total=48, open_points=40, accepted=8
        )

    def test_accepting_the_critical_finding_clears_the_asset(self, client):
        """With no open critical finding left, the asset's posture is stamped clear.

        PRD: "The asset's `open_finding_count` is decremented and, for a `CRITICAL` finding, so is its `open_critical_finding_count`, with the same potential `ELEVATED` → `CLEARED` consequence."
        PRD: "An asset at `ELEVATED` moves to `CLEARED` when its last open critical finding leaves the open set — whether by being closed, risk-accepted or marked duplicate — that is, when the critical count reaches 0 after the decrement, and at that moment `last_cleared_at` is stamped with the current instant."

        Design: Difficulty/compensating_invariant/risk_acceptance_round_trip_conserves_plan_risk_points
        """
        scenario, critical, medium = _two_findings_on_the_payments_api(client)
        _triage(client, medium["id"], "RISK_ACCEPT", ACCEPT_THE_MEDIUM)

        _triage(client, critical["id"], "RISK_ACCEPT", ACCEPT_THE_CRITICAL)

        assert_risk_ledger(
            _plan(client, scenario["plan_id"]), total=48, open_points=0, accepted=48
        )
        assert_asset_posture(
            _asset(client, scenario["asset_id"]),
            exposure_state="CLEARED",
            open_findings=0,
            open_critical=0,
            last_cleared_at=T_FIELDWORK_DAY,
        )

    def test_revoking_the_critical_acceptance_re_elevates_the_asset(self, client):
        """Revocation is the exact inverse, and it puts the finding back at TRIAGED.

        PRD: "It moves a finding from `RISK_ACCEPTED` back to `TRIAGED`."
        PRD: "The ledger subtracts the finding's points from `accepted_risk_points` and adds them back to `open_risk_points`, once more leaving the total untouched."
        PRD: "A `CLEARED` asset returns to `ELEVATED` when a new critical finding is reported against it, and also when a previously granted risk acceptance on a critical finding is revoked, since revocation puts those points and that finding back into the open set."

        Design: Difficulty/compensating_invariant/risk_acceptance_round_trip_conserves_plan_risk_points
        """
        scenario, critical, medium = _two_findings_on_the_payments_api(client)
        _triage(client, medium["id"], "RISK_ACCEPT", ACCEPT_THE_MEDIUM)
        _triage(client, critical["id"], "RISK_ACCEPT", ACCEPT_THE_CRITICAL)

        revoked = _triage(
            client, critical["id"], "REVOKE_RISK_ACCEPTANCE", REVOKE_THE_CRITICAL
        )

        assert revoked["status"] == "TRIAGED", (
            f"finding status: expected TRIAGED, got {revoked['status']}"
        )
        assert_risk_ledger(
            _plan(client, scenario["plan_id"]), total=48, open_points=40, accepted=8
        )
        assert_asset_posture(
            _asset(client, scenario["asset_id"]), exposure_state="ELEVATED", open_critical=1
        )

    def test_the_round_trip_restores_every_bucket_and_every_counter(self, client):
        """After both revocations the plan and the asset match their opening shape.

        PRD: "That is the second half of the invariant that makes the ledger trustworthy: after every one of these five events — rating, duplicate marking, risk acceptance, revocation and closure sign-off — the plan's `total_risk_points` must still equal the sum of its open, closed, accepted and duplicate buckets."
        PRD: "The asset's `open_finding_count` is incremented and, for a `CRITICAL` finding, so is its `open_critical_finding_count` — which can drive a `CLEARED` asset straight back to `ELEVATED`."

        Design: Difficulty/compensating_invariant/risk_acceptance_round_trip_conserves_plan_risk_points
        """
        scenario, critical, medium = _two_findings_on_the_payments_api(client)
        _triage(client, medium["id"], "RISK_ACCEPT", ACCEPT_THE_MEDIUM)
        _triage(client, critical["id"], "RISK_ACCEPT", ACCEPT_THE_CRITICAL)
        _triage(client, critical["id"], "REVOKE_RISK_ACCEPTANCE", REVOKE_THE_CRITICAL)

        _triage(client, medium["id"], "REVOKE_RISK_ACCEPTANCE", REVOKE_THE_MEDIUM)

        assert_risk_ledger(
            _plan(client, scenario["plan_id"]),
            total=48, open_points=48, closed=0, accepted=0, duplicate=0,
        )
        assert_asset_posture(
            _asset(client, scenario["asset_id"]),
            exposure_state="ELEVATED",
            open_findings=2,
            open_critical=1,
        )


# The second grant sits well after the first and is never provisioned.
SECOND_INTERVAL_START = "2026-09-15T09:00:00Z"
SECOND_INTERVAL_END = "2026-09-20T09:00:00Z"


def _one_provisioned_and_one_requested_grant(client):
    """Sixty of eighty hours reserved: forty provisioned, twenty merely requested."""
    scenario = build_scenario(client, stage="provisioned")
    second = created_data(
        client.create_tester_assignment(
            factories.tester_assignment_payload(
                scenario["engagement_id"],
                scenario["tester_id"],
                engagement_version(client, scenario["engagement_id"]),
                [scenario["asset_id"]],
                assignment_role="MEMBER",
                interval_start=SECOND_INTERVAL_START,
                interval_end=SECOND_INTERVAL_END,
                requested_hours=20,
            )
        )
    )
    advance_clock(client, T_FIELDWORK_DAY)
    return scenario, second


class TestRevocationsConserveTheHourLedger:
    """Two revocation paths, one invariant, and no hour lost along the way."""

    def test_the_opening_ledger_reserves_sixty_of_eighty_hours(self, client):
        """Both live grants reserve their requested hours and nothing is consumed yet.

        PRD: "Stated as standing definitions rather than as increments: an engagement's `hours_reserved` is the sum of `requested_hours` over its assignments whose `access_state` is `REQUESTED` or `PROVISIONED`; its `hours_consumed` is the sum of `settled_hours` over its assignments whose `access_state` is `REVOKED`; and its `hours_available` is `hours_allocated` minus `hours_reserved` minus `hours_consumed`."

        Design: Difficulty/compensating_invariant/assignment_revocations_conserve_the_engagement_hour_ledger
        """
        scenario, _second = _one_provisioned_and_one_requested_grant(client)

        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(engagement, allocated=80, reserved=60, consumed=0, available=20)

    def test_revoking_the_provisioned_grant_converts_part_of_its_reservation(self, client):
        """Twenty-five hours were held, so fifteen come back rather than vanishing.

        PRD: "The baseline is the later of the assignment's `interval_start` and its `provisioned_at`; the effective end is the earlier of its `revoked_at` and its `interval_end`; the elapsed duration is the effective end minus the baseline expressed in hours, floored at 0 so a revocation that lands before the baseline yields nothing."
        PRD: "The ledger is then updated in a fixed order on the parent engagement: `hours_reserved` is reduced by the assignment's `requested_hours`, `hours_consumed` is increased by the freshly computed `settled_hours`, and `hours_available` is recomputed as `hours_allocated` minus the new `hours_reserved` minus the new `hours_consumed`."
        PRD: "Applied that way, the invariant that allocated hours always equal reserved plus consumed plus available survives every revocation."

        Design: Difficulty/compensating_invariant/assignment_revocations_conserve_the_engagement_hour_ledger
        """
        scenario, _second = _one_provisioned_and_one_requested_grant(client)

        revoked = success_data(client.set_access(scenario["assignment_id"], "REVOKE"))

        assert revoked["access_state"] == "REVOKED", (
            f"access_state: expected REVOKED, got {revoked['access_state']}"
        )
        assert_exact_int(revoked["settled_hours"], 25, "settled_hours")
        assert_instant_equals(revoked["revoked_at"], T_FIELDWORK_DAY, "revoked_at")
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(engagement, allocated=80, reserved=20, consumed=25, available=35)

    def test_revoking_the_never_provisioned_grant_returns_its_whole_reservation(self, client):
        """A grant that never gave access consumes nothing at all.

        PRD: "A revocation of an assignment that was **never provisioned** — one still at `REQUESTED` — settles `settled_hours` at 0, since no access ever existed and nothing was consumed; it stamps `revoked_at`, subtracts the assignment's `requested_hours` from the engagement's `hours_reserved`, and recomputes `hours_available`."
        PRD: "Applied that way, the invariant that allocated hours always equal reserved plus consumed plus available survives every revocation."

        Design: Difficulty/compensating_invariant/assignment_revocations_conserve_the_engagement_hour_ledger
        """
        scenario, second = _one_provisioned_and_one_requested_grant(client)
        success_data(client.set_access(scenario["assignment_id"], "REVOKE"))

        revoked = success_data(client.set_access(second["id"], "REVOKE"))

        assert revoked["access_state"] == "REVOKED", (
            f"access_state: expected REVOKED, got {revoked['access_state']}"
        )
        assert revoked["provisioned_at"] is None, (
            f"provisioned_at: expected null, got {revoked['provisioned_at']}"
        )
        assert_exact_int(revoked["settled_hours"], 0, "settled_hours")
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(engagement, allocated=80, reserved=0, consumed=25, available=55)

    def test_the_tester_returns_to_the_roster_once_no_grant_is_live(self, client):
        """The count reaches zero across both revocation paths, so availability resets.

        PRD: "The tester's `active_assignment_count` is then decremented, and when it reaches 0 the tester's `availability_state` moves `ASSIGNED` → `AVAILABLE`."
        PRD: "`REVOKED` is a terminal access state: a revoked grant is never restored, and re-admitting the tester means booking and provisioning again from scratch."

        Design: Difficulty/compensating_invariant/assignment_revocations_conserve_the_engagement_hour_ledger
        """
        scenario, second = _one_provisioned_and_one_requested_grant(client)
        success_data(client.set_access(scenario["assignment_id"], "REVOKE"))
        success_data(client.set_access(second["id"], "REVOKE"))

        tester = success_data(client.get_tester(scenario["tester_id"]))
        assert_exact_int(tester["active_assignment_count"], 0, "active_assignment_count")
        assert tester["availability_state"] == "AVAILABLE", (
            f"availability_state: expected AVAILABLE, got {tester['availability_state']}"
        )
