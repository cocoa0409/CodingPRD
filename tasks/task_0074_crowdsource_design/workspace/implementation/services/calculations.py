"""Calculation helpers — precision-sensitive math (Decimal, round_half_up)."""
from decimal import ROUND_HALF_UP, Decimal


# Constants from §1.3
RESIDENT_RATE = Decimal("0.20")
NONRES_TIER1_RATE = Decimal("0.20")
NONRES_TIER2_RATE = Decimal("0.30")
TIER_BREAK_CENTS = 400_000  # 4,000.00 minor units

PEER_WEIGHT = Decimal("0.70")
PUBLIC_WEIGHT = Decimal("0.30")  # 1 - PEER_WEIGHT
PRELIM_ORIGINALITY_FLOOR = Decimal("60.00")
TRUST_PENALTY_ON_REJECT = Decimal("10.00")

OUTLIER_TRIM_THRESHOLD = 5
CLIENT_WEIGHT = Decimal("0.30")


def to_decimal(x, default=Decimal("0")) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if x is None:
        return default
    try:
        return Decimal(str(x))
    except Exception:
        return default


def round_half_up_cents(value) -> int:
    """Round to integer cents using round-half-up."""
    d = to_decimal(value)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> Decimal:
    d = to_decimal(value)
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_float_2dp(value) -> float:
    """Round half up to 2 decimals and return float for JSON serialization."""
    return float(round_half_up_2dp(value))


# --- prize_withholding -------------------------------------------------------


def compute_withholding(gross_cents: int, residency: str) -> dict:
    """Returns {gross_amount_cents, withholding_cents, net_amount_cents}.

    residency must be 'RESIDENT' or 'NON_RESIDENT'.
    """
    gross = int(gross_cents)
    if residency == "RESIDENT":
        withholding = round_half_up_cents(Decimal(gross) * RESIDENT_RATE)
    elif residency == "NON_RESIDENT":
        below = min(gross, TIER_BREAK_CENTS)
        above = max(gross - TIER_BREAK_CENTS, 0)
        tier1 = round_half_up_cents(Decimal(below) * NONRES_TIER1_RATE)
        tier2 = round_half_up_cents(Decimal(above) * NONRES_TIER2_RATE)
        withholding = tier1 + tier2
    else:
        # Defensive: treat unknown residency as resident-flat.
        withholding = round_half_up_cents(Decimal(gross) * RESIDENT_RATE)
    net = gross - withholding
    return {
        "gross_amount_cents": gross,
        "withholding_cents": withholding,
        "net_amount_cents": net,
    }


# --- submission_originality_score -------------------------------------------


def originality_score_preliminary(public_sim) -> float:
    """variant=PRELIMINARY_SCAN: score = round_half_up( (1 - public_sim) * 100, 2 )."""
    public = to_decimal(public_sim)
    score = (Decimal("1") - public) * Decimal("100")
    return to_float_2dp(score)


def originality_score_final(public_sim, peer_sim) -> float:
    """variant=FINAL_CROSSCHECK: combined = max(public, PEER_WEIGHT*peer + PUBLIC_WEIGHT*public)."""
    public = to_decimal(public_sim)
    peer = to_decimal(peer_sim)
    blended = PEER_WEIGHT * peer + PUBLIC_WEIGHT * public
    combined = public if public > blended else blended
    score = (Decimal("1") - combined) * Decimal("100")
    return to_float_2dp(score)


# --- assignment_aggregated_score --------------------------------------------


def aggregated_score(criterion_scores: dict, rubric: dict) -> float:
    """Weighted sum per rubric weights.

    Per §1.3 calc order: per-criterion no rounding -> sum (full precision) ->
    round_half_up to 2 decimals. We pre-round each criterion score to 2 dp
    (input pre-rounding) per PRD §3.5 wording.
    """
    total = Decimal("0")
    for code, weight in rubric.items():
        s = to_decimal(criterion_scores.get(code, 0))
        s = s.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        w = to_decimal(weight)
        total += s * (w / Decimal("100"))
    return to_float_2dp(total)


# --- submission_aggregate_score ---------------------------------------------


def stage_aggregate(scores_with_meta, stage_kind: str, client_participates_final: bool) -> float:
    """Compute the per-submission stage aggregate.

    scores_with_meta: list of {"id": assignment.id, "score": float, "is_client": bool}
    Returns the aggregate as a float (2 dp) or None if empty.
    """
    if not scores_with_meta:
        return None

    # Sort ascending by (score, id) for deterministic trimming.
    sorted_list = sorted(
        scores_with_meta,
        key=lambda x: (to_decimal(x["score"]), x["id"]),
    )

    n = len(sorted_list)
    if n >= OUTLIER_TRIM_THRESHOLD:
        trimmed = sorted_list[1:-1]
    else:
        trimmed = list(sorted_list)

    if not trimmed:
        return None

    use_client_blend = (
        stage_kind == "FINAL"
        and client_participates_final
        and any(item.get("is_client") for item in scores_with_meta)
    )

    if use_client_blend:
        # Use the original (non-trimmed) client score; if multiple, pick lowest-id.
        client_items = sorted(
            (item for item in scores_with_meta if item.get("is_client")),
            key=lambda x: x["id"],
        )
        client_score = to_decimal(client_items[0]["score"])
        # Reviewer-only list = trimmed minus any client items inside it.
        trimmed_reviewers = [item for item in trimmed if not item.get("is_client")]
        if trimmed_reviewers:
            mean_reviewers = sum(to_decimal(it["score"]) for it in trimmed_reviewers) / Decimal(len(trimmed_reviewers))
        else:
            mean_reviewers = Decimal("0")
        weighted = CLIENT_WEIGHT * client_score + (Decimal("1") - CLIENT_WEIGHT) * mean_reviewers
        return to_float_2dp(weighted)

    mean = sum(to_decimal(it["score"]) for it in trimmed) / Decimal(len(trimmed))
    return to_float_2dp(mean)
