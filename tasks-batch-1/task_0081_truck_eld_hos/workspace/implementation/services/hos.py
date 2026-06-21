"""Hours-of-Service clock recomputation, violation scan, PC segments, daily-log
reconciliation, and cascade side effects.

Implements scaffold calculations hos_clocks / violation_detection / pc_exclusion /
sleeper_split and PRD §3.4-§3.9.

The whole derived picture is recomputed from the surviving (ACTIVE) event stream
on every append / correction / mark-error / adverse-claim approve.
"""
import db
import clock
import timeutil
import model

# Constants (scaffold calculations.constants)
DRIVING_LIMIT_MIN = 660       # 11h
WINDOW_LIMIT_MIN = 840        # 14h
DRIVING_LIMIT_ADVERSE = 780   # 13h
WINDOW_LIMIT_ADVERSE = 960    # 16h
BREAK_REQUIRED_AFTER_MIN = 480  # 8h driving without a 30-min break
BREAK_MIN_MINUTES = 30
RESET_OFF_DUTY_MIN = 600      # 10h
CYCLE_70_LIMIT_MIN = 4200     # 70h
CYCLE_60_LIMIT_MIN = 3600     # 60h
CYCLE_70_WINDOW_DAYS = 8
CYCLE_60_WINDOW_DAYS = 7
LONG_REST_MIN = 420           # 7h
SHORT_REST_MIN = 120          # 2h
PAIR_TOTAL_MIN = 600          # 10h

NOTE_CORRECTED = "auto-dismissed: corrected"
NOTE_ADVERSE = "auto-dismissed: adverse conditions"


# ---------------------------------------------------------------------------
# event helpers
# ---------------------------------------------------------------------------
def _active_events_sorted(driver_id):
    evs = [e for e in db.duty_events.values()
           if e["driver_id"] == driver_id and e["record_status"] == "ACTIVE"]
    evs.sort(key=lambda e: (e["_event_dt"], e["_seq"]))
    return evs


def _is_driving_minutes(ev):
    if ev["duty_status"] == "DRIVING":
        return ev["special_driving_category"] in ("NONE", "YARD_MOVE")
    return False


def _is_window_minutes(ev):
    cat = ev["special_driving_category"]
    if cat == "PERSONAL_CONVEYANCE":
        return False
    if ev["duty_status"] == "DRIVING":
        return True
    if ev["duty_status"] == "ON_DUTY_NOT_DRIVING":
        return cat == "NONE"
    return False


def _is_off_duty(ev):
    return ev["duty_status"] in ("OFF_DUTY", "SLEEPER_BERTH")


def _is_pc(ev):
    return ev["special_driving_category"] == "PERSONAL_CONVEYANCE"


# ---------------------------------------------------------------------------
# top-level recompute
# ---------------------------------------------------------------------------
def recompute_driver(driver, dismiss_note=NOTE_CORRECTED, adverse_day=None):
    """Recompute everything derived for a driver from the surviving event stream.

    dismiss_note: note attached to auto-dismissed violations.
    adverse_day: when set, only DRIVING_11H/WINDOW_14H violations on that day are
      eligible for adverse auto-dismiss (PRD §3.9); for corrections all eligible.
    """
    driver_id = driver["id"]
    old_version = driver["version"]
    old_status = driver["current_duty_status"]
    old_cycle = driver["cycle_on_duty_minutes"]

    evs = _active_events_sorted(driver_id)

    # 1) duration_minutes per active event
    for i, ev in enumerate(evs):
        if i + 1 < len(evs):
            ev["duration_minutes"] = timeutil.whole_minutes_between(
                ev["_event_dt"], evs[i + 1]["_event_dt"])
        else:
            ev["duration_minutes"] = None

    # 2) current_duty_status
    driver["current_duty_status"] = evs[-1]["duty_status"] if evs else "OFF_DUTY"

    # 3) cycle_on_duty_minutes
    driver["cycle_on_duty_minutes"] = _compute_cycle(driver, evs)

    # bump driver version/updated_at if any driver-derived field changed
    if (driver["current_duty_status"] != old_status
            or driver["cycle_on_duty_minutes"] != old_cycle):
        model.touch(driver)

    # 4) PC segments
    _reconcile_pc_segments(driver, evs)

    # 5) compliance disposition reset + violation scan
    for ev in evs:
        ev["compliance_disposition"] = "COMPLIANT"
    _violation_scan(driver, evs, dismiss_note, adverse_day)

    # 6) daily-log reconciliation + cascade RECERTIFY
    _reconcile_daily_logs(driver, evs)

    return evs


