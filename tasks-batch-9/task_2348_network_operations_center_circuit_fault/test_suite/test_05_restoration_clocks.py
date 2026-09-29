"""Restoration measured on two clocks, and the soak that has to pass first.

The carrier clock starts when the ticket was opened and forgives approved carrier
maintenance; the NOC clock runs wall-to-wall from customer-visible detection.
Both are snapshotted when the carrier reports restoration, and a failed soak
throws the whole measurement away.
"""

from test_helpers import (
    SHIFT_LEAD_HEADERS,
    SHIFT_LEAD_USER_ID,
    VENDOR_MANAGER_HEADERS,
    ApiErrorId,
    advance_clock,
    advance_incident,
    assert_carrier_ledger,
    assert_credit_arithmetic,
    assert_instant,
    assert_restoration_clocks,
    build_approved_carrier_window,
    build_nlc_four_path,
    build_pft_single_leg,
    carrier_reports_restored,
    claim_submit_payload,
    clear_alarm,
    confirm_restoration,
    confirm_restoration_payload,
    count_claims_for_ticket,
    file_test_result,
    find_auto_drafted_claim,
    open_carrier_ticket,
    read_carrier,
    read_ticket,
    restore_and_confirm,
    stamped,
    validate_error,
    validate_success,
)


def _nlc_outage_with_carrier_maintenance(api, ticket_reference: str) -> dict:
    """One long NLC outage with an approved carrier window inside it.

    The window is the reason the two clocks diverge: an hour of carrier-announced
    maintenance is forgiven on the carrier clock and invisible to the NOC clock.
    """
    state = build_nlc_four_path(
        api,
        "2026-08-10T00:00:00Z",
        ticket_reference=ticket_reference,
        ticket_opened_at="2026-08-10T00:30:00Z",
    )
    build_approved_carrier_window(
        api,
        state["circuit_id"],
        state["carrier_id"],
        "2026-08-10T02:00:00Z",
        "2026-08-10T03:00:00Z",
        suppresses_monitoring=False,
        risk_acknowledged=True,
    )
    restore_and_confirm(
        api,
        state["ticket_id"],
        state["carrier_id"],
        state["alarm_id"],
        "2026-08-10T06:30:00Z",
        "2026-08-10T07:00:00Z",
        confirmer_user_id=SHIFT_LEAD_USER_ID,
    )
    return state


class TestDualRestorationClocks:
    """One outage yields two durations, and the claim picks which one it bills."""

    def test_carrier_clock_forgives_approved_maintenance_the_noc_clock_does_not(
        self, api
    ):
        """Excluded maintenance separates a 300-minute carrier clock from a 390-minute NOC clock.

        PRD 3.5: "The NOC clock is wall-to-wall from customer-visible detection: `restoration_minutes_noc_clock` is the elapsed minutes from the driving incident's `detected_at` to `restored_at`, with no exclusions at all."
        PRD 3.5: "Step one gathers every maintenance window on the ticket's circuit whose `origin` is `CARRIER_NOTIFIED` and whose `state` is `APPROVED`, `IN_PROGRESS` or `COMPLETED` — proposed, rejected and cancelled windows and every `INTERNAL_CHANGE` window are excluded — and merges their intervals into a disjoint union, each interval including its `window_start` and excluding its `window_end`, processed in ascending `window_start` order with ties broken by ascending `created_at`, and intervals that merely touch end-to-end merged into one."
        PRD 3.5: "`restoration_minutes_carrier_clock` is the raw elapsed minutes minus `excluded_minutes`."

        Design: Difficulty/dual_variant_calc/restoration_dual_clock_carrier_vs_noc_credit_divergence
        """
        state = _nlc_outage_with_carrier_maintenance(api, "NLC-TT-88001")
        ticket = read_ticket(api, state["ticket_id"])

        assert_restoration_clocks(
            ticket, carrier_clock=300.00, noc_clock=390.00, excluded_minutes=60.00
        )
        assert ticket["state"] == "CLOSED_RESTORED", (
            f"the confirmed ticket is closed, got {ticket['state']}"
        )

        claim = find_auto_drafted_claim(api, state["ticket_id"])
        assert claim is not None, "a breached carrier clock drafts a claim automatically"
        assert_credit_arithmetic(
            claim,
            basis="CARRIER_CLOCK",
            sla_target_minutes=240,
            breach_minutes=60.00,
            breach_hours=1,
            credit_amount_cents=45999,
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), exposure_cents=45999
        )

    def test_switching_the_basis_on_submit_rebills_the_whole_claim(self, api):
        """Re-filing on the NOC clock recomputes every amount and moves the ledger by the delta.

        PRD 3.6: "The request may carry a `basis` and an `attestation_note`; when a `basis` is supplied it replaces the stored `basis` and every derived amount — `breach_minutes`, `breach_hours` and `credit_amount_cents` — is recomputed under the new variant **before** the two fiscal checks run, and the carrier's exposure is adjusted by the difference."
        PRD 3.6: "`breach_hours` is zero when `breach_minutes` is zero, and otherwise `breach_minutes` divided by 60 and rounded **up** to the next whole hour, so a breach of 61 minutes is two breach hours."

        Design: Difficulty/dual_variant_calc/restoration_dual_clock_carrier_vs_noc_credit_divergence
        """
        state = _nlc_outage_with_carrier_maintenance(api, "NLC-TT-88001")
        drafted = find_auto_drafted_claim(api, state["ticket_id"])
        assert_credit_arithmetic(drafted, credit_amount_cents=45999)
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), exposure_cents=45999
        )

        advance_incident(api, state["incident_id"], "TRIAGED")
        advance_incident(api, state["incident_id"], "MITIGATED")

        submitted = validate_success(
            api.submit_sla_credit_claim(
                drafted["id"],
                claim_submit_payload(
                    basis="NOC_CLOCK",
                    attestation_note="Re-filed on the monitoring clock",
                ),
                VENDOR_MANAGER_HEADERS,
            )
        )["data"]

        assert_credit_arithmetic(
            submitted,
            basis="NOC_CLOCK",
            sla_target_minutes=240,
            breach_minutes=150.00,
            breach_hours=3,
            credit_amount_cents=138000,
        )
        assert submitted["state"] == "SUBMITTED", (
            f"the claim is now submitted, got {submitted['state']}"
        )
        assert submitted["origin"] == "AUTO_DRAFT", (
            "re-basing does not change how the claim came into existence"
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), exposure_cents=138000
        )


