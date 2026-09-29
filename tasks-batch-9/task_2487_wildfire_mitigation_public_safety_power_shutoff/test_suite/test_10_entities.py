"""Per-resource surface behaviour: what registration stores, what it derives, what a read
gives back, how rows are discovered, and which fields the server owns outright."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_CIRCUIT_NOT_FOUND, ERR_INVALID_REQUEST
from test_helpers.assertions import (
    assert_1dp,
    assert_append_only_record,
    assert_circuit_state,
    assert_envelope_meta,
    assert_event_dimensions,
    assert_fpi,
    assert_impact_counts,
    assert_instant,
    assert_integer,
    assert_list_meta_absent,
    assert_net_benefit,
    assert_population_counters,
    assert_scope_counts,
    assert_versioned_entity,
    assert_hardening_ledger,
)
from test_helpers.constants import DEFAULT_LIMIT, DEFAULT_OFFSET, UNKNOWN_UUID
from test_helpers.fixtures import (
    ALL_CLEAR_AT,
    FORECAST_DATE,
    ONSET_AT,
    PATROL_CLOCK_AT,
    PATROL_DONE_AT,
    PATROL_START_AT,
    build_advance_dispatched_event,
    build_feeder_chain,
    build_restoring_event,
    build_scoped_event,
    compute_index,
    file_finding,
    move_clock,
    read_circuit,
    read_patrol,
    read_records,
    read_scope_rows,
    register_circuit,
    schedule_patrol,
    start_patrol,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    OFFICER_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_HEADERS,
    SUPERVISOR_HEADERS,
)
from test_helpers.types import (
    ComputationVariant,
    DamageSeverity,
    HftdTier,
    PatrolMode,
)

SECOND_FINDING_AT = "2026-08-16T22:30:00Z"
MINOR_NOTE = "loose crossarm bolt at pole 41"
IGNITION_NOTE = "conductor slap marks with fresh char at pole 58"


# --------------------------------------------------------------------------
# Circuits
# --------------------------------------------------------------------------
def test_a_minimally_specified_circuit_takes_every_declared_default():
    """Registering with only the five required fields yields a three-year inspection cycle,
    no fast-trip settings, no upstream feeder, an empty hardening ledger and an energized,
    unscored circuit at version 1.

    "`inspection_cycle_months`, the nominal number of months between full inspections, must
    sit between 1 and 120 inclusive and **defaults to 36** — three years — when omitted."

    "Upon registration the server initialises the circuit's derived state:
    `energization_state` starts at `ENERGIZED`, `risk_posture` at `NORMAL`,
    `hardened_fraction` at zero carried to four decimal places, `covered_conductor_miles`
    and `underground_miles` at zero, the three population counters `customer_count`,
    `medical_baseline_count`, and `critical_facility_count` at zero, and both
    `latest_forecast_fpi_score` and `latest_forecast_fpi_tier` at null because no index has
    yet scored the circuit."

    Design: Corner/entities/circuit_create_applies_every_declared_default_and_system_field
    """
    response = api_client.create_circuit(
        factories.minimal_circuit_payload(
            circuit_code="MINIMAL-1",
            hftd_tier=HftdTier.TIER_1.value,
            overhead_miles=3.0,
            equipment_condition_index=90,
        ),
        PLANNER_HEADERS,
    )

    created = get_success_data(response, 201)

    assert response.json()["response_type"] == "object"
    assert_integer(created["inspection_cycle_months"], 36)
    assert created["fast_trip_enabled"] is False
    assert created["last_inspection_completed_at"] is None
    assert created["upstream_circuit_id"] is None
    assert_circuit_state(created, energization_state="ENERGIZED", risk_posture="NORMAL")
    assert_hardening_ledger(
        created,
        covered_conductor_miles=0.0,
        underground_miles=0.0,
        hardened_fraction=0.0000,
    )
    assert_population_counters(
        created, customer_count=0, medical_baseline_count=0, critical_facility_count=0
    )
    assert created["latest_forecast_fpi_score"] is None
    assert created["latest_forecast_fpi_tier"] is None
    assert_versioned_entity(created, expected_version=1)
    assert_envelope_meta(response)
    assert_list_meta_absent(response)


def test_a_circuit_read_returns_every_stored_input_unchanged():
    """The regulator reads ALPHA back and finds the operator-supplied identifier, district,
    terrain tier and both physical attributes exactly as registered.

    "A `GridPlanner` registers one by supplying a `circuit_code` — the operator-facing
    identifier, between 3 and 40 characters and unique across all circuits — together with
    the `district_code` of the operating district it belongs to (also between 3 and 40
    characters, and later the matching key for resource-center eligibility), the `hftd_tier`
    describing its terrain, and two physical attributes: `overhead_miles`, the baseline
    overhead line mileage, strictly greater than zero and carrying at most one decimal
    place, and `equipment_condition_index`, an asset-health score from 0 through 100
    inclusive where 100 means pristine."

    "The `hftd_tier` is one of `TIER_1`, `TIER_2`, `TIER_3`, or `NON_HFTD`, mirroring the
    regulator's high fire threat district designations."

    Design: Corner/entities/circuit_get_round_trips_every_stored_input_field
    """
    alpha = register_circuit(circuit_code="ALPHA")

    response = api_client.get_circuit(alpha["id"], REVIEWER_HEADERS)

    stored = get_success_data(response, 200)
    assert stored["id"] == alpha["id"]
    assert stored["circuit_code"] == "ALPHA"
    assert stored["district_code"] == "D-NORTH"
    assert stored["hftd_tier"] == "TIER_3"
    assert_1dp(stored["overhead_miles"], 7.0)
    # PRD calls `equipment_condition_index` "an asset-health score from 0 through 100
    # inclusive" and §2.6 does not list it among the integer quantities, so only its
    # round-tripped value is asserted here, not its JSON numeric type.
    assert float(stored["equipment_condition_index"]) == 55
    assert_integer(stored["inspection_cycle_months"], 36)
    assert_instant(stored["last_inspection_completed_at"], "2026-05-01T00:00:00Z")
    assert stored["fast_trip_enabled"] is False
    assert_list_meta_absent(response)


def test_the_circuit_listing_pages_and_filters_over_the_whole_matching_set():
    """Two pages of two cover the three-circuit chain, the terrain filter narrows it to the
    two TIER_2 feeders, and an unfiltered call applies the declared page defaults.

    "`limit` controls page size: it defaults to 10 when omitted, its minimum accepted value
    is 1, and its maximum accepted value is 100."

    "Every list response populates four fields inside `meta`: `limit` (the effective page
    size actually applied), `offset` (the effective offset actually applied), `total_count`
    (the number of rows matching the filters *before* the page window is applied), and
    `has_more` (true when rows remain beyond the current page, false otherwise)."

    Design: Corner/entities/circuits_list_paginates_and_filters_by_district_and_energization_state
    """
    build_feeder_chain(with_customers=False, with_index=False)

    first_page = api_client.list_circuits(
        ANALYST_HEADERS, params={"limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(first_page)
    assert first_page.json()["response_type"] == "array"
    assert len(rows) == 2
    assert_integer(meta["total_count"], 3)
    assert_integer(meta["limit"], 2)
    assert_integer(meta["offset"], 0)
    assert meta["has_more"] is True

    tail_rows, tail_meta = validate_paginated(
        api_client.list_circuits(ANALYST_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert len(tail_rows) == 1
    assert_integer(tail_meta["total_count"], 3)
    assert_integer(tail_meta["offset"], 2)
    assert tail_meta["has_more"] is False

    tier_rows, tier_meta = validate_paginated(
        api_client.list_circuits(ANALYST_HEADERS, params={"hftd_tier": "TIER_2"})
    )
    assert_integer(tier_meta["total_count"], 2)
    assert {row["circuit_code"] for row in tier_rows} == {"BRAVO", "CHARLIE"}

    served_rows, served_meta = validate_paginated(
        api_client.list_circuits(
            ANALYST_HEADERS,
            params={"energization_state": "ENERGIZED", "district_code": "D-NORTH"},
        )
    )
    assert_integer(served_meta["total_count"], 3)
    assert len(served_rows) == 3

    _, default_meta = validate_paginated(api_client.list_circuits(ANALYST_HEADERS))
    assert_integer(default_meta["limit"], DEFAULT_LIMIT)
    assert_integer(default_meta["offset"], DEFAULT_OFFSET)


def test_reading_a_circuit_that_was_never_registered_is_a_not_found():
    """A well-formed identifier that names no row is refused with the circuit's own code and
    an error envelope that still carries the request correlation fields.

    "**Path identifiers resolve** — every id embedded in the request path resolves to an
    existing row, validated left to right, so that the leftmost unresolvable segment
    determines the error."

    "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/entities/circuit_get_with_unknown_id_returns_not_found
    """
    register_circuit(circuit_code="ALPHA")

    response = api_client.get_circuit(UNKNOWN_UUID, PLANNER_HEADERS)

    error = validate_error(response, ERR_CIRCUIT_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"
    assert error["message"], "an error must carry a human-readable message"
    assert_envelope_meta(response)
    assert_list_meta_absent(response)


def test_a_circuit_without_positive_overhead_miles_is_refused_outright():
    """Omitting the mileage and supplying zero mileage are both malformed requests, and
    neither one leaves a row behind.

    "**Request shape** — every required body field is present; every enum value is a
    declared member; every numeric value sits inside its declared range (`overhead_miles`
    greater than 0; `equipment_condition_index` from 0 through 100 inclusive;
    `representativeness_weight` greater than 0 and at most 1; `site_capacity` at least 1;
    `planned_miles` greater than 0; `unit_cost_per_mile_cents` at least 0;
    `completed_miles_delta` greater than 0; `miles_patrolled` at least 0; `plan_year` from
    2020 through 2100 inclusive; `limit` from 1 through 100 inclusive; `offset` at least
    0); `notification_channels` is a non-empty, duplicate-free subset of `SMS`, `VOICE`,
    and `EMAIL`; `accessibility_needs` is a duplicate-free subset of `LARGE_PRINT`, `TTY`,
    and `AUDIO`; every datetime parses as an ISO 8601 UTC instant; and `forecast_date`
    matches the four-digit-year, two-digit-month, two-digit-day pattern `YYYY-MM-DD`."

    "`overhead_miles` is an immutable baseline — it is the denominator of every hardening
    ratio the circuit will ever report — and nothing in this specification changes it after
    registration."

    Design: Corner/entities/circuit_create_missing_required_overhead_miles_rejected
    """
    missing = api_client.create_circuit(
        {
            "circuit_code": "NO-MILES",
            "district_code": "D-NORTH",
            "hftd_tier": HftdTier.TIER_2.value,
            "equipment_condition_index": 80,
        },
        PLANNER_HEADERS,
    )
    validate_error(missing, ERR_INVALID_REQUEST, 400)

    zero = api_client.create_circuit(
        {
            "circuit_code": "ZERO-MILES",
            "district_code": "D-NORTH",
            "hftd_tier": HftdTier.TIER_2.value,
            "overhead_miles": 0.0,
            "equipment_condition_index": 80,
        },
        PLANNER_HEADERS,
    )
    validate_error(zero, ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api_client.list_circuits(PLANNER_HEADERS))
    assert_integer(meta["total_count"], 0)


def test_the_feeder_self_reference_is_discovered_in_the_reverse_direction():
    """ALPHA is fed from transmission and stores no parent, while filtering on the upstream
    identifier is what surfaces each circuit's single child.

    "A fourth optional field, `upstream_circuit_id`, is the system's only self-reference:
    it names the immediately upstream feeder circuit and **defaults to null**, and a null
    value means the circuit is fed directly from transmission rather than from another
    distribution circuit."

    "Because a circuit stores only its parent, discovering a circuit's children means
    listing circuits filtered by `upstream_circuit_id` — that filter is the
    reverse-reachability channel for the feeder chain, alongside filters on
    `district_code`, `hftd_tier`, `energization_state`, and `risk_posture`."

    Design: Corner/entities/circuit_upstream_self_reference_is_validated_and_reverse_listable
    """
    ctx = build_feeder_chain(with_customers=False, with_index=False)
    assert ctx["alpha"]["upstream_circuit_id"] is None

    children_of_alpha, alpha_meta = validate_paginated(
        api_client.list_circuits(
            PLANNER_HEADERS, params={"upstream_circuit_id": ctx["alpha"]["id"]}
        )
    )
    assert_integer(alpha_meta["total_count"], 1)
    assert children_of_alpha[0]["id"] == ctx["bravo"]["id"]
    assert children_of_alpha[0]["upstream_circuit_id"] == ctx["alpha"]["id"]

    children_of_bravo, bravo_meta = validate_paginated(
        api_client.list_circuits(
            PLANNER_HEADERS, params={"upstream_circuit_id": ctx["bravo"]["id"]}
        )
    )
    assert_integer(bravo_meta["total_count"], 1)
    assert children_of_bravo[0]["id"] == ctx["charlie"]["id"]

    _, leaf_meta = validate_paginated(
        api_client.list_circuits(
            PLANNER_HEADERS, params={"upstream_circuit_id": ctx["charlie"]["id"]}
        )
    )
    assert_integer(leaf_meta["total_count"], 0)


# --------------------------------------------------------------------------
# Served accounts
# --------------------------------------------------------------------------
def test_an_account_omitting_both_optional_fields_lands_in_the_standard_tier():
    """No medical enrolment and no accessibility needs means false, an empty set, and the
    residual notification tier — and the circuit still counts the account.

    "Two fields are optional: `medical_baseline`, flagging enrolment in the medical
    baseline programme, **defaults to false**, and `accessibility_needs`, a duplicate-free
    set drawn from `LARGE_PRINT`, `TTY`, and `AUDIO`, **defaults to an empty set**."

    "Registration computes one derived field, the account's `notification_tier`, from a
    strict precedence: an account whose `customer_class` is `CRITICAL_FACILITY` is
    `TIER_A_CRITICAL`; otherwise an account whose `medical_baseline` is true is
    `TIER_B_MEDICAL`; otherwise the account is `TIER_C_STANDARD`."

    Design: Corner/entities/customer_create_applies_medical_baseline_and_accessibility_defaults
    """
    alpha = register_circuit(circuit_code="ALPHA")

    response = api_client.create_customer(
        factories.customer_payload(
            alpha["id"], account_number="ACC-DEF", address_zone_code="Z9"
        ),
        PLANNER_HEADERS,
    )

    created = get_success_data(response, 201)
    assert created["medical_baseline"] is False
    assert created["accessibility_needs"] == []
    assert created["notification_tier"] == "TIER_C_STANDARD"
    assert created["circuit_id"] == alpha["id"]
    assert_versioned_entity(created, expected_version=1)
    assert_population_counters(
        read_circuit(alpha["id"]),
        customer_count=1,
        medical_baseline_count=0,
        critical_facility_count=0,
    )


def test_the_population_counters_are_derived_from_the_account_rows():
    """ALPHA's three accounts include one medical baseline and one critical facility, the
    two downstream feeders carry one ordinary account each, and the medical filter is what
    isolates the enrolled household.

    "Registration then rolls the account up onto its circuit: `customer_count` increases by
    one always, `medical_baseline_count` increases by one when `medical_baseline` is true,
    and `critical_facility_count` increases by one when `customer_class` is
    `CRITICAL_FACILITY` — so a medical-baseline critical facility increments all three."

    "Service class dominates the medical flag, so a critical facility that also carries a
    medical baseline enrolment is `TIER_A_CRITICAL` and not `TIER_B_MEDICAL`."

    Design: Corner/entities/circuit_customer_counters_derive_from_customer_rows
    """
    ctx = build_feeder_chain()

    assert_population_counters(
        read_circuit(ctx["alpha"]["id"]),
        customer_count=3,
        medical_baseline_count=1,
        critical_facility_count=1,
    )
    assert_population_counters(
        read_circuit(ctx["bravo"]["id"]),
        customer_count=1,
        medical_baseline_count=0,
        critical_facility_count=0,
    )
    assert_population_counters(
        read_circuit(ctx["charlie"]["id"]),
        customer_count=1,
        medical_baseline_count=0,
        critical_facility_count=0,
    )

    enrolled, enrolled_meta = validate_paginated(
        api_client.list_circuit_customers(
            ctx["alpha"]["id"], PLANNER_HEADERS, params={"medical_baseline": True}
        )
    )
    assert_integer(enrolled_meta["total_count"], 1)
    assert enrolled[0]["account_number"] == "ACC-A1"
    assert enrolled[0]["notification_tier"] == "TIER_B_MEDICAL"
    assert ctx["cust_a2"]["notification_tier"] == "TIER_A_CRITICAL"
    assert ctx["cust_a2"]["medical_baseline"] is False


def test_an_account_with_a_bad_enum_or_a_malformed_channel_set_is_refused():
    """An undeclared service class, an empty channel set, a duplicated channel and an
    undeclared language are each malformed, and none of the four reaches the circuit's
    counters.

    "Each **Customer** carries an `account_number` — unique across all accounts, 3 to 40
    characters — a `circuit_id` naming the circuit that serves it (an identifier that does
    not resolve yields `ERR_CIRCUIT_NOT_FOUND`, and reading an account that does not exist
    yields `ERR_CUSTOMER_NOT_FOUND`), a `customer_class` of `RESIDENTIAL`, `COMMERCIAL`, or
    `CRITICAL_FACILITY`, a `preferred_language` chosen from `EN`, `ES`, `ZH`, `TL`, and
    `VI`, a `notification_channels` set that must be non-empty, duplicate-free, and drawn
    from `SMS`, `VOICE`, and `EMAIL`, and an `address_zone_code` of 1 to 20 characters that
    field crews use to locate the service address."

    "Both channel and accessibility sets are unordered — the order in which a client lists
    them is never a decision input anywhere in this specification."

    Design: Corner/entities/customer_create_with_invalid_enum_or_duplicate_channels_rejected
    """
    alpha = register_circuit(circuit_code="ALPHA")

    undeclared_class = api_client.create_customer(
        factories.customer_payload(
            alpha["id"], account_number="ACC-BAD-1", customer_class="GOVERNMENT"
        ),
        PLANNER_HEADERS,
    )
    validate_error(undeclared_class, ERR_INVALID_REQUEST, 400)

    empty_channels = api_client.create_customer(
        factories.customer_payload(
            alpha["id"], account_number="ACC-BAD-2", notification_channels=[]
        ),
        PLANNER_HEADERS,
    )
    validate_error(empty_channels, ERR_INVALID_REQUEST, 400)

    duplicate_channels = api_client.create_customer(
        factories.customer_payload(
            alpha["id"], account_number="ACC-BAD-3", notification_channels=["SMS", "SMS"]
        ),
        PLANNER_HEADERS,
    )
    validate_error(duplicate_channels, ERR_INVALID_REQUEST, 400)

    undeclared_language = api_client.create_customer(
        factories.customer_payload(
            alpha["id"], account_number="ACC-BAD-4", preferred_language="FR"
        ),
        PLANNER_HEADERS,
    )
    validate_error(undeclared_language, ERR_INVALID_REQUEST, 400)

    assert_population_counters(
        read_circuit(alpha["id"]),
        customer_count=0,
        medical_baseline_count=0,
        critical_facility_count=0,
    )
    _, meta = validate_paginated(
        api_client.list_circuit_customers(alpha["id"], PLANNER_HEADERS)
    )
    assert_integer(meta["total_count"], 0)


# --------------------------------------------------------------------------
# The weather desk
# --------------------------------------------------------------------------
def test_a_new_station_starts_online_with_an_empty_telemetry_history():
    """Leaving the telemetry status out puts the station on line, and it reports no
    observations and no most-recent observation instant until one is filed.

    "`telemetry_status` is optional and **defaults to `ONLINE`**; the accepted values are
    `ONLINE`, `DEGRADED`, and `OFFLINE`."

    "New stations start with `observation_count` at zero and `last_observation_at` at
    null."

    Design: Corner/entities/weather_station_create_defaults_telemetry_status_and_observation_counters
    """
    alpha = register_circuit(circuit_code="ALPHA")

    response = api_client.create_weather_station(
        factories.weather_station_payload(
            alpha["id"],
            station_code="WS-DEF",
            elevation_ft=1500,
            representativeness_weight=0.25,
            telemetry_status=None,
        ),
        ANALYST_HEADERS,
    )

    created = get_success_data(response, 201)
    assert created["telemetry_status"] == "ONLINE"
    assert_integer(created["observation_count"], 0)
    assert created["last_observation_at"] is None
    assert created["circuit_id"] == alpha["id"]
    assert abs(float(created["representativeness_weight"]) - 0.25) < 1e-9
    # PRD fixes `elevation_ft` only as a value "between -300 and 15,000 feet above sea
    # level inclusive" and §2.6 does not list it among the integer quantities, so only its
    # round-tripped value is asserted here, not its JSON numeric type.
    assert float(created["elevation_ft"]) == 1500
    assert_versioned_entity(created, expected_version=1)


def test_a_station_naming_a_circuit_that_does_not_exist_is_refused():
    """The body foreign key is checked before anything is written, and the real circuit's
    station network stays empty.

    "**Body foreign keys resolve** — every foreign-key identifier carried in the request
    body resolves to an existing row: `circuit_id`, `weather_station_id`, `psps_event_id`,
    `trigger_fire_potential_index_id`, `patrol_assignment_id`, and each member of
    `requested_resource_center_ids`."

    "The applicable code is `ERR_CIRCUIT_NOT_FOUND`, `ERR_WEATHER_STATION_NOT_FOUND`,
    `ERR_PSPS_EVENT_NOT_FOUND`, `ERR_FIRE_POTENTIAL_INDEX_NOT_FOUND`,
    `ERR_PATROL_ASSIGNMENT_NOT_FOUND`, or `ERR_RESOURCE_CENTER_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/weather_station_with_unknown_circuit_parent_rejected
    """
    alpha = register_circuit(circuit_code="ALPHA")

    response = api_client.create_weather_station(
        factories.weather_station_payload(
            UNKNOWN_UUID,
            station_code="WS-ORPHAN",
            elevation_ft=1200,
            representativeness_weight=0.50,
        ),
        ANALYST_HEADERS,
    )

    validate_error(response, ERR_CIRCUIT_NOT_FOUND, 404)
    _, meta = validate_paginated(
        api_client.list_circuit_weather_stations(alpha["id"], ANALYST_HEADERS)
    )
    assert_integer(meta["total_count"], 0)


def test_recomputing_an_index_appends_a_second_row_instead_of_editing_the_first():
    """A refreshed forecast for the same day and the same circuit produces a distinct row
    with the same score, and both rows remain listable side by side as append-only records.

    "Index rows are immutable once written; a refreshed forecast produces a new row."

    "A fire potential index, in particular, is immutable once computed — a later forecast
    produces a new row rather than editing an existing one, which is why the risk posture
    selects among rows rather than reading one."

    "Four resource types are **append-only records** and carry only `id` and `created_at`:
    both `updated_at` and `version` are absent from their representations entirely."

    Design: Corner/entities/immutable_entities_expose_no_version_and_no_mutating_endpoint
    """
    ctx = build_feeder_chain()
    first = ctx["fpi_forecast"]
    assert_fpi(first, 85.93, "R5")

    second = compute_index(
        ctx["alpha"]["id"], FORECAST_DATE, ComputationVariant.FORECAST.value
    )

    assert second["id"] != first["id"]
    assert_fpi(second, 85.93, "R5")
    assert_append_only_record(first)
    assert_append_only_record(second)

    rows, meta = validate_paginated(
        api_client.list_circuit_fire_potential_indices(
            ctx["alpha"]["id"],
            ANALYST_HEADERS,
            params={
                "computation_variant": ComputationVariant.FORECAST.value,
                "forecast_date": FORECAST_DATE,
            },
        )
    )
    assert_integer(meta["total_count"], 2)
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    for row in rows:
        assert_fpi(row, 85.93, "R5")
        assert_append_only_record(row)

    observations, observation_meta = validate_paginated(
        api_client.list_station_observations(ctx["ws_a1"]["id"], ANALYST_HEADERS)
    )
    assert_integer(observation_meta["total_count"], 2)
    for observation in observations:
        assert_append_only_record(observation)


# --------------------------------------------------------------------------
# Shutoff events and their scope rows
# --------------------------------------------------------------------------
def test_a_newly_opened_event_starts_at_draft_with_every_score_at_zero():
    """Opening the event records only the window and the trigger; both state dimensions sit
    at their initial values and every count, score and instant the server owns is empty.

    "A new event starts with `scope_status` at `DRAFT`, `notification_status` at
    `NOT_STARTED`, `benefit_variant` at `PRE_EVENT`, `cancellation_reason`,
    `actual_de_energized_at`, and `actual_restored_at` all null, `duration_hours` at zero,
    and every computed count and score at zero."

    "Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp with three
    fractional digits, refreshed on every mutation of the row — and `version`, an integer
    that starts at 1 when the row is created and increments by exactly 1 on every
    mutation."

    Design: Corner/entities/psps_event_system_fields_start_at_draft_and_not_started
    """
    ctx = build_feeder_chain()

    response = api_client.create_psps_event(
        factories.psps_event_payload(
            ctx["fpi_forecast"]["id"], ONSET_AT, ALL_CLEAR_AT, event_code="EV-FRESH"
        ),
        OFFICER_HEADERS,
    )

    created = get_success_data(response, 201)
    assert_event_dimensions(
        created, scope_status="DRAFT", notification_status="NOT_STARTED"
    )
    assert created["cancellation_reason"] is None
    assert created["actual_de_energized_at"] is None
    assert created["actual_restored_at"] is None
    assert_scope_counts(created, confirmed=0, excluded=0)
    assert_impact_counts(created, impacted=0, medical_baseline=0, critical_facility=0)
    assert_integer(created["crc_capacity_required"], 0)
    assert_integer(created["crc_capacity_served"], 0)
    assert_net_benefit(
        created,
        variant="PRE_EVENT",
        duration_hours=0,
        customer_impact_score=0.00,
        crc_mitigation_credit=0.00,
        adjusted_customer_impact_score=0.00,
        ignition_risk_avoided_score=0.00,
        net_benefit_ratio=0.0000,
    )
    assert_versioned_entity(created, expected_version=1)


def test_a_scope_row_reads_the_same_from_the_event_and_from_its_circuit():
    """The three rows come back from the event in walk order, the head of the chain reaches
    its single row from the circuit side, and both views name the same row.

    "Each written row captures `customer_count_snapshot` from its circuit's
    `customer_count` at write time — a frozen figure, so later account registrations do not
    retroactively change what the event reports."

    "Unless a specific endpoint's description in §4 says otherwise, list results are
    ordered by `created_at` ascending."

    Design: Corner/entities/event_scope_rows_are_reachable_from_both_of_their_parents
    """
    ctx = build_scoped_event()

    rows = read_scope_rows(ctx["event_id"])
    assert [row["circuit_id"] for row in rows] == [
        ctx["alpha"]["id"],
        ctx["bravo"]["id"],
        ctx["charlie"]["id"],
    ]
    head = rows[0]
    assert head["psps_event_id"] == ctx["event_id"]
    assert head["inclusion_basis"] == "PRIMARY_RISK"
    assert head["scope_status"] == "CONFIRMED"
    assert_integer(head["customer_count_snapshot"], 3)
    assert_versioned_entity(head)

    from_circuit, circuit_meta = validate_paginated(
        api_client.list_circuit_event_scopes(ctx["alpha"]["id"], OFFICER_HEADERS)
    )
    assert_integer(circuit_meta["total_count"], 1)
    assert from_circuit[0]["id"] == head["id"]
    assert from_circuit[0]["psps_event_id"] == ctx["event_id"]

    _, excluded_meta = validate_paginated(
        api_client.list_event_scopes(
            ctx["event_id"], OFFICER_HEADERS, params={"scope_status": "EXCLUDED"}
        )
    )
    assert_integer(excluded_meta["total_count"], 0)


# --------------------------------------------------------------------------
# Notification records and damage findings
# --------------------------------------------------------------------------
def test_every_delivery_record_field_is_written_by_the_dispatch_routine():
    """The caller supplies nothing per account: the five records carry a contiguous attempt
    order and a server-chosen language, format and outcome, with no version field at all.

    "Each target receives one **NotificationRecord** naming its `notification_batch_id` and
    `customer_id`, with `attempt_order` recording its 1-based position in that order."

    "Targets are ordered deterministically, first by notification tier —
    `TIER_A_CRITICAL` before `TIER_B_MEDICAL` before `TIER_C_STANDARD` — and then by
    account `created_at` ascending."

    Design: Corner/entities/notification_record_fields_are_entirely_server_derived
    """
    ctx = build_advance_dispatched_event()

    records, meta = read_records(notification_batch_id=ctx["batch_advance"]["id"])

    assert_integer(meta["total_count"], 5)
    assert len(records) == 5
    for record in records:
        assert record["notification_batch_id"] == ctx["batch_advance"]["id"]
        assert record["customer_id"] is not None
        assert record["attempt_order"] is not None
        assert record["language_used"] is not None
        assert record["accessibility_format"] is not None
        assert record["delivery_status"] is not None
        assert_append_only_record(record)
    assert sorted(record["attempt_order"] for record in records) == [1, 2, 3, 4, 5]


def test_a_damage_finding_takes_its_found_at_from_the_logical_clock():
    """Two findings filed an hour and a half apart carry the two clock positions rather
    than anything the supervisor supplied, and the assignment counts them separately.

    "`found_at` is stamped from the logical clock by the server rather than supplied."

    "Filing a finding increments the assignment's `damage_finding_count` and, when the
    `severity` is `IGNITION_RISK`, also its `ignition_risk_finding_count`, and increments
    the assignment's `version`."

    Design: Corner/entities/damage_finding_found_at_is_stamped_from_the_logical_clock
    """
    ctx = build_restoring_event()
    assignment = schedule_patrol(
        ctx["event_id"],
        ctx["alpha"]["id"],
        PATROL_START_AT,
        PATROL_DONE_AT,
        patrol_lead_user_id="crew_lead_1",
        patrol_mode=PatrolMode.GROUND.value,
    )
    move_clock(PATROL_CLOCK_AT)
    assert start_patrol(assignment["id"])["status"] == "IN_PROGRESS"

    minor = file_finding(
        assignment["id"],
        DamageSeverity.MINOR.value,
        description=MINOR_NOTE,
        requires_repair=False,
    )
    move_clock(SECOND_FINDING_AT)
    ignition = file_finding(
        assignment["id"],
        DamageSeverity.IGNITION_RISK.value,
        description=IGNITION_NOTE,
        requires_repair=True,
    )

    assert_instant(minor["found_at"], PATROL_CLOCK_AT)
    assert_instant(ignition["found_at"], SECOND_FINDING_AT)
    assert_append_only_record(minor)
    assert_append_only_record(ignition)

    counted = read_patrol(assignment["id"])
    assert_integer(counted["damage_finding_count"], 2)
    assert_integer(counted["ignition_risk_finding_count"], 1)

    rows, meta = validate_paginated(
        api_client.list_patrol_damage_findings(
            assignment["id"],
            SUPERVISOR_HEADERS,
            params={"severity": DamageSeverity.IGNITION_RISK.value},
        )
    )
    assert_integer(meta["total_count"], 1)
    assert rows[0]["id"] == ignition["id"]
    assert rows[0]["requires_repair"] is True
