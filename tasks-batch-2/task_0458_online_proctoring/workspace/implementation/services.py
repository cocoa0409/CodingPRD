"""Business-logic services: calculations, state transitions, cascades.

Every rule here traces to a verbatim PRD sentence (§2.6, §2.7, §2.8, §3.x)
and SCAFFOLD §1.3 calculations.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import parse_iso, format_iso, format_iso_like

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
SETUP_MINUTES = 10
SEVERITY_WEIGHT = {"MINOR": Decimal("5"), "MAJOR": Decimal("15"), "CRITICAL": Decimal("40")}
AUTO_VOID_THRESHOLD = Decimal("50")
MODE_WEIGHT = {"LIVE": Decimal("1.0"), "RECORD_REVIEW": Decimal("0.4")}
MAX_LOAD_FACTOR = Decimal("1.0")


def _round_half_up(value, places):
    """Round a Decimal to `places` decimal places using round-half-up."""
    quant = Decimal(1).scaleb(-places)  # 10**-places
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def _as_number(dec):
    """Return a Decimal as int if it is integral, else float, for JSON output."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


# ---------------------------------------------------------------------------
# appointment_effective_window (SCAFFOLD §1.3, PRD §3.2, §2.8)
# ---------------------------------------------------------------------------
def compute_effective_window(exam, accommodation, scheduled_start_iso):
    """Return (effective_duration_minutes, effective_end_iso).

    base = Exam.base_duration_minutes
    extra_pct = accommodation.extra_time_pct when accommodation present AND
                its status == APPROVED, else 0
    core = ceil(base * (1 + extra_pct/100))   # ceil on the accommodated core
    effective_duration = core + SETUP_MINUTES (10)
    effective_end = scheduled_start + effective_duration minutes
    """
    base = exam["base_duration_minutes"]
    if accommodation is not None and accommodation["status"] == "APPROVED":
        extra_pct = accommodation["extra_time_pct"]
    else:
        extra_pct = 0
    # ceil(base * (1 + extra_pct/100)) using exact Decimal arithmetic.
    core_exact = Decimal(base) * (Decimal(1) + Decimal(extra_pct) / Decimal(100))
    core_minutes = int(math.ceil(core_exact))
    effective_duration = core_minutes + SETUP_MINUTES
    start_dt = parse_iso(scheduled_start_iso)
    end_dt = start_dt + timedelta(minutes=effective_duration)
    # effective_end_utc = scheduled_start_utc advanced by whole minutes; render
    # at the same fractional precision as the supplied scheduled_start_utc.
    return effective_duration, format_iso_like(end_dt, scheduled_start_iso)


# ---------------------------------------------------------------------------
# session_integrity_score (SCAFFOLD §1.3, PRD §2.6, §3.5)
# ---------------------------------------------------------------------------
def compute_integrity_score(session):
    """100 minus weighted incident penalties; counting flags only.

    Only flags with status in {OPEN, ESCALATED} count. RESOLVED excluded.
    Under RECORD_REVIEW, MINOR weight is halved (2.5); MAJOR/CRITICAL never
    adjusted. Penalty summed first, then subtracted from 100, floored at 0.
    Held to 2 dp round-half-up.
    """
    mode = session["monitoring_mode"]
    penalty = Decimal("0")
    for flag in db.incident_flags.values():
        if flag["session_id"] != session["id"]:
            continue
        if flag["status"] not in ("OPEN", "ESCALATED"):
            continue
        w = SEVERITY_WEIGHT[flag["severity"]]
        if mode == "RECORD_REVIEW" and flag["severity"] == "MINOR":
            w = w * Decimal("0.5")
        penalty += w
    score = Decimal("100") - penalty
    if score < 0:
        score = Decimal("0")
    return _round_half_up(score, 2)


def refresh_integrity_score(session):
    """Recompute and store the session's integrity_score (no version bump).

    integrity_score is a computed field (SCAFFOLD entity source: computed);
    recomputing it does not by itself constitute a versioned mutation, but
    callers that change session state bump the version separately.
    """
    session["integrity_score"] = _as_number(compute_integrity_score(session))
    return session


# ---------------------------------------------------------------------------
# proctor_load_factor (SCAFFOLD §1.3, PRD §2.7)
# ---------------------------------------------------------------------------
def _counted_sessions_for_proctor(proctor_id):
    return [
        s for s in db.sessions.values()
        if s["proctor_id"] == proctor_id and s["status"] in ("ACTIVE", "PAUSED")
    ]


def compute_load(proctor_id, capacity, extra_mode=None):
    """Return (active_session_count, load_factor Decimal@4dp).

    Weighted sum over the proctor's ACTIVE/PAUSED sessions (LIVE=1.0,
    RECORD_REVIEW=0.4) divided by capacity. extra_mode, when given, adds a
    prospective session of that mode to the weight (admission check).
    """
    counted = _counted_sessions_for_proctor(proctor_id)
    weighted = Decimal("0")
    for s in counted:
        weighted += MODE_WEIGHT[s["monitoring_mode"]]
    active_count = len(counted)
    if extra_mode is not None:
        weighted += MODE_WEIGHT[extra_mode]
    load = weighted / Decimal(capacity)
    return active_count, _round_half_up(load, 4)


def refresh_proctor_denorm(proctor):
    """Recompute the denormalized active_session_count + load_factor fields.

    Reflects only currently-counted sessions (reporting snapshot variant).
    """
    active_count, load = compute_load(proctor["id"], proctor["concurrent_capacity"])
    proctor["active_session_count"] = active_count
    proctor["load_factor"] = _as_number(load)
    return proctor


