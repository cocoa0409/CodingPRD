"""Occupancy counter reconciliation + interval conflict calculations.

All datetime inputs here are aware UTC datetimes. Counters are integers.
"""
import db
import errors
import helpers

# Statuses that count as "live" on a gate for window-conflict purposes.
GATE_LIVE_STATUSES = {"PLANNED", "OCCUPIED", "TOWED_AWAY"}
# Statuses that count as "live" on a remote stand for capacity purposes.
REMOTE_LIVE_STATUSES = {"PLANNED", "OCCUPIED", "TOWED_AWAY"}


# ---------------------------------------------------------------------------
# Interval parsing for an assignment record (cache parsed datetimes lazily).
# ---------------------------------------------------------------------------


def _assignment_interval(a):
    return a["_start_dt"], a["_end_dt"]


# ---------------------------------------------------------------------------
# Gate window conflict (calc gate_window_conflict). Half-open base interval,
# buffer added to BOTH ends. conflict = (s < e2 + buffer) and (s2 < e + buffer).
# ---------------------------------------------------------------------------


def gate_window_conflicts(gate_id, s_dt, e_dt, buffer_minutes, exclude_id=None):
    buffer_sec = buffer_minutes * 60
    for a in db.gate_assignments.values():
        if a.get("gate_id") != gate_id:
            continue
        if a["status"] not in GATE_LIVE_STATUSES:
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        s2, e2 = _assignment_interval(a)
        # add buffer to both ends of the EXISTING window comparison
        if s_dt.timestamp() < e2.timestamp() + buffer_sec and \
           s2.timestamp() < e_dt.timestamp() + buffer_sec:
            return True
    return False


# ---------------------------------------------------------------------------
# Remote stand capacity overlap (calc remote_stand_capacity_overlap).
# Closed intervals [s, e]; touching endpoints collide. Sweep for max overlap.
# Live windows: rows whose primary remote_stand_id == stand_id, OR rows that are
# TOWED_AWAY with tow_target_stand_id == stand_id; status IN live set.
# ---------------------------------------------------------------------------


def _remote_live_windows(stand_id, exclude_id=None):
    windows = []
    for a in db.gate_assignments.values():
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        status = a["status"]
        if status not in REMOTE_LIVE_STATUSES:
            continue
        # primary occupant of this stand
        if a.get("stand_type") == "REMOTE" and a.get("remote_stand_id") == stand_id:
            windows.append(_assignment_interval(a))
        # towed-in occupant: a TOWED_AWAY gate assignment parked here
        elif status == "TOWED_AWAY" and a.get("tow_target_stand_id") == stand_id:
            windows.append(_assignment_interval(a))
    return windows


def remote_capacity_exceeded(stand_id, s_dt, e_dt, capacity, exclude_id=None,
                             extra_windows=None):
    """Return True if adding [s,e] to the live windows on this stand would push
    simultaneous closed-interval overlap above capacity.

    extra_windows: optional list of (s_dt, e_dt) already-counted occupants on
    this stand that are not yet persisted as primary rows (e.g. a tow target).
    """
    existing = _remote_live_windows(stand_id, exclude_id=exclude_id)
    if extra_windows:
        existing = existing + list(extra_windows)
    all_windows = existing + [(s_dt, e_dt)]
    # Sweep: at each window start, count how many windows (closed) contain it.
    s_target = s_dt.timestamp()
    e_target = e_dt.timestamp()
    # Candidate instants where max overlap can occur: every window start that
    # lies inside [s_target, e_target], plus s_target itself.
    candidate_instants = {s_target, e_target}
    for (ws, we) in all_windows:
        wts = ws.timestamp()
        if s_target <= wts <= e_target:
            candidate_instants.add(wts)
    max_overlap = 0
    for t in candidate_instants:
        count = 0
        for (ws, we) in all_windows:
            if ws.timestamp() <= t <= we.timestamp():
                count += 1
        if count > max_overlap:
            max_overlap = count
    return max_overlap > capacity


