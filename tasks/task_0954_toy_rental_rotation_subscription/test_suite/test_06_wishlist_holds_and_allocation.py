"""Wishlist capture rules, the allocation selector (rank then created_at, the
max_holds gate, copy availability), hold acceptance, and ops-run hold expiry
with re-promotion."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_item_to_box,
    assert_same_instant,
    assert_version_incremented,
    create_accept_hold_payload,
    create_catalog_item,
    create_next_box,
    create_wishlist_entry,
    create_wishlist_entry_payload,
    list_box_items,
    list_wishlist_entries,
    make_member_headers,
    mint_copy,
    ops_run,
    read_box,
    read_copy,
    read_wishlist_entry,
    set_clock,
    setup_held_entry_with_box,
    setup_member_with_subscription,
    validate_error,
    validate_success,
)


class TestWishlistCreateRules:
    def test_wishlist_create_on_retired_catalog_item_rejected(self, api):
        """PRD §3.2: "Retiring an item — a `PlatformAdmin` action allowed only
        while the item is `ACTIVE`, otherwise `ERR_INVALID_STATE` — moves it to
        `RETIRED`; existing wishlist entries and physical copies are
        unaffected, but any new wishlist entry naming the retired item is
        rejected with `ERR_CATALOG_ITEM_RETIRED` (HTTP 422)."

        Design: Corner/validations/wishlist_create_on_retired_catalog_item_rejected
        """
        ctx = setup_member_with_subscription(member_email="m.ret@x.com",
                                             with_child=False)
        member = ctx["member"]
        item = create_catalog_item(title="Old Toy", piece_count=4,
                                   retail_value_cents=3000,
                                   replacement_value_cents=2000)
        validate_success(api.retire_catalog_item(item["id"], ADMIN))

        resp = api.create_wishlist_entry(
            member["id"], create_wishlist_entry_payload(item["id"], 1),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CATALOG_ITEM_RETIRED.value, 422)
        assert list_wishlist_entries(member) == []

    def test_duplicate_waiting_entry_rejected_then_readd_after_cancel(self, api):
        """PRD §3.4: "One open entry per toy per member: a second `WAITING` or
        `HELD` entry for the same catalog item is rejected with
        `ERR_WISHLIST_DUPLICATE` (HTTP 409)"
        PRD §3.4: "A member may also cancel an entry outright while it is
        `WAITING` or `HELD` — any other state yields `ERR_INVALID_STATE`"

        Design: Corner/validations/wishlist_duplicate_waiting_entry_rejected
        """
        ctx = setup_member_with_subscription(member_email="m.dup@x.com",
                                             with_child=False)
        member = ctx["member"]
        headers = make_member_headers(member["id"])
        item = create_catalog_item(title="Xylophone", piece_count=6,
                                   retail_value_cents=5000, replacement_value_cents=4000)

        entry = create_wishlist_entry(member, item["id"], rank=1)
        assert entry["status"] == "WAITING"

        resp = api.create_wishlist_entry(
            member["id"], create_wishlist_entry_payload(item["id"], 2), headers)
        validate_error(resp, ApiErrorId.ERR_WISHLIST_DUPLICATE.value, 409)

        validate_success(api.cancel_wishlist_entry(entry["id"], headers))
        resp2 = api.create_wishlist_entry(
            member["id"], create_wishlist_entry_payload(item["id"], 3), headers)
        entry2 = validate_success(resp2, 201)
        assert entry2["status"] == "WAITING"
        assert entry2["id"] != entry["id"]


class TestSweepRequiresAvailableCopy:
    def _setup_reserved_copy_with_waiting_entry(self, api):
        item = create_catalog_item(title="Xylophone", piece_count=6,
                                   retail_value_cents=5000, replacement_value_cents=4000)
        c1 = mint_copy(item["id"], barcode="BC-XDEP-1")
        ctx_a = setup_member_with_subscription(member_email="m.xa@x.com")
        box_a = create_next_box(ctx_a["member"], ctx_a["subscription"]["id"])
        add_item_to_box(ctx_a["member"], box_a["id"], c1["id"])  # RESERVED to A
        ctx_b = setup_member_with_subscription(member_email="m.xb@x.com")
        entry_b = create_wishlist_entry(ctx_b["member"], item["id"], rank=1)
        return item, c1, ctx_a, ctx_b, entry_b

    def test_ops_run_promotes_nothing_when_no_copy_available(self, api):
        """PRD §3.4: "For each `AVAILABLE`, sanitization-valid copy — scanned
        in `created_at` ascending order — the candidate set is the `WAITING`
        entries for that copy's catalog item whose member holds an `ACTIVE`
        subscription, whose count of `HELD` entries is below the plan's
        `max_holds`, and for whom at least one child profile passes the
        calendar age gate."
        PRD §3.4: "When no candidate qualifies, the copy simply stays
        `AVAILABLE`."

        The only copy of the item is RESERVED inside another member's PLANNED
        box, so the sweep has no copy to promote against.

        Design: Difficulty/cross_entity_state_dependency/sweep_promotion_requires_available_copy
        """
        _, _, _, ctx_b, entry_b = self._setup_reserved_copy_with_waiting_entry(api)

        run = ops_run()
        assert run["promoted_count"] == 0
        assert run["promoted_entry_ids"] == []

        entry_now = read_wishlist_entry(ctx_b["member"], entry_b["id"])
        assert entry_now["status"] == "WAITING"
        assert entry_now["held_copy_id"] is None

    def test_reserved_copy_undisturbed_by_sweep(self, api):
        """PRD §3.4: "A sweep runs in targeted form whenever a copy returns to
        `AVAILABLE`, and globally during the operations checkpoint."
        PRD §3.4: "Promotion moves the entry `WAITING` → `HELD`, stamps
        `held_copy_id` with the chosen copy, sets `hold_expires_at` to exactly
        72 hours after the promotion instant, and moves the copy `AVAILABLE` →
        `RESERVED` with `reserved_member_id` naming the lucky member."

        With the sole copy RESERVED (never returning to AVAILABLE), the global
        run leaves both the copy and the waiting entry untouched.

        Design: Difficulty/cross_entity_state_dependency/sweep_promotion_requires_available_copy
        """
        _, c1, ctx_a, ctx_b, entry_b = self._setup_reserved_copy_with_waiting_entry(api)

        ops_run()

        copy_now = read_copy(c1["id"])
        assert copy_now["status"] == "RESERVED"
        assert copy_now["reserved_member_id"] == ctx_a["member"]["id"]
        assert read_wishlist_entry(ctx_b["member"], entry_b["id"])["status"] == "WAITING"


class TestSelectorDeterminism:
    def test_equal_ranks_break_by_earliest_created_at(self, api):
        """PRD §3.4: "The winner is the candidate with the lowest `rank`, ties
        broken by earliest `created_at`."
        PRD §3.9: "The run reports `promoted_count`, `expired_count`, and
        `resumed_count`, plus the `promoted_entry_ids` of the entries it
        promoted."

        Both entries carry rank 1; B's was created first, so B wins the only
        copy.

        Design: Corner/calculations/allocation_selector_rank_then_created_at_tiebreak
        """
        item = create_catalog_item(title="Xylophone", piece_count=6,
                                   retail_value_cents=5000, replacement_value_cents=4000)
        c1 = mint_copy(item["id"], barcode="BC-TIE-1")
        ctx_b = setup_member_with_subscription(
            plan_overrides={"max_holds": 5}, member_email="m.tb@x.com")
        entry_b = create_wishlist_entry(ctx_b["member"], item["id"], rank=1)
        ctx_c = setup_member_with_subscription(
            plan_overrides={"max_holds": 5}, member_email="m.tc@x.com")
        entry_c = create_wishlist_entry(ctx_c["member"], item["id"], rank=1)

        run = ops_run()
        assert run["promoted_count"] == 1
        assert run["promoted_entry_ids"] == [entry_b["id"]]

        entry_b_now = read_wishlist_entry(ctx_b["member"], entry_b["id"])
        assert entry_b_now["status"] == "HELD"
        assert entry_b_now["held_copy_id"] == c1["id"]
        assert read_wishlist_entry(ctx_c["member"], entry_c["id"])["status"] == "WAITING"

    def test_max_holds_gate_skips_member_in_sweep(self, api):
        """PRD §3.4: "For each `AVAILABLE`, sanitization-valid copy — scanned
        in `created_at` ascending order — the candidate set is the `WAITING`
        entries for that copy's catalog item whose member holds an `ACTIVE`
        subscription, whose count of `HELD` entries is below the plan's
        `max_holds`, and for whom at least one child profile passes the
        calendar age gate."

        With max_holds 1, member B's promotion on the first copy puts B at the
        cap, so the sweep skips B's second entry and the next eligible member
        wins the second copy.

        Design: Corner/calculations/max_holds_gate_skips_member_in_sweep
        """
        plan_kw = {"name": "TINYHOLD", "max_holds": 1}
        item_x = create_catalog_item(title="Xylophone", piece_count=6,
                                     retail_value_cents=5000, replacement_value_cents=4000)
        cx = mint_copy(item_x["id"], barcode="BC-MH-X")
        item_y = create_catalog_item(title="Yo-yo", piece_count=1,
                                     retail_value_cents=1000, replacement_value_cents=800)
        cy = mint_copy(item_y["id"], barcode="BC-MH-Y")

        ctx_b = setup_member_with_subscription(plan_overrides=plan_kw,
                                               member_email="m.mhb@x.com")
        entry_bx = create_wishlist_entry(ctx_b["member"], item_x["id"], rank=1)
        entry_by = create_wishlist_entry(ctx_b["member"], item_y["id"], rank=1)
        ctx_c = setup_member_with_subscription(plan_overrides=plan_kw,
                                               member_email="m.mhc@x.com")
        entry_cy = create_wishlist_entry(ctx_c["member"], item_y["id"], rank=2)

        run1 = ops_run()
        assert run1["promoted_count"] == 2
        assert set(run1["promoted_entry_ids"]) == {entry_bx["id"], entry_cy["id"]}

        # B is now at 1 HELD == max_holds 1, so B's Y-entry is ineligible.
        run2 = ops_run()
        assert run2["promoted_count"] == 0
        assert run2["promoted_entry_ids"] == []

        entry_bx_now = read_wishlist_entry(ctx_b["member"], entry_bx["id"])
        assert entry_bx_now["status"] == "HELD"
        assert entry_bx_now["held_copy_id"] == cx["id"]
        entry_by_now = read_wishlist_entry(ctx_b["member"], entry_by["id"])
        assert entry_by_now["status"] == "WAITING"
        assert entry_by_now["held_copy_id"] is None
        entry_cy_now = read_wishlist_entry(ctx_c["member"], entry_cy["id"])
        assert entry_cy_now["status"] == "HELD"
        assert entry_cy_now["held_copy_id"] == cy["id"]


class TestHoldAcceptance:
    def test_accept_hold_happy_path_creates_box_item(self, api):
        """PRD §3.4: "Acceptance moves the entry `HELD` → `FULFILLED` and
        creates a box item whose `toy_copy_id` is the held copy, which remains
        `RESERVED` — now backing the box slot rather than the hold — and the
        box's `version` increments by one."
        PRD §3.4: "Promotion moves the entry `WAITING` → `HELD`, stamps
        `held_copy_id` with the chosen copy, sets `hold_expires_at` to exactly
        72 hours after the promotion instant, and moves the copy `AVAILABLE` →
        `RESERVED` with `reserved_member_id` naming the lucky member."

        Design: Corner/endpoints/accept_hold_happy_path_creates_box_item
        """
        ctx = setup_held_entry_with_box(member_email="m.ahp@x.com",
                                        barcode="BC-AHP-1")
        member, entry, box, copy = (
            ctx["member"], ctx["entry"], ctx["box"], ctx["copy"])
        assert entry["status"] == "HELD"
        assert entry["held_copy_id"] == copy["id"]
        # Promotion happened at the default clock 2026-05-01T00:00:00Z + 72h.
        assert_same_instant(entry["hold_expires_at"], "2026-05-04T00:00:00Z",
                            "hold_expires_at")
        box_before = read_box(box["id"], member)

        accepted = validate_success(api.accept_hold(
            entry["id"], create_accept_hold_payload(box["id"]),
            make_member_headers(member["id"])))
        assert accepted["status"] == "FULFILLED"

        items = list_box_items(box["id"], member)
        assert len(items) == 1
        assert items[0]["toy_copy_id"] == copy["id"]
        assert items[0]["loan_status"] == "PENDING_RETURN"

        copy_now = read_copy(copy["id"])
        assert copy_now["status"] == "RESERVED"
        assert copy_now["reserved_member_id"] == member["id"]
        assert_version_incremented(read_box(box["id"], member)["version"],
                                   box_before["version"])

    def test_accept_hold_at_exact_expiry_rejected(self, api):
        """PRD §3.4: "the logical clock must be strictly before
        `hold_expires_at` — acceptance at or after the expiry instant fails
        with `ERR_HOLD_EXPIRED` (HTTP 409)"
        PRD §3.4: "The operations checkpoint expires any `HELD` entry whose
        `hold_expires_at` has been reached"

        The hold was promoted at the default clock (expiry 2026-05-04T00:00:00Z
        = +72h); at exactly that instant acceptance is already expired.  No
        checkpoint has run since, so the entry itself still reads HELD.

        Design: Corner/state_machines/hold_accept_at_exact_expiry_rejected
        """
        ctx = setup_held_entry_with_box(member_email="m.hex@x.com",
                                        barcode="BC-HEX-1")
        member, entry, box = ctx["member"], ctx["entry"], ctx["box"]
        assert_same_instant(entry["hold_expires_at"], "2026-05-04T00:00:00Z",
                            "hold_expires_at")

        set_clock("2026-05-04T00:00:00Z")
        resp = api.accept_hold(entry["id"], create_accept_hold_payload(box["id"]),
                               make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_HOLD_EXPIRED.value, 409)

        assert read_wishlist_entry(member, entry["id"])["status"] == "HELD"
        assert list_box_items(box["id"], member) == []


class TestOpsRunHoldExpiry:
    def test_ops_run_expires_stale_hold_and_repromotes_next_entry(self, api):
        """PRD §3.9: "It expires every `HELD` entry whose `hold_expires_at` has
        been reached, releasing each held copy and re-sweeping it for the next
        eligible entry."
        PRD §3.4: "The winner is the candidate with the lowest `rank`, ties
        broken by earliest `created_at`. Promotion moves the entry `WAITING` →
        `HELD`, stamps `held_copy_id` with the chosen copy, sets
        `hold_expires_at` to exactly 72 hours after the promotion instant, and
        moves the copy `AVAILABLE` → `RESERVED` with `reserved_member_id`
        naming the lucky member."

        Design: Corner/complexity_layers/ops_run_expires_stale_hold_and_repromotes
        """
        item = create_catalog_item(title="Xylophone", piece_count=6,
                                   retail_value_cents=5000, replacement_value_cents=4000)
        c1 = mint_copy(item["id"], barcode="BC-EXP-1")
        ctx_b = setup_member_with_subscription(member_email="m.expb@x.com")
        entry_b = create_wishlist_entry(ctx_b["member"], item["id"], rank=1)
        ctx_c = setup_member_with_subscription(member_email="m.expc@x.com")
        entry_c = create_wishlist_entry(ctx_c["member"], item["id"], rank=1)

        # Run 1 at the default clock: B wins the tie (created first).
        run1 = ops_run()
        assert run1["promoted_entry_ids"] == [entry_b["id"]]

        # Past B's expiry instant (2026-05-04T00:00:00Z).
        set_clock("2026-05-05T00:00:00Z")
        run2 = ops_run()
        assert run2["expired_count"] == 1
        assert run2["promoted_count"] == 1
        assert run2["promoted_entry_ids"] == [entry_c["id"]]

        assert read_wishlist_entry(ctx_b["member"], entry_b["id"])["status"] == "EXPIRED"
        entry_c_now = read_wishlist_entry(ctx_c["member"], entry_c["id"])
        assert entry_c_now["status"] == "HELD"
        assert entry_c_now["held_copy_id"] == c1["id"]
        # Re-promotion at clock 2026-05-05 + 72h.
        assert_same_instant(entry_c_now["hold_expires_at"], "2026-05-08T00:00:00Z",
                            "re-promoted hold_expires_at")

        copy_now = read_copy(c1["id"])
        assert copy_now["status"] == "RESERVED"
        assert copy_now["reserved_member_id"] == ctx_c["member"]["id"]
