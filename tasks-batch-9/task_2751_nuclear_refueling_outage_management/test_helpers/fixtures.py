"""Composite state builders.

The harness restarts the API server before every individual test, so each test
starts against an empty database and must build every precondition through the
endpoints PRD section 4 declares. These builders do exactly that, in five
tiers: standing plant configuration, entity hierarchy, whole-lifecycle
shortcuts, accumulation and threshold targeting, and terminal-state drives.

Every builder accepts ``**overrides`` that are merged into the creation payload
so a test can vary the one input it is examining and inherit everything else.
"""

from prd_bench_local_runner.testing.validators import get_success_data

from . import factories
from .api_client import api_client
from .constants import CLOCK_EPOCH
from .test_users import (
    SECOND_USERS,
    make_access_authority_headers,
    make_contractor_coordinator_headers,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_rad_protection_manager_headers,
    make_rad_protection_planner_headers,
    make_reactor_engineer_headers,
    make_regulatory_affairs_headers,
    make_station_admin_headers,
)
from .types import (
    BackgroundOutcome,
    Disposition,
    HoldPointType,
    ReservationPurpose,
    UserRole,
)


# ============================================================== tier 0: reads
def read_outage(outage_id, headers=None):
    return get_success_data(
        api_client.get_outage(outage_id, headers or make_outage_director_headers())
    )


def read_work_order(work_order_id, headers=None):
    return get_success_data(
        api_client.get_work_order(work_order_id, headers or make_outage_planner_headers())
    )


def read_activity(activity_id, headers=None):
    return get_success_data(
        api_client.get_schedule_activity(
            activity_id, headers or make_outage_planner_headers()
        )
    )


def read_pool(pool_id, headers=None):
    return get_success_data(
        api_client.get_spent_fuel_pool(pool_id, headers or make_reactor_engineer_headers())
    )


def read_pattern(pattern_id, headers=None):
    return get_success_data(
        api_client.get_core_load_pattern(
            pattern_id, headers or make_reactor_engineer_headers()
        )
    )


def read_reservation(reservation_id, headers=None):
    return get_success_data(
        api_client.get_pool_cell_reservation(
            reservation_id, headers or make_reactor_engineer_headers()
        )
    )


def read_worker(worker_id, headers=None):
    return get_success_data(
        api_client.get_supplemental_worker(
            worker_id, headers or make_contractor_coordinator_headers()
        )
    )


def read_rwp(rwp_id, headers=None):
    return get_success_data(
        api_client.get_rwp(rwp_id, headers or make_rad_protection_planner_headers())
    )


def read_emergent_item(item_id, headers=None):
    return get_success_data(
        api_client.get_emergent_item(item_id, headers or make_outage_planner_headers())
    )


def read_startup_test(test_id, headers=None):
    return get_success_data(
        api_client.get_startup_test(test_id, headers or make_regulatory_affairs_headers())
    )


def read_dose_rows(rwp_id, headers=None, **filters):
    response = api_client.list_dose_transactions(
        rwp_id, headers or make_rad_protection_planner_headers(), **filters
    )
    return get_success_data(response)


def outage_version(outage_id):
    return read_outage(outage_id)["version"]


def pool_version(pool_id):
    return read_pool(pool_id)["version"]


# =============================================== tier 1: plant configuration
def set_clock(instant=CLOCK_EPOCH):
    """PRD 2.4: the logical clock stamps created_at, updated_at,
    scope_locked_at, started_at and completed_at."""
    return get_success_data(
        api_client.set_current_utc(instant, make_station_admin_headers())
    )


def given_spent_fuel_pool(**overrides):
    payload = factories.create_spent_fuel_pool_payload(**overrides)
    return get_success_data(
        api_client.create_spent_fuel_pool(payload, make_station_admin_headers())
    )


def given_rad_area(**overrides):
    payload = factories.create_rad_area_payload(**overrides)
    return get_success_data(
        api_client.create_rad_area(payload, make_station_admin_headers())
    )


def given_safety_function(**overrides):
    payload = factories.create_safety_function_payload(**overrides)
    return get_success_data(
        api_client.create_safety_function(payload, make_station_admin_headers())
    )


# ================================================== tier 2: entity hierarchy
def given_outage(**overrides):
    payload = factories.create_outage_payload(**overrides)
    return get_success_data(api_client.create_outage(payload, make_station_admin_headers()))


def given_work_order(outage_id, **overrides):
    """A newly created work order lands in SCOPED (PRD 3.2)."""
    payload = factories.create_work_order_payload(**overrides)
    return get_success_data(
        api_client.create_work_order(outage_id, payload, make_outage_planner_headers())
    )


def given_planned_work_order(outage_id, **overrides):
    work_order = given_work_order(outage_id, **overrides)
    return get_success_data(
        api_client.plan_work_order(work_order["id"], make_outage_planner_headers())
    )


