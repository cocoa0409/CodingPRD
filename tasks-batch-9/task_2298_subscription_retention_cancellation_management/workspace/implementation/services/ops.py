"""Domain operations: pricing, invoicing, modification application, the renewal
run, dunning, cascades, save-offer selection and win-back suppression."""
from decimal import Decimal

import constants as K
from db import store, base_record, touch, ordered, days, hours
from errors import fail
from services import calc

ONE = Decimal("1")


# --------------------------------------------------------------------------
# Pricing (PRD §2.8, §3.3, §3.4)
# --------------------------------------------------------------------------
def cycle_days(sub):
    return sub["frequency_weeks"] * 7


def plan_of(sub):
    return store.plans[sub["plan_id"]]


def committed_price(plan, addons, discount_pct):
    mult = ONE - Decimal(discount_pct)
    total = calc.cents(Decimal(plan["monthly_price_cents"]) * plan["shipments_per_cycle"] * mult)
    for addon in addons:
        total += calc.cents(Decimal(addon["unit_price_cents"]) * addon["qty"] * mult)
    return total


def recompute_committed(sub):
    sub["committed_price_cents"] = committed_price(plan_of(sub), sub["addons"],
                                                   sub["active_discount_pct"])
    return sub["committed_price_cents"]


def effective_discount(sub):
    if sub["discount_remaining_cycles"] > 0:
        return Decimal(sub["active_discount_pct"])
    return Decimal("0.0000")


def build_amounts(plan, addons, discount_pct, proration):
    """Returns (amount_cents, cogs_cents, line_items) with the pinned rounding
    order: each line rounded to whole cents first, then summed."""
    mult = ONE - Decimal(discount_pct)
    prorate = Decimal(proration)
    plan_line = calc.cents(Decimal(plan["monthly_price_cents"]) * plan["shipments_per_cycle"]
                           * mult * prorate)
    lines = [{
        "kind": "PLAN",
        "code": plan["code"],
        "unit_price_cents": plan["monthly_price_cents"],
        "qty": plan["shipments_per_cycle"],
        "line_cents": plan_line,
    }]
    amount = plan_line
    cogs = calc.cents(Decimal(plan["unit_cogs_cents"]) * plan["shipments_per_cycle"] * prorate)
    for addon in sorted(addons, key=lambda a: a["code"]):
        line = calc.cents(Decimal(addon["unit_price_cents"]) * addon["qty"] * mult * prorate)
        amount += line
        cogs += calc.cents(Decimal(addon["unit_cogs_cents"]) * addon["qty"] * prorate)
        lines.append({
            "kind": "ADDON",
            "code": addon["code"],
            "unit_price_cents": addon["unit_price_cents"],
            "qty": addon["qty"],
            "line_cents": line,
        })
    return amount, cogs, lines


def issue_invoice(sub, cycle_index, is_renewal):
    """FULL_CYCLE variant: proration_factor is exactly 1.0000."""
    plan = plan_of(sub)
    amount, cogs, lines = build_amounts(plan, sub["addons"], effective_discount(sub), ONE)
    inv = base_record()
    inv.update({
        "subscription_id": sub["id"],
        "payment_method_id": sub["payment_method_id"],
        "cycle_index": cycle_index,
        "amount_cents": amount,
        "cogs_cents": cogs,
        "line_items": lines,
        "status": "OPEN",
        "due_at": store.now(),
        "paid_at": None,
        "attempt_count": 0,
        "proration_factor": Decimal("1.0000"),
        "is_renewal": is_renewal,
    })
    store.invoices[inv["id"]] = inv
    return inv


def open_invoice_of(sub):
    rows = [i for i in calc.invoices_of_subscription(sub["id"]) if i["status"] == "OPEN"]
    return rows[-1] if rows else None


