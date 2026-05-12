"""Review spam scoring & aggregate computation."""
from datetime import timedelta

from db import (
    store, parse_iso, now_dt,
    SHORT_COMMENT_THRESHOLD, REPEAT_REVIEW_THRESHOLD, SCORE_SPREAD_THRESHOLD,
    SPAM_SIGNAL_HARD_BLOCK,
)


def compute_spam_signal_count(review: dict, is_resubmit: bool) -> int:
    count = 0
    # Snapshot of REJECTED reviews by author taken before step 1
    author_rejected_with_round = sum(
        1 for r in store.reviews.values()
        if r.get("author_player_id") == review.get("author_player_id")
        and r["id"] != review.get("id")
        and r.get("status") == "REJECTED"
        and int(r.get("moderation_round", 0)) >= 1
    )

    # Step 1 — Length signal
    comment = review.get("comment") or ""
    if len(comment) < SHORT_COMMENT_THRESHOLD:
        count += 1

    # Step 2 — Repetition signal (last 24h, same theme_id)
    booking = store.bookings.get(review.get("booking_id"))
    theme_id = None
    if booking:
        slot = store.session_slots.get(booking.get("slot_id"))
        if slot:
            theme_id = slot.get("theme_id")
    cutoff = now_dt() - timedelta(hours=24)
    rep_count = 0
    if theme_id:
        for r in store.reviews.values():
            if r["id"] == review.get("id"):
                continue
            if r.get("author_player_id") != review.get("author_player_id"):
                continue
            r_book = store.bookings.get(r.get("booking_id"))
            if not r_book:
                continue
            r_slot = store.session_slots.get(r_book.get("slot_id"))
            if not r_slot:
                continue
            if r_slot.get("theme_id") != theme_id:
                continue
            try:
                created = parse_iso(r.get("created_at"))
            except Exception:
                continue
            if created >= cutoff:
                rep_count += 1
    if rep_count >= REPEAT_REVIEW_THRESHOLD:
        count += 1

    # Step 3 — Score-spread signal: max(theme,venue) - min(theme,venue) >= 3
    theme_score = review.get("theme_score") or 0
    venue_score = review.get("venue_score") or 0
    if abs(int(theme_score) - int(venue_score)) >= SCORE_SPREAD_THRESHOLD:
        count += 1

    # Step 4 — Tier signal: prior REJECTED with moderation_round>=1 (snapshot)
    if author_rejected_with_round >= 1:
        count += 1

    # Step 5 — Resubmission signal
    if is_resubmit and int(review.get("moderation_round", 0)) > 0:
        count += 1

    return count


def recompute_theme_aggregates(theme_id: str):
    """Recompute aggregated_theme_score, aggregated_host_score, aggregated_venue_score on Theme."""
    theme = store.themes.get(theme_id)
    if not theme:
        return

    sums = {"theme_score": 0, "host_score": 0, "venue_score": 0}
    counts = {"theme_score": 0, "host_score": 0, "venue_score": 0}

    for r in store.reviews.values():
        if r.get("status") != "PUBLISHED":
            continue
        booking = store.bookings.get(r.get("booking_id"))
        if not booking:
            continue
        slot = store.session_slots.get(booking.get("slot_id"))
        if not slot or slot.get("theme_id") != theme_id:
            continue
        for d in ("theme_score", "host_score", "venue_score"):
            if r.get(d) is not None:
                sums[d] += int(r[d])
                counts[d] += 1

    def round_half_up_to_one_decimal(s, c):
        if c == 0:
            return None
        v = s / c * 10
        # round half up
        from decimal import Decimal, ROUND_HALF_UP
        rounded = int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return rounded / 10.0

    theme["aggregated_theme_score"] = round_half_up_to_one_decimal(sums["theme_score"], counts["theme_score"])
    theme["aggregated_host_score"] = round_half_up_to_one_decimal(sums["host_score"], counts["host_score"])
    theme["aggregated_venue_score"] = round_half_up_to_one_decimal(sums["venue_score"], counts["venue_score"])
