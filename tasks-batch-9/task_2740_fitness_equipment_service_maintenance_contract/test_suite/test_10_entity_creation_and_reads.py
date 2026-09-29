"""
Entity creation, single-row reads, listing and identifier resolution.

These tests exercise what the PRD says about bringing a row into existence and
reading it back: which optional inputs carry declared defaults, which values are
derived at creation from the tier tables, which fields are system-owned, and which
not-found code each path or body identifier answers with when it names no row.

Every precondition is built through declared endpoints because the database is empty
at the start of each test, and every instant is written against the logical service
clock rather than the host wall clock.
"""

from decimal import Decimal

import pytest

from test_helpers import (
    CLUB_DEFAULT_CLOSE_MINUTE,
    CLUB_DEFAULT_MAX_CONCURRENT_VISITS,
    CLUB_DEFAULT_OPEN_MINUTE,
    CREDIT_CAP_PCT,
    DEFAULT_LIMIT,
    ERR_CALL_NOT_FOUND,
    ERR_CLUB_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_DOWNTIME_EVENT_NOT_FOUND,
    ERR_EQUIPMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MODEL_NOT_FOUND,
    ERR_PART_NOT_FOUND,
    ERR_PART_ORDER_NOT_FOUND,
    ERR_QUOTE_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_TECHNICIAN_NOT_FOUND,
    ERR_VISIT_NOT_FOUND,
    HEALTH_AGE_POINTS_PER_YEAR,
    SLA_RESPONSE_MINUTES,
    TECHNICIAN_DEFAULT_MAX_COMMITTED_MINUTES,
    UNKNOWN_UUID,
    assert_common_fields,
    assert_created_at_ascending,
    assert_envelope_meta,
    assert_fields,
    assert_instant,
    assert_money,
    assert_null_fields,
    assert_pagination_meta,
    assert_two_decimals,
    arrive_call,
    club_payload,
    contract_payload,
    dispatch_call,
    dispatch_payload,
    equipment_model_payload,
    equipment_payload,
    new_active_contract,
    new_club,
    new_equipment,
    new_model,
    new_technician,
    open_call,
    part_payload,
    parts_hold_payload,
    read_call,
    read_club,
    read_technician,
    round_half_up,
    round_half_up_cents,
    set_clock,
    technician_headers,
    technician_payload,
    usage_reading_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Shared literals for the worlds these tests build ─────────────────────────

CLOCK = "2026-08-15T08:00:00Z"

# Region codes are two to four uppercase letters, and technician eligibility is an
# exact match against the club's code.
REGION_A = "NW"
REGION_B = "STH"

PM_INTERVAL_HOURS = 250
SERVICE_LIFE_HOURS = 20000
BASE_ANNUAL_SERVICE_CENTS = 120000

INSTALL_DATE = "2024-03-01"
# floor((2026-08-15 − 2024-03-01) / 365 days) == floor(897 / 365) == 2 whole years.
AGE_YEARS_AT_CLOCK = 2


def _usage_based_health_score(usage_hours, service_life_hours, age_years):
    """The usage-based condition score of §3.9, rounded half up to two decimals."""
    usage_ratio = Decimal(str(usage_hours)) / Decimal(service_life_hours)
    raw = (
        Decimal(100)
        - Decimal(100) * usage_ratio
        - Decimal(HEALTH_AGE_POINTS_PER_YEAR) * Decimal(age_years)
    )
    return round_half_up(raw, 2)


def test_club_creation_applies_declared_operating_window_and_capacity_defaults(
    api, admin
):
    """
    A club registered with only a name and a region takes its declared window, capacity and counter defaults.

    "Opening defaults to 300 — five in the morning UTC — and accepts any value from 0 through 1439."
    "The two derived counters `covered_unit_count` and `open_safety_lockout_count` both start at zero on a newly registered club."

    Design: Corner/entities/club_creation_applies_operating_window_and_capacity_defaults
    """
    payload = club_payload(name="Northside Fitness", region_code=REGION_A)
    assert set(payload) == {"name", "region_code"}, (
        "the optional window and capacity inputs must be omitted entirely"
    )

    response = api.create_club(payload, admin)
    club = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object"
    assert_envelope_meta(body)

    assert_fields(
        club,
        name="Northside Fitness",
        region_code=REGION_A,
        operating_open_minute=CLUB_DEFAULT_OPEN_MINUTE,
        operating_close_minute=CLUB_DEFAULT_CLOSE_MINUTE,
        max_concurrent_visits=CLUB_DEFAULT_MAX_CONCURRENT_VISITS,
        covered_unit_count=0,
        open_safety_lockout_count=0,
    )
    assert_common_fields(club, expected_version=1)


def test_equipment_read_returns_the_stored_snapshot_with_the_pm_baseline_seeded(
    api, coordinator
):
    """
    A freshly registered unit reads back with its PM baseline seeded to the opening meter and a usage-based condition score.

    "On registration, `usage_hours` and `usage_hours_at_last_pm` are both seeded to `initial_usage_hours` (zero when the field is omitted), `pm_status` reads `OK`, `lifecycle_status` reads `IN_SERVICE`, `support_status` reads `SUPPORTED`, `downtime_minutes_ytd` is zero, `loaner_active` is `false`, and `eos_notified_at`, `last_safety_clearance_at` and `safety_lockout_reason` are all null."
    "It takes `usage_ratio = usage_hours / model.expected_service_life_hours` and `age_years = floor((clock date − install_date) / 365 days)`, then `raw = 100 − (100 × usage_ratio) − (2 × age_years)`."

    Design: Corner/entities/equipment_get_returns_stored_snapshot_with_seeded_pm_baseline
    """
    set_clock(api, CLOCK)
    club = new_club(api, name="Northside Fitness", region_code=REGION_A)
    model = new_model(
        api,
        pm_interval_hours=PM_INTERVAL_HOURS,
        expected_service_life_hours=SERVICE_LIFE_HOURS,
        base_annual_service_cents=BASE_ANNUAL_SERVICE_CENTS,
    )
    created = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-GET-1",
        install_date=INSTALL_DATE,
        initial_usage_hours=4000,
    )

    response = api.get_equipment(created["id"], coordinator)
    unit = validate_success(response, 200)
    assert response.json()["response_type"] == "object"

    assert_fields(
        unit,
        id=created["id"],
        club_id=club["id"],
        model_id=model["id"],
        serial_number="SN-GET-1",
        install_date=INSTALL_DATE,
        pm_status="OK",
        lifecycle_status="IN_SERVICE",
        support_status="SUPPORTED",
        downtime_minutes_ytd=0,
        loaner_active=False,
        replacement_recommended=False,
        health_score_variant="USAGE_BASED",
    )
    assert_two_decimals(unit["usage_hours"], Decimal("4000.00"), "usage_hours")
    assert_two_decimals(
        unit["usage_hours_at_last_pm"], Decimal("4000.00"), "usage_hours_at_last_pm"
    )
    assert_two_decimals(
        unit["health_score"],
        _usage_based_health_score(4000, SERVICE_LIFE_HOURS, AGE_YEARS_AT_CLOCK),
        "health_score",
    )
    assert_null_fields(unit, "safety_lockout_reason", "eos_notified_at")
    assert_common_fields(unit)


