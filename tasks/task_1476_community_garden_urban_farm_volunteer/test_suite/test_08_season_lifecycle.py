"""Season lifecycle guards: opening enrollment, revert blocking, and the
planting/growing plan guards (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_season,
    create_crop_plan_payload,
    create_shift_slot_payload,
    make_admin_headers,
    make_bed,
    make_season,
    make_volunteer,
    setup_season_open,
    validate_error,
    validate_success,
)


def test_season_open_enrollment_guard_and_invalid_skip_rejected(api):
    """PRD §3.3: "A new season starts in `DRAFT` with its water counters zeroed."
    PRD §3.3: "`DRAFT → OPEN_ENROLLMENT` requires that at least one garden bed
    exists whose status is not `OUT_OF_SERVICE`, otherwise
    `ERR_SEASON_GUARD_ACTIVE_BED_REQUIRED`."
    PRD §3.3: "Any transition attempted from a from-state it does not allow is
    rejected with `ERR_INVALID_SEASON_STATE`."

    Design: Corner/state_machines/season_open_enrollment_guard_and_invalid_skip_rejected
    """
    admin = make_admin_headers()
    season = make_season()
    assert season["status"] == "DRAFT"
    assert_season(season)
    assert season["water_committed_gallons"] == 0
    assert season["water_actual_gallons"] == 0
    assert season["water_remaining_gallons"] == season["water_budget_gallons"]

    err = validate_error(
        api.transition_season(season["id"], {"to_state": "OPEN_ENROLLMENT"}, admin),
        ApiErrorId.ERR_SEASON_GUARD_ACTIVE_BED_REQUIRED,
    )
    assert err["error_id"] == "ERR_SEASON_GUARD_ACTIVE_BED_REQUIRED", "no bed exists yet"

    err = validate_error(
        api.transition_season(season["id"], {"to_state": "GROWING"}, admin),
        ApiErrorId.ERR_INVALID_SEASON_STATE,
    )
    assert err["error_id"] == "ERR_INVALID_SEASON_STATE", "DRAFT -> GROWING is not a transition"

    make_bed()
    opened = validate_success(
        api.transition_season(season["id"], {"to_state": "OPEN_ENROLLMENT"}, admin)
    )
    assert opened["status"] == "OPEN_ENROLLMENT"


def test_season_revert_blocked_after_activity(api):
    """PRD §3.3: "`OPEN_ENROLLMENT → DRAFT` (a revert) is permitted only while
    zero shift slots, zero crop plans, and zero irrigation schedules reference
    the season, otherwise `ERR_SEASON_REVERT_BLOCKED`."

    Design: Corner/state_machines/season_revert_blocked_after_activity
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    validate_success(
        api.create_shift_slot(
            create_shift_slot_payload(season_id=season["id"]), admin
        ),
        expected_status=201,
    )

    err = validate_error(
        api.transition_season(season["id"], {"to_state": "DRAFT"}, admin),
        ApiErrorId.ERR_SEASON_REVERT_BLOCKED,
    )
    assert err["error_id"] == "ERR_SEASON_REVERT_BLOCKED", (
        "a shift slot references the season"
    )


def test_season_planting_and_growing_plan_guards(api):
    """PRD §3.3: "`OPEN_ENROLLMENT → PLANTING` requires at least one crop plan
    for the season in `APPROVED` or `PLANTED`, otherwise
    `ERR_CROP_PLANS_UNRESOLVED`."
    PRD §3.3: "`PLANTING → GROWING` requires zero crop plans for the season in
    `PROPOSED` or `APPROVED` — every plan must be resolved, otherwise
    `ERR_CROP_PLANS_UNRESOLVED` — and cascades: every bed in `PLANTED` moves to
    `GROWING`."
    PRD §3.3: "Any transition attempted from a from-state it does not allow is
    rejected with `ERR_INVALID_SEASON_STATE`."

    Design: Corner/state_machines/season_planting_and_growing_plan_guards
    """
    admin = make_admin_headers()
    season, bed = setup_season_open()

    err = validate_error(
        api.transition_season(season["id"], {"to_state": "GROWING"}, admin),
        ApiErrorId.ERR_INVALID_SEASON_STATE,
    )
    assert err["error_id"] == "ERR_INVALID_SEASON_STATE", "OPEN_ENROLLMENT -> GROWING skips PLANTING"

    proposer = make_volunteer()
    plan = validate_success(
        api.create_crop_plan(
            create_crop_plan_payload(
                season_id=season["id"],
                bed_id=bed["id"],
                proposer_volunteer_id=proposer["id"],
            ),
            admin,
        ),
        expected_status=201,
    )
    validate_success(api.transition_crop_plan(plan["id"], {"to_state": "APPROVED"}, admin))

    planting = validate_success(
        api.transition_season(season["id"], {"to_state": "PLANTING"}, admin)
    )
    assert planting["status"] == "PLANTING", "the APPROVED plan satisfies the PLANTING guard"

    err = validate_error(
        api.transition_season(season["id"], {"to_state": "GROWING"}, admin),
        ApiErrorId.ERR_CROP_PLANS_UNRESOLVED,
    )
    assert err["error_id"] == "ERR_CROP_PLANS_UNRESOLVED", (
        "an APPROVED-but-not-planted plan blocks GROWING"
    )

    validate_success(api.transition_bed(bed["id"], {"to_state": "RESERVED"}, admin))
    validate_success(api.transition_crop_plan(plan["id"], {"to_state": "PLANTED"}, admin))
    # PRD §3.4: RESERVED -> PLANTED requires an APPROVED/PLANTED plan on the bed.
    validate_success(api.transition_bed(bed["id"], {"to_state": "PLANTED"}, admin))

    growing = validate_success(
        api.transition_season(season["id"], {"to_state": "GROWING"}, admin)
    )
    assert growing["status"] == "GROWING"
    bed_now = validate_success(api.get_bed(bed["id"], admin))
    assert bed_now["status"] == "GROWING", "season cascade flips PLANTED beds"
