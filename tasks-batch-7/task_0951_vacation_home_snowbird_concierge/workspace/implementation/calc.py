"""Every calculation rule from SCAFFOLD 1.3, plus the derived-field re-derivations."""
import math
from datetime import timedelta
from decimal import Decimal

import core
from core import (D, fmt_iso, get, now, rhu, rhu1, rhu_cents, rows, touch)

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def children(collection, field, value):
    return [r for r in rows(collection) if r.get(field) == value]


def property_subscription(property_id):
    """The property's subscription: the newest one that is not CANCELLED,
    falling back to the newest row when every subscription is cancelled."""
    subs = children("subscriptions", "property_id", property_id)
    live = [s for s in subs if s["status"] != "CANCELLED"]
    if live:
        return live[-1]
    return subs[-1] if subs else None


def open_cycle(sub):
    if sub is None:
        return None
    cid = sub.get("current_cycle_id")
    if cid:
        cyc = get("billing_cycles", cid)
        if cyc is not None and cyc["status"] == "OPEN":
            return cyc
    for cyc in children("billing_cycles", "subscription_id", sub["id"]):
        if cyc["status"] == "OPEN":
            return cyc
    return None


def in_force_plan(sub):
    if sub is None:
        return None
    return get("service_plans", sub.get("service_plan_id"))


def property_of(row):
    return get("properties", row.get("property_id"))


def owner_of_property(prop):
    if prop is None:
        return None
    return get("owners", prop.get("owner_id"))


def property_draft_invoice(property_id):
    """The property's DRAFT invoice; the most recently created when several exist."""
    drafts = [i for i in rows("invoices")
              if i.get("property_id") == property_id and i["status"] == "DRAFT"]
    return drafts[-1] if drafts else None


# ---------------------------------------------------------------------------
# Property derivations
# ---------------------------------------------------------------------------
def travel_zone_assignment(miles):
    m = D(miles)
    if m <= core.TRAVEL_ZONE_Z1_MAX_MILES:
        return "Z1"
    if m <= core.TRAVEL_ZONE_Z2_MAX_MILES:
        return "Z2"
    if m <= core.TRAVEL_ZONE_Z3_MAX_MILES:
        return "Z3"
    return "OUT_OF_AREA"


def travel_surcharge(prop):
    return core.TRAVEL_SURCHARGE.get(prop.get("travel_zone"), 0)


def freeze_risk_score(prop):
    t = prop.get("last_interior_temp_f")
    if t is None:
        delta_term = Decimal("0.0")
    else:
        delta = D(prop.get("freeze_setpoint_f")) - D(t)
        if delta < 0:
            delta = Decimal("0")
        delta_term = core.FREEZE_RISK_WEIGHT_DELTA * delta
        if delta_term > core.FREEZE_RISK_DELTA_CAP:
            delta_term = core.FREEZE_RISK_DELTA_CAP
    w = D(prop.get("winterization_completeness_pct") or 0.0)
    if w >= Decimal("100.0"):
        wint_term = Decimal("0.0")
    else:
        wint_term = core.FREEZE_RISK_WEIGHT_WINTERIZATION * (Decimal("1.0") - w / Decimal("100.0"))
    vac_term = core.FREEZE_RISK_WEIGHT_VACANCY if prop.get("occupancy_state") == "VACANT" else Decimal("0.0")
    total = rhu(delta_term + wint_term + vac_term, 1)
    if total > core.FREEZE_RISK_SCORE_MAX:
        total = core.FREEZE_RISK_SCORE_MAX
    return float(total)


def property_risk_posture(score):
    s = D(score)
    if s >= core.FREEZE_RISK_CRITICAL_THRESHOLD:
        return "CRITICAL"
    if s >= core.FREEZE_RISK_ELEVATED_THRESHOLD:
        return "ELEVATED"
    return "NORMAL"


