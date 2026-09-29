"""Shared lookups, derived-field recomputation, lazy expiry and the cascades."""

from errors import ApiError
from store import db, now, days, bump, table_rows, base_record, event_record
import calc

TERMINAL = {
    "patients": ("DEACTIVATED",),
    "screening_sessions": ("INVALIDATED",),
    "provider_referrals": ("CLEARED", "NOT_CLEARED", "EXPIRED", "WITHDRAWN"),
    "remote_fitting_sessions": ("COMPLETED", "CANCELLED"),
    "trial_periods": ("RETURN_SETTLED", "EXPIRED_KEPT", "VOIDED"),
    "return_authorizations": ("REFUND_SETTLED", "EXPIRED", "VOIDED"),
    "fit_exchanges": ("COMPLETED", "REJECTED", "CANCELLED"),
    "repair_orders": ("RETURNED_TO_PATIENT", "ESCALATED_TO_WARRANTY", "CANCELLED"),
    "warranty_claims": ("FULFILLED", "DENIED", "WITHDRAWN"),
    "reimbursement_claims": ("PAID", "VOIDED"),
    "care_plan_subscriptions": ("CANCELLED",),
    "firmware_campaigns": ("COMPLETED", "ABORTED"),
    "firmware_rollouts": ("INSTALLED", "ROLLED_BACK", "CANCELLED_INELIGIBLE"),
    "compliance_overrides": ("APPROVED", "REJECTED"),
}

PAYMENT_TERMINAL = ("REFUNDED", "AUTH_FAILED", "VOIDED")
FULFILLMENT_TERMINAL = ("RETURNED", "CANCELLED")


# ----------------------------------------------------------------- lookups
def find(table, row_id):
    row = table.get(row_id) if row_id is not None else None
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return row


def ref(table, row_id):
    row = table.get(row_id) if row_id is not None else None
    if row is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return row


def ensure_state(row, field, allowed, table_name=None):
    """Rule 23 (already terminal) then rule 22 (invalid state)."""
    current = row.get(field)
    if current in allowed:
        return
    terminals = ()
    if table_name is not None:
        terminals = TERMINAL.get(table_name, ())
    if current in terminals:
        raise ApiError("ERR_ALREADY_TERMINAL")
    raise ApiError("ERR_INVALID_STATE")


def policy_of(patient):
    if patient is None:
        return None
    return db.state_policies.get(patient.get("state_policy_id"))


def pinned_policy(order):
    snapshot = order.get("_pinned_policy")
    if snapshot is not None:
        return snapshot
    return db.state_policies.get(order.get("state_policy_id")) or {}


def order_patient(order):
    return db.patients.get(order.get("patient_id"))


def plan_for_order(order_id):
    rows = [p for p in table_rows(db.care_plan_subscriptions)
            if p.get("device_order_id") == order_id]
    if not rows:
        return None
    live = [p for p in rows if p.get("status") != "CANCELLED"]
    return live[-1] if live else rows[-1]


def plans_for_order(order_id):
    return [p for p in table_rows(db.care_plan_subscriptions)
            if p.get("device_order_id") == order_id]


def plan_for_patient(patient_id):
    rows = [p for p in table_rows(db.care_plan_subscriptions)
            if p.get("patient_id") == patient_id and p.get("status") != "CANCELLED"]
    return rows[-1] if rows else None


def plan_for_device(device):
    if device is None or device.get("device_order_id") is None:
        return None
    return plan_for_order(device["device_order_id"])


def trial_for_order(order_id):
    rows = [t for t in table_rows(db.trial_periods) if t.get("device_order_id") == order_id]
    return rows[-1] if rows else None


def device_for_order(order_id):
    rows = [d for d in table_rows(db.devices)
            if d.get("device_order_id") == order_id and d.get("status") != "RETIRED"]
    if rows:
        return rows[-1]
    rows = [d for d in table_rows(db.devices) if d.get("device_order_id") == order_id]
    return rows[-1] if rows else None


def pool_for(model, dome_size, tip_type):
    for pool in table_rows(db.inventory_pools):
        if (pool.get("model") == model and pool.get("dome_size") == dome_size
                and pool.get("tip_type") == tip_type):
            return pool
    return None


def patient_of_device(device):
    order = db.device_orders.get(device.get("device_order_id")) if device else None
    return order.get("patient_id") if order else None


# ------------------------------------------------------- derived recomputation
def sessions_of(patient_id):
    return [s for s in table_rows(db.screening_sessions) if s.get("patient_id") == patient_id]


def findings_of_session(session_id):
    return [f for f in table_rows(db.red_flag_findings)
            if f.get("screening_session_id") == session_id]


