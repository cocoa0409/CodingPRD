"""What the API refuses before it does any work: an identifier that resolves to nothing,
a parent that does not exist, a field that was never sent, and a value whose shape the
declaration does not allow."""
from test_helpers import (
    CLERK,
    COORDINATOR,
    MANAGER,
    SCALE_OPERATOR,
    ApiErrorId,
    create_block,
    create_contract,
    create_crew,
    create_grape_contract_payload,
    create_grower,
    create_quality_spec,
    create_sampling_visit_payload,
    create_vineyard_block_payload,
    create_weigh_tag_payload,
    get_success_data,
    move_clock,
    single_installment_plan,
    validate_error,
    validate_paginated,
)

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"

# Syntactically valid and deliberately unused.
UNUSED_ID = "00000000-0000-4000-8000-000000000000"

PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}


# --- Thirteen entities, thirteen distinct not-found identifiers -------------------


def _path_reads(api) -> tuple:
    """One read per resource family, each addressed by the same unused identifier and
    each performed by a role the endpoint admits."""
    return (
        (api.get_grower(UNUSED_ID, MANAGER), ApiErrorId.ERR_GROWER_NOT_FOUND),
        (api.get_vineyard_block(UNUSED_ID, MANAGER), ApiErrorId.ERR_BLOCK_NOT_FOUND),
        (api.get_quality_spec(UNUSED_ID, MANAGER), ApiErrorId.ERR_QUALITY_SPEC_NOT_FOUND),
        (api.get_grape_contract(UNUSED_ID, MANAGER), ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api.get_allocation(UNUSED_ID, MANAGER), ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        (api.get_lane(UNUSED_ID, COORDINATOR), ApiErrorId.ERR_LANE_NOT_FOUND),
        (api.get_sampling_crew(UNUSED_ID, COORDINATOR), ApiErrorId.ERR_CREW_NOT_FOUND),
        (api.get_sampling_visit(UNUSED_ID, COORDINATOR), ApiErrorId.ERR_SAMPLING_VISIT_NOT_FOUND),
        (api.get_pick_call(UNUSED_ID, COORDINATOR), ApiErrorId.ERR_PICK_CALL_NOT_FOUND),
        (api.get_delivery_appointment(UNUSED_ID, COORDINATOR), ApiErrorId.ERR_APPOINTMENT_NOT_FOUND),
        (api.get_weigh_tag(UNUSED_ID, SCALE_OPERATOR), ApiErrorId.ERR_WEIGH_TAG_NOT_FOUND),
        (api.get_settlement_line(UNUSED_ID, CLERK), ApiErrorId.ERR_SETTLEMENT_LINE_NOT_FOUND),
        (api.get_installment(UNUSED_ID, CLERK), ApiErrorId.ERR_INSTALLMENT_NOT_FOUND),
    )


def test_every_resource_family_reports_its_own_not_found_identifier(api):
    """Thirteen reads against an empty database return thirteen different error
    identifiers, so a single shared not-found code cannot satisfy the catalogue.

    PRD: "The catalogue provides a distinct not-found identifier per resource family:
    `ERR_GROWER_NOT_FOUND` for `growerId` and for a `grower_id` in a body,
    `ERR_BLOCK_NOT_FOUND` for `blockId` and `block_id`, `ERR_QUALITY_SPEC_NOT_FOUND` for
    `specId` and `quality_spec_id`, `ERR_CONTRACT_NOT_FOUND` for `contractId` and
    `contract_id`, `ERR_ALLOCATION_NOT_FOUND` for `allocationId`, `ERR_LANE_NOT_FOUND` for
    `laneId` and `lane_id`, `ERR_CREW_NOT_FOUND` for `crewId` and `crew_id`,
    `ERR_SAMPLING_VISIT_NOT_FOUND` for `visitId`, `ERR_PICK_CALL_NOT_FOUND` for `pickCallId`
    and `pick_call_id`, `ERR_APPOINTMENT_NOT_FOUND` for `appointmentId` and `appointment_id`,
    `ERR_WEIGH_TAG_NOT_FOUND` for `tagId` and `weigh_tag_id`, `ERR_SETTLEMENT_LINE_NOT_FOUND`
    for `lineId`, and `ERR_INSTALLMENT_NOT_FOUND` for `installmentId`. All of these carry
    HTTP 404."

    Design: Corner/entities/path_id_not_found_returns_404_for_every_entity
    """
    move_clock(CLOCK_PINNED_AT)

    reported = []
    for response, expected in _path_reads(api):
        validate_error(response, expected.value, 404)
        reported.append(response.json()["data"]["error_id"])

    assert len(reported) == 13
    assert len(set(reported)) == 13, f"the thirteen codes must be distinct, got {reported}"


def test_a_not_found_body_is_an_error_envelope_and_nothing_else(api):
    """Every one of the thirteen refusals answers in the error envelope, carrying an
    identifier and a message but no resource.

    PRD: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/entities/path_id_not_found_returns_404_for_every_entity
    """
    move_clock(CLOCK_PINNED_AT)

    for response, _ in _path_reads(api):
        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}
        assert "id" not in body["data"]
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


