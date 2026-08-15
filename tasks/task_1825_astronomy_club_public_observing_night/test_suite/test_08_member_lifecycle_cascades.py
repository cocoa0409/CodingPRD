"""Member lifecycle: suspension/reinstatement cycle and the depth-3
suspension cascade onto staffing and event coverage."""
from test_helpers import (
    TEST_USERS,
    create_certification,
    create_confirmed_event,
    create_member,
    create_member_with_paid_dues,
    create_reserved_loan,
    create_telescope,
    create_tier,
    get_success_data,
    issue_invoice,
    make_member_headers,
    pay_invoice,
    set_clock,
    setup_member_with_cert_and_scope,
    validate_success,
)

OFFICER = TEST_USERS["club_officer_headers"]
COORDINATOR = TEST_USERS["event_coordinator_headers"]


class TestSuspensionReinstatementCycle:
    def test_suspension_drops_access_level_to_zero(self, api):
        """PRD: "When the logical clock reaches `dues_paid_through` plus a
        grace period of 7 days while the member is `ACTIVE`, the member
        transitions `ACTIVE → SUSPENDED`; the boundary is inclusive, so
        exactly at `dues_paid_through` plus 7 days the member is suspended,
        and one second earlier they are still active."
        PRD: "Suspension recomputes `effective_access_level` to 0"

        Design: Difficulty/non_linear_state_machine/member_suspension_reinstatement_cycle
        """
        member, _tier, _inv, _pay = create_member_with_paid_dues(
            period_start="2025-08-10T00:00:00Z",
            period_end="2026-08-10T00:00:00Z",
            full_name="Cyclical Cy")
        # 8 days past paid-through 2026-08-10: beyond the 7-day grace.
        set_clock("2026-08-18T00:00:00Z")
        suspended = validate_success(api.get_member(member["id"], OFFICER))
        assert suspended["status"] == "SUSPENDED", (
            "Clock past dues_paid_through + 7 days suspends the member")
        assert suspended["effective_access_level"] == 0, (
            "Suspension recomputes effective_access_level to 0")

    def test_reinstatement_restores_access_level(self, api):
        """PRD: "A `ClubOfficer` may reinstate a member `SUSPENDED →
        ACTIVE`, but only while the logical clock is still earlier than the
        member's `dues_paid_through` — which in practice means a payment
        posted while the member was suspended has already pushed
        `dues_paid_through` forward past the current instant."
        PRD: "Reinstatement recomputes `effective_access_level` back to the
        tier's `observatory_access_level`."

        Design: Difficulty/non_linear_state_machine/member_suspension_reinstatement_cycle
        """
        member, tier, _inv, _pay = create_member_with_paid_dues(
            period_start="2025-08-10T00:00:00Z",
            period_end="2026-08-10T00:00:00Z",
            full_name="Cyclical Cy")
        set_clock("2026-08-18T00:00:00Z")
        suspended = validate_success(api.get_member(member["id"], OFFICER))
        assert suspended["status"] == "SUSPENDED"

        # Pay a fresh year while suspended, pushing dues_paid_through forward.
        inv2 = issue_invoice(member["id"], "2026-08-10T00:00:00Z",
                             "2027-08-10T00:00:00Z")
        pay_invoice(inv2["id"], member["id"], 120000)

        reinstated = validate_success(
            api.reinstate_member(member["id"], OFFICER))
        assert reinstated["status"] == "ACTIVE", (
            "Reinstate succeeds once dues are current")
        assert reinstated["effective_access_level"] == tier["observatory_access_level"], (
            "The cycle returns effective_access_level to the tier level")