def recompute_patient_counters(patient):
    sessions = sessions_of(patient["id"])
    live = [s for s in sessions if s.get("status") != "INVALIDATED"]
    live_ids = set(s["id"] for s in live)
    mandatory = 0
    for finding in table_rows(db.red_flag_findings):
        if finding.get("screening_session_id") not in live_ids:
            continue
        if finding.get("severity") == "MANDATORY_REFERRAL" and finding.get("cleared_by_referral_id") is None:
            mandatory += 1
    advisory_total = 0.0
    if live:
        latest = live[-1]
        total = 0.0
        for finding in findings_of_session(latest["id"]):
            if finding.get("severity") == "ADVISORY" and finding.get("cleared_by_referral_id") is None:
                total += float(finding.get("weight") or 0)
        advisory_total = calc.one_dp(total)
    patient["open_mandatory_flag_count"] = mandatory
    patient["advisory_weight_total"] = advisory_total
    return patient


def recompute_screening_attempt_count(patient):
    count = 0
    for session in sessions_of(patient["id"]):
        if session.get("status") in ("SCORED", "INVALIDATED"):
            count += 1
    patient["screening_attempt_count"] = count
    return count


def refresh_provider_counters(provider, focus_date=None):
    if provider is None:
        return
    if focus_date is None:
        focus_date = provider.get("_focus_date")
    if focus_date is None:
        return
    provider["_focus_date"] = focus_date
    booked = calc.booked_minutes(provider["id"], focus_date)
    provider["booked_minutes_on_focus_date"] = booked
    provider["utilization_pct"] = calc.utilization(booked, provider["daily_capacity_minutes"])
    bump(provider)


def recompute_campaign_counters(campaign):
    rollouts = [r for r in db.firmware_rollouts.values()
                if r.get("firmware_campaign_id") == campaign["id"]]
    active = [r for r in rollouts if r.get("status") != "CANCELLED_INELIGIBLE"]
    installed = sum(1 for r in rollouts if r.get("status") == "INSTALLED")
    failed = sum(1 for r in rollouts if r.get("status") == "FAILED")
    campaign["rollout_count"] = len(active)
    campaign["installed_count"] = installed
    denominator = installed + failed
    if denominator == 0:
        campaign["failure_rate_pct"] = 0.0
    else:
        campaign["failure_rate_pct"] = calc.one_dp(
            calc.D(100) * calc.D(failed) / calc.D(denominator))
    bump(campaign)
    return campaign


def recompute_order_cash(order):
    order["open_balance_cents"] = (int(order["captured_cents"])
                                   - int(order["refunded_cents"])
                                   - int(order["retained_cents"]))
    return order


def recompute_loss_damage_claims(device):
    count = 0
    for claim in db.warranty_claims.values():
        if claim.get("device_id") != device["id"]:
            continue
        if claim.get("status") in ("APPROVED_REPLACEMENT", "FULFILLED") and \
                claim.get("claim_kind") in ("LOSS", "DAMAGE"):
            count += 1
    device["loss_damage_claims_approved"] = count
    return count


# --------------------------------------------------------------- lazy expiry
def touch_referral(referral):
    if referral is None:
        return referral
    if referral.get("status") in ("OPEN", "SCHEDULED"):
        expires = referral.get("expires_at")
        if expires is not None and now() >= expires:
            previous = referral["status"]
            referral["status"] = "EXPIRED"
            bump(referral)
            if previous == "SCHEDULED":
                for session in table_rows(db.remote_fitting_sessions):
                    if session.get("provider_referral_id") != referral["id"]:
                        continue
                    if session.get("status") not in ("SCHEDULED", "IN_PROGRESS"):
                        continue
                    session["status"] = "CANCELLED"
                    session["no_show_charged_cents"] = 0
                    bump(session)
                    provider = db.providers.get(session.get("provider_id"))
                    start = session.get("scheduled_start_utc")
                    if provider is not None and start is not None:
                        refresh_provider_counters(provider, start.date())
    return referral


def touch_trial(trial):
    if trial is None:
        return trial
    if trial.get("status") in ("ACTIVE", "PAUSED", "RETURN_INITIATED"):
        calc.trial_days_used(trial)
    status = trial.get("status")
    if status in ("ACTIVE", "PAUSED"):
        effective_end = trial.get("effective_end_utc")
        if effective_end is not None and now() > effective_end:
            blocking = [a for a in db.return_authorizations.values()
                        if a.get("trial_period_id") == trial["id"]
                        and a.get("status") in ("ISSUED", "IN_TRANSIT", "RECEIVED", "INSPECTED")]
            if not blocking:
                if status == "PAUSED":
                    for interval in trial.get("pause_intervals") or []:
                        if interval.get("pause_end_utc") is None:
                            interval["pause_end_utc"] = effective_end
                    calc.trial_days_used(trial)
                trial["status"] = "EXPIRED_KEPT"
                bump(trial)
    return trial


