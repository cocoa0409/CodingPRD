"""Scheduling and starting routine maintenance visits.

Site work windows are closed intervals, so a window that begins exactly when
another ends collides; a window lying in the past is refused before the site's
capacity is ever counted; and a visit that is otherwise ready to start still
depends on the custody dimension of a different entity, the artwork.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_maintenance_visit
from test_helpers.factories import maintenance_visit_payload
from test_helpers.test_users import TEST_USERS, make_conservator_vendor_headers


def _one_scheduled_visit(api, site=None):
    """A BRONZE work at a single-work-at-a-time site with one visit booked."""
    register = fixtures.setup_register(api, site=site)
    protocol = fixtures.create_protocol(api)
    visit = fixtures.schedule_visit(
        api, register["artwork"]["id"], protocol["id"]
    )
    assert visit["status"] == "SCHEDULED"
    assert visit["window_start"].startswith("2026-08-10T08:00:00")
    assert visit["window_end"].startswith("2026-08-12T17:00:00")
    return register, protocol, visit


def test_a_past_window_is_refused_before_the_site_capacity_is_counted(api):
    """PRD §3.3: "A window may not be scheduled into the past: `window_start` must be
    at or after the logical clock, and an earlier value draws `ERR_WINDOW_IN_PAST`."
    PRD §2.8: "A scheduled work window not lying in the past — `ERR_WINDOW_IN_PAST`."
    PRD §2.8: "Site concurrent-work capacity — `ERR_SITE_WORK_CAPACITY_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/visit_window_in_past_outranks_site_work_capacity_conflict
    """
    register, protocol, visit = _one_scheduled_visit(api)
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")

    # The requested window is both behind the clock and colliding with the visit
    # already booked at this single-work-at-a-time site.
    refused = api.create_maintenance_visit(
        maintenance_visit_payload(
            register["artwork"]["id"],
            protocol["id"],
            window_start="2026-08-11T08:00:00Z",
            window_end="2026-08-13T17:00:00Z",
        ),
        TEST_USERS["crew_headers"],
    )
    body = validate_error(refused, ApiErrorId.ERR_WINDOW_IN_PAST.value)
    assert body["error_id"] != ApiErrorId.ERR_SITE_WORK_CAPACITY_CONFLICT.value

    rows, _meta = validate_paginated(
        api.list_maintenance_visits(TEST_USERS["manager_headers"])
    )
    assert [row["id"] for row in rows] == [visit["id"]]
    assert rows[0]["status"] == "SCHEDULED"


def test_the_same_colliding_window_reaches_the_capacity_check_when_it_is_not_past(api):
    """PRD §3.3: "The count of visits at the same site whose `status` is `SCHEDULED` or
    `IN_PROGRESS` and whose window collides with the requested one must be strictly
    less than that site's `concurrent_work_capacity`; otherwise the request is refused
    with `ERR_SITE_WORK_CAPACITY_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/visit_window_in_past_outranks_site_work_capacity_conflict
    """
    register, protocol, visit = _one_scheduled_visit(api)

    # The clock is still at 2026-08-01, so the identical window is no longer in the
    # past and the later capacity check becomes the first failure.
    refused = api.create_maintenance_visit(
        maintenance_visit_payload(
            register["artwork"]["id"],
            protocol["id"],
            window_start="2026-08-11T08:00:00Z",
            window_end="2026-08-13T17:00:00Z",
        ),
        TEST_USERS["crew_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_SITE_WORK_CAPACITY_CONFLICT.value)

    rows, _meta = validate_paginated(
        api.list_maintenance_visits(TEST_USERS["manager_headers"])
    )
    assert [row["id"] for row in rows] == [visit["id"]]


def _two_works_one_at_a_time(api, concurrent_work_capacity=1):
    """Two BRONZE works sharing a site, one visit already booked on the first."""
    register, protocol, visit = _one_scheduled_visit(
        api, site={"concurrent_work_capacity": concurrent_work_capacity}
    )
    work_b = fixtures.create_artwork(
        api,
        register["artist"]["id"],
        register["site"]["id"],
        accession_number="2024.002",
        title="Seated Figure",
        significance_tier="STANDARD",
        acquisition_document_ref="DEED-2016-002",
    )
    return register, protocol, visit, work_b


def test_a_window_starting_where_another_ends_collides(api):
    """PRD §3.3: "Site work windows are treated as **closed** intervals running from
    `window_start` through `window_end` inclusive, which means two windows collide
    even when one begins at the exact instant the other ends."

    Design: Difficulty/resource_temporal_overlap/site_work_window_closed_interval_touching_endpoints_collide
    """
    _register, protocol, _visit, work_b = _two_works_one_at_a_time(api)

    refused = api.create_maintenance_visit(
        maintenance_visit_payload(
            work_b["id"],
            protocol["id"],
            window_start="2026-08-12T17:00:00Z",
            window_end="2026-08-14T17:00:00Z",
        ),
        TEST_USERS["crew_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_SITE_WORK_CAPACITY_CONFLICT.value)

    rows, meta = validate_paginated(
        api.list_maintenance_visits(TEST_USERS["manager_headers"])
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1


def test_a_window_starting_after_the_touching_instant_is_accepted(api):
    """PRD §3.3: "Scheduling a visit is open to `MaintenanceCrew` and
    `ChiefConservator`."
    PRD §3.3: "A visit that has never been aborted keeps `abort_reason` at `NONE`."

    Design: Difficulty/resource_temporal_overlap/site_work_window_closed_interval_touching_endpoints_collide
    """
    _register, protocol, visit_a, work_b = _two_works_one_at_a_time(api)

    visit_b = validate_success(
        api.create_maintenance_visit(
            maintenance_visit_payload(
                work_b["id"],
                protocol["id"],
                window_start="2026-08-13T08:00:00Z",
                window_end="2026-08-14T17:00:00Z",
            ),
            TEST_USERS["crew_headers"],
        ),
        201,
    )
    assert visit_b["status"] == "SCHEDULED"
    assert_maintenance_visit(visit_b)

    unchanged = fixtures.read_visit(api, visit_a["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["abort_reason"] == "NONE"

    rows, meta = validate_paginated(
        api.list_maintenance_visits(TEST_USERS["manager_headers"])
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2


def test_a_second_crew_may_share_the_touching_instant_when_capacity_allows_two(api):
    """PRD §3.3: "Site work capacity is enforced at scheduling time."
    PRD §3.3: "The count of visits at the same site whose `status` is `SCHEDULED` or
    `IN_PROGRESS` and whose window collides with the requested one must be strictly
    less than that site's `concurrent_work_capacity`; otherwise the request is refused
    with `ERR_SITE_WORK_CAPACITY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/site_work_window_closed_interval_touching_endpoints_collide
    """
    _register, protocol, _visit_a, work_b = _two_works_one_at_a_time(
        api, concurrent_work_capacity=2
    )

    # One colliding visit is strictly fewer than two, so the same touching window
    # that a capacity of one refused is now accepted.
    visit_b = validate_success(
        api.create_maintenance_visit(
            maintenance_visit_payload(
                work_b["id"],
                protocol["id"],
                window_start="2026-08-12T17:00:00Z",
                window_end="2026-08-14T17:00:00Z",
            ),
            TEST_USERS["crew_headers"],
        ),
        201,
    )
    assert visit_b["status"] == "SCHEDULED"
    assert visit_b["window_start"].startswith("2026-08-12T17:00:00")

    rows, meta = validate_paginated(
        api.list_maintenance_visits(TEST_USERS["manager_headers"])
    )
    assert meta["total_count"] == 2
    assert all(row["status"] == "SCHEDULED" for row in rows)


def _visit_ready_while_the_vendor_holds_the_work(api):
    """A visit whose window has opened on a work the conservator has taken away."""
    state = fixtures.setup_approved_proposal(api)
    protocol = fixtures.create_protocol(api)
    # The visit is booked after finalization, so no treatment requirement can have
    # aborted it.
    visit = fixtures.schedule_visit(api, state["artwork"]["id"], protocol["id"])
    assert visit["status"] == "SCHEDULED"

    fixtures.set_clock(api, "2026-08-10T09:00:00Z")
    proposal = fixtures.start_execution(
        api, state["proposal"]["id"], state["conservator"]["id"]
    )
    assert proposal["status"] == "IN_EXECUTION"
    state["protocol"] = protocol
    state["visit"] = visit
    return state


def test_a_work_under_treatment_cannot_receive_routine_care(api):
    """PRD §3.3: "The logical clock must be at or after `window_start` — an earlier
    attempt draws `ERR_VISIT_WINDOW_NOT_OPEN` — and the work's `custody_status` must
    be `ON_VIEW` or `IN_STORAGE`, since a work already `IN_TREATMENT` cannot receive
    routine care; that failure is `ERR_ARTWORK_CUSTODY_INVALID`."
    PRD §3.5: "On success the work's custody moves `ON_VIEW → IN_TREATMENT` or
    `IN_STORAGE → IN_TREATMENT` and its conservation dimension moves
    `TREATMENT_REQUIRED → TREATMENT_IN_PROGRESS`."

    Design: Difficulty/cross_entity_state_dependency/visit_start_depends_on_artwork_custody_dimension
    """
    state = _visit_ready_while_the_vendor_holds_the_work(api)

    work = fixtures.read_artwork(api, state["artwork"]["id"])
    assert work["custody_status"] == "IN_TREATMENT"
    assert work["conservation_status"] == "TREATMENT_IN_PROGRESS"

    refused = api.start_maintenance_visit(
        state["visit"]["id"],
        {"crew_note": "routine wash crew on site"},
        TEST_USERS["crew_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_ARTWORK_CUSTODY_INVALID.value)

    blocked = fixtures.read_visit(api, state["visit"]["id"])
    assert blocked["status"] == "SCHEDULED"
    assert blocked["started_at"] is None
    assert blocked["abort_reason"] == "NONE"
    assert fixtures.read_proposal(api, state["proposal"]["id"])["status"] == "IN_EXECUTION"
    assert fixtures.read_allocation(api, state["allocation"]["id"])["status"] == "COMMITTED"


def test_the_same_visit_starts_once_the_work_comes_back_on_view(api):
    """PRD §3.5: "The work's custody returns `IN_TREATMENT → ON_VIEW` and its
    conservation dimension moves `TREATMENT_IN_PROGRESS → STABILIZED`."
    PRD §3.3: "Starting stamps `started_at` from the logical clock and moves any
    funding allocation attached to the visit from `RESERVED` to `COMMITTED`."

    Design: Difficulty/cross_entity_state_dependency/visit_start_depends_on_artwork_custody_dimension
    """
    state = _visit_ready_while_the_vendor_holds_the_work(api)
    completed = validate_success(
        api.complete_treatment_proposal(
            state["proposal"]["id"],
            {"completion_report_ref": "report/2026/patina-recoat.pdf"},
            make_conservator_vendor_headers(state["conservator"]["id"]),
        )
    )
    assert completed["status"] == "COMPLETED"

    work = fixtures.read_artwork(api, state["artwork"]["id"])
    assert work["custody_status"] == "ON_VIEW"
    assert work["conservation_status"] == "STABILIZED"

    started = validate_success(
        api.start_maintenance_visit(
            state["visit"]["id"], {}, TEST_USERS["crew_headers"]
        )
    )
    assert started["status"] == "IN_PROGRESS"
    assert started["started_at"].startswith("2026-08-10T09:00:00")
    assert started["abort_reason"] == "NONE"