def rederive_risk(prop):
    prop["freeze_risk_score"] = freeze_risk_score(prop)
    prop["risk_posture"] = property_risk_posture(prop["freeze_risk_score"])


def newest_winterization_record(property_id):
    recs = children("winterization_records", "property_id", property_id)
    if not recs:
        return None
    return sorted(recs, key=lambda r: (r["created_at"], r.get("completed_step_count", 0), r["_seq"]))[-1]


def rederive_winterization_pct(prop):
    rec = newest_winterization_record(prop["id"])
    prop["winterization_completeness_pct"] = rec["completeness_pct"] if rec else 0.0


def open_critical_finding_count(property_id):
    live = {"OPEN", "TRIAGED", "WORK_ORDERED", "MONITORING"}
    return len([f for f in rows("findings")
                if f.get("property_id") == property_id
                and f.get("severity") == "CRITICAL" and f.get("status") in live])


def false_alarm_count_window(property_id):
    cutoff = now() - timedelta(days=core.FALSE_ALARM_WINDOW_DAYS)
    return len([i for i in rows("security_incidents")
                if i.get("property_id") == property_id and i.get("status") == "FALSE_ALARM"
                and i.get("reported_at") is not None and i["reported_at"] > cutoff])


def rederive_storm_hold(prop):
    open_states = {"SECURE_SWEEP_SCHEDULED", "SECURED", "SECURED_LATE",
                   "MISSED_DEADLINE", "AWAITING_ALL_CLEAR", "ASSESSMENT_DUE"}
    prop["storm_hold_flag"] = any(
        r["status"] in open_states for r in children("storm_responses", "property_id", prop["id"]))


# ---------------------------------------------------------------------------
# Visit calculations
# ---------------------------------------------------------------------------
def after_hours_flag(arrived_at):
    h = arrived_at.hour
    return h >= core.AFTER_HOURS_START_HOUR_UTC or h < core.AFTER_HOURS_END_HOUR_UTC


def visit_base_fee(visit):
    if visit["trigger_source"] == core.ENTITLEMENT_CONSUMING_TRIGGER_SOURCE:
        return core.VISIT_BASE_FEE_SCHEDULED_CENTS, 0
    expedite = core.OWNER_REQUEST_EXPEDITE_FEE_CENTS if visit["trigger_source"] == "OWNER_REQUESTED" else 0
    return core.VISIT_BASE_FEE_UNSCHEDULED_CENTS, expedite


def visit_billable_amount(visit, prop):
    base, expedite = visit_base_fee(visit)
    zone = travel_surcharge(prop)
    if visit["entitlement_applied"]:
        return zone
    if visit["after_hours_flag"]:
        multiplied = rhu_cents(D(base) * core.AFTER_HOURS_MULTIPLIER)
    else:
        multiplied = base
    return multiplied + expedite + zone


def checklist_completion_pct(visit, template):
    total = len(visit.get("completed_item_codes") or []) + len(visit.get("failed_item_codes") or [])
    required = template.get("required_item_count") or 0
    if not required:
        return 0.0
    return rhu1(Decimal(100) * Decimal(total) / Decimal(required))


def visit_duration_minutes(visit):
    a, c = visit.get("arrived_at"), visit.get("completed_at")
    if a is None or c is None:
        return 0
    return int(math.floor((c - a).total_seconds() / 60))


def temp_breach_detection(reading, prop):
    return D(reading) < (D(prop["freeze_setpoint_f"]) - core.FREEZE_TOLERANCE_BAND_F)


# ---------------------------------------------------------------------------
# Entitlement / billing-cycle calculations
# ---------------------------------------------------------------------------
def entitlement_consumption(visit, cycle, sub, plan):
    return (cycle is not None
            and sub is not None and sub["status"] == "ACTIVE"
            and visit["trigger_source"] == core.ENTITLEMENT_CONSUMING_TRIGGER_SOURCE
            and plan is not None and visit["visit_type"] in (plan.get("covered_visit_types") or [])
            and visit["visit_type"] in core.ENTITLEMENT_CONSUMING_VISIT_TYPES
            and visit.get("storm_response_id") is None
            and cycle["entitlement_remaining_units"] >= 1)


