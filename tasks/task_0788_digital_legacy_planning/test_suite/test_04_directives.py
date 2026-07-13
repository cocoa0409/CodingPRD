"""Advance directives: the ACTIVE<->UNDER_REVISION cycle, OCC on plan version, and
terminal lockdown."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_owner_headers,
    set_clock, create_plan, create_directive, get_plan, setup_activated_directive,
)


# --------------------------------------------------------------------------- #
# directive_revision_cycle  (Difficulty/non_linear_state_machine)
# --------------------------------------------------------------------------- #
def test_revise_moves_active_directive_to_under_revision_bumping_version_number(api):
    """PRD 3.5: "Revising an active directive moves it to `UNDER_REVISION` and increments
    its `version_number` by one."

    Design: Difficulty/non_linear_state_machine/directive_revision_cycle
    """
    ctx = setup_activated_directive(api)
    owner = make_owner_headers(ctx["plan_id"])
    data = validate_success(api.revise_directive(ctx["directive_id"], owner), 200)
    assert data["status"] == "UNDER_REVISION", f"expected UNDER_REVISION, got {data['status']}"
    assert data["version_number"] == 2, f"expected version_number 2, got {data['version_number']}"


def test_reactivate_after_revision_returns_active_with_version_number_two(api):
    """PRD 3.5: "Its lifecycle is `DRAFT | UNDER_REVISION → ACTIVE`, with `ACTIVE →
    UNDER_REVISION` for edits, and `SUPERSEDED` and `REVOKED` as terminal states."
    PRD 3.5: "Revising an active directive moves it to `UNDER_REVISION` and increments its
    `version_number` by one."

    Design: Difficulty/non_linear_state_machine/directive_revision_cycle
    """
    ctx = setup_activated_directive(api)
    owner = make_owner_headers(ctx["plan_id"])
    api.revise_directive(ctx["directive_id"], owner)
    plan_now = get_plan(api, ctx["plan_id"])
    data = validate_success(
        api.activate_directive(ctx["directive_id"],
                               {"expected_plan_version": plan_now["version"]}, owner), 200)
    assert data["status"] == "ACTIVE", f"expected ACTIVE after re-activation, got {data['status']}"
    assert data["version_number"] == 2, f"expected version_number 2, got {data['version_number']}"


# --------------------------------------------------------------------------- #
# directive_activate_stale_plan_version_conflict  (Corner/errors)
# --------------------------------------------------------------------------- #
def test_activate_second_directive_with_stale_plan_version_conflicts(api):
    """PRD 2.6: "Therefore, if `expected_plan_version` does not equal the plan's current
    `version`, the activation is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 3.5: "On a successful activation, any other directive of the same `directive_type`
    that is currently `ACTIVE` on the plan is superseded (moved to `SUPERSEDED`), and the
    plan's `version` increments by one."

    Design: Corner/errors/directive_activate_stale_plan_version_conflict
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id, stale_version = plan["id"], plan["version"]
    owner = make_owner_headers(plan_id)
    dir_a = create_directive(api, plan_id, directive_type="MEDICAL", content="A")
    dir_b = create_directive(api, plan_id, directive_type="MEDICAL", content="B")
    # Activate A against the observed plan version -> plan version advances past `stale_version`.
    validate_success(api.activate_directive(
        dir_a["id"], {"expected_plan_version": stale_version}, owner), 200)
    # Activating B while still carrying the pre-first-activate version is stale.
    resp = api.activate_directive(dir_b["id"], {"expected_plan_version": stale_version}, owner)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# --------------------------------------------------------------------------- #
# revise_revoked_directive_terminal_lockdown  (Corner/state_machines)
# --------------------------------------------------------------------------- #
def test_revise_revoked_directive_rejected(api):
    """PRD 3.5: "An owner may revoke a directive from `DRAFT`, `ACTIVE`, or
    `UNDER_REVISION`, moving it to the terminal `REVOKED` state."
    PRD 2.8: "Sixth, for state-transition endpoints, the target must be in a state from
    which the requested transition is defined, otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/revise_revoked_directive_terminal_lockdown
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = create_plan(api)
    plan_id = plan["id"]
    owner = make_owner_headers(plan_id)
    directive = create_directive(api, plan_id, directive_type="FUNERAL", content="wishes")
    validate_success(api.revoke_directive(directive["id"], owner), 200)
    resp = api.revise_directive(directive["id"], owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
