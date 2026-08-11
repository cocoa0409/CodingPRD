"""Pre-shipment swaps: the allowance boundary, the transitive copy-release ->
sweep -> hold-promotion cascade, and active-slot conservation across a swap
pair."""

from test_helpers import (
    ApiErrorId,
    add_item_to_box,
    assert_active_slot_count,
    assert_same_instant,
    create_catalog_item,
    create_next_box,
    create_swap_payload,
    create_wishlist_entry,
    list_box_items,
    make_member_headers,
    mint_copy,
    read_box,
    read_box_item,
    read_copy,
    read_wishlist_entry,
    setup_member_with_subscription,
    validate_error,
    validate_success,
)


def _two_item_planned_box(api, member_email="m.inv2@x.com", plan_overrides=None):
    """Item X copies C1/C3 and item Y copy C2 (all NEW, age window [12, 36]);
    a PLANNED box holding C1 and C2; no wishlist entries exist."""
    ctx = setup_member_with_subscription(member_email=member_email,
                                         plan_overrides=plan_overrides)
    member = ctx["member"]
    item_x = create_catalog_item(title="Xylophone", piece_count=6,
                                 retail_value_cents=5000, replacement_value_cents=4000)
    c1 = mint_copy(item_x["id"], barcode="BC-INV2-X1")
    c3 = mint_copy(item_x["id"], barcode="BC-INV2-X3")
    item_y = create_catalog_item(title="Yo-yo", piece_count=1,
                                 retail_value_cents=1000, replacement_value_cents=800)
    c2 = mint_copy(item_y["id"], barcode="BC-INV2-Y2")
    box = create_next_box(member, ctx["subscription"]["id"])
    it_1 = add_item_to_box(member, box["id"], c1["id"])
    it_2 = add_item_to_box(member, box["id"], c2["id"])
    return {"ctx": ctx, "member": member, "item_x": item_x, "item_y": item_y,
            "c1": c1, "c2": c2, "c3": c3, "box": box, "it_1": it_1, "it_2": it_2}


class TestSwapAllowanceBoundary:
    def _swap1_setup(self, api):
        ctx = setup_member_with_subscription(
            plan_overrides={"name": "SWAP1", "toys_per_box": 1,
                            "swap_allowance_per_cycle": 1, "max_holds": 1},
            member_email="m.bnd2@x.com")
        member = ctx["member"]
        item = create_catalog_item(title="Stacking Rings", piece_count=5,
                                   retail_value_cents=3000,
                                   replacement_value_cents=2400)
        copies = [mint_copy(item["id"], barcode=f"BC-BND2-{n}") for n in (1, 2, 3)]
        box = create_next_box(member, ctx["subscription"]["id"])
        it_1 = add_item_to_box(member, box["id"], copies[0]["id"])
        return member, box, it_1, copies

    def test_last_legal_swap_at_allowance_minus_one(self, api):
        """PRD §3.5: "the box's `swap_count` must be below the plan's
        `swap_allowance_per_cycle` — when the count equals the allowance the
        swap fails with `ERR_SWAP_ALLOWANCE_EXCEEDED` (HTTP 422), so a count
        one below the allowance marks the last legal swap."

        With allowance 1, the swap at count 0 (< 1) is that last legal swap.

        Design: Difficulty/boundary_precision_check/swap_allowance_boundary
        """
        member, box, it_1, copies = self._swap1_setup(api)

        created = validate_success(api.swap_box_item(
            it_1["id"], create_swap_payload(copies[1]["id"]),
            make_member_headers(member["id"])), 201)
        assert created["loan_status"] == "PENDING_RETURN"
        assert created["toy_copy_id"] == copies[1]["id"]
        assert created["swapped_from_item_id"] == it_1["id"]

        box_now = read_box(box["id"], member)
        assert box_now["swap_count"] == 1
        assert read_box_item(it_1["id"], member)["loan_status"] == "SWAPPED_OUT"

    def test_swap_at_allowance_rejected(self, api):
        """PRD §3.5: "the box's `swap_count` must be below the plan's
        `swap_allowance_per_cycle` — when the count equals the allowance the
        swap fails with `ERR_SWAP_ALLOWANCE_EXCEEDED` (HTTP 422), so a count
        one below the allowance marks the last legal swap."

        After the first swap the count is 1 == allowance 1, so the second swap
        is rejected and nothing moves.

        Design: Difficulty/boundary_precision_check/swap_allowance_boundary
        """
        member, box, it_1, copies = self._swap1_setup(api)
        it_2 = validate_success(api.swap_box_item(
            it_1["id"], create_swap_payload(copies[1]["id"]),
            make_member_headers(member["id"])), 201)

        resp = api.swap_box_item(it_2["id"], create_swap_payload(copies[2]["id"]),
                                 make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_SWAP_ALLOWANCE_EXCEEDED.value, 422)

        assert read_box_item(it_2["id"], member)["loan_status"] == "PENDING_RETURN"
        assert read_copy(copies[2]["id"])["status"] == "AVAILABLE"
        assert read_box(box["id"], member)["swap_count"] == 1


