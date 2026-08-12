"""Boundary precision: cure amount and hearing lead time (PRD 3.2, 3.5)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    create_hearing_payload,
    get_case,
    get_notice,
    make_landlord_headers,
    set_clock,
    setup_case_notice_active,
    setup_case_service_complete,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestCureExactAmountBoundary:
    """Depth instance: money boundary on record-cure (>=, not >)."""

    def test_one_cent_short_rejected_exact_amount_cures(self, api):
        """PRD 3.2: "For a PAY_OR_QUIT notice the payload's paid_amount_cents
        must be at least the claimed claimed_rent_owed_cents, or the attempt
        is rejected with ERR_CURE_AMOUNT_INSUFFICIENT (HTTP 422)."

        Design: Difficulty/boundary_precision_check/cure_exact_amount_boundary
        """
        ctx = setup_case_notice_active(
            "CA", claimed_rent_owed_cents=150000, served_on="2026-05-02")
        set_clock("2026-05-03T09:00:00Z")  # inside the cure window
        ll = make_landlord_headers(ctx["landlord"]["id"])
        notice_id = ctx["notice"]["id"]

        resp_short = api.record_cure(notice_id, {"paid_amount_cents": 149999}, ll)
        validate_error(resp_short, ApiErrorId.ERR_CURE_AMOUNT_INSUFFICIENT, 422)

        resp_exact = api.record_cure(notice_id, {"paid_amount_cents": 150000}, ll)
        notice = validate_success(resp_exact, 200)
        assert notice["status"] == "CURED"
        assert get_case(ctx["case"]["id"])["status"] == "CURED"

    def test_overpayment_cure_accepted(self, api):
        """PRD 3.2: "paid_amount_cents must be at least the claimed
        claimed_rent_owed_cents" — an amount one cent ABOVE the claim also
        satisfies 'at least'.

        Design: Difficulty/boundary_precision_check/cure_exact_amount_boundary
        """
        ctx = setup_case_notice_active(
            "CA", claimed_rent_owed_cents=150000, served_on="2026-05-02")
        set_clock("2026-05-03T09:00:00Z")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.record_cure(
            ctx["notice"]["id"], {"paid_amount_cents": 150001}, ll)
        notice = validate_success(resp, 200)
        assert notice["status"] == "CURED"
        assert get_case(ctx["case"]["id"])["status"] == "CURED"


class TestHearingLeadTimeExactBoundary:
    """Depth instance: whole-day lead-time boundary on hearing scheduling."""

    def test_nine_days_fails_ten_days_succeeds(self, api):
        """PRD 3.5: "the calendar date of start_at must be at least the
        calendar date of service_completed_at plus the jurisdiction's lead
        days — 10 in CA, 8 in TX, 12 in OH (ERR_HEARING_LEAD_TIME, HTTP 422)."

        Design: Difficulty/boundary_precision_check/hearing_lead_time_exact_boundary
        """
        ctx = setup_case_service_complete("CA", served_at="2026-06-01T10:00:00Z")
        assert ctx["case"]["status"] == "SERVICE_COMPLETE"

        # 2026-06-10 is 9 days after 2026-06-01: below the CA 10-day lead.
        resp = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(start_at="2026-06-10T10:00:00Z",
                                   end_at="2026-06-10T10:30:00Z"),
            CLERK_A,
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_LEAD_TIME, 422)

        # 2026-06-11 is exactly 10 days: the >= boundary admits it.
        ok = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(start_at="2026-06-11T10:00:00Z",
                                   end_at="2026-06-11T10:30:00Z"),
            CLERK_A,
        )
        hearing = validate_success(ok, 201)
        assert hearing["status"] == "SCHEDULED"

    def test_tx_eight_day_lead_boundary(self, api):
        """PRD 3.5: "the calendar date of start_at must be at least the
        calendar date of service_completed_at plus the jurisdiction's lead
        days — 10 in CA, 8 in TX, 12 in OH (ERR_HEARING_LEAD_TIME, HTTP 422)."

        Design: Difficulty/boundary_precision_check/hearing_lead_time_exact_boundary
        """
        ctx = setup_case_service_complete("TX", served_at="2026-06-01T10:00:00Z")
        # TX lead 8: 2026-06-08 is 7 days out (fails); 2026-06-09 is 8 (passes).
        resp = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(start_at="2026-06-08T10:00:00Z",
                                   end_at="2026-06-08T10:30:00Z"),
            CLERK_A,
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_LEAD_TIME, 422)

        ok = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(start_at="2026-06-09T10:00:00Z",
                                   end_at="2026-06-09T10:30:00Z"),
            CLERK_A,
        )
        assert validate_success(ok, 201)["status"] == "SCHEDULED"
