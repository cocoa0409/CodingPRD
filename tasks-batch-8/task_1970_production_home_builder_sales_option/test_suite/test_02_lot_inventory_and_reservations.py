"""Lot inventory: release pricing, reservation holds, and the churn paths that
must never reprice (PRD §2.3, §2.6, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_RELEASE_PRICE_CENTS,
    NON_EXISTENT_UUID,
    STANDARD_LOT_RELEASE_PRICE_CENTS,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_instant_equals,
    assert_lot,
    create_community,
    create_lot,
    create_price_phase,
    make_buyer_headers,
    open_sales,
    register_buyer,
    release_lot,
    release_reservation,
    reserve_lot,
    setup_community_selling,
    setup_released_scenario,
    setup_reserved_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["sales_director_headers"]
AGENT = TEST_USERS["sales_agent_headers"]


def test_lot_create_missing_required_field_returns_invalid_request():
    """PRD §2.10: "a missing required field, a wrong type, an unknown enum
    member, or a numeric value out of range (for example a `quantity` below 1
    or an `amount_cents` below 1) is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/lot_create_missing_required_field_returns_invalid_request
    """
    community = create_community()
    resp = api_client.create_lot(
        {
            "community_id": community["id"],
            "base_price_cents": 8_000_000,
            "lot_type": "CORNER",
            "view_adjustment_cents": 0,
        },
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_lot_not_found_returns_404():
    """PRD §2.10: "The first unresolvable identifier produces its dedicated 404:
    `ERR_COMMUNITY_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_OPTION_ITEM_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_SELECTION_NOT_FOUND`,
    `ERR_MILESTONE_NOT_FOUND`, or `ERR_INCENTIVE_NOT_FOUND`."

    Design: Corner/entities/get_lot_not_found_returns_404
    """
    resp = api_client.get_lot(NON_EXISTENT_UUID, AGENT)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_FOUND, 404)


def test_lot_listing_pagination_window():
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips that many items from the start of the result set and
    defaults to 0."
    PRD §2.3: "Unless otherwise specified, list endpoints sort by creation
    timestamp (`created_at`) in ascending order, using stable insertion order
    to break ties."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/lot_listing_pagination_window
    """
    community = create_community()
    for number, base, ltype in (
        ("L-101", 8_000_000, "CORNER"),
        ("L-102", 5_000_000, "STANDARD"),
        ("L-103", 6_000_000, "VIEW"),
    ):
        create_lot(
            community["id"], lot_number=number, base_price_cents=base,
            lot_type=ltype, view_adjustment_cents=0,
        )

    page1, meta1 = validate_paginated(
        api_client.list_lots(
            AGENT, params={"community_id": community["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2 and meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert [lot["lot_number"] for lot in page1] == ["L-101", "L-102"], (
        "created_at ASC with stable insertion order on ties"
    )

    page2, meta2 = validate_paginated(
        api_client.list_lots(
            AGENT, params={"community_id": community["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1 and meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert page2[0]["lot_number"] == "L-103"


def test_community_open_sales_gates_lot_release():
    """PRD §3.1: "Nothing can be sold while the community is in `SETUP`:
    releasing a lot, reserving a lot, or signing an agreement against a
    community that has not opened is rejected with
    `ERR_COMMUNITY_NOT_SELLING`."
    PRD §3.2: "A director may release only a `DRAFT` lot (any other state is
    rejected with `ERR_LOT_INVALID_STATE`), and only while the lot's community
    is `SELLING` (else `ERR_COMMUNITY_NOT_SELLING`)."

    Design: Corner/state_machines/community_open_sales_gates_lot_release
    """
    community = create_community()
    create_price_phase(community["id"])
    lot = create_lot(community["id"])

    resp = api_client.release_lot(lot["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_COMMUNITY_NOT_SELLING)
    assert api_client.get_lot(lot["id"], AGENT).json()["data"]["status"] == "DRAFT"

    open_sales(community["id"])
    released = validate_success(api_client.release_lot(lot["id"], DIRECTOR), 200)
    assert released["status"] == "RELEASED"
    assert released["release_price_cents"] == CANONICAL_RELEASE_PRICE_CENTS


def test_lot_release_from_released_returns_invalid_state():
    """PRD §3.2: "A director may release only a `DRAFT` lot (any other state is
    rejected with `ERR_LOT_INVALID_STATE`), and only while the lot's community
    is `SELLING` (else `ERR_COMMUNITY_NOT_SELLING`)."

    Design: Corner/state_machines/lot_release_from_released_returns_invalid_state
    """
    bundle = setup_released_scenario(with_plan=False)
    lot = bundle["lot"]
    assert lot["status"] == "RELEASED"

    resp = api_client.release_lot(lot["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE)

    after = validate_success(api_client.get_lot(lot["id"], AGENT), 200)
    assert after["release_price_cents"] == CANONICAL_RELEASE_PRICE_CENTS, (
        "a rejected release must not re-price the lot"
    )
    assert after["status"] == "RELEASED"


def test_duplicate_lot_number_rejected():
    """PRD §3.2: "A `SalesDirector` creates each lot in `DRAFT` status with a
    `community_id`, a `lot_number` that must be unique within its community (a
    duplicate is rejected with `ERR_DUPLICATE_LOT_NUMBER`), a
    `base_price_cents` strictly greater than zero, a `lot_type` of `STANDARD`,
    `CORNER`, `VIEW`, or `CUL_DE_SAC`, and an optional `view_adjustment_cents`
    defaulting to 0 for premium frontage."

    Design: Corner/validations/duplicate_lot_number_rejected
    """
    community = create_community()
    create_lot(community["id"], lot_number="L-101")

    resp = api_client.create_lot(
        {
            "community_id": community["id"],
            "lot_number": "L-101",
            "base_price_cents": 9_000_000,
            "lot_type": "STANDARD",
            "view_adjustment_cents": 0,
        },
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOT_NUMBER)

    other = create_community(name="Aspen Grove")
    ok = api_client.create_lot(
        {
            "community_id": other["id"],
            "lot_number": "L-101",
            "base_price_cents": 9_000_000,
            "lot_type": "STANDARD",
            "view_adjustment_cents": 0,
        },
        DIRECTOR,
    )
    validate_success(ok, 201)  # uniqueness is community-scoped


def test_reserve_draft_lot_returns_not_released():
    """PRD §3.2: "If the lot is in any state other than `RELEASED`, the outcome
    depends on which state: a lot in `RESERVED` whose hold is still active —
    the current instant strictly earlier than its `hold_expires_at` — rejects
    the reservation with `ERR_LOT_HOLD_ACTIVE`; a lot in `RESERVED` whose hold
    has expired but which the sweep has not yet released, or a lot in any other
    non-`RELEASED` state, is rejected with `ERR_LOT_NOT_RELEASED`."

    Design: Corner/validations/reserve_draft_lot_returns_not_released
    """
    base = setup_community_selling(with_phase=False)
    lot = create_lot(base["community"]["id"], view_adjustment_cents=0)
    buyer = register_buyer()

    resp = api_client.reserve_lot(
        lot["id"], {"buyer_id": buyer["id"]}, make_buyer_headers(buyer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_RELEASED)

    after = validate_success(api_client.get_lot(lot["id"], AGENT), 200)
    assert after["status"] == "DRAFT"
    assert after["release_price_cents"] is None


def test_buyer_cannot_release_lot():
    """PRD §2.1: "Even with valid headers, a caller whose role is not authorized
    for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: the release endpoint's authorized role is "SalesDirector".

    Design: Corner/rbac/buyer_cannot_release_lot
    """
    base = setup_community_selling(with_phase=False)
    lot = create_lot(base["community"]["id"], view_adjustment_cents=0)
    buyer = register_buyer()

    resp = api_client.release_lot(lot["id"], make_buyer_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    after = validate_success(api_client.get_lot(lot["id"], AGENT), 200)
    assert after["status"] == "DRAFT"


def test_release_price_sums_separately_rounded_components():
    """PRD §3.2: "The base component is the lot's `base_price_cents` multiplied
    by one plus the uplift fraction, rounded half up to whole cents; the
    premium component is the capped premium multiplied by one plus the same
    uplift fraction, likewise rounded half up; the release price is the sum of
    the two rounded components, in that pinned order."
    PRD §3.2: "The premium side of the formula starts from a per-type premium —
    zero cents for `STANDARD`, $15,000 for `CORNER`, $25,000 for `VIEW`, and
    $10,000 for `CUL_DE_SAC` — adds the lot's `view_adjustment_cents`, and caps
    the combined premium at $30,000, taking the lesser of the cap and the raw
    sum."

    Design: Difficulty/combinatorial_formula/lot_release_price_pinned_component_rounding
    """
    bundle = setup_released_scenario(with_plan=False)
    lot = bundle["lot"]
    assert_lot(lot)
    # base component round(8,000,000 * 1.03) = 8,240,000;
    # premium component round(min(3,000,000, 1,500,000 + 200,000) * 1.03) = 1,751,000
    assert lot["release_price_cents"] == 9_991_000
    assert lot["status"] == "RELEASED"
    assert lot["release_count"] == 0


def test_release_price_caps_combined_premium_before_uplift():
    """PRD §3.2: "The premium side of the formula starts from a per-type premium
    — zero cents for `STANDARD`, $15,000 for `CORNER`, $25,000 for `VIEW`, and
    $10,000 for `CUL_DE_SAC` — adds the lot's `view_adjustment_cents`, and caps
    the combined premium at $30,000, taking the lesser of the cap and the raw
    sum."
    PRD §3.2: "If the lot's community has an `ACTIVE` price phase at the release
    instant, that phase's `uplift_pct` applies; with no active phase the uplift
    is zero."

    Design: Difficulty/combinatorial_formula/lot_release_price_pinned_component_rounding
    """
    bundle = setup_released_scenario(
        with_plan=False,
        lot_overrides=dict(
            lot_number="L-201", base_price_cents=7_000_000, lot_type="VIEW",
            view_adjustment_cents=900_000,
        ),
    )
    lot = bundle["lot"]
    # raw premium 2,500,000 + 900,000 = 3,400,000 exceeds the 3,000,000 cap:
    # premium component round(3,000,000 * 1.03) = 3,090,000 (not 3,502,000);
    # base component round(7,000,000 * 1.03) = 7,210,000.
    assert lot["release_price_cents"] == 10_300_000


def test_reserve_release_reservation_cycle_restores_released_state():
    """PRD §3.2: "The holder — or a `SalesDirector`, who is exempt from the
    holder check — may release an active reservation, returning the lot from
    `RESERVED` to `RELEASED` with `reserved_buyer_id` and `hold_expires_at`
    cleared; the lot must be `RESERVED` (else `ERR_LOT_INVALID_STATE`), and a
    `Buyer` caller who is not the holder is rejected with
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.2: "In both paths the `release_price_cents` is left unchanged and
    `release_count` is not incremented — only post-contract fallout, covered in
    §3.8, reprices a lot."

    Design: Difficulty/non_linear_state_machine/lot_released_reserved_cycle_restores_inventory
    """
    bundle = setup_reserved_scenario(with_plan=False)
    lot = bundle["lot"]
    buyer = bundle["buyer"]
    assert lot["status"] == "RESERVED"
    assert lot["reserved_buyer_id"] == buyer["id"]
    assert_instant_equals(
        lot["hold_expires_at"], "2026-08-04T00:00:00Z",
        "hold expires 72 hours after the reservation instant",
    )

    released = release_reservation(lot["id"], make_buyer_headers(buyer["id"]))
    assert released["status"] == "RELEASED", (
        "cycle RELEASED -> RESERVED -> RELEASED completed"
    )
    assert released["reserved_buyer_id"] is None
    assert released["hold_expires_at"] is None
    assert released["release_price_cents"] == CANONICAL_RELEASE_PRICE_CENTS
    assert released["release_count"] == 0


def test_director_can_release_another_buyers_reservation_without_repricing():
    """PRD §3.2: "The holder — or a `SalesDirector`, who is exempt from the
    holder check — may release an active reservation, returning the lot from
    `RESERVED` to `RELEASED` with `reserved_buyer_id` and `hold_expires_at`
    cleared; the lot must be `RESERVED` (else `ERR_LOT_INVALID_STATE`), and a
    `Buyer` caller who is not the holder is rejected with
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.2: "In both paths the `release_price_cents` is left unchanged and
    `release_count` is not incremented — only post-contract fallout, covered in
    §3.8, reprices a lot."

    Design: Difficulty/non_linear_state_machine/lot_released_reserved_cycle_restores_inventory
    """
    bundle = setup_reserved_scenario(with_plan=False)
    lot = bundle["lot"]

    released = release_reservation(lot["id"], DIRECTOR)
    assert released["status"] == "RELEASED"
    assert released["reserved_buyer_id"] is None
    assert released["hold_expires_at"] is None
    assert released["release_price_cents"] == CANONICAL_RELEASE_PRICE_CENTS
    assert released["release_count"] == 0


def test_released_count_tracks_reserve_and_release_reservation():
    """PRD §3.2: "A successful reservation moves the lot to `RESERVED`, records
    the caller in `reserved_buyer_id`, sets `hold_expires_at` to 72 hours after
    the reservation instant, and increments the lot's `version`."
    PRD §3.2: "In both paths the `release_price_cents` is left unchanged and
    `release_count` is not incremented — only post-contract fallout, covered in
    §3.8, reprices a lot."

    Design: Difficulty/compensating_invariant/released_lot_count_conserved_across_reserve_cycle
    """
    bundle = setup_released_scenario(with_plan=False)
    community_id = bundle["community"]["id"]
    buyer = bundle["buyer"]
    lot1 = bundle["lot"]
    lot2 = release_lot(
        create_lot(
            community_id, lot_number="L-102", base_price_cents=5_000_000,
            lot_type="STANDARD", view_adjustment_cents=0,
        )["id"]
    )
    assert lot2["release_price_cents"] == STANDARD_LOT_RELEASE_PRICE_CENTS

    def released_count():
        _data, meta = validate_paginated(
            api_client.list_lots(
                AGENT,
                params={"community_id": community_id, "status": "RELEASED"},
            )
        )
        return meta["total_count"]

    assert released_count() == 2, "both lots start RELEASED"
    reserve_lot(lot1["id"], buyer["id"])
    assert released_count() == 1, "the reserve decrements the released pool"
    release_reservation(lot1["id"], make_buyer_headers(buyer["id"]))
    assert released_count() == 2, "release-reservation restores the pool"

    after = validate_success(api_client.get_lot(lot1["id"], AGENT), 200)
    assert after["release_price_cents"] == CANONICAL_RELEASE_PRICE_CENTS
    assert after["release_count"] == 0
    untouched = validate_success(api_client.get_lot(lot2["id"], AGENT), 200)
    assert untouched["release_price_cents"] == STANDARD_LOT_RELEASE_PRICE_CENTS


def test_released_lot_after_cycle_is_reservable_by_another_buyer():
    """PRD §3.2: "A successful reservation moves the lot to `RESERVED`, records
    the caller in `reserved_buyer_id`, sets `hold_expires_at` to 72 hours after
    the reservation instant, and increments the lot's `version`."
    PRD §3.2: "The holder — or a `SalesDirector`, who is exempt from the holder
    check — may release an active reservation, returning the lot from
    `RESERVED` to `RELEASED` with `reserved_buyer_id` and `hold_expires_at`
    cleared"

    Design: Difficulty/compensating_invariant/released_lot_count_conserved_across_reserve_cycle
    """
    bundle = setup_released_scenario(with_plan=False)
    community_id = bundle["community"]["id"]
    bea = bundle["buyer"]
    lot1 = bundle["lot"]
    release_lot(
        create_lot(
            community_id, lot_number="L-102", base_price_cents=5_000_000,
            lot_type="STANDARD", view_adjustment_cents=0,
        )["id"]
    )
    ben = register_buyer(full_name="Ben Buyer", email="ben@example.com")

    reserve_lot(lot1["id"], bea["id"])
    release_reservation(lot1["id"], make_buyer_headers(bea["id"]))

    reserved = reserve_lot(lot1["id"], ben["id"])
    assert reserved["status"] == "RESERVED", (
        "the cycled lot is genuinely back in inventory for a new buyer"
    )
    assert reserved["reserved_buyer_id"] == ben["id"]

    _data, meta = validate_paginated(
        api_client.list_lots(
            AGENT, params={"community_id": community_id, "status": "RELEASED"}
        )
    )
    assert meta["total_count"] == 1, "only L-102 remains RELEASED"


def test_reserve_blocked_one_second_before_hold_expiry():
    """PRD §3.2: "If the lot is in any state other than `RELEASED`, the outcome
    depends on which state: a lot in `RESERVED` whose hold is still active —
    the current instant strictly earlier than its `hold_expires_at` — rejects
    the reservation with `ERR_LOT_HOLD_ACTIVE`; a lot in `RESERVED` whose hold
    has expired but which the sweep has not yet released, or a lot in any other
    non-`RELEASED` state, is rejected with `ERR_LOT_NOT_RELEASED`."
    PRD §3.2: "A successful reservation moves the lot to `RESERVED`, records
    the caller in `reserved_buyer_id`, sets `hold_expires_at` to 72 hours after
    the reservation instant, and increments the lot's `version`."

    Design: Difficulty/resource_temporal_overlap/lot_hold_point_containment_half_open
    """
    bundle = setup_reserved_scenario(with_plan=False)
    lot = bundle["lot"]
    ben = register_buyer(full_name="Ben Buyer", email="ben@example.com")

    assert_instant_equals(
        lot["hold_expires_at"], "2026-08-04T00:00:00Z",
        "hold window is [reserve instant, reserve + 72h)",
    )

    advance_clock("2026-08-03T23:59:59Z")
    resp = api_client.reserve_lot(
        lot["id"], {"buyer_id": ben["id"]}, make_buyer_headers(ben["id"])
    )
    validate_error(resp, ApiErrorId.ERR_LOT_HOLD_ACTIVE)

    after = validate_success(api_client.get_lot(lot["id"], AGENT), 200)
    assert after["status"] == "RESERVED"
    assert after["reserved_buyer_id"] == bundle["buyer"]["id"]


def test_reserve_succeeds_exactly_at_hold_expiry():
    """PRD §3.2: "Independently, the clock sweep releases any reservation whose
    expiry has been reached: once the current instant is at or after
    `hold_expires_at`, the lot returns to `RELEASED` by the same field-clearing
    path."
    PRD §3.2: "In both paths the `release_price_cents` is left unchanged and
    `release_count` is not incremented — only post-contract fallout, covered in
    §3.8, reprices a lot."

    Design: Difficulty/resource_temporal_overlap/lot_hold_point_containment_half_open
    """
    bundle = setup_reserved_scenario(with_plan=False)
    lot = bundle["lot"]
    ben = register_buyer(full_name="Ben Buyer", email="ben@example.com")

    advance_clock("2026-08-04T00:00:00Z")  # exactly hold_expires_at
    reserved = validate_success(
        api_client.reserve_lot(
            lot["id"], {"buyer_id": ben["id"]}, make_buyer_headers(ben["id"])
        ),
        200,
    )
    assert reserved["status"] == "RESERVED", (
        "the sweep released the lot at the expiry instant, so the reserve succeeds"
    )
    assert reserved["reserved_buyer_id"] == ben["id"]
    assert_instant_equals(
        reserved["hold_expires_at"], "2026-08-07T00:00:00Z",
        "the new hold runs 72 hours from the new reservation instant",
    )
    assert reserved["release_price_cents"] == CANONICAL_RELEASE_PRICE_CENTS
    assert reserved["release_count"] == 0


def test_hold_expiry_sweep_releases_lot_without_reprice():
    """PRD §3.2: "Independently, the clock sweep releases any reservation whose
    expiry has been reached: once the current instant is at or after
    `hold_expires_at`, the lot returns to `RELEASED` by the same field-clearing
    path."
    PRD §3.2: "In both paths the `release_price_cents` is left unchanged and
    `release_count` is not incremented — only post-contract fallout, covered in
    §3.8, reprices a lot."

    Design: Corner/complexity_layers/hold_expiry_sweep_releases_lot_without_reprice
    """
    bundle = setup_reserved_scenario(with_plan=False)
    lot = bundle["lot"]

    advance_clock("2026-08-04T00:00:01Z")
    after = validate_success(api_client.get_lot(lot["id"], AGENT), 200)
    assert after["status"] == "RELEASED", "sweep released the expired hold"
    assert after["reserved_buyer_id"] is None
    assert after["hold_expires_at"] is None
    assert after["release_price_cents"] == CANONICAL_RELEASE_PRICE_CENTS
    assert after["release_count"] == 0