def entitlement_rollover(cycle, plan, force_zero_carry_out=False):
    remaining = cycle["entitlement_remaining_units"]
    if force_zero_carry_out:
        return 0, remaining
    policy = (plan or {}).get("entitlement_rollover_policy", "EXPIRE")
    if policy == "CARRY_CAPPED":
        carried_out = min(remaining, core.ENTITLEMENT_ROLLOVER_CAP_UNITS)
        return carried_out, remaining - carried_out
    return 0, remaining


def whole_days(delta_seconds):
    return int(math.floor(delta_seconds / 86400.0))


def proration_pause(cycle, sub, plan):
    paused_at = sub.get("paused_at")
    if paused_at is None:
        return cycle["prorated_fee_cents"]
    end = min(now(), cycle["period_end"])
    paused_days = whole_days((end - paused_at).total_seconds())
    paused_days = max(0, min(paused_days, core.PRORATION_DAY_BASIS))
    fee = rhu_cents(D(plan["monthly_fee_cents"]) * D(core.PRORATION_DAY_BASIS - paused_days)
                    / D(core.PRORATION_DAY_BASIS))
    return fee


def proration_tier_change(cycle, old_plan, new_plan):
    used_days = whole_days((now() - cycle["period_start"]).total_seconds())
    used_days = max(0, min(used_days, core.PRORATION_DAY_BASIS))
    remaining_days = core.PRORATION_DAY_BASIS - used_days
    leg1 = rhu_cents(D(old_plan["monthly_fee_cents"]) * D(used_days) / D(core.PRORATION_DAY_BASIS))
    leg2 = rhu_cents(D(new_plan["monthly_fee_cents"]) * D(remaining_days) / D(core.PRORATION_DAY_BASIS))
    return leg1 + leg2


def tier_change_entitlement_rederivation(cycle, new_plan):
    cycle["entitlement_granted_units"] = new_plan["included_visit_units"]
    remaining = (cycle["entitlement_granted_units"] + cycle["entitlement_carried_in_units"]
                 - cycle["entitlement_consumed_units"])
    cycle["entitlement_remaining_units"] = max(0, remaining)


def late_fee(invoice):
    qualifies = (invoice["status"] == "ISSUED" and invoice["balance_due_cents"] > 0
                 and invoice.get("issued_at") is not None
                 and invoice["issued_at"] + timedelta(days=core.DELINQUENCY_THRESHOLD_DAYS) <= now())
    if not qualifies:
        return 0
    return rhu_cents(D(invoice["balance_due_cents"]) * core.LATE_FEE_PCT)


# ---------------------------------------------------------------------------
# Away period
# ---------------------------------------------------------------------------
def away_period_derived_status(ap):
    clock = now()
    if clock < ap["start_at"]:
        return "PLANNED"
    if clock < ap["end_at"]:
        return "IN_EFFECT"
    return "ENDED"


def away_scheduled_visit_count(ap):
    live = {"SCHEDULED", "EN_ROUTE", "IN_PROGRESS", "COMPLETED"}
    return len([v for v in rows("visits")
                if v.get("away_period_id") == ap["id"] and v["status"] in live])


def cadence_projection_initial(ap):
    away_days = whole_days((ap["end_at"] - ap["start_at"]).total_seconds())
    return int(math.floor(away_days / ap["cadence_days"])) if ap["cadence_days"] else 0


def cadence_projection_revision(ap, new_cadence):
    anchor = max(now(), ap["start_at"])
    remaining_days = whole_days((ap["end_at"] - anchor).total_seconds())
    if remaining_days < 0:
        remaining_days = 0
    return away_scheduled_visit_count(ap) + int(math.floor(remaining_days / new_cadence))