# ---------------------------------------------------------------------------
# cycle
# ---------------------------------------------------------------------------
def _cycle_window_bounds(driver, evs):
    tz = driver["home_terminal_tz_offset_minutes"]
    window_days = (CYCLE_70_WINDOW_DAYS if driver["cycle_rule"] == "SEVENTY_HOUR_8_DAY"
                   else CYCLE_60_WINDOW_DAYS)
    latest_ord = timeutil.date_to_ordinal(
        timeutil.home_terminal_date(evs[-1]["_event_dt"], tz))
    earliest_ord = latest_ord - (window_days - 1)
    return earliest_ord, latest_ord


def _cycle_contributes(ev):
    cat = ev["special_driving_category"]
    if cat == "PERSONAL_CONVEYANCE":
        return False
    if ev["duty_status"] == "DRIVING" and cat in ("NONE", "YARD_MOVE"):
        return True
    if ev["duty_status"] == "ON_DUTY_NOT_DRIVING" and cat == "NONE":
        return True
    return False


def _compute_cycle(driver, evs):
    if not evs:
        return 0
    tz = driver["home_terminal_tz_offset_minutes"]
    earliest_ord, latest_ord = _cycle_window_bounds(driver, evs)
    total = 0
    for i, ev in enumerate(evs):
        if i + 1 >= len(evs) or ev["duration_minutes"] is None:
            continue
        d_ord = timeutil.date_to_ordinal(timeutil.home_terminal_date(ev["_event_dt"], tz))
        if earliest_ord <= d_ord <= latest_ord and _cycle_contributes(ev):
            total += ev["duration_minutes"]
    return total


def _cycle_limit(driver):
    return (CYCLE_70_LIMIT_MIN if driver["cycle_rule"] == "SEVENTY_HOUR_8_DAY"
            else CYCLE_60_LIMIT_MIN)


# ---------------------------------------------------------------------------
# closed-interval build + sleeper-split resets
# ---------------------------------------------------------------------------
def _build_closed(evs):
    closed = []
    for i, ev in enumerate(evs):
        if i + 1 >= len(evs) or ev["duration_minutes"] is None:
            continue
        closed.append({
            "index_in_closed": len(closed),
            "ev": ev,
            "minutes": ev["duration_minutes"],
            "drives": _is_driving_minutes(ev),
            "window": _is_window_minutes(ev),
            "off": _is_off_duty(ev) and not _is_pc(ev),
            "pc": _is_pc(ev),
        })
    return closed


