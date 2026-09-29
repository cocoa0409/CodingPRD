"""Error-family corners for the merchandise allocation and replenishment API.

Three families are exercised here, each one probing that codes which are easy to
conflate stay distinct and surface in the order the PRD's validation ladder pins:
the five business-key uniqueness codes, the four size-array codes, and the
receipt pool ceiling that guards the DC ledger from both directions.
"""
import pytest

from test_helpers import (
    HTTP_STATUS_CODES,
    ApiErrorId,
    api_client,
    create_item_payload,
    create_program,
    create_promo_event_payload,
    create_proposed_run,
    create_receipt,
    create_receipt_payload,
    create_run,
    create_scheduled_promo_event,
    create_size_profile_payload,
    create_store_payload,
    create_store_position_payload,
    get_success_data,
    line_for_store,
    lines_for_run,
    make_allocation_manager_headers,
    make_allocator_headers,
    make_planning_admin_headers,
    reset_clock,
    setup_network,
    size_map,
    units_by_size,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

PLANNER = make_planning_admin_headers()
ALLOCATOR = make_allocator_headers()
MANAGER = make_allocation_manager_headers()

ONE_STORE_SPECS = [
    {
        "store_code": "0101",
        "grade": "A",
        "grade_index_bp": 13000,
        "cluster_code": "URBAN",
        "freight_flat_usd": 41.00,
        "historical_sell_through_bp": 6500,
    },
]
ONE_FIXTURE_SPECS = {
    "0101": {
        "fixture_count": 4,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 6,
    },
}
ONE_POSITION_SPECS = {
    "0101": {
        "on_hand_units": 6,
        "size_on_hand": [
            {"size_code": "S", "units": 0},
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 2},
            {"size_code": "XL", "units": 0},
        ],
        "min_units": 12,
        "max_units": 48,
        "weekly_forecast_units": 9,
        "trailing_4wk_sales_units": 30,
    },
}


@pytest.fixture
def uniqueness_scenario():
    """One ACTIVE program holding a store, a size curve, a SKU, a position and a
    SCHEDULED promotional event, plus a second program to test scoping against."""
    reset_clock()
    scenario = setup_network(
        store_specs=ONE_STORE_SPECS,
        fixture_specs=ONE_FIXTURE_SPECS,
        position_specs=ONE_POSITION_SPECS,
    )
    scenario["event"] = create_scheduled_promo_event(
        scenario["program"]["id"],
        event_code="EV-FALL",
        start_date="2026-08-10T00:00:00Z",
        end_date="2026-08-14T00:00:00Z",
    )
    scenario["other_program"] = create_program(
        name="FA26 Second Banner", banner_code="SOUTH"
    )
    return scenario


def _duplicate_store_code(api, scenario):
    return api.create_store(
        create_store_payload(scenario["program"]["id"], "0101"), PLANNER
    )


def _duplicate_sku_code(api, scenario):
    return api.create_item(
        create_item_payload(
            scenario["program"]["id"],
            scenario["size_profile"]["id"],
            sku_code="SKU-1001",
            style_code="ST-999",
        ),
        PLANNER,
    )


def _duplicate_profile_code(api, scenario):
    return api.create_size_profile(
        create_size_profile_payload(
            scenario["program"]["id"],
            profile_code="TOP-4SZ",
            item_class="APPAREL_BOTTOM",
            size_curve=[
                {"size_code": "28", "share_bp": 5000},
                {"size_code": "30", "share_bp": 5000},
            ],
        ),
        PLANNER,
    )


def _duplicate_position(api, scenario):
    return api.create_store_position(
        create_store_position_payload(
            scenario["stores"]["0101"]["id"],
            scenario["item"]["id"],
            on_hand_units=4,
            size_on_hand=size_map({"S": 4}),
        ),
        ALLOCATOR,
    )


def _duplicate_event_code(api, scenario):
    return api.create_promo_event(
        create_promo_event_payload(
            scenario["program"]["id"],
            event_code="EV-FALL",
            start_date="2026-09-10T00:00:00Z",
            end_date="2026-09-14T00:00:00Z",
        ),
        PLANNER,
    )