# ---------------------------------------------------------------------------
# Finding / work-order cost chain
# ---------------------------------------------------------------------------
def finding_escalation_score(finding, prop):
    sev = core.FINDING_SEVERITY_WEIGHT[finding["severity"]]
    recheck = core.FINDING_RECHECK_WEIGHT * D(finding["monitor_recheck_count"])
    if recheck > core.FINDING_RECHECK_CAP:
        recheck = core.FINDING_RECHECK_CAP
    posture = core.FINDING_POSTURE_WEIGHT.get((prop or {}).get("risk_posture", "NORMAL"), Decimal("0.0"))
    total = rhu(sev + recheck + posture, 1)
    if total > core.FINDING_SCORE_MAX:
        total = core.FINDING_SCORE_MAX
    return float(total)


def bound_vendor(work_order):
    """The Vendor on the ACCEPTED / WORKING / FINISHED assignment of this work order."""
    for a in children("vendor_assignments", "work_order_id", work_order["id"]):
        if a["status"] in ("ACCEPTED", "WORKING", "FINISHED"):
            return get("vendors", a["vendor_id"])
    return None


def labour_cost(work_order):
    hours = work_order.get("actual_labour_hours")
    if hours is None:
        hours = work_order.get("estimated_labour_hours") or 0
    vendor = bound_vendor(work_order)
    rate = vendor["hourly_rate_cents"] if vendor else core.LABOUR_RATE_DEFAULT_CENTS_PER_HOUR
    return rhu_cents(D(hours) * D(rate))


def vendor_markup(work_order, base):
    vendor = bound_vendor(work_order)
    mode = vendor["billing_mode"] if vendor else "MANAGED"
    pct = core.VENDOR_MARKUP_PCT_MANAGED if mode == "MANAGED" else core.VENDOR_MARKUP_PCT_PASS_THROUGH
    if base >= core.VENDOR_MARKUP_VOLUME_TIER_BASE_CENTS:
        pct = pct - core.VENDOR_MARKUP_VOLUME_RELIEF_PCT
    return min(rhu_cents(D(base) * pct), core.VENDOR_MARKUP_CAP_CENTS)


def pipeline_of(work_order):
    return "STORM" if work_order.get("storm_event_id") else "ROUTINE"


def work_order_storm_surcharge(work_order, pre):
    if pipeline_of(work_order) == "ROUTINE":
        return 0
    return rhu_cents(D(pre) * D(work_order.get("surcharge_pct_applied") or 0.0))


def approval_ceiling(work_order):
    if pipeline_of(work_order) == "ROUTINE":
        prop = property_of(work_order)
        owner = owner_of_property(prop)
        override = (owner or {}).get("approval_ceiling_override_cents")
        return override if override is not None else core.WO_OWNER_APPROVAL_CEILING_CENTS
    return core.STORM_EMERGENCY_APPROVAL_CEILING_CENTS


def run_cost_chain(work_order):
    """calculation work_order_total - the pinned six-step evaluation order."""
    work_order["pipeline"] = pipeline_of(work_order)
    work_order["labour_cost_cents"] = labour_cost(work_order)
    if work_order.get("actual_parts_cents") is not None and \
            work_order["status"] in ("COMPLETED", "INVOICED"):
        work_order["parts_cost_cents"] = work_order["actual_parts_cents"]
    else:
        work_order["parts_cost_cents"] = work_order.get("estimated_parts_cents") or 0
    base = work_order["labour_cost_cents"] + work_order["parts_cost_cents"]
    work_order["markup_cents"] = vendor_markup(work_order, base)
    pre = base + work_order["markup_cents"]
    work_order["storm_surcharge_cents"] = work_order_storm_surcharge(work_order, pre)
    work_order["total_cents"] = base + work_order["markup_cents"] + work_order["storm_surcharge_cents"]
    work_order["approval_ceiling_cents"] = approval_ceiling(work_order)
    work_order["approval_required"] = work_order["total_cents"] > work_order["approval_ceiling_cents"]


