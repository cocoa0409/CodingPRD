"""PSPS event lifecycle: scoping, arming, de-energization, restoration, cancel."""

from collections import deque
from decimal import Decimal

import clock
import db
from errors import ApiError
from services import calc
from services.calc import D, ONE, ZERO, q, rhu

TERMINAL_EVENT_STATES = ("CLOSED", "CANCELLED")


# --------------------------------------------------------------------- helpers
def scopes_of(event):
    return db.in_order(
        [s for s in db.event_scopes.values() if s["psps_event_id"] == event["id"]]
    )


def confirmed_scopes(event):
    return [s for s in scopes_of(event) if s["scope_status"] == "CONFIRMED"]


def batches_of(event):
    return db.in_order(
        [b for b in db.notification_batches.values() if b["psps_event_id"] == event["id"]]
    )


def centers_of(event):
    return db.in_order(
        [c for c in db.resource_centers.values() if c.get("psps_event_id") == event["id"]]
    )


def patrols_of(event):
    return db.in_order(
        [p for p in db.patrol_assignments.values() if p["psps_event_id"] == event["id"]]
    )


def assert_not_terminal(event):
    """Any state-advancing call on a CLOSED or CANCELLED event is refused."""
    if event["scope_status"] in TERMINAL_EVENT_STATES:
        raise ApiError(
            "ERR_EVENT_TERMINAL",
            "The event is already %s." % event["scope_status"],
        )


def new_event_defaults(event):
    event["scope_status"] = "DRAFT"
    event["notification_status"] = "NOT_STARTED"
    event["cancellation_reason"] = None
    event["actual_de_energized_at"] = None
    event["actual_restored_at"] = None
    event["duration_hours"] = 0
    event["benefit_variant"] = "PRE_EVENT"
    event["confirmed_scope_count"] = 0
    event["excluded_scope_count"] = 0
    event["impacted_customer_count"] = 0
    event["medical_baseline_customer_count"] = 0
    event["critical_facility_count"] = 0
    event["ignition_risk_avoided_score"] = Decimal("0.00")
    event["customer_impact_score"] = Decimal("0.00")
    event["crc_capacity_required"] = 0
    event["crc_capacity_served"] = 0
    event["crc_mitigation_credit"] = Decimal("0.00")
    event["adjusted_customer_impact_score"] = Decimal("0.00")
    event["net_benefit_ratio"] = Decimal("0.0000")
    return event


# ------------------------------------------------------- aggregate recomputes
def recompute_counts(event):
    scopes = scopes_of(event)
    confirmed = [s for s in scopes if s["scope_status"] == "CONFIRMED"]
    excluded = [s for s in scopes if s["scope_status"] == "EXCLUDED"]
    event["confirmed_scope_count"] = len(confirmed)
    event["excluded_scope_count"] = len(excluded)
    impacted = 0
    medical = 0
    critical = 0
    for scope in confirmed:
        impacted += int(scope["customer_count_snapshot"])
        circuit = db.circuits.get(scope["circuit_id"])
        if circuit is not None:
            medical += int(circuit["medical_baseline_count"])
            critical += int(circuit["critical_facility_count"])
    event["impacted_customer_count"] = impacted
    event["medical_baseline_customer_count"] = medical
    event["critical_facility_count"] = critical
    event["crc_capacity_required"] = medical + critical


def recompute_ignition_risk(event):
    """C5 - per-row terms rounded to 2dp, then summed exactly."""
    total = ZERO
    for scope in scopes_of(event):
        if scope["scope_status"] == "CONFIRMED":
            circuit = db.circuits.get(scope["circuit_id"])
            term = rhu(
                D(scope["fpi_score_applied"])
                * D(circuit["overhead_miles"])
                * (ONE - D(circuit["hardened_fraction"]))
                / Decimal("100"),
                2,
            )
        else:
            term = Decimal("0.00")
        if scope["ignition_risk_term"] != term:
            scope["ignition_risk_term"] = term
            db.touch(scope)
        total += term
    event["ignition_risk_avoided_score"] = q(total, 2)