@pytest.mark.parametrize(
    "duplicate_kind, attempt, expected_error_id",
    [
        ("store_code", _duplicate_store_code, ApiErrorId.ERR_DUPLICATE_STORE_CODE),
        ("sku_code", _duplicate_sku_code, ApiErrorId.ERR_DUPLICATE_SKU_CODE),
        ("profile_code", _duplicate_profile_code, ApiErrorId.ERR_DUPLICATE_PROFILE_CODE),
        ("position", _duplicate_position, ApiErrorId.ERR_DUPLICATE_POSITION),
        ("event_code", _duplicate_event_code, ApiErrorId.ERR_DUPLICATE_EVENT_CODE),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_each_business_key_collision_reports_its_own_code(
    api, uniqueness_scenario, duplicate_kind, attempt, expected_error_id
):
    """The five business-key uniqueness codes are not interchangeable: each
    collision reports the code the PRD names for that key.

    "Uniqueness of business keys — `ERR_DUPLICATE_STORE_CODE`, `ERR_DUPLICATE_SKU_CODE`, `ERR_DUPLICATE_EVENT_CODE`, `ERR_DUPLICATE_POSITION` or `ERR_DUPLICATE_PROFILE_CODE`, all 409."

    "Attempting a second store with a `store_code` already used inside the same
    program is rejected with `ERR_DUPLICATE_STORE_CODE`."

    "A duplicate `sku_code` inside the program is refused with
    `ERR_DUPLICATE_SKU_CODE`."

    "A `profile_code` already used within the same program is refused with
    `ERR_DUPLICATE_PROFILE_CODE`."

    "Only one position may exist for a given store-and-SKU pair; a second attempt
    is refused with `ERR_DUPLICATE_POSITION`."

    "an `event_code` unique within that program — a duplicate is refused with
    `ERR_DUPLICATE_EVENT_CODE`"

    Design: Corner/errors/five_uniqueness_codes_are_distinct_and_all_scoped_to_the_program
    """
    response = attempt(api, uniqueness_scenario)
    validate_error(response, expected_error_id)


def test_a_duplicate_business_key_persists_nothing(api, uniqueness_scenario):
    """A refused collision leaves the collection exactly as it was: the program
    still holds one store, one SKU, one size curve, one position and one event.

    "Attempting a second store with a `store_code` already used inside the same
    program is rejected with `ERR_DUPLICATE_STORE_CODE`."

    "A `profile_code` already used within the same program is refused with
    `ERR_DUPLICATE_PROFILE_CODE`."

    Design: Corner/errors/five_uniqueness_codes_are_distinct_and_all_scoped_to_the_program
    """
    program_id = uniqueness_scenario["program"]["id"]
    validate_error(
        _duplicate_store_code(api, uniqueness_scenario),
        ApiErrorId.ERR_DUPLICATE_STORE_CODE,
    )
    validate_error(
        _duplicate_profile_code(api, uniqueness_scenario),
        ApiErrorId.ERR_DUPLICATE_PROFILE_CODE,
    )
    validate_error(
        _duplicate_position(api, uniqueness_scenario), ApiErrorId.ERR_DUPLICATE_POSITION
    )

    stores, stores_meta = validate_paginated(
        api.list_stores(PLANNER, params={"program_id": program_id})
    )
    assert stores_meta["total_count"] == 1, (
        "a rejected duplicate store must not be persisted"
    )
    profiles, profiles_meta = validate_paginated(
        api.list_size_profiles(PLANNER, params={"program_id": program_id})
    )
    assert profiles_meta["total_count"] == 1, (
        "a rejected duplicate size curve must not be persisted"
    )
    positions, positions_meta = validate_paginated(
        api.list_store_positions(ALLOCATOR, params={"item_id": uniqueness_scenario["item"]["id"]})
    )
    assert positions_meta["total_count"] == 1, (
        "a rejected duplicate position must not be persisted"
    )


def test_business_key_uniqueness_is_scoped_to_the_owning_program(
    api, uniqueness_scenario
):
    """A store code that collides inside its own program is free again in a
    different program, because the key is unique per program and not globally.

    "each carrying its owning `program_id`, a `store_code` that must be unique
    within that program"

    "Attempting a second store with a `store_code` already used inside the same
    program is rejected with `ERR_DUPLICATE_STORE_CODE`."

    Design: Corner/errors/five_uniqueness_codes_are_distinct_and_all_scoped_to_the_program
    """
    validate_error(
        _duplicate_store_code(api, uniqueness_scenario),
        ApiErrorId.ERR_DUPLICATE_STORE_CODE,
    )

    reused = validate_success(
        api.create_store(
            create_store_payload(uniqueness_scenario["other_program"]["id"], "0101"),
            PLANNER,
        ),
        expected_status=201,
    )
    assert reused["store_code"] == "0101", (
        "the same store_code must be accepted under a different program"
    )
    assert reused["program_id"] == uniqueness_scenario["other_program"]["id"]
    assert reused["id"] != uniqueness_scenario["stores"]["0101"]["id"]


def test_a_duplicate_event_code_outranks_a_window_conflict(api, uniqueness_scenario):
    """An event that both reuses a code and overlaps a scheduled peer reports the
    uniqueness code, because uniqueness sits above window conflict on the ladder.

    "later checks are never reached, so a request that violates three rules always
    reports the lowest-numbered one"

    "Uniqueness of business keys — `ERR_DUPLICATE_STORE_CODE`, `ERR_DUPLICATE_SKU_CODE`, `ERR_DUPLICATE_EVENT_CODE`, `ERR_DUPLICATE_POSITION` or `ERR_DUPLICATE_PROFILE_CODE`, all 409."

    "Promotional windows do not conflict — `ERR_PROMO_WINDOW_CONFLICT`, 409."

    Design: Corner/errors/five_uniqueness_codes_are_distinct_and_all_scoped_to_the_program
    """
    response = api.create_promo_event(
        create_promo_event_payload(
            uniqueness_scenario["program"]["id"],
            event_code="EV-FALL",
            start_date="2026-08-12T00:00:00Z",
            end_date="2026-08-16T00:00:00Z",
        ),
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_EVENT_CODE)


def test_a_unique_event_code_still_hits_the_window_conflict(api, uniqueness_scenario):
    """With the uniqueness rung satisfied the same overlapping window finally
    reports the conflict code, which proves the two codes are separately reachable.

    "A conflict is refused with `ERR_PROMO_WINDOW_CONFLICT`."

    "Only an incumbent whose `status` is `SCHEDULED` or `ACTIVE` can be conflicted
    with"

    Design: Corner/errors/five_uniqueness_codes_are_distinct_and_all_scoped_to_the_program
    """
    response = api.create_promo_event(
        create_promo_event_payload(
            uniqueness_scenario["program"]["id"],
            event_code="EV-WINTER",
            start_date="2026-08-12T00:00:00Z",
            end_date="2026-08-16T00:00:00Z",
        ),
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_PROMO_WINDOW_CONFLICT)


@pytest.fixture
def size_array_scenario():
    """An ACTIVE program with one store, an APPAREL_TOP curve of S/M/L/XL, one SKU
    on that curve, a second curve for APPAREL_BOTTOM and one booked receipt. No
    position exists yet, so every size array below is a first attempt."""
    reset_clock()
    scenario = setup_network(
        store_specs=ONE_STORE_SPECS,
        fixture_specs=ONE_FIXTURE_SPECS,
        create_positions=False,
    )
    scenario["bottom_profile"] = get_success_data(
        api_client.create_size_profile(
            create_size_profile_payload(
                scenario["program"]["id"],
                profile_code="BTM-2SZ",
                item_class="APPAREL_BOTTOM",
                size_curve=[
                    {"size_code": "28", "share_bp": 5000},
                    {"size_code": "30", "share_bp": 5000},
                ],
            ),
            PLANNER,
        )
    )
    scenario["receipt"] = get_success_data(
        api_client.create_receipt(
            create_receipt_payload(
                scenario["program"]["id"],
                scenario["item"]["id"],
                reference="ASN-7001",
                units_received=20,
                size_received=size_map({"S": 4, "M": 7, "L": 6, "XL": 3}),
            ),
            ALLOCATOR,
        )
    )
    return scenario


MALFORMED_CURVES = [
    (
        "repeated_size_code",
        "TOP-DUP",
        [
            {"size_code": "S", "share_bp": 2000},
            {"size_code": "S", "share_bp": 3500},
            {"size_code": "L", "share_bp": 3000},
            {"size_code": "XL", "share_bp": 1500},
        ],
    ),
    (
        "shares_sum_to_9999",
        "TOP-LOW",
        [
            {"size_code": "S", "share_bp": 2000},
            {"size_code": "M", "share_bp": 3500},
            {"size_code": "L", "share_bp": 3000},
            {"size_code": "XL", "share_bp": 1499},
        ],
    ),
    (
        "shares_sum_to_10001",
        "TOP-HIGH",
        [
            {"size_code": "S", "share_bp": 2000},
            {"size_code": "M", "share_bp": 3500},
            {"size_code": "L", "share_bp": 3000},
            {"size_code": "XL", "share_bp": 1501},
        ],
    ),
]


@pytest.mark.parametrize(
    "curve_fault, profile_code, size_curve",
    MALFORMED_CURVES,
    ids=[case[0] for case in MALFORMED_CURVES],
)
def test_a_malformed_size_curve_is_refused_on_its_own_code(
    api, size_array_scenario, curve_fault, profile_code, size_curve
):
    """A repeated size code and a share total either side of 10000 all report the
    curve code, and none of them leaks into a units or unknown-code refusal.

    "The `size_code` values must be distinct and the `share_bp` values must sum to"
    exactly 10000, and "a repeated size code or any other sum is refused with
    `ERR_SIZE_CURVE_INVALID`."

    Design: Corner/errors/size_array_rejections_keep_four_codes_apart_and_in_priority_order
    """
    response = api.create_size_profile(
        create_size_profile_payload(
            size_array_scenario["program"]["id"],
            profile_code=profile_code,
            item_class="APPAREL_TOP",
            size_curve=size_curve,
        ),
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_SIZE_CURVE_INVALID)


def test_a_sku_may_not_sit_on_a_curve_of_another_merchandise_class(
    api, size_array_scenario
):
    """The class check is its own code: an APPAREL_BOTTOM SKU pointed at the
    APPAREL_TOP curve is refused for the class, not for anything about the curve.

    "The SKU's `item_class` must equal the referenced profile's `item_class`; a
    mismatch is refused with `ERR_ITEM_CLASS_MISMATCH`."

    Design: Corner/errors/size_array_rejections_keep_four_codes_apart_and_in_priority_order
    """
    response = api.create_item(
        create_item_payload(
            size_array_scenario["program"]["id"],
            size_array_scenario["size_profile"]["id"],
            sku_code="SKU-2001",
            style_code="ST-200",
            item_class="APPAREL_BOTTOM",
        ),
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_ITEM_CLASS_MISMATCH)


POSITION_SIZE_FAULTS = [
    ("units_do_not_reconcile", 10, {"S": 2, "M": 4, "L": 2, "XL": 1},
     ApiErrorId.ERR_SIZE_UNITS_MISMATCH),
    ("size_code_absent_from_the_curve", 10, {"S": 2, "M": 4, "L": 2, "XL": 1, "XXL": 1},
     ApiErrorId.ERR_SIZE_CODE_UNKNOWN),
]


@pytest.mark.parametrize(
    "size_fault, on_hand_units, mix, expected_error_id",
    POSITION_SIZE_FAULTS,
    ids=[case[0] for case in POSITION_SIZE_FAULTS],
)
def test_opening_stock_keeps_the_two_size_codes_apart(
    api, size_array_scenario, size_fault, on_hand_units, mix, expected_error_id
):
    """Opening stock is given twice and the two failure modes are separate codes:
    a mix that does not add up, and a mix naming a size the curve never declared.

    "The sum of the `units` entries must equal `on_hand_units` exactly, or the
    request is refused with `ERR_SIZE_UNITS_MISMATCH`, and every `size_code` used
    must already exist in the SKU's size curve, or the request is refused with
    `ERR_SIZE_CODE_UNKNOWN`."

    Design: Corner/errors/size_array_rejections_keep_four_codes_apart_and_in_priority_order
    """
    response = api.create_store_position(
        create_store_position_payload(
            size_array_scenario["stores"]["0101"]["id"],
            size_array_scenario["item"]["id"],
            on_hand_units=on_hand_units,
            size_on_hand=size_map(mix),
        ),
        ALLOCATOR,
    )
    validate_error(response, expected_error_id)


def test_a_position_carrying_both_size_faults_reports_the_reconciliation_code(
    api, size_array_scenario
):
    """A mix that both fails to add up and names an undeclared size reports only
    the reconciliation code, because that rung is evaluated first.

    "later checks are never reached, so a request that violates three rules always
    reports the lowest-numbered one"

    "Size arrays reconcile with their unit totals — `ERR_SIZE_UNITS_MISMATCH`, 422."

    "Every size code in a size array exists in the SKU's curve — `ERR_SIZE_CODE_UNKNOWN`, 422."

    Design: Corner/errors/size_array_rejections_keep_four_codes_apart_and_in_priority_order
    """
    response = api.create_store_position(
        create_store_position_payload(
            size_array_scenario["stores"]["0101"]["id"],
            size_array_scenario["item"]["id"],
            on_hand_units=10,
            size_on_hand=size_map({"S": 2, "M": 4, "L": 2, "XXL": 1}),
        ),
        ALLOCATOR,
    )
    validate_error(response, ApiErrorId.ERR_SIZE_UNITS_MISMATCH)


RECEIPT_SIZE_FAULTS = [
    ("units_do_not_reconcile", 20, {"S": 4, "M": 7, "L": 6, "XL": 2},
     ApiErrorId.ERR_SIZE_UNITS_MISMATCH),
    ("size_code_absent_from_the_curve", 20, {"S": 4, "M": 7, "L": 6, "XL": 2, "XXL": 1},
     ApiErrorId.ERR_SIZE_CODE_UNKNOWN),
]


@pytest.mark.parametrize(
    "size_fault, units_received, mix, expected_error_id",
    RECEIPT_SIZE_FAULTS,
    ids=[case[0] for case in RECEIPT_SIZE_FAULTS],
)
def test_booking_a_receipt_keeps_the_two_size_codes_apart(
    api, size_array_scenario, size_fault, units_received, mix, expected_error_id
):
    """The DC booking runs the same pair of size validations as opening stock and
    reports the same two distinct codes.

    "the sum of the `units` entries in `size_received` must equal `units_received`
    exactly or the booking is refused with `ERR_SIZE_UNITS_MISMATCH`, and every
    `size_code` must exist in the SKU's size curve or it is refused with
    `ERR_SIZE_CODE_UNKNOWN`"

    Design: Corner/errors/size_array_rejections_keep_four_codes_apart_and_in_priority_order
    """
    response = api.create_receipt(
        create_receipt_payload(
            size_array_scenario["program"]["id"],
            size_array_scenario["item"]["id"],
            reference="ASN-7002",
            units_received=units_received,
            size_received=size_map(mix),
        ),
        ALLOCATOR,
    )
    validate_error(response, expected_error_id)


@pytest.mark.parametrize(
    "size_fault, units_received, mix, expected_error_id",
    RECEIPT_SIZE_FAULTS,
    ids=[case[0] for case in RECEIPT_SIZE_FAULTS],
)
def test_a_recount_runs_the_same_two_size_validations(
    api, size_array_scenario, size_fault, units_received, mix, expected_error_id
):
    """Correcting a DC count is not a back door around the size rules: the recount
    reports the same two codes the booking would have reported.

    "The two size validations apply exactly as they do at booking."

    "the sum of the `units` entries in `size_received` must equal `units_received`
    exactly or the booking is refused with `ERR_SIZE_UNITS_MISMATCH`, and every
    `size_code` must exist in the SKU's size curve or it is refused with
    `ERR_SIZE_CODE_UNKNOWN`"

    Design: Corner/errors/size_array_rejections_keep_four_codes_apart_and_in_priority_order
    """
    response = api.adjust_receipt(
        size_array_scenario["receipt"]["id"],
        {
            "units_received": units_received,
            "size_received": size_map(mix),
            "adjustment_reason": "DC recount",
        },
        ALLOCATOR,
    )
    validate_error(response, expected_error_id)


def test_a_refused_size_array_leaves_the_receipt_ledger_untouched(
    api, size_array_scenario
):
    """A rejected recount changes nothing at all: the booked count, the size mix
    and the receipt's version all stand exactly where the booking left them.

    "The two size validations apply exactly as they do at booking."

    "On success the receipt's `version` advances by one"

    Design: Corner/errors/size_array_rejections_keep_four_codes_apart_and_in_priority_order
    """
    receipt = size_array_scenario["receipt"]
    validate_error(
        api.adjust_receipt(
            receipt["id"],
            {
                "units_received": 20,
                "size_received": size_map({"S": 4, "M": 7, "L": 6, "XL": 2}),
                "adjustment_reason": "DC recount",
            },
            ALLOCATOR,
        ),
        ApiErrorId.ERR_SIZE_UNITS_MISMATCH,
    )

    unchanged = validate_success(api.get_receipt(receipt["id"], ALLOCATOR))
    assert unchanged["units_received"] == 20
    assert unchanged["units_unallocated"] == 20
    assert unchanged["version"] == receipt["version"], (
        "a refused recount must not advance the receipt's version"
    )
    assert units_by_size(unchanged["size_received"]) == {"S": 4, "M": 7, "L": 6, "XL": 3}


TWO_STORE_SPECS = [
    {
        "store_code": "0101",
        "grade": "A",
        "grade_index_bp": 13000,
        "cluster_code": "URBAN",
        "freight_flat_usd": 41.00,
        "historical_sell_through_bp": 6500,
    },
    {
        "store_code": "0102",
        "grade": "B",
        "grade_index_bp": 10000,
        "cluster_code": "URBAN",
        "freight_flat_usd": 38.00,
        "historical_sell_through_bp": 5800,
    },
]
TWO_FIXTURE_SPECS = {
    "0101": {
        "fixture_count": 4,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 6,
    },
    "0102": {
        "fixture_count": 2,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 2,
    },
}
TWO_POSITION_SPECS = {
    "0101": {
        "on_hand_units": 6,
        "size_on_hand": [
            {"size_code": "S", "units": 0},
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 2},
            {"size_code": "XL", "units": 0},
        ],
        "min_units": 12,
        "max_units": 48,
        "weekly_forecast_units": 9,
        "trailing_4wk_sales_units": 30,
    },
    "0102": {
        "on_hand_units": 20,
        "size_on_hand": [
            {"size_code": "S", "units": 5},
            {"size_code": "M", "units": 7},
            {"size_code": "L", "units": 6},
            {"size_code": "XL", "units": 2},
        ],
        "min_units": 8,
        "max_units": 24,
        "weekly_forecast_units": 5,
        "trailing_4wk_sales_units": 16,
    },
}
RECEIPT_TWELVE = {"S": 2, "M": 4, "L": 4, "XL": 2}


def _network_with_no_active_store(api):
    """Both stores hold a position for the SKU but neither is ACTIVE any more."""
    scenario = setup_network(
        store_specs=TWO_STORE_SPECS,
        fixture_specs=TWO_FIXTURE_SPECS,
        position_specs=TWO_POSITION_SPECS,
    )
    validate_success(
        api.set_store_status(
            scenario["stores"]["0101"]["id"], {"target_status": "REMODEL"}, PLANNER
        )
    )
    validate_success(
        api.set_store_status(
            scenario["stores"]["0102"]["id"], {"target_status": "CLOSING"}, PLANNER
        )
    )
    return scenario


def _network_with_no_position(api):
    """Both stores are ACTIVE but no position exists for the receipt's SKU."""
    return setup_network(
        store_specs=TWO_STORE_SPECS,
        fixture_specs=TWO_FIXTURE_SPECS,
        create_positions=False,
    )


@pytest.mark.parametrize(
    "filter_failure, build_network",
    [
        ("no_store_is_active", _network_with_no_active_store),
        ("no_position_exists_for_the_sku", _network_with_no_position),
    ],
    ids=["no_store_is_active", "no_position_exists_for_the_sku"],
)
def test_propose_refuses_when_no_store_survives_the_candidate_filter(
    api, filter_failure, build_network
):
    """Each independent limb of the candidate filter empties the candidate set on
    its own, and an empty candidate set is reported as an eligibility failure.

    "And at least one store must survive the candidate filter, or the request is
    refused with `ERR_NO_ELIGIBLE_STORES`."

    "A store enters the candidate set only when its `status` is `ACTIVE` — a
    `REMODEL`, `CLOSING` or `CLOSED` store never does — only when a store position
    already exists for that store and the receipt's SKU"

    Design: Corner/errors/propose_separates_an_empty_candidate_set_from_a_zero_need_network
    """
    reset_clock()
    scenario = build_network(api)
    receipt = create_receipt(
        scenario["program"]["id"],
        scenario["item"]["id"],
        reference="ASN-8001",
        units_received=12,
        size_received=size_map(RECEIPT_TWELVE),
    )
    run = create_run(receipt["id"])

    validate_error(
        api.propose_run(run["id"], ALLOCATOR), ApiErrorId.ERR_NO_ELIGIBLE_STORES
    )


@pytest.fixture
def zero_need_scenario():
    """One ACTIVE store whose pipeline exactly covers its four-week target, so the
    store is a candidate but its need is zero. The second store is ACTIVE with a
    shelf plan but holds no position for the SKU, so it never enters the filter."""
    reset_clock()
    scenario = setup_network(
        store_specs=TWO_STORE_SPECS,
        fixture_specs=TWO_FIXTURE_SPECS,
        position_specs={
            "0101": {
                "on_hand_units": 20,
                "size_on_hand": [
                    {"size_code": "S", "units": 6},
                    {"size_code": "M", "units": 7},
                    {"size_code": "L", "units": 5},
                    {"size_code": "XL", "units": 2},
                ],
                "on_order_units": 0,
                "min_units": 8,
                "max_units": 40,
                "weekly_forecast_units": 5,
                "trailing_4wk_sales_units": 20,
            },
        },
    )
    scenario["receipt"] = create_receipt(
        scenario["program"]["id"],
        scenario["item"]["id"],
        reference="ASN-8002",
        units_received=12,
        size_received=size_map(RECEIPT_TWELVE),
    )
    scenario["run"] = create_run(scenario["receipt"]["id"])
    return scenario


def test_propose_refuses_a_candidate_network_whose_total_need_is_zero(
    api, zero_need_scenario
):
    """A store may pass the candidate filter and still ask for nothing: its
    four-week target is exactly covered by its pipeline, so its need is zero and
    the proposal has nowhere to place the pool.

    "The proration candidate set is the candidate stores whose `need_units` is
    greater than zero; if that set is empty the proposal is refused with
    `ERR_NO_ELIGIBLE_STORES`, and if the total need summed across the set is zero
    the proposal is refused with `ERR_ZERO_NETWORK_NEED`."

    "`need_units` is the greater of zero and the target minus the pipeline"

    Both named outcomes describe this single-candidate, zero-need network, so
    either identifier is accepted here while the refusal itself is required.

    Design: Corner/errors/propose_separates_an_empty_candidate_set_from_a_zero_need_network
    """
    response = api.propose_run(zero_need_scenario["run"]["id"], ALLOCATOR)
    actual = validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_ZERO_NETWORK_NEED, ApiErrorId.ERR_NO_ELIGIBLE_STORES],
    )
    # PRD §2.10/§5 pin a distinct status per identifier: ERR_ZERO_NETWORK_NEED is
    # 409 (rung 31) while ERR_NO_ELIGIBLE_STORES is 422 (rung 30).
    assert response.status_code == HTTP_STATUS_CODES[ApiErrorId(actual)], (
        f"{actual} must carry the HTTP status the PRD pairs with it"
    )


