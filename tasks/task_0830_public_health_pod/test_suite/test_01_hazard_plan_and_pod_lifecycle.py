"""HazardPlan and POD lifecycle: creation defaults, pagination, terminal lockdown,
the POD operational_status cycle, and the HazardPlan<->POD stand-down/close gates."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_hazard_plan_payload,
    create_hazard_plan,
    create_activated_hazard_plan,
    create_pod,
    create_open_pod,
    open_pod,
    restrict_pod,
    resume_pod,
    close_pod,
    setup_activated_plan_with_open_pod,
    create_verified_staff_member,
    create_confirmed_shift_assignment,
    create_checked_in_shift_assignment,
)


def test_hazard_plan_creation_returns_declared_defaults(api, admin_headers):
    """PRD §3.1: "The plan starts in `DRAFT`."
    PRD §3.1: "It starts at 0 on plan creation and is recomputed synchronously
    every time a drill is completed or has its corrective action closed — see §3.7."

    Design: Corner/entities/hazard_plan_creation_returns_all_declared_fields
    """
    payload = create_hazard_plan_payload(
        hazard_type="NATURAL_DISASTER", title="Corner Creation Plan",
        jurisdiction_code="CTY20", target_population=4200,
    )
    res = api.create_hazard_plan(payload, admin_headers)
    hp = validate_success(res, 201)
    assert hp["status"] == "DRAFT"
    assert hp["readiness_score"] == 0
    assert hp["hazard_type"] == "NATURAL_DISASTER"


def test_pod_list_pagination_limit_and_has_more(api, admin_headers):
    """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
    `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100;
    `offset` defaults to 0."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`,
    `has_more`) are included for list endpoints."

    Design: Corner/entities/pod_listing_pagination_total_count_has_more
    """
    hp = create_activated_hazard_plan()
    for i in range(3):
        create_pod(hp["id"], site_name=f"Page POD {i + 1}")

    data, meta = validate_paginated(
        api.list_pods(admin_headers, params={"hazard_plan_id": hp["id"], "limit": 2, "offset": 0})
    )
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_pod_reopen_after_close_rejected_terminal_state(api, admin_headers):
    """PRD §3.2: "Closing a POD is permitted from `STAGING`, `OPERATIONAL`, or
    `RESTRICTED`, moves it to the terminal `CLOSED` state, and is blocked
    (`ERR_POD_STAFF_ONSITE`) while any `ShiftAssignment` at that POD is currently
    `CHECKED_IN`..."

    Design: Corner/entities/pod_closed_terminal_lockdown
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    close_pod(pod["id"])

    res = api.open_pod(pod["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_pod_restrict_then_resume_returns_to_operational(api, admin_headers):
    """PRD §3.2: "From `OPERATIONAL`, a POD can be manually restricted by
    `PublicHealthAdmin`, or automatically restricted by the system as the
    second hop of either cascade described in §2.6 — the InventoryLot-depletion
    cascade triggered by dispensing (§3.6) or the credential-revocation cascade
    triggered by revoking a staff member's credential (§3.3) — landing in
    `RESTRICTED` either way."
    PRD §3.2: "A `RESTRICTED` POD can be resumed back to `OPERATIONAL` by
    `PublicHealthAdmin`."

    Design: Difficulty/non_linear_state_machine/pod_operational_restricted_cycle_twice
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])

    restricted = restrict_pod(pod["id"])
    assert restricted["operational_status"] == "RESTRICTED"

    resumed = resume_pod(pod["id"])
    assert resumed["operational_status"] == "OPERATIONAL"


def test_pod_restrict_resume_restrict_cycles_twice(api, admin_headers):
    """PRD §3.2: "From `OPERATIONAL`, a POD can be manually restricted by
    `PublicHealthAdmin`, or automatically restricted by the system as the
    second hop of either cascade described in §2.6 — the InventoryLot-depletion
    cascade triggered by dispensing (§3.6) or the credential-revocation cascade
    triggered by revoking a staff member's credential (§3.3) — landing in
    `RESTRICTED` either way."
    PRD §3.2: "A `RESTRICTED` POD can be resumed back to `OPERATIONAL` by
    `PublicHealthAdmin`."

    Design: Difficulty/non_linear_state_machine/pod_operational_restricted_cycle_twice
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])

    first_restrict = restrict_pod(pod["id"])
    assert first_restrict["operational_status"] == "RESTRICTED"
    resumed = resume_pod(pod["id"])
    assert resumed["operational_status"] == "OPERATIONAL"
    second_restrict = restrict_pod(pod["id"])
    assert second_restrict["operational_status"] == "RESTRICTED", (
        "RESTRICTED must be reachable a second time; it is not treated as terminal"
    )


def test_hazard_plan_stand_down_blocked_while_pod_operational(api, admin_headers):
    """PRD §3.1: "Standing a plan down moves it from `ACTIVATED` to `STOOD_DOWN`
    and stamps `stood_down_at`, but only once every `POD` that references this
    plan's id via `hazard_plan_id` has reached `operational_status` `CLOSED`; if
    any child POD is not yet closed, the request is rejected with
    `ERR_POD_NOT_READY_FOR_STAND_DOWN`."

    Design: Corner/validations/hazard_plan_stand_down_blocked_by_open_pod
    """
    hp = create_activated_hazard_plan()
    create_open_pod(hp["id"])

    res = api.stand_down_hazard_plan(hp["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_POD_NOT_READY_FOR_STAND_DOWN)


def test_pod_close_blocked_by_checked_in_staff(api, admin_headers):
    """PRD §3.2: "Closing a POD is permitted from `STAGING`, `OPERATIONAL`, or
    `RESTRICTED`, moves it to the terminal `CLOSED` state, and is blocked
    (`ERR_POD_STAFF_ONSITE`) while any `ShiftAssignment` at that POD is currently
    `CHECKED_IN`..."

    Design: Corner/validations/pod_close_blocked_by_checked_in_staff
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    staff = create_verified_staff_member(primary_role="VACCINATOR")
    create_checked_in_shift_assignment(pod["id"], staff["id"], assigned_role="VACCINATOR")

    res = api.close_pod(pod["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_POD_STAFF_ONSITE)
