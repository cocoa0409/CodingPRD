"""File fee computation: per-entry rounding order and quoted-vs-assessed cards."""
from test_helpers import (
    append_entries_ok,
    create_active_originator,
    create_warehoused_file,
    define_cutoff_window,
    define_next_day_window,
    define_same_day_1_window,
    entry_payload,
    release_file_ok,
    set_clock,
)


def _setup_rounding_file():
    """SAME_DAY_2 card (61/100/0); originator discount 5000 bps; empty file."""
    define_cutoff_window(window_kind="SAME_DAY_2", opens_at_utc="13:00",
                         closes_at_utc="16:00", per_entry_fee_cents=61,
                         file_fee_cents=100, large_entry_surcharge_cents=0)
    org = create_active_originator("Delta Inc", ["WEB"],
                                   exposure_limit_cents=100_000_000,
                                   fee_discount_bps=5_000)
    set_clock("2026-08-03T10:00:00Z")
    return create_warehoused_file(org, "WEB", "SAME_DAY_2", "2026-08-03")


class TestPerEntryRoundingOrder:
    def test_quoted_fee_rounds_per_entry_then_sums(self, api):
        """PRD 2.8: "**Per-entry fee discounts** are rounded half-up to a whole
        cent per entry before summing (§3.2). The rounding order is pinned:
        discount each entry first, then sum."
        PRD 3.2: "The total file fee is the window's `file_fee_cents` — which is
        never discounted — plus the sum of the discounted per-entry fees over
        the file's entries."

        Design: Difficulty/combinatorial_formula/file_fee_per_entry_rounding_order
        """
        ach_file = _setup_rounding_file()
        appended = append_entries_ok(ach_file["id"], [
            entry_payload("DEBIT", 1_000, "d-1"),
            entry_payload("DEBIT", 2_000, "d-2"),
            entry_payload("DEBIT", 3_000, "d-3"),
        ])
        # rhu(61 * 0.5) = 31 per entry; 100 + 31 + 31 + 31 = 193.
        # (Sum-then-round would give 192 — not the pinned rule.)
        assert appended["quoted_fee_cents"] == 193

    def test_append_recomputes_entry_count_and_total(self, api):
        """PRD 3.3: "`entry_count` and `total_amount_cents` are recomputed as
        the count and the `amount_cents` sum over all of the file's entries in
        every status — figures that only ever grow, since cancelled or returned
        entries still count".

        Design: Difficulty/combinatorial_formula/file_fee_per_entry_rounding_order
        """
        ach_file = _setup_rounding_file()
        appended = append_entries_ok(ach_file["id"], [
            entry_payload("DEBIT", 1_000, "d-1"),
            entry_payload("DEBIT", 2_000, "d-2"),
            entry_payload("DEBIT", 3_000, "d-3"),
        ])
        assert appended["entry_count"] == 3
        assert appended["total_amount_cents"] == 6_000


def _setup_rollover_file():
    """SAME_DAY_1 (150/500/400) + NEXT_DAY (60/200/100); originator discount
    333 bps; file requesting SAME_DAY_1 effective 2026-08-03, entries appended
    at 10:00 while the window is still open."""
    define_same_day_1_window()
    define_next_day_window()
    org = create_active_originator("Beta Corp", ["CCD"],
                                   exposure_limit_cents=1_000_000_000,
                                   fee_discount_bps=333)
    set_clock("2026-08-03T10:00:00Z")
    ach_file = create_warehoused_file(org, "CCD", "SAME_DAY_1", "2026-08-03")
    appended = append_entries_ok(ach_file["id"], [
        entry_payload("DEBIT", 1_000_000, "r-1"),
        entry_payload("DEBIT", 20_000_000, "r-2"),
        entry_payload("DEBIT", 500_000, "r-3"),
    ])
    return appended


class TestQuotedVsAssessedFee:
    def test_quoted_fee_uses_requested_window_card(self, api):
        """PRD 3.3: "`quoted_fee_cents` is recomputed under the
        `requested_window_kind` rate card, failing with
        `ERR_NO_ELIGIBLE_WINDOW` if that window row is missing."
        PRD 3.2: "Each entry's base per-entry fee is the window's
        `per_entry_fee_cents`, plus the window's `large_entry_surcharge_cents`
        when the entry's `amount_cents` is strictly greater than $100,000.00 —
        an entry of exactly $100,000.00 carries no surcharge."

        Design: Difficulty/dual_variant_calc/file_fee_quoted_vs_assessed_cutoff_rollover
        """
        appended = _setup_rollover_file()
        # SAME_DAY_1 card: rhu(150*.9667)=145, rhu(550*.9667)=532, 145; +500.
        assert appended["quoted_fee_cents"] == 1_322
        assert appended["status"] == "WAREHOUSED"
        # PRD 3.3: assessed_fee_cents "remain unset until release".
        assert appended.get("assessed_fee_cents") is None

    def test_assessed_fee_uses_assigned_window_after_rollover(self, api):
        """PRD 3.4: "Otherwise the file falls to `NEXT_DAY`."
        PRD 3.4: "the `settlement_date` follows from it: today when a same-day
        window was assigned, or the next banking day when the file rolled to
        `NEXT_DAY`."
        PRD 3.4: "The assessed fee diverges from the quoted fee exactly when the
        requested window's cutoff was missed and the file rolled to another
        window."

        Design: Difficulty/dual_variant_calc/file_fee_quoted_vs_assessed_cutoff_rollover
        """
        appended = _setup_rollover_file()
        # Advance past the SAME_DAY_1 close (12:00); no other same-day window.
        set_clock("2026-08-03T13:00:00Z")
        released = release_file_ok(appended["id"])

        assert released["status"] == "RELEASED"
        assert released["assigned_window_kind"] == "NEXT_DAY"
        assert released["settlement_date"] == "2026-08-04"
        # NEXT_DAY card: rhu(60*.9667)=58, rhu(160*.9667)=155, 58; +200.
        assert released["assessed_fee_cents"] == 471
        assert released["quoted_fee_cents"] == 1_322