def reprice_open_invoice(sub):
    """MID_CYCLE_REPRICE variant: lines rebuilt from the (new) current plan."""
    inv = open_invoice_of(sub)
    if inv is None:
        return None
    plan = plan_of(sub)
    remaining = calc.floor_days(sub["next_renewal_at"] - store.now())
    factor = calc.ratio4(remaining, cycle_days(sub))
    amount, cogs, lines = build_amounts(plan, sub["addons"], effective_discount(sub), factor)
    inv["amount_cents"] = amount
    inv["cogs_cents"] = cogs
    inv["line_items"] = lines
    inv["proration_factor"] = factor
    touch(inv)
    return inv


def latest_invoice(sub):
    rows = calc.invoices_of_subscription(sub["id"])
    return rows[-1] if rows else None


def upcoming_cycle_index(sub):
    """cycle_index of the renewal that is next to be issued."""
    rows = calc.invoices_of_subscription(sub["id"])
    if not rows:
        return 0
    return max(i["cycle_index"] for i in rows) + 1


# --------------------------------------------------------------------------
# Compliance notices (PRD §2.11)
# --------------------------------------------------------------------------
def create_notice(sub, notice_type, state, scheduled_for, cycle_index,
                  sent_at=None, channel="EMAIL", body_ref=None):
    rec = base_record()
    rec.update({
        "subscription_id": sub["id"],
        "notice_type": notice_type,
        "state": state,
        "scheduled_for": scheduled_for,
        "sent_at": sent_at,
        "channel": channel,
        "renewal_cycle_index": cycle_index,
        "body_ref": body_ref,
    })
    store.compliance_notices[rec["id"]] = rec
    return rec


def reminder_window(sub, plan):
    """Closed interval [next_renewal_at - lead, next_renewal_at - 3d]."""
    end = sub["next_renewal_at"]
    if end is None:
        return None, None
    return (end - days(plan["renewal_reminder_days_before"]),
            end - days(K.MIN_REMINDER_LEAD_DAYS))


def schedule_renewal_reminder(sub, plan, cycle_index):
    scheduled_for = sub["next_renewal_at"] - days(plan["renewal_reminder_days_before"])
    return create_notice(sub, "RENEWAL_REMINDER", "SCHEDULED", scheduled_for, cycle_index)


# --------------------------------------------------------------------------
# Modification application (PRD §3.3)
# --------------------------------------------------------------------------
SNAPSHOT_FIELDS = ("plan_id", "frequency_weeks", "addons", "active_discount_pct",
                   "discount_remaining_cycles", "committed_price_cents",
                   "term_shipments_skipped")


def snapshot_of(sub):
    import copy
    return {f: copy.deepcopy(sub[f]) for f in SNAPSHOT_FIELDS}


def restore_snapshot(sub, snap):
    import copy
    for f in SNAPSHOT_FIELDS:
        if f in snap:
            sub[f] = copy.deepcopy(snap[f])


def pause_span_cycles(start_at, end_at, cdays):
    if start_at is None or end_at is None:
        return 0
    return max(0, calc.ceil_days_ratio(end_at - start_at, cdays))


def catalog_entry(plan, code):
    for entry in plan.get("addon_catalog") or []:
        if entry["code"] == code:
            return entry
    return None