def test_equipment_list_filters_by_club_and_applies_the_requested_page_window(
    api, admin
):
    """
    Filtering the fleet by club returns only that club's units, and the page window counts the filtered set.

    "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending — oldest row first."
    "The `meta` object of every list response carries `limit` (the page size actually applied), `offset` (the starting position actually applied), `total_count` (the number of rows matching the filters before pagination) and `has_more` (`true` when rows matching the filters remain beyond the current page)."

    Design: Corner/entities/equipment_list_filters_by_club_and_honors_pagination_window
    """
    set_clock(api, CLOCK)
    club_a = new_club(api, name="Northside Fitness", region_code=REGION_A)
    club_b = new_club(api, name="Southside Fitness", region_code=REGION_B)
    model = new_model(
        api,
        pm_interval_hours=PM_INTERVAL_HOURS,
        expected_service_life_hours=SERVICE_LIFE_HOURS,
        base_annual_service_cents=BASE_ANNUAL_SERVICE_CENTS,
    )

    # Each unit is registered a minute later than the last so that the oldest-first
    # order the PRD requires is unambiguous on the wire.
    first = new_equipment(
        api, club_a["id"], model["id"], serial_number="SN-L-1", install_date="2024-03-01"
    )
    set_clock(api, "2026-08-15T08:01:00Z")
    second = new_equipment(
        api, club_a["id"], model["id"], serial_number="SN-L-2", install_date="2024-03-02"
    )
    set_clock(api, "2026-08-15T08:02:00Z")
    third = new_equipment(
        api, club_a["id"], model["id"], serial_number="SN-L-3", install_date="2024-03-03"
    )
    set_clock(api, "2026-08-15T08:03:00Z")
    elsewhere = new_equipment(
        api, club_b["id"], model["id"], serial_number="SN-L-9", install_date="2024-03-04"
    )

    filtered = api.list_equipment(admin, club_id=club_a["id"])
    rows, meta = validate_paginated(filtered)
    assert filtered.json()["response_type"] == "array"
    assert_pagination_meta(
        meta, limit=DEFAULT_LIMIT, offset=0, total_count=3, has_more=False
    )
    assert [row["id"] for row in rows] == [first["id"], second["id"], third["id"]]
    assert_created_at_ascending(rows)
    assert elsewhere["id"] not in [row["id"] for row in rows]

    paged = api.list_equipment(admin, club_id=club_a["id"], limit=2, offset=2)
    paged_rows, paged_meta = validate_paginated(paged)
    assert_pagination_meta(
        paged_meta, limit=2, offset=2, total_count=3, has_more=False
    )
    assert [row["id"] for row in paged_rows] == [third["id"]]


