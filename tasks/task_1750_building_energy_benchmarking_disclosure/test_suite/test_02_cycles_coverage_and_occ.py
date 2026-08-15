"""Cycle administration, the covered-building list, and optimistic concurrency (PRD §2.7, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_filing_cycle,
    create_and_open_cycle,
    create_building,
    create_cycle,
    create_owner,
    create_report,
    get_cycle,
    make_owner_headers,
    open_cycle,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestCycleOpenAndClose:
    def test_cycle_open_twice_rejected(self, api):
        """PRD §3.1: "Opening the cycle moves it `SCHEDULED → OPEN` and is valid only
        from `SCHEDULED`, otherwise `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/s_cycle_open_twice_rejected
        """
        cycle = create_and_open_cycle()
        resp = api.open_reporting_cycle(cycle["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        still = get_cycle(cycle["id"])
        assert still["status"] == "OPEN"

    def test_close_filing_at_exact_deadline_rejected(self, api):
        """PRD §3.1: "It requires the cycle to be `OPEN` and the logical clock to sit
        strictly later than `filing_deadline_at` — at exactly the deadline instant, or
        before it, the attempt fails with `ERR_CYCLE_NOT_CLOSABLE`."

        Design: Corner/validations/v_close_filing_before_deadline_rejected
        """
        cycle = create_and_open_cycle()
        set_clock("2027-06-01T00:00:00Z")
        resp = api.close_filing(cycle["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_CLOSABLE)
        still = get_cycle(cycle["id"])
        assert still["status"] == "OPEN"

    def test_cycle_patch_after_close_rejected(self, api):
        """PRD §3.1: "A cycle's configuration — the deadline, the fine rates, the
        weather factor, the performance standards, and the four optional thresholds —
        may be edited only while the cycle is `SCHEDULED` or `OPEN`; once filing has
        closed, the attempt is rejected with `ERR_CYCLE_NOT_EDITABLE`."

        The OCC version supplied here is current, so the temporal edit gate is the
        rule that fires.

        Design: Corner/validations/v_cycle_patch_after_close_returns_not_editable
        """
        cycle = create_and_open_cycle()
        close_filing_cycle(cycle["id"])
        current = get_cycle(cycle["id"])
        assert current["status"] == "FILING_CLOSED"
        resp = api.patch_reporting_cycle(
            cycle["id"],
            {"expected_cycle_version": current["version"], "late_fine_daily_rate_cents": 6000},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_EDITABLE)


class TestOptimisticConcurrency:
    def test_building_patch_with_stale_version_rejected(self, api):
        """PRD §2.7: "A request to update a building must carry
        `expected_building_version` equal to the building's current `version`; the
        field is required, not optional."
        PRD §2.7: "When the supplied value does not match the entity's current
        `version` — because the client is building on a stale read — the update is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/x_occ_building_patch_stale_version
        """
        owner = create_owner()
        building = create_building(owner["id"])
        stale_version = building["version"]

        first = validate_success(
            api.patch_building(
                building["id"],
                {"expected_building_version": stale_version, "address": "95 Main St (Suite A)"},
                make_owner_headers(owner["id"]),
            )
        )
        assert first["version"] == stale_version + 1

        resp = api.patch_building(
            building["id"],
            {"expected_building_version": stale_version, "address": "95 Main St (Suite B)"},
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_building(building["id"], OFFICER))
        assert after["address"] == "95 Main St (Suite A)", "stale write must not clobber"

    def test_cycle_patch_with_stale_version_rejected(self, api):
        """PRD §2.7: "A request to edit a reporting cycle's configuration must
        likewise carry `expected_cycle_version` equal to the cycle's current
        `version`."
        PRD §2.7: "When the supplied value does not match the entity's current
        `version` — because the client is building on a stale read — the update is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/x_occ_cycle_patch_stale_version
        """
        cycle = create_cycle(covered_property_types=["OFFICE"])
        stale_version = cycle["version"]

        first = validate_success(
            api.patch_reporting_cycle(
                cycle["id"],
                {"expected_cycle_version": stale_version, "late_fine_daily_rate_cents": 6000},
                OFFICER,
            )
        )
        assert first["version"] == stale_version + 1
        assert first["late_fine_daily_rate_cents"] == 6000

        resp = api.patch_reporting_cycle(
            cycle["id"],
            {"expected_cycle_version": stale_version, "late_fine_daily_rate_cents": 7000},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_cycle(cycle["id"])
        assert after["late_fine_daily_rate_cents"] == 6000

    def test_owner_cannot_patch_others_building(self, api):
        """PRD §2.1: "When `X-User-Role` is `BuildingOwner`, `X-User-ID` is the `id`
        of the acting `Owner`; ownership checks on any resource that references an
        owner or a building compare the building's `owner_id` to `X-User-ID`."
        PRD §2.1: "A failure of any of these entity-backed ownership checks is
        rejected with `ERR_NOT_RESOURCE_OWNER`."

        The correct current version is supplied, so only the ownership gate can fire.

        Design: Corner/validations/v_owner_cannot_patch_others_building
        """
        o1 = create_owner()
        o2 = create_owner()
        building = create_building(o2["id"])

        resp = api.patch_building(
            building["id"],
            {"expected_building_version": building["version"], "address": "60 Hijack St"},
            make_owner_headers(o1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        after = validate_success(api.get_building(building["id"], OFFICER))
        assert after["address"] == building["address"]


class TestReportCreationCycleGate:
    def test_report_create_rejected_while_cycle_scheduled(self, api):
        """PRD §3.5: "Creation requires the cycle to be `OPEN` — a cycle still in
        `SCHEDULED` rejects the request with `ERR_CYCLE_NOT_OPEN`"

        Design: Difficulty/cross_entity_state_dependency/report_creation_requires_cycle_open
        """
        owner = create_owner()
        cycle = create_cycle()  # never opened
        building = create_building(owner["id"])

        resp = api.create_benchmark_report(
            {"building_id": building["id"], "cycle_id": cycle["id"]},
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)

    def test_report_create_succeeds_once_cycle_open(self, api):
        """PRD §3.5: "Creation requires the cycle to be `OPEN` — a cycle still in
        `SCHEDULED` rejects the request with `ERR_CYCLE_NOT_OPEN`"
        PRD §3.5: "The new report starts in `DRAFT` with `revision_number` zero,
        `is_late` false, `days_late` zero"

        The identical create call succeeds unchanged once the cycle is OPEN.

        Design: Difficulty/cross_entity_state_dependency/report_creation_requires_cycle_open
        """
        owner = create_owner()
        cycle = create_cycle()
        building = create_building(owner["id"])
        open_cycle(cycle["id"])

        report = create_report(building["id"], cycle["id"], owner["id"])
        assert report["status"] == "DRAFT"
        assert report["revision_number"] == 0


class TestCoveredBuildingList:
    def _setup_coverage_trio(self):
        """One building at the threshold, one below, one of an uncovered type."""
        owner = create_owner()
        cycle = create_and_open_cycle()
        b_exact = create_building(owner["id"], address="16 Main St", gross_floor_area_sqft=25000)
        b_under = create_building(owner["id"], address="17 Main St", gross_floor_area_sqft=24999)
        b_industrial = create_building(
            owner["id"], address="18 Main St", gross_floor_area_sqft=60000, property_type="INDUSTRIAL"
        )
        return owner, cycle, b_exact, b_under, b_industrial

    def test_floor_area_at_threshold_appears_on_covered_list(self, api):
        """PRD §3.2: "its `gross_floor_area_sqft` is at least the cycle's
        `covered_floor_area_threshold_sqft` — the threshold is inclusive, so a
        building at exactly the threshold is covered; its `property_type` is among
        the cycle's `covered_property_types`"
        PRD §3.2: "Listing buildings with the `covered_in_cycle_id` query parameter
        applies this determination for the named cycle and returns exactly the
        covered list."

        Design: Difficulty/boundary_precision_check/floor_area_exactly_at_coverage_threshold
        """
        _owner, cycle, b_exact, _b_under, _b_ind = self._setup_coverage_trio()

        data, meta = validate_paginated(
            api.list_buildings(OFFICER, params={"covered_in_cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 1, "only the at-threshold OFFICE building is covered"
        assert data[0]["id"] == b_exact["id"]

    def test_below_threshold_and_uncovered_type_cannot_file(self, api):
        """PRD §3.5: "Creation requires the cycle to be `OPEN` — a cycle still in
        `SCHEDULED` rejects the request with `ERR_CYCLE_NOT_OPEN` — and requires the
        building to be on that cycle's covered list, else `ERR_BUILDING_NOT_COVERED`."

        24999 sqft misses the inclusive 25000 threshold; INDUSTRIAL is outside the
        cycle's covered property types. Both report creations fail identically.

        Design: Difficulty/boundary_precision_check/floor_area_exactly_at_coverage_threshold
        """
        owner, cycle, _b_exact, b_under, b_ind = self._setup_coverage_trio()

        for building in (b_under, b_ind):
            resp = api.create_benchmark_report(
                {"building_id": building["id"], "cycle_id": cycle["id"]},
                make_owner_headers(owner["id"]),
            )
            validate_error(resp, ApiErrorId.ERR_BUILDING_NOT_COVERED)

    def test_second_report_for_same_pair_rejected(self, api):
        """PRD §3.5: "One building files at most one report per cycle; a second
        creation for the same pair is refused with `ERR_DUPLICATE_REPORT`."

        Design: Corner/validations/v_duplicate_report_rejected
        """
        owner = create_owner()
        cycle = create_and_open_cycle()
        building = create_building(owner["id"])
        create_report(building["id"], cycle["id"], owner["id"])

        resp = api.create_benchmark_report(
            {"building_id": building["id"], "cycle_id": cycle["id"]},
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT)
