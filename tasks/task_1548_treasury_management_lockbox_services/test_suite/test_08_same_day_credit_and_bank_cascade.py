"""Same-day credit provisional-vs-final reads, and the bank suspension
cascade through sites to batches."""
from test_helpers import (
    TEST_USERS,
    accept_item,
    balance_batch_ok,
    begin_capture,
    capture_item,
    close_batch,
    create_batch,
    get_batch,
    set_clock,
    setup_live_lockbox,
    validate_success,
)

ADMIN = TEST_USERS["bank_admin_headers"]


def _setup_batch_first_item_accepted():
    """LIVE site with a SAME_DAY schedule; batch of two items (5000c and
    10000c) in CAPTURING with only the first item accepted."""
    set_clock("2026-08-01T13:00:00Z")
    ws = setup_live_lockbox()
    batch = create_batch(ws, batch_reference="B-1",
                         received_at="2026-08-01T13:00:00Z",
                         declared_item_count=2, declared_total_cents=15000)
    begin_capture(ws, batch["id"], operator_id="lock-op-1")
    item1 = capture_item(ws, batch["id"], check_number="101",
                         payer_routing_number="071000288", amount_cents=5000)
    item2 = capture_item(ws, batch["id"], check_number="102",
                         payer_routing_number="071000288", amount_cents=10000)
    accept_item(ws, batch["id"], item1["id"])
    return ws, batch, item1, item2


class TestSameDayCreditVariants:
    def test_provisional_same_day_credit_reflects_accepted_so_far(self, api):
        """PRD §3.4: "The batch's `same_day_credit_cents` is recomputed on
        every acceptance rather than cached: while the batch is still being
        worked it is provisional and reflects only items accepted so far, and
        it freezes for good when capture closes — the frozen figure is what the
        ledger credit uses at settlement."
        PRD §3.4: "Acceptance assigns the item's `availability_tier` and
        `availability_date`, grows the batch's `accepted_item_count` by one and
        `accepted_total_cents` by `amount_cents`, and — when the tier is
        `SAME_DAY` — adds `amount_cents` to the batch's `same_day_credit_cents`."

        Design: Difficulty/dual_variant_calc/same_day_credit_provisional_vs_final_on_batch
        """
        ws, batch, _i1, _i2 = _setup_batch_first_item_accepted()
        provisional = get_batch(ws, batch["id"])
        assert provisional["capture_status"] == "CAPTURING"
        assert provisional["accepted_item_count"] == 1
        assert provisional["same_day_credit_cents"] == 5000, (
            "Provisional read must reflect only the item accepted so far"
        )

    def test_final_same_day_credit_frozen_at_close(self, api):
        """PRD §3.4: "The batch's `same_day_credit_cents` is recomputed on
        every acceptance rather than cached: while the batch is still being
        worked it is provisional and reflects only items accepted so far, and
        it freezes for good when capture closes — the frozen figure is what the
        ledger credit uses at settlement."

        Design: Difficulty/dual_variant_calc/same_day_credit_provisional_vs_final_on_batch
        """
        ws, batch, _i1, item2 = _setup_batch_first_item_accepted()
        accept_item(ws, batch["id"], item2["id"])
        balance_batch_ok(ws, batch["id"])
        closed = close_batch(ws, batch["id"], operator_id="lock-op-2")
        assert closed["capture_status"] == "CLOSED"
        final = get_batch(ws, batch["id"])
        assert final["capture_status"] == "CLOSED"
        assert final["same_day_credit_cents"] == 15000, (
            "Both SAME_DAY items are in the frozen figure at close"
        )
        assert final["accepted_item_count"] == 2
        assert final["batch_status"] == "READY_TO_SETTLE"


class TestBankSuspendCascade:
    def _setup_capturing_batch(self):
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=1,
                             declared_total_cents=1000)
        begin_capture(ws, batch["id"], operator_id="lock-op-1")
        return ws, batch

    def test_bank_suspend_cascades_to_sites_and_batches(self, api):
        """PRD §3.1: "Suspending the bank moves `OPERATING → SUSPENDED` and
        cascades immediately: every `LIVE` LockboxSite drops to `SUSPENDED`,
        every RemittanceBatch still in `CAPTURING` or `BALANCED` becomes `HELD`
        through compound-status recompute, and no new batches or image
        retrieval requests are accepted anywhere in the bank while the
        suspension holds."

        Design: Difficulty/transitive_cascade/bank_suspend_cascades_to_batch_held_depth3
        """
        ws, batch = self._setup_capturing_batch()
        bank = validate_success(api.suspend_bank(ws["bank"]["id"], ADMIN))
        assert bank["posture"] == "SUSPENDED"
        site = validate_success(api.get_site(
            ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
            ws["site"]["id"], ADMIN))
        assert site["status"] == "SUSPENDED", "Site cascade link must fire"
        after = get_batch(ws, batch["id"])
        assert after["batch_status"] == "HELD", (
            "The batch compound status must recompute to HELD via the cascade"
        )

    def test_bank_resume_restores_cascade_suspended_sites(self, api):
        """PRD §3.1: "Resuming moves `SUSPENDED → OPERATING`, but only while no
        `CONFIRMED` SLA incident has been left unresolved for more than thirty
        days; the sites that the suspension cascade took down return to
        `LIVE`."

        Design: Difficulty/transitive_cascade/bank_suspend_cascades_to_batch_held_depth3
        """
        ws, _batch = self._setup_capturing_batch()
        validate_success(api.suspend_bank(ws["bank"]["id"], ADMIN))
        bank = validate_success(api.resume_bank(ws["bank"]["id"], ADMIN))
        assert bank["posture"] == "OPERATING"
        site = validate_success(api.get_site(
            ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
            ws["site"]["id"], ADMIN))
        assert site["status"] == "LIVE", (
            "Sites taken down by the suspension cascade must return to LIVE"
        )
