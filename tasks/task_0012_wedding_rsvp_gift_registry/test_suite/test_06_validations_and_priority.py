"""Validation rules and priority conflicts: state vs kids-meal, plus-one vs
meal-full, cross-wedding reference, meal-capacity boundary."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_guest_payload,
    create_meal_option_payload,
    create_plus_one_payload,
    make_couple_headers,
    set_clock,
    bootstrap_wedding_in_draft,
    bootstrap_wedding_in_rsvp_open,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / priority_pair_validation_conflict / state_vs_kids_meal_pairing_priority
# ─────────────────────────────────────────────────────────────────────────────

def test_state_vs_kids_meal_pairing_priority(api):
    """PRD §2.9: "then state-machine preconditions on the target entity
    (`ERR_INVALID_STATE` at 409). Business-safety rules — the kids-meal
    pairing rule and the kids-only seating rule — fire next".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_kids_meal_pairing_priority
    """
    set_clock("2027-08-01T00:00:00Z")
    wedding = bootstrap_wedding_in_draft(
        couple_user_id="couple_w9",
        clock_iso="2027-08-01T00:00:00Z",
        ceremony_at="2028-01-01T18:00:00Z",
        rsvp_deadline_at="2027-12-15T23:59:59Z",
    )
    couple = make_couple_headers("couple_w9")
    validate_success(api.create_meal_option(
        wedding["id"],
        create_meal_option_payload(code="ADULT", label="Adult", max_servings=10, is_kids=False),
        couple,
    ), expected_status=201)
    meal_kids = validate_success(api.create_meal_option(
        wedding["id"],
        create_meal_option_payload(code="KIDS", label="Kids pasta", max_servings=10, is_kids=True),
        couple,
    ), expected_status=201)
    g_adult = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Adult", email="adult@example.com", is_child=False),
        couple,
    ), expected_status=201)

    res = api.guest_rsvp(
        g_adult["id"], {"attending": True, "meal_option_id": meal_kids["id"]}, couple,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / priority_pair_validation_conflict / plus_one_referential_vs_meal_full_priority
# ─────────────────────────────────────────────────────────────────────────────

def test_plus_one_referential_vs_meal_full_priority(api):
    """PRD §2.9: "Business-safety rules — the kids-meal pairing rule and the
    kids-only seating rule — fire next, ahead of plus-one eligibility, ahead
    of cross-wedding referential checks, ahead of meal-capacity and
    table-capacity caps".

    Design: Difficulty/priority_pair_validation_conflict/plus_one_referential_vs_meal_full_priority
    """
    set_clock("2027-09-01T00:00:00Z")
    wedding, _adult_meal = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w10",
        clock_iso="2027-09-01T00:00:00Z",
        ceremony_at="2028-02-01T18:00:00Z",
        rsvp_deadline_at="2028-01-15T23:59:59Z",
        title="W10 Wedding",
        adult_meal_max_servings=1,
    )
    couple = make_couple_headers("couple_w10")
    # The bootstrap created an "ADULT" meal with max_servings=1 — we'll use it.
    meal_low = _adult_meal
    g_eats = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Eats It", email="eats@example.com"),
        couple,
    ), expected_status=201)
    g_noplus = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="NoPlus", email="noplus@example.com"),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        g_eats["id"], {"attending": True, "meal_option_id": meal_low["id"]}, couple,
    ), expected_status=200)

    # g_noplus has plus_one_allowed=false AND meal is full → plus-one violation
    # should fire first per PRD priority order.
    res = api.create_plus_one(
        g_noplus["id"],
        create_plus_one_payload(
            full_name="Partner X", is_child=False, meal_option_id=meal_low["id"],
        ),
        couple,
    )
    validate_error(res, ApiErrorId.ERR_PLUS_ONE_NOT_ALLOWED, expected_status=422)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / boundary_precision_check / meal_capacity_exact_boundary_then_overflow
# ─────────────────────────────────────────────────────────────────────────────

def test_meal_capacity_exact_boundary_then_overflow(api):
    """PRD §3.4: "Boundary inclusivity matters here — the cap is inclusive,
    so a count exactly equal to `max_servings` is permitted; only a count
    strictly greater than `max_servings` is rejected."
    PRD §3.4: "a request that would, after the change, raise count(M) above
    M.`max_servings` is rejected with `ERR_MEAL_FULL` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/meal_capacity_exact_boundary_then_overflow
    """
    set_clock("2027-10-01T00:00:00Z")
    wedding, _meal_unused = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w11",
        clock_iso="2027-10-01T00:00:00Z",
        ceremony_at="2028-03-01T18:00:00Z",
        rsvp_deadline_at="2028-02-15T23:59:59Z",
        title="W11 Wedding",
    )
    couple = make_couple_headers("couple_w11")
    meal_bound = validate_success(api.create_meal_option(
        wedding["id"],
        create_meal_option_payload(code="BOUND", label="Bound", max_servings=2, is_kids=False),
        couple,
    ), expected_status=201)
    g1 = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="G1", email="g1@example.com"), couple,
    ), expected_status=201)
    g2 = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="G2", email="g2@example.com"), couple,
    ), expected_status=201)
    g_overflow = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="Ov", email="ov@example.com"), couple,
    ), expected_status=201)

    # count == max_servings is allowed (boundary inclusive).
    validate_success(api.guest_rsvp(
        g1["id"], {"attending": True, "meal_option_id": meal_bound["id"]}, couple,
    ), expected_status=200)
    validate_success(api.guest_rsvp(
        g2["id"], {"attending": True, "meal_option_id": meal_bound["id"]}, couple,
    ), expected_status=200)

    # count would become max_servings + 1 → ERR_MEAL_FULL.
    res = api.guest_rsvp(
        g_overflow["id"], {"attending": True, "meal_option_id": meal_bound["id"]},
        couple,
    )
    validate_error(res, ApiErrorId.ERR_MEAL_FULL, expected_status=422)

    summary = validate_success(api.get_meal_summary(wedding["id"], couple), expected_status=200)
    for item in summary["items"]:
        if item["meal_option_id"] == meal_bound["id"]:
            assert item["count"] == 2, f"count must remain at boundary, got {item['count']}"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / validations / cross_wedding_meal_reference_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_cross_wedding_meal_reference_rejected(api):
    """PRD §2.6: "Cross-wedding foreign-key references are likewise forbidden.
    A guest's chosen `meal_option_id` must refer to a `MealOption` whose
    `wedding_id` matches the guest's own `wedding_id`".
    PRD §2.6: "Any payload that violates these constraints is rejected with
    `ERR_CROSS_WEDDING_REFERENCE` (HTTP 422)."

    Design: Corner/validations/cross_wedding_meal_reference_rejected
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding_a = bootstrap_wedding_in_draft(couple_user_id="couple_xwa")
    wedding_b = bootstrap_wedding_in_draft(
        couple_user_id="couple_xwb",
        clock_iso="2027-01-01T00:00:00Z",
    )
    couple_a = make_couple_headers("couple_xwa")
    couple_b = make_couple_headers("couple_xwb")

    validate_success(api.create_meal_option(
        wedding_a["id"],
        create_meal_option_payload(code="AM", label="A meal", max_servings=10, is_kids=False),
        couple_a,
    ), expected_status=201)
    meal_b = validate_success(api.create_meal_option(
        wedding_b["id"],
        create_meal_option_payload(code="BM", label="B meal", max_servings=10, is_kids=False),
        couple_b,
    ), expected_status=201)
    guest_a = validate_success(api.create_guest(
        wedding_a["id"],
        create_guest_payload(full_name="Across", email="across@example.com"),
        couple_a,
    ), expected_status=201)
    validate_success(api.open_rsvp(wedding_a["id"], couple_a), expected_status=200)

    res = api.guest_rsvp(
        guest_a["id"], {"attending": True, "meal_option_id": meal_b["id"]}, couple_a,
    )
    validate_error(res, ApiErrorId.ERR_CROSS_WEDDING_REFERENCE, expected_status=422)


# ─────────────────────────────────────────────────────────────────────────────
# Corner / errors / error_invalid_request_meal_option_missing_max_servings
# ─────────────────────────────────────────────────────────────────────────────

def test_error_invalid_request_meal_option_missing_max_servings(api):
    """PRD §3.1: "Meal options are added with a short `code` (unique within
    the wedding), a human-readable `label`, an `is_kids` flag (defaulting to
    false) that marks the option as reserved for guests under the wedding's
    kids age threshold, and a `max_servings` integer of at least 1
    representing the caterer's hard ceiling on how many attendees can select
    that meal."
    PRD §2.9: "The shape-level `ERR_INVALID_REQUEST` (HTTP 400) — missing
    required field, malformed enum, integer out of range, empty
    `drafted_body` — fires last."

    Design: Corner/errors/error_invalid_request_meal_option_missing_max_servings
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding = bootstrap_wedding_in_draft(couple_user_id="couple_ir")
    couple = make_couple_headers("couple_ir")

    res = api.create_meal_option(
        wedding["id"], {"code": "X", "label": "X"}, couple,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
