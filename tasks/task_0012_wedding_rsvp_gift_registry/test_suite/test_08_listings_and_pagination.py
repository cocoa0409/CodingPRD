"""Listings, pagination, not-found, and immediate-consistency read paths."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_guest_payload,
    make_couple_headers,
    set_clock,
    bootstrap_wedding_in_draft,
    bootstrap_wedding_in_rsvp_open,
)


# ─────────────────────────────────────────────────────────────────────────────
# Corner / endpoints / list_guests_pagination_envelope
# ─────────────────────────────────────────────────────────────────────────────

def test_list_guests_pagination_envelope(api):
    """PRD §2.3: "All list endpoints accept two query parameters that govern
    paging: `limit` controls the maximum number of rows returned and defaults
    to 10, with a minimum of 1 and a maximum of 100; `offset` controls how
    many rows to skip and defaults to 0 with no upper bound beyond the size
    of the underlying set."
    PRD §2.3: "the `meta` block carries `limit`, `offset`, `total_count`,
    and `has_more` so a client can paginate without re-counting."

    Design: Corner/endpoints/list_guests_pagination_envelope
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding = bootstrap_wedding_in_draft(couple_user_id="couple_pg")
    couple = make_couple_headers("couple_pg")
    for i in range(3):
        validate_success(api.create_guest(
            wedding["id"],
            create_guest_payload(
                full_name=f"P{i+1}", email=f"p{i+1}@example.com",
            ),
            couple,
        ), expected_status=201)

    res = api.list_wedding_guests(wedding["id"], couple, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] >= 3
    assert len(data) == 2
    assert meta["has_more"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Corner / endpoints / get_nonexistent_wedding_returns_404
# ─────────────────────────────────────────────────────────────────────────────

def test_get_nonexistent_wedding_returns_404(api):
    """PRD §2.5: "The server validates path identifiers strictly
    left-to-right and returns `ERR_NOT_FOUND` (HTTP 404) for the
    **leftmost** identifier that fails to resolve to a live row."

    Design: Corner/endpoints/get_nonexistent_wedding_returns_404
    """
    res = api.get_wedding(
        "00000000-0000-0000-0000-000000000000",
        make_couple_headers("couple_nf"),
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


# ─────────────────────────────────────────────────────────────────────────────
# Corner / consistency / immediate_visibility_of_rsvp_in_meal_summary
# ─────────────────────────────────────────────────────────────────────────────

def test_immediate_visibility_of_rsvp_in_meal_summary(api):
    """PRD §3.4: "Whenever a guest's `rsvp_status` flips between `ATTENDING`
    and `DECLINED`, or whenever a plus-one does likewise, or whenever a
    couple changes a `meal_option_id` on an already-`ATTENDING` guest or
    plus-one, the server recomputes per-meal attendance counts."

    Design: Corner/consistency/immediate_visibility_of_rsvp_in_meal_summary
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_im")
    couple = make_couple_headers("couple_im")
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Imm", email="imm@example.com"),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    summary = validate_success(api.get_meal_summary(wedding["id"], couple),
                               expected_status=200)
    assert summary["total_attendees"] == 1
    found = False
    for item in summary["items"]:
        if item["meal_option_id"] == meal["id"]:
            assert item["count"] == 1
            found = True
    assert found


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations / meal_count_aggregation_excludes_declined
# ─────────────────────────────────────────────────────────────────────────────

def test_meal_count_aggregation_excludes_declined(api):
    """PRD §3.4: "For each `MealOption` of the wedding, the count is the
    number of `Guest` rows belonging to that wedding whose `rsvp_status` is
    `ATTENDING` and whose `meal_option_id` equals that meal's `id`, plus the
    number of `PlusOne` rows under the same condition. `INVITED` rows are
    excluded; `DECLINED` rows are excluded; rows where `meal_option_id` is
    null are excluded."

    Design: Corner/calculations/meal_count_aggregation_excludes_declined
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_ex")
    couple = make_couple_headers("couple_ex")
    g_yes = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Yes", email="yes@example.com"),
        couple,
    ), expected_status=201)
    g_no = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="No", email="no@example.com"),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        g_yes["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    validate_success(api.guest_rsvp(
        g_no["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    validate_success(api.guest_rsvp(
        g_no["id"], {"attending": False}, couple,
    ), expected_status=200)

    summary = validate_success(api.get_meal_summary(wedding["id"], couple),
                               expected_status=200)
    by_id = {item["meal_option_id"]: item for item in summary["items"]}
    assert by_id[meal["id"]]["count"] == 1
    assert summary["total_attendees"] == 1
