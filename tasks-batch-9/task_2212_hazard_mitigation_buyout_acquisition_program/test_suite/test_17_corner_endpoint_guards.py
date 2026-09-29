"""Endpoints: per-parent uniqueness on disconnections and the viability gate on closeout."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


ADMIN = TEST_USERS["program_administrator_headers"]


# ─── The utility type, unique per work order rather than per parcel ───────────

def test_the_repeated_electric_row_is_refused_on_its_own_work_order_only(api):
    """Both work orders sit on one parcel, yet the second may still order ELECTRIC.

    "A `utility_type` is unique within its work order, and a second disconnection for
    the same utility on the same work order is `ERR_DUPLICATE_UTILITY_TYPE` - the same
    `utility_type` may of course appear once on each of many work orders."

    "The parent work order must be in `ISSUED`, `UTILITY_HOLD` or `READY`, otherwise
    `ERR_INVALID_WORK_ORDER_STATE`."

    "The disconnection opens in `status` `PENDING` at `version` 1 with
    `failed_attempt_count` 0 and `confirmation_reference` and `resolved_at` null.
    Creating the **first** child moves the parent work order from `ISSUED` to
    `UTILITY_HOLD` and advances the parent's `version` by 1."

    Design: Corner/endpoints/a_second_disconnection_for_the_same_utility_type_on_one_work_order_is_refused
    """
    api.set_clock("2026-08-01T00:00:00Z")
    project = fixtures.create_draft_project(
        api, project_code="EP-DUPUT-1", grant_program="FMA"
    )
    parcel = fixtures.create_parcel(
        api, project, apn="APN-EP-DUPUT-1", site_address="4201 River Rd",
        acreage=0.34, occupancy_type="VACANT", structure_type="NONE",
    )
    contractor = fixtures.create_contractor(
        api, name="Cedar Point Demolition", license_no="DEM-9",
        asbestos_certified=True, max_concurrent_work_orders=3,
    )
    coordinator = make_subrecipient_coordinator_headers(project["id"])

    first_order = fixtures.issue_work_order(
        api, project, parcel["id"], contractor["id"],
        asbestos_survey_status="CLEARED",
        scheduled_start="2026-09-01T08:00:00Z",
        scheduled_end="2026-09-03T17:00:00Z",
    )
    first_child = validate_success(
        api.create_utility_disconnection(
            first_order["id"],
            factories.create_utility_disconnection_payload(
                first_order["id"], "ELECTRIC", provider_name="Riverbend Electric Coop"
            ),
            coordinator,
        ),
        201,
    )
    assert first_child["status"] == "PENDING"

    second_order = fixtures.issue_work_order(
        api, project, parcel["id"], contractor["id"],
        asbestos_survey_status="CLEARED",
        scheduled_start="2026-10-01T08:00:00Z",
        scheduled_end="2026-10-03T17:00:00Z",
    )

    validate_error(
        api.create_utility_disconnection(
            first_order["id"],
            factories.create_utility_disconnection_payload(
                first_order["id"], "ELECTRIC",
                provider_name="Another Electric Provider",
            ),
            coordinator,
        ),
        ApiErrorId.ERR_DUPLICATE_UTILITY_TYPE.value,
        409,
    )

    twin = validate_success(
        api.create_utility_disconnection(
            second_order["id"],
            factories.create_utility_disconnection_payload(
                second_order["id"], "ELECTRIC",
                provider_name="Riverbend Electric Coop",
            ),
            coordinator,
        ),
        201,
    )
    assert twin["status"] == "PENDING"
    assert twin["utility_type"] == "ELECTRIC"

    children, meta = validate_paginated(
        api.list_utility_disconnections(
            ADMIN, params={"work_order_id": first_order["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert len(children) == 1

    held = validate_success(api.get_demolition_work_order(first_order["id"], ADMIN))
    assert held["status"] == "UTILITY_HOLD"
    also_held = validate_success(
        api.get_demolition_work_order(second_order["id"], ADMIN)
    )
    assert also_held["status"] == "UTILITY_HOLD"


# ─── The viability gate standing in front of closeout ─────────────────────────

def test_closeout_is_refused_while_the_only_parcel_acquired_nothing(api):
    """A cancelled acquisition leaves the denominator at 1 and the node set empty.

    "The denominator is `participating_parcel_count`, the count of parcels of this
    project whose `participation_status` is `NOT_CONTACTED`, `INTERESTED`,
    `VOLUNTARY_CONFIRMED` or `DECLINED` - that is, every parcel except those that have
    withdrawn."

    "Then `contiguous_open_space_parcel_count` is the size of the largest component, or
    0 when the node set is empty."

    "Link one: the parcel's `acquisition_status` moves to `ACQUISITION_CANCELLED` if and
    only if it is currently one of `NOT_STARTED`, `APPRAISAL_IN_PROGRESS`,
    `VALUE_ESTABLISHED`, `OFFER_OUTSTANDING` or `OFFER_ACCEPTED`."

    "And the project's `viability_status` must not be `NONVIABLE`, otherwise
    `ERR_NEIGHBORHOOD_NONVIABLE`; `AT_RISK` and `VIABLE` both pass, because the program
    tolerates a partially assembled block but not a failed one."

    Design: Corner/endpoints/closeout_initiation_is_refused_while_the_neighborhood_is_nonviable
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_approved_project(
        api,
        project_overrides={"project_code": "EP-VIAB-1", "grant_program": "FMA"},
        parcel_overrides={
            "apn": "APN-EP-VIAB-1", "site_address": "4301 River Rd", "acreage": 0.34,
            "occupancy_type": "OWNER_OCCUPIED", "structure_type": "SINGLE_FAMILY",
        },
    )
    project = state["project"]
    parcel = state["parcel"]
    coordinator = make_subrecipient_coordinator_headers(project["id"])

    validate_success(
        api.record_participation(
            parcel["id"],
            factories.participation_payload(parcel["id"], "INTERESTED"),
            coordinator,
        )
    )
    declined = validate_success(
        api.record_participation(
            parcel["id"],
            factories.participation_payload(
                parcel["id"], "DECLINE", decision_note="owner will not sell"
            ),
            coordinator,
        )
    )
    assert declined["participation_status"] == "DECLINED"
    assert declined["acquisition_status"] == "ACQUISITION_CANCELLED"

    nonviable = validate_success(api.get_mitigation_project(project["id"], ADMIN))
    assert nonviable["viability_status"] == "NONVIABLE"
    assert float(nonviable["neighborhood_viability_ratio"]) == 0.0
    assert nonviable["participating_parcel_count"] == 1
    assert nonviable["contiguous_open_space_parcel_count"] == 0
    assert nonviable["largest_component_parcel_ids"] == []

    validate_error(
        api.closeout_mitigation_project(
            project["id"],
            factories.closeout_payload(project["id"], "INITIATE"),
            ADMIN,
        ),
        ApiErrorId.ERR_NEIGHBORHOOD_NONVIABLE.value,
        409,
    )

    unchanged = validate_success(api.get_mitigation_project(project["id"], ADMIN))
    assert unchanged["status"] == "APPROVED"
    assert unchanged["viability_status"] == "NONVIABLE"