def given_approved_work_order(outage_id, **overrides):
    work_order = given_planned_work_order(outage_id, **overrides)
    return get_success_data(
        api_client.approve_work_order_scope(
            work_order["id"], make_outage_director_headers()
        )
    )


def given_schedule_activity(outage_id, **overrides):
    payload = factories.create_schedule_activity_payload(**overrides)
    return get_success_data(
        api_client.create_schedule_activity(
            outage_id, payload, make_outage_planner_headers()
        )
    )


def given_core_load_pattern(outage_id, **overrides):
    """PRD 2.7 requires expected_outage_version on this create, so the builder
    re-reads the outage and supplies the version that read returned."""
    payload = factories.create_core_load_pattern_payload(**overrides)
    payload.setdefault("expected_outage_version", outage_version(outage_id))
    return get_success_data(
        api_client.create_core_load_pattern(
            outage_id, payload, make_reactor_engineer_headers()
        )
    )


def given_approved_core_load_pattern(outage_id, **overrides):
    """PRD 2.10 bars self-approval, so the approver is a second reactor
    engineer identity."""
    pattern = given_core_load_pattern(outage_id, **overrides)
    return get_success_data(
        api_client.approve_core_load_pattern(
            pattern["id"],
            make_reactor_engineer_headers(SECOND_USERS[UserRole.REACTOR_ENGINEER]),
        )
    )


def given_pool_cell_reservation(outage_id, pool_id, **overrides):
    payload = factories.create_pool_cell_reservation_payload(**overrides)
    payload.setdefault("outage_id", outage_id)
    payload.setdefault("spent_fuel_pool_id", pool_id)
    payload.setdefault("expected_spent_fuel_pool_version", pool_version(pool_id))
    return get_success_data(
        api_client.create_pool_cell_reservation(payload, make_reactor_engineer_headers())
    )


def given_supplemental_worker(outage_id, **overrides):
    payload = factories.create_supplemental_worker_payload(**overrides)
    return get_success_data(
        api_client.create_supplemental_worker(
            outage_id, payload, make_contractor_coordinator_headers()
        )
    )


def given_draft_rwp(work_order_id, rad_area_id, **overrides):
    payload = factories.create_rwp_payload(**overrides)
    payload.setdefault("rad_area_id", rad_area_id)
    return get_success_data(
        api_client.draft_rwp(work_order_id, payload, make_rad_protection_planner_headers())
    )


def given_emergent_item(work_order_id, **overrides):
    payload = factories.create_emergent_item_payload(**overrides)
    return get_success_data(
        api_client.create_emergent_item(
            work_order_id, payload, make_outage_planner_headers()
        )
    )


def given_startup_test(outage_id, **overrides):
    payload = factories.create_startup_test_payload(**overrides)
    return get_success_data(
        api_client.create_startup_test(outage_id, payload, make_regulatory_affairs_headers())
    )


# ================================================ tier 3: lifecycle shortcuts
def given_planning_outage(outage=None, work_order=None, pattern=None, clock=CLOCK_EPOCH):
    """An outage in PLANNING that already satisfies both scope-lock
    preconditions of PRD 3.6: one APPROVED work order and one APPROVED core
    loading pattern."""
    if clock is not None:
        set_clock(clock)
    outage_row = given_outage(**(outage or {}))
    pattern_row = given_approved_core_load_pattern(outage_row["id"], **(pattern or {}))
    work_order_row = given_approved_work_order(outage_row["id"], **(work_order or {}))
    return {
        "outage": read_outage(outage_row["id"]),
        "outage_id": outage_row["id"],
        "pattern": pattern_row,
        "pattern_id": pattern_row["id"],
        "work_order": read_work_order(work_order_row["id"]),
        "work_order_id": work_order_row["id"],
    }


def given_scope_locked_outage(**kwargs):
    """Drives PLANNING -> SCOPE_LOCKED (PRD 3.6)."""
    ctx = given_planning_outage(**kwargs)
    get_success_data(
        api_client.lock_scope(ctx["outage_id"], make_outage_director_headers())
    )
    ctx["outage"] = read_outage(ctx["outage_id"])
    ctx["work_order"] = read_work_order(ctx["work_order_id"])
    return ctx


def given_executing_outage(**kwargs):
    """Drives SCOPE_LOCKED -> EXECUTION. PRD 3.6 gates this on
    badged_worker_count reaching required_badged_workers, which defaults to
    zero."""
    ctx = given_scope_locked_outage(**kwargs)
    get_success_data(
        api_client.commence_execution(ctx["outage_id"], make_outage_director_headers())
    )
    ctx["outage"] = read_outage(ctx["outage_id"])
    return ctx


