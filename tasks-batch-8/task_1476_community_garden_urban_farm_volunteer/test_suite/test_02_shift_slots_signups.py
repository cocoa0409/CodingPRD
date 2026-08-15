"""Shift-slot occupancy, waitlist promotion, locking, check-in/out credit,
youth supervision, and the no-show threshold (PRD §3.5, §3.1, §2.8)."""
from test_helpers import (
    ApiErrorId,
    assert_shift_signup,
    assert_shift_slot,
    make_admin_headers,
    make_confirmed_signup,
    make_group_booking,
    make_officer_and_issue_cert,
    make_open_slot,
    make_participating_volunteer,
    make_signup_request,
    make_tool,
    make_tool_checkout,
    make_volunteer,
    make_volunteer_headers,
    setup_full_slot_with_waitlist,
    setup_open_slot_scenario,
    setup_season_open,
    validate_error,
    validate_success,
)


def test_signup_blocked_until_waiver_signed(api):
    """PRD §2.8: "The gates are evaluated in a fixed sub-order: the volunteer's
    `orientation_status` must be `ORIENTED` (otherwise `ERR_ORIENTATION_REQUIRED`),
    then `waiver_status` must be `SIGNED` (otherwise `ERR_WAIVER_REQUIRED`, which
    covers both `UNSIGNED` and `EXPIRED`), then `standing` must not be `SUSPENDED`
    (otherwise `ERR_VOLUNTEER_SUSPENDED`)."

    Design: Difficulty/cross_entity_state_dependency/signup_blocked_until_waiver_signed
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=3, capacity_youth=1)
    # ORIENTED but waiver still UNSIGNED.
    vol = validate_success(
        api.create_volunteer(
            {"full_name": "V One", "email": "v1@x.com", "date_of_birth": "1990-05-20"},
            admin,
        ),
        expected_status=201,
    )
    validate_success(api.complete_orientation(vol["id"], admin))

    err = validate_error(
        api.create_shift_signup(
            {"slot_id": slot["id"], "volunteer_id": vol["id"]},
            make_volunteer_headers(vol["id"]),
        ),
        ApiErrorId.ERR_WAIVER_REQUIRED,
    )
    assert err["error_id"] == "ERR_WAIVER_REQUIRED"

    validate_success(api.sign_waiver(vol["id"], admin))
    signup = validate_success(
        api.create_shift_signup(
            {"slot_id": slot["id"], "volunteer_id": vol["id"]},
            make_volunteer_headers(vol["id"]),
        ),
        expected_status=201,
    )
    assert_shift_signup(signup)
    assert signup["status"] == "REQUESTED", "signing the waiver unblocks the same request"


def test_slot_open_full_waitlist_promotion_cycle(api):
    """PRD §3.5: "`OPEN → FULL` is automatic: the moment `confirmed_count` reaches
    `capacity_total`, the slot fills."
    PRD §3.5: "When there is no room, the signup does not fail; it becomes
    `WAITLISTED` instead, receiving `waitlist_position` from the slot's
    `next_waitlist_position` — a per-slot monotonic counter that starts at 1 and
    increments with each assignment — while the slot stays `FULL` and its
    `waitlist_count` grows by one."
    PRD §3.5: "When no waitlisted candidate is eligible — or none exists — no
    promotion occurs and a `FULL` slot falls back to `OPEN`."

    Design: Difficulty/non_linear_state_machine/slot_full_open_full_cycle
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=2, capacity_youth=1)
    v1 = make_participating_volunteer()
    v2 = make_participating_volunteer()
    v3 = make_participating_volunteer()
    s1 = make_signup_request(slot["id"], v1["id"])
    s2 = make_signup_request(slot["id"], v2["id"])
    s3 = make_signup_request(slot["id"], v3["id"])

    validate_success(api.confirm_shift_signup(s1["id"], admin))
    s2_after = validate_success(api.confirm_shift_signup(s2["id"], admin))
    assert s2_after["status"] == "CONFIRMED"
    slot_now = validate_success(api.get_shift_slot(slot["id"], admin))
    assert slot_now["status"] == "FULL" and slot_now["confirmed_count"] == 2

    s3_after = validate_success(api.confirm_shift_signup(s3["id"], admin))
    assert s3_after["status"] == "WAITLISTED", "confirm on a full slot waitlists instead of failing"
    assert s3_after["waitlist_position"] == 1

    validate_success(api.cancel_shift_signup(s1["id"], admin))
    s3_promoted = validate_success(api.get_shift_signup(s3["id"], admin))
    assert s3_promoted["status"] == "CONFIRMED"
    assert s3_promoted["waitlist_position"] is None
    slot_now = validate_success(api.get_shift_slot(slot["id"], admin))
    assert slot_now["status"] == "FULL" and slot_now["confirmed_count"] == 2, (
        "the promotion refilled the freed spot; OPEN is never observable"
    )

    validate_success(api.cancel_shift_signup(s2["id"], admin))
    slot_now = validate_success(api.get_shift_slot(slot["id"], admin))
    assert slot_now["status"] == "OPEN" and slot_now["confirmed_count"] == 1, (
        "empty waitlist: FULL falls back to OPEN"
    )


