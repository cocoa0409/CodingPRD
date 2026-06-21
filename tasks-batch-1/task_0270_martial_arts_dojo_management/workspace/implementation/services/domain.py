"""Core domain logic: computed-field reconciliation, calculations, cascades.

All behavioral claims trace to PRD §2.5-2.8 and §3. Money is integer cents;
rounding is half-up with the per-calculation order pinned by PRD §2.7.
"""
from decimal import Decimal

from db import db
from common import round_half_up, parse_iso8601

# ---- Constants (SCAFFOLD §1.3 / PRD §3) ----------------------------------
SUSPEND_THRESHOLD_CENTS = 10000
TEST_BALANCE_CEILING_CENTS = 10000
PASS_SCORE = 70
BUYOUT_RATE = Decimal("0.50")
BUYOUT_CAP_CENTS = 50000

# Family discount tiers (PRD §3.2)
TIER_2_PCT = Decimal("0.10")
TIER_3_PCT = Decimal("0.15")
TIER_4_PLUS_PCT = Decimal("0.20")

# Pro-shop belt tiers (PRD §2.8)
BELT_TIER_HIGH_PCT = Decimal("0.15")
BELT_TIER_MID_PCT = Decimal("0.10")
HIGH_RANK_ORDER = 5
MID_RANK_ORDER = 2

# Tournament division ages (PRD §3.7)
TEEN_MIN_AGE = 13
ADULT_MIN_AGE = 18
MASTERS_MIN_AGE = 40


# ---- system field bumps --------------------------------------------------

def touch(rec):
    """Bump updated_at + version on a mutated record."""
    rec["updated_at"] = db.now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ---- Family discount tier (PRD §3.2, SCAFFOLD family_discount_tier) -------

def count_family_members(family_id):
    """n = members in the family with account_status IN {ACTIVE, FROZEN}."""
    if family_id is None:
        return 0
    n = 0
    for m in db.members.values():
        if m.get("family_id") == family_id and m["account_status"] in ("ACTIVE", "FROZEN"):
            n += 1
    return n


def discount_pct_for_count(n):
    if n <= 1:
        return Decimal("0.00")
    if n == 2:
        return TIER_2_PCT
    if n == 3:
        return TIER_3_PCT
    return TIER_4_PLUS_PCT  # n >= 4


def live_family_discount_pct(family_id):
    """The live tier based on the family's current roster."""
    return discount_pct_for_count(count_family_members(family_id))


def recompute_family_active_member_count(family_id):
    if family_id is None:
        return
    fam = db.families.get(family_id)
    if fam is None:
        return
    fam["active_member_count"] = count_family_members(family_id)
    touch(fam)


# ---- Outstanding balance (PRD §2.5) --------------------------------------

def member_outstanding_balance(member_id):
    """Sum of amount_due_cents over the member's DUE|OVERDUE invoices."""
    total = 0
    for inv in db.invoices.values():
        if inv["member_id"] == member_id and inv["status"] in ("DUE", "OVERDUE"):
            total += inv["amount_due_cents"]
    return total


def recompute_member_balance(member_id):
    """Recompute outstanding_balance_cents and run suspend / unsuspend cascades.

    Returns nothing; mutates the member and cascades as needed."""
    member = db.members.get(member_id)
    if member is None:
        return
    member["outstanding_balance_cents"] = member_outstanding_balance(member_id)
    _maybe_suspend(member)
    _maybe_unsuspend(member)


def _maybe_suspend(member):
    """ACTIVE -> SUSPENDED when balance strictly above threshold (PRD §3.3)."""
    if (member["account_status"] == "ACTIVE"
            and member["outstanding_balance_cents"] > SUSPEND_THRESHOLD_CENTS):
        member["account_status"] = "SUSPENDED"
        touch(member)
        # Cascade: every ACTIVE contract -> PAST_DUE (which strips tournaments).
        for contract in db.contracts.values():
            if contract["member_id"] == member["id"] and contract["status"] == "ACTIVE":
                contract["status"] = "PAST_DUE"
                touch(contract)
                _cascade_contract_past_due_tournaments(member["id"])


