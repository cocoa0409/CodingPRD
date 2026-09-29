"""All domain calculations and cascades (PRD sections 3.2 - 3.10)."""
from datetime import timedelta
from decimal import Decimal

import clock
import db
from config import (
    BURST_FLOW_FACTOR,
    BURST_MIN_DURATION_MINUTES,
    BURST_MIN_GALLONS,
    CONTACT_SLA_MINUTES,
    COVERAGE_MINUTES_PER_READING,
    DRIP_CEILING_GPM,
    DRIP_FRACTION,
    DRIP_MIN_DURATION_MINUTES,
    DUPLICATE_COOLDOWN_MINUTES,
    FALSE_POSITIVE_WINDOW_DAYS,
    HOMEOWNER_SLA_MINUTES,
    MAX_FALSE_POSITIVES_BEFORE_RELEARN,
    MIN_DRIP_GPM,
    MIN_LEARNING_SAMPLES,
    MIN_OFFLINE_GAP_MINUTES,
    OVERRIDE_GRACE_MINUTES,
    PERIODS_PER_POLICY_YEAR,
    POLICY_ANNUAL_PAYOUT_CAP_CENTS,
    RUNNING_FLOW_FACTOR,
    RUNNING_MIN_DURATION_MINUTES,
    SEVERITY_DURATION_WEIGHT,
    SEVERITY_FLOW_WEIGHT,
    SEVERITY_GALLON_WEIGHT,
    SEVERITY_REFERENCE_FACTOR,
    TIER_BASE_CUT,
    TIER_BASE_PCT,
    TIER_ELITE_CUT,
    TIER_ELITE_PCT,
    TIER_STRONG_CUT,
    TIER_STRONG_PCT,
    TUNING_STEP,
    UNMITIGATED_FACTOR,
    UPTIME_CREDIT_FLOOR_PCT,
    VACATION_RUNNING_GALLON_CAP,
    VACATION_SENSITIVITY_MULTIPLIER,
    WARRANTY_CAP_CENTS,
    WATER_DAMAGE_CAP_CENTS,
)
from serializers import mitigation_credited
from util import rhu, rhu_int, to_dec

D = Decimal
ONE = D("1")
ZERO = D("0")


# ================================================================= baseline
def eligible_readings(profile):
    started = profile.get("learning_started_at")
    out = []
    for r in db.telemetry_readings.values():
        if r["device_id"] != profile["device_id"]:
            continue
        if not r.get("baseline_eligible"):
            continue
        if started is not None and r["reading_at"] < started:
            continue
        out.append(r)
    return db.by_seq(out)


def recompute_baseline(profile, device_row, reading=None):
    """Step 3 of an ingest: publish a fresh snapshot while COLLECTING."""
    if profile is None or profile["learning_state"] != "COLLECTING":
        return
    readings = eligible_readings(profile)
    count = len(readings)
    if count == 0:
        return
    if reading is not None and reading["id"] not in {r["id"] for r in readings}:
        # The aggregate is recomputed only to include a reading that belongs to
        # the eligible set: a bench test teaches the baseline nothing.
        return
    pressure_total = ZERO
    peak = ZERO
    for r in readings:
        pressure_total += to_dec(r["static_pressure_psi"])
        flow = to_dec(r["flow_gpm"])
        if flow > peak:
            peak = flow
    profile["baseline_version"] = profile["baseline_version"] + 1
    if count < MIN_LEARNING_SAMPLES:
        # Values stay unpublished until the cycle completes.
        db.touch(profile)
        return
    profile["baseline_static_pressure_psi"] = rhu(pressure_total / D(count), 1)
    profile["baseline_peak_flow_gpm"] = rhu(peak, 2)
    profile["drip_threshold_gpm"] = rhu(
        max(MIN_DRIP_GPM, rhu(peak, 2) * DRIP_FRACTION), 2
    )
    profile["learning_state"] = "COMPLETE"
    profile["completed_at"] = clock.now()
    db.touch(profile)
    # Bubble-up promotion: the profile's completion arms the device.
    if device_row["lifecycle_state"] == "LEARNING":
        device_row["lifecycle_state"] = "ARMED"
    device_row["baseline_ready"] = True
    db.touch(device_row)