def test_occupancy_conserved_across_cancel_and_promotion(api):
    """PRD §3.5: "Whenever a `CONFIRMED` spot is freed — by any cancellation,
    including the slot-independent suspension cascade of §3.1 — the server scans
    the slot's `WAITLISTED` signups in ascending `waitlist_position` (positions are
    unique per slot, so no tie-break is ever needed) and promotes the first
    candidate that satisfies both pool constraints: `confirmed_count` plus one
    within `capacity_total`, and, for a youth candidate, `confirmed_youth_count`
    plus one within `capacity_youth`."

    Design: Difficulty/compensating_invariant/slot_occupancy_conserved_across_cancel_and_promotion
    """
    admin = make_admin_headers()
    ctx = setup_full_slot_with_waitlist(capacity_total=3, capacity_youth=1)
    slot, confirmed, waitlisted = ctx["slot"], ctx["confirmed"], ctx["waitlisted"]
    assert slot["status"] == "FULL"
    assert slot["confirmed_count"] == 3
    assert slot["waitlist_count"] == 1
    assert waitlisted["status"] == "WAITLISTED"

    validate_success(api.cancel_shift_signup(confirmed[1]["id"], admin))

    promoted = validate_success(api.get_shift_signup(waitlisted["id"], admin))
    assert promoted["status"] == "CONFIRMED"
    assert promoted["waitlist_position"] is None
    slot_after = validate_success(api.get_shift_slot(slot["id"], admin))
    assert slot_after["confirmed_count"] == 3, "one spot freed and one promoted: occupancy conserved"
    assert slot_after["waitlist_count"] == 0
    assert slot_after["status"] == "FULL"


