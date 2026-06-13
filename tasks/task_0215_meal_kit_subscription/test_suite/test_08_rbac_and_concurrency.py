"""RBAC enforcement (role permission + member ownership) and optimistic-concurrency on plan
changes.

Translates queue B (Corner) rbac and optimistic_concurrency instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, create_plan, create_zone, create_recipes,
    register_member, create_subscription, create_box, add_recipes_to_box,
    lock_box, plan_change_payload,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


# ─── Corner: rbac / member_cannot_charge_box ────────────────────────────────

def test_member_cannot_charge_box(api):
    """PRD §2.1: "When the headers are well-formed but the role (or the specific identity) is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: charge is authorized for "PlatformOps" only.

    Design: Corner/rbac/member_cannot_charge_box
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    recipes = create_recipes(2, prefix="RB")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    hdr = make_member_headers(member["id"])
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes)
    lock_box(member, box)
    set_clock("2026-07-11T00:00:00.000Z")
    # Member attempts a PlatformOps-exclusive charge.
    res = api.charge_box(box["id"], hdr)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


# ─── Corner: rbac / member_cannot_act_on_another_members_subscription ────────

def test_member_cannot_cancel_another_members_subscription(api):
    """PRD §2.1: "A member acting on a subscription, weekly box, or box-recipe slot it does not own is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/member_cannot_act_on_another_members_subscription
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    m1 = register_member(zone["id"], full_name="OW1")
    m2 = register_member(zone["id"], full_name="OW2")
    sub = create_subscription(m1, plan)  # owned by m1
    # m2 (a different member) tries to cancel m1's subscription.
    res = api.cancel_subscription(sub["id"], make_member_headers(m2["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


# ─── Corner: optimistic_concurrency / occ_correct_version_plan_change_succeeds ──

def test_plan_change_with_correct_version_succeeds(api):
    """PRD §2.10: "A successful plan change installs the new plan as the one in force and increments the subscription's `version` by one."
    PRD §3.3: "On success the new plan supersedes the prior binding and the subscription's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_plan_change_succeeds
    """
    set_clock("2026-07-01T00:00:00.000Z")
    p1 = create_plan(servings_per_meal=2, meals_per_week=2, code="OCC1")
    p2 = create_plan(servings_per_meal=4, meals_per_week=3, code="OCC2")
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, p1)
    assert sub["version"] == 1
    changed = validate_success(api.change_plan(
        sub["id"], plan_change_payload(p2["id"], sub["version"]),
        make_member_headers(member["id"])), 200)
    assert changed["plan_id"] == p2["id"]
    assert changed["version"] == 2


# ─── Corner: optimistic_concurrency / occ_stale_version_plan_change_rejected ──

def test_plan_change_with_stale_version_rejected(api):
    """PRD §2.10: "The server compares it to the subscription's current `version`; if they do not match — because a pause, a resume, or an earlier plan change has advanced the version since the client last read the subscription — the request is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_plan_change_rejected
    """
    set_clock("2026-07-01T00:00:00.000Z")
    p1 = create_plan(servings_per_meal=2, meals_per_week=2, code="ST1")
    p2 = create_plan(servings_per_meal=4, meals_per_week=3, code="ST2")
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, p1)
    stale_version = sub["version"]  # observed as 1
    hdr = make_member_headers(member["id"])
    # Pause advances version to 2, making the observed version stale.
    validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-08-01T00:00:00.000Z"}, hdr), 200)
    res = api.change_plan(sub["id"], plan_change_payload(p2["id"], stale_version), hdr)
    validate_error(res, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION.value, expected_status=412)
