"""The global validation ladder: gate precedence, pagination and the
per-segment not-found catalogue."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_catalog,
    canonical_world,
    create_member_order_payload,
    create_order_line_payload,
    get_success_data,
    make_member_headers,
    member_version,
    open_cycle,
    open_drop_run,
    place_order,
    publish_item,
    set_clock,
    tier_change_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]


def _ambient_route_world(api, *, discontinue_berry: bool):
    """Mara ordering through a drop point on a route with zero reefer slots."""
    set_clock(api, "2026-05-05T00:00:00Z")
    south = get_success_data(
        api.create_route(
            {
                "code": "R-SOUTH",
                "name": "South Route",
                "reefer_slots": 0,
                "route_minimum_cents": 1000,
                "max_pallets": 12,
            },
            ADMIN,
        )
    )
    dry_depot = get_success_data(
        api.create_drop_point(
            {"route_id": south["id"], "name": "Dry Depot", "drop_minimum_cents": 1000},
            ADMIN,
        )
    )
    member = get_success_data(
        api.create_member(
            {
                "email": "mara@coop.test",
                "full_name": "Mara Plus",
                "home_drop_point_id": dry_depot["id"],
                "tier": "PLUS",
            },
            ADMIN,
        )
    )
    get_success_data(
        api.pay_dues(
            member["id"],
            {"amount_cents": 9000, "term_years": 1, "expected_member_version": member["version"]},
            ADMIN,
        )
    )

    class Bag:
        pass

    w = Bag()
    w.admin = ADMIN
    w.items = {}
    w.prices = {}
    w.mara_id = member["id"]
    w.depot_b_id = dry_depot["id"]
    w.cycle_id = None
    w.drop_run_id = None

    publish_item(api, w, "berry")
    publish_item(api, w, "oat")
    if discontinue_berry:
        get_success_data(api.discontinue_item(w.items["berry"], ADMIN))

    cycle = get_success_data(
        api.create_cycle(
            {
                "code": "CY-MAY",
                "opens_at": "2026-05-05T00:00:00Z",
                "cutoff_at": "2026-05-25T00:00:00Z",
            },
            ADMIN,
        )
    )
    w.cycle_id = cycle["id"]
    drop_run = get_success_data(
        api.create_drop_run(
            {"cycle_id": cycle["id"], "drop_point_id": dry_depot["id"]}, ADMIN
        )
    )
    w.drop_run_id = drop_run["id"]
    order = get_success_data(
        api.create_member_order(
            create_member_order_payload(member["id"], drop_run["id"]),
            make_member_headers(member["id"]),
        )
    )
    w.order_mara = order["id"]
    w.order = order
    return w


def test_cold_chain_safety_beats_the_discontinued_item_check(api):
    """PRD §2.9: "**Rung 28 — COLD CHAIN.** Either the item's `temp_class` is
    `DRY`, or the route serving the order's drop point has `reefer_slots` greater than
    0. This rung is deliberately placed ahead of the discontinued-item check, so a
    frozen line ordered onto an ambient route reports the cold-chain failure even when
    the item is also discontinued. Applies to creating and patching an order line.
    Failure: `ERR_ROUTE_NO_COLD_CHAIN`, HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/cold_chain_safety_beats_the_discontinued_item_check
    """
    w = _ambient_route_world(api, discontinue_berry=True)

    body = validate_error(
        api.create_order_line(
            create_order_line_payload(
                w.order_mara, w.items["berry"], 4, w.order["version"]
            ),
            make_member_headers(w.mara_id),
        ),
        ApiErrorId.ERR_ROUTE_NO_COLD_CHAIN.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_ITEM_DISCONTINUED.value

    _, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": w.order_mara})
    )
    assert meta["total_count"] == 0


def test_an_ambient_route_refuses_frozen_goods_but_still_takes_dry_ones(api):
    """PRD §3.3: "Cold goods may not be ordered onto an ambient route: unless the
    item's `temp_class` is `DRY`, the route serving the order's drop point must have a
    positive `reefer_slots`, and a violation is refused with
    `ERR_ROUTE_NO_COLD_CHAIN`."
    PRD §3.2: "From `reefer_slots` the server derives `cold_capable`, which is true
    exactly when `reefer_slots` is greater than 0; a route that is not cold-capable may
    not carry frozen or chilled goods at all."

    Design: Difficulty/priority_pair_validation_conflict/cold_chain_safety_beats_the_discontinued_item_check
    """
    w = _ambient_route_world(api, discontinue_berry=False)
    headers = make_member_headers(w.mara_id)

    validate_error(
        api.create_order_line(
            create_order_line_payload(
                w.order_mara, w.items["berry"], 4, w.order["version"]
            ),
            headers,
        ),
        ApiErrorId.ERR_ROUTE_NO_COLD_CHAIN.value,
    )

    accepted = validate_success(
        api.create_order_line(
            create_order_line_payload(
                w.order_mara, w.items["oat"], 4, w.order["version"]
            ),
            headers,
        ),
        201,
    )
    assert accepted["status"] == "REQUESTED"

    _, meta = validate_paginated(
        api.list_order_lines(ADMIN, params={"member_order_id": w.order_mara})
    )
    assert meta["total_count"] == 1


def test_membership_gate_beats_the_cycle_lock_gate(api):
    """PRD §2.9: "**Rung 10 — MEMBERSHIP GATE.** The member in scope — the acting
    member for a member-owned write, or the `member_id` supplied in the body — does not
    have status `LAPSED`. It pre-empts every order, line and substitution rung below
    it."
    PRD §2.9: "**Rung 13 — CYCLE LOCK GATE.** For member order and order-line
    writes, the parent cycle has status `OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/membership_gate_beats_the_cycle_lock_gate
    """
    w = build_catalog(api, items=("oat",), include_ben=False)
    open_cycle(api, w)
    open_drop_run(api, w)
    place_order(api, w, w.mara_id, w.drop_run_id, [("oat", 5)])

    set_clock(api, "2026-05-25T00:00:00Z")
    get_success_data(api.lock_cycle(w.cycle_id, ADMIN))
    set_clock(api, "2027-06-01T00:00:00Z")
    get_success_data(api.lapse_member(w.mara_id, ADMIN))

    body = validate_error(
        api.create_member_order(
            create_member_order_payload(w.mara_id, w.drop_run_id),
            make_member_headers(w.mara_id),
        ),
        ApiErrorId.ERR_MEMBERSHIP_LAPSED.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_CYCLE_LOCKED.value
    assert body["error_id"] != ApiErrorId.ERR_DUPLICATE_ORDER_FOR_MEMBER.value

    assert validate_success(api.get_member(w.mara_id, ADMIN))["status"] == "LAPSED"
    _, meta = validate_paginated(
        api.list_member_orders(ADMIN, params={"member_id": w.mara_id})
    )
    assert meta["total_count"] == 1


def test_membership_gate_beats_the_cutoff_rung_on_a_still_open_cycle(api):
    """PRD §2.9: "**Rung 10 — MEMBERSHIP GATE.** The member in scope — the acting
    member for a member-owned write, or the `member_id` supplied in the body — does not
    have status `LAPSED`. It pre-empts every order, line and substitution rung below
    it. Applies to opening a member order, creating an order line, patching an order
    line, cancelling an order line, submitting a member order, and approving or
    declining a substitution offer. Failure: `ERR_MEMBERSHIP_LAPSED`, HTTP 403."
    PRD §2.9: "**Rung 14** — for member order and line writes reaching a cycle that
    is still `OPEN`, the clock is strictly before the cycle's `cutoff_at`. Applies to
    opening a member order, creating an order line, patching an order line, cancelling
    an order line, and submitting a member order. Failure: `ERR_CUTOFF_PASSED`, HTTP
    409."

    Design: Difficulty/priority_pair_validation_conflict/membership_gate_beats_the_cycle_lock_gate
    """
    w = build_catalog(api, items=("oat",), include_ben=False)
    open_cycle(api, w)
    open_drop_run(api, w)

    set_clock(api, "2027-06-01T00:00:00Z")
    get_success_data(api.lapse_member(w.mara_id, ADMIN))

    body = validate_error(
        api.create_member_order(
            create_member_order_payload(w.mara_id, w.drop_run_id),
            make_member_headers(w.mara_id),
        ),
        ApiErrorId.ERR_MEMBERSHIP_LAPSED.value,
    )
    assert body["error_id"] != ApiErrorId.ERR_CUTOFF_PASSED.value

    assert validate_success(api.get_cycle(w.cycle_id, ADMIN))["status"] == "OPEN"
    _, meta = validate_paginated(
        api.list_member_orders(ADMIN, params={"member_id": w.mara_id})
    )
    assert meta["total_count"] == 0


def test_pagination_limit_above_the_maximum_returns_invalid_pagination(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, must be an integer of at
    least 1, and may not exceed 100. `offset` defaults to 0 when omitted and must be an
    integer of at least 0. A `limit` outside that range, or a negative `offset`, or a
    non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` (HTTP
    400)."

    Design: Corner/validations/pagination_limit_above_the_maximum_returns_invalid_pagination
    """
    build_catalog(api, items=("oat", "berry"))

    validate_error(
        api.list_items(ADMIN, params={"limit": 500, "offset": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
    )


def test_every_addressable_entity_returns_its_own_not_found_code(api):
    """PRD §2.8: "Which not-found code is returned is fixed per path segment and
    admits no interpretation: `member_id` yields `ERR_MEMBER_NOT_FOUND`,
    `drop_point_id` yields `ERR_DROP_POINT_NOT_FOUND`, `item_id` yields
    `ERR_ITEM_NOT_FOUND`, `price_version_id` yields `ERR_PRICE_VERSION_NOT_FOUND`,
    `cycle_id` yields `ERR_CYCLE_NOT_FOUND`, `route_run_id` yields
    `ERR_ROUTE_RUN_NOT_FOUND`, `drop_run_id` yields `ERR_DROP_RUN_NOT_FOUND`,
    `member_order_id` yields `ERR_MEMBER_ORDER_NOT_FOUND`, `order_line_id` yields
    `ERR_ORDER_LINE_NOT_FOUND`, `case_aggregate_id` yields
    `ERR_CASE_AGGREGATE_NOT_FOUND`, `receipt_line_id` yields
    `ERR_RECEIPT_LINE_NOT_FOUND`, `substitution_offer_id` yields
    `ERR_SUBSTITUTION_OFFER_NOT_FOUND`, `pallet_id` yields `ERR_PALLET_NOT_FOUND`,
    `payment_id` yields `ERR_PAYMENT_NOT_FOUND`, `drop_reconciliation_id` yields
    `ERR_RECONCILIATION_NOT_FOUND`, `commission_accrual_id` yields
    `ERR_COMMISSION_ACCRUAL_NOT_FOUND`, `volunteer_shift_id` yields
    `ERR_VOLUNTEER_SHIFT_NOT_FOUND`, and `credit_grant_id` yields
    `ERR_CREDIT_GRANT_NOT_FOUND`. All eighteen carry HTTP 404."

    Design: Corner/errors/every_addressable_entity_returns_its_own_not_found_code
    """
    canonical_world(api, "cycle_reconciled")

    expectations = [
        (api.get_member, ApiErrorId.ERR_MEMBER_NOT_FOUND),
        (api.get_drop_point, ApiErrorId.ERR_DROP_POINT_NOT_FOUND),
        (api.get_item, ApiErrorId.ERR_ITEM_NOT_FOUND),
        (api.get_price_version, ApiErrorId.ERR_PRICE_VERSION_NOT_FOUND),
        (api.get_cycle, ApiErrorId.ERR_CYCLE_NOT_FOUND),
        (api.get_route_run, ApiErrorId.ERR_ROUTE_RUN_NOT_FOUND),
        (api.get_drop_run, ApiErrorId.ERR_DROP_RUN_NOT_FOUND),
        (api.get_member_order, ApiErrorId.ERR_MEMBER_ORDER_NOT_FOUND),
        (api.get_order_line, ApiErrorId.ERR_ORDER_LINE_NOT_FOUND),
        (api.get_case_aggregate, ApiErrorId.ERR_CASE_AGGREGATE_NOT_FOUND),
        (api.get_receipt_line, ApiErrorId.ERR_RECEIPT_LINE_NOT_FOUND),
        (api.get_substitution_offer, ApiErrorId.ERR_SUBSTITUTION_OFFER_NOT_FOUND),
        (api.get_pallet, ApiErrorId.ERR_PALLET_NOT_FOUND),
        (api.get_payment, ApiErrorId.ERR_PAYMENT_NOT_FOUND),
        (api.get_drop_reconciliation, ApiErrorId.ERR_RECONCILIATION_NOT_FOUND),
        (api.get_commission_accrual, ApiErrorId.ERR_COMMISSION_ACCRUAL_NOT_FOUND),
        (api.get_volunteer_shift, ApiErrorId.ERR_VOLUNTEER_SHIFT_NOT_FOUND),
        (api.get_credit_grant, ApiErrorId.ERR_CREDIT_GRANT_NOT_FOUND),
    ]
    for reader, expected in expectations:
        validate_error(reader(NON_EXISTENT_UUID, ADMIN), expected.value)