def test_slot_cancellation_cascades_signup_checkout_and_tool_counts(api):
    """PRD §3.5: "Cancellation cascades: signups in `REQUESTED`, `CONFIRMED`, or
    `WAITLISTED` become `CANCELLED` with no no-show penalty, and group bookings in
    `REQUESTED` or `CONFIRMED` become `CANCELLED`; then, for each cancelled signup,
    any of its tool checkouts in `OPEN` that were linked through `signup_id` become
    `AUTO_CLOSED`, and for each auto-closed checkout the tool's counts are
    recomputed — `checked_out_count` falls by the outstanding units and
    `available_count` rises by the same amount."

    Design: Difficulty/transitive_cascade/slot_cancel_cascades_signup_checkout_tool
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(
        season["id"], capacity_total=5, capacity_youth=2, task_type="REPAIR"
    )
    vol = make_participating_volunteer()
    signup = make_confirmed_signup(slot["id"], vol["id"])
    tool = make_tool(total_count=5, tool_name="Hoe set")
    checkout = make_tool_checkout(tool["id"], vol["id"], 2, signup_id=signup["id"])

    cancelled_slot = validate_success(
        api.transition_shift_slot(slot["id"], {"to_state": "CANCELLED"}, admin)
    )
    assert cancelled_slot["status"] == "CANCELLED"

    signup_after = validate_success(api.get_shift_signup(signup["id"], admin))
    assert signup_after["status"] == "CANCELLED", "cascade link 1"

    checkout_after = validate_success(api.get_tool_checkout(checkout["id"], admin))
    assert checkout_after["status"] == "AUTO_CLOSED", "cascade link 2"

    tool_after = validate_success(api.get_tool(tool["id"], admin))
    assert tool_after["checked_out_count"] == 0, "cascade link 3"
    assert tool_after["available_count"] == 5

    vol_after = validate_success(api.get_volunteer(vol["id"], admin))
    assert vol_after["no_show_count"] == 0, "cancellation carries no no-show penalty"


def test_slot_completion_marks_no_shows_third_triggers_probation(api):
    """PRD §3.5: "Completion cascades: every signup still `CONFIRMED` becomes
    `NO_SHOW`, incrementing its volunteer's `no_show_count` by one, and each
    volunteer whose count thereby reaches 3 while in `GOOD` standing drops to
    `PROBATION`".
    PRD §3.1: "The boundary is exact: the third no-show triggers the drop, the
    second does not. `PROBATION` never auto-reverts; reinstatement is always a
    manual act."

    Design: Corner/state_machines/slot_completion_marks_no_shows_third_triggers_probation
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    vol = make_participating_volunteer()
    slots = [
        make_open_slot(
            season["id"],
            capacity_total=3,
            capacity_youth=1,
            starts_at=f"2026-08-{15 + i}T09:00:00Z",
            ends_at=f"2026-08-{15 + i}T12:00:00Z",
        )
        for i in range(3)
    ]
    signups = [make_confirmed_signup(slot["id"], vol["id"]) for slot in slots]

    expected = [(1, "GOOD"), (2, "GOOD"), (3, "PROBATION")]
    for i, (slot, (count, standing)) in enumerate(zip(slots, expected)):
        validate_success(
            api.set_clock({"to_iso8601": f"2026-08-{15 + i}T13:00:00Z"}, admin)
        )
        validate_success(api.run_epoch(admin))  # locks the slot at starts_at - 24h
        completed = validate_success(
            api.transition_shift_slot(slot["id"], {"to_state": "COMPLETED"}, admin)
        )
        assert completed["status"] == "COMPLETED"
        vol_now = validate_success(api.get_volunteer(vol["id"], admin))
        assert vol_now["no_show_count"] == count, f"no_show_count after slot {i + 1}"
        assert vol_now["standing"] == standing, (
            f"standing after {count} no-shows: {standing}"
        )

    first = validate_success(api.get_shift_signup(signups[0]["id"], admin))
    assert first["status"] == "NO_SHOW"


