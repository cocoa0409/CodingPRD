"""Domain derivations: health, topology posture, SPOF, incident classification,
correlation, restoration clocks, credits, availability, capacity, ledgers and
the vendor scorecard.
"""

from datetime import timedelta
from decimal import Decimal

import db
from calc import (
    cents,
    ceil_div,
    dec,
    intersect_unions,
    merge_intervals,
    rhu,
    union_minutes,
    upgrade_cost,
)
from consts import (
    BANDWIDTH_LADDER_MBPS,
    CHRONIC_CANDIDATE_FAULTS,
    CHRONIC_FAULTS,
    CHRONIC_WINDOW_DAYS,
    COMMITTED_ORDER_STATES,
    CONSECUTIVE_HIGH_READINGS_FOR_UPGRADE,
    CORRELATION_WINDOW_SECONDS,
    CREDIT_RATIO_WEIGHT,
    CHRONIC_WEIGHT,
    ESCALATION_MINUTES,
    HIGH_UTILIZATION_PCT,
    INCIDENT_REOPEN_WINDOW_MINUTES,
    LEG_GROUPS,
    MTTR_HOURS_CAP,
    MTTR_WEIGHT,
    OPEN_CLAIM_STATES,
    RESPONSE_MINUTES,
    SEVERITY_RANK,
    TIER_WEIGHT,
)
from db import base_record, now, rows, touch
from timeutil import minutes_between, seconds_between, truncate_seconds

# --------------------------------------------------------------------------
# segment / leg helpers
# --------------------------------------------------------------------------


def active_segments(path_id):
    return [
        s
        for s in rows(db.db.segments)
        if s["application_path_id"] == path_id and s["segment_state"] == "ACTIVE"
    ]


def segment_target(segment):
    if segment.get("circuit_id"):
        return db.db.circuits.get(segment["circuit_id"])
    if segment.get("device_id"):
        return db.db.devices.get(segment["device_id"])
    return None


def segment_target_up(segment):
    target = segment_target(segment)
    if target is None:
        return False
    if segment.get("circuit_id"):
        return target["operational_state"] != "DOWN"
    return target["operational_state"] == "UP"


def segment_target_monitored(segment):
    target = segment_target(segment)
    return target is not None and target["monitoring_state"] == "MONITORED"


def leg_groups_present(segments):
    return [group for group in LEG_GROUPS if any(s["leg_group"] == group for s in segments)]


def leg_under_test(path_id, leg_group):
    """A leg being exercised by an in-progress failover test counts as unavailable."""
    for test in db.db.failover_tests.values():
        if (
            test["application_path_id"] == path_id
            and test["state"] == "IN_PROGRESS"
            and test["tested_leg_group"] == leg_group
        ):
            return True
    return False


def leg_is_up(path_id, leg_group, segments):
    if leg_under_test(path_id, leg_group):
        return False
    return all(
        segment_target_up(s) for s in segments if s["leg_group"] == leg_group
    )


# --------------------------------------------------------------------------
# source health
# --------------------------------------------------------------------------


def uncleared_root_alarms_for_circuit(circuit_id):
    return [
        a
        for a in rows(db.db.alarms)
        if a["source_circuit_id"] == circuit_id
        and a["correlation_state"] == "ROOT"
        and a["cleared_at"] is None
    ]


def uncleared_root_alarms_for_device(device_id):
    return [
        a
        for a in rows(db.db.alarms)
        if a["source_device_id"] == device_id
        and a["correlation_state"] == "ROOT"
        and a["cleared_at"] is None
    ]


def circuit_operational_state(circuit_id):
    alarms = uncleared_root_alarms_for_circuit(circuit_id)
    if any(a["raw_severity"] == "CRITICAL" for a in alarms):
        return "DOWN"
    if any(a["raw_severity"] in ("MAJOR", "MINOR") for a in alarms):
        return "DEGRADED"
    return "UP"


def device_operational_state(device_id):
    alarms = uncleared_root_alarms_for_device(device_id)
    for alarm in alarms:
        if alarm["raw_severity"] == "CRITICAL" or alarm["alarm_type"] == "DEVICE_UNREACHABLE":
            return "DOWN"
    return "UP"


def refresh_source_health(circuit_ids=(), device_ids=()):
    for circuit_id in circuit_ids:
        circuit = db.db.circuits.get(circuit_id)
        if circuit is None:
            continue
        state = circuit_operational_state(circuit_id)
        if circuit["operational_state"] != state:
            circuit["operational_state"] = state
            touch(circuit)
    for device_id in device_ids:
        device = db.db.devices.get(device_id)
        if device is None:
            continue
        state = device_operational_state(device_id)
        if device["operational_state"] != state:
            device["operational_state"] = state
            touch(device)