def remote_current_occupancy(stand_id):
    """Count of GateAssignment rows on this remote stand whose status == OCCUPIED,
    counting both primary-occupant rows and towed-in rows. Used for the tow
    capacity precondition (occupancy_count < capacity)."""
    return db.remote_stands[stand_id]["occupancy_count"]


# ---------------------------------------------------------------------------
# CUTE overlap (calc cute_overlap). Half-open, capacity 1, zero buffer.
# conflict = (s < e2) and (s2 < e), strict.
# ---------------------------------------------------------------------------


def cute_conflicts(cute_unit_id, s_dt, e_dt):
    s = s_dt.timestamp()
    e = e_dt.timestamp()
    for a in db.cute_allocations.values():
        if a.get("cute_unit_id") != cute_unit_id:
            continue
        if a["status"] != "HELD":
            continue
        s2 = a["_start_dt"].timestamp()
        e2 = a["_end_dt"].timestamp()
        if s < e2 and s2 < e:
            return True
    return False


# ---------------------------------------------------------------------------
# GSE cooldown overlap (calc equipment_cooldown_overlap). Half-open, one-sided
# cooldown of turnaround_minutes. conflict = not (s >= e2 + turn or s2 >= e + turn).
# ---------------------------------------------------------------------------


def gse_conflicts(equipment_id, s_dt, e_dt, turnaround_minutes):
    s = s_dt.timestamp()
    e = e_dt.timestamp()
    turn_sec = turnaround_minutes * 60
    for a in db.gse_allocations.values():
        if a.get("equipment_id") != equipment_id:
            continue
        if a["status"] != "HELD":
            continue
        s2 = a["_start_dt"].timestamp()
        e2 = a["_end_dt"].timestamp()
        # conflict when NOT separated by cooldown on the ordered pair
        if not (s >= e2 + turn_sec or s2 >= e + turn_sec):
            return True
    return False


# ---------------------------------------------------------------------------
# Counter increment helpers.
# ---------------------------------------------------------------------------


def inc_source_counter(assignment):
    """Increment the source stand's occupancy counter and bump that stand."""
    if assignment["stand_type"] == "GATE":
        gate = db.gates[assignment["gate_id"]]
        gate["active_assignment_count"] += 1
        db.touch(gate)
    else:
        stand = db.remote_stands[assignment["remote_stand_id"]]
        stand["occupancy_count"] += 1
        db.touch(stand)


def teardown_counters(assignment):
    """Pinned 3-step reconciliation (PRD §2.6 / calc occupancy_counter_reconcile).

    Step 1: if TOWED_AWAY, decrement tow target RemoteStand.occupancy_count, clear
            tow_target_stand_id.
    Step 2: decrement the source stand counter (Gate.active_assignment_count for
            GATE, else RemoteStand.occupancy_count).
    Caller sets the terminal status (step 3) afterwards.

    Only applies the decrements when the assignment was active
    (OCCUPIED or TOWED_AWAY). For a PLANNED assignment, nothing to decrement.
    """
    status = assignment["status"]
    if status == "TOWED_AWAY":
        target_id = assignment.get("tow_target_stand_id")
        if target_id is not None and target_id in db.remote_stands:
            target = db.remote_stands[target_id]
            target["occupancy_count"] -= 1
            db.touch(target)
        assignment["tow_target_stand_id"] = None
    if status in ("OCCUPIED", "TOWED_AWAY"):
        if assignment["stand_type"] == "GATE":
            gate = db.gates.get(assignment["gate_id"])
            if gate is not None:
                gate["active_assignment_count"] -= 1
                db.touch(gate)
        else:
            stand = db.remote_stands.get(assignment["remote_stand_id"])
            if stand is not None:
                stand["occupancy_count"] -= 1
                db.touch(stand)