# ─── Path identifiers that name no row ────────────────────────────────────────

UNKNOWN_READ_PATHS = (
    ("get_club", ERR_CLUB_NOT_FOUND),
    ("get_equipment_model", ERR_MODEL_NOT_FOUND),
    ("get_contract", ERR_CONTRACT_NOT_FOUND),
    ("get_technician", ERR_TECHNICIAN_NOT_FOUND),
    ("get_renewal_quote", ERR_QUOTE_NOT_FOUND),
    ("get_technician_assignment", ERR_ASSIGNMENT_NOT_FOUND),
    ("get_downtime_event", ERR_DOWNTIME_EVENT_NOT_FOUND),
    ("get_part_order", ERR_PART_ORDER_NOT_FOUND),
)


@pytest.mark.parametrize("read_method, expected_error_id", UNKNOWN_READ_PATHS)
def test_unknown_id_on_a_single_row_read_path_returns_the_owning_entity_not_found(
    api, admin, read_method, expected_error_id
):
    """
    Each single-row read answers with the not-found code of its own entity, never a generic one.

    "`{clubId}` that matches no club yields `ERR_CLUB_NOT_FOUND`; `{modelId}` yields `ERR_MODEL_NOT_FOUND`; `{equipmentId}` yields `ERR_EQUIPMENT_NOT_FOUND`; `{contractId}` yields `ERR_CONTRACT_NOT_FOUND`; `{technicianId}` yields `ERR_TECHNICIAN_NOT_FOUND`; `{visitId}` yields `ERR_VISIT_NOT_FOUND`; `{callId}` yields `ERR_CALL_NOT_FOUND`; `{assignmentId}` yields `ERR_ASSIGNMENT_NOT_FOUND`; `{partId}` yields `ERR_PART_NOT_FOUND`; `{orderId}` yields `ERR_PART_ORDER_NOT_FOUND`; `{eventId}` yields `ERR_DOWNTIME_EVENT_NOT_FOUND`; and `{quoteId}` yields `ERR_QUOTE_NOT_FOUND`."
    "All twelve carry HTTP 404."

    Design: Corner/entities/unknown_ids_on_read_paths_return_the_owning_entity_not_found
    """
    response = getattr(api, read_method)(UNKNOWN_UUID, admin)
    validate_error(response, expected_error_id, 404)


UNKNOWN_ACTION_PATHS = (
    ("usage_reading", ERR_EQUIPMENT_NOT_FOUND),
    ("call_arrival", ERR_CALL_NOT_FOUND),
    ("visit_start", ERR_VISIT_NOT_FOUND),
    ("part_end_of_support", ERR_PART_NOT_FOUND),
)


