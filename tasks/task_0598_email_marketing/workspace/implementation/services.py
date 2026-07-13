"""Domain services: derived-field recomputation, cascades, state machines,
the operations epoch and the telemetry event handler."""
from datetime import timedelta

import calc
from errors import ApiError
from store import (base_fields, db, days_between, mutate, new_id, new_token, now)


# ==========================================================================
# Lookup helpers
# ==========================================================================
def account_of_audience(aud):
    return db.accounts[aud["account_id"]]


def audience_of_subscriber(sub):
    return db.audiences[sub["audience_id"]]


def account_of_subscriber(sub):
    return db.accounts[audience_of_subscriber(sub)["account_id"]]


def account_id_of_send(send):
    sub = db.subscribers[send["subscriber_id"]]
    return db.audiences[sub["audience_id"]]["account_id"]


def sends_of_account(account_id):
    return [s for s in db.sends.values() if account_id_of_send(s) == account_id]


def sends_of_subscriber(subscriber_id):
    return [s for s in db.sends.values() if s["subscriber_id"] == subscriber_id]


def sends_of_campaign(campaign_id):
    return [s for s in db.sends.values() if s["campaign_id"] == campaign_id]


def suppression_for(account_id, email):
    for e in db.suppressions.values():
        if e["account_id"] == account_id and e["email"] == email:
            return e
    return None


def add_suppression(account_id, email, reason):
    """At most one row per (account_id, email); a duplicate is never written."""
    if suppression_for(account_id, email) is not None:
        return None
    entry = {"id": new_id(), "created_at": now(), "account_id": account_id,
             "email": email, "reason": reason}
    db.suppressions[entry["id"]] = entry
    return entry


# ==========================================================================
# Derived-field recomputation (PRD 2.4: recomputation is a mutation)
# ==========================================================================
def sync_subscriber(sub, force=False):
    sends = sends_of_subscriber(sub["id"])
    delivered = [s for s in sends if s["delivery_status"] == "DELIVERED"]
    before = (sub["delivered_send_count"], sub["opened_send_count"],
              sub["clicked_send_count"], sub["engagement_score"],
              sub["engagement_score_90d"], sub["engagement_state"])
    sub["delivered_send_count"] = len(delivered)
    sub["opened_send_count"] = sum(
        1 for s in delivered if s["engagement_status"] in ("OPENED", "CLICKED"))
    sub["clicked_send_count"] = sum(
        1 for s in delivered if s["engagement_status"] == "CLICKED")
    sub["engagement_score"] = calc.engagement_score(sends, now(), "LIFETIME")
    sub["engagement_score_90d"] = calc.engagement_score(sends, now(), "ROLLING_90D")
    sub["engagement_state"] = calc.engagement_state(
        sub["delivered_send_count"], sub["engagement_score"])
    after = (sub["delivered_send_count"], sub["opened_send_count"],
             sub["clicked_send_count"], sub["engagement_score"],
             sub["engagement_score_90d"], sub["engagement_state"])
    if force or before != after:
        mutate(sub)


def sync_audience(aud, force=False):
    count = sum(1 for s in db.subscribers.values()
                if s["audience_id"] == aud["id"]
                and s["consent_state"] in calc.BILLABLE_CONSENT)
    changed = aud["subscriber_count"] != count
    aud["subscriber_count"] = count
    if force or changed:
        mutate(aud)


def _recompute_account_fields(acct):
    acct["billable_contact_count"] = sum(
        a["subscriber_count"] for a in db.audiences.values()
        if a["account_id"] == acct["id"])
    reserved = 0
    consumed = 0
    for c in db.campaigns.values():
        if c["account_id"] != acct["id"]:
            continue
        if c["status"] in ("SCHEDULED", "SENDING"):
            reserved += c["reserved_credit_count"]
        elif c["status"] == "SENT":
            consumed += c["reserved_credit_count"]
    acct["reserved_send_credits"] = reserved
    acct["consumed_send_credits"] = consumed
    score, n_scored, n_hard = calc.sender_reputation(sends_of_account(acct["id"]))
    acct["sender_reputation_score"] = score
    if acct["status"] == "ACTIVE" and calc.suspension_triggered(n_scored, n_hard):
        acct["status"] = "SUSPENDED"
        acct["suspension_reason"] = "HIGH_HARD_BOUNCE_RATE"