def apply_modification(mod, sub):
    """Applies mod to sub, sets prior_snapshot / delta_price_cents / applied_at."""
    before = sub["committed_price_cents"]
    mod["prior_snapshot"] = snapshot_of(sub)
    mod_type = mod["mod_type"]
    now = store.now()

    if mod_type == "FREQUENCY_CHANGE":
        if mod.get("frequency_weeks"):
            sub["frequency_weeks"] = mod["frequency_weeks"]
    elif mod_type == "ADDON_ADD":
        entry = catalog_entry(plan_of(sub), mod.get("addon_code"))
        if entry is not None:
            qty = mod.get("addon_qty") or 1
            sub["addons"] = list(sub["addons"]) + [{
                "code": entry["code"],
                "qty": qty,
                "unit_price_cents": entry["unit_price_cents"],
                "unit_cogs_cents": entry["unit_cogs_cents"],
            }]
    elif mod_type == "ADDON_REMOVE":
        sub["addons"] = [a for a in sub["addons"] if a["code"] != mod.get("addon_code")]
    elif mod_type == "SKIP_SHIPMENT":
        sub["term_shipments_skipped"] += 1
    elif mod_type == "PLAN_DOWNGRADE":
        target = store.plans[mod["target_plan_id"]]
        sub["plan_id"] = target["id"]
        allowed = {e["code"] for e in (target.get("addon_catalog") or [])}
        sub["addons"] = [a for a in sub["addons"] if a["code"] in allowed]
    elif mod_type == "PAUSE":
        sub["lifecycle_state"] = "PAUSED"
        sub["paused_until"] = mod["pause_end_at"]
        sub["next_renewal_at"] = mod["pause_end_at"]
        sub["pause_cycles_used"] += pause_span_cycles(mod["pause_start_at"],
                                                      mod["pause_end_at"], cycle_days(sub))
    elif mod_type == "RESUME":
        sub["lifecycle_state"] = "ACTIVE"
        sub["paused_until"] = None
        sub["next_renewal_at"] = now
    elif mod_type == "DISCOUNT_APPLY":
        if mod.get("_discount_pct") is not None:
            sub["active_discount_pct"] = mod["_discount_pct"]
        if mod.get("_discount_cycles") is not None:
            sub["discount_remaining_cycles"] = mod["_discount_cycles"]

    recompute_committed(sub)
    mod["state"] = "APPLIED"
    mod["applied_at"] = now
    mod["delta_price_cents"] = sub["committed_price_cents"] - before

    if mod_type == "PLAN_DOWNGRADE":
        if open_invoice_of(sub) is not None:
            reprice_open_invoice(sub)
        create_notice(sub, "PRICE_CHANGE", "SCHEDULED",
                      now + days(K.PRICE_CHANGE_NOTICE_LEAD_DAYS),
                      upcoming_cycle_index(sub))
    return mod


def new_modification(sub, mod_type, effective_at, **fields):
    mod = base_record()
    mod.update({
        "subscription_id": sub["id"],
        "save_offer_grant_id": None,
        "reverses_modification_id": None,
        "target_plan_id": None,
        "mod_type": mod_type,
        "state": "REQUESTED",
        "frequency_weeks": None,
        "addon_code": None,
        "addon_qty": None,
        "skip_ship_at": None,
        "pause_start_at": None,
        "pause_end_at": None,
        "effective_at": effective_at,
        "delta_price_cents": 0,
        "prior_snapshot": None,
        "applied_at": None,
    })
    mod.update(fields)
    store.subscription_modifications[mod["id"]] = mod
    return mod


# --------------------------------------------------------------------------
# Cascades (PRD §3.5, §3.7)
# --------------------------------------------------------------------------
def expire_presented_grants(session):
    for grant in calc.grants_of_session(session["id"]):
        if grant["state"] == "PRESENTED":
            grant["state"] = "EXPIRED"
            touch(grant)


def abandon_session(session):
    session["state"] = "ABANDONED"
    session["completed_at"] = store.now()
    touch(session)
    expire_presented_grants(session)


def abandon_sessions(sub, stale_only=False):
    for session in calc.sessions_of_subscription(sub["id"]):
        if session["state"] in K.SESSION_TERMINAL:
            continue
        if stale_only and (store.now() - session["started_at"]) <= hours(K.SESSION_TTL_HOURS):
            continue
        abandon_session(session)


def mark_lapsed(subscriber):
    """lapsed_at is the instant the subscriber's last non-cancelled subscription
    reached CANCELLED."""
    remaining = [s for s in calc.subscriptions_of(subscriber["id"])
                 if s["lifecycle_state"] != "CANCELLED"]
    if not remaining:
        subscriber["lapsed_at"] = store.now()


