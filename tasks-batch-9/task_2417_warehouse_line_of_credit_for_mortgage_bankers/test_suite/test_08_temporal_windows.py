"""Two overlap rules with opposite interval conventions.

Bailee windows are half-open and measured in instants; commitment windows are
closed on both ends, measured in calendar dates, and widened by a two-day
operational buffer before they are compared.
"""

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as make
from test_helpers import fixtures as fx


# ─── Half-open bailee windows ─────────────────────────────────────────────────

def _ship_once_and_hold_the_letter_live():
    """A shipped advance whose only letter runs to 2026-09-04T00:00:00Z.

    No aging run is executed anywhere here, so the letter stays `ISSUED` and the
    overlap filter still sees it.
    """
    scenario = fx.setup_shipped_advance(ship_clock_utc="2026-08-05T00:00:00Z")
    return scenario


class TestBaileeWindowHalfOpen:
    def test_a_reship_one_instant_early_overlaps_the_live_letter(self):
        """One second before expiry the incumbent window still covers the clock.

        PRD 2.8: "No existing `ISSUED` bailee letter of the advance has a window
        overlapping the new letter's, failing shipment with
        `ERR_BAILEE_WINDOW_OVERLAP` (422)."

        Design: Difficulty/resource_temporal_overlap/temporal_bailee_letter_half_open_window_no_overlap
        """
        scenario = _ship_once_and_hold_the_letter_live()
        first = scenario.bailee_letter

        asserts.assert_bailee_letter(first)
        assert first["bailee_period_days"] == 30
        asserts.assert_instant(first["effective_from"], "2026-08-05T00:00:00Z")
        asserts.assert_instant(first["expires_at"], "2026-09-04T00:00:00Z")

        fx.set_clock("2026-09-03T23:59:59Z")
        validate_error(
            api_client.ship_advance(
                scenario.advance["id"],
                make.ship_payload(scenario.investor["id"]),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_BAILEE_WINDOW_OVERLAP,
        )

        letters, meta = validate_paginated(
            api_client.list_advance_bailee_letters(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 1
        assert letters[0]["id"] == first["id"]
        assert letters[0]["status"] == "ISSUED"

    def test_a_reship_at_exactly_the_expiry_instant_is_legal_with_zero_gap(self):
        """The upper bound is exclusive, so adjacency is not overlap.

        PRD 3.7: "It re-stamps `shipped_at`, leaves the custody axis at
        `RELEASED_TO_INVESTOR`, and issues a fresh letter whose `effective_from`
        may equal the prior letter's `expires_at` exactly — half-open windows
        make that zero-gap adjacency legal, while an `effective_from` even one
        instant earlier overlaps and is refused with
        `ERR_BAILEE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/temporal_bailee_letter_half_open_window_no_overlap
        """
        scenario = _ship_once_and_hold_the_letter_live()

        fx.set_clock("2026-09-03T23:59:59Z")
        validate_error(
            api_client.ship_advance(
                scenario.advance["id"],
                make.ship_payload(scenario.investor["id"]),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_BAILEE_WINDOW_OVERLAP,
        )

        fx.set_clock("2026-09-04T00:00:00Z")
        validate_success(
            api_client.ship_advance(
                scenario.advance["id"],
                make.ship_payload(scenario.investor["id"]),
                COLLATERAL_ANALYST,
            ),
            expected_status=201,
        )

        letters, meta = validate_paginated(
            api_client.list_advance_bailee_letters(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 2
        assert [letter["status"] for letter in letters] == ["ISSUED", "ISSUED"]

        second = letters[-1]
        asserts.assert_bailee_letter(second)
        asserts.assert_instant(second["effective_from"], "2026-09-04T00:00:00Z")
        asserts.assert_instant(second["expires_at"], "2026-10-04T00:00:00Z")

        advance = fx.read_advance(scenario.advance["id"])
        assert advance["funding_status"] == "SHIPPED"
        assert advance["custody_status"] == "RELEASED_TO_INVESTOR"


# ─── Closed commitment windows with a two-day buffer ──────────────────────────

def _grant_alpha_an_august_window_and_add_a_second_investor():
    """Alpha holds [2026-08-01, 2026-08-31]; Bravo holds nothing at all."""
    scenario = fx.setup_facility_panel(
        commitment_overrides={
            "committed_amount_cents": 5_000_000_000,
            "price_pct": 1.0125,
            "effective_on": "2026-08-01",
            "expires_on": "2026-08-31",
        },
        with_commitment=True,
    )
    scenario.second_investor = fx.register_investor(
        scenario.facility["id"],
        investor_name="Bravo Capital Markets",
        counterparty_rating="A",
        concentration_limit_pct=0.60,
    )
    return scenario


def _september_window(investor_id, effective_on):
    return make.commitment_payload(
        investor_id,
        committed_amount_cents=3_000_000_000,
        price_pct=1.0100,
        effective_on=effective_on,
        expires_on="2026-09-30",
    )


class TestCommitmentWindowBuffer:
    def test_the_day_after_the_prior_window_still_conflicts_through_the_buffer(self):
        """A one-day gap is inside the two-day buffer on each side.

        PRD 3.2: "Because the underlying windows are closed on both ends and the
        buffer is two days wide, a window that starts on the day immediately
        after a prior window's last date still conflicts, a window that starts
        two days after still conflicts, and only the third day is clear."

        Design: Difficulty/resource_temporal_overlap/temporal_commitment_window_closed_interval_with_buffer
        """
        scenario = _grant_alpha_an_august_window_and_add_a_second_investor()

        incumbent = fx.read_commitment(scenario.commitment["id"])
        asserts.assert_commitment(incumbent)
        assert incumbent["status"] == "OPEN"
        assert incumbent["effective_on"] == "2026-08-01"
        assert incumbent["expires_on"] == "2026-08-31"

        validate_error(
            api_client.create_commitment(
                scenario.facility["id"],
                _september_window(scenario.investor["id"], "2026-09-02"),
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_COMMITMENT_WINDOW_CONFLICT,
        )

        # The third day after the prior window's last date is clear.
        cleared = validate_success(
            api_client.create_commitment(
                scenario.facility["id"],
                _september_window(scenario.investor["id"], "2026-09-03"),
                CREDIT_OFFICER,
            ),
            expected_status=201,
        )
        asserts.assert_commitment(cleared)
        assert cleared["effective_on"] == "2026-09-03"
        assert cleared["status"] == "OPEN"

        _rows, meta = validate_paginated(
            api_client.list_investor_commitments(
                scenario.investor["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 2

    def test_the_exclusion_is_scoped_to_one_facility_and_investor_pair(self):
        """The identical rejected window is accepted for a different investor.

        PRD 3.2: "A proposed window is widened by two days on each side and must
        not intersect the window of any existing commitment of that pair whose
        status is `OPEN` or `PARTIALLY_ALLOCATED`; an intersection is rejected
        with `ERR_COMMITMENT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/temporal_commitment_window_closed_interval_with_buffer
        """
        scenario = _grant_alpha_an_august_window_and_add_a_second_investor()

        validate_error(
            api_client.create_commitment(
                scenario.facility["id"],
                _september_window(scenario.investor["id"], "2026-09-02"),
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_COMMITMENT_WINDOW_CONFLICT,
        )

        accepted = validate_success(
            api_client.create_commitment(
                scenario.facility["id"],
                _september_window(scenario.second_investor["id"], "2026-09-02"),
                CREDIT_OFFICER,
            ),
            expected_status=201,
        )
        asserts.assert_commitment(accepted)
        assert accepted["investor_id"] == scenario.second_investor["id"]
        assert accepted["effective_on"] == "2026-09-02"
        assert accepted["status"] == "OPEN"

        # Alpha's own book is untouched by the refusal.
        _rows, meta = validate_paginated(
            api_client.list_investor_commitments(
                scenario.investor["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 1
