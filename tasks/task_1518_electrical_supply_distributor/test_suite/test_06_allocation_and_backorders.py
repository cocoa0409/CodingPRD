"""Stock allocation, the backorder waterfall, and stock conservation under
allocate/cancel compensation."""
from test_helpers import (
    WH_MGR,
    allocate_release,
    api_client,
    assert_backorder_allocation,
    assert_stock_conserved,
    cancel_release,
    create_awarded_quote,
    create_contractor,
    create_foot_item,
    create_job_account,
    create_release,
    credit_approve_release,
    get_catalog_item,
    get_contractor,
    get_release,
    list_release_lines,
    receive_stock,
    setup_partially_allocated_release,
    setup_two_release_backorder_waterfall,
)


class TestPartialAllocation:

    def test_partial_allocation_creates_open_backorder(self):
        """PRD section 3.7: "When any line comes up short, the release becomes
        `PARTIALLY_ALLOCATED`: fully covered lines still transition to
        `ALLOCATED`, each short line remains `OPEN`, and the system creates an
        `OPEN` **BackorderAllocation** for every short line, recording its
        `release_line_id`, the line's `catalog_item_id` denormalized onto the
        backorder for the waterfall, and a `qty_open` equal to the unfilled
        remainder — the requested quantity minus what was allocated."

        Design: Difficulty/transitive_cascade/stock_receipt_fills_backorder_chain
        """
        ctx = setup_partially_allocated_release(stock_qty=100, request_qty=300)
        release = ctx["release"]
        assert release["status"] == "PARTIALLY_ALLOCATED"

        line = ctx["line"]
        assert line["qty_allocated"] == 100, (
            f"allocation takes the smaller of requested and on-hand, got "
            f"{line['qty_allocated']}")
        assert line["status"] == "OPEN", (
            f"the short line remains OPEN, got {line['status']}")

        backorder = ctx["backorder"]
        assert_backorder_allocation(backorder)
        assert backorder["qty_open"] == 200, (
            f"backorder covers the unfilled remainder 300 - 100 = 200, got "
            f"{backorder['qty_open']}")
        assert backorder["status"] == "OPEN"
        assert backorder["catalog_item_id"] == ctx["item"]["id"]
        assert backorder["release_line_id"] == line["id"]

        item = get_catalog_item(ctx["item"]["id"])
        assert item["stock_on_hand"] == 0
        assert item["stock_allocated"] == 100

    def test_stock_receipt_fills_backorder_and_completes_release(self):
        """PRD section 3.7: "A candidate whose `qty_open` reaches zero
        transitions to `FILLED`. A line whose `qty_allocated` reaches its
        `qty_requested` transitions `OPEN` → `ALLOCATED`. And when a release's
        last open backorder is filled so that every line is allocated, the
        release itself advances `PARTIALLY_ALLOCATED` → `ALLOCATED`."

        Design: Difficulty/transitive_cascade/stock_receipt_fills_backorder_chain
        """
        ctx = setup_partially_allocated_release(stock_qty=100, request_qty=300)
        receive_stock(ctx["item"]["id"], 200)

        backorder = api_client.get_backorder_allocation(
            ctx["backorder"]["id"], WH_MGR).json()["data"]
        assert backorder["status"] == "FILLED"
        assert backorder["qty_open"] == 0

        line = list_release_lines(ctx["release"]["id"])[0]
        assert line["qty_allocated"] == 300
        assert line["status"] == "ALLOCATED"

        release = get_release(ctx["release"]["id"])
        assert release["status"] == "ALLOCATED", (
            f"filling the last open backorder advances the release to "
            f"ALLOCATED, got {release['status']}")

        item = get_catalog_item(ctx["item"]["id"])
        assert item["stock_on_hand"] == 0
        assert item["stock_allocated"] == 300


