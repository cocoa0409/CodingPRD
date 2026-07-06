"""The completion production cascade, the client-cancel cascade, container shelf
life, and the divergent no-show branch.

Queue A (Difficulty): transitive_cascade, non_linear_state_machine.
Queue B (Corner): entities (container use-by).
"""
from datetime import datetime, timedelta

from test_helpers import (
    validate_success, get_success_data,
    ingredient,
    setup_cooked_single_meal, setup_approved_single_meal, schedule_session,
    containers_for_meal, get_menu, get_session, get_client,
    make_client_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ─── transitive_cascade / cascade_session_complete depth 3 ────────────

def test_completion_cascades_menu_and_meal_to_cooked(api):
    """PRD §3.7: "Completion drives a three-level production cascade off the parent
    menu. The menu advances from `APPROVED` to `COOKED`. Every one of the menu's meals
    still in `PLANNED` advances to `COOKED`."

    Design: Difficulty/transitive_cascade/cascade_session_complete_menu_meal_container_depth3
    """
    ctx = setup_cooked_single_meal(
        meal_kwargs={"meal_name": "Curry", "meal_slot": "DINNER", "servings": 2,
                     "is_perishable": True,
                     "ingredients": [ingredient("lentils", 1, "batch", 4000)]},
        scheduled_start="2026-03-03T10:00:00Z", scheduled_end="2026-03-03T12:00:00Z",
        clock_at_start="2026-03-03T09:00:00Z")
    assert ctx["menu"]["status"] == "COOKED"
    meal_after = validate_success(api.get_menu_meal(ctx["meal"]["id"], ADMIN), 200)
    assert meal_after["status"] == "COOKED"


def test_completion_produces_container_with_useby_and_portions(api):
    """PRD §3.7: "For each meal that becomes `COOKED`, a container is synthesized to
    hold its leftovers: the container records the `menu_meal_id` it portions, a
    `label_prep_date` equal to the logical clock at the moment the session completed, a
    `portion_count` copied from that meal's `servings`, and a `label_use_by_date`
    derived from the prep date — the prep date plus 3 days when the meal is perishable,
    or plus 5 days when it is not."

    Design: Difficulty/transitive_cascade/cascade_session_complete_menu_meal_container_depth3
    """
    ctx = setup_cooked_single_meal(
        meal_kwargs={"meal_name": "Curry", "meal_slot": "DINNER", "servings": 2,
                     "is_perishable": True,
                     "ingredients": [ingredient("lentils", 1, "batch", 4000)]},
        scheduled_start="2026-03-03T10:00:00Z", scheduled_end="2026-03-03T12:00:00Z",
        clock_at_start="2026-03-03T09:00:00Z")
    containers = containers_for_meal(ctx["meal"]["id"])
    assert len(containers) == 1
    container = containers[0]
    assert container["portion_count"] == 2
    # Clock was 2026-03-03T09:00:00Z at completion -> prep date; use-by is prep + 3 days.
    assert container["label_prep_date"].startswith("2026-03-03T09:00:00")
    assert _parse(container["label_use_by_date"]) - _parse(container["label_prep_date"]) \
        == timedelta(days=3)


def test_container_non_perishable_uses_five_day_shelf_life(api):
    """PRD §3.7: "a `label_use_by_date` derived from the prep date — the prep date plus
    3 days when the meal is perishable, or plus 5 days when it is not."

    Design: Corner/entities/container_use_by_non_perishable_five_days
    """
    ctx = setup_cooked_single_meal(
        meal_kwargs={"meal_name": "Jerky", "meal_slot": "LUNCH", "servings": 3,
                     "is_perishable": False,
                     "ingredients": [ingredient("dried beef", 1, "bag", 4000)]},
        scheduled_start="2026-03-03T10:00:00Z", scheduled_end="2026-03-03T11:00:00Z",
        clock_at_start="2026-03-03T10:00:00Z")
    containers = containers_for_meal(ctx["meal"]["id"])
    assert len(containers) == 1
    container = containers[0]
    assert container["portion_count"] == 3
    assert container["label_prep_date"].startswith("2026-03-03T10:00:00")
    assert _parse(container["label_use_by_date"]) - _parse(container["label_prep_date"]) \
        == timedelta(days=5)


# ─── transitive_cascade / cascade_client_cancel depth 2 ───────────────

def test_client_cancel_cascades_menu_to_cancelled(api):
    """PRD §3.1: "Cancelling a client is a `PlatformAdmin` action that moves the
    client's `status` from `ACTIVE` to `CANCELLED` and cascades: every one of that
    client's menus whose status is `DRAFT`, `PROPOSED`, `APPROVED`, or `SKIPPED` is
    driven to `CANCELLED`".

    Design: Difficulty/transitive_cascade/cascade_client_cancel_menu_session_depth2
    """
    ctx = setup_approved_single_meal(meal_kwargs={
        "meal_name": "Bowl", "meal_slot": "LUNCH",
        "ingredients": [ingredient("rice", 1, "batch", 4000)]})
    schedule_session(ctx["menu"], ctx["chef"], "2026-03-03T09:00:00Z", "2026-03-03T12:00:00Z")
    cancelled = validate_success(api.cancel_client(ctx["client"]["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_menu(ctx["menu"]["id"])["status"] == "CANCELLED"


def test_client_cancel_cascades_session_to_cancelled(api):
    """PRD §3.8: "when a menu is cancelled its non-terminal sessions are driven to
    `CANCELLED`, the provisional payout is no longer owed, and the chef's schedule slot
    and the kitchen slot are freed."

    Design: Difficulty/transitive_cascade/cascade_client_cancel_menu_session_depth2
    """
    ctx = setup_approved_single_meal(meal_kwargs={
        "meal_name": "Bowl", "meal_slot": "LUNCH",
        "ingredients": [ingredient("rice", 1, "batch", 4000)]})
    session = schedule_session(ctx["menu"], ctx["chef"],
                               "2026-03-03T09:00:00Z", "2026-03-03T12:00:00Z")
    get_success_data(api.cancel_client(ctx["client"]["id"], ADMIN))
    assert get_session(session["id"])["status"] == "CANCELLED"


# ─── non_linear_state_machine / branching no-show divergent effects ───

def test_no_show_sets_session_noshow_and_grants_client_credit(api):
    """PRD §3.8: "Reporting moves the session from `SCHEDULED` to `NO_SHOW` and
    produces two divergent side effects with no menu progression: the client is
    compensated by adding the client's `weekly_base_fee_cents` to their
    `wallet_credit_cents`, and the chef's `no_show_strikes` is incremented by one."

    Design: Difficulty/non_linear_state_machine/branching_session_noshow_divergent_effects
    """
    ctx = setup_approved_single_meal(
        client_kwargs={"weekly_base_fee_cents": 5000},
        meal_kwargs={"meal_name": "Bowl", "meal_slot": "LUNCH",
                     "ingredients": [ingredient("rice", 1, "batch", 4000)]})
    session = schedule_session(ctx["menu"], ctx["chef"],
                               "2026-03-03T09:00:00Z", "2026-03-03T12:00:00Z")
    reported = validate_success(
        api.no_show_session(session["id"], make_client_headers(ctx["client"]["id"])), 200)
    assert reported["status"] == "NO_SHOW"
    assert get_client(ctx["client"]["id"])["wallet_credit_cents"] == 5000


def test_no_show_does_not_progress_the_menu(api):
    """PRD §3.8: "Reporting moves the session from `SCHEDULED` to `NO_SHOW` and
    produces two divergent side effects with no menu progression".

    Design: Difficulty/non_linear_state_machine/branching_session_noshow_divergent_effects
    """
    ctx = setup_approved_single_meal(
        client_kwargs={"weekly_base_fee_cents": 5000},
        meal_kwargs={"meal_name": "Bowl", "meal_slot": "LUNCH",
                     "ingredients": [ingredient("rice", 1, "batch", 4000)]})
    session = schedule_session(ctx["menu"], ctx["chef"],
                               "2026-03-03T09:00:00Z", "2026-03-03T12:00:00Z")
    get_success_data(api.no_show_session(session["id"], make_client_headers(ctx["client"]["id"])))
    assert get_menu(ctx["menu"]["id"])["status"] == "APPROVED"
