"""Priority-pair validation conflicts: the earlier pipeline stage masks the
later one when both would fail."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, get_success_data,
    create_active_home_patient, create_draft_order, set_clock, get_patient,
    create_log, list_reviews, api_client,
    make_admin_headers, make_patient_headers, make_nurse_headers,
)


class TestSubmitCancelledOrderBlockedPostureStateWins:
    """State violation (priority 5) masks the business-safety violation
    (priority 6) when both hold."""

    def test_state_error_wins_over_posture_error(self, api):
        """PRD §2.6: "Every request is validated against a fixed pipeline, and
        earlier stages mask later ones — a request rejected at an earlier stage
        never reaches later checks."
        PRD §3.5: "Submission runs a gate ladder in a pinned order, and the
        state check outranks every business check: the order must be `DRAFT` or
        `CHANGES_REQUESTED` (`ERR_ORDER_INVALID_STATE`); the month must not be
        in the past (`ERR_ORDER_MONTH_IN_PAST`); the patient's posture must be
        `HOME_READY` or `AT_RISK` (`ERR_POSTURE_NOT_ORDERABLE`);"

        Design: Difficulty/priority_pair_validation_conflict/submit_cancelled_order_blocked_posture_state_wins
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        order = create_draft_order(pat, "2026-05",
                                   [{"sku": "DIALYSATE_2L", "quantity": 10}])
        # Cancel the order (CANCELLED is terminal; submit from it is invalid).
        validate_success(api.cancel_supply_order(order["id"],
                                                 make_patient_headers(pat)))
        # Drive posture to BLOCKED via an open escalation.
        set_clock("2026-05-03T12:00:00Z")
        create_log(pat, mach, "2026-05-02")
        create_log(pat, mach, "2026-05-03")
        reviews = list_reviews(pat)
        assert reviews and reviews[0]["due_reason"] == "CADENCE"
        validate_success(api.escalate_review(reviews[0]["id"],
                                             make_nurse_headers("nurse-1")))
        assert get_patient(pat)["posture"] == "BLOCKED"
        # Both violations hold; the state error must surface.
        resp = api.submit_supply_order(order["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

    def test_posture_error_wins_when_state_is_valid(self, api):
        """PRD §3.5: "the patient's posture must be `HOME_READY` or `AT_RISK`
        (`ERR_POSTURE_NOT_ORDERABLE`);"

        Design: Difficulty/priority_pair_validation_conflict/submit_cancelled_order_blocked_posture_state_wins

        Note: per §3.4 (PRD line 209) the escalation cascade cancels any DRAFT
        orders. To leave a DRAFT order in place for the submit call we
        escalate FIRST, then create the draft — so the only violation at
        submit time is posture (state is valid).
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        set_clock("2026-05-03T12:00:00Z")
        create_log(pat, mach, "2026-05-02")
        create_log(pat, mach, "2026-05-03")
        reviews = list_reviews(pat)
        validate_success(api.escalate_review(reviews[0]["id"],
                                             make_nurse_headers("nurse-1")))
        assert get_patient(pat)["posture"] == "BLOCKED"
        # Escalation done; now create the draft so the cascade cannot cancel it.
        order = create_draft_order(pat, "2026-05",
                                   [{"sku": "DIALYSATE_2L", "quantity": 10}])
        # Only the posture violation holds on this DRAFT order.
        resp = api.submit_supply_order(order["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_ORDERABLE)


class TestSubmitPastMonthOverCapacityTemporalWins:
    """business_temporal (priority 7) masks business_fiscal (priority 10)."""

    def test_temporal_error_wins_over_storage_error(self, api):
        """PRD §2.6: "Every request is validated against a fixed pipeline, and
        earlier stages mask later ones — a request rejected at an earlier stage
        never reaches later checks."
        PRD §3.5: "The month may not lie before the current clock month, at
        creation or at submission (`ERR_ORDER_MONTH_IN_PAST`)."

        Design: Difficulty/priority_pair_validation_conflict/submit_past_month_over_capacity_temporal_wins
        """
        catalog = [{"sku": "CONCENTRATE_5L", "name": "Concentrate 5L",
                    "unit_price_cents": 4000, "handling_rate_cents": 20,
                    "unit_credit_cents": 1000}]
        set_clock("2026-04-10T00:00:00Z")
        ctx = create_active_home_patient(catalog=catalog)
        pat = ctx["patient"]["id"]
        # Create is legal: 2026-04 is the current clock month.
        order = create_draft_order(pat, "2026-04",
                                   [{"sku": "CONCENTRATE_5L", "quantity": 500}])
        # Advance into May: the month is now past AND 500 > 400 cap.
        set_clock("2026-05-01T00:00:00Z")
        resp = api.submit_supply_order(order["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_ORDER_MONTH_IN_PAST)
        after = get_success_data(api.get_supply_order(order["id"],
                                                      make_admin_headers("admin-1")))
        assert after["order_status"] == "DRAFT", "no state change on rejection"

    def test_storage_error_wins_over_allowance_error(self, api):
        """PRD §3.5: "and then the two quota bounds, storage before allowance."
        PRD §2.6: "**Quota and fiscal checks, always last** —
        `ERR_STORAGE_CAPACITY_EXCEEDED` (evaluated before the allowance bound,
        per §3.5), `ERR_ALLOWANCE_EXCEEDED`, `ERR_QUANTITY_EXCEEDS_ON_HAND`,
        and `ERR_DELIVERED_UNITS_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/submit_past_month_over_capacity_temporal_wins
        """
        catalog = [{"sku": "CONCENTRATE_5L", "name": "Concentrate 5L",
                    "unit_price_cents": 4000, "handling_rate_cents": 20,
                    "unit_credit_cents": 1000}]
        ctx = create_active_home_patient(catalog=catalog)
        pat = ctx["patient"]["id"]
        # Current-month order: storage (400) and allowance (72) both exceeded;
        # storage must surface first.
        order = create_draft_order(pat, "2026-05",
                                   [{"sku": "CONCENTRATE_5L", "quantity": 500}])
        resp = api.submit_supply_order(order["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED)
