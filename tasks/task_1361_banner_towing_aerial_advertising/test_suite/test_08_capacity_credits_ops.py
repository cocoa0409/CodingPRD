"""Seasonal-capacity conservation, make-good credit conservation across
invoice issue/void, and the ops checkpoint that expires stale credits."""
from test_helpers import (
    book_slot_in,
    create_base,
    fly_slot,
    get_capacity,
    get_slot,
    issue_invoice,
    make_client_headers,
    set_clock,
    setup_operation,
    validate_success,
    weather_cancel_slot,
)
from test_helpers.fixtures import ADMIN, FINANCE


class TestSeasonalCapacityConservation:

    def test_book_then_cancel_restores_committed_hours(self, api):
        """PRD §2.8: "Both figures are recomputed on every transition that
        moves a slot into or out of the contributing set — booking consumes
        from the pool, and every cancellation of any flavor releases the
        slot's planned hours back to it."

        Booking a 3-hour slot commits 3 hours; cancelling it returns the
        committed figure to zero.

        Design: Difficulty/compensating_invariant/seasonal_capacity_conservation_on_book_cancel
        """
        sc = setup_operation(base_code="KCC1")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=3)
        after_book = get_capacity(sc["capacity"]["id"])
        assert after_book["hours_committed"] == 3, (
            f"booking must consume 3 hours, got {after_book['hours_committed']}"
        )
        validate_success(
            api.cancel_slot_by_client(slot["id"],
                                      make_client_headers(sc["client"]["id"])),
            expected_status=200)
        after_cancel = get_capacity(sc["capacity"]["id"])
        assert after_cancel["hours_committed"] == 0, (
            f"cancellation must release the same 3 hours, got "
            f"{after_cancel['hours_committed']}"
        )
        assert get_slot(slot["id"])["status"] == "CANCELLED_CLIENT"

    def test_hours_remaining_tracks_quota_minus_committed(self, api):
        """PRD §2.8: "The derived `hours_remaining` is the quota minus the
        committed hours." and "booking consumes from the pool, and every
        cancellation of any flavor releases the slot's planned hours back
        to it."

        Design: Difficulty/compensating_invariant/seasonal_capacity_conservation_on_book_cancel
        """
        sc = setup_operation(base_code="KCC2", quota=100)
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=3)
        after_book = get_capacity(sc["capacity"]["id"])
        assert after_book["hours_committed"] == 3
        assert after_book["hours_remaining"] == 97, (
            f"hours_remaining must be quota - committed = 97, got "
            f"{after_book['hours_remaining']}"
        )
        validate_success(
            api.cancel_slot_by_client(slot["id"],
                                      make_client_headers(sc["client"]["id"])),
            expected_status=200)
        after_cancel = get_capacity(sc["capacity"]["id"])
        assert after_cancel["hours_committed"] == 0
        assert after_cancel["hours_remaining"] == 100