def prospective_load_ok(proctor, new_session_mode):
    """Admission check: prospective load_factor (incl. new session) <= 1.0.

    Equal to 1.0 admitted; strictly greater rejected (PRD §2.7, §3.3).
    """
    _, prospective = compute_load(
        proctor["id"], proctor["concurrent_capacity"], extra_mode=new_session_mode
    )
    return prospective <= MAX_LOAD_FACTOR


# ---------------------------------------------------------------------------
# report_aggregate_score (SCAFFOLD §1.3, PRD §3.7)
# ---------------------------------------------------------------------------
def compute_aggregate_score(session_ids):
    """PER_SESSION_ROUND: round each session score to 0 dp half-up, take the
    arithmetic mean, then round the mean to 2 dp half-up.
    """
    rounded = []
    for sid in session_ids:
        session = db.sessions[sid]
        score = Decimal(str(session["integrity_score"]))
        rounded.append(_round_half_up(score, 0))
    total = sum(rounded, Decimal("0"))
    mean = total / Decimal(len(rounded))
    return _round_half_up(mean, 2)


# ---------------------------------------------------------------------------
# Interval / window helpers
# ---------------------------------------------------------------------------
def _interval_of(appt):
    return parse_iso(appt["scheduled_start_utc"]), parse_iso(appt["effective_end_utc"])


def window_fits_exam(exam, start_iso, end_iso):
    """Effective window [start, end) must fit inside [window_start, window_end).

    Half-open on both ends: start >= window_start_utc AND end <= window_end_utc.
    """
    start = parse_iso(start_iso)
    end = parse_iso(end_iso)
    win_start = parse_iso(exam["window_start_utc"])
    win_end = parse_iso(exam["window_end_utc"])
    return start >= win_start and end <= win_end


def proctor_overlaps(proctor_id, start_iso, end_iso, exclude_appt_id=None):
    """True if [start, end) genuinely overlaps a non-terminal appointment of
    the same proctor. Half-open: touching endpoints allowed.
    """
    start = parse_iso(start_iso)
    end = parse_iso(end_iso)
    for appt in db.appointments.values():
        if appt["proctor_id"] != proctor_id:
            continue
        if exclude_appt_id is not None and appt["id"] == exclude_appt_id:
            continue
        if appt["status"] in TERMINAL_APPOINTMENT_STATES:
            continue
        a_start, a_end = _interval_of(appt)
        # Half-open overlap: start < a_end AND a_start < end.
        if start < a_end and a_start < end:
            return True
    return False


def candidate_overlaps(candidate_id, exam_id, start_iso, end_iso, exclude_appt_id=None):
    """True if the candidate already holds an appointment for the SAME exam
    whose window collides under a CLOSED-interval rule (touching endpoints
    rejected). Only non-terminal appointments collide.
    """
    start = parse_iso(start_iso)
    end = parse_iso(end_iso)
    for appt in db.appointments.values():
        if appt["candidate_id"] != candidate_id or appt["exam_id"] != exam_id:
            continue
        if exclude_appt_id is not None and appt["id"] == exclude_appt_id:
            continue
        if appt["status"] in TERMINAL_APPOINTMENT_STATES:
            continue
        a_start, a_end = _interval_of(appt)
        # Closed-interval overlap: a back-to-back (0-minute gap) collides.
        if start <= a_end and a_start <= end:
            return True
    return False


# Appointment terminal states for overlap purposes (NO_SHOW, CANCELLED,
# CONSUMED are terminal). SCHEDULED and CHECKED_IN are non-terminal.
TERMINAL_APPOINTMENT_STATES = {"NO_SHOW", "CANCELLED", "CONSUMED"}


# ---------------------------------------------------------------------------
# Cascades (PRD §2.5, §3.4, §3.5, §3.6)
# ---------------------------------------------------------------------------
def consume_appointment(appointment):
    """Drive an appointment to CONSUMED (status-changing mutation)."""
    appointment["status"] = "CONSUMED"
    db.touch(appointment)


def void_session(session, void_reason, resolve_only_flag_id=None):
    """Void a session and run the standard void cascade.

    The integrity_score is FROZEN at the value computed from the counting
    flags BEFORE any flags are resolved (PRD §3.4/§3.5: a terminal transition
    freezes the score). Then:
    - session.status -> VOIDED, void_reason set, version bumped
    - flags resolved: AUTO_THRESHOLD resolves every still-OPEN flag on the
      session; ESCALATION_UPHELD resolves the single triggering flag
      (resolve_only_flag_id)
    - underlying appointment -> CONSUMED
    - proctor load recomputed
    Mutates in place.
    """
    # Freeze score from the counting flags as they stand right now.
    refresh_integrity_score(session)
    session["status"] = "VOIDED"
    session["void_reason"] = void_reason
    if resolve_only_flag_id is not None:
        flag = db.incident_flags.get(resolve_only_flag_id)
        if flag is not None:
            flag["status"] = "RESOLVED"
    else:
        # All still-OPEN incident flags on this session -> RESOLVED.
        for flag in db.incident_flags.values():
            if flag["session_id"] == session["id"] and flag["status"] == "OPEN":
                flag["status"] = "RESOLVED"
    db.touch(session)
    # Appointment -> CONSUMED.
    appt = db.appointments.get(session["appointment_id"])
    if appt is not None:
        consume_appointment(appt)
    # Proctor denorm recomputed (this session no longer counted).
    proctor = db.proctors.get(session["proctor_id"])
    if proctor is not None:
        refresh_proctor_denorm(proctor)
        db.touch(proctor)
