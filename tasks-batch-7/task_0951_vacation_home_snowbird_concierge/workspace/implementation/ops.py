"""Cross-cutting operations shared by several route modules."""
from datetime import timedelta

import calc
import core
from core import D, fail, get, new_row, now, rhu_cents, touch
from gates import check_state


# ---------------------------------------------------------------------------
# Visits created as a side effect
# ---------------------------------------------------------------------------
def create_visit(property_id, checklist_template_id, visit_type, trigger_source,
                 scheduled_start_at, scheduled_end_at, away_period_id=None,
                 storm_response_id=None, rental_turnover_id=None):
    return new_row(
        "visits",
        property_id=property_id,
        checklist_template_id=checklist_template_id,
        away_period_id=away_period_id,
        storm_response_id=storm_response_id,
        rental_turnover_id=rental_turnover_id,
        billing_cycle_id=None,
        visit_type=visit_type,
        trigger_source=trigger_source,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        status="SCHEDULED",
        departed_at=None,
        arrived_at=None,
        completed_at=None,
        tech_user_id=None,
        completed_item_codes=[],
        failed_item_codes=[],
        checklist_completion_pct=0.0,
        interior_temp_f=None,
        entitlement_applied=False,
        billable_amount_cents=0,
        after_hours_flag=False,
        deferral_count=0,
        defer_reason=None,
    )


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
def create_finding(property_id, visit_id, item_code, severity, category, description,
                   status="OPEN"):
    finding = new_row(
        "findings",
        visit_id=visit_id,
        property_id=property_id,
        item_code=item_code,
        severity=severity,
        category=category,
        status=status,
        escalation_score=0.0,
        triaged_at=None,
        dismissed_at=None,
        monitor_recheck_count=0,
        description=description,
    )
    return finding


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------
def create_work_order(finding, work_type, estimated_labour_hours, estimated_parts_cents,
                      created_by_user_id, storm_event_id=None, key_asset_id=None):
    wo = new_row(
        "work_orders",
        finding_id=finding["id"],
        property_id=finding["property_id"],
        storm_event_id=storm_event_id,
        key_asset_id=key_asset_id,
        work_type=work_type,
        pipeline="STORM" if storm_event_id else "ROUTINE",
        estimated_labour_hours=estimated_labour_hours,
        estimated_parts_cents=estimated_parts_cents,
        labour_cost_cents=0,
        parts_cost_cents=0,
        markup_cents=0,
        surcharge_pct_applied=0.0,
        storm_surcharge_cents=0,
        total_cents=0,
        approval_ceiling_cents=0,
        approval_required=False,
        status="DRAFT",
        dispatch_attempt_count=0,
        approved_by_user_id=None,
        created_by_user_id=created_by_user_id,
        rejection_reason=None,
        actual_labour_hours=None,
        actual_parts_cents=None,
    )
    return wo


def submit_work_order(wo, allow_auto_approve=True):
    """DRAFT -> PENDING_APPROVAL, running the whole pinned cost chain, and on
    to APPROVED inside the same request when approval_required is false."""
    wo["status"] = "PENDING_APPROVAL"
    calc.run_cost_chain(wo)
    if allow_auto_approve and not wo["approval_required"]:
        wo["status"] = "APPROVED"
        wo["approved_by_user_id"] = "system"
    touch(wo)
    return wo


def freeze_storm_surcharge(wo):
    event = get("storm_events", wo.get("storm_event_id"))
    if event is None:
        return
    pct = calc.storm_surcharge_pct(event)
    response = None
    for r in calc.children("storm_responses", "storm_event_id", event["id"]):
        if r["property_id"] == wo["property_id"]:
            response = r
            break
    if response is not None:
        if not response.get("_surcharge_frozen"):
            response["surcharge_pct_at_dispatch"] = pct
            response["_surcharge_frozen"] = True
            touch(response)
        wo["surcharge_pct_applied"] = response["surcharge_pct_at_dispatch"]
    else:
        wo["surcharge_pct_applied"] = pct


