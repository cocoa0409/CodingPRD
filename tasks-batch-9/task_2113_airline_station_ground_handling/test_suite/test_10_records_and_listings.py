"""Record shape, declared defaults, computed fields, the domain-specific
not-found codes and the filtered list channels."""
from test_helpers import (
    ApiErrorId,
    assert_pct,
    assert_station,
    assert_turn,
    create_agent,
    create_billing_period,
    create_certified_agent,
    create_flight_bank,
    create_gse_unit,
    create_open_station,
    create_station,
    create_turn,
    add_billing_line,
    add_gse_occupation,
    get_agent,
    get_billing_period,
    get_flight_bank,
    get_turn,
    issue_certification,
    make_contract_auditor_headers,
    make_duty_officer_headers,
    make_safety_officer_headers,
    make_station_manager_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_STATION_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
UNKNOWN_AGENT_ID = "11111111-2222-3333-4444-555555555555"


# ---------------------------------------------------------------------------
# Queue B: entities / station_create_applies_declared_defaults_and_system_fields
# ---------------------------------------------------------------------------

def test_station_registration_applies_every_declared_default(api):
    """PRD §3.1: "A freshly registered station lands in `PLANNED` with
    `oversight_posture` at `NORMAL`, `otp_rolling_pct` at 100.00, and
    `completed_turn_count`, `on_time_turn_count`, `open_critical_incident_count`
    and `open_major_incident_count` all at zero. Both `opened_at` and
    `closed_at` are null."
    PRD §3.1: "`otp_target_pct` is the contractual on-time-performance target,
    defaulting to 85.00, carried to two decimal places, and constrained to the
    range from 0.00 to 100.00 inclusive."
    PRD §3.1: "`penalty_cap_cents` is the largest combined penalty an invoice
    may carry before finalization is refused, defaulting to 5000000 cents, and
    may not be negative."
    PRD §2.4: "`version` (integer): starts at 1 when the record is created and
    increments by exactly 1 on every mutation of that record."

    Design: Corner/entities/station_create_applies_declared_defaults_and_system_fields
    """
    set_clock("2026-04-01T00:00:00Z")
    created = validate_success(api.create_station(
        {"iata_code": "ZRH", "name": "Zurich", "handler_code": "SWP",
         "season_code": "SUMMER"}, make_station_manager_headers()), 201)
    assert_station(created)
    assert created["status"] == "PLANNED"
    assert_pct(created["otp_target_pct"], 85.00, "otp_target_pct")
    assert created["otp_tolerance_minutes"] == 15
    assert created["gse_reposition_buffer_minutes"] == 20
    assert created["penalty_cap_cents"] == 5000000
    assert_pct(created["damage_penalty_multiplier"], 1.00,
               "damage_penalty_multiplier")
    assert created["oversight_posture"] == "NORMAL"
    assert_pct(created["otp_rolling_pct"], 100.00, "otp_rolling_pct")
    assert created["version"] == 1
    assert created["opened_at"] is None
    assert created["closed_at"] is None
    assert created["completed_turn_count"] == 0
    assert created["open_critical_incident_count"] == 0


# ---------------------------------------------------------------------------
# Queue B: entities / get_station_with_unknown_id_returns_station_not_found
# ---------------------------------------------------------------------------

def test_reading_an_unknown_station_returns_the_station_not_found_code(api):
    """PRD §2.4: "Every endpoint whose URL carries record identifiers resolves
    them strictly left to right, and the first identifier that does not resolve
    produces its own 404 immediately, before any later identifier or any body
    field is examined."
    PRD §2.4: "The eleven not-found codes are `ERR_STATION_NOT_FOUND`,
    `ERR_SUBCONTRACTOR_NOT_FOUND`, `ERR_FLIGHT_BANK_NOT_FOUND`,
    `ERR_TURN_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_GSE_UNIT_NOT_FOUND`, `ERR_TURN_RESOURCE_NOT_FOUND`,
    `ERR_INCIDENT_NOT_FOUND`, `ERR_BILLING_PERIOD_NOT_FOUND` and
    `ERR_BILLING_LINE_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/get_station_with_unknown_id_returns_station_not_found
    """
    set_clock("2026-04-01T00:00:00Z")
    resp = api.get_station(UNKNOWN_STATION_ID, make_station_manager_headers())
    validate_error(resp, ApiErrorId.ERR_STATION_NOT_FOUND, 404)


# ---------------------------------------------------------------------------
# Queue B: entities / station_list_honours_limit_and_offset_pagination
# ---------------------------------------------------------------------------

def test_station_list_paginates_and_orders_by_creation(api):
    """PRD §2.3: "`limit` sets the maximum number of records returned; it
    defaults to 10, may not be smaller than 1, and may not be larger than 100.
    `offset` sets how many records are skipped before the page begins; it
    defaults to 0."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count`
    counts the records that match the filters before pagination is applied."
    PRD §2.3: "Unless a specific endpoint says otherwise, list results are
    ordered by `created_at` ascending."

    Design: Corner/entities/station_list_honours_limit_and_offset_pagination
    """
    set_clock("2026-04-01T00:00:00Z")
    create_station(iata_code="ZRH", name="Zurich", handler_code="SWP")
    create_station(iata_code="GVA", name="Geneva", handler_code="SWP")
    create_station(iata_code="BSL", name="Basel", handler_code="MNZ")

    first_page, first_meta = validate_paginated(api.list_stations(
        make_contract_auditor_headers(), {"limit": 2, "offset": 0}))
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_page[0]["iata_code"] == "ZRH"

    second_page, second_meta = validate_paginated(api.list_stations(
        make_contract_auditor_headers(), {"limit": 2, "offset": 2}))
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_page[0]["iata_code"] == "BSL"


# ---------------------------------------------------------------------------
# Queue B: entities / create_turn_missing_required_turn_type_returns_invalid_request
# ---------------------------------------------------------------------------

def test_scheduling_a_turn_without_turn_type_is_rejected(api):
    """PRD §3.4: "A `DutyOfficer` schedules one inside a bank by supplying the
    `station_id`, the `flight_bank_id`, the carrier's `flight_number`, the
    `turn_type`, and the scheduled on-block and off-block instants
    `scheduled_in` and `scheduled_out`. All six are required."
    PRD §2.6: "Any violation is `ERR_INVALID_REQUEST` (400). Applies to every
    write endpoint."

    Design: Corner/entities/create_turn_missing_required_turn_type_returns_invalid_request
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)

    resp = api.create_turn(
        {"station_id": station["id"], "flight_bank_id": bank["id"],
         "flight_number": "LX318", "scheduled_in": "2026-04-10T06:00:00Z",
         "scheduled_out": "2026-04-10T06:20:00Z"},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    bank = get_flight_bank(bank["id"])
    assert bank["turn_count"] == 0
    assert bank["required_headcount"] == 0


# ---------------------------------------------------------------------------
# Queue B: entities / create_gse_unit_invalid_enum_gse_type_returns_invalid_request
# ---------------------------------------------------------------------------

def test_registering_equipment_with_an_undeclared_type_is_rejected(api):
    """PRD §3.6: "A `StationManager` registers each piece of equipment against
    a `station_id` with an `asset_tag` unique among that station's units and a
    `gse_type` drawn from `PUSHBACK_TUG`, `BELT_LOADER`, `GPU`, `DEICER` and
    `STAIRS`."
    PRD §2.6: "Every required body field is present; every enum field carries
    a declared member; every numeric field sits inside its declared range;
    `window_end` is strictly after `window_start`; an endorsement's
    `expires_at` is strictly after its `issued_at`; an incident's `occurred_at`
    is not after the current logical clock; an agent occupation carries
    `agent_id` and `role_on_turn` and carries neither `gse_unit_id` nor
    `gse_type`; an equipment occupation carries exactly one of `gse_unit_id` or
    `gse_type` and carries neither `agent_id` nor `role_on_turn`."
    PRD §2.6: "Any violation is `ERR_INVALID_REQUEST` (400). Applies to every
    write endpoint."

    Design: Corner/entities/create_gse_unit_invalid_enum_gse_type_returns_invalid_request
    """
    station = create_open_station()

    resp = api.create_gse_unit(
        {"station_id": station["id"], "asset_tag": "FL-01",
         "gse_type": "FORKLIFT"}, make_station_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


# ---------------------------------------------------------------------------
# Queue B: entities / turn_requirement_counts_are_computed_from_turn_type
# ---------------------------------------------------------------------------

def test_widebody_turn_publishes_its_requirement_counts_and_ground_time(api):
    """PRD §3.4: "A widebody needs 4 agents and 2 units, bills at 145000 cents,
    and is standard at 90 minutes."
    PRD §3.4: "The agent and equipment figures are published on the turnaround
    as `required_agent_count` and `required_gse_count`; the rate and the
    standard ground time surface later, in billing."
    PRD §3.4: "On creation the turnaround lands in `SCHEDULED` with
    `otp_result` at `PENDING`, `version` at 1, `assigned_agent_count` and
    `assigned_gse_count` at zero, and `billed` false."
    PRD §3.4: "Its `scheduled_ground_minutes` is the elapsed time from
    `scheduled_in` to `scheduled_out` expressed in whole minutes."

    Design: Corner/entities/turn_requirement_counts_are_computed_from_turn_type
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=0)

    turn = create_turn(station["id"], bank["id"], flight_number="LX16",
                       turn_type="WIDEBODY",
                       scheduled_in="2026-04-10T06:00:00Z",
                       scheduled_out="2026-04-10T07:30:00Z")
    assert_turn(turn)
    assert turn["required_agent_count"] == 4
    assert turn["required_gse_count"] == 2
    assert turn["scheduled_ground_minutes"] == 90
    assert turn["status"] == "SCHEDULED"
    assert turn["otp_result"] == "PENDING"
    assert turn["assigned_agent_count"] == 0
    assert turn["billed"] is False

    bank = get_flight_bank(bank["id"])
    assert bank["required_headcount"] == 4
    assert bank["turn_count"] == 1
    assert_pct(bank["staffing_coverage_pct"], 0.00, "staffing_coverage_pct")


