"""The write response and the reads that follow it agree without any delay.

One close by the last investor ends the raise, buys the building, funds the
reserve and shuts the offering. Everything that cascade produced is already
visible in the close response itself and in the very next reads, with no
intervening write and nothing to poll for.
"""

from test_helpers import (
    SPONSOR,
    TRUSTEE,
    api_client,
    make_investor_headers,
    setup_raise_one_close_short,
    validate_success,
)


class TestTheClosingCascadeIsVisibleImmediately:
    def test_the_close_response_and_the_next_two_reads_already_agree(self):
        """Sequence two, the trust operating, and the rollup reconciled.

        PRD: "Hop one is the close itself, moving the subscription `RESERVED →
        CLOSED`. The subscription's `closed_at` is stamped from the logical clock,
        its `closing_sequence_no` is assigned, and its `rescission_deadline` is
        set to `closed_at` plus the offering's `rescission_window_days` days."

        PRD: "Hop two fires only when the raise is complete: if the trust's
        recomputed `equity_raised_cents` is at least the offering's
        `target_equity_cents`, the trust moves `FUNDING → OPERATING`."

        PRD: "A single close by the last investor therefore ends the raise, buys
        the building, funds the reserve, shuts the offering and turns away
        everyone still queuing — all inside one request."

        PRD: "The trust's own condition is available as a computed read that
        reports the `trust_id`, its `status` and `posture`, the `units_issued` and
        the `units_available` still unsold (the `total_units` minus
        `units_issued`), the `equity_raised_cents`, the `operating_balance_cents`
        and `reserve_balance_cents`, the `reserve_target_cents` (the property's
        `purchase_price_cents` multiplied by the trust's `reserve_target_pct`,
        rounded half up), the `reserve_variance_cents` (the
        `reserve_balance_cents` minus that target, which is negative when the
        reserve is short), the `distributions_paid_cents` (the sum of
        `final_amount_cents` over the trust's distributions in status `PAID`), and
        the `closed_investor_count` (the count of *distinct* `investor_id` values
        over the trust's `CLOSED` subscriptions, so one investor holding two
        closed subscriptions counts once)."

        Design: Corner/consistency_model/closing_subscription_effects_visible_in_the_same_response
        """
        deal = setup_raise_one_close_short()
        assert deal["subscription_a"]["closing_sequence_no"] == 1
        assert deal["subscription_b"]["status"] == "RESERVED"
        assert deal["trust"]["status"] == "FUNDING"

        closed = validate_success(
            api_client.close_subscription(deal["subscription_b"]["id"], SPONSOR)
        )
        assert closed["status"] == "CLOSED"
        assert closed["closing_sequence_no"] == 2
        assert closed["closed_at"] == "2026-11-20T00:00:00.000Z"
        assert closed["rescission_deadline"] == "2026-11-25T00:00:00.000Z"

        trust = validate_success(api_client.get_trust(deal["trust"]["id"], TRUSTEE))
        assert trust["status"] == "OPERATING"
        assert trust["posture"] == "OPEN"
        assert trust["units_issued"] == 600
        assert trust["equity_raised_cents"] == 600_000_000
        assert trust["reserve_balance_cents"] == 30_000_000
        assert trust["operating_balance_cents"] == 1_098_901

        report = validate_success(
            api_client.get_investor_report(
                deal["trust"]["id"], make_investor_headers(deal["investor_b"]["id"])
            )
        )
        assert report["units_available"] == 20
        assert report["reserve_target_cents"] == 24_000_000
        assert report["reserve_variance_cents"] == 6_000_000
        assert report["distributions_paid_cents"] == 0
        assert report["closed_investor_count"] == 2
