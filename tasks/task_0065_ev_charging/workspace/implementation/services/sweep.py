"""Reservation expiry sweep."""

import db
from clock import now, parse_iso
from services import settlement


BASE_PENALTY_CENTS = 500
STRIKE_MULTIPLIER = 2
MAX_PENALTY_CENTS = 5000


def compute_no_show_penalty(prior_strikes: int) -> int:
    raw = BASE_PENALTY_CENTS * (STRIKE_MULTIPLIER ** prior_strikes)
    return min(raw, MAX_PENALTY_CENTS)


def run_sweep() -> list[str]:
    """Expire any HELD reservation whose hold_expires_at <= clock.now().

    Returns a list of expired reservation ids in deterministic order.
    """
    current = now()
    expired_ids: list[str] = []
    # Iterate by insertion order for determinism.
    reservations = sorted(db.reservations.values(), key=lambda r: r.get("_seq", 0))
    for res in reservations:
        if res["status"] != "HELD":
            continue
        try:
            hold_at = parse_iso(res["hold_expires_at"])
        except Exception:
            continue
        if hold_at > current:
            continue

        member = db.members.get(res["member_id"])
        prior_strikes = int(member["no_show_strikes"]) if member else 0
        penalty = compute_no_show_penalty(prior_strikes)

        res["status"] = "EXPIRED"
        res["no_show_penalty_cents"] = penalty
        db.bump(res)

        if member is not None:
            member["no_show_strikes"] = prior_strikes + 1
            member["wallet_balance_cents"] = max(
                0, int(member["wallet_balance_cents"]) - penalty
            )
            db.bump(member)

        # Ledger entry for the no-show penalty.
        settlement.write_ledger_entry(
            session_id=res["id"],  # use reservation id as source reference
            operator_id="PLATFORM",
            counterparty_kind="PLATFORM_SERVICE_FEE",
            amount_cents=penalty,
            reason="NO_SHOW_PENALTY",
            tax_cents=0,
        )

        expired_ids.append(res["id"])

    return expired_ids
