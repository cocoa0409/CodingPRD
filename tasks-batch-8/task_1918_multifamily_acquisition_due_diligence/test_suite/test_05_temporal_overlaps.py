"""Resource/temporal overlap: half-open walk windows vs closed coverage intervals."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_lease,
    add_unit,
    create_kicked_off_acquisition,
    get_success_data,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
POL1 = TEST_USERS["property_ops_headers"]


class TestInspectorWalkHalfOpenOverlap:
    def test_adjacent_walks_allowed_and_overlap_rejected(self, api):
        """PRD §3.4: "The window must not overlap any other non-terminal
        inspection booked under the same `inspector_ref` — because the interval
        is half-open, two walks that merely touch, one's `walk_end` equaling
        the other's `walk_start`, do not overlap and are allowed; a genuine
        overlap is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/inspector_walk_half_open_overlap
        """
        acq = create_kicked_off_acquisition(property_name="Overlap One")
        unit1 = add_unit(acq["id"], unit_number="1A")
        unit2 = add_unit(acq["id"], unit_number="2B", floor_plan="2BR",
                         sqft=900, market_rent_cents=180000)
        get_success_data(api.create_inspection(
            {"unit_id": unit1["id"], "inspector_ref": "insp-9",
             "walk_start": "2026-08-10T09:00:00Z",
             "walk_end": "2026-08-10T11:00:00Z"}, POL1), 201)

        adjacent = validate_success(api.create_inspection(
            {"unit_id": unit2["id"], "inspector_ref": "insp-9",
             "walk_start": "2026-08-10T11:00:00Z",
             "walk_end": "2026-08-10T13:00:00Z"}, POL1), 201)
        assert adjacent["status"] == "SCHEDULED", (
            "half-open [09:00,11:00) and [11:00,13:00) do not overlap"
        )

        resp = api.create_inspection(
            {"unit_id": unit2["id"], "inspector_ref": "insp-9",
             "walk_start": "2026-08-10T10:30:00Z",
             "walk_end": "2026-08-10T12:00:00Z"}, POL1)
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED, 409)

    def test_overlap_binds_the_inspector_not_the_unit(self, api):
        """PRD §3.4: "A `PropertyOperationsLead` schedules a unit walk by
        naming the `unit_id`, the `inspector_ref` whose calendar the walk
        books, and a half-open window from `walk_start` (inclusive) to
        `walk_end` (exclusive). The window must not overlap any other
        non-terminal inspection booked under the same `inspector_ref`..."

        Design: Difficulty/resource_temporal_overlap/inspector_walk_half_open_overlap
        """
        acq = create_kicked_off_acquisition(property_name="Overlap One B")
        unit1 = add_unit(acq["id"], unit_number="1A")
        unit2 = add_unit(acq["id"], unit_number="2B", floor_plan="2BR",
                         sqft=900, market_rent_cents=180000)
        get_success_data(api.create_inspection(
            {"unit_id": unit1["id"], "inspector_ref": "insp-9",
             "walk_start": "2026-08-10T09:00:00Z",
             "walk_end": "2026-08-10T11:00:00Z"}, POL1), 201)

        # Same window, different inspector: allowed (the inspector is the resource).
        other_inspector = validate_success(api.create_inspection(
            {"unit_id": unit2["id"], "inspector_ref": "insp-7",
             "walk_start": "2026-08-10T09:30:00Z",
             "walk_end": "2026-08-10T12:00:00Z"}, POL1), 201)
        assert other_inspector["inspector_ref"] == "insp-7"

        # Same inspector, overlapping window: rejected.
        resp = api.create_inspection(
            {"unit_id": unit2["id"], "inspector_ref": "insp-9",
             "walk_start": "2026-08-10T10:30:00Z",
             "walk_end": "2026-08-10T12:00:00Z"}, POL1)
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED, 409)


class TestConcessionCoverageClosedIntervalOverlap:
    def test_shared_single_day_collides_and_next_day_allowed(self, api):
        """PRD §3.3: "a coverage window from `coverage_start_date` through
        `coverage_end_date` that is a closed interval — both endpoints are
        included days. Two concessions on the same lease may not share even one
        calendar day of coverage; any overlap between a new concession and an
        existing `PENDING` or `VERIFIED` concession on the same lease is
        rejected with `ERR_CONCESSION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/concession_coverage_closed_interval_overlap
        """
        acq = create_kicked_off_acquisition(property_name="Overlap Two")
        unit = add_unit(acq["id"])
        lease = add_lease(unit["id"])
        get_success_data(api.create_concession(
            {"lease_file_id": lease["id"],
             "concession_type": "RECURRING_MONTHLY", "value_cents": 10000,
             "coverage_start_date": "2026-01-01T00:00:00Z",
             "coverage_end_date": "2026-01-31T00:00:00Z"}, ANALYST), 201)

        resp = api.create_concession(
            {"lease_file_id": lease["id"],
             "concession_type": "ONE_TIME_CREDIT", "value_cents": 30000,
             "coverage_start_date": "2026-01-31T00:00:00Z",
             "coverage_end_date": "2026-02-28T00:00:00Z"}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_CONCESSION_OVERLAP, 409)

        ok = validate_success(api.create_concession(
            {"lease_file_id": lease["id"],
             "concession_type": "ONE_TIME_CREDIT", "value_cents": 30000,
             "coverage_start_date": "2026-02-01T00:00:00Z",
             "coverage_end_date": "2026-02-28T00:00:00Z"}, ANALYST), 201)
        assert ok["verification_status"] == "PENDING"

    def test_closed_interval_semantics_differ_from_half_open(self, api):
        """PRD §3.3: "a coverage window from `coverage_start_date` through
        `coverage_end_date` that is a closed interval — both endpoints are
        included days."
        PRD §3.4: "because the interval is half-open, two walks that merely
        touch, one's `walk_end` equaling the other's `walk_start`, do not
        overlap and are allowed"

        Design: Difficulty/resource_temporal_overlap/concession_coverage_closed_interval_overlap
        """
        acq = create_kicked_off_acquisition(property_name="Overlap Two B")
        unit = add_unit(acq["id"])
        lease = add_lease(unit["id"])
        get_success_data(api.create_concession(
            {"lease_file_id": lease["id"],
             "concession_type": "RECURRING_MONTHLY", "value_cents": 10000,
             "coverage_start_date": "2026-01-01T00:00:00Z",
             "coverage_end_date": "2026-01-31T00:00:00Z"}, ANALYST), 201)

        # A concession starting on the day the sibling ends shares one day.
        resp = api.create_concession(
            {"lease_file_id": lease["id"],
             "concession_type": "ONE_TIME_CREDIT", "value_cents": 30000,
             "coverage_start_date": "2026-01-31T00:00:00Z",
             "coverage_end_date": "2026-02-28T00:00:00Z"}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_CONCESSION_OVERLAP, 409)

        # The first day after the inclusive end is clear.
        ok = validate_success(api.create_concession(
            {"lease_file_id": lease["id"],
             "concession_type": "ONE_TIME_CREDIT", "value_cents": 30000,
             "coverage_start_date": "2026-02-01T00:00:00Z",
             "coverage_end_date": "2026-02-28T00:00:00Z"}, ANALYST), 201)
        assert ok["coverage_start_date"].startswith("2026-02-01")
