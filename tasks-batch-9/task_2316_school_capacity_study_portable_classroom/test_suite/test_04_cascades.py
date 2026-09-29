"""Four-deep cascades: the permit join downwards, the condemnation upwards."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import ASSET_HEADERS, OFFICIAL_HEADERS, PLANNER_HEADERS, SCHEDULER_HEADERS
from test_helpers.assertions import assert_budget_partition, assert_clock_stamp
from test_helpers.factories import condition_payload, permit_decision_payload
from test_helpers.fixtures import approve_all_permits, build_request_context


def _last_permit_approved(api):
    """A permit-pending request with only the electrical discipline outstanding."""
    ctx = build_request_context(api, stage="permit_pending",
                               unit_overrides={"asset_tag": "PU-7001"})
    approve_all_permits(api, ctx["request_id"], skip=("ELECTRICAL",))
    ctx["decision"] = validate_success(
        api.decide_permit(ctx["permit_ids"]["ELECTRICAL"],
                          permit_decision_payload("APPROVED"), OFFICIAL_HEADERS)
    )
    return ctx


def test_final_permit_approval_cascades_down_to_the_pad(api):
    """PRD §3.7: "A decision of `APPROVED` moves the permit `SUBMITTED → APPROVED`,
    stamps `approved_on` from the logical clock ... When, and only when, every permit of
    the request now stands `APPROVED`, the request joins on the favourable arm: it moves
    `PERMIT_PENDING → PERMITTED` ... the estimate is copied into the request's
    `encumbered_cost_cents`, added to the appropriation's `encumbered_cents`, and
    `uncommitted_cents` is recomputed. Third, the reserved unit moves `RESERVED →
    SCHEDULED`, and because the unit is now scheduled onto that pad, the pad's
    `occupied_by_unit_id` is set to the unit."

    Design: Difficulty/transitive_cascade/permit_join_cascade_to_pad_occupation
    """
    ctx = _last_permit_approved(api)

    assert ctx["decision"]["status"] == "APPROVED"
    assert_clock_stamp(ctx["decision"]["approved_on"], "2027-03-01T00:00:00Z")

    request = validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )
    assert request["status"] == "PERMITTED"
    assert request["encumbered_cost_cents"] == 7_741_440

    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=500_000_000, encumbered_cents=7_741_440, expended_cents=0,
        uncommitted_cents=492_258_560,
    )

    assert validate_success(
        api.get_portable_unit(ctx["unit_id"], PLANNER_HEADERS)
    )["allocation_status"] == "SCHEDULED"
    assert validate_success(
        api.get_placement_site(ctx["site_id"], PLANNER_HEADERS)
    )["occupied_by_unit_id"] == ctx["unit_id"]


def test_permit_cascade_stops_at_scheduled_and_does_not_install_the_unit(api):
    """PRD §3.9: "The allocation dimension is cyclic — `IN_STORAGE → RESERVED →
    SCHEDULED → INSTALLED → PENDING_REMOVAL → IN_STORAGE`". Only completion installs:
    PRD §3.7 gives the permit join no effect beyond `RESERVED → SCHEDULED`, and PRD §3.1
    opens a unit where the server "seeds `lifetime_relocation_count` from
    `prior_relocation_count`, leaves `current_school_id` null" — figures that the cascade
    must leave alone.

    Design: Difficulty/transitive_cascade/permit_join_cascade_to_pad_occupation
    """
    ctx = _last_permit_approved(api)

    unit = validate_success(api.get_portable_unit(ctx["unit_id"], PLANNER_HEADERS))
    assert unit["allocation_status"] == "SCHEDULED"
    assert unit["lifetime_relocation_count"] == 0
    assert unit["current_school_id"] is None

    school = validate_success(api.get_school(ctx["school_id"], PLANNER_HEADERS))
    assert school["hosted_portable_seats"] == 0


def _condemned_scheduled_unit(api):
    """A scheduled placement whose unit is condemned in a single inspection."""
    ctx = build_request_context(api, stage="scheduled",
                               unit_overrides={"asset_tag": "PU-8001"})
    ctx["condition"] = validate_success(
        api.record_condition(ctx["unit_id"], condition_payload("UNSAFE", "D"),
                             ASSET_HEADERS)
    )
    return ctx


def test_condemnation_withdraws_the_request_and_cancels_its_schedule(api):
    """PRD §3.9: "Declaring a unit `UNSAFE` ... fires the withdrawal cascade in three
    linked steps. First, because the unit is now unsafe, every placement request
    referencing it whose status is `DRAFT`, `SITE_ASSESSED`, `PERMIT_PENDING`,
    `PERMITTED` or `SCHEDULED` moves to `WITHDRAWN` with `rejection_reason` recorded as
    `UNIT_UNSAFE` ... Second ... every installation schedule of that request whose
    status is `PLANNED` or `IN_PROGRESS` moves to `CANCELLED` with `cancellation_reason`
    recorded as `UNIT_UNSAFE`."

    Design: Difficulty/transitive_cascade/unsafe_condition_cascade_to_pad_release
    """
    ctx = _condemned_scheduled_unit(api)

    assert ctx["condition"]["condition_status"] == "UNSAFE"
    assert ctx["condition"]["condition_grade"] == "D"

    request = validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )
    assert request["status"] == "WITHDRAWN"
    assert request["rejection_reason"] == "UNIT_UNSAFE"

    schedule = validate_success(
        api.get_installation_schedule(ctx["schedule_id"], SCHEDULER_HEADERS)
    )
    assert schedule["status"] == "CANCELLED"
    assert schedule["cancellation_reason"] == "UNIT_UNSAFE"


def test_condemnation_releases_the_encumbrance_frees_the_pad_and_restores_storage(api):
    """PRD §3.9: "its `encumbered_cost_cents` is released back out of the
    appropriation's `encumbered_cents` and zeroed, `uncommitted_cents` is recomputed ...
    Third, because each of those schedules was cancelled, the pad of the request
    releases its hold by clearing `occupied_by_unit_id`, and the unit's
    `allocation_status` returns to `IN_STORAGE` with `current_school_id` cleared". PRD
    §3.9 also holds the two dimensions apart: "`condition_status` records serviceability
    and moves only when an `AssetManager` records an inspection. `allocation_status`
    records where the unit stands in the allocation lifecycle".

    Design: Difficulty/transitive_cascade/unsafe_condition_cascade_to_pad_release
    """
    ctx = _condemned_scheduled_unit(api)

    request = validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )
    assert request["encumbered_cost_cents"] == 0

    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=500_000_000, encumbered_cents=0, expended_cents=0,
        uncommitted_cents=500_000_000,
    )

    assert validate_success(
        api.get_placement_site(ctx["site_id"], PLANNER_HEADERS)
    )["occupied_by_unit_id"] is None

    unit = validate_success(api.get_portable_unit(ctx["unit_id"], PLANNER_HEADERS))
    assert unit["allocation_status"] == "IN_STORAGE"
    assert unit["condition_status"] == "UNSAFE"
    assert unit["current_school_id"] is None

    school = validate_success(api.get_school(ctx["school_id"], PLANNER_HEADERS))
    assert school["hosted_portable_seats"] == 0
