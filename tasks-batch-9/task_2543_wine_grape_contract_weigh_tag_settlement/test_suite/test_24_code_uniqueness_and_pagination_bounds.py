"""Seven uniqueness constraints and one pagination bracket. Two of the seven are composite, so
a label that repeats under a different owner is a different key entirely; and the page-size
bracket owns the only 400 in the catalogue, accepted inclusively at both ends.
"""
from test_helpers import (
    COORDINATOR,
    MANAGER,
    ApiErrorId,
    create_allocation,
    create_block,
    create_grower,
    create_quality_spec,
    move_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"

PRODUCER_A = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}
PRODUCER_B = {
    "name": "Stonegate Ranch",
    "license_number": "PL-44822",
    "region_code": "NAPA-NORTH",
}
BLOCK_A = {
    "block_code": "B-12",
    "varietal": "CABERNET_SAUVIGNON",
    "acres": 20.000,
    "expected_yield_tons_per_acre": 2.000,
    "ava_code": "NAPA-VALLEY",
}
A_DIFFERENT_BLOCK_UNDER_THE_SAME_CODE = {
    "block_code": "B-12",
    "varietal": "MERLOT",
    "acres": 5.000,
    "expected_yield_tons_per_acre": 1.000,
    "ava_code": "NAPA-VALLEY",
}
ONE_HUNDRED_PCT = [
    {"installment_no": 1, "pct_of_settlement": 100.0, "due_offset_days": 30, "lien_protected": True}
]


def _two_producers_and_the_reference_tables(api) -> dict:
    """Two producers, one block under the first, one specification, one lane, one crew, and two
    contracts for the first producer — the second of which has no allocation yet."""
    move_clock(CLOCK_PINNED_AT)
    ctx = {
        "grower_a": create_grower(**PRODUCER_A),
        "grower_b": create_grower(**PRODUCER_B),
    }
    ctx["block_a"] = create_block(ctx["grower_a"]["id"], **BLOCK_A)
    ctx["spec"] = create_quality_spec(spec_code="CAB-STD-2026", min_brix_pick_call=21.0)
    ctx["lane"] = validate_success(
        api.create_lane(
            {
                "lane_code": "L1",
                "daily_capacity_tons": 80.000,
                "turnaround_buffer_minutes": 30,
                "max_load_tons": 40.000,
            },
            COORDINATOR,
        ),
        201,
    )
    ctx["crew"] = validate_success(
        api.create_sampling_crew(
            {"crew_code": "SC-1", "region_code": "NAPA-NORTH", "max_concurrent_visits": 2},
            COORDINATOR,
        ),
        201,
    )
    for key, code in (("contract_a", "GC-UNIQ"), ("contract_b", "GC-UNIQ-2")):
        ctx[key] = validate_success(
            api.create_grape_contract(_a_tonnage_contract(ctx["grower_a"]["id"], ctx, code), MANAGER),
            201,
        )
    create_allocation(ctx["contract_a"]["id"], ctx["block_a"]["id"])
    return ctx


def _a_tonnage_contract(grower_id: str, ctx: dict, contract_code: str) -> dict:
    return {
        "grower_id": grower_id,
        "quality_spec_id": ctx["spec"]["id"],
        "contract_code": contract_code,
        "contract_basis": "TONNAGE",
        "committed_tons": 40.000,
        "base_price_per_ton_cents": 450000,
        "over_delivery_policy": "ACCEPT_AT_CONTRACT",
        "term_start_vintage": 2026,
        "term_end_vintage": 2026,
        "installment_plan": ONE_HUNDRED_PCT,
    }


# --- One error id, seven constraints, two of them composite ---------------------------


def test_a_repeated_producer_licence_is_refused(api):
    """The licence identifier is the producer's real-world key, so a second registration under
    the same licence is refused even with a different name and a different region.

    PRD: "A duplicate `license_number` is refused with `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/uniqueness_violations_return_409_duplicate_code
    """
    _two_producers_and_the_reference_tables(api)

    validate_error(
        api.create_grower(
            {
                "name": "Another Name Entirely",
                "license_number": "PL-44821",
                "region_code": "SONOMA-COAST",
            },
            MANAGER,
        ),
        ApiErrorId.ERR_DUPLICATE_CODE.value,
        409,
    )


