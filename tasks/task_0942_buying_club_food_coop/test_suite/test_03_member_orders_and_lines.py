"""Member orders and order lines while the cycle is open: creation rules,
quantity constraints, amendment, withdrawal and the membership gate."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_order_line,
    build_catalog,
    canonical_world,
    create_member_order_payload,
    create_order_line_payload,
    get_success_data,
    make_member_headers,
    open_cycle,
    open_drop_run,
    order_version,
    patch_order_line_payload,
    place_order,
    publish_item,
    salt_world,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]


def _draft_order(api, items=("oat",), **catalog_kwargs):
    """Catalog + open cycle + drop run + one empty DRAFT order for Mara."""
    w = build_catalog(api, items=items, include_ben=False, **catalog_kwargs)
    open_cycle(api, w)
    open_drop_run(api, w)
    order = get_success_data(
        api.create_member_order(
            create_member_order_payload(w.mara_id, w.drop_run_id),
            make_member_headers(w.mara_id),
        )
    )
    w.order_mara = order["id"]
    return w, order


# ----------------------------------------------------- creating a line ---
def test_a_valid_order_line_passes_every_rung_and_is_created(api):
    """PRD §3.3: "A line supplies its `member_order_id`, the `item_id`, a
    `qty_units` between 1 and 500 inclusive, and `expected_member_order_version`;
    it may also supply `rollover_opt_in`, which defaults to false and decides
    whether unfilled units may be carried into a later cycle, and
    `substitution_pref`, which defaults to `APPROVAL_REQUIRED` and is one of
    `NONE`, `ANY_SUBSTITUTE` and `APPROVAL_REQUIRED`."
    PRD §3.3: "A new line is created in status `REQUESTED` with
    `bound_case_price_cents`, `unit_price_cents`, `split_fee_per_unit_cents`,
    `confirmed_units`, `allocated_units`, `short_units`,
    `allocation_remainder_rank` and `line_gross_cents` all at 0, `is_split_unit`
    false, and a null `rolled_from_order_line_id`."

    Design: Corner/validations/a_valid_order_line_passes_every_rung_and_is_created
    """
    w, order = _draft_order(api)
    line = validate_success(
        api.create_order_line(
            create_order_line_payload(
                order["id"],
                w.items["oat"],
                5,
                order["version"],
                rollover_opt_in=True,
                substitution_pref="ANY_SUBSTITUTE",
            ),
            make_member_headers(w.mara_id),
        ),
        201,
    )

    assert_order_line(line)
    assert line["status"] == "REQUESTED"
    assert line["qty_units"] == 5
    assert line["rollover_opt_in"] is True
    assert line["substitution_pref"] == "ANY_SUBSTITUTE"
    assert line["bound_case_price_cents"] == 0
    assert line["confirmed_units"] == 0
    assert line["allocated_units"] == 0


def test_zero_quantity_order_line_returns_invalid_quantity(api):
    """PRD §2.9: "**Rung 33** — `qty_units` is an integer between 1 and 500
    inclusive, and when the item has `split_allowed` false, `qty_units` is an
    exact whole multiple of the item's `case_pack_units`. Applies to creating and
    patching an order line. Failure: `ERR_INVALID_QUANTITY`, HTTP 422."

    Design: Corner/validations/zero_quantity_order_line_returns_invalid_quantity
    """
    w, order = _draft_order(api)
    validate_error(
        api.create_order_line(
            create_order_line_payload(order["id"], w.items["oat"], 0, order["version"]),
            make_member_headers(w.mara_id),
        ),
        ApiErrorId.ERR_INVALID_QUANTITY.value,
    )

    _, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_partial_case_on_a_non_splittable_item_returns_invalid_quantity(api):
    """PRD §3.3: "When the item has `split_allowed` false, `qty_units` must
    additionally be an exact whole multiple of the item's `case_pack_units`; a
    quantity outside the range or violating the multiple rule is refused with
    `ERR_INVALID_QUANTITY`."

    Design: Corner/validations/partial_case_on_a_non_splittable_item_returns_invalid_quantity
    """
    w, order = _draft_order(api, items=("rice",))
    validate_error(
        api.create_order_line(
            create_order_line_payload(order["id"], w.items["rice"], 3, order["version"]),
            make_member_headers(w.mara_id),
        ),
        ApiErrorId.ERR_INVALID_QUANTITY.value,
    )

    _, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_a_second_line_for_the_same_item_returns_duplicate_line_for_item(api):
    """PRD §3.3: "Only one non-cancelled line per item is permitted on an order —
    a second one is refused with `ERR_DUPLICATE_LINE_FOR_ITEM` — and a member
    wanting more of the same item raises the quantity on the existing line
    instead."

    Design: Corner/validations/a_second_line_for_the_same_item_returns_duplicate_line_for_item
    """
    w, order = _draft_order(api)
    headers = make_member_headers(w.mara_id)
    first = get_success_data(
        api.create_order_line(
            create_order_line_payload(order["id"], w.items["oat"], 5, order["version"]),
            headers,
        )
    )

    validate_error(
        api.create_order_line(
            create_order_line_payload(
                order["id"], w.items["oat"], 3, order_version(api, w, order["id"])
            ),
            headers,
        ),
        ApiErrorId.ERR_DUPLICATE_LINE_FOR_ITEM.value,
    )

    rows, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": order["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["qty_units"] == 5


def test_a_second_order_for_the_same_member_on_one_drop_run_is_refused(api):
    """PRD §3.3: "A member may hold only one non-cancelled order per drop run: a
    second one is refused with `ERR_DUPLICATE_ORDER_FOR_MEMBER`."

    Design: Corner/validations/a_second_order_for_the_same_member_on_one_drop_run_is_refused
    """
    w, order = _draft_order(api, items=())
    validate_error(
        api.create_member_order(
            create_member_order_payload(w.mara_id, w.drop_run_id),
            make_member_headers(w.mara_id),
        ),
        ApiErrorId.ERR_DUPLICATE_ORDER_FOR_MEMBER.value,
    )

    _, meta = validate_paginated(
        api.list_member_orders(ADMIN, params={"member_id": w.mara_id})
    )
    assert meta["total_count"] == 1


def test_a_line_write_at_the_cutoff_instant_returns_cutoff_passed(api):
    """PRD §2.7: "**Cutoff.** Member order and order-line writes are permitted
    while the clock is strictly before the cycle's `cutoff_at`. The bound is
    exclusive at the top: at the cutoff instant itself, writes are already
    refused."
    PRD §2.9: "**Rung 14** — for member order and line writes reaching a cycle
    that is still `OPEN`, the clock is strictly before the cycle's `cutoff_at`."

    Design: Corner/validations/a_line_write_at_the_cutoff_instant_returns_cutoff_passed
    """
    w, order = _draft_order(api)
    set_clock(api, "2026-05-25T00:00:00Z")

    body = validate_error(
        api.create_order_line(
            create_order_line_payload(order["id"], w.items["oat"], 5, order["version"]),
            make_member_headers(w.mara_id),
        ),
        ApiErrorId.ERR_CUTOFF_PASSED.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_CYCLE_LOCKED.value

    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["status"] == "OPEN"
    _, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_an_item_with_no_price_effective_by_the_cutoff_returns_no_effective_price(api):
    """PRD §3.3: "An item that has no price version effective at or before the
    cycle's `cutoff_at` cannot be ordered at all, and the attempt fails with
    `ERR_NO_EFFECTIVE_PRICE`."

    Design: Corner/validations/an_item_with_no_price_effective_by_the_cutoff_returns_no_effective_price
    """
    w, order = _draft_order(api, items=("late",))
    validate_error(
        api.create_order_line(
            create_order_line_payload(order["id"], w.items["late"], 4, order["version"]),
            make_member_headers(w.mara_id),
        ),
        ApiErrorId.ERR_NO_EFFECTIVE_PRICE.value,
    )

    assert validate_success(api.get_item(w.items["late"], ADMIN))["status"] == "ACTIVE"
    _, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": order["id"]})
    )
    assert meta["total_count"] == 0


# ------------------------------------------------- amending and cancelling --
def test_patching_a_requested_line_reprices_the_drop_run_provisionally(api):
    """PRD §3.3: "While the cycle is `OPEN` and the clock is strictly before
    `cutoff_at`, a member may amend a `REQUESTED` line — changing its
    `qty_units`, its `rollover_opt_in` or its `substitution_pref` — or withdraw
    it entirely, moving it `REQUESTED → CANCELLED`. Both operations carry
    `expected_member_order_version`, both recompute the drop run's
    `subtotal_cents`, and both bump the versions of the line and of its owning
    order."

    Design: Corner/endpoints/patching_a_requested_line_reprices_the_drop_run_provisionally
    """
    w = salt_world(api)
    headers = make_member_headers(w.mara_id)

    patched = validate_success(
        api.patch_order_line(
            w.lines["mara_salt"],
            patch_order_line_payload(
                order_version(api, w, w.order_mara), qty_units=10
            ),
            headers,
        )
    )
    assert patched["qty_units"] == 10
    assert patched["status"] == "REQUESTED"

    drop_run = validate_success(api.get_drop_run(w.drop_run_id, headers))
    assert drop_run["subtotal_cents"] == 10500

    order = validate_success(api.get_member_order(w.order_mara, headers))
    assert order["status"] == "SUBMITTED"


def test_cancelling_an_already_cancelled_order_returns_invalid_order_state(api):
    """PRD §2.9: "**Rung 16** — the member order is in a from-state the requested
    transition declares, on both the fulfilment axis and the payment axis. Applies
    to submitting, cancelling, authorizing, capturing and refunding a member
    order. Failure: `ERR_INVALID_ORDER_STATE`, HTTP 409."

    Design: Corner/state_machines/cancelling_an_already_cancelled_order_returns_invalid_order_state
    """
    w, order = _draft_order(api, items=())
    headers = make_member_headers(w.mara_id)
    get_success_data(api.cancel_member_order(order["id"], headers))

    validate_error(
        api.cancel_member_order(order["id"], headers),
        ApiErrorId.ERR_INVALID_ORDER_STATE.value,
    )

    stored = validate_success(api.get_member_order(order["id"], headers))
    assert stored["status"] == "CANCELLED"
    assert stored["payment_status"] == "UNPAID"


def test_cancelling_an_already_cancelled_line_returns_invalid_line_state(api):
    """PRD §2.9: "**Rung 17** — the order line is in a from-state the requested
    transition declares. Applies to patching and cancelling an order line.
    Failure: `ERR_INVALID_LINE_STATE`, HTTP 409."
    PRD §2.9: "**Rung 25** — the optimistic-concurrency field the endpoint
    declares equals the stored `version` of the named parent."

    Design: Corner/state_machines/cancelling_an_already_cancelled_line_returns_invalid_line_state
    """
    w = salt_world(api, submit=False)
    headers = make_member_headers(w.mara_id)
    get_success_data(
        api.cancel_order_line(
            w.lines["mara_salt"],
            {"expected_member_order_version": order_version(api, w, w.order_mara)},
            headers,
        )
    )

    body = validate_error(
        api.cancel_order_line(
            w.lines["mara_salt"],
            {"expected_member_order_version": order_version(api, w, w.order_mara)},
            headers,
        ),
        ApiErrorId.ERR_INVALID_LINE_STATE.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_STALE_VERSION.value

    assert (
        validate_success(api.get_order_line(w.lines["mara_salt"], headers))["status"]
        == "CANCELLED"
    )
    assert validate_success(api.get_drop_run(w.drop_run_id, headers))["subtotal_cents"] == 0


def test_empty_order_line_collection_returns_zero_count_and_no_more(api):
    """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and
    `has_more` in `meta`; `total_count` counts the rows matching the filters
    before pagination is applied, and `has_more` is true when rows remain beyond
    the current page."

    Design: Difficulty/boundary_precision_check/empty_order_line_collection_returns_zero_count_and_no_more
    """
    w, order = _draft_order(api)
    rows, meta = validate_paginated(
        api.list_order_lines(
            make_member_headers(w.mara_id),
            params={"member_order_id": order["id"], "limit": 10, "offset": 0},
        )
    )

    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert validate_success(api.get_member_order(order["id"], ADMIN))["status"] == "DRAFT"


def test_one_line_collection_reports_a_single_row_and_no_more(api):
    """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and
    `has_more` in `meta`; `total_count` counts the rows matching the filters
    before pagination is applied, and `has_more` is true when rows remain beyond
    the current page."
    PRD §3.3: "Lines may be listed filtered by `member_order_id`, `item_id`,
    `rolled_from_order_line_id` or `status`."

    Design: Difficulty/boundary_precision_check/empty_order_line_collection_returns_zero_count_and_no_more
    """
    w = salt_world(api, submit=False)
    rows, meta = validate_paginated(
        api.list_order_lines(
            make_member_headers(w.mara_id),
            params={"member_order_id": w.order_mara, "limit": 10, "offset": 0},
        )
    )

    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


# ----------------------------------------- conservation on line reversal ---
def test_adding_then_cancelling_a_line_conserves_the_drop_run_subtotal(api):
    """PRD §2.11: "**Aggregate demand conserved on line reversal.** Creating an
    order line and then cancelling that same line before the cycle locks must
    leave both the case aggregate's `requested_units` for that route-run-and-item
    pair and the drop run's `subtotal_cents` exactly where they started."
    PRD §3.3: "A cancellation returns the drop run's `subtotal_cents` to precisely
    the value it held before the line existed."

    Design: Difficulty/compensating_invariant/adding_then_cancelling_a_line_conserves_the_drop_run_subtotal
    """
    w = salt_world(api, extra_items=("oat",))
    headers = make_member_headers(w.mara_id)
    before = validate_success(api.get_drop_run(w.drop_run_id, headers))["subtotal_cents"]
    assert before == 5250

    added = get_success_data(
        api.create_order_line(
            create_order_line_payload(
                w.order_mara, w.items["oat"], 4, order_version(api, w, w.order_mara)
            ),
            headers,
        )
    )
    after_add = validate_success(api.get_drop_run(w.drop_run_id, headers))
    assert after_add["subtotal_cents"] == 17250

    get_success_data(
        api.cancel_order_line(
            added["id"],
            {"expected_member_order_version": order_version(api, w, w.order_mara)},
            headers,
        )
    )
    after_cancel = validate_success(api.get_drop_run(w.drop_run_id, headers))
    assert after_cancel["subtotal_cents"] == before

    assert validate_success(api.get_order_line(added["id"], headers))["status"] == "CANCELLED"
    assert (
        validate_success(api.get_order_line(w.lines["mara_salt"], headers))["status"]
        == "REQUESTED"
    )
    _, meta = validate_paginated(
        api.list_order_lines(
            headers, params={"member_order_id": w.order_mara, "status": "REQUESTED"}
        )
    )
    assert meta["total_count"] == 1


def test_patching_a_quantity_up_and_back_down_conserves_the_drop_run_subtotal(api):
    """PRD §3.3: "Both operations carry `expected_member_order_version`, both
    recompute the drop run's `subtotal_cents`, and both bump the versions of the
    line and of its owning order."
    PRD §2.11: "**Aggregate demand conserved on line reversal.** Creating an
    order line and then cancelling that same line before the cycle locks must
    leave both the case aggregate's `requested_units` for that route-run-and-item
    pair and the drop run's `subtotal_cents` exactly where they started."

    Design: Difficulty/compensating_invariant/adding_then_cancelling_a_line_conserves_the_drop_run_subtotal
    """
    w = salt_world(api)
    headers = make_member_headers(w.mara_id)
    before = validate_success(api.get_drop_run(w.drop_run_id, headers))["subtotal_cents"]

    get_success_data(
        api.patch_order_line(
            w.lines["mara_salt"],
            patch_order_line_payload(order_version(api, w, w.order_mara), qty_units=15),
            headers,
        )
    )
    raised = validate_success(api.get_drop_run(w.drop_run_id, headers))
    assert raised["subtotal_cents"] == 15750

    get_success_data(
        api.patch_order_line(
            w.lines["mara_salt"],
            patch_order_line_payload(order_version(api, w, w.order_mara), qty_units=5),
            headers,
        )
    )
    restored = validate_success(api.get_drop_run(w.drop_run_id, headers))
    assert restored["subtotal_cents"] == before


# ------------------------------------- the membership gate on order writes --
def test_order_submit_depends_on_the_ordering_members_membership_status(api):
    """PRD §2.9: "**Rung 10 — MEMBERSHIP GATE.** The member in scope — the acting
    member for a member-owned write, or the `member_id` supplied in the body —
    does not have status `LAPSED`."
    PRD §3.1: "Once the member is `LAPSED`, the membership gate described at rung
    10 of §2.9 refuses every subsequent order, line and substitution write for
    that member with `ERR_MEMBERSHIP_LAPSED` until dues are paid again."

    Design: Difficulty/cross_entity_state_dependency/order_submit_depends_on_the_ordering_members_membership_status
    """
    w = build_catalog(api, items=("oat",), include_ben=False)
    open_cycle(api, w, code="CY-LONG", cutoff_at="2027-12-31T00:00:00Z")
    open_drop_run(api, w)
    placed = place_order(api, w, w.mara_id, w.drop_run_id, [("oat", 5)], submit=False)
    order_id = placed["order"]["id"]

    set_clock(api, "2027-06-01T00:00:00Z")
    get_success_data(api.lapse_member(w.mara_id, ADMIN))

    validate_error(
        api.submit_member_order(order_id, make_member_headers(w.mara_id)),
        ApiErrorId.ERR_MEMBERSHIP_LAPSED.value,
    )

    assert validate_success(api.get_member_order(order_id, ADMIN))["status"] == "DRAFT"
    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["status"] == "OPEN"
    assert validate_success(api.get_member(w.mara_id, ADMIN))["status"] == "LAPSED"


def test_a_lapsed_member_cannot_add_a_line_but_an_active_one_can(api):
    """PRD §2.9: "**Rung 10 — MEMBERSHIP GATE.** The member in scope — the acting
    member for a member-owned write, or the `member_id` supplied in the body —
    does not have status `LAPSED`. It pre-empts every order, line and substitution
    rung below it. Applies to opening a member order, creating an order line,
    patching an order line, cancelling an order line, submitting a member order,
    and approving or declining a substitution offer. Failure:
    `ERR_MEMBERSHIP_LAPSED`, HTTP 403."

    Design: Difficulty/cross_entity_state_dependency/order_submit_depends_on_the_ordering_members_membership_status
    """
    w = build_catalog(api, items=("oat",), include_ben=False)
    open_cycle(api, w, code="CY-LONG", cutoff_at="2027-12-31T00:00:00Z")
    open_drop_run(api, w)
    placed = place_order(api, w, w.mara_id, w.drop_run_id, [("oat", 5)], submit=False)
    order_id = placed["order"]["id"]
    headers = make_member_headers(w.mara_id)

    set_clock(api, "2027-06-01T00:00:00Z")
    get_success_data(api.lapse_member(w.mara_id, ADMIN))

    validate_error(
        api.create_order_line(
            create_order_line_payload(
                order_id, w.items["oat"], 2, order_version(api, w, order_id)
            ),
            headers,
        ),
        ApiErrorId.ERR_MEMBERSHIP_LAPSED.value,
    )

    _, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": order_id})
    )
    assert meta["total_count"] == 1, "the gated line must not have been created"


# ------------------------------------------- discontinuation is forward-only --
def test_discontinuing_an_item_blocks_new_lines_but_leaves_confirmed_ones_alone(api):
    """PRD §3.2: "Retirement is forward-looking only: order lines that have
    already reached `CONFIRMED` are untouched, and only *new* order lines against
    the item are refused, with `ERR_ITEM_DISCONTINUED`."

    Design: Corner/endpoints/discontinuing_an_item_blocks_new_lines_but_leaves_confirmed_ones_alone
    """
    w = canonical_world(api, "locked")
    june = open_cycle(
        api,
        w,
        code="CY-JUN",
        opens_at="2026-05-27T00:00:00Z",
        cutoff_at="2026-06-20T00:00:00Z",
    )
    june_run = get_success_data(
        api.create_drop_run({"cycle_id": june["id"], "drop_point_id": w.depot_b_id}, ADMIN)
    )
    june_order = get_success_data(
        api.create_member_order(
            create_member_order_payload(w.mara_id, june_run["id"]),
            make_member_headers(w.mara_id),
        )
    )

    item = validate_success(api.discontinue_item(w.items["oat"], ADMIN))
    assert item["status"] == "DISCONTINUED"

    validate_error(
        api.create_order_line(
            create_order_line_payload(
                june_order["id"], w.items["oat"], 4, june_order["version"]
            ),
            make_member_headers(w.mara_id),
        ),
        ApiErrorId.ERR_ITEM_DISCONTINUED.value,
    )

    confirmed = validate_success(api.get_order_line(w.lines["mara_oat"], ADMIN))
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["bound_case_price_cents"] == 13200
    assert confirmed["confirmed_units"] == 5

    _, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": june_order["id"]})
    )
    assert meta["total_count"] == 0
