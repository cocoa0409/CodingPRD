"""Domain services: entity helpers, balance derivation, RG re-evaluation,
ledger posting, market liability, and the settlement/void/self-exclusion
cascades.
"""

from datetime import timedelta

from db import db, clock, iso_now, new_id, next_seq, format_iso, parse_iso, parse_date
from errors import err
import calc


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def base_record(versioned=True):
    """Create the common-field skeleton (PRD §2.4).

    versioned=True  -> id, created_at, updated_at, version (starts 1).
    versioned=False -> id, created_at only (append-only event records).
    """
    ts = iso_now()
    rec = {"id": new_id(), "created_at": ts, "_seq": next_seq()}
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at + version on a versioned record (PRD §2.4)."""
    rec["updated_at"] = iso_now()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Ledger + balance derivation (PRD §2.7)
# ---------------------------------------------------------------------------
def post_ledger(account_id, entry_type, bucket, amount_cents, ref_type="NONE", ref_id=None):
    rec = base_record(versioned=False)
    rec.update({
        "account_id": account_id,
        "entry_type": entry_type,
        "bucket": bucket,
        "amount_cents": amount_cents,
        "ref_type": ref_type,
        "ref_id": ref_id,
    })
    db.ledger_entries[rec["id"]] = rec
    return rec


def account_ledger(account_id):
    return [e for e in db.ledger_entries.values() if e["account_id"] == account_id]


def cash_balance(account_id):
    return sum(e["amount_cents"] for e in account_ledger(account_id) if e["bucket"] == "CASH")


def bonus_balance(account_id):
    return sum(e["amount_cents"] for e in account_ledger(account_id) if e["bucket"] == "BONUS")


def lifetime_deposits(account_id):
    return sum(
        e["amount_cents"]
        for e in account_ledger(account_id)
        if e["entry_type"] == "DEPOSIT" and e["bucket"] == "CASH"
    )


# ---------------------------------------------------------------------------
# Responsible-gaming re-evaluation (PRD §3.2)
# ---------------------------------------------------------------------------
def reeval_cooling_off(acct):
    """Retire a lapsed cooling-off: if rg_status COOLING_OFF and clock has reached
    cooling_off_until, move back to ACTIVE and clear cooling_off_until.

    This is a state-correcting read side effect; it does NOT bump version.
    """
    if acct["rg_status"] == "COOLING_OFF" and acct.get("cooling_off_until"):
        until = parse_iso(acct["cooling_off_until"])
        if clock.get() >= until:
            acct["rg_status"] = "ACTIVE"
            acct["cooling_off_until"] = None


# ---------------------------------------------------------------------------
# Serializers (apply derived/computed fields per PRD)
# ---------------------------------------------------------------------------
def serialize_account(acct):
    reeval_cooling_off(acct)
    return {
        "id": acct["id"],
        "email": acct["email"],
        "full_name": acct["full_name"],
        "date_of_birth": acct["date_of_birth"],
        "residence_state": acct["residence_state"],
        "kyc_status": acct["kyc_status"],
        "rg_status": acct["rg_status"],
        "cash_balance_cents": cash_balance(acct["id"]),
        "bonus_balance_cents": bonus_balance(acct["id"]),
        "lifetime_deposits_cents": lifetime_deposits(acct["id"]),
        "cooling_off_until": acct.get("cooling_off_until"),
        "kyc_decided_by": acct.get("kyc_decided_by"),
        "created_at": acct["created_at"],
        "updated_at": acct["updated_at"],
        "version": acct["version"],
    }


def serialize_rg_control(c):
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "control_type": c["control_type"],
        "period": c["period"],
        "limit_cents": c["limit_cents"],
        "duration_days": c["duration_days"],
        "status": c["status"],
        "set_at": c["set_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_geo_check(g):
    return {
        "id": g["id"],
        "account_id": g["account_id"],
        "detected_state": g["detected_state"],
        "accuracy_meters": g["accuracy_meters"],
        "is_vpn_suspected": g["is_vpn_suspected"],
        "eligible": g["eligible"],
        "expires_at": g["expires_at"],
        "created_at": g["created_at"],
    }


def serialize_event(e):
    return {
        "id": e["id"],
        "sport": e["sport"],
        "home_team": e["home_team"],
        "away_team": e["away_team"],
        "starts_at": e["starts_at"],
        "status": e["status"],
        "home_score": e["home_score"],
        "away_score": e["away_score"],
        "result_posted_by": e["result_posted_by"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_market(m, recompute=True):
    if recompute:
        recompute_market_liability(m)
    return {
        "id": m["id"],
        "event_id": m["event_id"],
        "market_type": m["market_type"],
        "line": m["line"],
        "liability_cap_cents": m["liability_cap_cents"],
        "current_liability_cents": m["current_liability_cents"],
        "status": m["status"],
        "set_by": m["set_by"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_selection(s):
    return {
        "id": s["id"],
        "market_id": s["market_id"],
        "name": s["name"],
        "american_odds": s["american_odds"],
        "decimal_odds": calc.decimal_to_float(s["decimal_odds"]),
        "result": s["result"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_bet(b):
    return {
        "id": b["id"],
        "account_id": b["account_id"],
        "bet_type": b["bet_type"],
        "stake_cents": b["stake_cents"],
        "stake_bucket": b["stake_bucket"],
        "combined_decimal_odds": calc.decimal_to_float(b["combined_decimal_odds"]),
        "potential_payout_cents": b["potential_payout_cents"],
        "actual_payout_cents": b["actual_payout_cents"],
        "bonus_grant_id": b["bonus_grant_id"],
        "status": b["status"],
        "settled_at": b["settled_at"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_bet_leg(l):
    return {
        "id": l["id"],
        "bet_id": l["bet_id"],
        "selection_id": l["selection_id"],
        "odds_at_placement": l["odds_at_placement"],
        "decimal_odds_at_placement": calc.decimal_to_float(l["decimal_odds_at_placement"]),
        "leg_result": l["leg_result"],
        "created_at": l["created_at"],
    }


def serialize_promotion(p):
    return {
        "id": p["id"],
        "code": p["code"],
        "bonus_cents": p["bonus_cents"],
        "wagering_multiplier": p["wagering_multiplier"],
        "min_odds_american": p["min_odds_american"],
        "max_claims": p["max_claims"],
        "claims_used": claims_used(p["id"]),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_bonus_grant(g, recompute=False):
    return {
        "id": g["id"],
        "account_id": g["account_id"],
        "promotion_id": g["promotion_id"],
        "bonus_cents": g["bonus_cents"],
        "wagering_target_cents": g["wagering_target_cents"],
        "wagering_progress_cents": g["wagering_progress_cents"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_ledger_entry(e):
    return {
        "id": e["id"],
        "account_id": e["account_id"],
        "entry_type": e["entry_type"],
        "bucket": e["bucket"],
        "amount_cents": e["amount_cents"],
        "ref_type": e["ref_type"],
        "ref_id": e["ref_id"],
        "created_at": e["created_at"],
    }


# ---------------------------------------------------------------------------
# Promotion claims_used (PRD §3.11: count of grants referencing it)
# ---------------------------------------------------------------------------
def claims_used(promotion_id):
    return sum(1 for g in db.bonus_grants.values() if g["promotion_id"] == promotion_id)


# ---------------------------------------------------------------------------
# Bet/leg/market relationship helpers
# ---------------------------------------------------------------------------
def legs_of_bet(bet_id):
    legs = [l for l in db.bet_legs.values() if l["bet_id"] == bet_id]
    legs.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return legs


def markets_touched_by_bet(bet):
    """Distinct market ids touched by a bet's legs."""
    market_ids = set()
    for leg in legs_of_bet(bet["id"]):
        sel = db.selections.get(leg["selection_id"])
        if sel:
            market_ids.add(sel["market_id"])
    return market_ids