def test_a_refused_proposal_leaves_the_run_and_the_receipt_pool_intact(
    api, zero_need_scenario
):
    """The refusal is not a state transition: the run stays in DRAFT with nothing
    proposed, no line exists, and every received unit is still unallocated.

    "`units_proposed` is the sum of the lines' proposed units and is 0 while the
    run is `DRAFT`"

    "A newly booked receipt opens in `STAGED` with `units_committed` at 0 and
    `units_unallocated` equal to `units_received`"

    Design: Corner/errors/propose_separates_an_empty_candidate_set_from_a_zero_need_network
    """
    run_id = zero_need_scenario["run"]["id"]
    validate_error_is_one_of(
        api.propose_run(run_id, ALLOCATOR),
        [ApiErrorId.ERR_ZERO_NETWORK_NEED, ApiErrorId.ERR_NO_ELIGIBLE_STORES],
    )

    run = validate_success(api.get_allocation_run(run_id, ALLOCATOR))
    assert run["status"] == "DRAFT", "a refused proposal must not move the run"
    assert run["units_proposed"] == 0
    assert lines_for_run(run_id) == [], "a refused proposal must materialise no line"

    receipt = validate_success(
        api.get_receipt(zero_need_scenario["receipt"]["id"], ALLOCATOR)
    )
    assert receipt["units_committed"] == 0
    assert receipt["units_unallocated"] == receipt["units_received"] == 12


