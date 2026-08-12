"""Permit-to-work and isolation coordination: activation gates, de-isolation
blocking, hold/resume cascades, cross-scope references, closed-interval
conflicts, and the logical clock's effect on permit windows."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
    create_permit_for_item,
    create_turnaround,
    create_verified_isolation,
    create_work_item_payload,
    freeze_turnaround,
    issue_permit,
    activate_permit,
    set_clock,
    setup_active_permit_scenario,
    setup_execution_turnaround,
    make_supervisor_headers,
)


def test_deisolation_blocked_while_referencing_permit_live(
    api, coordinator_headers
):
    """PRD §3.4: "De-isolation — from `ISOLATED` or from `VERIFIED` to
    `DEISOLATED` — is blocked while any permit whose `required_isolation_ids`
    contains this isolation stands in `ISSUED`, `ACTIVE`, or `SUSPENDED`; the
    attempt is rejected with `ERR_ISOLATION_IN_USE`."

    Design: Corner/state_machines/isolation_deisolate_blocked_while_permit_live
    """
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Bundle pull", "estimated_hours": 100,
            "estimated_cost_cents": 200000, "requires_permit": True,
        },
        contingency_budget_cents=100000,
    )
    w1 = ctx["items"][0]
    iso = create_verified_isolation(ctx["turnaround"]["id"])
    permit = create_permit_for_item(w1["id"], isolation_ids=[iso["id"]])
    issue_permit(permit["id"])  # default clock 2026-05-01 < valid_until

    resp = api.transition_isolation(iso["id"], {"to": "DEISOLATED"}, coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_ISOLATION_IN_USE)

    # work item is FROZEN (never started), so the revoke fires no hold cascade
    validate_success(
        api.transition_permit(permit["id"], {"to": "REVOKED"}, coordinator_headers)
    )
    deisolated = validate_success(
        api.transition_isolation(iso["id"], {"to": "DEISOLATED"}, coordinator_headers)
    )
    assert deisolated["status"] == "DEISOLATED"


def test_hold_suspends_active_permit_and_permit_can_resume(
    api, coordinator_headers, planner_headers
):
    """PRD §3.5: "A `ContractorSupervisor` may place an `IN_PROGRESS` item on
    hold. The hold cascades sideways: every permit covering the item that
    currently stands in `ACTIVE` is moved to `SUSPENDED`, while permits already
    `CLOSED`, `REVOKED`, or `EXPIRED` are untouched."
    PRD §3.4: "Activation — `ISSUED` to `ACTIVE`, or resumption from
    `SUSPENDED` to `ACTIVE` — tightens the isolation requirement to full
    `VERIFIED` status on every required isolation, requires the turnaround to
    be in `EXECUTION`, and requires the logical now to fall at or after
    `valid_from` and strictly before `valid_until` — the window is half-open at
    its end."

    Design: Corner/state_machines/hold_suspends_active_permit
    """
    ctx = setup_active_permit_scenario()
    w1 = ctx["items"][0]
    contractor = ctx["contractor"]
    permit = ctx["permit"]
    assert permit["status"] == "ACTIVE"

    validate_success(
        api.start_work_item(w1["id"], make_supervisor_headers(contractor["id"]))
    )
    held = validate_success(
        api.hold_work_item(w1["id"], make_supervisor_headers(contractor["id"]))
    )
    assert held["status"] == "ON_HOLD"

    suspended = validate_success(api.get_permit(permit["id"], coordinator_headers))
    assert suspended["status"] == "SUSPENDED", (
        "holding the covered item must auto-suspend its ACTIVE permit"
    )

    resumed = validate_success(
        api.transition_permit(permit["id"], {"to": "ACTIVE"}, coordinator_headers)
    )
    assert resumed["status"] == "ACTIVE"


def test_start_requires_active_permit(api, coordinator_headers, planner_headers):
    """PRD §3.5: "Every start requires the turnaround to be in `EXECUTION`,
    failing with `ERR_INVALID_STATE` otherwise, and whenever the item's
    `requires_permit` flag is set, a permit covering this work item must
    currently stand in `ACTIVE` — the absence of one is rejected with
    `ERR_PERMIT_NOT_ACTIVE`."

    Design: Corner/errors/start_requires_active_permit
    """
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Bundle pull", "estimated_hours": 100,
            "estimated_cost_cents": 200000, "requires_permit": True,
        }
    )
    w1 = ctx["items"][0]
    contractor = ctx["contractor"]
    validate_success(api.schedule_work_item(w1["id"], planner_headers))
    iso = create_verified_isolation(ctx["turnaround"]["id"])
    permit = create_permit_for_item(w1["id"], isolation_ids=[iso["id"]])
    set_clock("2026-06-15T09:00:00Z")
    issue_permit(permit["id"])  # ISSUED is not ACTIVE

    resp = api.start_work_item(w1["id"], make_supervisor_headers(contractor["id"]))
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

    activate_permit(permit["id"])
    started = validate_success(
        api.start_work_item(w1["id"], make_supervisor_headers(contractor["id"]))
    )
    assert started["status"] == "IN_PROGRESS"


def test_permit_activation_uses_default_logical_clock(
    api, coordinator_headers, manager_headers
):
    """PRD §2.4: "At server startup, before any client has set it, the logical
    clock reads exactly `2026-05-01T00:00:00Z`."
    PRD §3.4: "Issuance — `REQUESTED` to `ISSUED` — requires every isolation in
    `required_isolation_ids` to stand in `ISOLATED` or `VERIFIED`, drawing
    `ERR_ISOLATION_NOT_VERIFIED` otherwise, and requires the logical now to
    fall strictly before `valid_until`, drawing `ERR_PERMIT_WINDOW_INVALID`
    otherwise."
    PRD §3.4: "Activation — `ISSUED` to `ACTIVE`, or resumption from
    `SUSPENDED` to `ACTIVE` — tightens the isolation requirement to full
    `VERIFIED` status on every required isolation, requires the turnaround to
    be in `EXECUTION`, and requires the logical now to fall at or after
    `valid_from` and strictly before `valid_until` — the window is half-open at
    its end."

    Design: Corner/validations/permit_activation_uses_default_clock_before_window
    """
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Bundle pull", "estimated_hours": 100,
            "estimated_cost_cents": 200000, "requires_permit": True,
        }
    )
    w1 = ctx["items"][0]
    iso = create_verified_isolation(ctx["turnaround"]["id"])
    permit = create_permit_for_item(w1["id"], isolation_ids=[iso["id"]])
    # no set_clock call: issuance only needs now < valid_until, and the
    # startup default 2026-05-01 precedes the window's end
    issue_permit(permit["id"])

    # default clock 2026-05-01 is before valid_from 2026-06-12
    resp = api.transition_permit(permit["id"], {"to": "ACTIVE"}, coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_INVALID)

    set_clock("2026-06-15T09:00:00Z")
    activated = validate_success(
        api.transition_permit(permit["id"], {"to": "ACTIVE"}, coordinator_headers)
    )
    assert activated["status"] == "ACTIVE"


def test_permit_referencing_foreign_turnaround_isolation_rejected(
    api, coordinator_headers, planner_headers
):
    """PRD §3.4: "Every referenced isolation must belong to the same turnaround
    as the covered work item, recorded on the permit as `work_item_id`, or the
    request fails with `ERR_CROSS_SCOPE_REFERENCE`."

    Design: Corner/validations/cross_scope_isolation_reference_rejected
    """
    # T1 with a FROZEN permit-requiring work item
    ta1 = create_turnaround(name="TA-X1", plant_unit="CRU-2",
                            authorized_budget_cents=500000,
                            contingency_budget_cents=100000)
    w1 = validate_success(
        api.create_work_item(
            ta1["id"],
            create_work_item_payload(
                title="T1 item", system_area="A", estimated_hours=10,
                estimated_cost_cents=10000, requires_permit=True,
            ),
            planner_headers,
        ),
        201,
    )
    freeze_turnaround(ta1["id"], scope_cutoff_count=1)

    # T2 owns the isolation the permit will wrongly reference
    ta2 = create_turnaround(name="TA-X2", plant_unit="CRU-3",
                            authorized_budget_cents=500000,
                            contingency_budget_cents=100000)
    validate_success(
        api.create_work_item(ta2["id"], create_work_item_payload(title="T2 item"),
                             planner_headers),
        201,
    )
    freeze_turnaround(ta2["id"], scope_cutoff_count=1)
    iso2 = validate_success(
        api.create_isolation(
            ta2["id"],
            {
                "equipment_tag": "V-201", "isolation_mode": "EXCLUSIVE",
                "isolated_from": "2026-06-10T00:00:00Z",
                "isolated_until": "2026-06-20T00:00:00Z",
            },
            coordinator_headers,
        ),
        201,
    )

    resp = api.create_permit(
        w1["id"],
        {
            "permit_type": "COLD_WORK", "hazard_class": "LOW",
            "valid_from": "2026-06-12T00:00:00Z",
            "valid_until": "2026-06-20T00:00:00Z",
            "required_isolation_ids": [iso2["id"]],
        },
        coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_SCOPE_REFERENCE)


def _setup_two_isolation_permit(api, coordinator_headers):
    """EXECUTION turnaround; W1 (requires_permit) FROZEN; I1 VERIFIED and I2
    ISOLATED; permit P requiring both, ISSUED under clock 2026-06-15T09:00Z."""
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Agitator seal", "estimated_hours": 50,
            "estimated_cost_cents": 90000, "requires_permit": True,
        }
    )
    t_id = ctx["turnaround"]["id"]
    w1 = ctx["items"][0]
    i1 = validate_success(
        api.create_isolation(
            t_id,
            {
                "equipment_tag": "P-101", "isolation_mode": "EXCLUSIVE",
                "isolated_from": "2026-06-10T00:00:00Z",
                "isolated_until": "2026-06-25T00:00:00Z",
            },
            coordinator_headers,
        ),
        201,
    )
    i2 = validate_success(
        api.create_isolation(
            t_id,
            {
                "equipment_tag": "P-102", "isolation_mode": "EXCLUSIVE",
                "isolated_from": "2026-06-10T00:00:00Z",
                "isolated_until": "2026-06-25T00:00:00Z",
            },
            coordinator_headers,
        ),
        201,
    )
    validate_success(
        api.transition_isolation(i1["id"], {"to": "ISOLATED"}, coordinator_headers)
    )
    validate_success(
        api.transition_isolation(i1["id"], {"to": "VERIFIED"}, coordinator_headers)
    )
    validate_success(
        api.transition_isolation(i2["id"], {"to": "ISOLATED"}, coordinator_headers)
    )
    permit = create_permit_for_item(w1["id"], isolation_ids=[i1["id"], i2["id"]])
    set_clock("2026-06-15T09:00:00Z")
    issue_permit(permit["id"])
    return ctx, i1, i2, permit


def test_permit_activation_rejected_while_any_isolation_unverified(
    api, coordinator_headers
):
    """PRD §3.4: "Activation — `ISSUED` to `ACTIVE`, or resumption from
    `SUSPENDED` to `ACTIVE` — tightens the isolation requirement to full
    `VERIFIED` status on every required isolation, requires the turnaround to
    be in `EXECUTION`, and requires the logical now to fall at or after
    `valid_from` and strictly before `valid_until` — the window is half-open at
    its end."

    Design: Difficulty/cross_entity_state_dependency/permit_activation_blocked_until_all_isolations_verified
    """
    _ctx, _i1, i2, permit = _setup_two_isolation_permit(api, coordinator_headers)
    # I2 stands only ISOLATED; issuance tolerated it, activation must not
    check = validate_success(api.get_isolation(i2["id"], coordinator_headers))
    assert check["status"] == "ISOLATED"

    resp = api.transition_permit(permit["id"], {"to": "ACTIVE"}, coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_ISOLATION_NOT_VERIFIED)


def test_permit_activation_succeeds_once_all_isolations_verified(
    api, coordinator_headers
):
    """PRD §3.4: "Activation — `ISSUED` to `ACTIVE`, or resumption from
    `SUSPENDED` to `ACTIVE` — tightens the isolation requirement to full
    `VERIFIED` status on every required isolation, requires the turnaround to
    be in `EXECUTION`, and requires the logical now to fall at or after
    `valid_from` and strictly before `valid_until` — the window is half-open at
    its end."

    Design: Difficulty/cross_entity_state_dependency/permit_activation_blocked_until_all_isolations_verified
    """
    _ctx, _i1, i2, permit = _setup_two_isolation_permit(api, coordinator_headers)
    resp = api.transition_permit(permit["id"], {"to": "ACTIVE"}, coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_ISOLATION_NOT_VERIFIED)

    validate_success(
        api.transition_isolation(i2["id"], {"to": "VERIFIED"}, coordinator_headers)
    )
    activated = validate_success(
        api.transition_permit(permit["id"], {"to": "ACTIVE"}, coordinator_headers)
    )
    assert activated["status"] == "ACTIVE"


def _setup_shared_isolations(api, coordinator_headers, manager_headers, planner_headers):
    """SCOPE_FROZEN turnaround; I1 SHARED on TK-301 [06-10, 06-20] and I2
    SHARED on TK-301 [06-10, 06-15] (interior overlap)."""
    ta = create_turnaround(name="TA-ISO", authorized_budget_cents=900000000)
    validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="Tank entry prep", system_area="CRU-2-TK",
                work_type="PREVENTIVE", risk_class="A", estimated_hours=80,
                estimated_cost_cents=160000, requires_permit=True,
            ),
            planner_headers,
        ),
        201,
    )
    freeze_turnaround(ta["id"], scope_cutoff_count=1)
    i1 = validate_success(
        api.create_isolation(
            ta["id"],
            {
                "equipment_tag": "TK-301", "isolation_mode": "SHARED",
                "isolated_from": "2026-06-10T00:00:00Z",
                "isolated_until": "2026-06-20T00:00:00Z",
            },
            coordinator_headers,
        ),
        201,
    )
    return ta, i1


def test_shared_isolations_may_overlap_on_same_equipment(
    api, coordinator_headers, manager_headers, planner_headers
):
    """PRD §3.4: "Isolation windows are closed intervals — both bounds are
    inclusive — and the conflict rule is mode-conditional: two `SHARED`
    isolations may coexist on the same `equipment_tag` even with overlapping
    windows, but any overlap involving an `EXCLUSIVE` isolation on the same tag
    is rejected with `ERR_ISOLATION_CONFLICT`; because the intervals are
    closed, windows that merely touch at an endpoint still count as
    overlapping."

    Design: Difficulty/resource_temporal_overlap/isolation_closed_interval_touch_exclusive_conflicts_shared_allowed
    """
    ta, i1 = _setup_shared_isolations(api, coordinator_headers, manager_headers,
                                      planner_headers)
    # SHARED + SHARED with a full interior overlap is admitted
    i2 = validate_success(
        api.create_isolation(
            ta["id"],
            {
                "equipment_tag": "TK-301", "isolation_mode": "SHARED",
                "isolated_from": "2026-06-10T00:00:00Z",
                "isolated_until": "2026-06-15T00:00:00Z",
            },
            coordinator_headers,
        ),
        201,
    )
    assert i1["status"] == "PLANNED"
    assert i2["status"] == "PLANNED"
    assert i2["equipment_tag"] == i1["equipment_tag"] == "TK-301"


def test_exclusive_isolation_touching_at_endpoint_conflicts(
    api, coordinator_headers, manager_headers, planner_headers
):
    """PRD §3.4: "Isolation windows are closed intervals — both bounds are
    inclusive — and the conflict rule is mode-conditional: two `SHARED`
    isolations may coexist on the same `equipment_tag` even with overlapping
    windows, but any overlap involving an `EXCLUSIVE` isolation on the same tag
    is rejected with `ERR_ISOLATION_CONFLICT`; because the intervals are
    closed, windows that merely touch at an endpoint still count as
    overlapping."

    Design: Difficulty/resource_temporal_overlap/isolation_closed_interval_touch_exclusive_conflicts_shared_allowed
    """
    ta, _i1 = _setup_shared_isolations(api, coordinator_headers, manager_headers,
                                       planner_headers)
    validate_success(
        api.create_isolation(
            ta["id"],
            {
                "equipment_tag": "TK-301", "isolation_mode": "SHARED",
                "isolated_from": "2026-06-10T00:00:00Z",
                "isolated_until": "2026-06-15T00:00:00Z",
            },
            coordinator_headers,
        ),
        201,
    )
    # EXCLUSIVE window [06-20, 06-30] touches I1's closed window at 06-20
    resp = api.create_isolation(
        ta["id"],
        {
            "equipment_tag": "TK-301", "isolation_mode": "EXCLUSIVE",
            "isolated_from": "2026-06-20T00:00:00Z",
            "isolated_until": "2026-06-30T00:00:00Z",
        },
        coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ISOLATION_CONFLICT)
