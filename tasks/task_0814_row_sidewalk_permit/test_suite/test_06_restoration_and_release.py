"""Restoration inspection sign-off, the restoration-rejected rework loop,
segment-count maintenance, and the bond-release outstanding-closure gate."""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

REVIEWER_1 = TEST_USERS["reviewer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def test_sign_off_active_closure_returns_invalid_closure_state(api):
    """PRD §3.7: "Signing off a closure that is not `RESTORATION_PENDING` is
    rejected with `ERR_INVALID_CLOSURE_STATE`."

    Design: Corner/state_machines/sign_off_from_active_returns_invalid_closure_state
    """
    ctx = fixtures.setup_issued_permit_with_active_closure(api)
    resp = api.sign_off(
        ctx["closure_id"], {"result": "PASS", "assessed_deficiency_cents": 0}, INSPECTOR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_CLOSURE_STATE.value)


def test_signoff_fail_moves_closure_to_rejected(api):
    """PRD §3.7: "When the `result` fails, the closure moves to
    `RESTORATION_REJECTED`."

    Design: Difficulty/non_linear_state_machine/lane_closure_restoration_reject_cycle
    """
    ctx = fixtures.setup_issued_permit_with_active_closure(api)
    fixtures.request_restoration(api, ctx["closure_id"], ctx["app_id"], 5000)
    rejected = fixtures.sign_off(api, ctx["closure_id"], "FAIL", 30000)
    assert rejected["status"] == "RESTORATION_REJECTED"


def test_rejected_closure_can_request_restoration_again(api):
    """PRD §3.7: "This same request also carries a closure from
    `RESTORATION_REJECTED` back to `RESTORATION_PENDING`, forming the restoration
    loop for closures that failed a prior inspection."

    Design: Difficulty/non_linear_state_machine/lane_closure_restoration_reject_cycle
    """
    ctx = fixtures.setup_issued_permit_with_active_closure(api)
    fixtures.request_restoration(api, ctx["closure_id"], ctx["app_id"], 5000)
    fixtures.sign_off(api, ctx["closure_id"], "FAIL", 30000)
    reworked = fixtures.request_restoration(api, ctx["closure_id"], ctx["app_id"], 2000)
    assert reworked["status"] == "RESTORATION_PENDING"


def test_signoff_pass_restores_closure(api):
    """PRD §3.7: "When the `result` passes, the closure moves to `RESTORED`, and
    the occupied segment's `active_lane_closure_count` is decremented by one."

    Design: Difficulty/transitive_cascade/signoff_restores_closure_decrements_segment_depth2
    """
    ctx = fixtures.setup_issued_permit_with_active_closure(api)
    fixtures.request_restoration(api, ctx["closure_id"], ctx["app_id"], 0)
    restored = fixtures.sign_off(api, ctx["closure_id"], "PASS", 0)
    assert restored["status"] == "RESTORED"


def test_signoff_pass_decrements_segment_count(api):
    """PRD §3.7: "When the `result` passes, the closure moves to `RESTORED`, and
    the occupied segment's `active_lane_closure_count` is decremented by one."

    Design: Difficulty/transitive_cascade/signoff_restores_closure_decrements_segment_depth2
    """
    ctx = fixtures.setup_issued_permit_with_active_closure(api)
    fixtures.request_restoration(api, ctx["closure_id"], ctx["app_id"], 0)
    fixtures.sign_off(api, ctx["closure_id"], "PASS", 0)
    seg = get_success_data(api.get_street_segment(ctx["seg_id"], REVIEWER_1))
    assert seg["active_lane_closure_count"] == 0


def test_bond_release_with_active_closure_rejected(api):
    """PRD §3.7: "Release is gated: every lane closure on the bond's permit must
    be terminal — in `RESTORED` or `VOIDED` — or the release is rejected with
    `ERR_CLOSURES_OUTSTANDING`."

    Design: Difficulty/cross_entity_state_dependency/bond_release_requires_closures_terminal
    """
    ctx = fixtures.setup_issued_permit_with_active_closure(api)
    resp = api.release_bond(ctx["bond_id"], REVIEWER_1)
    validate_error(resp, ApiErrorId.ERR_CLOSURES_OUTSTANDING.value)


def test_bond_stays_posted_after_failed_release(api):
    """PRD §3.7: "A `PermitReviewer` or a `PlatformAdmin` releases a bond that is
    `POSTED`, moving it to `RELEASED`."
    PRD §3.7: "Release is gated: every lane closure on the bond's permit must be
    terminal — in `RESTORED` or `VOIDED` — or the release is rejected with
    `ERR_CLOSURES_OUTSTANDING`."

    Design: Difficulty/cross_entity_state_dependency/bond_release_requires_closures_terminal
    """
    ctx = fixtures.setup_issued_permit_with_active_closure(api)
    resp = api.release_bond(ctx["bond_id"], REVIEWER_1)
    validate_error(resp, ApiErrorId.ERR_CLOSURES_OUTSTANDING.value)
    bonds = get_success_data(api.list_bond(ctx["permit_id"], REVIEWER_1))
    assert bonds[0]["status"] == "POSTED"
