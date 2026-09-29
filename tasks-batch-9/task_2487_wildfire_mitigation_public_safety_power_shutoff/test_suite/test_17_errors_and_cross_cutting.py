"""The error catalogue's reachability, the two optimistic-concurrency guards, the credit-rate
band breaks, and the immediacy of every cascade: what one call writes is what the very next
call reads, and what it refuses it refuses without moving anything."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_CIRCUIT_NOT_CLEARED_FOR_RESTORE,
    ERR_CIRCUIT_NOT_DE_ENERGIZED,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_EVENT_SCOPE_NOT_FOUND,
    ERR_MITIGATION_PROJECT_NOT_FOUND,
    ERR_NOTIFICATION_BATCH_NOT_FOUND,
    ERR_NOTIFICATION_RECORD_NOT_FOUND,
    ERR_PLAN_FILING_NOT_FOUND,
    ERR_RESOURCE_CENTER_ALREADY_ACTIVE,
    ERR_RESOURCE_CENTER_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_WEATHER_STATION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_4dp,
    assert_activation_summary,
    assert_center_state,
    assert_circuit_state,
    assert_event_dimensions,
    assert_fpi,
    assert_hardening_ledger,
    assert_impact_counts,
    assert_instant,
    assert_integer,
    assert_net_benefit,
    assert_scope_counts,
    assert_scope_row,
)
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.fixtures import (
    DE_ENERGIZED_AT,
    FORECAST_DATE,
    PATROL_CLOCK_AT,
    PATROL_DONE_AT,
    PATROL_START_AT,
    RESTORE_ALPHA_AT,
    activate_centers,
    arm_event,
    book_project,
    build_active_event,
    build_advance_dispatched_event,
    build_approved_project,
    build_armed_event,
    build_feeder_chain,
    build_imminent_dispatched_event,
    build_restoring_event,
    build_scoped_event,
    complete_patrol,
    compute_index,
    dispatch_batch,
    file_observation,
    move_clock,
    open_event,
    plan_batch,
    read_circuit,
    read_event,
    read_project,
    read_scope_rows,
    record_completion,
    register_center,
    register_circuit,
    register_customer,
    register_station,
    review_project,
    scope_event,
    schedule_patrol,
    start_patrol,
    submit_project,
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
    BenefitVariant,
    Channel,
    CustomerClass,
    EnergizationState,
    HftdTier,
    NotificationStage,
    PatrolStatus,
    ProgramType,
    ProjectStatus,
    ResourceCenterStatus,
    ReviewDecision,
    RiskPosture,
    ScopeRowStatus,
    TelemetryStatus,
)

FIRST_COMPLETION_DATE = "2026-07-01T00:00:00Z"
SECOND_COMPLETION_DATE = "2026-07-10T00:00:00Z"

#: EV-MIKE — an R4 TIER_2 circuit over district D-WEST needing five shelter seats.
MIKE_FORECAST_DATE = "2026-09-10"
MIKE_OBSERVED_AT = "2026-09-09T12:00:00Z"
MIKE_ONSET_AT = "2026-09-10T00:00:00Z"
MIKE_ALL_CLEAR_AT = "2026-09-10T08:00:00Z"
MIKE_ADVANCE_SEND_AT = "2026-09-08T00:00:00Z"

#: The two OSCAR events sit on the two credit-rate band edges, 20.00 and 60.00.
OSCAR_A_FORECAST_DATE = "2026-08-15"
OSCAR_A_OBSERVED_AT = "2026-08-14T12:00:00Z"
OSCAR_A_ONSET_AT = "2026-08-15T18:00:00Z"
OSCAR_A_ALL_CLEAR_AT = "2026-08-16T04:00:00Z"
OSCAR_A_SEND_AT = "2026-08-13T18:00:00Z"
OSCAR_B_FORECAST_DATE = "2026-08-20"
OSCAR_B_OBSERVED_AT = "2026-08-19T12:00:00Z"
OSCAR_B_ONSET_AT = "2026-08-20T18:00:00Z"
OSCAR_B_ALL_CLEAR_AT = "2026-08-22T00:00:00Z"
OSCAR_B_SEND_AT = "2026-08-18T18:00:00Z"


def _mike_armed_over_one_three_seat_site():
    """EV-MIKE armed over D-WEST — impact 24.80 against a required five seats — with the
    district's single certified three-seat site already taken by a selector-mode call."""
    site = register_center(
        resource_center_code="CRC-W2",
        district_code="D-WEST",
        site_capacity=3,
        accessibility_certified=True,
    )
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
    event = arm_event(event["id"])
    summary = activate_centers(event["id"])
    return {"site": site, "event": event, "summary": summary}


