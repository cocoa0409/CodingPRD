"""Waterfall conservation and the three reversal strengths (PRD §3.5)."""
from test_helpers import (
    api_client,
    assert_pools_cover_lines,
    assert_waterfall_conservation,
    create_payment,
    create_run,
    get_facility,
    get_participant,
    get_success_data,
    lines_for_run,
    make_agent_headers,
    setup_funded_facility,
    validate_success,
)

AGENT = make_agent_headers()

STANDARD_COMMITMENTS = [("P1", 6_000_000), ("P2", 3_000_000), ("P3", 1_000_000)]


class TestWaterfallConservationAndReversal:
    def test_waterfall_conservation_and_reversal_compensation(self):
        """PRD §3.5: "Two conservation invariants always hold:
        `servicing_fee_cents` plus the interest and principal pools equals the
        payment's `amount_cents`, and the line totals plus
        `agent_retained_cents` equal the two pools."
        PRD §3.5: "Reversing a `REMITTED` payment is a full clawback: hop 1 moves
        the remitted run's lines from `REMITTED` to `CLAWED_BACK`; hop 2 debits
        each clawed-back line's amounts from its participant's
        `cumulative_interest_cents` and `cumulative_principal_cents` and restores
        draw `outstanding_cents` by walking the same oldest-first allocation in
        reverse, adding each line's `principal_cents` back; hop 3 restores the
        facility's `outstanding_principal_cents` and `accrued_interest_cents` to
        their pre-payment values".

        Design: Difficulty/compensating_invariant/waterfall_conservation_and_reversal_compensation
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 5_000_000)
        facility = setup["facility"]
        p1, p2, p3 = setup["participants"]

        pay = create_payment(facility["id"], setup["borrower"]["id"], 200_000, "2026-08-31")
        run = create_run(pay["id"])
        # Conservation at run creation: 1,041 + 50,000 + 148,959 == 200,000.
        assert run["servicing_fee_cents"] == 1_041
        assert run["interest_pool_cents"] == 50_000
        assert run["principal_pool_cents"] == 148_959
        assert_waterfall_conservation(run, 200_000)
        assert_pools_cover_lines(run, lines_for_run(run["id"]))

        validate_success(api_client.remit_distribution_run(run["id"], AGENT))
        assert get_facility(facility["id"])["outstanding_principal_cents"] == 4_851_041

        reversed_payment = validate_success(api_client.reverse_payment(pay["id"], AGENT))
        assert reversed_payment["status"] == "REVERSED"
        assert reversed_payment["reversed_at"] is not None

        for line in lines_for_run(run["id"]):
            assert line["status"] == "CLAWED_BACK"

        restored = get_facility(facility["id"])
        assert restored["outstanding_principal_cents"] == 5_000_000, (
            "principal ledger must be restored to its pre-payment value exactly"
        )
        # §3.5 restores accrued_interest_cents "to their pre-payment values",
        # but the stored pre-payment figure is not uniquely pinned: §3.4
        # materializes accrual at distribution-run creation (after the payment
        # was recorded), so the stored value before the payment was 0 while the
        # run materialized 50,000 to the value date. What §2.7 pins standing:
        # the facility figure always equals the sum over its settled draws.
        settled_draws = [
            d for d in get_success_data(
                api_client.list_draws(AGENT, params={"facility_id": facility["id"]})
            )
            if d["status"] == "SETTLED"
        ]
        assert restored["accrued_interest_cents"] == sum(
            d["accrued_unpaid_interest_cents"] for d in settled_draws
        ), "facility accrued must equal the sum over settled draws (§2.7)"
        for p in (p1, p2, p3):
            refreshed = get_participant(p["id"])
            assert refreshed["cumulative_interest_cents"] == 0
            assert refreshed["cumulative_principal_cents"] == 0

    def test_reversal_of_received_and_allocated_payments(self):
        """PRD §3.5: "Reversing a `RECEIVED` payment simply deducts
        `amount_cents` from `undistributed_cash_cents`. Reversing an `ALLOCATED`
        payment voids its `COMPUTED` runs into `VOIDED` and their `PENDING` lines
        into `VOID`, leaving `undistributed_cash_cents` untouched because it was
        already deducted at allocation."

        Design: Difficulty/compensating_invariant/waterfall_conservation_and_reversal_compensation
        """
        setup = setup_funded_facility(
            [("Solo", 5_000_000)], 1_000_000,
            facility_overrides={"total_commitment_cents": 5_000_000},
        )
        facility = setup["facility"]
        borrower = setup["borrower"]

        # ALLOCATED-strength reversal.
        pay1 = create_payment(facility["id"], borrower["id"], 50_000, "2026-08-31")
        assert get_facility(facility["id"])["undistributed_cash_cents"] == 50_000
        run1 = create_run(pay1["id"])
        assert get_facility(facility["id"])["undistributed_cash_cents"] == 0
        run1_lines = lines_for_run(run1["id"])

        reversed1 = validate_success(api_client.reverse_payment(pay1["id"], AGENT))
        assert reversed1["status"] == "REVERSED"
        old_run = get_success_data(api_client.get_distribution_run(run1["id"], AGENT))
        assert old_run["status"] == "VOIDED"
        for line in run1_lines:
            refreshed = get_success_data(api_client.get_distribution_line(line["id"], AGENT))
            assert refreshed["status"] == "VOID"
        # Deducted at allocation and untouched by this reversal strength.
        assert get_facility(facility["id"])["undistributed_cash_cents"] == 0

        # RECEIVED-strength reversal.
        pay2 = create_payment(facility["id"], borrower["id"], 20_000, "2026-08-31")
        assert get_facility(facility["id"])["undistributed_cash_cents"] == 20_000
        reversed2 = validate_success(api_client.reverse_payment(pay2["id"], AGENT))
        assert reversed2["status"] == "REVERSED"
        assert get_facility(facility["id"])["undistributed_cash_cents"] == 0
