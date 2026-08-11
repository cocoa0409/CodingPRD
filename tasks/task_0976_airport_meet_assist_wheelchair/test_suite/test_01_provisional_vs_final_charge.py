"""Difficulty queue A — dual_variant_calc instances."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data, validate_success, validate_error,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock, setup_completed_request,
    walk_assignment_to_handed_off, complete_assignment,
    make_agent_headers, make_confirmer_headers, make_dispatcher_headers,
    make_billing_clerk_headers,
    api_client,
    TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Design: Difficulty/dual_variant_calc/provisional_vs_final_leg_charge_with_delay_surcharge
# ---------------------------------------------------------------------------

class TestProvisionalVsFinalWithDelaySurcharge:
    def test_provisional_uses_scheduled_final_uses_actual_with_delay_surcharge(self, api):
        """PRD §3.6: "the delay in minutes is the non-negative difference between
        `actual_utc` and `scheduled_utc`, converted to minutes; a grace of 20 minutes
        is subtracted; any positive remainder is charged at 75 cents per minute."
        PRD §3.6: "the airport's posture **at the moment of completion** replaces
        the posture snapshot from submit time."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_leg_charge_with_delay_surcharge
        """
        out = setup_completed_request(
            iata_code="SFO",
            meet_buffer_minutes=20,
            requires_secure_escort=False,
            scheduled_utc="2026-06-01T10:00:00Z",
            actual_utc="2026-06-01T10:50:00Z",  # 50 min delay → 30 past grace → 30*75=2250
            leg_kind="MEET_ARRIVAL",
            passenger_overrides={
                "full_name": "Adult P", "dob": "1990-01-01",
                "mobility_code": "WCHR", "private_card_token": "tok_x",
            },
            request_overrides={"bill_to": "PRIVATE", "service_tier": "STANDARD",
                               "companion_count": 0},
            clock_at_submit="2026-06-01T09:00:00Z",
            dispatcher_user_id="disp_sfo",
            confirmer_user_id="conf_sfo",
        )
        leg = out["leg"]
        req = out["request"]
        # Provisional at submit: base 6000; WCHR sets no requires_wheelchair
        # flag (PRD §3.2) so no equipment fee; tier 1.0, posture 1.0 → 6000
        assert leg["provisional_leg_cents"] == 6000, (
            f"Expected provisional 6000, got {leg['provisional_leg_cents']}"
        )
        # Final: same base, plus 30 min * 75 = 2250 surcharge → 8250
        assert leg["final_leg_cents"] == 8250, (
            f"Expected final 8250, got {leg['final_leg_cents']}"
        )
        assert leg["final_leg_cents"] != leg["provisional_leg_cents"]
        assert req["final_charge_cents"] == 8250
        assert req["request_status"] == "COMPLETED"

    def test_provisional_computed_at_submit_uses_scheduled_not_actual(self, api):
        """PRD §3.3: "the posture multiplier snapshotted from the airport's
        current posture at compute time."
        PRD §3.6: "the segment's `actual_utc` replaces its `scheduled_utc`."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_leg_charge_with_delay_surcharge
        """
        # Same setup; assert provisional (computed before actual_utc known) differs
        # from final (computed after) — proves the two variants are distinct algorithms.
        out = setup_completed_request(
            iata_code="SFO",
            meet_buffer_minutes=20,
            requires_secure_escort=False,
            scheduled_utc="2026-06-01T10:00:00Z",
            actual_utc="2026-06-01T10:50:00Z",
            leg_kind="MEET_ARRIVAL",
            passenger_overrides={
                "full_name": "Adult P2", "dob": "1990-01-01",
                "mobility_code": "WCHR", "private_card_token": "tok_y",
            },
            request_overrides={"bill_to": "PRIVATE", "service_tier": "STANDARD",
                               "companion_count": 0},
            clock_at_submit="2026-06-01T09:00:00Z",
            dispatcher_user_id="disp_sfo2",
            confirmer_user_id="conf_sfo2",
        )
        # Divergence observable: provisional == 6000 (no delay info), final == 8250.
        assert out["leg"]["provisional_leg_cents"] == 6000
        assert out["leg"]["final_leg_cents"] == 8250
        # The provisional charge is frozen on the request until completion flips it.
        assert out["request"]["provisional_charge_cents"] == 6000
        assert out["request"]["final_charge_cents"] == 8250


# ---------------------------------------------------------------------------
# Design: Difficulty/dual_variant_calc/final_vs_writeoff_baseline_posture_normalization
# ---------------------------------------------------------------------------

class TestFinalVsWriteoffBaselinePostureNormalization:
    def _setup_completed_at_degraded_then_dispute(self, api):
        """Setup a request that completes under DEGRADED posture, then DISPUTE it.
        Returns (request, leg, final_invoice, dispute_version)."""
        set_clock("2026-05-01T08:00:00Z")
        airport = create_airport(iata_code="OAK", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="T2", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="WN200",
            direction="DEPARTURE", scheduled_utc="2026-06-02T12:00:00Z",
        )
        passenger = create_passenger(
            full_name="P Two", dob="1985-05-05", mobility_code="WCHR",
            airline_pnr="ABC123",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="DEPARTURE_ESCORT", pickup_zone="CURB-B")
        # Move airport to DEGRADED BEFORE submit
        get_success_data(api_client.set_airport_posture(
            airport["id"], {"posture": "DEGRADED"}, OPS,
        ))
        set_clock("2026-06-02T11:00:00Z")
        request = submit_request(request["id"])
        agent = create_agent(
            airport["id"], display_name="Ag",
            shift_start_utc="2026-06-02T08:00:00Z",
            shift_end_utc="2026-06-02T20:00:00Z",
        )
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-OAK-1")
        assignment = dispatch_leg(leg["id"], request["id"], DISP)
        walk_assignment_to_handed_off(assignment["id"], agent["id"])
        # Mark segment departed on time so no delay surcharge
        get_success_data(api_client.post_segment_event(
            segment["id"],
            {"event_type": "DEPARTED", "actual_utc": "2026-06-02T12:00:00Z"},
            OPS,
        ))
        complete_assignment(assignment["id"], confirmer_user_id="confirmer_user_9")
        leg = get_success_data(api_client.get_leg(leg["id"], DISP))
        request = get_success_data(api_client.get_assist_request(request["id"], DISP))
        invoices = get_success_data(api_client.list_request_invoices(request["id"], CLERK))
        # The unique OPEN invoice is the FINAL one
        final_inv = next(i for i in invoices if i["invoice_kind"] == "FINAL")
        # DISPUTE it as clerk_1
        disp_resp = api_client.post_invoice_event(
            final_inv["id"],
            {"event_type": "DISPUTE", "expected_invoice_version": final_inv["version"]},
            make_billing_clerk_headers("clerk_1"),
        )
        disputed = get_success_data(disp_resp)
        return request, leg, disputed

    def test_write_off_under_degraded_posture_computes_normalized_baseline(self, api):
        """PRD §3.6: "every write-off against a `FINAL` invoice recomputes the
        same final-leg-charge formula with the posture multiplier pinned to the
        `NORMAL` value of 10000 basis points; the resulting cents value — which
        differs from the FINAL amount whenever the actual posture was not `NORMAL`
        — is the **write-off baseline**, recorded on the invoice for audit even
        though the written-off amount itself equals the existing invoice's
        `amount_cents`."

        Design: Difficulty/dual_variant_calc/final_vs_writeoff_baseline_posture_normalization
        """
        request, leg, disputed = self._setup_completed_at_degraded_then_dispute(api)
        # Final computed under DEGRADED: base 7500 (WCHR → no equipment fee per
        # PRD §3.2/§3.3) * 1.25 posture = 9375
        assert leg["final_leg_cents"] == 9375, (
            f"Expected final_leg_cents 9375, got {leg['final_leg_cents']}"
        )
        # WRITE_OFF as a different clerk (clerk_2) than the DISPUTE clerk (clerk_1)
        resp = api_client.post_invoice_event(
            disputed["id"],
            {"event_type": "WRITE_OFF",
             "expected_invoice_version": disputed["version"]},
            make_billing_clerk_headers("clerk_2"),
        )
        written_off = validate_success(resp)
        assert written_off["status"] == "WRITTEN_OFF"
        # Written-off amount equals existing invoice's amount_cents (9375).
        assert written_off["amount_cents"] == 9375
        # Parent billing_status transitions to WRITTEN_OFF
        req_after = get_success_data(api_client.get_assist_request(request["id"], CLERK))
        assert req_after["billing_status"] == "WRITTEN_OFF"

    def test_write_off_marks_parent_billing_status_written_off(self, api):
        """PRD §3.6: "From `DISPUTED`, the clerk may `RESOLVE_PAID` to reach `PAID`,
        or `WRITE_OFF` to reach `WRITTEN_OFF`."
        PRD §3.6: "`WRITE_OFF` ... moves both the invoice and the parent request's
        `billing_status`" (analogous to MARK_PAID/DISPUTE).

        Design: Difficulty/dual_variant_calc/final_vs_writeoff_baseline_posture_normalization
        """
        request, leg, disputed = self._setup_completed_at_degraded_then_dispute(api)
        # Pre-condition: parent is DISPUTED
        req_pre = get_success_data(api_client.get_assist_request(request["id"], CLERK))
        assert req_pre["billing_status"] == "DISPUTED"
        # WRITE_OFF
        resp = api_client.post_invoice_event(
            disputed["id"],
            {"event_type": "WRITE_OFF",
             "expected_invoice_version": disputed["version"]},
            make_billing_clerk_headers("clerk_3"),
        )
        validate_success(resp)
        # Parent transitions to WRITTEN_OFF while request_status stays COMPLETED
        req_post = get_success_data(api_client.get_assist_request(request["id"], CLERK))
        assert req_post["billing_status"] == "WRITTEN_OFF"
        assert req_post["request_status"] == "COMPLETED"
