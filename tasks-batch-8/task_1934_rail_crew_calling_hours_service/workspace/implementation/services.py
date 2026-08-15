"""Business logic: calculations, cascades, board rotation, selectors (PRD §3)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, base_record, touch, minutes_between

# ---------------------------------------------------------------------------
# Constants (PRD §2.6 / scaffold §1.3)
# ---------------------------------------------------------------------------
MAX_DUTY_MINUTES_PER_TOUR = 720
MAX_DUTY_MINUTES_PER_MONTH = 16560
DEFAULT_PROJECTED_TOUR_MINUTES = 480
LONG_TOUR_PROJECTED_MINUTES = 700
SHORT_TOUR_PROJECTED_MINUTES = 100
MIN_UNDISTURBED_REST_MINUTES = 600
EARLY_REPORT_WINDOW_MINUTES = 60
CALL_RESPONSE_WINDOW_MINUTES = 120
FATIGUE_BLOCK_THRESHOLD = 80.0
LEAVE_QUOTA_PER_CRAFT_DAY = 1
BASIC_DAY_CENTS = 30010
OT_MULTIPLIER = Decimal("1.5")
OVERTIME_THRESHOLD_MINUTES = 480
DEADHEAD_HOURLY_CENTS = 18755
TRAIN_DEADHEAD_MULTIPLIER = Decimal("1.075")

CRAFTS = ("CONDUCTOR", "ENGINEER", "BRAKEMAN", "YARDMASTER")
DEADHEAD_MODES = ("NONE", "TAXI", "COMPANY_VEHICLE", "TRAIN")
LEAVE_TYPES = ("VACATION", "PERSONAL_DAY")


# ---------------------------------------------------------------------------
# agreement_pay (scaffold §1.3): provisional = round per component then sum;
# final = sum exact then round once. ROUND_HALF_UP to integer cents.
# ---------------------------------------------------------------------------
def _rhu(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def agreement_pay(claimed_minutes, claimed_deadhead_minutes, deadhead_mode, variant):
    basic = (
        Decimal(BASIC_DAY_CENTS)
        * Decimal(min(claimed_minutes, OVERTIME_THRESHOLD_MINUTES))
        / Decimal(OVERTIME_THRESHOLD_MINUTES)
    )
    overtime = (
        OT_MULTIPLIER
        * Decimal(BASIC_DAY_CENTS)
        * Decimal(max(claimed_minutes - OVERTIME_THRESHOLD_MINUTES, 0))
        / Decimal(OVERTIME_THRESHOLD_MINUTES)
    )
    deadhead = (
        Decimal(DEADHEAD_HOURLY_CENTS)
        * Decimal(claimed_deadhead_minutes)
        / Decimal(60)
    )
    if deadhead_mode == "TRAIN":
        deadhead = deadhead * TRAIN_DEADHEAD_MULTIPLIER
    if variant == "provisional":
        return _rhu(basic) + _rhu(overtime) + _rhu(deadhead)
    return _rhu(basic + overtime + deadhead)


# ---------------------------------------------------------------------------
# hos_duty_accumulation (chronological ledger + forward-looking accept gate)
# ---------------------------------------------------------------------------
def projected_tour_minutes(job_symbol):
    if isinstance(job_symbol, str) and job_symbol.endswith("-L"):
        return LONG_TOUR_PROJECTED_MINUTES
    if isinstance(job_symbol, str) and job_symbol.endswith("-S"):
        return SHORT_TOUR_PROJECTED_MINUTES
    return DEFAULT_PROJECTED_TOUR_MINUTES


def _duty_rows(emp_id):
    now = store.now
    rows = [
        a for a in store.assignments.values()
        if a["employee_id"] == emp_id
        and a["on_duty_at"] is not None
        and a["assignment_status"] in ("ON_DUTY", "TIE_UP_PENDING", "COMPLETED", "RECREWED")
        and a["on_duty_at"].year == now.year
        and a["on_duty_at"].month == now.month
    ]
    rows.sort(key=lambda a: (a["on_duty_at"], a["_seq"]))
    return rows


def recompute_cumulative(emp_id):
    emp = store.employees.get(emp_id)
    if emp is None:
        return
    total = 0
    for a in _duty_rows(emp_id):
        end = a["off_duty_at"] if a["off_duty_at"] is not None else store.now
        total += minutes_between(a["on_duty_at"], end)
    emp["cumulative_duty_minutes_month"] = total


def on_duty_elapsed_now(emp_id):
    """Minutes accrued right now on an ON_DUTY assignment (forward gate term)."""
    total = 0
    for a in store.assignments.values():
        if (
            a["employee_id"] == emp_id
            and a["assignment_status"] == "ON_DUTY"
            and a["on_duty_at"] is not None
        ):
            total += minutes_between(a["on_duty_at"], store.now)
    return total


# ---------------------------------------------------------------------------
# fatigue_index (weighted scoring, clamp 0..100, 1 decimal ROUND_HALF_UP)
# ---------------------------------------------------------------------------
def recompute_fatigue(emp_id):
    emp = store.employees.get(emp_id)
    if emp is None:
        return
    now = store.now
    term1 = Decimal("0.5") * (
        Decimal(emp["cumulative_duty_minutes_month"])
        / Decimal(MAX_DUTY_MINUTES_PER_MONTH)
        * Decimal(100)
    )
    duty_days = set()
    for a in store.assignments.values():
        if a["employee_id"] == emp_id and a["on_duty_at"] is not None:
            duty_days.add(a["on_duty_at"].date())
    streak = 0
    day = now.date()
    while day in duty_days:
        streak += 1
        day = day - timedelta(days=1)
    term2 = Decimal("0.3") * Decimal(streak * 10)
    cutoff = now - timedelta(days=30)
    disturbed = sum(
        1
        for rp in store.rest_periods.values()
        if rp["employee_id"] == emp_id
        and rp["rest_status"] == "DISTURBED"
        and cutoff <= rp["rest_start"] <= now
    )
    term3 = Decimal("0.2") * Decimal(disturbed * 15)
    score = term1 + term2 + term3
    if score < 0:
        score = Decimal(0)
    elif score > 100:
        score = Decimal(100)
    emp["fatigue_score"] = float(score.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# board_rotation (penalty rotation / freeze / restore / vacate / append)
# ---------------------------------------------------------------------------
def board_active_slots(board_id):
    return sorted(
        (
            s for s in store.slots.values()
            if s["board_id"] == board_id and s["slot_status"] == "ACTIVE"
        ),
        key=lambda s: (s["standing_position"], s["_seq"]),
    )


def renumber_board(board_id):
    for i, s in enumerate(board_active_slots(board_id), start=1):
        if s["standing_position"] != i:
            s["standing_position"] = i
            touch(s)


def penalty_rotate(slot):
    """Offending ACTIVE slot -> last position; slots behind it shift up one."""
    if slot["slot_status"] != "ACTIVE":
        return
    actives = board_active_slots(slot["board_id"])
    n = len(actives)
    p = slot["standing_position"]
    for s in actives:
        if s["id"] != slot["id"] and s["standing_position"] > p:
            s["standing_position"] -= 1
            touch(s)
    if slot["standing_position"] != n:
        slot["standing_position"] = n
    touch(slot)


def freeze_employee_slots(emp_id):
    affected = set()
    for s in store.slots.values():
        if s["employee_id"] == emp_id and s["slot_status"] == "ACTIVE":
            # standing_position is kept as the remembered position
            s["slot_status"] = "FROZEN"
            touch(s)
            affected.add(s["board_id"])
    for board_id in affected:
        renumber_board(board_id)


def restore_employee_slots(emp_id):
    frozen = sorted(
        (
            s for s in store.slots.values()
            if s["employee_id"] == emp_id and s["slot_status"] == "FROZEN"
        ),
        key=lambda s: s["_seq"],
    )
    for s in frozen:
        actives = board_active_slots(s["board_id"])
        p = s["standing_position"]
        if not isinstance(p, int):
            p = len(actives) + 1
        p = max(1, min(p, len(actives) + 1))
        for a in actives:
            if a["standing_position"] >= p:
                a["standing_position"] += 1
                touch(a)
        s["slot_status"] = "ACTIVE"
        s["standing_position"] = p
        touch(s)


def vacate_employee_slots(emp_id):
    affected = set()
    for s in store.slots.values():
        if s["employee_id"] == emp_id and s["slot_status"] == "ACTIVE":
            s["slot_status"] = "VACATED"
            s["standing_position"] = None
            touch(s)
            affected.add(s["board_id"])
    for board_id in affected:
        renumber_board(board_id)


def append_slot(board_id, emp_id):
    slot = base_record()
    slot.update({
        "board_id": board_id,
        "employee_id": emp_id,
        "slot_status": "ACTIVE",
        "standing_position": len(board_active_slots(board_id)) + 1,
    })
    store.slots[slot["id"]] = slot
    return slot


def find_matching_board(craft, terminal):
    matches = [
        b for b in store.boards.values()
        if b["craft"] == craft and b["terminal"] == terminal
    ]
    if not matches:
        return None
    matches.sort(key=lambda b: b["_seq"])
    return matches[0]


def return_to_board_tail(emp):
    board = find_matching_board(emp["craft"], emp["home_terminal"])
    if board is not None:
        append_slot(board["id"], emp["id"])


# ---------------------------------------------------------------------------
# calling_selector (scaffold §1.3)
# ---------------------------------------------------------------------------
def matching_boards_exist(job):
    return any(
        b["craft"] == job["craft"] and b["terminal"] == job["origin_terminal"]
        for b in store.boards.values()
    )


def eligible_slots(job):
    out = []
    for s in store.slots.values():
        if s["slot_status"] != "ACTIVE":
            continue
        b = store.boards.get(s["board_id"])
        if b is None or b["craft"] != job["craft"] or b["terminal"] != job["origin_terminal"]:
            continue
        e = store.employees.get(s["employee_id"])
        if e is None or e["availability_status"] != "AVAILABLE":
            continue
        if e["fatigue_score"] >= FATIGUE_BLOCK_THRESHOLD:
            continue
        out.append(s)
    out.sort(key=lambda s: (s["standing_position"], s["_seq"]))
    return out


def open_shortage(job):
    sh = base_record()
    sh.update({
        "job_id": job["id"],
        "craft": job["craft"],
        "shortage_status": "OPEN",
        "opened_at": store.now,
        "resolved_at": None,
    })
    store.shortages[sh["id"]] = sh
    return sh


# ---------------------------------------------------------------------------
# Rest periods
# ---------------------------------------------------------------------------
def open_rest(emp_id):
    rp = base_record(with_version=False)  # RestPeriod: no updated_at / version
    rp.update({
        "employee_id": emp_id,
        "rest_start": store.now,
        "rest_end": None,
        "rest_status": "OPEN",
        "undisturbed_minutes": 0,
    })
    store.rest_periods[rp["id"]] = rp
    return rp


def open_rest_for(emp_id):
    for rp in store.rest_periods.values():
        if rp["employee_id"] == emp_id and rp["rest_status"] == "OPEN":
            return rp
    return None


def rest_elapsed(rp):
    end = rp["rest_end"] if rp["rest_end"] is not None else store.now
    return minutes_between(rp["rest_start"], end)


def refresh_rest(rp):
    """Keep undisturbed_minutes current (recomputed as the clock advances)."""
    rp["undisturbed_minutes"] = rest_elapsed(rp)
    return rp


# ---------------------------------------------------------------------------
# Call helpers
# ---------------------------------------------------------------------------
def slot_for_call(call):
    """The callee's ACTIVE slot on a board matching the call's job context."""
    job = store.jobs.get(call["job_id"])
    if job is None:
        return None
    cands = []
    for s in store.slots.values():
        if s["employee_id"] != call["employee_id"] or s["slot_status"] != "ACTIVE":
            continue
        b = store.boards.get(s["board_id"])
        if b is not None and b["craft"] == job["craft"] and b["terminal"] == job["origin_terminal"]:
            cands.append(s)
    if not cands:
        return None
    cands.sort(key=lambda s: s["_seq"])
    return cands[0]


def run_expiry_sweep():
    """OFFERED calls with expires_at <= now transition to EXPIRED + penalty."""
    expired = []
    due = [
        c for c in store.calls.values()
        if c["call_status"] == "OFFERED" and c["expires_at"] <= store.now
    ]
    due.sort(key=lambda c: (c["expires_at"], c["_seq"]))
    for c in due:
        c["call_status"] = "EXPIRED"
        c["responded_at"] = c["expires_at"]
        touch(c)
        slot = slot_for_call(c)
        if slot is not None:
            penalty_rotate(slot)
        expired.append(c["id"])
    for rp in store.rest_periods.values():
        if rp["rest_status"] == "OPEN":
            rp["undisturbed_minutes"] = rest_elapsed(rp)
    return expired
