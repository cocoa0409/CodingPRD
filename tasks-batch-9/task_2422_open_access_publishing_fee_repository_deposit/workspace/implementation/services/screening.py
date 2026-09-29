"""predatory_screening_score (PRD 3.1)."""
from decimal import Decimal

import constants as C
from clock import clock
from db import set_fields
from util import dec, round_half_up


def run_screening(publisher, signals):
    score = 0
    if signals["doaj_indexed"] is False:
        score += C.W_NO_DOAJ
    if signals["cope_member"] is False:
        score += C.W_NO_COPE
    if signals["editorial_board_verified"] is False:
        score += C.W_NO_BOARD
    retraction = round_half_up(dec(signals["retraction_rate_per_1000"]) * Decimal(C.RETRACTION_MULTIPLIER))
    score += min(C.W_RETRACTION_CAP, retraction)
    if signals["peer_review_days_median"] < C.PEER_REVIEW_MIN_DAYS:
        score += C.W_FAST_REVIEW
    score -= round_half_up(dec(signals["apc_transparency_score"]) * Decimal(C.TRANSPARENCY_CREDIT))

    predatory_score = max(0, min(100, score))
    if predatory_score >= C.BLOCK_MIN:
        status = "BLOCKED"
    elif predatory_score >= C.FLAG_MIN:
        status = "PREDATORY_FLAGGED"
    elif predatory_score >= C.WATCH_MIN:
        status = "WATCHLIST"
    else:
        status = "CLEARED"

    set_fields(
        publisher,
        _force=True,
        doaj_indexed=signals["doaj_indexed"],
        cope_member=signals["cope_member"],
        editorial_board_verified=signals["editorial_board_verified"],
        retraction_rate_per_1000=signals["retraction_rate_per_1000"],
        peer_review_days_median=signals["peer_review_days_median"],
        apc_transparency_score=signals["apc_transparency_score"],
        predatory_score=predatory_score,
        screening_status=status,
        author_guidance=C.AUTHOR_GUIDANCE[status],
        last_screened_at=clock.now_iso(),
    )
    return publisher
