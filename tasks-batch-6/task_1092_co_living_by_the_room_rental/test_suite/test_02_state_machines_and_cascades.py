"""Difficulty queue A — parallel state axes and transitive cascade chains.

Covers the independent tenancy/billing axes, the UPHELD<->DISPUTED review cycle,
the depth-4 strike-uphold cascade, and the depth-4 payment auto-rescind.
"""
from test_helpers import (
    validate_success,
    active_tenancy, active_tenancy_with_open_invoice, set_clock,
    file_notice, assess_fee, pay_invoice, file_incident, adjudicate, dispute,
    read_membership, read_member, read_room, read_house, read_invoice,
    manager_headers, finance_headers, compliance_headers, make_member_headers,
)


# ==========================================================================
# non_linear_state_machine / membership_tenancy_and_billing_axes_move_independently
# ==========================================================================
class TestTenancyBillingAxesIndependent:
    def _setup_overdue(self, api):
        ctx = active_tenancy_with_open_invoice(
            api, weekly=25000, monthly=100000, budget=60000,
            period_start="2026-06-01", period_end="2026-06-07")
        set_clock(api, "2026-06-06T00:00:00Z")
        assess_fee(api, ctx["invoice"]["id"])
        return ctx

    def test_fee_assessment_moves_only_billing_axis(self, api):
        """PRD §3.6: "The billing_status axis moves independently of the tenancy
        axis: a tenancy can be PAST_DUE while ACTIVE, NOTICE_GIVEN, or MOVED_OUT."

        Design: Difficulty/non_linear_state_machine/membership_tenancy_and_billing_axes_move_independently
        """
        ctx = self._setup_overdue(api)
        membership = read_membership(api, ctx["membership"]["id"])
        assert membership["tenancy_status"] == "ACTIVE"
        assert membership["billing_status"] == "PAST_DUE"
        assert membership["balance_due_cents"] == 41500

    def test_nonpayment_notice_moves_only_tenancy_axis(self, api):
        """PRD §3.8: "A NONPAYMENT notice ignores the supplied date entirely and
        instead pins scheduled_move_out_date to the clock date plus a seven-day
        non-payment window; it is only permitted while the tenancy's billing_status
        is PAST_DUE, otherwise ERR_NOT_PAST_DUE."

        Design: Difficulty/non_linear_state_machine/membership_tenancy_and_billing_axes_move_independently
        """
        ctx = self._setup_overdue(api)
        result = validate_success(api.file_notice(
            ctx["membership"]["id"], {"reason": "NONPAYMENT"}, manager_headers()))
        assert result["tenancy_status"] == "NOTICE_GIVEN"
        assert result["billing_status"] == "PAST_DUE"
        assert result["notice_reason"] == "NONPAYMENT"
        assert result["scheduled_move_out_date"] == "2026-06-13"
        assert result["balance_due_cents"] == 41500
        room = read_room(api, ctx["room"]["id"])
        assert room["occupancy_state"] == "NOTICE_PENDING"
        assert room["available_from_date"] == "2026-06-15"


