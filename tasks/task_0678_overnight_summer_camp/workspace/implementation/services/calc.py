"""Calculation rules (SCAFFOLD §1.3 / PRD §3.5, §3.2, §3.8, §3.9).

All monetary quantities are integer cents — pure integer arithmetic, no rounding
(PRD §2.7). Staffing weight is kept x10 to stay integral.
"""
import math

import db

# --- list_tuition constants (SCAFFOLD §1.3 list_tuition) ---
BASE_TUITION_CENTS = 400000
EARLY_DISCOUNT_CENTS = 30000
LATE_SURCHARGE_CENTS = 25000
MED_PER_MED_CENTS = 1500
EPIPEN_SUPPORT_CENTS = 5000


def latest_nondraft_health_form(camper_id):
    """Return the camper's latest HealthForm (by created_at, then seq) whose
    status is in {SUBMITTED, CLEARED, FLAGGED}, or None.
    """
    candidates = [
        hf for hf in db.health_forms.values()
        if hf["camper_id"] == camper_id and hf["status"] in ("SUBMITTED", "CLEARED", "FLAGGED")
    ]
    if not candidates:
        return None
    # latest by created_at, tie-break by creation seq (both ascending -> take last)
    candidates.sort(key=lambda hf: (hf["created_at_dt"], hf["_seq"]))
    return candidates[-1]


def compute_list_tuition(session, camper):
    """Tiered, surcharge-adjusted gross tuition. Evaluation order PINNED:
    (1) days_before_start -> tier, (2) apply tier, (3) ADD med support. (PRD §3.5)
    """
    clock = db.now()
    starts_on = session["starts_on_dt"]
    # whole days before start, rounded down (may be negative)
    delta_seconds = (starts_on - clock).total_seconds()
    days_before_start = math.floor(delta_seconds / 86400.0)

    if days_before_start >= 60:
        tier_cents = BASE_TUITION_CENTS - EARLY_DISCOUNT_CENTS
    elif days_before_start >= 14:
        tier_cents = BASE_TUITION_CENTS
    else:
        tier_cents = BASE_TUITION_CENTS + LATE_SURCHARGE_CENTS

    hf = latest_nondraft_health_form(camper["id"])
    med_support = 0
    if hf is not None:
        med_support = hf["daily_medication_count"] * MED_PER_MED_CENTS
        if hf["has_life_threatening_allergy"]:
            med_support += EPIPEN_SUPPORT_CENTS

    return tier_cents + med_support


def _applied_payments(application_id):
    return [
        p for p in db.payments.values()
        if p["application_id"] == application_id and p["status"] == "APPLIED"
    ]


def compute_estimated_balance(application):
    """FORWARD-LOOKING / OPTIMISTIC (PRD §3.5).

    aid inclusion set = {REQUESTED, APPROVED}; pooled single-step subtraction,
    floored at zero once.
    """
    app_id = application["id"]
    optimistic_aid = sum(
        a["amount_cents"] for a in db.financial_aid_awards.values()
        if a["application_id"] == app_id and a["status"] in ("REQUESTED", "APPROVED")
    )
    applied_payments = sum(p["amount_cents"] for p in _applied_payments(app_id))
    return max(0, application["list_tuition_cents"] - optimistic_aid - applied_payments)


def compute_settled_balance(application):
    """CHRONOLOGICAL / AUTHORITATIVE (PRD §3.5).

    aid inclusion set = {APPROVED} ONLY. Replays APPROVED-aid and APPLIED-payment
    events in created_at ASC order (tie-break created_at equal -> aid before
    payment), flooring at 0 PER EVENT against running = list_tuition_cents.
    """
    app_id = application["id"]
    events = []
    for a in db.financial_aid_awards.values():
        if a["application_id"] == app_id and a["status"] == "APPROVED":
            # kind_order 0 => aid applied before payment on created_at tie
            events.append((a["created_at_dt"], 0, a["_seq"], a["amount_cents"]))
    for p in _applied_payments(app_id):
        events.append((p["created_at_dt"], 1, p["_seq"], p["amount_cents"]))

    # sort by created_at ASC; tie -> aid (0) before payment (1); then seq
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    running = application["list_tuition_cents"]
    for _, _, _, amount in events:
        running = max(0, running - amount)
    return running


