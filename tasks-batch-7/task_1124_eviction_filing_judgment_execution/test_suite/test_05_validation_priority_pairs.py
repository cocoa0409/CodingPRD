"""Validation-ladder priority pairs (PRD 2.7).

The PRD pins an ordered validation ladder: "Every request is evaluated
against an ordered validation ladder, and the first failing rung determines
the error returned." These tests violate two rungs at once and assert the
higher rung's error surfaces.
"""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    create_hearing_payload,
    create_writ_payload,
    finalize_judgment,
    make_landlord_headers,
    set_clock,
    setup_case_filed,
    setup_case_service_complete,
    setup_judgment_entered,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestHearingCreateStateBeatsLeadTime:
    """Depth instance: state gate (rung 7) vs hearing lead time (rung 10)."""

    def test_state_error_wins_when_both_violated(self, api):
        """PRD 2.7: "the first failing rung determines the error returned."
        PRD 2.7 rung 7: "State admissibility — the target entity is in a
        status that permits the operation ... failure yields
        ERR_INVALID_STATE." PRD 3.5: "the calendar date of start_at must be at
        least the calendar date of service_completed_at plus the
        jurisdiction's lead days — 10 in CA, 8 in TX, 12 in OH
        (ERR_HEARING_LEAD_TIME, HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/hearing_create_state_beats_lead_time
        """
        # Case only FILED (no service completed) AND hearing 2 days out.
        ctx = setup_case_filed("CA")
        set_clock("2026-05-06T00:00:01Z")
        resp = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(start_at="2026-05-08T10:00:00Z",
                                   end_at="2026-05-08T10:30:00Z"),
            CLERK_A,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_lead_time_error_surfaces_once_state_allows(self, api):
        """PRD 3.5: "the calendar date of start_at must be at least the
        calendar date of service_completed_at plus the jurisdiction's lead
        days — 10 in CA, 8 in TX, 12 in OH (ERR_HEARING_LEAD_TIME, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/hearing_create_state_beats_lead_time
        """
        ctx = setup_case_service_complete("CA", served_at="2026-06-01T10:00:00Z")
        # 2026-06-10 is 9 days after service date 2026-06-01: short of CA 10.
        resp = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(start_at="2026-06-10T10:00:00Z",
                                   end_at="2026-06-10T10:30:00Z"),
            CLERK_A,
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_LEAD_TIME, 422)


class TestWritRequestSafetyBeatsFee:
    """Depth instance: appeal-window safety (rung 8) vs writ-fee fiscal rule
    (rung 12)."""

    def test_appeal_window_error_wins_over_fee_mismatch(self, api):
        """PRD 2.7: "the first failing rung determines the error returned."
        PRD 3.7: "the judgment must be FINAL — a request during the appeal
        window is rejected with ERR_APPEAL_WINDOW_OPEN (HTTP 409)". PRD 2.7
        rung 8 lists "segregation-of-duties rules, appeal finality,
        possession, and storage-disposal eligibility" ahead of rung 12's
        fiscal rules including "the exact writ fee".

        Design: Difficulty/priority_pair_validation_conflict/writ_request_safety_beats_fee
        """
        ctx = setup_judgment_entered("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        # Judgment still ENTERED (appeal window open) AND fee is wrong (1).
        resp = api.request_writ(
            ctx["judgment"]["id"], {"writ_fee_paid_cents": 1}, ll)
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_OPEN, 409)

    def test_fee_mismatch_surfaces_once_judgment_final(self, api):
        """PRD 3.7: "the writ_fee_paid_cents in the request must exactly
        equal the jurisdictional writ fee — 4000 cents in CA, 3500 in TX,
        2500 in OH — with any mismatch rejected as ERR_WRIT_FEE_MISMATCH
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/writ_request_safety_beats_fee
        """
        ctx = setup_judgment_entered("CA")
        finalize_judgment(ctx)
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.request_writ(
            ctx["judgment"]["id"], {"writ_fee_paid_cents": 3999}, ll)
        validate_error(resp, ApiErrorId.ERR_WRIT_FEE_MISMATCH, 422)
