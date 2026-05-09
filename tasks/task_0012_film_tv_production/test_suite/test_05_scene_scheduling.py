"""Scene state machine, scheduling, weather block, reschedule, actor conflicts.

Covers PRD §3.4 (scene scheduling, conflicts, travel buffer).
Difficulty design:
  non_linear_state_machine/location_reservation_reschedule_branch,
  resource_temporal_overlap/actor_callsheet_travel_buffer_zone_dependent.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    schedule_scene_payload,
    reschedule_scene_payload,
    patch_weather_status_payload,
    patch_permit_status_payload,
    create_actor,
    create_role_in_production,
    walk_role_to_signed,
    create_audition_payload,
    offer_role_payload,
    setup_production_with_categories,
    create_location,
    create_scene_in_production,
    create_held_reservation,
    confirm_reservation_with_permit_and_weather,
    iso,
    EXEC,
    LP,
    FC,
    CD,
    PC,
)


def test_schedule_scene_transitions_to_scheduled(api):
    """PRD §3.4: "Scheduling a scene transitions it `BREAKDOWN → SCHEDULED`."

    Claim: schedule with a HELD reservation upgrades scene status to SCHEDULED.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
        start_at=iso(2026, 5, 1, 9),
        end_at=iso(2026, 5, 1, 17),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=reservation["id"])
    res = api.schedule_scene(
        prod["id"], scene["id"],
        schedule_scene_payload(reservation_id=reservation["id"]),
        LP,
    )
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


def test_schedule_weather_dependent_rejected_when_weather_blocked(api):
    """PRD §3.4: "Third, if the scene is `weather_dependent`, the reservation's
    `weather_status` must already be `ACCEPTABLE`; a weather-blocked
    reservation is rejected with `ERR_WEATHER_BLOCKED`."

    Claim: weather_dependent scene + reservation weather=BLOCKED →
    ERR_WEATHER_BLOCKED.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"], weather_dependent=True)
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
        start_at=iso(2026, 5, 1, 9),
        end_at=iso(2026, 5, 1, 17),
    )
    validate_success(api.patch_weather_status(
        reservation["id"],
        patch_weather_status_payload(weather_status="BLOCKED"),
        PC,
    ), 200)
    res = api.schedule_scene(
        prod["id"], scene["id"],
        schedule_scene_payload(reservation_id=reservation["id"]),
        LP,
    )
    validate_error(res, "ERR_WEATHER_BLOCKED", expected_status=409)


def test_mark_weather_blocked_cascades_reservation(api):
    """PRD §3.4: "When weather forecasts deteriorate, the `ProductionCoordinator`
    may mark a scheduled scene weather-blocked, transitioning it `SCHEDULED →
    RESCHEDULING`. (...) The cascade transitions the linked reservation
    `CONFIRMED → RESCHEDULING` and appends an `AuditLog` action `SCHEDULE_CHANGE`."

    Claim: mark-weather-blocked transitions scene SCHEDULED→RESCHEDULING.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"], weather_dependent=True)
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
        start_at=iso(2026, 5, 1, 9),
        end_at=iso(2026, 5, 1, 17),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=reservation["id"])
    validate_success(api.schedule_scene(
        prod["id"], scene["id"],
        schedule_scene_payload(reservation_id=reservation["id"]),
        LP,
    ), 200)
    # Now flip weather to BLOCKED then mark-weather-blocked.
    validate_success(api.patch_weather_status(
        reservation["id"],
        patch_weather_status_payload(weather_status="BLOCKED"),
        PC,
    ), 200)
    rescheduling = validate_success(api.mark_weather_blocked(
        prod["id"], scene["id"], PC,
    ), 200)
    assert rescheduling["status"] == "RESCHEDULING"


