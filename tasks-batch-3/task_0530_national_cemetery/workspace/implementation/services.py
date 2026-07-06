import math

from db import db, touch
from clock import parse_iso8601

# ---- Constants (PRD §3, scaffold §constants) ----
MIN_SERVICE_DAYS = 730
PMC_RESERVATION_DAYS = 365
INSCRIPTION_MAX_LINES = 6
INSCRIPTION_MAX_CHARS_PER_LINE = 40
FREE_CHARACTER_ALLOWANCE = 60
EMBLEM_CHAR_EQUIV = 15
CHARS_PER_BLOCK = 10
BLOCK_PRICE_CENTS = 250
GRAVESITE_BUFFER_HOURS = 48
HONORS_FULL_SQUAD_MIN_SCORE = 110

BASE_BY_ROLE = {"VETERAN": 100, "SPOUSE": 60, "DEPENDENT": 40}
SERVICE_YEAR_POINTS = 3
SERVICE_BONUS_CAP = 30
DIED_IN_SERVICE_BONUS = 25
DISCHARGE_HONORABLE_BONUS = 10
SCORE_CEILING = 150


# ---------------------------------------------------------------------------
# Section inventory reconciliation (calc section_inventory, PRD §2.7)
# ---------------------------------------------------------------------------
def recompute_section_inventory(section):
    """Recompute derived counts from children; this is a mutation of the section."""
    kind = section["kind"]
    if kind == "IN_GROUND":
        children = [g for g in db.gravesites.values() if g["section_id"] == section["id"]]
    else:
        children = [n for n in db.niches.values() if n["section_id"] == section["id"]]
    capacity = len(children)
    available = sum(1 for c in children if c["status"] == "AVAILABLE")
    interred = sum(1 for c in children if c["status"] == "OCCUPIED")
    changed = (
        section.get("capacity_units") != capacity
        or section.get("available_units") != available
        or section.get("interred_units") != interred
    )
    section["capacity_units"] = capacity
    section["available_units"] = available
    section["interred_units"] = interred
    if changed:
        touch(section)


def recompute_section_by_id(section_id):
    section = db.sections.get(section_id)
    if section is not None:
        recompute_section_inventory(section)


# ---------------------------------------------------------------------------
# Eligibility decision (calc eligibility_decision, PRD §3.2)
# ---------------------------------------------------------------------------
def eligibility_decision(case, cemetery):
    """Return dict: decision, basis, denial_reason (first matching branch wins)."""
    # 1. CEMETERY_MISMATCH
    if bool(case.get("is_overseas_case")) != bool(cemetery["is_overseas"]):
        return {"decision": "DENIED", "basis": None, "denial_reason": "CEMETERY_MISMATCH"}

    role = case["applicant_role"]
    approved_basis = None

    if role == "VETERAN":
        if case.get("died_on_active_duty"):
            approved_basis = "DIED_IN_SERVICE"
        elif case.get("character_of_discharge") in ("OTHER_THAN_HONORABLE", "DISHONORABLE"):
            return {"decision": "DENIED", "basis": None, "denial_reason": "DISCHARGE_BAR"}
        elif (case.get("service_days") or 0) < MIN_SERVICE_DAYS:
            return {"decision": "DENIED", "basis": None, "denial_reason": "INSUFFICIENT_SERVICE"}
        else:
            approved_basis = "VETERAN_SERVICE"
    else:  # SPOUSE / DEPENDENT
        sponsor = db.burial_cases.get(case.get("reserving_case_id"))
        if sponsor is None or sponsor["status"] not in ("ELIGIBLE", "ASSIGNED", "SCHEDULED", "INTERRED"):
            return {"decision": "DENIED", "basis": None, "denial_reason": "SPONSOR_NOT_ELIGIBLE"}
        approved_basis = "DERIVED_SPONSOR"

    # 4. Overseas-only override
    if case.get("is_overseas_case") and cemetery["is_overseas"]:
        approved_basis = "OVERSEAS_ONLY"

    return {"decision": "APPROVED", "basis": approved_basis, "denial_reason": None}


