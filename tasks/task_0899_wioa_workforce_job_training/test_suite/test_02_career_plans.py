"""Career-plan cyclic lifecycle (ACTIVE <-> UNDER_REVISION) and its guards."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_area, intake_participant, make_eligible, create_plan, activate_plan,
    CM,
)


def _active_plan(api):
    area = create_area(api)
    p = intake_participant(api, area["id"])
    make_eligible(api, p["id"])
    cp = create_plan(api, p["id"])
    activate_plan(api, cp["id"])
    return cp["id"]


def test_revision_cycle_twice_reaches_count_two(api):
    """PRD §3.3: "Approving a revision returns an `UNDER_REVISION` plan to `ACTIVE`
    and increments `revision_count` by one (rejected with `ERR_INVALID_STATE` unless
    `UNDER_REVISION`). The `ACTIVE ↔ UNDER_REVISION` cycle may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/career_plan_revision_cycle
    """
    cp_id = _active_plan(api)
    validate_success(api.request_revision(cp_id, CM))
    validate_success(api.approve_revision(cp_id, CM))
    validate_success(api.request_revision(cp_id, CM))
    final = validate_success(api.approve_revision(cp_id, CM))
    assert final["status"] == "ACTIVE", final
    assert final["revision_count"] == 2, final


def test_single_revision_cycle_increments_count_once(api):
    """PRD §3.3: "Requesting a revision on an `ACTIVE` plan advances its `status` to
    `UNDER_REVISION` (rejected with `ERR_INVALID_STATE` unless `ACTIVE`). Approving a
    revision returns an `UNDER_REVISION` plan to `ACTIVE` and increments `revision_count`
    by one".

    Design: Difficulty/non_linear_state_machine/career_plan_revision_cycle
    """
    cp_id = _active_plan(api)
    under = validate_success(api.request_revision(cp_id, CM))
    assert under["status"] == "UNDER_REVISION", under
    back = validate_success(api.approve_revision(cp_id, CM))
    assert back["status"] == "ACTIVE", back
    assert back["revision_count"] == 1, back


def test_approve_revision_on_active_plan_rejected(api):
    """PRD §3.3: "Approving a revision returns an `UNDER_REVISION` plan to `ACTIVE` and
    increments `revision_count` by one (rejected with `ERR_INVALID_STATE` unless
    `UNDER_REVISION`)."

    Design: Corner/state_machines/approve_revision_on_active_plan_returns_invalid_state
    """
    cp_id = _active_plan(api)
    resp = api.approve_revision(cp_id, CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
