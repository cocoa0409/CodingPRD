"""Calculation rules (SCAFFOLD §1.3 / PRD §3). Money in integer cents via
Decimal with ROUND_HALF_UP; scores rounded half-up to 2 dp at each step."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from db import DB, now_ts, parse_iso


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

W_CRAFTSMANSHIP = Decimal("0.5")
W_ACCURACY = Decimal("0.3")
W_PRESENTATION = Decimal("0.2")
TRIM_MIN_PANEL = 3

RANK1_SHARE = Decimal("0.50")
RANK2_SHARE = Decimal("0.30")

TAX_THRESHOLD_CENTS = 60000
BACKUP_WITHHOLDING_RATE = Decimal("0.24")

JUNIOR_AGE_LIMIT = 16
GREEN_ROOM_CAPACITY = 4
ACCESSIBLE_ROOMS = {"EAST"}

BANNED_PROP_TYPES = {"LIVE_STEEL", "FIREARM", "PYROTECHNICS"}

CENT = Decimal("1")
TWO_DP = Decimal("0.01")


def _rhup_int(value):
    """Round a Decimal half-up to an integer."""
    return int(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _rhup_2dp(value):
    """Round a Decimal half-up to two decimal places; returned as float for JSON."""
    return float(value.quantize(TWO_DP, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# category_purse_split — pinned rounding order, rank3 absorbs remainder
# ---------------------------------------------------------------------------

def purse_split(prize_purse_cents):
    purse = Decimal(int(prize_purse_cents))
    rank1 = _rhup_int(purse * RANK1_SHARE)
    rank2 = _rhup_int(purse * RANK2_SHARE)
    rank3 = int(prize_purse_cents) - rank1 - rank2
    return rank1, rank2, rank3


# ---------------------------------------------------------------------------
# ScoreSheet.sheet_total
# ---------------------------------------------------------------------------

def sheet_total(craftsmanship, accuracy, presentation):
    total = (
        W_CRAFTSMANSHIP * Decimal(int(craftsmanship))
        + W_ACCURACY * Decimal(int(accuracy))
        + W_PRESENTATION * Decimal(int(presentation))
    )
    return _rhup_2dp(total)


# ---------------------------------------------------------------------------
# entry_final_score — WEIGHTED_MEAN / TRIMMED_MEAN variants
# ---------------------------------------------------------------------------

def entry_final_score(entry, tabulation_method):
    """Compute (final_score, craftsmanship_mean) over the entry's LOCKED sheets."""
    locked = [
        s for s in DB.scoresheets.values()
        if s["entry_id"] == entry["id"] and s["status"] == "LOCKED"
    ]
    if not locked:
        return None, None
    totals = [Decimal(str(s["sheet_total"])) for s in locked]
    crafts = [Decimal(int(s["craftsmanship"])) for s in locked]

    if tabulation_method == "TRIMMED_MEAN" and len(totals) >= TRIM_MIN_PANEL:
        ordered = sorted(totals)
        trimmed = ordered[1:-1]  # drop exactly one lowest and one highest
        mean = sum(trimmed) / Decimal(len(trimmed))
    else:
        mean = sum(totals) / Decimal(len(totals))

    craft_mean = sum(crafts) / Decimal(len(crafts))
    return _rhup_2dp(mean), _rhup_2dp(craft_mean)


# ---------------------------------------------------------------------------
# placement_rank_assignment — final_score DESC, craftsmanship_mean DESC,
# created_at ASC (id NEVER a tie-break)
# ---------------------------------------------------------------------------

def assign_placements(category):
    """Compute scores for PERFORMED entries of the category, rank them, and
    flip them to PLACED. Returns the number of entries placed."""
    performed = [
        e for e in DB.entries.values()
        if e["category_id"] == category["id"] and e["status"] == "PERFORMED"
    ]
    scored = []
    for e in performed:
        final_score, craft_mean = entry_final_score(e, category["tabulation_method"])
        e["final_score"] = final_score
        e["craftsmanship_mean"] = craft_mean
        scored.append(e)

    scored.sort(key=lambda e: (
        -_score_key(e["final_score"]),
        -_score_key(e["craftsmanship_mean"]),
        e["created_at"],
    ))

    ts = now_ts()
    for idx, e in enumerate(scored, start=1):
        e["placement_rank"] = idx
        e["status"] = "PLACED"
        e["updated_at"] = ts
        e["version"] += 1
    return len(scored)


