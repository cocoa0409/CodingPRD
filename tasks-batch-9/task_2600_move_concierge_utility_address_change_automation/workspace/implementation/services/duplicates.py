"""Calculation 1: duplicate_match_score and the two-pass duplicate detector."""

from decimal import Decimal

import db
from services import enums

ZERO = Decimal("0.00")
ONE = Decimal("1.00")
HALF = Decimal("0.50")
SIXTY = Decimal("0.60")


def _norm(text):
    return (text or "").strip().casefold()


def _last_token(name):
    parts = _norm(name).split()
    return parts[-1] if parts else ""


def name_component(candidate_resident, new_resident):
    a = _norm(candidate_resident["full_name"])
    b = _norm(new_resident["full_name"])
    if a and a == b:
        return ONE
    ta, tb = _last_token(a), _last_token(b)
    if ta and ta == tb:
        return SIXTY
    return ZERO


def email_component(candidate_resident, new_resident):
    a = _norm(candidate_resident["email"])
    b = _norm(new_resident["email"])
    return ONE if a and a == b else ZERO


def address_component(candidate_address, new_address):
    if candidate_address is None or new_address is None:
        return ZERO
    if candidate_address["address_hash"] == new_address["address_hash"]:
        return ONE
    if (
        candidate_address["postal_code"] == new_address["postal_code"]
        and candidate_address["state_code"] == new_address["state_code"]
    ):
        return HALF
    return ZERO


def recency_component(gap_days, window_days):
    if window_days <= 0:
        return ZERO
    quotient = (Decimal(window_days) - Decimal(gap_days)) / Decimal(window_days)
    return quotient if quotient > ZERO else ZERO


def _gap_days(a_date, b_date):
    return abs((a_date - b_date).days)


def score_pair(candidate, new_move, window_days):
    cand_resident = db.db.residents[candidate["resident_id"]]
    new_resident = db.db.residents[new_move["resident_id"]]
    cand_address = db.db.service_addresses.get(candidate["destination_address_id"])
    new_address = db.db.service_addresses.get(new_move["destination_address_id"])
    gap = _gap_days(
        db.parse_date(candidate["move_date"]), db.parse_date(new_move["move_date"])
    )
    total = (
        enums.WEIGHT_NAME * name_component(cand_resident, new_resident)
        + enums.WEIGHT_EMAIL * email_component(cand_resident, new_resident)
        + enums.WEIGHT_ADDRESS * address_component(cand_address, new_address)
        + enums.WEIGHT_RECENCY * recency_component(gap, window_days)
    )
    return db.round_money(total, 2)


def _shares_identifier(candidate, new_move):
    if candidate["resident_id"] == new_move["resident_id"]:
        return True
    cand_address = db.db.service_addresses.get(candidate["destination_address_id"])
    new_address = db.db.service_addresses.get(new_move["destination_address_id"])
    if (
        cand_address is not None
        and new_address is not None
        and cand_address["address_hash"] == new_address["address_hash"]
    ):
        return True
    cand_resident = db.db.residents.get(candidate["resident_id"])
    new_resident = db.db.residents.get(new_move["resident_id"])
    if (
        cand_resident is not None
        and new_resident is not None
        and _norm(cand_resident["email"]) == _norm(new_resident["email"])
    ):
        return True
    return False


def candidates(new_move, lifecycle_pool, window_days):
    """The shared candidate-selection rule for both passes."""
    new_date = db.parse_date(new_move["move_date"])
    out = []
    for m in db.db.moves.values():
        if m["id"] == new_move["id"]:
            continue
        if m["lifecycle_status"] not in lifecycle_pool:
            continue
        if m["duplicate_flag"] == "CONFIRMED_DUPLICATE":
            continue
        if not db.created_before(m, new_move):
            continue
        if _gap_days(db.parse_date(m["move_date"]), new_date) > window_days:
            continue
        if not _shares_identifier(m, new_move):
            continue
        out.append(m)
    return out


def best_match(new_move, lifecycle_pool, window_days):
    """Highest score first, then oldest created_at, then earliest move_date."""
    scored = []
    for m in candidates(new_move, lifecycle_pool, window_days):
        scored.append((score_pair(m, new_move, window_days), m))
    if not scored:
        return None, None
    scored.sort(
        key=lambda pair: (
            -pair[0],
            pair[1]["created_at"],
            pair[1]["move_date"],
            pair[1]["_seq"],
        )
    )
    return scored[0][1], scored[0][0]


def evaluate(new_move, feed_source):
    """Run both detector passes against the move row just written.

    Mutates the move in place; does not bump its version.
    """
    window_days = feed_source["dedupe_window_days"]
    new_move["duplicate_match_score"] = ZERO
    new_move["duplicate_candidate_move_id"] = None

    winner, score = best_match(new_move, enums.OPEN_LIFECYCLE, window_days)
    suspected = False
    if winner is not None:
        new_move["duplicate_match_score"] = score
        new_move["duplicate_candidate_move_id"] = winner["id"]
        if score >= enums.DUPLICATE_THRESHOLD:
            new_move["duplicate_flag"] = "SUSPECTED"
            new_move["blocked_reason"] = "DUPLICATE_SUSPECTED"
            suspected = True
        else:
            new_move["duplicate_flag"] = (
                "DISMISSED" if feed_source["trust_tier"] == "TIER_A" else "NONE"
            )
    else:
        new_move["duplicate_flag"] = "NONE"

    if not suspected:
        reactivation, react_score = best_match(
            new_move, enums.CLOSED_LIFECYCLE, window_days
        )
        if reactivation is not None:
            if winner is None:
                new_move["duplicate_match_score"] = react_score
            if react_score >= enums.DUPLICATE_THRESHOLD:
                new_move["reactivation_candidate_move_id"] = reactivation["id"]
    return new_move


def rescore(move, feed_source):
    """RESCORE re-runs the first pass from scratch against current data."""
    window_days = feed_source["dedupe_window_days"]
    winner, score = best_match(move, enums.OPEN_LIFECYCLE, window_days)
    if winner is None:
        move["duplicate_match_score"] = ZERO
        move["duplicate_candidate_move_id"] = None
        move["duplicate_flag"] = "NONE"
        if move["blocked_reason"] == "DUPLICATE_SUSPECTED":
            move["blocked_reason"] = "NONE"
        return move
    move["duplicate_match_score"] = score
    move["duplicate_candidate_move_id"] = winner["id"]
    if score >= enums.DUPLICATE_THRESHOLD:
        move["duplicate_flag"] = "SUSPECTED"
        move["blocked_reason"] = "DUPLICATE_SUSPECTED"
    else:
        move["duplicate_flag"] = (
            "DISMISSED" if feed_source["trust_tier"] == "TIER_A" else "NONE"
        )
        if move["blocked_reason"] == "DUPLICATE_SUSPECTED":
            move["blocked_reason"] = "NONE"
    return move