def touch_return_auth(auth):
    if auth is None:
        return auth
    if auth.get("status") == "ISSUED":
        deadline = auth.get("return_deadline_utc")
        if deadline is not None and now() > deadline:
            auth["status"] = "EXPIRED"
            bump(auth)
            trial = db.trial_periods.get(auth.get("trial_period_id"))
            if trial is not None and trial.get("status") == "RETURN_INITIATED":
                calc.trial_days_used(trial)
                effective_end = trial.get("effective_end_utc")
                if effective_end is not None and now() > effective_end:
                    trial["status"] = "EXPIRED_KEPT"
                else:
                    trial["status"] = "ACTIVE"
                bump(trial)
    return auth


def touch_all_referrals():
    for referral in list(db.provider_referrals.values()):
        touch_referral(referral)


def touch_all_trials():
    for trial in list(db.trial_periods.values()):
        touch_trial(trial)


def touch_all_return_auths():
    for auth in list(db.return_authorizations.values()):
        touch_return_auth(auth)


# ------------------------------------------------------------ plan money moves
def charge_plan(plan, amount_cents):
    """Draw an amount against plan credit first; the shortfall rides the next cycle."""
    if plan is None or amount_cents <= 0:
        return 0
    applied = min(int(plan.get("credit_balance_cents") or 0), amount_cents)
    if applied:
        plan["credit_balance_cents"] = int(plan["credit_balance_cents"]) - applied
        bump(plan)
    return applied


def credit_plan(plan, amount_cents):
    if plan is None or amount_cents <= 0:
        return
    plan["credit_balance_cents"] = int(plan.get("credit_balance_cents") or 0) + amount_cents
    bump(plan)


# ---------------------------------------------------------------- rollouts
def cancel_rollouts_for_device(device_id, statuses=("PENDING", "OFFERED"),
                               skip_mandatory_safety=False):
    campaigns = []
    for rollout in table_rows(db.firmware_rollouts):
        if rollout.get("device_id") != device_id:
            continue
        if rollout.get("status") not in statuses:
            continue
        campaign = db.firmware_campaigns.get(rollout.get("firmware_campaign_id"))
        if skip_mandatory_safety and campaign is not None and campaign.get("is_mandatory_safety"):
            continue
        rollout["status"] = "CANCELLED_INELIGIBLE"
        bump(rollout)
        if campaign is not None and campaign not in campaigns:
            campaigns.append(campaign)
    for campaign in campaigns:
        recompute_campaign_counters(campaign)


def cancel_plan(plan, forfeit=True):
    if plan is None or plan.get("status") == "CANCELLED":
        return
    plan["status"] = "CANCELLED"
    if forfeit:
        plan["credit_balance_cents"] = 0
    bump(plan)
    order = db.device_orders.get(plan.get("device_order_id"))
    device = device_for_order(order["id"]) if order else None
    if device is not None:
        cancel_rollouts_for_device(device["id"])


# ------------------------------------------------------------ inventory moves
def release_reservation(order):
    pool = db.inventory_pools.get(order.get("_reserved_pool_id"))
    if pool is None:
        return
    pool["reserved_units"] = max(0, int(pool["reserved_units"]) - 1)
    pool["on_hand_units"] = int(pool["on_hand_units"]) + 1
    bump(pool)
    order["_reserved_pool_id"] = None


def unassign_device(order):
    device = device_for_order(order["id"])
    if device is not None and device.get("status") == "ASSIGNED":
        device["status"] = "IN_STOCK"
        device["device_order_id"] = None
        bump(device)


# ---------------------------------------------------------- CASCADE-B (hold)
def cascade_medical_hold(patient):
    """Hops 2-4: orders to MEDICAL_HOLD, sessions cancelled, capacity recomputed."""
    for order in table_rows(db.device_orders):
        if order.get("patient_id") != patient["id"]:
            continue
        status = order.get("fulfillment_status")
        if status not in ("PENDING_FIT_CONFIRM", "READY_TO_SHIP"):
            continue
        if status == "READY_TO_SHIP":
            release_reservation(order)
            unassign_device(order)
        order["fulfillment_status"] = "MEDICAL_HOLD"
        order["medical_hold_reason"] = "MANDATORY_RED_FLAG"
        bump(order)
        for session in table_rows(db.remote_fitting_sessions):
            if session.get("device_order_id") != order["id"]:
                continue
            if session.get("status") != "SCHEDULED":
                continue
            if session.get("session_type") not in ("INITIAL_FIT", "FOLLOW_UP"):
                continue
            session["status"] = "CANCELLED"
            session["no_show_charged_cents"] = 0
            bump(session)
            provider = db.providers.get(session.get("provider_id"))
            start = session.get("scheduled_start_utc")
            if provider is not None and start is not None:
                refresh_provider_counters(provider, start.date())