def test_a_repeated_specification_code_is_refused_however_different_its_thresholds(api):
    """Every threshold differs, so only the code can be the reason.

    PRD: "A duplicate `spec_code` is refused with `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/uniqueness_violations_return_409_duplicate_code
    """
    _two_producers_and_the_reference_tables(api)

    validate_error(
        api.create_quality_spec(
            {
                "spec_code": "CAB-STD-2026",
                "min_brix_accept": 21.0,
                "brix_bonus_start": 25.0,
                "brix_penalty_start": 23.0,
                "rot_rejection_pct": 7.0,
            },
            MANAGER,
        ),
        ApiErrorId.ERR_DUPLICATE_CODE.value,
        409,
    )


def test_a_contract_code_is_unique_across_the_winery_not_per_producer(api):
    """The second producer has never been party to GC-UNIQ, and the code is still taken.

    PRD: "carries a winery-facing `contract_code` of 3 to 32 characters that must be unique
    across contracts"

    Design: Corner/validations/uniqueness_violations_return_409_duplicate_code
    """
    ctx = _two_producers_and_the_reference_tables(api)

    validate_error(
        api.create_grape_contract(
            _a_tonnage_contract(ctx["grower_b"]["id"], ctx, "GC-UNIQ"), MANAGER
        ),
        ApiErrorId.ERR_DUPLICATE_CODE.value,
        409,
    )


def test_the_two_receiving_side_reference_codes_are_unique_as_well(api):
    """The lane and the crew are plain reference rows, and both still carry the constraint.

    PRD: "Lanes are listed with an optional `status` filter, and a duplicate `lane_code` is
    `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/uniqueness_violations_return_409_duplicate_code
    """
    _two_producers_and_the_reference_tables(api)

    validate_error(
        api.create_lane({"lane_code": "L1", "daily_capacity_tons": 40.000}, COORDINATOR),
        ApiErrorId.ERR_DUPLICATE_CODE.value,
        409,
    )
    validate_error(
        api.create_sampling_crew(
            {"crew_code": "SC-1", "region_code": "SONOMA-COAST"}, COORDINATOR
        ),
        ApiErrorId.ERR_DUPLICATE_CODE.value,
        409,
    )


def test_a_block_label_is_unique_only_within_its_own_producer(api):
    """The composite half: B-12 is taken under the first producer and free under the second, so
    a globally unique block code would refuse a perfectly legal registration.

    PRD: "a `block_code` that is the grower-scoped label printed on the weigh tag and must be
    unique within that producer"

    Design: Corner/validations/uniqueness_violations_return_409_duplicate_code
    """
    ctx = _two_producers_and_the_reference_tables(api)

    validate_error(
        api.create_vineyard_block(
            dict(A_DIFFERENT_BLOCK_UNDER_THE_SAME_CODE, grower_id=ctx["grower_a"]["id"]), MANAGER
        ),
        ApiErrorId.ERR_DUPLICATE_CODE.value,
        409,
    )

    under_the_other_producer = validate_success(
        api.create_vineyard_block(
            dict(A_DIFFERENT_BLOCK_UNDER_THE_SAME_CODE, grower_id=ctx["grower_b"]["id"]), MANAGER
        ),
        201,
    )
    assert under_the_other_producer["block_code"] == "B-12"
    assert under_the_other_producer["grower_id"] == ctx["grower_b"]["id"]


def test_a_block_may_be_committed_once_per_contract_and_to_several_contracts(api):
    """The other composite half: repeating the pair is refused, while the same block on a second
    agreement is a different key — which is exactly how one block feeds two contracts.

    PRD: "The same block may be committed to a given contract only once: a repeated
    contract-and-block pair is refused with `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/uniqueness_violations_return_409_duplicate_code
    """
    ctx = _two_producers_and_the_reference_tables(api)

    validate_error(
        api.create_allocation(
            {"contract_id": ctx["contract_a"]["id"], "block_id": ctx["block_a"]["id"]}, MANAGER
        ),
        ApiErrorId.ERR_DUPLICATE_CODE.value,
        409,
    )

    on_the_second_contract = validate_success(
        api.create_allocation(
            {"contract_id": ctx["contract_b"]["id"], "block_id": ctx["block_a"]["id"]}, MANAGER
        ),
        201,
    )
    assert on_the_second_contract["block_id"] == ctx["block_a"]["id"]
    assert on_the_second_contract["contract_id"] == ctx["contract_b"]["id"]


# --- The page-size bracket, refused outside and accepted on both edges -----------------