@pytest.mark.parametrize("action, expected_error_id", UNKNOWN_ACTION_PATHS)
def test_unknown_id_on_an_action_path_returns_the_owning_entity_not_found(
    api, admin, planner, action, expected_error_id
):
    """
    An action endpoint addressed at an unknown identifier answers its own 404 even though the payload is well formed.

    "Path variables are resolved strictly left to right, and the first unresolvable variable decides the response."
    "An unresolvable body identifier produces the not-found code of the entity type it was supposed to name, with HTTP 404."

    Design: Corner/entities/unknown_ids_on_action_paths_return_the_owning_entity_not_found
    """
    set_clock(api, CLOCK)
    technician = new_technician(
        api, full_name="Dana Reyes", region_code=REGION_A, skill_categories=["TREADMILL"]
    )
    field_headers = technician_headers(technician["id"])

    probes = {
        "usage_reading": lambda: api.record_usage_reading(
            UNKNOWN_UUID, usage_reading_payload(5000), admin
        ),
        "call_arrival": lambda: api.arrive_service_call(UNKNOWN_UUID, field_headers),
        "visit_start": lambda: api.start_visit(UNKNOWN_UUID, field_headers),
        "part_end_of_support": lambda: api.declare_end_of_support(UNKNOWN_UUID, planner),
    }

    validate_error(probes[action](), expected_error_id, 404)

    # Nothing was brought into existence by a request that never resolved its target.
    for listing in (
        api.list_equipment(admin),
        api.list_service_calls(admin),
        api.list_preventive_visits(admin),
        api.list_parts(admin),
    ):
        rows, meta = validate_paginated(listing)
        assert rows == [] and meta["total_count"] == 0


# ─── Foreign keys travelling in the request body ──────────────────────────────


def test_unknown_body_foreign_keys_on_creation_paths_return_the_referenced_entity_not_found(
    api, admin, planner
):
    """
    An unknown model_id or club_id carried in a creation body answers the referenced entity's 404 and persists nothing.

    "Identifiers carried in a request *body* are resolved after the request shape has been validated, and they use the same catalogue of not-found codes: `club_id` resolves against clubs, `model_id` against equipment models, `equipment_id` against machines, `contract_id` against contracts, `technician_id` and `safety_clearance_technician_id` against technicians, and `part_id` against the parts catalogue."
    "An unresolvable body identifier produces the not-found code of the entity type it was supposed to name, with HTTP 404."

    Design: Corner/entities/foreign_key_targets_in_the_body_are_resolved_before_business_rules
    """
    set_clock(api, CLOCK)
    club = new_club(api, name="Northside Fitness", region_code=REGION_A)
    new_model(
        api,
        pm_interval_hours=PM_INTERVAL_HOURS,
        expected_service_life_hours=SERVICE_LIFE_HOURS,
        base_annual_service_cents=BASE_ANNUAL_SERVICE_CENTS,
    )

    unresolved_model = api.create_equipment(
        equipment_payload(
            club["id"], UNKNOWN_UUID, serial_number="SN-FK-BAD", install_date=INSTALL_DATE
        ),
        admin,
    )
    validate_error(unresolved_model, ERR_MODEL_NOT_FOUND, 404)

    unresolved_club = api.create_contract(
        contract_payload(
            UNKNOWN_UUID,
            coverage_tier="SILVER",
            parts_inclusion="WEAR_ONLY",
            pm_visits_per_year=2,
            annual_base_cents=100000,
            initial_parts_allowance_cents=0,
        ),
        admin,
    )
    validate_error(unresolved_club, ERR_CLUB_NOT_FOUND, 404)

    unresolved_part_model = api.create_part(
        part_payload(
            UNKNOWN_UUID,
            part_number="BELT-BAD",
            category="WEAR",
            unit_price_cents=1000,
        ),
        planner,
    )
    validate_error(unresolved_part_model, ERR_MODEL_NOT_FOUND, 404)

    for listing in (
        api.list_equipment(admin),
        api.list_contracts(admin),
        api.list_parts(admin),
    ):
        rows, meta = validate_paginated(listing)
        assert rows == [] and meta["total_count"] == 0


