"""Cook-session scheduling: chef buffer, kitchen occupancy, kitchen hours,
the start precondition, and no-show driven chef suspension.

Queue A (Difficulty): boundary_precision_check, resource_temporal_overlap,
cross_entity_state_dependency.
Queue B (Corner): validations and cross_cutting_complexity_layers.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ingredient, create_cook_session_payload,
    create_client, create_chef, create_active_plan, create_draft_menu, add_meal,
    propose, schedule_session, make_chef_headers, get_session,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def _client_chef_menu(chef=None, client_kwargs=None, week_start_date="2026-03-09T00:00:00Z"):
    """Create a client, (optionally reuse a) chef, active plan, and one DRAFT menu.
    Returns (client, chef, menu)."""
    client = create_client(**(client_kwargs or {}))
    chef = chef or create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan, week_start_date=week_start_date)
    return client, chef, menu


# ─── boundary_precision_check / boundary_chef_buffer_at_exactly_60min ─

def test_chef_buffer_exactly_60_minutes_accepted(api):
    """PRD §3.6: "Exact adjacency — a gap of precisely 60 minutes — is permitted;
    anything closer, including any overlap, is rejected with `ERR_CHEF_SCHEDULE_CONFLICT`."

    Design: Difficulty/boundary_precision_check/boundary_chef_buffer_at_exactly_60min
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu1 = create_draft_menu(client, chef, plan, week_start_date="2026-03-09T00:00:00Z")
    menu2 = create_draft_menu(client, chef, plan, week_start_date="2026-03-16T00:00:00Z")
    schedule_session(menu1, chef, "2026-03-03T09:00:00Z", "2026-03-03T11:00:00Z")
    # Second session starts exactly 60 minutes after the first ends.
    res = api.create_cook_session(
        create_cook_session_payload(menu2["id"], chef["id"],
                                    "2026-03-03T12:00:00Z", "2026-03-03T13:00:00Z"),
        make_chef_headers(chef["id"]))
    sess2 = validate_success(res, 201)
    assert sess2["status"] == "SCHEDULED"