# ---------------------------------------------------------------------------
# Entitlement score (calc entitlement_score, PRD §3.3)
# ---------------------------------------------------------------------------
def entitlement_score(case):
    role = case["applicant_role"]
    base = BASE_BY_ROLE[role]

    if role == "VETERAN":
        src = case
    else:
        src = db.burial_cases.get(case.get("reserving_case_id")) or {}

    service_days = src.get("service_days") or 0
    years = math.floor(service_days / 365)
    service_bonus = min(years * SERVICE_YEAR_POINTS, SERVICE_BONUS_CAP)
    service_flag = DIED_IN_SERVICE_BONUS if src.get("died_on_active_duty") else 0
    discharge_adj = DISCHARGE_HONORABLE_BONUS if src.get("character_of_discharge") == "HONORABLE" else 0

    raw = base + service_bonus + service_flag + discharge_adj
    return min(raw, SCORE_CEILING)


# ---------------------------------------------------------------------------
# Plot allocation waterfall (calc plot_allocation, PRD §3.4)
# ---------------------------------------------------------------------------
def _section_of(unit):
    return db.sections.get(unit["section_id"])


def auto_select_unit(case):
    """Return (unit, unit_type) or None if no candidate."""
    requested = case["requested_class"]
    cemetery_id = case["cemetery_id"]
    candidates = []

    for g in db.gravesites.values():
        if g["status"] != "AVAILABLE":
            continue
        section = _section_of(g)
        if section is None or section["cemetery_id"] != cemetery_id:
            continue
        if g["gravesite_class"] == requested:
            candidates.append(("GRAVESITE", g, section))

    if requested == "CREMATION":
        for n in db.niches.values():
            if n["status"] != "AVAILABLE":
                continue
            section = _section_of(n)
            if section is None or section["cemetery_id"] != cemetery_id:
                continue
            candidates.append(("NICHE", n, section))

    if not candidates:
        return None

    def rank_key(item):
        unit_type, unit, section = item
        # 1) unit-kind priority: exact-class gravesite (0) before niche fallback (1)
        kind_priority = 0 if unit_type == "GRAVESITE" else 1
        # 2) section.code ASC
        code = section["code"]
        # 3) grid_ref / niche_ref ASC lexicographic
        ref = unit.get("grid_ref") if unit_type == "GRAVESITE" else unit.get("niche_ref")
        # 4) created_at ASC (use insertion seq as stable creation order)
        seq = unit["_seq"]
        return (kind_priority, code, ref, seq)

    candidates.sort(key=rank_key)
    unit_type, unit, _section = candidates[0]
    return unit, unit_type


# ---------------------------------------------------------------------------
# Marker charge (calc marker_charge, PRD §3.6)
# ---------------------------------------------------------------------------
def marker_charge(inscription_lines, emblem_of_belief):
    total_chars = sum(len(line) for line in inscription_lines)
    emblem_extra = EMBLEM_CHAR_EQUIV if emblem_of_belief else 0
    chargeable = max(total_chars + emblem_extra - FREE_CHARACTER_ALLOWANCE, 0)
    billable = chargeable
    blocks = math.ceil(chargeable / CHARS_PER_BLOCK) if chargeable > 0 else 0
    charge_cents = blocks * BLOCK_PRICE_CENTS
    return billable, charge_cents


# ---------------------------------------------------------------------------
# Overlap checks (calc overlap_gravesite / overlap_niche, PRD §3.7)
# ---------------------------------------------------------------------------
def gravesite_conflict(new_start, new_end, existing_schedules):
    """CLOSED-CLOSED with 48h buffer on each side."""
    buffer = GRAVESITE_BUFFER_HOURS * 3600
    for s in existing_schedules:
        s_start = parse_iso8601(s["window_start"])
        s_end = parse_iso8601(s["window_end"])
        if new_start.timestamp() <= s_end.timestamp() + buffer and \
           new_end.timestamp() + buffer >= s_start.timestamp():
            return True
    return False


def niche_conflict(new_start, new_end, existing_schedules):
    """HALF-OPEN [start, end), zero buffer; strict inequalities."""
    for s in existing_schedules:
        s_start = parse_iso8601(s["window_start"])
        s_end = parse_iso8601(s["window_end"])
        if new_start.timestamp() < s_end.timestamp() and s_start.timestamp() < new_end.timestamp():
            return True
    return False
