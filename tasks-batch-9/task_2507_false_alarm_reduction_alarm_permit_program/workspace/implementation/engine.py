"""Domain engine: counting windows, pricing, invoices, roll-ups, cascades.

Every rule in here traces to a sentence of PRD.md section 3.
"""

from datetime import timedelta

import calc
from errors import ApiError
from store import (add_days, base_row, now, occurrence_key, order_key, store,
                   touch, whole_days_between)

CHARGEABLE_STATUSES = ("COUNTED", "APPEALED")
LIVE_PERMIT_STATUSES = ("ACTIVE", "RENEWAL_DUE", "RENEWAL_BLOCKED", "GRACE")
OPEN_REQUEST_STATUSES = ("SUBMITTED", "VALIDATED", "DISPATCHED")
LIVE_ORDER_STATUSES = ("EFFECTIVE", "REINSTATEMENT_PENDING")
LIVE_APPEAL_STATUSES = ("FILED", "SCHEDULED", "HEARD")
STAGE_RANK = {"REFERRED": 4, "FINAL_NOTICE": 3, "NOTICE": 2, "CURRENT": 1,
              "WRITTEN_OFF": 0}

DEFAULT_COMPANY_PROBATION_THRESHOLD = 0.70
DEFAULT_COMPANY_SUSPENSION_THRESHOLD = 0.50


# ---------------------------------------------------------------------------
# fee schedules
# ---------------------------------------------------------------------------

def active_status_schedule():
    """The single row whose `status` is `ACTIVE`, regardless of the clock.

    PRD 2.9: "At most one schedule is `ACTIVE` program-wide at any logical
    instant" -- this is what a fresh activation pushes to `SUPERSEDED`.
    """
    for s in sorted(store.fee_schedules.values(), key=order_key):
        if s.get("status") == "ACTIVE":
            return s
    return None


def active_schedule():
    """The schedule that is `ACTIVE` *at the logical clock*.

    PRD 3.1 calls `effective_from` "the `effective_from` instant it governs
    from", and PRD 2.9 / 2.10 position 43 gate money on a schedule being
    "`ACTIVE` at the logical clock".  An activated row whose `effective_from`
    is still in the future therefore governs nothing yet.
    """
    sched = active_status_schedule()
    if sched is None:
        return None
    starts = sched.get("effective_from")
    if starts is not None and starts > now():
        return None
    return sched


def governing_schedule(site):
    sid = site.get("governing_fee_schedule_id")
    if not sid:
        return None
    return store.fee_schedules.get(sid)


def require_governing(site):
    sched = governing_schedule(site)
    if sched is None:
        raise ApiError("ERR_NO_ACTIVE_FEE_SCHEDULE",
                       "The premises is not pinned to a governing fee schedule.")
    return sched


def company_thresholds():
    # Constant lookup, not a money gate: read whatever row carries the
    # ordinance's numbers rather than testing the clock.
    sched = active_status_schedule()
    if sched is None:
        return (DEFAULT_COMPANY_PROBATION_THRESHOLD,
                DEFAULT_COMPANY_SUSPENSION_THRESHOLD)
    return (float(sched.get("company_probation_score_threshold")),
            float(sched.get("company_suspension_score_threshold")))


# ---------------------------------------------------------------------------
# child collections
# ---------------------------------------------------------------------------

def _by_site(table, site_id):
    return sorted([r for r in getattr(store, table).values()
                   if r.get("alarm_site_id") == site_id], key=order_key)


def site_contacts(site_id):
    return _by_site("site_contacts", site_id)


def live_callable_contacts(site_id):
    return [c for c in site_contacts(site_id)
            if c.get("status") == "ACTIVE" and c.get("is_ecv_callable") is True]


def site_systems(site_id):
    return _by_site("alarm_systems", site_id)


def site_permits(site_id):
    return _by_site("alarm_permits", site_id)


def site_invoices(site_id):
    return _by_site("penalty_invoices", site_id)


def site_orders(site_id):
    return _by_site("suspension_orders", site_id)


def site_incidents(site_id):
    return _by_site("false_alarm_incidents", site_id)


def system_permits(system_id):
    return sorted([p for p in store.alarm_permits.values()
                   if p.get("alarm_system_id") == system_id], key=order_key)


def system_requests(system_id):
    return sorted([r for r in store.dispatch_requests.values()
                   if r.get("alarm_system_id") == system_id], key=order_key)


