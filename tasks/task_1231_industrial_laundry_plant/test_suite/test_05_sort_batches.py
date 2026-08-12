"""Sort batch workflows: classification schema, lock-time reject rate and
alert threshold, immediate derived values, void/unlock guards, and the piece
conservation invariant."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_sort_batch,
    setup_stop_received, create_batch, create_batch_with_items,
    get_sort_batch, set_par_level, get_on_site_pieces,
    stage_wash_load,
)

OPERATOR = TEST_USERS["plant_operator_headers"]


def _ctx_with_batch(plant_alert_pct=25.0, pieces_accepted=3, pieces_rejected=1,
                    reject_reason="STAIN"):
    """Pipeline through cart receive plus an OPEN batch with the given rows."""
    ctx = setup_stop_received(
        plant_overrides={"reject_rate_alert_pct": plant_alert_pct},
        stop_overrides={"declared_soiled_weight_lb": 10.0},
        carts=[{"cart_tag": "CART-1", "scale_weight_lb": 10.0}],
    )
    items = []
    if pieces_accepted:
        items.append({
            "category_id": ctx["category"]["id"],
            "pieces": pieces_accepted,
            "disposition": "ACCEPTED",
        })
    if pieces_rejected:
        items.append({
            "category_id": ctx["category"]["id"],
            "pieces": pieces_rejected,
            "disposition": "REJECTED",
            "reject_reason": reject_reason,
        })
    ctx["batch"] = create_batch_with_items(ctx["stop"]["id"], items)
    return ctx


class TestSortItemSchema:
    def test_reject_reason_forbidden_on_accepted(self, api):
        """PRD §3.3: "Supplying a `reject_reason` on an accepted row, or omitting it on a rejected row, is a schema violation rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/sort_item_reject_reason_forbidden_on_accepted
        """
        ctx = setup_stop_received()
        batch = create_batch(ctx["stop"]["id"])
        resp = api.create_sort_item(
            batch["id"],
            {
                "category_id": ctx["category"]["id"],
                "pieces": 5,
                "disposition": "ACCEPTED",
                "reject_reason": "STAIN",
            },
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLockPreconditions:
    def test_lock_empty_batch_rejected(self, api):
        """PRD §3.3: "The move from `OPEN` to `LOCKED` requires at least one sorted piece — locking an empty batch fails with `ERR_EMPTY_SORT_BATCH` — and requires the parent stop to be past pickup, that is in `PICKED_UP`, `DELIVERED`, or `DISPUTED`, failing otherwise with `ERR_STOP_NOT_PICKED_UP`."

        Design: Corner/state_machines/sort_batch_lock_empty_rejected
        """
        ctx = setup_stop_received()
        batch = create_batch(ctx["stop"]["id"])
        resp = api.lock_sort_batch(batch["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_EMPTY_SORT_BATCH)


class TestRejectRateThreshold:
    def test_rate_exactly_at_threshold_raises_alert(self, api):
        """PRD §3.3: "At lock time the batch's `reject_rate_pct` is computed: zero when `total_sorted_pieces` is zero, otherwise the rejected pieces divided by the total sorted pieces, multiplied by 100, and rounded half-up to 2 decimal places. The alert flag `alert_raised` is then set to true exactly when the computed reject rate is greater than or equal to the plant's `reject_rate_alert_pct` — a rate landing exactly on the threshold raises the alert."

        Design: Difficulty/boundary_precision_check/reject_rate_exactly_at_threshold_raises_alert
        """
        ctx = _ctx_with_batch(pieces_accepted=3, pieces_rejected=1)
        resp = api.lock_sort_batch(ctx["batch"]["id"], OPERATOR)
        data = validate_success(resp, 200)
        assert_sort_batch(data)
        assert data["status"] == "LOCKED"
        assert data["reject_rate_pct"] == 25.0, (
            f"1 of 4 rejected must be 25.00%%, got {data['reject_rate_pct']}"
        )
        assert data["alert_raised"] is True, (
            "a rate exactly equal to the 25.0 threshold must raise the alert"
        )

    def test_rate_below_threshold_does_not_raise_alert(self, api):
        """PRD §3.3: "The alert flag `alert_raised` is then set to true exactly when the computed reject rate is greater than or equal to the plant's `reject_rate_alert_pct` — a rate landing exactly on the threshold raises the alert."

        Design: Difficulty/boundary_precision_check/reject_rate_exactly_at_threshold_raises_alert
        """
        ctx = _ctx_with_batch(pieces_accepted=4, pieces_rejected=1,
                              reject_reason="TEAR")
        data = validate_success(api.lock_sort_batch(ctx["batch"]["id"], OPERATOR), 200)
        assert data["reject_rate_pct"] == 20.0, (
            f"1 of 5 rejected must be 20.00%%, got {data['reject_rate_pct']}"
        )
        assert data["alert_raised"] is False, (
            "a 20.00% rate is below the 25.0 threshold and must not alert"
        )


class TestImmediateConsistency:
    def test_lock_response_carries_computed_values(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.3: "At lock time the batch's `reject_rate_pct` is computed: zero when `total_sorted_pieces` is zero, otherwise the rejected pieces divided by the total sorted pieces, multiplied by 100, and rounded half-up to 2 decimal places."

        Design: Corner/consistency_model/immediate_visibility_of_cascade_effects
        """
        ctx = _ctx_with_batch(pieces_accepted=3, pieces_rejected=1)
        data = validate_success(api.lock_sort_batch(ctx["batch"]["id"], OPERATOR), 200)
        assert data["status"] == "LOCKED"
        assert data["reject_rate_pct"] == 25.0
        assert data["alert_raised"] is True