def sync_account(acct, force=False):
    before = (acct["billable_contact_count"], acct["reserved_send_credits"],
              acct["consumed_send_credits"], acct["sender_reputation_score"],
              acct["status"], acct["suspension_reason"])
    _recompute_account_fields(acct)
    after = (acct["billable_contact_count"], acct["reserved_send_credits"],
             acct["consumed_send_credits"], acct["sender_reputation_score"],
             acct["status"], acct["suspension_reason"])
    if force or before != after:
        mutate(acct)


def sync_journey(journey, force=False):
    active = sum(1 for e in db.enrollments.values()
                 if e["journey_id"] == journey["id"] and e["status"] == "ACTIVE")
    entered = sum(1 for e in db.enrollments.values()
                  if e["journey_id"] == journey["id"])
    before = (journey["active_enrollment_count"], journey["entered_count"])
    journey["active_enrollment_count"] = active
    journey["entered_count"] = entered
    if force or before != (active, entered):
        mutate(journey)


def sync_segment(segment, force=False):
    members = segment_members(segment)
    changed = segment["member_count"] != len(members)
    segment["member_count"] = len(members)
    if force or changed:
        mutate(segment)


def segment_members(segment):
    current = now()
    return [s for s in db.subscribers.values()
            if calc.segment_matches(segment, s, current)]


def cascade_consent_change(sub):
    """A subscriber's consent_state moved: audience count, then account count."""
    aud = audience_of_subscriber(sub)
    sync_audience(aud)
    sync_account(db.accounts[aud["account_id"]])


# ==========================================================================
# Journey enrollment triggers (PRD 3.10)
# ==========================================================================
def fire_enrollments(sub, trigger_event):
    for journey in list(db.journeys.values()):
        if journey["status"] != "ACTIVE":
            continue
        if journey["audience_id"] != sub["audience_id"]:
            continue
        if journey["trigger_event"] != trigger_event:
            continue
        existing = any(e for e in db.enrollments.values()
                       if e["journey_id"] == journey["id"]
                       and e["subscriber_id"] == sub["id"]
                       and e["status"] == "ACTIVE")
        if existing:
            continue
        enrollment = base_fields()
        enrollment.update({
            "journey_id": journey["id"],
            "subscriber_id": sub["id"],
            "status": "ACTIVE",
            "current_step_index": 0,
            "next_action_at": now(),
            "enrolled_at": now(),
        })
        db.enrollments[enrollment["id"]] = enrollment
        sync_journey(journey)


# ==========================================================================
# Subscriber creation (shared by the single-add endpoint and the importer)
# ==========================================================================
def create_subscriber(aud, email, first_name, consent_source):
    """Mints the row. Callers are responsible for the count recomputations."""
    sub = base_fields()
    double_optin = aud["double_optin_required"]
    sub.update({
        "audience_id": aud["id"],
        "email": email,
        "first_name": first_name,
        "consent_source": consent_source,
        "consent_state": "PENDING" if double_optin else "CONFIRMED",
        "engagement_state": "NEW",
        "confirmation_token": new_token() if double_optin else None,
        "unsubscribe_token": new_token(),
        "consent_confirmed_at": None if double_optin else now(),
        "unsubscribed_at": None,
        "delivered_send_count": 0,
        "opened_send_count": 0,
        "clicked_send_count": 0,
        "last_opened_at": None,
        "engagement_score": 50,
        "engagement_score_90d": 50,
    })
    db.subscribers[sub["id"]] = sub
    return sub


# ==========================================================================
# Campaign scheduling helpers (PRD 3.6)
# ==========================================================================
def recipient_snapshot(campaign):
    aud_id = campaign["audience_id"]
    pool = [s for s in db.subscribers.values()
            if s["audience_id"] == aud_id and s["consent_state"] == "CONFIRMED"]
    if campaign["segment_id"]:
        segment = db.segments[campaign["segment_id"]]
        sync_segment(segment)
        member_ids = {s["id"] for s in segment_members(segment)}
        pool = [s for s in pool if s["id"] in member_ids]
    pool = [s for s in pool
            if suppression_for(campaign["account_id"], s["email"]) is None]
    pool.sort(key=lambda s: (s["created_at"], s["email"]))
    return [s["id"] for s in pool]


def campaign_end(campaign):
    return campaign["scheduled_at"] + timedelta(minutes=campaign["send_window_minutes"])


def check_audience_fatigue(campaign, scheduled_at):
    buffer_seconds = calc.AUDIENCE_FATIGUE_BUFFER_HOURS * 3600
    for other in db.campaigns.values():
        if other["id"] == campaign["id"]:
            continue
        if other["audience_id"] != campaign["audience_id"]:
            continue
        if other["status"] not in ("SCHEDULED", "SENDING"):
            continue
        gap = abs((scheduled_at - other["scheduled_at"]).total_seconds())
        if gap < buffer_seconds:
            raise ApiError("ERR_AUDIENCE_FATIGUE_CONFLICT")


