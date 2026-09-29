"""The bounded negotiation loop on a job quote: COUNTERED back to SUBMITTED and round again."""

import pytest

from test_helpers import (
    PRO_DESK_ASSOCIATE,
    SKU_SHINGLE_BUNDLE,
    api_client,
    counter_offer_line_price,
    create_draft_quote,
    get_success_data,
    make_contractor_admin_headers,
    setup_pro_desk,
    submit_quote,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Local setup helpers (built from published endpoints only)                    #
# --------------------------------------------------------------------------- #


def _setup_submitted_quote():
    """One stocked store, a GOLD account, and an eight-unit quote in SUBMITTED."""
    scenario = setup_pro_desk(
        tier_code="GOLD",
        skus=[(SKU_SHINGLE_BUNDLE, 600)],
        account_overrides={
            "business_name": "Ridgeline Roofing",
            "tier_review_mode": "PINNED_AT_REVIEW",
            "baseline_volume_cents": 6_000_000,
        },
    )
    account = scenario["account"]
    quote, quote_lines = create_draft_quote(
        account["id"],
        scenario["store"]["id"],
        [(SKU_SHINGLE_BUNDLE, 8)],
        job_name="MAPLE-ST-REROOF",
        requested_term_days=45,
    )
    submitted = submit_quote(quote["id"], account["id"])
    return account, submitted, quote_lines


def _write_round(quote_id: str, quote_line_id: str, unit_price_cents: int, version: int):
    return validate_success(
        api_client.counter_offer_job_quote(
            quote_id,
            [counter_offer_line_price(quote_line_id, unit_price_cents)],
            45,
            version,
            PRO_DESK_ASSOCIATE,
        ),
        expected_status=200,
    )


def _revise(quote_id: str, account_id: str, note: str):
    return validate_success(
        api_client.revise_job_quote(
            quote_id, note, make_contractor_admin_headers(account_id)
        ),
        expected_status=200,
    )


def _read_quote_line(quote_line_id: str, account_id: str) -> dict:
    return get_success_data(
        api_client.get_quote_line(
            quote_line_id, make_contractor_admin_headers(account_id)
        )
    )


class TestQuoteNegotiationCycle:
    def test_quote_cycles_countered_back_to_submitted_and_counters_again(self):
        """PRD §3.5: "A `ProDeskAssociate` writes a **counter-offer round**, taking the quote from `SUBMITTED` to `COUNTERED`."

        PRD §3.5: "The contractor's answer to a round is either acceptance further down the chain or a **revision**, which is the cycle edge that closes the loop: a revision takes the quote from `COUNTERED` back to `SUBMITTED`, carries a `revision_note` explaining what the contractor wants changed, increases `revision_count` by one, and increments the quote's `version`."

        PRD §3.5: "The quote also records the round's proposed `term_days` as the candidate term, stamps `authored_by_user_id` with the acting associate's `X-User-ID`, increases `round_count` by one, and increments its `version`."

        PRD §3.5: "The full cycle is therefore `DRAFT → SUBMITTED → COUNTERED → SUBMITTED → COUNTERED`, and it can turn until the round budget is spent."

        Design: Difficulty/non_linear_state_machine/job_quote_negotiation_cycle_countered_back_to_submitted
        """
        account, submitted, quote_lines = _setup_submitted_quote()
        quote_line = quote_lines[0]

        after_round_one = _write_round(
            submitted["id"], quote_line["id"], 1300, submitted["version"]
        )
        assert after_round_one["status"] == "COUNTERED"
        assert after_round_one["round_count"] == 1
        assert after_round_one["revision_count"] == 0

        after_revision = _revise(
            submitted["id"],
            account["id"],
            "1300 is under our cost basis; re-price at 1500",
        )
        assert after_revision["status"] == "SUBMITTED"
        assert after_revision["round_count"] == 1
        assert after_revision["revision_count"] == 1

        after_round_two = _write_round(
            submitted["id"], quote_line["id"], 1500, after_revision["version"]
        )
        assert after_round_two["status"] == "COUNTERED"
        assert after_round_two["round_count"] == 2
        assert after_round_two["revision_count"] == 1

    def test_second_round_supersedes_the_first_rounds_negotiated_prices(self):
        """PRD §3.5: "A successful round **supersedes** the previous one wholesale."

        PRD §3.5: "Each named line's `negotiated_unit_price_cents` is overwritten and its `line_negotiated_subtotal_cents` is set to that price multiplied by the line's `qty_units`."

        PRD §3.5: "The quote's `negotiated_total_cents` becomes the sum of those line figures, and its `discount_depth_pct` is recomputed as the amount given away divided by the list value — that is, `list_subtotal_cents` less `negotiated_total_cents`, divided by `list_subtotal_cents` — rounded half up to four decimal places."

        PRD §3.5: "They stay on the quote lines until the next counter-offer overwrites them, so a quote sitting in `SUBMITTED` after a revision still reports the last round's `negotiated_total_cents` and `discount_depth_pct`."

        Design: Difficulty/non_linear_state_machine/job_quote_negotiation_cycle_countered_back_to_submitted
        """
        account, submitted, quote_lines = _setup_submitted_quote()
        quote_line = quote_lines[0]
        assert submitted["list_subtotal_cents"] == 15992

        after_round_one = _write_round(
            submitted["id"], quote_line["id"], 1300, submitted["version"]
        )
        assert after_round_one["negotiated_total_cents"] == 10400
        assert after_round_one["discount_depth_pct"] == pytest.approx(0.3497, abs=1e-9)

        after_revision = _revise(
            submitted["id"],
            account["id"],
            "1300 is under our cost basis; re-price at 1500",
        )
        assert after_revision["negotiated_total_cents"] == 10400
        assert after_revision["discount_depth_pct"] == pytest.approx(0.3497, abs=1e-9)

        after_round_two = _write_round(
            submitted["id"], quote_line["id"], 1500, after_revision["version"]
        )
        assert after_round_two["list_subtotal_cents"] == 15992
        assert after_round_two["negotiated_total_cents"] == 12000
        assert after_round_two["discount_depth_pct"] == pytest.approx(0.2496, abs=1e-9)

        refreshed_line = _read_quote_line(quote_line["id"], account["id"])
        assert refreshed_line["negotiated_unit_price_cents"] == 1500
        assert refreshed_line["line_negotiated_subtotal_cents"] == 12000