def test_slot_lock_blocks_late_signup_and_late_cancel(api):
    """PRD §3.5: "Creation applies its gates in sequence: the slot must be in
    `OPEN` or `FULL` (otherwise `ERR_INVALID_SLOT_STATE`); the clock must still be
    earlier than 24 hours before `starts_at` (otherwise `ERR_SLOT_LOCKED`)".
    PRD §3.5: "From `CONFIRMED` the manual move additionally requires the clock to
    be earlier than 24 hours before `starts_at` (otherwise `ERR_SLOT_LOCKED`)".
    PRD §3.5: "`OPEN` or `FULL → LOCKED` happens automatically at the epoch run
    once the clock reaches 24 hours before `starts_at`".

    Design: Corner/state_machines/slot_lock_blocks_late_signup_and_late_cancel
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=3, capacity_youth=1)
    v1 = make_participating_volunteer()
    v2 = make_participating_volunteer()
    s1 = make_confirmed_signup(slot["id"], v1["id"])

    # 2026-08-14T10:00 is inside starts_at - 24h (2026-08-14T09:00) but the
    # epoch has not run, so the slot is still OPEN and the temporal guard fires.
    validate_success(api.set_clock({"to_iso8601": "2026-08-14T10:00:00Z"}, admin))
    err = validate_error(
        api.create_shift_signup(
            {"slot_id": slot["id"], "volunteer_id": v2["id"]},
            make_volunteer_headers(v2["id"]),
        ),
        ApiErrorId.ERR_SLOT_LOCKED,
    )
    assert err["error_id"] == "ERR_SLOT_LOCKED"

    err = validate_error(
        api.cancel_shift_signup(s1["id"], make_volunteer_headers(v1["id"])),
        ApiErrorId.ERR_SLOT_LOCKED,
    )
    assert err["error_id"] == "ERR_SLOT_LOCKED"

    validate_success(api.run_epoch(admin))
    slot_now = validate_success(api.get_shift_slot(slot["id"], admin))
    assert slot_now["status"] == "LOCKED"

    err = validate_error(
        api.create_shift_signup(
            {"slot_id": slot["id"], "volunteer_id": v2["id"]},
            make_volunteer_headers(v2["id"]),
        ),
        ApiErrorId.ERR_INVALID_SLOT_STATE,
    )
    assert err["error_id"] == "ERR_INVALID_SLOT_STATE", (
        "with the slot LOCKED the state guard fires first"
    )


def test_youth_signup_requires_certified_supervising_adult(api):
    """PRD §3.5: "a minor — the signup snapshots `is_youth` from the volunteer's
    `is_minor` at creation — must name a `supervision_adult_signup_id` that
    references a signup on the same slot in `CONFIRMED` or `CHECKED_IN` whose
    volunteer `can_supervise` (otherwise `ERR_YOUTH_SUPERVISION_REQUIRED`)".
    PRD §3.5: "Confirmation is the staff decision, by a `GardenAdmin` or
    `Coordinator`, and it re-runs the structural gates: the signup is `REQUESTED`
    (otherwise `ERR_INVALID_SIGNUP_STATE`), the slot is `OPEN` or `FULL`
    (otherwise `ERR_INVALID_SLOT_STATE`), the clock is earlier than 24 hours
    before `starts_at` (otherwise `ERR_SLOT_LOCKED`), and a youth signup's
    supervising adult is still valid (otherwise `ERR_YOUTH_SUPERVISION_REQUIRED`)."

    Design: Corner/state_machines/youth_signup_requires_certified_supervising_adult
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=5, capacity_youth=3)
    youth = make_participating_volunteer(dob="2012-03-01")
    adult = make_participating_volunteer()
    adult_signup = make_signup_request(slot["id"], adult["id"])

    # No supervision link at create.
    err = validate_error(
        api.create_shift_signup(
            {"slot_id": slot["id"], "volunteer_id": youth["id"]},
            make_volunteer_headers(youth["id"]),
        ),
        ApiErrorId.ERR_YOUTH_SUPERVISION_REQUIRED,
    )
    assert err["error_id"] == "ERR_YOUTH_SUPERVISION_REQUIRED"

    # Adult signup still REQUESTED at create: supervision check refuses.
    err = validate_error(
        api.create_shift_signup(
            {
                "slot_id": slot["id"],
                "volunteer_id": youth["id"],
                "supervision_adult_signup_id": adult_signup["id"],
            },
            make_volunteer_headers(youth["id"]),
        ),
        ApiErrorId.ERR_YOUTH_SUPERVISION_REQUIRED,
    )
    assert err["error_id"] == "ERR_YOUTH_SUPERVISION_REQUIRED", (
        "create-time supervision requires a CONFIRMED/CHECKED_IN adult signup"
    )

    # Adult CONFIRMED but holds no SUPERVISION certification: create still refused.
    validate_success(api.confirm_shift_signup(adult_signup["id"], admin))
    err = validate_error(
        api.create_shift_signup(
            {
                "slot_id": slot["id"],
                "volunteer_id": youth["id"],
                "supervision_adult_signup_id": adult_signup["id"],
            },
            make_volunteer_headers(youth["id"]),
        ),
        ApiErrorId.ERR_YOUTH_SUPERVISION_REQUIRED,
    )
    assert err["error_id"] == "ERR_YOUTH_SUPERVISION_REQUIRED", (
        "create-time supervision requires can_supervise on the adult"
    )

    # Issue the adult a SUPERVISION cert; create now succeeds.
    cert = make_officer_and_issue_cert(adult["id"], "SUPERVISION")
    youth_signup = validate_success(
        api.create_shift_signup(
            {
                "slot_id": slot["id"],
                "volunteer_id": youth["id"],
                "supervision_adult_signup_id": adult_signup["id"],
            },
            make_volunteer_headers(youth["id"]),
        ),
        expected_status=201,
    )
    assert youth_signup["is_youth"] is True, "is_youth snapshots is_minor at creation"

    # Confirm-time re-check: revoke the adult's SUPERVISION cert so the
    # supervising adult is no longer valid; confirm must be refused.
    validate_success(
        api.revoke_certification(
            cert["id"], {"revoked_reason": "test"}, make_admin_headers()
        )
    )
    err = validate_error(
        api.confirm_shift_signup(youth_signup["id"], admin),
        ApiErrorId.ERR_YOUTH_SUPERVISION_REQUIRED,
    )
    assert err["error_id"] == "ERR_YOUTH_SUPERVISION_REQUIRED", (
        "confirm-time re-check refuses when supervisor cert is revoked"
    )

    # Re-issue the cert; confirm succeeds.
    make_officer_and_issue_cert(adult["id"], "SUPERVISION")
    confirmed = validate_success(api.confirm_shift_signup(youth_signup["id"], admin))
    assert confirmed["status"] == "CONFIRMED"