def check_send_capacity(campaign, acct, scheduled_at, window_minutes, recipient_count):
    end = scheduled_at + timedelta(minutes=window_minutes)
    total = 0
    for other in db.campaigns.values():
        if other["id"] == campaign["id"]:
            continue
        if other["account_id"] != acct["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "SENDING"):
            continue
        # half-open intervals: touching windows do not overlap
        if other["scheduled_at"] < end and scheduled_at < campaign_end(other):
            total += other["recipient_count"]
    if total + recipient_count > acct["hourly_send_capacity"]:
        raise ApiError("ERR_SEND_CAPACITY_EXCEEDED")


# ==========================================================================
# Campaign bubble-up (PRD 3.7)
# ==========================================================================
def maybe_bubble_to_sent(campaign):
    if campaign["status"] != "SENDING":
        return False
    sends = sends_of_campaign(campaign["id"])
    if not all(s["delivery_status"] in calc.TERMINAL_DELIVERY for s in sends):
        return False
    campaign["status"] = "SENT"
    mutate(campaign)
    return True


def mint_send(campaign_id, journey_id, subscriber_id, delivery_status,
              variant_label=None):
    send = base_fields()
    send.update({
        "campaign_id": campaign_id,
        "journey_id": journey_id,
        "subscriber_id": subscriber_id,
        "variant_label": variant_label,
        "delivery_status": delivery_status,
        "engagement_status": "NOT_OPENED",
        "soft_bounce_count": 0,
        "open_count": 0,
        "click_count": 0,
        "delivered_at": None,
        "first_opened_at": None,
        "last_clicked_at": None,
    })
    db.sends[send["id"]] = send
    return send


# ==========================================================================
# Telemetry events (PRD 3.8)
# ==========================================================================
def _hard_bounce_cascade(send):
    send["delivery_status"] = "HARD_BOUNCED"
    mutate(send)
    sub = db.subscribers[send["subscriber_id"]]
    aud = audience_of_subscriber(sub)
    acct = db.accounts[aud["account_id"]]
    add_suppression(acct["id"], sub["email"], "HARD_BOUNCE")
    if sub["consent_state"] in ("PENDING", "CONFIRMED"):
        sub["consent_state"] = "CLEANED"
        sub["confirmation_token"] = None
        mutate(sub)
    sync_subscriber(sub)
    sync_audience(aud)


def apply_event(send, kind):
    sub = db.subscribers[send["subscriber_id"]]
    aud = audience_of_subscriber(sub)
    acct = db.accounts[aud["account_id"]]
    delivery = send["delivery_status"]

    if kind == "DELIVERED":
        if delivery not in ("QUEUED", "SOFT_BOUNCED"):
            raise ApiError("ERR_INVALID_STATE")
        send["delivery_status"] = "DELIVERED"
        send["delivered_at"] = now()
        mutate(send)
        sync_subscriber(sub)

    elif kind == "SOFT_BOUNCE":
        if delivery not in ("QUEUED", "SOFT_BOUNCED"):
            raise ApiError("ERR_INVALID_STATE")
        send["soft_bounce_count"] += 1
        if send["soft_bounce_count"] >= calc.SOFT_BOUNCE_ESCALATION_COUNT:
            _hard_bounce_cascade(send)
        else:
            send["delivery_status"] = "SOFT_BOUNCED"
            mutate(send)

    elif kind == "HARD_BOUNCE":
        if delivery not in ("QUEUED", "SOFT_BOUNCED"):
            raise ApiError("ERR_INVALID_STATE")
        _hard_bounce_cascade(send)

    elif kind == "COMPLAINT":
        if delivery != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE")
        send["delivery_status"] = "COMPLAINED"
        # engagement_status is left exactly as it was.
        mutate(send)
        if sub["consent_state"] == "CONFIRMED":
            sub["consent_state"] = "UNSUBSCRIBED"
            sub["unsubscribed_at"] = now()
            mutate(sub)
        add_suppression(acct["id"], sub["email"], "COMPLAINT")
        sync_subscriber(sub)
        sync_audience(aud)

    elif kind == "OPEN":
        if delivery != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE")
        send["open_count"] += 1
        if send["engagement_status"] == "NOT_OPENED":
            send["engagement_status"] = "OPENED"
            send["first_opened_at"] = now()
        mutate(send)
        sub["last_opened_at"] = now()
        mutate(sub)
        sync_subscriber(sub)

    elif kind == "CLICK":
        if delivery != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE")
        if send["engagement_status"] not in ("OPENED", "CLICKED"):
            raise ApiError("ERR_CLICK_WITHOUT_OPEN")
        first_click = send["engagement_status"] == "OPENED"
        send["click_count"] += 1
        send["last_clicked_at"] = now()
        if first_click:
            send["engagement_status"] = "CLICKED"
        mutate(send)
        sub["last_opened_at"] = now()
        mutate(sub)
        sync_subscriber(sub)
        if first_click and send["campaign_id"]:
            fire_enrollments(sub, "CAMPAIGN_CLICK")

    else:  # pragma: no cover -- guarded by body validation
        raise ApiError("ERR_INVALID_REQUEST")

    # Campaign bubble-up before the account recompute, so the reservation
    # migration lands in a single account mutation.
    if send["campaign_id"]:
        campaign = db.campaigns.get(send["campaign_id"])
        if campaign:
            maybe_bubble_to_sent(campaign)
    sync_account(acct)
    return send


# ==========================================================================
# Billing (PRD 3.11)
# ==========================================================================
def open_cycle_of(account_id):
    for c in db.billing_cycles.values():
        if c["account_id"] == account_id and c["status"] == "OPEN":
            return c
    return None


def create_billing_cycle(account_id, period_start, peak):
    cycle = base_fields()
    cycle.update({
        "account_id": account_id,
        "period_start": period_start,
        "period_end": period_start + timedelta(days=calc.BILLING_PERIOD_DAYS),
        "status": "OPEN",
        "peak_contact_count": peak,
        "tier_applied": None,
        "base_fee_cents": 0,
        "overage_cents": 0,
        "total_cents": 0,
        "closed_at": None,
    })
    db.billing_cycles[cycle["id"]] = cycle
    return cycle


# ==========================================================================
# The operations epoch (PRD 2.11)
# ==========================================================================
def run_ops():
    current = now()
    report = {
        "subscribers_archived": 0,
        "campaigns_dispatched": 0,
        "sends_created": 0,
        "enrollments_advanced": 0,
        "billing_cycles_closed": 0,
    }

    # --- Phase 1: archive expired PENDING subscribers ----------------------
    ttl = timedelta(hours=calc.CONFIRMATION_TOKEN_TTL_HOURS)
    touched_audiences = set()
    for sub in list(db.subscribers.values()):
        if sub["consent_state"] != "PENDING":
            continue
        if current < sub["created_at"] + ttl:
            continue
        sub["consent_state"] = "ARCHIVED"
        sub["confirmation_token"] = None
        mutate(sub)
        report["subscribers_archived"] += 1
        touched_audiences.add(sub["audience_id"])
    for aud_id in touched_audiences:
        aud = db.audiences[aud_id]
        sync_audience(aud)
        sync_account(db.accounts[aud["account_id"]])

    # --- Phase 2: dispatch SCHEDULED campaigns of ACTIVE accounts ----------
    due = [c for c in db.campaigns.values()
           if c["status"] == "SCHEDULED"
           and c["scheduled_at"] is not None
           and c["scheduled_at"] <= current
           and db.accounts[c["account_id"]]["status"] == "ACTIVE"]
    due.sort(key=lambda c: (c["scheduled_at"], c["created_at"]))
    for campaign in due:
        campaign["status"] = "SENDING"
        mutate(campaign)
        snapshot = campaign["recipient_snapshot_ids"]
        acct_id = campaign["account_id"]
        a_count = 0
        if campaign["ab_test_enabled"]:
            a_count = (len(snapshot) * campaign["variant_split_pct"]) // 100
        for pos, sub_id in enumerate(snapshot):
            sub = db.subscribers[sub_id]
            suppressed = (sub["consent_state"] != "CONFIRMED"
                          or suppression_for(acct_id, sub["email"]) is not None)
            status = "SUPPRESSED" if suppressed else "QUEUED"
            label = None
            if campaign["ab_test_enabled"]:
                label = "A" if pos < a_count else "B"
            mint_send(campaign["id"], None, sub_id, status, label)
            report["sends_created"] += 1
        report["campaigns_dispatched"] += 1
        maybe_bubble_to_sent(campaign)
        sync_account(db.accounts[acct_id])

    # --- Phase 3: advance due enrollments ---------------------------------
    candidates = [e for e in db.enrollments.values() if e["status"] == "ACTIVE"]
    candidates.sort(key=lambda e: e["created_at"])
    for enrollment in candidates:
        journey = db.journeys[enrollment["journey_id"]]
        if journey["status"] != "ACTIVE":
            continue
        if enrollment["next_action_at"] is None or enrollment["next_action_at"] > current:
            continue
        report["enrollments_advanced"] += 1
        sub = db.subscribers[enrollment["subscriber_id"]]

        if sub["consent_state"] != "CONFIRMED":
            enrollment["status"] = "SUPPRESSED"
            mutate(enrollment)
            sync_journey(journey)
            continue

        steps = {s["step_index"]: s for s in journey["steps"]}
        n_steps = len(journey["steps"])
        while True:
            idx = enrollment["current_step_index"]
            if idx >= n_steps or idx not in steps:
                enrollment["status"] = "COMPLETED"
                break
            step = steps[idx]
            kind = step["kind"]
            if kind == "WAIT":
                enrollment["next_action_at"] = current + timedelta(
                    hours=step.get("wait_hours") or 0)
                enrollment["current_step_index"] = idx + 1
                break
            if kind == "EMAIL":
                mint_send(None, journey["id"], sub["id"], "QUEUED", None)
                report["sends_created"] += 1
                enrollment["current_step_index"] = idx + 1
                continue
            if kind == "CONDITION":
                if sub["engagement_score"] >= step.get("condition_min_score", 0):
                    enrollment["current_step_index"] = step["on_true_step_index"]
                else:
                    enrollment["current_step_index"] = step["on_false_step_index"]
                continue
            break
        mutate(enrollment)
        sync_journey(journey)

    # --- Phase 4: snapshot billable_contact_count into the OPEN cycle ------
    for acct in db.accounts.values():
        cycle = open_cycle_of(acct["id"])
        if cycle is None:
            continue
        peak = max(cycle["peak_contact_count"], acct["billable_contact_count"])
        if peak != cycle["peak_contact_count"]:
            cycle["peak_contact_count"] = peak
            mutate(cycle)

    # --- Phase 5: close and roll forward ----------------------------------
    for acct in db.accounts.values():
        while True:
            cycle = open_cycle_of(acct["id"])
            if cycle is None or cycle["period_end"] > current:
                break
            tier = acct["plan_tier"]
            cycle["status"] = "CLOSED"
            cycle["tier_applied"] = tier
            cycle["base_fee_cents"] = calc.PLAN_BASE_FEE_CENTS[tier]
            cycle["overage_cents"] = calc.tiered_overage_cents(
                cycle["peak_contact_count"], tier)
            cycle["total_cents"] = cycle["base_fee_cents"] + cycle["overage_cents"]
            cycle["closed_at"] = current
            mutate(cycle)
            report["billing_cycles_closed"] += 1
            create_billing_cycle(acct["id"], cycle["period_end"],
                                 acct["billable_contact_count"])

    return report


# ==========================================================================
# A/B winner (PRD 3.9)
# ==========================================================================
def select_winner(campaign):
    sends = [s for s in sends_of_campaign(campaign["id"])
             if s["delivery_status"] == "DELIVERED"]
    stats = {}
    for label in ("A", "B"):
        pool = [s for s in sends if s["variant_label"] == label]
        stats[label] = {
            "n": len(pool),
            "opens": sum(1 for s in pool
                         if s["engagement_status"] in ("OPENED", "CLICKED")),
            "clicks": sum(1 for s in pool if s["engagement_status"] == "CLICKED"),
            "earliest": min((s["created_at"] for s in pool), default=None),
        }
    a, b = stats["A"], stats["B"]
    if (a["n"] < calc.AB_MIN_SAMPLE_PER_VARIANT
            or b["n"] < calc.AB_MIN_SAMPLE_PER_VARIANT
            or (a["opens"] + b["opens"]) < calc.AB_MIN_TOTAL_OPENS):
        raise ApiError("ERR_INSUFFICIENT_AB_SAMPLE")

    # Exact rational comparison: clicks_A / n_A  vs  clicks_B / n_B
    lhs = a["clicks"] * b["n"]
    rhs = b["clicks"] * a["n"]
    if lhs > rhs:
        winner = "A"
    elif rhs > lhs:
        winner = "B"
    else:
        lhs = a["opens"] * b["n"]
        rhs = b["opens"] * a["n"]
        if lhs > rhs:
            winner = "A"
        elif rhs > lhs:
            winner = "B"
        else:
            winner = "A" if a["earliest"] <= b["earliest"] else "B"

    campaign["winning_variant"] = winner
    campaign["winner_selected_at"] = now()
    mutate(campaign)
    return campaign