def _find_sleeper_resets(closed):
    """Return dict: closed-index whose END triggers a driving/window reset ->
    list of excluded paired-rest interval indices (empty for a full continuous reset)."""
    n = len(closed)
    resets = {}

    # full continuous off-duty/sleeper span >= 600 min
    i = 0
    while i < n:
        if closed[i]["off"]:
            run = 0
            j = i
            while j < n and closed[j]["off"]:
                run += closed[j]["minutes"]
                j += 1
                if run >= RESET_OFF_DUTY_MIN:
                    resets[j - 1] = []
                    break
            i = j
        else:
            i += 1

    # sleeper-berth split pairings
    paired = set()
    long_idxs = set(c["index_in_closed"] for c in closed
                    if c["ev"]["duty_status"] == "SLEEPER_BERTH" and c["minutes"] >= LONG_REST_MIN)
    short_idxs = set(c["index_in_closed"] for c in closed
                     if c["off"] and c["minutes"] >= SHORT_REST_MIN)
    qualifying = sorted(long_idxs | short_idxs)
    for idx in qualifying:
        if idx in paired:
            continue
        c = closed[idx]
        best = None
        for k in range(idx - 1, -1, -1):
            if k in paired:
                continue
            ck = closed[k]
            if not ck["off"]:
                continue
            a_long = c["ev"]["duty_status"] == "SLEEPER_BERTH" and c["minutes"] >= LONG_REST_MIN
            b_long = ck["ev"]["duty_status"] == "SLEEPER_BERTH" and ck["minutes"] >= LONG_REST_MIN
            a_short = c["minutes"] >= SHORT_REST_MIN
            b_short = ck["minutes"] >= SHORT_REST_MIN
            total = c["minutes"] + ck["minutes"]
            if total >= PAIR_TOTAL_MIN and ((a_long and b_short) or (b_long and a_short)):
                best = k
                break
        if best is not None:
            paired.add(best)
            paired.add(idx)
            later = max(best, idx)
            existing = resets.get(later, [])
            resets[later] = sorted(set(existing) | {best, idx})
    return resets


def _has_approved_claim(driver_id, log_date):
    for c in db.adverse_claims.values():
        if (c["driver_id"] == driver_id and c["log_date"] == log_date
                and c["status"] == "APPROVED"):
            return True
    return False


def _run_clocks(driver, evs):
    """Replay closed intervals; return per-interval step dicts with running clocks
    and variant-aware limits."""
    closed = _build_closed(evs)
    resets = _find_sleeper_resets(closed)
    tz = driver["home_terminal_tz_offset_minutes"]

    driving_clock = 0
    window_clock = 0
    window_open = False
    break_clock = 0

    steps = []
    for c in closed:
        ev = c["ev"]
        minutes = c["minutes"]
        idx = c["index_in_closed"]

        if c["drives"]:
            driving_clock += minutes
            break_clock += minutes
        elif c["window"]:
            # on-duty (not driving) is a non-driving interval; >=30 min resets break
            if minutes >= BREAK_MIN_MINUTES:
                break_clock = 0
        else:
            if c["off"] and minutes >= BREAK_MIN_MINUTES:
                break_clock = 0

        if c["window"]:
            if not window_open:
                window_open = True
                window_clock = minutes
            else:
                window_clock += minutes
        else:
            # Off-duty / sleeper time elapses inside an open 14h window (the window
            # is wall-clock elapsed time). PC time is excluded. The reset interval
            # itself is handled below and never advances the window into a violation.
            if window_open and not c["pc"]:
                window_clock += minutes

        day = timeutil.home_terminal_date(ev["_event_dt"], tz)
        adverse = _has_approved_claim(driver["id"], day)
        steps.append({
            "ev": ev,
            "drives": c["drives"],
            "window": c["window"],
            "is_reset": idx in resets,
            "driving_clock": driving_clock,
            "window_clock": window_clock,
            "break_clock": break_clock,
            "d_limit": DRIVING_LIMIT_ADVERSE if adverse else DRIVING_LIMIT_MIN,
            "w_limit": WINDOW_LIMIT_ADVERSE if adverse else WINDOW_LIMIT_MIN,
            "day": day,
        })

        if idx in resets:
            driving_clock = 0
            window_clock = 0
            window_open = False
            break_clock = 0

    return steps


