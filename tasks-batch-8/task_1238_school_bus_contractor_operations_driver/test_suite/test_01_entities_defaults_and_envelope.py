"""Entity creation defaults, system-managed fields, envelope shape, pagination."""
import re

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_active_contract,
    create_contract,
    create_district,
    create_driver_applicant,
    create_driver_payload,
    create_route,
    create_route_payload,
    get_day_assignments,
    get_success_data,
    is_valid_uuid,
    log_training,
    setup_ops_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPS, HR, SYSADMIN

ISO_3FRAC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class TestDistrictDefaults:
    def test_create_district_defaults_applied(self, api):
        """PRD section 3.1: "A `SystemAdmin` creates one with a display `name`,
        a `region_fuel_index_code` identifying which fuel price index governs its
        escalation clauses, a `credit_limit_cents` bounding the district's
        outstanding billed balance, and an optional `billing_dispute_window_days`
        that defaults to 30 when omitted."
        PRD section 3.1: "A district's `status` is `ACTIVE` — version 1 has no
        district suspension lifecycle — and its `outstanding_balance_cents` is a
        computed figure, derived from its invoices as described in §3.7, starting
        at zero."

        Design: Corner/entities/create_district_defaults_applied
        """
        resp = api.create_district(
            {"name": "D-ENT1", "region_fuel_index_code": "WEST",
             "credit_limit_cents": 5000000},
            SYSADMIN)
        district = validate_success(resp, 201)
        assert district["billing_dispute_window_days"] == 30
        assert district["status"] == "ACTIVE"
        assert district["outstanding_balance_cents"] == 0

        fetched = validate_success(api.get_district(district["id"], SYSADMIN))
        assert fetched["billing_dispute_window_days"] == 30
        assert fetched["status"] == "ACTIVE"
        assert fetched["outstanding_balance_cents"] == 0


class TestSystemFieldsOnCreate:
    def test_system_fields_generated_on_create(self, api):
        """PRD section 2.4: "Every primary resource — District, Contract, Route,
        Driver, Credential, Bus, Inspection, WorkOrder, ServiceDay, Assignment,
        CharterTrip, Invoice, and Incident — carries four system-managed fields:
        `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601
        UTC timestamp with three fractional digits recorded at creation;
        `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation;
        and `version`, an integer that starts at its initial value and
        increments by one on every mutation, including system-driven
        mutations caused by cascades and clock advancement."
        PRD section 3.1: "A `ContractorOps` manager bids on district work by
        creating a Contract, which is born in `DRAFT_BID` with `amendment_seq` at
        zero."

        Design: Corner/entities/system_fields_generated_on_create
        """
        district = create_district(name="D-ENT2")
        contract = validate_success(
            api.create_contract(
                {"district_id": district["id"], "bid_reference": "BID-SYS",
                 "daily_rate_per_bus_cents": 50000, "school_days_per_year": 180,
                 "fuel_base_price_cents": 400, "penalty_mode": "FLAT_PER_ROUTE",
                 "shortage_penalty_flat_cents": 15000,
                 "shortage_penalty_per_student_minute_cents": 25,
                 "assumed_minutes_per_missed_route": 45, "monthly_cap_cents": 10000000,
                 "charter_hourly_rate_cents": 12000, "charter_per_mile_cents": 250,
                 "start_date": "2026-01-01", "end_date": "2026-12-31"},
                OPS),
            201)
        assert is_valid_uuid(contract["id"]), "id must be a server-minted UUID"
        assert not contract["id"].startswith("contract"), "id carries no type prefix"
        assert ISO_3FRAC_Z.match(contract["created_at"]), (
            f"created_at must be ISO 8601 UTC with three fractional digits, "
            f"got {contract['created_at']!r}")
        assert isinstance(contract["version"], int), "version is an integer"
        assert contract["status"] == "DRAFT_BID"
        assert contract["amendment_seq"] == 0