def reopen_profile_if_invalidated(profile):
    """A profile that was invalidated re-enters COLLECTING on the next reading."""
    if profile is None or profile["learning_state"] != "INVALIDATED":
        return
    profile["learning_state"] = "COLLECTING"
    profile["learning_cycle_no"] = profile["learning_cycle_no"] + 1
    profile["learning_started_at"] = clock.now()
    profile["baseline_static_pressure_psi"] = None
    profile["baseline_peak_flow_gpm"] = None
    profile["drip_threshold_gpm"] = None
    profile["false_positive_count"] = 0
    profile["completed_at"] = None
    db.touch(profile)


def invalidate_baseline(device_row, reason):
    """Demotion cascade shared by firmware, false-positive relearn and transfer."""
    profile = db.profile_for_device(device_row["id"])
    was_complete = profile is not None and profile["learning_state"] == "COMPLETE"
    if was_complete:
        profile["learning_state"] = "INVALIDATED"
        profile["invalidated_reason"] = reason
        profile["completed_at"] = None
        if reason != "FALSE_POSITIVE_THRESHOLD":
            # Firmware and ownership-transfer invalidations reset the tally; the
            # false-positive relearn keeps the count that tripped it, and the
            # reopening reading is what clears it.
            profile["false_positive_count"] = 0
        db.touch(profile)
    return was_complete


# ================================================================= classification
def sensitivity_multiplier(device_row):
    if device_row["monitor_mode"] == "VACATION":
        return VACATION_SENSITIVITY_MULTIPLIER
    return ONE


def gates(device_row, profile):
    peak = to_dec(profile.get("baseline_peak_flow_gpm") or 0)
    m = sensitivity_multiplier(device_row)
    return {
        "burst_flow": rhu(peak * BURST_FLOW_FACTOR * m, 2),
        "running_flow": rhu(peak * RUNNING_FLOW_FACTOR * m, 2),
        "burst_gallon": rhu(BURST_MIN_GALLONS * m, 2),
        "drip": to_dec(profile.get("drip_threshold_gpm") or 0),
    }


def classify(device_row, profile, flow, duration, gallons):
    g = gates(device_row, profile)
    if (
        flow >= g["burst_flow"]
        and duration >= BURST_MIN_DURATION_MINUTES
        and gallons >= g["burst_gallon"]
    ):
        return "CATASTROPHIC_BURST", g
    if flow >= g["running_flow"] and duration >= RUNNING_MIN_DURATION_MINUTES:
        return "RUNNING_FIXTURE", g
    if (
        device_row["monitor_mode"] == "VACATION"
        and flow > ZERO
        and gallons >= VACATION_RUNNING_GALLON_CAP
    ):
        return "RUNNING_FIXTURE", g
    if flow >= g["drip"] and duration >= DRIP_MIN_DURATION_MINUTES:
        return "DRIP", g
    return "NONE", g


def severity(g, flow, duration, gallons):
    flow_ref = rhu(g["burst_flow"] * SEVERITY_REFERENCE_FACTOR, 4)
    duration_ref = rhu(BURST_MIN_DURATION_MINUTES * SEVERITY_REFERENCE_FACTOR, 4)
    gallon_ref = rhu(g["burst_gallon"] * SEVERITY_REFERENCE_FACTOR, 4)

    def component(value, ref):
        if ref == ZERO:
            return ONE if value > ZERO else ZERO
        return min(ONE, value / ref)

    total = (
        component(flow, flow_ref) * SEVERITY_FLOW_WEIGHT
        + component(duration, duration_ref) * SEVERITY_DURATION_WEIGHT
        + component(gallons, gallon_ref) * SEVERITY_GALLON_WEIGHT
    )
    return rhu(total, 3)


# ================================================================= irrigation
def irrigation_suppresses(property_id, reading_at, flow):
    for w in db.irrigation_windows.values():
        if w["property_id"] != property_id or w["status"] != "ACTIVE":
            continue
        if w["start_at"] <= reading_at < w["end_at"] and flow <= to_dec(
            w["expected_max_flow_gpm"]
        ):
            return True
    return False


def suspend_irrigation(property_id):
    now = clock.now()
    for w in db.windows_for_property(property_id):
        if w["status"] == "ACTIVE":
            w["status"] = "SUSPENDED_BY_SHUTOFF"
            w["suspended_at"] = now
            db.touch(w)