# ---------------------------------------------------------------------------
# violation scan
# ---------------------------------------------------------------------------
def _violation_scan(driver, evs, dismiss_note, adverse_day):
    driver_id = driver["id"]
    steps = _run_clocks(driver, evs)

    triggered = {}  # type -> {ev, overage}
    for st in steps:
        if st["is_reset"]:
            # The qualifying break that closes the shift is never itself a trigger.
            continue
        # DRIVING_11H / BREAK_30MIN advance only on driving (DRIVING&NONE / YARD_MOVE)
        if st["drives"]:
            d_over = st["driving_clock"] - st["d_limit"]
            if d_over >= 1:
                _register_trigger(triggered, "DRIVING_11H", st["ev"], d_over)
            b_over = st["break_clock"] - BREAK_REQUIRED_AFTER_MIN
            if b_over >= 1:
                _register_trigger(triggered, "BREAK_30MIN", st["ev"], b_over)
        # WINDOW_14H is tested on intervals that advance the window (on-duty/driving)
        if st["window"]:
            w_over = st["window_clock"] - st["w_limit"]
            if w_over >= 1:
                _register_trigger(triggered, "WINDOW_14H", st["ev"], w_over)

    cyc_limit = _cycle_limit(driver)
    cyc_trigger, cyc_over = _cycle_trigger(driver, evs, cyc_limit)
    if cyc_trigger is not None and cyc_over >= 1:
        triggered["CYCLE_70H"] = {"ev": cyc_trigger, "overage": cyc_over}

    for vt, info in triggered.items():
        info["ev"]["compliance_disposition"] = "VIOLATING"

    _reconcile_violations(driver_id, triggered, dismiss_note, adverse_day)


def _register_trigger(triggered, vtype, ev, overage):
    if vtype not in triggered:
        triggered[vtype] = {"ev": ev, "overage": overage}
    elif overage > triggered[vtype]["overage"]:
        triggered[vtype]["overage"] = overage


def _cycle_trigger(driver, evs, limit):
    if not evs:
        return None, 0
    tz = driver["home_terminal_tz_offset_minutes"]
    earliest_ord, latest_ord = _cycle_window_bounds(driver, evs)
    running = 0
    for i, ev in enumerate(evs):
        if i + 1 >= len(evs) or ev["duration_minutes"] is None:
            continue
        d_ord = timeutil.date_to_ordinal(timeutil.home_terminal_date(ev["_event_dt"], tz))
        if not (earliest_ord <= d_ord <= latest_ord):
            continue
        if _cycle_contributes(ev):
            running += ev["duration_minutes"]
            if running - limit >= 1:
                return ev, running - limit
    return None, 0


def _reconcile_violations(driver_id, triggered, dismiss_note, adverse_day):
    """Open new violations / update overage; auto-dismiss obsolete OPEN/ACK rows.

    At most one OPEN row per (driver_id, violation_type). A still-crossing type
    updates its existing OPEN/ACKNOWLEDGED row's overage upward (does not duplicate).
    A type no longer crossing whose row is OPEN/ACKNOWLEDGED is auto-dismissed.
    """
    existing = {}
    for v in db.violations.values():
        if v["driver_id"] != driver_id:
            continue
        if v["status"] in ("OPEN", "ACKNOWLEDGED"):
            existing.setdefault(v["violation_type"], []).append(v)

    # Open / update
    for vtype, info in triggered.items():
        rows = existing.get(vtype, [])
        if rows:
            v = rows[0]
            if v["overage_minutes"] != info["overage"]:
                v["overage_minutes"] = info["overage"]
                v["trigger_event_id"] = info["ev"]["id"]
                model.touch(v)
        else:
            v = {
                "driver_id": driver_id,
                "trigger_event_id": info["ev"]["id"],
                "violation_type": vtype,
                "overage_minutes": info["overage"],
                "status": "OPEN",
                "resolution_note": None,
            }
            model.stamp_new(v)
            db.violations[v["id"]] = v

    # Auto-dismiss obsolete (no longer triggered)
    for vtype, rows in existing.items():
        if vtype in triggered:
            continue
        for v in rows:
            note = dismiss_note
            if dismiss_note == NOTE_ADVERSE:
                # adverse dismiss only applies to DRIVING_11H / WINDOW_14H on the day
                if vtype not in ("DRIVING_11H", "WINDOW_14H"):
                    continue
            v["status"] = "DISMISSED"
            v["resolution_note"] = note
            model.touch(v)


