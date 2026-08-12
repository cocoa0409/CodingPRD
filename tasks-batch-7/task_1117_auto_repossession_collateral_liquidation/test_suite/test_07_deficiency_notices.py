"""Deficiency estimates and notices: PROVISIONAL vs FINAL dual variants,
the 30-day send window, the dispute/revise cycle, and partial payments."""
from test_helpers import (
    ApiErrorId,
    certify_sale,
    consign,
    create_auction_house,
    create_deficiency_notice,
    issue_quote,
    list_consignment,
    make_borrower_headers,
    parse_instant,
    record_deficiency_payment_payload,
    report_sale,
    revise_deficiency_payload,
    rm_headers,
    set_clock,
    setup_case_collateral_secured,
    setup_case_consign_pending,
    setup_case_deficiency_noticed,
    setup_case_sale_confirmed,
    validate_error,
    validate_success,
)


class TestProvisionalVsFinalDeficiency:
    """The two deficiency variants share one arithmetic skeleton and differ
    only in the proceeds term and the as-of date."""

    def test_deficiency_provisional_estimate_uses_appraisal_proceeds(self, api):
        """PRD §3.7: "if the case has no consignment yet, proceeds are instead
        ninety percent of the grade-adjusted appraisal (the same grade table as
        the reserve price), again rounded half up."
        PRD §3.7: "The payoff as of that date is the loan's
        `total_outstanding_cents` plus the pinned per-diem figure times those
        days, and the total owed is that payoff plus the case's recovery-costs
        total."

        Design: Difficulty/dual_variant_calc/deficiency_provisional_vs_final_diverge
        """
        # COLLATERAL_SECURED at 2026-05-16; no consignment exists yet, so the
        # provisional proceeds come from the grade-adjusted appraisal.
        ctx = setup_case_collateral_secured(
            borrower_overrides={"full_name": "Dana Voss", "email": "dana@x.com"},
            loan_overrides={"vin": "1HGCM82633A004352"})
        set_clock("2026-05-25T00:00:00Z")
        resp = api.get_deficiency_estimate(ctx["case"]["id"], rm_headers())
        estimate = validate_success(resp)
        # payoff = 2,072,000 + 658 x 24 days = 2,087,792; owed +39,500 costs;
        # proceeds = rhu(0.9 x rhu(1,500,000 x 0.75)) = rhu(0.9 x 1,125,000) = 1,012,500.
        assert estimate["estimated_deficiency_cents"] == 1_114_792
        assert estimate["estimated_surplus_cents"] == 0
        assert isinstance(estimate.get("basis"), str) and estimate["basis"], (
            "the response carries a basis string describing the proceeds basis")

    def test_deficiency_final_notice_diverges_from_provisional(self, api):
        """PRD §3.7: "The notice's proceeds term is that record's actual
        `net_proceeds_cents` and its as-of date is the case's `sold_at`, so
        identical ledger data yields a different number than the provisional
        estimate whenever actual proceeds differ from the estimate."
        PRD §3.7: "The deficiency is the excess of total owed over proceeds,
        floored at zero; the surplus is the excess of proceeds over total owed,
        floored at zero."

        Design: Difficulty/dual_variant_calc/deficiency_provisional_vs_final_diverge
        """
        # Same case, same ledger: read the PROVISIONAL estimate at 2026-05-25
        # (no consignment yet), then drive through a certified 1,200,000c sale.
        ctx = setup_case_collateral_secured(
            borrower_overrides={"full_name": "Dana Voss", "email": "dana@x.com"},
            loan_overrides={"vin": "1HGCM82633A004352"})
        quote = issue_quote(ctx["case"]["id"], "REDEMPTION")  # clock still 05-16
        assert quote["status"] == "ISSUED"
        set_clock("2026-05-25T00:00:00Z")
        estimate = validate_success(api.get_deficiency_estimate(ctx["case"]["id"], rm_headers()))
        provisional = estimate["estimated_deficiency_cents"]

        set_clock("2026-05-27T00:00:00Z")  # -> CONSIGNMENT_PENDING
        house = create_auction_house(name="West Auction")
        consignment = consign(ctx["case"]["id"], house["id"])
        list_consignment(consignment["id"], house["id"])
        set_clock("2026-06-05T00:00:00Z")
        sale = report_sale(consignment["id"], house["id"], 1_200_000)
        certify_sale(sale["id"])
        notice = create_deficiency_notice(ctx["case"]["id"])

        # FINAL: payoff 2,072,000 + 658 x 35 (05-01 -> 06-05) = 2,095,030;
        # owed + 39,500 = 2,134,530; proceeds = certified net 1,125,000.
        assert notice["deficiency_amount_cents"] == 1_009_530
        assert notice["surplus_cents"] == 0
        assert notice["status"] == "DRAFT"
        assert provisional == 1_114_792
        assert notice["deficiency_amount_cents"] != provisional, (
            "identical ledger data, different proceeds term: the variants diverge")


