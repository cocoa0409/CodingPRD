"""Creation, defaults, required fields, immutability and reads on the core entities."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_acreage,
    assert_append_only_entity_shape,
    assert_burden,
    assert_full_entity_shape,
    assert_identity_fields,
    assert_pagination_meta,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    MANAGER_HEADERS,
    OPERATOR_HEADERS,
    OPERATOR_USER_ID,
)


def test_opening_a_tract_file_returns_every_declared_field(api):
    """A new tract file is RESEARCH with nothing certified yet.

    PRD: "A newly opened tract file is stamped with `title_status` of `RESEARCH`,
    a `chain_entry_count` of 0, and a `net_mineral_acres_certified`,
    `existing_burden_fraction` and `certified_at` that are all null."

    Design: Corner/entities/create_tract_returns_201_with_all_declared_fields
    """
    tract = validate_success(api.create_tract(f.tract_payload(), ANALYST_HEADERS), 201)

    assert tract["county"] == "Reeves"
    assert tract["state_code"] == "TX"
    assert_acreage(tract["gross_acres"], "640.0000", "gross_acres")
    assert tract["operator_activity_tier"] == "HIGH"
    assert tract["title_status"] == "RESEARCH"
    assert tract["net_mineral_acres_certified"] is None
    assert tract["existing_burden_fraction"] is None
    assert tract["certified_at"] is None
    assert tract["chain_entry_count"] == 0
    assert_full_entity_shape(
        tract,
        [
            "county",
            "state_code",
            "gross_acres",
            "operator_activity_tier",
            "title_status",
            "net_mineral_acres_certified",
            "existing_burden_fraction",
            "certified_at",
            "chain_entry_count",
        ],
    )


def test_omitting_the_activity_tier_defaults_it_to_moderate(api):
    """The optional classification falls back to MODERATE on create and on read.

    PRD: "An optional `operator_activity_tier` classifies how active the
    surrounding operator is; it is one of `HIGH`, `MODERATE` or `LOW` and defaults
    to `MODERATE` when omitted."

    Design: Corner/entities/create_tract_without_activity_tier_defaults_to_moderate
    """
    tract = validate_success(
        api.create_tract(f.tract_payload(operator_activity_tier=f.OMIT), ANALYST_HEADERS),
        201,
    )

    assert tract["operator_activity_tier"] == "MODERATE"
    reread = validate_success(api.get_tract(tract["id"], ANALYST_HEADERS), 200)
    assert reread["operator_activity_tier"] == "MODERATE"


def test_a_tract_without_gross_acres_is_rejected(api):
    """The denominator of every downstream fraction is mandatory.

    PRD: "The payload names the `county` whose deed records will be searched —
    between 1 and 80 characters and never empty — the `state_code` in which the
    tract lies, and the tract's surveyed `gross_acres`, which must be strictly
    greater than zero and is carried to 4 decimal places."

    Design: Corner/entities/create_tract_missing_gross_acres_returns_400
    """
    response = api.create_tract(f.tract_payload(gross_acres=f.OMIT), ANALYST_HEADERS)

    validate_error(response, "ERR_INVALID_REQUEST", 400)
    tracts, meta = validate_paginated(api.list_tracts(ANALYST_HEADERS))
    assert meta["total_count"] == 0
    assert tracts == []


def test_a_unit_in_an_unsupported_state_is_rejected(api):
    """CO is not one of the four producing states the severance table knows.

    PRD: "An `Operator` forms a unit by naming the operator's own `unit_name`
    designation for the pooled area, the target `formation`, the producing
    `state_code` (one of `TX`, `OK`, `NM` or `ND`, and the value that later
    selects the severance-tax row)"

    Design: Corner/entities/create_unit_with_unknown_state_code_returns_400
    """
    response = api.create_unit(
        f.unit_payload(unit_name="Bad State Unit", state_code="CO"), OPERATOR_HEADERS
    )

    validate_error(response, "ERR_INVALID_REQUEST", 400)
    units, meta = validate_paginated(api.list_units(OPERATOR_HEADERS))
    assert meta["total_count"] == 0
    assert units == []


def test_more_producing_depths_than_the_unit_holds_is_rejected(api):
    """Four of three depths on production is not a describable depth stack.

    PRD: "Two integers describe the depth stack: `total_depth_count`, the number
    of depth intervals the unit's leases hold, which must be at least 1, and
    `producing_depth_count`, the number actually on production, which must be at
    least zero and must not exceed `total_depth_count`."

    Design: Corner/entities/create_unit_with_producing_depths_above_total_returns_400
    """
    response = api.create_unit(
        f.unit_payload(unit_name="Deep Unit", producing_depth_count=4, total_depth_count=3),
        OPERATOR_HEADERS,
    )

    validate_error(response, "ERR_INVALID_REQUEST", 400)
    _units, meta = validate_paginated(api.list_units(OPERATOR_HEADERS))
    assert meta["total_count"] == 0


def test_server_owned_unit_fields_come_from_the_server_not_the_body(api):
    """operator_user_id is taken from the header and the acreage figures are derived.

    PRD: "On creation the unit's `unallocated_acres` is set equal to
    `unit_gross_acres`, its `active_allocation_count` is 0, and its
    `operator_user_id` is stamped from the creating `X-User-ID` — the identifier
    every later operator action on this unit, on its allocations and on its
    division orders must present."

    Design: Corner/entities/create_unit_ignores_client_supplied_system_fields
    """
    unit = validate_success(
        api.create_unit(
            f.unit_payload(
                unit_name="Reeves Unit 10H",
                operator_user_id="op-user-999",
                unallocated_acres=1.0000,
                active_allocation_count=7,
                version=99,
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )

    assert unit["operator_user_id"] == OPERATOR_USER_ID
    assert_acreage(unit["unallocated_acres"], "1280.0000", "unallocated_acres")
    assert unit["active_allocation_count"] == 0
    assert unit["version"] == 1
    assert unit["created_at"] == unit["updated_at"]


def test_certification_computes_acreage_and_burden_from_the_chain(api):
    """The replay lands on 80.0000 acres and a 0.0625 burden at the clock instant.

    PRD: "On success the tract's `title_status` becomes `CERTIFIED`, `certified_at`
    is stamped with the logical-clock instant, and the tract's `version`
    increments by 1."

    Design: Corner/entities/certify_title_computes_certified_acreage_and_burden_from_chain
    """
    tract = fx.create_tract(api)
    fx.add_canonical_chain(api, tract["id"])

    before = validate_success(api.get_tract(tract["id"], ANALYST_HEADERS), 200)
    assert before["title_status"] == "RESEARCH"
    assert before["net_mineral_acres_certified"] is None
    assert before["existing_burden_fraction"] is None

    certified = fx.certify_tract(api, tract["id"])

    assert certified["title_status"] == "CERTIFIED"
    assert_acreage(
        certified["net_mineral_acres_certified"], "80.0000", "net_mineral_acres_certified"
    )
    assert_burden(certified["existing_burden_fraction"], "0.0625", "existing_burden_fraction")
    assert certified["certified_at"].startswith("2026-08-01T00:00:00")
    assert certified["version"] == 6


def test_each_filed_instrument_bumps_the_tract_counter_and_version(api):
    """Four filings walk chain_entry_count from 1 to 4 and version from 2 to 5.

    PRD: "Filing one increments the tract's `chain_entry_count` by 1 and the
    tract's `version` by 1."

    Design: Corner/entities/certify_title_computes_certified_acreage_and_burden_from_chain
    """
    tract = fx.create_tract(api)
    assert tract["version"] == 1

    payloads = [
        f.patent_entry_payload(),
        f.deed_entry_payload(),
        f.probate_entry_payload(),
        f.assignment_entry_payload(),
    ]
    for index, payload in enumerate(payloads, start=1):
        fx.add_chain_entry(api, tract["id"], payload)
        current = validate_success(api.get_tract(tract["id"], ANALYST_HEADERS), 200)
        assert current["chain_entry_count"] == index
        assert current["version"] == index + 1


def test_a_chain_entry_carries_no_version_and_no_updated_at(api):
    """The append-only instrument exposes only id and created_at.

    PRD: "One resource is deliberately different. A chain-of-title entry is
    append-only and immutable: once a county instrument has been filed it is never
    edited and never deleted, so it carries only `id` and `created_at`. It has no
    `updated_at` and no `version` field at all, and neither key appears in its
    representation."

    Design: Corner/entities/title_chain_entry_is_immutable_and_has_no_version_field
    """
    tract = fx.create_tract(api)
    entry = fx.add_chain_entry(api, tract["id"], f.patent_entry_payload())

    assert_append_only_entity_shape(
        entry,
        [
            "tract_id",
            "instrument_type",
            "instrument_date",
            "county_book_page",
            "grantor_name",
            "grantee_name",
        ],
    )

    entries, meta = validate_paginated(
        api.list_title_chain_entries(tract["id"], ANALYST_HEADERS, {"instrument_type": "PATENT"})
    )
    assert meta["total_count"] == 1
    assert entries[0]["instrument_type"] == "PATENT"
    assert entries[0]["instrument_date"] == "1902-05-01"
    assert entries[0]["county_book_page"] == "100/1"
    assert "version" not in entries[0]
    assert "updated_at" not in entries[0]


def test_filing_an_instrument_under_an_unknown_tract_is_a_tract_not_found(api):
    """The nested write reports the missing parent, not a generic failure.

    PRD: "Research proceeds one county instrument at a time. Each filing records
    an `instrument_type` — `PATENT`, `DEED`, `PROBATE` or `ASSIGNMENT` — an
    `instrument_date` given as a `YYYY-MM-DD` calendar date, a `county_book_page`
    citation matching the clerk's format of one to six digits, a forward slash,
    then one to six digits, and the `grantor_name` and `grantee_name` as recited on
    the instrument."

    Design: Corner/entities/create_chain_entry_under_unknown_tract_returns_404
    """
    response = api.create_title_chain_entry(
        NON_EXISTENT_UUID, f.patent_entry_payload(), ANALYST_HEADERS
    )

    validate_error(response, "ERR_TRACT_NOT_FOUND", 404)


def test_reading_an_unknown_interest_is_a_mineral_interest_not_found(api):
    """The 404 still arrives inside the standard error envelope.

    PRD: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    PRD: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/get_mineral_interest_with_unknown_id_returns_404
    """
    response = api.get_mineral_interest(NON_EXISTENT_UUID, MANAGER_HEADERS)

    body = validate_error(response, "ERR_MINERAL_INTEREST_NOT_FOUND", 404)
    assert body["message"]


def test_reading_an_interest_returns_its_stored_and_frozen_figures(api):
    """40.0000 net mineral acres and a copied 0.0625 burden, still a PROSPECT.

    PRD: "Two figures are frozen from the tract at creation and never move again:
    `net_mineral_acres` is the tract's `net_mineral_acres_certified` multiplied by
    `seller_share_fraction`, rounded half-up to 4 decimal places, and
    `existing_burden_fraction` is a straight copy of the tract's
    `existing_burden_fraction`, carried at 4 decimal places."

    Design: Corner/entities/get_mineral_interest_returns_stored_and_derived_fields
    """
    tract = fx.create_certified_tract(api)
    owner = fx.create_owner(api)
    created = fx.create_interest(api, tract["id"], owner["id"])

    interest = validate_success(api.get_mineral_interest(created["id"], MANAGER_HEADERS), 200)

    assert interest["id"] == created["id"]
    assert interest["tract_id"] == tract["id"]
    assert interest["seller_owner_id"] == owner["id"]
    assert float(interest["seller_share_fraction"]) == 0.5
    assert float(interest["lease_royalty_rate"]) == 0.1875
    assert_acreage(interest["net_mineral_acres"], "40.0000", "net_mineral_acres")
    assert_burden(interest["existing_burden_fraction"], "0.0625", "existing_burden_fraction")
    assert interest["interest_status"] == "PROSPECT"
    assert interest["current_valuation_id"] is None
    assert_identity_fields(interest)


def test_the_interest_list_paginates_and_honours_the_tract_filter(api):
    """Three interests on one tract come back two then one, with the other tract absent.

    PRD: "`limit` controls page size: it defaults to 10, must be at least 1, and
    must not exceed 100. `offset` controls the starting position: it defaults to 0
    and must not be negative."

    PRD: "List responses populate `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` counts every row matching the filters before
    pagination is applied and `has_more` indicates whether further rows exist beyond
    the current page."

    Design: Corner/entities/list_mineral_interests_paginates_and_filters_by_tract
    """
    tract = fx.create_certified_tract(api)
    owner = fx.create_owner(api)
    for share in (0.5, 0.25, 0.125):
        fx.create_interest(api, tract["id"], owner["id"], seller_share_fraction=share)

    other = fx.create_tract(api, county="Loving", gross_acres=320.0000, operator_activity_tier="LOW")
    fx.add_chain_entry(
        api,
        other["id"],
        f.patent_entry_payload(
            instrument_date="1905-06-01",
            county_book_page="310/7",
            grantee_name="D Patentee",
        ),
    )
    fx.certify_tract(api, other["id"])
    fx.create_interest(
        api, other["id"], owner["id"], lease_royalty_rate=0.2, undeveloped_net_acres=8.0000
    )

    first_page, first_meta = validate_paginated(
        api.list_mineral_interests(MANAGER_HEADERS, {"tract_id": tract["id"], "limit": 2, "offset": 0})
    )
    second_page, second_meta = validate_paginated(
        api.list_mineral_interests(MANAGER_HEADERS, {"tract_id": tract["id"], "limit": 2, "offset": 2})
    )

    assert len(first_page) == 2
    assert_pagination_meta(first_meta, 2, 0, total_count=3, has_more=True)
    assert len(second_page) == 1
    assert_pagination_meta(second_meta, 2, 2, total_count=3, has_more=False)

    combined = first_page + second_page
    assert all(item["tract_id"] == tract["id"] for item in combined)
    assert len({item["id"] for item in combined}) == 3
