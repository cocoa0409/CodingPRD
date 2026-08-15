"""Rating engine: rating_update (PROVISIONAL/ESTABLISHED), event replay,
confirmation side effects, dispute-overturn void/repost cascade."""
import math
from fractions import Fraction

from db import store, new_id, next_seq, now_iso
from services.common import player_season, touch

RATED_RESULTS = ("WHITE_WIN", "BLACK_WIN", "DRAW")
FORFEIT_RESULTS = ("WHITE_FORFEIT_WIN", "BLACK_FORFEIT_WIN", "DOUBLE_FORFEIT")
ALL_RESULTS = RATED_RESULTS + FORFEIT_RESULTS

RATING_FLOOR = 100
RATING_CEILING = 2900
PROVISIONAL_SWING = 400
K_LOW, K_MID, K_HIGH = 32, 24, 16
K_TIER_BOUND_1, K_TIER_BOUND_2 = 2100, 2400


def round_half_up(x):
    """floor(x + 0.5) for all signs — a negative half rounds toward zero."""
    from decimal import Decimal, ROUND_FLOOR
    if isinstance(x, Fraction):
        return math.floor(x + Fraction(1, 2))
    if isinstance(x, Decimal):
        return int((x + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))
    return math.floor(x + 0.5)


def rating_update(rp, ro, score, games_before, threshold):
    """Returns (new_rating, formula_variant, k_factor)."""
    s = Fraction(score)
    n = games_before
    if n < threshold:
        raw = Fraction(rp * n + ro, 1) + PROVISIONAL_SWING * (2 * s - 1)
        new = round_half_up(raw / (n + 1))
        variant, k = "PROVISIONAL", None
    else:
        e = 1.0 / (1.0 + 10.0 ** ((ro - rp) / 400.0))
        if rp < K_TIER_BOUND_1:
            k = K_LOW
        elif rp < K_TIER_BOUND_2:
            k = K_MID
        else:
            k = K_HIGH
        new = rp + round_half_up(k * (float(s) - e))
        variant = "ESTABLISHED"
    new = max(RATING_FLOOR, min(RATING_CEILING, new))
    return new, variant, k


def effective_events(player_id):
    evs = [e for e in store.rating_events.values()
           if e["player_id"] == player_id and e["status"] == "EFFECTIVE"]

    def order_key(e):
        pairing = store.pairings.get(e["pairing_id"])
        p_created = pairing["created_at"] if pairing else ""
        p_seq = pairing.get("_seq", 0) if pairing else 0
        return (e["confirmed_at"], p_created, p_seq, e.get("_seq", 0))

    evs.sort(key=order_key)
    return evs


def replay_player(player):
    """Recompute rating fields from the player's EFFECTIVE events (PRD 3.5)."""
    season = player_season(player)
    threshold = season["provisional_game_threshold"]
    rating = player["initial_rating"]
    games = player["initial_rated_games"]
    peak = player["initial_rating"]
    for e in effective_events(player["id"]):
        before = rating
        after, variant, k = rating_update(rating, e["opponent_rating_snapshot"],
                                          e["score"], games, threshold)
        e["rating_before"] = before
        e["rating_after"] = after
        e["formula_variant"] = variant
        e["k_factor"] = k
        rating = after
        games += 1
        if after > peak:
            peak = after
    player["rating"] = rating
    player["rated_games_played"] = games
    player["peak_rating"] = peak
    player["is_provisional"] = games < threshold
    touch(player)


def _create_event(player, opponent, pairing, score, confirmed_at):
    e = {
        "id": new_id(), "_seq": next_seq(), "created_at": now_iso(),
        "player_id": player["id"], "pairing_id": pairing["id"],
        "season_id": store.meets[pairing["meet_id"]]["season_id"],
        "formula_variant": "PROVISIONAL",
        "opponent_rating_snapshot": opponent["rating"],
        "score": score,
        "k_factor": None,
        "rating_before": player["rating"],
        "rating_after": player["rating"],
        "confirmed_at": confirmed_at,
        "status": "EFFECTIVE",
    }
    store.rating_events[e["id"]] = e
    return e


def _scores(result):
    """(white_score, black_score) for a rated result."""
    if result == "WHITE_WIN":
        return 1, 0
    if result == "BLACK_WIN":
        return 0, 1
    return 0.5, 0.5  # DRAW


def apply_confirmation_effects(pairing):
    """Pairing reaches CONFIRMED (first confirmation, or resolution of a dispute
    on a never-confirmed pairing). Sets was_confirmed/confirmed_at and, for a
    rated result, appends one RatingEvent per player then replays both."""
    white = store.players[pairing["white_player_id"]]
    black = store.players[pairing["black_player_id"]]
    pairing["was_confirmed"] = True
    pairing["confirmed_at"] = now_iso()
    touch(pairing)
    if pairing["result"] in RATED_RESULTS:
        ws, bs = _scores(pairing["result"])
        _create_event(white, black, pairing, ws, pairing["confirmed_at"])
        _create_event(black, white, pairing, bs, pairing["confirmed_at"])
        replay_player(white)
        replay_player(black)


def apply_overturn_effects(pairing, resolved_result):
    """Fixed four-link cascade (PRD 3.6): replace result; void the two original
    events when was_confirmed; replay both players; when the new result is
    rated, create two fresh events with post-replay snapshots and replay again.
    Fresh events inherit the pairing's confirmed_at so replay order is stable."""
    white = store.players[pairing["white_player_id"]]
    black = store.players[pairing["black_player_id"]]
    was_confirmed = pairing["was_confirmed"]
    if was_confirmed:
        for e in store.rating_events.values():
            if e["pairing_id"] == pairing["id"] and e["status"] == "EFFECTIVE":
                e["status"] = "VOIDED"
        replay_player(white)
        replay_player(black)
    pairing["result"] = resolved_result
    if not was_confirmed:
        pairing["was_confirmed"] = True
        pairing["confirmed_at"] = now_iso()
    touch(pairing)
    if resolved_result in RATED_RESULTS:
        ws, bs = _scores(resolved_result)
        _create_event(white, black, pairing, ws, pairing["confirmed_at"])
        _create_event(black, white, pairing, bs, pairing["confirmed_at"])
        replay_player(white)
        replay_player(black)
