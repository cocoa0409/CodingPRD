"""Campaign counting variants, credit-split rounding, counting-window edges,
and campaign lifecycle gates."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_campaign, create_prospect, create_payment, create_gift_payment_payload,
    create_campaign_payload, setup_active_pledge,
    get_pledge, get_prospect,
)

DIR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]
FIN = TEST_USERS["finance_headers"]


class TestCampaignVariantDivergence:
    """Queue A: dual_variant_calc / campaign_face_value_vs_cash_receipts_divergence."""

    def _setup(self, api):
        """Campaign ACTIVE; a 10000000 pledge in 3 monthly installments booked to
        it; payments 3333334 (plain) and 666666 (matched), both pledge-linked."""
        campaign = create_campaign()
        ctx = setup_active_pledge(
            10000000, installment_count=3, frequency="MONTHLY",
            first_due_date="2026-09-01T00:00:00Z", campaign_id=campaign["id"],
        )
        ctx["campaign"] = campaign
        create_payment(ctx["p"]["id"], 3333334, received_at="2026-09-01T00:00:00Z",
                       pledge_id=ctx["pledge"]["id"], campaign_id=campaign["id"])
        create_payment(ctx["p"]["id"], 666666, received_at="2026-09-02T00:00:00Z",
                       payment_method="CHECK", pledge_id=ctx["pledge"]["id"],
                       campaign_id=campaign["id"], corporate_matched=True)
        return ctx

    def test_face_value_counts_booked_pledge_not_pledge_linked_payments(self, api):
        """PRD §3.9: "Under `FACE_VALUE_BOOKING` — the board-facing booking
        measure — the campaign counts every pledge booked to it whose creation
        time falls inside the inclusive window and whose status is `ACTIVE`,
        `FULFILLED`, or `WRITTEN_OFF`, at its `total_amount_cents` net of its
        `written_off_cents` ... plus every non-reversed payment booked to the
        campaign that is not pledge-linked and whose `received_at` falls inside
        the window, counted at full amount or, when `corporate_matched`, at half
        the amount rounded down to a whole cent per payment."

        Design: Difficulty/dual_variant_calc/campaign_face_value_vs_cash_receipts_divergence
        """
        ctx = self._setup(api)
        totals = validate_success(api.get_campaign_totals(ctx["campaign"]["id"], FIN))
        # Pledge face 10000000 net of write-offs (0); pledge-linked payments excluded.
        assert totals["face_value_counted_cents"] == 10000000

    def test_cash_receipts_counts_all_in_window_payments_with_matched_floor(self, api):
        """PRD §3.9: "Under `CASH_RECEIPTS` — the cash-flow measure — the
        campaign counts every non-reversed payment booked to it whose
        `received_at` falls inside the window, including pledge-linked payments
        that the face-value variant ignores, at the same full-or-floored-half
        amount; unpaid pledge balances count for nothing here."

        Design: Difficulty/dual_variant_calc/campaign_face_value_vs_cash_receipts_divergence
        """
        ctx = self._setup(api)
        totals = validate_success(api.get_campaign_totals(ctx["campaign"]["id"], FIN))
        # 3333334 + floor(666666 * 0.5) = 3333334 + 333333
        assert totals["cash_counted_cents"] == 3666667
        # The variants diverge on identical data.
        assert totals["face_value_counted_cents"] != totals["cash_counted_cents"]


class TestCreditSplitRounding:
    """Queue A: combinatorial_formula / credit_split_residual_rounding_order."""

    def _setup_split_payment(self, api):
        campaign = create_campaign(name="Split Campaign", goal_cents=1000000)
        pd = create_prospect(full_name="Donor D", contact_email="d@x.com")
        ps = create_prospect(full_name="Spouse S", contact_email="s@x.com",
                             spouse_prospect_id=pd["id"])
        pf = create_prospect(full_name="Friend F", contact_email="f@x.com")
        pay = create_payment(
            pd["id"], 10001, received_at="2026-09-01T00:00:00Z", payment_method="CHECK",
            campaign_id=campaign["id"],
            splits=[
                {"prospect_id": pd["id"], "credit_type": "HARD", "split_pct": 34},
                {"prospect_id": ps["id"], "credit_type": "SOFT", "split_pct": 33},
                {"prospect_id": pf["id"], "credit_type": "SOFT", "split_pct": 33},
            ],
        )
        return campaign, pd, ps, pf, pay

    def test_largest_split_absorbs_rounding_residual(self, api):
        """PRD §3.7: "The credited amounts are computed with a pinned rounding
        order: the splits are sorted by ascending `split_pct`, ties broken by
        their position in the request array (first listed counts as smaller);
        every split except the last in that order — the largest — is credited the
        payment's `amount_cents` multiplied by its percentage and divided by 100,
        rounded half up to a whole cent; and the largest split absorbs the
        residual, receiving the payment amount minus the sum of the rounded
        amounts, so the parts always total the payment exactly."

        Design: Difficulty/combinatorial_formula/credit_split_residual_rounding_order
        """
        campaign, pd, ps, pf, pay = self._setup_split_payment(api)
        rows, _ = validate_paginated(api.list_payment_credit_splits(pay["id"], FIN))
        by_prospect = {r["prospect_id"]: r for r in rows}

        # The two 33% splits round first: round_half_up(10001 * 0.33) = 3300 each.
        assert by_prospect[ps["id"]]["amount_cents"] == 3300
        assert by_prospect[pf["id"]]["amount_cents"] == 3300
        # The largest (HARD, 34%) absorbs the residual: 10001 - 3300 - 3300.
        assert by_prospect[pd["id"]]["amount_cents"] == 3401
        assert by_prospect[pd["id"]]["credit_type"] == "HARD"
        # No cent lost or created.
        assert sum(r["amount_cents"] for r in rows) == 10001

    def test_only_hard_split_enters_campaign_totals(self, api):
        """PRD §3.7: "Only the `HARD` split's amount enters campaign counting
        (§3.9); `SOFT` splits surface only in the comprehensive recognition
        projection."

        Design: Difficulty/combinatorial_formula/credit_split_residual_rounding_order
        """
        campaign, pd, ps, pf, pay = self._setup_split_payment(api)
        totals = validate_success(api.get_campaign_totals(campaign["id"], FIN))
        # Only the HARD split's 3401 counts; the payment is not pledge-linked so
        # the face variant also counts it.
        assert totals["cash_counted_cents"] == 3401
        assert totals["face_value_counted_cents"] == 3401

    def test_splits_sum_not_100_rejected(self, api):
        """PRD §3.7: "Exactly one split must be `HARD` and it must name the
        `donor_prospect_id`, and the percentages must sum to exactly 100; any
        deviation — a missing or duplicated hard split, a percentage outside 1 to
        100, or a sum other than 100 — is rejected with
        `ERR_SPLIT_PERCENT_SUM_INVALID`."

        Design: Corner/validations/splits_sum_not_100_rejected
        """
        pd = create_prospect(full_name="Donor D", contact_email="d@x.com")
        ps = create_prospect(full_name="Spouse S", contact_email="s@x.com")
        resp = api.create_gift_payment(
            create_gift_payment_payload(
                pd["id"], amount_cents=100000, payment_method="CHECK",
                splits=[
                    {"prospect_id": pd["id"], "credit_type": "HARD", "split_pct": 50},
                    {"prospect_id": ps["id"], "credit_type": "SOFT", "split_pct": 40},
                ],
            ),
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_SPLIT_PERCENT_SUM_INVALID)
        rows, meta = validate_paginated(api.list_gift_payments(FIN, params={"donor_prospect_id": pd["id"]}))
        assert rows == [] and meta["total_count"] == 0


class TestCampaignLifecycleAndWindows:
    def test_campaign_lifecycle_transition_gates(self, api):
        """PRD §3.9: "The same role activates a `DRAFT` campaign (`ACTIVE`),
        closes an `ACTIVE` one (`CLOSED`), and marks a `CLOSED` one as
        `REPORTED`; each step out of order fails with
        `ERR_CAMPAIGN_INVALID_STATE`, and `REPORTED` is terminal."

        Design: Corner/state_machines/campaign_lifecycle_transition_gates
        """
        campaign = create_campaign(active=False)

        resp = api.close_campaign(campaign["id"], VP)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_INVALID_STATE)  # close from DRAFT

        validate_success(api.activate_campaign(campaign["id"], VP))
        resp = api.report_campaign(campaign["id"], VP)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_INVALID_STATE)  # report from ACTIVE

        validate_success(api.close_campaign(campaign["id"], VP))
        validate_success(api.report_campaign(campaign["id"], VP))

        resp = api.activate_campaign(campaign["id"], VP)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_INVALID_STATE)  # REPORTED is terminal

        assert validate_success(api.get_campaign(campaign["id"], VP))["status"] == "REPORTED"

    def test_counting_window_inclusive_boundary(self, api):
        """PRD §3.9: "A `VPAdvancement` creates a campaign with a `name`, a
        positive integer `goal_cents`, and an **inclusive** counting window from
        `counting_start` through `counting_end`."
        PRD §3.7: "a campaign reference requires the campaign `ACTIVE`
        (`ERR_CAMPAIGN_INVALID_STATE`) with `received_at` inside the inclusive
        window from `counting_start` to `counting_end`
        (`ERR_OUTSIDE_COUNTING_WINDOW`)."

        Design: Corner/validations/counting_window_inclusive_boundary
        """
        campaign = create_campaign(
            name="Short Window", goal_cents=1000000,
            counting_start="2026-08-01T00:00:00Z", counting_end="2026-08-31T00:00:00Z",
        )
        p = create_prospect()

        pay = create_payment(p["id"], 100, received_at="2026-08-31T00:00:00Z",
                             payment_method="CHECK", campaign_id=campaign["id"])
        assert pay["id"]  # counting_end is inclusive

        resp = api.create_gift_payment(
            create_gift_payment_payload(
                p["id"], amount_cents=100, received_at="2026-08-31T00:00:01Z",
                payment_method="CHECK", campaign_id=campaign["id"],
            ),
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_COUNTING_WINDOW)

        totals = validate_success(api.get_campaign_totals(campaign["id"], FIN))
        assert totals["cash_counted_cents"] == 100

    def test_payment_to_closed_campaign_rejected(self, api):
        """PRD §3.9: "Closing freezes both counted totals permanently: payments
        or write-offs later referencing the campaign are rejected rather than
        re-opening the books."
        PRD §3.7: "a campaign reference requires the campaign `ACTIVE`
        (`ERR_CAMPAIGN_INVALID_STATE`)."

        Design: Corner/validations/payment_to_closed_campaign_rejected
        """
        campaign = create_campaign()
        validate_success(api.close_campaign(campaign["id"], VP))
        p = create_prospect()
        resp = api.create_gift_payment(
            create_gift_payment_payload(
                p["id"], amount_cents=100, payment_method="CHECK",
                campaign_id=campaign["id"],
            ),
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_INVALID_STATE)