class TestNotFound:
    def test_get_contract_not_found_returns_404(self, api):
        """PRD section 2.8: "4. **Existence.** Path identifiers are resolved
        first, then body foreign-key references — `contract_id`, `district_id`,
        `driver_id`, `bus_id`, `route_id`, `assignment_id`, and the
        uncovered/absorbing assignment identifiers of a doubling decision —
        validated left to right; the first missing reference yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_contract_not_found_returns_404
        """
        resp = api.get_contract(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestRequiredFields:
    def test_create_driver_missing_required_field_returns_invalid_request(self, api):
        """PRD section 2.8: "1. **Schema and format.** The body parses, required
        fields are present, enum values are valid, and integers are in range;
        violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD section 3.3: "An `HRRecruiter` onboards a driver by creating the
        record with `primary_district_id` — the district the driver is
        credentialed for — plus `full_name`, `license_number`, `license_class`
        (`A` or `B`; school bus dispatch requires `B`), and `hourly_wage_cents`."

        Design: Corner/entities/create_driver_missing_required_field_returns_invalid_request
        """
        district = create_district(name="D-ENT4")
        payload = create_driver_payload(district["id"], full_name="No License")
        del payload["license_number"]
        resp = api.create_driver(payload, HR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestRouteTimeRange:
    def test_create_route_inverted_time_range_returns_422(self, api):
        """PRD section 3.2: "plus the `school_site` served, the planned AM run
        window as `am_start_minute` and `am_end_minute` in minutes since midnight
        (the end must be strictly after the start, else `ERR_INVALID_TIME_RANGE`),
        and the `student_count` of assigned riders."

        Design: Corner/entities/create_route_inverted_time_range_returns_422
        """
        district = create_district(name="D-ENT5")
        contract = create_active_contract(district["id"], bid_reference="BID-E5")
        resp = api.create_route(
            create_route_payload(contract["id"], route_code="RBAD",
                                 am_start_minute=480, am_end_minute=480),
            OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE, 422)


class TestAppendOnlyTrainingEvent:
    def test_immutable_training_event_has_no_update_path(self, api):
        """PRD section 2.4: "Three resources are append-only and carry only `id`
        and `created_at` — both `updated_at` and `version` are absent on them:
        TrainingEvent, FuelPriceEntry, and RidershipReport. Once written, they
        are never modified."

        Design: Corner/entities/immutable_training_event_has_no_update_path
        """
        district = create_district(name="D-ENT6")
        driver = create_driver_applicant(district["id"], full_name="D Imm",
                                         license_number="L210")
        event = validate_success(
            api.create_training_event(
                {"driver_id": driver["id"], "category": "SAFETY", "minutes": 60,
                 "occurred_on": "2026-04-01"},
                HR),
            201)
        assert "version" not in event, "append-only resource must not carry version"
        assert "updated_at" not in event, "append-only resource must not carry updated_at"

        fetched = validate_success(api.get_training_event(event["id"], HR))
        assert fetched["minutes"] == 60
        assert "version" not in fetched
        assert "updated_at" not in fetched


class TestComputedDriverMinutes:
    def test_computed_driver_minutes_aggregation(self, api):
        """PRD section 3.3: "Training hours accumulate through append-only
        TrainingEvents, each logging a `driver_id`, a `category` of `CLASSROOM`,
        `BEHIND_WHEEL`, or `SAFETY`, a positive `minutes` duration, and the
        `occurred_on` date; every logged event recomputes the driver's
        aggregates, with `behind_wheel_minutes` summing only `BEHIND_WHEEL`
        events and `classroom_minutes` summing only `CLASSROOM` events —
        `SAFETY` minutes count toward neither."

        Design: Corner/entities/computed_driver_minutes_aggregation
        """
        district = create_district(name="D-ENT7")
        driver = create_driver_applicant(district["id"], full_name="D Agg",
                                         license_number="L211")
        log_training(driver["id"], "BEHIND_WHEEL", 1000, occurred_on="2026-04-01")
        log_training(driver["id"], "BEHIND_WHEEL", 1400, occurred_on="2026-04-02")
        log_training(driver["id"], "CLASSROOM", 1200, occurred_on="2026-04-03")
        log_training(driver["id"], "SAFETY", 300, occurred_on="2026-04-04")

        fetched = validate_success(api.get_driver(driver["id"], HR))
        assert fetched["behind_wheel_minutes"] == 2400  # 1000 + 1400
        assert fetched["classroom_minutes"] == 1200
        # SAFETY minutes count toward neither aggregate.
        assert fetched["behind_wheel_minutes"] + fetched["classroom_minutes"] == 3600


class TestServiceDayCreationSpawnsAssignments:
    def test_service_day_creation_spawns_planned_assignments(self, api):
        """PRD section 3.2: "Creation does real work: the day is born
        `SCHEDULED`, its `required_routes` is computed as the count of the
        contract's routes that are `ACTIVE` at that moment (suspended routes do
        not count), and one `PLANNED` assignment is auto-created per active route
        with `planned_start_minute` and `planned_end_minute` copied from the
        route's AM window."
        PRD section 3.2: "From then on the system maintains `covered_routes` —
        assignments of the day with a `driver_id` set and status `CONFIRMED`,
        `EN_ROUTE`, or `COMPLETED` — and `uncovered_routes` as the required count
        minus the covered count, with `shortage_flag` true exactly when anything
        is uncovered."

        Design: Corner/entities/service_day_creation_spawns_planned_assignments
        """
        ctx = setup_ops_scenario(
            district_name="D-ENT8",
            routes=[(420, 480, 40), (480, 540, 30), (600, 660, 20)],
            with_driver=False, with_bus=False)
        suspended = validate_success(
            api.deactivate_route(ctx["routes"][2]["id"], {}, OPS))
        assert suspended["status"] == "SUSPENDED"

        day = validate_success(
            api.create_service_day(
                {"contract_id": ctx["contract"]["id"], "service_date": "2026-06-01"},
                OPS),
            201)
        assert day["status"] == "SCHEDULED"
        assert day["required_routes"] == 2  # SUSPENDED route excluded
        assert day["covered_routes"] == 0
        assert day["uncovered_routes"] == 2
        assert day["shortage_flag"] is True

        assignments = get_day_assignments(day["id"])
        assert len(assignments) == 2
        assert assignments[0]["status"] == "PLANNED"
        assert assignments[0]["planned_start_minute"] == 420
        assert assignments[0]["planned_end_minute"] == 480
        assert assignments[1]["status"] == "PLANNED"
        assert assignments[1]["planned_start_minute"] == 480


class TestForeignKeyIntegrity:
    def test_fk_integrity_route_unknown_contract_returns_not_found(self, api):
        """PRD section 2.8: "4. **Existence.** Path identifiers are resolved
        first, then body foreign-key references — `contract_id`, `district_id`,
        `driver_id`, `bus_id`, `route_id`, `assignment_id`, and the
        uncovered/absorbing assignment identifiers of a doubling decision —
        validated left to right; the first missing reference yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/fk_integrity_route_unknown_contract_returns_not_found
        """
        resp = api.create_route(
            create_route_payload(NON_EXISTENT_UUID, route_code="RX",
                                 school_site="Nowhere", student_count=10),
            OPS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestListPagination:
    def test_list_drivers_pagination_defaults_and_offsets(self, api):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter skips that many items from the front of the
        result set and defaults to 0."
        PRD section 2.3: "List responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_drivers_pagination_defaults_and_offsets
        """
        district = create_district(name="D-ENT10")
        for i in range(1, 13):
            create_driver_applicant(district["id"], full_name=f"D P{i:02d}",
                                    license_number=f"LP{i:02d}")

        page1_resp = api.list_drivers(HR, params={"primary_district_id": district["id"]})
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 10
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        # Envelope meta always carries the request identifiers.
        body1 = page1_resp.json()
        assert isinstance(body1["meta"].get("api_request_id"), str)
        assert isinstance(body1["meta"].get("api_request_timestamp"), str)

        page2, meta2 = validate_paginated(
            api.list_drivers(HR, params={"primary_district_id": district["id"],
                                         "limit": 10, "offset": 10}))
        assert len(page2) == 2
        assert meta2["offset"] == 10
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False