def recompute_crc_capacity_served(event):
    served = 0
    for center in db.resource_centers.values():
        if center.get("psps_event_id") == event["id"] and center["status"] == "ACTIVATED":
            served += int(center["site_capacity"])
    event["crc_capacity_served"] = served


def recompute_net_benefit(event):
    """C6 - executed strictly in the pinned order."""
    if event["benefit_variant"] == "POST_EVENT":
        window_start = event.get("actual_de_energized_at")
        window_end = event.get("actual_restored_at")
    else:
        window_start = event.get("forecast_onset_at")
        window_end = event.get("forecast_all_clear_at")

    if window_start is None or window_end is None:
        duration = 0
    else:
        duration = calc.ceil_hours(window_start, window_end)
    event["duration_hours"] = duration

    base = (
        D(event["impacted_customer_count"])
        + calc.MEDICAL_BASELINE_WEIGHT * D(event["medical_baseline_customer_count"])
        + calc.CRITICAL_FACILITY_WEIGHT * D(event["critical_facility_count"])
    )
    impact = rhu(base * D(duration) / calc.IMPACT_DIVISOR, 2)
    event["customer_impact_score"] = impact

    credit_rate = calc.CRC_CREDIT_TOP_RATE
    for break_point, rate in calc.CRC_CREDIT_BANDS:
        if impact < break_point:
            credit_rate = rate
            break

    required = int(event["crc_capacity_required"])
    served = int(event["crc_capacity_served"])
    coverage = min(ONE, D(served) / D(max(1, required)))
    credit = rhu(impact * credit_rate * coverage, 2)
    event["crc_mitigation_credit"] = credit

    adjusted = rhu(impact - credit, 2)
    event["adjusted_customer_impact_score"] = adjusted

    denominator = max(calc.MIN_ADJUSTED_IMPACT, adjusted)
    event["net_benefit_ratio"] = rhu(
        D(event["ignition_risk_avoided_score"]) / denominator, 4
    )


def refresh_event_metrics(event):
    recompute_counts(event)
    recompute_ignition_risk(event)
    recompute_crc_capacity_served(event)
    recompute_net_benefit(event)


# ------------------------------------------------------- C4 scope determination
def _qualifying_index(circuit, target_date):
    rows = [
        i
        for i in db.fire_potential_indices.values()
        if i["circuit_id"] == circuit["id"]
        and i["computation_variant"] == "FORECAST"
        and i["forecast_date"] == target_date
    ]
    return db.newest(rows)