class TestEstimateProceedsBasis:
    def test_estimate_uses_latest_consignment_reserve(self, api):
        """PRD §3.7: "proceeds are estimated as ninety percent of the latest
        consignment's `reserve_price_cents`, rounded half up, where "latest" is
        decided by `consignment_seq`; if the case has no consignment yet,
        proceeds are instead ninety percent of the grade-adjusted appraisal
        (the same grade table as the reserve price), again rounded half up."

        Design: Corner/calculations/estimate_uses_latest_consignment_reserve
        """
        ctx = setup_case_consign_pending(
            borrower_overrides={"full_name": "ER", "email": "er@x.com"},
            loan_overrides={"vin": "VIN00000000000057"})
        house = create_auction_house(name="AH")
        consignment = consign(ctx["case"]["id"], house["id"])
        assert consignment["reserve_price_cents"] == 1_055_750

        resp = api.get_deficiency_estimate(ctx["case"]["id"], rm_headers())
        estimate = validate_success(resp)
        # At 2026-05-27: payoff = 2,072,000 + 658 x 26 = 2,089,108;
        # owed + 39,500 = 2,128,608; proceeds = rhu(0.9 x 1,055,750) = 950,175.
        assert estimate["estimated_deficiency_cents"] == 1_178_433
        assert estimate["estimated_surplus_cents"] == 0
        assert isinstance(estimate.get("basis"), str) and estimate["basis"]


class TestDeficiencySendWindow:
    def test_deficiency_send_after_window_returns_error(self, api):
        """PRD §3.7: "Sending is a separate, windowed act: the notice must be
        `DRAFT` (`ERR_INVALID_DEFICIENCY_STATE`), the case must stand in
        `SALE_CONFIRMED` (`ERR_INVALID_CASE_STATE`), and the logical clock must
        be on or before `sold_at` plus thirty days — the statutory
        deficiency-notice window — else the send is rejected with
        `ERR_DEFICIENCY_WINDOW_EXPIRED` (HTTP 422), a temporal check evaluated
        after the state tier."

        Design: Corner/validations/deficiency_send_after_window_returns_error
        """
        ctx = setup_case_sale_confirmed(
            borrower_overrides={"full_name": "DW", "email": "dw@x.com"},
            loan_overrides={"vin": "VIN00000000000061"})
        notice = create_deficiency_notice(ctx["case"]["id"])
        assert notice["status"] == "DRAFT"
        set_clock("2026-07-06T00:00:00Z")  # sold_at 2026-06-05 + 30d = 07-05; now past it
        resp = api.send_deficiency_notice(notice["id"], rm_headers())
        validate_error(resp, ApiErrorId.ERR_DEFICIENCY_WINDOW_EXPIRED)
        notices = validate_success(api.list_deficiency_notices(ctx["case"]["id"], rm_headers()))
        assert notices[0]["status"] == "DRAFT"
        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["status"] == "SALE_CONFIRMED"

    def test_double_send_rejected_invalid_deficiency_state(self, api):
        """PRD §3.7: "Sending is a separate, windowed act: the notice must be
        `DRAFT` (`ERR_INVALID_DEFICIENCY_STATE`), the case must stand in
        `SALE_CONFIRMED` (`ERR_INVALID_CASE_STATE`)"
        PRD §3.7: "A successful send moves the notice to `SENT`, stamps its
        `sent_at`, and moves the case from `SALE_CONFIRMED` to
        `DEFICIENCY_NOTICED`."

        Design: Corner/state_machines/double_send_rejected_invalid_deficiency_state
        """
        ctx = setup_case_deficiency_noticed(
            borrower_overrides={"full_name": "DS", "email": "ds@x.com"},
            loan_overrides={"vin": "VIN00000000000083"})
        notice = ctx["notice"]
        assert notice["status"] == "SENT"
        resp = api.send_deficiency_notice(notice["id"], rm_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_DEFICIENCY_STATE)
        after = validate_success(api.list_deficiency_notices(ctx["case"]["id"], rm_headers()))[0]
        assert parse_instant(after["sent_at"]) == parse_instant("2026-06-05T00:00:00Z"), (
            "sent_at is not re-stamped by a rejected send")


