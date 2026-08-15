"""Calculation rules per SCAFFOLD Table 3 / PRD 3.7-3.9."""
from decimal import Decimal, ROUND_HALF_UP

from store import db

# ---- constants ----
TIME_UNIT_MINUTES = 15
EMERGENCY_QUALIFYING_UNITS = 2
PS_TABLE = {"P1": 0, "P2": 0, "P3": 1, "P4": 2, "P5": 3, "P6": 0}

PERSONAL_CF_CENTS = 8000
DIRECTION_CF_CENTS = 8001
SUPERVISION_CF_CENTS = 4000
CRNA_SOLO_CF_CENTS = 7500
AD_FLAT_UNITS = 3

RATIO_MAX = 4
REST_MINUTES = 480

STANDBY_FULL_NOTICE_MINUTES = 120
STANDBY_NOTICE_FREE_MINUTES = 1440

DAILY_STIPEND_CAP_CENTS = 50000
MONTHLY_STIPEND_CAP_CENTS = 400000

SEVERITY_WEIGHT = {"MINOR": 10, "MAJOR": 30, "CRITICAL": 60}
FINDING_SEVERITY = {
    "TEFRA_GAP": "MAJOR",
    "CONCURRENCY_RETRO_BREACH": "CRITICAL",
    "CREDENTIAL_LAPSE": "MINOR",
}


def _q01(x):
    return x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _q0(x):
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def compute_units(base_units, minutes, physical_status, emergency_flag):
    """charge_units: base + round_half_up(minutes/15, 0.1) + PS adder + emergency qualifier."""
    time_units = _q01(Decimal(minutes) / Decimal(TIME_UNIT_MINUTES))
    total = (Decimal(base_units) + time_units + Decimal(PS_TABLE[physical_status])
             + (Decimal(EMERGENCY_QUALIFYING_UNITS) if emergency_flag else Decimal(0)))
    return _q01(total)


def charge_for(units, cf_cents):
    """round_half_up(units * cf, whole cents) -> int."""
    return int(_q0(units * Decimal(cf_cents)))


def direction_split(units):
    """direction_split pinned order: round units (done) -> multiply -> round gross ->
    round physician half (half up) -> remainder to primary."""
    gross = charge_for(units, DIRECTION_CF_CENTS)
    physician_half = (gross + 1) // 2  # round_half_up(gross / 2) for non-negative gross
    primary_half = gross - physician_half
    return gross, physician_half, primary_half


def fee_by_code(procedure_code):
    for f in db.fee_schedules.values():
        if f["procedure_code"] == procedure_code:
            return f
    return None


def roster_of(rec):
    return db.rosters.get(rec["roster_id"])


def service_date_of_case(case):
    roster = db.rosters.get(case["roster_id"])
    return roster["service_date"] if roster else None


def find_agreement(site_id, service_date):
    """StipendAgreement covering (site, date) on the closed date window."""
    for ag in db.agreements.values():
        if ag["site_id"] == site_id and ag["effective_from"] <= service_date <= ag["effective_to"]:
            return ag
    return None


def find_attestation(case_id, physician_id):
    for a in db.attestations.values():
        if a["case_id"] == case_id and a["physician_id"] == physician_id:
            return a
    return None