# ---------------------------------------------------------------------------
# Vendor / key selection
# ---------------------------------------------------------------------------
def vendor_selection(work_order, finding):
    required_trade = core.FINDING_CATEGORY_TRADE_MAP.get((finding or {}).get("category", "OTHER"), "GENERAL")
    excluded = {a["vendor_id"] for a in children("vendor_assignments", "work_order_id", work_order["id"])
                if a["status"] == "DECLINED"}
    storm = pipeline_of(work_order) == "STORM"
    clock = now()
    pool = []
    for v in rows("vendors"):
        if v["status"] != "ELIGIBLE":
            continue
        if v["trade"] != required_trade:
            continue
        if not (v["coi_expires_at"] > clock):
            continue
        if not (v["license_expires_at"] > clock):
            continue
        if rhu(D(v["rating"]), 1) < core.VENDOR_MIN_RATING:
            continue
        if storm and not v.get("emergency_capable"):
            continue
        if v["id"] in excluded:
            continue
        if any(k["status"] in ("OVERDUE", "LOST")
               for k in children("key_issuances", "vendor_id", v["id"])):
            continue
        pool.append(v)
    pool.sort(key=lambda v: (-float(v["rating"]), v["hourly_rate_cents"], v["created_at"], v["_seq"]))
    return pool


def key_selection(property_id):
    candidates = [k for k in children("key_assets", "property_id", property_id)
                  if not k.get("rekey_pending_flag") and key_copies_on_hand(k) >= 1]
    candidates.sort(key=lambda k: (0 if k["key_type"] == "LOCKBOX" else 1, k["created_at"], k["_seq"]))
    return candidates[0] if candidates else None


def key_copies_issued_outstanding(key):
    return sum(i["copies_issued"] for i in children("key_issuances", "key_asset_id", key["id"])
               if i["status"] in ("ISSUED", "OVERDUE"))


def key_copies_lost(key):
    return sum(i["copies_issued"] for i in children("key_issuances", "key_asset_id", key["id"])
               if i["status"] in ("LOST", "REKEY_ORDERED"))


def key_copies_on_hand(key):
    return key["copies_total"] - key_copies_issued_outstanding(key) - key_copies_lost(key)


def key_active_grant_count(key):
    return len([grant for grant in children("access_grants", "key_asset_id", key["id"])
                if grant["status"] == "ACTIVE"])


def vendor_outstanding_key_count(vendor_id):
    return len([i for i in children("key_issuances", "vendor_id", vendor_id)
                if i["status"] in ("ISSUED", "OVERDUE")])


def key_return_deadline(issued_at, key):
    hours = (core.KEY_RETURN_WINDOW_HOURS_LOCKBOX if key["key_type"] == "LOCKBOX"
             else core.KEY_RETURN_WINDOW_HOURS_PHYSICAL)
    return issued_at + timedelta(hours=hours)


def key_overdue_days(issuance):
    deadline = issuance.get("return_deadline_at")
    if deadline is None or now() <= deadline:
        return 0
    return int(math.ceil((now() - deadline).total_seconds() / 86400.0))


def access_grant_capacity_ok(grant, key):
    concurrent = 0
    for other in children("access_grants", "key_asset_id", key["id"]):
        if other["id"] == grant["id"]:
            continue
        if other["status"] not in ("PENDING", "ACTIVE"):
            continue
        if other["window_start_at"] <= grant["window_end_at"] and \
                grant["window_start_at"] <= other["window_end_at"]:
            concurrent += 1
    return concurrent < key["copies_total"]