def write_off_cascade(invoice, sub):
    invoice["status"] = "WRITTEN_OFF"
    touch(invoice)
    sub["billing_state"] = "DELINQUENT"
    if sub["lifecycle_state"] in ("ACTIVE", "PAUSED"):
        sub["lifecycle_state"] = "CANCELLED"
        sub["cancel_effective_at"] = store.now()
        subscriber = store.subscribers[sub["subscriber_id"]]
        subscriber["churn_type"] = "INVOLUNTARY"
        mark_lapsed(subscriber)
        subscriber["winback_suppressed_until"] = store.now() + days(K.INVOLUNTARY_SUPPRESSION_DAYS)
        subscriber["_suppression_grant_id"] = None
        touch(subscriber)
    touch(sub)
    abandon_sessions(sub)


# --------------------------------------------------------------------------
# The renewal run (PRD §3.4)
# --------------------------------------------------------------------------
def renewal_run(sub):
    now = store.now()
    if sub["next_renewal_at"] is None or now < sub["next_renewal_at"]:
        fail("ERR_RENEWAL_NOT_DUE", "The renewal cycle is not yet due.")

    finalising = False
    # -- step 1: finalise a due cancellation
    if sub["lifecycle_state"] == "PENDING_CANCEL" and sub["cancel_effective_at"] is not None \
            and now >= sub["cancel_effective_at"]:
        sub["lifecycle_state"] = "CANCELLED"
        subscriber = store.subscribers[sub["subscriber_id"]]
        subscriber["churn_type"] = "VOLUNTARY"
        mark_lapsed(subscriber)
        touch(subscriber)
        finalising = True

    # -- step 2: auto-resume a lapsed pause
    if sub["lifecycle_state"] == "PAUSED" and sub["paused_until"] is not None \
            and now >= sub["paused_until"]:
        sub["lifecycle_state"] = "ACTIVE"
        sub["paused_until"] = None

    # -- step 3: sweep stale cancellation conversations
    abandon_sessions(sub, stale_only=True)

    # -- step 4: apply deferred change
    due = [m for m in calc.mods_of_subscription(sub["id"])
           if m["state"] == "SCHEDULED" and m["effective_at"] is not None
           and now >= m["effective_at"]]
    for mod in due:
        apply_modification(mod, sub)
        touch(mod)
    if due:
        recompute_committed(sub)

    if finalising:
        touch(sub)
        return sub

    plan = plan_of(sub)

    # -- step 5: the negative-option gate
    cycle_index = upcoming_cycle_index(sub)
    if plan["is_negative_option"]:
        opens, closes = reminder_window(sub, plan)
        found = False
        for notice in calc.notices_of_subscription(sub["id"]):
            if (notice["notice_type"] == "RENEWAL_REMINDER" and notice["state"] == "SENT"
                    and notice["renewal_cycle_index"] == cycle_index
                    and notice["sent_at"] is not None
                    and opens <= notice["sent_at"] <= closes):
                found = True
                break
        if not found:
            fail("ERR_RENEWAL_REMINDER_MISSING",
                 "No SENT renewal reminder inside the statutory window for this cycle.")

    # -- step 6: record the compliance gap
    for notice in calc.notices_of_subscription(sub["id"]):
        if notice["state"] == "SCHEDULED" and notice["scheduled_for"] is not None \
                and notice["scheduled_for"] < now:
            notice["state"] = "MISSED"
            touch(notice)

    # -- step 7: bill the cycle
    cdays = days(cycle_days(sub))
    skipping = any(m["state"] == "APPLIED" and m["mod_type"] == "SKIP_SHIPMENT"
                   and m.get("skip_ship_at") is not None
                   and m["skip_ship_at"] == sub["next_ship_at"]
                   for m in calc.mods_of_subscription(sub["id"]))
    if skipping:
        sub["next_renewal_at"] = sub["next_renewal_at"] + cdays
        sub["next_ship_at"] = sub["next_ship_at"] + cdays
        touch(sub)
        return sub

    pm = store.payment_methods.get(sub["payment_method_id"])
    if pm is None or pm["status"] != "ACTIVE":
        fail("ERR_PAYMENT_METHOD_INACTIVE",
             "The subscription's payment method is no longer chargeable.")

    issue_invoice(sub, cycle_index, True)
    sub["term_shipments_delivered"] += 1
    if sub["discount_remaining_cycles"] > 0:
        sub["discount_remaining_cycles"] -= 1
    sub["next_renewal_at"] = sub["next_renewal_at"] + cdays
    sub["next_ship_at"] = sub["next_ship_at"] + cdays
    if plan["is_negative_option"]:
        schedule_renewal_reminder(sub, plan, cycle_index + 1)
    touch(sub)
    return sub