class TestReopenedRestorationCycle:
    """A failed soak sends the ticket backwards and discards the measurement."""

    def test_failed_soak_wipes_the_measurement_and_drafts_nothing(self, api):
        """`RESTORED_PENDING_CONFIRM → REOPENED` clears both clocks and creates no claim.

        PRD 3.5: "When `soak_passed` is false the fault has returned: the ticket moves to `REOPENED`, `reopen_count` advances by 1, and `restored_at` is cleared back to null along with `excluded_minutes` back to zero and both restoration-minute fields back to null, because the measurement they held is now meaningless."
        PRD 3.5: "No claim is synthesised on that branch."

        Design: Difficulty/non_linear_state_machine/carrier_ticket_reopened_cycle_reclears_and_recomputes_restoration
        """
        state = build_nlc_four_path(
            api,
            "2026-08-10T00:00:00Z",
            ticket_reference="NLC-TT-88003",
            ticket_opened_at="2026-08-10T00:30:00Z",
        )
        ticket_id = state["ticket_id"]

        advance_clock(api, "2026-08-10T05:00:00Z")
        carrier_reports_restored(
            api, ticket_id, state["carrier_id"], "2026-08-10T05:00:00Z"
        )
        clear_alarm(api, state["alarm_id"], "2026-08-10T05:00:00Z")

        first_attempt = read_ticket(api, ticket_id)
        assert_restoration_clocks(
            first_attempt, carrier_clock=270.00, noc_clock=300.00, excluded_minutes=0.00
        )

        advance_clock(api, "2026-08-10T05:30:00Z")
        reopened = confirm_restoration(
            api, ticket_id, soak_passed=False, user_id=SHIFT_LEAD_USER_ID
        )

        assert reopened["state"] == "REOPENED", (
            f"a failed soak reopens the ticket, got {reopened['state']}"
        )
        assert reopened["reopen_count"] == 1, (
            f"the loop counter advances once, got {reopened['reopen_count']}"
        )
        assert reopened["restored_at"] is None, "the abandoned restoration instant is cleared"
        assert reopened["restoration_minutes_carrier_clock"] is None, (
            "the carrier clock measurement is meaningless and is discarded"
        )
        assert reopened["restoration_minutes_noc_clock"] is None, (
            "the NOC clock measurement is discarded with it"
        )
        assert reopened["excluded_minutes"] == 0, "excluded minutes go back to zero"
        assert count_claims_for_ticket(api, ticket_id) == 0, (
            "the failed-soak branch synthesises no claim"
        )
        assert_carrier_ledger(read_carrier(api, state["carrier_id"]), exposure_cents=0)

    def test_second_restoration_measures_from_the_original_opening(self, api):
        """The re-derived clocks run from the first `opened_at`, so the credit is 184000.

        PRD 3.5: "A reopened ticket re-enters the cycle at `REOPENED → TESTING` as soon as fresh test evidence is recorded, and the whole loop may run repeatedly."
        PRD 3.5: "It starts from the raw elapsed minutes between the ticket's `opened_at` and `restored_at`, then subtracts `excluded_minutes`, computed in three fixed steps."

        Design: Difficulty/non_linear_state_machine/carrier_ticket_reopened_cycle_reclears_and_recomputes_restoration
        """
        state = build_nlc_four_path(
            api,
            "2026-08-10T00:00:00Z",
            ticket_reference="NLC-TT-88003",
            ticket_opened_at="2026-08-10T00:30:00Z",
        )
        ticket_id = state["ticket_id"]

        advance_clock(api, "2026-08-10T05:00:00Z")
        carrier_reports_restored(
            api, ticket_id, state["carrier_id"], "2026-08-10T05:00:00Z"
        )
        clear_alarm(api, state["alarm_id"], "2026-08-10T05:00:00Z")
        advance_clock(api, "2026-08-10T05:30:00Z")
        confirm_restoration(api, ticket_id, soak_passed=False, user_id=SHIFT_LEAD_USER_ID)

        file_test_result(
            api,
            ticket_id,
            test_type="BERT",
            outcome="FAIL",
            notes="errored seconds returned during soak",
        )
        after_evidence = read_ticket(api, ticket_id)
        assert after_evidence["state"] == "TESTING", (
            f"fresh evidence moves REOPENED to TESTING, got {after_evidence['state']}"
        )
        assert after_evidence["fail_test_count"] == 1, (
            "the failing test is counted as evidence"
        )

        advance_clock(api, "2026-08-10T08:00:00Z")
        carrier_reports_restored(
            api, ticket_id, state["carrier_id"], "2026-08-10T08:00:00Z"
        )
        advance_clock(api, "2026-08-10T08:30:00Z")
        closed = confirm_restoration(api, ticket_id, user_id=SHIFT_LEAD_USER_ID)

        assert closed["state"] == "CLOSED_RESTORED", (
            f"the second attempt closes the ticket, got {closed['state']}"
        )
        assert closed["reopen_count"] == 1, "the ticket reopened exactly once"
        assert_restoration_clocks(
            closed, carrier_clock=450.00, noc_clock=480.00, excluded_minutes=0.00
        )

        claim = find_auto_drafted_claim(api, ticket_id)
        assert claim is not None, "the second restoration breached the target and drafts a claim"
        assert_credit_arithmetic(
            claim,
            basis="CARRIER_CLOCK",
            sla_target_minutes=240,
            breach_minutes=210.00,
            breach_hours=4,
            credit_amount_cents=184000,
        )
        assert count_claims_for_ticket(api, ticket_id) == 1, (
            "only the surviving restoration produced a claim"
        )