def test_supervision_loss_cascade_cancels_youth_signup(api):
    """PRD §3.5: "Cancellation carries one supervision-loss cascade: if the
    cancelled signup is named as the `supervision_adult_signup_id` of youth
    signups on the same slot in `REQUESTED` or `CONFIRMED`, those youth signups
    are themselves cancelled, since their supervision guarantee has evaporated."

    Design: Corner/state_machines/supervision_loss_cascade_cancels_youth_signup
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=5, capacity_youth=3)
    adult_a = make_participating_volunteer()
    make_officer_and_issue_cert(adult_a["id"], "SUPERVISION")
    adult_b = make_participating_volunteer()
    youth = make_participating_volunteer(dob="2012-03-01")

    sa = make_confirmed_signup(slot["id"], adult_a["id"])
    sy = make_signup_request(
        slot["id"], youth["id"], supervision_adult_signup_id=sa["id"]
    )
    sy = validate_success(api.confirm_shift_signup(sy["id"], admin))
    assert sy["status"] == "CONFIRMED"
    sb = make_confirmed_signup(slot["id"], adult_b["id"])

    validate_success(
        api.cancel_shift_signup(sa["id"], make_volunteer_headers(adult_a["id"]))
    )

    sy_after = validate_success(api.get_shift_signup(sy["id"], admin))
    assert sy_after["status"] == "CANCELLED", "supervision-loss cascade"
    sb_after = validate_success(api.get_shift_signup(sb["id"], admin))
    assert sb_after["status"] == "CONFIRMED", "unrelated signup untouched"
    slot_after = validate_success(api.get_shift_slot(slot["id"], admin))
    assert_shift_slot(slot_after)
    assert slot_after["confirmed_count"] == 1
    assert slot_after["confirmed_youth_count"] == 0


def test_service_credit_scheduled_vs_actual_divergence(api):
    """PRD §3.5: "Check-in stamps `checked_in_at` and assigns a provisional
    `credited_minutes` equal to the slot's scheduled length — the whole-minute
    difference between `ends_at` and `starts_at`".
    PRD §3.5: "Checking out requires the signup to be `CHECKED_IN`, stamps
    `checked_out_at`, and finalizes the credit: the actual elapsed time between
    `checked_in_at` and `checked_out_at`, truncated to whole minutes, is compared
    against the scheduled length plus a 30-minute grace, and the final
    `credited_minutes` is the lesser of the two, never below zero."
    PRD §3.5: "it is always the sum of `credited_minutes` over their signups in
    `CHECKED_IN` (provisional values) or `COMPLETED` (final values)".

    Design: Difficulty/dual_variant_calc/service_credit_scheduled_vs_actual_divergence
    """
    admin = make_admin_headers()
    ctx = setup_open_slot_scenario(capacity_total=3, capacity_youth=1)
    vol = ctx["volunteer"]
    slot = ctx["slot"]
    signup = make_confirmed_signup(slot["id"], vol["id"])

    validate_success(api.set_clock({"to_iso8601": "2026-08-15T09:10:00Z"}, admin))
    checked_in = validate_success(
        api.check_in_shift_signup(signup["id"], make_volunteer_headers(vol["id"]))
    )
    assert checked_in["status"] == "CHECKED_IN"
    assert checked_in["credited_minutes"] == 180, (
        "provisional credit equals the 09:00-12:00 scheduled length"
    )

    validate_success(api.set_clock({"to_iso8601": "2026-08-15T11:00:00Z"}, admin))
    checked_out = validate_success(
        api.check_out_shift_signup(signup["id"], make_volunteer_headers(vol["id"]))
    )
    assert checked_out["status"] == "COMPLETED"
    assert checked_out["credited_minutes"] == 110, (
        "final credit is min(110 elapsed, 180 + 30 grace)"
    )
    assert checked_in["credited_minutes"] != checked_out["credited_minutes"]

    vol_after = validate_success(api.get_volunteer(vol["id"], admin))
    assert vol_after["total_service_minutes"] == 110


def test_service_credit_capped_by_grace_window(api):
    """PRD §3.5: "Checking out requires the signup to be `CHECKED_IN`, stamps
    `checked_out_at`, and finalizes the credit: the actual elapsed time between
    `checked_in_at` and `checked_out_at`, truncated to whole minutes, is compared
    against the scheduled length plus a 30-minute grace, and the final
    `credited_minutes` is the lesser of the two, never below zero."
    PRD §3.5: "Check-in stamps `checked_in_at` and assigns a provisional
    `credited_minutes` equal to the slot's scheduled length".

    Design: Difficulty/dual_variant_calc/service_credit_scheduled_vs_actual_divergence
    """
    admin = make_admin_headers()
    ctx = setup_open_slot_scenario(capacity_total=3, capacity_youth=1)
    vol, slot = ctx["volunteer"], ctx["slot"]
    signup = make_confirmed_signup(slot["id"], vol["id"])

    validate_success(api.set_clock({"to_iso8601": "2026-08-15T09:10:00Z"}, admin))
    checked_in = validate_success(
        api.check_in_shift_signup(signup["id"], make_volunteer_headers(vol["id"]))
    )
    assert checked_in["credited_minutes"] == 180, "provisional: scheduled length"

    # 230 elapsed minutes exceed the 180 + 30 grace cap: the cap wins.
    validate_success(api.set_clock({"to_iso8601": "2026-08-15T13:00:00Z"}, admin))
    checked_out = validate_success(
        api.check_out_shift_signup(signup["id"], make_volunteer_headers(vol["id"]))
    )
    assert checked_out["status"] == "COMPLETED"
    assert checked_out["credited_minutes"] == 210, "min(230 elapsed, 180 + 30)"
    vol_after = validate_success(api.get_volunteer(vol["id"], admin))
    assert vol_after["total_service_minutes"] == 210


def test_slot_waitlist_fifo_promotion_order(api):
    """PRD §3.5: "Whenever a `CONFIRMED` spot is freed — by any cancellation,
    including the slot-independent suspension cascade of §3.1 — the server scans
    the slot's `WAITLISTED` signups in ascending `waitlist_position` (positions
    are unique per slot, so no tie-break is ever needed) and promotes the first
    candidate that satisfies both pool constraints".

    Design: Difficulty/non_linear_state_machine/slot_full_open_full_cycle
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=2, capacity_youth=1)
    v1, v2 = make_participating_volunteer(), make_participating_volunteer()
    v3, v4 = make_participating_volunteer(), make_participating_volunteer()
    s1 = make_confirmed_signup(slot["id"], v1["id"])
    make_confirmed_signup(slot["id"], v2["id"])
    s3 = make_signup_request(slot["id"], v3["id"])
    s3 = validate_success(api.confirm_shift_signup(s3["id"], admin))
    s4 = make_signup_request(slot["id"], v4["id"])
    s4 = validate_success(api.confirm_shift_signup(s4["id"], admin))
    assert (s3["status"], s3["waitlist_position"]) == ("WAITLISTED", 1)
    assert (s4["status"], s4["waitlist_position"]) == ("WAITLISTED", 2)

    validate_success(api.cancel_shift_signup(s1["id"], admin))
    s3_after = validate_success(api.get_shift_signup(s3["id"], admin))
    assert s3_after["status"] == "CONFIRMED", "position 1 promotes first"
    assert s3_after["waitlist_position"] is None
    s4_after = validate_success(api.get_shift_signup(s4["id"], admin))
    assert s4_after["status"] == "WAITLISTED", "position 2 keeps waiting"
    assert s4_after["waitlist_position"] == 2
    slot_after = validate_success(api.get_shift_slot(slot["id"], admin))
    assert slot_after["status"] == "FULL" and slot_after["confirmed_count"] == 2


