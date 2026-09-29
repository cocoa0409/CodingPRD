"""The thirteen calculations of SCAFFOLD.yaml section 1.3 / PRD section 3."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

import db

D = Decimal
ZERO = D("0")
HUNDRED = D("100")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def r2(value):
    return dec(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def clamp(value, low, high):
    value = dec(value)
    if value < dec(low):
        return dec(low)
    if value > dec(high):
        return dec(high)
    return value


# ------------------------------------------------------------------ CALC 1

HABITAT_TARGETS = {
    "COLD_MARINE": {
        "temp": D("12.0"), "temp_band": D("1.5"),
        "sal": D("33.0"), "sal_band": D("1.0"),
        "ph": D("8.10"), "ph_band": D("0.20"),
        "do_warn": D("7.0"), "do_crit": D("5.5"),
    },
    "TROPICAL_MARINE": {
        "temp": D("25.0"), "temp_band": D("1.5"),
        "sal": D("35.0"), "sal_band": D("1.0"),
        "ph": D("8.20"), "ph_band": D("0.20"),
        "do_warn": D("6.0"), "do_crit": D("4.5"),
    },
    "FRESHWATER": {
        "temp": D("22.0"), "temp_band": D("2.0"),
        "sal": D("0.5"), "sal_band": D("0.5"),
        "ph": D("7.20"), "ph_band": D("0.30"),
        "do_warn": D("6.5"), "do_crit": D("5.0"),
    },
    "TOUCH_POOL": {
        "temp": D("14.0"), "temp_band": D("1.0"),
        "sal": D("33.0"), "sal_band": D("1.0"),
        "ph": D("8.10"), "ph_band": D("0.20"),
        "do_warn": D("7.5"), "do_crit": D("6.0"),
    },
}

AMMONIA_WARN = D("0.020")
AMMONIA_CRIT = D("0.050")
NITRITE_WARN = D("0.100")
NITRITE_CRIT = D("0.250")
SUM_WEIGHT = D("6.0")
MAX_WEIGHT = D("15.0")
TOUCH_CONTACT_WEIGHT = D("10.0")
WARNING_RATIO = D("1.0")
CRITICAL_RATIO = D("2.0")

BREACH_ORDER = (
    "temperature_c",
    "salinity_ppt",
    "ph",
    "dissolved_oxygen_mg_l",
    "ammonia_mg_l",
    "nitrite_mg_l",
)


def water_quality(design_habitat, values):
    """Returns (snapshot Decimal, severity, breach_parameters list)."""
    t = HABITAT_TARGETS[design_habitat]
    ratios = {}
    ratios["temperature_c"] = abs(dec(values["temperature_c"]) - t["temp"]) / t["temp_band"]
    ratios["salinity_ppt"] = abs(dec(values["salinity_ppt"]) - t["sal"]) / t["sal_band"]
    ratios["ph"] = abs(dec(values["ph"]) - t["ph"]) / t["ph_band"]
    do_short = t["do_warn"] - dec(values["dissolved_oxygen_mg_l"])
    if do_short < ZERO:
        do_short = ZERO
    ratios["dissolved_oxygen_mg_l"] = do_short / (t["do_warn"] - t["do_crit"]) * D("2")
    nh3_over = dec(values["ammonia_mg_l"]) - AMMONIA_WARN
    if nh3_over < ZERO:
        nh3_over = ZERO
    r_nh3 = nh3_over / (AMMONIA_CRIT - AMMONIA_WARN) * D("2")
    ratios["ammonia_mg_l"] = r_nh3
    no2_over = dec(values["nitrite_mg_l"]) - NITRITE_WARN
    if no2_over < ZERO:
        no2_over = ZERO
    ratios["nitrite_mg_l"] = no2_over / (NITRITE_CRIT - NITRITE_WARN) * D("2")

    ordered = [ratios[k] for k in BREACH_ORDER]
    total = sum(ordered, ZERO)
    worst = max(ordered)
    raw = HUNDRED - (SUM_WEIGHT * total + MAX_WEIGHT * worst)
    if design_habitat == "TOUCH_POOL":
        surcharge = r_nh3 - D("0.5")
        if surcharge < ZERO:
            surcharge = ZERO
        raw = raw - TOUCH_CONTACT_WEIGHT * surcharge
    snapshot = r2(clamp(raw, 0, 100))
    if worst >= CRITICAL_RATIO:
        severity = "CRITICAL"
    elif worst >= WARNING_RATIO:
        severity = "WARNING"
    else:
        severity = "NORMAL"
    breaches = [k for k in BREACH_ORDER if ratios[k] >= WARNING_RATIO]
    return snapshot, severity, breaches


# ------------------------------------------------------------------ CALC 2


def latest_reading(system_id):
    rows = [r for r in db.db.water_quality_readings.values()
            if r["life_support_system_id"] == system_id]
    if not rows:
        return None
    return max(rows, key=lambda r: (r["taken_at"], r["created_at"], r["_seq"]))


def plant_water_quality_index(system_id):
    row = latest_reading(system_id)
    if row is None:
        return D("100.00")
    return row["water_quality_index_snapshot"]


# ------------------------------------------------------------------ CALC 3

BIOLOAD_PRESSURE_PCT = D("95.00")
INTERACTION_AUTO_DISABLE_THRESHOLD = 2


def exhibit_posture(system, utilization_pct, redundancy_overdue):
    alarm = system["alarm_state"]
    if alarm == "CRITICAL":
        return "CLOSED", "LSS_CRITICAL"
    if alarm == "OFFLINE":
        return "CLOSED", "LSS_OFFLINE"
    if alarm == "WARNING":
        return "RESTRICTED", "LSS_WARNING"
    if redundancy_overdue:
        return "RESTRICTED", "REDUNDANCY_OVERDUE"
    if dec(utilization_pct) > BIOLOAD_PRESSURE_PCT:
        return "RESTRICTED", "BIOLOAD_PRESSURE"
    return "OPEN", None


# ------------------------------------------------------------------ CALC 4

BIOLOAD_DISPOSITIONS = ("ON_EXHIBIT", "TRANSFER_PENDING")


def exhibit_ledger(exhibit):
    total = ZERO
    for sp in db.db.specimens.values():
        if sp["exhibit_id"] == exhibit["id"] and sp["disposition_status"] in BIOLOAD_DISPOSITIONS:
            total = total + dec(sp["bioload_units"])
    occupied = r2(total)
    capacity = dec(exhibit["bioload_capacity_units"])
    if capacity == ZERO:
        utilization = D("0.00")
    else:
        utilization = r2(occupied / capacity * HUNDRED)
    return occupied, utilization


# ------------------------------------------------------------------ CALC 5

TAXON_MULTIPLIER = {
    "ELASMOBRANCH": D("1.5"),
    "TELEOST": D("1.0"),
    "INVERTEBRATE": D("0.5"),
    "MARINE_MAMMAL": D("2.0"),
    "REPTILE": D("1.25"),
    "BIRD": D("1.25"),
}
WILD_SURCHARGE_DAYS = 14
NON_ACCREDITED_SURCHARGE_DAYS = 10
PROVISIONAL_SURCHARGE_DAYS = 5
HIGH_TIER_TAXON_DAYS = 45
HIGH_TIER_EXTRA_DAYS = 7


def quarantine_required_days(species, source_type, source_institution):
    base = int(species["base_quarantine_days"])
    multiplier = TAXON_MULTIPLIER[species["taxon_group"]]
    taxon_days = int((D(base) * multiplier).to_integral_value(rounding=ROUND_CEILING))
    surcharge = 0
    if source_type == "WILD_COLLECTION":
        surcharge += WILD_SURCHARGE_DAYS
    if source_institution is not None:
        status = source_institution["accreditation_status"]
        if status == "NON_ACCREDITED":
            surcharge += NON_ACCREDITED_SURCHARGE_DAYS
        elif status == "PROVISIONAL":
            surcharge += PROVISIONAL_SURCHARGE_DAYS
    subtotal = taxon_days + surcharge
    if taxon_days >= HIGH_TIER_TAXON_DAYS:
        return subtotal + HIGH_TIER_EXTRA_DAYS
    return subtotal


# ------------------------------------------------------------------ CALC 6

RATING_POINTS = {"GREEN": D("40.0"), "YELLOW": D("24.0"), "RED": D("8.0")}
SOURCE_POINTS = {
    "CAPTIVE_BRED": D("35.0"),
    "RESCUE_STRANDING": D("30.0"),
    "INSTITUTIONAL_TRANSFER": D("22.0"),
    "WILD_COLLECTION": D("10.0"),
}
PROTECTION_PENALTY = {
    "UNLISTED": D("0.0"),
    "CITES_APPENDIX_II": D("6.0"),
    "CITES_APPENDIX_I": D("14.0"),
    "ESA_LISTED": D("18.0"),
}
INSTITUTION_WEIGHT = D("0.25")
NO_INSTITUTION_POINTS = D("20.0")
PERMIT_BONUS = D("5.0")
QUOTA_PRESSURE_WEIGHT = D("20.0")
MIN_CLEARANCE_SCORE = D("40.00")


def sustainability_score(species, source_type, source_institution, requested_count,
                        variant, has_issued_permit=False):
    base = RATING_POINTS[species["sustainability_rating"]] + SOURCE_POINTS[source_type]
    if source_institution is None:
        institution_component = NO_INSTITUTION_POINTS
    else:
        institution_component = INSTITUTION_WEIGHT * dec(source_institution["welfare_audit_score"])
    permit_bonus = ZERO
    quota_pressure = ZERO
    if variant == "FINAL":
        if has_issued_permit:
            permit_bonus = PERMIT_BONUS
        annual = int(species["wild_take_quota_annual"])
        if source_type == "WILD_COLLECTION" and annual > 0:
            reserved = int(species["wild_take_quota_reserved"])
            quota_pressure = QUOTA_PRESSURE_WEIGHT * (
                (D(reserved) + D(int(requested_count))) / D(annual))
    gross = base + institution_component + permit_bonus
    if gross > HUNDRED:
        gross = HUNDRED
    net = gross - PROTECTION_PENALTY[species["protection_status"]] - quota_pressure
    return r2(clamp(net, 0, 100))


# ------------------------------------------------------------------ CALC 7

BASE_WELFARE = D("40.0")
APPETITE_WEIGHT = D("8.0")
BEHAVIOR_POINTS = {
    "NORMAL": D("10.0"),
    "LETHARGIC": D("4.0"),
    "AGGRESSIVE": D("2.0"),
    "ABNORMAL_SWIM": D("0.0"),
}
OPEN_TREATMENT_PENALTY = D("6.0")
MISSING_DAY_PENALTY = D("3.0")
ROLLING_WINDOW_SIZE = 5
AUDIT_WINDOW_DAYS = 14

WELFARE_LOG_TYPES = ("FEEDING", "BEHAVIOR")


def _specimen_logs(specimen_id):
    return [r for r in db.db.husbandry_logs.values() if r["specimen_id"] == specimen_id]


def _open_treatment_count(specimen_id):
    return len([c for c in db.db.veterinary_cases.values()
                if c["specimen_id"] == specimen_id
                and c["case_type"] == "TREATMENT"
                and c["status"] == "OPEN"])


def _components(window):
    appetites = [dec(r["appetite_score"]) for r in window if r["log_type"] == "FEEDING"]
    behaviors = [BEHAVIOR_POINTS[r["behavior_code"]] for r in window if r["log_type"] == "BEHAVIOR"]
    return appetites, behaviors


def welfare_rolling(specimen_id):
    rows = [r for r in _specimen_logs(specimen_id) if r["log_type"] in WELFARE_LOG_TYPES]
    rows.sort(key=lambda r: (r["logged_at"], r["created_at"], r["_seq"]), reverse=True)
    window = rows[:ROLLING_WINDOW_SIZE]
    if not window:
        return None
    appetites, behaviors = _components(window)
    feeding = (sum(appetites, ZERO) / D(len(appetites)) * APPETITE_WEIGHT) if appetites else ZERO
    behavior = (sum(behaviors, ZERO) / D(len(behaviors))) if behaviors else ZERO
    raw = (BASE_WELFARE + feeding + behavior
           - OPEN_TREATMENT_PENALTY * D(_open_treatment_count(specimen_id)))
    return r2(clamp(raw, 0, 100))


def welfare_audit_snapshot(specimen_id):
    clock = db.db.clock
    low = clock - timedelta(days=AUDIT_WINDOW_DAYS)
    rows = [r for r in _specimen_logs(specimen_id)
            if r["log_type"] in WELFARE_LOG_TYPES and low <= r["logged_at"] <= clock]
    if not rows:
        return None
    appetites, behaviors = _components(rows)
    feeding = sum(appetites, ZERO) / D(AUDIT_WINDOW_DAYS) * APPETITE_WEIGHT
    behavior = (sum(behaviors, ZERO) / D(len(behaviors))) if behaviors else ZERO
    feed_days = set(r["logged_at"].date() for r in rows if r["log_type"] == "FEEDING")
    missing = AUDIT_WINDOW_DAYS - len(feed_days)
    raw = BASE_WELFARE + feeding + behavior - MISSING_DAY_PENALTY * D(missing)
    return r2(clamp(raw, 0, 100))


# ------------------------------------------------------------------ CALC 8

DOMAIN_WEIGHTS = (
    ("LIFE_SUPPORT", D("0.30")),
    ("ANIMAL_HEALTH", D("0.25")),
    ("RECORDS", D("0.20")),
    ("PERMITS", D("0.15")),
    ("PUBLIC_SAFETY", D("0.10")),
)
REDUNDANCY_PENALTY = D("10.00")
OFFLINE_PENALTY = D("25.00")
RECORD_GAP_PENALTY = D("5.00")
PERMIT_GAP_PENALTY = D("20.00")
SUSPENSION_PENALTY = D("15.00")
DISABLED_EXHIBIT_PENALTY = D("25.00")
BLOCKING_PENALTY = D("4.00")
AUDIT_PASS_SCORE = D("85.00")
AUDIT_CONDITIONAL_SCORE = D("70.00")


def readiness(redundancy_overdue_fn):
    """Returns (readiness_score, domain_subscores dict, blocking_finding_count)."""
    store = db.db

    plant_scores = []
    for sysrow in store.life_support_systems.values():
        value = dec(sysrow["water_quality_index"])
        if redundancy_overdue_fn(sysrow):
            value = value - REDUNDANCY_PENALTY
        if sysrow["alarm_state"] == "OFFLINE":
            value = value - OFFLINE_PENALTY
        plant_scores.append(clamp(value, 0, 100))
    if plant_scores:
        life_support = r2(sum(plant_scores, ZERO) / D(len(plant_scores)))
    else:
        life_support = D("100.00")

    welfare_values = [dec(sp["welfare_score"]) for sp in store.specimens.values()
                      if sp["disposition_status"] in ("CLEARED", "ON_EXHIBIT")
                      and sp["welfare_score"] is not None]
    if welfare_values:
        animal_health = r2(sum(welfare_values, ZERO) / D(len(welfare_values)))
    else:
        animal_health = D("100.00")

    logged = set(r["specimen_id"] for r in store.husbandry_logs.values())
    record_gaps = len([sp for sp in store.specimens.values()
                       if sp["disposition_status"] in ("QUARANTINE", "CLEARED", "ON_EXHIBIT")
                       and sp["id"] not in logged])
    records = r2(clamp(HUNDRED - RECORD_GAP_PENALTY * D(record_gaps), 0, 100))

    permit_gaps = 0
    for acq in store.acquisition_requests.values():
        if acq["status"] != "CLEARED" or not acq["permit_required"]:
            continue
        issued = [p for p in store.permits.values()
                  if p["acquisition_request_id"] == acq["id"] and p["status"] == "ISSUED"]
        if not issued:
            permit_gaps += 1
    permits = r2(clamp(HUNDRED - PERMIT_GAP_PENALTY * D(permit_gaps), 0, 100))

    suspended = len([s for s in store.interaction_sessions.values() if s["status"] == "SUSPENDED"])
    exhibits_with_sessions = set(s["exhibit_id"] for s in store.interaction_sessions.values())
    disabled = len([e for e in store.exhibits.values()
                    if not e["interaction_program_enabled"] and e["id"] in exhibits_with_sessions])
    public_safety = r2(clamp(
        HUNDRED - SUSPENSION_PENALTY * D(suspended) - DISABLED_EXHIBIT_PENALTY * D(disabled),
        0, 100))

    subscores = {
        "LIFE_SUPPORT": life_support,
        "ANIMAL_HEALTH": animal_health,
        "RECORDS": records,
        "PERMITS": permits,
        "PUBLIC_SAFETY": public_safety,
    }
    weighted = ZERO
    for name, weight in DOMAIN_WEIGHTS:
        weighted = weighted + weight * subscores[name]
    weighted_rounded = r2(weighted)

    blocking = len([s for s in store.life_support_systems.values()
                    if s["alarm_state"] in ("CRITICAL", "OFFLINE")])
    blocking += len([e for e in store.exhibits.values() if e["posture"] == "CLOSED"])
    blocking += len([sp for sp in store.specimens.values()
                     if sp["health_status"] == "DECEASED_PENDING_NECROPSY"])

    score = weighted_rounded - BLOCKING_PENALTY * D(blocking)
    if score < ZERO:
        score = ZERO
    return r2(score), subscores, blocking


def audit_determination(readiness_score, blocking):
    if dec(readiness_score) >= AUDIT_PASS_SCORE and blocking == 0:
        return "PASSED"
    if dec(readiness_score) >= AUDIT_CONDITIONAL_SCORE:
        return "CONDITIONAL"
    return "FAILED"


# ------------------------------------------------------------------ CALC 9

BUFFER_MINUTES = 30
LIVE_SESSION_STATUSES = ("SCHEDULED", "ACTIVE", "SUSPENDED")


def session_conflict(candidate_start, candidate_end, other_start, other_end):
    buf = timedelta(minutes=BUFFER_MINUTES)
    return candidate_start < other_end + buf and other_start < candidate_end + buf


def find_session_conflict(exhibit_id, starts_at, ends_at, exclude_id=None):
    rows = [s for s in db.db.interaction_sessions.values()
            if s["exhibit_id"] == exhibit_id
            and s["status"] in LIVE_SESSION_STATUSES
            and s["id"] != exclude_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for other in rows:
        if session_conflict(starts_at, ends_at, other["starts_at"], other["ends_at"]):
            return other
    return None


# ------------------------------------------------------------------ CALC 10


def withdrawal_window(case):
    start = case["treatment_start_at"]
    days = case["withdrawal_days"]
    if start is None or days is None:
        return None
    return start, start + timedelta(days=int(days))


def find_withdrawal_conflict(specimen_id, start, days, exclude_id=None):
    if days is None or int(days) == 0:
        return None
    end = start + timedelta(days=int(days))
    for case in db.db.veterinary_cases.values():
        if case["specimen_id"] != specimen_id or case["id"] == exclude_id:
            continue
        if case["case_type"] != "TREATMENT" or case["status"] != "OPEN":
            continue
        window = withdrawal_window(case)
        if window is None or window[0] == window[1]:
            continue
        if start < window[1] and window[0] < end:
            return case
    return None


def treatment_withdrawal_until(specimen_id):
    ends = []
    for case in db.db.veterinary_cases.values():
        if case["specimen_id"] != specimen_id:
            continue
        if case["case_type"] != "TREATMENT" or case["status"] != "OPEN":
            continue
        window = withdrawal_window(case)
        if window is None:
            continue
        ends.append(window[1])
    if not ends:
        return None
    return max(ends)


# ------------------------------------------------------------------ CALC 11

DOCUMENT_CODES = (
    "HEALTH_CERTIFICATE",
    "ORIGIN_DECLARATION",
    "IMPORT_LICENSE",
    "TRANSPORT_PLAN",
    "POSSESSION_AFFIDAVIT",
    "CITES_PERMIT",
    "ESA_AUTHORIZATION",
    "ACQUISITION_PROVENANCE",
    "CAPTIVE_BRED_CERT",
)

BASE_DOCUMENTS = {
    "IMPORT": ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"],
    "TRANSPORT": ["HEALTH_CERTIFICATE", "TRANSPORT_PLAN"],
    "POSSESSION": ["HEALTH_CERTIFICATE", "POSSESSION_AFFIDAVIT"],
}


def required_documents(permit_type, protection_status):
    required = list(BASE_DOCUMENTS[permit_type])
    if protection_status in ("CITES_APPENDIX_II", "CITES_APPENDIX_I"):
        required.append("CITES_PERMIT")
    if protection_status in ("CITES_APPENDIX_I", "ESA_LISTED"):
        required.append("ESA_AUTHORIZATION")
    return required


def missing_documents(permit_type, protection_status, supplied):
    supplied = set(supplied or [])
    return [code for code in required_documents(permit_type, protection_status)
            if code not in supplied]


# ------------------------------------------------------------------ CALC 12

WELFARE_CONDITION_CODES = (
    "WATER_CHEMISTRY_MATCH",
    "TRANSPORT_OXYGEN_PLAN",
    "QUARANTINE_ON_ARRIVAL",
    "CITES_TRANSPORT_CLEARANCE",
    "DIET_TRANSITION_PLAN",
    "NECROPSY_POLICY",
    "NO_COMMERCIAL_RESALE",
    "BREEDING_LOAN_TERMS",
)


def required_conditions(institution, species, specimen, counter_conditions):
    required = ["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN"]
    if institution["accreditation_status"] == "PROVISIONAL":
        required.append("QUARANTINE_ON_ARRIVAL")
    if species["protection_status"] != "UNLISTED":
        required.append("CITES_TRANSPORT_CLEARANCE")
    has_treatment = any(c["specimen_id"] == specimen["id"] and c["case_type"] == "TREATMENT"
                        for c in db.db.veterinary_cases.values())
    if has_treatment:
        required.append("DIET_TRANSITION_PLAN")
    for code in (counter_conditions or []):
        if code not in required:
            required.append(code)
    return required


def missing_conditions(institution, species, specimen, counter_conditions, supplied):
    supplied = set(supplied or [])
    return [code for code in required_conditions(institution, species, specimen, counter_conditions)
            if code not in supplied]


# ------------------------------------------------------------------ CALC 13

MIN_RECEIVER_WELFARE_SCORE = D("70.00")


def is_receiving_eligible(institution):
    return (institution["accreditation_status"] in ("ACCREDITED", "PROVISIONAL")
            and dec(institution["welfare_audit_score"]) >= MIN_RECEIVER_WELFARE_SCORE)


def species_permit_required(species):
    return species["protection_status"] != "UNLISTED"
