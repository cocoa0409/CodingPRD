from services.calc import (
    WITHDRAWAL_WEIGHT,
    DISPUTE_LOSS_WEIGHT,
    ACUTE_PENALTY_SHILL,
    ACUTE_PENALTY_TAKEOVER,
    ACUTE_PENALTY_DEFAULT,
    MAX_SCORE,
    RISK_RESTRICT_THRESHOLD,
    RISK_SUSPEND_THRESHOLD,
    round_half_up_one_dp,
)
import db


def recompute_risk(bidder: dict) -> None:
    chronic = bidder.get("withdrawal_count", 0) * WITHDRAWAL_WEIGHT + bidder.get("dispute_loss_count", 0) * DISPUTE_LOSS_WEIGHT
    chronic = min(MAX_SCORE, chronic)

    acute = 0.0
    if bidder.get("shill_pattern_detected"):
        acute += ACUTE_PENALTY_SHILL
    if bidder.get("account_takeover_alert"):
        acute += ACUTE_PENALTY_TAKEOVER
    acute += ACUTE_PENALTY_DEFAULT * bidder.get("default_count_since_reinstate", 0)

    total = min(MAX_SCORE, chronic + acute)

    bidder["chronic_score"] = round_half_up_one_dp(chronic)
    bidder["acute_score"] = round_half_up_one_dp(acute)
    bidder["risk_score"] = round_half_up_one_dp(total)


def maybe_threshold_transition(bidder: dict) -> None:
    """If risk crosses thresholds upward, transition status. Cascades on SUSPEND."""
    score = bidder.get("risk_score", 0.0)
    if bidder["status"] == "ACTIVE":
        if score >= RISK_SUSPEND_THRESHOLD:
            _suspend(bidder)
        elif score >= RISK_RESTRICT_THRESHOLD:
            bidder["status"] = "RESTRICTED"
            _bump(bidder)
    elif bidder["status"] == "RESTRICTED":
        if score >= RISK_SUSPEND_THRESHOLD:
            _suspend(bidder)


def _bump(bidder: dict) -> None:
    bidder["updated_at"] = db.now()
    bidder["version"] = bidder.get("version", 1) + 1


def _suspend(bidder: dict) -> None:
    from services.lot_service import bidder_suspend_cascade
    bidder["status"] = "SUSPENDED"
    bidder_suspend_cascade(bidder)
    _bump(bidder)


def update_withdrawal_count(bidder_id: str) -> None:
    b = db.bidders.get(bidder_id)
    if not b:
        return
    cnt = sum(1 for bid in db.bids.values() if bid["bidder_id"] == bidder_id and bid["status"] == "WITHDRAWN_BY_RISK")
    b["withdrawal_count"] = cnt


def update_dispute_loss_count(bidder_id: str) -> None:
    b = db.bidders.get(bidder_id)
    if not b:
        return
    cnt = sum(
        1 for d in db.disputes.values()
        if d.get("filed_by") == "BIDDER"
        and d.get("filer_user_id") == bidder_id
        and d.get("status") == "RESOLVED_DENIED"
    )
    b["dispute_loss_count"] = cnt