def _oscar_event(code, district, overhead_miles, forecast_date, observed_at, onset_at,
                 all_clear_at, send_at):
    """One TIER_3 circuit scoring exactly 89.95 with six accounts — one critical facility,
    one medical baseline and four standard — so the weighted impact base is exactly 20."""
    circuit = register_circuit(
        circuit_code=code,
        district_code=district,
        hftd_tier=HftdTier.TIER_3.value,
        overhead_miles=overhead_miles,
        equipment_condition_index=67,
    )
    station = register_station(
        circuit["id"], station_code=f"WS-{code}", representativeness_weight=1.00
    )
    file_observation(
        station["id"],
        observed_at,
        wind_gust_mph=60.0,
        relative_humidity_pct=20.0,
        temperature_f=100.0,
        dead_fuel_moisture_pct=4.0,
    )
    index = compute_index(circuit["id"], forecast_date)
    register_customer(
        circuit["id"],
        account_number=f"{code}-CF",
        customer_class=CustomerClass.CRITICAL_FACILITY.value,
        notification_channels=[Channel.SMS.value],
        address_zone_code="ZO",
    )
    register_customer(
        circuit["id"],
        account_number=f"{code}-MB",
        medical_baseline=True,
        notification_channels=[Channel.SMS.value],
        address_zone_code="ZO",
    )
    for ordinal in range(1, 5):
        register_customer(
            circuit["id"],
            account_number=f"{code}-S{ordinal}",
            notification_channels=[Channel.SMS.value],
            address_zone_code="ZO",
        )
    event = open_event(
        index["id"], onset_at=onset_at, all_clear_at=all_clear_at, event_code=f"EV-{code}"
    )
    event = scope_event(event["id"], event["version"])
    batch = plan_batch(
        event["id"], NotificationStage.ADVANCE_48H.value, send_at
    )
    return {"circuit": circuit, "index": index, "event": event, "batch": batch}


# --------------------------------------------------------------------------
# Error-catalogue reachability
# --------------------------------------------------------------------------
def test_every_not_found_code_is_reachable_from_its_own_entitys_path():
    """Eight unknown identifiers, eight different codes: the catalogue keeps one 404 per
    entity, each reachable from that entity's own path, and the well-formed exclusion body
    does not buy the missing scope row a different answer.

    "**Path identifiers resolve** — every id embedded in the request path resolves to an
    existing row, validated left to right, so that the leftmost unresolvable segment
    determines the error. The applicable code is `ERR_CIRCUIT_NOT_FOUND`,
    `ERR_WEATHER_STATION_NOT_FOUND`, `ERR_PSPS_EVENT_NOT_FOUND`,
    `ERR_EVENT_SCOPE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_NOTIFICATION_BATCH_NOT_FOUND`, `ERR_NOTIFICATION_RECORD_NOT_FOUND`,
    `ERR_MITIGATION_PROJECT_NOT_FOUND`, `ERR_PATROL_ASSIGNMENT_NOT_FOUND`,
    `ERR_RESOURCE_CENTER_NOT_FOUND`, or `ERR_PLAN_FILING_NOT_FOUND`, each HTTP 404.
    Applies to every endpoint with a path id."

    "Batches for an event can be listed filtered by `stage` and `status`; an unresolvable
    batch identifier yields `ERR_NOTIFICATION_BATCH_NOT_FOUND`."

    "Records can be listed filtered by `notification_batch_id`, `customer_id`, and
    `delivery_status`; an unresolvable record identifier yields
    `ERR_NOTIFICATION_RECORD_NOT_FOUND`."

    "Scope rows for an event, or every scope row that has ever named a given circuit, can
    be listed filtered by `scope_status`; an unresolvable scope row identifier yields
    `ERR_EVENT_SCOPE_NOT_FOUND`."

    Design: Corner/errors/every_not_found_id_is_reachable_from_its_own_read_path
    """
    reads = [
        (
            api_client.get_weather_station(UNKNOWN_UUID, ANALYST_HEADERS),
            ERR_WEATHER_STATION_NOT_FOUND,
        ),
        (
            api_client.get_customer(UNKNOWN_UUID, LIAISON_HEADERS),
            ERR_CUSTOMER_NOT_FOUND,
        ),
        (
            api_client.get_notification_batch(UNKNOWN_UUID, LIAISON_HEADERS),
            ERR_NOTIFICATION_BATCH_NOT_FOUND,
        ),
        (
            api_client.get_notification_record(UNKNOWN_UUID, LIAISON_HEADERS),
            ERR_NOTIFICATION_RECORD_NOT_FOUND,
        ),
        (
            api_client.get_mitigation_project(UNKNOWN_UUID, PLANNER_HEADERS),
            ERR_MITIGATION_PROJECT_NOT_FOUND,
        ),
        (
            api_client.get_resource_center(UNKNOWN_UUID, LIAISON_HEADERS),
            ERR_RESOURCE_CENTER_NOT_FOUND,
        ),
        (
            api_client.get_plan_filing(UNKNOWN_UUID, REVIEWER_HEADERS),
            ERR_PLAN_FILING_NOT_FOUND,
        ),
    ]
    for response, expected in reads:
        error_data = validate_error(response, expected, 404)
        assert error_data["message"].strip(), (
            f"{expected} must arrive with a populated human-readable message"
        )

    # A well-formed body does not rescue an unresolvable path segment.
    missing_row = api_client.exclude_event_scope(
        UNKNOWN_UUID, factories.exclude_payload("no such row"), ENGINEER_HEADERS
    )
    validate_error(missing_row, ERR_EVENT_SCOPE_NOT_FOUND, 404)

    assert len({expected for _, expected in reads}) == 7, (
        "the catalogue keeps one distinct 404 per entity rather than a shared code"
    )