def restore_irrigation(property_id):
    for w in db.windows_for_property(property_id):
        if w["status"] == "SUSPENDED_BY_SHUTOFF":
            w["status"] = "ACTIVE"
            w["suspended_at"] = None
            db.touch(w)


# ================================================================= events
def duplicate_within_cooldown(device_id, classification, exclude_id=None):
    cutoff = clock.now() - timedelta(minutes=DUPLICATE_COOLDOWN_MINUTES)
    for e in db.anomaly_events.values():
        if e["device_id"] != device_id or e["classification"] != classification:
            continue
        if exclude_id is not None and e["id"] == exclude_id:
            continue
        if e["detected_at"] > cutoff:
            return True
    return False


def mint_event(device_row, reading, classification, g):
    now = clock.now()
    flow = to_dec(reading["flow_gpm"])
    duration = to_dec(reading["duration_minutes"])
    gallons = to_dec(reading["total_gallons"])
    profile = db.profile_for_device(device_row["id"])
    event = {
        "device_id": device_row["id"],
        "telemetry_reading_id": reading["id"],
        "classification": classification,
        "severity_score": severity(g, flow, duration, gallons),
        "event_state": "DETECTED",
        "detected_at": now,
        "suppression_reason": None,
        "auto_shutoff_executed": False,
        "shutoff_latency_minutes": None,
        "override_reopen_at": None,
        "observed_flow_gpm": flow,
        "observed_duration_minutes": duration,
        "observed_gallons": gallons,
        "baseline_version_used": profile["baseline_version"] if profile else 0,
        "resolved_at": None,
        "resolution_note": None,
        "feedback_label": None,
    }
    db.insert(db.anomaly_events, event)
    reading["anomaly_event_created"] = True

    # Suppression precedence: transfer lock, then snooze, then duplicate cooldown.
    if device_row["lifecycle_state"] == "TRANSFER_PENDING":
        event["event_state"] = "SUPPRESSED"
        event["suppression_reason"] = "DEVICE_NOT_ARMED"
    elif device_row["monitor_mode"] == "SNOOZE":
        event["event_state"] = "SUPPRESSED"
        event["suppression_reason"] = "SNOOZE_ACTIVE"
    elif duplicate_within_cooldown(device_row["id"], classification, event["id"]):
        event["event_state"] = "SUPPRESSED"
        event["suppression_reason"] = "DUPLICATE_WITHIN_COOLDOWN"
    else:
        event["event_state"] = "ALERTED"
        mint_ticket(event)
    return event


def mint_ticket(event):
    now = clock.now()
    ticket = {
        "anomaly_event_id": event["id"],
        "notified_contact_id": None,
        "stage": "PENDING_HOMEOWNER",
        "contact_deadline_at": None,
        "escalated_at": None,
        "acknowledged_at": None,
        "acknowledged_by_user_id": None,
        "expiry_reason": None,
        "notification_attempt_count": 1,
    }
    db.insert(db.escalation_tickets, ticket)
    ticket["homeowner_deadline_at"] = ticket["created_at"] + timedelta(
        minutes=HOMEOWNER_SLA_MINUTES
    )
    return ticket


def expire_pending_ticket(event, reason):
    ticket = db.ticket_for_event(event["id"])
    if ticket is None:
        return
    if ticket["stage"] in ("PENDING_HOMEOWNER", "PENDING_EMERGENCY_CONTACT"):
        ticket["stage"] = "EXPIRED"
        ticket["expiry_reason"] = reason
        db.touch(ticket)


# ================================================================= auto shutoff
def override_grace_active(device_row):
    now = clock.now()
    for e in db.events_for_device(device_row["id"]):
        if e["event_state"] not in ("ALERTED", "ESCALATED"):
            continue
        stamp = e.get("override_reopen_at")
        if stamp is None:
            continue
        if now < stamp + timedelta(minutes=OVERRIDE_GRACE_MINUTES):
            return True
    return False


