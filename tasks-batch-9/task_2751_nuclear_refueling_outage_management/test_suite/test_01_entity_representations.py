"""Entity representation coverage: persistence, retrieval, listing, defaults,
computed fields, immutability, type bounds and the reference graph."""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    ConstraintStatus,
    DoseDirection,
    DoseReason,
    OutageStatus,
    Priority,
    RwpStatus,
    SchedulePosture,
    AlaraPosture,
    StationUnit,
    WorkOrderOrigin,
    WorkOrderStatus,
    WorkOrderType,
    api_client,
    assert_outage,
    assert_pool_ledger_consistent,
    assert_priority_band_matches_score,
    assert_same_instant,
    assert_spent_fuel_pool,
    assert_system_timestamps,
    assert_work_order,
    create_outage_payload,
    create_rwp_payload,
    create_work_order_payload,
    given_approved_core_load_pattern,
    given_approved_work_order,
    given_outage,
    given_rad_area,
    given_schedule_activity,
    given_spent_fuel_pool,
    given_work_order,
    is_valid_uuid,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_rad_protection_manager_headers,
    make_rad_protection_planner_headers,
    make_reactor_engineer_headers,
    make_station_admin_headers,
    read_dose_rows,
    read_outage,
    read_pool,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    NON_EXISTENT_UUID,
)


class TestOutageCreation:
    def test_every_supplied_input_field_is_persisted_and_echoed(self):
        """A create that supplies all eight input fields returns 201 and echoes
        each one unchanged, while the computed fields open at their declared
        starting values.

        PRD 2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/entities/create_outage_persists_every_declared_input_field
        """
        set_clock(CLOCK_EPOCH)
        response = api_client.create_outage(
            create_outage_payload(
                station_unit=StationUnit.UNIT_1,
                designation="1R24",
                duration_target_hours=720,
                dose_budget_total_mrem=5000,
                cost_budget_usd=40000000,
                scope_freeze_at="2026-08-15T00:00:00.000Z",
                required_training_modules=6,
                required_badged_workers=2,
            ),
            make_station_admin_headers(),
        )
        outage = validate_success(response, 201)
        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"] is not None

        assert_outage(outage)
        assert outage["station_unit"] == StationUnit.UNIT_1
        assert outage["designation"] == "1R24"
        assert outage["duration_target_hours"] == pytest.approx(720, abs=0.01)
        assert outage["dose_budget_total_mrem"] == pytest.approx(5000, abs=0.01)
        assert outage["cost_budget_usd"] == pytest.approx(40000000, abs=0.01)
        assert outage["required_training_modules"] == 6
        assert outage["required_badged_workers"] == 2

        assert outage["status"] == OutageStatus.PLANNING
        assert outage["schedule_posture"] == SchedulePosture.ON_TRACK
        assert outage["alara_posture"] == AlaraPosture.NORMAL
        assert outage["dose_committed_mrem"] == pytest.approx(0.00, abs=0.01)
        assert outage["dose_budget_remaining_mrem"] == pytest.approx(5000.00, abs=0.01)
        assert outage["approved_scope_cost_usd"] == pytest.approx(0.00, abs=0.01)
        assert outage["badged_worker_count"] == 0
        assert outage["critical_path_activity_id"] is None
        assert outage["actual_duration_hours"] is None

    def test_optional_fields_fall_back_to_their_two_distinct_defaults(self):
        """Omitting both optional counts yields 4 training modules and 0 badged
        workers, so the two defaults are distinct values rather than a shared
        zero or null.

        PRD 3.2: "`required_training_modules`, the number of outage-specific
        training modules a supplemental worker must complete, which must be at
        least zero and defaults to 4; and `required_badged_workers`, the badged
        headcount the outage must muster before the breaker may be opened, which
        must be at least zero and defaults to 0."

        Design: Corner/entities/outage_optional_fields_take_declared_defaults_when_omitted
        """
        set_clock(CLOCK_EPOCH)
        payload = create_outage_payload(designation="1R24")
        assert "required_training_modules" not in payload
        assert "required_badged_workers" not in payload

        outage = validate_success(
            api_client.create_outage(payload, make_station_admin_headers()), 201
        )
        assert outage["required_training_modules"] == 4
        assert outage["required_badged_workers"] == 0
        assert outage["status"] == OutageStatus.PLANNING
        assert outage["version"] == 1

    def test_reading_the_outage_back_returns_the_stored_values_unchanged(self):
        """A GET returns the same target figures the create persisted and leaves
        the version where it was.

        PRD 2.4: "`version`, an integer that starts at 1 when the row is created
        and increases by exactly 1 on every mutation of that row."

        Design: Corner/entities/get_outage_returns_the_stored_entity
        """
        set_clock(CLOCK_EPOCH)
        created = given_outage(designation="1R24")

        fetched = validate_success(
            api_client.get_outage(created["id"], make_outage_director_headers())
        )
        assert fetched["id"] == created["id"]
        assert fetched["duration_target_hours"] == pytest.approx(720, abs=0.01)
        assert fetched["dose_budget_total_mrem"] == pytest.approx(5000, abs=0.01)
        assert fetched["status"] == OutageStatus.PLANNING
        assert fetched["version"] == created["version"], "a read never bumps the version"