def determine_scope(event):
    target_date = event["forecast_onset_at"].strftime("%Y-%m-%d")
    circuits = db.in_order(db.circuits.values())

    # Step 1/2 - primary risk set.
    planned = []
    in_scope = set()
    primary_fpi = {}
    confirmed_primary = []
    qualifying = []
    for circuit in circuits:
        if circuit["energization_state"] != "ENERGIZED":
            continue
        index = _qualifying_index(circuit, target_date)
        if index is None or index["fpi_tier"] not in ("R4", "R5"):
            continue
        qualifying.append((circuit, index))

    if not qualifying:
        raise ApiError(
            "ERR_NO_QUALIFYING_CIRCUITS",
            "No energized circuit carries an R4 or R5 forecast index for the onset date.",
        )

    for circuit, index in qualifying:
        primary_fpi[circuit["id"]] = index["fpi_score"]
        in_scope.add(circuit["id"])
        if circuit["fast_trip_enabled"] and index["fpi_tier"] == "R4":
            planned.append(
                {
                    "circuit": circuit,
                    "inclusion_basis": "PRIMARY_RISK",
                    "scope_status": "EXCLUDED",
                    "exclusion_justification": "FAST_TRIP_MITIGATED_R4",
                    "fpi_score_applied": index["fpi_score"],
                }
            )
        else:
            planned.append(
                {
                    "circuit": circuit,
                    "inclusion_basis": "PRIMARY_RISK",
                    "scope_status": "CONFIRMED",
                    "exclusion_justification": None,
                    "fpi_score_applied": index["fpi_score"],
                }
            )
            confirmed_primary.append(circuit)

    # Step 3 - breadth-first downstream closure.
    queue = deque(confirmed_primary)
    while queue:
        parent = queue.popleft()
        for child in circuits:
            if child["upstream_circuit_id"] != parent["id"]:
                continue
            if child["energization_state"] != "ENERGIZED":
                continue
            if child["id"] in in_scope:
                continue
            inherited = _inherited_fpi(child, primary_fpi)
            planned.append(
                {
                    "circuit": child,
                    "inclusion_basis": "DOWNSTREAM_DEPENDENCY",
                    "scope_status": "CONFIRMED",
                    "exclusion_justification": None,
                    "fpi_score_applied": inherited,
                }
            )
            in_scope.add(child["id"])
            queue.append(child)

    # Step 4 - window conflict guard across the whole candidate set.
    for candidate in planned:
        _assert_no_window_conflict(event, candidate["circuit"])

    # Step 5 - commit.
    previous = scopes_of(event)
    previously_confirmed = set(
        s["circuit_id"] for s in previous if s["scope_status"] == "CONFIRMED"
    )
    for scope in previous:
        db.event_scopes.pop(scope["id"], None)

    now_confirmed = set(
        p["circuit"]["id"] for p in planned if p["scope_status"] == "CONFIRMED"
    )
    for circuit_id in previously_confirmed - now_confirmed:
        circuit = db.circuits.get(circuit_id)
        if circuit is not None and circuit["energization_state"] == "DE_ENERGIZATION_PENDING":
            circuit["energization_state"] = "ENERGIZED"
            calc.recompute_risk_posture(circuit)
            db.touch(circuit)

    for candidate in planned:
        circuit = candidate["circuit"]
        row = db.new_row()
        row["psps_event_id"] = event["id"]
        row["circuit_id"] = circuit["id"]
        row["inclusion_basis"] = candidate["inclusion_basis"]
        row["scope_status"] = candidate["scope_status"]
        row["exclusion_justification"] = candidate["exclusion_justification"]
        row["customer_count_snapshot"] = int(circuit["customer_count"])
        row["fpi_score_applied"] = candidate["fpi_score_applied"]
        row["ignition_risk_term"] = Decimal("0.00")
        row["restored_at"] = None
        db.event_scopes[row["id"]] = row

    event["scope_status"] = "SCOPED"
    refresh_event_metrics(event)
    db.touch(event)


def _inherited_fpi(circuit, primary_fpi):
    seen = set()
    current = circuit
    while current is not None and current["id"] not in seen:
        seen.add(current["id"])
        upstream_id = current["upstream_circuit_id"]
        if upstream_id is None:
            return None
        if upstream_id in primary_fpi:
            return primary_fpi[upstream_id]
        current = db.circuits.get(upstream_id)
    return None


def _assert_no_window_conflict(event, circuit):
    for scope in db.event_scopes.values():
        if scope["circuit_id"] != circuit["id"]:
            continue
        if scope["scope_status"] != "CONFIRMED":
            continue
        if scope["psps_event_id"] == event["id"]:
            continue
        other = db.psps_events.get(scope["psps_event_id"])
        if other is None or other["scope_status"] not in calc.LIVE_EVENT_STATES:
            continue
        if (
            other["forecast_onset_at"] < event["forecast_all_clear_at"]
            and event["forecast_onset_at"] < other["forecast_all_clear_at"]
        ):
            raise ApiError(
                "ERR_CIRCUIT_WINDOW_CONFLICT",
                "Circuit %s is already held by an overlapping event window." % circuit["circuit_code"],
            )


# ----------------------------------------------------------------- transitions
def arm(event):
    for scope in confirmed_scopes(event):
        circuit = db.circuits.get(scope["circuit_id"])
        if circuit is None or circuit["energization_state"] != "ENERGIZED":
            continue
        circuit["energization_state"] = "DE_ENERGIZATION_PENDING"
        calc.recompute_risk_posture(circuit)
        db.touch(circuit)
    event["scope_status"] = "ARMED"
    db.touch(event)


