"""Tour/show posture derivation and compliance-hold gating (PRD §2.6, §3.4,
§3.8).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_staged_tour, create_show_with_accepted_hold, create_confirmed_show,
    approve_all_sections, confirm_show_payload, get_tour, get_show,
    open_compliance_hold, assert_compliance_hold, assert_tour, assert_show,
    ApiErrorId, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]


class TestShowConfirmDependsOnTourPosture:
    def _stage_held_show(self, api, tour_name="TXD1", market_code="SF"):
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": tour_name},
            market_overrides={"market_code": market_code},
            venue_overrides={"capacity": 1800, "available_dates": ["2026-08-05"]})
        tid = staged["tour"]["id"]
        show, hold = create_show_with_accepted_hold(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-05", on_sale_at="2026-07-01T00:00:00Z",
            avg_ticket_price_cents=9000,
            hold_overrides={"guarantee_cents": 1500000, "versus_pct": 80})
        return tid, show

    def test_confirm_blocked_when_tour_frozen(self, api):
        """PRD §3.4: "The tour's posture must be `OPEN` (`ERR_POSTURE_NOT_OPEN`):
        because even a single active standard hold restricts the tour,
        confirmation is impossible while any compliance hold is outstanding."
        PRD §2.6: "When any `ACTIVE` ComplianceHold with `severity` of
        `CRITICAL` exists on the tour, the posture is `FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/show_confirm_depends_on_tour_posture
        """
        tid, show = self._stage_held_show(api)
        hold = open_compliance_hold(tid, hold_kind="ADVANCE_OVERDUE",
                                    severity="CRITICAL", reason="manual")
        assert_compliance_hold(hold)
        assert hold["status"] == "ACTIVE"
        assert get_tour(tid)["posture"] == "FROZEN"

        tour = get_tour(tid)
        res = api.confirm_show(tid, show["id"],
                               confirm_show_payload(tour["version"]), TM)
        validate_error(res, ApiErrorId.ERR_POSTURE_NOT_OPEN.value)

    def test_confirm_blocked_when_tour_restricted(self, api):
        """PRD §2.6: "A `RESTRICTED` tour blocks show confirmation and the
        tour-wide on-sale opening, while still permitting advance-packet edits
        and hold negotiation to continue." PRD §3.4: "The tour's posture must
        be `OPEN` (`ERR_POSTURE_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/show_confirm_depends_on_tour_posture
        """
        tid, show = self._stage_held_show(api, tour_name="TXD1b",
                                          market_code="OAK")
        open_compliance_hold(tid, hold_kind="BUDGET_OVERRUN", severity="STANDARD",
                             reason="manual flag")
        assert get_tour(tid)["posture"] == "RESTRICTED"

        tour = get_tour(tid)
        res = api.confirm_show(tid, show["id"],
                               confirm_show_payload(tour["version"]), TM)
        validate_error(res, ApiErrorId.ERR_POSTURE_NOT_OPEN.value)


class TestShowParallelStatusAndPosture:
    def test_status_unchanged_and_posture_gated_by_standard_hold(self, api):
        """PRD §2.6: "a show is `GATED` whenever its tour's posture is anything
        other than `OPEN` or while any section of its advance packet is not yet
        `APPROVED`, and a `GATED` show cannot be confirmed, advanced, or
        settled." And: "When no `CRITICAL` hold is active but at least one
        `ACTIVE` hold of `severity` `STANDARD` exists, the posture is
        `RESTRICTED`."

        Design: Difficulty/non_linear_state_machine/show_parallel_status_and_posture
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "TPar"},
            market_overrides={"market_code": "ATL", "metro_name": "Atlanta",
                              "radius_miles": 40},
            venue_overrides={"venue_name": "Tabernacle", "capacity": 600,
                             "available_dates": ["2026-08-12"]})
        tid = staged["tour"]["id"]
        show, _ = create_show_with_accepted_hold(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-12", on_sale_at="2026-07-01T00:00:00Z",
            avg_ticket_price_cents=6000,
            hold_overrides={"guarantee_cents": 700000, "versus_pct": 75})
        assert show["status"] == "HOLD_PLACED"

        open_compliance_hold(tid, hold_kind="BUDGET_OVERRUN", severity="STANDARD",
                             reason="manual flag")

        show_after = get_show(tid, show["id"])
        assert_show(show_after)
        assert show_after["status"] == "HOLD_PLACED", (
            "the status dimension is unchanged by opening a compliance hold")
        assert show_after["posture"] == "GATED", (
            "the posture dimension flips to GATED while the tour is not OPEN")
        tour_after = get_tour(tid)
        assert_tour(tour_after)
        assert tour_after["posture"] == "RESTRICTED", (
            "a STANDARD hold restricts but does not freeze")

    def test_show_stays_gated_after_hold_resolved_until_packet_approved(self, api):
        """PRD §2.6: "The show's posture opens again automatically once the
        tour is `OPEN` and every packet section has reached `APPROVED`." With
        sections still PENDING, resolving the hold reopens the tour but not
        the show.

        Design: Difficulty/non_linear_state_machine/show_parallel_status_and_posture
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "TPar2"},
            market_overrides={"market_code": "NASH", "metro_name": "Nashville"},
            venue_overrides={"capacity": 600, "available_dates": ["2026-08-12"]})
        tid = staged["tour"]["id"]
        show, _ = create_show_with_accepted_hold(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-12", on_sale_at="2026-07-01T00:00:00Z",
            avg_ticket_price_cents=6000)

        chold = open_compliance_hold(tid, hold_kind="ADVANCE_OVERDUE",
                                     severity="STANDARD", reason="manual")
        assert get_show(tid, show["id"])["posture"] == "GATED"

        validate_success(api.resolve_compliance_hold(tid, chold["id"], TM), 200)
        assert get_tour(tid)["posture"] == "OPEN", (
            "no ACTIVE ComplianceHold remains, so the tour posture returns to OPEN")
        assert get_show(tid, show["id"])["posture"] == "GATED", (
            "packet sections are still PENDING, so the show remains GATED")


class TestDerivedFieldShowPostureReconciliation:
    def test_posture_reconciles_on_tour_posture_change_both_directions(self, api):
        """PRD §2.6: "a show is `GATED` whenever its tour's posture is anything
        other than `OPEN` or while any section of its advance packet is not yet
        `APPROVED`", and "The show's posture opens again automatically once the
        tour is `OPEN` and every packet section has reached `APPROVED`."

        Design: Corner/cross_cutting_complexity_layers/derived_field_show_posture_reconciliation
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            venue_overrides={"capacity": 100, "available_dates": ["2026-08-01"]})
        tid = staged["tour"]["id"]
        show, _ = create_confirmed_show(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-01", on_sale_at="2026-07-01T00:00:00Z",
            avg_ticket_price_cents=5000,
            hold_overrides={"guarantee_cents": 100000, "versus_pct": 70})
        approve_all_sections(tid, show["id"])

        # Both preconditions hold: tour OPEN, all sections APPROVED.
        assert get_show(tid, show["id"])["posture"] == "OPEN"

        # Open a CRITICAL hold: tour FROZEN, show reconciles to GATED.
        chold = open_compliance_hold(tid, hold_kind="ADVANCE_OVERDUE",
                                     severity="CRITICAL", reason="audit")
        assert get_tour(tid)["posture"] == "FROZEN"
        assert get_show(tid, show["id"])["posture"] == "GATED", (
            "derived show posture updated on the tour posture change")

        # Resolve it: tour returns OPEN and the show reopens automatically.
        validate_success(api.resolve_compliance_hold(tid, chold["id"], TM), 200)
        assert get_tour(tid)["posture"] == "OPEN"
        assert get_show(tid, show["id"])["posture"] == "OPEN"