class TestWorkOrderListing:
    def test_two_pages_partition_the_three_rows_and_report_the_total(self):
        """With three work orders on one outage a two-row page reports
        total_count 3 and has_more true, the second page reports has_more false,
        and the two pages together cover every row exactly once.

        PRD 2.3: "the `meta` object of the success envelope carries `limit`,
        `offset`, `total_count` and `has_more`, where `total_count` is the number
        of rows matching the filters before pagination is applied and `has_more`
        is true exactly when rows matching the filters remain beyond the returned
        page."

        Design: Corner/entities/list_work_orders_paginates_with_total_count_and_has_more
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")
        ids = [
            given_work_order(outage["id"], title=title)["id"]
            for title in ("WO one", "WO two", "WO three")
        ]

        first_rows, first_meta = validate_paginated(
            api_client.list_work_orders(
                make_outage_planner_headers(), outage_id=outage["id"], limit=2, offset=0
            )
        )
        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_rows, second_meta = validate_paginated(
            api_client.list_work_orders(
                make_outage_planner_headers(), outage_id=outage["id"], limit=2, offset=2
            )
        )
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2

        seen = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
        assert len(seen) == len(set(seen)), "no row may appear on both pages"
        assert set(seen) == set(ids)

    def test_omitting_both_parameters_applies_the_declared_defaults(self):
        """Left to itself the endpoint serves all three rows under limit 10 and
        offset 0.

        PRD 2.3: "`limit` controls page size: it defaults to 10, its minimum
        accepted value is 1 and its maximum accepted value is 100. `offset`
        controls how many rows are skipped before the page begins: it defaults to
        0 and its minimum accepted value is 0."

        Design: Corner/entities/list_work_orders_paginates_with_total_count_and_has_more
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")
        for title in ("WO one", "WO two", "WO three"):
            given_work_order(outage["id"], title=title)

        rows, meta = validate_paginated(
            api_client.list_work_orders(
                make_outage_planner_headers(), outage_id=outage["id"]
            )
        )
        assert len(rows) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestNotFoundAndRequiredFields:
    def test_an_unknown_outage_id_is_a_not_found_rather_than_an_empty_success(self):
        """Reading a well-formed id that names no row is a 404, and the outage
        that does exist is unaffected.

        PRD 2.6: "The leftmost identifier is resolved first, and if it names no
        stored row the request fails immediately with that resource's own
        not-found code; only then is the next segment considered."

        Design: Corner/entities/get_outage_with_unknown_id_returns_outage_not_found
        """
        set_clock(CLOCK_EPOCH)
        existing = given_outage(designation="1R24")

        response = api_client.get_outage(NON_EXISTENT_UUID, make_outage_director_headers())
        validate_error(response, ApiErrorId.OUTAGE_NOT_FOUND.value)
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["message"]

        validate_success(
            api_client.get_outage(existing["id"], make_outage_director_headers())
        )

    def test_a_work_order_without_estimated_hours_is_refused_and_persists_nothing(self):
        """estimated_hours has no default, so omitting it is a request-shape
        violation and the outage's scope roll-up stays at zero.

        PRD 2.8: "Request shape: every required body field present, every value of
        its declared type, every enumerated value a declared member, no unknown
        fields, and every numeric within its declared bound (a permit's
        `worker_count` at least 1, a reservation's `cells_requested` at least 1, a
        permit's `shielding_factor` between 0 and 0.95 inclusive,
        `planned_duration_hours` strictly greater than zero, a startup test's
        `sequence_index` at least 1, and no negative money, hours or dose) —
        otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_work_order_without_estimated_hours_rejected
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")

        payload = create_work_order_payload(title="Missing hours")
        payload.pop("estimated_hours")
        response = api_client.create_work_order(
            outage["id"], payload, make_outage_planner_headers()
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        rows, meta = validate_paginated(
            api_client.list_work_orders(
                make_outage_planner_headers(), outage_id=outage["id"]
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert read_outage(outage["id"])["approved_scope_cost_usd"] == pytest.approx(
            0.00, abs=0.01
        )

    def test_the_nested_path_parent_is_resolved_before_the_body_is_considered(self):
        """An entirely valid body posted beneath an unknown outage id yields the
        outage's own not-found code and leaks nothing onto the real outage.

        PRD 2.8: "Path resolution: every identifier embedded in the request path
        resolves to a stored row, validated left to right — otherwise the matching
        404 code from §2.6."

        Design: Corner/entities/work_order_creation_requires_an_existing_parent_outage
        """
        set_clock(CLOCK_EPOCH)
        real = given_outage(designation="1R24")

        response = api_client.create_work_order(
            NON_EXISTENT_UUID,
            create_work_order_payload(title="Orphan work order"),
            make_outage_planner_headers(),
        )
        validate_error(response, ApiErrorId.OUTAGE_NOT_FOUND.value)

        rows, _meta = validate_paginated(
            api_client.list_work_orders(make_outage_planner_headers(), outage_id=real["id"])
        )
        assert rows == []


class TestComputedAndSystemFields:
    def test_priority_score_and_band_are_minted_by_the_server_at_creation(self):
        """A 240-hour INSPECTION carrying 200 mrem on a 720-hour target scores
        30 + 30 - 2 == 58.00 and bands as HIGH, with the duration term truncated
        by its own 30-point ceiling.

        PRD 3.2: "The band follows from the rounded score: a score of at least 75
        makes `priority` `CRITICAL`, a score of at least 45 makes it `HIGH`, and
        anything lower makes it `DISCRETIONARY`."

        Design: Corner/entities/work_order_priority_score_and_band_are_computed_at_creation
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24", duration_target_hours=720)

        work_order = validate_success(
            api_client.create_work_order(
                outage["id"],
                create_work_order_payload(
                    wo_type=WorkOrderType.INSPECTION,
                    title="Reactor vessel internals inspection",
                    estimated_hours=240,
                    estimated_cost_usd=500000,
                    estimated_dose_mrem=200,
                    regulatory_commitment=False,
                    requires_rad_work=True,
                ),
                make_outage_planner_headers(),
            ),
            201,
        )
        assert_work_order(work_order)
        assert work_order["priority_score"] == pytest.approx(58.00, abs=0.01)
        assert work_order["priority"] == Priority.HIGH
        assert_priority_band_matches_score(work_order)
        assert work_order["status"] == WorkOrderStatus.SCOPED
        assert work_order["origin"] == WorkOrderOrigin.PLANNED_SCOPE
        assert work_order["safety_function_id"] is None
        assert work_order["deferral_reason"] is None

    def test_identity_timestamps_and_derived_cell_figures_are_all_server_minted(self):
        """A newly registered pool opens at version 1, stamps created_at from the
        logical clock rather than wall-clock time, and derives all four cell
        figures without any client input.

        PRD 2.4: "Before the clock has ever been set, it reads exactly
        `2026-08-01T00:00:00Z`; the server must never fall back to real wall-clock
        time."

        Design: Corner/entities/system_fields_are_server_generated_on_create
        """
        set_clock(CLOCK_EPOCH)
        pool = validate_success(
            api_client.create_spent_fuel_pool(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "cells_total": 1200,
                    "cells_baseline_occupied": 900,
                    "full_core_offload_reserve_cells": 193,
                },
                make_station_admin_headers(),
            ),
            201,
        )
        assert_spent_fuel_pool(pool)
        assert pool["version"] == 1
        assert is_valid_uuid(pool["id"])
        assert_system_timestamps(pool, "spent fuel pool")
        assert_same_instant(pool["created_at"], CLOCK_EPOCH, "pool created_at")

        assert pool["cells_occupied"] == 900
        assert pool["cells_reserved"] == 0
        assert pool["cells_available"] == 300
        assert pool["protected_cells_available"] == 107
        assert_pool_ledger_consistent(pool)

    def test_dose_ledger_rows_carry_no_version_and_are_produced_only_by_transitions(self):
        """The single COMMIT row written at permit approval has no version and no
        updated_at, and re-reading the ledger returns the identical row set.

        PRD 2.4: "There is one exception: a dose ledger row is an immutable
        accounting record, so a `DoseTransaction` carries only `id` and
        `created_at` — it has no `updated_at` and no `version` field at all, and
        neither field should appear in its representation."

        Design: Corner/entities/dose_transaction_rows_are_immutable_and_versionless
        """
        set_clock(CLOCK_EPOCH)
        rad_area = given_rad_area(area_code="CTMT-EL471", dose_rate_mrem_per_hr=25)
        outage = given_outage(designation="1R24")
        given_approved_core_load_pattern(outage["id"])
        work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Cavity survey",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )
        permit = validate_success(
            api_client.draft_rwp(
                work_order["id"],
                create_rwp_payload(
                    rad_area_id=rad_area["id"],
                    worker_count=2,
                    shielding_factor=0.5,
                    planned_start_offset_hours=0,
                    planned_duration_hours=6,
                ),
                make_rad_protection_planner_headers(),
            ),
            201,
        )
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        validate_success(
            api_client.approve_rwp(permit["id"], make_rad_protection_manager_headers())
        )

        rows = read_dose_rows(permit["id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["rwp_id"] == permit["id"]
        assert row["direction"] == DoseDirection.COMMIT
        assert row["amount_mrem"] == pytest.approx(180.00, abs=0.01)
        assert row["reason"] == DoseReason.RWP_APPROVED
        assert "version" not in row
        assert "updated_at" not in row

        again = read_dose_rows(permit["id"])
        assert [r["id"] for r in again] == [row["id"]]


class TestTypeConstraintsAndGraphLinks:
    def test_three_independent_bound_violations_are_all_request_shape_errors(self):
        """An undeclared purpose, a shielding factor above the declared 0.95
        ceiling and a crew of zero are each refused at the request-shape rank,
        and neither the pool nor the permit list records anything.

        PRD 3.7: "`shielding_factor`, a dimensionless dose-reduction credit for
        temporary shielding and remote tooling which must be at least 0 and at
        most 0.95."

        Design: Corner/entities/invalid_enum_and_out_of_range_values_rejected
        """
        set_clock(CLOCK_EPOCH)
        pool = given_spent_fuel_pool()
        rad_area = given_rad_area(area_code="CTMT-EL471")
        outage = given_outage(designation="1R24")
        work_order = given_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Cavity survey",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )
        version_before = pool["version"]

        validate_error(
            api_client.create_pool_cell_reservation(
                {
                    "outage_id": outage["id"],
                    "spent_fuel_pool_id": pool["id"],
                    "cells_requested": 5,
                    "purpose": "SOMETHING_ELSE",
                    "expected_spent_fuel_pool_version": version_before,
                },
                make_reactor_engineer_headers(),
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )
        validate_error(
            api_client.draft_rwp(
                work_order["id"],
                create_rwp_payload(rad_area_id=rad_area["id"], shielding_factor=1),
                make_rad_protection_planner_headers(),
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )
        validate_error(
            api_client.draft_rwp(
                work_order["id"],
                create_rwp_payload(rad_area_id=rad_area["id"], worker_count=0),
                make_rad_protection_planner_headers(),
            ),
            ApiErrorId.INVALID_REQUEST.value,
        )

        after = read_pool(pool["id"])
        assert after["cells_reserved"] == 0
        assert after["version"] == version_before

        rows, _meta = validate_paginated(
            api_client.list_rwps(
                make_rad_protection_planner_headers(), work_order_id=work_order["id"]
            )
        )
        assert rows == []

    def test_a_permit_joins_a_work_order_a_rad_area_and_an_outage_in_one_row(self):
        """The permit copies its outage_id from the work order rather than taking
        it from the client, and each of the three filtered listings finds it.

        PRD 3.7: "The permit's `outage_id` is copied from the work order rather
        than supplied."

        Design: Corner/entities/permit_creation_links_work_order_and_rad_area_across_aggregates
        """
        set_clock(CLOCK_EPOCH)
        rad_area = given_rad_area(area_code="CTMT-EL471", dose_rate_mrem_per_hr=25)
        outage = given_outage(designation="1R24")
        work_order = given_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Cavity survey",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )

        permit = validate_success(
            api_client.draft_rwp(
                work_order["id"],
                create_rwp_payload(
                    rad_area_id=rad_area["id"],
                    worker_count=2,
                    shielding_factor=0.5,
                    planned_start_offset_hours=0,
                    planned_duration_hours=6,
                ),
                make_rad_protection_planner_headers(),
            ),
            201,
        )
        assert permit["work_order_id"] == work_order["id"]
        assert permit["rad_area_id"] == rad_area["id"]
        assert permit["outage_id"] == outage["id"]
        assert permit["status"] == RwpStatus.DRAFT
        assert permit["committed_dose_mrem"] == pytest.approx(180.00, abs=0.01)

        for kwargs in (
            {"work_order_id": work_order["id"]},
            {"rad_area_id": rad_area["id"]},
            {"outage_id": outage["id"]},
        ):
            rows, _meta = validate_paginated(
                api_client.list_rwps(make_rad_protection_planner_headers(), **kwargs)
            )
            assert [row["id"] for row in rows] == [permit["id"]]

    def test_the_predecessor_filter_returns_the_direct_successor_only(self):
        """Filtering on the direct predecessor edge of A1 returns A2 alone, while
        the transitively downstream A3 is absent even though the path walk carries
        A1's hours all the way through it.

        PRD 3.4: "That listing is the reverse-reachability channel for all four of
        an activity's foreign keys and the only way to discover the activity minted
        by the emergent-work cascade."

        Design: Corner/entities/self_referential_predecessor_chain_is_reverse_reachable
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")
        first = given_schedule_activity(
            outage["id"], label="A1", planned_start_offset_hours=0, planned_duration_hours=100
        )
        second = given_schedule_activity(
            outage["id"],
            label="A2",
            planned_start_offset_hours=100,
            planned_duration_hours=100,
            predecessor_activity_id=first["id"],
        )
        third = given_schedule_activity(
            outage["id"],
            label="A3",
            planned_start_offset_hours=200,
            planned_duration_hours=100,
            predecessor_activity_id=second["id"],
        )

        rows, _meta = validate_paginated(
            api_client.list_schedule_activities(
                make_outage_planner_headers(), predecessor_activity_id=first["id"]
            )
        )
        assert [row["id"] for row in rows] == [second["id"]]

        lengths = {}
        statuses = {}
        for activity_id in (first["id"], second["id"], third["id"]):
            row = validate_success(
                api_client.get_schedule_activity(activity_id, make_outage_planner_headers())
            )
            lengths[activity_id] = row["path_length_hours"]
            statuses[activity_id] = row["constraint_status"]

        assert lengths[first["id"]] == pytest.approx(100.00, abs=0.01)
        assert lengths[second["id"]] == pytest.approx(200.00, abs=0.01)
        assert lengths[third["id"]] == pytest.approx(300.00, abs=0.01)
        assert statuses[first["id"]] == ConstraintStatus.CLEAR
        assert statuses[second["id"]] == ConstraintStatus.BLOCKED
        assert statuses[third["id"]] == ConstraintStatus.BLOCKED

        after = read_outage(outage["id"])
        assert after["projected_duration_hours"] == pytest.approx(300.00, abs=0.01)
        assert after["critical_path_activity_id"] == third["id"]