# ==========================================================================
# non_linear_state_machine / incident_upheld_disputed_upheld_review_cycle
# ==========================================================================
class TestIncidentReviewCycle:
    def _setup_reported_incident(self, api):
        ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
        set_clock(api, "2026-06-03T00:00:00Z")
        inc = file_incident(api, ctx["membership"]["id"], co="co-2",
                            rule_code="QUIET_HOURS", severity="MAJOR",
                            description="Amplified music after 23:00 in the common area",
                            occurred_at="2026-06-02T23:30:00.000Z")
        return ctx, inc

    def test_uphold_then_dispute_swings_strikes_three_to_zero(self, api):
        """PRD §3.7: "An UPHOLD moves it to UPHELD and recomputes strike_points and
        standing_band." PRD §3.7: "A dispute moves the incident UPHELD → DISPUTED,
        increments dispute_round by one, records the dispute_reason, and recomputes
        strike_points — while under re-review a DISPUTED incident contributes zero,
        so a dispute can relax the member's standing_band."

        Design: Difficulty/non_linear_state_machine/incident_upheld_disputed_upheld_review_cycle
        """
        ctx, inc = self._setup_reported_incident(api)
        member_id = ctx["member"]["id"]
        upheld = adjudicate(api, inc["id"], "UPHOLD", co="co-1",
                            adjudication_note="two corroborating reports")
        assert upheld["status"] == "UPHELD"
        m = read_member(api, member_id)
        assert m["strike_points"] == 3 and m["standing_band"] == "WATCH"
        disputed = dispute(api, inc["id"], member_id, reason="I was not in the house that night")
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_round"] == 1
        m = read_member(api, member_id)
        assert m["strike_points"] == 0 and m["standing_band"] == "GOOD"

    def test_re_uphold_restores_strikes_without_bumping_dispute_round(self, api):
        """PRD §3.7: "From DISPUTED, a ComplianceOfficer may adjudicate again —
        UPHOLD back to UPHELD or DISMISS to DISMISSED, each recomputing
        strike_points and standing_band, each still segregated from the reporter —
        so the legal cycle is UPHELD → DISPUTED → UPHELD, bounded by the two-round
        ceiling."

        Design: Difficulty/non_linear_state_machine/incident_upheld_disputed_upheld_review_cycle
        """
        ctx, inc = self._setup_reported_incident(api)
        member_id = ctx["member"]["id"]
        adjudicate(api, inc["id"], "UPHOLD", co="co-1")
        dispute(api, inc["id"], member_id, reason="I was not in the house that night")
        re_upheld = adjudicate(api, inc["id"], "UPHOLD", co="co-1",
                               adjudication_note="key-fob log places the member on site")
        assert re_upheld["status"] == "UPHELD"
        assert re_upheld["dispute_round"] == 1
        assert re_upheld["severity_points"] == 3
        assert re_upheld["adjudicated_by_user_id"] == "co-1"
        assert re_upheld["reported_by_user_id"] == "co-2"
        m = read_member(api, member_id)
        assert m["strike_points"] == 3 and m["standing_band"] == "WATCH"
        assert read_membership(api, ctx["membership"]["id"])["tenancy_status"] == "ACTIVE"


# ==========================================================================
# transitive_cascade / uphold_strike_threshold_cascades_notice_room_and_house_posture
# ==========================================================================
class TestUpholdStrikeCascade:
    def _setup_at_threshold(self, api):
        ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
        set_clock(api, "2026-06-03T00:00:00Z")
        inc1 = file_incident(api, ctx["membership"]["id"], co="co-2",
                             rule_code="QUIET_HOURS", severity="MAJOR",
                             description="Amplified music after 23:00",
                             occurred_at="2026-06-01T23:30:00.000Z")
        adjudicate(api, inc1["id"], "UPHOLD", co="co-1")
        inc2 = file_incident(api, ctx["membership"]["id"], co="co-2",
                             rule_code="GUEST_POLICY", severity="MAJOR",
                             description="Overnight guest for a fourth consecutive night",
                             occurred_at="2026-06-02T21:00:00.000Z")
        return ctx, inc2

    def test_hop1_and_hop2_strike_threshold_forces_compliance_notice(self, api):
        """PRD §3.7: "If that recomputation carries the member to six or more strike
        points — the suspension threshold — hop two fires: any of that member's
        tenancies currently ACTIVE is driven to NOTICE_GIVEN with notice_reason set
        to COMPLIANCE and scheduled_move_out_date set to the clock date plus a
        fourteen-day compliance-notice window, and its provisional_final_charge_cents
        is written per the provisional notice-block accounting of §3.8."

        Design: Difficulty/transitive_cascade/uphold_strike_threshold_cascades_notice_room_and_house_posture
        """
        ctx, inc2 = self._setup_at_threshold(api)
        result = validate_success(api.adjudicate_incident(
            inc2["id"], {"outcome": "UPHOLD", "adjudication_note": "second corroborated violation"},
            compliance_headers("co-1")))
        assert result["status"] == "UPHELD"
        m = read_member(api, ctx["member"]["id"])
        assert m["strike_points"] == 6 and m["standing_band"] == "PROBATION"
        membership = read_membership(api, ctx["membership"]["id"])
        assert membership["tenancy_status"] == "NOTICE_GIVEN"
        assert membership["notice_reason"] == "COMPLIANCE"
        assert membership["scheduled_move_out_date"] == "2026-06-17"
        assert membership["provisional_final_charge_cents"] == 39000
        assert membership["billing_status"] == "CURRENT"

    def test_hop3_and_hop4_room_and_house_posture_cascade(self, api):
        """PRD §3.7: "Hop three drives that tenancy's room OCCUPIED → NOTICE_PENDING,
        setting the room's available_from_date to the scheduled_move_out_date plus
        the two-day turnover buffer. Hop four recomputes the house's room-state
        counts and then its compliance_posture."

        Design: Difficulty/transitive_cascade/uphold_strike_threshold_cascades_notice_room_and_house_posture
        """
        ctx, inc2 = self._setup_at_threshold(api)
        adjudicate(api, inc2["id"], "UPHOLD", co="co-1")
        room = read_room(api, ctx["room"]["id"])
        assert room["occupancy_state"] == "NOTICE_PENDING"
        assert room["available_from_date"] == "2026-06-19"
        house = read_house(api, ctx["house"]["id"])
        assert house["notice_pending_room_count"] == 1
        assert house["occupied_room_count"] == 0
        assert house["compliance_posture"] == "RESTRICTED"


