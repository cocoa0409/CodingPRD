"""Task templates, maintenance-plan kind validation, plan lifecycle."""
from __future__ import annotations

import pytest

from test_helpers import (
    activate_plan,
    api_client,
    assert_maintenance_plan,
    assert_task_template,
    create_equipment,
    create_plan,
    create_plan_payload,
    create_site,
    create_template,
    create_template_payload,
    place_in_service,
    commission_equipment,
    setup_site_with_in_service_equipment,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# 3.3 — TaskTemplate creation & immutability shape
# ---------------------------------------------------------------------------
def test_create_task_template_returns_no_updated_at_or_version(
        api, plan_owner_headers):
    """PRD §3.3 + §2.4: 'Templates are immutable after creation and carry
    no updated_at or version.'
    """
    site = create_site()
    res = api.create_template(site["id"], create_template_payload(),
                                plan_owner_headers)
    template = validate_success(res, expected_status=201)
    assert_task_template(template)


def test_template_estimated_minutes_must_be_positive(api, plan_owner_headers):
    """PRD §3.3: 'estimated_minutes (a planning estimate strictly greater
    than zero)'.
    """
    site = create_site()
    payload = create_template_payload(estimated_minutes=0)
    res = api.create_template(site["id"], payload, plan_owner_headers)
    assert res.status_code >= 400, \
        "PRD §3.3: estimated_minutes must be > 0"


# ---------------------------------------------------------------------------
# 3.3 — MaintenancePlan kind-required fields
# ---------------------------------------------------------------------------
def test_periodic_time_plan_requires_interval_days(api, plan_owner_headers):
    """PRD §3.3: 'PERIODIC_TIME requires interval_days (strictly positive).'
    PRD §3.3: 'A plan body that omits any kind-required field — or supplies
    fields that contradict the kind — is rejected with
    ERR_PLAN_KIND_FIELDS, both on creation and on adjustment.'
    """
    site = create_site()
    template = create_template(site["id"])
    eq = create_equipment(site["id"], "owner-001")
    payload = {
        "equipment_id": eq["id"],
        "template_id": template["id"],
        "kind": "PERIODIC_TIME",
        # interval_days OMITTED
    }
    res = api.create_plan(site["id"], payload, plan_owner_headers)
    validate_error(res, "ERR_PLAN_KIND_FIELDS", expected_status=422)


def test_periodic_usage_plan_requires_interval_usage(api, plan_owner_headers):
    """PRD §3.3: 'PERIODIC_USAGE requires interval_usage (strictly positive,
    in usage units between consecutive work orders).'
    PRD §3.3: 'A plan body that omits any kind-required field ... is
    rejected with ERR_PLAN_KIND_FIELDS, both on creation and on
    adjustment.'
    """
    site = create_site()
    template = create_template(site["id"])
    eq = create_equipment(site["id"], "owner-001")
    payload = {
        "equipment_id": eq["id"],
        "template_id": template["id"],
        "kind": "PERIODIC_USAGE",
    }
    res = api.create_plan(site["id"], payload, plan_owner_headers)
    validate_error(res, "ERR_PLAN_KIND_FIELDS", expected_status=422)


def test_trigger_alarm_plan_requires_alarm_code(api, plan_owner_headers):
    """PRD §3.3: 'TRIGGER_ALARM requires alarm_code (matched against
    AlarmEvent.alarm_code).'
    """
    site = create_site()
    template = create_template(site["id"])
    eq = create_equipment(site["id"], "owner-001")
    payload = {
        "equipment_id": eq["id"],
        "template_id": template["id"],
        "kind": "TRIGGER_ALARM",
    }
    res = api.create_plan(site["id"], payload, plan_owner_headers)
    validate_error(res, "ERR_PLAN_KIND_FIELDS", expected_status=422)


def test_trigger_threshold_plan_requires_all_three(api, plan_owner_headers):
    """PRD §3.3: 'TRIGGER_THRESHOLD requires all three of threshold_metric,
    threshold_op, and threshold_value.'
    """
    site = create_site()
    template = create_template(site["id"])
    eq = create_equipment(site["id"], "owner-001")
    payload = {
        "equipment_id": eq["id"],
        "template_id": template["id"],
        "kind": "TRIGGER_THRESHOLD",
        "threshold_metric": "VIBRATION",
        # threshold_op and threshold_value missing
    }
    res = api.create_plan(site["id"], payload, plan_owner_headers)
    validate_error(res, "ERR_PLAN_KIND_FIELDS", expected_status=422)


def test_create_plan_starts_in_draft(api, plan_owner_headers):
    """PRD §3.3: 'Maintenance plans are created in DRAFT status against a
    target equipment and a source template.'
    """
    site = create_site()
    template = create_template(site["id"])
    eq = create_equipment(site["id"], "owner-001")
    res = api.create_plan(
        site["id"],
        create_plan_payload(eq["id"], template["id"], "PERIODIC_TIME",
                             interval_days=7),
        plan_owner_headers,
    )
    plan = validate_success(res, expected_status=201)
    assert_maintenance_plan(plan)
    assert plan["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# 3.3 — Plan lifecycle and cyclic ACTIVE↔PAUSED
# ---------------------------------------------------------------------------
# DELETED: test_activate_requires_equipment_in_commissioned_or_in_service.
# PRD §3.3 says plan activation requires equipment in COMMISSIONED or
# IN_SERVICE; PRD §3.2 says equipment commissioning is rejected with
# ERR_NO_ACTIVE_PLAN unless the equipment has an ACTIVE plan. These two
# rules form a chicken-and-egg deadlock on a fresh INSTALLED asset — neither
# rule can be honoured unless the other is relaxed. PRD does not name a
# canonical resolution, so the unique-derivability check (STEP 1b) fails:
# a faithful reader could reasonably relax either side, and the asserted
# outcome is not uniquely determined by PRD prose. DELETED per the
# Cardinal-Rule "DELETE when STEP 1b finds PRD does not uniquely determine
# the asserted outcome" clause.


def test_plan_pause_resume_cycle(api, plan_owner_headers):
    """PRD §3.3: 'The plan lifecycle proceeds through DRAFT → ACTIVE →
    PAUSED ↔ ACTIVE → RETIRED (with PAUSED → RETIRED also allowed).'
    Cyclic ACTIVE ↔ PAUSED claim.
    # difficulty: non_linear_state_machine/maintenance_plan_pause_resume_cycle
    """
    bag = setup_site_with_in_service_equipment(plan_kind="PERIODIC_TIME")
    site_id = bag["site"]["id"]
    plan_id = bag["plan"]["id"]

    # ACTIVE → PAUSED
    res = api.pause_plan(site_id, plan_id, plan_owner_headers)
    after_pause = validate_success(res, expected_status=200)
    assert after_pause["status"] == "PAUSED"
    # PAUSED → ACTIVE
    res = api.resume_plan(site_id, plan_id, plan_owner_headers)
    after_resume = validate_success(res, expected_status=200)
    assert after_resume["status"] == "ACTIVE"
    # ACTIVE → PAUSED again (cycle is repeatable)
    res = api.pause_plan(site_id, plan_id, plan_owner_headers)
    after_second_pause = validate_success(res, expected_status=200)
    assert after_second_pause["status"] == "PAUSED"


def test_resume_periodic_time_plan_recomputes_next_due_at(
        api, plan_owner_headers, site_manager_headers):
    """PRD §3.3: 'Resuming a paused PERIODIC_TIME plan re-evaluates
    next_due_at to the maximum of last_generated_at + interval_days *
    86400 seconds and the current site clock.'

    For a plan with last_generated_at=null at first activation, the test
    verifies next_due_at exists after resume.
    # difficulty: non_linear_state_machine/maintenance_plan_pause_resume_cycle
    """
    bag = setup_site_with_in_service_equipment(
        plan_kind="PERIODIC_TIME",
        plan_overrides={"interval_days": 7},
    )
    site_id = bag["site"]["id"]
    plan_id = bag["plan"]["id"]
    api.pause_plan(site_id, plan_id, plan_owner_headers)
    api.advance_clock(site_id, {"seconds": 7 * 86400}, site_manager_headers)
    res = api.resume_plan(site_id, plan_id, plan_owner_headers)
    after_resume = validate_success(res, expected_status=200)
    assert after_resume["status"] == "ACTIVE"
    assert after_resume["next_due_at"] is not None


def test_retire_plan_is_terminal(api, plan_owner_headers):
    """PRD §3.3: 'Retiring is terminal and may also be triggered by the
    equipment-decommission cascade described in §3.2; either path
    reaches the same `RETIRED` state and the plan no longer generates
    work orders.'
    """
    bag = setup_site_with_in_service_equipment()
    site_id = bag["site"]["id"]
    plan_id = bag["plan"]["id"]
    api.retire_plan(site_id, plan_id, plan_owner_headers)
    # Subsequent transitions out of RETIRED are not allowed.
    res = api.activate_plan(site_id, plan_id, plan_owner_headers)
    assert res.status_code >= 400