def test_raising_the_forecast_turns_the_zero_need_network_into_a_spread(
    api, zero_need_scenario
):
    """Nothing about the network was ineligible — only its need was zero. Lifting
    the weekly forecast from 5 to 8 raises the four-week target from 20 to 32 over
    an unchanged pipeline of 20, and the same run then places the whole pool.

    "weekly demand is the position's `weekly_forecast_units` multiplied by the lift
    in effect for that store"

    "The pipeline under this basis is the position's `available_units` plus its
    `in_transit_units` plus its `on_order_units`"

    "`need_units` is the greater of zero and the target minus the pipeline"

    "applies the need ceiling, taking the lesser of the floor share and the store's
    own need"

    "`eligible_store_count` is the number of stores that entered the proration
    candidate set at proposal time"

    Design: Corner/errors/propose_separates_an_empty_candidate_set_from_a_zero_need_network
    """
    run_id = zero_need_scenario["run"]["id"]
    validate_error_is_one_of(
        api.propose_run(run_id, ALLOCATOR),
        [ApiErrorId.ERR_ZERO_NETWORK_NEED, ApiErrorId.ERR_NO_ELIGIBLE_STORES],
    )

    position = zero_need_scenario["positions"]["0101"]
    validate_success(
        api.patch_store_position(
            position["id"], {"weekly_forecast_units": 8}, ALLOCATOR
        )
    )

    run = validate_success(api.propose_run(run_id, ALLOCATOR))
    assert run["status"] == "PROPOSED"
    assert run["eligible_store_count"] == 1, (
        "only the store holding a position for the SKU may enter the candidate set"
    )
    assert run["units_proposed"] == 12
    assert run["unallocated_remainder_units"] == 0

    line = line_for_store(run_id, zero_need_scenario["stores"]["0101"]["id"])
    assert line["need_units"] == 12, "a target of 32 over a pipeline of 20 needs 12"
    assert line["units_proposed"] == 12
    assert line["capacity_capped_units"] == 0, (
        "a headroom of 28 units cannot clip a 12-unit allocation"
    )
    assert sum(entry["units"] for entry in line["size_breakdown"]) == 12