# ==========================================================================
# transitive_cascade / full_payment_clears_past_due_and_auto_rescinds_nonpayment_notice
# ==========================================================================
class TestFullPaymentAutoRescind:
    def _setup_nonpayment_notice(self, api):
        ctx = active_tenancy_with_open_invoice(
            api, weekly=25000, monthly=100000, budget=60000,
            period_start="2026-06-01", period_end="2026-06-07")
        set_clock(api, "2026-06-06T00:00:00Z")
        assess_fee(api, ctx["invoice"]["id"])
        file_notice(api, ctx["membership"]["id"], "NONPAYMENT", cm="cm-1")
        return ctx

    def test_hop1_and_hop2_payment_clears_balance_and_billing(self, api):
        """PRD §3.6: "A PAST_DUE tenancy returns to CURRENT when a payment brings
        its balance_due_cents to zero while the tenancy is still live". PRD §3.6:
        "From PAST_DUE, a payment equal to the remainder moves it to PAID."

        Design: Difficulty/transitive_cascade/full_payment_clears_past_due_and_auto_rescinds_nonpayment_notice
        """
        ctx = self._setup_nonpayment_notice(api)
        payment = pay_invoice(api, ctx["invoice"]["id"], 41500, "ACH",
                              member_id=ctx["member"]["id"])
        assert payment["amount_cents"] == 41500
        assert payment["invoice_id"] == ctx["invoice"]["id"]
        inv = read_invoice(api, ctx["invoice"]["id"])
        assert inv["status"] == "PAID" and inv["amount_paid_cents"] == 41500
        membership = read_membership(api, ctx["membership"]["id"])
        assert membership["balance_due_cents"] == 0
        assert membership["billing_status"] == "CURRENT"

    def test_hop3_and_hop4_notice_auto_rescinds_and_house_reopens(self, api):
        """PRD §3.8: "when a payment brings a NOTICE_GIVEN, NONPAYMENT tenancy's
        billing_status back to CURRENT, the notice is undone — notice_reason and
        scheduled_move_out_date clear to null, provisional_final_charge_cents clears
        to null, the tenancy returns NOTICE_GIVEN → ACTIVE, the room returns
        NOTICE_PENDING → OCCUPIED with its available_from_date cleared, and the
        house counts and posture recompute."

        Design: Difficulty/transitive_cascade/full_payment_clears_past_due_and_auto_rescinds_nonpayment_notice
        """
        ctx = self._setup_nonpayment_notice(api)
        pay_invoice(api, ctx["invoice"]["id"], 41500, "ACH", member_id=ctx["member"]["id"])
        membership = read_membership(api, ctx["membership"]["id"])
        assert membership["tenancy_status"] == "ACTIVE"
        assert membership["notice_reason"] is None
        assert membership["scheduled_move_out_date"] is None
        assert membership["provisional_final_charge_cents"] is None
        room = read_room(api, ctx["room"]["id"])
        assert room["occupancy_state"] == "OCCUPIED"
        assert room["available_from_date"] is None
        house = read_house(api, ctx["house"]["id"])
        assert house["occupied_room_count"] == 1
        assert house["notice_pending_room_count"] == 0
        assert house["compliance_posture"] == "OPEN"
