"""Drop planning gates: priority ordering, credit boundary, temporal overlap,
cross-entity state gates (PRD §2.9, §3.6)."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_agreement,
    create_and_deliver_drop,
    create_drop,
    create_gasoline_product,
    create_posted_price,
    create_station,
    create_tank,
    create_truck,
    deliver_drop,
    dispatch_drop,
    gauge_tank,
    make_dealer_operator_headers,
    schedule_drop,
    setup_full_drop_fixture,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
PRICING = TEST_USERS["pricing_headers"]
CREDIT = TEST_USERS["credit_headers"]


# ---------------------------------------------------------------------------
# Difficulty / priority_pair_validation_conflict / state_before_fiscal_on_drop_create
# ---------------------------------------------------------------------------


def _state_before_fiscal_fixture():
    """Station limit 1772800, exposure 1772800 from one delivered 8000-gal
    drop, limit then lowered to 1000, station then SUSPENDED."""
    from test_helpers import api_client as api
    fixture = setup_full_drop_fixture(
        state_code="NM",
        state_excise_tc_per_gal=0,
        credit_limit_cents=1_772_800,
        price_tc_per_gal=2000,
        tank_capacity=30000,
        opening_physical=0,
    )
    create_and_deliver_drop(fixture, planned_gallons=8000, delivered_gallons=8000)
    # Lower the limit so exposure > new limit (fiscal would fire).
    get_success_data(api.patch_dealer_station(
        fixture["station"]["id"], {"credit_limit_cents": 1000}, CREDIT
    ))
    # Suspend the station so the state gate also fails.
    get_success_data(api.suspend_dealer_station(fixture["station"]["id"], ADMIN))
    return fixture


def test_state_before_fiscal_on_drop_create_winner(api):
    """PRD §2.9: "Every request is validated in a fixed pipeline order, and
    the stages are evaluated in the sequence below — the first failing stage
    determines the response, so an earlier failure masks every later check."
    PRD §2.9 step 6: "State preconditions. State-machine from-state guards
    and cross-entity state gates are evaluated — the generic failure is
    `ERR_INVALID_STATE` (HTTP 409), with the dedicated gates
    `ERR_STATION_NOT_ACTIVE` and `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409) on
    drop creation..."
    PRD §2.9 step 10: "Projected credit. The drop's estimated amount is
    tested against the station's remaining credit headroom —
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_drop_create
    """
    fixture = _state_before_fiscal_fixture()
    resp = api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank"]["id"],
            "truck_id": fixture["truck"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 100,
            "window_start": "2026-05-04T08:00:00Z",
            "window_end": "2026-05-04T12:00:00Z",
        },
        DISPATCH,
    )
    validate_error(resp, ApiErrorId.ERR_STATION_NOT_ACTIVE)


def test_state_before_fiscal_on_drop_create_fiscal_alone_would_fire(api):
    """PRD §3.6: "Finally, the projected credit check of §2.10 extended
    forward: the station's `current_exposure_cents` plus this drop's
    `estimated_amount_cents` must not exceed `credit_limit_cents`, with
    equality allowed; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 422)."
    PRD §3.6: "The station's `operating_status` must be `ACTIVE` — planning
    against an onboarding, suspended, or terminated station is rejected with
    `ERR_STATION_NOT_ACTIVE`..."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_drop_create
    """
    fixture = _state_before_fiscal_fixture()
    # Verify the fiscal failure mode would fire on its own if state were not
    # already broken: reactivate the station and try again.
    get_success_data(api.reactivate_dealer_station(fixture["station"]["id"], ADMIN))
    resp = api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank"]["id"],
            "truck_id": fixture["truck"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 100,
            "window_start": "2026-05-04T08:00:00Z",
            "window_end": "2026-05-04T12:00:00Z",
        },
        DISPATCH,
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


# ---------------------------------------------------------------------------
# Difficulty / priority_pair_validation_conflict / safety_before_temporal_on_drop_create
# ---------------------------------------------------------------------------


def _safety_before_temporal_fixture():
    """Full fixture; tank capacity 5000 opening 0 (safe fill 4750); truck
    TRK-1 already holds a PLANNED drop with window 2026-05-02T08:00-12:00."""
    fixture = setup_full_drop_fixture(
        state_code="TX", state_excise_tc_per_gal=200,
        credit_limit_cents=100_000_000, price_tc_per_gal=2000,
        tank_capacity=5000, opening_physical=0,
    )
    create_drop(fixture, planned_gallons=100,
                window_start="2026-05-02T08:00:00Z",
                window_end="2026-05-02T12:00:00Z")
    return fixture


def test_safety_before_temporal_on_drop_create_winner(api):
    """PRD §2.9: "Every request is validated in a fixed pipeline order, and
    the stages are evaluated in the sequence below — the first failing stage
    determines the response, so an earlier failure masks every later check."
    PRD §2.9 step 7: "Drop safety. Truck capacity and tank safe-fill checks
    — `ERR_TRUCK_CAPACITY_EXCEEDED` and `ERR_SAFE_FILL_EXCEEDED` (HTTP 422)."
    PRD §2.9 step 8: "Temporal rules. Truck window conflicts, tank settle
    windows, ... `ERR_TRUCK_WINDOW_CONFLICT` and `ERR_TANK_SETTLE_WINDOW`
    (HTTP 409)..."

    Design: Difficulty/priority_pair_validation_conflict/safety_before_temporal_on_drop_create
    """
    fixture = _safety_before_temporal_fixture()
    # 4800 planned + 0 physical > 5000 * 0.95 = 4750 (safe-fill violation)
    # AND window 10:00-14:00 overlaps the existing 08:00-12:00 drop.
    resp = api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank"]["id"],
            "truck_id": fixture["truck"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 4800,
            "window_start": "2026-05-02T10:00:00Z",
            "window_end": "2026-05-02T14:00:00Z",
        },
        DISPATCH,
    )
    validate_error(resp, ApiErrorId.ERR_SAFE_FILL_EXCEEDED)


def test_safety_before_temporal_on_drop_create_temporal_alone_would_fire(api):
    """PRD §3.6: "The truck's schedule must stay coherent: among the truck's
    drops in `PLANNED`, `SCHEDULED`, or `EN_ROUTE`, the new half-open window
    — running from `window_start` up to but not including `window_end` —
    must not overlap any existing window; two windows that merely touch, one
    ending exactly when the other starts, are allowed. A true overlap is
    rejected with `ERR_TRUCK_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_before_temporal_on_drop_create
    """
    fixture = _safety_before_temporal_fixture()
    # Keep the same overlapping window but shrink planned so safe-fill passes.
    resp = api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank"]["id"],
            "truck_id": fixture["truck"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 100,
            "window_start": "2026-05-02T10:00:00Z",
            "window_end": "2026-05-02T14:00:00Z",
        },
        DISPATCH,
    )
    validate_error(resp, ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT)


# ---------------------------------------------------------------------------
# Difficulty / boundary_precision_check / credit_limit_equality_allowed
# ---------------------------------------------------------------------------


def _credit_equality_fixture():
    """Station NM excise 0 limit exactly 1772800; POSTED price 2000 tc;
    tank capacity 30000 opening 0; truck."""
    return setup_full_drop_fixture(
        state_code="NM", state_excise_tc_per_gal=0,
        credit_limit_cents=1_772_800, price_tc_per_gal=2000,
        tank_capacity=30000, opening_physical=0,
    )


def test_credit_limit_equality_allowed(api):
    """PRD §3.6: "Finally, the projected credit check of §2.10 extended
    forward: the station's `current_exposure_cents` plus this drop's
    `estimated_amount_cents` must not exceed `credit_limit_cents`, with
    equality allowed; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/credit_limit_equality_allowed
    """
    fixture = _credit_equality_fixture()
    drop = validate_success(api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank"]["id"],
            "truck_id": fixture["truck"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 8000,
            "window_start": "2026-05-02T08:00:00Z",
            "window_end": "2026-05-02T12:00:00Z",
        },
        DISPATCH,
    ), 201)
    # estimate = fuel 1600000 + freight 25600 + tax 147200 = 1772800 == limit.
    assert drop["estimated_amount_cents"] == 1_772_800


# ---------------------------------------------------------------------------
# Difficulty / cross_entity_state_dependency / drop_requires_active_agreement
# ---------------------------------------------------------------------------


def _draft_agreement_fixture():
    """Full fixture, but the agreement is left in DRAFT (not activated)."""
    from test_helpers import (
        create_draft_agreement,
        create_gasoline_product,
        create_posted_price,
        create_tank,
        create_truck,
        make_dealer_operator_headers,
    )
    product = create_gasoline_product()
    station = create_station(state_code="TX", state_excise_tc_per_gal=200,
                             credit_limit_cents=100_000_000)
    agreement = create_draft_agreement(
        station["id"],
        committed_gallons=100_000, imaging_allowance_cents=100_000,
        margin_tc_per_gal=25, shortfall_penalty_tc_per_gal=20,
    )
    posting = create_posted_price(product["id"], price_tc_per_gal=2000)
    tank = create_tank(station["id"], product["id"],
                       capacity_gallons=20000, opening_physical_gallons=0)
    truck = create_truck()
    return {
        "product": product, "station": station, "agreement": agreement,
        "posting": posting, "tank": tank, "truck": truck,
        "dealer_headers": make_dealer_operator_headers(station["id"]),
    }


def test_drop_create_blocked_when_agreement_draft(api):
    """PRD §3.6: "...and the station must have a supply agreement in
    `ACTIVE` status, else `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/drop_requires_active_agreement
    """
    fixture = _draft_agreement_fixture()
    resp = api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank"]["id"],
            "truck_id": fixture["truck"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 1000,
            "window_start": "2026-05-02T08:00:00Z",
            "window_end": "2026-05-02T12:00:00Z",
        },
        DISPATCH,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_drop_create_unblocked_after_agreement_activation(api):
    """PRD §3.6: "...and the station must have a supply agreement in
    `ACTIVE` status, else `ERR_AGREEMENT_NOT_ACTIVE`."
    PRD §3.2: "Activation moves an agreement from `DRAFT` to `ACTIVE` and
    requires the station's `operating_status` to be `ACTIVE`..."

    Design: Difficulty/cross_entity_state_dependency/drop_requires_active_agreement
    """
    fixture = _draft_agreement_fixture()
    # Activating the (different-entity) agreement unblocks the same create.
    get_success_data(api.activate_supply_agreement(fixture["agreement"]["id"], ADMIN))
    drop = validate_success(api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank"]["id"],
            "truck_id": fixture["truck"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 1000,
            "window_start": "2026-05-02T08:00:00Z",
            "window_end": "2026-05-02T12:00:00Z",
        },
        DISPATCH,
    ), 201)
    assert drop["id"]


# ---------------------------------------------------------------------------
# Difficulty / resource_temporal_overlap / truck_half_open_adjacency
# ---------------------------------------------------------------------------


def _truck_adjacency_fixture():
    """Full fixture with three tanks and one truck TRK-1 holding a PLANNED
    drop at 2026-06-10T08:00-12:00."""
    fixture = setup_full_drop_fixture()
    fixture["tank2"] = create_tank(fixture["station"]["id"], fixture["product"]["id"],
                                   capacity_gallons=20000, opening_physical_gallons=0)
    fixture["tank3"] = create_tank(fixture["station"]["id"], fixture["product"]["id"],
                                   capacity_gallons=20000, opening_physical_gallons=0)
    create_drop(fixture, planned_gallons=100,
                window_start="2026-06-10T08:00:00Z",
                window_end="2026-06-10T12:00:00Z")
    return fixture


def test_truck_half_open_adjacency_allowed(api):
    """PRD §3.6: "The truck's schedule must stay coherent: among the truck's
    drops in `PLANNED`, `SCHEDULED`, or `EN_ROUTE`, the new half-open window
    — running from `window_start` up to but not including `window_end` —
    must not overlap any existing window; two windows that merely touch, one
    ending exactly when the other starts, are allowed."

    Design: Difficulty/resource_temporal_overlap/truck_half_open_adjacency
    """
    fixture = _truck_adjacency_fixture()
    # [12:00, 16:00) touches [08:00, 12:00) — adjacency allowed.
    drop2 = validate_success(api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank2"]["id"],
            "truck_id": fixture["truck"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 100,
            "window_start": "2026-06-10T12:00:00Z",
            "window_end": "2026-06-10T16:00:00Z",
        },
        DISPATCH,
    ), 201)
    assert drop2["id"]


def test_truck_half_open_true_overlap_rejected(api):
    """PRD §3.6: "A true overlap is rejected with `ERR_TRUCK_WINDOW_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/truck_half_open_adjacency
    """
    fixture = _truck_adjacency_fixture()
    # [11:00, 13:00) intersects [08:00, 12:00).
    resp = api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank3"]["id"],
            "truck_id": fixture["truck"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 100,
            "window_start": "2026-06-10T11:00:00Z",
            "window_end": "2026-06-10T13:00:00Z",
        },
        DISPATCH,
    )
    validate_error(resp, ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT)


# ---------------------------------------------------------------------------
# Difficulty / resource_temporal_overlap / tank_settle_buffer
# ---------------------------------------------------------------------------


def _tank_settle_fixture():
    """Full fixture with ONE tank and THREE trucks; TRK-A already holds a
    PLANNED drop into the tank at 2026-06-10T08:00-10:00."""
    fixture = setup_full_drop_fixture()
    fixture["truck_b"] = create_truck(truck_code="TRK-B")
    fixture["truck_c"] = create_truck(truck_code="TRK-C")
    create_drop(fixture, planned_gallons=100,
                window_start="2026-06-10T08:00:00Z",
                window_end="2026-06-10T10:00:00Z")
    return fixture


def test_tank_settle_three_hour_gap_rejected(api):
    """PRD §3.6: "The receiving tank needs settle time: between any two
    drops into the same tank that are in `PLANNED`, `SCHEDULED`, or
    `EN_ROUTE`, the earlier window's end and the later window's start must
    be separated by at least 4 hours, else `ERR_TANK_SETTLE_WINDOW`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/tank_settle_buffer
    """
    fixture = _tank_settle_fixture()
    # 10:00 end -> 13:00 start = 3h gap: rejected.
    resp = api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank"]["id"],
            "truck_id": fixture["truck_b"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 100,
            "window_start": "2026-06-10T13:00:00Z",
            "window_end": "2026-06-10T15:00:00Z",
        },
        DISPATCH,
    )
    validate_error(resp, ApiErrorId.ERR_TANK_SETTLE_WINDOW)


def test_tank_settle_exactly_four_hours_allowed(api):
    """PRD §3.6: "The receiving tank needs settle time: between any two
    drops into the same tank that are in `PLANNED`, `SCHEDULED`, or
    `EN_ROUTE`, the earlier window's end and the later window's start must
    be separated by at least 4 hours, else `ERR_TANK_SETTLE_WINDOW`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/tank_settle_buffer
    """
    fixture = _tank_settle_fixture()
    # 10:00 end -> 14:00 start = exactly 4h: accepted (boundary inclusive).
    drop = validate_success(api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank"]["id"],
            "truck_id": fixture["truck_c"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 100,
            "window_start": "2026-06-10T14:00:00Z",
            "window_end": "2026-06-10T16:00:00Z",
        },
        DISPATCH,
    ), 201)
    assert drop["id"]


# ---------------------------------------------------------------------------
# Corner / validations / safe_fill_equality_allowed
# ---------------------------------------------------------------------------


def test_safe_fill_equality_allowed(api):
    """PRD §3.6: "The drop must respect the tank's safe-fill ceiling:
    `planned_gallons` plus the tank's current `physical_gallons` must not
    exceed the tank's `capacity_gallons` multiplied by its `safe_fill_pct` —
    a fill landing exactly on the ceiling is allowed — and a violation is
    rejected with `ERR_SAFE_FILL_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/safe_fill_equality_allowed
    """
    fixture = setup_full_drop_fixture(
        tank_capacity=20000, opening_physical=11000, safe_fill_pct=0.95,
    )
    # 8000 + 11000 == 19000 == 20000 * 0.95 exactly.
    drop = validate_success(api.create_transport_drop(
        {
            "station_id": fixture["station"]["id"],
            "tank_id": fixture["tank"]["id"],
            "truck_id": fixture["truck"]["id"],
            "product_id": fixture["product"]["id"],
            "planned_gallons": 8000,
            "window_start": "2026-05-02T08:00:00Z",
            "window_end": "2026-05-02T12:00:00Z",
        },
        DISPATCH,
    ), 201)
    assert drop["id"]


# ---------------------------------------------------------------------------
# Corner / validations / drop_create_without_posted_price_rejected
# ---------------------------------------------------------------------------


def test_drop_create_without_posted_price_rejected(api):
    """PRD §2.6: "If no `POSTED` posting exists with an effective date on or
    before the relevant date, pricing fails with `ERR_PRICE_NOT_POSTED`
    (HTTP 422)."
    PRD §3.6: "A planned drop is created in `PLANNED` with an
    `estimated_amount_cents` — the projected invoice total computed from
    `planned_gallons` and the current rack price (§2.6) at the current clock
    date, ...; when no posted price can be resolved the create fails with
    `ERR_PRICE_NOT_POSTED`."

    Design: Corner/validations/drop_create_without_posted_price_rejected
    """
    # Build the fixture but leave the only posting in DRAFT.
    from test_helpers import (
        create_draft_agreement,
        create_gasoline_product,
        create_rack_price_posting_payload,
        create_tank,
        create_truck,
        make_dealer_operator_headers,
    )
    product = create_gasoline_product()
    station = create_station()
    agreement_draft = create_draft_agreement(station["id"])
    get_success_data(api.activate_supply_agreement(agreement_draft["id"], ADMIN))
    # Create the posting but do NOT post it.
    get_success_data(api.create_rack_price_posting(
        create_rack_price_posting_payload(
            product_id=product["id"], terminal_code="TX-NORTH",
            effective_date="2026-05-01", price_tc_per_gal=2000,
        ),
        PRICING,
    ))
    tank = create_tank(station["id"], product["id"])
    truck = create_truck()
    resp = api.create_transport_drop(
        {
            "station_id": station["id"],
            "tank_id": tank["id"],
            "truck_id": truck["id"],
            "product_id": product["id"],
            "planned_gallons": 1000,
            "window_start": "2026-05-02T08:00:00Z",
            "window_end": "2026-05-02T12:00:00Z",
        },
        DISPATCH,
    )
    validate_error(resp, ApiErrorId.ERR_PRICE_NOT_POSTED)


# ---------------------------------------------------------------------------
# Corner / validations / posting_effective_date_in_past_rejected
# ---------------------------------------------------------------------------


def test_posting_effective_date_in_past_rejected(api):
    """PRD §3.5: "A posting's `effective_date` may not be earlier than the
    current clock date at creation — back-dated prices are rejected with
    `ERR_EFFECTIVE_DATE_IN_PAST` (HTTP 422)."

    Design: Corner/validations/posting_effective_date_in_past_rejected
    """
    product = create_gasoline_product()
    resp = api.create_rack_price_posting(
        {
            "terminal_code": "TX-NORTH",
            "product_id": product["id"],
            "effective_date": "2026-04-01",  # before default clock 2026-05-01
            "price_tc_per_gal": 2000,
        },
        PRICING,
    )
    validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_IN_PAST)


# ---------------------------------------------------------------------------
# Corner / validations / drop_create_with_unknown_tank_returns_not_found
# ---------------------------------------------------------------------------


def test_drop_create_with_unknown_tank_returns_not_found(api):
    """PRD §2.9 step 4: "Path identifiers are checked left to right, then
    body foreign keys (`station_id`, `tank_id`, `truck_id`, `product_id`,
    `invoice_id`). Each missing resource yields its resource-specific 404:
    `ERR_PRODUCT_NOT_FOUND`, `ERR_DEALER_STATION_NOT_FOUND`,
    `ERR_SUPPLY_AGREEMENT_NOT_FOUND`, `ERR_RACK_PRICE_POSTING_NOT_FOUND`,
    `ERR_STORAGE_TANK_NOT_FOUND`, ..."

    Design: Corner/validations/drop_create_with_unknown_tank_returns_not_found
    """
    from prd_bench_local_runner.testing import NON_EXISTENT_UUID
    product = create_gasoline_product()
    truck = create_truck()
    station = create_station(credit_limit_cents=500000, activate=False)
    resp = api.create_transport_drop(
        {
            "station_id": station["id"],
            "tank_id": NON_EXISTENT_UUID,
            "truck_id": truck["id"],
            "product_id": product["id"],
            "planned_gallons": 100,
            "window_start": "2026-05-02T08:00:00Z",
            "window_end": "2026-05-02T12:00:00Z",
        },
        DISPATCH,
    )
    validate_error(resp, ApiErrorId.ERR_STORAGE_TANK_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner / validations / deliver_nonexistent_drop_returns_not_found
# ---------------------------------------------------------------------------


def test_deliver_nonexistent_drop_returns_not_found(api):
    """PRD §2.9 step 4: "Path identifiers are checked left to right, then
    body foreign keys (`station_id`, `tank_id`, `truck_id`, `product_id`,
    `invoice_id`). Each missing resource yields its resource-specific 404:
    ... `ERR_TRANSPORT_DROP_NOT_FOUND`, ..."
    PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format: ... The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/validations/deliver_nonexistent_drop_returns_not_found
    """
    from prd_bench_local_runner.testing import NON_EXISTENT_UUID
    resp = api.deliver_transport_drop(
        NON_EXISTENT_UUID, {"delivered_gallons": 100}, DISPATCH
    )
    error_data = validate_error(resp, ApiErrorId.ERR_TRANSPORT_DROP_NOT_FOUND)
    assert "message" in error_data


# ---------------------------------------------------------------------------
# Corner / validations / request_missing_auth_headers
# ---------------------------------------------------------------------------


def test_request_missing_auth_headers(api):
    """PRD §2.1: "A request missing either header, carrying a blank header,
    or naming a role the system does not declare is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.9 step 1: "User context. `X-User-ID` and `X-User-Role` are
    present, non-blank, and the role is declared — otherwise
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/request_missing_auth_headers
    """
    # No headers at all.
    resp = api.get_dealer_station(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers={}
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