def test_unknown_body_foreign_keys_on_action_paths_are_resolved_before_business_rules(
    api, admin, coordinator
):
    """
    An unknown technician on a dispatch and an unknown part on a hold both answer the referenced entity's 404 and leave the call untouched.

    "Identifiers carried in a request *body* are resolved after the request shape has been validated, and they use the same catalogue of not-found codes: `club_id` resolves against clubs, `model_id` against equipment models, `equipment_id` against machines, `contract_id` against contracts, `technician_id` and `safety_clearance_technician_id` against technicians, and `part_id` against the parts catalogue."
    "This applies to machine registration, contract drafting, visit scheduling, call opening, call dispatch, parts holds, call resolution and part registration."

    Design: Corner/entities/foreign_key_targets_in_the_body_are_resolved_before_business_rules
    """
    set_clock(api, CLOCK)
    club = new_club(api, name="Northside Fitness", region_code=REGION_A)
    model = new_model(
        api,
        pm_interval_hours=PM_INTERVAL_HOURS,
        expected_service_life_hours=SERVICE_LIFE_HOURS,
        base_annual_service_cents=BASE_ANNUAL_SERVICE_CENTS,
    )
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-FK-1",
        install_date=INSTALL_DATE,
        initial_usage_hours=500,
    )
    contract = new_active_contract(
        api,
        club["id"],
        coverage_tier="GOLD",
        parts_inclusion="FULL",
        pm_visits_per_year=4,
        annual_base_cents=250000,
        initial_parts_allowance_cents=500000,
    )
    technician = new_technician(
        api, full_name="Dana Reyes", region_code=REGION_A, skill_categories=["TREADMILL"]
    )
    call = open_call(api, contract["id"], unit["id"], severity="MINOR")

    unresolved_technician = api.dispatch_service_call(
        call["id"], dispatch_payload(CLOCK, UNKNOWN_UUID), coordinator
    )
    validate_error(unresolved_technician, ERR_TECHNICIAN_NOT_FOUND, 404)
    assert_fields(read_call(api, call["id"]), status="OPEN")

    dispatch_call(api, call["id"], CLOCK, technician["id"])
    arrive_call(api, call["id"], technician["id"])

    unresolved_part = api.place_parts_hold(
        call["id"],
        parts_hold_payload(UNKNOWN_UUID, qty=1, source="NEW"),
        technician_headers(technician["id"]),
    )
    validate_error(unresolved_part, ERR_PART_NOT_FOUND, 404)

    assert_fields(read_call(api, call["id"]), status="ON_SITE", parts_hold_count=0)
    orders, order_meta = validate_paginated(api.list_part_orders(admin))
    assert orders == [] and order_meta["total_count"] == 0


# ─── Request shape at creation ────────────────────────────────────────────────


def test_contract_creation_without_a_coverage_tier_is_rejected_as_an_invalid_request(
    api, admin
):
    """
    Omitting the coverage tier from a contract draft is a shape failure, not a silently defaulted tier.

    "On every write endpoint, all required body fields must be present, every enum-typed field must hold one of its declared values, every field that is a count, an amount or a quantity must be non-negative where negativity is meaningless, `qty` must be at least 1, and every timestamp must parse as an ISO 8601 UTC instant."
    "A failure here is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/contract_create_missing_coverage_tier_returns_invalid_request
    """
    set_clock(api, CLOCK)
    club = new_club(api, name="Northside Fitness", region_code=REGION_A)

    payload = contract_payload(
        club["id"],
        parts_inclusion="FULL",
        pm_visits_per_year=4,
        annual_base_cents=250000,
        initial_parts_allowance_cents=500000,
    )
    del payload["coverage_tier"]

    validate_error(api.create_contract(payload, admin), ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_contracts(admin, club_id=club["id"]))
    assert rows == [] and meta["total_count"] == 0


def test_equipment_model_creation_with_an_undeclared_category_is_rejected_as_invalid_request(
    api, admin
):
    """
    A category outside the four declared equipment families is refused at shape validation and never stored.

    "A model carries a `manufacturer` (1 to 80 characters), a `model_code` (1 to 40 characters, unique within that manufacturer), a `category` drawn from `TREADMILL`, `ELLIPTICAL`, `BIKE` and `STRENGTH`, and a `model_year` between 1990 and 2100."
    "A failure here is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/model_create_with_unknown_category_enum_returns_invalid_request
    """
    payload = equipment_model_payload(
        model_code="RW-100",
        category="ROWER",
        model_year=2022,
        pm_interval_hours=300,
        expected_service_life_hours=12000,
        base_annual_service_cents=50000,
    )

    validate_error(api.create_equipment_model(payload, admin), ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_equipment_models(admin))
    assert rows == [] and meta["total_count"] == 0


# ─── Declared defaults on omitted optional inputs ─────────────────────────────