class TestVoidGuards:
    def test_void_batch_with_wash_load_rejected(self, api):
        """PRD §3.3: "Voiding abandons an `OPEN` batch entirely, moving it to `VOIDED` and discarding all of its sort items with the batch counters zeroed; voiding carries the same wash-load guard and fails with `ERR_BATCH_HAS_WASH_LOADS` when a load already exists."

        Design: Corner/errors/error_batch_has_wash_loads_on_void
        """
        ctx = _ctx_with_batch(pieces_accepted=10, pieces_rejected=0)
        stage_wash_load(ctx["batch"]["id"], ctx["category"]["id"])
        resp = api.void_sort_batch(ctx["batch"]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_BATCH_HAS_WASH_LOADS)


class TestVoidConservation:
    def test_void_open_batch_leaves_on_site_unchanged(self, api):
        """PRD §3.3: "And for each category, the customer par row's `current_on_site_pieces` is decremented by that category's accepted piece count: soiled linen acknowledged at sort time has left the customer site, and the on-site ledger must reflect it."
        PRD §3.5: "Posting deliberately does not modify `CustomerParLevel.current_on_site_pieces` — the on-site counter moves only when a delivery is marked delivered at the customer site."
        PRD §3.3: "Voiding abandons an `OPEN` batch entirely, moving it to `VOIDED` and discarding all of its sort items with the batch counters zeroed"

        Design: Difficulty/compensating_invariant/sort_batch_void_restores_piece_conservation
        """
        ctx = setup_stop_received(
            customer_overrides={"billing_mode": "RENTAL"},
            stop_overrides={"declared_soiled_weight_lb": 4.5},
            carts=[{"cart_tag": "CART-1", "scale_weight_lb": 4.5}],
        )
        set_par_level(ctx["customer"]["id"], ctx["category"]["id"], 10)
        batch = create_batch_with_items(ctx["stop"]["id"], [
            {"category_id": ctx["category"]["id"], "pieces": 7,
             "disposition": "ACCEPTED"},
            {"category_id": ctx["category"]["id"], "pieces": 2,
             "disposition": "REJECTED", "reject_reason": "TEAR"},
        ])
        pre = get_sort_batch(batch["id"])
        assert pre["total_sorted_pieces"] == 9
        assert pre["accepted_pieces"] + pre["rejected_pieces"] == pre["total_sorted_pieces"], (
            "accepted + rejected must equal total before void"
        )
        on_site_pre = get_on_site_pieces(ctx["customer"]["id"], ctx["category"]["id"])

        voided = validate_success(api.void_sort_batch(batch["id"], OPERATOR), 200)
        assert voided["status"] == "VOIDED"
        on_site_post = get_on_site_pieces(ctx["customer"]["id"], ctx["category"]["id"])
        assert on_site_post == on_site_pre, (
            f"voiding an OPEN batch must not move on-site pieces "
            f"({on_site_pre} -> {on_site_post})"
        )

    def test_void_zeroes_counters_and_discards_items(self, api):
        """PRD §3.3: "Voiding abandons an `OPEN` batch entirely, moving it to `VOIDED` and discarding all of its sort items with the batch counters zeroed; voiding carries the same wash-load guard and fails with `ERR_BATCH_HAS_WASH_LOADS` when a load already exists."

        Design: Difficulty/compensating_invariant/sort_batch_void_restores_piece_conservation
        """
        ctx = _ctx_with_batch(pieces_accepted=7, pieces_rejected=2,
                              reject_reason="TEAR")
        validate_success(api.void_sort_batch(ctx["batch"]["id"], OPERATOR), 200)
        post = get_sort_batch(ctx["batch"]["id"])
        assert post["status"] == "VOIDED"
        assert post["total_sorted_pieces"] == 0, "void must zero total_sorted_pieces"
        assert post["accepted_pieces"] == 0, "void must zero accepted_pieces"
        assert post["rejected_pieces"] == 0, "void must zero rejected_pieces"
        items, meta = validate_paginated(
            api.list_sort_items(ctx["batch"]["id"], OPERATOR)
        )
        assert items == [] and meta["total_count"] == 0, (
            "void must discard the batch's sort items"
        )