# ---------------------------------------------------------------------------
# Queue B: entities / create_turn_resource_with_unknown_agent_id_returns_agent_not_found
# ---------------------------------------------------------------------------

def test_occupation_naming_an_unknown_agent_returns_agent_not_found(api):
    """PRD §2.6: "**Body foreign keys.** Every foreign key supplied in the
    request body resolves to an existing record, otherwise the matching
    not-found code (404)."
    PRD §2.4: "The eleven not-found codes are `ERR_STATION_NOT_FOUND`,
    `ERR_SUBCONTRACTOR_NOT_FOUND`, `ERR_FLIGHT_BANK_NOT_FOUND`,
    `ERR_TURN_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_GSE_UNIT_NOT_FOUND`, `ERR_TURN_RESOURCE_NOT_FOUND`,
    `ERR_INCIDENT_NOT_FOUND`, `ERR_BILLING_PERIOD_NOT_FOUND` and
    `ERR_BILLING_LINE_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/create_turn_resource_with_unknown_agent_id_returns_agent_not_found
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])

    resp = api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "AGENT",
         "agent_id": UNKNOWN_AGENT_ID, "role_on_turn": "RAMP",
         "window_start": "2026-04-10T05:50:00Z",
         "window_end": "2026-04-10T06:30:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_AGENT_NOT_FOUND, 404)

    reread = get_turn(turn["id"])
    assert reread["assigned_agent_count"] == 0
    assert reread["version"] == turn["version"]


# ---------------------------------------------------------------------------
# Queue B: entities / certification_currency_state_is_expiring_within_thirty_days
# ---------------------------------------------------------------------------

def test_endorsement_expiring_within_thirty_days_reads_as_expiring(api):
    """PRD §3.5: "The published `currency_state` applies that primitive at the
    current logical clock: it reads `REVOKED` when the endorsement's `status`
    is `REVOKED`; otherwise `LAPSED` when the endorsement is not effective at
    the clock; otherwise `EXPIRING` when the time remaining from the clock to
    `expires_at` is 30 days or less; otherwise `CURRENT`."
    PRD §3.5: "An agent's `certification_posture` summarises the one
    endorsement the ramp cannot do without: it reads `LAPSED` when the agent
    holds no `RAMP_SAFETY` endorsement at their own station that is effective
    at the clock, `EXPIRING` when they hold one but it expires within 30 days,
    and `CURRENT` otherwise."

    Design: Corner/entities/certification_currency_state_is_expiring_within_thirty_days
    """
    station = create_open_station()
    agent = create_agent(station["id"])

    soon = issue_certification(agent["id"], station["id"],
                               expires_at="2026-04-20T00:00:00Z")
    assert soon["currency_state"] == "EXPIRING"
    assert get_agent(agent["id"])["certification_posture"] == "EXPIRING"

    far = issue_certification(agent["id"], station["id"], cert_type="PUSHBACK",
                              expires_at="2027-01-01T00:00:00Z")
    assert far["currency_state"] == "CURRENT"
    assert far["status"] == "VALID"

    rows, meta = validate_paginated(api.list_certifications(
        make_safety_officer_headers(),
        {"agent_id": agent["id"], "station_id": station["id"]}))
    assert meta["total_count"] == 2
    assert rows[0]["id"] == soon["id"]


# ---------------------------------------------------------------------------
# Queue B: entities / certification_expires_at_not_after_issued_at_is_rejected
# ---------------------------------------------------------------------------

def test_endorsement_expiring_at_its_issue_instant_is_rejected(api):
    """PRD §3.5: "Each names the `agent_id` it belongs to, the `station_id` it
    is valid at, the `cert_type`, and the effective window `issued_at` to
    `expires_at`, where `expires_at` must be strictly later than `issued_at`."
    PRD §2.6: "Any violation is `ERR_INVALID_REQUEST` (400). Applies to every
    write endpoint."

    Design: Corner/entities/certification_expires_at_not_after_issued_at_is_rejected
    """
    station = create_open_station()
    agent = create_agent(station["id"])

    resp = api.create_certification(
        {"agent_id": agent["id"], "station_id": station["id"],
         "cert_type": "RAMP_SAFETY", "issued_at": "2026-01-01T00:00:00Z",
         "expires_at": "2026-01-01T00:00:00Z"}, make_station_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert get_agent(agent["id"])["certification_posture"] == "LAPSED"


# ---------------------------------------------------------------------------
# Queue B: entities / turn_resource_agent_payload_missing_role_on_turn_is_rejected
# ---------------------------------------------------------------------------

def test_agent_occupation_without_a_ramp_role_is_a_shape_violation(api):
    """PRD §3.7: "An agent occupation carries `agent_id` and `role_on_turn` —
    the ramp role, one of `LEAD`, `RAMP`, `LOADER`, `PUSHBACK_OPERATOR` or
    `DEICER` — and must carry neither `gse_unit_id` nor `gse_type`."
    PRD §3.7: "Supplying both or neither of the equipment fields, or mixing
    fields across families, is a shape violation rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/turn_resource_agent_payload_missing_role_on_turn_is_rejected
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])

    resp = api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "window_start": "2026-04-10T05:50:00Z",
         "window_end": "2026-04-10T06:30:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 0


