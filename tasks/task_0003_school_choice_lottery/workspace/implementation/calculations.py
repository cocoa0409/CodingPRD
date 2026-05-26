"""Calculations per PRD §3.6, §3.7, §3.8 and SCAFFOLD §1.3.

- lottery_weight_total (provisional and final variants)
- family_risk_score (provisional and final variants)
- school_acceptance_rate
- lottery_seat_assignment (waterfall with IDT cap)
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from db import store, parse_iso8601


D = Decimal


def _round3(value) -> float:
    """Round half-up to 3 decimal places; return float for JSON."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(quant)


def _has_sibling_at_school(student_id, school_id, accepted_statuses):
    """True iff a SiblingBond ties (student_id, school_id) AND the linked sibling
    student has at least one Application against this school whose status is in
    accepted_statuses."""
    bonds = [
        b for b in store.sibling_bonds.values()
        if b["student_id"] == student_id and b["school_id"] == school_id
    ]
    if not bonds:
        return False
    sibling_ids = {b["sibling_student_id"] for b in bonds}
    for app in store.applications.values():
        if app["student_id"] in sibling_ids and app["school_id"] == school_id and app["status"] in accepted_statuses:
            return True
    return False


def _has_in_boundary(school_id: str, zone_code: str) -> bool:
    for r in store.boundary_rules.values():
        if r["school_id"] == school_id and r["zone_code"] == zone_code and r["is_in_boundary"]:
            return True
    return False


def compute_lottery_weight(application: dict, variant: str) -> float:
    """Compute lottery_weight per the §3.6 formula and ordering pin.

    variant: "provisional" or "final".
    """
    if variant == "final":
        sibling_statuses = {"ENROLLED"}
    else:  # provisional
        sibling_statuses = {"SUBMITTED", "ACCEPTED", "ENROLLED"}

    student = store.students.get(application["student_id"]) or {}
    family = store.families.get(student.get("family_id", "")) or {}
    school_id = application["school_id"]

    # Term 1: base
    base = D("1.000")

    # Term 2: sibling
    sibling_boost = D("0.500") if _has_sibling_at_school(
        application["student_id"], school_id, sibling_statuses
    ) else D("0.000")

    # Term 3: in-boundary
    in_boundary = D("0.300") if _has_in_boundary(school_id, family.get("residence_zone_code", "")) else D("0.000")

    # Term 4: poverty boost — rounded INDEPENDENTLY to 3 decimals before being summed.
    district = store.districts.get(family.get("residence_district_id", "")) or {}
    pov_pct = D(str(district.get("poverty_index_pct", 0)))
    poverty_boost_raw = pov_pct / D("100") * D("0.400")
    poverty_boost = poverty_boost_raw.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    # Term 5: family flag
    family_flag_boost = D("0.200") if family.get("poverty_flag") else D("0.000")

    total = base + sibling_boost + in_boundary + poverty_boost + family_flag_boost
    return _round3(total)


def compute_family_risk_score(family_id: str, variant: str) -> float:
    """Compute family_risk_score per §3.7.

    provisional: 0.15*waitlisted - 0.20*enrolled; ignore DECLINED.
    final:       0.35*declined + 0.15*waitlisted - 0.20*enrolled.
    Round half-up to 3 decimals, then clamp to [0.000, 1.000].
    """
    apps = [a for a in store.applications.values()
            if (store.students.get(a["student_id"]) or {}).get("family_id") == family_id]
    cnt_declined = sum(1 for a in apps if a["status"] == "DECLINED")
    cnt_waitlisted = sum(1 for a in apps if a["status"] == "WAITLISTED")
    cnt_enrolled = sum(1 for a in apps if a["status"] == "ENROLLED")

    if variant == "final":
        raw = D("0.35") * cnt_declined + D("0.15") * cnt_waitlisted + D("-0.20") * cnt_enrolled
    else:
        raw = D("0.15") * cnt_waitlisted + D("-0.20") * cnt_enrolled

    rounded = raw.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if rounded < D("0.000"):
        rounded = D("0.000")
    if rounded > D("1.000"):
        rounded = D("1.000")
    return float(rounded)


def compute_school_acceptance_rate(school_id: str):
    """Return (acceptance_rate, is_competitive, source_window_id_or_none) per §3.8."""
    school = store.schools.get(school_id) or {}
    district_id = school.get("district_id")
    # Find most recent runnable window in this district
    candidates = [
        w for w in store.windows.values()
        if w["district_id"] == district_id and w["status"] in ("LOTTERY_RUN", "FINALIZED")
    ]
    if not candidates:
        # No qualifying window → denominator is zero → rate is 0.000 (§3.8).
        # is_competitive uses strict less-than 0.300, so 0.000 < 0.300 → True.
        return 0.000, True, None
    # Sort by lottery_runs_at DESC, then created_at ASC for tie-break
    def _key(w):
        lra = parse_iso8601(w["lottery_runs_at"])
        ca = parse_iso8601(w["created_at"])
        return (-lra.timestamp(), ca.timestamp())
    candidates.sort(key=_key)
    src = candidates[0]
    window_id = src["id"]

    apps_for_school = [a for a in store.applications.values()
                       if a["school_id"] == school_id and a["window_id"] == window_id]
    n_accepted = sum(1 for a in apps_for_school if a["status"] == "ACCEPTED")
    n_denom = sum(1 for a in apps_for_school if a["status"] in ("SUBMITTED", "ACCEPTED", "WAITLISTED"))

    if n_denom == 0:
        rate = 0.000
    else:
        raw = D(n_accepted) / D(n_denom)
        rate = float(raw.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
    is_competitive = rate < 0.300
    return rate, is_competitive, window_id


def compute_idt_cap(total_seats):
    """floor(0.10 * total_seats)."""
    return (total_seats * 10) // 100  # integer floor


def assign_lottery_ranks(apps_for_school, total_seats):
    """Sort and assign lottery_rank + decide ACCEPTED vs WAITLISTED with IDT cap.

    Returns (accepted_list, waitlisted_list) where each list is in rank order
    and each app dict gets `lottery_rank` (1-based) set. WAITLISTED entries
    are paired with queue_rank = lottery_rank - total_seats.

    The sort key per §3.6:
      1) lottery_weight DESC
      2) family.poverty_flag DESC (true before false)
      3) created_at ASC
    """
    def _key(a):
        family = store.families.get((store.students.get(a["student_id"]) or {}).get("family_id", "")) or {}
        pov = 1 if family.get("poverty_flag") else 0
        ca = parse_iso8601(a["created_at"]).timestamp()
        return (-float(a["lottery_weight"]), -pov, ca)

    apps_sorted = sorted(apps_for_school, key=_key)
    for i, a in enumerate(apps_sorted, start=1):
        a["lottery_rank"] = i

    idt_cap = compute_idt_cap(total_seats)
    accepted = []
    waitlisted = []
    idt_admitted = 0

    # School & families for IDT check
    school_district = (store.schools.get(apps_sorted[0]["school_id"]) if apps_sorted else {}) if apps_sorted else {}
    # We'll recompute per-app to be safe
    for a in apps_sorted:
        school = store.schools.get(a["school_id"]) or {}
        family = store.families.get((store.students.get(a["student_id"]) or {}).get("family_id", "")) or {}
        is_idt = school.get("district_id") != family.get("residence_district_id")
        if len(accepted) < total_seats:
            if is_idt and idt_admitted >= idt_cap:
                # demote: skip into waitlist
                waitlisted.append(a)
            else:
                accepted.append(a)
                if is_idt:
                    idt_admitted += 1
        else:
            waitlisted.append(a)

    return accepted, waitlisted