POOL_POSITION_SPECS = {
    "0101": {
        "on_hand_units": 6,
        "size_on_hand": [
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 2},
        ],
        "on_order_units": 4,
        "min_units": 12,
        "max_units": 48,
        "weekly_forecast_units": 9,
        "trailing_4wk_sales_units": 30,
    },
    "0102": {
        "on_hand_units": 2,
        "size_on_hand": [
            {"size_code": "M", "units": 1},
            {"size_code": "L", "units": 1},
        ],
        "on_order_units": 0,
        "min_units": 8,
        "max_units": 24,
        "weekly_forecast_units": 3,
        "trailing_4wk_sales_units": 6,
    },
}


def _recount(api, receipt_id, units_received, mix):
    return api.adjust_receipt(
        receipt_id,
        {
            "units_received": units_received,
            "size_received": size_map(mix),
            "adjustment_reason": "DC recount",
        },
        ALLOCATOR,
    )


@pytest.fixture
def pool_ceiling_scenario():
    """A 60-unit receipt with 36 units already committed by a first run, leaving a
    pool of 24 unallocated units and a floor of 36 under any downward recount."""
    reset_clock()
    scenario = setup_network(
        store_specs=TWO_STORE_SPECS,
        fixture_specs=TWO_FIXTURE_SPECS,
        position_specs=POOL_POSITION_SPECS,
    )
    scenario["receipt"] = create_receipt(
        scenario["program"]["id"],
        scenario["item"]["id"],
        reference="ASN-9101",
        units_received=60,
        size_received=size_map({"S": 12, "M": 21, "L": 18, "XL": 9}),
    )
    first_run = create_proposed_run(scenario["receipt"]["id"])
    scenario["first_run"] = get_success_data(
        api_client.commit_run(first_run["id"], MANAGER)
    )
    assert scenario["first_run"]["units_committed"] == 36, (
        "setup expects a first commit of 26 units to 0101 and 10 units to 0102"
    )
    return scenario