# ---------------------------------------------------------------------------
# Queue B: entities / turn_resources_reverse_lookup_by_gse_unit_id
# ---------------------------------------------------------------------------

def test_occupations_are_discoverable_by_the_unit_they_occupy(api):
    """PRD §2.3: "Resource occupations accept `turn_id`, `agent_id`,
    `gse_unit_id`, `status` and `resource_kind`."
    PRD §2.3: "Most list endpoints also accept domain filters, and where a
    filter is supplied it narrows the result set by exact match on that
    attribute."

    Design: Corner/entities/turn_resources_reverse_lookup_by_gse_unit_id
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    gse = create_gse_unit(station["id"])
    occupation = add_gse_occupation(turn["id"], gse_unit_id=gse["id"],
                                    window_start="2026-04-10T06:00:00Z",
                                    window_end="2026-04-10T06:20:00Z")

    rows, meta = validate_paginated(api.list_turn_resources(
        make_contract_auditor_headers(),
        {"gse_unit_id": gse["id"], "status": "RESERVED"}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == occupation["id"]
    assert rows[0]["resource_kind"] == "GSE"
    assert rows[0]["occupied_minutes"] == 20


# ---------------------------------------------------------------------------
# Queue B: endpoints / billing_lines_filtered_by_turn_id_and_period_id
# ---------------------------------------------------------------------------

def test_billing_lines_are_reachable_by_period_and_by_turn(api):
    """PRD §2.3: "Billing lines accept `billing_period_id`, `turn_id` and
    `status`."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count`
    counts the records that match the filters before pagination is applied."

    Design: Corner/endpoints/billing_lines_filtered_by_turn_id_and_period_id
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=2)
    first_turn = create_turn(station["id"], bank["id"], flight_number="LX801")
    second_turn = create_turn(station["id"], bank["id"], flight_number="LX802",
                              scheduled_in="2026-04-10T08:00:00Z",
                              scheduled_out="2026-04-10T08:20:00Z")
    period = create_billing_period(station["id"], period_code="2026-04")
    first_line = add_billing_line(period["id"], first_turn["id"])
    second_line = add_billing_line(period["id"], second_turn["id"])

    by_period, period_meta = validate_paginated(api.list_billing_lines(
        make_contract_auditor_headers(),
        {"billing_period_id": period["id"], "limit": 10, "offset": 0}))
    assert period_meta["total_count"] == 2
    assert period_meta["has_more"] is False
    assert len(by_period) == 2
    assert by_period[0]["id"] == first_line["id"]

    by_turn, turn_meta = validate_paginated(api.list_billing_lines(
        make_contract_auditor_headers(), {"turn_id": second_turn["id"]}))
    assert turn_meta["total_count"] == 1
    assert by_turn[0]["id"] == second_line["id"]
    assert by_turn[0]["net_amount_cents"] == 18000
    assert get_billing_period(period["id"])["accrued_cents"] == 36000


