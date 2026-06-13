"""Calculation rules (§1.3 / PRD §2.5, §3.4, §3.6, §3.8)."""
from decimal import Decimal, ROUND_HALF_UP

from services.common import round_half_up, round_half_up_dp
from services import lookups

RETAINAGE_PCT = Decimal("0.10")
PRICE_WEIGHT = Decimal("0.5")
DURATION_WEIGHT = Decimal("0.3")
RATING_WEIGHT = Decimal("0.2")


# ---------------------------------------------------------------------------
# bid_line_total / bid total: round per line, then sum
# ---------------------------------------------------------------------------
def line_total(quantity, unit_price_cents):
    return round_half_up(Decimal(str(quantity)) * Decimal(str(unit_price_cents)))


def recompute_bid_total(bid):
    total = 0
    for li in lookups.line_items_for_bid(bid["id"]):
        total += li["line_total_cents"]
    bid["total_cents"] = total
    return total


# ---------------------------------------------------------------------------
# project_estimate: per-line round then sum
# ---------------------------------------------------------------------------
def scope_line_estimate(quantity, estimated_unit_cost_cents):
    return round_half_up(Decimal(str(quantity)) * Decimal(str(estimated_unit_cost_cents)))


def project_estimate(project_id):
    items = lookups.scope_items_for_project(project_id)
    total = 0
    for s in items:
        total += s["estimated_total_cents"]
    return total, len(items)


# ---------------------------------------------------------------------------
# bid_rank_score: weighted, lower is better, 4 dp round-half-up
# ---------------------------------------------------------------------------
def compute_rank_scores(submitted_bids):
    """Return a dict bid_id -> rank_score (float, 4dp) over the SUBMITTED pool."""
    scores = {}
    if not submitted_bids:
        return scores
    totals = [b["total_cents"] for b in submitted_bids]
    durations = [b["duration_days"] for b in submitted_bids]
    min_total, max_total = min(totals), max(totals)
    min_dur, max_dur = min(durations), max(durations)

    for b in submitted_bids:
        if max_total == min_total:
            price_norm = Decimal("0")
        else:
            price_norm = (Decimal(b["total_cents"]) - Decimal(min_total)) / (
                Decimal(max_total) - Decimal(min_total))
        if max_dur == min_dur:
            dur_norm = Decimal("0")
        else:
            dur_norm = (Decimal(b["duration_days"]) - Decimal(min_dur)) / (
                Decimal(max_dur) - Decimal(min_dur))
        contractor = lookups.get_contractor(b["contractor_id"])
        rating_norm = (Decimal("5") - Decimal(str(contractor["average_rating"]))) / Decimal("5")
        raw = (PRICE_WEIGHT * price_norm
               + DURATION_WEIGHT * dur_norm
               + RATING_WEIGHT * rating_norm)
        score = float(raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        scores[b["id"]] = score
    return scores


def rank_bids(submitted_bids):
    """Return submitted bids sorted best-first.

    Order: lower rank_score, then lower total_cents, then earlier created_at.
    Annotates each returned dict copy with its rank_score.
    """
    scores = compute_rank_scores(submitted_bids)
    annotated = []
    for b in submitted_bids:
        copy = dict(b)
        copy["rank_score"] = scores[b["id"]]
        annotated.append(copy)
    annotated.sort(key=lambda b: (b["rank_score"], b["total_cents"], b.get("_seq", 0)))
    return annotated, scores


# ---------------------------------------------------------------------------
# draw_release_amounts: provisional at request (frozen)
# ---------------------------------------------------------------------------
def draw_amounts(contract_value_cents, release_pct, is_final):
    gross = round_half_up(Decimal(str(contract_value_cents)) * Decimal(str(release_pct)))
    if is_final:
        retainage = 0
    else:
        retainage = round_half_up(Decimal(gross) * RETAINAGE_PCT)
    net = gross - retainage
    return gross, retainage, net


# ---------------------------------------------------------------------------
# contractor_average_rating: 2 dp round-half-up
# ---------------------------------------------------------------------------
def average_rating(rating_sum, rating_count):
    if rating_count == 0:
        return 0
    return round_half_up_dp(Decimal(rating_sum) / Decimal(rating_count), 2)