class TestSuspensionCascadeDepth3:
    def test_suspension_cascade_depth3_full_chain(self, api):
        """PRD: "withdraws every operator assignment the member holds in
        `INVITED` or `CONFIRMED` status (each recomputing the host event's
        coverage per §3.6)"
        PRD: "Whenever a `CONFIRMED` operator assignment is withdrawn or
        marked no-show such that the recomputed `confirmed_operator_count`
        falls below `min_operators`, the host event automatically falls back
        `CONFIRMED → SCHEDULED`"

        Design: Difficulty/transitive_cascade/suspension_cascade_depth3
        """
        # Member with dues paid only through 2026-08-10.
        tier = create_tier()
        op = create_member(tier["id"], full_name="Cascade Op")
        inv = issue_invoice(op["id"], "2025-08-10T00:00:00Z",
                            "2026-08-10T00:00:00Z")
        pay_invoice(inv["id"], op["id"], inv["amount_cents"])
        scope = create_telescope(name="8in SCT", equipment_class="SCT")
        create_certification(op["id"], "SCT", "2027-08-01T00:00:00Z")

        event, assignment, _m, _s = create_confirmed_event(
            operator_member=op, operator_scope=scope,
            title="PN Cascade", window_start="2026-08-20T01:00:00Z",
            window_end="2026-08-20T05:00:00Z", moon_illumination_pct=10,
            min_operators=1, equipment_class="SCT")
        assert event["status"] == "CONFIRMED"

        # Link 1: clock past dues_paid_through + 7 days -> SUSPENDED.
        set_clock("2026-08-18T00:00:00Z")
        member_after = validate_success(api.get_member(op["id"], OFFICER))
        assert member_after["status"] == "SUSPENDED", "Link 1: suspension"

        # Link 2: the CONFIRMED assignment is withdrawn by the cascade.
        asg_after = validate_success(
            api.get_operator_assignment(assignment["id"], COORDINATOR))
        assert asg_after["status"] == "WITHDRAWN", (
            "Link 2: suspension withdraws the CONFIRMED assignment")

        # Link 3: coverage lapses below min_operators -> host falls back.
        event_after = validate_success(
            api.get_observing_event(event["id"], COORDINATOR))
        assert event_after["confirmed_operator_count"] == 0
        assert event_after["status"] == "SCHEDULED", (
            "Link 3: coverage lapse knocks the CONFIRMED event back to "
            "SCHEDULED")

    def test_suspension_cancels_reserved_loan_and_releases_telescope(self, api):
        """PRD: "Suspension recomputes `effective_access_level` to 0,
        cancels every loan reservation the member holds in `RESERVED`
        status (each releasing its telescope per the cascade of §3.3), and
        withdraws every operator assignment the member holds in `INVITED` or
        `CONFIRMED` status (each recomputing the host event's coverage per
        §3.6)."

        Design: Difficulty/transitive_cascade/suspension_cascade_depth3
        """
        # Member with dues paid only through 2026-08-10 and a live
        # RESERVED loan on a certified telescope.
        tier = create_tier()
        member = create_member(tier["id"], full_name="Loan Susp")
        inv = issue_invoice(member["id"], "2025-08-10T00:00:00Z",
                            "2026-08-10T00:00:00Z")
        pay_invoice(inv["id"], member["id"], inv["amount_cents"])
        scope = create_telescope(name="Susp Scope", equipment_class="REFRACTOR")
        create_certification(member["id"], "REFRACTOR",
                             "2027-08-01T00:00:00Z")
        loan = create_reserved_loan(member, scope, "2026-08-20T00:00:00Z",
                                    "2026-08-22T00:00:00Z")
        assert loan["status"] == "RESERVED"

        set_clock("2026-08-18T00:00:00Z")
        member_after = validate_success(api.get_member(member["id"], OFFICER))
        assert member_after["status"] == "SUSPENDED"

        loan_after = validate_success(
            api.get_loan_reservation(loan["id"], OFFICER))
        assert loan_after["status"] == "CANCELLED", (
            "Suspension cancels the member's RESERVED loans")
        scope_after = validate_success(api.get_telescope(scope["id"], OFFICER))
        assert scope_after["status"] == "AVAILABLE", (
            "The cancellation cascade releases the telescope to AVAILABLE")