def incident_for_request(request_id):
    for inc in sorted(store.false_alarm_incidents.values(), key=order_key):
        if inc.get("dispatch_request_id") == request_id:
            return inc
    return None


def invoice_for_incident(incident_id):
    for inv in sorted(store.penalty_invoices.values(), key=order_key):
        if inv.get("false_alarm_incident_id") == incident_id \
                and inv.get("payment_status") != "VOIDED":
            return inv
    return None


def invoice_for_order(order_id):
    for inv in sorted(store.penalty_invoices.values(), key=order_key):
        if inv.get("suspension_order_id") == order_id \
                and inv.get("payment_status") != "VOIDED":
            return inv
    return None


def appeals_for_incident(incident_id):
    return sorted([a for a in store.appeals.values()
                   if a.get("false_alarm_incident_id") == incident_id],
                  key=order_key)


def live_appeal_for_incident(incident_id):
    for a in appeals_for_incident(incident_id):
        if a.get("status") in LIVE_APPEAL_STATUSES:
            return a
    return None


def docket_appeals(docket_id):
    return sorted([a for a in store.appeals.values()
                   if a.get("hearing_docket_id") == docket_id], key=order_key)


def allocations_for_invoice(invoice_id):
    return sorted([a for a in store.payment_allocations.values()
                   if a.get("penalty_invoice_id") == invoice_id], key=order_key)


def allocations_for_payment(payment_id):
    return sorted([a for a in store.payment_allocations.values()
                   if a.get("payment_record_id") == payment_id],
                  key=lambda r: r.get("sequence_index", 0))


def company_reports(company_id):
    return sorted([r for r in store.compliance_reports.values()
                   if r.get("monitoring_company_id") == company_id],
                  key=order_key)


# ---------------------------------------------------------------------------
# false_alarm_occurrence_index  (PRD 3.5)
# ---------------------------------------------------------------------------

def chargeable_incidents(site_id):
    return [i for i in site_incidents(site_id)
            if i.get("status") in CHARGEABLE_STATUSES]


def _permit_year_start(site_id, at):
    best = None
    for p in site_permits(site_id):
        ts = p.get("term_start_at")
        gt = p.get("grace_through_at")
        if ts is None or gt is None:
            continue
        if ts <= at <= gt:
            if best is None:
                best = p
            else:
                bts = best.get("term_start_at")
                if ts > bts or (ts == bts and order_key(p) < order_key(best)):
                    best = p
    return best.get("term_start_at") if best is not None else None


def window_start(site_id, mode, at):
    if mode == "PERMIT_YEAR":
        return _permit_year_start(site_id, at)
    return at - timedelta(days=365)


def count_chargeable_in_window(site_id, mode, at):
    start = window_start(site_id, mode, at)
    total = 0
    for inc in chargeable_incidents(site_id):
        occurred = inc.get("occurred_at")
        if occurred is None:
            continue
        if start is not None and occurred < start:
            continue
        total += 1
    return total


def occurrence_index_for(site, sched, incident):
    """Size of the governing window's chargeable set, counting this incident."""
    mode = sched.get("counting_window_mode")
    at = incident.get("occurred_at")
    start = window_start(site["id"], mode, at)
    key = occurrence_key(incident)
    index = 1
    for other in chargeable_incidents(site["id"]):
        if other["id"] == incident["id"]:
            continue
        occurred = other.get("occurred_at")
        if occurred is None:
            continue
        if start is not None and occurred < start:
            continue
        if occurrence_key(other) < key:
            index += 1
    return index


def aggravation_applies(site_id, at):
    for order in site_orders(site_id):
        if order.get("status") not in LIVE_ORDER_STATUSES:
            continue
        frm = order.get("effective_from")
        thr = order.get("effective_through")
        if frm is None or thr is None:
            continue
        if frm <= at <= thr:
            return True
    return False


def price_incident(site, sched, incident):
    req = store.dispatch_requests.get(incident.get("dispatch_request_id")) or {}
    aggravated = aggravation_applies(site["id"], incident.get("occurred_at"))
    return calc.compute_false_alarm_fee(sched, site, req,
                                        incident.get("occurrence_index") or 0,
                                        aggravated)


# ---------------------------------------------------------------------------
# invoices
# ---------------------------------------------------------------------------