def auto_shutoff(device_row, event):
    required = event["classification"] == "CATASTROPHIC_BURST" or (
        event["classification"] == "RUNNING_FIXTURE"
        and device_row["monitor_mode"] == "VACATION"
    )
    if not required:
        return False
    if event["event_state"] == "SUPPRESSED":
        return False
    if device_row["valve_state"] == "CLOSED":
        return False
    if override_grace_active(device_row):
        return False
    now = clock.now()
    device_row["valve_state"] = "CLOSED"
    device_row["close_count"] = device_row["close_count"] + 1
    device_row["last_shutoff_at"] = now
    db.touch(device_row)
    event["auto_shutoff_executed"] = True
    event["shutoff_latency_minutes"] = rhu(
        D(str((now - event["detected_at"]).total_seconds())) / D("60"), 1
    )
    db.touch(event)
    suspend_irrigation(device_row["property_id"])
    return True


# ================================================================= ingest
def ingest_reading(device_row, reading_at, pressure, flow, duration, gallons, source):
    """The fixed three-step order of one accepted telemetry ingest."""
    profile = db.profile_for_device(device_row["id"])
    reopen_profile_if_invalidated(profile)

    suppressed = irrigation_suppresses(device_row["property_id"], reading_at, flow)
    reading = {
        "device_id": device_row["id"],
        "reading_at": reading_at,
        "static_pressure_psi": pressure,
        "flow_gpm": flow,
        "duration_minutes": duration,
        "total_gallons": gallons,
        "reading_source": source,
        "classification_at_ingest": "NONE",
        "suppressed_by_irrigation": suppressed,
        "baseline_eligible": False,
        "coverage_minutes": COVERAGE_MINUTES_PER_READING,
        "anomaly_event_created": False,
    }
    db.insert(db.telemetry_readings, reading, versioned=False)
    device_row["last_reading_at"] = reading_at
    device_row["updated_at"] = clock.now()

    # step 2: classify against the snapshot as it stood before this reading.
    classification = "NONE"
    if (
        not suppressed
        and profile is not None
        and profile["learning_state"] == "COMPLETE"
        and device_row["lifecycle_state"] == "ARMED"
    ):
        classification, g = classify(device_row, profile, flow, duration, gallons)
        reading["classification_at_ingest"] = classification
        if classification != "NONE":
            event = mint_event(device_row, reading, classification, g)
            auto_shutoff(device_row, event)

    reading["baseline_eligible"] = (
        reading["classification_at_ingest"] == "NONE"
        and source == "DEVICE"
        and not suppressed
    )

    # step 3: recompute and publish the baseline including this reading.
    recompute_baseline(db.profile_for_device(device_row["id"]), device_row, reading)
    return reading