def test_a_recount_below_the_committed_total_is_refused(api, pool_ceiling_scenario):
    """The DC ledger may never go negative: correcting 60 received units down to 30
    while 36 are already committed is refused, and the receipt is left alone.

    "A correction that would leave `units_committed` above the corrected
    `units_received` is refused outright with `ERR_RECEIPT_UNITS_EXCEEDED` — the
    ledger may never go negative."

    Design: Corner/errors/receipt_pool_ceiling_fires_from_the_commit_side_and_the_recount_side
    """
    receipt_id = pool_ceiling_scenario["receipt"]["id"]
    validate_error(
        _recount(api, receipt_id, 30, {"S": 6, "M": 11, "L": 9, "XL": 4}),
        ApiErrorId.ERR_RECEIPT_UNITS_EXCEEDED,
    )

    receipt = validate_success(api.get_receipt(receipt_id, ALLOCATOR))
    assert receipt["units_received"] == 60, "a refused recount must not book anything"
    assert receipt["units_committed"] == 36
    assert receipt["units_unallocated"] == 24


def test_a_recount_down_to_the_committed_total_is_accepted(api, pool_ceiling_scenario):
    """Correcting down to 40 leaves the committed 36 intact, so the correction is
    legal and only the unallocated pool shrinks.

    "`units_unallocated` is re-derived as the corrected `units_received` minus the
    unchanged `units_committed`"

    "The receipt's `status` itself never changes as a result of a recount."

    Design: Corner/errors/receipt_pool_ceiling_fires_from_the_commit_side_and_the_recount_side
    """
    receipt_id = pool_ceiling_scenario["receipt"]["id"]
    corrected = validate_success(
        _recount(api, receipt_id, 40, {"S": 8, "M": 14, "L": 12, "XL": 6})
    )
    assert corrected["units_received"] == 40
    assert corrected["units_committed"] == 36
    assert corrected["units_unallocated"] == 4
    assert corrected["status"] == "ALLOCATING", (
        "a recount never moves the receipt's own status"
    )