def test_chef_buffer_61_minutes_accepted(api):
    """PRD §3.6: "The new interval must not overlap any other non-terminal session of
    the same chef, and it must additionally be separated from every such session by at
    least the chef buffer of 60 minutes."

    Design: Difficulty/boundary_precision_check/boundary_chef_buffer_at_exactly_60min
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu1 = create_draft_menu(client, chef, plan, week_start_date="2026-03-09T00:00:00Z")
    menu2 = create_draft_menu(client, chef, plan, week_start_date="2026-03-16T00:00:00Z")
    schedule_session(menu1, chef, "2026-03-03T09:00:00Z", "2026-03-03T11:00:00Z")
    res = api.create_cook_session(
        create_cook_session_payload(menu2["id"], chef["id"],
                                    "2026-03-03T12:01:00Z", "2026-03-03T13:00:00Z"),
        make_chef_headers(chef["id"]))
    validate_success(res, 201)


# ─── resource_temporal_overlap / chef_overlap_requires_60min_buffer ───

def test_chef_gap_59_minutes_rejected(api):
    """PRD §3.6: "Exact adjacency — a gap of precisely 60 minutes — is permitted;
    anything closer, including any overlap, is rejected with `ERR_CHEF_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/chef_overlap_requires_60min_buffer
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu1 = create_draft_menu(client, chef, plan, week_start_date="2026-03-09T00:00:00Z")
    menu2 = create_draft_menu(client, chef, plan, week_start_date="2026-03-16T00:00:00Z")
    schedule_session(menu1, chef, "2026-03-03T09:00:00Z", "2026-03-03T11:00:00Z")
    # 59-minute gap — closer than the 60-minute buffer.
    res = api.create_cook_session(
        create_cook_session_payload(menu2["id"], chef["id"],
                                    "2026-03-03T11:59:00Z", "2026-03-03T12:59:00Z"),
        make_chef_headers(chef["id"]))
    validate_error(res, "ERR_CHEF_SCHEDULE_CONFLICT")


def test_chef_overlapping_sessions_rejected(api):
    """PRD §3.6: "The new interval must not overlap any other non-terminal session of
    the same chef, and it must additionally be separated from every such session by at
    least the chef buffer of 60 minutes."

    Design: Difficulty/resource_temporal_overlap/chef_overlap_requires_60min_buffer
    """
    # Same chef across two different clients' kitchens, so ONLY the chef rule can fail.
    chef = create_chef()
    c1, _, menu1 = _client_chef_menu(chef=chef)
    c2, _, menu2 = _client_chef_menu(chef=chef)
    schedule_session(menu1, chef, "2026-03-03T09:00:00Z", "2026-03-03T11:00:00Z")
    res = api.create_cook_session(
        create_cook_session_payload(menu2["id"], chef["id"],
                                    "2026-03-03T10:00:00Z", "2026-03-03T11:00:00Z"),
        make_chef_headers(chef["id"]))
    validate_error(res, "ERR_CHEF_SCHEDULE_CONFLICT")


# ─── resource_temporal_overlap / kitchen_touching_allowed_no_buffer ───

def test_kitchen_touching_sessions_different_chefs_accepted(api):
    """PRD §3.6: "Unlike the chef rule, no buffer is required here: two sessions that
    merely touch back-to-back, with a gap of zero, are allowed; only a genuine overlap
    is rejected, with `ERR_CLIENT_KITCHEN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/kitchen_touching_allowed_no_buffer
    """
    client = create_client()
    chefA = create_chef()
    chefB = create_chef()
    plan = create_active_plan(client)
    menuA = create_draft_menu(client, chefA, plan, week_start_date="2026-03-09T00:00:00Z")
    menuB = create_draft_menu(client, chefB, plan, week_start_date="2026-03-09T00:00:00Z")
    schedule_session(menuA, chefA, "2026-03-03T09:00:00Z", "2026-03-03T11:00:00Z")
    res = api.create_cook_session(
        create_cook_session_payload(menuB["id"], chefB["id"],
                                    "2026-03-03T11:00:00Z", "2026-03-03T13:00:00Z"),
        make_chef_headers(chefB["id"]))
    sessB = validate_success(res, 201)
    assert sessB["status"] == "SCHEDULED"


def test_kitchen_positive_gap_different_chefs_accepted(api):
    """PRD §3.6: "Unlike the chef rule, no buffer is required here: two sessions that
    merely touch back-to-back, with a gap of zero, are allowed; only a genuine overlap
    is rejected, with `ERR_CLIENT_KITCHEN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/kitchen_touching_allowed_no_buffer
    """
    client = create_client()
    chefA = create_chef()
    chefB = create_chef()
    plan = create_active_plan(client)
    menuA = create_draft_menu(client, chefA, plan, week_start_date="2026-03-09T00:00:00Z")
    menuB = create_draft_menu(client, chefB, plan, week_start_date="2026-03-09T00:00:00Z")
    schedule_session(menuA, chefA, "2026-03-03T09:00:00Z", "2026-03-03T11:00:00Z")
    # A positive (non-overlapping) gap at the shared kitchen is also allowed.
    res = api.create_cook_session(
        create_cook_session_payload(menuB["id"], chefB["id"],
                                    "2026-03-03T11:30:00Z", "2026-03-03T13:00:00Z"),
        make_chef_headers(chefB["id"]))
    validate_success(res, 201)


def test_kitchen_overlapping_sessions_rejected(api):
    """PRD §3.6: "The new interval must not overlap any other non-terminal session at
    the same client's kitchen."

    Design: Corner/validations/kitchen_overlap_rejected
    """
    client = create_client()
    chefA = create_chef()
    chefB = create_chef()
    plan = create_active_plan(client)
    menuA = create_draft_menu(client, chefA, plan, week_start_date="2026-03-09T00:00:00Z")
    menuB = create_draft_menu(client, chefB, plan, week_start_date="2026-03-09T00:00:00Z")
    schedule_session(menuA, chefA, "2026-03-03T09:00:00Z", "2026-03-03T11:00:00Z")
    # Different chef (so the chef rule cannot fire), overlapping at the same kitchen.
    res = api.create_cook_session(
        create_cook_session_payload(menuB["id"], chefB["id"],
                                    "2026-03-03T10:00:00Z", "2026-03-03T12:00:00Z"),
        make_chef_headers(chefB["id"]))
    validate_error(res, "ERR_CLIENT_KITCHEN_DOUBLE_BOOKED")


def test_schedule_outside_kitchen_hours_rejected(api):
    """PRD §3.6: "The UTC hour of `scheduled_start` must be at or after the client's
    `kitchen_open_hour`, and the UTC hour of `scheduled_end` must be at or before the
    client's `kitchen_close_hour`. A session that begins before the kitchen opens or
    ends after it closes is rejected with `ERR_OUTSIDE_KITCHEN_HOURS`."

    Design: Corner/validations/schedule_outside_kitchen_hours_rejected
    """
    client, chef, menu = _client_chef_menu(client_kwargs={"kitchen_open_hour": 8,
                                                          "kitchen_close_hour": 20})
    res = api.create_cook_session(
        create_cook_session_payload(menu["id"], chef["id"],
                                    "2026-03-03T06:00:00Z", "2026-03-03T07:00:00Z"),
        make_chef_headers(chef["id"]))
    validate_error(res, "ERR_OUTSIDE_KITCHEN_HOURS")


# ─── cross_entity_state_dependency / start_requires_menu_approved ─────

def test_start_session_on_unapproved_menu_rejected(api):
    """PRD §3.7: "Two conditions gate the start: the parent menu must be in `APPROVED`
    status — starting against a menu that is not approved is rejected with
    `ERR_MENU_NOT_APPROVED`".

    Design: Difficulty/cross_entity_state_dependency/start_requires_menu_approved
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan)
    add_meal(menu, chef, meal_name="Bowl", meal_slot="LUNCH",
             ingredients=[ingredient("rice", 1, "batch", 4000)])
    propose(menu, chef)  # menu is PROPOSED, never APPROVED
    session = schedule_session(menu, chef, "2026-03-03T09:00:00Z", "2026-03-03T12:00:00Z")
    res = api.start_session(session["id"], make_chef_headers(chef["id"]))
    validate_error(res, "ERR_MENU_NOT_APPROVED")


def test_start_failure_leaves_session_scheduled(api):
    """PRD §3.7: "The staffing chef starts a scheduled session, moving it from
    `SCHEDULED` to `IN_PROGRESS`."
    PRD §3.7: "starting against a menu that is not approved is rejected with
    `ERR_MENU_NOT_APPROVED`".

    Design: Difficulty/cross_entity_state_dependency/start_requires_menu_approved
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan)
    add_meal(menu, chef, meal_name="Bowl", meal_slot="LUNCH",
             ingredients=[ingredient("rice", 1, "batch", 4000)])
    propose(menu, chef)
    session = schedule_session(menu, chef, "2026-03-03T09:00:00Z", "2026-03-03T12:00:00Z")
    validate_error(api.start_session(session["id"], make_chef_headers(chef["id"])),
                   "ERR_MENU_NOT_APPROVED")
    assert get_session(session["id"])["status"] == "SCHEDULED"


# ─── cross_cutting / chef_auto_suspends_after_three_no_shows ──────────

def test_chef_auto_suspends_after_third_no_show(api):
    """PRD §3.8: "If that increment brings the chef's strike count to the limit of
    three, the chef transitions from `ACTIVE` to `SUSPENDED`."
    PRD §3.6: "The assigned chef must be `ACTIVE`; a suspended chef cannot be scheduled
    and the attempt is rejected with `ERR_CHEF_SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/chef_auto_suspends_after_three_no_shows
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menus = [create_draft_menu(client, chef, plan, week_start_date=ws) for ws in (
        "2026-03-09T00:00:00Z", "2026-03-16T00:00:00Z",
        "2026-03-23T00:00:00Z", "2026-03-30T00:00:00Z")]
    # Three non-overlapping sessions (adjacent 60-min gaps are allowed).
    s1 = schedule_session(menus[0], chef, "2026-03-03T09:00:00Z", "2026-03-03T10:00:00Z")
    s2 = schedule_session(menus[1], chef, "2026-03-03T11:00:00Z", "2026-03-03T12:00:00Z")
    s3 = schedule_session(menus[2], chef, "2026-03-03T13:00:00Z", "2026-03-03T14:00:00Z")
    get_success_data(api.no_show_session(s1["id"], ADMIN))
    get_success_data(api.no_show_session(s2["id"], ADMIN))
    # Third no-show pushes strikes to the limit of 3 and suspends the chef.
    get_success_data(api.no_show_session(s3["id"], ADMIN))
    # A subsequent schedule attempt is the observable proof the chef is SUSPENDED.
    res = api.create_cook_session(
        create_cook_session_payload(menus[3]["id"], chef["id"],
                                    "2026-03-04T09:00:00Z", "2026-03-04T10:00:00Z"),
        make_chef_headers(chef["id"]))
    validate_error(res, "ERR_CHEF_SUSPENDED")
