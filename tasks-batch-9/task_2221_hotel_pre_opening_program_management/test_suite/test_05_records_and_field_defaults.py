"""Record shape, declared field defaults and derived-field seeding.

Every assertion in this module is anchored in the Hotel Pre-Opening Program
Management PRD: the tuning defaults of §3.1, the common resource properties and
append-only row shape of §2.4, the pagination envelope of §2.3, the referential
resolution order of §2.5, the validation precedence of §2.10, and the
computed-field definitions of §3.7 and §3.9.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_HIRING_PLAN_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MILESTONE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_append_only_row,
    assert_budget_split,
    assert_cents,
    assert_common_fields,
    assert_dates_null,
    assert_page,
    assert_program_dimensions,
    assert_ratio,
)
from test_helpers.constants import (
    DEFAULT_LICENSING_BUFFER_DAYS,
    DEFAULT_REWORK_BUFFER_DAYS,
    DEFAULT_SLIP_TOLERANCE_DAYS,
    DEFAULT_STABILIZATION_WINDOW_DAYS,
)
from test_helpers.fixtures import make_milestone
from test_helpers.test_users import (
    CONSTRUCTION_MANAGER,
    LICENSING_COORDINATOR,
    PROGRAM_DIRECTOR,
    QUALITY_INSPECTOR,
    TALENT_MANAGER,
)

# An identifier that is a well-formed UUID but resolves to no stored record.
UNKNOWN_UUID = "99999999-9999-4999-8999-999999999999"


class TestProgramCreateFieldDefaults:
    """The four optional tuning inputs and the seeded derived fields."""

    def test_program_create_applies_declared_tuning_defaults(self, api, clock_at_default):
        """A director creates a property programme without stating any of the four
        tuning parameters. The server must fill in the declared defaults rather
        than leaving them null or zero.

        `licensing_buffer_days` — the days added to the computed schedule finish to obtain the projected opening date — defaults to 14 and must lie between 0 and 120.

        Design: Corner/entities/program_create_applies_declared_defaults_for_omitted_tuning_fields
        """
        payload = factories.program_payload()
        for tuning_field in (
            "licensing_buffer_days",
            "rework_buffer_days",
            "slip_tolerance_days",
            "stabilization_window_days",
        ):
            assert tuning_field not in payload

        data = validate_success(api.create_program(payload, PROGRAM_DIRECTOR), 201)

        assert data["licensing_buffer_days"] == DEFAULT_LICENSING_BUFFER_DAYS
        assert data["rework_buffer_days"] == DEFAULT_REWORK_BUFFER_DAYS
        assert data["slip_tolerance_days"] == DEFAULT_SLIP_TOLERANCE_DAYS
        assert data["stabilization_window_days"] == DEFAULT_STABILIZATION_WINDOW_DAYS

    def test_program_create_seeds_state_dimensions_and_derived_counters(
        self, api, clock_at_default
    ):
        """The same create must open both state dimensions at their starting
        values, seed every derived counter at zero and leave both schedule
        projections unwritten until the first schedule computation.

        A newly created program starts in `PLANNING` on the delivery dimension and `BOOKING_CLOSED` on the commercial dimension, with `readiness_posture` at `MOBILIZING`, every derived counter at 0 and `readiness_score` at 0.0.

        Design: Corner/entities/program_create_applies_declared_defaults_for_omitted_tuning_fields
        """
        data = validate_success(
            api.create_program(factories.program_payload(), PROGRAM_DIRECTOR), 201
        )

        assert_common_fields(data)
        assert data["version"] == 1
        assert_program_dimensions(
            data,
            schedule_state="PLANNING",
            commercial_state="BOOKING_CLOSED",
            readiness_posture="MOBILIZING",
        )
        assert_ratio(data["readiness_score"], 0.0)

        for counter in (
            "critical_path_milestone_count",
            "open_critical_punch_count",
            "required_system_count",
            "certified_system_count",
            "issued_mandatory_permit_count",
            "hiring_plan_count",
            "departments_ready_count",
            "committed_room_nights",
            "schedule_slip_days",
        ):
            assert data[counter] == 0, f"{counter} must start at 0, got {data[counter]}"

        assert_cents(data["contingency_liability_cents"], 0)
        assert_cents(data["payroll_accrual_cents"], 0)
        assert_dates_null(data)
        assert data["soft_opening_date"] is None
        assert data["baselined_by_user_id"] is None
        assert data["soft_opening_authorized_by_user_id"] is None


class TestProgramRetrieval:
    """Reading a stored programme back through its own endpoint."""

    def test_program_get_by_id_returns_the_stored_row(self, api, program):
        """An inspector reads the programme created a moment earlier. The read
        must return the persisted anchors and ceilings alongside the derived
        counters, not a fresh echo of the create request.

        A single program read exposes every derived counter and both projected opening dates.

        Design: Corner/entities/program_get_by_id_returns_the_stored_row
        """
        data = validate_success(api.get_program(program["id"], QUALITY_INSPECTOR))

        assert data["id"] == program["id"]
        assert data["property_name"] == "Cobalt Bay Hotel"
        assert data["brand_code"] == "CBH"
        assert data["room_count"] == 120
        assert data["construction_start_date"] == "2026-09-01"
        assert data["target_opening_date"] == "2027-05-01"
        assert data["storage_capacity_pallets"] == 40
        assert data["room_night_ceiling"] == 200
        assert_cents(data["contingency_liability_cap_cents"], 50000000)
        assert data["version"] == 1
        assert data["created_at"] == program["created_at"]
        assert_dates_null(data)
        assert data["critical_path_milestone_count"] == 0


class TestMilestoneRecordAccess:
    """Listing, resolving and shape-checking milestone records."""

    def test_milestone_list_pagination_reports_total_count_and_has_more(
        self, api, program
    ):
        """Three milestones are filed against one programme and read back two at
        a time. The envelope must count the whole filtered set, so page one
        still reports three records with more to come.

        List responses populate four pagination fields inside `meta`: the effective `limit`, the effective `offset`, `total_count` (the number of records matching the filter before the page window is applied), and `has_more` (true when records remain beyond the current window).

        Design: Corner/entities/milestone_list_pagination_reports_total_count_and_has_more
        """
        first = make_milestone(
            api,
            program["id"],
            code="STRUCTURE_TOPPED_OUT",
            name="Structure topped out",
            duration_days=30,
            planned_start_date="2026-09-01",
        )
        second = make_milestone(
            api,
            program["id"],
            code="MEP_ROUGH_IN",
            name="MEP rough-in",
            duration_days=20,
            planned_start_date="2026-10-01",
        )
        third = make_milestone(
            api,
            program["id"],
            code="INTERIOR_FIT_OUT",
            name="Interior fit-out",
            duration_days=25,
            planned_start_date="2026-10-21",
        )

        page_one, meta_one = validate_paginated(
            api.list_milestones(
                PROGRAM_DIRECTOR,
                {"program_id": program["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page_one) == 2
        assert_page(meta_one, total_count=3, has_more=True, limit=2, offset=0)

        page_two, meta_two = validate_paginated(
            api.list_milestones(
                PROGRAM_DIRECTOR,
                {"program_id": program["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page_two) == 1
        assert_page(meta_two, total_count=3, has_more=False, limit=2, offset=2)

        assert {row["id"] for row in page_one} | {row["id"] for row in page_two} == {
            first["id"],
            second["id"],
            third["id"],
        }

    def test_milestone_get_with_unknown_id_returns_milestone_not_found(
        self, api, clock_at_default
    ):
        """A read is attempted against a milestone identifier that was never
        issued. The answer must name the milestone entity rather than falling
        back on a generic rejection.

        The first identifier that resolves to nothing determines the error: `ERR_PROGRAM_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_PERMIT_APPLICATION_NOT_FOUND`, `ERR_SYSTEM_IMPLEMENTATION_NOT_FOUND`, `ERR_HIRING_PLAN_NOT_FOUND`, `ERR_HIRE_NOT_FOUND`, `ERR_TRAINING_SESSION_NOT_FOUND`, `ERR_BUDGET_LINE_NOT_FOUND`, `ERR_OSE_ORDER_NOT_FOUND`, `ERR_RESERVATION_BLOCK_NOT_FOUND` or `ERR_PUNCH_LIST_ITEM_NOT_FOUND`, each returned with HTTP 404.

        Design: Corner/entities/milestone_get_with_unknown_id_returns_milestone_not_found
        """
        validate_error(
            api.get_milestone(UNKNOWN_UUID, CONSTRUCTION_MANAGER),
            ERR_MILESTONE_NOT_FOUND,
            expected_status=404,
        )

    def test_milestone_create_without_duration_days_returns_invalid_request(
        self, api, program
    ):
        """A milestone is filed with a code, a name and a planned start but no
        planned duration. Request shape is checked before anything else, so the
        create is rejected and no milestone is stored.

        3. **Request shape** — required fields present, enum values in range, integers within their declared bounds, `cases_passed` not greater than `cases_total`, `ends_at` strictly after `starts_at`, `delivery_window_end` strictly after `delivery_window_start`, `target_opening_date` strictly after `construction_start_date`, and pagination within bounds. Any failure is `ERR_INVALID_REQUEST`.

        Design: Corner/entities/milestone_create_without_duration_days_returns_invalid_request
        """
        payload = factories.milestone_payload(
            program["id"],
            code="STRUCTURE_TOPPED_OUT",
            name="Structure topped out",
            planned_start_date="2026-09-01",
            duration_days=None,
        )
        assert "duration_days" not in payload

        validate_error(
            api.create_milestone(payload, CONSTRUCTION_MANAGER),
            ERR_INVALID_REQUEST,
            expected_status=400,
        )

        rows, meta = validate_paginated(
            api.list_milestones(PROGRAM_DIRECTOR, {"program_id": program["id"]})
        )
        assert_page(meta, total_count=0, has_more=False)
        assert rows == []


class TestPermitApplicationEnumClosure:
    """The permit type enumeration is closed to six members."""

    def test_permit_application_with_unknown_permit_type_returns_invalid_request(
        self, api, program
    ):
        """A coordinator drafts a file for a permit type the statute book does
        not contain. The enumeration is closed, so the draft is refused on shape
        before the gating milestone is even considered.

        Six permit types exist: `CERTIFICATE_OF_OCCUPANCY`, `LIQUOR_LICENSE`, `FOOD_SERVICE`, `ELEVATOR`, `FIRE_ALARM` and `SIGNAGE`.

        Design: Corner/entities/permit_application_with_unknown_permit_type_returns_invalid_request
        """
        milestone = make_milestone(
            api,
            program["id"],
            code="STRUCTURE_TOPPED_OUT",
            name="Structure topped out",
            duration_days=30,
            planned_start_date="2026-09-01",
        )

        validate_error(
            api.create_permit_application(
                factories.permit_payload(
                    program["id"],
                    milestone["id"],
                    permit_type="POOL_PERMIT",
                    review_days=21,
                ),
                LICENSING_COORDINATOR,
            ),
            ERR_INVALID_REQUEST,
            expected_status=400,
        )


class TestMilestoneDependencyRows:
    """The dependency edge is an append-only join row over the milestone graph."""

    @pytest.fixture
    def two_milestones(self, api, program):
        first = make_milestone(
            api,
            program["id"],
            code="STRUCTURE_TOPPED_OUT",
            name="Structure topped out",
            duration_days=30,
            planned_start_date="2026-09-01",
        )
        second = make_milestone(
            api,
            program["id"],
            code="MEP_ROUGH_IN",
            name="MEP rough-in",
            duration_days=20,
            planned_start_date="2026-10-01",
        )
        return first, second

    def test_milestone_dependency_carries_no_version_and_no_updated_at(
        self, api, two_milestones
    ):
        """A finish-to-start edge is added between two milestones. Edges are
        evidence of the plan rather than mutable records, so the created row
        carries only an identifier and a creation instant.

        Two record types are append-only join or evidence rows and therefore carry **only** `id` and `created_at`: a milestone dependency edge and a system test run.

        Design: Corner/entities/milestone_dependency_is_immutable_and_carries_no_version
        """
        predecessor, successor = two_milestones

        data = validate_success(
            api.create_dependency(
                factories.dependency_payload(
                    predecessor["id"],
                    successor["id"],
                    dependency_type="FINISH_START",
                    lag_days=0,
                ),
                CONSTRUCTION_MANAGER,
            ),
            201,
        )

        assert data["predecessor_milestone_id"] == predecessor["id"]
        assert data["successor_milestone_id"] == successor["id"]
        assert data["dependency_type"] == "FINISH_START"
        assert data["lag_days"] == 0
        assert_append_only_row(data)

    def test_dependency_is_readable_from_both_endpoints_of_the_edge(
        self, api, two_milestones
    ):
        """One edge joins a predecessor to a successor with two days of lag. The
        same row must surface when the incident edges of either endpoint are
        listed, which is what makes the network navigable in both directions.

        Every edge incident to a given milestone can be retrieved, in either direction, with an optional `role` filter selecting whether the milestone acts as predecessor or as successor on the returned edges.

        Design: Corner/entities/milestone_dependency_junction_links_two_milestones_and_is_readable_from_both_sides
        """
        predecessor, successor = two_milestones
        edge = validate_success(
            api.create_dependency(
                factories.dependency_payload(
                    predecessor["id"],
                    successor["id"],
                    dependency_type="FINISH_START",
                    lag_days=2,
                ),
                CONSTRUCTION_MANAGER,
            ),
            201,
        )

        from_predecessor, _ = validate_paginated(
            api.list_dependencies(predecessor["id"], PROGRAM_DIRECTOR)
        )
        assert [row["id"] for row in from_predecessor] == [edge["id"]]
        assert from_predecessor[0]["successor_milestone_id"] == successor["id"]

        from_successor, _ = validate_paginated(
            api.list_dependencies(successor["id"], PROGRAM_DIRECTOR)
        )
        assert [row["id"] for row in from_successor] == [edge["id"]]
        assert from_successor[0]["predecessor_milestone_id"] == predecessor["id"]
        assert from_successor[0]["lag_days"] == 2


class TestChildRecordResolutionAndDefaults:
    """Parent resolution, computed flags and system-minted fields on children."""

    def test_hire_create_under_unknown_hiring_plan_returns_hiring_plan_not_found(
        self, api, clock_at_default
    ):
        """An offer is extended against a departmental plan that does not exist.
        The parent reference is resolved before the wave-date and headcount
        rules, so the plan is what the error names.

        Referenced resources are resolved left to right: identifiers appearing in the URL path are validated before identifiers appearing in the request body, and body identifiers are validated in declaration order — the `program_id` first, then whichever of `budget_line_id`, `hiring_plan_id`, `milestone_id`, `orientation_session_id` or `prerequisite_system_id` the payload carries.

        Design: Corner/entities/hire_create_under_unknown_hiring_plan_returns_hiring_plan_not_found
        """
        validate_error(
            api.create_hire(
                factories.hire_payload(
                    UNKNOWN_UUID,
                    full_name="R. Alvarez",
                    hourly_rate_cents=2500,
                    scheduled_hours_per_day=8,
                    start_date="2026-09-15",
                ),
                TALENT_MANAGER,
            ),
            ERR_HIRING_PLAN_NOT_FOUND,
            expected_status=404,
        )

    def test_punch_item_blocks_certificate_of_occupancy_derived_from_severity(
        self, api, program
    ):
        """Two defects are raised against the same milestone, one major and one
        critical. The certificate-of-occupancy flag is computed from severity
        and state, so the pair must read false and true respectively.

        An item begins `OPEN` with `submitted_by_user_id`, `verified_by_user_id` null and `rejection_count` at 0, and the system derives `blocks_certificate_of_occupancy` as true exactly when the item's `severity` is `CRITICAL` and its state is anything other than `VERIFIED`.

        Design: Corner/entities/punch_item_blocks_certificate_of_occupancy_derived_from_severity
        """
        milestone = make_milestone(
            api,
            program["id"],
            code="STRUCTURE_TOPPED_OUT",
            name="Structure topped out",
            duration_days=30,
            planned_start_date="2026-09-01",
        )

        major = validate_success(
            api.create_punch_item(
                factories.punch_item_payload(
                    program["id"],
                    milestone_id=milestone["id"],
                    description="Corridor paint touch-up",
                    severity="MAJOR",
                ),
                CONSTRUCTION_MANAGER,
            ),
            201,
        )
        assert major["state"] == "OPEN"
        assert major["severity"] == "MAJOR"
        assert major["rejection_count"] == 0
        assert major["submitted_by_user_id"] is None
        assert major["verified_by_user_id"] is None
        assert major["blocks_certificate_of_occupancy"] is False

        critical = validate_success(
            api.create_punch_item(
                factories.punch_item_payload(
                    program["id"],
                    milestone_id=milestone["id"],
                    description="Stair pressurization fan inoperative",
                    severity="CRITICAL",
                ),
                CONSTRUCTION_MANAGER,
            ),
            201,
        )
        assert critical["state"] == "OPEN"
        assert critical["severity"] == "CRITICAL"
        assert critical["blocks_certificate_of_occupancy"] is True

    def test_budget_line_response_carries_system_generated_id_and_version(
        self, api, program
    ):
        """A setup budget line is authorized for one million cents. The
        identifier, timestamps and version are minted by the server, and the
        three-way money split is seeded from the authorized amount.

        Most resources — pre-opening programs, milestones, permit applications, system implementations, hiring plans, hires, training sessions, budget lines, OS&E orders, reservation blocks and punch-list items — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that record.

        Design: Corner/entities/budget_line_response_carries_system_generated_id_and_version
        """
        data = validate_success(
            api.create_budget_line(
                factories.budget_line_payload(
                    program["id"], category="SETUP", authorized_cents=1000000
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )

        assert_common_fields(data)
        assert data["version"] == 1
        assert data["program_id"] == program["id"]
        assert data["category"] == "SETUP"
        assert_budget_split(
            data, authorized_cents=1000000, committed_cents=0, spent_cents=0
        )