# --------------------------------------------------------------------------
# Dunning (PRD §3.7)
# --------------------------------------------------------------------------
def base_grace_days(sub):
    subscriber = store.subscribers[sub["subscriber_id"]]
    anchor = sub.get("first_failed_at") or store.now()
    bucket = calc.tenure_bucket_at(subscriber, anchor)
    return K.BASE_GRACE_DAYS_BY_TENURE[bucket]


def schedule_dunning_attempt(invoice):
    sub = store.subscriptions[invoice["subscription_id"]]
    attempts = calc.attempts_of_invoice(invoice["id"])
    previous = attempts[-1] if attempts else None
    attempt_number = invoice["attempt_count"] + 1
    now = store.now()

    if attempt_number == 1:
        scheduled_at = now
        backoff = 0
        clamped = False
    else:
        # steps 1-3: recompute the grace window
        if sub.get("first_failed_at") is not None:
            allowance = base_grace_days(sub)
            pm = store.payment_methods.get(invoice["payment_method_id"])
            extended = pm is not None and pm["updater_status"] == "PENDING"
            if extended:
                allowance += K.CARD_UPDATER_EXTENSION_DAYS
            sub["grace_end_at"] = sub["first_failed_at"] + days(allowance)
            if extended and sub["billing_state"] == "PAST_DUE":
                sub["billing_state"] = "GRACE"
            touch(sub)
            if now > sub["grace_end_at"]:
                fail("ERR_GRACE_PERIOD_ENDED", "The collections grace window has closed.")
        if attempt_number > K.MAX_RETRY_ATTEMPTS:
            fail("ERR_DUNNING_ATTEMPTS_EXHAUSTED", "The retry ceiling has been reached.")
        # step 4: the raw schedule instant
        code = previous.get("decline_code") if previous else None
        table = K.BACKOFF_DAYS_BY_DECLINE.get(code)
        if table is None:
            backoff = 0
        else:
            index = min(max(previous["attempt_number"], 1), len(table)) - 1
            backoff = table[index]
        anchor = previous.get("attempted_at") if previous else None
        raw = (anchor or now) + days(backoff)
        # steps 5-6: clamp to the grace window
        grace_end = sub.get("grace_end_at")
        if grace_end is not None and raw > grace_end:
            scheduled_at = grace_end
            clamped = True
        else:
            scheduled_at = raw
            clamped = False

    if attempt_number > K.MAX_RETRY_ATTEMPTS:
        fail("ERR_DUNNING_ATTEMPTS_EXHAUSTED", "The retry ceiling has been reached.")

    rec = base_record(versioned=False)
    rec.update({
        "invoice_id": invoice["id"],
        "previous_attempt_id": previous["id"] if previous else None,
        "attempt_number": attempt_number,
        "scheduled_at": scheduled_at,
        "attempted_at": None,
        "outcome": "PENDING",
        "decline_code": None,
        "backoff_days_applied": backoff,
        "grace_clamped": clamped,
        "is_final": clamped,
    })
    store.dunning_attempts[rec["id"]] = rec
    invoice["attempt_count"] += 1
    touch(invoice)
    return rec