class TestSwapReleasePromotesWaitingHold:
    def _cascade_setup(self, api):
        """Member A's PLANNED box holds copy C1 of item X; member B has a
        WAITING rank-1 entry on item X.  C2 (also item X) stays AVAILABLE
        because no allocation run has executed since it was minted."""
        item_x = create_catalog_item(title="Xylophone", piece_count=6,
                                     retail_value_cents=5000, replacement_value_cents=4000)
        c1 = mint_copy(item_x["id"], barcode="BC-SWP-X1")
        c2 = mint_copy(item_x["id"], barcode="BC-SWP-X2")
        item_y = create_catalog_item(title="Yo-yo", piece_count=1,
                                     retail_value_cents=1000, replacement_value_cents=800)
        c3 = mint_copy(item_y["id"], barcode="BC-SWP-Y3")

        ctx_a = setup_member_with_subscription(member_email="m.a@x.com")
        box_a = create_next_box(ctx_a["member"], ctx_a["subscription"]["id"])
        it_a1 = add_item_to_box(ctx_a["member"], box_a["id"], c1["id"])

        ctx_b = setup_member_with_subscription(member_email="m.b@x.com")
        entry_b = create_wishlist_entry(ctx_b["member"], item_x["id"], rank=1)
        return {"item_x": item_x, "item_y": item_y, "c1": c1, "c2": c2, "c3": c3,
                "ctx_a": ctx_a, "box_a": box_a, "it_a1": it_a1,
                "ctx_b": ctx_b, "entry_b": entry_b}

    def test_swap_retires_old_item_and_counts(self, api):
        """PRD §3.5: "A legal swap retires the old item to `SWAPPED_OUT`,
        creates the replacement item `PENDING_RETURN` with
        `swapped_from_item_id` pointing at the old item — members and operators
        can trace an item's swap chain through these links — increments
        `swap_count` and the box `version`, reserves the new copy, and releases
        the old copy `RESERVED` → `AVAILABLE`, whose targeted sweep may
        immediately promote a waiting wishlist entry."

        Design: Difficulty/transitive_cascade/swap_release_promotes_waiting_hold
        """
        s = self._cascade_setup(api)
        member_a = s["ctx_a"]["member"]

        it_new = validate_success(api.swap_box_item(
            s["it_a1"]["id"], create_swap_payload(s["c3"]["id"]),
            make_member_headers(member_a["id"])), 201)

        old = read_box_item(s["it_a1"]["id"], member_a)
        assert old["loan_status"] == "SWAPPED_OUT"
        assert it_new["swapped_from_item_id"] == s["it_a1"]["id"]
        assert it_new["loan_status"] == "PENDING_RETURN"
        assert it_new["toy_copy_id"] == s["c3"]["id"]
        assert read_box(s["box_a"]["id"], member_a)["swap_count"] == 1

    def test_swap_release_triggers_targeted_sweep_promotion(self, api):
        """PRD §2.11: "Whenever a reserved physical copy is released back to
        `AVAILABLE` — through a swap, a hold expiring or being cancelled, or
        the cancellation of a planned box — the release immediately triggers a
        targeted allocation sweep for that copy's catalog item (§3.4). A
        released copy is never left idle when eligible demand exists."
        PRD §3.5: "The cascade is transitive: swap, copy release, hold
        promotion."
        PRD §3.4: "Promotion moves the entry `WAITING` → `HELD`, stamps
        `held_copy_id` with the chosen copy, sets `hold_expires_at` to exactly
        72 hours after the promotion instant, and moves the copy `AVAILABLE` →
        `RESERVED` with `reserved_member_id` naming the lucky member."

        The swap releases C1; the targeted sweep re-reserves C1 under member B
        in the same request cascade, while C2 (never released) stays AVAILABLE.

        Design: Difficulty/transitive_cascade/swap_release_promotes_waiting_hold
        """
        s = self._cascade_setup(api)
        member_a, member_b = s["ctx_a"]["member"], s["ctx_b"]["member"]

        validate_success(api.swap_box_item(
            s["it_a1"]["id"], create_swap_payload(s["c3"]["id"]),
            make_member_headers(member_a["id"])), 201)

        # Links 2+3: release fired the sweep, which promoted B's entry onto C1.
        copy_c1 = read_copy(s["c1"]["id"])
        assert copy_c1["status"] == "RESERVED"
        assert copy_c1["reserved_member_id"] == member_b["id"]

        entry_now = read_wishlist_entry(member_b, s["entry_b"]["id"])
        assert entry_now["status"] == "HELD"
        assert entry_now["held_copy_id"] == s["c1"]["id"]
        # Promotion at the default clock 2026-05-01T00:00:00Z + 72h.
        assert_same_instant(entry_now["hold_expires_at"], "2026-05-04T00:00:00Z",
                            "hold_expires_at")

        copy_c3 = read_copy(s["c3"]["id"])
        assert copy_c3["status"] == "RESERVED"
        assert copy_c3["reserved_member_id"] == member_a["id"]
        # The sweep consumed exactly the released copy; C2 was never in play.
        assert read_copy(s["c2"]["id"])["status"] == "AVAILABLE"