def new_invoice(site, sched, kind, lines, link_field=None, link_id=None):
    subtotal = sum(l["extended_cents"] for l in lines)
    admin_fee = calc.admin_fee_for(sched, subtotal)
    assessed = subtotal + admin_fee
    issued = now()
    row = base_row()
    row["alarm_site_id"] = site["id"]
    row["false_alarm_incident_id"] = None
    row["alarm_permit_id"] = None
    row["suspension_order_id"] = None
    row["invoice_number"] = store.next_invoice_number()
    row["kind"] = kind
    row["line_items"] = lines
    row["subtotal_cents"] = subtotal
    row["admin_fee_cents"] = admin_fee
    row["assessed_cents"] = assessed
    row["paid_cents"] = 0
    row["adjusted_cents"] = 0
    row["outstanding_cents"] = assessed
    row["payment_status"] = "UNPAID"
    row["collections_stage"] = "CURRENT"
    row["issued_on"] = issued
    row["due_on"] = add_days(issued, int(sched.get("invoice_due_days") or 0))
    row["late_penalty_cents"] = 0
    row["days_delinquent"] = 0
    row["referral_total_cents"] = None
    row["referral_agency"] = None
    row["referred_on"] = None
    if link_field:
        row[link_field] = link_id
    store.penalty_invoices[row["id"]] = row
    return row


def recompute_outstanding(inv):
    # A voided invoice has left every rollup and dunning set (PRD 3.6/3.7):
    # `assessed_cents` is preserved for audit but `outstanding_cents` stays 0.
    if inv.get("payment_status") == "VOIDED":
        inv["outstanding_cents"] = 0
        return
    inv["outstanding_cents"] = max(
        0, inv["assessed_cents"] - inv["paid_cents"] - inv["adjusted_cents"])


def settle_check(inv):
    """Settlement is exactly paid + adjusted == assessed after the write."""
    if inv.get("payment_status") == "VOIDED":
        return
    total = inv["paid_cents"] + inv["adjusted_cents"]
    if total >= inv["assessed_cents"]:
        inv["payment_status"] = "PAID"
    elif total > 0:
        inv["payment_status"] = "PARTIALLY_PAID"
    else:
        inv["payment_status"] = "UNPAID"
    recompute_outstanding(inv)


def refresh_days_delinquent(inv):
    due = inv.get("due_on")
    if due is None:
        inv["days_delinquent"] = 0
    else:
        inv["days_delinquent"] = whole_days_between(now(), due)
    return inv["days_delinquent"]


def invoice_frozen_by_appeal(inv):
    """Dunning is frozen while the linked incident sits in APPEALED."""
    incident_id = inv.get("false_alarm_incident_id")
    if not incident_id:
        return False
    inc = store.false_alarm_incidents.get(incident_id)
    return bool(inc and inc.get("status") == "APPEALED")


def void_invoice_cascade(inv, site):
    """Compensating void: applied allocations reverse into the site credit."""
    if inv is None:
        return
    if inv.get("payment_status") == "VOIDED":
        return
    reversed_cents = 0
    for al in allocations_for_invoice(inv["id"]):
        if al.get("status") == "APPLIED":
            al["status"] = "REVERSED"
            reversed_cents += al.get("amount_cents") or 0
    if reversed_cents:
        site["credit_balance_cents"] = (site.get("credit_balance_cents") or 0) \
            + reversed_cents
        inv["paid_cents"] = max(0, inv["paid_cents"] - reversed_cents)
    inv["payment_status"] = "VOIDED"
    inv["outstanding_cents"] = 0
    touch(inv)


def reassess_invoice(inv, sched, lines, site):
    inv["line_items"] = lines
    inv["subtotal_cents"] = sum(l["extended_cents"] for l in lines)
    inv["admin_fee_cents"] = calc.admin_fee_for(sched, inv["subtotal_cents"])
    inv["assessed_cents"] = (inv["subtotal_cents"] + inv["admin_fee_cents"]
                             + (inv.get("late_penalty_cents") or 0))
    excess = inv["paid_cents"] - inv["assessed_cents"]
    if excess > 0:
        inv["paid_cents"] = inv["assessed_cents"]
        site["credit_balance_cents"] = (site.get("credit_balance_cents") or 0) + excess
    if inv["adjusted_cents"] > max(0, inv["assessed_cents"] - inv["paid_cents"]):
        inv["adjusted_cents"] = max(0, inv["assessed_cents"] - inv["paid_cents"])
    settle_check(inv)
    touch(inv)