# ================================================================= uptime
def whole_minutes_between(later, earlier):
    return int((later - earlier).total_seconds() // 60)


def uptime_for_window(device_row, start_at, end_at):
    period_minutes = whole_minutes_between(end_at, start_at)
    intervals = []
    if device_row is not None:
        for r in db.readings_for_device(device_row["id"]):
            at = r["reading_at"]
            if at < start_at or at >= end_at:
                continue
            finish = at + timedelta(minutes=COVERAGE_MINUTES_PER_READING)
            if finish > end_at:
                finish = end_at
            intervals.append((at, finish))
    intervals.sort(key=lambda pair: pair[0])
    merged = []
    for begin, finish in intervals:
        if merged and begin <= merged[-1][1]:
            if finish > merged[-1][1]:
                merged[-1] = (merged[-1][0], finish)
        else:
            merged.append((begin, finish))
    covered = 0
    for begin, finish in merged:
        covered += whole_minutes_between(finish, begin)
    if period_minutes > 0:
        uptime = rhu(D(covered) * D("100") / D(period_minutes), 2)
    else:
        uptime = D("0.00")

    gaps = 0
    cursor = start_at
    for begin, finish in merged:
        if begin > cursor:
            if whole_minutes_between(begin, cursor) >= MIN_OFFLINE_GAP_MINUTES:
                gaps += 1
        if finish > cursor:
            cursor = finish
    if cursor < end_at and whole_minutes_between(end_at, cursor) >= MIN_OFFLINE_GAP_MINUTES:
        gaps += 1
    return {
        "covered_minutes": covered,
        "period_minutes": period_minutes,
        "uptime_pct": uptime,
        "offline_gap_count": gaps,
    }


def resolve_device_for_property(property_id):
    for d in db.devices_for_property(property_id):
        if d["lifecycle_state"] != "DECOMMISSIONED":
            return d
    return None


def tier_for(uptime):
    if uptime >= TIER_ELITE_CUT:
        return TIER_ELITE_PCT
    if uptime >= TIER_STRONG_CUT:
        return TIER_STRONG_PCT
    if uptime >= TIER_BASE_CUT:
        return TIER_BASE_PCT
    return D("0.00")


# ================================================================= credit
def finalized_attestations(policy_id, exclude_id=None):
    rows = [
        a
        for a in db.attestations.values()
        if a["policy_id"] == policy_id
        and a["status"] in ("FINALIZED_AWARDED", "FINALIZED_DENIED")
        and a["id"] != exclude_id
    ]
    return db.by_seq(rows)


def clawback(policy_row, reason):
    """Compensating reversal when a device leaves ARMED mid-year."""
    if policy_row["credit_state"] != "CREDIT_ACTIVE":
        return
    now = clock.now()
    candidates = [
        a
        for a in db.attestations_for_policy(policy_row["id"])
        if a["status"] == "FINALIZED_AWARDED" and a["period_end_at"] <= now
    ]
    amount = 0
    if candidates:
        candidates.sort(key=lambda a: (a["period_end_at"], a["_seq"]))
        amount = candidates[-1]["credit_cents_awarded"]
    policy_row["credit_state"] = "CREDIT_SUSPENDED"
    policy_row["suspended_reason"] = reason
    policy_row["clawback_cents_total"] = policy_row["clawback_cents_total"] + amount
    policy_row["credited_cents_total"] = policy_row["credited_cents_total"] - amount
    policy_row["current_credit_tier_pct"] = D("0")
    db.touch(policy_row)


def suspend_policies_for_property(property_id, reason):
    for p in db.policies_for_property(property_id):
        if p["credit_state"] == "CREDIT_ACTIVE":
            clawback(p, reason)


def demote_device(device_row, reason, target_state="LEARNING"):
    """Invalidate the baseline, demote the device, suspend and claw back credit."""
    was_complete = invalidate_baseline(device_row, reason)
    if not was_complete:
        return False
    device_row["lifecycle_state"] = target_state
    device_row["baseline_ready"] = False
    db.touch(device_row)
    policy_reason = (
        "OWNERSHIP_TRANSFER" if reason == "OWNERSHIP_TRANSFER" else "DEVICE_NOT_ARMED"
    )
    suspend_policies_for_property(device_row["property_id"], policy_reason)
    return True


def finalize_attestation(att, policy_row):
    device_row = resolve_device_for_property(policy_row["property_id"])
    stats = uptime_for_window(device_row, att["period_start_at"], att["period_end_at"])
    att["covered_minutes"] = stats["covered_minutes"]
    att["uptime_pct"] = stats["uptime_pct"]
    att["offline_gap_count"] = stats["offline_gap_count"]
    att["finalized_at"] = clock.now()

    denial = None
    if device_row is None:
        denial = "NO_ENROLLED_DEVICE"
    elif device_row["lifecycle_state"] != "ARMED":
        denial = "DEVICE_NOT_ARMED"
    elif stats["uptime_pct"] < UPTIME_CREDIT_FLOOR_PCT:
        denial = "UPTIME_BELOW_FLOOR"

    if device_row is not None:
        att["device_snapshot_lifecycle_state"] = device_row["lifecycle_state"]

    premium = D(policy_row["annual_premium_cents"])
    if denial is not None:
        att["status"] = "FINALIZED_DENIED"
        att["denial_reason"] = denial
        tier = D("0.00")
        awarded = 0
    else:
        tier = tier_for(stats["uptime_pct"])
        awarded = rhu_int(premium * tier / D(PERIODS_PER_POLICY_YEAR))
        att["status"] = "FINALIZED_AWARDED"
    att["tier_pct"] = tier
    att["credit_cents_awarded"] = awarded

    # The annual true-up runs on the finalize that brings finalized_period_count
    # up to the two periods of a policy year, award or denial alike: "A denied
    # period contributes a tier of 0.00 to the annual sum and nothing to the
    # provisional total, so it drags the annual number down".
    prior = finalized_attestations(policy_row["id"], exclude_id=att["id"])
    count_after = len(prior) + 1
    true_up = 0
    if count_after == PERIODS_PER_POLICY_YEAR:
        tier_sum = tier
        booked = awarded
        for row in prior:
            tier_sum += to_dec(row.get("tier_pct") or 0)
            booked += row.get("credit_cents_awarded") or 0
        annual = rhu_int(premium * tier_sum / D(PERIODS_PER_POLICY_YEAR))
        true_up = annual - booked
        att["is_policy_year_close"] = True
        att["true_up_cents"] = true_up
    db.touch(att)

    if denial is None:
        policy_row["current_credit_tier_pct"] = tier
        policy_row["credited_cents_total"] = policy_row["credited_cents_total"] + awarded
    if att["is_policy_year_close"]:
        policy_row["true_up_cents"] = true_up
        policy_row["credited_cents_total"] = policy_row["credited_cents_total"] + true_up
    policy_row["last_attestation_end_at"] = att["period_end_at"]
    if denial is not None:
        if policy_row["credit_state"] == "CREDIT_ACTIVE" and denial == "UPTIME_BELOW_FLOOR":
            policy_row["credit_state"] = "CREDIT_SUSPENDED"
            policy_row["suspended_reason"] = "UPTIME_BELOW_FLOOR"
            policy_row["current_credit_tier_pct"] = D("0")
    elif policy_row["credit_state"] in ("PENDING_ENROLLMENT", "CREDIT_SUSPENDED"):
        policy_row["credit_state"] = "CREDIT_ACTIVE"
        policy_row["suspended_reason"] = None
    db.touch(policy_row)
    return att


# ================================================================= claims
def payout_for(claim_row, policy_row):
    """Returns (variant, deductible_applied_cents, approved_payout_cents)."""
    loss = claim_row["documented_loss_cents"]
    if claim_row["claim_type"] == "WARRANTY_DEVICE":
        return "WARRANTY_FLAT", 0, min(loss, WARRANTY_CAP_CENTS)
    event = db.anomaly_events.get(claim_row.get("anomaly_event_id"))
    if event is not None and mitigation_credited(event):
        return "MITIGATED", 0, min(loss, WATER_DAMAGE_CAP_CENTS)
    applied = min(loss, policy_row["deductible_cents"])
    net = loss - applied
    scaled_net = rhu_int(D(net) * UNMITIGATED_FACTOR)
    scaled_cap = rhu_int(D(WATER_DAMAGE_CAP_CENTS) * UNMITIGATED_FACTOR)
    return "UNMITIGATED", applied, min(scaled_net, scaled_cap)


def cap_exceeded(policy_row, amount):
    return policy_row["paid_payout_cents_total"] + amount > POLICY_ANNUAL_PAYOUT_CAP_CENTS


# ================================================================= tuning
def false_positive_tuning(event, device_row):
    profile = db.profile_for_device(device_row["id"])
    cutoff = clock.now() - timedelta(days=FALSE_POSITIVE_WINDOW_DAYS)
    count = 0
    for e in db.events_for_device(device_row["id"]):
        if e.get("feedback_label") != "FALSE_POSITIVE":
            continue
        if e.get("updated_at") is not None and e["updated_at"] < cutoff:
            continue
        count += 1
    if profile is None:
        return
    profile["false_positive_count"] = count
    if profile["learning_state"] == "COMPLETE":
        current = to_dec(profile.get("drip_threshold_gpm") or 0)
        profile["drip_threshold_gpm"] = rhu(
            min(DRIP_CEILING_GPM, current * (ONE + TUNING_STEP)), 2
        )
        profile["last_false_positive_at"] = clock.now()
        profile["baseline_version"] = profile["baseline_version"] + 1
        db.touch(profile)
        if count >= MAX_FALSE_POSITIVES_BEFORE_RELEARN:
            demote_device(device_row, "FALSE_POSITIVE_THRESHOLD")
    else:
        db.touch(profile)


# ================================================================= sweep
def run_sweep():
    now = clock.now()
    report = {
        "modes_reverted": 0,
        "tickets_escalated": 0,
        "tickets_expired": 0,
        "transfers_expired": 0,
    }
    # 1. lapsed monitor modes revert.
    for device_row in db.by_seq(list(db.devices.values())):
        changed = False
        if (
            device_row["monitor_mode"] == "VACATION"
            and device_row.get("vacation_ends_at") is not None
            and now >= device_row["vacation_ends_at"]
        ):
            device_row["monitor_mode"] = "NORMAL"
            device_row["vacation_started_at"] = None
            device_row["vacation_ends_at"] = None
            changed = True
        elif (
            device_row["monitor_mode"] == "SNOOZE"
            and device_row.get("snooze_window_end_at") is not None
            and now >= device_row["snooze_window_end_at"]
        ):
            device_row["monitor_mode"] = "NORMAL"
            changed = True
        if changed:
            device_row["monitor_mode_updated_at"] = now
            db.touch(device_row)
            report["modes_reverted"] += 1

    # 2. escalation SLA hops, chronologically by ticket created_at.
    tickets = db.sort_rows(
        list(db.escalation_tickets.values()), lambda t: t["created_at"]
    )
    for ticket in tickets:
        if ticket["stage"] not in ("PENDING_HOMEOWNER", "PENDING_EMERGENCY_CONTACT"):
            continue
        event = db.anomaly_events.get(ticket["anomaly_event_id"])
        if event is None or event["event_state"] not in ("ALERTED", "ESCALATED"):
            continue
        if ticket["stage"] == "PENDING_HOMEOWNER":
            if now < ticket["homeowner_deadline_at"]:
                continue
            owner_id = db.owner_of_event(event)
            pool = [
                c
                for c in db.contacts_for_homeowner(owner_id)
                if c["status"] == "ACTIVE" and c["verification_state"] == "VERIFIED"
            ]
            if pool:
                pool.sort(key=lambda c: (c["priority_rank"], c["created_at"], c["_seq"]))
                chosen = pool[0]
                ticket["stage"] = "PENDING_EMERGENCY_CONTACT"
                ticket["notified_contact_id"] = chosen["id"]
                ticket["escalated_at"] = now
                ticket["contact_deadline_at"] = now + timedelta(minutes=CONTACT_SLA_MINUTES)
                ticket["notification_attempt_count"] = 2
                db.touch(ticket)
                chosen["last_notified_at"] = now
                db.touch(chosen)
                if event["event_state"] == "ALERTED":
                    event["event_state"] = "ESCALATED"
                    db.touch(event)
                report["tickets_escalated"] += 1
            else:
                ticket["stage"] = "EXPIRED"
                ticket["expiry_reason"] = "NO_ELIGIBLE_CONTACT"
                db.touch(ticket)
                report["tickets_expired"] += 1
        else:
            if ticket.get("contact_deadline_at") is None or now < ticket["contact_deadline_at"]:
                continue
            ticket["stage"] = "EXPIRED"
            ticket["expiry_reason"] = "CONTACT_SLA_BREACH"
            db.touch(ticket)
            report["tickets_expired"] += 1

    # 3. lapsed transfers expire.
    for row in db.by_seq(list(db.transfers.values())):
        if row["status"] != "INITIATED" or now <= row["expires_at"]:
            continue
        row["status"] = "EXPIRED"
        db.touch(row)
        report["transfers_expired"] += 1
        device_row = db.devices.get(row["device_id"])
        if device_row is not None and device_row["lifecycle_state"] == "TRANSFER_PENDING":
            profile = db.profile_for_device(device_row["id"])
            complete = profile is not None and profile["learning_state"] == "COMPLETE"
            device_row["lifecycle_state"] = "ARMED" if complete else "LEARNING"
            device_row["baseline_ready"] = bool(complete)
            db.touch(device_row)
            prop = db.properties.get(device_row["property_id"])
            if prop is not None and prop["property_state"] == "TRANSFER_PENDING":
                prop["property_state"] = "ACTIVE"
                db.touch(prop)
    report["swept_at"] = now
    return report


# ================================================================= transfer accept
def accept_transfer(transfer_row):
    now = clock.now()
    device_row = db.devices[transfer_row["device_id"]]
    prop = db.properties[device_row["property_id"]]

    transfer_row["status"] = "ACCEPTED"
    transfer_row["accepted_at"] = now
    transfer_row["accepted_by_user_id"] = transfer_row["to_homeowner_id"]
    db.touch(transfer_row)

    prop["homeowner_id"] = transfer_row["to_homeowner_id"]
    if prop["property_state"] == "TRANSFER_PENDING":
        prop["property_state"] = "ACTIVE"
    db.touch(prop)

    was_complete = invalidate_baseline(device_row, "OWNERSHIP_TRANSFER")
    device_row["lifecycle_state"] = "LEARNING"
    device_row["baseline_ready"] = False
    device_row["monitor_mode"] = "NORMAL"
    device_row["monitor_mode_updated_at"] = now
    device_row["vacation_started_at"] = None
    device_row["vacation_ends_at"] = None
    db.touch(device_row)
    if was_complete:
        suspend_policies_for_property(prop["id"], "OWNERSHIP_TRANSFER")
    return transfer_row


# ================================================================= account closure
def deactivate_account(homeowner_row):
    now = clock.now()
    homeowner_row["account_state"] = "DEACTIVATED"
    homeowner_row["deactivated_at"] = now
    db.touch(homeowner_row)

    for contact in db.contacts_for_homeowner(homeowner_row["id"]):
        if contact["status"] == "ACTIVE":
            contact["status"] = "REMOVED"
            db.touch(contact)

    for prop in db.properties_for_homeowner(homeowner_row["id"]):
        if prop["property_state"] != "ARCHIVED":
            prop["property_state"] = "ARCHIVED"
            prop["archived_at"] = now
            db.touch(prop)

        for w in db.windows_for_property(prop["id"]):
            if w["status"] in ("ACTIVE", "SUSPENDED_BY_SHUTOFF"):
                w["status"] = "CANCELLED"
                db.touch(w)

        for device_row in db.devices_for_property(prop["id"]):
            if device_row["lifecycle_state"] != "DECOMMISSIONED":
                device_row["lifecycle_state"] = "DECOMMISSIONED"
                device_row["decommissioned_at"] = now
                device_row["valve_state"] = "CLOSED"
                device_row["monitor_mode"] = "NORMAL"
                device_row["baseline_ready"] = False
                db.touch(device_row)

            profile = db.profile_for_device(device_row["id"])
            if profile is not None and profile["learning_state"] == "COMPLETE":
                profile["learning_state"] = "INVALIDATED"
                profile["completed_at"] = None
                db.touch(profile)

            for event in db.events_for_device(device_row["id"]):
                if event["event_state"] in (
                    "DETECTED",
                    "ALERTED",
                    "ESCALATED",
                    "SUPPRESSED",
                ):
                    event["event_state"] = "RESOLVED"
                    event["resolved_at"] = now
                    event["resolution_note"] = "ACCOUNT_CLOSED"
                    db.touch(event)
                ticket = db.ticket_for_event(event["id"])
                if ticket is not None and ticket["stage"] in (
                    "PENDING_HOMEOWNER",
                    "PENDING_EMERGENCY_CONTACT",
                ):
                    ticket["stage"] = "EXPIRED"
                    ticket["expiry_reason"] = "ACCOUNT_DEACTIVATED"
                    db.touch(ticket)

            for claim_row in db.claims_for_device(device_row["id"]):
                if claim_row["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"):
                    claim_row["status"] = "DENIED"
                    claim_row["denial_reason"] = "ACCOUNT_CLOSED"
                    claim_row["decided_at"] = now
                    db.touch(claim_row)

            for row in db.transfers_for_device(device_row["id"]):
                if row["status"] == "INITIATED":
                    row["status"] = "CANCELLED"
                    row["cancel_reason"] = "ACCOUNT_DEACTIVATED"
                    db.touch(row)

        for policy_row in db.policies_for_property(prop["id"]):
            if policy_row["credit_state"] != "TERMINATED":
                policy_row["credit_state"] = "TERMINATED"
                policy_row["current_credit_tier_pct"] = D("0")
                db.touch(policy_row)
            for att in db.attestations_for_policy(policy_row["id"]):
                if att["status"] == "OPEN":
                    att["status"] = "FINALIZED_DENIED"
                    att["denial_reason"] = "ACCOUNT_CLOSED"
                    att["finalized_at"] = now
                    db.touch(att)
    return homeowner_row


def account_has_approved_claim(homeowner_id):
    for prop in db.properties_for_homeowner(homeowner_id):
        for device_row in db.devices_for_property(prop["id"]):
            for claim_row in db.claims_for_device(device_row["id"]):
                if claim_row["status"] == "APPROVED":
                    return True
    for claim_row in db.claims.values():
        if claim_row["submitted_by_user_id"] == homeowner_id and claim_row["status"] == "APPROVED":
            return True
    return False