class TestMakeGoodCreditConservationOnVoid:

    def test_partial_application_then_void_restores_credit(self, api):
        """PRD §3.8: "each credit in order applies the smaller of its
        `remaining_cents` and the pool not yet covered by previously applied
        credits; the applied amount accumulates into `make_good_applied_cents`,
        the credit's `remaining_cents` decreases by the same amount, and the
        credit lands in `FULLY_APPLIED` when its remainder reaches zero or
        `PARTIALLY_APPLIED` otherwise."
        PRD §3.8: "Voiding an invoice is the compensating action: the invoice
        moves to `VOID`, every make-good credit that was applied to it
        reverts — its `remaining_cents` restored and its status returning to
        `OPEN` or `PARTIALLY_APPLIED` as the restored remainder warrants".

        A 60,000-cent credit (2h weather-cancelled at 30,000c/h) faces a
        30,000-cent subtotal (1.0 FLOWN hour): 30,000 applies, the remainder
        sits at 30,000 as PARTIALLY_APPLIED, and voiding restores 60,000 OPEN.

        Design: Difficulty/compensating_invariant/make_good_credit_conservation_on_invoice_void
        """
        sc = setup_operation(base_code="KMGV1")
        s1 = book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                          planned_duration_hours=2)
        weather_cancel_slot(s1["id"], "2026-08-13T15:00:00Z")
        s2 = book_slot_in(sc, planned_start="2026-08-13T16:00:00Z",
                          planned_duration_hours=2)
        fly_slot(s2["id"], hobbs_out=100.0, hobbs_in=101.0)
        credits = validate_success(
            api.list_make_good_credits(sc["campaign"]["id"], ADMIN),
            expected_status=200)
        assert len(credits) == 1
        credit_id = credits[0]["id"]
        assert credits[0]["remaining_cents"] == 60000

        invoice = issue_invoice(sc["campaign"]["id"])
        assert invoice["make_good_applied_cents"] == 30000, (
            f"pool is 30000 subtotal + 0 penalty, credit must apply 30000, "
            f"got {invoice['make_good_applied_cents']}"
        )
        mid = validate_success(api.get_make_good_credit(credit_id, ADMIN),
                               expected_status=200)
        assert mid["remaining_cents"] == 30000
        assert mid["status"] == "PARTIALLY_APPLIED"

        validate_success(api.void_invoice(invoice["id"], FINANCE),
                         expected_status=200)
        restored = validate_success(api.get_make_good_credit(credit_id, ADMIN),
                                    expected_status=200)
        assert restored["remaining_cents"] == 60000, (
            f"void must restore the applied 30000, got "
            f"{restored['remaining_cents']}"
        )
        assert restored["status"] == "OPEN"

    def test_full_application_then_void_restores_credit(self, api):
        """PRD §3.8: "the credit lands in `FULLY_APPLIED` when its remainder
        reaches zero or `PARTIALLY_APPLIED` otherwise."
        PRD §3.8: "Voiding an invoice is the compensating action: the invoice
        moves to `VOID`, every make-good credit that was applied to it
        reverts — its `remaining_cents` restored and its status returning to
        `OPEN` or `PARTIALLY_APPLIED` as the restored remainder warrants".

        A 60,000-cent credit against a 90,000-cent subtotal (3.0 FLOWN
        hours) is fully consumed; voiding restores it to 60,000 OPEN.

        Design: Difficulty/compensating_invariant/make_good_credit_conservation_on_invoice_void
        """
        sc = setup_operation(base_code="KMGV2")
        s1 = book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                          planned_duration_hours=2)
        weather_cancel_slot(s1["id"], "2026-08-13T15:00:00Z")
        s2 = book_slot_in(sc, planned_start="2026-08-13T16:00:00Z",
                          planned_duration_hours=2)
        fly_slot(s2["id"], hobbs_out=100.0, hobbs_in=103.0)
        credits = validate_success(
            api.list_make_good_credits(sc["campaign"]["id"], ADMIN),
            expected_status=200)
        assert len(credits) == 1
        credit_id = credits[0]["id"]

        invoice = issue_invoice(sc["campaign"]["id"])
        assert invoice["flight_subtotal_cents"] == 90000
        assert invoice["make_good_applied_cents"] == 60000, (
            f"credit must be fully consumed against the 90000 pool, got "
            f"{invoice['make_good_applied_cents']}"
        )
        assert invoice["total_cents"] == 30000
        mid = validate_success(api.get_make_good_credit(credit_id, ADMIN),
                               expected_status=200)
        assert mid["remaining_cents"] == 0
        assert mid["status"] == "FULLY_APPLIED"

        validate_success(api.void_invoice(invoice["id"], FINANCE),
                         expected_status=200)
        restored = validate_success(api.get_make_good_credit(credit_id, ADMIN),
                                    expected_status=200)
        assert restored["remaining_cents"] == 60000
        assert restored["status"] == "OPEN"


class TestOpsCheckpoint:

    def test_run_ops_with_no_credits_expires_none(self, api):
        """PRD §3.8: "The checkpoint reports how many credits it expired in
        the `expired_credit_count` field and lists their identifiers in the
        `expired_credit_ids` field."

        With no credits on record for the base, the sweep expires none.

        Design: Corner/cross_cutting_layers/run_ops_expires_stale_make_good_credits
        """
        set_clock("2026-08-15T00:00:00Z")
        base = create_base(code="KOPS0", name="Quiet Field")
        resp = api.run_ops(base["id"], ADMIN)
        data = validate_success(resp, expected_status=200)
        assert data["expired_credit_count"] == 0
        assert data["expired_credit_ids"] == []

    def test_run_ops_expires_credit_past_freshness_window(self, api):
        """PRD §3.8: "A `PlatformAdmin` runs the periodic ops checkpoint for
        a base, which sweeps every credit still `OPEN` or `PARTIALLY_APPLIED`
        whose `expires_on_local` has fallen before the current local date and
        flips it to `EXPIRED`, recomputing each affected campaign's
        `unapplied_make_good_cents`."
        PRD §3.6: the credit's "`expires_on_local` falls exactly thirty days
        after the source slot's `date_local`".

        A credit born of a 2026-08-13 weather cancellation expires
        2026-09-12; with the clock at 2026-09-13 the checkpoint expires it.

        Design: Corner/cross_cutting_layers/run_ops_expires_stale_make_good_credits
        """
        sc = setup_operation(base_code="KOPS1")
        s1 = book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                          planned_duration_hours=2)
        weather_cancel_slot(s1["id"], "2026-08-13T15:00:00Z")
        credits = validate_success(
            api.list_make_good_credits(sc["campaign"]["id"], ADMIN),
            expected_status=200)
        assert len(credits) == 1
        credit_id = credits[0]["id"]
        assert credits[0]["status"] == "OPEN"
        assert credits[0]["expires_on_local"] == "2026-09-12"

        set_clock("2026-09-13T00:00:00Z")
        data = validate_success(api.run_ops(sc["base"]["id"], ADMIN),
                                expected_status=200)
        assert data["expired_credit_count"] == 1, (
            f"one stale credit must be expired, got "
            f"{data['expired_credit_count']}"
        )
        assert credit_id in data["expired_credit_ids"]
        after = validate_success(api.get_make_good_credit(credit_id, ADMIN),
                                 expected_status=200)
        assert after["status"] == "EXPIRED"
