"""Seedling orders: lead time, tiered pricing, lifecycle, and order OCC."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    is_valid_uuid, ApiErrorId, TEST_USERS,
    create_landowner, create_seed_zone, create_order, confirm_order,
    set_clock,
    make_landowner_headers,
)

NM = TEST_USERS["nursery_manager_headers"]
CO = TEST_USERS["contract_officer_headers"]


def _zone_and_landowner():
    zone = create_seed_zone(zone_min=1400, zone_max=2400)
    landowner = create_landowner()
    return zone, landowner


def test_lead_time_exactly_210_days_accepted(api):
    """PRD §3.3: "the requested ship date must lie at least 210 days after the
    current date for the conifer species (`DOUGLAS_FIR` and `LOBLOLLY_PINE`) and
    at least 120 days after it for the hardwood `WHITE_OAK`, with a date exactly
    at the limit passing; anything shorter is rejected with
    `ERR_LEAD_TIME_INSUFFICIENT`"

    Design: Difficulty/boundary_precision_check/lead_time_exactly_210_days_accepted
    """
    set_clock("2026-08-01T00:00:00Z")
    zone, landowner = _zone_and_landowner()

    res = api.create_seedling_order(
        {
            "landowner_id": landowner["id"],
            "destination_zone_id": zone["id"],
            "species": "DOUGLAS_FIR",
            "quantity": 100,
            "requested_ship_date": "2027-02-27",
        },
        make_landowner_headers(landowner["id"]),
    )
    created = validate_success(res, 201)
    assert is_valid_uuid(created.get("id", "")), (
        "order exactly 210 days out must be created"
    )


def test_lead_time_209_days_rejected(api):
    """PRD §3.3: "the requested ship date must lie at least 210 days after the
    current date for the conifer species (`DOUGLAS_FIR` and `LOBLOLLY_PINE`) and
    at least 120 days after it for the hardwood `WHITE_OAK`, with a date exactly
    at the limit passing; anything shorter is rejected with
    `ERR_LEAD_TIME_INSUFFICIENT`"

    Design: Difficulty/boundary_precision_check/lead_time_exactly_210_days_accepted
    """
    set_clock("2026-08-01T00:00:00Z")
    zone, landowner = _zone_and_landowner()

    res = api.create_seedling_order(
        {
            "landowner_id": landowner["id"],
            "destination_zone_id": zone["id"],
            "species": "DOUGLAS_FIR",
            "quantity": 100,
            "requested_ship_date": "2027-02-26",
        },
        make_landowner_headers(landowner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LEAD_TIME_INSUFFICIENT)


def test_lead_time_hardwood_120_day_category(api):
    """PRD §3.3: "the requested ship date must lie at least 210 days after the
    current date for the conifer species (`DOUGLAS_FIR` and `LOBLOLLY_PINE`) and
    at least 120 days after it for the hardwood `WHITE_OAK`, with a date exactly
    at the limit passing; anything shorter is rejected with
    `ERR_LEAD_TIME_INSUFFICIENT`"

    Design: Corner/validations/lead_time_hardwood_120_day_category
    """
    set_clock("2026-08-01T00:00:00Z")
    zone, landowner = _zone_and_landowner()

    oak_res = api.create_seedling_order(
        {
            "landowner_id": landowner["id"],
            "destination_zone_id": zone["id"],
            "species": "WHITE_OAK",
            "quantity": 100,
            "requested_ship_date": "2026-11-29",
        },
        make_landowner_headers(landowner["id"]),
    )
    oak = validate_success(oak_res, 201)
    assert oak["species"] == "WHITE_OAK", "hardwood order exactly 120 days out must be created"

    fir_res = api.create_seedling_order(
        {
            "landowner_id": landowner["id"],
            "destination_zone_id": zone["id"],
            "species": "DOUGLAS_FIR",
            "quantity": 100,
            "requested_ship_date": "2026-11-29",
        },
        make_landowner_headers(landowner["id"]),
    )
    validate_error(fir_res, ApiErrorId.ERR_LEAD_TIME_INSUFFICIENT)


def test_order_price_tier2_prediscount_at_create(api):
    """PRD §3.3: "The `total_price_cents` applies a volume discount keyed on the
    pre-discount subtotal, meaning `quantity` multiplied by `unit_price_cents`:
    fifteen percent off when that subtotal is at least 5,000,000 cents, ten
    percent off when it is at least 2,000,000 cents but below the higher tier,
    and full price below that. Keying the tier on the post-discount total would
    be circular and is not permitted."

    Design: Difficulty/combinatorial_formula/order_price_tier_keyed_on_prediscount_subtotal
    """
    zone, landowner = _zone_and_landowner()
    order = create_order(landowner["id"], zone["id"], 16000)
    assert order["unit_price_cents"] == 320
    assert order["total_price_cents"] == 4352000, (
        "16000 * 320 = 5,120,000 subtotal selects the 15% tier: "
        f"5,120,000 * 0.85 = 4,352,000, got {order['total_price_cents']}"
    )
    assert order["total_price_cents"] != 4608000, (
        "4,608,000 is the forbidden post-discount-keyed value (10% of the "
        "already-discounted total)"
    )


def test_order_amend_recomputes_price_and_reopens(api):
    """PRD §3.3: "An amendment must keep the lead-time rule satisfiable
    (`ERR_LEAD_TIME_INSUFFICIENT` otherwise), must carry
    `expected_seedling_order_version` under §2.7, recomputes `total_price_cents`,
    and returns the order to `PENDING_REVIEW` to be reviewed anew"

    Design: Difficulty/combinatorial_formula/order_price_tier_keyed_on_prediscount_subtotal
    """
    zone, landowner = _zone_and_landowner()
    order = create_order(landowner["id"], zone["id"], 16000)
    order = confirm_order(order["id"])

    amended = get_success_data(
        api.amend_seedling_order(
            order["id"],
            {"quantity": 10000, "expected_seedling_order_version": order["version"]},
            make_landowner_headers(landowner["id"]),
        )
    )
    assert amended["total_price_cents"] == 2880000, (
        "10000 * 320 = 3,200,000 subtotal selects the 10% tier: "
        f"3,200,000 * 0.90 = 2,880,000, got {amended['total_price_cents']}"
    )
    assert amended["status"] == "PENDING_REVIEW", (
        f"amendment must reopen review, got {amended['status']}"
    )


def test_order_price_tier_boundary_two_million_cents(api):
    """PRD §3.3: "The `total_price_cents` applies a volume discount keyed on the
    pre-discount subtotal, meaning `quantity` multiplied by `unit_price_cents`:
    fifteen percent off when that subtotal is at least 5,000,000 cents, ten
    percent off when it is at least 2,000,000 cents but below the higher tier,
    and full price below that."

    Design: Corner/calculations/order_price_tier_boundary_two_million_cents
    """
    zone, landowner = _zone_and_landowner()
    at_tier = create_order(landowner["id"], zone["id"], 6250)
    assert at_tier["total_price_cents"] == 1800000, (
        "6250 * 320 = 2,000,000 exactly reaches the 10% tier (inclusive): "
        f"2,000,000 * 0.90 = 1,800,000, got {at_tier['total_price_cents']}"
    )

    below_tier = create_order(landowner["id"], zone["id"], 6249)
    assert below_tier["total_price_cents"] == 1999680, (
        "6249 * 320 = 1,999,680 is below the tier: full price expected, "
        f"got {below_tier['total_price_cents']}"
    )


def test_order_initial_state_and_confirm_once(api):
    """PRD §3.3: "A new order enters `PENDING_REVIEW`." and "A `ContractOfficer`
    confirms a reviewed order, moving it from `PENDING_REVIEW` to `CONFIRMED`"
    and PRD §2.6: "State legality: the state machine's from-state permits the
    requested transition — otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/order_initial_state_and_confirm_once
    """
    zone, landowner = _zone_and_landowner()
    order = create_order(landowner["id"], zone["id"], 100)
    assert order["status"] == "PENDING_REVIEW", (
        f"new order must start PENDING_REVIEW, got {order['status']}"
    )

    confirmed = confirm_order(order["id"])
    assert confirmed["status"] == "CONFIRMED"

    res = api.confirm_seedling_order(order["id"], CO)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_terminal_cancelled_order_rejects_all_actions(api):
    """PRD §3.3: "A successful cancel moves the order to the terminal
    `CANCELLED` state" and "The landowner may amend an order in `PENDING_REVIEW`
    or `CONFIRMED`" and PRD §2.6: "State legality: the state machine's
    from-state permits the requested transition — otherwise `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/terminal_cancelled_order_rejects_all_actions
    """
    zone, landowner = _zone_and_landowner()
    order = create_order(landowner["id"], zone["id"], 100)
    cancelled = get_success_data(
        api.cancel_seedling_order(order["id"], make_landowner_headers(landowner["id"]))
    )
    assert cancelled["status"] == "CANCELLED"

    res_confirm = api.confirm_seedling_order(order["id"], CO)
    validate_error(res_confirm, ApiErrorId.ERR_INVALID_STATE)

    # Carry the order's current version so the OCC check passes and the state
    # legality check is the one that fires.
    current = get_success_data(api.get_seedling_order(order["id"], CO))
    res_amend = api.amend_seedling_order(
        order["id"],
        {"quantity": 200, "expected_seedling_order_version": current["version"]},
        make_landowner_headers(landowner["id"]),
    )
    validate_error(res_amend, ApiErrorId.ERR_INVALID_STATE)


def test_occ_order_amend_stale_version(api):
    """PRD §2.7: "Amending a seedling order likewise requires
    `expected_seedling_order_version` matching the order's current `version`; a
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)" and "a successful
    order amendment advances the order's `version` by one"

    Design: Corner/cross_cutting/occ_order_amend_stale_version
    """
    zone, landowner = _zone_and_landowner()
    order = create_order(landowner["id"], zone["id"], 1000)
    observed_version = order["version"]

    amended = get_success_data(
        api.amend_seedling_order(
            order["id"],
            {"quantity": 1500, "expected_seedling_order_version": observed_version},
            make_landowner_headers(landowner["id"]),
        )
    )
    assert amended["version"] == observed_version + 1, (
        f"successful amendment must advance the version by one: "
        f"{observed_version} -> {amended['version']}"
    )

    res = api.amend_seedling_order(
        order["id"],
        {"quantity": 2000, "expected_seedling_order_version": observed_version},
        make_landowner_headers(landowner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