def de_energize(event):
    stamp = clock.now()
    db.set_dt(event, "actual_de_energized_at", stamp)
    for scope in confirmed_scopes(event):
        circuit = db.circuits.get(scope["circuit_id"])
        if circuit is None or circuit["energization_state"] != "DE_ENERGIZATION_PENDING":
            continue
        circuit["energization_state"] = "DE_ENERGIZED"
        calc.recompute_risk_posture(circuit)
        db.touch(circuit)
        for project in db.in_order(calc.circuit_projects(circuit)):
            if project["status"] == "IN_EXECUTION":
                project["status"] = "SUSPENDED"
                db.touch(project)
    event["scope_status"] = "ACTIVE"
    db.touch(event)


def all_clear(event):
    event["scope_status"] = "RESTORING"
    db.touch(event)


def close(event):
    event["scope_status"] = "CLOSED"
    demobilize_centers(event)
    db.touch(event)


def cancel(event, reason):
    previous_state = event["scope_status"]
    event["cancellation_reason"] = reason
    if previous_state in ("SCOPED", "ARMED"):
        for scope in confirmed_scopes(event):
            scope["scope_status"] = "EXCLUDED"
            scope["exclusion_justification"] = "EVENT_CANCELLED"
            scope["ignition_risk_term"] = Decimal("0.00")
            db.touch(scope)
            circuit = db.circuits.get(scope["circuit_id"])
            if (
                circuit is not None
                and circuit["energization_state"] == "DE_ENERGIZATION_PENDING"
            ):
                circuit["energization_state"] = "ENERGIZED"
                calc.recompute_risk_posture(circuit)
                db.touch(circuit)
        # Every computed roll-up keeps matching the rows it is defined over.
        refresh_event_metrics(event)
    demobilize_centers(event)
    abort_patrols(patrols_of(event))
    event["scope_status"] = "CANCELLED"
    db.touch(event)


def demobilize_centers(event):
    demobilized = False
    for center in centers_of(event):
        if center["status"] != "ACTIVATED":
            continue
        center["status"] = "DEMOBILIZED"
        db.set_dt(center, "demobilized_at", clock.now())
        db.touch(center)
        demobilized = True
    if demobilized:
        recompute_crc_capacity_served(event)
        recompute_net_benefit(event)
        db.touch(event)
    return demobilized


def abort_patrols(assignments):
    for assignment in assignments:
        if assignment["status"] in ("SCHEDULED", "IN_PROGRESS"):
            assignment["status"] = "ABORTED"
            db.touch(assignment)


# ---------------------------------------------------------------- re-energize
def governing_event_for_circuit(circuit):
    candidates = [
        s
        for s in db.event_scopes.values()
        if s["circuit_id"] == circuit["id"]
        and s["scope_status"] == "CONFIRMED"
        and s.get("restored_at") is None
    ]
    if not candidates:
        return None, None
    ordered = sorted(
        candidates, key=lambda s: (s["created_at"], s["_seq"]), reverse=True
    )
    for state_group in (("RESTORING",), calc.LIVE_EVENT_STATES):
        for scope in ordered:
            event = db.psps_events.get(scope["psps_event_id"])
            if event is not None and event["scope_status"] in state_group:
                return event, scope
    scope = ordered[0]
    return db.psps_events.get(scope["psps_event_id"]), scope


def re_energize(circuit, event, scope):
    circuit["energization_state"] = "ENERGIZED"
    calc.recompute_risk_posture(circuit)
    db.touch(circuit)

    for project in db.in_order(calc.circuit_projects(circuit)):
        if project["status"] == "SUSPENDED":
            project["status"] = "IN_EXECUTION"
            db.touch(project)

    db.set_dt(scope, "restored_at", clock.now())
    db.touch(scope)

    remaining = [s for s in confirmed_scopes(event) if s.get("restored_at") is None]
    if not remaining:
        db.set_dt(event, "actual_restored_at", clock.now())
        event["benefit_variant"] = "POST_EVENT"
        recompute_net_benefit(event)
        db.touch(event)
        demobilize_centers(event)

    abort_patrols(
        db.in_order(
            [
                p
                for p in db.patrol_assignments.values()
                if p["circuit_id"] == circuit["id"]
            ]
        )
    )