def settle_payment(invoice, outcome, decline_code):
    pending = None
    for attempt in calc.attempts_of_invoice(invoice["id"]):
        if attempt["outcome"] == "PENDING":
            pending = attempt
            break
    if pending is None:
        fail("ERR_NO_PENDING_ATTEMPT", "No pending charge attempt exists on this invoice.")

    sub = store.subscriptions[invoice["subscription_id"]]
    subscriber = store.subscribers[sub["subscriber_id"]]
    now = store.now()
    pending["outcome"] = outcome
    pending["decline_code"] = decline_code if outcome in ("SOFT_DECLINE", "HARD_DECLINE") else None
    pending["attempted_at"] = now

    if pending["decline_code"] == "EXPIRED_CARD":
        pm = store.payment_methods.get(invoice["payment_method_id"])
        if pm is not None:
            pm["updater_status"] = "PENDING"
            pm["updater_requested_at"] = now
            touch(pm)

    if outcome == "SUCCEEDED":
        invoice["status"] = "PAID"
        invoice["paid_at"] = now
        touch(invoice)
        if sub["billing_state"] in ("PAST_DUE", "GRACE"):
            sub["billing_state"] = "CURRENT"
        sub["first_failed_at"] = None
        sub["grace_end_at"] = None
        sub["consecutive_failed_attempts"] = 0
        touch(sub)
        touch(subscriber)
    elif outcome == "SOFT_DECLINE" and not pending["is_final"]:
        invoice["status"] = "FAILED"
        touch(invoice)
        if sub["billing_state"] == "CURRENT":
            sub["billing_state"] = "PAST_DUE"
        sub["consecutive_failed_attempts"] += 1
        if sub["first_failed_at"] is None:
            sub["first_failed_at"] = now
        sub["grace_end_at"] = sub["first_failed_at"] + days(base_grace_days(sub))
        touch(sub)
    else:
        sub["consecutive_failed_attempts"] += 1
        write_off_cascade(invoice, sub)
    return pending


# --------------------------------------------------------------------------
# Save-offer selection (PRD §3.6)
# --------------------------------------------------------------------------
def template_margins(template, plan):
    target = None
    if template["offer_type"] == "PLAN_DOWNGRADE" and plan.get("downgrade_target_plan_id"):
        target = store.plans.get(plan["downgrade_target_plan_id"])
    return calc.offer_margins(plan, template, target)


def grants_of_template_365d(subscriber_id, template_id):
    cutoff = store.now() - days(K.GRANT_WINDOW_DAYS)
    count = 0
    for grant in calc.grants_of_subscriber(subscriber_id):
        if (grant["save_offer_template_id"] == template_id
                and grant["state"] in ("PRESENTED", "ACCEPTED")
                and grant["created_at"] >= cutoff):
            count += 1
    return count


def select_offer(session, sub, subscriber):
    plan = plan_of(sub)
    reason = session["reason_code"]
    tenure = calc.tenure_days_now(subscriber)
    remaining = (plan["shipments_per_term"] - sub["term_shipments_delivered"]
                 - sub["term_shipments_skipped"])

    matches = [t for t in ordered(list(store.save_offer_templates.values()))
               if t["status"] == "ACTIVE" and reason in (t["eligible_reason_codes"] or [])]
    candidates = []
    tenure_excluded = 0
    for template in matches:
        if tenure < template["min_tenure_days"]:
            tenure_excluded += 1
            continue
        kind = template["offer_type"]
        if kind == "PAUSE" and sub["lifecycle_state"] != "ACTIVE":
            continue
        if kind == "SKIP" and remaining <= 0:
            continue
        if kind == "PLAN_DOWNGRADE" and not plan.get("downgrade_target_plan_id"):
            continue
        candidates.append(template)

    if not candidates:
        if matches and tenure_excluded == len(matches):
            fail("ERR_TENURE_REQUIREMENT_NOT_MET",
                 "The subscriber's tenure is below every eligible template's minimum.")
        fail("ERR_NO_ELIGIBLE_SAVE_OFFER", "No save-offer template is eligible for this session.")

    scored = [(t, template_margins(t, plan)) for t in candidates]
    scored.sort(key=lambda row: (row[0]["priority_rank"],
                                 -row[1]["blended_term_margin_pct"],
                                 row[0]["created_at"], row[0]["_seq"]))
    template, margins = scored[0]

    used = grants_of_template_365d(subscriber["id"], template["id"])
    if used >= template["max_per_subscriber_per_365d"]:
        fail("ERR_OFFER_QUOTA_EXCEEDED",
             "The subscriber has exhausted this offer's 365-day quota.")
    return template, margins