class TestSwapSlotConservation:
    def test_swap_pair_preserves_active_slot_count(self, api):
        """PRD §3.5: "The box's slotted items — those with `loan_status`
        `PENDING_RETURN` — must number fewer than the plan's `toys_per_box`, or
        the add fails with `ERR_SLOT_CAPACITY_EXCEEDED`."
        PRD §3.5: "A legal swap retires the old item to `SWAPPED_OUT`, creates
        the replacement item `PENDING_RETURN` with `swapped_from_item_id`
        pointing at the old item"

        A swap pair (C1 -> C3, then C3 -> C1) retires one item and creates one
        item per hop, so the count of active (non-SWAPPED_OUT, non-CANCELLED)
        slots is invariant at 2.

        Design: Difficulty/compensating_invariant/swap_slot_conservation
        """
        s = _two_item_planned_box(api)
        member = s["member"]
        headers = make_member_headers(member["id"])

        it_3 = validate_success(api.swap_box_item(
            s["it_1"]["id"], create_swap_payload(s["c3"]["id"]), headers), 201)
        it_4 = validate_success(api.swap_box_item(
            it_3["id"], create_swap_payload(s["c1"]["id"]), headers), 201)

        items = list_box_items(s["box"]["id"], member)
        assert len(items) == 4
        active = assert_active_slot_count(items, 2)
        active_ids = {i["id"] for i in active}
        assert active_ids == {s["it_2"]["id"], it_4["id"]}

        swapped_out = [i for i in items if i["loan_status"] == "SWAPPED_OUT"]
        assert {i["id"] for i in swapped_out} == {s["it_1"]["id"], it_3["id"]}
        assert read_box_item(it_3["id"], member)["swapped_from_item_id"] == s["it_1"]["id"]
        assert read_box_item(it_4["id"], member)["swapped_from_item_id"] == it_3["id"]

    def test_swap_pair_counts_copies_and_box_state(self, api):
        """PRD §3.5: "A legal swap retires the old item to `SWAPPED_OUT`,
        creates the replacement item `PENDING_RETURN` with
        `swapped_from_item_id` pointing at the old item — members and operators
        can trace an item's swap chain through these links — increments
        `swap_count` and the box `version`, reserves the new copy, and releases
        the old copy `RESERVED` → `AVAILABLE`, whose targeted sweep may
        immediately promote a waiting wishlist entry."
        PRD §3.5: "While the box is still `PLANNED`, the member may swap a
        slotted copy for a different one by naming a `new_toy_copy_id`."

        After the pair, swap_count is 2, the twice-cycled C1 is RESERVED to the
        member again, and the box never left PLANNED.

        Design: Difficulty/compensating_invariant/swap_slot_conservation
        """
        s = _two_item_planned_box(api)
        member = s["member"]
        headers = make_member_headers(member["id"])

        it_3 = validate_success(api.swap_box_item(
            s["it_1"]["id"], create_swap_payload(s["c3"]["id"]), headers), 201)
        validate_success(api.swap_box_item(
            it_3["id"], create_swap_payload(s["c1"]["id"]), headers), 201)

        box_now = read_box(s["box"]["id"], member)
        assert box_now["swap_count"] == 2
        assert box_now["status"] == "PLANNED"

        copy_c1 = read_copy(s["c1"]["id"])
        assert copy_c1["status"] == "RESERVED"
        assert copy_c1["reserved_member_id"] == member["id"]
        # C2 still occupies its slot; C3 was released by the second swap and,
        # with no wishlist demand, stays AVAILABLE.  No copy left the pool.
        assert read_copy(s["c2"]["id"])["status"] == "RESERVED"
        assert read_copy(s["c3"]["id"])["status"] == "AVAILABLE"
        for copy in (s["c1"], s["c2"], s["c3"]):
            assert read_copy(copy["id"])["status"] not in ("LOST", "SOLD", "QUARANTINED")