class TestDisputeReviseCycle:
    def test_dispute_then_revise_returns_to_sent_with_adjusted_amount(self, api):
        """PRD §3.7: "The borrower who owns the case may dispute a `SENT`
        notice, moving it to `DISPUTED`. The manager answers a `DISPUTED`
        notice with a revision carrying an `adjustment_cents` and a `reason`:
        the notice's `deficiency_amount_cents` becomes the greater of zero and
        the prior amount plus the adjustment, the notice returns to `SENT`, and
        its `version` increments — the `SENT` → `DISPUTED` → `SENT` cycle may
        repeat as negotiation continues."

        Design: Difficulty/non_linear_state_machine/deficiency_notice_dispute_revise_cycle
        """
        ctx = setup_case_deficiency_noticed(
            borrower_overrides={"full_name": "DC", "email": "dc@x.com"},
            loan_overrides={"vin": "VIN0000000000000E"})
        notice = ctx["notice"]
        assert notice["deficiency_amount_cents"] == 1_009_530

        disputed = validate_success(api.dispute_deficiency_notice(
            notice["id"], make_borrower_headers(ctx["borrower"]["id"])))
        assert disputed["status"] == "DISPUTED"

        revised = validate_success(api.revise_deficiency_notice(
            notice["id"], revise_deficiency_payload(-10_000, "storage fee waived"),
            rm_headers()))
        assert revised["status"] == "SENT", "DISPUTED -> SENT cycle completed"
        assert revised["deficiency_amount_cents"] == 999_530  # 1,009,530 - 10,000

    def test_dispute_revise_cycle_increments_version_each_step(self, api):
        """PRD §2.4: "The `version` field is a system-managed integer that
        increments on every mutation of the resource"
        PRD §3.7: "the notice returns to `SENT`, and its `version` increments"

        Design: Difficulty/non_linear_state_machine/deficiency_notice_dispute_revise_cycle
        """
        ctx = setup_case_sale_confirmed(
            borrower_overrides={"full_name": "DC", "email": "dc@x.com"},
            loan_overrides={"vin": "VIN0000000000000E"})
        notice = create_deficiency_notice(ctx["case"]["id"])
        version_at_create = notice["version"]

        sent = validate_success(api.send_deficiency_notice(notice["id"], rm_headers()))
        assert sent["version"] == version_at_create + 1, "send mutates DRAFT -> SENT"
        disputed = validate_success(api.dispute_deficiency_notice(
            notice["id"], make_borrower_headers(ctx["borrower"]["id"])))
        assert disputed["version"] == version_at_create + 2
        revised = validate_success(api.revise_deficiency_notice(
            notice["id"], revise_deficiency_payload(-10_000, "storage fee waived"),
            rm_headers()))
        assert revised["version"] == version_at_create + 3, (
            "send + dispute + revise each incremented the version")


class TestPartialPayment:
    def test_partial_deficiency_payment_keeps_sent(self, api):
        """PRD §3.7: "The borrower pays down the balance with payments of
        `amount_cents` against a notice in `SENT` or `DISPUTED`: each payment
        accumulates into the notice's `paid_cents`, writes a `PAYMENT` ledger
        entry, and increments the loan's `paid_to_date_cents` by the same
        amount; the notice moves to `PAID` only once `paid_cents` reaches at
        least the `deficiency_amount_cents`, and otherwise remains in its
        current status — partial payments change the numbers, not the state."

        Design: Corner/validations/partial_deficiency_payment_keeps_sent
        """
        ctx = setup_case_deficiency_noticed(
            borrower_overrides={"full_name": "PP2", "email": "pp2@x.com"},
            loan_overrides={"vin": "VIN00000000000064"})
        notice = ctx["notice"]
        assert notice["deficiency_amount_cents"] == 1_009_530

        resp = api.record_deficiency_payment(
            notice["id"], record_deficiency_payment_payload(100_000),
            make_borrower_headers(ctx["borrower"]["id"]))
        after = validate_success(resp)
        assert after["paid_cents"] == 100_000
        assert after["status"] == "SENT", "partial payment does not transition the notice"