def _two_producers_only() -> dict:
    """Just enough rows that an accepted page is non-empty and a one-row page leaves something
    behind."""
    move_clock(CLOCK_PINNED_AT)
    return {
        "grower_a": create_grower(**PRODUCER_A),
        "grower_b": create_grower(**PRODUCER_B),
    }


def test_a_page_size_of_zero_is_refused_with_the_catalogues_only_four_hundred(api):
    """The pagination bracket has its own status code, deliberately distinct from the 422 that
    every other shape problem returns.

    PRD: "A `limit` outside the inclusive range 1 through 100, or an `offset` that is negative
    or not an integer, is refused with `ERR_INVALID_PAGINATION` and HTTP 400 — note the
    deliberate distinction from the 422 used for general request-shape problems."

    Design: Corner/validations/pagination_bounds_are_enforced_and_return_400
    """
    _two_producers_only()

    validate_error(
        api.list_growers(MANAGER, params={"limit": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )


def test_a_page_size_above_one_hundred_is_refused(api):
    """101 is one past the ceiling.

    PRD: "`limit` caps the number of rows returned; it defaults to 10 when omitted, may not be
    smaller than 1, and may not be larger than 100."

    Design: Corner/validations/pagination_bounds_are_enforced_and_return_400
    """
    _two_producers_only()

    validate_error(
        api.list_growers(MANAGER, params={"limit": 101}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )


def test_a_negative_offset_is_refused(api):
    """The skip count is a count, so it cannot run backwards.

    PRD: "`offset` is the number of rows to skip before the page begins; it defaults to 0 and
    may not be negative."

    Design: Corner/validations/pagination_bounds_are_enforced_and_return_400
    """
    _two_producers_only()

    validate_error(
        api.list_growers(MANAGER, params={"offset": -1}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )


def test_the_bracket_is_enforced_on_every_listing_and_not_just_on_producers(api):
    """The rule is a property of collection reads in general, so a different collection refuses
    the same page size the same way.

    PRD: "Ranks 7 and 8 are request shape: (7) required fields present, JSON types correct, enum
    values inside their declared sets, numeric ranges and decimal-place limits respected,
    ISO-8601 instants parseable, and any window's `window_end` strictly after its
    `window_start` — else `ERR_VALIDATION` with HTTP 422, on every endpoint; (8) pagination
    bounds, else `ERR_INVALID_PAGINATION` with HTTP 400, on every list endpoint."

    Design: Corner/validations/pagination_bounds_are_enforced_and_return_400
    """
    _two_producers_only()

    validate_error(
        api.list_vineyard_blocks(MANAGER, params={"limit": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )


def test_the_smallest_legal_page_is_accepted_and_reports_what_it_left_behind(api):
    """A page size of one is inside the inclusive range, and the envelope still counts the whole
    filtered set rather than the page.

    PRD: "Every list response repeats `limit` and `offset` in the `meta` object alongside
    `total_count` — the number of rows matching the filter before pagination is applied — and
    `has_more`, which is true exactly when rows remain beyond the current page."

    Design: Corner/validations/pagination_bounds_are_enforced_and_return_400
    """
    _two_producers_only()

    rows, meta = validate_paginated(api.list_growers(MANAGER, params={"limit": 1}))
    assert len(rows) == 1
    assert meta["limit"] == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_the_largest_legal_page_is_accepted_and_exhausts_the_collection(api):
    """100 is the inclusive ceiling, so it is admitted and there is nothing beyond the page.

    PRD: "A `limit` outside the inclusive range 1 through 100, or an `offset` that is negative
    or not an integer, is refused with `ERR_INVALID_PAGINATION` and HTTP 400 — note the
    deliberate distinction from the 422 used for general request-shape problems."

    Design: Corner/validations/pagination_bounds_are_enforced_and_return_400
    """
    _two_producers_only()

    rows, meta = validate_paginated(api.list_growers(MANAGER, params={"limit": 100}))
    assert len(rows) == 2
    assert meta["limit"] == 100
    assert meta["has_more"] is False


def test_the_lower_edge_of_the_skip_count_is_accepted(api):
    """Zero is the default and also a legal explicit value, so supplying it changes nothing.

    PRD: "`offset` is the number of rows to skip before the page begins; it defaults to 0 and
    may not be negative."

    Design: Corner/validations/pagination_bounds_are_enforced_and_return_400
    """
    _two_producers_only()

    rows, meta = validate_paginated(api.list_growers(MANAGER, params={"offset": 0}))
    assert len(rows) == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
