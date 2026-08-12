"""Lien release coordination: dual-variant effective payoff, the depth-3
record cascade, quote windows, and release terminal lockdown (PRD §3.4, §2.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_lien,
    assert_lien_release,
    complete_title_search,
    file_release,
    get_escrow_file,
    get_lien,
    lien_by_amount,
    liens_for_file,
    make_finding,
    make_lender_headers,
    order_title_search,
    quote_release_flat,
    quote_release_per_diem,
    receive_release,
    record_release,
    request_lien_release,
    set_clock,
    setup_basic_file,
    setup_file_with_lien,
    setup_lien_release_filed,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestEffectivePayoffDualVariant:
    def _setup_two_liens(self, api):
        """One file, two liens (500,000 FAA_RECORDED; 800,000 IR_INTEREST),
        releases quoted FLAT and PER_DIEM 5,000/day at 2026-06-01, both FILED."""
        ctx = setup_basic_file(
            with_lender=True,
            aircraft_overrides={"n_number": "N200PA", "serial_number": "S-200",
                                "is_international_registry": True},
            file_overrides={"purchase_price_cents": 5_000_000},
        )
        lender = ctx["lender"]
        search = order_title_search(ctx["file"]["id"])
        complete_title_search(search["id"], [
            make_finding(lender["id"], 500_000, filed_at="2025-03-01"),
            make_finding(lender["id"], 800_000, lien_type="IR_INTEREST",
                         filed_at="2025-04-01", ir_registered_at="2025-04-02"),
        ])
        lien_flat = lien_by_amount(ctx["file"]["id"], 500_000)
        lien_diem = lien_by_amount(ctx["file"]["id"], 800_000)

        rel_flat = request_lien_release(lien_flat["id"])
        rel_diem = request_lien_release(lien_diem["id"])
        quote_release_flat(rel_flat["id"], lender["id"], 500_000, "2026-06-30")
        quote_release_per_diem(rel_diem["id"], lender["id"], 500_000, 5_000,
                               "2026-06-30")
        set_clock("2026-06-10T00:00:00Z")
        receive_release(rel_flat["id"], lender["id"])
        receive_release(rel_diem["id"], lender["id"])
        file_release(rel_flat["id"])
        file_release(rel_diem["id"])
        ctx.update({"lien_flat": lien_flat, "lien_diem": lien_diem,
                    "rel_flat": rel_flat, "rel_diem": rel_diem})
        return ctx

    def test_flat_payoff_ignores_elapsed_days(self, api):
        """PRD §3.4: "For a `FLAT` quote, the effective payoff is simply
        `quoted_payoff_cents`, regardless of the record date."
        PRD §3.4: "The frozen payoff becomes the lien's `amount_paid_cents`; the
        lien's `outstanding_cents` becomes `original_amount_cents` minus
        `amount_paid_cents`."

        Design: Difficulty/dual_variant_calc/d2_payoff_flat_vs_per_diem
        """
        ctx = self._setup_two_liens(api)
        record_release(ctx["rel_flat"]["id"])
        lien = get_lien(ctx["lien_flat"]["id"])
        assert lien["status"] == "RELEASED"
        assert lien["amount_paid_cents"] == 500_000
        assert lien["outstanding_cents"] == 0

    def test_per_diem_payoff_accrues_whole_days(self, api):
        """PRD §3.4: "For a `PER_DIEM` quote, the effective payoff is
        `quoted_payoff_cents` plus `per_diem_cents` multiplied by the number of
        whole days elapsed between `quote_date` and the record date, but capped so
        the elapsed-day count never exceeds the number of whole days between
        `quote_date` and `good_through_date`."

        9 whole days from 2026-06-01 to 2026-06-10 x 5,000 -> 545,000 frozen;
        outstanding 800,000 - 545,000 = 255,000. Identical quote base and dates
        as the FLAT leg, different frozen payoff.

        Design: Difficulty/dual_variant_calc/d2_payoff_flat_vs_per_diem
        """
        ctx = self._setup_two_liens(api)
        record_release(ctx["rel_diem"]["id"])
        lien = get_lien(ctx["lien_diem"]["id"])
        assert lien["status"] == "RELEASED"
        assert lien["amount_paid_cents"] == 545_000
        assert lien["outstanding_cents"] == 255_000


class TestRecordCascadeToCleared:
    def _setup_filed_release(self, api):
        return setup_lien_release_filed(
            amount_cents=500_000, quoted_payoff_cents=500_000,
            good_through_date="2026-06-30",
            file_overrides={"purchase_price_cents": 5_000_000},
        )

    def test_record_releases_lien_and_freezes_payoff(self, api):
        """PRD §3.4: "The lien transitions from `RELEASE_PENDING` to `RELEASED`,
        the file's posture is recomputed, and a file in `SEARCH_COMPLETE` whose
        posture flips to `READY` automatically bubbles to `CLEARED` — and from
        there to `FUNDED` if the funding threshold is already met."
        PRD §3.4: "An `EscrowOfficer` then files the release with the registry
        (`RELEASE_RECEIVED` to `FILED`) and, once the registry confirms, records
        it (`FILED` to `RECORDED`)."

        Design: Difficulty/transitive_cascade/cas_a_release_record_to_cleared
        """
        ctx = self._setup_filed_release(api)
        assert ctx["release"]["status"] == "FILED"
        recorded = record_release(ctx["release"]["id"])
        assert_lien_release(recorded)
        assert recorded["status"] == "RECORDED"

        lien = get_lien(ctx["lien"]["id"])
        assert lien["status"] == "RELEASED"
        assert lien["amount_paid_cents"] == 500_000

    def test_record_bubbles_file_search_complete_to_cleared(self, api):
        """PRD §2.9: "Posture is recomputed on every event that could change it:
        lien discovery, dispute, dispute-resolution, release voiding, release
        recording, trust acceptance, and trust expiry."
        PRD §2.9: "When a recompute flips a file in `SEARCH_COMPLETE` to `READY`,
        the file automatically bubbles up to `CLEARED`."

        Design: Difficulty/transitive_cascade/cas_a_release_record_to_cleared
        """
        ctx = self._setup_filed_release(api)
        before = ctx["file"]
        assert before["status"] == "SEARCH_COMPLETE"
        assert before["posture"] == "LIEN_BLOCKED"

        record_release(ctx["release"]["id"])
        after = get_escrow_file(ctx["file"]["id"])
        assert after["posture"] == "READY"
        assert after["status"] == "CLEARED"


class TestQuoteWindow:
    def _setup_quoted_release(self, api):
        ctx = setup_file_with_lien(amount_cents=500_000, filed_at="2025-03-01",
                                   file_overrides={"purchase_price_cents": 5_000_000})
        release = request_lien_release(ctx["lien"]["id"])
        quote_release_flat(release["id"], ctx["lender"]["id"], 500_000, "2026-06-30")
        ctx["release"] = release
        return ctx

    def test_second_release_rejected_inside_and_on_window_end(self, api):
        """PRD §3.4: "A release cannot be requested while another release on the
        same lien is in `QUOTED` with a quote window — the closed interval from
        `quote_date` through `good_through_date`, inclusive on both ends — that
        still covers today's logical date; that attempt is rejected with
        `ERR_QUOTE_WINDOW_OPEN`."

        2026-06-10 is inside the window; 2026-06-30 is the inclusive last day —
        both rejected.

        Design: Difficulty/resource_temporal_overlap/t2_lien_quote_window
        """
        ctx = self._setup_quoted_release(api)
        lien_id = ctx["lien"]["id"]

        set_clock("2026-06-10T00:00:00Z")
        mid = api.request_lien_release(lien_id, OFFICER)
        validate_error(mid, ApiErrorId.ERR_QUOTE_WINDOW_OPEN, expected_status=409)

        set_clock("2026-06-30T12:00:00Z")
        edge = api.request_lien_release(lien_id, OFFICER)
        validate_error(edge, ApiErrorId.ERR_QUOTE_WINDOW_OPEN, expected_status=409)

    def test_window_frees_one_day_after_good_through(self, api):
        """PRD §2.4: "A `LienRelease` in `QUOTED` whose `good_through_date` is
        strictly earlier than the new logical date transitions to
        `QUOTE_EXPIRED`."
        PRD §3.4: "Either path — `VOIDED` or `QUOTE_EXPIRED` — leaves the lien
        without an active release, and a `RELEASE_PENDING` lien in that position
        returns automatically to `DISCOVERED`, recomputing posture as it goes."
        PRD §3.4: "An `EscrowOfficer` requests release coordination on a
        `DISCOVERED` lien. The new `LienRelease` begins in `REQUESTED`, and the
        lien automatically transitions from `DISCOVERED` to `RELEASE_PENDING`."

        Design: Difficulty/resource_temporal_overlap/t2_lien_quote_window
        """
        ctx = self._setup_quoted_release(api)
        lien_id = ctx["lien"]["id"]

        set_clock("2026-07-01T00:00:00Z")
        lien = get_lien(lien_id)
        assert lien["status"] == "DISCOVERED"

        fresh = validate_success(api.request_lien_release(lien_id, OFFICER), 201)
        assert fresh["status"] == "REQUESTED"
        assert get_lien(lien_id)["status"] == "RELEASE_PENDING"


class TestPayoffRecordOnGoodThrough:
    def test_record_on_good_through_date_succeeds_with_capped_days(self, api):
        """PRD §3.4: "Recording is gated on the logical date being on or before
        `good_through_date`, inclusive — a release whose window has already passed
        will already have been swept to `QUOTE_EXPIRED` and the transition does
        not exist."
        PRD §3.4: "For a `PER_DIEM` quote, the effective payoff is
        `quoted_payoff_cents` plus `per_diem_cents` multiplied by the number of
        whole days elapsed between `quote_date` and the record date, but capped so
        the elapsed-day count never exceeds the number of whole days between
        `quote_date` and `good_through_date`."

        Quote 2026-06-01, record 2026-06-30: min(29, 29) = 29 days ->
        500,000 + 5,000 x 29 = 645,000.

        Design: Corner/calculations/c_payoff_record_on_good_through
        """
        ctx = setup_lien_release_filed(
            amount_cents=700_000, payoff_basis="PER_DIEM",
            quoted_payoff_cents=500_000, per_diem_cents=5_000,
            good_through_date="2026-06-30",
            file_overrides={"purchase_price_cents": 5_000_000},
        )
        set_clock("2026-06-30T23:59:59Z")
        recorded = record_release(ctx["release"]["id"])
        assert recorded["status"] == "RECORDED"
        lien = get_lien(ctx["lien"]["id"])
        assert lien["amount_paid_cents"] == 645_000


class TestReleaseTerminalLockdown:
    def test_record_twice_rejected_and_payoff_unchanged(self, api):
        """PRD §3.4: "An `EscrowOfficer` then files the release with the registry
        (`RELEASE_RECEIVED` to `FILED`) and, once the registry confirms, records
        it (`FILED` to `RECORDED`)."
        PRD §3.4: "Recording is the moment the effective payoff freezes onto the
        lien."

        RECORDED is terminal: a second record has no defined transition and fails
        as an invalid state-machine transition; the frozen payoff does not move.

        Design: Corner/state_machines/s_record_twice_returns_invalid_transition
        """
        ctx = setup_lien_release_filed(
            amount_cents=500_000, quoted_payoff_cents=500_000,
            good_through_date="2026-06-30",
            file_overrides={"purchase_price_cents": 5_000_000},
        )
        record_release(ctx["release"]["id"])
        second = api.record_release(ctx["release"]["id"], OFFICER)
        validate_error(second, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)
        lien = get_lien(ctx["lien"]["id"])
        assert lien["amount_paid_cents"] == 500_000
