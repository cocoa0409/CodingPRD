"""Which rule decides when several could reject the same request: authentication before
authorisation, authorisation before existence, existence before shape, shape before body
foreign keys, and the version guard before the target's own state."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_CIRCUIT_NOT_FOUND,
    ERR_EVENT_SCOPE_NOT_FOUND,
    ERR_EVENT_TERMINAL,
    ERR_FIRE_POTENTIAL_INDEX_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_PATROL_ASSIGNMENT_NOT_FOUND,
    ERR_PSPS_EVENT_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import assert_integer, assert_scope_counts
from test_helpers.constants import MAX_LIMIT, UNKNOWN_UUID
from test_helpers.fixtures import (
    ADVANCE_SEND_AT,
    ALL_CLEAR_AT,
    ONSET_AT,
    build_active_event,
    build_advance_dispatched_event,
    build_armed_event,
    build_closed_event,
    build_feeder_chain,
    build_imminent_dispatched_event,
    build_patrolled_event,
    build_restored_event,
    build_restoring_event,
    list_circuits,
    open_event,
    read_circuit,
    read_event,
    read_scope_rows,
    register_circuit,
    scope_event,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    EMPTY_USER_HEADERS,
    ENGINEER_HEADERS,
    INSPECTOR_HEADERS,
    LIAISON_HEADERS,
    MISSING_ROLE_HEADERS,
    NO_HEADERS,
    OFFICER_HEADERS,
    PLANNER_HEADERS,
    PLANNER_PRIMARY,
    SUPERVISOR_HEADERS,
    UNDECLARED_ROLE_HEADERS,
)
from test_helpers.types import HftdTier, NotificationStage

#: A second unrecognised role string, so the priority-2 refusal is not an artefact of one
#: particular spelling.
SUPER_USER_HEADERS = {"X-User-ID": PLANNER_PRIMARY, "X-User-Role": "SuperUser"}

MALFORMED_FORECAST_DATE = "2026-8-1"


def _closed_event_with_its_creation_version():
    """The feeder chain driven all the way to a `CLOSED` EV-1, returning the event's
    version as it read at creation alongside the live context."""
    ctx = build_feeder_chain()
    event = open_event(ctx["fpi_forecast"]["id"])
    created_version = event["version"]
    ctx["event_id"] = event["id"]
    ctx["event"] = scope_event(event["id"], created_version)
    ctx = build_advance_dispatched_event(ctx)
    ctx = build_armed_event(ctx)
    ctx = build_imminent_dispatched_event(ctx)
    ctx = build_active_event(ctx)
    ctx = build_restoring_event(ctx)
    ctx = build_patrolled_event(ctx)
    ctx = build_restored_event(ctx)
    ctx = build_closed_event(ctx)
    return ctx, created_version


# --------------------------------------------------------------------------
# Priorities 1 and 2 — the identity headers
# --------------------------------------------------------------------------
def test_an_anonymous_call_is_refused_before_the_path_the_body_or_the_role_list():
    """A header-less read, a role-less read and a POST whose `X-User-ID` is the empty
    string all come back 401, and the circuit the POST described was never written.

    "**Headers present** — `X-User-Role` and `X-User-ID` are both present and
    non-empty. Otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    "When more than one rule could reject a request, the rule with the lowest
    priority number below decides the response. This ordering is normative: a caller
    who violates two rules receives the error of the earlier one, and a test that
    provokes a late-priority failure must not be masked by an early-priority one."

    Design: Corner/validations/missing_user_headers_is_unauthenticated
    """
    headerless = api_client.list_circuits(NO_HEADERS)
    anonymous = validate_error(headerless, ERR_UNAUTHENTICATED, 401)
    assert anonymous["message"].strip()

    role_less = api_client.list_circuits(MISSING_ROLE_HEADERS)
    validate_error(role_less, ERR_UNAUTHENTICATED, 401)

    ghost = api_client.create_circuit(
        factories.circuit_payload(
            circuit_code="GHOST",
            hftd_tier=HftdTier.TIER_1.value,
            overhead_miles=3.0,
            equipment_condition_index=90,
        ),
        EMPTY_USER_HEADERS,
    )
    empty_identifier = validate_error(ghost, ERR_UNAUTHENTICATED, 401)
    assert empty_identifier["message"].strip()

    rows, meta = list_circuits()
    assert_integer(meta["total_count"], 0)
    assert rows == [], "the GHOST circuit must never have been created"


def test_an_unrecognised_role_string_is_an_authentication_failure_not_a_forbidden_one():
    """`WildfireCzar` and `SuperUser` are both refused at priority 2 with 401 rather than
    at priority 3 with 403, on an endpoint that a declared role reads happily.

    "**Role recognised** — `X-User-Role` names one of the eight roles in §2.1.
    Otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    "**Role authorised** — `X-User-Role` appears in the called endpoint's
    authorised-role list in §4. Otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to
    every endpoint."

    Design: Corner/validations/undeclared_role_header_is_unauthenticated_not_forbidden
    """
    alpha = register_circuit(circuit_code="ALPHA")

    czar_read = api_client.get_circuit(alpha["id"], UNDECLARED_ROLE_HEADERS)
    validate_error(czar_read, ERR_UNAUTHENTICATED, 401)
    assert czar_read.status_code != 403, "priority 2 fires before priority 3"

    super_user_create = api_client.create_circuit(
        factories.circuit_payload(
            circuit_code="NOPE",
            hftd_tier=HftdTier.TIER_1.value,
            overhead_miles=3.0,
            equipment_condition_index=90,
        ),
        SUPER_USER_HEADERS,
    )
    validate_error(super_user_create, ERR_UNAUTHENTICATED, 401)
    assert super_user_create.status_code != 403, "priority 2 fires before priority 3"

    readable = validate_success(api_client.get_circuit(alpha["id"], ANALYST_HEADERS), 200)
    assert readable["circuit_code"] == "ALPHA"


# --------------------------------------------------------------------------
# Priority 3 — the endpoint's own allow list
# --------------------------------------------------------------------------
def test_authorisation_is_decided_per_endpoint_and_not_by_a_global_rank():
    """The analyst who may compute indices may not register a circuit, and the inspector
    who may read a circuit may not read its account roster.

    "**Role authorised** — `X-User-Role` appears in the called endpoint's
    authorised-role list in §4. Otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to
    every endpoint."

    Design: Corner/validations/role_outside_the_endpoint_allow_list_is_forbidden
    """
    alpha = register_circuit(circuit_code="ALPHA")

    analyst_create = api_client.create_circuit(
        factories.circuit_payload(
            circuit_code="MET-1",
            hftd_tier=HftdTier.TIER_1.value,
            overhead_miles=3.0,
            equipment_condition_index=90,
        ),
        ANALYST_HEADERS,
    )
    validate_error(analyst_create, ERR_FORBIDDEN_ROLE, 403)

    inspector_roster = api_client.list_circuit_customers(alpha["id"], INSPECTOR_HEADERS)
    validate_error(inspector_roster, ERR_FORBIDDEN_ROLE, 403)

    neighbouring_read = validate_success(
        api_client.get_circuit(alpha["id"], INSPECTOR_HEADERS), 200
    )
    assert neighbouring_read["circuit_code"] == "ALPHA"

    rows, meta = list_circuits()
    assert_integer(meta["total_count"], 1)
    assert [row["circuit_code"] for row in rows] == ["ALPHA"]


# --------------------------------------------------------------------------
# Priorities 4 and 6 — existence, in the path and in the body
# --------------------------------------------------------------------------
def test_each_unresolvable_identifier_reports_the_entity_that_is_actually_missing():
    """Three reads and three creates against the same absent UUID produce four different
    404 codes, because each names the entity whose row is missing.

    "**Path identifiers resolve** — every id embedded in the request path resolves
    to an existing row, validated left to right, so that the leftmost unresolvable
    segment determines the error. The applicable code is `ERR_CIRCUIT_NOT_FOUND`,
    `ERR_WEATHER_STATION_NOT_FOUND`, `ERR_PSPS_EVENT_NOT_FOUND`,
    `ERR_EVENT_SCOPE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_NOTIFICATION_BATCH_NOT_FOUND`, `ERR_NOTIFICATION_RECORD_NOT_FOUND`,
    `ERR_MITIGATION_PROJECT_NOT_FOUND`, `ERR_PATROL_ASSIGNMENT_NOT_FOUND`,
    `ERR_RESOURCE_CENTER_NOT_FOUND`, or `ERR_PLAN_FILING_NOT_FOUND`, each HTTP 404.
    Applies to every endpoint with a path id."

    "**Body foreign keys resolve** — every foreign-key identifier carried in the
    request body resolves to an existing row: `circuit_id`, `weather_station_id`,
    `psps_event_id`, `trigger_fire_potential_index_id`, `patrol_assignment_id`, and
    each member of `requested_resource_center_ids`. The applicable code is
    `ERR_CIRCUIT_NOT_FOUND`, `ERR_WEATHER_STATION_NOT_FOUND`,
    `ERR_PSPS_EVENT_NOT_FOUND`, `ERR_FIRE_POTENTIAL_INDEX_NOT_FOUND`,
    `ERR_PATROL_ASSIGNMENT_NOT_FOUND`, or `ERR_RESOURCE_CENTER_NOT_FOUND`, each HTTP
    404. Applies to `POST /weather-stations`, `POST /weather-observations`, `POST
    /fire-potential-indices`, `POST /psps-events`, `POST /customers`, `POST
    /notification-batches`, `POST /mitigation-projects`, `POST /patrol-assignments`,
    `POST /damage-findings`, and `POST /psps-events/{id}/activate-resource-centers`."

    Design: Corner/validations/unknown_path_id_and_unknown_body_fk_each_return_not_found
    """
    alpha = register_circuit(circuit_code="ALPHA")

    validate_error(
        api_client.get_circuit(UNKNOWN_UUID, PLANNER_HEADERS), ERR_CIRCUIT_NOT_FOUND, 404
    )
    validate_error(
        api_client.get_psps_event(UNKNOWN_UUID, OFFICER_HEADERS),
        ERR_PSPS_EVENT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_patrol_assignment(UNKNOWN_UUID, SUPERVISOR_HEADERS),
        ERR_PATROL_ASSIGNMENT_NOT_FOUND,
        404,
    )

    validate_error(
        api_client.create_weather_station(
            factories.weather_station_payload(
                UNKNOWN_UUID,
                station_code="WS-GHOST",
                elevation_ft=1000,
                representativeness_weight=1.00,
            ),
            ANALYST_HEADERS,
        ),
        ERR_CIRCUIT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_psps_event(
            factories.psps_event_payload(
                UNKNOWN_UUID, ONSET_AT, ALL_CLEAR_AT, event_code="EV-GHOST"
            ),
            OFFICER_HEADERS,
        ),
        ERR_FIRE_POTENTIAL_INDEX_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_notification_batch(
            factories.notification_batch_payload(
                UNKNOWN_UUID, ADVANCE_SEND_AT, stage=NotificationStage.ADVANCE_48H.value
            ),
            LIAISON_HEADERS,
        ),
        ERR_PSPS_EVENT_NOT_FOUND,
        404,
    )

    stations, station_meta = validate_paginated(
        api_client.list_circuit_weather_stations(alpha["id"], PLANNER_HEADERS)
    )
    assert_integer(station_meta["total_count"], 0)
    assert stations == []
    events, event_meta = validate_paginated(api_client.list_psps_events(OFFICER_HEADERS))
    assert_integer(event_meta["total_count"], 0)
    assert events == []


# --------------------------------------------------------------------------
# Priority 5 — one code for every shape failure
# --------------------------------------------------------------------------
def test_absent_fields_bad_enums_out_of_range_numbers_and_bad_dates_share_one_code():
    """Ten differently malformed requests — a zero mileage, an undeclared tier, an index
    above 100, an absent required field, a duplicated and an empty channel set, an
    undeclared language, a zero weight, a short-form date and an oversized page — all
    report the same 400.

    "**Request shape** — every required body field is present; every enum value is a
    declared member; every numeric value sits inside its declared range
    (`overhead_miles` greater than 0; `equipment_condition_index` from 0 through 100
    inclusive; `representativeness_weight` greater than 0 and at most 1;
    `site_capacity` at least 1; `planned_miles` greater than 0;
    `unit_cost_per_mile_cents` at least 0; `completed_miles_delta` greater than 0;
    `miles_patrolled` at least 0; `plan_year` from 2020 through 2100 inclusive;
    `limit` from 1 through 100 inclusive; `offset` at least 0);
    `notification_channels` is a non-empty, duplicate-free subset of `SMS`, `VOICE`,
    and `EMAIL`; `accessibility_needs` is a duplicate-free subset of `LARGE_PRINT`,
    `TTY`, and `AUDIO`; every datetime parses as an ISO 8601 UTC instant; and
    `forecast_date` matches the four-digit-year, two-digit-month, two-digit-day
    pattern `YYYY-MM-DD`. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every
    endpoint with a request body or query parameters."

    Design: Corner/validations/out_of_range_numbers_and_bad_enums_are_invalid_request
    """
    alpha = register_circuit(circuit_code="ALPHA")

    zero_miles = api_client.create_circuit(
        factories.circuit_payload(
            circuit_code="ZERO",
            hftd_tier=HftdTier.TIER_1.value,
            overhead_miles=0.0,
            equipment_condition_index=90,
        ),
        PLANNER_HEADERS,
    )
    validate_error(zero_miles, ERR_INVALID_REQUEST, 400)

    undeclared_tier = api_client.create_circuit(
        factories.circuit_payload(
            circuit_code="TIER4",
            hftd_tier="TIER_4",
            overhead_miles=3.0,
            equipment_condition_index=90,
        ),
        PLANNER_HEADERS,
    )
    validate_error(undeclared_tier, ERR_INVALID_REQUEST, 400)

    above_the_index_ceiling = api_client.create_circuit(
        factories.circuit_payload(
            circuit_code="ECI",
            hftd_tier=HftdTier.TIER_1.value,
            overhead_miles=3.0,
            equipment_condition_index=101,
        ),
        PLANNER_HEADERS,
    )
    validate_error(above_the_index_ceiling, ERR_INVALID_REQUEST, 400)

    without_mileage = factories.circuit_payload(
        circuit_code="NOMILES",
        hftd_tier=HftdTier.TIER_1.value,
        equipment_condition_index=90,
    )
    without_mileage.pop("overhead_miles")
    validate_error(
        api_client.create_circuit(without_mileage, PLANNER_HEADERS),
        ERR_INVALID_REQUEST,
        400,
    )

    duplicate_channels = api_client.create_customer(
        factories.customer_payload(
            alpha["id"],
            account_number="DUP-CH",
            notification_channels=["SMS", "SMS"],
            address_zone_code="Z9",
        ),
        LIAISON_HEADERS,
    )
    validate_error(duplicate_channels, ERR_INVALID_REQUEST, 400)

    no_channels = api_client.create_customer(
        factories.customer_payload(
            alpha["id"],
            account_number="NO-CH",
            notification_channels=[],
            address_zone_code="Z9",
        ),
        LIAISON_HEADERS,
    )
    validate_error(no_channels, ERR_INVALID_REQUEST, 400)

    undeclared_language = api_client.create_customer(
        factories.customer_payload(
            alpha["id"],
            account_number="BAD-LANG",
            preferred_language="FR",
            address_zone_code="Z9",
        ),
        LIAISON_HEADERS,
    )
    validate_error(undeclared_language, ERR_INVALID_REQUEST, 400)

    zero_weight = api_client.create_weather_station(
        factories.weather_station_payload(
            alpha["id"],
            station_code="W0",
            elevation_ft=900,
            representativeness_weight=0.0,
        ),
        ANALYST_HEADERS,
    )
    validate_error(zero_weight, ERR_INVALID_REQUEST, 400)

    short_form_date = api_client.create_fire_potential_index(
        factories.fpi_payload(alpha["id"], MALFORMED_FORECAST_DATE), ANALYST_HEADERS
    )
    validate_error(short_form_date, ERR_INVALID_REQUEST, 400)

    oversized_page = api_client.list_circuits(
        PLANNER_HEADERS, params={"limit": MAX_LIMIT + 1}
    )
    validate_error(oversized_page, ERR_INVALID_REQUEST, 400)

    rows, meta = list_circuits()
    assert_integer(meta["total_count"], 1)
    assert [row["circuit_code"] for row in rows] == ["ALPHA"]
    roster, roster_meta = validate_paginated(
        api_client.list_circuit_customers(alpha["id"], PLANNER_HEADERS)
    )
    assert_integer(roster_meta["total_count"], 0)
    assert roster == []
    stations, station_meta = validate_paginated(
        api_client.list_circuit_weather_stations(alpha["id"], PLANNER_HEADERS)
    )
    assert_integer(station_meta["total_count"], 0)
    indices, index_meta = validate_paginated(
        api_client.list_circuit_fire_potential_indices(alpha["id"], PLANNER_HEADERS)
    )
    assert_integer(index_meta["total_count"], 0)
    assert indices == []


# --------------------------------------------------------------------------
# The orderings themselves
# --------------------------------------------------------------------------
def test_authorisation_is_decided_before_existence_so_a_missing_id_never_leaks():
    """The same arm call against the same absent event answers 403 to the analyst and 404
    to the duty officer, so the only observable difference is the caller's role.

    "**Role authorised** — `X-User-Role` appears in the called endpoint's
    authorised-role list in §4. Otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to
    every endpoint."

    "**Path identifiers resolve** — every id embedded in the request path resolves
    to an existing row, validated left to right, so that the leftmost unresolvable
    segment determines the error."

    Design: Corner/validations/forbidden_role_beats_unknown_path_id
    """
    forbidden = api_client.arm_psps_event(UNKNOWN_UUID, ANALYST_HEADERS)
    validate_error(forbidden, ERR_FORBIDDEN_ROLE, 403)

    not_found = api_client.arm_psps_event(UNKNOWN_UUID, OFFICER_HEADERS)
    validate_error(not_found, ERR_PSPS_EVENT_NOT_FOUND, 404)

    assert forbidden.status_code == 403
    assert not_found.status_code == 404


def test_path_existence_is_resolved_before_the_body_is_inspected():
    """A completion carrying a negative mileage and an exclusion carrying no justification
    at all both report the missing path row, not the malformed body.

    "**Path identifiers resolve** — every id embedded in the request path resolves
    to an existing row, validated left to right, so that the leftmost unresolvable
    segment determines the error."

    "**Request shape** — every required body field is present; every enum value is a
    declared member; every numeric value sits inside its declared range
    (`overhead_miles` greater than 0; `equipment_condition_index` from 0 through 100
    inclusive; `representativeness_weight` greater than 0 and at most 1;
    `site_capacity` at least 1; `planned_miles` greater than 0;
    `unit_cost_per_mile_cents` at least 0; `completed_miles_delta` greater than 0;
    `miles_patrolled` at least 0; `plan_year` from 2020 through 2100 inclusive;
    `limit` from 1 through 100 inclusive; `offset` at least 0);
    `notification_channels` is a non-empty, duplicate-free subset of `SMS`, `VOICE`,
    and `EMAIL`; `accessibility_needs` is a duplicate-free subset of `LARGE_PRINT`,
    `TTY`, and `AUDIO`; every datetime parses as an ISO 8601 UTC instant; and
    `forecast_date` matches the four-digit-year, two-digit-month, two-digit-day
    pattern `YYYY-MM-DD`. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every
    endpoint with a request body or query parameters."

    Design: Corner/validations/unknown_path_id_beats_malformed_body_returns_not_found
    """
    negative_mileage = api_client.complete_patrol(
        UNKNOWN_UUID, factories.complete_patrol_payload(-5.0), SUPERVISOR_HEADERS
    )
    validate_error(negative_mileage, ERR_PATROL_ASSIGNMENT_NOT_FOUND, 404)
    assert negative_mileage.status_code != 400

    no_justification = api_client.exclude_event_scope(
        UNKNOWN_UUID, {}, ENGINEER_HEADERS
    )
    validate_error(no_justification, ERR_EVENT_SCOPE_NOT_FOUND, 404)
    assert no_justification.status_code != 400


def test_body_well_formedness_is_decided_before_body_foreign_keys_are_resolved():
    """A weight of five and an undeclared programme type each mask a genuinely unknown
    `circuit_id`, so both requests report 400 rather than 404.

    "**Request shape** — every required body field is present; every enum value is a
    declared member; every numeric value sits inside its declared range
    (`overhead_miles` greater than 0; `equipment_condition_index` from 0 through 100
    inclusive; `representativeness_weight` greater than 0 and at most 1;
    `site_capacity` at least 1; `planned_miles` greater than 0;
    `unit_cost_per_mile_cents` at least 0; `completed_miles_delta` greater than 0;
    `miles_patrolled` at least 0; `plan_year` from 2020 through 2100 inclusive;
    `limit` from 1 through 100 inclusive; `offset` at least 0);
    `notification_channels` is a non-empty, duplicate-free subset of `SMS`, `VOICE`,
    and `EMAIL`; `accessibility_needs` is a duplicate-free subset of `LARGE_PRINT`,
    `TTY`, and `AUDIO`; every datetime parses as an ISO 8601 UTC instant; and
    `forecast_date` matches the four-digit-year, two-digit-month, two-digit-day
    pattern `YYYY-MM-DD`. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every
    endpoint with a request body or query parameters."

    "**Body foreign keys resolve** — every foreign-key identifier carried in the
    request body resolves to an existing row: `circuit_id`, `weather_station_id`,
    `psps_event_id`, `trigger_fire_potential_index_id`, `patrol_assignment_id`, and
    each member of `requested_resource_center_ids`."

    Design: Corner/validations/malformed_body_beats_unknown_body_fk_invalid_request
    """
    out_of_range_weight = api_client.create_weather_station(
        factories.weather_station_payload(
            UNKNOWN_UUID,
            station_code="WS-BAD",
            elevation_ft=900,
            representativeness_weight=5.0,
        ),
        ANALYST_HEADERS,
    )
    validate_error(out_of_range_weight, ERR_INVALID_REQUEST, 400)
    assert out_of_range_weight.status_code != 404

    undeclared_programme = api_client.create_mitigation_project(
        factories.mitigation_project_payload(
            UNKNOWN_UUID,
            project_code="MP-BAD",
            program_type="TREE_TRIMMING",
            planned_miles=1.0,
            unit_cost_per_mile_cents=100,
        ),
        PLANNER_HEADERS,
    )
    validate_error(undeclared_programme, ERR_INVALID_REQUEST, 400)
    assert undeclared_programme.status_code != 404


def test_the_version_guard_is_decided_before_the_events_own_terminal_state():
    """Re-scoping a closed event with the version captured at creation answers 412, and
    only a caller holding the current version is told the event is terminal.

    "**Parent version guard** — the OCC field equals the guarded parent's current
    `version`, as specified in §2.7. Otherwise `ERR_STALE_VERSION` (412). Applies to
    exactly two endpoints: `POST /psps-events/{id}/scope` and `POST
    /mitigation-projects/{id}/record-completion`."

    "**Own-state guard** — the target resource itself is in a state that admits the
    requested transition."

    "Any state-advancing call against an event whose `scope_status` is already
    `CLOSED` or `CANCELLED` is rejected with `ERR_EVENT_TERMINAL` (409) at the
    own-state step, regardless of which specific transition was requested."

    Design: Corner/validations/stale_version_beats_terminal_state_and_returns_stale_version
    """
    ctx, created_version = _closed_event_with_its_creation_version()
    closed = read_event(ctx["event_id"])
    assert closed["scope_status"] == "CLOSED"
    assert closed["version"] != created_version

    stale = api_client.scope_psps_event(
        ctx["event_id"], factories.scope_payload(created_version), OFFICER_HEADERS
    )
    validate_error(stale, ERR_STALE_VERSION, 412)

    current = api_client.scope_psps_event(
        ctx["event_id"], factories.scope_payload(closed["version"]), OFFICER_HEADERS
    )
    validate_error(current, ERR_EVENT_TERMINAL, 409)

    unmoved = read_event(ctx["event_id"])
    assert unmoved["scope_status"] == "CLOSED"
    assert_integer(unmoved["version"], closed["version"])
    assert_scope_counts(unmoved, confirmed=3, excluded=0)

    rows = read_scope_rows(ctx["event_id"])
    assert len(rows) == 3, "neither rejection may re-write the scope set"
    for row in rows:
        assert row["scope_status"] == "CONFIRMED"
        assert row["restored_at"] is not None
    assert read_circuit(ctx["alpha"]["id"])["energization_state"] == "ENERGIZED"