def test_the_same_code_fires_from_the_commit_side_when_a_recount_strands_a_spread(
    api, pool_ceiling_scenario
):
    """A second spread sized against a pool of 4 becomes unaffordable when a later
    recount drops the pool to 0, and the commit — not the recount — is what refuses
    it. The refusal leaves the run PROPOSED so the pool can be restored.

    "a downward recount can strand a spread that has already been proposed, because
    that spread's lines were sized against the older, larger pool"

    "Fifth, the total across the run of `units_proposed` must not exceed the
    receipt's current `units_unallocated`, or the commit is refused with
    `ERR_RECEIPT_UNITS_EXCEEDED` — this is the rung that catches a spread stranded
    by a downward recount."

    Design: Corner/errors/receipt_pool_ceiling_fires_from_the_commit_side_and_the_recount_side
    """
    receipt_id = pool_ceiling_scenario["receipt"]["id"]
    validate_success(_recount(api, receipt_id, 40, {"S": 8, "M": 14, "L": 12, "XL": 6}))

    second_run = create_proposed_run(receipt_id)
    assert second_run["units_proposed"] == 4, (
        "the second spread may only size itself against the 4 remaining units"
    )

    validate_success(_recount(api, receipt_id, 36, {"S": 7, "M": 13, "L": 11, "XL": 5}))
    stranded = validate_success(api.get_receipt(receipt_id, ALLOCATOR))
    assert stranded["units_unallocated"] == 0

    validate_error(
        api.commit_run(second_run["id"], MANAGER),
        ApiErrorId.ERR_RECEIPT_UNITS_EXCEEDED,
    )
    unchanged = validate_success(api.get_allocation_run(second_run["id"], ALLOCATOR))
    assert unchanged["status"] == "PROPOSED", (
        "a refused commit must leave the run available to commit again"
    )
    assert unchanged["units_committed"] == 0


