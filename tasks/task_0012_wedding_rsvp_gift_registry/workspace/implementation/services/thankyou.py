"""ThankYouNote helpers and the completion-score calculation
(scaffold §1.3 thank_you_completion_score, PRD §3.6)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import db


def _round_half_up(value: Decimal, places: int) -> Decimal:
    quant = Decimal(10) ** -places
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def auto_create_thank_you(purchase: dict, wedding_id: str) -> dict:
    """Create a PENDING ThankYouNote attached to a freshly-CONFIRMED purchase.

    Idempotent: returns the existing row if one already exists.
    """
    for t in db.thank_you_notes.values():
        if t.get("purchase_id") == purchase["id"]:
            return t
    note = {
        "purchase_id": purchase["id"],
        "wedding_id": wedding_id,
        "status": "PENDING",
        "drafted_body": None,
        "sent_at": None,
    }
    db.stamp_common(note)
    db.thank_you_notes[note["id"]] = note
    return note


def delete_thank_you_for_purchase(purchase_id: str) -> int:
    """Hard-delete any ThankYouNote whose purchase_id matches. Returns count."""
    n = 0
    for tid, t in list(db.thank_you_notes.items()):
        if t.get("purchase_id") == purchase_id:
            del db.thank_you_notes[tid]
            n += 1
    return n


def thank_you_report(wedding_id: str) -> dict:
    """Returns the weighted completion-score payload for a wedding.

    PRD §3.6 / scaffold §1.3:
      W_SENT=1.00, W_DRAFTED=0.40, W_PENDING=0.00.
      S_raw = N_sent + 0.4*N_drafted   (PENDING contributes 0)
      completion_pct = round_half_up(S_raw / N_total * 100, 2) if N_total > 0
                      else 100.00.
      is_complete = (N_sent == N_total) and (N_total > 0).
    """
    n_total = 0
    n_sent = 0
    n_drafted = 0
    n_pending = 0
    for t in db.thank_you_notes.values():
        if t.get("wedding_id") != wedding_id:
            continue
        # PRD §3.6: include notes attached to CONFIRMED purchases. ThankYouNotes
        # are only ever attached to CONFIRMED purchases (created on CONFIRMED
        # transition and hard-deleted on cancel), so every surviving row
        # qualifies; we still cross-check to be safe.
        purchase = db.purchases.get(t.get("purchase_id"))
        if purchase is None or purchase.get("status") != "CONFIRMED":
            continue
        n_total += 1
        s = t.get("status")
        if s == "SENT":
            n_sent += 1
        elif s == "DRAFTED":
            n_drafted += 1
        elif s == "PENDING":
            n_pending += 1

    if n_total == 0:
        completion_pct = Decimal("100.00")
    else:
        # Aggregate at full precision, then divide, then *100, then round once.
        s_raw = Decimal(n_sent) * Decimal("1.00") + Decimal(n_drafted) * Decimal("0.40")
        # PENDING contributes 0.
        pct = (s_raw / Decimal(n_total)) * Decimal(100)
        completion_pct = _round_half_up(pct, 2)

    is_complete = (n_sent == n_total) and (n_total > 0)

    # Return completion_pct as a JSON number (float). Decimal -> str -> float
    # preserves the canonical "two decimal places" rendering for tests.
    return {
        "n_total": n_total,
        "n_sent": n_sent,
        "n_drafted": n_drafted,
        "n_pending": n_pending,
        "completion_pct": float(completion_pct),
        "is_complete": is_complete,
    }
