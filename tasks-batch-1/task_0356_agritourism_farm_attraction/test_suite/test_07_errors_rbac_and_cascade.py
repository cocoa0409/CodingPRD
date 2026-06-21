"""Breadth coverage: the error catalog (pricing/policy/pass/window-cancelled
errors), RBAC (unauthenticated, forbidden role, not-owner), and the cancel
cascade that voids child line items.
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_farm_payload, create_season_pass_payload, create_reservation_payload,
)
from test_helpers.test_users import make_visitor_headers

MANAGER = fx.MANAGER
GATE = fx.GATE


# ===========================================================================
# Queue B — errors
# ===========================================================================

def test_issue_pass_without_active_policy_rejected(api):
    """PRD §3.1: "Pricing operations that need a live rate card — issuing a season
    pass, attaching an activity pass, computing an admission or pumpkin charge —
    depend on the farm having exactly one `ACTIVE` policy; when none exists, the
    operation is rejected with `ERR_NO_ACTIVE_POLICY`."

    Design: Corner/errors/pricing_op_without_active_policy_rejected
    """
    farm = fx.create_farm(name="No Policy Farm")
    # Create a DRAFT policy but never activate it.
    fx.create_policy(farm["id"])
    visitor = fx.create_visitor(email="np@x.com", full_name="Nina Policy")

    resp = api.create_season_pass(
        farm["id"], create_season_pass_payload(visitor["id"]), MANAGER)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_POLICY.value)


def test_activate_already_active_policy_rejected(api):
    """PRD §3.1: "Activating a policy that is already `ACTIVE` or already
    `SUPERSEDED` is rejected with `ERR_POLICY_ALREADY_ACTIVE`."

    Design: Corner/errors/activate_already_active_policy_rejected
    """
    farm = fx.create_farm(name="Reactivate Farm")
    policy = fx.create_active_policy(farm["id"])
    resp = api.activate_pricing_policy(policy["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_POLICY_ALREADY_ACTIVE.value)


def test_revoke_already_revoked_pass_rejected(api):
    """PRD §3.2: "Revoking a pass that is already `REVOKED` is rejected with
    `ERR_PASS_ALREADY_REVOKED`."

    Design: Corner/errors/revoke_already_revoked_pass_rejected
    """
    farm = fx.create_farm(name="Revoke Farm")
    fx.create_active_policy(farm["id"])
    visitor = fx.create_visitor(email="rv2@x.com", full_name="Rose Void")
    season_pass = fx.create_season_pass(farm["id"], visitor["id"])
    validate_success(api.revoke_season_pass(season_pass["id"], MANAGER))

    resp = api.revoke_season_pass(season_pass["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_PASS_ALREADY_REVOKED.value)

    after = validate_success(api.get_season_pass(season_pass["id"], MANAGER))
    assert after["status"] == "REVOKED"


def test_create_against_closure_cancelled_window_rejected(api):
    """PRD §3.3: "a create against a closure-cancelled window is rejected with
    `ERR_WINDOW_CANCELLED`, and this holds even after the farm reopens, because a
    cancelled window admits nothing."
    PRD §3.6: "A `CLEARED` event declared while the farm is `CLOSED` reopens
    posture `CLOSED → OPEN` and clears `active_weather_event_id`, but does not
    revive any window the closure cancelled — only posture reopens."

    Design: Corner/errors/operate_on_cancelled_window_rejected
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Cancelled Window Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=5)
    # Close (cancels the window), then clear (reopens the farm but not the window).
    fx.declare_closure(farm["id"], note="closure cancels window")
    fx.declare_cleared(farm["id"], note="reopened")
    visitor = fx.create_visitor(email="cw2@x.com", full_name="Cal Window")

    v_now = fx.window_version(window["id"])
    resp = api.create_reservation(
        create_reservation_payload(window["id"], visitor["id"], v_now, adult_count=1, child_count=0),
        make_visitor_headers(visitor["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_CANCELLED.value)

    win_after = validate_success(api.get_admission_window(window["id"], MANAGER))
    assert win_after["status"] == "CANCELLED"
    farm_after = validate_success(api.get_farm(farm["id"], MANAGER))
    assert farm_after["operational_status"] == "OPEN"


# ===========================================================================
# Queue B — rbac
# ===========================================================================

def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    resp = api.create_farm(create_farm_payload(name="NoAuth Farm"), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_gate_agent_cannot_create_farm_forbidden(api):
    """PRD §2.1: "When a request is authenticated but the acting role is not
    permitted to perform the requested operation, the response is
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/gate_agent_cannot_create_farm_forbidden
    """
    resp = api.create_farm(create_farm_payload(name="Forbidden Farm"), GATE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_visitor_cannot_cancel_other_visitors_reservation(api):
    """PRD §2.1: "When an entity-backed user targets a resource they do not own,
    the operation is rejected with `ERR_NOT_OWNER`; this guard covers the
    reservation-owner actions (confirm, cancel, and the attachment of activity
    passes, waivers, and pumpkin purchases)".

    Design: Corner/rbac/visitor_cannot_cancel_other_visitors_reservation_not_owner
    """
    s = fx.setup_farm_with_visitor(capacity=5, visitor_email="oa@x.com")
    va = s["visitor"]
    vb = fx.create_visitor(email="ob@x.com", full_name="Olga B")
    res = fx.create_pending_reservation(s["window"]["id"], va["id"], s["window"]["version"],
                                        adult_count=1, child_count=0)

    # Visitor B attempts to cancel Visitor A's reservation.
    resp = api.cancel_reservation(res["id"], make_visitor_headers(vb["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)

    after = validate_success(api.get_reservation(res["id"], make_visitor_headers(va["id"])))
    assert after["status"] == "PENDING"


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / cancel voids child lines
# ===========================================================================

def test_cancel_reservation_voids_child_lines(api):
    """PRD §3.3: "Cancellation revokes every child `ActivityPass` (their `status`
    becomes `REVOKED`), voids every child `Waiver` (`VOID`), voids every child
    `PumpkinPurchase` (`VOID`), and refunds every child `ConcessionOrder`
    (`REFUNDED`)."

    Design: Corner/cross_cutting_complexity_layers/cancel_reservation_voids_child_lines
    """
    s = fx.setup_farm_with_visitor(capacity=5)
    res = fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"],
                                        s["window"]["version"], adult_count=1, child_count=0)
    ap = fx.add_activity_pass(res["id"], s["visitor"]["id"], "MAZE", quantity=1)
    co = fx.add_concession(res["id"], s["visitor"]["id"], food_cents=500, vehicle_count=1)
    wv = fx.sign_waiver(res["id"], s["visitor"]["id"], "Cara Cascade")

    fx.cancel_reservation(res["id"], s["visitor"]["id"])

    headers = make_visitor_headers(s["visitor"]["id"])
    ap_after = next(x for x in validate_success(api.list_activity_passes(res["id"], headers)) if x["id"] == ap["id"])
    co_after = next(x for x in validate_success(api.list_concession_orders(res["id"], headers)) if x["id"] == co["id"])
    wv_after = next(x for x in validate_success(api.list_waivers(res["id"], headers)) if x["id"] == wv["id"])

    assert ap_after["status"] == "REVOKED"
    assert co_after["status"] == "REFUNDED"
    assert wv_after["status"] == "VOID"