def test_restoring_the_pool_lets_the_stranded_spread_commit(api, pool_ceiling_scenario):
    """Recounting back up to 40 restores the 4-unit pool the second spread was sized
    against, the commit then passes the pool ceiling, and the receipt lands
    ALLOCATED with a program ledger that shows no drift.

    "Fifth, the total across the run of `units_proposed` must not exceed the
    receipt's current `units_unallocated`, or the commit is refused with
    `ERR_RECEIPT_UNITS_EXCEEDED`"

    "A commit that leaves `units_unallocated` at 0 once the committed lines are
    booked drives the receipt `ALLOCATING → ALLOCATED`"

    "`open_reserve_units` is `total_units_received` minus `total_units_committed`"

    Design: Corner/errors/receipt_pool_ceiling_fires_from_the_commit_side_and_the_recount_side
    """
    receipt_id = pool_ceiling_scenario["receipt"]["id"]
    validate_success(_recount(api, receipt_id, 40, {"S": 8, "M": 14, "L": 12, "XL": 6}))
    second_run = create_proposed_run(receipt_id)
    validate_success(_recount(api, receipt_id, 36, {"S": 7, "M": 13, "L": 11, "XL": 5}))
    validate_error(
        api.commit_run(second_run["id"], MANAGER),
        ApiErrorId.ERR_RECEIPT_UNITS_EXCEEDED,
    )

    validate_success(_recount(api, receipt_id, 40, {"S": 8, "M": 14, "L": 12, "XL": 6}))
    committed = validate_success(api.commit_run(second_run["id"], MANAGER))
    assert committed["status"] == "COMMITTED"
    assert committed["units_committed"] == 4

    receipt = validate_success(api.get_receipt(receipt_id, ALLOCATOR))
    assert receipt["units_received"] == 40
    assert receipt["units_committed"] == 40
    assert receipt["units_unallocated"] == 0
    assert receipt["status"] == "ALLOCATED"

    program = validate_success(
        api.get_program(pool_ceiling_scenario["program"]["id"], PLANNER)
    )
    assert program["total_units_received"] == 40
    assert program["total_units_committed"] == 40
    assert program["open_reserve_units"] == 0
