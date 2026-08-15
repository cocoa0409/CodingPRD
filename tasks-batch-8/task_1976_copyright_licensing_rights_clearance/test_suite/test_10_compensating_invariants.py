"""Compensating invariants: reserve/release and pay/refund conservation."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_curator_headers,
    make_ingest_headers,
    make_payer_headers,
    setup_license,
    validate_paginated,
    validate_success,
)


class TestReserveReleaseConservation:
    def test_reserve_then_release_restores_availability(self, api):
        """PRD §3.5: "Release is a deliberate `IngestionAgent` action that
        moves a hold to `RELEASED` and returns its units to the pool."
        PRD §3.5: "The units available for new reservation are what's left:
        `unit_limit` minus `units_reserved` minus `units_consumed_net`."

        Design: Difficulty/compensating_invariant/reserve_release_conserves_units_available
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-12-10T00:00:00Z",
        )
        ingest = make_ingest_headers("ing_ci_1")
        res_a = get_success_data(
            api.create_reservation(
                lic["id"],
                {"units": 3, "expected_license_version": lic["version"]},
                ingest,
            )
        )
        # Release all 3.
        get_success_data(api.release_reservation(res_a["id"], ingest))
        payer = make_payer_headers("fin_ci_1")
        mid = get_success_data(api.get_license(lic["id"], payer))
        assert mid["units_reserved"] == 0
        assert mid["units_consumed_net"] == 0

    def test_reserve_consume_partial_release_conserves_availability(self, api):
        """PRD §3.5: "The effects of a successful draw: the license's
        `units_reserved` falls by the event's `units`, both
        `units_consumed_gross` and `units_consumed_net` rise by the same
        amount, and the reservation either stays `HELD` with its `units`
        reduced by the event's amount (a partial draw) or, when the event
        exactly empties it, moves to `CONSUMED`."
        PRD §3.5: "Release is a deliberate `IngestionAgent` action that
        moves a hold to `RELEASED` and returns its units to the pool."

        Design: Difficulty/compensating_invariant/reserve_release_conserves_units_available
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-12-10T00:00:00Z",
        )
        ingest = make_ingest_headers("ing_ci_2")
        payer = make_payer_headers("fin_ci_2")
        # Reserve 3, consume 2 (partial draw), release the remaining 1.
        res_b = get_success_data(
            api.create_reservation(
                lic["id"],
                {"units": 3, "expected_license_version": lic["version"]},
                ingest,
            )
        )
        get_success_data(
            api.post_usage_event(
                lic["id"],
                {
                    "units": 2,
                    "used_at": "2026-09-01T00:00:00Z",
                    "reservation_id": res_b["id"],
                },
                ingest,
            )
        )
        get_success_data(api.release_reservation(res_b["id"], ingest))
        final = get_success_data(api.get_license(lic["id"], payer))
        # units_available = unit_limit - units_reserved - units_consumed_net
        # = 5 - 0 - 2 = 3, conserved.
        assert final["units_reserved"] == 0
        assert final["units_consumed_net"] == 2


class TestPayRefundConservation:
    def test_full_pay_then_refund_returns_ledger_to_zero(self, api):
        """PRD §3.6: "From `PAID`, only a full refund is accepted — the
        negative `amount_cents` must exactly match `fee_agreed_cents` in
        magnitude."
        PRD §3.6: "If the total is zero or negative and at least one payment
        row exists, the status is `REFUNDED`."

        Design: Difficulty/compensating_invariant/pay_refund_conserves_fee_ledger_zero
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=500000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-08-20T00:00:00Z",
        )
        payer = make_payer_headers("fin_ci_3")
        # Pay in full while ACTIVE.
        get_success_data(
            api.post_payment(
                lic["id"],
                {"amount_cents": 500000, "expected_license_version": lic["version"]},
                payer,
            )
        )
        # Advance clock past term end.
        api.set_clock("2026-08-21T00:00:00Z", make_curator_headers("cur_ci_3"))
        expired = get_success_data(api.get_license(lic["id"], payer))
        assert expired["fee_status"] == "PAID"
        assert expired["lifecycle"] == "EXPIRED"
        # Refund full amount.
        refund = api.post_payment(
            lic["id"],
            {"amount_cents": -500000, "expected_license_version": expired["version"]},
            payer,
        )
        get_success_data(refund)
        final = get_success_data(api.get_license(lic["id"], payer))
        assert final["fee_status"] == "REFUNDED"

    def test_payment_ledger_sums_to_zero_after_compensation(self, api):
        """PRD §3.6: "Let the cumulative total be the sum of all
        `amount_cents` on the license, refunds counting negative. If the
        total is zero or negative and at least one payment row exists, the
        status is `REFUNDED`."

        Design: Difficulty/compensating_invariant/pay_refund_conserves_fee_ledger_zero
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=500000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-08-20T00:00:00Z",
        )
        payer = make_payer_headers("fin_ci_4")
        get_success_data(
            api.post_payment(
                lic["id"],
                {"amount_cents": 500000, "expected_license_version": lic["version"]},
                payer,
            )
        )
        api.set_clock("2026-08-21T00:00:00Z", make_curator_headers("cur_ci_4"))
        expired = get_success_data(api.get_license(lic["id"], payer))
        get_success_data(
            api.post_payment(
                lic["id"],
                {"amount_cents": -500000, "expected_license_version": expired["version"]},
                payer,
            )
        )
        # Sum of payment ledger should be zero.
        payments, _ = validate_paginated(api.list_payments(lic["id"], payer))
        total = sum(p["amount_cents"] for p in payments)
        assert total == 0