# ---- interval helpers ----
def half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def closed_overlap(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def peak_overlap(intervals):
    """Peak concurrent count for half-open intervals (endpoint touch does not overlap)."""
    events = []
    for s, e in intervals:
        events.append((s, 1))
        events.append((e, -1))
    events.sort(key=lambda x: (x[0], x[1]))  # ends (-1) before starts (+1) at same minute
    peak = 0
    cur = 0
    for _, d in events:
        cur += d
        if cur > peak:
            peak = cur
    return peak


def peak_set(intervals):
    """(peak, payloads covering the first point achieving peak). intervals: (s, e, payload)."""
    starts = sorted({s for s, _, _ in intervals})
    best = 0
    best_pt = None
    for p in starts:
        c = sum(1 for s, e, _ in intervals if s <= p < e)
        if c > best:
            best = c
            best_pt = p
    if best_pt is None:
        return 0, []
    members = [pay for s, e, pay in intervals if s <= best_pt < e]
    return best, members


# ---- supervision / booking / rest checks ----
def directing_intervals_for(provider_id, service_date, statuses=("PROPOSED", "CONFIRMED")):
    """Physician's CASE_DIRECTING assignments with the given statuses on the service date."""
    out = []
    for a in db.assignments.values():
        if a["provider_id"] == provider_id and a["assignment_role"] == "CASE_DIRECTING" \
                and a["status"] in statuses:
            c = db.cases.get(a["case_id"])
            if c and service_date_of_case(c) == service_date:
                out.append((a, c))
    return out


def primary_intervals_for(provider_id, service_date, statuses=("PROPOSED", "CONFIRMED")):
    out = []
    for a in db.assignments.values():
        if a["provider_id"] == provider_id and a["assignment_role"] == "CASE_PRIMARY" \
                and a["status"] in statuses:
            c = db.cases.get(a["case_id"])
            if c and service_date_of_case(c) == service_date:
                out.append((a, c))
    return out


def has_call_on_date(provider_id, service_date):
    for ca in db.call_assignments.values():
        if ca["provider_id"] != provider_id:
            continue
        r = db.rosters.get(ca["roster_id"])
        if r and r["service_date"] == service_date:
            return True
    return False


# ---- stipend waterfall ----
def run_daily_waterfall(provider_id, occurred_date):
    bucket = [e for e in db.stipend_entries.values()
              if e["provider_id"] == provider_id and e["occurred_date"] == occurred_date
              and e["status"] != "VOIDED" and e["entry_type"] in ("STANDBY", "LATE_STAY")]
    bucket.sort(key=lambda e: (e["created_at"], e["_seq"]))
    running = 0
    for e in bucket:
        e["applied_amount_cents"] = min(e["amount_cents"],
                                        max(0, DAILY_STIPEND_CAP_CENTS - running))
        running += e["applied_amount_cents"]


def create_stipend_entry(provider_id, roster_id, entry_type, occurred_date, amount_cents):
    rec = db.new_record(
        provider_id=provider_id,
        roster_id=roster_id,
        entry_type=entry_type,
        occurred_date=occurred_date,
        amount_cents=amount_cents,
        applied_amount_cents=amount_cents if entry_type == "CALL" else 0,
        status="ACCRUED",
    )
    db.stipend_entries[rec["id"]] = rec
    if entry_type != "CALL":
        run_daily_waterfall(provider_id, occurred_date)
    return rec


# ---- roster posture ----
def derive_posture(roster):
    count = 0
    for a in db.assignments.values():
        if a["roster_id"] == roster["id"] and a["assignment_role"] == "CASE_PRIMARY" \
                and a["status"] == "CONFIRMED":
            count += 1
    return "STAFFED" if count >= roster["required_primary_slots"] else "UNDERSTAFFED"


# ---- audit scoring ----
def finding_bucket_case(finding):
    if finding.get("case_id"):
        return db.cases.get(finding["case_id"])
    if finding.get("assignment_id"):
        a = db.assignments.get(finding["assignment_id"])
        if a:
            return db.cases.get(a["case_id"])
    return None


def compute_scores(audit):
    realtime = 0
    period = 0
    for f in db.findings.values():
        if f["audit_id"] != audit["id"] or f["status"] != "OPEN":
            continue
        w = SEVERITY_WEIGHT[f["severity"]]
        case = finding_bucket_case(f)
        cstatus = case["status"] if case else None
        if cstatus in ("SCHEDULED", "IN_PROGRESS"):
            realtime += w
        elif cstatus in ("COMPLETED", "CANCELLED"):
            period += w
    if period < 20:
        band = "LOW"
    elif period < 50:
        band = "ELEVATED"
    elif period < 100:
        band = "HIGH"
    else:
        band = "CRITICAL"
    return realtime, period, band