def test_a_circuit_that_was_never_patrolled_is_refused_at_its_own_state_gate():
    """CHARLIE has no patrol at all, so the answer is about CHARLIE's own state rather than
    about a missing clearance — and ALPHA, which was walked, closes immediately afterwards.

    "**Own-state guard** — the target resource itself is in a state that admits the
    requested transition."

    "The circuit's `energization_state` must be `CLEARED_FOR_RESTORE`, otherwise
    `ERR_CIRCUIT_NOT_CLEARED_FOR_RESTORE`."

    "Completing a patrol requires `miles_patrolled`, a value of at least zero, and moves
    the assignment from `IN_PROGRESS` to `COMPLETED`, stamping `completed_at` from the
    logical clock and recording the reported mileage; an assignment in any other status
    refuses the completion with `ERR_PATROL_INVALID_STATE`."

    Design: Corner/errors/re_energizing_a_circuit_that_was_never_patrolled_is_rejected
    """
    ctx = build_restoring_event()
    alpha_id = ctx["alpha"]["id"]
    charlie_id = ctx["charlie"]["id"]

    patrol = schedule_patrol(ctx["event_id"], alpha_id, PATROL_START_AT, PATROL_DONE_AT)
    move_clock(PATROL_CLOCK_AT)
    start_patrol(patrol["id"])
    move_clock(PATROL_DONE_AT)
    complete_patrol(patrol["id"], 7.0)

    validate_error(
        api_client.re_energize_circuit(charlie_id, OFFICER_HEADERS),
        ERR_CIRCUIT_NOT_CLEARED_FOR_RESTORE,
        409,
    )
    assert_circuit_state(
        read_circuit(charlie_id),
        energization_state=EnergizationState.DE_ENERGIZED.value,
        risk_posture=RiskPosture.LOCKED.value,
    )
    assert_scope_row(read_scope_rows(ctx["event_id"]), charlie_id, restored_at=None)
    assert_event_dimensions(read_event(ctx["event_id"]), scope_status="RESTORING")

    move_clock(RESTORE_ALPHA_AT)
    restored = validate_success(
        api_client.re_energize_circuit(alpha_id, OFFICER_HEADERS), 200
    )
    assert restored["energization_state"] == EnergizationState.ENERGIZED.value


