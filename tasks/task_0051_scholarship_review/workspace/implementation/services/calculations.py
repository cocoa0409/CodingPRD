"""Calculation rules from SCAFFOLD §1.3."""
from decimal import Decimal

import db
from clock import parse_iso, add_days
from services.validation import round_half_up


# ---- eligibility_check ----------------------------------------------------

def eligibility_check(application: dict, scholarship: dict) -> bool:
    if application.get("student_gpa_x100") is None:
        return False
    if application["student_gpa_x100"] < scholarship["gpa_threshold_x100"]:
        return False
    em = scholarship.get("eligible_majors") or []
    if em and application.get("student_major") not in em:
        return False
    eg = scholarship.get("eligible_grades") or []
    if eg and application.get("student_grade") not in eg:
        return False
    if scholarship.get("category") == "NEED":
        income = application.get("student_family_income_cents")
        if income is None:
            return False
        if income > scholarship.get("family_income_ceiling_cents", 0):
            return False
    return True


# ---- coi_check (helper, callers raise errors) ------------------------------

def coi_violation(reviewer: dict, application: dict) -> bool:
    if reviewer.get("department_code") == application.get("student_department_code"):
        return True
    if reviewer.get("id") == application.get("student_advisor_id"):
        return True
    rel = reviewer.get("family_relation_student_ids") or []
    if application.get("student_id") in rel:
        return True
    return False


# ---- aggregate_application_score ------------------------------------------

def aggregate_application_score(application_id: str, scholarship: dict):
    """Aggregate the 3 Score rows for an Application.

    Returns the new aggregated_score_x100 (int). May set is_outlier on dropped rows.
    Caller still needs to update Application.aggregated_score_x100.
    """
    score_rows = [s for s in db.scores.values() if s["application_id"] == application_id]
    score_rows.sort(key=lambda s: s["_seq"])
    if len(score_rows) != 3:
        # Defensive: should only be called when exactly 3 exist.
        return None

    raws = [s["raw_total_x100"] for s in score_rows]
    mean = sum(raws) / 3.0

    # Population standard deviation
    variance = sum((r - mean) ** 2 for r in raws) / 3.0
    stddev = variance ** 0.5

    threshold = scholarship.get("outlier_z_threshold_x100", 200)
    if stddev > 0:
        for s in score_rows:
            if abs(s["raw_total_x100"] - mean) * 100 > threshold * stddev:
                s["is_outlier"] = True
            else:
                s["is_outlier"] = False
    else:
        for s in score_rows:
            s["is_outlier"] = False

    kept = [s for s in score_rows if not s["is_outlier"]]
    if len(kept) == 0:
        agg_dec = Decimal(str(mean))
    else:
        kept_mean = sum(s["raw_total_x100"] for s in kept) / Decimal(len(kept))
        agg_dec = kept_mean

    return round_half_up(agg_dec)


# ---- dynamic_quota_adjustment ---------------------------------------------