# ---------------------------------------------------------------------------
# renumbering and re-pricing  (PRD 3.5 counting invariant)
# ---------------------------------------------------------------------------

def renumber_and_reprice(site):
    sched = governing_schedule(site)
    if sched is None:
        return
    items = sorted(chargeable_incidents(site["id"]), key=occurrence_key)
    for inc in items:
        new_index = occurrence_index_for(site, sched, inc)
        inc["occurrence_index"] = new_index
        inc["counted_window_mode"] = sched.get("counting_window_mode")
        assessed, basis, detail = price_incident(site, sched, inc)
        changed = (inc.get("assessed_fee_cents") != assessed
                   or inc.get("fee_basis") != basis)
        inc["assessed_fee_cents"] = assessed
        inc["fee_basis"] = basis
        if changed:
            touch(inc)
        inv = invoice_for_incident(inc["id"])
        if inv is not None:
            if assessed <= 0:
                void_invoice_cascade(inv, site)
            else:
                reassess_invoice(inv, sched, calc.false_alarm_lines(sched, detail),
                                 site)


# ---------------------------------------------------------------------------
# site_response_posture + site_balance_rollup  (PRD 3.5 / 3.9)
# ---------------------------------------------------------------------------

def recompute_chargeable_counts(site, sched):
    at = now()
    site["chargeable_count_rolling_365"] = count_chargeable_in_window(
        site["id"], "ROLLING_365", at)
    site["chargeable_count_permit_year"] = count_chargeable_in_window(
        site["id"], "PERMIT_YEAR", at)
    mode = sched.get("counting_window_mode") if sched else "ROLLING_365"
    site["chargeable_count_window"] = (
        site["chargeable_count_permit_year"] if mode == "PERMIT_YEAR"
        else site["chargeable_count_rolling_365"])


def derive_posture(site, sched):
    if sched is None:
        return "RESPONSE_ACTIVE"
    at = now()
    orders = site_orders(site["id"])
    for order in orders:
        if order.get("status") in LIVE_ORDER_STATUSES:
            frm = order.get("effective_from")
            thr = order.get("effective_through")
            if frm is not None and thr is not None and frm <= at <= thr:
                return "RESPONSE_SUSPENDED"
    for order in orders:
        if order.get("status") == "LIFTED":
            lifted = order.get("lifted_at")
            if lifted is None:
                continue
            if at <= add_days(lifted, int(order.get("probation_days") or 0)):
                return "RESPONSE_PROBATION"
    if site.get("chargeable_count_window", 0) >= int(
            sched.get("probation_threshold_count") or 0):
        return "RESPONSE_PROBATION"
    return "RESPONSE_ACTIVE"


def rollup_site(site, bump=True):
    """The pinned seven-step premises roll-up; step order is mandatory."""
    sched = governing_schedule(site)
    invoices = site_invoices(site["id"])
    # 1 — per invoice outstanding
    for inv in invoices:
        recompute_outstanding(inv)
    # 2 — outstanding balance
    site["outstanding_balance_cents"] = sum(
        inv["outstanding_cents"] for inv in invoices
        if inv.get("payment_status") in ("UNPAID", "PARTIALLY_PAID")
        and inv.get("collections_stage") != "WRITTEN_OFF")
    # 3 — lifetime assessed
    site["lifetime_assessed_cents"] = sum(
        inv["assessed_cents"] for inv in invoices
        if inv.get("payment_status") != "VOIDED")
    # 4 — derived counts
    site["ecv_callable_contact_count"] = len(live_callable_contacts(site["id"]))
    site["unpermitted_system_count"] = len(
        [s for s in site_systems(site["id"]) if s.get("status") == "UNPERMITTED"])
    site["lifted_suspension_count"] = len(
        [o for o in site_orders(site["id"]) if o.get("status") == "LIFTED"])
    recompute_chargeable_counts(site, sched)
    # 5 — renewal block flag (inclusive comparison)
    if sched is None:
        site["renewal_block_active"] = False
    else:
        site["renewal_block_active"] = (
            site["outstanding_balance_cents"]
            >= int(sched.get("delinquent_balance_block_cents") or 0))
    # 6 — permits follow the flag
    for permit in site_permits(site["id"]):
        if site["renewal_block_active"] and permit.get("status") == "RENEWAL_DUE":
            permit["status"] = "RENEWAL_BLOCKED"
            touch(permit)
        elif (not site["renewal_block_active"]
              and permit.get("status") == "RENEWAL_BLOCKED"):
            permit["status"] = "RENEWAL_DUE"
            touch(permit)
    # 7 — response posture
    site["response_status"] = derive_posture(site, sched)
    if bump:
        touch(site)
    return site