def test_technician_created_without_its_optional_inputs_takes_the_declared_defaults(
    api, admin
):
    """
    A technician registered without the credential or ceiling fields comes back on duty, uncertified and capped at the declared default.

    "Two optional fields shape what the technician is allowed to take on: `is_safety_inspector`, which defaults to `false` and marks the holder of the safety-inspector credential, and `max_committed_minutes`, which defaults to 480 — a standard eight-hour day — must be at least 1, and caps how much reserved work the technician may carry at once."
    "A newly registered technician starts `ON_DUTY` with `committed_minutes` at zero."

    Design: Corner/entities/technician_and_equipment_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(api, CLOCK)

    payload = technician_payload(
        full_name="Dana Reyes", region_code=REGION_A, skill_categories=["TREADMILL"]
    )
    assert "is_safety_inspector" not in payload, "the credential flag must be omitted"
    assert "max_committed_minutes" not in payload, "the minute ceiling must be omitted"

    technician = validate_success(api.create_technician(payload, admin), 201)

    expected = {
        "duty_status": "ON_DUTY",
        "is_safety_inspector": False,
        "max_committed_minutes": TECHNICIAN_DEFAULT_MAX_COMMITTED_MINUTES,
        "committed_minutes": 0,
    }
    assert_fields(technician, **expected)
    assert_common_fields(technician, expected_version=1)
    assert_fields(read_technician(api, technician["id"]), **expected)


def test_equipment_created_without_initial_usage_hours_starts_at_a_zero_meter(
    api, admin
):
    """
    A unit registered without an opening meter reading starts at zero hours with its PM baseline at zero too.

    "On registration, `usage_hours` and `usage_hours_at_last_pm` are both seeded to `initial_usage_hours` (zero when the field is omitted), `pm_status` reads `OK`, `lifecycle_status` reads `IN_SERVICE`, `support_status` reads `SUPPORTED`, `downtime_minutes_ytd` is zero, `loaner_active` is `false`, and `eos_notified_at`, `last_safety_clearance_at` and `safety_lockout_reason` are all null."
    "`covered_unit_count` is the number of machines whose `club_id` names that club, counted across every `lifecycle_status` — a machine that is `DOWN` or `TAGGED_OUT` still counts as covered."

    Design: Corner/entities/technician_and_equipment_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(api, CLOCK)
    club = new_club(api, name="Northside Fitness", region_code=REGION_A)
    model = new_model(
        api,
        pm_interval_hours=PM_INTERVAL_HOURS,
        expected_service_life_hours=SERVICE_LIFE_HOURS,
        base_annual_service_cents=BASE_ANNUAL_SERVICE_CENTS,
    )

    payload = equipment_payload(
        club["id"], model["id"], serial_number="SN-DEF-1", install_date=INSTALL_DATE
    )
    assert "initial_usage_hours" not in payload, "the opening meter must be omitted"

    unit = validate_success(api.create_equipment(payload, admin), 201)

    assert_two_decimals(unit["usage_hours"], Decimal("0.00"), "usage_hours")
    assert_two_decimals(
        unit["usage_hours_at_last_pm"], Decimal("0.00"), "usage_hours_at_last_pm"
    )
    assert_fields(
        unit,
        pm_status="OK",
        lifecycle_status="IN_SERVICE",
        support_status="SUPPORTED",
        health_score_variant="USAGE_BASED",
    )
    assert_two_decimals(
        unit["health_score"],
        _usage_based_health_score(0, SERVICE_LIFE_HOURS, AGE_YEARS_AT_CLOCK),
        "health_score",
    )
    assert_fields(read_club(api, club["id"]), covered_unit_count=1)


# ─── Values derived at creation ───────────────────────────────────────────────