def given_startup_outage(startup_test=None, **kwargs):
    """Drives EXECUTION -> STARTUP. PRD 3.6 requires at least one startup test
    and no work order left in SCOPED, PLANNED, APPROVED or EXECUTING, so the
    single approved work order is deferred before the gate is attempted."""
    ctx = given_executing_outage(**kwargs)
    test_row = given_startup_test(ctx["outage_id"], **(startup_test or {}))
    get_success_data(
        api_client.defer_work_order(
            ctx["work_order_id"],
            "Deferred to the next refueling window",
            make_outage_director_headers(),
        )
    )
    get_success_data(
        api_client.authorize_startup(ctx["outage_id"], make_outage_director_headers())
    )
    ctx["startup_test"] = read_startup_test(test_row["id"])
    ctx["startup_test_id"] = test_row["id"]
    ctx["outage"] = read_outage(ctx["outage_id"])
    ctx["work_order"] = read_work_order(ctx["work_order_id"])
    return ctx


def given_online_outage(measured_reactivity_pcm=500, **kwargs):
    """Drives STARTUP -> ONLINE. PRD 3.6 makes that hop automatic at the moment
    the last startup test reaches SATISFIED."""
    ctx = given_startup_outage(**kwargs)
    get_success_data(
        api_client.satisfy_startup_test(
            ctx["startup_test_id"],
            measured_reactivity_pcm,
            make_regulatory_affairs_headers(SECOND_USERS[UserRole.REGULATORY_AFFAIRS]),
        )
    )
    ctx["startup_test"] = read_startup_test(ctx["startup_test_id"])
    ctx["outage"] = read_outage(ctx["outage_id"])
    return ctx


# ================================= tier 4: accumulation and threshold targets
def given_badged_worker(outage_id, badge_number="B-1001", modules_completed=None, **overrides):
    """Walks the whole PRD 3.5 pipeline: request, both qualification branches,
    the join, then the badge."""
    worker = given_supplemental_worker(outage_id, **overrides)
    if modules_completed is None:
        modules_completed = read_outage(outage_id)["required_training_modules"]
    get_success_data(
        api_client.record_training_completion(
            worker["id"], modules_completed, make_access_authority_headers()
        )
    )
    get_success_data(
        api_client.record_background_result(
            worker["id"], BackgroundOutcome.CLEAR, make_access_authority_headers()
        )
    )
    return get_success_data(
        api_client.badge_worker(worker["id"], badge_number, make_access_authority_headers())
    )


def given_approved_rwp(work_order_id, rad_area_id, alara_review_reference=None, **overrides):
    """Drafts a permit and takes it DRAFT -> APPROVED (PRD 3.7). The owning
    outage must already be in SCOPE_LOCKED or EXECUTION."""
    permit = given_draft_rwp(work_order_id, rad_area_id, **overrides)
    if permit["alara_review_required"] and alara_review_reference is None:
        alara_review_reference = "ALARA-{}".format(permit["id"][:8])
    return get_success_data(
        api_client.approve_rwp(
            permit["id"],
            make_rad_protection_manager_headers(),
            alara_review_reference=alara_review_reference,
        )
    )


def given_reserved_cells(outage_id, pool_id, cells_requested, purpose=None, **overrides):
    """PRD 3.3: a CONTINGENCY reservation is admitted against cells_available
    while a DISCHARGE or FRESH_STAGING reservation is admitted against
    protected_cells_available."""
    return given_pool_cell_reservation(
        outage_id,
        pool_id,
        cells_requested=cells_requested,
        purpose=purpose or ReservationPurpose.CONTINGENCY,
        **overrides
    )


def given_started_activity(activity_id):
    """PRD 3.4: NOT_STARTED -> IN_PROGRESS, which also drags an APPROVED work
    order to EXECUTING."""
    return get_success_data(
        api_client.start_activity(activity_id, make_outage_planner_headers())
    )


def given_completed_activity(activity_id):
    """PRD 3.4: IN_PROGRESS -> COMPLETE, releasing successors on the
    constraint_status dimension."""
    given_started_activity(activity_id)
    return get_success_data(
        api_client.complete_activity(activity_id, make_outage_planner_headers())
    )


def given_disposed_emergent_item(item_id, disposition=None, disposition_note=None):
    return get_success_data(
        api_client.dispose_emergent_item(
            item_id,
            disposition or Disposition.APPROVED,
            make_outage_director_headers(),
            disposition_note=disposition_note,
        )
    )


# ============================================ tier 5: terminal state drives
def given_reviewed_outage(actual_duration_hours=780, actual_cost_usd=42000000, **kwargs):
    """Drives ONLINE -> REVIEWED, the terminal state of PRD 3.6."""
    ctx = given_online_outage(**kwargs)
    get_success_data(
        api_client.post_outage_review(
            ctx["outage_id"],
            factories.post_outage_review_payload(
                actual_duration_hours=actual_duration_hours,
                actual_cost_usd=actual_cost_usd,
            ),
            make_outage_director_headers(),
        )
    )
    ctx["outage"] = read_outage(ctx["outage_id"])
    return ctx


def given_regulatory_startup_test(outage_id, **overrides):
    """A REGULATORY hold point, which PRD 3.9 subjects both to the release
    reference requirement and to the two-person rule."""
    overrides.setdefault("hold_point_type", HoldPointType.REGULATORY)
    return given_startup_test(outage_id, **overrides)
