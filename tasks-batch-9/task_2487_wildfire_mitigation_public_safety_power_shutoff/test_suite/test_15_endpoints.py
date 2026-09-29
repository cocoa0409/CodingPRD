"""The API surface itself: that every child row is reachable from its parent, that a list's
counters follow the filter rather than the page, that one action call returns all of its
declared side effects, and that a nested read resolves its parent before it answers."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_CIRCUIT_NOT_FOUND,
    ERR_PATROL_ASSIGNMENT_NOT_FOUND,
    ERR_RESOURCE_CENTER_DISTRICT_MISMATCH,
    ERR_WEATHER_STATION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_activation_summary,
    assert_batch_outcome,
    assert_center_state,
    assert_circuit_state,
    assert_hardening_ledger,
    assert_instant,
    assert_integer,
    assert_record,
)
from test_helpers.constants import DEFAULT_LIMIT, UNKNOWN_UUID
from test_helpers.fixtures import (
    ADVANCE_SEND_AT,
    arm_event,
    build_advance_dispatched_event,
    build_approved_project,
    build_scoped_event,
    compute_index,
    dispatch_batch,
    file_observation,
    move_clock,
    open_event,
    plan_batch,
    read_center,
    read_circuit,
    read_event,
    read_records,
    record_completion,
    register_center,
    register_circuit,
    register_customer,
    register_station,
    scope_event,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    ENGINEER_HEADERS,
    INSPECTOR_HEADERS,
    LIAISON_HEADERS,
    OFFICER_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_HEADERS,
    SUPERVISOR_HEADERS,
)
from test_helpers.types import (
    BatchStatus,
    Channel,
    CustomerClass,
    DeliveryStatus,
    EnergizationState,
    EventScopeStatus,
    HftdTier,
    NotificationStage,
    NotificationStatus,
    ProgramType,
    ProjectStatus,
    ResourceCenterStatus,
    RiskPosture,
    TelemetryStatus,
)

COMPLETION_DATE = "2026-07-01T00:00:00Z"

#: EV-MIKE's eight-hour window over district D-WEST, and a second window well clear of it.
MIKE_FORECAST_DATE = "2026-09-10"
MIKE_OBSERVED_AT = "2026-09-09T12:00:00Z"
MIKE_ONSET_AT = "2026-09-10T00:00:00Z"
MIKE_ALL_CLEAR_AT = "2026-09-10T08:00:00Z"
MIKE_ADVANCE_SEND_AT = "2026-09-08T00:00:00Z"
SECOND_ONSET_AT = "2026-09-20T00:00:00Z"
SECOND_ALL_CLEAR_AT = "2026-09-20T08:00:00Z"


def _mike_chain():
    """EV-MIKE armed over district D-WEST — TIER_2 MIKE, 11.0 overhead miles, an R4 index
    of exactly 60.00, one critical facility and four medical-baseline accounts, so the
    required resource-centre capacity is five seats."""
    mike = register_circuit(
        circuit_code="MIKE",
        district_code="D-WEST",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=11.0,
        equipment_condition_index=80,
    )
    station = register_station(
        mike["id"],
        station_code="WS-MIKE",
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        station["id"],
        MIKE_OBSERVED_AT,
        wind_gust_mph=40.0,
        relative_humidity_pct=35.0,
        dead_fuel_moisture_pct=7.0,
    )
    index = compute_index(mike["id"], MIKE_FORECAST_DATE)
    register_customer(
        mike["id"],
        account_number="ACC-M1",
        customer_class=CustomerClass.CRITICAL_FACILITY.value,
        notification_channels=[Channel.SMS.value],
        address_zone_code="ZM",
    )
    for ordinal in range(2, 6):
        register_customer(
            mike["id"],
            account_number=f"ACC-M{ordinal}",
            medical_baseline=True,
            notification_channels=[Channel.SMS.value],
            address_zone_code="ZM",
        )
    event = open_event(
        index["id"],
        onset_at=MIKE_ONSET_AT,
        all_clear_at=MIKE_ALL_CLEAR_AT,
        event_code="EV-MIKE",
    )
    event = scope_event(event["id"], event["version"])
    batch = plan_batch(
        event["id"], NotificationStage.ADVANCE_48H.value, MIKE_ADVANCE_SEND_AT
    )
    move_clock(MIKE_ADVANCE_SEND_AT)
    dispatch_batch(batch["id"])
    return {"mike": mike, "index": index, "event": arm_event(event["id"])}


# --------------------------------------------------------------------------
# Reverse reachability
# --------------------------------------------------------------------------
def test_every_child_row_is_reachable_from_the_identifier_of_its_parent():
    """Ten reads, one per declared foreign key: the nine hierarchical keys through their
    sub-resource routes, the delivery records through their filter, and the circuit's own
    self-reference through the upstream filter that resolves it backwards.

    "Because a circuit stores only its parent, discovering a circuit's children means
    listing circuits filtered by `upstream_circuit_id` — that filter is the
    reverse-reachability channel for the feeder chain, alongside filters on
    `district_code`, `hftd_tier`, `energization_state`, and `risk_posture`."

    "Every list response populates four fields inside `meta`: `limit` (the effective
    page size actually applied), `offset` (the effective offset actually applied),
    `total_count` (the number of rows matching the filters *before* the page window is
    applied), and `has_more` (true when rows remain beyond the current page, false
    otherwise)."

    "List every shutoff scope row that has named this circuit, filterable by
    `scope_status`."

    Design: Corner/endpoints/every_child_row_is_reachable_from_its_parent_id
    """
    ctx = build_advance_dispatched_event()
    alpha_id = ctx["alpha"]["id"]
    metas = {}

    stations, metas["stations"] = validate_paginated(
        api_client.list_circuit_weather_stations(alpha_id, ANALYST_HEADERS)
    )
    _, metas["observations"] = validate_paginated(
        api_client.list_station_observations(ctx["ws_a1"]["id"], ANALYST_HEADERS)
    )
    _, metas["customers"] = validate_paginated(
        api_client.list_circuit_customers(alpha_id, LIAISON_HEADERS)
    )
    _, metas["indices"] = validate_paginated(
        api_client.list_circuit_fire_potential_indices(alpha_id, ANALYST_HEADERS)
    )
    _, metas["circuit_scopes"] = validate_paginated(
        api_client.list_circuit_event_scopes(alpha_id, ENGINEER_HEADERS)
    )
    projects, metas["projects"] = validate_paginated(
        api_client.list_circuit_mitigation_projects(alpha_id, INSPECTOR_HEADERS)
    )
    _, metas["event_scopes"] = validate_paginated(
        api_client.list_event_scopes(ctx["event_id"], OFFICER_HEADERS)
    )
    _, metas["batches"] = validate_paginated(
        api_client.list_event_notification_batches(ctx["event_id"], LIAISON_HEADERS)
    )
    _, metas["records"] = validate_paginated(
        api_client.list_notification_records(
            LIAISON_HEADERS, {"notification_batch_id": ctx["batch_advance"]["id"]}
        )
    )
    children, metas["children"] = validate_paginated(
        api_client.list_circuits(PLANNER_HEADERS, {"upstream_circuit_id": alpha_id})
    )

    assert_integer(metas["stations"]["total_count"], 2)
    assert_integer(metas["observations"]["total_count"], 2)
    assert_integer(metas["customers"]["total_count"], 3)
    assert_integer(metas["indices"]["total_count"], 1)
    assert_integer(metas["circuit_scopes"]["total_count"], 1)
    assert_integer(metas["event_scopes"]["total_count"], 3)
    assert_integer(metas["batches"]["total_count"], 1)
    assert_integer(metas["records"]["total_count"], 5)

    # A childless parent answers with an empty page rather than a 404.
    assert_integer(metas["projects"]["total_count"], 0)
    assert projects == [], "a circuit with no work packages returns an empty array"

    assert {row["station_code"] for row in stations} == {"WS-A1", "WS-A2"}
    assert [row["circuit_code"] for row in children] == ["BRAVO"]

    for name, meta in metas.items():
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"the {name} listing must carry meta.{field}"


# --------------------------------------------------------------------------
# Listing semantics
# --------------------------------------------------------------------------
def test_the_record_listing_counts_the_filtered_set_and_never_the_page():
    """One dispatch writes five records. Unfiltered they fill a default page of ten; the
    delivery filter narrows the count to one; and a second page of the delivered subset
    reports the subset's own total while returning only the rows it holds.

    "Records can be listed filtered by `notification_batch_id`, `customer_id`, and
    `delivery_status`; an unresolvable record identifier yields
    `ERR_NOTIFICATION_RECORD_NOT_FOUND`."

    "Every list response populates four fields inside `meta`: `limit` (the effective
    page size actually applied), `offset` (the effective offset actually applied),
    `total_count` (the number of rows matching the filters *before* the page window is
    applied), and `has_more` (true when rows remain beyond the current page, false
    otherwise)."

    "`channel_used` is the first channel in the fixed priority order that the account
    has consented to and that is not forbidden; when no channel survives the filter,
    `channel_used` is null."

    Design: Corner/endpoints/notification_record_listing_combines_filters_with_the_default_page
    """
    ctx = build_advance_dispatched_event()

    everything, all_meta = validate_paginated(
        api_client.list_notification_records(REVIEWER_HEADERS)
    )
    assert len(everything) == 5, "the default page holds all five records"
    assert_integer(all_meta["limit"], DEFAULT_LIMIT)
    assert_integer(all_meta["offset"], 0)
    assert_integer(all_meta["total_count"], 5)
    assert all_meta["has_more"] is False

    unreachable, unreachable_meta = validate_paginated(
        api_client.list_notification_records(
            REVIEWER_HEADERS, {"delivery_status": DeliveryStatus.UNREACHABLE.value}
        )
    )
    assert_integer(unreachable_meta["total_count"], 1)
    assert unreachable[0]["customer_id"] == ctx["cust_a3"]["id"]
    assert_record(
        unreachable[0],
        channel_used=None,
        delivery_status=DeliveryStatus.UNREACHABLE.value,
    )

    critical, critical_meta = validate_paginated(
        api_client.list_notification_records(
            REVIEWER_HEADERS, {"customer_id": ctx["cust_a2"]["id"]}
        )
    )
    assert_integer(critical_meta["total_count"], 1)
    assert_record(
        critical[0],
        channel_used=Channel.VOICE.value,
        delivery_status=DeliveryStatus.DELIVERED.value,
    )

    page, page_meta = validate_paginated(
        api_client.list_notification_records(
            REVIEWER_HEADERS,
            {
                "delivery_status": DeliveryStatus.DELIVERED.value,
                "limit": 2,
                "offset": 2,
            },
        )
    )
    assert len(page) == 2
    assert_integer(page_meta["total_count"], 4)
    assert_integer(page_meta["offset"], 2)
    assert page_meta["has_more"] is False

    one = validate_success(
        api_client.get_notification_record(unreachable[0]["id"], REVIEWER_HEADERS), 200
    )
    assert one["id"] == unreachable[0]["id"]
    assert one["delivery_status"] == DeliveryStatus.UNREACHABLE.value


def test_the_event_index_and_the_attached_centre_listing_each_filter_independently():
    """Two events on one trigger index, three registered sites and one activation: the event
    index answers each of its three filters and paginates over the filtered set, while the
    per-event centre listing shows only the two sites the selector actually attached.

    "List shutoff events, filterable by `scope_status`, `notification_status`, and
    `trigger_fire_potential_index_id`."

    "Candidates are ranked by three keys in order: `accessibility_certified`
    descending, so certified sites come before uncertified ones; then `site_capacity`
    descending, so the largest site of equal certification comes first; then
    `created_at` ascending as the final tie-break — the site identifier is never used to
    rank."

    "Otherwise the server walks the ranking, stopping as soon as the capacity
    accumulated so far has reached or exceeded the required capacity, and activates each
    site it passes with an `activation_order` equal to its 1-based position among the
    sites activated by this call."

    "A new site starts with `status` at `STANDBY` and with `psps_event_id`,
    `activated_at`, `demobilized_at`, `last_served_all_clear_at`, and
    `activation_order` all null."

    Design: Corner/endpoints/event_listing_and_attached_resource_center_listing_are_filterable
    """
    first_choice = register_center(
        resource_center_code="CRC-L1",
        district_code="D-WEST",
        site_capacity=3,
        accessibility_certified=True,
    )
    second_choice = register_center(
        resource_center_code="CRC-L2",
        district_code="D-WEST",
        site_capacity=2,
        accessibility_certified=False,
    )
    outsider = register_center(
        resource_center_code="CRC-L3",
        district_code="D-EAST",
        site_capacity=50,
        accessibility_certified=True,
    )

    ctx = _mike_chain()
    event_id = ctx["event"]["id"]
    second_event = open_event(
        ctx["index"]["id"],
        onset_at=SECOND_ONSET_AT,
        all_clear_at=SECOND_ALL_CLEAR_AT,
        event_code="EV-MIKE-2",
    )

    summary = validate_success(
        api_client.activate_resource_centers(
            event_id, factories.activation_payload(), OFFICER_HEADERS
        ),
        200,
    )
    assert_activation_summary(
        summary,
        activated_count=2,
        activated_capacity=5,
        unmet_capacity=0,
        activated_ids=[first_choice["id"], second_choice["id"]],
    )

    events, event_meta = validate_paginated(
        api_client.list_psps_events(REVIEWER_HEADERS)
    )
    assert_integer(event_meta["total_count"], 2)
    assert_integer(event_meta["limit"], DEFAULT_LIMIT)
    assert event_meta["has_more"] is False
    assert events[0]["id"] == event_id, "events are listed created_at ascending"

    armed, _ = validate_paginated(
        api_client.list_psps_events(
            REVIEWER_HEADERS, {"scope_status": EventScopeStatus.ARMED.value}
        )
    )
    assert [row["event_code"] for row in armed] == ["EV-MIKE"]

    drafts, _ = validate_paginated(
        api_client.list_psps_events(
            REVIEWER_HEADERS, {"scope_status": EventScopeStatus.DRAFT.value}
        )
    )
    assert [row["id"] for row in drafts] == [second_event["id"]]

    notified, _ = validate_paginated(
        api_client.list_psps_events(
            REVIEWER_HEADERS,
            {"notification_status": NotificationStatus.ADVANCE_SENT.value},
        )
    )
    assert [row["event_code"] for row in notified] == ["EV-MIKE"]

    by_index, index_meta = validate_paginated(
        api_client.list_psps_events(
            ANALYST_HEADERS,
            {"trigger_fire_potential_index_id": ctx["index"]["id"]},
        )
    )
    assert_integer(index_meta["total_count"], 2)
    assert len(by_index) == 2

    second_page, page_meta = validate_paginated(
        api_client.list_psps_events(REVIEWER_HEADERS, {"limit": 1, "offset": 1})
    )
    assert [row["event_code"] for row in second_page] == ["EV-MIKE-2"]
    assert_integer(page_meta["total_count"], 2)
    assert page_meta["has_more"] is False

    attached, attached_meta = validate_paginated(
        api_client.list_event_resource_centers(event_id, LIAISON_HEADERS)
    )
    assert_integer(attached_meta["total_count"], 2)
    assert attached[0]["id"] == first_choice["id"]
    assert outsider["id"] not in [row["id"] for row in attached]

    _, activated_meta = validate_paginated(
        api_client.list_event_resource_centers(
            event_id, LIAISON_HEADERS, {"status": ResourceCenterStatus.ACTIVATED.value}
        )
    )
    assert_integer(activated_meta["total_count"], 2)

    _, standby_meta = validate_paginated(
        api_client.list_event_resource_centers(
            event_id, LIAISON_HEADERS, {"status": ResourceCenterStatus.STANDBY.value}
        )
    )
    assert_integer(standby_meta["total_count"], 0)

    never_attached = validate_success(
        api_client.get_resource_center(outsider["id"], LIAISON_HEADERS), 200
    )
    assert_center_state(
        never_attached, ResourceCenterStatus.STANDBY.value, psps_event_id=None
    )
    assert never_attached["activation_order"] is None
    assert_instant(never_attached["activated_at"], None)


# --------------------------------------------------------------------------
# Action endpoints
# --------------------------------------------------------------------------
def test_the_dispatch_response_already_carries_every_declared_side_effect():
    """One action call writes the delivery records, rolls up the three counters, stamps the
    realised lead time and moves the event's notification dimension — and the 200 response
    itself shows the batch's half of that without a follow-up read.

    "The `scheduled_send_at` the operator wrote down is a plan, not the measurement:
    `dispatched_at` is stamped from the logical clock at the moment dispatch runs, and
    `lead_time_minutes` is computed as the number of whole minutes from `dispatched_at`
    to the event's `forecast_onset_at`, floored toward negative infinity — so a dispatch
    that happens after the onset yields a negative lead time."

    "The dispatch then rolls up: `target_count` is the number of records written,
    `delivered_count` the number whose `delivery_status` is `DELIVERED`, and
    `unreachable_count` the number whose `delivery_status` is `UNREACHABLE`, which is
    `target_count` minus `delivered_count`."

    "Dispatch also advances the event's `notification_status` along a fixed stage map,
    and increments both the batch's `version` and the event's `version` by one each."

    Design: Corner/endpoints/dispatch_response_carries_every_declared_side_effect_field
    """
    ctx = build_scoped_event()
    batch = plan_batch(
        ctx["event_id"], NotificationStage.ADVANCE_48H.value, ADVANCE_SEND_AT
    )
    before = read_event(ctx["event_id"])

    move_clock(ADVANCE_SEND_AT)
    dispatched = validate_success(
        api_client.dispatch_notification_batch(batch["id"], LIAISON_HEADERS), 200
    )
    assert_batch_outcome(dispatched, BatchStatus.FAILED_PARTIAL.value, 5, 4, 1)
    assert_instant(dispatched["dispatched_at"], ADVANCE_SEND_AT)
    assert_integer(dispatched["lead_time_minutes"], 2880)
    assert dispatched["version"] > batch["version"], "the batch's own version moved"

    _, record_meta = read_records(notification_batch_id=batch["id"])
    assert_integer(record_meta["total_count"], 5)

    after = read_event(ctx["event_id"])
    assert (
        after["notification_status"] == NotificationStatus.ADVANCE_SENT.value
    ), "the event's notification dimension advanced with the dispatch"
    assert after["version"] > before["version"], "the event's version moved too"


def test_explicit_activation_refuses_the_whole_request_rather_than_part_of_it():
    """Explicit mode is all-or-nothing: a request naming one eligible site and one
    out-of-district site activates neither, and the eligible site attaches cleanly the
    moment the ineligible member is dropped from the array.

    "In **explicit mode**, each named site is validated in the order the request array
    lists them, and every breach is reported loudly rather than silently skipped: a site
    whose `status` is already `ACTIVATED` refuses the call with
    `ERR_RESOURCE_CENTER_ALREADY_ACTIVE`, a site whose `district_code` is not among the
    scoped districts refuses it with `ERR_RESOURCE_CENTER_DISTRICT_MISMATCH`, and a site
    with a reset-buffer collision refuses it with
    `ERR_RESOURCE_CENTER_BUFFER_CONFLICT`."

    "All named sites are then activated together, and each site's `activation_order` is
    its 1-based position in the request array."

    "Either mode returns a summary object with four fields: `activated_count`, the
    number of sites activated by this call; `activated_capacity`, the sum of
    `site_capacity` over those sites; `unmet_capacity`, the required capacity less the
    event's post-activation `crc_capacity_served`, floored at zero so it never goes
    negative; and `activated_resource_center_ids`, the identifiers of the sites
    activated."

    Design: Corner/endpoints/explicit_activation_is_atomic_and_rejects_the_whole_request
    """
    eligible = register_center(
        resource_center_code="CRC-W2",
        district_code="D-WEST",
        site_capacity=3,
        accessibility_certified=True,
    )
    ineligible = register_center(
        resource_center_code="CRC-E9",
        district_code="D-EAST",
        site_capacity=50,
        accessibility_certified=True,
    )
    ctx = _mike_chain()
    event_id = ctx["event"]["id"]

    both = api_client.activate_resource_centers(
        event_id,
        factories.activation_payload([eligible["id"], ineligible["id"]]),
        OFFICER_HEADERS,
    )
    validate_error(both, ERR_RESOURCE_CENTER_DISTRICT_MISMATCH, 422)

    for site in (eligible, ineligible):
        assert_center_state(
            read_center(site["id"]),
            ResourceCenterStatus.STANDBY.value,
            psps_event_id=None,
        )
    assert_integer(read_event(event_id)["crc_capacity_served"], 0)

    summary = validate_success(
        api_client.activate_resource_centers(
            event_id, factories.activation_payload([eligible["id"]]), OFFICER_HEADERS
        ),
        200,
    )
    assert_activation_summary(
        summary,
        activated_count=1,
        activated_capacity=3,
        unmet_capacity=2,
        activated_ids=[eligible["id"]],
    )
    assert_center_state(
        read_center(eligible["id"]),
        ResourceCenterStatus.ACTIVATED.value,
        activation_order=1,
        psps_event_id=event_id,
    )
    assert_center_state(
        read_center(ineligible["id"]),
        ResourceCenterStatus.STANDBY.value,
        psps_event_id=None,
    )


# --------------------------------------------------------------------------
# Computed reads and nested reads
# --------------------------------------------------------------------------
def test_a_completion_leaves_the_project_and_the_circuit_reading_one_stored_ledger():
    """The mileage lands through the project endpoint, yet the circuit read reports the same
    ledger and a moved version without any circuit endpoint being called — and it invents no
    forecast data while doing so.

    "`risk_reduction_score` is `planned_miles` multiplied by a programme effectiveness
    factor and then by a terrain risk multiplier, rounded half up to two decimal
    places."

    "The effectiveness factors are 0.62 for `COVERED_CONDUCTOR`, 1.00 for
    `UNDERGROUNDING`, 0.45 for `FAST_TRIP_SETTING`, and 0.18 for `INSPECTION_CYCLE`;
    the terrain multipliers, read from the circuit's `hftd_tier` live at the moment of
    computation, are 1.5 for `TIER_3`, 1.2 for `TIER_2`, 1.0 for `TIER_1`, and 0.5 for
    `NON_HFTD`."

    "Covered conductor earns partial credit and undergrounding earns full credit: the
    numerator is `covered_conductor_miles` multiplied by 0.6 plus `underground_miles`
    multiplied by 1.0, and the denominator is the circuit's immutable
    `overhead_miles`."

    "If no such index exists the posture is `NORMAL` and both
    `latest_forecast_fpi_score` and `latest_forecast_fpi_tier` are null."

    Design: Corner/endpoints/computed_reads_return_the_persisted_ledger_after_a_completion
    """
    alpha = register_circuit(circuit_code="ALPHA")
    project = build_approved_project(
        alpha["id"],
        project_code="MP-CC",
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=4.0,
        unit_cost_per_mile_cents=1250000,
    )
    before_version = read_circuit(alpha["id"])["version"]
    record_completion(project["id"], 4.0, COMPLETION_DATE, before_version)

    stored_project = validate_success(
        api_client.get_mitigation_project(project["id"], INSPECTOR_HEADERS), 200
    )
    assert_1dp(stored_project["completed_miles"], 4.0)
    assert stored_project["status"] == ProjectStatus.COMPLETED.value
    assert_2dp(stored_project["risk_reduction_score"], 3.72)

    stored_circuit = validate_success(
        api_client.get_circuit(alpha["id"], INSPECTOR_HEADERS), 200
    )
    assert_hardening_ledger(stored_circuit, 4.0, 0.0, 0.3429)
    assert stored_circuit["version"] > before_version, (
        "the completion moved the circuit even though no circuit endpoint was called"
    )
    assert_circuit_state(
        stored_circuit,
        energization_state=EnergizationState.ENERGIZED.value,
        risk_posture=RiskPosture.NORMAL.value,
    )
    assert stored_circuit["latest_forecast_fpi_score"] is None
    assert stored_circuit["latest_forecast_fpi_tier"] is None


def test_a_nested_read_resolves_its_parent_before_it_answers_with_an_empty_page():
    """A sub-resource route is not a filtered global read: three unknown parents produce
    three different 404s named after their own path prefix, while the known parent with no
    children answers 200 with an empty array.

    "**Path identifiers resolve** — every id embedded in the request path resolves to
    an existing row, validated left to right, so that the leftmost unresolvable segment
    determines the error."

    "Accounts on a circuit can be listed filtered by `customer_class` and
    `medical_baseline`; a duplicate `account_number` is refused with
    `ERR_DUPLICATE_CODE`."

    "Findings on an assignment can be listed filtered by `severity` — the only
    discovery channel for finding rows."

    Design: Corner/endpoints/nested_reads_resolve_the_parent_id_first_or_return_not_found
    """
    alpha = register_circuit(circuit_code="ALPHA")

    missing_circuit = api_client.list_circuit_customers(UNKNOWN_UUID, LIAISON_HEADERS)
    validate_error(missing_circuit, ERR_CIRCUIT_NOT_FOUND, 404)

    missing_patrol = api_client.list_patrol_damage_findings(
        UNKNOWN_UUID, SUPERVISOR_HEADERS
    )
    validate_error(missing_patrol, ERR_PATROL_ASSIGNMENT_NOT_FOUND, 404)

    missing_station = api_client.list_station_observations(
        UNKNOWN_UUID, ANALYST_HEADERS
    )
    validate_error(missing_station, ERR_WEATHER_STATION_NOT_FOUND, 404)

    for response in (missing_circuit, missing_patrol, missing_station):
        assert response.status_code != 200, (
            "an unknown parent is a 404 and never an empty page"
        )

    rows, meta = validate_paginated(
        api_client.list_circuit_customers(alpha["id"], LIAISON_HEADERS)
    )
    assert_integer(meta["total_count"], 0)
    assert rows == [], "a served-account roster with no accounts is an empty array"