def recompute_market_liability(market):
    """current_liability_cents = sum over PLACED bets touching this market of
    (potential_payout_cents - stake_cents). Worst-case, no offsetting (PRD §3.8).
    """
    total = 0
    for bet in db.bets.values():
        if bet["status"] != "PLACED":
            continue
        if market["id"] in markets_touched_by_bet(bet):
            total += bet["potential_payout_cents"] - bet["stake_cents"]
    market["current_liability_cents"] = total
    return total


# ---------------------------------------------------------------------------
# Selection grading by market type (PRD §3.10)
# ---------------------------------------------------------------------------
def grade_selection(market, selection, home_score, away_score):
    """Return WON / LOST / PUSH for a selection given official scores.

    MONEYLINE: HOME wins if home>away; AWAY wins if away>home; tie -> PUSH.
    SPREAD (line applies to HOME): home_score + line vs away_score.
        HOME: (home+line) > away -> WON, < -> LOST, == -> PUSH.
        AWAY: mirror.
    TOTAL: total = home+away vs line.
        OVER: total > line -> WON, < -> LOST, == -> PUSH.
        UNDER: mirror.
    """
    mtype = market["market_type"]
    name = selection["name"].upper()

    if mtype == "MONEYLINE":
        if home_score == away_score:
            return "PUSH"
        home_wins = home_score > away_score
        if name == "HOME":
            return "WON" if home_wins else "LOST"
        if name == "AWAY":
            return "WON" if not home_wins else "LOST"
        # Unknown selection name on a moneyline: default by margin sign unknown.
        return "PUSH"

    line = market["line"] if market["line"] is not None else 0

    if mtype == "SPREAD":
        adjusted = home_score + line  # line is the home handicap
        if adjusted == away_score:
            return "PUSH"
        home_covers = adjusted > away_score
        if name == "HOME":
            return "WON" if home_covers else "LOST"
        if name == "AWAY":
            return "WON" if not home_covers else "LOST"
        return "PUSH"

    if mtype == "TOTAL":
        total = home_score + away_score
        if total == line:
            return "PUSH"
        over = total > line
        if name == "OVER":
            return "WON" if over else "LOST"
        if name == "UNDER":
            return "WON" if not over else "LOST"
        return "PUSH"

    return "PUSH"