# --- A parent named in the body: 404, and the earliest unresolvable field wins -----


def _one_resolvable_producer_and_one_resolvable_spec() -> tuple:
    """So that the resolvable half of each body below is genuinely resolvable."""
    move_clock(CLOCK_PINNED_AT)
    return create_grower(**PRODUCER), create_quality_spec(spec_code="CAB-STD-2026")


def test_a_body_parent_that_does_not_exist_is_not_downgraded_to_a_shape_error(api):
    """Everything about the block body is well formed except the producer it names, and
    the answer is the producer's own 404 rather than a 422 about the field.

    PRD: "Ranks 5 and 6 are existence: (5) every identifier in the URL path resolves,
    checked left to right; (6) every foreign-key identifier in the request body resolves,
    checked in the field order described for the target resource. Both use the
    family-specific not-found identifiers of §2.5 with HTTP 404, and both outrank every
    shape check — a body naming a non-existent lane is a 404, not a 422."

    Design: Corner/entities/body_foreign_key_that_does_not_resolve_returns_404_not_422
    """
    _one_resolvable_producer_and_one_resolvable_spec()

    response = api.create_vineyard_block(
        create_vineyard_block_payload(
            UNUSED_ID, block_code="B-99", varietal="MERLOT", acres=5.000,
            expected_yield_tons_per_acre=2.000, ava_code="NAPA-VALLEY",
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_GROWER_NOT_FOUND.value, 404)


def test_two_unresolvable_parents_report_the_one_described_first(api):
    """A contract names its counterparty before its rulebook, so when neither resolves the
    producer decides the error; once the producer resolves the rulebook decides it.

    PRD: "Foreign-key identifiers arriving in a request body are resolved after the path
    identifiers, in the order in which the fields are described for the target resource in
    §3."

    Design: Corner/entities/body_foreign_key_that_does_not_resolve_returns_404_not_422
    """
    grower, _ = _one_resolvable_producer_and_one_resolvable_spec()

    both_unresolvable = api.create_grape_contract(
        create_grape_contract_payload(
            UNUSED_ID, UNUSED_ID, contract_code="GC-FK", contract_basis="TONNAGE",
            base_price_per_ton_cents=450000, over_delivery_policy="ACCEPT_AT_CONTRACT",
            term_start_vintage=2026, term_end_vintage=2026, committed_tons=40.000,
            installment_plan=single_installment_plan(),
        ),
        MANAGER,
    )
    validate_error(both_unresolvable, ApiErrorId.ERR_GROWER_NOT_FOUND.value, 404)

    spec_unresolvable = api.create_grape_contract(
        create_grape_contract_payload(
            grower["id"], UNUSED_ID, contract_code="GC-FK2", contract_basis="TONNAGE",
            base_price_per_ton_cents=450000, over_delivery_policy="ACCEPT_AT_CONTRACT",
            term_start_vintage=2026, term_end_vintage=2026, committed_tons=40.000,
            installment_plan=single_installment_plan(),
        ),
        MANAGER,
    )
    validate_error(spec_unresolvable, ApiErrorId.ERR_QUALITY_SPEC_NOT_FOUND.value, 404)


def test_a_visit_booking_reports_the_first_of_its_three_parents(api):
    """All three of the visit's parents are unresolvable, and the contract — described
    first — is the one named in the refusal.

    PRD: "The request names the `contract_id` whose specification the reading will be
    judged against, the `block_id` to be sampled, the `crew_id` that will be occupied, and
    the field window as an inclusive `window_start` and an exclusive `window_end`, the
    latter strictly after the former."

    Design: Corner/entities/body_foreign_key_that_does_not_resolve_returns_404_not_422
    """
    _one_resolvable_producer_and_one_resolvable_spec()

    response = api.create_sampling_visit(
        create_sampling_visit_payload(
            UNUSED_ID, UNUSED_ID, UNUSED_ID, "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z"
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, 404)


def test_a_slot_booking_reports_the_pick_call_before_the_lane(api):
    """The call being served is described ahead of the lane being reserved, so an
    unresolvable lane never gets the chance to answer.

    PRD: "The request carries the `pick_call_id` of the acknowledged call being served, the
    `lane_id` of the lane being reserved, the reservation as an inclusive `window_start` and
    exclusive `window_end` with the end strictly after the start, and `planned_tons`, the
    tonnage the producer intends to deliver into the slot, positive with at most 3
    decimals."

    Design: Corner/entities/body_foreign_key_that_does_not_resolve_returns_404_not_422
    """
    _one_resolvable_producer_and_one_resolvable_spec()

    response = api.create_delivery_appointment(
        {
            "pick_call_id": UNUSED_ID,
            "lane_id": UNUSED_ID,
            "window_start": "2026-08-05T14:00:00Z",
            "window_end": "2026-08-05T16:00:00Z",
            "planned_tons": 10.000,
        },
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_PICK_CALL_NOT_FOUND.value, 404)


def test_the_weigh_tags_missing_appointment_outranks_the_version_guard_as_well(api):
    """The tag body names an unresolvable appointment, an unresolvable block, and an
    optimistic version that could never match — and existence still answers first.

    PRD: "Ranks 12 and 13 are the stale-version guards of §2.8: (12)
    `expected_appointment_version` on weigh-tag create, else
    `ERR_STALE_APPOINTMENT_VERSION`; (13) `expected_weigh_tag_version` on grading create,
    else `ERR_STALE_WEIGH_TAG_VERSION`."

    Design: Corner/entities/body_foreign_key_that_does_not_resolve_returns_404_not_422
    """
    _one_resolvable_producer_and_one_resolvable_spec()

    response = api.create_weigh_tag(
        create_weigh_tag_payload(UNUSED_ID, UNUSED_ID, 57000, 1), SCALE_OPERATOR
    )
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value, 404)


def test_none_of_the_refused_creates_left_a_row_behind(api):
    """Six refusals, five collections, and every one of them still empty.

    PRD: "The `data` field contains the resource object or an array of resource objects.
    For 2xx responses with no data, it contains an empty object. Unless otherwise noted,
    operations that create or modify a resource will return the created or updated resource
    object in the data field."

    Design: Corner/entities/body_foreign_key_that_does_not_resolve_returns_404_not_422
    """
    grower, _ = _one_resolvable_producer_and_one_resolvable_spec()

    api.create_vineyard_block(
        create_vineyard_block_payload(
            UNUSED_ID, block_code="B-99", varietal="MERLOT", acres=5.000,
            expected_yield_tons_per_acre=2.000, ava_code="NAPA-VALLEY",
        ),
        MANAGER,
    )
    for spec_id in (UNUSED_ID, UNUSED_ID):
        api.create_grape_contract(
            create_grape_contract_payload(
                UNUSED_ID, spec_id, contract_code="GC-FK", contract_basis="TONNAGE",
                base_price_per_ton_cents=450000, over_delivery_policy="ACCEPT_AT_CONTRACT",
                term_start_vintage=2026, term_end_vintage=2026, committed_tons=40.000,
                installment_plan=single_installment_plan(),
            ),
            MANAGER,
        )
    api.create_sampling_visit(
        create_sampling_visit_payload(
            UNUSED_ID, UNUSED_ID, UNUSED_ID, "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z"
        ),
        COORDINATOR,
    )
    api.create_delivery_appointment(
        {
            "pick_call_id": UNUSED_ID,
            "lane_id": UNUSED_ID,
            "window_start": "2026-08-05T14:00:00Z",
            "window_end": "2026-08-05T16:00:00Z",
            "planned_tons": 10.000,
        },
        COORDINATOR,
    )
    api.create_weigh_tag(create_weigh_tag_payload(UNUSED_ID, UNUSED_ID, 57000, 1), SCALE_OPERATOR)

    assert get_success_data(api.list_vineyard_blocks(MANAGER)) == []
    assert get_success_data(api.list_grape_contracts(MANAGER)) == []
    assert get_success_data(api.list_sampling_visits(COORDINATOR)) == []
    assert get_success_data(api.list_delivery_appointments(COORDINATOR)) == []
    assert get_success_data(api.list_weigh_tags(SCALE_OPERATOR)) == []
    assert grower["id"] is not None


# --- A field that was never sent ---------------------------------------------------


def test_the_state_licence_is_required_and_is_not_defaulted(api):
    """A producer without a licence number is refused on shape; the field has no default to
    fall back on.

    PRD: "Ranks 7 and 8 are request shape: (7) required fields present, JSON types correct,
    enum values inside their declared sets, numeric ranges and decimal-place limits
    respected, ISO-8601 instants parseable, and any window's `window_end` strictly after its
    `window_start` — else `ERR_VALIDATION` with HTTP 422, on every endpoint"

    Design: Corner/entities/missing_required_field_returns_422_validation
    """
    move_clock(CLOCK_PINNED_AT)
    create_grower(**PRODUCER)

    response = api.create_grower({"name": "No Licence Ranch", "region_code": "NAPA-NORTH"}, MANAGER)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_planted_acreage_is_required_on_a_block(api):
    """The producer resolves, so the only thing wrong with the block is the acreage the body
    never carried.

    PRD: "It is created with a `grower_id` naming the producer who farms it, a `block_code`
    that is the grower-scoped label printed on the weigh tag and must be unique within that
    producer, a `varietal` of 3 to 40 characters drawn only from uppercase letters and the
    underscore, the planted `acres` as a positive number with at most 3 decimal places, an
    `expected_yield_tons_per_acre` agronomic estimate likewise positive with at most 3
    decimals, and an `ava_code` of 2 to 24 uppercase letters and hyphens recording the
    American Viticultural Area for appellation reporting."

    Design: Corner/entities/missing_required_field_returns_422_validation
    """
    move_clock(CLOCK_PINNED_AT)
    grower = create_grower(**PRODUCER)

    response = api.create_vineyard_block(
        {
            "grower_id": grower["id"],
            "block_code": "B-1",
            "varietal": "MERLOT",
            "expected_yield_tons_per_acre": 2.000,
            "ava_code": "NAPA-VALLEY",
        },
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_the_bonus_threshold_is_mandatory_and_is_not_inferred_from_the_penalty_one(api):
    """Four of the five mandatory thresholds are present; the missing bonus threshold is not
    quietly derived from the penalty threshold that is.

    PRD: "Five values are mandatory: a `spec_code` of 3 to 32 characters unique across
    specifications, `min_brix_accept` (the minimum graded sugar at receipt, below which the
    load is rejected on quality), `brix_bonus_start` (which must be strictly greater than
    `min_brix_accept`), `brix_penalty_start` (which must be at least `min_brix_accept` and at
    most `brix_bonus_start`), and `rot_rejection_pct` (which must be strictly greater than
    `rot_free_pct`)."

    Design: Corner/entities/missing_required_field_returns_422_validation
    """
    move_clock(CLOCK_PINNED_AT)
    create_grower(**PRODUCER)

    response = api.create_quality_spec(
        {
            "spec_code": "CAB-NOBONUS",
            "min_brix_accept": 20.0,
            "brix_penalty_start": 22.0,
            "rot_rejection_pct": 8.0,
        },
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_the_three_incomplete_bodies_created_nothing(api):
    """The one producer registered in setup is still the only row anywhere; a rejected body
    is never partially stored.

    PRD: "Every list response repeats `limit` and `offset` in the `meta` object alongside
    `total_count` — the number of rows matching the filter before pagination is applied — and
    `has_more`, which is true exactly when rows remain beyond the current page."

    Design: Corner/entities/missing_required_field_returns_422_validation
    """
    move_clock(CLOCK_PINNED_AT)
    grower = create_grower(**PRODUCER)

    api.create_grower({"name": "No Licence Ranch", "region_code": "NAPA-NORTH"}, MANAGER)
    api.create_vineyard_block(
        {
            "grower_id": grower["id"],
            "block_code": "B-1",
            "varietal": "MERLOT",
            "expected_yield_tons_per_acre": 2.000,
            "ava_code": "NAPA-VALLEY",
        },
        MANAGER,
    )
    api.create_quality_spec(
        {
            "spec_code": "CAB-NOBONUS",
            "min_brix_accept": 20.0,
            "brix_penalty_start": 22.0,
            "rot_rejection_pct": 8.0,
        },
        MANAGER,
    )

    rows, meta = validate_paginated(api.list_growers(MANAGER))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [grower["id"]]
    assert get_success_data(api.list_vineyard_blocks(MANAGER)) == []
    assert get_success_data(api.list_quality_specs(MANAGER)) == []


# --- A value whose shape the declaration does not allow ---------------------------


def _one_of_everything_the_shape_probes_need() -> dict:
    """A producer, its rulebook, one block, one crew and one drafted contract, all valid,
    so that each probe below is wrong in exactly one way."""
    move_clock(CLOCK_PINNED_AT)
    grower = create_grower(**PRODUCER)
    spec = create_quality_spec(spec_code="CAB-STD-2026")
    block = create_block(
        grower["id"], block_code="B-12", varietal="CABERNET_SAUVIGNON", acres=20.000,
        expected_yield_tons_per_acre=2.000, ava_code="NAPA-VALLEY",
    )
    crew = create_crew(crew_code="SC-1", region_code=PRODUCER["region_code"], max_concurrent_visits=2)
    contract = create_contract(
        grower["id"], spec["id"], contract_code="GC-SHAPE", contract_basis="TONNAGE",
        base_price_per_ton_cents=450000, over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026, term_end_vintage=2026, committed_tons=40.000,
        installment_plan=single_installment_plan(),
    )
    return {"grower": grower, "spec": spec, "block": block, "crew": crew, "contract": contract}


def test_a_basis_outside_the_declared_set_is_refused(api):
    """`PER_VINE` is a plausible way to buy grapes and is simply not one of the three the
    contract admits.

    PRD: "`contract_basis` is one of `TONNAGE`, `ACREAGE` or `BLOCK`, and it decides which
    tonnage field the request must carry: a `TONNAGE` contract requires `committed_tons` and
    must not carry `contracted_yield_tons_per_acre`; an `ACREAGE` contract requires
    `contracted_yield_tons_per_acre` and must not carry `committed_tons`; a `BLOCK` contract
    must carry neither."

    Design: Corner/entities/enum_range_and_decimal_place_type_constraints_returns_422
    """
    ctx = _one_of_everything_the_shape_probes_need()

    response = api.create_grape_contract(
        create_grape_contract_payload(
            ctx["grower"]["id"], ctx["spec"]["id"], contract_code="GC-ENUM",
            contract_basis="PER_VINE", base_price_per_ton_cents=450000,
            over_delivery_policy="ACCEPT_AT_CONTRACT", term_start_vintage=2026,
            term_end_vintage=2026, committed_tons=40.000,
            installment_plan=single_installment_plan(),
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_a_fourth_decimal_place_on_acreage_is_refused_rather_than_rounded(api):
    """Acreage is declared to three decimals, so 20.0001 is a violation of the input
    contract and not a number to quietly round to 20.000.

    PRD: "the planted `acres` as a positive number with at most 3 decimal places"

    Design: Corner/entities/enum_range_and_decimal_place_type_constraints_returns_422
    """
    ctx = _one_of_everything_the_shape_probes_need()

    response = api.create_vineyard_block(
        create_vineyard_block_payload(
            ctx["grower"]["id"], block_code="B-13", varietal="MERLOT", acres=20.0001,
            expected_yield_tons_per_acre=2.000, ava_code="NAPA-VALLEY",
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_a_window_that_ends_where_it_starts_is_refused(api):
    """An instantaneous sampling window is not a window: the end must be strictly after the
    start, so an equal pair fails rather than being treated as a zero-length booking.

    PRD: "the field window as an inclusive `window_start` and an exclusive `window_end`, the
    latter strictly after the former."

    Design: Corner/entities/enum_range_and_decimal_place_type_constraints_returns_422
    """
    ctx = _one_of_everything_the_shape_probes_need()

    response = api.create_sampling_visit(
        create_sampling_visit_payload(
            ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"],
            "2026-08-02T09:00:00Z", "2026-08-02T09:00:00Z",
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_zero_acres_is_out_of_range_even_though_it_has_the_right_precision(api):
    """0.000 carries exactly three decimals and is still refused, because the declaration
    demands a positive number and zero is not one.

    PRD: "the planted `acres` as a positive number with at most 3 decimal places"

    Design: Corner/entities/enum_range_and_decimal_place_type_constraints_returns_422
    """
    ctx = _one_of_everything_the_shape_probes_need()

    response = api.create_vineyard_block(
        create_vineyard_block_payload(
            ctx["grower"]["id"], block_code="B-14", varietal="MERLOT", acres=0.000,
            expected_yield_tons_per_acre=2.000, ava_code="NAPA-VALLEY",
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_the_four_malformed_bodies_added_nothing_to_the_three_collections(api):
    """After four refusals the winery still holds exactly the one block and the one contract
    it started with, and no sampling visit at all.

    PRD: "Blocks are listed with the optional filters `grower_id`, `status` and `varietal`,
    and a single block read exposes the sampling readings and the vintage tonnage."

    Design: Corner/entities/enum_range_and_decimal_place_type_constraints_returns_422
    """
    ctx = _one_of_everything_the_shape_probes_need()

    api.create_grape_contract(
        create_grape_contract_payload(
            ctx["grower"]["id"], ctx["spec"]["id"], contract_code="GC-ENUM",
            contract_basis="PER_VINE", base_price_per_ton_cents=450000,
            over_delivery_policy="ACCEPT_AT_CONTRACT", term_start_vintage=2026,
            term_end_vintage=2026, committed_tons=40.000,
            installment_plan=single_installment_plan(),
        ),
        MANAGER,
    )
    for block_code, acres in (("B-13", 20.0001), ("B-14", 0.000)):
        api.create_vineyard_block(
            create_vineyard_block_payload(
                ctx["grower"]["id"], block_code=block_code, varietal="MERLOT", acres=acres,
                expected_yield_tons_per_acre=2.000, ava_code="NAPA-VALLEY",
            ),
            MANAGER,
        )
    api.create_sampling_visit(
        create_sampling_visit_payload(
            ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"],
            "2026-08-02T09:00:00Z", "2026-08-02T09:00:00Z",
        ),
        COORDINATOR,
    )

    blocks = get_success_data(api.list_vineyard_blocks(MANAGER))
    contracts = get_success_data(api.list_grape_contracts(MANAGER))
    assert [row["id"] for row in blocks] == [ctx["block"]["id"]]
    assert [row["id"] for row in contracts] == [ctx["contract"]["id"]]
    assert get_success_data(api.list_sampling_visits(COORDINATOR)) == []