def test_slot_cancellation_leaves_unlinked_checkout_open(api):
    """PRD §3.5: "for each cancelled signup, any of its tool checkouts in `OPEN`
    that were linked through `signup_id` become `AUTO_CLOSED`, and for each
    auto-closed checkout the tool's counts are recomputed — `checked_out_count`
    falls by the outstanding units and `available_count` rises by the same
    amount."

    Design: Difficulty/transitive_cascade/slot_cancel_cascades_signup_checkout_tool
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=5, capacity_youth=2)
    v1, v2 = make_participating_volunteer(), make_participating_volunteer()
    s1 = make_confirmed_signup(slot["id"], v1["id"])
    s2 = make_confirmed_signup(slot["id"], v2["id"])
    tool = make_tool(total_count=5)
    co_linked_1 = make_tool_checkout(tool["id"], v1["id"], 2, signup_id=s1["id"])
    co_linked_2 = make_tool_checkout(tool["id"], v2["id"], 1, signup_id=s2["id"])
    co_unlinked = make_tool_checkout(tool["id"], v1["id"], 1)  # no signup link

    validate_success(
        api.transition_shift_slot(slot["id"], {"to_state": "CANCELLED"}, admin)
    )

    for signup in (s1, s2):
        after = validate_success(api.get_shift_signup(signup["id"], admin))
        assert after["status"] == "CANCELLED"
    for checkout in (co_linked_1, co_linked_2):
        after = validate_success(api.get_tool_checkout(checkout["id"], admin))
        assert after["status"] == "AUTO_CLOSED", "linked checkouts auto-close"
    unlinked_after = validate_success(api.get_tool_checkout(co_unlinked["id"], admin))
    assert unlinked_after["status"] == "OPEN", "an unlinked checkout is untouched"

    tool_after = validate_success(api.get_tool(tool["id"], admin))
    assert tool_after["checked_out_count"] == 1, "only the unlinked unit remains out"
    assert tool_after["available_count"] == 4


def test_occupancy_conserved_with_group_booking_mix(api):
    """PRD §3.5: "A slot's `confirmed_count` is the number of its signups in
    `CONFIRMED` or `CHECKED_IN` — each counting one — plus the sum of
    `member_count` over its group bookings in `CONFIRMED` or `CHECKED_IN`."
    PRD §3.5: "the promotion selection runs on the freed spot, and the slot moves
    `FULL → OPEN` when promotion finds no eligible candidate."

    Design: Difficulty/compensating_invariant/slot_occupancy_conserved_across_cancel_and_promotion
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=3, capacity_youth=1)
    leader = make_participating_volunteer()
    booking = make_group_booking(
        slot["id"], leader, member_count=2, minor_count=0, chaperones=[]
    )
    booking = validate_success(
        api.transition_group_booking(booking["id"], {"to_state": "CONFIRMED"}, admin)
    )
    assert booking["status"] == "CONFIRMED"

    v1, v2 = make_participating_volunteer(), make_participating_volunteer()
    s1 = make_confirmed_signup(slot["id"], v1["id"])
    slot_now = validate_success(api.get_shift_slot(slot["id"], admin))
    assert slot_now["confirmed_count"] == 3 and slot_now["status"] == "FULL", (
        "2 booking members + 1 signup fill the slot"
    )
    s2 = make_signup_request(slot["id"], v2["id"])
    s2 = validate_success(api.confirm_shift_signup(s2["id"], admin))
    assert s2["status"] == "WAITLISTED"

    validate_success(api.cancel_shift_signup(s1["id"], admin))
    s2_after = validate_success(api.get_shift_signup(s2["id"], admin))
    assert s2_after["status"] == "CONFIRMED"
    slot_after = validate_success(api.get_shift_slot(slot["id"], admin))
    assert slot_after["confirmed_count"] == 3, "mixed-pool occupancy is conserved"
    assert slot_after["status"] == "FULL"
    booking_after = validate_success(api.get_group_booking(booking["id"], admin))
    assert booking_after["status"] == "CONFIRMED"