def _score_key(value):
    if value is None:
        return Decimal("-999999999")
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# prize_payout_net
# ---------------------------------------------------------------------------

def payout_net(value_cents, tax_form_received):
    if tax_form_received:
        return 0, int(value_cents)
    withheld = _rhup_int(Decimal(int(value_cents)) * BACKUP_WITHHOLDING_RATE)
    return withheld, int(value_cents) - withheld


# ---------------------------------------------------------------------------
# contest_tax_summary
# ---------------------------------------------------------------------------

def tax_summary(contest_id):
    included = [
        a for a in DB.prize_awards.values()
        if a["contest_id"] == contest_id and a["status"] in ("DISBURSED", "TAX_REPORTED")
    ]
    return {
        "total_prize_value_cents": sum(a["value_cents"] for a in included),
        "total_withheld_cents": sum(a["withheld_cents"] or 0 for a in included),
        "reportable_award_count": sum(1 for a in included if a["tax_reportable"]),
        "disbursed_award_count": len(included),
    }


# ---------------------------------------------------------------------------
# Budget computations (contest computed fields)
# ---------------------------------------------------------------------------

def budget_reserved(contest_id):
    return sum(
        a["value_cents"]
        for a in DB.prize_awards.values()
        if a["contest_id"] == contest_id
        and a["status"] in ("PENDING", "APPROVED", "DISBURSED", "TAX_REPORTED")
    )


# ---------------------------------------------------------------------------
# junior_age_eligibility — full calendar years between birth_date and the
# contest start DATE; a birthday ON the contest date has already occurred.
# ---------------------------------------------------------------------------

def age_at_contest(birth_date_str, contest_start_at):
    by, bm, bd = (int(p) for p in birth_date_str.split("-"))
    contest_dt = parse_iso(contest_start_at)
    contest_date = date(contest_dt.year, contest_dt.month, contest_dt.day)
    birth = date(by, bm, bd)
    age = contest_date.year - birth.year
    if (contest_date.month, contest_date.day) < (birth.month, birth.day):
        age -= 1
    return age


def junior_eligible(birth_date_str, contest_start_at):
    return age_at_contest(birth_date_str, contest_start_at) < JUNIOR_AGE_LIMIT


# ---------------------------------------------------------------------------
# stage_sequence_compaction — QUEUED slots resequenced 1..N by
# sequence_number ASC, tie-break created_at ASC; each bump increments version.
# ---------------------------------------------------------------------------

def compact_stage_sequence(contest_id):
    queued = [
        s for s in DB.performance_slots.values()
        if s["contest_id"] == contest_id and s["status"] == "QUEUED"
    ]
    queued.sort(key=lambda s: (s["sequence_number"], s["created_at"]))
    ts = now_ts()
    for idx, slot in enumerate(queued, start=1):
        if slot["sequence_number"] != idx:
            slot["sequence_number"] = idx
            slot["updated_at"] = ts
            slot["version"] += 1


# ---------------------------------------------------------------------------
# green_room_overlap_count — half-open on both ends; adjacency is NOT overlap.
# ---------------------------------------------------------------------------

def green_room_overlap_count(room_name, start_at, end_at, exclude_id=None):
    new_start = parse_iso(start_at)
    new_end = parse_iso(end_at)
    count = 0
    for b in DB.green_room_bookings.values():
        if b["room_name"] != room_name or b["status"] != "BOOKED":
            continue
        if exclude_id and b["id"] == exclude_id:
            continue
        ex_start = parse_iso(b["start_at"])
        ex_end = parse_iso(b["end_at"])
        if not (ex_end <= new_start or ex_start >= new_end):
            count += 1
    return count


# ---------------------------------------------------------------------------
# entry_count (category computed field)
# ---------------------------------------------------------------------------

def category_entry_count(category_id):
    return sum(
        1
        for e in DB.entries.values()
        if e["category_id"] == category_id
        and e["status"] not in ("WITHDRAWN", "DISQUALIFIED")
    )
