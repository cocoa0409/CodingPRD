"""RSVP workflows: branching state machine with revert, depth-3 decline
cascade in SEATED, deadline guards, compensating meal-count invariant."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_guest_payload,
    create_meal_option_payload,
    create_table_payload,
    create_plus_one_payload,
    create_seating_assignment_payload,
    make_couple_headers,
    make_guest_self_headers,
    set_clock,
    bootstrap_wedding_in_rsvp_open,
    bootstrap_wedding_in_draft,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / non_linear_state_machine / guest_state_machine_branching_with_revert
# ─────────────────────────────────────────────────────────────────────────────

def test_guest_attending_revoke_decline_revoke_cycle(api):
    """PRD §3.2: "An `attending=true` RSVP transitions the guest's
    `rsvp_status` from `INVITED` to `ATTENDING`, stores the supplied
    `meal_option_id` on the guest"
    PRD §3.2: "The couple may also reverse direction — taking a guest back
    from `ATTENDING` or `DECLINED` to `INVITED` — but only while the wedding
    is still `RSVP_OPEN` and `current_utc` is still before
    `rsvp_deadline_at`. The revoke from `ATTENDING` to `INVITED` clears
    `meal_option_id` back to null and is rejected if any `PlusOne` under
    the guest currently sits in `ATTENDING`"
    PRD §3.2: "An `attending=false` RSVP transitions the guest to `DECLINED`,
    sets `meal_option_id` to null"

    Design: Difficulty/non_linear_state_machine/guest_state_machine_branching_with_revert
    """
    set_clock("2027-04-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w5",
        clock_iso="2027-04-01T00:00:00Z",
        ceremony_at="2027-09-01T18:00:00Z",
        rsvp_deadline_at="2027-08-15T23:59:59Z",
    )
    headers = make_couple_headers("couple_w5")
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Revert Guest", email="rg@example.com"),
        headers,
    ), expected_status=201)

    # INVITED -> ATTENDING
    after_attend = validate_success(api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, headers,
    ), expected_status=200)
    assert after_attend["rsvp_status"] == "ATTENDING"
    assert after_attend["meal_option_id"] == meal["id"]

    # ATTENDING -> INVITED via revoke (meal cleared)
    after_revoke_1 = validate_success(
        api.revoke_guest_rsvp(guest["id"], headers), expected_status=200,
    )
    assert after_revoke_1["rsvp_status"] == "INVITED"
    assert after_revoke_1.get("meal_option_id") is None

    # INVITED -> DECLINED
    after_decline = validate_success(api.guest_rsvp(
        guest["id"], {"attending": False}, headers,
    ), expected_status=200)
    assert after_decline["rsvp_status"] == "DECLINED"
    assert after_decline.get("meal_option_id") is None

    # DECLINED -> INVITED via revoke
    after_revoke_2 = validate_success(
        api.revoke_guest_rsvp(guest["id"], headers), expected_status=200,
    )
    assert after_revoke_2["rsvp_status"] == "INVITED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / transitive_cascade / guest_decline_in_seated_wedding_depth3_cascade
# ─────────────────────────────────────────────────────────────────────────────

def test_guest_decline_in_seated_wedding_depth3_cascade(api):
    """PRD §3.2: "An `attending=false` RSVP transitions the guest to
    `DECLINED`, sets `meal_option_id` to null, and cascades downward: every
    `PlusOne` under that guest is itself auto-declined with `meal_option_id`
    cleared, and if the wedding was already `SEATED`, any `SeatingAssignment`
    whose `assignee_type` is `GUEST` and `assignee_id` is this guest is
    deleted, along with any assignment for any plus-one of this guest, and
    the wedding is reverted to `RSVP_CLOSED` with `seating_dirty=true`."

    Design: Difficulty/transitive_cascade/guest_decline_in_seated_wedding_depth3_cascade
    """
    set_clock("2027-06-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w7",
        clock_iso="2027-06-01T00:00:00Z",
        ceremony_at="2027-11-01T18:00:00Z",
        rsvp_deadline_at="2027-10-15T23:59:59Z",
    )
    headers = make_couple_headers("couple_w7")
    table = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=7, capacity=4),
        headers,
    ), expected_status=201)
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(
            full_name="Head", email="head@example.com",
            plus_one_allowed=True,
        ),
        headers,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, headers,
    ), expected_status=200)
    plus_one = validate_success(api.create_plus_one(
        guest["id"],
        create_plus_one_payload(
            full_name="Partner", is_child=False, meal_option_id=meal["id"],
        ),
        headers,
    ), expected_status=201)

    validate_success(api.close_rsvp(wedding["id"], headers), expected_status=200)
    validate_success(api.create_seating_assignment(
        create_seating_assignment_payload(
            wedding["id"], table["id"], "GUEST", guest["id"],
        ),
        headers,
    ), expected_status=201)
    validate_success(api.create_seating_assignment(
        create_seating_assignment_payload(
            wedding["id"], table["id"], "PLUS_ONE", plus_one["id"],
        ),
        headers,
    ), expected_status=201)
    fresh = validate_success(api.get_wedding(wedding["id"], headers), expected_status=200)
    seated = validate_success(api.finalize_seating(
        wedding["id"], fresh["version"], headers,
    ), expected_status=200)
    assert seated["status"] == "SEATED"

    # Trigger: guest declines while wedding is SEATED → depth-3 cascade.
    validate_success(api.guest_rsvp(
        guest["id"], {"attending": False}, headers,
    ), expected_status=200)

    after_guest = validate_success(api.get_guest(guest["id"], headers), expected_status=200)
    assert after_guest["rsvp_status"] == "DECLINED"
    assert after_guest.get("meal_option_id") is None

    after_plus_one = validate_success(
        api.get_plus_one(plus_one["id"], headers), expected_status=200,
    )
    assert after_plus_one["rsvp_status"] == "DECLINED"
    assert after_plus_one.get("meal_option_id") is None

    after_wedding = validate_success(api.get_wedding(wedding["id"], headers), expected_status=200)
    assert after_wedding["status"] == "RSVP_CLOSED"
    assert after_wedding["seating_dirty"] is True

    # All SeatingAssignment rows for this wedding are gone.
    seat_list_res = api.list_seating_assignments(headers, params={"wedding_id": wedding["id"]})
    seat_data = validate_success(seat_list_res, expected_status=200)
    if isinstance(seat_data, dict):
        # paginated envelope: data list under top key (framework returns data list,
        # this is the lenient path)
        seat_data = seat_data.get("items") or seat_data.get("data") or []
    assert seat_data == [], f"Expected zero seating assignments, got {seat_data!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / compensating_invariant / rsvp_decline_re_attend_preserves_meal_count
# ─────────────────────────────────────────────────────────────────────────────

def test_rsvp_decline_re_attend_preserves_meal_count(api):
    """PRD §3.4: "For each `MealOption` of the wedding, the count is the
    number of `Guest` rows belonging to that wedding whose `rsvp_status` is
    `ATTENDING` and whose `meal_option_id` equals that meal's `id`, plus the
    number of `PlusOne` rows under the same condition. `INVITED` rows are
    excluded; `DECLINED` rows are excluded".

    Design: Difficulty/compensating_invariant/rsvp_decline_re_attend_preserves_meal_count
    """
    set_clock("2028-05-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w18",
        clock_iso="2028-05-01T00:00:00Z",
        ceremony_at="2028-10-01T18:00:00Z",
        rsvp_deadline_at="2028-09-15T23:59:59Z",
    )
    headers = make_couple_headers("couple_w18")
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Back", email="back@example.com"),
        headers,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, headers,
    ), expected_status=200)

    def get_meal_count() -> int:
        summary = validate_success(api.get_meal_summary(wedding["id"], headers), expected_status=200)
        for item in summary["items"]:
            if item["meal_option_id"] == meal["id"]:
                return item["count"]
        return 0

    before = get_meal_count()
    assert before == 1

    validate_success(api.guest_rsvp(
        guest["id"], {"attending": False}, headers,
    ), expected_status=200)
    mid = get_meal_count()
    assert mid == 0, "DECLINED row must be excluded from count"

    validate_success(api.revoke_guest_rsvp(guest["id"], headers), expected_status=200)
    validate_success(api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, headers,
    ), expected_status=200)
    after = get_meal_count()
    assert after == 1, "count must return to its prior value after compensating pair"

    after_guest = validate_success(api.get_guest(guest["id"], headers), expected_status=200)
    assert after_guest["rsvp_status"] == "ATTENDING"
    assert after_guest["meal_option_id"] == meal["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Cross-entity state errors (RSVP path) live here for narrative flow.
# ─────────────────────────────────────────────────────────────────────────────

def test_guest_rsvp_blocked_by_wedding_state(api):
    """PRD §3.2: "While the wedding is in `RSVP_OPEN` and `current_utc` is
    still before `rsvp_deadline_at`, an invited guest may RSVP themselves
    through their `invitation_token`, or the couple may RSVP on their
    behalf."
    PRD §2.9: "then state-machine preconditions on the target entity
    (`ERR_INVALID_STATE` at 409)."

    Design: Difficulty/cross_entity_state_dependency/guest_rsvp_blocked_by_wedding_state
    """
    set_clock("2027-12-01T00:00:00Z")
    wedding = bootstrap_wedding_in_draft(
        couple_user_id="couple_w13",
        clock_iso="2027-12-01T00:00:00Z",
        ceremony_at="2028-05-01T18:00:00Z",
        rsvp_deadline_at="2028-04-15T23:59:59Z",
    )
    headers = make_couple_headers("couple_w13")
    meal = validate_success(api.create_meal_option(
        wedding["id"], create_meal_option_payload(code="ADULT", label="Adult", max_servings=10),
        headers,
    ), expected_status=201)
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Eager", email="eager@example.com"),
        headers,
    ), expected_status=201)

    res = api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    after = validate_success(api.get_guest(guest["id"], headers), expected_status=200)
    assert after["rsvp_status"] == "INVITED"


def test_rsvp_deadline_passed_for_guest_self(api):
    """PRD §3.2: "When a `GuestSelf` is the caller, an additional temporal
    check applies: even if the wedding is still nominally `RSVP_OPEN`, a
    `GuestSelf` RSVP submitted at or after `rsvp_deadline_at` is rejected
    with `ERR_RSVP_DEADLINE_PASSED` (HTTP 409)."

    Design: Corner/validations/rsvp_deadline_passed_for_guest_self
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_dl",
        clock_iso="2027-01-01T00:00:00Z",
        ceremony_at="2027-06-01T18:00:00Z",
        rsvp_deadline_at="2027-05-15T23:59:59Z",
    )
    couple_headers = make_couple_headers("couple_dl")
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="DL", email="dl@example.com"),
        couple_headers,
    ), expected_status=201)
    invitation_token = guest["invitation_token"]
    # Advance the clock past the deadline.
    set_clock("2027-05-16T00:00:00Z")

    self_headers = make_guest_self_headers(guest["id"], invitation_token)
    res = api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, self_headers,
    )
    validate_error(res, ApiErrorId.ERR_RSVP_DEADLINE_PASSED, expected_status=409)