def dynamic_quota_adjustment(scholarship_id: str):
    """Adjust QuotaAllocation.current_slots based on demand at OPEN→REVIEWING."""
    slices = [q for q in db.quota_allocations.values() if q["scholarship_id"] == scholarship_id]
    apps = [a for a in db.applications.values() if a["scholarship_id"] == scholarship_id]
    demand_statuses = {"SUBMITTED", "DEPT_PRELIM_PASSED", "DEPT_PRELIM_REJECTED"}

    # Demand count per slice
    demand = {}
    for s in slices:
        key = (s["department_code"], s["grade"], s["special_group"])
        demand[s["id"]] = sum(
            1 for a in apps
            if a["status"] in demand_statuses
            and a["student_department_code"] == key[0]
            and a["student_grade"] == key[1]
            and a.get("student_special_group", "NONE") == key[2]
        )

    # Baseline reset
    for s in slices:
        s["current_slots"] = s["initial_slots"]

    donor_pool = sum(max(0, s["initial_slots"] - demand[s["id"]]) for s in slices)
    over_demand_total = sum(max(0, demand[s["id"]] - s["initial_slots"]) for s in slices)

    if over_demand_total > 0 and donor_pool > 0:
        over_slices = [s for s in slices if demand[s["id"]] > s["initial_slots"]]
        # First pass: floor-share
        floor_shares = {}
        total_floor = 0
        for s in over_slices:
            excess = demand[s["id"]] - s["initial_slots"]
            share = (donor_pool * excess) // over_demand_total
            floor_shares[s["id"]] = share
            total_floor += share
        remainder = donor_pool - total_floor

        # Remainder distribution: descending demand_count, tie-break ascending id
        ordered = sorted(
            over_slices,
            key=lambda s: (-demand[s["id"]], s["id"]),
        )
        per_slice_extra = {s["id"]: 0 for s in over_slices}
        idx = 0
        while remainder > 0 and ordered:
            s = ordered[idx % len(ordered)]
            per_slice_extra[s["id"]] += 1
            remainder -= 1
            idx += 1

        for s in over_slices:
            s["current_slots"] = s["initial_slots"] + floor_shares[s["id"]] + per_slice_extra[s["id"]]

    # Slices with demand_count <= initial_slots → current_slots = demand_count
    for s in slices:
        if demand[s["id"]] <= s["initial_slots"]:
            s["current_slots"] = demand[s["id"]]
        db.stamp_update(s)


# ---- rank_and_award + unfilled_quota_reallocation -------------------------

def rank_and_award(scholarship_id: str, on_application_transition):
    """Rank REVIEW_COMPLETE applications within their slice and transition AWARDED/NOT_AWARDED.

    `on_application_transition(app, new_status, payload_extra=None)` is a callback
    that performs the actual state change (so the caller controls audit emit, etc.).
    """
    slices = [q for q in db.quota_allocations.values() if q["scholarship_id"] == scholarship_id]
    apps = [a for a in db.applications.values()
            if a["scholarship_id"] == scholarship_id and a["status"] == "REVIEW_COMPLETE"]

    # Group apps by slice key.
    by_slice = {s["id"]: [] for s in slices}
    no_slice = []
    slice_lookup = {(s["department_code"], s["grade"], s["special_group"]): s for s in slices}

    for a in apps:
        key = (a["student_department_code"], a["student_grade"], a.get("student_special_group", "NONE"))
        s = slice_lookup.get(key)
        if s is None:
            no_slice.append(a)
        else:
            by_slice[s["id"]].append(a)

    # Apps that don't match any slice — treat as NOT_AWARDED with no slot ownership.
    for a in no_slice:
        a["final_rank"] = 1
        on_application_transition(a, "NOT_AWARDED")

    for s in slices:
        s_apps = by_slice[s["id"]]
        s_apps.sort(key=lambda a: (-a.get("aggregated_score_x100", 0), a["id"]))
        for i, a in enumerate(s_apps, start=1):
            a["final_rank"] = i
            if i <= s["current_slots"]:
                on_application_transition(a, "AWARDED")
                s["filled_slots"] = s.get("filled_slots", 0) + 1
            else:
                on_application_transition(a, "NOT_AWARDED")
        db.stamp_update(s)


