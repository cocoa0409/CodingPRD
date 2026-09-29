"""Trunk group requests, provisioning against the facility ceiling and activation."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_AGREEMENT_NOT_EFFECTIVE,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_DUPLICATE_TRUNK_GROUP_SERIAL,
    ERR_INVALID_TRUNK_GROUP_STATE,
    ERR_POI_CAPACITY_EXCEEDED,
    ERR_TRANSIT_TRAFFIC_NOT_PERMITTED,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_envelope,
    assert_pct,
    assert_trunk_group_statuses,
    assert_versioned_entity,
)
from test_helpers.constants import (
    LATA_HOUSTON,
    POI_CLLI_DALLAS,
    POI_CLLI_HOUSTON,
)
from test_helpers.factories import (
    measurement_payload,
    provision_payload,
    trunk_group_payload,
)
from test_helpers.fixtures import (
    read_agreement,
    read_trunk_group,
    setup_draft_agreement,
    setup_effective_agreement,
    setup_executed_agreement,
    setup_in_service_trunk_group,
    setup_provisioned_trunk_group,
    setup_requested_trunk_group,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_trunk_group_creation_under_an_unknown_agreement_is_not_found(
    api, planner_headers
):
    """An unresolvable agreement_id in the body answers ERR_AGREEMENT_NOT_FOUND.

    PRD 3.3: "A `NetworkPlanner` requests a **trunk group** under an agreement, naming the `agreement_id`, a `trunk_group_serial` that is non-empty and unique among that agreement's trunk groups (a repeat is refused with `ERR_DUPLICATE_TRUNK_GROUP_SERIAL`), the `poi_clli_code` of the point of interconnection it lands on — exactly eleven uppercase characters — the `lata_code` of the LATA in which that point sits, given as exactly three digits, a `poi_type` drawn from `MEET_POINT`, `COLLOCATION` and `LEASED_FACILITY`, a `direction` drawn from `ONE_WAY_OUTBOUND`, `ONE_WAY_INBOUND` and `TWO_WAY`, a `traffic_type` drawn from `LOCAL_INTERCONNECTION`, `ACCESS_TANDEM` and `TRANSIT`, plus the forecast the counterparty has committed to: `forecast_busy_hour_ccs` at two decimals and greater than zero, covering `forecast_horizon_quarters` quarters, between 1 and 8 inclusive."
    PRD 2.7: "an `agreement_id` segment yields `ERR_AGREEMENT_NOT_FOUND`"
    PRD 2.7: "All thirteen not-found codes carry HTTP 404."

    Design: Corner/entities/trunk_group_creation_under_an_unknown_agreement_is_not_found
    """
    state = setup_draft_agreement(api, ensure_local_rate=False)

    response = api.create_trunk_group(
        trunk_group_payload(UNKNOWN_ID), planner_headers
    )
    validate_error(response, ERR_AGREEMENT_NOT_FOUND, expected_status=404)

    _, meta = validate_paginated(api.list_trunk_groups(planner_headers))
    assert meta["total_count"] == 0, "no orphan trunk group row may be written"

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["total_in_service_trunks"] == 0
    assert agreement["version"] == 1, "the live agreement was untouched"


def test_new_trunk_group_starts_requested_with_augment_status_none(
    api, planner_headers
):
    """A freshly requested group is REQUESTED/NONE and cannot yet carry a study.

    PRD 3.3: "A newly requested trunk group starts with `service_status` `REQUESTED` and `augment_status` `NONE`, with `provisioned_trunks`, `required_trunks` and `open_augment_order_count` all 0, `latest_blocking_pct` at 0.00, and `in_service_at` null."
    PRD 3.4: "Capacity management is driven by **traffic studies**. Either a `NetworkPlanner` or the counterparty's `CarrierRepresentative` records a study against a trunk group, and a study may only be recorded while that trunk group's `service_status` is `IN_SERVICE`; a study against a trunk group in `REQUESTED`, `PROVISIONED`, `DISCONNECT_PENDING` or `DISCONNECTED` is refused with `ERR_INVALID_TRUNK_GROUP_STATE`."

    Design: Corner/state_machines/new_trunk_group_starts_requested_with_augment_status_none
    """
    state = setup_effective_agreement(api)

    response = api.create_trunk_group(
        trunk_group_payload(state["agreement_id"]), planner_headers
    )
    trunk_group = validate_success(response, expected_status=201)

    assert_trunk_group_statuses(trunk_group, "REQUESTED", "NONE")
    assert trunk_group["provisioned_trunks"] == 0
    assert trunk_group["required_trunks"] == 0
    assert trunk_group["open_augment_order_count"] == 0
    assert_pct(trunk_group["latest_blocking_pct"], 0.00, "latest_blocking_pct")
    assert trunk_group["in_service_at"] is None
    assert_versioned_entity(trunk_group, expected_version=1, label="trunk group")

    too_early = api.create_traffic_measurement(
        trunk_group["id"], measurement_payload(), planner_headers
    )
    validate_error(too_early, ERR_INVALID_TRUNK_GROUP_STATE, expected_status=409)


def test_trunk_group_provisioned_trunks_input_ignored(api, planner_headers):
    """Client-supplied provisioned_trunks and required_trunks are both discarded.

    PRD 3.3: "A newly requested trunk group starts with `service_status` `REQUESTED` and `augment_status` `NONE`, with `provisioned_trunks`, `required_trunks` and `open_augment_order_count` all 0, `latest_blocking_pct` at 0.00, and `in_service_at` null."
    PRD 3.3: "Provisioning moves the trunk group `REQUESTED → PROVISIONED`. The `NetworkPlanner` supplies `provisioned_trunks`, which must be a **positive multiple of 24** — the number of trunks in a DS1 — and the request is measured against the shared facility at the point of interconnection."

    Design: Corner/entities/trunk_group_provisioned_trunks_input_ignored
    """
    state = setup_effective_agreement(api)

    response = api.create_trunk_group(
        trunk_group_payload(
            state["agreement_id"], provisioned_trunks=96, required_trunks=96
        ),
        planner_headers,
    )
    trunk_group = validate_success(response, expected_status=201)

    assert trunk_group["provisioned_trunks"] == 0, (
        "the client-supplied 96 provisioned trunks must be discarded"
    )
    assert trunk_group["required_trunks"] == 0
    assert_pct(trunk_group["latest_blocking_pct"], 0.00, "latest_blocking_pct")
    assert trunk_group["open_augment_order_count"] == 0
    assert_trunk_group_statuses(trunk_group, "REQUESTED", "NONE")
    assert trunk_group["in_service_at"] is None

    assert read_agreement(api, state["agreement_id"])["total_in_service_trunks"] == 0


def test_trunk_group_listing_paginates_and_filters_by_agreement(api, planner_headers):
    """The trunk group collection pages in created_at order and filters by POI.

    PRD 2.3: "Every collection endpoint accepts two optional query parameters. `limit` controls the page size: it defaults to 10, may be no smaller than 1 and no larger than 100. `offset` controls the starting position: it defaults to 0 and may be no smaller than 0."
    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside `meta`. `total_count` is the number of rows matching the request's filters before the page window is applied, and `has_more` is true when rows remain beyond the current window. Unless a specific endpoint states otherwise, every collection is ordered by `created_at` ascending; where two rows share a `created_at` instant, insertion order breaks the tie."
    PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/trunk_group_listing_paginates_and_filters_by_agreement
    """
    state = setup_effective_agreement(api)
    agreement_id = state["agreement_id"]
    first = setup_in_service_trunk_group(api, agreement_id, 24)
    second = setup_in_service_trunk_group(
        api, agreement_id, 24, trunk_group_serial="TG-DLLS-OUT-002",
        direction="ONE_WAY_OUTBOUND",
    )
    third = setup_in_service_trunk_group(
        api,
        agreement_id,
        24,
        trunk_group_serial="TG-HSTN-TWOWAY-003",
        poi_clli_code=POI_CLLI_HOUSTON,
        lata_code=LATA_HOUSTON,
    )

    page_one_response = api.list_trunk_groups(
        planner_headers, params={"agreement_id": agreement_id, "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(page_one_response)
    assert_envelope(page_one_response, "array")
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert_created_at_ascending(rows, "trunk group page one")

    rows_two, meta_two = validate_paginated(
        api.list_trunk_groups(
            planner_headers,
            params={"agreement_id": agreement_id, "limit": 2, "offset": 2},
        )
    )
    assert [row["id"] for row in rows_two] == [third["id"]]
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2

    for row in rows + rows_two:
        assert row["service_status"] == "IN_SERVICE"
        assert row["provisioned_trunks"] == 24

    _, dallas_meta = validate_paginated(
        api.list_trunk_groups(
            planner_headers,
            params={"agreement_id": agreement_id, "poi_clli_code": POI_CLLI_DALLAS},
        )
    )
    assert dallas_meta["total_count"] == 2, "two of the three groups land at Dallas"


def test_provisioning_past_the_poi_facility_ceiling_is_refused(api, planner_headers):
    """The sibling sum at a shared POI blocks a provisioning that would breach capacity.

    PRD 3.3: "Sum `provisioned_trunks` over the sibling trunk groups that share the same agreement and the same `poi_clli_code` and whose `service_status` is either `PROVISIONED` or `IN_SERVICE`, add the requested quantity, and the total must be no greater than the agreement's `poi_facility_capacity_trunks`."
    PRD 3.3: "Exceeding that ceiling is refused with `ERR_POI_CAPACITY_EXCEEDED`; a total exactly equal to the ceiling is permitted."
    PRD 3.3: "On success the trunk group's `provisioned_trunks` is set to the supplied value and its `version` increments by 1."

    Design: Corner/validations/provisioning_past_the_poi_facility_ceiling_is_refused
    """
    state = setup_effective_agreement(api, poi_facility_capacity_trunks=48)
    first = setup_in_service_trunk_group(api, state["agreement_id"], 48)
    second = setup_requested_trunk_group(
        api,
        state["agreement_id"],
        trunk_group_serial="TG-DLLS-OUT-002",
        direction="ONE_WAY_OUTBOUND",
    )

    response = api.provision_trunk_group(
        second["id"], provision_payload(24), planner_headers
    )
    validate_error(response, ERR_POI_CAPACITY_EXCEEDED, expected_status=409)

    refused = read_trunk_group(api, second["id"])
    assert refused["service_status"] == "REQUESTED"
    assert refused["provisioned_trunks"] == 0

    untouched = read_trunk_group(api, first["id"])
    assert untouched["provisioned_trunks"] == 48

    assert read_agreement(api, state["agreement_id"])["total_in_service_trunks"] == 48


def test_transit_trunk_group_under_a_non_transit_agreement_is_refused(
    api, planner_headers
):
    """A TRANSIT group needs the pinned privilege, and the refusal consumes no serial.

    PRD 3.3: "Transit traffic is a negotiated privilege: a trunk group whose `traffic_type` is `TRANSIT` may only be created under an agreement whose pinned `transit_traffic_allowed` is true, and otherwise the request is refused with `ERR_TRANSIT_TRAFFIC_NOT_PERMITTED`."
    PRD 3.3: "A newly requested trunk group starts with `service_status` `REQUESTED` and `augment_status` `NONE`, with `provisioned_trunks`, `required_trunks` and `open_augment_order_count` all 0, `latest_blocking_pct` at 0.00, and `in_service_at` null."

    Design: Corner/validations/transit_trunk_group_under_a_non_transit_agreement_is_refused
    """
    state = setup_effective_agreement(api)
    assert state["agreement"]["transit_traffic_allowed"] is False

    refused = api.create_trunk_group(
        trunk_group_payload(
            state["agreement_id"],
            trunk_group_serial="TG-DLLS-TRANSIT-009",
            traffic_type="TRANSIT",
        ),
        planner_headers,
    )
    validate_error(refused, ERR_TRANSIT_TRAFFIC_NOT_PERMITTED, expected_status=422)

    allowed = api.create_trunk_group(
        trunk_group_payload(
            state["agreement_id"],
            trunk_group_serial="TG-DLLS-TRANSIT-009",
            traffic_type="LOCAL_INTERCONNECTION",
        ),
        planner_headers,
    )
    trunk_group = validate_success(allowed, expected_status=201)
    assert trunk_group["traffic_type"] == "LOCAL_INTERCONNECTION"
    assert trunk_group["service_status"] == "REQUESTED", (
        "the serial was never consumed by the rejected TRANSIT request"
    )


def test_duplicate_trunk_group_serial_under_the_same_agreement_is_refused(
    api, planner_headers
):
    """Serial uniqueness is scoped to the agreement, not to the point of interconnection.

    PRD 3.3: "A `NetworkPlanner` requests a **trunk group** under an agreement, naming the `agreement_id`, a `trunk_group_serial` that is non-empty and unique among that agreement's trunk groups (a repeat is refused with `ERR_DUPLICATE_TRUNK_GROUP_SERIAL`), the `poi_clli_code` of the point of interconnection it lands on — exactly eleven uppercase characters — the `lata_code` of the LATA in which that point sits, given as exactly three digits, a `poi_type` drawn from `MEET_POINT`, `COLLOCATION` and `LEASED_FACILITY`, a `direction` drawn from `ONE_WAY_OUTBOUND`, `ONE_WAY_INBOUND` and `TWO_WAY`, a `traffic_type` drawn from `LOCAL_INTERCONNECTION`, `ACCESS_TANDEM` and `TRANSIT`, plus the forecast the counterparty has committed to: `forecast_busy_hour_ccs` at two decimals and greater than zero, covering `forecast_horizon_quarters` quarters, between 1 and 8 inclusive."
    PRD 2.7: "Uniqueness, window-overlap, capacity and round-limit constraints come next, followed by the two payload-shape constraints on installed trunks and agreed minutes and the clock monotonicity check."

    Design: Corner/errors/duplicate_trunk_group_serial_under_the_same_agreement_is_refused
    """
    state = setup_effective_agreement(api)
    incumbent = setup_in_service_trunk_group(api, state["agreement_id"], 48)

    response = api.create_trunk_group(
        trunk_group_payload(
            state["agreement_id"],
            trunk_group_serial=incumbent["trunk_group_serial"],
            poi_clli_code=POI_CLLI_HOUSTON,
            lata_code=LATA_HOUSTON,
            forecast_busy_hour_ccs=900.00,
        ),
        planner_headers,
    )
    validate_error(response, ERR_DUPLICATE_TRUNK_GROUP_SERIAL, expected_status=409)

    _, meta = validate_paginated(
        api.list_agreement_trunk_groups(state["agreement_id"], planner_headers)
    )
    assert meta["total_count"] == 1, "the duplicate must not be persisted"

    assert read_agreement(api, state["agreement_id"])["total_in_service_trunks"] == 48


def test_trunk_group_activation_under_an_executed_parent_is_refused(
    api, planner_headers
):
    """A PROVISIONED group cannot go into service while its parent is only EXECUTED.

    PRD 3.3: "Activation also carries a cross-entity guard: the parent agreement's `status` must be `EFFECTIVE`, since a trunk group cannot carry traffic under an agreement that has not gone live."
    PRD 3.3: "When the parent is in any other status the request is refused with `ERR_AGREEMENT_NOT_EFFECTIVE`."
    PRD 3.3: "On success the trunk group's `in_service_at` is stamped from the logical clock, the agreement's `total_in_service_trunks` increases by that trunk group's `provisioned_trunks`, and both the trunk group's and the agreement's `version` increment by 1."

    Design: Difficulty/cross_entity_state_dependency/trunk_group_activation_requires_effective_parent_agreement
    """
    state = setup_executed_agreement(api)
    trunk_group = setup_provisioned_trunk_group(api, state["agreement_id"], 48)
    assert trunk_group["service_status"] == "PROVISIONED"

    response = api.activate_trunk_group(trunk_group["id"], {}, planner_headers)
    validate_error(response, ERR_AGREEMENT_NOT_EFFECTIVE, expected_status=409)

    unchanged = read_trunk_group(api, trunk_group["id"])
    assert unchanged["service_status"] == "PROVISIONED"
    assert unchanged["in_service_at"] is None

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["status"] == "EXECUTED"
    assert agreement["total_in_service_trunks"] == 0


def test_trunk_group_activation_succeeds_once_the_parent_is_effective(
    api, manager_headers, planner_headers
):
    """The same activation succeeds after the agreement goes live, moving 48 trunks.

    PRD 3.3: "Activation moves the trunk group `PROVISIONED → IN_SERVICE`; a trunk group in `REQUESTED`, `IN_SERVICE`, `DISCONNECT_PENDING` or `DISCONNECTED` is refused with `ERR_INVALID_TRUNK_GROUP_STATE`."
    PRD 3.3: "On success the trunk group's `in_service_at` is stamped from the logical clock, the agreement's `total_in_service_trunks` increases by that trunk group's `provisioned_trunks`, and both the trunk group's and the agreement's `version` increment by 1."
    PRD 3.2: "Activation recomputes `capacity_posture`, which resolves to `NORMAL` when no child augment order is open, and increments the agreement's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/trunk_group_activation_requires_effective_parent_agreement
    """
    state = setup_executed_agreement(api)
    trunk_group = setup_provisioned_trunk_group(api, state["agreement_id"], 48)
    validate_error(
        api.activate_trunk_group(trunk_group["id"], {}, planner_headers),
        ERR_AGREEMENT_NOT_EFFECTIVE,
        expected_status=409,
    )

    activated_agreement = validate_success(
        api.activate_agreement(state["agreement_id"], {}, manager_headers),
        expected_status=200,
    )
    assert activated_agreement["status"] == "EFFECTIVE"

    response = api.activate_trunk_group(trunk_group["id"], {}, planner_headers)
    in_service = validate_success(response, expected_status=200)
    assert in_service["service_status"] == "IN_SERVICE"
    assert in_service["provisioned_trunks"] == 48

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["total_in_service_trunks"] == 48
    assert agreement["capacity_posture"] == "NORMAL"