def compute_aid_total(application):
    """Total APPROVED aid currently applied to the application (PRD §3.5)."""
    app_id = application["id"]
    return sum(
        a["amount_cents"] for a in db.financial_aid_awards.values()
        if a["application_id"] == app_id and a["status"] == "APPROVED"
    )


def compute_cabin_staff_weight(cabin):
    """Effective staff weight x10 over ACTIVE assignments to background-cleared
    staff. COUNSELOR=10; CIT=5 when cit_counts_as_half else 10. (PRD §3.2)
    """
    session = db.sessions[cabin["session_id"]]
    camp = db.camps[session["camp_id"]]
    cit_half = camp["cit_counts_as_half"]
    total = 0
    for ca in db.cabin_assignments.values():
        if ca["cabin_id"] != cabin["id"] or ca["status"] != "ACTIVE":
            continue
        staff = db.staff_members.get(ca["staff_member_id"])
        if staff is None or not staff["is_background_cleared"]:
            continue
        if staff["role_kind"] == "COUNSELOR":
            total += 10
        else:  # CIT
            total += 5 if cit_half else 10
    return total


def compute_cabin_is_staffable(cabin, counselor_camper_ratio):
    """A cabin is staffable when staff weight covers campers at ratio. Boundary
    PINNED as >=. Empty cabin always staffable. (PRD §3.2)
    """
    occupied = cabin["occupied_bunks"]
    if occupied == 0:
        return True
    required_weight_x10 = math.ceil(occupied / counselor_camper_ratio) * 10
    return cabin["staff_weight_x10"] >= required_weight_x10


def compute_session_ratio_posture(session):
    """Aggregate posture over cabins with occupied_bunks > 0. Boundaries PINNED.
    (PRD §3.2)
    """
    occupied_cabins = [
        c for c in db.cabins.values()
        if c["session_id"] == session["id"] and c["occupied_bunks"] > 0
    ]
    if not occupied_cabins:
        return "UNDERSTAFFED"
    staffable_flags = [c["is_staffable"] for c in occupied_cabins]
    if all(staffable_flags):
        return "STAFFED"
    if any(staffable_flags):
        return "MARGINAL"
    return "UNDERSTAFFED"


def activity_conflicts(new_offering, existing_offering):
    """True when new_offering conflicts with existing_offering on the same
    slot_day, via raw half-open interval overlap OR buffer-window violation.
    (PRD §3.8)

    Caller guarantees both are on the same slot_day.
    """
    n_start = new_offering["starts_minute"]
    n_end = new_offering["ends_minute"]
    n_buf = new_offering["setup_buffer_minutes"]
    e_start = existing_offering["starts_minute"]
    e_end = existing_offering["ends_minute"]
    e_buf = existing_offering["setup_buffer_minutes"]

    # (A) raw half-open [start, end) overlap. Adjacency (end == start) allowed.
    raw_overlap = (n_start < e_end) and (e_start < n_end)
    if raw_overlap:
        return True

    # (B) buffer collision (PRD §3.8). The two offerings must be separated by a
    # buffered gap in whichever direction one follows the other:
    #   - new sits after existing:   n_start >= e_end + e_buf
    #   - existing sits after new:   e_start >= n_end + n_buf
    # These are the two "symmetric" sub-conditions; for raw-disjoint intervals
    # exactly one direction is the operative one and clears when its gap is
    # respected. The booking is fine if EITHER direction's buffered gap holds;
    # the buffer window is "violated" only when NEITHER does. The boundary is
    # inclusive (>=): a start exactly at the other's end + buffer is allowed.
    gap_after = n_start >= e_end + e_buf
    gap_before = e_start >= n_end + n_buf
    if not (gap_after or gap_before):
        return True

    return False


def compute_canteen_balance(account_id):
    """balance = sum(APPLIED DEPOSIT) - sum(APPLIED PURCHASE) (PRD §3.9)."""
    deposits = 0
    purchases = 0
    for t in db.canteen_transactions.values():
        if t["account_id"] != account_id or t["status"] != "APPLIED":
            continue
        if t["kind"] == "DEPOSIT":
            deposits += t["amount_cents"]
        else:  # PURCHASE
            purchases += t["amount_cents"]
    return deposits - purchases