# --------------------------------------------------------------------------
# path posture / SPOF
# --------------------------------------------------------------------------


def path_posture_and_legs(path):
    segments = active_segments(path["id"])
    legs = leg_groups_present(segments)
    active_leg_count = len(legs)
    healthy = [g for g in legs if leg_is_up(path["id"], g, segments)]
    healthy_leg_count = len(healthy)
    monitored_segment_count = sum(1 for s in segments if segment_target_monitored(s))
    minimum = path["min_surviving_legs"]

    if active_leg_count == 0:
        posture = "PROTECTED"
    elif healthy_leg_count == 0:
        posture = "DOWN"
    elif healthy_leg_count < minimum:
        posture = "DOWN"
    elif healthy_leg_count == active_leg_count:
        posture = "PROTECTED"
    elif healthy_leg_count > minimum:
        posture = "DEGRADED_REDUNDANT"
    else:
        posture = "DEGRADED_NO_REDUNDANCY"
    return posture, active_leg_count, healthy_leg_count, monitored_segment_count


def recompute_path(path):
    posture, active_legs, healthy_legs, monitored = path_posture_and_legs(path)
    changed = (
        path["posture"] != posture
        or path["active_leg_count"] != active_legs
        or path["healthy_leg_count"] != healthy_legs
        or path["monitored_segment_count"] != monitored
    )
    path["posture"] = posture
    path["active_leg_count"] = active_legs
    path["healthy_leg_count"] = healthy_legs
    path["monitored_segment_count"] = monitored
    if changed:
        touch(path)
    return changed


def recompute_all_paths():
    for path in rows(db.db.paths):
        recompute_path(path)


def recompute_spof_flags():
    flags = {circuit_id: False for circuit_id in db.db.circuits}
    for path in rows(db.db.paths):
        if path["posture"] != "DEGRADED_NO_REDUNDANCY":
            continue
        segments = active_segments(path["id"])
        for group in leg_groups_present(segments):
            if not leg_is_up(path["id"], group, segments):
                continue
            for segment in segments:
                if segment["leg_group"] == group and segment.get("circuit_id"):
                    if segment["circuit_id"] in flags:
                        flags[segment["circuit_id"]] = True
    for circuit_id, flag in flags.items():
        circuit = db.db.circuits[circuit_id]
        if circuit["spof_flag"] != flag:
            circuit["spof_flag"] = flag
            touch(circuit)


def recompute_topology():
    recompute_all_paths()
    recompute_spof_flags()


def cascade_health(circuit_ids=(), device_ids=()):
    refresh_source_health(circuit_ids, device_ids)
    recompute_topology()


# --------------------------------------------------------------------------
# incident classification
# --------------------------------------------------------------------------


def affected_paths(circuit_id):
    """Paths carrying an ACTIVE segment whose circuit_id is this circuit."""
    result = []
    for path in rows(db.db.paths):
        segments = active_segments(path["id"])
        if any(s.get("circuit_id") == circuit_id for s in segments):
            result.append(path)
    return result


def severity_for_score(score):
    if score >= 50:
        return "SEV1"
    if score >= 30:
        return "SEV2"
    if score >= 12:
        return "SEV3"
    return "SEV4"


def impact_score_for_circuit(circuit_id):
    paths = affected_paths(circuit_id)
    tier_max = max((TIER_WEIGHT[p["service_tier"]] for p in paths), default=0)
    path_count_term = min(len(paths), 5) * 2
    worst_healthy_legs = min((p["healthy_leg_count"] for p in paths), default=99)
    if worst_healthy_legs == 0:
        redundancy_term = 8
    elif worst_healthy_legs == 1:
        redundancy_term = 4
    else:
        redundancy_term = 0
    circuit = db.db.circuits.get(circuit_id)
    spof_term = 3 if circuit is not None and circuit["spof_flag"] else 0
    score = tier_max * 10 + path_count_term + redundancy_term + spof_term
    return score, len(paths)


