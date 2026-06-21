"""Temporal overlap geometry and compensating-invariant tests (queue A: Difficulty).

Covers the half-open caregiver double-booking rule, the buffer-expanded client
conflict rule, and the conserved-ledger invariants (claim deny restoring
client responsibility; visit reset restoring the billing baseline).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_agency, create_active_caregiver, create_client,
    create_active_client, create_published_plan, create_active_match,
    schedule_visit, create_in_progress_visit,
    setup_submitted_claim, get_invoice,
    make_caregiver_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["agency_admin_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestCaregiverHalfOpenOverlap:
    """rule_id: resource_temporal_overlap / caregiver_half_open_overlap."""

    def _setup(self, api):
        set_clock("2026-06-01T07:00:00Z")
        agency = create_agency(travel_buffer_minutes=0)
        cg = create_active_caregiver(agency["id"], max_weekly_hours=50)
        cla = create_client(agency["id"], full_name="CL_A")
        plana = validate_success(api.create_care_plan(
            cla["id"], {"title": "PlanA"}, SCHEDULER), expected_status=201)
        clb = create_client(agency["id"], full_name="CL_B")
        planb = validate_success(api.create_care_plan(
            clb["id"], {"title": "PlanB"}, SCHEDULER), expected_status=201)
        schedule_visit(cg["id"], cla["id"], plana["id"],
                       "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
        return cg, clb, planb

    def test_touching_endpoint_is_accepted(self, api):
        """PRD §3.5: "the new visit's half-open interval from scheduled_start up to
        scheduled_end must not overlap the interval of any non-terminal visit ... for the
        same caregiver. Because the interval is half-open, an exact endpoint touch, where
        one visit's end equals the next visit's start, does not conflict".

        Design: Difficulty/resource_temporal_overlap/caregiver_half_open_overlap
        """
        cg, clb, planb = self._setup(api)
        # New visit starts exactly at the prior visit's end (11:00 == 11:00).
        v = validate_success(api.create_visit({
            "caregiver_id": cg["id"], "client_id": clb["id"],
            "care_plan_id": planb["id"], "billing_mode": "HOURLY",
            "scheduled_start": "2026-06-01T11:00:00Z",
            "scheduled_end": "2026-06-01T12:00:00Z",
        }, SCHEDULER), expected_status=201)
        assert v["status"] == "SCHEDULED", \
            f"touching endpoint visit should be accepted, got {v['status']}"

    def test_overlapping_interval_is_rejected(self, api):
        """PRD §3.5: "a true overlap is rejected with ERR_CAREGIVER_DOUBLE_BOOKED."

        Design: Difficulty/resource_temporal_overlap/caregiver_half_open_overlap
        """
        cg, clb, planb = self._setup(api)
        # 10:30-11:30 overlaps the existing 09:00-11:00 for the same caregiver.
        resp = api.create_visit({
            "caregiver_id": cg["id"], "client_id": clb["id"],
            "care_plan_id": planb["id"], "billing_mode": "HOURLY",
            "scheduled_start": "2026-06-01T10:30:00Z",
            "scheduled_end": "2026-06-01T11:30:00Z",
        }, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CAREGIVER_DOUBLE_BOOKED.value)


class TestClientBufferedOverlap:
    """rule_id: resource_temporal_overlap / client_buffered_overlap."""

    def _setup(self, api):
        set_clock("2026-06-01T07:00:00Z")
        agency = create_agency(travel_buffer_minutes=30)
        cg1 = create_active_caregiver(agency["id"], full_name="CG1", max_weekly_hours=50)
        cg2 = create_active_caregiver(agency["id"], full_name="CG2", max_weekly_hours=50)
        cl = create_client(agency["id"])
        plan = validate_success(api.create_care_plan(
            cl["id"], {"title": "Plan"}, SCHEDULER), expected_status=201)
        # Existing visit 09:00-10:00 for client CL by CG1.
        schedule_visit(cg1["id"], cl["id"], plan["id"],
                       "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z")
        return cg2, cl, plan

    def test_gap_beyond_buffer_is_accepted(self, api):
        """PRD §3.5: "the new visit's interval is expanded by the agency's
        travel_buffer_minutes on each side, and that buffered interval must not overlap any
        non-terminal visit for the same client; because the buffered interval is treated as
        closed, a touch that falls within the buffer does conflict, and the rejection is
        ERR_CLIENT_VISIT_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/client_buffered_overlap
        """
        cg2, cl, plan = self._setup(api)
        # 10:35 start is 35 min after the 10:00 end -> clears the 30-min buffer.
        v = validate_success(api.create_visit({
            "caregiver_id": cg2["id"], "client_id": cl["id"],
            "care_plan_id": plan["id"], "billing_mode": "HOURLY",
            "scheduled_start": "2026-06-01T10:35:00Z",
            "scheduled_end": "2026-06-01T11:00:00Z",
        }, SCHEDULER), expected_status=201)
        assert v["status"] == "SCHEDULED", \
            f"35-min gap should clear the buffer, got {v['status']}"

    def test_gap_inside_buffer_is_rejected(self, api):
        """PRD §3.5: "because the buffered interval is treated as closed, a touch that
        falls within the buffer does conflict, and the rejection is
        ERR_CLIENT_VISIT_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/client_buffered_overlap
        """
        cg2, cl, plan = self._setup(api)
        # 10:15-10:25 sits 15 min after the 10:00 end -> inside the 30-min buffer.
        resp = api.create_visit({
            "caregiver_id": cg2["id"], "client_id": cl["id"],
            "care_plan_id": plan["id"], "billing_mode": "HOURLY",
            "scheduled_start": "2026-06-01T10:15:00Z",
            "scheduled_end": "2026-06-01T10:25:00Z",
        }, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CLIENT_VISIT_CONFLICT.value)


class TestClaimDenyConservesResponsibility:
    """rule_id: compensating_invariant / claim_submit_then_deny_conserves_client_responsibility."""

    def test_deny_restores_responsibility_to_invoice_total(self, api):
        """PRD §3.11: "denial is compensating — it sets the claim's covered_amount back to
        0, restores the invoice's client_responsible_amount to the full invoice_total, and
        increments the invoice's version by one."

        Design: Difficulty/compensating_invariant/claim_submit_then_deny_conserves_client_responsibility
        """
        s = setup_submitted_claim(covered_pct=0.50, daily_benefit_max=500, covered_days=5)
        inv, claim = s["invoice"], s["claim"]
        # Sanity: submit lowered responsibility to 120.00.
        mid = get_invoice(inv["id"])
        assert mid["client_responsible_amount"] == pytest.approx(120.00, abs=0.01)
        validate_success(api.transition_claim(claim["id"], {"action": "DENY"}, ADMIN))
        after = get_invoice(inv["id"])
        assert after["invoice_total"] == pytest.approx(240.00, abs=0.01)
        assert after["client_responsible_amount"] == pytest.approx(240.00, abs=0.01), \
            f"deny should restore responsibility to invoice_total, got {after['client_responsible_amount']}"

    def test_deny_zeroes_covered_amount(self, api):
        """PRD §3.11: "denial is compensating — it sets the claim's covered_amount back to
        0, restores the invoice's client_responsible_amount to the full invoice_total".

        Design: Difficulty/compensating_invariant/claim_submit_then_deny_conserves_client_responsibility
        """
        s = setup_submitted_claim(covered_pct=0.50, daily_benefit_max=500, covered_days=5)
        claim = s["claim"]
        denied = validate_success(api.transition_claim(
            claim["id"], {"action": "DENY"}, ADMIN))
        assert denied["covered_amount"] == pytest.approx(0, abs=0.01), \
            f"deny should zero covered_amount, got {denied['covered_amount']}"


class TestVisitResetConservesBillingLedger:
    """rule_id: compensating_invariant / visit_clockin_then_reset_conserves_visit_charge_ledger."""

    def _setup_clocked_in(self, api):
        agency = create_agency()
        cg = create_active_caregiver(agency["id"])
        cl = create_active_client(agency["id"])
        plan = create_published_plan(cl["id"])
        create_active_match(cg["id"], cl["id"], is_primary=True)
        v = create_in_progress_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z", "2026-06-01T09:05:00Z")
        return v

    def test_reset_restores_zero_billing_baseline(self, api):
        """PRD §3.6: "Resetting a visit (action of RESET) is permitted from EN_ROUTE or
        IN_PROGRESS ... it returns the visit to SCHEDULED, clears clock_in_at,
        clock_out_at, and evv_source, and sets billable_minutes and visit_charge back to 0,
        providing the cyclic revert loop for mis-clocked visits."

        Design: Difficulty/compensating_invariant/visit_clockin_then_reset_conserves_visit_charge_ledger
        """
        v = self._setup_clocked_in(api)
        reset = validate_success(api.transition_visit(
            v["id"], {"action": "RESET"}, SCHEDULER))
        assert reset["status"] == "SCHEDULED"
        assert reset["billable_minutes"] == 0, \
            f"reset should zero billable_minutes, got {reset['billable_minutes']}"
        assert reset["visit_charge"] == pytest.approx(0.00, abs=0.01), \
            f"reset should zero visit_charge, got {reset['visit_charge']}"

    def test_reset_clears_clock_in_timestamp(self, api):
        """PRD §3.6: "it returns the visit to SCHEDULED, clears clock_in_at, clock_out_at,
        and evv_source, and sets billable_minutes and visit_charge back to 0".

        Design: Difficulty/compensating_invariant/visit_clockin_then_reset_conserves_visit_charge_ledger
        """
        v = self._setup_clocked_in(api)
        reset = validate_success(api.transition_visit(
            v["id"], {"action": "RESET"}, SCHEDULER))
        assert reset["clock_in_at"] is None, \
            f"reset should clear clock_in_at, got {reset['clock_in_at']}"
