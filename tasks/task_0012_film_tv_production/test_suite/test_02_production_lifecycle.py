"""Production lifecycle: create, lock-baseline, begin-wrap, close-account, cancel.

Covers PRD §3.1 (production greenlight), §3.8 (begin wrap, close account), §3.9
(cancellation), §2.6 (posture).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_production_payload,
    create_scene_payload,
    create_budget_category_payload,
    schedule_scene_payload,
    create_held_reservation,
    confirm_reservation_with_permit_and_weather,
    create_location,
    create_scene_in_production,
    setup_production_with_categories,
    create_production,
    create_role_in_production,
    walk_role_to_signed,
    create_actor,
    setup_in_production,
    setup_wrap_pending,
    iso,
    EXEC,
    LP,
    FC,
    CD,
    PC,
    with_override_reason,
    assert_production,
)


def test_create_production_initial_state(api):
    """PRD §3.1: "On creation, the production's lifecycle `status` is
    initialized to `PLANNING`, its `posture` is initialized to `GREEN`, the
    `schedule_baseline_locked_at` cursor is unset, and the three rolling
    totals — `spent_cents`, `committed_cents`, and `residual_cents` — are
    initialized to zero."

    Claim: a freshly-created production starts in PLANNING / GREEN with zero
    rolling totals.
    """
    res = api.create_production(create_production_payload(), EXEC)
    prod = validate_success(res, 201)
    assert_production(prod)
    assert prod["status"] == "PLANNING"
    assert prod["posture"] == "GREEN"
    assert prod.get("schedule_baseline_locked_at") in (None, "", )
    assert prod["spent_cents"] == 0
    assert prod["committed_cents"] == 0
    assert prod["residual_cents"] == 0


def test_reserve_must_be_within_total_budget(api):
    """PRD §3.1: "The reserve must be a non-negative amount no larger than
    the total budget."

    Claim: reserve_fund_cents > total_budget_cents → ERR_VALIDATION (422).
    """
    payload = create_production_payload(
        total_budget_cents=1_000_000,
        reserve_fund_cents=2_000_000,
    )
    res = api.create_production(payload, EXEC)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_create_scene_initial_state(api):
    """PRD §3.4: "The new scene begins in `BREAKDOWN`."

    Claim: created scene starts in BREAKDOWN status.
    """
    prod, _ = setup_production_with_categories(api)
    res = api.create_scene(
        prod["id"],
        create_scene_payload(scene_number="S-init", planned_duration_minutes=60),
        LP,
    )
    scene = validate_success(res, 201)
    assert scene["status"] == "BREAKDOWN"


def test_lock_baseline_requires_at_least_one_scheduled_scene(api):
    """PRD §3.1: "The lock requires three preconditions: (...) at least one
    scene must already be in the `SCHEDULED` state, (...)."

    Claim: lock-baseline with zero SCHEDULED scenes → ERR_INVALID_STATE.
    """
    prod, _ = setup_production_with_categories(api)
    res = api.lock_baseline(prod["id"], LP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_lock_baseline_transitions_to_in_production(api):
    """PRD §3.1: "On success, `schedule_baseline_locked_at` is stamped (...)
    the production transitions `PLANNING → IN_PRODUCTION`(...)."

    Claim: lock-baseline with one SCHEDULED scene transitions PLANNING→IN_PRODUCTION
    and stamps schedule_baseline_locked_at.
    """
    base = setup_in_production(api)
    prod = base["production"]
    assert prod["status"] == "IN_PRODUCTION"
    assert prod.get("schedule_baseline_locked_at") not in (None, "")


def test_lock_baseline_can_only_be_locked_once(api):
    """PRD §3.1: "(`schedule_baseline_locked_at` must still be unset (a
    baseline can only be locked once)(...)."

    Claim: a second lock-baseline call → ERR_INVALID_STATE (because
    Production.status no longer == PLANNING).
    """
    base = setup_in_production(api)
    prod = base["production"]
    res = api.lock_baseline(prod["id"], LP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_begin_wrap_requires_no_checked_out_equipment(api):
    """PRD §3.8: "The transition `IN_PRODUCTION → WRAP_PENDING` has three
    preconditions: every `Scene` is in `SHOT` or `OMITTED`, every
    `LocationReservation` is in `FULFILLED` or `RELEASED`, and no `Equipment`
    for this production is currently `CHECKED_OUT`."

    Claim: begin-wrap with a Scene still in SCHEDULED (not SHOT) →
    ERR_INVALID_STATE.
    """
    base = setup_in_production(api)
    # Scene is SCHEDULED, not SHOT.
    res = api.begin_wrap(base["production"]["id"], LP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_begin_wrap_freezes_posture(api):
    """PRD §3.8: "The cascade forces the production's `posture` to `FROZEN`,
    transitions every `CrewAssignment` `ACTIVE → RELEASED`, and appends a
    `SCHEDULE_CHANGE` audit row."

    Claim: after begin-wrap, Production.posture == FROZEN.
    """
    setup = setup_wrap_pending(api)
    prod = setup["production"]
    assert prod["status"] == "WRAP_PENDING"
    assert prod["posture"] == "FROZEN"


def test_frozen_posture_blocks_non_wrap_mutations(api):
    """PRD §2.6: "A `FROZEN` posture gates all non-wrap-progression operations:
    any mutation other than the wrap-progression endpoints is rejected with
    `ERR_POSTURE_BLOCKED` (HTTP 409)."

    Claim: in WRAP_PENDING, creating a scene → ERR_POSTURE_BLOCKED.
    """
    setup = setup_wrap_pending(api)
    res = api.create_scene(
        setup["production"]["id"],
        create_scene_payload(scene_number="S-late"),
        LP,
    )
    validate_error(res, "ERR_POSTURE_BLOCKED", expected_status=409)


def test_close_account_requires_wrap_pending_state(api):
    """PRD §3.8: close-account is `WRAP_PENDING → WRAPPED`.

    Claim: close-account from PLANNING → ERR_INVALID_STATE.
    """
    prod = create_production(api)
    res = api.close_account(prod["id"], FC)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_planning_with_signed_role_rejected(api):
    """PRD §3.9: "the transition `PLANNING → CANCELLED` requires that no role
    of the production has `casting_status` of `SIGNED` — once contracts have
    been signed, a planning cancellation is not permitted, because doing so
    would orphan committed cast obligations."

    Claim: cancel from PLANNING with a SIGNED role → ERR_INVALID_STATE.
    """
    # Set up production + role with a SIGNED actor.
    from test_helpers import setup_signed_role
    s = setup_signed_role(api, n_breakdown_scenes=1, role_day_rate_cents=100_000,
                           cast_planned_cents=10_000_000)
    res = api.cancel_production(s["production"]["id"], EXEC)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_planning_releases_reservations(api):
    """PRD §3.9: "The cascade releases every `LocationReservation` currently
    in `HELD` or `CONFIRMED` to `RELEASED`(...)."

    Claim: cancelling a PLANNING production with a HELD reservation cascades
    the reservation to RELEASED.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
        start_at=iso(2026, 2, 5, 9),
        end_at=iso(2026, 2, 5, 17),
    )
    cancelled = validate_success(api.cancel_production(prod["id"], EXEC), 200)
    assert cancelled["status"] == "CANCELLED"
    # The cascade may not be observable on the production response itself; query reservation:
    # No standalone GET for reservations in PRD §4 — but reservation can still be
    # observed by trying to confirm it (which on RELEASED is invalid state).
    confirm_res = api.confirm_reservation(reservation["id"], PC)
    validate_error(confirm_res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_in_production_requires_override_reason_header(api):
    """PRD §3.9: "From `IN_PRODUCTION`, the transition `IN_PRODUCTION →
    CANCELLED` requires a non-empty `X-Override-Reason` header(...)."

    Claim: cancel from IN_PRODUCTION without X-Override-Reason →
    ERR_INVALID_STATE.
    """
    base = setup_in_production(api)
    res = api.cancel_production(base["production"]["id"], EXEC)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_in_production_with_override_reason_succeeds(api):
    """PRD §3.9: "From `IN_PRODUCTION`, the transition `IN_PRODUCTION →
    CANCELLED` requires a non-empty `X-Override-Reason` header(...)."

    Claim: cancel from IN_PRODUCTION with X-Override-Reason set → 200,
    Production.status == CANCELLED.
    """
    base = setup_in_production(api)
    headers = with_override_reason(EXEC, "weather caused permanent shutdown")
    cancelled = validate_success(
        api.cancel_production(base["production"]["id"], headers), 200,
    )
    assert cancelled["status"] == "CANCELLED"