def test_contract_creation_derives_the_sla_window_and_credit_cap_from_the_tier_tables(
    api, admin
):
    """
    Drafting pins the tier's arrival window and the fifteen-percent credit ceiling, and starts every counter at zero.

    "`sla_response_minutes`, the contractual arrival window, is taken from the tier at this moment: eight hours (480 minutes) on `BRONZE`, four hours (240 minutes) on `SILVER`, two hours (120 minutes) on `GOLD`."
    "`credit_cap_cents`, the hard ceiling on credit the club can earn across the whole term, is fifteen percent of `annual_base_cents`, rounded half up to whole cents."

    Design: Corner/entities/contract_creation_derives_sla_and_credit_cap_from_the_tier_tables
    """
    set_clock(api, CLOCK)
    club = new_club(api, name="Northside Fitness", region_code=REGION_A)

    annual_base_cents = 250000
    opening_allowance_cents = 500000
    response = api.create_contract(
        contract_payload(
            club["id"],
            coverage_tier="GOLD",
            parts_inclusion="FULL",
            pm_visits_per_year=4,
            annual_base_cents=annual_base_cents,
            initial_parts_allowance_cents=opening_allowance_cents,
            term_start_date="2026-01-01",
            term_end_date="2026-12-31",
        ),
        admin,
    )
    contract = validate_success(response, 201)

    assert_fields(
        contract,
        status="DRAFT",
        coverage_tier="GOLD",
        parts_inclusion="FULL",
        sla_response_minutes=SLA_RESPONSE_MINUTES["GOLD"],
        pm_visits_completed_count=0,
        pm_visits_missed_count=0,
        obsolete_unit_count=0,
        replacement_candidate_count=0,
        fleet_renewal_risk="LOW",
    )
    assert_money(
        contract["credit_cap_cents"],
        round_half_up_cents(Decimal(annual_base_cents) * CREDIT_CAP_PCT),
        "credit_cap_cents",
    )
    assert_money(
        contract["parts_allowance_total_cents"],
        opening_allowance_cents,
        "parts_allowance_total_cents",
    )
    assert_money(
        contract["parts_allowance_remaining_cents"],
        opening_allowance_cents,
        "parts_allowance_remaining_cents",
    )
    assert_money(contract["credit_provisional_cents"], 0, "credit_provisional_cents")
    assert_money(contract["credit_accrued_cents"], 0, "credit_accrued_cents")
    assert_money(contract["credit_forgone_cents"], 0, "credit_forgone_cents")
    assert_two_decimals(
        contract["pm_compliance_pct"], Decimal("100.00"), "pm_compliance_pct"
    )
    assert_null_fields(contract, "last_reconciled_period_key", "suspension_reason")
    assert_common_fields(contract, expected_version=1)


# ─── The four system-owned common properties ──────────────────────────────────


def test_creation_generates_the_system_fields_and_stamps_them_from_the_logical_clock(
    api, admin
):
    """
    Two clubs and a technician created in sequence each get their own identifier, a version of 1 and clock-stamped timestamps.

    "`created_at` is the ISO 8601 UTC instant at which the row was inserted, rendered with exactly three fractional-second digits and a trailing `Z`."
    "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row, again including cascaded mutations."

    Design: Corner/entities/system_fields_are_generated_and_client_supplied_values_are_ignored
    """
    set_clock(api, CLOCK)

    first_response = api.create_club(
        club_payload(name="Northside Fitness", region_code=REGION_A), admin
    )
    second_response = api.create_club(
        club_payload(name="Southside Fitness", region_code=REGION_B), admin
    )
    technician_response = api.create_technician(
        technician_payload(
            full_name="Dana Reyes", region_code=REGION_A, skill_categories=["TREADMILL"]
        ),
        admin,
    )

    rows = []
    for response in (first_response, second_response, technician_response):
        rows.append(validate_success(response, 201))
        assert_envelope_meta(response.json())

    identifiers = [row["id"] for row in rows]
    assert len(set(identifiers)) == 3, f"identifiers must be distinct: {identifiers}"

    for row in rows:
        assert_common_fields(row, expected_version=1)
        assert_instant(row["created_at"], CLOCK, "created_at")
        assert_instant(row["updated_at"], CLOCK, "updated_at")


def test_client_supplied_system_field_values_are_ignored_at_creation(api, admin):
    """
    A creation body that tries to dictate the identifier, timestamps and version is ignored in favour of the server's own values.

    "`id` is a server-minted UUID."
    "It carries no type prefix and no client-supplied component; a client-provided identifier in a creation payload is ignored."

    Design: Corner/entities/system_fields_are_generated_and_client_supplied_values_are_ignored
    """
    set_clock(api, CLOCK)

    client_identifier = "11111111-1111-4111-8111-111111111111"
    club = validate_success(
        api.create_club(
            club_payload(
                name="Northside Fitness",
                region_code=REGION_A,
                id=client_identifier,
                created_at="2020-01-01T00:00:00Z",
                updated_at="2020-01-01T00:00:00Z",
                version=99,
            ),
            admin,
        ),
        201,
    )

    assert club["id"] != client_identifier, (
        "the client-supplied identifier must be ignored"
    )
    assert_common_fields(club, expected_version=1)
    assert_instant(club["created_at"], CLOCK, "created_at")
    assert_instant(club["updated_at"], CLOCK, "updated_at")

    validate_error(api.get_club(client_identifier, admin), ERR_CLUB_NOT_FOUND, 404)
    assert_fields(
        read_club(api, club["id"]), name="Northside Fitness", region_code=REGION_A
    )