def assignment_window_conflict(assignment):
    for other in rows("vendor_assignments"):
        if other["id"] == assignment["id"]:
            continue
        if other["vendor_id"] != assignment["vendor_id"]:
            continue
        if other["status"] not in ("ACCEPTED", "WORKING"):
            continue
        if other["window_start_at"] <= assignment["window_end_at"] and \
                assignment["window_start_at"] <= other["window_end_at"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Turnover / mail / incident calculations
# ---------------------------------------------------------------------------
def turnover_padded_window(turnover):
    pad = timedelta(minutes=core.TURNOVER_OVERLAP_BUFFER_MINUTES)
    return turnover["checkout_at"] - pad, turnover["checkin_at"] + pad


def turnover_overlap(start_at, end_at, turnover):
    lo, hi = turnover_padded_window(turnover)
    return start_at < hi and end_at > lo


def any_turnover_overlap(property_id, start_at, end_at):
    for t in children("rental_turnovers", "property_id", property_id):
        if t["status"] in ("CHECKIN", "CANCELLED"):
            continue
        if turnover_overlap(start_at, end_at, t):
            return True
    return False


def mail_hold_days(hold):
    return whole_days((hold["end_on"] - hold["start_on"]).total_seconds())


def mail_disposition_fee_forward(hold):
    return core.MAIL_FORWARD_BASE_CENTS + core.MAIL_FORWARD_PER_ITEM_CENTS * hold["package_count"]


def mail_disposition_fee_extension(hold):
    return core.HOLD_EXTENSION_FEE_CENTS * hold["extension_count"]


def false_alarm_sequence(incident):
    cutoff = now() - timedelta(days=core.FALSE_ALARM_WINDOW_DAYS)
    peers = [i for i in rows("security_incidents")
             if i.get("property_id") == incident["property_id"]
             and i["status"] == "FALSE_ALARM"
             and i.get("reported_at") is not None and i["reported_at"] > cutoff]
    peers.sort(key=lambda i: (i["reported_at"], i["created_at"], i["_seq"]))
    for idx, peer in enumerate(peers, start=1):
        if peer["id"] == incident["id"]:
            return idx
    return len(peers) + 1


def false_alarm_fee(sequence):
    return core.FALSE_ALARM_FEES.get(sequence, core.FALSE_ALARM_FEE_5_PLUS_CENTS)


# ---------------------------------------------------------------------------
# Storm calculations
# ---------------------------------------------------------------------------
def storm_advisory_tier(event):
    hours = D((event["landfall_eta_at"] - now()).total_seconds()) / Decimal(3600)
    if hours > core.STORM_TIER_WATCH_MAX_HOURS:
        return "FORECAST"
    if hours > core.STORM_TIER_WARNING_MAX_HOURS:
        return "WATCH"
    if hours > core.STORM_TIER_IMMINENT_MAX_HOURS:
        return "WARNING"
    return "IMMINENT"


def response_deadline_pre_storm(event):
    lead = core.STORM_SWEEP_LEAD_HOURS[storm_advisory_tier(event)]
    return event["landfall_eta_at"] - timedelta(hours=lead)


def response_deadline_post_storm(event):
    if event.get("all_clear_at") is None:
        return None
    return event["all_clear_at"] + timedelta(hours=core.STORM_ASSESSMENT_SLA_HOURS)


def sweep_timeliness(response):
    return response["secured_at"] <= response["secure_sweep_deadline_at"]


def guarantee_credit_amount(response, plan):
    if not response.get("sweep_on_time") or not (plan or {}).get("storm_guarantee_included"):
        return 0
    basis = sum(w["storm_surcharge_cents"] for w in rows("work_orders")
                if w.get("storm_event_id") == response["storm_event_id"]
                and w.get("property_id") == response["property_id"]
                and w["status"] in ("COMPLETED", "INVOICED"))
    if basis == 0:
        return core.STORM_GUARANTEE_CREDIT_CENTS
    return min(core.STORM_GUARANTEE_CREDIT_CENTS, rhu_cents(D(basis) * core.STORM_GUARANTEE_CREDIT_PCT))


def storm_surcharge_pct(event):
    return core.STORM_SURCHARGE_PCT[storm_advisory_tier(event)]


def storm_response_count(event_id):
    return len(children("storm_responses", "storm_event_id", event_id))


# ---------------------------------------------------------------------------
# Invoice pipeline
# ---------------------------------------------------------------------------
def invoice_line_tax(line):
    if line.get("taxable") and line["status"] == "ACTIVE":
        return rhu_cents(D(line["amount_cents"]) * core.TAX_RATE_PCT)
    return 0


def invoice_lines_of(invoice_id):
    lines = children("invoice_lines", "invoice_id", invoice_id)
    lines.sort(key=lambda l: (l.get("sequence_index") or 0, l["_seq"]))
    return lines


def invoice_storm_surcharge_pct(invoice):
    best = None
    for line in invoice_lines_of(invoice["id"]):
        if line["status"] != "ACTIVE" or line["line_type"] != "WORK_ORDER":
            continue
        wo = get("work_orders", line.get("work_order_id"))
        if wo is None or pipeline_of(wo) != "STORM":
            continue
        pct = wo.get("surcharge_pct_applied") or 0.0
        best = pct if best is None else max(best, pct)
    return best if best is not None else 0.0


def recompute_invoice(invoice):
    """The nine-step total pipeline (PRD 3.11)."""
    invoice["storm_surcharge_pct"] = invoice_storm_surcharge_pct(invoice)
    lines = [l for l in invoice_lines_of(invoice["id"]) if l["status"] == "ACTIVE"]
    gross = sum(l["amount_cents"] for l in lines if l["line_type"] in core.GROSS_SERVICE_LINE_TYPES)
    offset = sum(l["amount_cents"] for l in lines if l["line_type"] == "ENTITLEMENT_OFFSET")
    net = gross + offset
    surcharge = rhu_cents(D(net) * D(invoice["storm_surcharge_pct"]))
    credit = sum(l["amount_cents"] for l in lines if l["line_type"] == "GUARANTEE_CREDIT")
    subtotal = net + surcharge + credit
    tax = sum(l["tax_cents"] for l in lines) + rhu_cents(D(surcharge) * core.TAX_RATE_PCT)
    invoice["gross_service_cents"] = gross
    invoice["entitlement_offset_cents"] = offset
    invoice["storm_surcharge_cents"] = surcharge
    invoice["guarantee_credit_cents"] = credit
    invoice["subtotal_cents"] = subtotal
    invoice["tax_cents"] = tax
    invoice["total_cents"] = subtotal + tax + invoice["late_fee_cents"]
    invoice["balance_due_cents"] = invoice["total_cents"] - invoice["amount_paid_cents"]


def owner_lifetime_credit(owner_id):
    total = 0
    for line in rows("invoice_lines"):
        if line["status"] != "ACTIVE" or line["line_type"] != "GUARANTEE_CREDIT":
            continue
        inv = get("invoices", line["invoice_id"])
        if inv is not None and inv.get("owner_id") == owner_id:
            total += abs(line["amount_cents"])
    return total


def append_invoice_line(invoice, line_type, description, amount_cents, taxable=True, **links):
    seq = len(invoice_lines_of(invoice["id"])) + 1
    line = core.new_row(
        "invoice_lines",
        invoice_id=invoice["id"],
        visit_id=links.get("visit_id"),
        work_order_id=links.get("work_order_id"),
        security_incident_id=links.get("security_incident_id"),
        mail_hold_id=links.get("mail_hold_id"),
        line_type=line_type,
        description=description,
        amount_cents=amount_cents,
        taxable=taxable,
        tax_cents=0,
        status="ACTIVE",
        sequence_index=seq,
    )
    line["tax_cents"] = invoice_line_tax(line)
    recompute_invoice(invoice)
    touch(invoice)
    return line
