"""The junction between contracts and blocks is the only many-to-many surface in the model, and it
has to be navigable from both ends: one contract holding two blocks and one block held by two
contracts is the smallest arrangement a one-to-many shortcut gets wrong. Alongside it, the
specification book — the most parameter-heavy row in the system — written once with every optional
threshold moved off its default and read back unchanged.
"""
from test_helpers import (
    COORDINATOR,
    LAB_TECH,
    MANAGER,
    QUALITY_SPEC_DEFAULTS,
    accept_contract,
    create_allocation,
    create_block,
    create_contract,
    create_grower,
    create_quality_spec,
    move_clock,
    offer_contract,
    read_allocation,
    read_contract,
    single_installment_plan,
    validate_paginated,
    validate_success,
)

SETUP_AT = "2026-08-01T00:00:00Z"

PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}
FIRST_BLOCK = {
    "block_code": "B-12",
    "varietal": "CABERNET_SAUVIGNON",
    "acres": 20.000,
    "expected_yield_tons_per_acre": 2.000,
    "ava_code": "NAPA-VALLEY",
}
SECOND_BLOCK = {
    "block_code": "B-13",
    "varietal": "MERLOT",
    "acres": 6.000,
    "expected_yield_tons_per_acre": 2.500,
    "ava_code": "NAPA-VALLEY",
}
SPEC = {
    "spec_code": "CAB-STD-2026",
    "min_brix_accept": 20.0,
    "brix_bonus_start": 24.0,
    "brix_penalty_start": 22.0,
    "rot_rejection_pct": 8.0,
    "min_brix_pick_call": 21.0,
}

CONTRACTED_YIELD_TONS_PER_ACRE = 2.500
ACRES_OFF_THE_FIRST_BLOCK = 12.500
ACRES_OFF_THE_SECOND_BLOCK = 6.000
# (12.500 + 6.000) allocated acres at 2.500 contracted tons apiece.
ACREAGE_CAP_TONS = 46.250


# --- The many-to-many, walked from both ends ---------------------------------------------


def _two_contracts_over_two_blocks(api) -> dict:
    """One producer with two blocks and two agreements: the first commits both blocks on an
    acreage basis, the second commits only the first block on a tonnage basis."""
    move_clock(SETUP_AT)
    ctx = {"grower": create_grower(**PRODUCER)}
    ctx["spec"] = create_quality_spec(**SPEC)
    ctx["first_block"] = create_block(ctx["grower"]["id"], **FIRST_BLOCK)
    ctx["second_block"] = create_block(ctx["grower"]["id"], **SECOND_BLOCK)

    ctx["acreage_contract"] = validate_success(
        api.create_grape_contract(
            {
                "grower_id": ctx["grower"]["id"],
                "quality_spec_id": ctx["spec"]["id"],
                "contract_code": "GC-LINK-1",
                "contract_basis": "ACREAGE",
                "contracted_yield_tons_per_acre": CONTRACTED_YIELD_TONS_PER_ACRE,
                "base_price_per_ton_cents": 450000,
                "over_delivery_policy": "ACCEPT_AT_CONTRACT",
                "term_start_vintage": 2026,
                "term_end_vintage": 2027,
                "installment_plan": single_installment_plan(),
            },
            MANAGER,
        ),
        201,
    )
    ctx["tonnage_contract"] = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code="GC-LINK-2",
        contract_basis="TONNAGE",
        committed_tons=30.000,
    )

    ctx["first_link"] = create_allocation(
        ctx["acreage_contract"]["id"],
        ctx["first_block"]["id"],
        allocated_acres=ACRES_OFF_THE_FIRST_BLOCK,
    )
    ctx["second_link"] = create_allocation(
        ctx["acreage_contract"]["id"],
        ctx["second_block"]["id"],
        allocated_acres=ACRES_OFF_THE_SECOND_BLOCK,
    )
    ctx["shared_link"] = create_allocation(
        ctx["tonnage_contract"]["id"], ctx["first_block"]["id"]
    )
    return ctx