# ---------------------------------------------------------------------------
# Queue B: errors / every_path_parameter_not_found_error_is_triggerable
# ---------------------------------------------------------------------------

def test_each_single_record_read_has_its_own_not_found_code(api):
    """PRD §2.6: "**Path existence.** Every record named in the URL exists,
    validated left to right, otherwise the matching not-found code (404).
    Applies to every endpoint that carries a path identifier."
    PRD §2.4: "The eleven not-found codes are `ERR_STATION_NOT_FOUND`,
    `ERR_SUBCONTRACTOR_NOT_FOUND`, `ERR_FLIGHT_BANK_NOT_FOUND`,
    `ERR_TURN_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_GSE_UNIT_NOT_FOUND`, `ERR_TURN_RESOURCE_NOT_FOUND`,
    `ERR_INCIDENT_NOT_FOUND`, `ERR_BILLING_PERIOD_NOT_FOUND` and
    `ERR_BILLING_LINE_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/every_path_parameter_not_found_error_is_triggerable
    """
    set_clock("2026-04-01T00:00:00Z")
    headers = make_station_manager_headers()
    cases = [
        (api.get_subcontractor, "11111111-1111-1111-1111-111111111111",
         ApiErrorId.ERR_SUBCONTRACTOR_NOT_FOUND),
        (api.get_flight_bank, "22222222-2222-2222-2222-222222222222",
         ApiErrorId.ERR_FLIGHT_BANK_NOT_FOUND),
        (api.get_turn, "33333333-3333-3333-3333-333333333333",
         ApiErrorId.ERR_TURN_NOT_FOUND),
        (api.get_certification, "44444444-4444-4444-4444-444444444444",
         ApiErrorId.ERR_CERTIFICATION_NOT_FOUND),
        (api.get_gse_unit, "55555555-5555-5555-5555-555555555555",
         ApiErrorId.ERR_GSE_UNIT_NOT_FOUND),
        (api.get_turn_resource, "66666666-6666-6666-6666-666666666666",
         ApiErrorId.ERR_TURN_RESOURCE_NOT_FOUND),
        (api.get_incident, "77777777-7777-7777-7777-777777777777",
         ApiErrorId.ERR_INCIDENT_NOT_FOUND),
        (api.get_billing_period, "88888888-8888-8888-8888-888888888888",
         ApiErrorId.ERR_BILLING_PERIOD_NOT_FOUND),
        (api.get_billing_line, "99999999-9999-9999-9999-999999999999",
         ApiErrorId.ERR_BILLING_LINE_NOT_FOUND),
    ]
    for read, unknown_id, expected_error in cases:
        resp = read(unknown_id, headers)
        error = validate_error(resp, expected_error, 404)
        assert error["message"], f"{expected_error} must carry a message"


# ---------------------------------------------------------------------------
# Queue B: validations / duplicate_iata_code_returns_duplicate_code
# ---------------------------------------------------------------------------

def test_a_second_station_with_the_same_iata_code_is_refused(api):
    """PRD §3.1: "The registration carries the `iata_code` — exactly three
    characters, all uppercase letters A through Z, and unique across every
    station the system knows about — together with a human-readable `name` and
    the `handler_code` of the ground handling company operating the contract.
    An `iata_code` that already exists is refused with `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/duplicate_iata_code_returns_duplicate_code
    """
    set_clock("2026-04-01T00:00:00Z")
    original = create_station(iata_code="ZRH", name="Zurich", handler_code="SWP")

    resp = api.create_station(
        {"iata_code": "ZRH", "name": "Zurich Cargo", "handler_code": "MNZ",
         "season_code": "WINTER"}, make_station_manager_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE, 409)

    rows, meta = validate_paginated(api.list_stations(
        make_station_manager_headers(), {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == original["id"]