# ---------------------------------------------------------------------------
# Bonus wagering-requirement contribution (PRD §3.11)
# ---------------------------------------------------------------------------
def advance_wagering_requirement(bet):
    """Apply a settled bet's qualifying stake to its bonus grant, then complete
    the grant if it reaches target (converting remaining bonus to cash).
    """
    grant_id = bet.get("bonus_grant_id")
    if not grant_id:
        return
    grant = db.bonus_grants.get(grant_id)
    if not grant or grant["status"] != "ACTIVE":
        return
    promo = db.promotions.get(grant["promotion_id"])
    if not promo:
        return

    status = bet["status"]
    # Cash-outs, voids, and pushes never contribute (PRD §3.11).
    if status in ("CASHED_OUT", "VOIDED", "PUSHED"):
        contribution = 0
    elif status in ("WON", "LOST"):
        min_dec = calc.american_to_decimal(promo["min_odds_american"])
        if bet["combined_decimal_odds"] >= min_dec:
            contribution = bet["stake_cents"]
        else:
            contribution = 0
    else:
        contribution = 0

    if contribution:
        new_progress = min(
            grant["wagering_progress_cents"] + contribution,
            grant["wagering_target_cents"],
        )
        grant["wagering_progress_cents"] = new_progress
        touch(grant)

    if grant["wagering_progress_cents"] >= grant["wagering_target_cents"]:
        complete_bonus_grant(grant)


def complete_bonus_grant(grant):
    """ACTIVE -> COMPLETED: convert remaining bonus balance to cash via a matched
    ledger pair (BONUS debit + equal CASH credit) (PRD §3.11).
    """
    if grant["status"] != "ACTIVE":
        return
    account_id = grant["account_id"]
    remaining = bonus_balance(account_id)
    if remaining > 0:
        post_ledger(account_id, "BONUS_GRANT", "BONUS", -remaining,
                    ref_type="BONUS_GRANT", ref_id=None)
        post_ledger(account_id, "PAYOUT", "CASH", remaining,
                    ref_type="BONUS_GRANT", ref_id=None)
    grant["status"] = "COMPLETED"
    touch(grant)


# ---------------------------------------------------------------------------
# Bet grading from its legs (PRD §3.10)
# ---------------------------------------------------------------------------
def grade_bet_from_legs(bet):
    """Grade a PLACED bet once all its legs are terminal, posting payout/refund
    ledger entries and advancing any bonus WR. Idempotent guard via PLACED check.
    """
    if bet["status"] != "PLACED":
        return
    legs = legs_of_bet(bet["id"])
    if not legs:
        return
    if any(l["leg_result"] == "PENDING" for l in legs):
        return  # not all terminal yet

    effective, any_won, any_lost = calc.settlement_effective_odds(legs)
    all_push_void = all(l["leg_result"] in ("PUSH", "VOID") for l in legs)

    if any_lost:
        bet["status"] = "LOST"
        bet["actual_payout_cents"] = 0
        # no payout entry
    elif all_push_void:
        bet["status"] = "PUSHED"
        bet["actual_payout_cents"] = bet["stake_cents"]
        post_ledger(bet["account_id"], "VOID_REFUND", bet["stake_bucket"],
                    bet["stake_cents"], ref_type="BET", ref_id=bet["id"])
    else:
        # WON (with possible pushes dropped)
        payout = calc.floor_cents(bet["stake_cents"], effective)
        bet["status"] = "WON"
        bet["actual_payout_cents"] = payout
        post_ledger(bet["account_id"], "PAYOUT", "CASH", payout,
                    ref_type="BET", ref_id=bet["id"])

    bet["settled_at"] = iso_now()
    touch(bet)

    # Cascade step 4: advance bonus WR for the settled qualifying bet.
    advance_wagering_requirement(bet)


# ---------------------------------------------------------------------------
# Void cascade (event void / self-exclusion)
# ---------------------------------------------------------------------------
def void_bet(bet):
    """Move a PLACED bet to VOIDED, refunding its stake to the funding bucket."""
    if bet["status"] != "PLACED":
        return
    bet["status"] = "VOIDED"
    bet["actual_payout_cents"] = bet["stake_cents"]
    bet["settled_at"] = iso_now()
    post_ledger(bet["account_id"], "VOID_REFUND", bet["stake_bucket"],
                bet["stake_cents"], ref_type="BET", ref_id=bet["id"])
    touch(bet)


def bets_touching_event(event_id):
    result = []
    for bet in db.bets.values():
        for leg in legs_of_bet(bet["id"]):
            sel = db.selections.get(leg["selection_id"])
            if not sel:
                continue
            mkt = db.markets.get(sel["market_id"])
            if mkt and mkt["event_id"] == event_id:
                result.append(bet)
                break
    return result