def apply_classification(incident, ratchet):
    score, path_count = impact_score_for_circuit(incident["primary_circuit_id"])
    if ratchet:
        score = max(score, incident["impact_score"])
    severity = severity_for_score(score)
    if ratchet and incident.get("severity"):
        if SEVERITY_RANK[incident["severity"]] < SEVERITY_RANK[severity]:
            severity = incident["severity"]
    incident["severity"] = severity
    incident["impact_score"] = score
    incident["affected_path_count"] = path_count
    incident["response_due_at"] = incident["detected_at"] + timedelta(
        minutes=RESPONSE_MINUTES[severity]
    )
    incident["escalation_due_at"] = incident["detected_at"] + timedelta(
        minutes=ESCALATION_MINUTES[severity]
    )


def open_incident_for_circuit(circuit_id):
    candidates = [
        i
        for i in rows(db.db.incidents)
        if i["primary_circuit_id"] == circuit_id and i["response_state"] != "RESOLVED"
    ]
    return candidates[-1] if candidates else None


def reopenable_incident_for_circuit(circuit_id):
    instant = now()
    best = None
    for incident in rows(db.db.incidents):
        if incident["primary_circuit_id"] != circuit_id:
            continue
        if incident["response_state"] != "RESOLVED" or incident["resolved_at"] is None:
            continue
        elapsed = minutes_between(incident["resolved_at"], instant)
        if elapsed < 0 or elapsed > INCIDENT_REOPEN_WINDOW_MINUTES:
            continue
        if best is None or incident["resolved_at"] >= best["resolved_at"]:
            best = incident
    return best


def new_incident(circuit_id, root_alarm_id):
    instant = now()
    incident = base_record()
    incident.update(
        {
            "primary_circuit_id": circuit_id,
            "root_alarm_id": root_alarm_id,
            "severity": "SEV4",
            "impact_score": 0,
            "response_state": "DETECTED",
            "escalation_state": "NONE",
            "detected_at": instant,
            "triaged_at": None,
            "mitigated_at": None,
            "resolved_at": None,
            "response_due_at": None,
            "escalation_due_at": None,
            "affected_path_count": 0,
            "alarm_count": 1,
            "reopen_count": 0,
        }
    )
    apply_classification(incident, ratchet=False)
    db.db.incidents[incident["id"]] = incident
    circuit = db.db.circuits.get(circuit_id)
    if circuit is not None:
        circuit["last_incident_at"] = incident["detected_at"]
        touch(circuit)
    return incident


def attach_or_open_incident(alarm, anchor_circuit_id):
    """Third and last cascade step for a stored ROOT alarm."""
    if anchor_circuit_id is None or anchor_circuit_id not in db.db.circuits:
        return None
    incident = open_incident_for_circuit(anchor_circuit_id)
    if incident is not None:
        incident["alarm_count"] = incident["alarm_count"] + 1
        apply_classification(incident, ratchet=True)
        touch(incident)
        alarm["incident_id"] = incident["id"]
        return incident
    incident = reopenable_incident_for_circuit(anchor_circuit_id)
    if incident is not None:
        incident["response_state"] = "TRIAGED"
        incident["resolved_at"] = None
        incident["reopen_count"] = incident["reopen_count"] + 1
        incident["alarm_count"] = incident["alarm_count"] + 1
        apply_classification(incident, ratchet=True)
        touch(incident)
        alarm["incident_id"] = incident["id"]
        return incident
    incident = new_incident(anchor_circuit_id, alarm["id"])
    alarm["incident_id"] = incident["id"]
    return incident


def attach_suppressed_alarm(alarm, parent):
    """A suppressed alarm inherits the parent's incident and counts against it."""
    incident_id = parent.get("incident_id")
    alarm["incident_id"] = incident_id
    if not incident_id:
        return None
    incident = db.db.incidents.get(incident_id)
    if incident is None:
        return None
    incident["alarm_count"] = incident["alarm_count"] + 1
    apply_classification(incident, ratchet=True)
    touch(incident)
    return incident


# --------------------------------------------------------------------------
# alarm correlation
# --------------------------------------------------------------------------


def anchor_circuit_id(alarm):
    if alarm.get("source_circuit_id"):
        return alarm["source_circuit_id"]
    device = db.db.devices.get(alarm.get("source_device_id"))
    if device is None:
        return None
    return device.get("primary_uplink_circuit_id")


