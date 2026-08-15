"""Suspension cascade, reinstatement cascade, and termination cascade
(PRD §3.2, §3.6)."""
from test_helpers import (
    brief_event,
    complete_event,
    create_adult_waiver,
    create_agreement,
    create_depot,
    create_event,
    create_group,
    estimated_report_payload,
    get_agreement,
    get_depot,
    get_event,
    get_supply,
    issue_supplies,
    make_coordinator_headers,
    make_group_leader_headers,
    set_clock,
    setup_active_agreement,
    setup_completed_event,
    validate_success,
)

COORD = make_coordinator_headers()


class TestSuspensionCascade:
    def test_suspension_cascade_event_cancel_supply_restock(self, api):
        """PRD §3.2: "Either path runs the same three-link cascade: every child
        cleanup event in `SCHEDULED` or `POSTPONED` moves to `CANCELLED` —
        events already in `BRIEFING_DONE` are deliberately not touched — each
        cancelled event's supply distribution in `ISSUED` or
        `PARTIALLY_RETURNED` moves to `RECONCILED` with all outstanding
        returnables treated as returned and no loss recorded, and the issuing
        depot's `vests_on_hand` and `grabbers_on_hand` are restocked by the
        returned counts with the depot's `updated_at` refreshed."

        Design: Difficulty/transitive_cascade/suspension_cascade_event_cancel_supply_restock
        """
        depot = create_depot(bags=500, vests=100, grabbers=50)
        group, segment, agreement = setup_active_agreement()
        waiver = create_adult_waiver(agreement["id"], group["id"])

        # ea: SCHEDULED, supplies issued (V=7 -> vests 7, grabbers 4, bags 35)
        ea = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-10", expected_volunteers=7)
        da = issue_supplies(ea["id"], group["id"], depot["id"])
        # eb: SCHEDULED, supplies issued (V=3 -> vests 3, grabbers 2, bags 15)
        eb = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-12", expected_volunteers=3)
        db = issue_supplies(eb["id"], group["id"], depot["id"])
        # ec: BRIEFING_DONE, supplies issued (V=5 -> vests 5, grabbers 3, bags 25)
        ec = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-14", expected_volunteers=5)
        brief_event(ec["id"], group["id"], [waiver["id"]])
        dc = issue_supplies(ec["id"], group["id"], depot["id"])

        suspended = validate_success(
            api.suspend_agreement(agreement["id"], {"reason": "safety audit"}, COORD),
            200)
        assert suspended["status"] == "SUSPENDED"

        assert get_event(ea["id"])["status"] == "CANCELLED"
        assert get_event(eb["id"])["status"] == "CANCELLED"
        assert get_event(ec["id"])["status"] == "BRIEFING_DONE"

        da_after = get_supply(da["id"])
        assert da_after["status"] == "RECONCILED"
        assert da_after["vests_returned"] == 7
        assert da_after["grabbers_returned"] == 4
        assert da_after["lost_vests"] == 0

        db_after = get_supply(db["id"])
        assert db_after["status"] == "RECONCILED"
        assert db_after["vests_returned"] == 3
        assert db_after["grabbers_returned"] == 2

        dc_after = get_supply(dc["id"])
        assert dc_after["status"] == "ISSUED"

        dep = get_depot(depot["id"])
        assert dep["grabbers_on_hand"] == 47
        assert dep["vests_on_hand"] == 95
        assert dep["bags_on_hand"] == 425
        assert dep["lost_vests_total"] == 0

    def test_suspension_leaves_briefing_done_event_untouched(self, api):
        """PRD §3.2: "every child cleanup event in `SCHEDULED` or `POSTPONED`
        moves to `CANCELLED` — events already in `BRIEFING_DONE` are
        deliberately not touched"

        Design: Difficulty/transitive_cascade/suspension_cascade_event_cancel_supply_restock
        """
        group, segment, agreement = setup_active_agreement()
        waiver = create_adult_waiver(agreement["id"], group["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        brief_event(event["id"], group["id"], [waiver["id"]])
        validate_success(
            api.suspend_agreement(agreement["id"], {"reason": "audit"}, COORD), 200)
        assert get_event(event["id"])["status"] == "BRIEFING_DONE"


class TestSuspensionReinstatementCycle:
    def test_agreement_suspension_reinstatement_cycle(self, api):
        """PRD §3.2: "The second path is automatic: when a clock sweep
        recomputes an agreement's standing and finds it `NON_COMPLIANT` — at
        least 180 days old with fewer than three completed cleanups in the
        rolling window — the sweep suspends the agreement itself and records
        `suspension_reason` as `COMPLIANCE_DEFICIENCY`."
        PRD §3.6: "if the agreement was `SUSPENDED` and the recomputed standing
        is `COMPLIANT` — three or more completions now inside the window — the
        agreement lifts itself back to `ACTIVE` with `suspension_reason`
        cleared, an automatic reinstatement that increments the agreement's
        `version` just as a coordinator action would."

        Design: Difficulty/non_linear_state_machine/agreement_suspension_reinstatement_cycle
        """
        group, segment, agreement = setup_active_agreement(
            route_name="Hill Rd", mile_marker_start=3.0, mile_marker_end=4.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        waiver = create_adult_waiver(agreement["id"], group["id"])
        e1 = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-10", expected_volunteers=3)
        brief_event(e1["id"], group["id"], [waiver["id"]])
        e2 = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-15", expected_volunteers=3)
        brief_event(e2["id"], group["id"], [waiver["id"]])
        e3 = create_event(agreement["id"], group["id"],
                          scheduled_date="2027-02-10", expected_volunteers=3)
        brief_event(e3["id"], group["id"], [waiver["id"]])

        set_clock("2026-09-10T10:00:00Z")
        complete_event(e1["id"], group["id"])
        set_clock("2026-09-15T10:00:00Z")
        complete_event(e2["id"], group["id"])
        # Sweep fires at 2027-02-10: age 193 days >= 180, rolling count 2 < 3.
        set_clock("2027-02-10T09:00:00Z")
        mid = get_agreement(agreement["id"])
        assert mid["status"] == "SUSPENDED"
        assert mid["standing"] == "NON_COMPLIANT"
        assert mid["suspension_reason"] == "COMPLIANCE_DEFICIENCY"

        # The BRIEFING_DONE event survives; its completion reinstates.
        report = complete_event(
            e3["id"], group["id"],
            estimated_report_payload(bag_count=4),
        )
        assert report["official_weight_lbs"] == 51.0
        fin = get_agreement(agreement["id"])
        assert fin["status"] == "ACTIVE"
        assert fin["standing"] == "COMPLIANT"
        assert fin["cleanups_completed_in_window"] == 3

    def test_system_suspension_records_compliance_deficiency_reason(self, api):
        """PRD §3.2: "the sweep suspends the agreement itself and records
        `suspension_reason` as `COMPLIANCE_DEFICIENCY`."

        Design: Difficulty/non_linear_state_machine/agreement_suspension_reinstatement_cycle
        """
        group, segment, agreement = setup_active_agreement(
            route_name="Hill Rd", mile_marker_start=3.0, mile_marker_end=4.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        # No cleanups at all; advance past the 180-day grace window.
        set_clock("2027-02-01T09:00:00Z")
        ag = get_agreement(agreement["id"])
        assert ag["status"] == "SUSPENDED"
        assert ag["standing"] == "NON_COMPLIANT"
        assert ag["suspension_reason"] == "COMPLIANCE_DEFICIENCY"


class TestDebrisReportReinstatementCascade:
    def test_debris_report_reinstatement_cascade(self, api):
        """PRD §3.6: "Filing the report fires the completion cascade. The event
        moves to `COMPLETED` and its `completed_weight_lbs` is set to the
        report's `official_weight_lbs` ... The parent agreement's
        `cleanups_completed_in_window` and `standing` are then recomputed under
        the rolling measure of §2.6. And if the agreement was `SUSPENDED` and
        the recomputed standing is `COMPLIANT` — three or more completions now
        inside the window — the agreement lifts itself back to `ACTIVE` with
        `suspension_reason` cleared"

        Design: Difficulty/transitive_cascade/debris_report_reinstatement_cascade
        """
        group, segment, agreement = setup_active_agreement(
            route_name="Hill Rd", mile_marker_start=3.0, mile_marker_end=4.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        waiver = create_adult_waiver(agreement["id"], group["id"])
        events = []
        for day in ("2026-09-10", "2026-09-15", "2026-09-20", "2026-09-25"):
            ev = create_event(agreement["id"], group["id"],
                              scheduled_date=day, expected_volunteers=3)
            brief_event(ev["id"], group["id"], [waiver["id"]])
            events.append(ev)

        set_clock("2026-09-10T10:00:00Z")
        complete_event(events[0]["id"], group["id"])
        set_clock("2026-09-15T10:00:00Z")
        complete_event(events[1]["id"], group["id"])
        set_clock("2026-09-20T10:00:00Z")
        complete_event(events[2]["id"], group["id"])

        # Coordinator suspends; e4 is BRIEFING_DONE and survives.
        validate_success(
            api.suspend_agreement(agreement["id"], {"reason": "manual review"}, COORD),
            200)
        assert get_agreement(agreement["id"])["status"] == "SUSPENDED"

        set_clock("2026-09-25T10:00:00Z")
        report = complete_event(events[3]["id"], group["id"])
        assert report["official_weight_lbs"] == 25.5

        ev_after = get_event(events[3]["id"])
        assert ev_after["status"] == "COMPLETED"
        assert ev_after["completed_weight_lbs"] == 25.5

        ag_after = get_agreement(agreement["id"])
        assert ag_after["cleanups_completed_in_window"] == 4
        assert ag_after["status"] == "ACTIVE"
        assert ag_after["standing"] == "COMPLIANT"

    def test_completion_sets_denormalized_event_weight(self, api):
        """PRD §3.6: "The event moves to `COMPLETED` and its
        `completed_weight_lbs` is set to the report's `official_weight_lbs`;
        the two are reconciled against each other on every read of the event."

        Design: Difficulty/transitive_cascade/debris_report_reinstatement_cascade
        """
        group, segment, agreement, waiver, event, report = setup_completed_event(
            scheduled_date="2026-09-10", clock_iso="2026-09-10T10:00:00Z",
        )
        assert event["status"] == "COMPLETED"
        assert event["completed_weight_lbs"] == report["official_weight_lbs"] == 25.5


class TestTerminateCascade:
    def test_terminate_cascade_removes_sign_and_frees_segment(self, api):
        """PRD §3.2: "every non-terminal child event — `SCHEDULED`,
        `BRIEFING_DONE`, and `POSTPONED` alike — moves to `CANCELLED`, each
        such event's distribution in `ISSUED` or `PARTIALLY_RETURNED` is
        reconciled with outstanding returnables restocked to the depot and no
        loss recorded, any `INSTALLED` recognition sign under the agreement
        moves to `REMOVED`, and the segment returns to `AVAILABLE`."

        Design: Corner/state_machines/terminate_cascade_removes_sign_and_frees_segment
        """
        group, segment, agreement, waiver, event, report = setup_completed_event(
            scheduled_date="2026-09-10", clock_iso="2026-09-10T10:00:00Z",
        )
        gl = make_group_leader_headers(group["id"])
        sign = validate_success(
            api.request_sign(agreement["id"],
                             {"sign_text": "Riverkeepers of Maple County"}, gl),
            201)
        validate_success(api.install_sign(sign["id"], COORD), 200)

        terminated = validate_success(
            api.terminate_agreement(
                agreement["id"], {"reason": "group dissolved"}, COORD), 200)
        assert terminated["status"] == "TERMINATED"

        signs = validate_success(api.list_agreement_signs(agreement["id"], COORD), 200)
        assert signs[0]["status"] == "REMOVED"

        seg = validate_success(api.get_segment(segment["id"], COORD), 200)
        assert seg["status"] == "AVAILABLE"

    def test_terminate_frees_segment_for_new_adoption(self, api):
        """PRD §2.8: "termination, expiry, or renewal denial moves it back from
        `ADOPTED` to `AVAILABLE`."

        Design: Corner/state_machines/terminate_cascade_removes_sign_and_frees_segment
        """
        group, segment, agreement = setup_active_agreement()
        validate_success(api.terminate_agreement(agreement["id"], {}, COORD), 200)
        seg = validate_success(api.get_segment(segment["id"], COORD), 200)
        assert seg["status"] == "AVAILABLE"
        # A fresh application against the freed segment now succeeds.
        g2 = create_group(name="Second Wave", contact_email="second@wave.org")
        ag2 = create_agreement(g2, seg, contact_email="second@wave.org")
        assert ag2["status"] == "PENDING_REVIEW"
