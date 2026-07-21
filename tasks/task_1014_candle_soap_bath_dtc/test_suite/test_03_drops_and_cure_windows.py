"""Seasonal drops (half-open windows, liveness) and batch cure windows (closed intervals)."""
import test_helpers as H


def _sku(product_type="SOAP", price=1000):
    return H.new_sku(H.new_product(product_type=product_type)["id"], list_price_cents=price)


# ==========================================================================
# Queue B — drop status auto-transition
# ==========================================================================
def test_drop_reads_live_within_window(api, merchops_headers):
    """PRD §2.8: "A `Drop`'s `status` is derived from the clock on each read: it is `SCHEDULED`
    while the current instant is before `starts_at`, `LIVE` while the current instant is at or
    after `starts_at` and strictly before `ends_at`, and `ENDED` once the current instant is at
    or after `ends_at`."

    Design: Corner/state_machines/drop_status_live_within_window_auto_transition
    """
    H.set_clock("2026-07-01T00:00:00Z")
    sku = _sku()
    drop = H.new_drop(
        listings=[{"sku_id": sku["id"], "drop_price_cents": 900, "is_exclusive": False}],
        starts_at="2026-07-05T00:00:00Z", ends_at="2026-07-10T00:00:00Z", season="SUMMER_2026", title="Win")
    assert H.validate_success(api.get_drop(drop["id"], merchops_headers), 200)["status"] == "SCHEDULED"
    H.set_clock("2026-07-07T00:00:00Z")
    assert H.validate_success(api.get_drop(drop["id"], merchops_headers), 200)["status"] == "LIVE"


# ==========================================================================
# Queue A — resource_temporal_overlap / drop_exclusive_window_overlap_half_open
# ==========================================================================
def test_overlapping_exclusive_drop_window_rejected(api, merchops_headers):
    """PRD §3.3: "if any exclusive listing's window overlaps the exclusive window of the same sku
    in another drop that has not already `ENDED`, the drop is rejected with
    `ERR_DROP_WINDOW_OVERLAP`. These windows are treated with **half-open** semantics — start
    inclusive, end exclusive — so a new drop that begins exactly when a prior one ends does not
    overlap."

    Design: Difficulty/resource_temporal_overlap/drop_exclusive_window_overlap_half_open
    """
    sku = _sku(price=1200)
    H.new_drop(listings=[{"sku_id": sku["id"], "drop_price_cents": 1100, "is_exclusive": True}],
               starts_at="2026-08-01T00:00:00Z", ends_at="2026-08-10T00:00:00Z", title="D1")
    resp = api.create_drop(H.create_drop_payload(
        title="D2-overlap", starts_at="2026-08-05T00:00:00Z", ends_at="2026-08-15T00:00:00Z",
        listings=[{"sku_id": sku["id"], "drop_price_cents": 1100, "is_exclusive": True}]), merchops_headers)
    H.validate_error(resp, H.ApiErrorId.ERR_DROP_WINDOW_OVERLAP)


def test_adjacent_exclusive_drop_window_accepted(api, merchops_headers):
    """PRD §3.3: "These windows are treated with **half-open** semantics — start inclusive, end
    exclusive — so a new drop that begins exactly when a prior one ends does not overlap."

    Design: Difficulty/resource_temporal_overlap/drop_exclusive_window_overlap_half_open
    """
    sku = _sku(price=1200)
    H.new_drop(listings=[{"sku_id": sku["id"], "drop_price_cents": 1100, "is_exclusive": True}],
               starts_at="2026-08-01T00:00:00Z", ends_at="2026-08-10T00:00:00Z", title="D1")
    resp = api.create_drop(H.create_drop_payload(
        title="D3-adjacent", starts_at="2026-08-10T00:00:00Z", ends_at="2026-08-20T00:00:00Z",
        listings=[{"sku_id": sku["id"], "drop_price_cents": 1100, "is_exclusive": True}]), merchops_headers)
    H.validate_success(resp, 201)


# ==========================================================================
# Queue A — resource_temporal_overlap / batch_cure_window_conflict_closed
# ==========================================================================
def test_touching_cure_window_same_line_rejected(api, merchops_headers):
    """PRD §3.2: "creating a batch whose cure window overlaps that of another batch on the same
    `line_code` is rejected with `ERR_BATCH_LINE_CONFLICT`. The cure windows are treated as
    **closed intervals**, so two windows that merely touch at an endpoint are considered
    overlapping."

    Design: Difficulty/resource_temporal_overlap/batch_cure_window_conflict_closed
    """
    sku = _sku(price=1500)
    H.new_batch(sku["id"], quantity_produced=40, line_code="LINE_Z",
                cure_starts_at="2026-06-01T00:00:00Z", cure_ends_at="2026-06-05T00:00:00Z")
    resp = api.create_batch(sku["id"], {
        "quantity_produced": 40, "line_code": "LINE_Z",
        "cure_starts_at": "2026-06-05T00:00:00Z", "cure_ends_at": "2026-06-10T00:00:00Z"}, merchops_headers)
    H.validate_error(resp, H.ApiErrorId.ERR_BATCH_LINE_CONFLICT)


def test_overlapping_cure_window_different_line_accepted(api, merchops_headers):
    """PRD §3.2: "creating a batch whose cure window overlaps that of another batch on the same
    `line_code` is rejected with `ERR_BATCH_LINE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/batch_cure_window_conflict_closed
    """
    sku = _sku(price=1500)
    H.new_batch(sku["id"], quantity_produced=40, line_code="LINE_Z",
                cure_starts_at="2026-06-01T00:00:00Z", cure_ends_at="2026-06-05T00:00:00Z")
    resp = api.create_batch(sku["id"], {
        "quantity_produced": 40, "line_code": "LINE_Y",
        "cure_starts_at": "2026-06-03T00:00:00Z", "cure_ends_at": "2026-06-07T00:00:00Z"}, merchops_headers)
    H.validate_success(resp, 201)


# ==========================================================================
# Queue B — add line while drop still SCHEDULED
# ==========================================================================
def test_add_line_for_scheduled_drop_sku_rejected(api):
    """PRD §3.6: "Second, drop exclusivity: if the sku is exclusive to a drop, that drop must be
    `LIVE` at the current logical-clock instant for the line to be added, otherwise it is
    rejected with `ERR_DROP_NOT_LIVE`."

    Design: Corner/validations/add_line_drop_scheduled_not_live
    """
    H.set_clock("2026-07-01T00:00:00Z")
    product = H.new_product(product_type="SOAP")
    sku = H.new_sku(product["id"], list_price_cents=1200, scent="Jasmine")
    batch = H.new_batch(sku["id"], quantity_produced=50)
    H.release_batch(batch["id"])
    H.new_drop(listings=[{"sku_id": sku["id"], "drop_price_cents": 1100, "is_exclusive": True}],
               starts_at="2026-08-01T00:00:00Z", ends_at="2026-08-10T00:00:00Z", title="Future")
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    resp = api.add_line(order["id"], H.create_line_payload(sku["id"], batch["id"], 1),
                        H.make_customer_headers(customer["id"]))
    H.validate_error(resp, H.ApiErrorId.ERR_DROP_NOT_LIVE)
