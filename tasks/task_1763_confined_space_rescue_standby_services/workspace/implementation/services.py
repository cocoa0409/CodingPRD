"""Business logic: clock sweeps, cascades, exposure classification, billing.

All time rules are evaluated against the logical clock (PRD section 2.4).
Monetary math uses Decimal with round-half-up applied once at the end
(PRD section 2.8).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from helpers import iso_z, now_dt, parse_dt, stamp_append_only, touch

# Constants from SCAFFOLD section 1.3
PRE_ENTRY_MAX_AGE = timedelta(minutes=30)
VERIFICATION_TTL = timedelta(hours=12)
MONITORING_MAX_GAP = timedelta(minutes=15)
ROSTER_CHECKIN_EARLY = timedelta(minutes=15)
ROSTER_NO_SHOW_GRACE = timedelta(minutes=15)
ROSTER_REST_GAP = timedelta(hours=8)
STANDBY_CHECKIN_EARLY = timedelta(minutes=30)
STANDBY_NO_SHOW_GRACE = timedelta(minutes=15)
QUARTER_HOUR = 15
TWA_NORMALIZATION_MINUTES = Decimal("480")
TWA8_ACTION_PPM = Decimal("5")
TWA8_EXCEEDANCE_PPM = Decimal("10")
PEAK_ACTION_PPM = Decimal("10")
PEAK_EXCEEDANCE_PPM = Decimal("15")
CANCELLATION_FEE_RATIO = Decimal("0.5")

OPEN_INCIDENT_STATES = ("REPORTED", "TRIAGED", "ESCALATED", "REOPENED")
NON_TERMINAL_PERMIT_STATES = ("DRAFT", "ISSUED", "ACTIVE", "SUSPENDED")
COMMITTED_STANDBY_STATES = ("SCHEDULED", "ON_STANDBY", "DEPLOYED")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def permit_of(entity):
    return db.entry_permits.get(entity["permit_id"])


def space_of_permit(permit):
    return db.confined_spaces.get(permit["space_id"])


def account_of_permit(permit):
    return db.client_accounts.get(permit["client_account_id"])


def approved_plan_for_space(space_id):
    for p in db.rescue_plans.values():
        if p["space_id"] == space_id and p["status"] == "APPROVED":
            return p
    return None


def open_incidents_for_permit(permit_id):
    return [i for i in db.incidents.values()
            if i["permit_id"] == permit_id and i["status"] in OPEN_INCIDENT_STATES]


def on_duty_entries_for_permit(permit_id):
    return [e for e in db.roster_entries.values()
            if e["permit_id"] == permit_id and e["status"] == "ON_DUTY"]


# ---------------------------------------------------------------------------
# Committed standby minutes (Personnel computed field)
# ---------------------------------------------------------------------------

def window_minutes(start_iso, end_iso):
    seconds = (parse_dt(end_iso) - parse_dt(start_iso)).total_seconds()
    return int(seconds // 60)


def recompute_committed(rescuer_id):
    person = db.personnel.get(rescuer_id)
    if person is None:
        return
    total = 0
    for a in db.standby_assignments.values():
        if a["rescuer_id"] == rescuer_id and a["status"] in COMMITTED_STANDBY_STATES:
            total += window_minutes(a["standby_start_at"], a["standby_end_at"])
    if person["committed_standby_minutes"] != total:
        person["committed_standby_minutes"] = total
        touch(person)


# ---------------------------------------------------------------------------
# Entrant exposure classification (SCAFFOLD 1.3 entrant_exposure_classification)
# ---------------------------------------------------------------------------

def compute_exposure(entry, end_dt):
    """Return (twa_ppm, peak_ppm, exposure_class) for the duty window.

    Duty window W = [checked_in_at, end]. Each CONTINUOUS reading of the
    permit applies its h2s_ppm forward from its recorded_at until the next
    reading's recorded_at or the end of W; time before the first reading
    counts as 0 ppm. Values rounded to 2 dp half-up; thresholds compared
    after rounding; thresholds inclusive.
    """
    start = parse_dt(entry["checked_in_at"])
    readings = [r for r in db.atmospheric_readings.values()
                if r["permit_id"] == entry["permit_id"]
                and r["reading_kind"] == "CONTINUOUS"
                and start <= parse_dt(r["recorded_at"]) <= end_dt]
    readings.sort(key=lambda r: (r["recorded_at"], r["_seq"]))
    twa_sum = Decimal("0")
    peak = Decimal("0")
    prev_t = None
    prev_ppm = None
    for r in readings:
        t = parse_dt(r["recorded_at"])
        ppm = Decimal(str(r["h2s_ppm"]))
        if prev_t is not None:
            minutes = Decimal(str((t - prev_t).total_seconds())) / Decimal("60")
            twa_sum += prev_ppm * minutes
        prev_t, prev_ppm = t, ppm
        if ppm > peak:
            peak = ppm
    if prev_t is not None:
        minutes = Decimal(str((end_dt - prev_t).total_seconds())) / Decimal("60")
        twa_sum += prev_ppm * minutes
    twa = (twa_sum / TWA_NORMALIZATION_MINUTES).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    peak_q = peak.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    permit = permit_of(entry)
    space = space_of_permit(permit) if permit else None
    standard = space["exposure_standard"] if space else "TWA8"
    if standard == "TWA8":
        if twa >= TWA8_EXCEEDANCE_PPM:
            cls = "EXCEEDANCE"
        elif twa >= TWA8_ACTION_PPM:
            cls = "ACTION"
        else:
            cls = "OK"
    else:  # PEAK_CEILING
        if peak_q >= PEAK_EXCEEDANCE_PPM:
            cls = "EXCEEDANCE"
        elif peak_q >= PEAK_ACTION_PPM:
            cls = "ACTION"
        else:
            cls = "OK"
    return twa, peak_q, cls


def finalize_exposure(entry, end_dt):
    """Stamp exposure fields for a duty window ending at end_dt."""
    twa, peak, cls = compute_exposure(entry, end_dt)
    entry["exposure_twa_ppm"] = twa
    entry["exposure_peak_ppm"] = peak
    entry["exposure_class"] = cls


def recompute_entry_exposure(entry, now):
    """Clock-sweep / post-reading recompute; auto-relief on EXCEEDANCE."""
    twa, peak, cls = compute_exposure(entry, now)
    entry["exposure_twa_ppm"] = twa
    entry["exposure_peak_ppm"] = peak
    entry["exposure_class"] = cls
    if cls == "EXCEEDANCE" and entry["status"] == "ON_DUTY":
        entry["status"] = "RELIEVED"
        entry["checked_out_at"] = iso_z(now)
    touch(entry)


# ---------------------------------------------------------------------------
# Permit cascades (SCAFFOLD 1.2)
# ---------------------------------------------------------------------------

def _void_open_verifications(permit_id):
    for v in db.isolation_verifications.values():
        if v["permit_id"] == permit_id and v["status"] in ("PENDING", "VERIFIED"):
            v["status"] = "VOIDED"
            touch(v)


def _release_assignment(a, now):
    """ON_STANDBY|DEPLOYED -> RELEASED with billable fields computed."""
    a["checked_out_at"] = iso_z(now)
    a["status"] = "RELEASED"
    in_dt = parse_dt(a["checked_in_at"])
    actual_seconds = (now - in_dt).total_seconds()
    actual_minutes = int(actual_seconds // 60)
    billable = ((actual_minutes + QUARTER_HOUR - 1) // QUARTER_HOUR) * QUARTER_HOUR
    a["billable_minutes"] = billable
    permit = permit_of(a)
    account = account_of_permit(permit) if permit else None
    if account is not None and account["billing_mode"] == "HOURLY_STANDBY":
        a["line_amount_cents"] = compute_hourly_line_amount(a, account)
    touch(a)
    recompute_committed(a["rescuer_id"])


def compute_hourly_line_amount(a, account):
    """standby_line_amount_hourly (SCAFFOLD 1.3): tiered pricing, quarter-hour
    roundup, minimum floor, marginal tier2, non-stacking day multiplier with
    weekend precedence. Round half-up once at the end."""
    billable_hours = Decimal(a["billable_minutes"]) / Decimal("60")
    min_hours = Decimal(str(account["minimum_billable_hours"]))
    chargeable = max(min_hours, billable_hours)
    threshold = Decimal(str(account["tier1_hours_threshold"]))
    tier1 = min(chargeable, threshold)
    tier2 = max(Decimal("0"), chargeable - threshold)
    rate = Decimal(str(account["hourly_standby_rate_cents"]))
    base = tier1 * rate + tier2 * rate * Decimal(str(account["tier2_multiplier"]))
    in_dt = parse_dt(a["checked_in_at"])  # naive UTC
    if in_dt.weekday() >= 5:  # Saturday=5, Sunday=6 — weekend takes precedence
        day_mult = Decimal(str(account["weekend_multiplier"]))
    elif in_dt.hour < 7 or in_dt.hour >= 19:
        day_mult = Decimal(str(account["after_hours_multiplier"]))
    else:
        day_mult = Decimal("1.0")
    return int((base * day_mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def chargeable_hours(a, account):
    billable_hours = Decimal(a["billable_minutes"]) / Decimal("60")
    return max(Decimal(str(account["minimum_billable_hours"])), billable_hours)


def release_assignment(a, now):
    _release_assignment(a, now)


def cancel_scheduled_assignment(a):
    a["status"] = "CANCELLED"
    touch(a)
    recompute_committed(a["rescuer_id"])


def deploy_on_standby(permit_id, now):
    for a in db.standby_assignments.values():
        if a["permit_id"] == permit_id and a["status"] == "ON_STANDBY":
            a["status"] = "DEPLOYED"
            a["deployed_at"] = iso_z(now)
            touch(a)


def evacuate_on_duty(permit_id, now):
    for e in db.roster_entries.values():
        if e["permit_id"] == permit_id and e["status"] == "ON_DUTY":
            finalize_exposure(e, now)
            e["status"] = "EVACUATED"
            e["checked_out_at"] = iso_z(now)
            touch(e)


def emergency_suspend(permit, now):
    """ACTIVE -> SUSPENDED emergency path: evacuate roster, deploy standby.

    Shared by the alarm cascade, the monitoring-gap sweep, and incident
    reports on ACTIVE permits. No Incident is created here (the alarm path
    adds one at the call site).
    """
    permit["status"] = "SUSPENDED"
    permit["suspension_count"] += 1
    permit["last_suspended_at"] = iso_z(now)
    touch(permit)
    evacuate_on_duty(permit["id"], now)
    deploy_on_standby(permit["id"], now)


def cancel_permit_cascade(permit, now, escalation):
    """Permit -> CANCELLED. Manual path releases ON_STANDBY standby; the
    escalation path deploys it and evacuates on-duty roster instead."""
    permit["status"] = "CANCELLED"
    permit["close_reason"] = "INCIDENT" if escalation else "CANCELLED"
    permit["closed_at"] = iso_z(now)
    touch(permit)
    for e in db.roster_entries.values():
        if e["permit_id"] != permit["id"]:
            continue
        if e["status"] == "SCHEDULED":
            e["status"] = "CANCELLED"
            touch(e)
        elif e["status"] == "ON_DUTY" and escalation:
            finalize_exposure(e, now)
            e["status"] = "EVACUATED"
            e["checked_out_at"] = iso_z(now)
            touch(e)
    for a in db.standby_assignments.values():
        if a["permit_id"] != permit["id"]:
            continue
        if a["status"] == "SCHEDULED":
            cancel_scheduled_assignment(a)
        elif a["status"] == "ON_STANDBY":
            if escalation:
                a["status"] = "DEPLOYED"
                a["deployed_at"] = iso_z(now)
                touch(a)
            else:
                _release_assignment(a, now)
    _void_open_verifications(permit["id"])


def close_permit_cascade(permit, now):
    """Permit -> CLOSED (orderly completion)."""
    permit["status"] = "CLOSED"
    permit["close_reason"] = "COMPLETED"
    permit["closed_at"] = iso_z(now)
    touch(permit)
    for e in db.roster_entries.values():
        if e["permit_id"] == permit["id"] and e["status"] == "SCHEDULED":
            e["status"] = "CANCELLED"
            touch(e)
    for a in db.standby_assignments.values():
        if a["permit_id"] != permit["id"]:
            continue
        if a["status"] == "SCHEDULED":
            cancel_scheduled_assignment(a)
        elif a["status"] == "ON_STANDBY":
            _release_assignment(a, now)
        # DEPLOYED assignments are left unchanged (explicit release required)
    _void_open_verifications(permit["id"])


# ---------------------------------------------------------------------------
# Account ledger (SCAFFOLD 1.3 balance_reconciliation / credit_hold_evaluation)
# ---------------------------------------------------------------------------

def recompute_credit_hold(account):
    hold = account["balance_cents"] >= account["credit_limit_cents"]
    account["on_credit_hold"] = hold


def adjust_balance(account, delta):
    """Ledger mutation (SCAFFOLD 1.3 balance_reconciliation). A zero delta
    leaves balance and hold unchanged, so no version bump is needed."""
    if delta == 0:
        return
    account["balance_cents"] += delta
    recompute_credit_hold(account)
    touch(account)


# ---------------------------------------------------------------------------
# Clock sweeps (PRD section 2.4)
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    now = now_dt()
    # 1. Roster no-show: SCHEDULED and now strictly past start + 15 minutes
    for e in list(db.roster_entries.values()):
        if e["status"] == "SCHEDULED":
            if now > parse_dt(e["scheduled_start_at"]) + ROSTER_NO_SHOW_GRACE:
                e["status"] = "NO_SHOW"
                touch(e)
    # 2. Standby no-show: same grace, releases committed minutes
    for a in list(db.standby_assignments.values()):
        if a["status"] == "SCHEDULED":
            if now > parse_dt(a["standby_start_at"]) + STANDBY_NO_SHOW_GRACE:
                a["status"] = "NO_SHOW"
                touch(a)
                recompute_committed(a["rescuer_id"])
    # 3. Verification expiry: VERIFIED and now >= expires_at (inclusive)
    for v in list(db.isolation_verifications.values()):
        if v["status"] == "VERIFIED" and v["expires_at"] is not None:
            if now >= parse_dt(v["expires_at"]):
                v["status"] = "EXPIRED"
                touch(v)
    # 4. Monitoring-gap suspension (strictly greater than 15 minutes)
    for p in list(db.entry_permits.values()):
        if p["status"] != "ACTIVE":
            continue
        space = space_of_permit(p)
        if space is None or not space["requires_continuous_monitoring"]:
            continue
        continuous = [r for r in db.atmospheric_readings.values()
                      if r["permit_id"] == p["id"] and r["reading_kind"] == "CONTINUOUS"]
        if continuous:
            last = max(parse_dt(r["recorded_at"]) for r in continuous)
        else:
            last = parse_dt(p["actual_entry_at"])
        if (now - last) > MONITORING_MAX_GAP:
            emergency_suspend(p, now)  # no Incident on the gap path
    # 5. Exposure recompute for on-duty entries
    for e in list(db.roster_entries.values()):
        if e["status"] == "ON_DUTY":
            recompute_entry_exposure(e, now)