def _site_snapshot(site):
    keys = ("outstanding_balance_cents", "lifetime_assessed_cents",
            "ecv_callable_contact_count", "unpermitted_system_count",
            "lifted_suspension_count", "chargeable_count_window",
            "chargeable_count_rolling_365", "chargeable_count_permit_year",
            "renewal_block_active", "response_status", "credit_balance_cents")
    return tuple(site.get(k) for k in keys)


def rollup_site_conditional(site):
    """Roll the premises up, bumping version only when something moved."""
    before = _site_snapshot(site)
    rollup_site(site, bump=False)
    if before != _site_snapshot(site):
        touch(site)
        return True
    return False


# ---------------------------------------------------------------------------
# monitoring companies  (PRD 3.10)
# ---------------------------------------------------------------------------

def recompute_company_score(company):
    reports = [r for r in company_reports(company["id"])
               if r.get("status") in ("ACCEPTED", "VARIANCE_FLAGGED")]
    reports.sort(key=lambda r: (r.get("period_start"), order_key(r)))
    windowed = reports[-6:]
    company["reporting_compliance_score"] = calc.company_score(
        company.get("score_mode"),
        [(r.get("period_score") or 0, r.get("system_dispatch_count") or 0)
         for r in windowed])


def recompute_flagged_run(company):
    """PRD 3.10 registration: the most-recent unbroken VARIANCE_FLAGGED run."""
    ordered = sorted(company_reports(company["id"]),
                     key=lambda r: (r.get("period_start"), order_key(r)))
    run = 0
    for report in ordered:
        if report.get("status") == "VARIANCE_FLAGGED":
            run += 1
        else:
            run = 0
    company["consecutive_flagged_report_count"] = run
    return run


def rollup_company(company, bump=True):
    cid = company["id"]
    company["monitored_system_count"] = len(
        [s for s in store.alarm_systems.values()
         if s.get("monitoring_company_id") == cid
         and s.get("status") in ("SUBMITTED", "PERMITTED", "UNPERMITTED")])
    company["dispatch_request_count_lifetime"] = len(
        [r for r in store.dispatch_requests.values()
         if r.get("monitoring_company_id") == cid])
    # `consecutive_flagged_report_count` is NOT recomputed here: PRD 3.10 makes
    # it a stateful counter, incremented on FLAG_VARIANCE, reset on ACCEPT and on
    # the PROBATION -> ACTIVE hop.  Only registration derives it from the reports.
    recompute_company_score(company)
    if bump:
        touch(company)
    return company


def apply_company_status_from_score(company, reason):
    """Status consequences evaluated on each review (PRD 3.10)."""
    probation_threshold, suspension_threshold = company_thresholds()
    score = float(company.get("reporting_compliance_score") or 0)
    status = company.get("status")
    flagged = company.get("consecutive_flagged_report_count") or 0
    stamped = now()
    if status == "ACTIVE":
        if score < suspension_threshold:
            company["probation_started_at"] = stamped
            company["status"] = "SUSPENDED"
            company["status_reason"] = reason
            company["last_status_action_at"] = stamped
        elif score < probation_threshold:
            company["status"] = "PROBATION"
            company["probation_started_at"] = stamped
            company["status_reason"] = reason
            company["last_status_action_at"] = stamped
    elif status == "PROBATION":
        if score < suspension_threshold or flagged >= 3:
            company["status"] = "SUSPENDED"
            company["status_reason"] = reason
            company["last_status_action_at"] = stamped
        elif score >= probation_threshold:
            company["status"] = "ACTIVE"
            company["probation_started_at"] = None
            company["consecutive_flagged_report_count"] = 0
            company["status_reason"] = reason
            company["last_status_action_at"] = stamped


def reinstatement_earned(company):
    """Two consecutive accepted periods scoring at or above 0.70, after the anchor."""
    anchor = company.get("probation_started_at")
    ordered = sorted(company_reports(company["id"]),
                     key=lambda r: (r.get("period_start"), order_key(r)))
    eligible = [r for r in ordered if r.get("status") == "ACCEPTED"
                and r.get("period_end") is not None
                and (anchor is None or r.get("period_end") > anchor)]
    streak = 0
    for report in eligible:
        if float(report.get("period_score") or 0) >= 0.70:
            streak += 1
            if streak >= 2:
                return True
        else:
            streak = 0
    return False