def test_signup_orientation_gate_precedes_waiver(api):
    """PRD §2.8: "The gates are evaluated in a fixed sub-order: the volunteer's
    `orientation_status` must be `ORIENTED` (otherwise `ERR_ORIENTATION_REQUIRED`),
    then `waiver_status` must be `SIGNED` (otherwise `ERR_WAIVER_REQUIRED`, which
    covers both `UNSIGNED` and `EXPIRED`), then `standing` must not be `SUSPENDED`
    (otherwise `ERR_VOLUNTEER_SUSPENDED`)."

    Design: Difficulty/cross_entity_state_dependency/signup_blocked_until_waiver_signed
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=3, capacity_youth=1)
    vol = make_volunteer()  # PENDING orientation, UNSIGNED waiver

    err = validate_error(
        api.create_shift_signup(
            {"slot_id": slot["id"], "volunteer_id": vol["id"]},
            make_volunteer_headers(vol["id"]),
        ),
        ApiErrorId.ERR_ORIENTATION_REQUIRED,
    )
    assert err["error_id"] == "ERR_ORIENTATION_REQUIRED", "orientation is checked first"

    validate_success(api.complete_orientation(vol["id"], admin))
    err = validate_error(
        api.create_shift_signup(
            {"slot_id": slot["id"], "volunteer_id": vol["id"]},
            make_volunteer_headers(vol["id"]),
        ),
        ApiErrorId.ERR_WAIVER_REQUIRED,
    )
    assert err["error_id"] == "ERR_WAIVER_REQUIRED", "waiver is checked second"
