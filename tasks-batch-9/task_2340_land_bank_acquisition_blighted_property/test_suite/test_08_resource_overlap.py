"""
Window exclusivity over the two resources a maintenance order contends for.

A parcel's calendar is a single-resource exclusion evaluated pairwise over
half-open windows, while a contractor's crews are an aggregate count over every
one of that contractor's scheduled windows that intersects the requested one.
Both are expressed in half-open intervals, so windows that merely touch at an
instant are not in contention.
"""

from typing import Any, Dict

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_ledger_position,
    assert_maintenance_order,
    assert_same_instant,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import INV_1

# A 10,000 sqft mow is ten started thousand-square-foot blocks at 1,850 cents,
# an 18,500-cent subtotal, plus county overhead of 6.5 percent rounded half up.
MOW_ESTIMATE_10K_SQFT_CENTS = 19703
# Securing four openings: a 45,000-cent base plus 4 x 12,750 cents, a 96,000-cent
# subtotal, plus 6,240 cents of county overhead.
SECURE_ESTIMATE_4_OPENINGS_CENTS = 102240


def _order_payload(
    api: ApiClient,
    property_id: str,
    contractor_id: str,
    funding_source_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Build a maintenance-order payload, stating the parcel version just read:
    every accepted order mutates the parcel, so the version must be re-read
    before each attempt.
    """
    return factories.maintenance_order_payload(
        contractor_id,
        funding_source_id,
        fixtures.property_version(api, property_id),
        **overrides,
    )


def _parcel_with_three_crew_contractor(api: ApiClient) -> Dict[str, Any]:
    """
    One acquired 10,000 sqft parcel funded by an unrestricted line, plus a
    contractor carrying three crews and both the mowing and securing
    specialties. The donation channel with a zero title-search fee keeps the
    source's disbursed position at zero.
    """
    funding_source = fixtures.create_funding_source(api)
    prop = fixtures.create_property(
        api,
        address="170 Osprey Dr",
        situs_ward=4,
        lot_area_sqft=10000,
        assessed_value_cents=200000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=5,
    )
    fixtures.acquire_property(
        api,
        prop["id"],
        funding_source["id"],
        donor_name="Osprey Drive Trust",
        title_search_fee_cents=0,
    )
    contractor = fixtures.create_contractor(
        api,
        name="Triple Crew Services",
        max_concurrent_crews=3,
        specialties=["MOW", "SECURE"],
    )
    mow = fixtures.schedule_order(
        api,
        prop["id"],
        funding_source_id=funding_source["id"],
        contractor_id=contractor["id"],
        work_type="MOW",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-05T00:00:00Z",
    )
    return {
        "funding_source": funding_source,
        "property": prop,
        "contractor": contractor,
        "mow_order": mow,
    }


def test_order_starting_at_the_instant_another_ends_is_accepted(api: ApiClient) -> None:
    """A securing order that begins at the very instant the parcel's mowing order ends is accepted, because half-open windows that only touch do not intersect.

    "First, the parcel's own calendar is exclusive: the requested window may not intersect the window of any order on that parcel still in `SCHEDULED`, where two half-open windows intersect exactly when each starts strictly before the other ends; two windows that merely touch — one ending at the very instant the other begins — do not intersect and are both accepted."

    Design: Difficulty/resource_temporal_overlap/parcel_half_open_window_touching_allowed_overlap_rejected
    """
    bundle = _parcel_with_three_crew_contractor(api)
    prop = bundle["property"]
    assert bundle["mow_order"]["estimated_cost_cents"] == MOW_ESTIMATE_10K_SQFT_CENTS

    response = api.create_maintenance_order(
        prop["id"],
        _order_payload(
            api,
            prop["id"],
            bundle["contractor"]["id"],
            bundle["funding_source"]["id"],
            work_type="SECURE",
            window_start="2026-09-05T00:00:00Z",
            window_end="2026-09-08T00:00:00Z",
            openings_count=4,
        ),
        INV_1,
    )
    secure = validate_success(response, 201)

    assert_maintenance_order(secure)
    assert secure["status"] == "SCHEDULED"
    assert_same_instant(secure["window_start"], "2026-09-05T00:00:00Z")
    assert_same_instant(secure["window_end"], "2026-09-08T00:00:00Z")
    assert secure["estimated_cost_cents"] == SECURE_ESTIMATE_4_OPENINGS_CENTS

    # Both estimates are committed against the same source; the donation left
    # nothing disbursed.
    assert_ledger_position(
        fixtures.read_funding_source(api, bundle["funding_source"]["id"]),
        authorized_cents=1000000,
        committed_cents=MOW_ESTIMATE_10K_SQFT_CENTS
        + SECURE_ESTIMATE_4_OPENINGS_CENTS,
        disbursed_cents=0,
        available_cents=1000000
        - MOW_ESTIMATE_10K_SQFT_CENTS
        - SECURE_ESTIMATE_4_OPENINGS_CENTS,
        status="ACTIVE",
    )


def test_window_intersecting_a_scheduled_order_on_the_same_parcel_is_rejected(
    api: ApiClient,
) -> None:
    """A third order whose window genuinely overlaps an order already scheduled on the same parcel is refused as a parcel window conflict, not as a crew shortage.

    "First, the parcel's own calendar is exclusive: the requested window may not intersect the window of any order on that parcel still in `SCHEDULED`, where two half-open windows intersect exactly when each starts strictly before the other ends; two windows that merely touch — one ending at the very instant the other begins — do not intersect and are both accepted. A conflict is `ERR_PROPERTY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/parcel_half_open_window_touching_allowed_overlap_rejected
    """
    bundle = _parcel_with_three_crew_contractor(api)
    prop = bundle["property"]
    funding_source_id = bundle["funding_source"]["id"]

    secure = fixtures.schedule_order(
        api,
        prop["id"],
        funding_source_id=funding_source_id,
        contractor_id=bundle["contractor"]["id"],
        work_type="SECURE",
        window_start="2026-09-05T00:00:00Z",
        window_end="2026-09-08T00:00:00Z",
        openings_count=4,
    )
    assert secure["status"] == "SCHEDULED"

    version_before = fixtures.property_version(api, prop["id"])

    # 2026-09-04 starts strictly before the mow order ends at 2026-09-05, and the
    # mow order starts strictly before 2026-09-06: a genuine intersection.
    response = api.create_maintenance_order(
        prop["id"],
        _order_payload(
            api,
            prop["id"],
            bundle["contractor"]["id"],
            funding_source_id,
            work_type="MOW",
            window_start="2026-09-04T00:00:00Z",
            window_end="2026-09-06T00:00:00Z",
        ),
        INV_1,
    )
    error = validate_error(response, ApiErrorId.PROPERTY_WINDOW_CONFLICT.value, 409)

    # Only two of the contractor's three crews are engaged over that window, so
    # the aggregate crew rule is satisfied and cannot be the reported cause.
    assert error["error_id"] != ApiErrorId.CONTRACTOR_CAPACITY_EXCEEDED.value

    # Nothing was written: the parcel's version and the scheduled set are intact.
    assert fixtures.property_version(api, prop["id"]) == version_before
    scheduled, meta = validate_paginated(
        api.list_maintenance_orders(
            INV_1, {"property_id": prop["id"], "status": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 2
    assert len(scheduled) == 2
    assert_ledger_position(
        fixtures.read_funding_source(api, funding_source_id),
        committed_cents=MOW_ESTIMATE_10K_SQFT_CENTS
        + SECURE_ESTIMATE_4_OPENINGS_CENTS,
        disbursed_cents=0,
    )


def _three_parcels_with_two_crew_contractor(api: ApiClient) -> Dict[str, Any]:
    """
    Three acquired 10,000 sqft parcels and a mowing contractor limited to two
    concurrent crews, with mow orders already scheduled on the first two parcels
    over windows that both straddle 2026-09-06.
    """
    funding_source = fixtures.create_funding_source(api)
    contractor = fixtures.create_contractor(
        api,
        name="Two Crew Mowing",
        max_concurrent_crews=2,
        specialties=["MOW"],
    )
    parcels = []
    for address in ("180 Poplar Way", "181 Poplar Way", "182 Poplar Way"):
        prop = fixtures.create_property(
            api,
            address=address,
            situs_ward=4,
            lot_area_sqft=10000,
            assessed_value_cents=200000,
            structure_present=False,
            structure_condition_grade="C",
            vacancy_months=5,
        )
        fixtures.acquire_property(
            api,
            prop["id"],
            funding_source["id"],
            donor_name="Poplar Way Trust",
            title_search_fee_cents=0,
        )
        parcels.append(prop)

    for prop, (start, end) in zip(
        parcels[:2],
        (
            ("2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z"),
            ("2026-09-05T00:00:00Z", "2026-09-12T00:00:00Z"),
        ),
    ):
        fixtures.schedule_order(
            api,
            prop["id"],
            funding_source_id=funding_source["id"],
            contractor_id=contractor["id"],
            work_type="MOW",
            window_start=start,
            window_end=end,
        )

    return {
        "funding_source": funding_source,
        "contractor": contractor,
        "parcels": parcels,
    }


def test_intersecting_order_count_equal_to_the_crew_ceiling_is_rejected(
    api: ApiClient,
) -> None:
    """A contractor already running exactly as many intersecting orders as it has crews may take no further order over that window, even on a parcel with an empty calendar.

    "Third, the contractor's crews are finite: count that contractor's `SCHEDULED` orders whose half-open windows intersect the requested one, and the count must be strictly less than `max_concurrent_crews` — a count equal to the crew ceiling is already a rejection, reported as `ERR_CONTRACTOR_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/contractor_crew_capacity_at_aggregate_boundary
    """
    bundle = _three_parcels_with_two_crew_contractor(api)
    third = bundle["parcels"][2]
    version_before = fixtures.property_version(api, third["id"])

    # [09-06, 09-08) intersects both scheduled windows, so the count is exactly
    # the two-crew ceiling.
    response = api.create_maintenance_order(
        third["id"],
        _order_payload(
            api,
            third["id"],
            bundle["contractor"]["id"],
            bundle["funding_source"]["id"],
            work_type="MOW",
            window_start="2026-09-06T00:00:00Z",
            window_end="2026-09-08T00:00:00Z",
        ),
        INV_1,
    )
    error = validate_error(response, ApiErrorId.CONTRACTOR_CAPACITY_EXCEEDED.value, 409)

    # The three orders sit on three different parcels, so the parcel's own
    # exclusive calendar is untouched.
    assert error["error_id"] != ApiErrorId.PROPERTY_WINDOW_CONFLICT.value

    assert fixtures.property_version(api, third["id"]) == version_before
    scheduled, meta = validate_paginated(
        api.list_maintenance_orders(
            INV_1, {"property_id": third["id"], "status": "SCHEDULED"}
        )
    )
    assert meta["total_count"] == 0
    assert scheduled == []


def test_order_touching_the_end_of_a_scheduled_window_engages_no_crew(
    api: ApiClient,
) -> None:
    """Moving the same order to a window that only touches the end of the contractor's last scheduled window drops the intersecting count to zero and the order is accepted.

    "Third, the contractor's crews are finite: count that contractor's `SCHEDULED` orders whose half-open windows intersect the requested one, and the count must be strictly less than `max_concurrent_crews` — a count equal to the crew ceiling is already a rejection, reported as `ERR_CONTRACTOR_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/contractor_crew_capacity_at_aggregate_boundary
    """
    bundle = _three_parcels_with_two_crew_contractor(api)
    third = bundle["parcels"][2]
    funding_source_id = bundle["funding_source"]["id"]
    version_before = fixtures.property_version(api, third["id"])

    # [09-12, 09-14) begins at the instant the second order ends and lies wholly
    # after the first, so it intersects neither.
    response = api.create_maintenance_order(
        third["id"],
        _order_payload(
            api,
            third["id"],
            bundle["contractor"]["id"],
            funding_source_id,
            work_type="MOW",
            window_start="2026-09-12T00:00:00Z",
            window_end="2026-09-14T00:00:00Z",
        ),
        INV_1,
    )
    order = validate_success(response, 201)

    assert_maintenance_order(order)
    assert order["status"] == "SCHEDULED"
    assert_same_instant(order["window_start"], "2026-09-12T00:00:00Z")
    assert_same_instant(order["window_end"], "2026-09-14T00:00:00Z")
    assert order["estimated_cost_cents"] == MOW_ESTIMATE_10K_SQFT_CENTS

    assert fixtures.property_version(api, third["id"]) == version_before + 1
    assert_ledger_position(
        fixtures.read_funding_source(api, funding_source_id),
        authorized_cents=1000000,
        committed_cents=3 * MOW_ESTIMATE_10K_SQFT_CENTS,
        disbursed_cents=0,
        available_cents=1000000 - 3 * MOW_ESTIMATE_10K_SQFT_CENTS,
        status="ACTIVE",
    )