def test_a_patrol_against_an_energized_circuit_is_refused_and_writes_nothing():
    """The event is legitimately in restoration, so the refusal is entirely about the
    circuit: DELTA was never scoped and is still live, while the identically-timed ALPHA
    reservation is admitted.

    "A reservation is admitted only when the circuit's `energization_state` is
    `DE_ENERGIZED`, `PATROL_IN_PROGRESS`, or `CLEARED_FOR_RESTORE`, otherwise
    `ERR_CIRCUIT_NOT_DE_ENERGIZED`, and it is refused with `ERR_PATROL_WINDOW_OVERLAP`
    when its closed window from `window_start_at` through `window_end_at` intersects the
    closed window of another assignment on the same circuit whose `status` is `SCHEDULED`
    or `IN_PROGRESS` — shared endpoints count as an intersection."

    "A new assignment starts at `SCHEDULED` with `started_at` and `completed_at` null and
    `miles_patrolled`, `damage_finding_count`, and `ignition_risk_finding_count` all at
    zero."

    "Assignments can be listed filtered by `psps_event_id`, `circuit_id`, and `status`,
    which is the reverse-reachability channel for both of the assignment's foreign keys; an
    unresolvable assignment identifier yields `ERR_PATROL_ASSIGNMENT_NOT_FOUND`."

    Design: Corner/errors/patrolling_an_energized_circuit_is_rejected
    """
    ctx = build_restoring_event()
    delta = register_circuit(circuit_code="DELTA")

    validate_error(
        api_client.create_patrol_assignment(
            factories.patrol_assignment_payload(
                ctx["event_id"],
                delta["id"],
                PATROL_START_AT,
                PATROL_DONE_AT,
                patrol_lead_user_id="crew_lead_8",
            ),
            SUPERVISOR_HEADERS,
        ),
        ERR_CIRCUIT_NOT_DE_ENERGIZED,
        409,
    )
    _, delta_meta = validate_paginated(
        api_client.list_patrol_assignments(
            SUPERVISOR_HEADERS, {"circuit_id": delta["id"]}
        )
    )
    assert_integer(delta_meta["total_count"], 0)

    accepted = validate_success(
        api_client.create_patrol_assignment(
            factories.patrol_assignment_payload(
                ctx["event_id"],
                ctx["alpha"]["id"],
                PATROL_START_AT,
                PATROL_DONE_AT,
            ),
            SUPERVISOR_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == PatrolStatus.SCHEDULED.value
    assert_circuit_state(
        read_circuit(delta["id"]),
        energization_state=EnergizationState.ENERGIZED.value,
        risk_posture=RiskPosture.NORMAL.value,
    )


def test_naming_a_site_this_event_already_took_is_refused_without_double_counting():
    """Activation is not idempotent: the second call names the very site the selector took,
    and the refusal leaves the order, the served capacity and the credit exactly where the
    first call left them.

    "In **explicit mode**, each named site is validated in the order the request array
    lists them, and every breach is reported loudly rather than silently skipped: a site
    whose `status` is already `ACTIVATED` refuses the call with
    `ERR_RESOURCE_CENTER_ALREADY_ACTIVE`, a site whose `district_code` is not among the
    scoped districts refuses it with `ERR_RESOURCE_CENTER_DISTRICT_MISMATCH`, and a site
    with a reset-buffer collision refuses it with
    `ERR_RESOURCE_CENTER_BUFFER_CONFLICT`."

    "In **selector mode**, the server builds the candidate pool itself: sites whose
    `status` is `STANDBY` or `DEMOBILIZED`, whose `district_code` is among the scoped
    districts, and which have no reset-buffer collision. Sites already `ACTIVATED` are
    never candidates."

    "`crc_capacity_served` is the sum of `site_capacity` over the resource centers whose
    `psps_event_id` is this event and whose `status` is `ACTIVATED`; sites that are
    `DEMOBILIZED` or `STANDBY` contribute nothing."

    Design: Corner/errors/naming_an_already_activated_resource_center_is_rejected
    """
    ctx = _mike_armed_over_one_three_seat_site()
    event_id = ctx["event"]["id"]
    site_id = ctx["site"]["id"]
    assert_activation_summary(
        ctx["summary"],
        activated_count=1,
        activated_capacity=3,
        unmet_capacity=2,
        activated_ids=[site_id],
    )

    validate_error(
        api_client.activate_resource_centers(
            event_id, factories.activation_payload([site_id]), OFFICER_HEADERS
        ),
        ERR_RESOURCE_CENTER_ALREADY_ACTIVE,
        409,
    )
    assert_center_state(
        validate_success(api_client.get_resource_center(site_id, LIAISON_HEADERS), 200),
        ResourceCenterStatus.ACTIVATED.value,
        activation_order=1,
        psps_event_id=event_id,
    )

    after = read_event(event_id)
    assert_integer(after["crc_capacity_served"], 3)
    assert_net_benefit(
        after,
        customer_impact_score=24.80,
        crc_mitigation_credit=0.74,
        adjusted_customer_impact_score=24.06,
        ignition_risk_avoided_score=6.60,
        net_benefit_ratio=0.2743,
    )


# --------------------------------------------------------------------------
# Optimistic concurrency
# --------------------------------------------------------------------------
def test_a_rescope_needs_the_version_the_first_scope_left_behind():
    """Re-scoping is a legitimate self-loop that rewrites the whole scope set, so the only
    thing between two scope calls is the token: the creation version is refused, the
    refreshed one succeeds, and the set is replaced rather than appended to.

    "`POST /psps-events/{id}/scope` requires a non-optional body field
    `expected_psps_event_version`, carrying the client's last observed `version` of the
    target `PSPSEvent`."

    "Such a request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    "The call runs from `DRAFT` to `SCOPED` the first time and as a self-loop from
    `SCOPED` back to `SCOPED` on every re-scope after a forecast refresh; a re-scope first
    **hard-deletes** every existing scope row of the event and then rewrites the set from
    scratch, and it reverts any circuit that was staged for de-energization but is no
    longer confirmed back to `ENERGIZED`."

    Design: Corner/cross_cutting_complexity_layers/rescope_rejects_a_stale_expected_psps_event_version
    """
    ctx = build_feeder_chain()
    opened = open_event(ctx["fpi_forecast"]["id"])
    creation_version = opened["version"]
    scoped = scope_event(opened["id"], creation_version)
    assert scoped["version"] > creation_version

    validate_error(
        api_client.scope_psps_event(
            opened["id"], factories.scope_payload(creation_version), OFFICER_HEADERS
        ),
        ERR_STALE_VERSION,
        412,
    )
    refused = read_event(opened["id"])
    assert_integer(refused["version"], scoped["version"])
    _, refused_meta = validate_paginated(
        api_client.list_event_scopes(opened["id"], OFFICER_HEADERS)
    )
    assert_integer(refused_meta["total_count"], 3)

    rewritten = validate_success(
        api_client.scope_psps_event(
            opened["id"],
            factories.scope_payload(refused["version"]),
            OFFICER_HEADERS,
        ),
        200,
    )
    _, rewritten_meta = validate_paginated(
        api_client.list_event_scopes(opened["id"], OFFICER_HEADERS)
    )
    assert_integer(rewritten_meta["total_count"], 3)
    assert_scope_counts(rewritten, confirmed=3, excluded=0)
    assert_net_benefit(
        rewritten, ignition_risk_avoided_score=15.48, net_benefit_ratio=0.3395
    )
    assert rewritten["version"] > refused["version"], (
        "the successful rescope moved the token again, so replaying it would fail too"
    )


def test_each_completion_needs_a_freshly_read_circuit_version():
    """A project accretes miles across several records, so the guard is purely the circuit's
    version: replaying the token that carried the first two miles is refused, and the ledger
    stays exactly where the accepted record left it.

    "`POST /mitigation-projects/{id}/record-completion` requires a non-optional body
    field `expected_circuit_version`, carrying the client's last observed `version` of the
    project's `Circuit`."

    "The first record advances the project from `APPROVED` to `IN_EXECUTION`; further
    records that leave the cumulative total strictly below `planned_miles` keep it in
    `IN_EXECUTION`; and the record whose cumulative total lands exactly on `planned_miles`
    advances it to `COMPLETED`."

    "Covered conductor earns partial credit and undergrounding earns full credit: the
    numerator is `covered_conductor_miles` multiplied by 0.6 plus `underground_miles`
    multiplied by 1.0, and the denominator is the circuit's immutable
    `overhead_miles`."

    Design: Corner/cross_cutting_complexity_layers/record_completion_rejects_a_stale_expected_circuit_version
    """
    alpha = register_circuit(circuit_code="ALPHA")
    project = build_approved_project(
        alpha["id"],
        project_code="MP-CC",
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=4.0,
    )
    stale_version = read_circuit(alpha["id"])["version"]

    first = record_completion(project["id"], 2.0, FIRST_COMPLETION_DATE, stale_version)
    assert_1dp(first["completed_miles"], 2.0)
    assert first["status"] == ProjectStatus.IN_EXECUTION.value
    assert_hardening_ledger(read_circuit(alpha["id"]), 2.0, 0.0, 0.1714)

    validate_error(
        api_client.record_project_completion(
            project["id"],
            factories.record_completion_payload(
                1.0, SECOND_COMPLETION_DATE, stale_version
            ),
            INSPECTOR_HEADERS,
        ),
        ERR_STALE_VERSION,
        412,
    )
    assert_1dp(read_project(project["id"])["completed_miles"], 2.0)
    assert_hardening_ledger(read_circuit(alpha["id"]), 2.0, 0.0, 0.1714)

    fresh_version = read_circuit(alpha["id"])["version"]
    second = record_completion(
        project["id"], 1.0, SECOND_COMPLETION_DATE, fresh_version
    )
    assert_1dp(second["completed_miles"], 3.0)
    assert second["status"] == ProjectStatus.IN_EXECUTION.value
    assert_hardening_ledger(read_circuit(alpha["id"]), 3.0, 0.0, 0.2571)


def test_the_circuit_token_also_moves_when_somebody_elses_call_writes_it():
    """Four captured versions, only the first from a circuit endpoint: the index restamped
    the posture fields, each account raised the counters, and the shutoff cascade flipped the
    state — so a token held across any of them is already stale.

    "Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp with
    three fractional digits, refreshed on every mutation of the row — and `version`, an
    integer that starts at 1 when the row is created and increments by exactly 1 on every
    mutation."

    "A mutation includes any change to a *computed* field, not only to operator-supplied
    input: when a customer registration raises a circuit's `customer_count`, when a
    completion record moves a circuit's `hardened_fraction`, or when a resource-center
    activation moves an event's `net_benefit_ratio`, the affected row's `version`
    increments and its `updated_at` refreshes."

    "A `FORECAST` row additionally re-runs the circuit's risk-posture evaluation and
    refreshes `latest_forecast_fpi_score` and `latest_forecast_fpi_tier`, incrementing the
    circuit's `version` when the posture or either of those two fields changes."

    "Every `CONFIRMED`-scoped circuit moves from `DE_ENERGIZATION_PENDING` to
    `DE_ENERGIZED`, keeping its `risk_posture` at `LOCKED`."

    Design: Corner/cross_cutting_complexity_layers/version_advances_on_direct_and_cascaded_writes_alike
    """
    ctx = build_feeder_chain(with_customers=False, with_index=False)
    alpha_id = ctx["alpha"]["id"]
    after_create = read_circuit(alpha_id)["version"]
    assert_integer(after_create, 1)

    ctx["fpi_forecast"] = compute_index(alpha_id, FORECAST_DATE)
    after_index = read_circuit(alpha_id)
    assert after_index["version"] > after_create, (
        "the index creation restamped the posture and the two latest-forecast fields"
    )
    assert_circuit_state(after_index, risk_posture=RiskPosture.EXTREME.value)

    register_customer(
        alpha_id,
        account_number="ACC-CF",
        customer_class=CustomerClass.CRITICAL_FACILITY.value,
        notification_channels=[Channel.SMS.value],
    )
    register_customer(
        alpha_id,
        account_number="ACC-MB",
        medical_baseline=True,
        notification_channels=[Channel.SMS.value],
    )
    register_customer(
        alpha_id, account_number="ACC-ST", notification_channels=[Channel.SMS.value]
    )
    after_customers = read_circuit(alpha_id)["version"]
    assert after_customers > after_index["version"], (
        "each registration raised the circuit's own population counters"
    )

    ctx = build_scoped_event(ctx)
    ctx = build_advance_dispatched_event(ctx)
    ctx = build_armed_event(ctx)
    ctx = build_imminent_dispatched_event(ctx)
    ctx = build_active_event(ctx)
    after_deenergize = read_circuit(alpha_id)
    assert after_deenergize["version"] > after_customers, (
        "the shutoff cascade wrote the circuit without any circuit endpoint being called"
    )
    assert_circuit_state(
        after_deenergize,
        energization_state=EnergizationState.DE_ENERGIZED.value,
        risk_posture=RiskPosture.LOCKED.value,
    )

    captured = [after_create, after_index["version"], after_customers,
                after_deenergize["version"]]
    assert captured == sorted(set(captured)), (
        f"the four captured versions must be strictly increasing, got {captured}"
    )


def test_the_credit_rate_bands_break_inclusively_at_twenty_and_at_sixty():
    """Two events, two band edges: an impact of exactly 20.00 earns the 0.05 rate rather than
    the 0.00 of the band below, and exactly 60.00 earns 0.12 rather than 0.05 — and the rate
    is read off the unadjusted score, never the one the credit already reduced.

    "*Step two — the credit rate.* The rate is read from `customer_impact_score` as
    computed in step one, on four bands: a score below 20 earns a rate of 0.00, a score
    from 20 up to but not including 60 earns 0.05, a score from 60 up to but not including
    200 earns 0.12, and a score of 200 or above earns 0.20."

    "The impact base is `impacted_customer_count`, plus four times
    `medical_baseline_customer_count`, plus ten times the event's `critical_facility_count`
    — a medical-baseline household counts as four ordinary accounts and a critical facility
    as ten."

    "*Step four — credit and adjustment.* `crc_mitigation_credit` is
    `customer_impact_score` multiplied by the step-two rate and then by the step-three
    coverage ratio, rounded half up to two decimal places."

    "The coverage ratio is `crc_capacity_served` divided by `crc_capacity_required`,
    where a required capacity of zero is treated as one to keep the division defined, and
    the quotient is capped at 1 so over-provisioning earns no extra credit."

    Design: Corner/cross_cutting_complexity_layers/credit_rate_bands_break_exactly_at_twenty_and_sixty
    """
    oscar_a = _oscar_event(
        "OSCAR-A", "D-OA", 6.0, OSCAR_A_FORECAST_DATE, OSCAR_A_OBSERVED_AT,
        OSCAR_A_ONSET_AT, OSCAR_A_ALL_CLEAR_AT, OSCAR_A_SEND_AT,
    )
    oscar_b = _oscar_event(
        "OSCAR-B", "D-OB", 18.0, OSCAR_B_FORECAST_DATE, OSCAR_B_OBSERVED_AT,
        OSCAR_B_ONSET_AT, OSCAR_B_ALL_CLEAR_AT, OSCAR_B_SEND_AT,
    )
    assert_fpi(oscar_a["index"], 89.95, "R5")
    assert_fpi(oscar_b["index"], 89.95, "R5")
    for scoped in (oscar_a["event"], oscar_b["event"]):
        assert_impact_counts(scoped, impacted=6, medical_baseline=1, critical_facility=1)

    move_clock(OSCAR_A_SEND_AT)
    dispatch_batch(oscar_a["batch"]["id"])
    armed_a = arm_event(oscar_a["event"]["id"])
    move_clock(OSCAR_B_SEND_AT)
    dispatch_batch(oscar_b["batch"]["id"])
    armed_b = arm_event(oscar_b["event"]["id"])
    assert_net_benefit(
        armed_a,
        variant=BenefitVariant.PRE_EVENT.value,
        duration_hours=10,
        customer_impact_score=20.00,
        crc_mitigation_credit=0.00,
        ignition_risk_avoided_score=5.40,
        net_benefit_ratio=0.2700,
    )
    assert_net_benefit(
        armed_b,
        variant=BenefitVariant.PRE_EVENT.value,
        duration_hours=30,
        customer_impact_score=60.00,
        crc_mitigation_credit=0.00,
        ignition_risk_avoided_score=16.19,
        net_benefit_ratio=0.2698,
    )

    site_a = register_center(
        resource_center_code="CRC-OA",
        district_code="D-OA",
        site_capacity=2,
        accessibility_certified=True,
    )
    site_b = register_center(
        resource_center_code="CRC-OB",
        district_code="D-OB",
        site_capacity=2,
        accessibility_certified=True,
    )
    summary_a = activate_centers(oscar_a["event"]["id"])
    summary_b = activate_centers(oscar_b["event"]["id"])
    assert_activation_summary(
        summary_a,
        activated_count=1,
        activated_capacity=2,
        unmet_capacity=0,
        activated_ids=[site_a["id"]],
    )
    assert_activation_summary(
        summary_b,
        activated_count=1,
        activated_capacity=2,
        unmet_capacity=0,
        activated_ids=[site_b["id"]],
    )

    # 20.00 x 0.05 x 1 is 1.00, not the 0.00 the band below would have given.
    assert_net_benefit(
        read_event(oscar_a["event"]["id"]),
        customer_impact_score=20.00,
        crc_mitigation_credit=1.00,
        adjusted_customer_impact_score=19.00,
        ignition_risk_avoided_score=5.40,
        net_benefit_ratio=0.2842,
    )
    # 60.00 x 0.12 x 1 is 7.20, not the 3.00 the 0.05 band would have given.
    assert_net_benefit(
        read_event(oscar_b["event"]["id"]),
        customer_impact_score=60.00,
        crc_mitigation_credit=7.20,
        adjusted_customer_impact_score=52.80,
        ignition_risk_avoided_score=16.19,
        net_benefit_ratio=0.3066,
    )


# --------------------------------------------------------------------------
# Immediate consistency
# --------------------------------------------------------------------------
def test_the_scope_response_already_carries_everything_its_cascade_produced():
    """Nothing settles between requests: the counts, the summed ignition score, the impact
    score and the ratio are all in the scope call's own 200, and the follow-up reads repeat
    them value for value.

    "The event's `confirmed_scope_count` and `excluded_scope_count` are the counts of its
    scope rows in each `scope_status`; `impacted_customer_count` is the sum of
    `customer_count_snapshot` over the `CONFIRMED` rows; `medical_baseline_customer_count`
    and the event's own `critical_facility_count` are the sums of `medical_baseline_count`
    and `critical_facility_count` over the circuits of those `CONFIRMED` rows; and
    `crc_capacity_required` is `medical_baseline_customer_count` plus
    `critical_facility_count`."

    "The event's `ignition_risk_avoided_score` is the exact sum of the
    `ignition_risk_term` values of **all** the event's scope rows — the per-row rounding
    has already happened, and no further rounding is applied to the total."

    "A downstream row does not have its own qualifying index — it **inherits**
    `fpi_score_applied` from the nearest ancestor scope row whose `inclusion_basis` is
    `PRIMARY_RISK`, found by walking the feeder chain upward."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response
    """
    ctx = build_feeder_chain()
    opened = open_event(ctx["fpi_forecast"]["id"])
    scoped = scope_event(opened["id"], opened["version"])

    assert_scope_counts(scoped, confirmed=3, excluded=0)
    assert_impact_counts(scoped, impacted=5, medical_baseline=1, critical_facility=1)
    assert_integer(scoped["crc_capacity_required"], 2)
    assert_net_benefit(
        scoped,
        variant=BenefitVariant.PRE_EVENT.value,
        duration_hours=24,
        customer_impact_score=45.60,
        crc_mitigation_credit=0.00,
        adjusted_customer_impact_score=45.60,
        ignition_risk_avoided_score=15.48,
        net_benefit_ratio=0.3395,
    )

    later = read_event(opened["id"])
    for field in (
        "confirmed_scope_count",
        "excluded_scope_count",
        "impacted_customer_count",
        "medical_baseline_customer_count",
        "critical_facility_count",
        "crc_capacity_required",
        "duration_hours",
    ):
        assert_integer(later[field], scoped[field])
    assert_2dp(later["customer_impact_score"], scoped["customer_impact_score"])
    assert_2dp(later["ignition_risk_avoided_score"], scoped["ignition_risk_avoided_score"])
    assert_4dp(later["net_benefit_ratio"], scoped["net_benefit_ratio"])

    rows = read_scope_rows(opened["id"])
    assert len(rows) == 3
    assert_scope_row(rows, ctx["alpha"]["id"], fpi_score_applied=85.93, ignition_risk_term=6.02)
    assert_scope_row(rows, ctx["bravo"]["id"], fpi_score_applied=85.93, ignition_risk_term=5.16)
    assert_scope_row(rows, ctx["charlie"]["id"], fpi_score_applied=85.93, ignition_risk_term=4.30)


def test_one_de_energize_call_is_wholly_visible_to_the_next_four_reads():
    """The cascade crosses four entities in one call, and there is no window in which the
    event reads `ACTIVE` while a circuit is still live or a suspended project still says it is
    executing.

    "When the gate clears, the event advances from `ARMED` to `ACTIVE` and the cascade
    runs in three hops. The event's `actual_de_energized_at` is stamped from the logical
    clock. Every `CONFIRMED`-scoped circuit moves from `DE_ENERGIZATION_PENDING` to
    `DE_ENERGIZED`, keeping its `risk_posture` at `LOCKED`. And because each posture is
    `LOCKED`, every mitigation project on those circuits whose `status` is `IN_EXECUTION`
    moves to `SUSPENDED`."

    "Each written row captures `customer_count_snapshot` from its circuit's
    `customer_count` at write time — a frozen figure, so later account registrations do not
    retroactively change what the event reports."

    "The first record advances the project from `APPROVED` to `IN_EXECUTION`; further
    records that leave the cumulative total strictly below `planned_miles` keep it in
    `IN_EXECUTION`; and the record whose cumulative total lands exactly on `planned_miles`
    advances it to `COMPLETED`."

    Design: Corner/consistency_model/a_multi_entity_cascade_is_fully_visible_to_the_next_read
    """
    ctx = build_feeder_chain()
    alpha_id = ctx["alpha"]["id"]
    project = book_project(alpha_id, project_code="MP-CC", planned_miles=4.0)
    submit_project(project["id"])
    review_project(project["id"], ReviewDecision.APPROVE.value, "hardening plan accepted")
    in_flight = record_completion(
        project["id"], 2.0, FIRST_COMPLETION_DATE, read_circuit(alpha_id)["version"]
    )
    assert in_flight["status"] == ProjectStatus.IN_EXECUTION.value

    ctx = build_scoped_event(ctx)
    ctx = build_advance_dispatched_event(ctx)
    ctx = build_armed_event(ctx)
    ctx = build_imminent_dispatched_event(ctx)
    ctx = build_active_event(ctx)

    assert_event_dimensions(ctx["event"], scope_status="ACTIVE")
    assert_instant(ctx["event"]["actual_de_energized_at"], DE_ENERGIZED_AT)

    assert_circuit_state(
        read_circuit(alpha_id),
        energization_state=EnergizationState.DE_ENERGIZED.value,
        risk_posture=RiskPosture.LOCKED.value,
    )
    suspended = read_project(project["id"])
    assert suspended["status"] == ProjectStatus.SUSPENDED.value
    assert_1dp(suspended["completed_miles"], 2.0)

    rows = read_scope_rows(ctx["event_id"])
    assert len(rows) == 3
    for circuit_key, snapshot in (("alpha", 3), ("bravo", 1), ("charlie", 1)):
        assert_scope_row(
            rows,
            ctx[circuit_key]["id"],
            scope_status=ScopeRowStatus.CONFIRMED.value,
            customer_count_snapshot=snapshot,
            restored_at=None,
        )
