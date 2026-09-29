"""Entity creation and reads: required fields, declared defaults and reference resolution."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_money,
    assert_pagination_meta,
    created,
    failed,
    ok,
    page,
)

UNKNOWN_ID = "00000000-0000-0000-0000-000000000009"


def test_a_candidate_missing_its_agl_is_rejected_and_joins_no_ring(api: ApiClient) -> None:
    """A required survey field is absent, so the body-shape tier refuses the create.

    PRD: "Request-body shape: every required field present, no unknown fields,
    correct types, enum members drawn from the declared set, and numeric bounds
    respected — `ERR_INVALID_REQUEST`, on every write endpoint."

    PRD: "The structure itself is described by `site_type` — one of `TOWER`, `ROOFTOP`
    or `RAW_LAND` — its position as `lat` and `lon`, its surveyed
    `distance_from_center_m` from the ring centre (non-negative), the available antenna
    centreline height as `agl_m` (non-negative), and `months_to_availability`, the
    non-negative number of months before the site can be occupied."

    PRD: "Creating the candidate recomputes the ring's `candidate_count` and increments
    the ring's `version`."

    Design: Corner/entities/corner_candidate_create_missing_required_field_rejected
    """
    chain = S.base_reference_data(api)

    refused = api.create_candidate(
        F.candidate_payload(
            chain["ring_id"], chain["ll_id"], chain["jur_id"], agl_m=F.OMIT
        ),
        headers=S.agent(),
    )
    failed(refused, ApiError.INVALID_REQUEST, expected_status=400)

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(ring, candidate_count=0)

    _, meta = page(
        api.list_candidates({"search_ring_id": chain["ring_id"]}, headers=S.rf())
    )
    assert_pagination_meta(meta, total_count=0)


def test_a_new_search_ring_carries_the_declared_ledger_defaults(api: ApiClient) -> None:
    """Creation mints the ring in `DRAFT` with every rollup at its declared start value.

    PRD: "A new ring begins in `DRAFT` with `candidate_count` at 0,
    `committed_capex_usd` at 0, `reopen_count` at 0 and `selected_candidate_id` null."

    PRD: "`version` (integer): a counter that increments by one on every mutation of
    that record."

    Design: Corner/entities/corner_search_ring_create_applies_declared_defaults
    """
    S.reset_clock(api)

    ring = created(api.create_search_ring(F.search_ring_payload(), headers=S.rf()))

    assert_common_fields(ring)
    assert_fields(ring, status="DRAFT", candidate_count=0, reopen_count=0, version=1)
    assert_money(ring["committed_capex_usd"], 0.00, "committed_capex_usd")
    assert ring["selected_candidate_id"] is None, "a fresh ring has selected nothing"


def test_a_new_landlord_starts_active_with_an_empty_lease_ledger(api: ApiClient) -> None:
    """The server generates standing, the lease count and the opt-out default itself.

    PRD: "A landlord's `standing` starts at `ACTIVE` and its `executed_lease_count` at
    0."

    PRD: "The optional `outreach_optout` flag defaults to false; when it is true the
    landlord has refused contact, and both outreach events and lease drafting against
    that landlord are refused with `ERR_LANDLORD_OPTED_OUT`."

    Design: Corner/entities/corner_landlord_create_generates_system_fields
    """
    S.reset_clock(api)

    landlord = created(
        api.create_landlord(
            F.landlord_payload(outreach_optout=F.OMIT), headers=S.agent()
        )
    )

    assert_common_fields(landlord)
    assert_fields(
        landlord,
        legal_name=C.LANDLORD_NAME,
        standing="ACTIVE",
        executed_lease_count=0,
        outreach_optout=False,
        version=1,
    )


def test_a_site_type_outside_the_declared_enum_is_rejected(api: ApiClient) -> None:
    """`BALLOON` is not a member of the declared set, so the create never lands.

    PRD: "The structure itself is described by `site_type` — one of `TOWER`, `ROOFTOP`
    or `RAW_LAND` — its position as `lat` and `lon`, its surveyed
    `distance_from_center_m` from the ring centre (non-negative), the available antenna
    centreline height as `agl_m` (non-negative), and `months_to_availability`, the
    non-negative number of months before the site can be occupied."

    PRD: "Request-body shape: every required field present, no unknown fields,
    correct types, enum members drawn from the declared set, and numeric bounds
    respected — `ERR_INVALID_REQUEST`, on every write endpoint."

    Design: Corner/entities/corner_candidate_create_rejects_invalid_site_type_enum
    """
    chain = S.base_reference_data(api)

    refused = api.create_candidate(
        F.candidate_payload(
            chain["ring_id"], chain["ll_id"], chain["jur_id"], site_type="BALLOON"
        ),
        headers=S.agent(),
    )
    failed(refused, ApiError.INVALID_REQUEST, expected_status=400)

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(ring, candidate_count=0)


def _three_candidates_on_one_ring(api: ApiClient) -> Dict[str, Any]:
    """Three `PROSPECTING` candidates hung off one ring and one landlord."""
    chain = S.base_reference_data(api)
    offsets = ((42.3510, -71.0620, 200), (42.3520, -71.0630, 220), (42.3530, -71.0640, 240))
    for lat, lon, distance in offsets:
        S.create_candidate(
            api,
            chain["ring_id"],
            chain["ll_id"],
            chain["jur_id"],
            lat=lat,
            lon=lon,
            distance_from_center_m=distance,
        )
    return chain


def test_the_candidate_list_pages_three_rows_two_at_a_time(api: ApiClient) -> None:
    """The envelope reports the full count on both pages and flips `has_more` once.

    PRD: "`limit` sets the maximum number of records returned; it defaults to 10, may
    not be less than 1, and may not exceed 100."

    PRD: "The `meta` object of a list response carries `limit`, `offset`, `total_count`
    and `has_more`."

    PRD: "`candidate_count` tracks the number of candidates attached to the ring whose
    `acquisition_status` is anything other than `RELINQUISHED`, and is recomputed
    whenever a candidate joins the ring or is relinquished or disqualified."

    Design: Corner/entities/corner_candidate_list_returns_paginated_envelope
    """
    chain = _three_candidates_on_one_ring(api)

    first_rows, first_meta = page(
        api.list_candidates(
            {"search_ring_id": chain["ring_id"], "limit": 2, "offset": 0},
            headers=S.rf(),
        )
    )
    assert len(first_rows) == 2, "the first page carries the requested two rows"
    assert_pagination_meta(
        first_meta, total_count=3, limit=2, offset=0, has_more=True
    )

    second_rows, second_meta = page(
        api.list_candidates(
            {"search_ring_id": chain["ring_id"], "limit": 2, "offset": 2},
            headers=S.rf(),
        )
    )
    assert len(second_rows) == 1, "the tail page carries the single remaining row"
    assert_pagination_meta(second_meta, total_count=3, limit=2, offset=2, has_more=False)

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(ring, candidate_count=3)


def test_reading_a_ring_returns_the_rf_objective_exactly_as_stored(api: ApiClient) -> None:
    """The single-resource read echoes the declared target, geometry and budget.

    PRD: "The RF objective itself is declared through `objective_type`, one of
    `COVERAGE`, `CAPACITY` or `COVERAGE_AND_CAPACITY`, alongside a `target_rsrp_dbm`
    reference-signal power (a negative dBm figure) and a `target_capacity_gbps`
    backhaul objective greater than zero."

    PRD: "Three commercial parameters complete the ring:
    `market_benchmark_monthly_rent_usd`, the benchmark ground rent for the market,
    which must be greater than zero; `capex_budget_usd`, the non-negative ceiling on
    tower modification spend for this ring; and `priority_rank`, an integer expressing
    RF program priority where 1 is highest."

    Design: Corner/entities/corner_search_ring_get_returns_stored_values
    """
    S.reset_clock(api)
    ring = S.create_search_ring(api)

    reread = ok(api.get_search_ring(ring["id"], headers=S.planner()))

    assert_fields(
        reread,
        id=ring["id"],
        status="DRAFT",
        market_code=C.MARKET_CODE,
        radius_m=C.RING_RADIUS_M,
        required_agl_m=C.RING_REQUIRED_AGL_M,
        objective_type=C.RING_OBJECTIVE_TYPE,
        target_rsrp_dbm=C.RING_TARGET_RSRP_DBM,
        target_capacity_gbps=C.RING_TARGET_CAPACITY_GBPS,
        priority_rank=1,
    )
    assert_money(reread["capex_budget_usd"], C.CAPEX_BUDGET_USD, "capex_budget_usd")
    assert_money(
        reread["market_benchmark_monthly_rent_usd"],
        C.MARKET_BENCHMARK_MONTHLY_RENT_USD,
        "market_benchmark_monthly_rent_usd",
    )


def test_a_candidate_naming_an_unknown_landlord_reports_the_landlord_404(
    api: ApiClient,
) -> None:
    """Body identifiers resolve in declaration order, and the ring is left untouched.

    PRD: "Identifiers supplied in a request body are resolved after the path and in the
    order in which the receiving record declares them, so a create whose payload names
    two unknown records reports the first-declared one."

    PRD: "A `SiteAcquisitionAgent` attaches a candidate site to a ring by supplying the
    ring through `search_ring_id`, the property owner through `landlord_id`, the zoning
    authority through `jurisdiction_id`, and the opaque agent identifier that will own
    the record through `owning_agent_user_id`."

    Design: Corner/entities/corner_candidate_create_with_unknown_landlord_rejected
    """
    S.reset_clock(api)
    jurisdiction = S.create_jurisdiction(api)
    ring = S.create_open_ring(api)

    refused = api.create_candidate(
        F.candidate_payload(ring["id"], UNKNOWN_ID, jurisdiction["id"]),
        headers=S.agent(),
    )
    failed(refused, ApiError.LANDLORD_NOT_FOUND, expected_status=404)

    reread = ok(api.get_search_ring(ring["id"], headers=S.director()))
    assert_fields(reread, candidate_count=0, status="OPEN", version=2)