def correlation_candidates(alarm):
    circuit_id = anchor_circuit_id(alarm)
    if circuit_id is None:
        return []
    raised_at = alarm["raised_at"]
    candidates = []
    for other in rows(db.db.alarms):
        if other["id"] == alarm["id"]:
            continue
        if other["source_circuit_id"] != circuit_id:
            continue
        if other["correlation_state"] != "ROOT" or other["cleared_at"] is not None:
            continue
        if other["raised_at"] > raised_at:
            continue
        delta = seconds_between(
            truncate_seconds(other["raised_at"]), truncate_seconds(raised_at)
        )
        if delta > CORRELATION_WINDOW_SECONDS:
            continue
        candidates.append(other)
    candidates.sort(key=lambda a: (a["raised_at"], -a["_seq"]), reverse=True)
    return candidates


def choose_correlation_parent(alarm):
    candidates = correlation_candidates(alarm)
    return candidates[0] if candidates else None


# --------------------------------------------------------------------------
# restoration clocks
# --------------------------------------------------------------------------


def carrier_notified_exclusions(circuit_id):
    windows = [
        w
        for w in rows(db.db.windows)
        if w["circuit_id"] == circuit_id
        and w["origin"] == "CARRIER_NOTIFIED"
        and w["state"] in ("APPROVED", "IN_PROGRESS", "COMPLETED")
    ]
    return merge_intervals([(w["window_start"], w["window_end"]) for w in windows])


def restoration_clocks(ticket, restored_at):
    """Returns (noc_minutes, carrier_minutes, excluded_minutes) each 2dp."""
    incident = db.db.incidents.get(ticket["incident_id"])
    if incident is not None:
        noc = minutes_between(incident["detected_at"], restored_at)
    else:
        noc = minutes_between(ticket["opened_at"], restored_at)
    raw = minutes_between(ticket["opened_at"], restored_at)
    excluded = Decimal(0)
    for start, end in carrier_notified_exclusions(ticket["circuit_id"]):
        overlap_start = max(start, ticket["opened_at"])
        overlap_end = min(end, restored_at)
        if overlap_end > overlap_start:
            excluded += minutes_between(overlap_start, overlap_end)
    return rhu(noc, 2), rhu(raw - excluded, 2), rhu(excluded, 2)


# --------------------------------------------------------------------------
# SLA credit
# --------------------------------------------------------------------------


def credit_figures(ticket, basis):
    carrier = db.db.carriers.get(ticket["carrier_id"])
    circuit = db.db.circuits.get(ticket["circuit_id"])
    incident = db.db.incidents.get(ticket["incident_id"])
    severity = incident["severity"] if incident is not None else "SEV4"
    if severity in ("SEV1", "SEV2"):
        target = carrier["sla_restore_minutes_critical"]
    else:
        target = carrier["sla_restore_minutes_standard"]

    if basis == "NOC_CLOCK":
        restoration = ticket.get("restoration_minutes_noc_clock")
    else:
        restoration = ticket.get("restoration_minutes_carrier_clock")
    restoration = dec(restoration if restoration is not None else 0)

    breach = restoration - dec(target)
    if breach < 0:
        breach = Decimal(0)
    breach = rhu(breach, 2)
    breach_hours = 0 if breach == 0 else ceil_div(breach, 60)

    credit_pct = dec(carrier["credit_pct_per_breach_hour"]) * dec(breach_hours)
    cap_pct = dec(carrier["credit_pct_cap"])
    if credit_pct > cap_pct:
        credit_pct = cap_pct

    mrc = dec(circuit["mrc_cents"])
    paths = affected_paths(circuit["id"])
    total_weight = sum(TIER_WEIGHT[p["service_tier"]] for p in paths)
    if total_weight == 0:
        line_total = cents(mrc * credit_pct / Decimal(100))
    else:
        line_total = 0
        for path in paths:
            weight = dec(TIER_WEIGHT[path["service_tier"]])
            line_total += cents(mrc * weight / dec(total_weight) * credit_pct / Decimal(100))
    cap_cents = cents(mrc * cap_pct / Decimal(100))
    amount = min(line_total, cap_cents)
    return {
        "sla_target_minutes": int(target),
        "breach_minutes": breach,
        "breach_hours": int(breach_hours),
        "credit_amount_cents": int(amount),
    }


def apply_credit_figures(claim, ticket, basis):
    """(Re)computes the frozen credit arithmetic onto a claim under `basis`."""
    figures = credit_figures(ticket, basis)
    claim["basis"] = basis
    claim["sla_target_minutes"] = figures["sla_target_minutes"]
    claim["breach_minutes"] = figures["breach_minutes"]
    claim["breach_hours"] = figures["breach_hours"]
    claim["credit_amount_cents"] = figures["credit_amount_cents"]
    return claim


