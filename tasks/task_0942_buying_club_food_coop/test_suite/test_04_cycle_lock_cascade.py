"""The cutoff: price binding, split-case pricing, whole-case aggregation and
the six-hop lock cascade."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_catalog,
    canonical_world,
    create_member_order_payload,
    create_price_version_payload,
    get_success_data,
    make_member_headers,
    open_cycle,
    open_drop_run,
    order_version,
    place_order,
    salt_world,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]


def _aggregate(api, route_run_id, item_id):
    rows, _ = validate_paginated(
        api.list_case_aggregates(
            ADMIN, params={"route_run_id": route_run_id, "item_id": item_id}
        )
    )
    assert rows, "the lock must have produced a case aggregate for this item"
    return rows[0]


# ------------------------------------------------------------ price binding --
def test_price_binding_uses_the_cutoff_instant_not_the_line_creation_instant(api):
    """PRD §3.4: "Note carefully that the comparison instant is the cycle's
    `cutoff_at` and **not** the moment the member added the line: a price
    published after a member created their line, but before the cutoff, still
    binds that line."
    PRD §3.4: "Among all price versions for the line's item, consider those whose
    `effective_from` is at or before the cycle's `cutoff_at`; the bound one is
    whichever of those has the greatest `effective_from`."

    Design: Difficulty/dual_variant_calc/price_binding_uses_cutoff_instant_not_line_creation_instant
    """
    w = canonical_world(api, "locked")

    line = validate_success(api.get_order_line(w.lines["mara_oat"], ADMIN))
    assert line["bound_case_price_cents"] == 13200
    assert line["unit_price_cents"] == 3696
    assert line["split_fee_per_unit_cents"] == 396
    assert line["is_split_unit"] is True
    assert line["confirmed_units"] == 5
    assert line["status"] == "CONFIRMED"


def test_price_binding_ignores_a_version_effective_after_the_cutoff(api):
    """PRD §2.7: "**Price binding.** The price version bound to a line is the one
    with the greatest `effective_from` among those whose `effective_from` is at or
    before the cycle's `cutoff_at`. The comparison is inclusive: a price effective
    exactly at the cutoff instant binds."

    Design: Difficulty/dual_variant_calc/price_binding_uses_cutoff_instant_not_line_creation_instant
    """
    w = build_catalog(api, items=("oat",), include_ben=False)
    get_success_data(
        api.create_price_version(
            create_price_version_payload(
                w.items["oat"], 20000, effective_from="2026-06-01T00:00:00Z"
            ),
            ADMIN,
        )
    )
    open_cycle(api, w)
    open_drop_run(api, w)
    placed = place_order(api, w, w.mara_id, w.drop_run_id, [("oat", 4)])
    line_id = placed["lines"][0]["id"]

    set_clock(api, "2026-05-25T00:00:00Z")
    get_success_data(api.lock_cycle(w.cycle_id, ADMIN))

    line = validate_success(api.get_order_line(line_id, ADMIN))
    assert line["bound_case_price_cents"] == 13200, (
        "the 2026-06-01 price sits after the cutoff and must not bind"
    )
    assert line["unit_price_cents"] == 3300
    assert line["is_split_unit"] is False


# ------------------------------------------------------ split-case pricing --
def test_split_unit_price_ceils_the_base_before_applying_the_fee(api):
    """PRD §3.4: "First take the **base**, the ceiling of
    `bound_case_price_cents` divided by the item's `case_pack_units` — a ceiling
    to the whole cent, applied *before* anything else."
    PRD §3.4: "Otherwise the member is buying a broken case: `is_split_unit` is
    true, `split_fee_per_unit_cents` is the greater of 25 cents and the base
    multiplied by 0.12 rounded half up to the whole cent, and `unit_price_cents`
    is the base plus that fee."
    PRD §3.4: "Computing the fee against the unrounded per-unit figure in a single
    step gives a different answer: for a case price of 10000 cents over a
    three-unit case, the pinned order yields 3734 and the collapsed one yields
    3733."

    Design: Difficulty/dual_variant_calc/split_unit_price_ceils_the_base_before_applying_the_fee
    """
    w = canonical_world(api, "locked")

    mara_cheese = validate_success(api.get_order_line(w.lines["mara_cheese"], ADMIN))
    assert mara_cheese["unit_price_cents"] == 3734
    assert mara_cheese["split_fee_per_unit_cents"] == 400
    assert mara_cheese["is_split_unit"] is True

    ben_cheese = validate_success(api.get_order_line(w.lines["ben_cheese"], ADMIN))
    assert ben_cheese["unit_price_cents"] == 3334
    assert ben_cheese["split_fee_per_unit_cents"] == 0
    assert ben_cheese["is_split_unit"] is False


def test_split_fee_is_twelve_percent_of_the_base_when_the_case_divides_exactly(api):
    """PRD §3.4: "If the line's `qty_units` is an exact whole multiple of
    `case_pack_units`, then `is_split_unit` is false, `split_fee_per_unit_cents`
    is 0, and `unit_price_cents` is the base."
    PRD §3.4: "The order of operations is pinned and is not commutative — the
    ceiling on the base happens first, the twelve-percent fee is computed from the
    already-ceilinged base, and only then are the two added."

    Design: Difficulty/dual_variant_calc/split_unit_price_ceils_the_base_before_applying_the_fee
    """
    w = canonical_world(api, "locked")

    mara_berry = validate_success(api.get_order_line(w.lines["mara_berry"], ADMIN))
    assert mara_berry["bound_case_price_cents"] == 9000
    assert mara_berry["split_fee_per_unit_cents"] == 180
    assert mara_berry["unit_price_cents"] == 1680
    assert mara_berry["is_split_unit"] is True

    ben_berry = validate_success(api.get_order_line(w.lines["ben_berry"], ADMIN))
    assert ben_berry["split_fee_per_unit_cents"] == 180
    assert ben_berry["unit_price_cents"] == 1680


# ---------------------------------------------------- whole-case aggregation --
def test_round_up_policy_charges_the_whole_overage_to_the_largest_line(api):
    """PRD §3.4: "Under `ROUND_UP`, `cases_ordered` is the whole-case count plus
    one, `overage_units` is the item's `case_pack_units` less `remainder_units`,
    and `dropped_units` is 0. The overage is not spread: it is charged whole to
    exactly one line, namely the line with the greatest `qty_units`, with ties
    broken by the earlier `created_at`. That line's `confirmed_units` becomes its
    own `qty_units` plus the whole `overage_units`, and the aggregate's
    `overage_order_line_id` records which line it was. Every other line is
    untouched."

    Design: Corner/state_machines/round_up_policy_charges_the_whole_overage_to_the_largest_line
    """
    w = canonical_world(api, "locked")
    aggregate = _aggregate(api, w.route_run_id, w.items["berry"])

    assert aggregate["requested_units"] == 7
    assert aggregate["cases_ordered"] == 2
    assert aggregate["covered_units"] == 12
    assert aggregate["remainder_units"] == 1
    assert aggregate["overage_units"] == 5
    assert aggregate["policy_applied"] == "ROUND_UP"
    assert aggregate["overage_order_line_id"] == w.lines["mara_berry"]

    mara_berry = validate_success(api.get_order_line(w.lines["mara_berry"], ADMIN))
    assert mara_berry["confirmed_units"] == 9
    assert mara_berry["qty_units"] == 4

    ben_berry = validate_success(api.get_order_line(w.lines["ben_berry"], ADMIN))
    assert ben_berry["confirmed_units"] == 3


def test_drop_policy_trims_the_most_recently_created_line(api):
    """PRD §3.4: "Under `DROP`, `cases_ordered` stays at the whole-case count,
    `overage_units` is 0 and `dropped_units` equals `remainder_units`. The units
    are taken back from members starting at the **latest** line: walking the
    feeding lines in descending `created_at` order, each line surrenders the
    smaller of its own `qty_units` and the shortfall still outstanding, its
    `confirmed_units` becomes its `qty_units` less what it surrendered, the
    outstanding shortfall falls by the same amount, and the walk stops as soon as
    the shortfall reaches 0."

    Design: Corner/state_machines/drop_policy_trims_the_most_recently_created_line
    """
    w = canonical_world(api, "locked")
    aggregate = _aggregate(api, w.route_run_id, w.items["cheese"])

    assert aggregate["requested_units"] == 7
    assert aggregate["cases_ordered"] == 2
    assert aggregate["covered_units"] == 6
    assert aggregate["remainder_units"] == 1
    assert aggregate["dropped_units"] == 1
    assert aggregate["policy_applied"] == "DROP"

    mara_cheese = validate_success(api.get_order_line(w.lines["mara_cheese"], ADMIN))
    assert mara_cheese["confirmed_units"] == 4

    ben_cheese = validate_success(api.get_order_line(w.lines["ben_cheese"], ADMIN))
    assert ben_cheese["confirmed_units"] == 2
    assert ben_cheese["status"] == "CONFIRMED"


# ----------------------------------------------------------- the cascade ----
def test_cycle_lock_cascades_six_hops_from_cycle_down_to_cancelled_lines(api):
    """PRD §3.4: "**Hop 5 — routes qualify.** Because drop qualification has
    settled, each route run's `aggregated_subtotal_cents` is recomputed as the sum
    of `subtotal_cents` over the drop runs on it whose status is `OPEN` or
    `QUALIFIED`."
    PRD §3.4: "**Hop 6 — a deferred route reaches back down.** Because a route run
    moved to `DEFERRED`, every drop run on it that had already reached `QUALIFIED`
    reverts `QUALIFIED → DEFERRED`, every member order on those drop runs moves
    `LOCKED → CANCELLED`, and every line on those orders moves
    `CONFIRMED → CANCELLED`."

    Design: Difficulty/transitive_cascade/cycle_lock_cascades_six_hops_from_cycle_down_to_cancelled_lines
    """
    w = canonical_world(api, "locked", route_minimum_cents=100000)

    cycle = validate_success(api.get_cycle(w.cycle_id, ADMIN))
    assert cycle["status"] == "LOCKED"

    aggregate = _aggregate(api, w.route_run_id, w.items["oat"])
    assert aggregate["requested_units"] == 11
    assert aggregate["cases_ordered"] == 2
    assert aggregate["covered_units"] == 8
    assert aggregate["remainder_units"] == 3
    assert aggregate["policy_applied"] == "SHORT_FILL"

    route_run = validate_success(api.get_route_run(w.route_run_id, ADMIN))
    assert route_run["aggregated_subtotal_cents"] == 82420
    assert route_run["status"] == "DEFERRED"

    assert validate_success(api.get_drop_run(w.drop_run_id, ADMIN))["status"] == "DEFERRED"
    assert validate_success(api.get_member_order(w.order_mara, ADMIN))["status"] == "CANCELLED"
    assert validate_success(api.get_member_order(w.order_ben, ADMIN))["status"] == "CANCELLED"

    mara_oat = validate_success(api.get_order_line(w.lines["mara_oat"], ADMIN))
    assert mara_oat["status"] == "CANCELLED"
    assert mara_oat["confirmed_units"] == 5, (
        "hop 2 confirmed the line before hop 6 cancelled it"
    )
    assert (
        validate_success(api.get_order_line(w.lines["ben_cheese"], ADMIN))["status"]
        == "CANCELLED"
    )


def test_lock_hop_one_cancels_draft_orders_and_locks_submitted_ones(api):
    """PRD §3.4: "**Hop 1 — orders settle.** Every member order on this cycle
    with status `DRAFT` moves `DRAFT → CANCELLED`, and every one of its lines
    moves `REQUESTED → CANCELLED`; a member who filled a basket and never
    committed it simply does not participate. Every member order with status
    `SUBMITTED` moves `SUBMITTED → LOCKED`."
    PRD §3.4: "**Hop 3 — demand is rounded into whole cases.** Because lines
    confirmed, the server creates one **case aggregate** per combination of route
    run and item."

    Design: Difficulty/transitive_cascade/cycle_lock_cascades_six_hops_from_cycle_down_to_cancelled_lines
    """
    w = canonical_world(api, "orders_submitted")
    cora_headers = make_member_headers(w.cora_id)
    draft = get_success_data(
        api.create_member_order(
            create_member_order_payload(w.cora_id, w.drop_run_id), cora_headers
        )
    )
    draft_line = get_success_data(
        api.create_order_line(
            {
                "member_order_id": draft["id"],
                "item_id": w.items["oat"],
                "qty_units": 4,
                "expected_member_order_version": draft["version"],
            },
            cora_headers,
        )
    )

    set_clock(api, "2026-05-25T00:00:00Z")
    get_success_data(api.lock_cycle(w.cycle_id, ADMIN))

    assert validate_success(api.get_member_order(draft["id"], ADMIN))["status"] == "CANCELLED"
    assert (
        validate_success(api.get_order_line(draft_line["id"], ADMIN))["status"]
        == "CANCELLED"
    )
    assert validate_success(api.get_member_order(w.order_mara, ADMIN))["status"] == "LOCKED"
    assert validate_success(api.get_member_order(w.order_ben, ADMIN))["status"] == "LOCKED"

    rows, _ = validate_paginated(
        api.list_route_runs(ADMIN, params={"cycle_id": w.cycle_id})
    )
    aggregate = _aggregate(api, rows[0]["id"], w.items["oat"])
    assert aggregate["requested_units"] == 11, (
        "the never-committed basket contributes nothing to the aggregate"
    )


def test_the_lock_cascade_is_fully_visible_the_moment_the_lock_returns(api):
    """PRD §3.4: "The cycle moves `OPEN → LOCKED`, `locked_at` is stamped with the
    current clock reading, and a six-hop cascade runs."
    PRD §3.4: "**Hop 4 — drops qualify.** Because `confirmed_units` has settled,
    each member order's `estimated_total_cents` is recomputed and each drop run's
    `subtotal_cents` and `discounted_subtotal_cents` are recomputed."

    Design: Corner/consistency_model/the_lock_cascade_is_fully_visible_the_moment_the_lock_returns
    """
    w = salt_world(api)
    set_clock(api, "2026-05-25T00:00:00Z")

    cycle = validate_success(api.lock_cycle(w.cycle_id, ADMIN))
    assert cycle["status"] == "LOCKED"
    assert cycle["locked_at"] is not None

    line = validate_success(api.get_order_line(w.lines["mara_salt"], ADMIN))
    assert line["status"] == "CONFIRMED"
    assert line["bound_case_price_cents"] == 5250
    assert line["unit_price_cents"] == 1050
    assert line["confirmed_units"] == 5

    assert validate_success(api.get_member_order(w.order_mara, ADMIN))["status"] == "LOCKED"

    drop_run = validate_success(api.get_drop_run(w.drop_run_id, ADMIN))
    assert drop_run["subtotal_cents"] == 5250
    assert drop_run["status"] == "QUALIFIED"

    rows, _ = validate_paginated(
        api.list_route_runs(ADMIN, params={"cycle_id": w.cycle_id})
    )
    route_run_id = rows[0]["id"]
    assert validate_success(api.get_route_run(route_run_id, ADMIN))["status"] == "QUALIFIED"

    aggregate = _aggregate(api, route_run_id, w.items["salt"])
    assert aggregate["requested_units"] == 5
    assert aggregate["cases_ordered"] == 1
    assert aggregate["covered_units"] == 5


def test_locking_a_cycle_twice_returns_invalid_cycle_state(api):
    """PRD §3.4: "It is available to a club administrator while the cycle has
    status `OPEN`; attempting it from any other status fails with
    `ERR_INVALID_CYCLE_STATE`."

    Design: Corner/state_machines/locking_a_cycle_twice_returns_invalid_cycle_state
    """
    w = salt_world(api)
    set_clock(api, "2026-05-25T00:00:00Z")
    get_success_data(api.lock_cycle(w.cycle_id, ADMIN))
    version_after_lock = order_version(api, w, w.order_mara)

    validate_error(
        api.lock_cycle(w.cycle_id, ADMIN), ApiErrorId.ERR_INVALID_CYCLE_STATE.value
    )

    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["status"] == "LOCKED"
    assert order_version(api, w, w.order_mara) == version_after_lock
    assert (
        validate_success(api.get_order_line(w.lines["mara_salt"], ADMIN))["status"]
        == "CONFIRMED"
    )


# ---------------------------------------------------------- qualification ---
def test_drop_minimum_qualifies_at_exactly_the_threshold(api):
    """PRD §2.7: "**Drop minimum.** A drop run qualifies when its
    `subtotal_cents` is greater than or equal to the drop point's
    `drop_minimum_cents`. The boundary is inclusive: a drop landing exactly on its
    minimum qualifies."
    PRD §2.7: "**Route minimum.** A route run qualifies when its
    `aggregated_subtotal_cents` is strictly greater than the route's
    `route_minimum_cents`. The boundary is exclusive: a route landing exactly on
    its minimum is deferred."

    Design: Difficulty/boundary_precision_check/drop_minimum_qualifies_at_exactly_the_threshold
    """
    w = build_catalog(
        api,
        items=("rice",),
        include_ben=False,
        route_minimum_cents=39999,
        drop_minimum_cents=40000,
    )
    open_cycle(api, w)
    open_drop_run(api, w)
    placed = place_order(api, w, w.mara_id, w.drop_run_id, [("rice", 2)])
    set_clock(api, "2026-05-25T00:00:00Z")
    get_success_data(api.lock_cycle(w.cycle_id, ADMIN))

    drop_run = validate_success(api.get_drop_run(w.drop_run_id, ADMIN))
    assert drop_run["subtotal_cents"] == 40000
    assert drop_run["status"] == "QUALIFIED"

    line = validate_success(api.get_order_line(placed["lines"][0]["id"], ADMIN))
    assert line["unit_price_cents"] == 20000
    assert line["is_split_unit"] is False

    rows, _ = validate_paginated(
        api.list_route_runs(ADMIN, params={"cycle_id": w.cycle_id})
    )
    assert rows[0]["aggregated_subtotal_cents"] == 40000
    assert rows[0]["status"] == "QUALIFIED"

    assert validate_success(api.get_member_order(placed["order"]["id"], ADMIN))["status"] == "LOCKED"


def test_route_landing_exactly_on_its_minimum_is_deferred(api):
    """PRD §3.4: "The asymmetry with hop 4 is deliberate and is the single most
    common misreading of this system: a *drop* landing exactly on its minimum
    qualifies, while a *route* landing exactly on its minimum is deferred."
    PRD §3.4: "The route run then moves `PLANNED → QUALIFIED` when
    `aggregated_subtotal_cents` is **strictly greater** than the route's
    `route_minimum_cents`, and `PLANNED → DEFERRED` otherwise."

    Design: Difficulty/boundary_precision_check/drop_minimum_qualifies_at_exactly_the_threshold
    """
    w = build_catalog(
        api,
        items=("rice",),
        include_ben=False,
        route_minimum_cents=40000,
        drop_minimum_cents=40000,
    )
    open_cycle(api, w)
    open_drop_run(api, w)
    placed = place_order(api, w, w.mara_id, w.drop_run_id, [("rice", 2)])
    set_clock(api, "2026-05-25T00:00:00Z")
    get_success_data(api.lock_cycle(w.cycle_id, ADMIN))

    rows, _ = validate_paginated(
        api.list_route_runs(ADMIN, params={"cycle_id": w.cycle_id})
    )
    assert rows[0]["aggregated_subtotal_cents"] == 40000
    assert rows[0]["status"] == "DEFERRED"

    drop_run = validate_success(api.get_drop_run(w.drop_run_id, ADMIN))
    assert drop_run["status"] == "DEFERRED"
    assert (
        validate_success(api.get_member_order(placed["order"]["id"], ADMIN))["status"]
        == "CANCELLED"
    )


def test_submitting_a_cycle_whose_only_route_was_deferred_returns_route_minimum_not_met(api):
    """PRD §3.6: "It requires the cycle to be `LOCKED` and at least one route run
    on it to have status `QUALIFIED`; a cycle whose every route run was deferred at
    the route minimum cannot be submitted and fails with
    `ERR_ROUTE_MINIMUM_NOT_MET`."

    Design: Corner/state_machines/submitting_a_cycle_whose_only_route_was_deferred_returns_route_minimum_not_met
    """
    w = canonical_world(api, "locked", route_minimum_cents=100000)

    validate_error(
        api.submit_cycle(w.cycle_id, ADMIN), ApiErrorId.ERR_ROUTE_MINIMUM_NOT_MET.value
    )
    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["status"] == "LOCKED"