def unfilled_quota_reallocation(scholarship_id: str, on_application_transition):
    """Promote NOT_AWARDED applications up to unfilled current_slots across slices."""
    slices = [q for q in db.quota_allocations.values() if q["scholarship_id"] == scholarship_id]
    # Compute surplus pool and donor ids (slices with leftover slots).
    donors = []
    for s in slices:
        leftover = s["current_slots"] - s.get("filled_slots", 0)
        if leftover > 0:
            donors.append((s["id"], leftover))
    surplus_pool = sum(l for _, l in donors)
    if surplus_pool <= 0:
        return

    # Recipient slices: those that have at least one NOT_AWARDED Application.
    not_awarded_by_slice = {}
    slice_lookup = {(s["department_code"], s["grade"], s["special_group"]): s for s in slices}
    for a in db.applications.values():
        if a["scholarship_id"] != scholarship_id or a["status"] != "NOT_AWARDED":
            continue
        key = (a["student_department_code"], a["student_grade"], a.get("student_special_group", "NONE"))
        s = slice_lookup.get(key)
        if s is None:
            continue
        not_awarded_by_slice.setdefault(s["id"], []).append(a)

    recipient_ids = [sid for sid, lst in not_awarded_by_slice.items() if lst]
    id_to_slice = {s["id"]: s for s in slices}

    def ratio(sid):
        s = id_to_slice[sid]
        if s["current_slots"] > 0:
            return s.get("filled_slots", 0) / s["current_slots"]
        return 1.0

    recipient_ids.sort(key=lambda sid: (ratio(sid), sid))

    # Donor pool as a stack — pick lowest id first for deterministic appending
    donors.sort(key=lambda x: x[0])

    def take_donor():
        # Returns a donor slice id with positive leftover; mutates the local donors list.
        while donors:
            sid, leftover = donors[0]
            if leftover > 0:
                donors[0] = (sid, leftover - 1)
                if donors[0][1] == 0:
                    donors.pop(0)
                return sid
            donors.pop(0)
        return None

    for sid in recipient_ids:
        if surplus_pool <= 0:
            break
        candidates = not_awarded_by_slice[sid]
        candidates.sort(key=lambda a: (-a.get("aggregated_score_x100", 0), a["id"]))
        take = min(surplus_pool, len(candidates))
        s = id_to_slice[sid]
        for app in candidates[:take]:
            donor_sid = take_donor()
            on_application_transition(app, "AWARDED")
            s["filled_slots"] = s.get("filled_slots", 0) + 1
            ra = s.setdefault("reallocated_from_ids", [])
            if donor_sid is not None:
                ra.append(donor_sid)
            db.stamp_update(s)
        surplus_pool -= take


# ---- tax_withholding -------------------------------------------------------

TAX_TIERS = [
    (0,            500_000,         0),
    (500_000,      2_000_000,       3),
    (2_000_000,    5_000_000,       10),
    (5_000_000,    1_000_000_000,   20),
]


def compute_tax_withheld(gross_cents: int) -> int:
    base_tax = 0
    for (lo, hi, rate) in TAX_TIERS:
        if gross_cents <= lo:
            break
        slice_amount = min(gross_cents, hi) - lo
        if slice_amount > 0:
            base_tax += round_half_up(Decimal(slice_amount) * rate / Decimal(100))
    surcharge = round_half_up(Decimal(gross_cents) * 3 / Decimal(1000))
    return base_tax + surcharge


# ---- payment_channel_routing ----------------------------------------------

ROUTING_THRESHOLD_CENTS = 1_000_000


def route_channel(net_cents: int, plan_channel: str) -> str:
    if net_cents >= ROUTING_THRESHOLD_CENTS:
        return "BANK"
    return plan_channel


# ---- window-overlap helpers (cross-scholarship & cross-application) -------

def windows_half_open_overlap(a_start_iso: str, a_end_iso: str,
                              b_start_iso: str, b_end_iso: str) -> bool:
    """Intervals are half-open [start, end). Touching at boundary does NOT overlap."""
    a_s = parse_iso(a_start_iso)
    a_e = parse_iso(a_end_iso)
    b_s = parse_iso(b_start_iso)
    b_e = parse_iso(b_end_iso)
    return a_s < b_e and b_s < a_e


def windows_3day_buffered_overlap(a_start_iso: str, a_end_iso: str,
                                  b_start_iso: str, b_end_iso: str) -> bool:
    """Closed-closed intervals extended by +3 days on END only.

    Per PRD §3.3: "the buffered interval for each scholarship is the closed-closed
    interval running from its application_window_start to its application_window_end
    extended by an additional three days (i.e. application_window_end + 3 days,
    inclusive)".
    """
    a_s = parse_iso(a_start_iso)
    a_e = add_days(parse_iso(a_end_iso), 3)
    b_s = parse_iso(b_start_iso)
    b_e = add_days(parse_iso(b_end_iso), 3)
    return a_s <= b_e and b_s <= a_e
