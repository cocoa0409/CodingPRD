"""Compliance violations: penalty scoring with tier/repeat interaction,
suspension cascades, appeal/reverse conservation, and adjudication RBAC
(PRD §3.9, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    adjudicate,
    advance_clock,
    api_client,
    cite_violation,
    create_active_vessel,
    create_opening,
    create_permit,
    get_assignment,
    get_permit_status,
    get_trip,
    get_trip_assignment,
    get_vessel,
    get_violation,
    make_captain_headers,
    make_observer_headers,
    make_vessel_owner_headers,
    plan_trip,
    setup_vessel_ready,
    validate_error,
    validate_success,
)

REG = TEST_USERS["regulator_headers"]


def _adjudicate_three_over_quota(vessel_id):
    """Cite and adjudicate three OVER_QUOTA violations; returns severities."""
    violations = [cite_violation(vessel_id, violation_type="OVER_QUOTA",
                                 details=f"d{i}") for i in (1, 2, 3)]
    return [adjudicate(v["id"])["severity_points"] for v in violations]


class TestPenaltyScoring:
    def test_penalty_severity_sequence_tier_repeat(self):
        """PRD §3.9: "The penalty starts from a base by type: 20 points for
        `OVER_QUOTA`, 25 for `OUT_OF_SEASON`, 15 for `OBSERVER_BREACH`, 10 for
        `VMS_GAP`, 5 for `GEAR_MISMATCH`, and 10 for `MANUAL_CITATION`."
        PRD §3.9: "The base is scaled by a tier multiplier read from the vessel's
        `compliance_points` before any deduction: 80 or more points yields a
        multiplier of 1.0; 50 through 79 yields 1.5; below 50 yields 2.0."
        PRD §3.9: "A repeat factor of 1.5 applies when any other violation of the
        same vessel, same `violation_type`, and same `season_year` already stands
        in `ADJUDICATED` or `UPHELD`; otherwise the factor is 1.0."
        PRD §3.9: "If the deduction leaves the vessel below 50 points, the vessel
        moves to `SUSPENDED` with the full cascade of §3.1; a landing on exactly
        50 does not suspend."

        Design: Difficulty/combinatorial_formula/violation_penalty_tier_and_repeat_interaction
        """
        vessel = create_active_vessel()
        n1 = cite_violation(vessel["id"], violation_type="OVER_QUOTA", details="first")
        n2 = cite_violation(vessel["id"], violation_type="OVER_QUOTA", details="second")
        n3 = cite_violation(vessel["id"], violation_type="VMS_GAP", details="third")
        sev1 = adjudicate(n1["id"])["severity_points"]
        assert sev1 == 20, f"20 x 1.0 tier (100 pts) x 1.0 repeat, got {sev1}"
        sev2 = adjudicate(n2["id"])["severity_points"]
        assert sev2 == 30, f"20 x 1.0 tier (80 pts) x 1.5 repeat, got {sev2}"
        sev3 = adjudicate(n3["id"])["severity_points"]
        assert sev3 == 15, f"10 x 1.5 tier (50 pts) x 1.0 repeat, got {sev3}"
        vessel_now = get_vessel(vessel["id"])
        assert vessel_now["compliance_points"] == 35
        assert vessel_now["status"] == "SUSPENDED", "35 < 50 suspends the vessel"

    def test_penalty_base_points_and_tier_rounding(self):
        """PRD §3.9: "The penalty starts from a base by type: 20 points for
        `OVER_QUOTA`, 25 for `OUT_OF_SEASON`, 15 for `OBSERVER_BREACH`, 10 for
        `VMS_GAP`, 5 for `GEAR_MISMATCH`, and 10 for `MANUAL_CITATION`."
        PRD §3.9: "The three factors are multiplied and the product rounded
        half-up once, at the end, to whole points — that figure is stored in
        `severity_points` and deducted from the vessel's `compliance_points`."

        Design: Difficulty/combinatorial_formula/violation_penalty_tier_and_repeat_interaction
        """
        vessel = create_active_vessel()
        n1 = cite_violation(vessel["id"], violation_type="OUT_OF_SEASON",
                            details="offseason")
        n2 = cite_violation(vessel["id"], violation_type="GEAR_MISMATCH",
                            details="gear")
        sev1 = adjudicate(n1["id"])["severity_points"]
        assert sev1 == 25, f"25 x 1.0 (100 pts) x 1.0, got {sev1}"
        sev2 = adjudicate(n2["id"])["severity_points"]
        # 75 points -> tier 1.5; 5 x 1.5 = 7.5 -> round half-up -> 8.
        assert sev2 == 8, f"5 x 1.5 tier (75 pts) = 7.5 -> 8, got {sev2}"
        assert get_vessel(vessel["id"])["compliance_points"] == 67


class TestSuspensionReinstatementCycle:
    def test_suspension_then_reverse_reinstate_cycle(self):
        """PRD §3.9: "a landing on exactly 50 does not suspend"; "reversal moves
        `APPEALED` → `REVERSED` and refunds the stored `severity_points` back to
        the vessel's `compliance_points`, but deliberately does not lift a
        suspension — regaining `ACTIVE` status requires the manual reinstatement
        path with its own 50-point gate". PRD §3.1: "Reinstatement restores the
        vessel's `SUSPENDED` permits to `ISSUED`, but only those whose
        `valid_to` is still ahead of the current logical clock".

        Design: Difficulty/non_linear_state_machine/vessel_suspension_reinstatement_cycle
        """
        vessel = create_active_vessel()
        permit = create_permit(vessel["id"])
        violations = [cite_violation(vessel["id"], violation_type="OVER_QUOTA",
                                     details=f"d{i}") for i in (1, 2, 3)]
        adjudicate(violations[0]["id"])
        adjudicate(violations[1]["id"])
        mid = get_vessel(vessel["id"])
        assert mid["compliance_points"] == 50
        assert mid["status"] == "ACTIVE", "exactly 50 does not suspend"
        sev3 = adjudicate(violations[2]["id"])["severity_points"]
        assert sev3 == 45, f"20 x 1.5 tier x 1.5 repeat, got {sev3}"
        assert get_vessel(vessel["id"])["status"] == "SUSPENDED"
        assert get_permit_status(vessel["id"]) == "SUSPENDED"
        validate_success(api_client.appeal_violation(
            violations[2]["id"], make_vessel_owner_headers(vessel["id"])), 200)
        reversed_violation = validate_success(
            api_client.reverse_violation(violations[2]["id"], REG), 200)
        assert reversed_violation["status"] == "REVERSED"
        after_reverse = get_vessel(vessel["id"])
        assert after_reverse["compliance_points"] == 50
        assert after_reverse["status"] == "SUSPENDED", (
            "reversal refunds points but does not lift the suspension")
        reinstated = validate_success(
            api_client.reinstate_vessel(vessel["id"], REG), 200)
        assert reinstated["status"] == "ACTIVE"
        assert get_permit_status(vessel["id"]) == "ISSUED", (
            "permit valid_to 2026-12-31 is still ahead of the 2026-08-01 clock")

    def test_exactly_50_points_does_not_suspend(self):
        """PRD §3.9: "If the deduction leaves the vessel below 50 points, the
        vessel moves to `SUSPENDED` with the full cascade of §3.1; a landing on
        exactly 50 does not suspend."

        Design: Difficulty/non_linear_state_machine/vessel_suspension_reinstatement_cycle
        """
        vessel = create_active_vessel()
        violations = [cite_violation(vessel["id"], violation_type="OVER_QUOTA",
                                     details=f"d{i}") for i in (1, 2, 3)]
        adjudicate(violations[0]["id"])   # 20 -> 80
        adjudicate(violations[1]["id"])   # 30 -> 50
        current = get_vessel(vessel["id"])
        assert current["compliance_points"] == 50
        assert current["status"] == "ACTIVE"
        assert get_violation(violations[2]["id"])["status"] == "OPEN"


class TestSuspensionCascade:
    def test_adjudication_suspension_cascade(self):
        """PRD §3.1: "when a violation adjudication pushes a vessel's
        `compliance_points` below 50, the vessel drops from `ACTIVE` to
        `SUSPENDED` automatically, and the cascade fires — every permit of the
        vessel in `ISSUED` moves to `SUSPENDED`, and every trip of the vessel in
        `PLANNED` moves to `CANCELLED`, with each cancelled trip's non-terminal
        observer assignments cancelled as well."

        Design: Difficulty/transitive_cascade/violation_adjudication_suspension_cascade
        """
        ctx = setup_vessel_ready()
        vessel_id = ctx["vessel"]["id"]
        opening = create_opening()
        trip = plan_trip(vessel_id, opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-14T06:00:00Z")  # 100h -> observer required
        assignment = get_trip_assignment(trip["id"])
        severities = _adjudicate_three_over_quota(vessel_id)
        assert severities == [20, 30, 45]
        vessel_now = get_vessel(vessel_id)
        assert vessel_now["compliance_points"] == 5
        assert vessel_now["status"] == "SUSPENDED"
        assert get_permit_status(vessel_id) == "SUSPENDED"
        assert get_trip(trip["id"])["status"] == "CANCELLED"
        assert get_assignment(assignment["id"])["status"] == "CANCELLED"

    def test_suspension_cascade_cancels_only_planned_trips(self):
        """PRD §3.1: "every trip of the vessel in `PLANNED` moves to `CANCELLED`" —
        a trip already `DEPARTED` is outside the cascade's stated scope and must
        be untouched.

        Design: Difficulty/transitive_cascade/violation_adjudication_suspension_cascade
        """
        ctx = setup_vessel_ready()
        vessel_id = ctx["vessel"]["id"]
        opening = create_opening()
        advance_clock("2026-08-10T06:00:00Z")
        trip1 = plan_trip(vessel_id, opening["id"],
                          departure="2026-08-10T06:00:00Z",
                          return_="2026-08-12T06:00:00Z")
        validate_success(api_client.depart_trip(
            trip1["id"], make_captain_headers(vessel_id)), 200)
        trip2 = plan_trip(vessel_id, opening["id"],
                          departure="2026-08-14T06:00:00Z",
                          return_="2026-08-16T06:00:00Z")
        _adjudicate_three_over_quota(vessel_id)
        assert get_vessel(vessel_id)["status"] == "SUSPENDED"
        assert get_trip(trip1["id"])["status"] == "DEPARTED", (
            "the cascade cancels PLANNED trips only")
        assert get_trip(trip2["id"])["status"] == "CANCELLED"
        assert get_permit_status(vessel_id) == "SUSPENDED"


class TestCompliancePointsConservation:
    def test_adjudicate_deducts_stored_severity(self):
        """PRD §3.9: "The three factors are multiplied and the product rounded
        half-up once, at the end, to whole points — that figure is stored in
        `severity_points` and deducted from the vessel's `compliance_points`."

        Design: Difficulty/compensating_invariant/compliance_points_conserved_across_adjudicate_reverse
        """
        vessel = create_active_vessel()
        violation = cite_violation(vessel["id"], violation_type="OVER_QUOTA",
                                   details="d1")
        adjudicated = adjudicate(violation["id"])
        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated["severity_points"] == 20
        vessel_now = get_vessel(vessel["id"])
        assert vessel_now["compliance_points"] == 80
        assert vessel_now["status"] == "ACTIVE"

    def test_reverse_refunds_stored_severity(self):
        """PRD §3.9: "reversal moves `APPEALED` → `REVERSED` and refunds the
        stored `severity_points` back to the vessel's `compliance_points`".

        Design: Difficulty/compensating_invariant/compliance_points_conserved_across_adjudicate_reverse
        """
        vessel = create_active_vessel()
        violation = cite_violation(vessel["id"], violation_type="OVER_QUOTA",
                                   details="d1")
        adjudicate(violation["id"])
        assert get_vessel(vessel["id"])["compliance_points"] == 80
        validate_success(api_client.appeal_violation(
            violation["id"], make_vessel_owner_headers(vessel["id"])), 200)
        reversed_violation = validate_success(
            api_client.reverse_violation(violation["id"], REG), 200)
        assert reversed_violation["status"] == "REVERSED"
        vessel_now = get_vessel(vessel["id"])
        assert vessel_now["compliance_points"] == 100, (
            "the refund is the stored severity, restoring 100 exactly")
        assert vessel_now["status"] == "ACTIVE"


class TestViolationStateGates:
    def test_compliance_too_low_reinstate_rejected(self):
        """PRD §3.1: "A regulator may reinstate a `SUSPENDED` vessel to `ACTIVE`,
        but only when its `compliance_points` have recovered to at least 50;
        below that threshold the attempt is rejected with
        `ERR_COMPLIANCE_TOO_LOW`".

        Design: Corner/state_machines/compliance_too_low_reinstate_rejected
        """
        vessel = create_active_vessel()
        _adjudicate_three_over_quota(vessel["id"])
        assert get_vessel(vessel["id"])["compliance_points"] == 5
        resp = api_client.reinstate_vessel(vessel["id"], REG)
        validate_error(resp, "ERR_COMPLIANCE_TOO_LOW", 409)
        vessel_now = get_vessel(vessel["id"])
        assert vessel_now["status"] == "SUSPENDED"
        assert vessel_now["compliance_points"] == 5

    def test_decommission_with_open_trip_rejected(self):
        """PRD §3.1: "a regulator may move a vessel to `DECOMMISSIONED` provided
        the vessel has no trip in `PLANNED`, `DEPARTED`, `RETURNED`, or
        `LANDING_FINALIZED`; open trips block decommissioning with
        `ERR_VESSEL_HAS_OPEN_TRIPS`."

        Design: Corner/state_machines/decommission_with_open_trip_rejected
        """
        ctx = setup_vessel_ready(with_holding=False)
        opening = create_opening()
        plan_trip(ctx["vessel"]["id"], opening["id"])
        resp = api_client.decommission_vessel(ctx["vessel"]["id"], REG)
        validate_error(resp, "ERR_VESSEL_HAS_OPEN_TRIPS", 409)
        assert get_vessel(ctx["vessel"]["id"])["status"] == "ACTIVE"

    def test_appeal_open_violation_rejected(self):
        """PRD §3.9: "The owner of the cited vessel may appeal an `ADJUDICATED`
        violation, with `X-User-ID` matching the violation's `vessel_id`
        (`ERR_NOT_RESOURCE_OWNER`), moving it to `APPEALED`; appealing from any
        other status is `ERR_VIOLATION_NOT_ADJUDICATED`."

        Design: Corner/state_machines/appeal_open_violation_rejected
        """
        ctx = setup_vessel_ready(with_holding=False)
        violation = cite_violation(ctx["vessel"]["id"],
                                   violation_type="MANUAL_CITATION",
                                   details="logbook")
        resp = api_client.appeal_violation(
            violation["id"], make_vessel_owner_headers(ctx["vessel"]["id"]))
        validate_error(resp, "ERR_VIOLATION_NOT_ADJUDICATED", 409)

    def test_reverse_unappealed_violation_rejected(self):
        """PRD §3.9: "On appeal, a regulator either reverses or upholds: reversal
        moves `APPEALED` → `REVERSED` and refunds the stored `severity_points`
        back to the vessel's `compliance_points`, but deliberately does not lift
        a suspension — regaining `ACTIVE` status requires the manual
        reinstatement path with its own 50-point gate; upholding moves
        `APPEALED` → `UPHELD` and the penalty stands. Both actions require
        `APPEALED` status, failing otherwise with `ERR_VIOLATION_NOT_APPEALED`."

        Design: Corner/state_machines/reverse_unappealed_violation_rejected
        """
        vessel = create_active_vessel()
        violation = cite_violation(vessel["id"], violation_type="MANUAL_CITATION",
                                   details="logbook")
        adjudicate(violation["id"])   # 10 points -> 90
        resp = api_client.reverse_violation(violation["id"], REG)
        validate_error(resp, "ERR_VIOLATION_NOT_APPEALED", 409)
        assert get_vessel(vessel["id"])["compliance_points"] == 90, (
            "a rejected reversal refunds nothing")

    def test_rbac_observer_cannot_adjudicate_violation(self):
        """PRD §4: POST /violations/{id}/adjudicate lists only FisheriesRegulator;
        PRD §2.1: "a role that is not listed for the endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)".

        Design: Corner/rbac/rbac_observer_cannot_adjudicate_violation
        """
        ctx = setup_vessel_ready(with_holding=False)
        violation = cite_violation(ctx["vessel"]["id"],
                                   violation_type="MANUAL_CITATION",
                                   details="logbook")
        resp = api_client.adjudicate_violation(
            violation["id"], make_observer_headers(NON_EXISTENT_UUID))
        validate_error(resp, "ERR_FORBIDDEN_ROLE", 403)
        assert get_violation(violation["id"])["status"] == "OPEN"