def build_claim(ticket, basis, origin):
    """Creates a DRAFT claim on the ticket; the caller recomputes the ledger."""
    claim = base_record()
    claim.update(
        {
            "carrier_ticket_id": ticket["id"],
            "carrier_id": ticket["carrier_id"],
            "basis": basis,
            "sla_target_minutes": 0,
            "breach_minutes": Decimal("0.00"),
            "breach_hours": 0,
            "credit_amount_cents": 0,
            "state": "DRAFT",
            "origin": origin,
            "submitted_by_user_id": None,
            "submitted_at": None,
            "paid_amount_cents": None,
            "rejection_reason": None,
            "revision_count": 0,
        }
    )
    apply_credit_figures(claim, ticket, basis)
    db.db.claims[claim["id"]] = claim
    return claim


# --------------------------------------------------------------------------
# availability
# --------------------------------------------------------------------------


def _availability_alarms(segment):
    if segment.get("circuit_id"):
        pool = [
            a
            for a in rows(db.db.alarms)
            if a["source_circuit_id"] == segment["circuit_id"]
        ]
    else:
        pool = [
            a for a in rows(db.db.alarms) if a["source_device_id"] == segment["device_id"]
        ]
    return [
        a
        for a in pool
        if a["correlation_state"] in ("ROOT", "CLEARED")
        and a["correlation_parent_alarm_id"] is None
        and a["raw_severity"] == "CRITICAL"
    ]


def availability_report(path, window_from, window_to, basis):
    instant = now()
    segments = active_segments(path["id"])
    legs = leg_groups_present(segments)
    period_minutes = minutes_between(window_from, window_to)

    leg_unions = {}
    for group in legs:
        intervals = []
        for segment in segments:
            if segment["leg_group"] != group:
                continue
            for alarm in _availability_alarms(segment):
                start = max(alarm["raised_at"], window_from)
                end = min(alarm["cleared_at"] or instant, window_to)
                if end > start:
                    intervals.append((start, end))
        leg_unions[group] = merge_intervals(intervals)

    leg_totals = {group: union_minutes(union) for group, union in leg_unions.items()}

    if not legs:
        path_down = Decimal(0)
    elif basis == "BEST_LEG":
        path_down = min(leg_totals.values())
    else:
        path_down = union_minutes(intersect_unions([leg_unions[g] for g in legs]))

    if period_minutes > 0:
        availability_pct = rhu(
            Decimal(100) * (Decimal(1) - (path_down / period_minutes)), 3
        )
    else:
        availability_pct = rhu(Decimal(100), 3)

    return {
        "basis": basis,
        "period_minutes": rhu(period_minutes, 2),
        "path_down_minutes": rhu(path_down, 2),
        "availability_pct": availability_pct,
        "leg_down_minutes": {group: rhu(total, 2) for group, total in leg_totals.items()},
    }


# --------------------------------------------------------------------------
# capacity
# --------------------------------------------------------------------------


def threshold_state_for(utilization_pct):
    return "HIGH" if dec(utilization_pct) >= dec(HIGH_UTILIZATION_PCT) else "NORMAL"


def capacity_state_for(consecutive_high):
    if consecutive_high >= CONSECUTIVE_HIGH_READINGS_FOR_UPGRADE:
        return "UPGRADE_REQUIRED"
    if consecutive_high >= 1:
        return "WATCH"
    return "NORMAL"


def next_ladder_rung(bandwidth_mbps):
    rungs = [r for r in BANDWIDTH_LADDER_MBPS if r > bandwidth_mbps]
    return min(rungs) if rungs else None


def build_order(circuit, target_mbps, expedite, origin, created_by_user_id):
    delta, subtotal, fee, total = upgrade_cost(circuit["bandwidth_mbps"], target_mbps, expedite)
    order = base_record()
    order.update(
        {
            "circuit_id": circuit["id"],
            "target_bandwidth_mbps": int(target_mbps),
            "delta_mbps": int(delta),
            "expedite": bool(expedite),
            "subtotal_cents": int(subtotal),
            "expedite_fee_cents": int(fee),
            "total_cost_cents": int(total),
            "state": "DRAFT",
            "origin": origin,
            "created_by_user_id": created_by_user_id,
            "approved_by_user_id": None,
            "cancel_reason": None,
        }
    )
    db.db.orders[order["id"]] = order
    return order


# --------------------------------------------------------------------------
# chronic fault accounting
# --------------------------------------------------------------------------