# ---------------------------------------------------------------------------
# PC segments
# ---------------------------------------------------------------------------
def _reconcile_pc_segments(driver, evs):
    driver_id = driver["id"]
    # Active PC events with a known (non-null) duration should each have one segment.
    active_pc = {}
    for ev in evs:
        if _is_pc(ev) and ev["duration_minutes"] is not None:
            active_pc[ev["id"]] = ev

    # remove segments whose event is no longer eligible
    for sid in list(db.pc_segments.keys()):
        seg = db.pc_segments[sid]
        if seg["driver_id"] != driver_id:
            continue
        if seg["event_id"] not in active_pc:
            del db.pc_segments[sid]

    # create/refresh segments for eligible events
    by_event = {}
    for seg in db.pc_segments.values():
        if seg["driver_id"] == driver_id:
            by_event[seg["event_id"]] = seg
    for eid, ev in active_pc.items():
        if eid in by_event:
            seg = by_event[eid]
            seg["minutes_excluded"] = ev["duration_minutes"]
        else:
            seg = {
                "driver_id": driver_id,
                "event_id": eid,
                "minutes_excluded": ev["duration_minutes"],
            }
            # PersonalConveyanceSegment carries only id + created_at (PRD §2.4)
            model.stamp_new(seg, common_fields=False)
            db.pc_segments[seg["id"]] = seg


# ---------------------------------------------------------------------------
# daily-log reconciliation + cascade
# ---------------------------------------------------------------------------
def compute_log_totals(driver, log_date):
    """Compute (driving, on_duty, off_duty) totals for a driver-day from ACTIVE events."""
    tz = driver["home_terminal_tz_offset_minutes"]
    evs = _active_events_sorted(driver["id"])
    total_driving = 0
    total_on_duty = 0
    total_off_duty = 0
    for i, ev in enumerate(evs):
        if i + 1 >= len(evs) or ev["duration_minutes"] is None:
            continue
        day = timeutil.home_terminal_date(ev["_event_dt"], tz)
        if day != log_date:
            continue
        cat = ev["special_driving_category"]
        mins = ev["duration_minutes"]
        if ev["duty_status"] == "DRIVING" and cat == "NONE":
            total_driving += mins
            total_on_duty += mins
        elif ev["duty_status"] == "ON_DUTY_NOT_DRIVING":
            # total_on_duty: ON_DUTY_NOT_DRIVING + category-NONE DRIVING (PRD §3.8)
            total_on_duty += mins
        elif ev["duty_status"] == "OFF_DUTY":
            total_off_duty += mins
        elif ev["duty_status"] == "SLEEPER_BERTH":
            total_off_duty += mins
    return total_driving, total_on_duty, total_off_duty


def _reconcile_daily_logs(driver, evs):
    """Refresh totals on every materialized daily log for this driver; cascade a
    CERTIFIED -> RECERTIFY_REQUIRED when its totals changed."""
    for log in db.daily_logs.values():
        if log["driver_id"] != driver["id"]:
            continue
        d, on, off = compute_log_totals(driver, log["log_date"])
        changed = (log["total_driving_minutes"] != d
                   or log["total_on_duty_minutes"] != on
                   or log["total_off_duty_minutes"] != off)
        if changed:
            log["total_driving_minutes"] = d
            log["total_on_duty_minutes"] = on
            log["total_off_duty_minutes"] = off
            if log["certification_status"] == "CERTIFIED":
                log["certification_status"] = "RECERTIFY_REQUIRED"
                log["certified_at"] = None
            model.touch(log)