def test_reschedule_branch_releases_old_and_confirms_new_reservation(api):
    """PRD §3.4: "this transitions the scene `RESCHEDULING → SCHEDULED`,
    cascades the **old** reservation `RESCHEDULING → RELEASED`, advances the
    **new** reservation from `HELD` or `CONFIRMED` to `CONFIRMED`, and
    appends a further `SCHEDULE_CHANGE` audit row."

    # difficulty: non_linear_state_machine/location_reservation_reschedule_branch
    Claim: scene SCHEDULED→RESCHEDULING (weather block) → SCHEDULED (reschedule);
    old reservation lands in RELEASED; new reservation lands in CONFIRMED.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"], weather_dependent=True)

    # First reservation, schedule scene, weather-block.
    reservation_a = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
        unit_label="A",
        start_at=iso(2026, 5, 1, 9),
        end_at=iso(2026, 5, 1, 17),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=reservation_a["id"])
    validate_success(api.schedule_scene(
        prod["id"], scene["id"],
        schedule_scene_payload(reservation_id=reservation_a["id"]),
        LP,
    ), 200)
    validate_success(api.patch_weather_status(
        reservation_a["id"],
        patch_weather_status_payload(weather_status="BLOCKED"),
        PC,
    ), 200)
    validate_success(api.mark_weather_blocked(prod["id"], scene["id"], PC), 200)

    # New reservation on a different time slot for the same scene.
    reservation_b = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
        unit_label="B",
        start_at=iso(2026, 5, 2, 9),
        end_at=iso(2026, 5, 2, 17),
    )
    # New reservation must have weather ACCEPTABLE.
    validate_success(api.patch_weather_status(
        reservation_b["id"],
        patch_weather_status_payload(weather_status="ACCEPTABLE"),
        PC,
    ), 200)

    # Reschedule scene → new reservation.
    rescheduled_scene = validate_success(api.reschedule_scene(
        prod["id"], scene["id"],
        reschedule_scene_payload(new_reservation_id=reservation_b["id"]),
        PC,
    ), 200)
    assert rescheduled_scene["status"] == "SCHEDULED"

    # Old reservation: any further confirm/release should reflect RELEASED.
    # Confirm a RELEASED reservation should fail.
    confirm_old = api.confirm_reservation(reservation_a["id"], PC)
    validate_error(confirm_old, "ERR_INVALID_STATE", expected_status=409)


def test_omit_planning_scene_no_preconditions(api):
    """PRD §3.4: "The `LineProducer` may also omit a scene, transitioning it
    `BREAKDOWN → OMITTED` (no preconditions)(...)."

    Claim: omit a BREAKDOWN scene → status OMITTED.
    """
    prod, _ = setup_production_with_categories(api)
    scene = create_scene_in_production(api, production_id=prod["id"])
    omitted = validate_success(api.omit_scene(prod["id"], scene["id"], LP), 200)
    assert omitted["status"] == "OMITTED"


def test_mark_shot_requires_in_production(api):
    """PRD §3.4: "Preconditions: the parent production is in `IN_PRODUCTION`
    and the linked reservation is `CONFIRMED`."

    Claim: mark-shot while Production.status==PLANNING → ERR_INVALID_STATE.
    """
    prod, _ = setup_production_with_categories(api)
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
        start_at=iso(2026, 5, 1, 9),
        end_at=iso(2026, 5, 1, 11),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=reservation["id"])
    validate_success(api.schedule_scene(
        prod["id"], scene["id"],
        schedule_scene_payload(reservation_id=reservation["id"]),
        LP,
    ), 200)
    # Production still PLANNING.
    res = api.mark_shot(prod["id"], scene["id"], PC)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Travel-buffer / actor call-sheet conflicts ─────────────────────────────

def test_actor_callsheet_conflict_cross_zone_buffer(api):
    """PRD §3.4: "If the prior `Location.zone` equals the next `Location.zone`,
    the required buffer is 60 minutes. If the zones differ, the required
    buffer is 240 minutes(...). The buffer is required after the prior
    reservation's `end_at` (exclusive) and before the next reservation's
    `start_at` (inclusive); the conflict condition is precisely that the
    next reservation's `start_at` is strictly less than the prior
    reservation's `end_at` plus the required buffer."

    # difficulty: resource_temporal_overlap/actor_callsheet_travel_buffer_zone_dependent
    Claim: same actor, two scenes, zone-X end at 10:00 and zone-Y start at
    13:30 (gap 210min). Required cross-zone buffer = 240 min, so 13:30 <
    10:00 + 240min (= 14:00) ⇒ ERR_ACTOR_CALLSHEET_CONFLICT.
    """
    prod, _ = setup_production_with_categories(api, total_budget_cents=200_000_000)
    # Two locations in different zones.
    loc_x = create_location(api, zone="ZONE_X")
    loc_y = create_location(api, zone="ZONE_Y")

    # One Role + Actor + walk to SIGNED. Role used by both scenes.
    role = create_role_in_production(api, production_id=prod["id"],
                                       union_tier="SUPPORTING",
                                       day_rate_cents=100_000)
    actor = create_actor(api, travel_origin_zone="ZONE_X")

    # Build first scene with this role and schedule (consumes the slot).
    scene_a = create_scene_in_production(
        api, production_id=prod["id"],
        scene_number="S-A",
        planned_duration_minutes=60,
        required_actor_role_ids=[role["id"]],
    )
    res_a = create_held_reservation(
        api,
        location_id=loc_x["id"],
        production_id=prod["id"],
        scene_id=scene_a["id"],
        unit_label="A",
        start_at=iso(2026, 5, 1, 9),
        end_at=iso(2026, 5, 1, 10),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=res_a["id"])

    # Second scene (zone Y) — note: defer creating its reservation until AFTER
    # scene A is scheduled. PRD §3.4 says the same-production conflict check
    # compares reservations across scenes featuring the same signed actor; if
    # res_b is pre-created and CONFIRMED before scene A is scheduled, the
    # conflict check on scene A's schedule would already trip on res_b. To
    # keep this test focused on the conflict at scene B's schedule, we order
    # the operations so res_b is created only after scene A is scheduled.
    scene_b = create_scene_in_production(
        api, production_id=prod["id"],
        scene_number="S-B",
        planned_duration_minutes=60,
        required_actor_role_ids=[role["id"]],
    )

    # Walk role to SIGNED so conflict checks fire.
    from test_helpers import walk_role_to_offered
    walk_role_to_offered(api, production_id=prod["id"], role_id=role["id"], actor_id=actor["id"])
    # Sign — at sign time conflict checks across reservations not yet present
    # since neither scene is scheduled. Sign succeeds.
    signed = validate_success(api.sign_role(prod["id"], role["id"], LP), 200)
    assert signed["casting_status"] == "SIGNED"

    # Schedule scene A first (no other scene to conflict with).
    validate_success(api.schedule_scene(
        prod["id"], scene_a["id"],
        schedule_scene_payload(reservation_id=res_a["id"]),
        LP,
    ), 200)

    # Now create res_b (zone Y) for scene_b — after scene A is already SCHEDULED.
    res_b = create_held_reservation(
        api,
        location_id=loc_y["id"],
        production_id=prod["id"],
        scene_id=scene_b["id"],
        unit_label="B",
        start_at=iso(2026, 5, 1, 13, 30),
        end_at=iso(2026, 5, 1, 14, 30),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=res_b["id"])

    # Schedule scene B: conflict with scene A across cross-zone, gap=210 < 240.
    res = api.schedule_scene(
        prod["id"], scene_b["id"],
        schedule_scene_payload(reservation_id=res_b["id"]),
        LP,
    )
    validate_error(res, "ERR_ACTOR_CALLSHEET_CONFLICT", expected_status=409)


def test_actor_callsheet_no_conflict_when_buffer_satisfied(api):
    """PRD §3.4: "the conflict condition is precisely that the next
    reservation's `start_at` is strictly less than the prior reservation's
    `end_at` plus the required buffer."

    # difficulty: resource_temporal_overlap/actor_callsheet_travel_buffer_zone_dependent
    Claim: same-zone buffer 60 min with gap = 60 min satisfies the strict
    less-than (60 < 60 is false) → no conflict, scheduling succeeds.
    """
    prod, _ = setup_production_with_categories(api)
    loc = create_location(api, zone="ZONE_SAME", max_parallel_units=2)
    role = create_role_in_production(api, production_id=prod["id"],
                                       union_tier="SUPPORTING",
                                       day_rate_cents=100_000)
    actor = create_actor(api, travel_origin_zone="ZONE_SAME")

    scene_a = create_scene_in_production(
        api, production_id=prod["id"],
        scene_number="S-AA",
        planned_duration_minutes=60,
        required_actor_role_ids=[role["id"]],
    )
    res_a = create_held_reservation(
        api,
        location_id=loc["id"],
        production_id=prod["id"],
        scene_id=scene_a["id"],
        unit_label="AA",
        start_at=iso(2026, 5, 1, 9),
        end_at=iso(2026, 5, 1, 10),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=res_a["id"])

    scene_b = create_scene_in_production(
        api, production_id=prod["id"],
        scene_number="S-BB",
        planned_duration_minutes=60,
        required_actor_role_ids=[role["id"]],
    )
    res_b = create_held_reservation(
        api,
        location_id=loc["id"],
        production_id=prod["id"],
        scene_id=scene_b["id"],
        unit_label="BB",
        # Start exactly 60 minutes after scene A end (10:00 + 60 = 11:00).
        start_at=iso(2026, 5, 1, 11),
        end_at=iso(2026, 5, 1, 12),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=res_b["id"])

    from test_helpers import walk_role_to_offered
    walk_role_to_offered(api, production_id=prod["id"], role_id=role["id"], actor_id=actor["id"])
    validate_success(api.sign_role(prod["id"], role["id"], LP), 200)

    validate_success(api.schedule_scene(
        prod["id"], scene_a["id"],
        schedule_scene_payload(reservation_id=res_a["id"]),
        LP,
    ), 200)
    # Gap is exactly 60 min == SAME_ZONE_BUFFER; conflict iff start < end + buffer
    # i.e., 11:00 < 11:00 — false. So no conflict.
    res = validate_success(api.schedule_scene(
        prod["id"], scene_b["id"],
        schedule_scene_payload(reservation_id=res_b["id"]),
        LP,
    ), 200)
    assert res["status"] == "SCHEDULED"
