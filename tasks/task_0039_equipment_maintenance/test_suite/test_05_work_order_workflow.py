"""Work-order lifecycle: pending → in_progress → paused ↔ in_progress →
completed → closed, plus cancel and reassign paths."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    accept_work_order,
    api_client,
    assert_audit_entry,
    assert_repair_record,
    assert_version_incremented,
    assert_work_order,
    cancel_work_order_payload,
    complete_payload,
    complete_work_order,
    create_ad_hoc_work_order,
    create_technician,
    create_work_order_payload,
    find_audit_entries,
    make_site_manager_headers,
    make_technician_headers,
    pause_payload,
    pause_work_order,
    reassign_payload,
    resume_work_order,
    run_sweep,
    setup_completed_workorder,
    setup_full_workorder_scenario,
    setup_pending_workorder,
    setup_started_workorder,
    setup_two_techs_for_aggregate_capacity,
    start_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# 3.6 — start/pause/resume/complete/accept happy path
# ---------------------------------------------------------------------------
def test_start_transitions_pending_to_in_progress(api, dispatcher_headers):
    """PRD §3.6: 'Starting a work order moves it from PENDING to
    IN_PROGRESS. ... On a successful start, WorkOrder.started_at is set
    to the current site clock if it was null, the equipment transitions
    from IN_SERVICE to UNDER_MAINTENANCE, Equipment.open_work_order_id is
    pinned to the work order's id, and an audit entry with action
    WORK_ORDER_STATE_CHANGE is appended.'
    """
    bag = setup_pending_workorder()
    site_id = bag["site"]["id"]
    wo = bag["work_order"]
    assert wo["status"] == "PENDING"

    headers = make_technician_headers(bag["technician"]["id"])
    res = api.start_work_order(site_id, wo["id"], headers)
    started = validate_success(res, expected_status=200)
    assert started["status"] == "IN_PROGRESS"
    assert started["started_at"] is not None
    assert_version_incremented(started["version"], wo["version"])

    eq_after = validate_success(
        api.get_equipment(site_id, bag["equipment"]["id"], headers),
        expected_status=200,
    )
    assert eq_after["lifecycle_status"] == "UNDER_MAINTENANCE"
    assert eq_after["open_work_order_id"] == wo["id"]


def test_start_rejected_when_caller_not_assigned_technician(
        api, technician_headers_fallback):
    """PRD §3.6: 'Every transition out of PENDING initiated by a technician
    requires X-User-ID to equal WorkOrder.assigned_technician_id; a
    mismatch produces ERR_FORBIDDEN_NOT_OWNER.'
    """
    bag = setup_pending_workorder()
    res = api.start_work_order(
        bag["site"]["id"], bag["work_order"]["id"],
        technician_headers_fallback,
    )
    validate_error(res, "ERR_FORBIDDEN_NOT_OWNER", expected_status=403)


def test_start_rejected_when_equipment_not_in_service(api):
    """PRD §3.6: 'The transition is rejected if the equipment's
    lifecycle_status is not in IN_SERVICE or COMMISSIONED
    (ERR_EQUIPMENT_LIFECYCLE)'.
    # difficulty: cross_entity_state_dependency/workorder_start_requires_equipment_lifecycle
    """
    # Create an INSTALLED equipment and try to create a WO on it. Per PRD
    # §3.4, creation requires lifecycle in {COMMISSIONED, IN_SERVICE} too,
    # so this returns ERR_EQUIPMENT_LIFECYCLE on /work-orders.
    from test_helpers import (
        create_equipment, create_site, create_template,
        TEST_USERS,
    )
    site = create_site()
    template = create_template(site["id"])
    eq = create_equipment(site["id"], "owner-001")  # INSTALLED
    res = api.create_work_order(
        site["id"],
        create_work_order_payload(eq["id"], template["id"]),
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(res, "ERR_EQUIPMENT_LIFECYCLE", expected_status=409)


def test_pause_records_active_minutes_and_pause_reason(api):
    """PRD §3.6: 'Pausing moves the work order from IN_PROGRESS to PAUSED.
    The body must specify pause_reason from WAIT_PARTS, WAIT_VENDOR, or
    WAIT_INFO. On a successful pause, the elapsed minutes since the most
    recent IN_PROGRESS entry — that is, the floor of (Site.clock_now −
    last IN_PROGRESS entry) / 60 — are added to
    WorkOrder.total_active_minutes, the pause_reason is stored, and an
    audit entry is appended.'
    """
    bag = setup_started_workorder()
    api.advance_clock(bag["site"]["id"], {"seconds": 600},
                       __import__("test_helpers").TEST_USERS["site_manager_headers"])
    headers = make_technician_headers(bag["technician"]["id"])
    res = api.pause_work_order(
        bag["site"]["id"], bag["work_order"]["id"],
        pause_payload("WAIT_INFO"), headers,
    )
    paused = validate_success(res, expected_status=200)
    assert paused["status"] == "PAUSED"
    assert paused["pause_reason"] == "WAIT_INFO"
    assert paused["total_active_minutes"] >= 10  # 600s / 60 = 10


def test_resume_clears_pause_reason(api):
    """PRD §3.6: 'On a successful resume, the active-minute timer restarts
    from the current site clock, and pause_reason is cleared to null.'
    """
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    pause_work_order(site_id, wo_id, tech_id, "WAIT_INFO")
    res = api.resume_work_order(
        site_id, wo_id, make_technician_headers(tech_id),
    )
    resumed = validate_success(res, expected_status=200)
    assert resumed["status"] == "IN_PROGRESS"
    assert resumed["pause_reason"] is None


def test_pause_resume_cycle_is_repeatable(api):
    """PRD §3.6: 'The lifecycle is PENDING → IN_PROGRESS → (PAUSED ↔
    IN_PROGRESS) → COMPLETED → CLOSED'.
    # difficulty: non_linear_state_machine/work_order_pause_resume_cycle
    """
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    started_version = bag["work_order"]["version"]

    pause_work_order(site_id, wo_id, tech_id, "WAIT_INFO")
    resume_work_order(site_id, wo_id, tech_id)
    pause_work_order(site_id, wo_id, tech_id, "WAIT_VENDOR")
    final = resume_work_order(site_id, wo_id, tech_id)

    assert final["status"] == "IN_PROGRESS"
    assert final["pause_reason"] is None
    # Four mutations after start → version incremented at least 4 times.
    assert final["version"] >= started_version + 4


# ---------------------------------------------------------------------------
# 3.6 — completion side effects
# ---------------------------------------------------------------------------
def test_complete_creates_repair_record_and_clears_open_work_order(api):
    """PRD §3.6: 'On a successful completion: the elapsed IN_PROGRESS
    minutes are added to total_active_minutes; a new RepairRecord is
    created with the body fields ... ; WorkOrder.parts_cost_cents is
    computed via the parts-cost calculation in §3.8;
    WorkOrder.completed_at is stamped with the current site clock; the
    equipment transitions from UNDER_MAINTENANCE to IN_SERVICE,
    Equipment.open_work_order_id is cleared to null, and
    Equipment.last_repair_completed_at is set to the current site clock'.
    """
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    res = api.complete_work_order(
        site_id, wo_id, complete_payload(),
        make_technician_headers(tech_id),
    )
    wo = validate_success(res, expected_status=200)
    assert wo["status"] == "COMPLETED"
    assert wo["completed_at"] is not None

    # RepairRecord exists for this WO
    rr_res = api.get_repair_record(
        site_id, wo_id, make_technician_headers(tech_id),
    )
    rr = validate_success(rr_res, expected_status=200)
    assert_repair_record(rr)

    # Equipment lifecycle restored, open_work_order_id cleared.
    eq_res = api.get_equipment(
        site_id, bag["equipment"]["id"], make_technician_headers(tech_id),
    )
    eq_after = validate_success(eq_res, expected_status=200)
    assert eq_after["lifecycle_status"] == "IN_SERVICE"
    assert eq_after["open_work_order_id"] is None
    assert eq_after["last_repair_completed_at"] is not None


# ---------------------------------------------------------------------------
# 3.6 — acceptance: caller must equal responsible_user_id
# ---------------------------------------------------------------------------
def test_accept_requires_responsible_user_id(api, site_manager_headers):
    """PRD §3.6: 'Acceptance moves the work order from COMPLETED to CLOSED
    and may only be performed by a SiteManager whose X-User-ID equals the
    equipment's responsible_user_id (otherwise ERR_FORBIDDEN_NOT_OWNER).'
    """
    responsible_user_id = "responsible-owner-001"
    bag = setup_completed_workorder(responsible_user_id=responsible_user_id)
    # site_manager_headers fixture uses 'site-manager-001', NOT the
    # responsible_user_id. So acceptance must reject.
    res = api.accept_work_order(
        bag["site"]["id"], bag["work_order"]["id"], site_manager_headers,
    )
    validate_error(res, "ERR_FORBIDDEN_NOT_OWNER", expected_status=403)


def test_accept_succeeds_when_caller_matches_responsible_user(api):
    """PRD §3.6: 'Acceptance moves the work order from COMPLETED to CLOSED
    and may only be performed by a SiteManager whose X-User-ID equals the
    equipment's responsible_user_id'.
    """
    responsible_user_id = "responsible-owner-002"
    bag = setup_completed_workorder(responsible_user_id=responsible_user_id)
    res = api.accept_work_order(
        bag["site"]["id"], bag["work_order"]["id"],
        make_site_manager_headers(responsible_user_id),
    )
    closed = validate_success(res, expected_status=200)
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None


# ---------------------------------------------------------------------------
# 3.7 — reassign happy path & skill mismatch
# ---------------------------------------------------------------------------
def test_reassign_updates_assignee_and_increments_count(api,
                                                         dispatcher_headers):
    """PRD §3.7: 'On a successful reassign, WorkOrder.assigned_technician_id
    is replaced, WorkOrder.reassign_count is incremented by one only if the
    previous assigned_technician_id was non-null'.
    """
    bag = setup_pending_workorder()
    new_tech = create_technician(bag["site"]["id"], skills=["MECHANICAL"])
    res = api.reassign_work_order(
        bag["site"]["id"], bag["work_order"]["id"],
        reassign_payload(new_tech["id"]), dispatcher_headers,
    )
    after = validate_success(res, expected_status=200)
    assert after["assigned_technician_id"] == new_tech["id"]
    assert after["reassign_count"] == bag["work_order"]["reassign_count"] + 1


def test_reassign_with_skill_mismatch_rejected(api, dispatcher_headers):
    """PRD §3.7: 'The new technician must have status ACTIVE and skills
    that include WorkOrder.required_skill; a skill-set mismatch yields
    ERR_SKILL_MISMATCH.'
    """
    bag = setup_pending_workorder()
    # Required skill on the WO is whatever the template said (MECHANICAL by
    # default). Build a tech with a non-matching skill set.
    bad_tech = create_technician(bag["site"]["id"], skills=["HVAC_CERT"])
    res = api.reassign_work_order(
        bag["site"]["id"], bag["work_order"]["id"],
        reassign_payload(bad_tech["id"]), dispatcher_headers,
    )
    validate_error(res, "ERR_SKILL_MISMATCH", expected_status=422)


# ---------------------------------------------------------------------------
# 3.7 — cancel rules
# ---------------------------------------------------------------------------
def test_pending_cancel_succeeds(api, dispatcher_headers):
    """PRD §3.7: 'A Dispatcher may also cancel a work order... From
    PENDING, cancellation requires that no requisition for this work order
    is in status ISSUED'.
    """
    bag = setup_pending_workorder()
    res = api.cancel_work_order(
        bag["site"]["id"], bag["work_order"]["id"],
        cancel_work_order_payload(), dispatcher_headers,
    )
    cancelled = validate_success(res, expected_status=200)
    assert cancelled["status"] == "CANCELLED"


def test_paused_cancel_rejected_when_no_sweep_since_pause(api,
                                                          dispatcher_headers):
    """PRD §3.7: 'From PAUSED, cancellation additionally requires that the
    pause has lasted at least one sweep tick — that is, sweep_run_index has
    advanced by at least one since the pause; otherwise the cancellation
    is rejected with ERR_PAUSE_TOO_FRESH.'
    """
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    pause_work_order(site_id, wo_id, tech_id, "WAIT_INFO")
    res = api.cancel_work_order(
        site_id, wo_id, cancel_work_order_payload(), dispatcher_headers,
    )
    validate_error(res, "ERR_PAUSE_TOO_FRESH", expected_status=409)


def test_paused_cancel_succeeds_after_sweep(api, dispatcher_headers):
    """PRD §3.7: 'From PAUSED, cancellation additionally requires that the
    pause has lasted at least one sweep tick — that is, sweep_run_index has
    advanced by at least one since the pause'.
    """
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    pause_work_order(site_id, wo_id, tech_id, "WAIT_INFO")
    run_sweep(site_id)
    res = api.cancel_work_order(
        site_id, wo_id, cancel_work_order_payload(), dispatcher_headers,
    )
    cancelled = validate_success(res, expected_status=200)
    assert cancelled["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# 3.4 — equipment-busy gate
# ---------------------------------------------------------------------------
def test_create_workorder_when_equipment_busy_rejected(api, dispatcher_headers):
    """PRD §3.4: 'equipment that already has an open work order cannot host
    a new one and produces ERR_EQUIPMENT_BUSY.'
    # difficulty: resource_temporal_overlap/equipment_open_workorder_exclusive
    """
    bag = setup_pending_workorder()
    res = api.create_work_order(
        bag["site"]["id"],
        create_work_order_payload(
            bag["equipment"]["id"], bag["template"]["id"],
        ),
        dispatcher_headers,
    )
    validate_error(res, "ERR_EQUIPMENT_BUSY", expected_status=409)


def test_create_workorder_after_cancel_succeeds(api, dispatcher_headers):
    """PRD §3.4 + §3.7 + §3.2: After cancelling a PENDING WO, the
    equipment's open_work_order_id is cleared and a new WO can be created
    on the same equipment.
    # difficulty: resource_temporal_overlap/equipment_open_workorder_exclusive
    """
    bag = setup_pending_workorder()
    api.cancel_work_order(
        bag["site"]["id"], bag["work_order"]["id"],
        cancel_work_order_payload(), dispatcher_headers,
    )
    res = api.create_work_order(
        bag["site"]["id"],
        create_work_order_payload(
            bag["equipment"]["id"], bag["template"]["id"],
        ),
        dispatcher_headers,
    )
    new_wo = validate_success(res, expected_status=201)
    assert new_wo["status"] == "PENDING"
    assert new_wo["equipment_id"] == bag["equipment"]["id"]


# ---------------------------------------------------------------------------
# 3.4 — selector aggregate-capacity (technician_workload)
# ---------------------------------------------------------------------------
def test_technician_selector_picks_least_loaded_then_oldest(api,
                                                             dispatcher_headers):
    """PRD §3.4: 'Candidates are ranked by open_load ascending (the count
    of work orders assigned to that technician with status in PENDING,
    IN_PROGRESS, or PAUSED), with created_at ascending as the secondary
    key, and lexicographic ascending order of id as the final tie-break.'
    # difficulty: resource_temporal_overlap/technician_workload_aggregate_capacity
    """
    bag = setup_two_techs_for_aggregate_capacity()
    site_id = bag["site"]["id"]
    template_id = bag["template"]["id"]

    # WO_1 on E1 — both techs at open_load=0; T_A is older → T_A wins.
    res = api.create_work_order(
        site_id,
        create_work_order_payload(bag["equipment_1"]["id"], template_id),
        dispatcher_headers,
    )
    wo_1 = validate_success(res, expected_status=201)
    assert wo_1["assigned_technician_id"] == bag["technician_a"]["id"]

    # WO_2 on E2 — T_A.open_load=1, T_B.open_load=0 → T_B wins.
    res = api.create_work_order(
        site_id,
        create_work_order_payload(bag["equipment_2"]["id"], template_id),
        dispatcher_headers,
    )
    wo_2 = validate_success(res, expected_status=201)
    assert wo_2["assigned_technician_id"] == bag["technician_b"]["id"]

    # WO_3 on E3 — both at open_load=1; tie broken by created_at ASC, T_A older.
    res = api.create_work_order(
        site_id,
        create_work_order_payload(bag["equipment_3"]["id"], template_id),
        dispatcher_headers,
    )
    wo_3 = validate_success(res, expected_status=201)
    assert wo_3["assigned_technician_id"] == bag["technician_a"]["id"]


def test_technician_selector_assigns_null_when_no_match(api,
                                                         dispatcher_headers):
    """PRD §3.4: 'If the candidate set is empty, the work order is still
    created in PENDING state but assigned_technician_id remains null; it
    is not rejected.'
    """
    # In-service equipment but no eligible technician (skills mismatch).
    bag = setup_full_workorder_scenario(
        template_required_skill="HVAC_CERT",
        technician_skills=["MECHANICAL"],  # tech does not have HVAC_CERT
    )
    res = api.create_work_order(
        bag["site"]["id"],
        create_work_order_payload(
            bag["equipment"]["id"], bag["template"]["id"],
        ),
        dispatcher_headers,
    )
    wo = validate_success(res, expected_status=201)
    assert wo["status"] == "PENDING"
    assert wo["assigned_technician_id"] is None


# ---------------------------------------------------------------------------
# 2.10 — audit trail on transitions
# ---------------------------------------------------------------------------
def test_state_change_emits_audit_entry(api, site_manager_headers):
    """PRD §2.10: 'Every state-changing operation on a WorkOrder ...
    produces an AuditEntry carrying actor_role, actor_user_id, an action
    drawn from WORK_ORDER_STATE_CHANGE, PARTS_ISSUED, PARTS_RETURNED, or
    TECHNICIAN_ASSIGNED, the affected resource's target_id, the prior
    status as from_value (the empty string on creation), the new status
    as to_value, and occurred_at set to the site clock at the moment of
    the action.'
    """
    bag = setup_started_workorder()
    res = api.list_audit(
        bag["site"]["id"], site_manager_headers,
        params={"target_id": bag["work_order"]["id"]},
    )
    data, meta = validate_paginated(res)
    state_changes = find_audit_entries(
        data, action="WORK_ORDER_STATE_CHANGE",
        target_id=bag["work_order"]["id"],
    )
    assert len(state_changes) >= 1, \
        "PRD §2.10: at least one WORK_ORDER_STATE_CHANGE audit row " \
        "exists after the start transition"
    for row in state_changes:
        assert_audit_entry(row)
        assert row["target_id"] == bag["work_order"]["id"]
