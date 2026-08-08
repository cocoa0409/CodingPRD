"""Difficulty queue A — numeric-threshold boundaries and cross-entity gates.

Covers the inclusive income boundary that splits APPROVED from CONDITIONAL, the
empty-cycle payout that settles to zero, the frozen-house move-in block, and the
reserved-room decision block.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    base_portfolio, new_room, new_member, new_application, screen, decide,
    new_membership, do_move_in, set_clock, open_ticket, new_payout, project,
    active_tenancy_with_open_invoice, pay_invoice,
    read_house, read_room, read_application, read_membership, read_ticket, read_invoice,
    manager_headers, compliance_headers, finance_headers,
)


# ==========================================================================
# boundary_precision_check / income_multiple_inclusive_boundary_splits_approved_from_conditional
# ==========================================================================
class TestIncomeMultipleInclusiveBoundary:
    def _setup_two_screened(self, api):
        base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
        host_id, house_id = base["host"]["id"], base["house"]["id"]
        room = new_room(api, house_id, host_id, "101",
                        weekly_rate_cents=25000, monthly_rate_cents=100000)
        m_at = new_member(api, full_name="Ada Reyes", email="ada@resident.example",
                          declared_monthly_income_cents=324999)
        m_below = new_member(api, full_name="Bea Novak", email="bea@resident.example",
                             declared_monthly_income_cents=324998)
        app_at = new_application(api, m_at["id"], room["id"],
                                 requested_move_in_date="2026-06-05", billing_cycle="WEEKLY")
        app_below = new_application(api, m_below["id"], room["id"],
                                    requested_move_in_date="2026-06-05", billing_cycle="WEEKLY")
        screen(api, app_at["id"], verified_monthly_income_cents=324999, report_reference="SCR-AT")
        screen(api, app_below["id"], verified_monthly_income_cents=324998, report_reference="SCR-BELOW")
        return app_at, app_below

    def test_income_at_bar_approves_with_single_deposit(self, api):
        """PRD §3.3: "The application lands in APPROVED when the latest
        background_result is CLEAR and the qualifying income is at least the
        required_income_cents bar (equality qualifies — the comparison is
        inclusive)." PRD §3.3: "An APPROVED decision sets required_deposit_cents to
        the weekly rate multiplied by a deposit multiple of one, rounded half up."

        Design: Difficulty/boundary_precision_check/income_multiple_inclusive_boundary_splits_approved_from_conditional
        """
        app_at, app_below = self._setup_two_screened(api)
        result = decide(api, app_at["id"], decision="APPROVE")
        assert result["monthly_equivalent_cents"] == 108333
        assert result["required_income_cents"] == 324999
        assert result["status"] == "APPROVED"
        assert result["required_deposit_cents"] == 25000

    def test_income_one_cent_below_bar_falls_to_conditional_with_double_deposit(self, api):
        """PRD §3.3: "The application lands in CONDITIONAL when the latest
        background_result is FLAGGED, or when the qualifying income falls below the
        required_income_cents bar while no cosigner income has yet been recorded."
        PRD §3.3: "A CONDITIONAL decision sets it to the weekly rate multiplied by a
        conditional deposit multiple of two — a doubled deposit — rounded half up."

        Design: Difficulty/boundary_precision_check/income_multiple_inclusive_boundary_splits_approved_from_conditional
        """
        app_at, app_below = self._setup_two_screened(api)
        # decide() asserts a 2xx envelope, so reaching CONDITIONAL proves no
        # ERR_INCOME_INSUFFICIENT was raised (no cosigner round consumed yet).
        result = decide(api, app_below["id"], decision="APPROVE")
        assert result["status"] == "CONDITIONAL"
        assert result["required_deposit_cents"] == 50000


# ==========================================================================
# boundary_precision_check / empty_cycle_payout_releases_zero_without_error
# ==========================================================================
class TestEmptyCyclePayoutZero:
    def _setup_empty_cycle(self, api):
        ctx = active_tenancy_with_open_invoice(
            api, weekly=25000, monthly=100000, budget=60000,
            period_start="2026-06-01", period_end="2026-06-07")
        pay_invoice(api, ctx["invoice"]["id"], 39000, "ACH", member_id=ctx["member"]["id"])
        set_clock(api, "2026-06-15T00:00:00Z")
        payout = new_payout(api, ctx["house"]["id"], "2026-07-01", "2026-07-31")
        return ctx, payout

    def test_projection_of_empty_cycle_yields_all_zero(self, api):
        """PRD §3.10: "An empty invoice set is legal and yields a gross of zero and
        a net of zero." PRD §3.10: "The net_payout_cents is the gross minus the
        platform fee minus the maintenance credit minus the reserve, floored at
        zero."

        Design: Difficulty/boundary_precision_check/empty_cycle_payout_releases_zero_without_error
        """
        ctx, payout = self._setup_empty_cycle(api)
        projected = project(api, payout["id"])
        assert projected["gross_cents"] == 0
        assert projected["platform_fee_cents"] == 0
        assert projected["maintenance_credit_cents"] == 0
        assert projected["reserve_cents"] == 0
        assert projected["net_payout_cents"] == 0

    def test_release_of_empty_cycle_reaches_released_without_error(self, api):
        """PRD §3.10: "An empty invoice set is legal and yields a gross of zero and
        a net of zero." PRD §3.10: "Release rewrites all the money fields, sets
        variant_applied to CASH_FINAL, records released_by_user_id and released_at,
        and advances the payout to RELEASED."

        Design: Difficulty/boundary_precision_check/empty_cycle_payout_releases_zero_without_error
        """
        ctx, payout = self._setup_empty_cycle(api)
        project(api, payout["id"])
        released = validate_success(api.release_payout(payout["id"], finance_headers("fa-2")))
        assert released["status"] == "RELEASED"
        assert released["variant_applied"] == "CASH_FINAL"
        assert released["gross_cents"] == 0
        assert released["net_payout_cents"] == 0
        june = read_invoice(api, ctx["invoice"]["id"])
        assert june["total_amount_cents"] == 39000 and june["amount_paid_cents"] == 39000


# ==========================================================================
# cross_entity_state_dependency / move_in_blocked_while_house_posture_is_frozen
# ==========================================================================
class TestMoveInBlockedWhileFrozen:
    def _setup_frozen_house(self, api):
        base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
        host_id, house_id = base["host"]["id"], base["house"]["id"]
        room1 = new_room(api, house_id, host_id, "101",
                         weekly_rate_cents=25000, monthly_rate_cents=100000)
        room2 = new_room(api, house_id, host_id, "102",
                         weekly_rate_cents=20000, monthly_rate_cents=80000, private_bath=False)
        ada = new_member(api, full_name="Ada Reyes", email="ada@resident.example",
                         declared_monthly_income_cents=400000)
        bea = new_member(api, full_name="Bea Novak", email="bea@resident.example",
                         declared_monthly_income_cents=400000)
        app1 = new_application(api, ada["id"], room1["id"],
                               requested_move_in_date="2026-06-01", billing_cycle="WEEKLY")
        screen(api, app1["id"], verified_monthly_income_cents=400000, report_reference="SCR-A1")
        decide(api, app1["id"], decision="APPROVE")
        mem1 = new_membership(api, app1["id"], "2026-06-01")
        do_move_in(api, mem1["id"])
        app2 = new_application(api, bea["id"], room2["id"],
                               requested_move_in_date="2026-06-03", billing_cycle="WEEKLY")
        screen(api, app2["id"], verified_monthly_income_cents=400000, report_reference="SCR-B1")
        decide(api, app2["id"], decision="APPROVE")
        mem2 = new_membership(api, app2["id"], "2026-06-03")
        ticket = open_ticket(api, house_id, area="COMMON_AREA", severity="CRITICAL",
                             description="Gas smell in the hallway")
        set_clock(api, "2026-06-03T00:00:00Z")
        return base, room2, mem2, ticket

    def test_move_in_rejected_and_house_reads_frozen(self, api):
        """PRD §3.4: "a RESTRICTED or FROZEN house blocks the move-in with
        ERR_HOUSE_POSTURE_BLOCKED." PRD §2.8: "The frozen condition holds when the
        house has at least one maintenance ticket whose severity is CRITICAL, whose
        status is either OPEN or SCHEDULED, and whose sla_deadline_at is strictly
        earlier than the current clock instant."

        Design: Difficulty/cross_entity_state_dependency/move_in_blocked_while_house_posture_is_frozen
        """
        base, room2, mem2, ticket = self._setup_frozen_house(api)
        resp = api.move_in(mem2["id"], manager_headers())
        validate_error(resp, ApiErrorId.ERR_HOUSE_POSTURE_BLOCKED.value)
        assert read_house(api, base["house"]["id"])["compliance_posture"] == "FROZEN"
        stored_ticket = read_ticket(api, ticket["id"])
        assert stored_ticket["status"] == "OPEN"
        assert stored_ticket["sla_deadline_at"] == "2026-06-02T00:00:00.000Z"

    def test_blocked_membership_and_room_stay_reserved(self, api):
        """PRD §3.4: "Moving the resident in is a CommunityManager action, legal
        only from PENDING_MOVE_IN (ERR_INVALID_MEMBERSHIP_STATE). It requires ...
        that the house compliance_posture is OPEN when freshly re-evaluated". PRD
        §3.4: "it drives the room from VACANT to RESERVED".

        Design: Difficulty/cross_entity_state_dependency/move_in_blocked_while_house_posture_is_frozen
        """
        base, room2, mem2, ticket = self._setup_frozen_house(api)
        api.move_in(mem2["id"], manager_headers())
        assert read_membership(api, mem2["id"])["tenancy_status"] == "PENDING_MOVE_IN"
        assert read_room(api, room2["id"])["occupancy_state"] == "RESERVED"
        house = read_house(api, base["house"]["id"])
        assert house["occupied_room_count"] == 1
        assert house["reserved_room_count"] == 1


# ==========================================================================
# cross_entity_state_dependency / application_decision_blocked_when_room_already_reserved
# ==========================================================================
class TestDecisionBlockedWhenRoomReserved:
    def _setup_reserved_room(self, api):
        base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
        host_id, house_id = base["host"]["id"], base["house"]["id"]
        room1 = new_room(api, house_id, host_id, "101",
                         weekly_rate_cents=25000, monthly_rate_cents=100000)
        ada = new_member(api, full_name="Ada Reyes", email="ada@resident.example",
                         declared_monthly_income_cents=400000)
        bea = new_member(api, full_name="Bea Novak", email="bea@resident.example",
                         declared_monthly_income_cents=400000)
        app1 = new_application(api, ada["id"], room1["id"],
                               requested_move_in_date="2026-06-01", billing_cycle="WEEKLY")
        screen(api, app1["id"], verified_monthly_income_cents=400000, report_reference="SCR-A1")
        decide(api, app1["id"], decision="APPROVE")
        new_membership(api, app1["id"], "2026-06-01")   # room1 -> RESERVED
        app2 = new_application(api, bea["id"], room1["id"],
                               requested_move_in_date="2026-06-08", billing_cycle="WEEKLY")
        screen(api, app2["id"], verified_monthly_income_cents=400000, report_reference="SCR-B1")
        return base, room1, app1, app2

    def test_approve_on_reserved_room_rejected(self, api):
        """PRD §3.3: "The room named by the application must also be VACANT at
        decision time — a cross-entity gate that yields ERR_ROOM_NOT_AVAILABLE when
        the room is anything else."

        Design: Difficulty/cross_entity_state_dependency/application_decision_blocked_when_room_already_reserved
        """
        base, room1, app1, app2 = self._setup_reserved_room(api)
        resp = api.decide_application(app2["id"], {"decision": "APPROVE"},
                                      compliance_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_AVAILABLE.value)
        assert read_room(api, room1["id"])["occupancy_state"] == "RESERVED"

    def test_blocked_decision_leaves_application_screened(self, api):
        """PRD §3.3: "The room named by the application must also be VACANT at
        decision time — a cross-entity gate that yields ERR_ROOM_NOT_AVAILABLE when
        the room is anything else." PRD §3.4: "It advances the application to
        CONVERTED (terminal) ... it drives the room from VACANT to RESERVED".

        Design: Difficulty/cross_entity_state_dependency/application_decision_blocked_when_room_already_reserved
        """
        base, room1, app1, app2 = self._setup_reserved_room(api)
        api.decide_application(app2["id"], {"decision": "APPROVE"}, compliance_headers("co-1"))
        assert read_application(api, app1["id"])["status"] == "CONVERTED"
        stored2 = read_application(api, app2["id"])
        assert stored2["status"] == "SCREENED"
        assert stored2["required_deposit_cents"] == 0
