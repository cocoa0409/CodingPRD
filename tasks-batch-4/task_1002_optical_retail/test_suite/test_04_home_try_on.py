"""Home try-on: the kit gates, the closed-interval window rule, the three-link
return cascade, the conserved sample units, and the late fee."""

from test_helpers import (
    ApiErrorId,
    assert_home_try_on_kit,
    assert_tryon_units_conserved,
    create_kit_payload,
    find_item_by_frame,
    list_frame_items,
    list_kit_items,
    make_customer_headers,
    new_customer,
    new_frame,
    new_kit,
    new_shipped_kit,
    read_customer,
    read_frame,
    read_kit,
    return_kit,
    set_clock,
    ship_kit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import STORE


# ═════════════════════════════════════════════════════════════════════════════
# The three-link return cascade  (kit → items → frame availability)
# ═════════════════════════════════════════════════════════════════════════════

def test_kit_return_resolves_every_pending_item_to_kept_or_returned(api):
    """PRD §3.4: "Second, every item on the kit still sitting at `PENDING` resolves:
    an item whose `frame_id` appears in `kept_frame_ids` resolves to `KEPT`, and
    every other pending item resolves to `RETURNED`."
    PRD §3.4: "The kit's `kept_count` becomes the number of items that resolved to
    `KEPT`, its `version` increments, and the customer's `lifetime_kit_count` and
    `return_risk_score` are recomputed."

    Design: Difficulty/transitive_cascade/kit_return_cascades_kit_to_items_to_frame_availability
    """
    frame_one = new_frame(tryon_stock=2, min_pd_mm=50.0, max_pd_mm=75.0)
    frame_two = new_frame(tryon_stock=1, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Kit Retter", email="kit@example.com")
    kit = new_kit(
        customer["id"],
        [frame_one["id"], frame_two["id"]],
        "2026-05-05T00:00:00Z",
        "2026-05-15T00:00:00Z",
    )
    ship_kit(kit["id"])

    resp = api.return_home_try_on_kit(
        kit["id"],
        {"kept_frame_ids": [frame_two["id"]]},
        make_customer_headers(customer["id"]),
    )
    returned = validate_success(resp, 200)

    assert_home_try_on_kit(returned)
    assert returned["status"] == "RETURNED"
    assert returned["item_count"] == 2
    assert returned["kept_count"] == 1
    # The clock is untouched at 2026-05-01, which is before the 2026-05-15 due date.
    assert returned["late_fee_cents"] == 0

    items, _ = validate_paginated(api.list_kit_items(kit["id"], STORE))
    assert find_item_by_frame(items, frame_one["id"])["outcome"] == "RETURNED"
    assert find_item_by_frame(items, frame_two["id"])["outcome"] == "KEPT"


def test_kit_return_releases_the_sample_hold_for_kept_and_returned_alike(api):
    """PRD §3.4: "Third, every frame behind a resolved item has its `tryon_available`
    incremented by one — **both** resolutions release the physical hold, because a
    customer who "keeps" a sample in the try-on sense is expressing purchase intent,
    not walking off with the sample."
    PRD §3.4: "The kit's `kept_count` becomes the number of items that resolved to
    `KEPT`, its `version` increments, and the customer's `lifetime_kit_count` and
    `return_risk_score` are recomputed."

    Design: Difficulty/transitive_cascade/kit_return_cascades_kit_to_items_to_frame_availability
    """
    frame_one = new_frame(tryon_stock=2, min_pd_mm=50.0, max_pd_mm=75.0)
    frame_two = new_frame(tryon_stock=1, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Kit Retter", email="kit@example.com")
    kit = new_kit(
        customer["id"],
        [frame_one["id"], frame_two["id"]],
        "2026-05-05T00:00:00Z",
        "2026-05-15T00:00:00Z",
    )
    ship_kit(kit["id"])

    # Mid-flight: one unit of each frame is held by a PENDING item.
    assert read_frame(frame_one["id"])["tryon_available"] == 1
    assert read_frame(frame_two["id"])["tryon_available"] == 0

    return_kit(kit["id"], customer["id"], [frame_two["id"]])

    after_one = read_frame(frame_one["id"])
    after_two = read_frame(frame_two["id"])
    assert after_one["tryon_available"] == 2, "the RETURNED item released its sample"
    assert after_two["tryon_available"] == 1, "the KEPT item released its sample too"

    customer_after = read_customer(customer["id"])
    assert customer_after["lifetime_kit_count"] == 1
    assert customer_after["return_risk_score"] == 0, (
        "one on-time kit that kept a frame is neither zero-kept nor overdue"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Conserved quantity #2 — physical try-on sample units
# ═════════════════════════════════════════════════════════════════════════════

def test_tryon_sample_units_are_conserved_across_a_kit_request_and_return(api):
    """PRD §2.8: "For any frame, the frame's `tryon_available` plus the count of
    try-on kit items on that frame whose `outcome` is still `PENDING` always equals
    the frame's `tryon_stock`."
    PRD §2.8: "returning the kit is the compensating action that resolves every
    `PENDING` item and increments availability by exactly one per resolved item —
    regardless of whether the item resolved to `KEPT` or to `RETURNED`, because both
    outcomes physically release the sample."

    Design: Difficulty/compensating_invariant/tryon_sample_units_conserved_across_kit_request_and_return
    """
    frame = new_frame(tryon_stock=2, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Sam Ple", email="sam@example.com")

    # Before: 2 available + 0 PENDING == stock 2.
    assert_tryon_units_conserved(read_frame(frame["id"]), list_frame_items(frame["id"]))

    kit = new_kit(customer["id"], [frame["id"]], "2026-05-05T00:00:00Z", "2026-05-15T00:00:00Z")

    # During: 1 available + 1 PENDING == stock 2.
    mid_frame = read_frame(frame["id"])
    assert mid_frame["tryon_available"] == 1
    assert_tryon_units_conserved(mid_frame, list_frame_items(frame["id"]))

    ship_kit(kit["id"])
    returned = return_kit(kit["id"], customer["id"], [frame["id"]])

    # After: 2 available + 0 PENDING == stock 2, even though the item went KEPT.
    end_frame = read_frame(frame["id"])
    assert end_frame["tryon_available"] == 2
    assert end_frame["tryon_stock"] == 2
    assert_tryon_units_conserved(end_frame, list_frame_items(frame["id"]))

    items = list_kit_items(kit["id"])
    assert len(items) == 1
    assert items[0]["outcome"] == "KEPT"
    assert returned["kept_count"] == 1


def test_no_pending_item_survives_the_return_of_a_kept_frame(api):
    """PRD §2.8: "The second is **physical try-on sample units of a frame**. For any
    frame, the frame's `tryon_available` plus the count of try-on kit items on that
    frame whose `outcome` is still `PENDING` always equals the frame's `tryon_stock`."
    PRD §3.4: "Those items are the physical hold, and they are readable both as the
    items of a kit and — filtered by `outcome` — as the items that hold a given frame."

    Design: Difficulty/compensating_invariant/tryon_sample_units_conserved_across_kit_request_and_return
    """
    frame = new_frame(tryon_stock=2, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Sam Ple", email="sam@example.com")
    kit = new_kit(customer["id"], [frame["id"]], "2026-05-05T00:00:00Z", "2026-05-15T00:00:00Z")

    pending, meta = validate_paginated(
        api.list_frame_try_on_kit_items(frame["id"], STORE, params={"outcome": "PENDING"})
    )
    assert meta["total_count"] == 1, "the kit request minted one PENDING hold"

    ship_kit(kit["id"])
    return_kit(kit["id"], customer["id"], [frame["id"]])

    pending, meta = validate_paginated(
        api.list_frame_try_on_kit_items(frame["id"], STORE, params={"outcome": "PENDING"})
    )
    assert meta["total_count"] == 0, "the KEPT resolution left no PENDING hold behind"
    assert read_frame(frame["id"])["tryon_available"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# Interval semantics B — CLOSED [ship_date, due_date], capacity 1 per customer
# ═════════════════════════════════════════════════════════════════════════════

def test_kit_window_whose_ship_date_touches_a_live_due_date_collides(api):
    """PRD §2.10: "Two of the same customer's windows therefore collide even when they
    merely touch: if one kit's `due_date` falls on the same instant as another kit's
    `ship_date`, that is an overlap, and the second request is refused with
    `ERR_TRYON_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/kit_window_closed_interval_touching_dates_collide_for_customer
    """
    frame = new_frame(tryon_stock=2, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Tessa Touch", email="tessa@example.com")
    new_kit(customer["id"], [frame["id"]], "2026-05-05T00:00:00Z", "2026-05-15T00:00:00Z")

    resp = api.create_home_try_on_kit(
        create_kit_payload(
            customer["id"],
            [frame["id"]],
            "2026-05-15T00:00:00Z",  # exactly the live kit's due_date
            "2026-05-25T00:00:00Z",
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TRYON_WINDOW_CONFLICT.value)


def test_kit_window_one_day_clear_of_a_live_due_date_is_accepted(api):
    """PRD §2.10: "**Customer try-on windows use closed intervals with a capacity of
    one.** A kit occupies the span from `ship_date` through `due_date`, with **both**
    endpoints inclusive."
    PRD §2.10: "The candidate set for the collision check is the customer's own kits
    whose `status` is `REQUESTED`, `SHIPPED`, or `OVERDUE`; a `RETURNED` kit no longer
    occupies a window. Capacity is one — a customer may hold at most one live kit
    window at a time."

    Design: Difficulty/resource_temporal_overlap/kit_window_closed_interval_touching_dates_collide_for_customer
    """
    frame = new_frame(tryon_stock=2, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Tessa Touch", email="tessa@example.com")
    headers = make_customer_headers(customer["id"])
    new_kit(customer["id"], [frame["id"]], "2026-05-05T00:00:00Z", "2026-05-15T00:00:00Z")

    touching = api.create_home_try_on_kit(
        create_kit_payload(
            customer["id"], [frame["id"]], "2026-05-15T00:00:00Z", "2026-05-25T00:00:00Z"
        ),
        headers,
    )
    validate_error(touching, ApiErrorId.ERR_TRYON_WINDOW_CONFLICT.value)

    resp = api.create_home_try_on_kit(
        create_kit_payload(
            customer["id"], [frame["id"]], "2026-05-16T00:00:00Z", "2026-05-26T00:00:00Z"
        ),
        headers,
    )
    second = validate_success(resp, 201)
    assert second["status"] == "REQUESTED"

    # Both live kits now hold one sample unit each of a 2-stock frame.
    assert read_frame(frame["id"])["tryon_available"] == 0

    rows, meta = validate_paginated(
        api.list_customer_home_try_on_kits(customer["id"], STORE)
    )
    assert meta["total_count"] == 2, "the touching request never landed; the 05-16 one did"


# ═════════════════════════════════════════════════════════════════════════════
# The kit cardinality boundary
# ═════════════════════════════════════════════════════════════════════════════

def test_empty_frame_ids_array_is_refused_as_kit_empty(api):
    """PRD §3.4: "The `frame_ids` array must be non-empty, or the request is refused
    with `ERR_KIT_EMPTY`."

    Zero frames is not a schema error — `frame_ids` is a well-typed array — so it is
    the dedicated emptiness rule that catches it.

    Design: Difficulty/boundary_precision_check/empty_frame_ids_array_rejected_at_kit_request
    """
    new_frame(tryon_stock=1, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Emma Ty", email="emma@example.com")

    resp = api.create_home_try_on_kit(
        create_kit_payload(customer["id"], [], "2026-05-05T00:00:00Z", "2026-05-15T00:00:00Z"),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_KIT_EMPTY.value)


def test_a_single_frame_kit_sits_on_the_other_side_of_the_empty_boundary(api):
    """PRD §3.4: "The `frame_ids` array must be non-empty, or the request is refused
    with `ERR_KIT_EMPTY`. It must name at most five distinct frames, or the request is
    refused with `ERR_KIT_SIZE_EXCEEDED`."
    PRD §3.4: "The kit is created in `REQUESTED` with `was_overdue` false, `kept_count`
    zero, `late_fee_cents` zero, and `item_count` set to the number of frames
    requested."

    Design: Difficulty/boundary_precision_check/empty_frame_ids_array_rejected_at_kit_request
    """
    frame = new_frame(tryon_stock=1, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Emma Ty", email="emma@example.com")
    headers = make_customer_headers(customer["id"])

    empty = api.create_home_try_on_kit(
        create_kit_payload(customer["id"], [], "2026-05-05T00:00:00Z", "2026-05-15T00:00:00Z"),
        headers,
    )
    validate_error(empty, ApiErrorId.ERR_KIT_EMPTY.value)

    resp = api.create_home_try_on_kit(
        create_kit_payload(
            customer["id"], [frame["id"]], "2026-05-05T00:00:00Z", "2026-05-15T00:00:00Z"
        ),
        headers,
    )
    kit = validate_success(resp, 201)

    assert_home_try_on_kit(kit)
    assert kit["status"] == "REQUESTED"
    assert kit["item_count"] == 1
    assert kit["kept_count"] == 0
    assert kit["was_overdue"] is False
    assert kit["late_fee_cents"] == 0
    assert read_frame(frame["id"])["tryon_available"] == 0


def test_a_six_frame_kit_is_refused_and_persists_nothing(api):
    """PRD §3.4: "It must name at most five distinct frames, or the request is refused
    with `ERR_KIT_SIZE_EXCEEDED`."

    Design: Corner/validations/kit_with_six_frames_rejected
    """
    frames = [new_frame(tryon_stock=1, min_pd_mm=50.0, max_pd_mm=75.0) for _ in range(6)]
    customer = new_customer(full_name="Six Frames", email="six@example.com")

    resp = api.create_home_try_on_kit(
        create_kit_payload(
            customer["id"],
            [f["id"] for f in frames],
            "2026-05-05T00:00:00Z",
            "2026-05-15T00:00:00Z",
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_KIT_SIZE_EXCEEDED.value)

    assert read_frame(frames[0]["id"])["tryon_available"] == 1, (
        "a refused request decrements no availability"
    )
    _rows, meta = validate_paginated(
        api.list_customer_home_try_on_kits(customer["id"], STORE)
    )
    assert meta["total_count"] == 0


def test_kit_request_for_a_frame_with_no_free_sample_unit_is_refused(api):
    """PRD §3.4: "Finally, every requested frame must have at least one sample unit
    free — `tryon_available` of one or more — or the request is refused with
    `ERR_TRYON_STOCK_UNAVAILABLE`; that check fires at exactly zero and never at one."

    Design: Corner/validations/kit_request_when_every_sample_unit_is_held_rejected
    """
    frame = new_frame(tryon_stock=1, min_pd_mm=50.0, max_pd_mm=75.0)
    holder = new_customer(full_name="Ann Holder", email="annh@example.com")
    waiter = new_customer(full_name="Bee Waiter", email="beew@example.com")

    new_kit(holder["id"], [frame["id"]], "2026-05-05T00:00:00Z", "2026-05-15T00:00:00Z")
    assert read_frame(frame["id"])["tryon_available"] == 0

    resp = api.create_home_try_on_kit(
        create_kit_payload(
            waiter["id"], [frame["id"]], "2026-06-01T00:00:00Z", "2026-06-11T00:00:00Z"
        ),
        make_customer_headers(waiter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TRYON_STOCK_UNAVAILABLE.value)

    _rows, meta = validate_paginated(
        api.list_customer_home_try_on_kits(waiter["id"], STORE)
    )
    assert meta["total_count"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Kit lifecycle and the late fee
# ═════════════════════════════════════════════════════════════════════════════

def test_shipping_an_already_shipped_kit_is_an_invalid_state(api):
    """PRD §2.9: "**From-state.** The target entity sits in a state from which the
    requested transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to
    every state-transition endpoint."
    PRD §3.4: "A `StoreAssociate` ships the kit, advancing it `REQUESTED → SHIPPED` and
    incrementing its `version`."

    Design: Corner/state_machines/shipping_an_already_shipped_kit_returns_invalid_state
    """
    frame = new_frame(tryon_stock=1, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Idem Potent", email="idem@example.com")
    kit = new_shipped_kit(customer["id"], [frame["id"]])
    shipped_version = kit["version"]

    resp = api.ship_home_try_on_kit(kit["id"], STORE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = read_kit(kit["id"])
    assert after["status"] == "SHIPPED"
    assert after["version"] == shipped_version, "a refused transition mutates nothing"


def test_late_fee_clamps_at_its_five_thousand_cent_ceiling(api):
    """PRD §3.4: "The fee is five hundred cents for each day late, and it is then
    clamped to a ceiling of five thousand cents — so a kit ten or more days late
    incurs the same fifty-dollar maximum as a kit a hundred days late."
    PRD §3.4: "Otherwise the system takes the elapsed time from `due_date` to the
    clock, divides it by one day, and rounds **up** to a whole number of days late; a
    return one minute past the deadline is one day late."

    Twenty days late would accrue 10,000c; the ceiling holds it at 5,000c.

    Design: Corner/calculations/kit_late_fee_clamps_at_its_cap
    """
    frame = new_frame(tryon_stock=1, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Lay Tee", email="late@example.com")
    kit = new_shipped_kit(
        customer["id"], [frame["id"]], "2026-05-02T00:00:00Z", "2026-05-10T00:00:00Z"
    )

    set_clock("2026-05-30T00:00:00Z")  # 20 days past the due date

    resp = api.return_home_try_on_kit(
        kit["id"], {"kept_frame_ids": []}, make_customer_headers(customer["id"])
    )
    returned = validate_success(resp, 200)

    assert returned["status"] == "RETURNED"
    assert returned["was_overdue"] is True, "the flag latched when the clock passed due_date"
    assert returned["late_fee_cents"] == 5000
    assert read_frame(frame["id"])["tryon_available"] == 1
    assert read_customer(customer["id"])["return_risk_score"] == 100, (
        "the sole kit in the window is both zero-kept and overdue: 100 * (0.6 + 0.4) / 1"
    )


def test_risk_history_ignores_kits_that_are_still_shipped(api):
    """PRD §3.4: "The system first assembles the customer's **history**: every one of
    that customer's kits whose `status` is `RETURNED` or `OVERDUE`. Kits still sitting
    at `REQUESTED` or `SHIPPED` are excluded entirely — they have not yet told us
    anything."
    PRD §3.4: "If the window is empty, the score is zero."

    Design: Corner/calculations/risk_score_ignores_requested_and_shipped_kits
    """
    frame = new_frame(tryon_stock=1, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Zed Zero", email="zed@example.com")
    kit = new_kit(customer["id"], [frame["id"]], "2026-05-05T00:00:00Z", "2026-05-15T00:00:00Z")

    resp = api.ship_home_try_on_kit(kit["id"], STORE)
    shipped = validate_success(resp, 200)
    assert shipped["status"] == "SHIPPED"

    after = read_customer(customer["id"])
    assert after["lifetime_kit_count"] == 0, "a SHIPPED kit is not history"
    assert after["return_risk_score"] == 0
