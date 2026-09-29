"""Calculation rules (scaffold 1.3 / PRD 3.2-3.9)."""
from datetime import timedelta

import config
import db
from db import ordered
from util import round_half_up, whole_days, whole_hours


# ---------------------------------------------------------------------------
# season_sink_faucet_ratio_bp
# ---------------------------------------------------------------------------
def ratio_bp(sinks, faucets):
    if faucets == 0 and sinks == 0:
        return 10000
    if faucets == 0:
        return config.RATIO_CEILING_BP
    return min(config.RATIO_CEILING_BP, round_half_up(sinks * 10000, faucets))


def health_band(value_bp):
    if value_bp >= config.ECONOMY_HEALTHY_FLOOR_BP:
        return "HEALTHY"
    if value_bp >= config.ECONOMY_WATCH_FLOOR_BP:
        return "WATCH"
    return "INFLATED"


def season_ledger_rows(season_id):
    return [e for e in db.db.ledger.values() if e["season_id"] == season_id]


def lifetime_totals(season_id):
    """GROSS semantics: every row of the season, reversals included."""
    faucet = 0
    sink = 0
    for entry in season_ledger_rows(season_id):
        if entry["direction"] == "FAUCET":
            faucet += entry["amount_minor"]
        else:
            sink += entry["amount_minor"]
    return faucet, sink


def epoch_totals(season_id, window_start, window_end):
    """NET semantics: window rows only, with every compensating pair removed."""
    rows = season_ledger_rows(season_id)
    excluded = set()
    for entry in rows:
        if entry.get("reversal_of_entry_id"):
            excluded.add(entry["id"])
            excluded.add(entry["reversal_of_entry_id"])
    faucet = 0
    sink = 0
    for entry in rows:
        if entry["id"] in excluded:
            continue
        occurred = entry["occurred_at"]
        if occurred < window_start or occurred >= window_end:
            continue
        if entry["direction"] == "FAUCET":
            faucet += entry["amount_minor"]
        else:
            sink += entry["amount_minor"]
    return faucet, sink


def refresh_lifetime_ratio(season):
    season["lifetime_ratio_bp"] = ratio_bp(season["gross_sink_minor"], season["gross_faucet_minor"])


# ---------------------------------------------------------------------------
# offer_fairness_index_bp
# ---------------------------------------------------------------------------
def offer_fairness_index_bp(offer):
    declared = sum(line["declared_value_minor"] for line in offer["line_items"])
    value_ratio_bp = round_half_up(declared * 10000, offer["list_price_minor"])
    window_hours = whole_hours(offer["window_end"] - offer["window_start"])
    if window_hours >= 72:
        scarcity_penalty_bp = 0
    elif window_hours >= 24:
        scarcity_penalty_bp = 500
    else:
        scarcity_penalty_bp = 1200
    minor_safety_penalty_bp = 800 if (offer["offer_type"] == "LOOT_BOX" and offer["minor_purchasable"]) else 0
    personalization_penalty_bp = min(600, round_half_up(offer["personalization_discount_bp"], 5))
    raw = value_ratio_bp - scarcity_penalty_bp - minor_safety_penalty_bp - personalization_penalty_bp
    return max(0, min(config.FAIRNESS_CEILING_BP, raw))