def release_medical_hold(patient):
    for order in table_rows(db.device_orders):
        if order.get("patient_id") != patient["id"]:
            continue
        if order.get("fulfillment_status") != "MEDICAL_HOLD":
            continue
        order["fulfillment_status"] = "PENDING_FIT_CONFIRM"
        order["medical_hold_reason"] = None
        bump(order)


def cancel_held_orders(patient):
    """NOT_CLEARED determination: cancel held orders with a regulatory full refund."""
    for order in table_rows(db.device_orders):
        if order.get("patient_id") != patient["id"]:
            continue
        if order.get("fulfillment_status") != "MEDICAL_HOLD":
            continue
        cancel_order_regulatory(order)


def cancel_order_regulatory(order):
    order["fulfillment_status"] = "CANCELLED"
    if order.get("payment_status") == "AUTHORIZED":
        order["payment_status"] = "VOIDED"
    elif order.get("payment_status") in ("CAPTURED", "PARTIALLY_REFUNDED"):
        order["payment_status"] = "REFUNDED"
        order["refunded_cents"] = int(order["captured_cents"])
        order["retained_cents"] = 0
    recompute_order_cash(order)
    bump(order)
    trial = trial_for_order(order["id"])
    if trial is not None and trial.get("status") in ("ACTIVE", "PAUSED", "RETURN_INITIATED"):
        trial["status"] = "VOIDED"
        bump(trial)
        for auth in table_rows(db.return_authorizations):
            if auth.get("trial_period_id") == trial["id"] and auth.get("status") == "ISSUED":
                auth["status"] = "VOIDED"
                auth["restocking_fee_cents"] = 0
                auth["refund_amount_cents"] = 0
                bump(auth)
    for plan in plans_for_order(order["id"]):
        cancel_plan(plan)


# ---------------------------------------------------------- CASCADE-A (return)
def cascade_return_settlement(auth, trial, order):
    """The five-hop return-settlement cascade, synchronous inside the request."""
    # hop 1
    trial["status"] = "RETURN_SETTLED"
    bump(trial)
    patient = db.patients.get(trial.get("patient_id"))
    if patient is not None:
        patient["lifetime_return_count"] = int(patient.get("lifetime_return_count") or 0) + 1
        bump(patient)
    # hop 2
    refund = int(auth["refund_amount_cents"])
    retained = int(auth["restocking_fee_cents"]) + int(auth["non_refundable_shipping_cents"])
    order["refunded_cents"] = int(order["refunded_cents"]) + refund
    order["retained_cents"] = int(order["retained_cents"]) + retained
    recompute_order_cash(order)
    if order["refunded_cents"] == int(order["captured_cents"]):
        order["payment_status"] = "REFUNDED"
        order["retained_cents"] = 0
        recompute_order_cash(order)
    else:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    order["fulfillment_status"] = "RETURNED"
    bump(order)
    # hop 3
    device = device_for_order(order["id"])
    if device is not None:
        device["status"] = "RETIRED"
        bump(device)
    # hop 4
    for plan in plans_for_order(order["id"]):
        cancel_plan(plan)
    # hop 5
    if device is not None:
        cancel_rollouts_for_device(device["id"])


# ------------------------------------------------------------------ creation
def new_row(table, **fields):
    row = base_record()
    row.update(fields)
    table[row["id"]] = row
    return row


def new_event(table, **fields):
    row = event_record()
    row.update(fields)
    table[row["id"]] = row
    return row


def unique_or_conflict(table, field, value, transform=None):
    for row in table.values():
        current = row.get(field)
        if transform is not None:
            current = transform(current) if current is not None else current
            value_cmp = transform(value)
        else:
            value_cmp = value
        if current == value_cmp:
            raise ApiError("ERR_DUPLICATE_KEY")


def sla_days_for(plan):
    if plan is None or plan.get("status") in ("SUSPENDED", "CANCELLED"):
        return 15
    if plan.get("plan_tier") == "PREMIUM":
        return 5
    return 10


def resume_trial_after_repair(repair):
    trial = None
    order = None
    device = db.devices.get(repair.get("device_id"))
    if device is not None and device.get("device_order_id"):
        order = db.device_orders.get(device["device_order_id"])
    if order is not None:
        trial = trial_for_order(order["id"])
    if trial is None or trial.get("status") != "PAUSED":
        return
    for interval in trial.get("pause_intervals") or []:
        if interval.get("pause_end_utc") is None:
            interval["pause_end_utc"] = now()
    calc.trial_days_used(trial)
    trial["status"] = "ACTIVE"
    bump(trial)


def close_repair(repair, plan):
    repair["closed_at"] = now()
    turnaround, credit = calc.repair_sla_credit(repair, plan)
    repair["turnaround_days"] = turnaround
    repair["sla_credit_cents"] = credit
    if plan is not None and credit:
        credit_plan(plan, credit)


def days_from(instant, count):
    return instant + days(count)
