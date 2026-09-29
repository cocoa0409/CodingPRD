"""Sites of employment, the roster, statute rows and the logical clock."""

from test_helpers import (
    ALICE,
    BEN,
    CARLA,
    CLOCK_START_UTC,
    ELENA,
    OMAR,
    TEST_USERS,
    ApiErrorId,
    assert_employee,
    assert_site,
    assert_warn_rule,
    create_employee_payload,
    create_locked_plan,
    create_site,
    create_site_payload,
    decide,
    federal_rule_payload,
    generate_disclosure,
    is_iso8601_timestamp,
    is_valid_uuid,
    propose,
    read_employee,
    read_site,
    roster_import_payload,
    setup_site_with_roster,
    validate_error,
    validate_paginated,
    validate_success,
)

LEAD = TEST_USERS["lead_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_fresh_site_reports_every_counter_at_zero(api):
    """PRD 3.2: "Every counter on a fresh site starts at 0 — `roster_count`,
    `active_headcount`, `pending_separation_count`, `separated_count`,
    `federal_loss_count`, `state_loss_count` and `required_notice_days` — its
    `warn_trigger_status` starts at `NONE`, and its `window_start_date` starts
    null."

    Design: Corner/entities/get_site_returns_the_stored_entity_with_zeroed_counters
    """
    created = validate_success(
        api.create_site(create_site_payload(name="Austin Campus", state_code="TX"), LEAD),
        201,
    )

    site = validate_success(api.get_site(created["id"], COUNSEL))
    assert_site(site)
    assert site["name"] == "Austin Campus"
    assert site["state_code"] == "TX"
    assert site["is_single_site"] is True
    assert site["roster_count"] == 0
    assert site["active_headcount"] == 0
    assert site["pending_separation_count"] == 0
    assert site["separated_count"] == 0
    assert site["federal_loss_count"] == 0
    assert site["state_loss_count"] == 0
    assert site["required_notice_days"] == 0
    assert site["warn_trigger_status"] == "NONE"
    assert site["window_start_date"] is None


def test_is_single_site_defaults_to_true_when_the_flag_is_omitted(api):
    """PRD 3.2: "A `RestructuringLead` registers a site with a `name`, a
    two-letter `state_code` that selects which state mini-WARN rule governs it,
    and an optional `is_single_site` flag that defaults to true and records
    whether the location qualifies as a single site of employment for
    plant-closing analysis."

    Design: Corner/entities/site_is_single_site_defaults_to_true_when_omitted
    """
    site = validate_success(
        api.create_site({"name": "Austin Campus", "state_code": "TX"}, LEAD), 201
    )
    assert site["is_single_site"] is True
    assert read_site(site["id"])["is_single_site"] is True


def test_site_without_a_state_code_is_malformed(api):
    """PRD 2.6: "Request and query well-formedness — every required input field
    present, every enum value a declared member, integers and booleans correctly
    typed, `limit` between 1 and 100 inclusive, `offset` not negative, every
    `weight_pct` an integer, every criterion `score` an integer from 0 through
    100 inclusive, every date in `YYYY-MM-DD` form, and `state_code` exactly two
    uppercase letters; otherwise `ERR_INVALID_REQUEST` (400). Applies to every
    endpoint."

    Design: Corner/entities/create_site_without_state_code_returns_invalid_request
    """
    response = api.create_site({"name": "Austin Campus"}, LEAD)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400


def test_part_time_is_derived_at_the_twenty_hour_line(api):
    """PRD 3.2: "The derived `is_part_time` flag is true when the person's
    `weekly_hours` is below 20 hours per week and false otherwise — the same
    twenty-hour line the federal statute draws."
    PRD 3.2: "Each hire recomputes the site's `roster_count` and
    `active_headcount`."

    Design: Corner/entities/employee_is_part_time_computed_from_weekly_hours_boundary
    """
    site = create_site(name="Austin Campus", state_code="TX")

    part_timer = validate_success(
        api.create_employee(create_employee_payload(site["id"], ELENA), LEAD), 201
    )
    full_timer = validate_success(
        api.create_employee(create_employee_payload(site["id"], OMAR), LEAD), 201
    )

    assert part_timer["is_part_time"] is True, "16 weekly hours is below the 20-hour line"
    assert full_timer["is_part_time"] is False, "exactly 20 weekly hours is not below 20"
    assert part_timer["employment_status"] == "ACTIVE"
    assert full_timer["employment_status"] == "ACTIVE"

    site = read_site(site["id"])
    assert site["roster_count"] == 2
    assert site["active_headcount"] == 2


def test_new_hire_carries_server_minted_identity_and_declared_defaults(api):
    """PRD 2.4: "Every resource the API persists — reduction plans, sites,
    employees, selections, WARN rules, adverse-impact analyses, OWBPA
    disclosures, WARN notices, severance offers, and position restrictions —
    carries an `id` that is a server-minted UUID with no type prefix of any kind,
    and a `created_at` timestamp recorded as an ISO 8601 UTC string with three
    fractional-second digits."
    PRD 3.2: "On creation the person's `employment_status` is `ACTIVE`,
    `separation_date` is null, `age_at_separation` and `years_of_service` are
    null, `release_signed` is false, `benefit_continuation_status` is `NONE`,
    `benefit_subsidy_months` and `benefit_subsidy_cents` are 0, and
    `outplacement_tier` is `NONE`."
    PRD 2.4: "`version` is an integer that starts at 1 when the resource is
    created and increases by exactly 1 on every persisted mutation of that
    resource."

    Design: Corner/entities/employee_system_fields_are_server_minted_and_input_ignored
    """
    site = create_site(name="Austin Campus", state_code="TX")
    employee = validate_success(
        api.create_employee(create_employee_payload(site["id"], ALICE), LEAD), 201
    )

    assert_employee(employee)
    assert is_valid_uuid(employee["id"]), "id is a bare UUID with no type prefix"
    assert is_iso8601_timestamp(employee["created_at"])
    assert employee["version"] == 1
    assert employee["employment_status"] == "ACTIVE"
    assert employee["separation_date"] is None
    assert employee["age_at_separation"] is None
    assert employee["years_of_service"] is None
    assert employee["release_signed"] is False
    assert employee["benefit_continuation_status"] == "NONE"
    assert employee["benefit_subsidy_months"] == 0
    assert employee["benefit_subsidy_cents"] == 0
    assert employee["outplacement_tier"] == "NONE"


def test_unknown_demographic_code_is_malformed(api):
    """PRD 3.2: "Hiring one person onto a roster requires a `site_id` naming the
    site, a `full_name`, a `job_title`, a `birth_date`, a `hire_date`, an
    `annual_base_cents` figure that must be strictly greater than zero, a
    `weekly_hours` figure that may not be negative, a `demographic_code` drawn
    from `CLASS_A`, `CLASS_B` or `CLASS_C`, and an optional
    `monthly_premium_cents` recording the employer's group-health monthly
    premium for that person, which defaults to 90000 cents when omitted."
    PRD 2.6: "Request and query well-formedness — every required input field
    present, every enum value a declared member, integers and booleans correctly
    typed, `limit` between 1 and 100 inclusive, `offset` not negative, every
    `weight_pct` an integer, every criterion `score` an integer from 0 through
    100 inclusive, every date in `YYYY-MM-DD` form, and `state_code` exactly two
    uppercase letters; otherwise `ERR_INVALID_REQUEST` (400). Applies to every
    endpoint."

    Design: Corner/entities/create_employee_with_unknown_demographic_code_returns_invalid_request
    """
    site = create_site(name="Austin Campus", state_code="TX")

    response = api.create_employee(
        create_employee_payload(site["id"], ALICE, demographic_code="CLASS_D"), LEAD
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400
    assert read_site(site["id"])["roster_count"] == 0


def test_configured_statute_row_is_immutable_and_carries_no_revision_fields(api):
    """PRD 2.4: "The one exception is the `WarnRule` resource. A configured
    statute row is immutable once written, so it carries only `id` and
    `created_at` — it has neither an `updated_at` field nor a `version` field,
    and neither field appears in its representation."

    Design: Corner/entities/warn_rule_is_immutable_configuration_without_version_field
    """
    created = validate_success(
        api.create_warn_rule(federal_rule_payload(), ADMIN), 201
    )
    rule = validate_success(api.get_warn_rule(created["id"], COUNSEL))

    assert_warn_rule(rule)
    assert rule["rule_code"] == "FED-WARN-1988"
    assert "version" not in rule
    assert "updated_at" not in rule
    assert rule["window_days"] == 90
    assert rule["counts_part_time"] is False
    assert rule["min_service_days"] == 180


def test_roster_import_creates_every_entry_in_order_and_refreshes_the_site(api):
    """PRD 3.2: "A site-scoped roster import accepts an `entries` array, each
    element carrying the same per-person attributes described above, and creates
    one employee per entry in `ACTIVE` status. The response reports a
    `created_count` and an `employee_ids` array whose order matches the order in
    which the `entries` were supplied. As with single hires, the site's
    `roster_count` and `active_headcount` are recomputed afterwards."

    Design: Corner/endpoints/roster_import_creates_every_entry_and_refreshes_site_counters
    """
    site = create_site(name="Austin Campus", state_code="TX")

    response = api.roster_import(
        site["id"], roster_import_payload([ALICE, BEN, CARLA]), LEAD
    )
    result = validate_success(response, 201)
    assert result["created_count"] == 3

    ids = result["employee_ids"]
    assert len(ids) == 3
    assert read_employee(ids[0])["full_name"] == "Alice Nunez"
    assert read_employee(ids[2])["full_name"] == "Carla Reyes"

    refreshed = read_site(site["id"])
    assert refreshed["roster_count"] == 3
    assert refreshed["active_headcount"] == 3
    assert refreshed["pending_separation_count"] == 0

    rows, _meta = validate_paginated(
        api.list_employees(LEAD, params={"site_id": site["id"]})
    )
    assert len(rows) == 3


def test_employee_listing_paginates_over_a_three_person_roster(api):
    """PRD 2.3: "The `limit` parameter caps the number of records returned; when
    omitted it defaults to 10, its minimum accepted value is 1 and its maximum
    accepted value is 100."
    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is
    the number of records matching the request's filters before pagination is
    applied and `has_more` indicates whether records remain beyond the returned
    page."

    Design: Corner/entities/list_employees_paginates_with_total_count_and_has_more
    """
    site, employees = setup_site_with_roster((ALICE, BEN, CARLA), "TX")
    assert len(employees) == 3

    first_response = api.list_employees(
        LEAD, params={"site_id": site["id"], "limit": 2, "offset": 0}
    )
    first, first_meta = validate_paginated(first_response)
    assert len(first) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_response.json()["response_type"] == "array"

    second_response = api.list_employees(
        LEAD, params={"site_id": site["id"], "limit": 2, "offset": 2}
    )
    second, second_meta = validate_paginated(second_response)
    assert len(second) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_response.json()["response_type"] == "array"


def test_logical_clock_starts_at_the_declared_instant_and_moves_on_demand(api):
    """PRD 2.5: "On server startup the clock stands at exactly
    `2026-08-01T00:00:00.000Z`, and it never falls back to real time. A
    `SystemAdmin` moves it with the clock-setting operation at
    `POST /_clock/set_current_utc`, supplying the target instant as
    `to_iso8601`; the response reports the resulting `current_utc`."
    PRD 3.6: "The disclosure is persisted with `status` of `ATTACHED` and a
    `generated_utc` stamp from the logical clock."

    Design: Corner/endpoints/logical_clock_starts_at_the_declared_default_and_moves_on_demand
    """
    site, employees = setup_site_with_roster((ALICE, BEN), "TX")
    plan = create_locked_plan()
    selection = propose(plan["id"], employees[0]["id"])
    decide(selection["id"], "SELECT")

    disclosure = generate_disclosure(plan["id"])
    assert disclosure["generated_utc"] == CLOCK_START_UTC, (
        "before any clock-setting call the logical clock stands at the startup instant"
    )

    moved = validate_success(
        api.set_clock({"to_iso8601": "2026-09-10T12:00:00.000Z"}, ADMIN)
    )
    assert moved["current_utc"] == "2026-09-10T12:00:00.000Z"