# ---------------------------------------------------------------------------
# personalized_offer_quote_minor
# ---------------------------------------------------------------------------
def personalized_quote(offer, player):
    region_bp = config.REGION_PRICE_MULTIPLIER_BP[player["region_code"]]
    tier_bp = config.TIER_DISCOUNT_BP[offer["price_tier"]]
    if player["retention_band"] == "AT_RISK":
        pers_bp = min(config.PERSONALIZATION_CAP_BP, offer["personalization_discount_bp"])
    else:
        pers_bp = 0
    quote_minor = 0
    breakdown = []
    for line in sorted(offer["line_items"], key=lambda l: l["sku"]):
        gross_line = round_half_up(line["base_price_minor"] * region_bp, 10000)
        net_line = round_half_up(gross_line * (10000 - tier_bp - pers_bp), 10000)
        quote_minor += net_line
        breakdown.append(
            {
                "sku": line["sku"],
                "base_price_minor": line["base_price_minor"],
                "gross_line_minor": gross_line,
                "net_line_minor": net_line,
            }
        )
    return {
        "region_multiplier_bp": region_bp,
        "tier_discount_bp": tier_bp,
        "applied_personalization_bp": pers_bp,
        "retention_band": player["retention_band"],
        "quote_minor": quote_minor,
        "line_breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# season_cadence_debt_days
# ---------------------------------------------------------------------------
def recompute_cadence(season):
    clock = db.now()
    debt = 0
    episodes = [e for e in db.db.episodes.values() if e["season_id"] == season["id"]]
    for episode in sorted(episodes, key=lambda e: e["sequence_no"]):
        status = episode["status"]
        if status in ("LIVE", "CONCLUDED"):
            if episode["actual_release_at"] is not None:
                debt += max(0, whole_days(episode["actual_release_at"] - episode["planned_release_at"]))
        elif status == "SCHEDULED" and episode["planned_release_at"] < clock:
            debt += whole_days(clock - episode["planned_release_at"])
        debt += config.ROLLBACK_DEBT_DAYS * episode["rollback_count"]
    season["cadence_debt_days"] = debt
    season["content_posture"] = "BEHIND" if debt > config.CADENCE_DEBT_LIMIT_DAYS else "ON_TRACK"
    return debt


# ---------------------------------------------------------------------------
# player_pacing_bp
# ---------------------------------------------------------------------------
def retention_band(pacing_bp):
    if pacing_bp >= config.RETENTION_HEALTHY_FLOOR_BP:
        return "HEALTHY"
    if pacing_bp >= config.RETENTION_AT_RISK_FLOOR_BP:
        return "AT_RISK"
    return "CHURN_RISK"


def pacing(player, season, variant):
    clock = db.now()
    if season is None:
        return {
            "elapsed_days": 0,
            "season_total_days": 0,
            "expected_to_date_xp": 0,
            "eligible_scheduled_xp": 0,
            "season_xp_total": player["season_xp_total"],
            "pacing_bp": 10000,
            "retention_band": retention_band(10000),
        }
    season_total_days = whole_days(season["ends_at"] - season["starts_at"])
    if season_total_days <= 0:
        elapsed_days = 0
        expected_to_date_xp = 0
    else:
        elapsed_days = min(season_total_days, max(0, whole_days(clock - season["starts_at"])))
        expected_to_date_xp = round_half_up(season["target_xp_total"] * elapsed_days, season_total_days)

    eligible_scheduled_xp = 0
    for episode in db.db.episodes.values():
        if (
            episode["season_id"] == season["id"]
            and episode["status"] == "SCHEDULED"
            and episode["planned_release_at"] >= clock
        ):
            eligible_scheduled_xp += episode["xp_grant"]

    if variant == "PROJECTED":
        denominator = season["target_xp_total"]
        if denominator <= 0:
            value_bp = 10000
        else:
            value_bp = min(
                config.PACING_CEILING_BP,
                round_half_up((player["season_xp_total"] + eligible_scheduled_xp) * 10000, denominator),
            )
    else:
        if expected_to_date_xp == 0:
            value_bp = 10000
        else:
            value_bp = min(
                config.PACING_CEILING_BP,
                round_half_up(player["season_xp_total"] * 10000, expected_to_date_xp),
            )
    return {
        "elapsed_days": elapsed_days,
        "season_total_days": season_total_days,
        "expected_to_date_xp": expected_to_date_xp,
        "eligible_scheduled_xp": eligible_scheduled_xp,
        "season_xp_total": player["season_xp_total"],
        "pacing_bp": value_bp,
        "retention_band": retention_band(value_bp),
    }


def refresh_realized_pacing(player):
    season = db.db.seasons.get(player["active_season_id"])
    result = pacing(player, season, "REALIZED")
    player["pacing_bp_realized"] = result["pacing_bp"]
    player["retention_band"] = result["retention_band"]
    return result


# ---------------------------------------------------------------------------
# player_rolling_spend_minor
# ---------------------------------------------------------------------------
def rolling_spend_minor(player):
    clock = db.now()
    window_start = clock - timedelta(days=config.ROLLING_SPEND_WINDOW_DAYS)
    settled = 0
    for purchase in db.db.purchases.values():
        if purchase["player_id"] != player["id"]:
            continue
        if purchase["status"] not in ("SETTLED", "REFUNDED"):
            continue
        settled_at = purchase["settled_at"]
        if settled_at is None or settled_at < window_start or settled_at > clock:
            continue
        settled += purchase["price_paid_minor"]
    refunded = 0
    for request in db.db.refunds.values():
        if request["status"] != "EXECUTED":
            continue
        purchase = db.db.purchases.get(request["purchase_id"])
        if purchase is None or purchase["player_id"] != player["id"]:
            continue
        executed_at = request["executed_at"]
        if executed_at is None or executed_at < window_start or executed_at > clock:
            continue
        refunded += request["refund_amount_minor"]
    return max(0, settled - refunded)


# ---------------------------------------------------------------------------
# refund_settlement_minor
# ---------------------------------------------------------------------------
def refund_settlement(purchase, player):
    consumed_ratio_bp = min(
        10000,
        round_half_up(purchase["granted_consumed_minor"] * 10000, max(1, purchase["granted_total_minor"])),
    )
    refund_base_minor = round_half_up(purchase["price_paid_minor"] * (10000 - consumed_ratio_bp), 10000)
    if refund_base_minor < config.RESTOCK_TIER1_CEILING_MINOR:
        fee_tier_bp = 0
    elif refund_base_minor < config.RESTOCK_TIER2_CEILING_MINOR:
        fee_tier_bp = 500
    else:
        fee_tier_bp = 1000
    restock_fee_minor = round_half_up(refund_base_minor * fee_tier_bp, 10000)
    refund_amount_minor = max(0, refund_base_minor - restock_fee_minor)
    has_soft_coin = any(
        account["player_id"] == player["id"] and account["currency_code"] == "SOFT_COIN"
        for account in db.db.accounts.values()
    )
    if has_soft_coin and player["spend_state"] != "LOCKED":
        goodwill_credit_minor = round_half_up(restock_fee_minor * config.GOODWILL_SHARE_BP, 10000)
    else:
        goodwill_credit_minor = 0
    return {
        "consumed_ratio_bp": consumed_ratio_bp,
        "refund_base_minor": refund_base_minor,
        "restock_fee_minor": restock_fee_minor,
        "refund_amount_minor": refund_amount_minor,
        "goodwill_credit_minor": goodwill_credit_minor,
    }


# ---------------------------------------------------------------------------
# cluster_ccu_overlap_load
# ---------------------------------------------------------------------------
def cluster_overlap_load(cluster, candidate):
    buffer_seconds = cluster["maintenance_buffer_minutes"] * 60
    buffer = timedelta(seconds=buffer_seconds)
    candidate_end = candidate["window_end"] + buffer
    load = candidate["forecast_ccu"]
    for event in db.db.live_events.values():
        if event["capacity_cluster_id"] != candidate["capacity_cluster_id"]:
            continue
        if event["id"] == candidate["id"]:
            continue
        if event["status"] not in ("APPROVED", "RUNNING"):
            continue
        neighbour_end = event["window_end"] + buffer
        if candidate["window_start"] < neighbour_end and event["window_start"] < candidate_end:
            load += event["forecast_ccu"]
    return load


# ---------------------------------------------------------------------------
# offer_sku_window_conflict
# ---------------------------------------------------------------------------
def offer_sku_window_conflict(candidate):
    cooldown = timedelta(hours=config.SKU_COOLDOWN_HOURS)
    candidate_skus = set(line["sku"] for line in candidate["line_items"])
    for other in db.db.offers.values():
        if other["id"] == candidate["id"]:
            continue
        if other["season_id"] != candidate["season_id"]:
            continue
        if other["availability_status"] not in ("LIVE", "SUSPENDED"):
            continue
        if not candidate_skus.intersection(line["sku"] for line in other["line_items"]):
            continue
        if (
            candidate["window_start"] <= other["window_end"] + cooldown
            and other["window_start"] <= candidate["window_end"] + cooldown
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# episode_grant_recipient_set
# ---------------------------------------------------------------------------
def episode_grant_recipients(episode):
    candidates = []
    for account in db.db.accounts.values():
        if account["currency_code"] != "SOFT_COIN" or account["status"] != "ACTIVE":
            continue
        player = db.db.players.get(account["player_id"])
        if player is None:
            continue
        if player["active_season_id"] != episode["season_id"]:
            continue
        if player["spend_state"] == "LOCKED":
            continue
        candidates.append((account, player))
    candidates.sort(key=lambda pair: (pair[0]["created_at"], pair[1]["handle"]))
    return [pair[0] for pair in candidates]


# ---------------------------------------------------------------------------
# disclosure figures
# ---------------------------------------------------------------------------
def disclosure_totals(entries):
    total_probability_bp = sum(entry["probability_bp"] for entry in entries)
    weighted = sum(entry["probability_bp"] * entry["item_value_minor"] for entry in entries)
    expected_value_minor = round_half_up(weighted, 10000)
    return total_probability_bp, expected_value_minor