def perform_dispatch(wo, window_start_at, window_end_at, raise_on_empty=True):
    """G8 vendor selection followed by the key-custody chain (cascade hops 4-8)."""
    finding = get("findings", wo.get("finding_id"))
    pool = calc.vendor_selection(wo, finding)
    if not pool:
        if raise_on_empty:
            fail("ERR_NO_ELIGIBLE_VENDOR", "No eligible vendor matches this work order.")
        return None
    vendor = pool[0]
    wo["dispatch_attempt_count"] += 1
    wo["status"] = "DISPATCHED"
    assignment = new_row(
        "vendor_assignments",
        work_order_id=wo["id"],
        vendor_id=vendor["id"],
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        status="OFFERED",
        offered_at=now(),
        accepted_at=None,
        finished_at=None,
        decline_reason=None,
        coi_valid_at_offer=vendor["coi_expires_at"] > now(),
        access_blocked_flag=False,
    )
    if calc.pipeline_of(wo) == "STORM":
        freeze_storm_surcharge(wo)
    touch(wo)

    key = calc.key_selection(wo["property_id"])
    if key is None:
        assignment["access_blocked_flag"] = True
    else:
        issuance = create_key_issuance(key, vendor["id"], assignment["id"], 1)
        create_access_grant(key, vendor["id"], window_start_at, window_end_at, issuance["id"])
    return assignment


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------
def create_key_issuance(key, vendor_id, vendor_assignment_id, copies_issued):
    issued_at = now()
    issuance = new_row(
        "key_issuances",
        key_asset_id=key["id"],
        vendor_id=vendor_id,
        vendor_assignment_id=vendor_assignment_id,
        issued_at=issued_at,
        return_deadline_at=calc.key_return_deadline(issued_at, key),
        returned_at=None,
        status="ISSUED",
        overdue_days=0,
        copies_issued=copies_issued,
    )
    return issuance


def next_lockbox_code(previous):
    if previous is not None and isinstance(previous, str) and previous.strip().isdigit():
        return "%04d" % (int(previous) + 1)
    return "0001"


def invalidate_stale_grants(key, exclude_id=None, statuses=("PENDING", "ACTIVE")):
    for grant in calc.children("access_grants", "key_asset_id", key["id"]):
        if exclude_id is not None and grant["id"] == exclude_id:
            continue
        if grant["status"] not in statuses:
            continue
        if grant["rotation_index_at_grant"] < key["code_rotation_count"]:
            grant["status"] = "INVALIDATED"
            grant["invalidated_reason"] = "CODE_ROTATION"
            touch(grant)


def create_access_grant(key, vendor_id, window_start_at, window_end_at, key_issuance_id=None):
    """Cascade hops 6-8: create the grant, rotate a LOCKBOX code, invalidate
    every grant stamped with an earlier rotation index."""
    if key["key_type"] == "LOCKBOX":
        key["code_rotation_count"] += 1
        key["current_code"] = next_lockbox_code(key.get("current_code"))
    grant = new_row(
        "access_grants",
        key_asset_id=key["id"],
        vendor_id=vendor_id,
        key_issuance_id=key_issuance_id,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        code_snapshot=key.get("current_code"),
        status="PENDING",
        invalidated_reason=None,
        rotation_index_at_grant=key["code_rotation_count"],
    )
    invalidate_stale_grants(key, exclude_id=grant["id"])
    touch(key)
    return grant


# ---------------------------------------------------------------------------
# Billing cycles
# ---------------------------------------------------------------------------
def close_cycle(cycle, plan, force_zero_carry_out=False):
    carried_out, expired = calc.entitlement_rollover(cycle, plan, force_zero_carry_out)
    cycle["entitlement_carried_out_units"] = carried_out
    cycle["entitlement_expired_units"] = expired
    cycle["status"] = "CLOSED"
    cycle["closed_at"] = now()
    touch(cycle)
    sub = get("subscriptions", cycle["subscription_id"])
    if sub is not None and sub.get("current_cycle_id") == cycle["id"]:
        sub["current_cycle_id"] = None
        touch(sub)


# ---------------------------------------------------------------------------
# Storm sweep settlement (fired by visit completion)
# ---------------------------------------------------------------------------
def settle_storm_sweep(visit, user_id):
    response = get("storm_responses", visit.get("storm_response_id"))
    if response is None or response["status"] != "SECURE_SWEEP_SCHEDULED":
        return
    response["secured_at"] = now()
    response["swept_by_user_id"] = user_id
    on_time = calc.sweep_timeliness(response)
    response["sweep_on_time"] = on_time
    sub = get("subscriptions", response.get("subscription_id")) or \
        calc.property_subscription(response["property_id"])
    plan = calc.in_force_plan(sub)
    if on_time:
        response["status"] = "SECURED"
        response["guarantee_credit_cents"] = calc.guarantee_credit_amount(response, plan)
    else:
        response["status"] = "SECURED_LATE"
        response["guarantee_credit_cents"] = 0
    touch(response)


# ---------------------------------------------------------------------------
# Property occupancy helpers driven by vendor activity
# ---------------------------------------------------------------------------
def occupancy_to_contractor(prop):
    if prop is not None and prop["occupancy_state"] == "VACANT":
        prop["occupancy_state"] = "CONTRACTOR_ONSITE"
        touch(prop)


def occupancy_from_contractor(prop, assignment):
    if prop is None or prop["occupancy_state"] != "CONTRACTOR_ONSITE":
        return
    for other in core.rows("vendor_assignments"):
        if other["id"] == assignment["id"]:
            continue
        if other["status"] != "WORKING":
            continue
        wo = get("work_orders", other["work_order_id"])
        if wo is not None and wo["property_id"] == prop["id"]:
            return
    prop["occupancy_state"] = "VACANT"
    calc.rederive_risk(prop)
    touch(prop)