def recompute_chronic(circuit):
    cutoff = now() - timedelta(days=CHRONIC_WINDOW_DAYS)
    count = 0
    for incident in db.db.incidents.values():
        if incident["primary_circuit_id"] != circuit["id"]:
            continue
        if incident["response_state"] != "RESOLVED" or incident["resolved_at"] is None:
            continue
        if incident["resolved_at"] >= cutoff:
            count += 1
    circuit["fault_count_period"] = count
    if circuit["chronic_state"] != "REPLACEMENT_APPROVED":
        if count >= CHRONIC_FAULTS:
            circuit["chronic_state"] = "CHRONIC"
        elif count >= CHRONIC_CANDIDATE_FAULTS:
            circuit["chronic_state"] = "CHRONIC_CANDIDATE"
        else:
            circuit["chronic_state"] = "NORMAL"
    return count


# --------------------------------------------------------------------------
# carrier ledgers
# --------------------------------------------------------------------------


def recompute_exposure(carrier):
    total = 0
    for claim in db.db.claims.values():
        if claim["carrier_id"] == carrier["id"] and claim["state"] in OPEN_CLAIM_STATES:
            total += claim["credit_amount_cents"]
    carrier["open_credit_exposure_cents"] = total
    carrier["watchlist_state"] = (
        "WATCHLIST" if total >= carrier["watchlist_exposure_threshold_cents"] else "ACTIVE"
    )
    return total


def recompute_committed_upgrade(carrier):
    circuit_ids = {
        c["id"] for c in db.db.circuits.values() if c["carrier_id"] == carrier["id"]
    }
    total = 0
    for order in db.db.orders.values():
        if order["circuit_id"] in circuit_ids and order["state"] in COMMITTED_ORDER_STATES:
            total += order["delta_mbps"]
    carrier["committed_upgrade_mbps"] = total
    return total


def recompute_chronic_circuit_count(carrier):
    count = 0
    for circuit in db.db.circuits.values():
        if circuit["carrier_id"] != carrier["id"]:
            continue
        if circuit["chronic_state"] in ("CHRONIC", "REPLACEMENT_APPROVED"):
            count += 1
    carrier["chronic_circuit_count"] = count
    return count


# --------------------------------------------------------------------------
# vendor scorecard
# --------------------------------------------------------------------------


def vendor_scorecard(carrier, period_start, period_end):
    credited = 0
    for claim in db.db.claims.values():
        if claim["carrier_id"] != carrier["id"]:
            continue
        if claim["state"] not in ("ACKNOWLEDGED", "PAID"):
            continue
        submitted_at = claim.get("submitted_at")
        if submitted_at is None:
            continue
        if period_start <= submitted_at < period_end:
            credited += claim["credit_amount_cents"]

    base = 0
    for circuit in db.db.circuits.values():
        if circuit["carrier_id"] == carrier["id"] and circuit["created_at"] < period_end:
            base += circuit["mrc_cents"]

    if base == 0:
        credit_ratio = rhu(Decimal(0), 4)
    else:
        credit_ratio = rhu(dec(credited) / dec(base), 4)

    durations = []
    for ticket in db.db.tickets.values():
        if ticket["carrier_id"] != carrier["id"] or ticket["state"] != "CLOSED_RESTORED":
            continue
        confirmed_at = ticket.get("confirmed_at")
        if confirmed_at is None:
            continue
        if period_start <= confirmed_at < period_end:
            durations.append(dec(ticket.get("restoration_minutes_carrier_clock") or 0))
    if durations:
        mttr_minutes = rhu(sum(durations) / dec(len(durations)), 2)
    else:
        mttr_minutes = rhu(Decimal(0), 2)

    chronic_count = recompute_chronic_circuit_count(carrier)

    mttr_hours = mttr_minutes / Decimal(60)
    if mttr_hours > dec(MTTR_HOURS_CAP):
        mttr_hours = dec(MTTR_HOURS_CAP)
    raw = (
        Decimal(100)
        - (credit_ratio * Decimal(100) * dec(CREDIT_RATIO_WEIGHT))
        - (dec(chronic_count) * dec(CHRONIC_WEIGHT))
        - (mttr_hours * dec(MTTR_WEIGHT))
    )
    net = rhu(raw, 2)
    if net < 0:
        net = rhu(Decimal(0), 2)
    return {
        "chronic_circuit_count": chronic_count,
        "credit_ratio": credit_ratio,
        "mttr_minutes": mttr_minutes,
        "net_performance_score": net,
    }