class TestConfirmationGuards:
    """Confirmation is guarded by an alarm check and then by the soak clock."""

    def test_open_alarm_outranks_the_unmet_soak_window(self, api):
        """The uncleared root alarm is reported first, then the soak, then success.

        PRD 3.5: "When `soak_passed` is true, two further conditions guard the closure: at least 30 minutes must have elapsed from `restored_at` to the current clock instant, or the request is refused with `ERR_SOAK_WINDOW_NOT_ELAPSED`, and no uncleared root alarm may remain on the ticket's circuit, or the request is refused with `ERR_OPEN_ALARMS_PRESENT`."
        PRD 2.7: "`ERR_OPEN_ALARMS_PRESENT`, guarding two operations: incident resolution requires every alarm attached to the incident to be cleared, and restoration confirmation requires that no uncleared `ROOT` alarm remains on the ticket's circuit."

        Design: Corner/validations/corner_confirm_restoration_before_soak_and_with_open_alarm
        """
        state = build_pft_single_leg(
            api, "2026-08-30T00:00:00Z", alarm_raised_at="2026-08-30T00:00:00Z"
        )

        advance_clock(api, "2026-08-30T00:10:00Z")
        ticket = open_carrier_ticket(
            api, state["incident_id"], state["circuit_id"], "PFT-TT-13"
        )
        ticket_id = ticket["id"]

        advance_clock(api, "2026-08-30T01:00:00Z")
        carrier_reports_restored(
            api, ticket_id, state["carrier_id"], "2026-08-30T01:00:00Z"
        )

        validate_error(
            api.confirm_restoration(
                ticket_id, confirm_restoration_payload(True), SHIFT_LEAD_HEADERS
            ),
            ApiErrorId.ERR_OPEN_ALARMS_PRESENT,
        )

        clear_alarm(api, state["alarm_id"], "2026-08-30T01:00:00Z")
        validate_error(
            api.confirm_restoration(
                ticket_id, confirm_restoration_payload(True), SHIFT_LEAD_HEADERS
            ),
            ApiErrorId.ERR_SOAK_WINDOW_NOT_ELAPSED,
        )

        advance_clock(api, "2026-08-30T01:30:00Z")
        closed = confirm_restoration(api, ticket_id, user_id=SHIFT_LEAD_USER_ID)

        assert closed["state"] == "CLOSED_RESTORED", (
            f"an exactly-30-minute soak is enough, got {closed['state']}"
        )
        assert_instant(
            closed["confirmed_at"], stamped("2026-08-30", "01:30"), "confirmed_at"
        )
        assert closed["restoration_confirmed_by_user_id"] == SHIFT_LEAD_USER_ID, (
            "the confirming shift lead is recorded for the segregation-of-duties check"
        )
        assert_restoration_clocks(closed, carrier_clock=50.00, noc_clock=60.00)
        assert count_claims_for_ticket(api, ticket_id) == 0, (
            "a 50-minute restoration is far inside the standard target, so nothing is drafted"
        )
        assert_carrier_ledger(read_carrier(api, state["carrier_id"]), exposure_cents=0)