def report_system_dispatch_count(company_id, period_start, period_end):
    total = 0
    for req in store.dispatch_requests.values():
        if req.get("monitoring_company_id") != company_id:
            continue
        if req.get("status") == "CANCELLED":
            continue
        occurred = req.get("occurred_at")
        if occurred is None:
            continue
        if period_start <= occurred <= period_end:
            total += 1
    return total


def recompute_report_metrics(report):
    count = report_system_dispatch_count(report["monitoring_company_id"],
                                        report["period_start"],
                                        report["period_end"])
    report["system_dispatch_count"] = count
    metrics = calc.period_metrics(report["reported_dispatch_count"],
                                 report["ecv_attempt_count"], count)
    report.update(metrics)
    return report


# ---------------------------------------------------------------------------
# permits, cascades
# ---------------------------------------------------------------------------

def set_permit_term(permit, sched, start_at):
    permit["term_start_at"] = start_at
    permit["term_end_at"] = add_days(start_at, int(sched.get("permit_term_days") or 0))
    permit["grace_through_at"] = add_days(
        permit["term_end_at"], int(sched.get("renewal_grace_days") or 0))


def pin_site_schedule(site, sched):
    if not site.get("governing_fee_schedule_id"):
        site["governing_fee_schedule_id"] = sched["id"]


def unpermitted_cascade(permit, site):
    """Hops two and three of PRD 3.3: system falls, penalty issues, block flips."""
    system = store.alarm_systems.get(permit.get("alarm_system_id"))
    if system is not None and system.get("status") == "PERMITTED":
        system["status"] = "UNPERMITTED"
        system["unpermitted_since"] = now()
        touch(system)
    sched = governing_schedule(site)
    if sched is not None:
        new_invoice(site, sched, "UNPERMITTED_OPERATION_PENALTY",
                    calc.unpermitted_penalty_lines(sched),
                    "alarm_permit_id", permit["id"])