class TestWaterfallOrdering:

    def test_waterfall_fills_oldest_release_first(self):
        """PRD section 3.7: "the system visits each `OPEN` BackorderAllocation
        for that item whose owning release is `PARTIALLY_ALLOCATED`, ordered
        by the owning release's `created_at` ascending and, within a release,
        by the release line's `created_at` ascending — never by identifier."

        Design: Corner/calculations/waterfall_fills_oldest_release_first
        """
        world = setup_two_release_backorder_waterfall()
        receive_stock(world["thhn"]["id"], 150)

        bo1 = api_client.get_backorder_allocation(world["bo1"]["id"], WH_MGR) \
            .json()["data"]
        assert bo1["status"] == "FILLED", (
            f"the older release's backorder fills first, got {bo1['status']}")
        assert bo1["qty_open"] == 0
        assert get_release(world["r1"]["id"])["status"] == "ALLOCATED"

        bo2 = api_client.get_backorder_allocation(world["bo2"]["id"], WH_MGR) \
            .json()["data"]
        assert bo2["status"] == "OPEN"
        assert bo2["qty_open"] == 50, (
            f"only 50 ft remain for the newer backorder, got "
            f"{bo2['qty_open']}")
        line2 = list_release_lines(world["r2"]["id"])[0]
        assert line2["qty_allocated"] == 50

        item = get_catalog_item(world["thhn"]["id"])
        assert item["stock_on_hand"] == 0


class TestAllocateCancelConservation:

    def _setup_allocated_60(self):
        contractor = create_contractor("Conserve Electric", 10_000_000)
        thhn = create_foot_item()
        receive_stock(thhn["id"], 100)
        job = create_job_account(contractor["id"], "Conserve Job",
                                 jobsite_address="22 Site Rd")
        quote = create_awarded_quote(job["id"], [(thhn["id"], 60, 45.25)])
        release = create_release(job["id"], quote["id"], [(thhn["id"], 60)])
        credit_approve_release(release["id"])
        release = allocate_release(release["id"])
        assert release["status"] == "ALLOCATED"
        return contractor, thhn, release

    def test_cancel_returns_allocated_stock(self):
        """PRD section 3.6: "From `PARTIALLY_ALLOCATED` or `ALLOCATED`, each
        line returns its `qty_allocated` to the item's `stock_on_hand`, the
        item's `stock_allocated` decreases by the same amount, each line —
        whether still `OPEN` or already `ALLOCATED` — transitions to
        `CANCELLED`, any `OPEN` backorder allocations of the release move to
        `CANCELLED`, and the committed estimate is released as above."

        Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_stock
        """
        contractor, thhn, release = self._setup_allocated_60()
        item = get_catalog_item(thhn["id"])
        assert item["stock_on_hand"] == 40
        assert item["stock_allocated"] == 60
        assert_stock_conserved(item, 100)

        cancelled = cancel_release(release["id"])
        assert cancelled["status"] == "CANCELLED"

        item = get_catalog_item(thhn["id"])
        assert item["stock_on_hand"] == 100, (
            f"cancel must return the 60 allocated feet, got on_hand "
            f"{item['stock_on_hand']}")
        assert item["stock_allocated"] == 0
        assert_stock_conserved(item, 100)

        line = list_release_lines(release["id"])[0]
        assert line["status"] == "CANCELLED"

    def test_cancel_releases_committed_balance(self):
        """PRD section 3.6: "From `CREDIT_APPROVED` the committed estimate is
        released: the contractor's `committed_balance_cents` decreases by
        `estimated_total_cents`."
        PRD section 2.6: "Balance mutations are immediate and atomic with the
        operations that cause them: credit approval commits a release's
        estimate, invoicing releases the commitment and posts the billed
        amount, cancellation releases the commitment, and a recorded payment
        reduces the invoiced balance."

        Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_stock
        """
        contractor, thhn, release = self._setup_allocated_60()
        estimate = release["estimated_total_cents"]
        committed = get_contractor(contractor["id"])
        assert committed["committed_balance_cents"] == estimate
        assert estimate > 0

        cancel_release(release["id"])
        after = get_contractor(contractor["id"])
        assert after["committed_balance_cents"] == 0, (
            f"cancel must release the committed estimate {estimate}, got "
            f"{after['committed_balance_cents']}")
        assert after["credit_used_cents"] == 0