def _maybe_unsuspend(member):
    """SUSPENDED -> ACTIVE when balance back at/below threshold (PRD §3.3)."""
    if (member["account_status"] == "SUSPENDED"
            and member["outstanding_balance_cents"] <= SUSPEND_THRESHOLD_CENTS):
        member["account_status"] = "ACTIVE"
        touch(member)
        # Cascade: each PAST_DUE contract whose member balance is clear -> ACTIVE.
        for contract in db.contracts.values():
            if (contract["member_id"] == member["id"]
                    and contract["status"] == "PAST_DUE"):
                contract["status"] = "ACTIVE"
                touch(contract)


def _cascade_contract_past_due_tournaments(member_id):
    """Contract ACTIVE->PAST_DUE strips future REGISTERED tournament spots."""
    now = db.now()
    for reg in db.tournament_registrations.values():
        if (reg["member_id"] == member_id
                and reg["status"] == "REGISTERED"
                and parse_iso8601(reg["event_date"]) > now):
            reg["status"] = "WITHDRAWN"
            touch(reg)


# ---- Invoice creation ----------------------------------------------------

def make_invoice(member_id, kind, amount_due_cents, contract_id=None, due_at=None):
    """Create a DUE invoice. due_at defaults to the current clock when absent."""
    now_iso = db.now_iso()
    inv_id = db.new_id()
    if due_at is None:
        due_at = now_iso
    inv = {
        "id": inv_id,
        "member_id": member_id,
        "contract_id": contract_id,
        "kind": kind,
        "amount_due_cents": amount_due_cents,
        "status": "DUE",
        "due_at": due_at,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.invoices[inv_id] = inv
    return inv


# ---- recurring tuition charge (PRD §3.6, SCAFFOLD recurring_tuition_charge)

def recurring_tuition_amount(program, locked_pct):
    """base - round_half_up(base * pinned_pct); floored at 0."""
    base = program["base_monthly_tuition_cents"]
    discount_cents = round_half_up(Decimal(base) * Decimal(locked_pct))
    amount = base - discount_cents
    return max(0, amount)


# ---- pro-shop pricing (PRD §2.8, SCAFFOLD pro_shop_pricing) ---------------

def member_highest_active_rank_order(member_id):
    """Highest BeltRank.rank_order across the member's ACTIVE enrollments; 0 if none."""
    best = 0
    found = False
    for enr in db.enrollments.values():
        if enr["member_id"] == member_id and enr["status"] == "ACTIVE":
            rank = _belt_rank(enr["program_id"], enr["current_rank_code"])
            if rank is not None:
                found = True
                if rank["rank_order"] > best:
                    best = rank["rank_order"]
    return best if found else 0


def pro_shop_member_pct(member_id):
    max_rank = member_highest_active_rank_order(member_id)
    if max_rank >= HIGH_RANK_ORDER:
        return BELT_TIER_HIGH_PCT
    if max_rank >= MID_RANK_ORDER:
        return BELT_TIER_MID_PCT
    return Decimal("0.00")


def compute_pro_shop_amounts(member_id, line_items):
    """Return (gross_cents, net_cents). Round per line BEFORE summing (PRD §2.8)."""
    pct = pro_shop_member_pct(member_id)
    gross = 0
    net = 0
    for li in line_items:
        line_total = li["unit_price_cents"] * li["qty"]
        gross += line_total
        discount = round_half_up(Decimal(line_total) * pct)
        net += (line_total - discount)
    return gross, net


# ---- early termination buyout (PRD §3.6, SCAFFOLD early_termination_buyout)

def buyout_amount(remaining_months, monthly_cents):
    """round_half_up(remaining * monthly * 0.50) then cap at 50000."""
    raw = round_half_up(Decimal(remaining_months) * Decimal(monthly_cents) * BUYOUT_RATE)
    return min(raw, BUYOUT_CAP_CENTS)


# ---- private lesson charge (PRD §3.7, SCAFFOLD private_lesson_charge) -----

def private_lesson_amount(hourly_rate_cents, starts_at_iso, ends_at_iso):
    """duration_minutes between starts/ends (ends exclusive); single rounding."""
    start = parse_iso8601(starts_at_iso)
    end = parse_iso8601(ends_at_iso)
    duration_minutes = (end - start).total_seconds() / 60.0
    raw = Decimal(hourly_rate_cents) * (Decimal(duration_minutes) / Decimal(60))
    return round_half_up(raw)


# ---- testing eligibility (PRD §3.5, SCAFFOLD testing_eligibility_score) ---

def whole_days_between(start_iso, now_dt):
    start = parse_iso8601(start_iso)
    delta = now_dt - start
    days = int(delta.total_seconds() // 86400)
    return max(0, days)


def test_eligibility(enrollment):
    """Return (eligible, readiness, failed_gates) per PRD §3.5."""
    program = db.programs[enrollment["program_id"]]
    member = db.members[enrollment["member_id"]]
    now = db.now()

    rank_att = enrollment["rank_attendance_count"]
    min_att = program["min_attendance_for_test"]
    days_in_rank = whole_days_between(enrollment["rank_acquired_at"], now)
    min_days = program["min_days_in_rank"]
    rank = _belt_rank(enrollment["program_id"], enrollment["current_rank_code"])
    next_code = rank["next_rank_code"] if rank else None

    failed = []
    if not (rank_att >= min_att):
        failed.append("attendance")
    if not (days_in_rank >= min_days):
        failed.append("days_in_rank")
    if member["account_status"] != "ACTIVE":
        failed.append("account_status")
    if not member["waiver_signed"]:
        failed.append("waiver_signed")
    if not (member["outstanding_balance_cents"] <= TEST_BALANCE_CEILING_CENTS):
        failed.append("outstanding_balance")
    if next_code is None:
        failed.append("rank_terminal")

    eligible = len(failed) == 0

    att_ratio = Decimal(rank_att) / Decimal(max(1, min_att))
    if att_ratio > 1:
        att_ratio = Decimal(1)
    days_ratio = Decimal(days_in_rank) / Decimal(max(1, min_days))
    if days_ratio > 1:
        days_ratio = Decimal(1)
    readiness_raw = Decimal(40) * att_ratio + Decimal(60) * days_ratio
    readiness = round_half_up(readiness_raw)
    if readiness > 100:
        readiness = 100

    return eligible, readiness, failed


# ---- tournament division (PRD §3.7, SCAFFOLD tournament_division) ---------

def tournament_division(date_of_birth_iso, event_date_iso):
    dob = parse_iso8601(date_of_birth_iso)
    event = parse_iso8601(event_date_iso)
    age = event.year - dob.year
    # subtract one if birthday hasn't occurred yet on/before event date
    if (event.month, event.day) < (dob.month, dob.day):
        age -= 1
    if age < TEEN_MIN_AGE:
        return "YOUTH"
    if age < ADULT_MIN_AGE:
        return "TEEN"
    if age < MASTERS_MIN_AGE:
        return "ADULT"
    return "MASTERS"


# ---- belt-rank lookup helpers --------------------------------------------

def _belt_rank(program_id, code):
    for r in db.belt_ranks.values():
        if r["program_id"] == program_id and r["code"] == code:
            return r
    return None


def entry_rank_for_program(program_id):
    for r in db.belt_ranks.values():
        if r["program_id"] == program_id and r.get("is_entry_rank"):
            return r
    return None


# ---- promotion application (PRD §3.5) ------------------------------------

def apply_promotion(enrollment, target_rank_code):
    """Advance the belt on the enrollment; COMPLETED if target is terminal."""
    enrollment["current_rank_code"] = target_rank_code
    enrollment["rank_acquired_at"] = db.now_iso()
    enrollment["rank_attendance_count"] = 0
    new_rank = _belt_rank(enrollment["program_id"], target_rank_code)
    if new_rank is not None and new_rank["next_rank_code"] is None:
        enrollment["status"] = "COMPLETED"
    touch(enrollment)


# ---- instructor booking overlap (PRD §3.4 / §3.7) ------------------------

def instructor_has_overlap(instructor_id, start_iso, end_iso, exclude_lesson_id=None):
    """True if [start, end) overlaps another CONFIRMED private lesson or
    SCHEDULED class session of this instructor (half-open; adjacency allowed)."""
    start = parse_iso8601(start_iso)
    end = parse_iso8601(end_iso)
    for cs in db.class_sessions.values():
        if cs["instructor_id"] == instructor_id and cs["status"] == "SCHEDULED":
            if _overlaps(start, end, parse_iso8601(cs["starts_at"]), parse_iso8601(cs["ends_at"])):
                return True
    for pl in db.private_lessons.values():
        if pl["id"] == exclude_lesson_id:
            continue
        if pl["instructor_id"] == instructor_id and pl["status"] == "CONFIRMED":
            if _overlaps(start, end, parse_iso8601(pl["starts_at"]), parse_iso8601(pl["ends_at"])):
                return True
    return False


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: true iff a_start < b_end AND b_start < a_end."""
    return a_start < b_end and b_start < a_end