def auto_propose_suspension(site, sched, incident):
    """Auto-proposal when the window count reaches the suspension threshold."""
    threshold = int(sched.get("suspension_threshold_count") or 0)
    if site.get("chargeable_count_window", 0) < threshold:
        return None
    effective_from = add_days(now(), 10)
    effective_through = add_days(effective_from, 30)
    for order in site_orders(site["id"]):
        if order.get("status") not in ("PROPOSED",) + LIVE_ORDER_STATUSES:
            continue
        if calc.suspension_periods_conflict(effective_from, effective_through,
                                            order.get("effective_from"),
                                            order.get("effective_through")):
            return None
    row = base_row()
    row["alarm_site_id"] = site["id"]
    row["triggering_incident_id"] = incident["id"]
    row["basis"] = "EXCESSIVE_FALSE_ALARMS"
    row["status"] = "PROPOSED"
    row["effective_from"] = effective_from
    row["effective_through"] = effective_through
    row["suspension_sequence"] = (site.get("lifted_suspension_count") or 0) + 1
    row["reinstatement_fee_cents"] = None
    row["probation_days"] = None
    row["required_conditions"] = None
    row["served_at"] = None
    row["reinstatement_requested_at"] = None
    row["technician_inspection_date"] = None
    row["ecv_attestation"] = None
    row["lifted_at"] = None
    row["vacated_reason"] = None
    store.suspension_orders[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# delinquency / dunning
# ---------------------------------------------------------------------------

def apply_late_penalty(inv, sched):
    """Step 1 and 2 of the delinquency arithmetic; at most once per invoice."""
    if inv.get("_late_penalty_applied"):
        return
    principal = inv["assessed_cents"] - inv["paid_cents"] - inv["adjusted_cents"]
    if principal <= 0:
        return
    penalty = calc.rhu(calc.D(principal) * calc.D(sched.get("late_penalty_pct")))
    inv["late_penalty_cents"] = penalty
    inv["assessed_cents"] = inv["assessed_cents"] + penalty
    inv["_late_penalty_applied"] = True
    recompute_outstanding(inv)


def compute_referral_total(inv):
    """Steps 3 to 5: interim total after the penalty, then the collections charge."""
    interim = inv["assessed_cents"] - inv["paid_cents"] - inv["adjusted_cents"]
    if interim < 0:
        interim = 0
    return calc.referral_total(interim)


# ---------------------------------------------------------------------------
# nightly program run  (PRD 2.6)
# ---------------------------------------------------------------------------

def nightly_run():
    at = now()
    summary = {"permits_advanced": 0, "invoices_escalated": 0,
               "orders_expired": 0, "appeals_dismissed": 0}

    # --- permits -----------------------------------------------------------
    for permit in sorted(store.alarm_permits.values(), key=order_key):
        site = store.alarm_sites.get(permit.get("alarm_site_id"))
        if site is None:
            continue
        status = permit.get("status")
        term_end = permit.get("term_end_at")
        grace_through = permit.get("grace_through_at")
        if status == "ACTIVE" and term_end is not None \
                and at >= term_end - timedelta(days=30):
            permit["status"] = "RENEWAL_DUE"
            touch(permit)
            status = "RENEWAL_DUE"
            summary["permits_advanced"] += 1
        if status in ("RENEWAL_DUE", "RENEWAL_BLOCKED") and term_end is not None \
                and at > term_end:
            permit["status"] = "GRACE"
            touch(permit)
            status = "GRACE"
            summary["permits_advanced"] += 1
        if status == "GRACE" and grace_through is not None and at > grace_through:
            permit["status"] = "EXPIRED"
            touch(permit)
            summary["permits_advanced"] += 1
            unpermitted_cascade(permit, site)

    # --- invoices ----------------------------------------------------------
    for inv in sorted(store.penalty_invoices.values(), key=order_key):
        site = store.alarm_sites.get(inv.get("alarm_site_id"))
        if site is None:
            continue
        recompute_outstanding(inv)
        refresh_days_delinquent(inv)
        stage = inv.get("collections_stage")
        if stage == "WRITTEN_OFF" or inv.get("payment_status") == "VOIDED":
            continue
        if inv["outstanding_cents"] <= 0:
            if stage in ("NOTICE", "FINAL_NOTICE"):
                inv["collections_stage"] = "CURRENT"
                touch(inv)
            continue
        if invoice_frozen_by_appeal(inv):
            continue
        sched = governing_schedule(site)
        if sched is None:
            continue
        if stage == "CURRENT" and inv["days_delinquent"] >= 1:
            apply_late_penalty(inv, sched)
            inv["collections_stage"] = "NOTICE"
            touch(inv)
            summary["invoices_escalated"] += 1
        elif stage == "NOTICE" and inv["days_delinquent"] >= 30:
            inv["collections_stage"] = "FINAL_NOTICE"
            touch(inv)
            summary["invoices_escalated"] += 1

    # --- suspension orders -------------------------------------------------
    for order in sorted(store.suspension_orders.values(), key=order_key):
        if order.get("status") != "EFFECTIVE":
            continue
        through = order.get("effective_through")
        if through is not None and at > through:
            order["status"] = "EXPIRED"
            touch(order)
            summary["orders_expired"] += 1

    # --- appeals -----------------------------------------------------------
    for appeal in sorted(store.appeals.values(), key=order_key):
        if appeal.get("status") != "FILED":
            continue
        if appeal.get("hearing_docket_id"):
            continue
        filed = appeal.get("filed_at")
        if filed is None:
            continue
        if whole_days_between(at, filed) > 60:
            appeal["status"] = "DISMISSED_UNTIMELY"
            touch(appeal)
            summary["appeals_dismissed"] += 1
            inc = store.false_alarm_incidents.get(
                appeal.get("false_alarm_incident_id"))
            if inc is not None and inc.get("status") == "APPEALED":
                inc["status"] = "COUNTED"
                touch(inc)

    # --- premises roll-up --------------------------------------------------
    for site in sorted(store.alarm_sites.values(), key=order_key):
        rollup_site_conditional(site)
    for company in sorted(store.alarm_companies.values(), key=order_key):
        before = (company.get("monitored_system_count"),
                  company.get("dispatch_request_count_lifetime"),
                  company.get("consecutive_flagged_report_count"),
                  company.get("reporting_compliance_score"))
        rollup_company(company, bump=False)
        after = (company.get("monitored_system_count"),
                 company.get("dispatch_request_count_lifetime"),
                 company.get("consecutive_flagged_report_count"),
                 company.get("reporting_compliance_score"))
        if before != after:
            touch(company)
    return summary
