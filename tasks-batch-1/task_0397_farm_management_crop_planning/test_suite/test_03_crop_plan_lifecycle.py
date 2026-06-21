"""Crop-plan lifecycle: revision cycle, approval guards, transition preconditions,
terminal lockdown, and optimistic concurrency on parcel version.

Difficulty queue A: non_linear_state_machine (revision cycle),
boundary_precision_check (zero-planting begin-growing),
cross_entity_state_dependency (approve depends on parcel AVAILABLE).
Corner queue B: state_machines (close/abandon/request-revision), validations
(planned_acres exceed), cross_cutting_complexity_layers (OCC stale/fresh).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_parcel, create_draft_plan, create_and_approve_plan,
    setup_growing_plan, setup_confirmed_restricted_application,
    record_planting, create_seed_product, create_input_lot,
)

FM = TEST_USERS["farm_manager_headers"]
AG = TEST_USERS["agronomist_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine — crop_plan_revision_cycle_increments_count
# ===========================================================================
def test_revision_cycle_increments_count_to_two(api):
    """PRD §3.1: "A plan may cycle `APPROVED → UNDER_REVISION → APPROVED` any number of
    times; `revision_count` records how many loops it has taken."
    PRD §3.1: "Each such trip increments the plan's `revision_count` by one".

    Design: Difficulty/non_linear_state_machine/crop_plan_revision_cycle_increments_count
    """
    parcel = create_parcel(name="Cycle Field", acreage=50.0)
    plan = create_draft_plan(parcel["id"], crop="CORN", planned_acres=40.0)
    # loop 1: approve, request-revision
    validate_success(api.approve_crop_plan(plan["id"], {"expected_parcel_version": parcel["version"]}, FM))
    validate_success(api.request_revision(plan["id"], AG))
    # loop 2: re-read parcel version, approve, request-revision
    pv = validate_success(api.get_parcel(parcel["id"], FM))["version"]
    validate_success(api.approve_crop_plan(plan["id"], {"expected_parcel_version": pv}, FM))
    validate_success(api.request_revision(plan["id"], AG))

    data = validate_success(api.get_crop_plan(plan["id"], FM))
    assert data["revision_count"] == 2, f"expected revision_count 2, got {data['revision_count']}"
    assert data["status"] == "UNDER_REVISION", f"expected UNDER_REVISION, got {data['status']}"


def test_revision_cycle_first_loop_sets_count_one_and_state(api):
    """PRD §3.1: "Requesting a revision moves the plan from `APPROVED` to
    `UNDER_REVISION`, provided no `PlantingEvent` with `status` `RECORDED` exists for the
    plan". PRD §3.1: "Each such trip increments the plan's `revision_count` by one".

    Design: Difficulty/non_linear_state_machine/crop_plan_revision_cycle_increments_count
    """
    parcel = create_parcel(name="Cycle One", acreage=50.0)
    plan = create_draft_plan(parcel["id"], crop="CORN", planned_acres=40.0)
    validate_success(api.approve_crop_plan(plan["id"], {"expected_parcel_version": parcel["version"]}, FM))
    revised = validate_success(api.request_revision(plan["id"], AG))
    assert revised["status"] == "UNDER_REVISION", f"expected UNDER_REVISION, got {revised['status']}"
    assert revised["revision_count"] == 1, f"expected revision_count 1, got {revised['revision_count']}"


# ===========================================================================
# Difficulty: boundary_precision_check — begin_growing_zero_planted_acres_empty_set
# ===========================================================================
def test_begin_growing_zero_planted_acres_rejected(api):
    """PRD §3.2: "This transition requires that `planted_acres` be greater than zero —
    that is, at least one `RECORDED` `PlantingEvent` exists — failing which it is
    rejected with `ERR_NO_PLANTING_RECORDED`."

    Design: Difficulty/boundary_precision_check/begin_growing_zero_planted_acres_empty_set_boundary
    """
    parcel = create_parcel(name="ZeroPlant", acreage=50.0)
    plan, _ = create_and_approve_plan(parcel, crop="CORN", planned_acres=40.0)
    resp = api.begin_growing(plan["id"], AG)
    validate_error(resp, ApiErrorId.ERR_NO_PLANTING_RECORDED.value)
    data = validate_success(api.get_crop_plan(plan["id"], FM))
    assert data["planted_acres"] == 0, f"planted_acres must be 0, got {data['planted_acres']}"


def test_begin_growing_succeeds_after_one_planting(api):
    """PRD §3.2: "Once a plan is `APPROVED` and seed is in the ground, an `Agronomist`
    begins growth, advancing the plan from `APPROVED` to `GROWING`. This transition
    requires that `planted_acres` be greater than zero — that is, at least one `RECORDED`
    `PlantingEvent` exists".

    Design: Difficulty/boundary_precision_check/begin_growing_zero_planted_acres_empty_set_boundary
    """
    parcel = create_parcel(name="OnePlant", acreage=50.0)
    plan, _ = create_and_approve_plan(parcel, crop="CORN", planned_acres=40.0)
    seed = create_seed_product()
    lot = create_input_lot(seed["id"], quantity_received=200.0)
    record_planting(plan["id"], lot["id"], acres_planted=40.0, seed_rate_per_acre=1.0)
    data = validate_success(api.begin_growing(plan["id"], AG))
    assert data["status"] == "GROWING", f"expected GROWING, got {data['status']}"


# ===========================================================================
# Difficulty: cross_entity_state_dependency — plan_approve_depends_on_parcel_available
# ===========================================================================
def test_approve_blocked_when_parcel_restricted(api):
    """PRD §3.1: "The parcel's `status` must be `AVAILABLE`, or the request is rejected
    with `ERR_PARCEL_NOT_AVAILABLE`."
    PRD §3.4: "The parcel's `status` is set to `RESTRICTED`" (on a confirmed restricted
    application).

    Design: Difficulty/cross_entity_state_dependency/plan_approve_depends_on_parcel_available
    """
    # Plan A confirmed a restricted application -> parcel RESTRICTED.
    ctx = setup_confirmed_restricted_application(
        reentry_interval_hours=72, preharvest_interval_days=5,
        confirm_clock="2026-06-10T00:00:00Z", initial_clock="2026-06-10T00:00:00Z",
        acres_treated=40.0)
    parcel = ctx["parcel"]
    parcel_now = validate_success(api.get_parcel(parcel["id"], FM))
    assert parcel_now["status"] == "RESTRICTED", f"parcel must be RESTRICTED, got {parcel_now['status']}"

    # Fresh DRAFT plan B on the same restricted parcel; approve must fail.
    plan_b = create_draft_plan(parcel["id"], crop="SOY", planned_acres=50.0)
    resp = api.approve_crop_plan(
        plan_b["id"], {"expected_parcel_version": parcel_now["version"]}, FM)
    validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_AVAILABLE.value)


def test_approve_succeeds_when_parcel_available(api):
    """PRD §3.1: "Approval is a `FarmManager` action that moves a plan from `DRAFT` to
    `APPROVED`."
    PRD §3.1: "The parcel's `status` must be `AVAILABLE`, or the request is rejected with
    `ERR_PARCEL_NOT_AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/plan_approve_depends_on_parcel_available
    """
    parcel = create_parcel(name="Avail Field", acreage=100.0)
    plan = create_draft_plan(parcel["id"], crop="CORN", planned_acres=50.0)
    data = validate_success(api.approve_crop_plan(
        plan["id"], {"expected_parcel_version": parcel["version"]}, FM))
    assert data["status"] == "APPROVED", f"expected APPROVED, got {data['status']}"


# ===========================================================================
# Corner: state_machines / validations on the crop-plan machine
# ===========================================================================
def test_close_plan_from_growing_invalid_state(api):
    """PRD §3.3: "Closing is the final act, performed by a `FarmManager`, moving the plan
    from `HARVESTING` to `CLOSED`." PRD §2.10: "the target resource must be in a state
    from which the requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/close_plan_from_growing_invalid_state
    """
    ctx = setup_growing_plan(crop="CORN", planned_acres=40.0, acreage=50.0)
    resp = api.close_crop_plan(ctx["plan"]["id"], FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_abandoned_plan_cannot_be_approved(api):
    """PRD §3.1: "`CLOSED` and `ABANDONED` are terminal." PRD §2.10: "the target
    resource must be in a state from which the requested transition is defined, else
    `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/abandoned_plan_terminal_lockdown
    """
    parcel = create_parcel(name="AB", acreage=50.0)
    plan = create_draft_plan(parcel["id"], crop="CORN", planned_acres=40.0)
    validate_success(api.abandon_crop_plan(plan["id"], FM))
    resp = api.approve_crop_plan(plan["id"], {"expected_parcel_version": parcel["version"]}, FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_request_revision_blocked_after_planting(api):
    """PRD §3.1: "Requesting a revision moves the plan from `APPROVED` to
    `UNDER_REVISION`, provided no `PlantingEvent` with `status` `RECORDED` exists for the
    plan; if one does, the request is rejected with `ERR_PLAN_ALREADY_PLANTED`."

    Design: Corner/state_machines/request_revision_blocked_after_planting
    """
    parcel = create_parcel(name="RR", acreage=50.0)
    plan, _ = create_and_approve_plan(parcel, crop="CORN", planned_acres=40.0)
    seed = create_seed_product()
    lot = create_input_lot(seed["id"], quantity_received=200.0)
    record_planting(plan["id"], lot["id"], acres_planted=40.0, seed_rate_per_acre=1.0)
    resp = api.request_revision(plan["id"], AG)
    validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_PLANTED.value)


def test_planned_acres_exceed_parcel_on_approve(api):
    """PRD §3.1: "The plan's `planned_acres` must not exceed the parcel's `acreage`, or
    it is rejected with `ERR_PLANNED_ACRES_EXCEED_PARCEL`."

    Design: Corner/validations/planned_acres_exceed_parcel_on_approve
    """
    parcel = create_parcel(name="PA", acreage=100.0)
    plan = create_draft_plan(parcel["id"], crop="CORN", planned_acres=120.0)
    resp = api.approve_crop_plan(
        plan["id"], {"expected_parcel_version": parcel["version"]}, FM)
    validate_error(resp, ApiErrorId.ERR_PLANNED_ACRES_EXCEED_PARCEL.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers — OCC on parcel version
# ===========================================================================
def test_occ_stale_parcel_version_on_approve(api):
    """PRD §2.6: "If `expected_parcel_version` does not equal the parcel's current
    `version` at the moment of approval, the request is rejected with
    `ERR_STALE_PARCEL_VERSION` (HTTP 412), and no state changes."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_parcel_version_on_approve
    """
    parcel = create_parcel(name="OCC", acreage=200.0)
    v1 = parcel["version"]
    plan_a = create_draft_plan(parcel["id"], crop="CORN", planned_acres=80.0)
    plan_b = create_draft_plan(parcel["id"], crop="SOY", planned_acres=80.0)
    # Plan A approve bumps the parcel version past v1.
    validate_success(api.approve_crop_plan(plan_a["id"], {"expected_parcel_version": v1}, FM))
    # Plan B approve with the now-stale v1 must fail.
    resp = api.approve_crop_plan(plan_b["id"], {"expected_parcel_version": v1}, FM)
    validate_error(resp, ApiErrorId.ERR_STALE_PARCEL_VERSION.value)


def test_occ_fresh_parcel_version_succeeds(api):
    """PRD §2.6: "the approve request must carry `expected_parcel_version`, a non-optional
    field whose value is the parcel's `version` as the client last read it."
    PRD §3.1: "A successful approval recomputes the parcel's `active_crop_plan_count` — the
    number of plans on that parcel whose `status` is `APPROVED`, `GROWING`, or
    `HARVESTING` — and increments the parcel's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_parcel_version_succeeds
    """
    parcel = create_parcel(name="OCC2", acreage=200.0)
    v1 = parcel["version"]
    plan_a = create_draft_plan(parcel["id"], crop="CORN", planned_acres=80.0)
    plan_b = create_draft_plan(parcel["id"], crop="SOY", planned_acres=80.0)
    validate_success(api.approve_crop_plan(plan_a["id"], {"expected_parcel_version": v1}, FM))
    v2 = validate_success(api.get_parcel(parcel["id"], FM))["version"]
    # Plan B approve with the fresh version succeeds.
    data_b = validate_success(api.approve_crop_plan(plan_b["id"], {"expected_parcel_version": v2}, FM))
    assert data_b["status"] == "APPROVED", f"expected APPROVED, got {data_b['status']}"
    parcel_final = validate_success(api.get_parcel(parcel["id"], FM))
    assert parcel_final["version"] == 3, f"expected parcel.version 3, got {parcel_final['version']}"
    assert parcel_final["active_crop_plan_count"] == 2, (
        f"expected 2 active plans, got {parcel_final['active_crop_plan_count']}")