def accept_offer_modification(grant, template, sub):
    """Creates the APPLIED modification implementing the accepted offer."""
    now = store.now()
    kind = template["offer_type"]
    fields = {"save_offer_grant_id": grant["id"]}
    if kind == "DISCOUNT":
        mod_type = "DISCOUNT_APPLY"
    elif kind == "PAUSE":
        mod_type = "PAUSE"
        cycles = max(1, template["pause_cycles"])
        fields["pause_start_at"] = now
        fields["pause_end_at"] = now + days(cycles * cycle_days(sub))
    elif kind == "SKIP":
        mod_type = "SKIP_SHIPMENT"
        fields["skip_ship_at"] = sub["next_ship_at"]
    else:
        mod_type = "PLAN_DOWNGRADE"
        fields["target_plan_id"] = plan_of(sub)["downgrade_target_plan_id"]

    mod = new_modification(sub, mod_type, now, **fields)
    if kind == "DISCOUNT":
        mod["_discount_pct"] = template["discount_pct"]
        mod["_discount_cycles"] = template["discount_cycles"]
    apply_modification(mod, sub)
    touch(mod)
    return mod


# --------------------------------------------------------------------------
# Win-back (PRD §3.8)
# --------------------------------------------------------------------------
def suppression_reason(subscriber):
    """First matching predicate in the pinned order, or NONE."""
    now = store.now()
    if subscriber.get("do_not_contact"):
        return "DO_NOT_CONTACT"
    subs = calc.subscriptions_of(subscriber["id"])
    if any(s["lifecycle_state"] in ("ACTIVE", "PAUSED", "PENDING_CANCEL") for s in subs):
        return "ACTIVE_SUBSCRIPTION"
    if subscriber.get("churn_type") == "INVOLUNTARY" and subs:
        newest = subs[-1]
        pm = store.payment_methods.get(newest["payment_method_id"])
        if pm is None or pm["status"] != "ACTIVE" or pm["updater_status"] in ("PENDING", "UNAVAILABLE"):
            return "INVOLUNTARY_UNRESOLVED"
    cutoff = now - days(K.RECENT_SAVE_OFFER_DAYS)
    for grant in calc.grants_of_subscriber(subscriber["id"]):
        if grant["state"] == "ACCEPTED" and grant.get("accepted_at") is not None \
                and grant["accepted_at"] >= cutoff:
            return "RECENT_SAVE_OFFER"
    contacted = calc.last_contacted_at(subscriber)
    if contacted is not None and contacted > now - days(K.CONTACT_CAP_WINDOW_DAYS):
        return "CONTACT_CAP"
    return "NONE"


def contacts_in_window(subscriber_id):
    now = store.now()
    opens = now - days(K.CONTACT_CAP_WINDOW_DAYS)
    count = 0
    for target in calc.targets_of_subscriber(subscriber_id):
        sent = target.get("sent_at")
        if sent is not None and opens <= sent <= now:
            count += 1
    return count


def maybe_close_campaign(campaign):
    targets = calc.targets_of_campaign(campaign["id"])
    if campaign["state"] != "LAUNCHED" or not targets:
        return
    if all(t["state"] in ("CONVERTED", "EXPIRED", "SUPPRESSED") for t in targets):
        campaign["state"] = "CLOSED"
        touch(campaign)
