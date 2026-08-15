"""Write-off approval cascade: latest-first allocation, pledge WRITTEN_OFF,
campaign FACE netting, and recognition demotion."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_campaign, create_payment, setup_active_pledge,
    create_recognition_society,
    get_pledge, list_installments,
)

DIR = TEST_USERS["director_headers"]
DRO = TEST_USERS["dro_headers"]
FIN = TEST_USERS["finance_headers"]


class TestWriteOffCascade:
    """Queue A: transitive_cascade / writeoff_approval_pledge_campaign_recognition_cascade."""

    def _setup(self, api):
        """Campaign ACTIVE; BRONZE at 10000000; UNRESTRICTED pledge 10000000 in
        3 monthly installments [3333334, 3333333, 3333333] booked to the
        campaign; payments 3333334 + 666666 (installment 1 PAID, installment 2
        partially paid 666666); outstanding 6000000."""
        create_recognition_society()
        campaign = create_campaign()
        ctx = setup_active_pledge(
            10000000, installment_count=3, frequency="MONTHLY",
            first_due_date="2026-09-01T00:00:00Z", campaign_id=campaign["id"],
        )
        ctx["campaign"] = campaign
        pl_id, p_id, c_id = ctx["pledge"]["id"], ctx["p"]["id"], campaign["id"]
        create_payment(p_id, 3333334, received_at="2026-09-01T00:00:00Z",
                       pledge_id=pl_id, campaign_id=c_id)
        create_payment(p_id, 666666, received_at="2026-09-02T00:00:00Z",
                       payment_method="CHECK", pledge_id=pl_id, campaign_id=c_id)
        return ctx

    def test_approval_allocates_latest_first_and_flips_pledge(self, api):
        """PRD §3.6: "Approval allocates the written amount **latest-first**:
        installments with an open balance are visited from the latest due date to
        the earliest — ties broken by descending `sequence_number` — and each
        receives the smaller of the remaining write-off amount and its open
        balance, added to its `written_off_cents`. An installment thereby fully
        covered with `paid_cents` still zero becomes `WRITTEN_OFF`; partial
        coverage simply raises `written_off_cents`; and an installment that
        becomes fully covered while holding `paid_cents` above zero is treated as
        settled and becomes `PAID`."
        PRD §3.6: "it becomes `WRITTEN_OFF` when no installment remains in
        `SCHEDULED`, `REMINDED`, or `OVERDUE` and at least one installment
        carries a positive `written_off_cents`."

        Design: Difficulty/transitive_cascade/writeoff_approval_pledge_campaign_recognition_cascade
        """
        ctx = self._setup(api)
        pl_id = ctx["pledge"]["id"]

        # Pre-approval recognition: 4000000 cash + 6000000 outstanding projects BRONZE.
        rec_before = validate_success(api.get_recognition(ctx["p"]["id"], DRO))
        assert rec_before["comprehensive_total_cents"] == 10000000
        assert rec_before["projected_level"] == "BRONZE"

        resp = api.create_write_off(pl_id, {"amount_cents": 6000000, "reason": "UNCOLLECTIBLE"}, FIN)
        wo = validate_success(resp, expected_status=201)
        validate_success(api.review_write_off(wo["id"], {"decision": "APPROVE"}, DIR))

        rows = list_installments(pl_id)
        # Latest-first: installment 3 fully written off (paid 0) -> WRITTEN_OFF.
        assert rows[2]["status"] == "WRITTEN_OFF"
        assert rows[2]["written_off_cents"] == 3333333
        # Installment 2: 666666 paid + 2666667 written off -> fully covered, PAID.
        assert rows[1]["status"] == "PAID"
        assert rows[0]["status"] == "PAID"

        pledge = get_pledge(pl_id)
        assert pledge["status"] == "WRITTEN_OFF"
        assert pledge["outstanding_cents"] == 0
        assert pledge["written_off_cents"] == 6000000

    def test_approval_nets_campaign_face_and_demotes_recognition(self, api):
        """PRD §3.6: "Approval also nets the written amount out of the booking
        campaign's face-value total (§3.9) and recomputes the prospect's
        outstanding balance and recognition standing."
        PRD §3.9: "the campaign counts every pledge booked to it whose creation
        time falls inside the inclusive window and whose status is `ACTIVE`,
        `FULFILLED`, or `WRITTEN_OFF`, at its `total_amount_cents` net of its
        `written_off_cents`."

        Design: Difficulty/transitive_cascade/writeoff_approval_pledge_campaign_recognition_cascade
        """
        ctx = self._setup(api)
        pl_id, c_id, p_id = ctx["pledge"]["id"], ctx["campaign"]["id"], ctx["p"]["id"]

        resp = api.create_write_off(pl_id, {"amount_cents": 6000000, "reason": "UNCOLLECTIBLE"}, FIN)
        wo = validate_success(resp, expected_status=201)
        validate_success(api.review_write_off(wo["id"], {"decision": "APPROVE"}, DIR))

        totals = validate_success(api.get_campaign_totals(c_id, FIN))
        # FACE nets out the write-off: 10000000 - 6000000.
        assert totals["face_value_counted_cents"] == 4000000
        # CASH unchanged by the write-off.
        assert totals["cash_counted_cents"] == 4000000

        rec_after = validate_success(api.get_recognition(p_id, DRO))
        # The pledge leaving ACTIVE drops 6000000 from the comprehensive total.
        assert rec_after["comprehensive_total_cents"] == 4000000
        assert rec_after["projected_level"] is None
