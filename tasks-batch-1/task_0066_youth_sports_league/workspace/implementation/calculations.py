"""Domain calculations: league age, eval tier, snake order, seeding, refunds."""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def parse_date(s):
    return date.fromisoformat(s)


def parse_iso(s):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    if s is None:
        return None
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def league_age(birth_date_str, cutoff_str):
    """Completed years from birth_date to cutoff."""
    cutoff = parse_date(cutoff_str)
    bd = parse_date(birth_date_str)
    age = cutoff.year - bd.year
    if (bd.month, bd.day) > (cutoff.month, cutoff.day):
        age -= 1
    return age


def round_half_up_2(value):
    """Round a numeric to 2 decimals, half up. Returns a float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def eval_score_and_tier(eval_speed, eval_hitting, eval_fielding):
    raw = Decimal("0.50") * Decimal(eval_hitting) \
        + Decimal("0.30") * Decimal(eval_fielding) \
        + Decimal("0.20") * Decimal(eval_speed)
    score = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if score >= Decimal("70.00"):
        tier = "A"
    elif score >= Decimal("55.00"):
        tier = "B"
    elif score >= Decimal("40.00"):
        tier = "C"
    else:
        tier = "D"
    return float(score), tier


def snake_expected_slot(picks_made, team_count, draft_snake):
    """Return (round_number, expected_slot, overall_number) for the next pick."""
    T = team_count
    round_number = picks_made // T + 1
    pos_in_round = picks_made % T
    if draft_snake and round_number % 2 == 0:
        expected_slot = T - pos_in_round
    else:
        expected_slot = pos_in_round + 1
    overall_number = picks_made + 1
    return round_number, expected_slot, overall_number


def win_pct_fraction(wins, losses):
    """Return win pct as a (numerator, denominator) exact rational; 0 if no games."""
    decided = wins + losses
    if decided == 0:
        return (0, 1)
    return (wins, decided)


def round_half_up_cents(value):
    """Round a numeric to whole cents, half up. Returns an int."""
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def volunteer_fee(credit_cents):
    """5% admin fee on a credit, rounded half up to whole cents."""
    return round_half_up_cents(Decimal(credit_cents) * Decimal("0.05"))


def intervals_overlap(s1, e1, s2, e2):
    """Half-open [s,e) strict overlap test."""
    return s1 < e2 and s2 < e1