def test_one_contract_side_lists_every_block_it_committed(api):
    """Walking from the contract end finds both of its blocks and neither of the neighbouring
    agreement's rows.

    PRD: "Allocations are listed with the optional filters `contract_id` and `block_id`, which is
    how either side of the many-to-many between contracts and blocks is walked."

    Design: Corner/endpoints/contract_block_allocation_links_a_contract_and_a_block_readable_from_both_sides
    """
    ctx = _two_contracts_over_two_blocks(api)

    rows, meta = validate_paginated(
        api.list_allocations(MANAGER, params={"contract_id": ctx["acreage_contract"]["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["block_id"] for row in rows} == {
        ctx["first_block"]["id"],
        ctx["second_block"]["id"],
    }


def test_one_block_side_lists_every_contract_that_claims_it(api):
    """Walking from the block end finds both agreements over that block — the answer a one-to-many
    shortcut from contract to block cannot produce at all.

    PRD: "Allocations are listed with the optional filters `contract_id` and `block_id`, which is
    how either side of the many-to-many between contracts and blocks is walked."

    Design: Corner/endpoints/contract_block_allocation_links_a_contract_and_a_block_readable_from_both_sides
    """
    ctx = _two_contracts_over_two_blocks(api)

    rows, meta = validate_paginated(
        api.list_allocations(MANAGER, params={"block_id": ctx["first_block"]["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["contract_id"] for row in rows} == {
        ctx["acreage_contract"]["id"],
        ctx["tonnage_contract"]["id"],
    }


def test_the_other_contract_sees_only_its_own_single_link(api):
    """The shared block does not drag the neighbour's second block into this agreement's view: the
    two filters are genuinely independent.

    PRD: "The same block may be committed to a given contract only once: a repeated
    contract-and-block pair is refused with `ERR_DUPLICATE_CODE`."

    Design: Corner/endpoints/contract_block_allocation_links_a_contract_and_a_block_readable_from_both_sides
    """
    ctx = _two_contracts_over_two_blocks(api)

    rows, meta = validate_paginated(
        api.list_allocations(MANAGER, params={"contract_id": ctx["tonnage_contract"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["block_id"] == ctx["first_block"]["id"]
    assert rows[0]["id"] == ctx["shared_link"]["id"]


def test_the_link_row_carries_its_acreage_and_no_caps_yet(api):
    """The junction row is readable in its own right, holding the acreage the agreement committed
    off that block — and its per-block caps are still empty, because nobody has signed.

    PRD: "At creation time `block_cap_tons` and `block_hard_cap_tons` are null and stay null until
    the contract is accepted. The allocation also carries a derived `delivered_net_tons`, which
    accumulates the tonnage settled against this contract from this block."

    Design: Corner/endpoints/contract_block_allocation_links_a_contract_and_a_block_readable_from_both_sides
    """
    ctx = _two_contracts_over_two_blocks(api)

    link = read_allocation(ctx["first_link"]["id"])
    assert link["contract_id"] == ctx["acreage_contract"]["id"]
    assert link["block_id"] == ctx["first_block"]["id"]
    assert float(link["allocated_acres"]) == ACRES_OFF_THE_FIRST_BLOCK
    assert link["block_cap_tons"] is None
    assert link["block_hard_cap_tons"] is None
    assert float(link["delivered_net_tons"]) == 0.000


def test_the_junction_rows_are_what_the_acreage_cap_is_built_from(api):
    """The links are not decoration: acceptance sums the acreage they carry and prices the whole
    agreement off it, so 12.500 and 6.000 acres at 2.500 tons apiece make 46.250 tons.

    PRD: "On an `ACREAGE` contract the allocated acreage of every block allocation of the contract
    is summed, that total is multiplied by `contracted_yield_tons_per_acre`, and the product is
    rounded half up to 3 decimals; `cap_scope` is again `PER_CONTRACT`."

    Design: Corner/endpoints/contract_block_allocation_links_a_contract_and_a_block_readable_from_both_sides
    """
    ctx = _two_contracts_over_two_blocks(api)
    offer_contract(ctx["acreage_contract"]["id"])
    accept_contract(ctx["acreage_contract"]["id"], ctx["grower"]["id"])

    contract = read_contract(ctx["acreage_contract"]["id"])
    assert float(contract["contract_cap_tons"]) == ACREAGE_CAP_TONS
    assert contract["cap_scope"] == "PER_CONTRACT"


# --- The specification book: write once, read back exactly -------------------------------


A_FULLY_SPECIFIED_RULEBOOK = {
    "spec_code": "PINOT-PREMIUM-2026",
    "min_brix_accept": 21.5,
    "brix_bonus_start": 25.0,
    "brix_penalty_start": 23.0,
    "rot_rejection_pct": 6.0,
    "min_brix_pick_call": 22.0,
    "brix_step": 0.2,
    "brix_bonus_pct_per_step": 1.0,
    "brix_penalty_pct_per_step": 1.5,
    "ta_min_gl": 6.0,
    "ta_max_gl": 8.5,
    "acid_out_of_spec_penalty_pct": 2.0,
    "rot_free_pct": 1.0,
    "rot_penalty_pct_per_point": 2.5,
    "mog_max_pct": 0.8,
    "mog_penalty_pct": 3.0,
    "max_total_bonus_pct": 10.0,
    "max_total_penalty_pct": 25.0,
}
NO_SUCH_SPEC_CODE = "NO-SUCH-SPEC"


def _a_specification_written_by_the_lab(api) -> dict:
    """The rulebook the lab authors itself, with every optional threshold supplied."""
    move_clock(SETUP_AT)
    return validate_success(
        api.create_quality_spec(dict(A_FULLY_SPECIFIED_RULEBOOK), LAB_TECH), 201
    )


def test_the_lab_may_author_a_specification_itself(api):
    """The rulebook is the one reference row the lab shares authorship of, and it is written with
    the audit fields every row gets on creation.

    PRD: "The **quality specification** is the price-and-rejection rulebook, and it is the one
    reference table a `QualityLabTech` may author alongside the `GrowerRelationsManager`."

    Design: Corner/endpoints/quality_spec_create_read_list_is_the_whole_crud_surface
    """
    spec = _a_specification_written_by_the_lab(api)

    assert spec["created_at"].startswith("2026-08-01T00:00:00")
    assert spec["updated_at"] == spec["created_at"]
    assert spec["version"] == 1


def test_the_detail_read_echoes_every_supplied_threshold(api):
    """Seventeen values in, the same seventeen out: nothing was quietly replaced by a house
    default on the way through.

    PRD: "Read one quality specification."

    Design: Corner/endpoints/quality_spec_create_read_list_is_the_whole_crud_surface
    """
    spec = _a_specification_written_by_the_lab(api)

    read_back = validate_success(api.get_quality_spec(spec["id"], MANAGER))
    for field, supplied in A_FULLY_SPECIFIED_RULEBOOK.items():
        if field == "spec_code":
            assert read_back[field] == supplied
        else:
            assert float(read_back[field]) == supplied, field


def test_none_of_the_stored_thresholds_is_its_declared_default(api):
    """Every optional knob was moved off the value it would have defaulted to, so a row that
    merely echoed the defaults could not have passed the read above.

    PRD: "Everything else is optional and defaulted: `min_brix_pick_call`, the minimum sampled
    sugar that lets a pick call be issued, defaults to 21.0; `brix_step`, the sugar increment that
    constitutes one bonus or penalty step, defaults to 0.5; `brix_bonus_pct_per_step` defaults to
    1.5 and `brix_penalty_pct_per_step` to 2.0 percentage points"

    Design: Corner/endpoints/quality_spec_create_read_list_is_the_whole_crud_surface
    """
    spec = _a_specification_written_by_the_lab(api)

    for field, default in QUALITY_SPEC_DEFAULTS.items():
        assert A_FULLY_SPECIFIED_RULEBOOK[field] != default, field
        assert float(spec[field]) == A_FULLY_SPECIFIED_RULEBOOK[field], field


def test_the_harvest_desk_can_find_the_specification_by_its_code(api):
    """The listing is filtered by the code and is served to the harvest desk as well as to the
    author, on a single page with nothing beyond it.

    PRD: "Specifications are listed with an optional `spec_code` filter."

    Design: Corner/endpoints/quality_spec_create_read_list_is_the_whole_crud_surface
    """
    spec = _a_specification_written_by_the_lab(api)

    rows, meta = validate_paginated(
        api.list_quality_specs(
            COORDINATOR, params={"spec_code": A_FULLY_SPECIFIED_RULEBOOK["spec_code"]}
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == spec["id"]


def test_a_filter_that_matches_nothing_is_an_empty_page(api):
    """A code nobody registered is not an error: the collection answers with no rows rather than
    refusing the request.

    PRD: "Every list response repeats `limit` and `offset` in the `meta` object alongside
    `total_count` — the number of rows matching the filter before pagination is applied — and
    `has_more`, which is true exactly when rows remain beyond the current page."

    Design: Corner/endpoints/quality_spec_create_read_list_is_the_whole_crud_surface
    """
    _a_specification_written_by_the_lab(api)

    rows, meta = validate_paginated(
        api.list_quality_specs(COORDINATOR, params={"spec_code": NO_SUCH_SPEC_CODE})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
