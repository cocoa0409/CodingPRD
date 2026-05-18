"""Calculation rules (scaffold §1.3, PRD §3.4 / §3.8)."""
from __future__ import annotations

from decimal import Decimal

from config import (
    AGENT_ROLE_BUYER,
    AGENT_ROLE_DUAL,
    AGENT_ROLE_LISTING,
    MATCH_CUTOFF,
    W_BB,
    W_FEAT,
    W_LOC,
    W_PRICE,
)
from utils import round_half_up_dec, round_half_up_int, to_decimal


# ─────────────────────────────────────────────────────────────────────────────
# Buyer / listing match scoring  (scaffold calculations.buyer_match_score)
# ─────────────────────────────────────────────────────────────────────────────


def _fit_price(listing: dict, buyer: dict) -> Decimal:
    lp = to_decimal(listing["list_price_cents"])
    lo = to_decimal(buyer["min_price_cents"])
    hi = to_decimal(buyer["max_price_cents"])
    if lo <= lp <= hi:
        return Decimal("100")
    if lp > hi:
        over = lp - hi
        band = hi // 10
        if band < 1:
            band = Decimal(1)
        else:
            band = Decimal(band)
        decayed = Decimal("100") - (over / band) * Decimal("100")
        return decayed if decayed > 0 else Decimal("0")
    # lp < lo
    under = lo - lp
    band = lo // 10
    if band < 1:
        band = Decimal(1)
    else:
        band = Decimal(band)
    decayed = Decimal("100") - (under / band) * Decimal("100")
    return decayed if decayed > 0 else Decimal("0")


def _fit_location(listing: dict, buyer: dict) -> Decimal:
    if listing["zip_code"] in (buyer.get("desired_zips") or []):
        return Decimal("100")
    return Decimal("0")


def _fit_bed_bath(listing: dict, buyer: dict) -> Decimal:
    bed_ok = to_decimal(listing["bedrooms"]) >= to_decimal(buyer["min_bedrooms"])
    bath_ok = to_decimal(listing["bathrooms"]) >= to_decimal(buyer["min_bathrooms"])
    if bed_ok and bath_ok:
        return Decimal("100")
    if bed_ok or bath_ok:
        return Decimal("50")
    return Decimal("0")


def _fit_features(listing: dict, buyer: dict) -> Decimal:
    desired = set(buyer.get("desired_features") or [])
    if not desired:
        return Decimal("100")
    overlap = desired.intersection(set(listing.get("features") or []))
    raw = (Decimal(len(overlap)) / Decimal(len(desired))) * Decimal("100")
    # Local rounding to 4 dp before entering weighted sum (PRD §3.4 exception).
    return round_half_up_dec(raw, 4)


def buyer_match_score(listing: dict, buyer: dict) -> Decimal:
    """Return the 0..100 buyer-listing fit score, 2dp round-half-up on the final sum."""
    raw = (
        Decimal(W_PRICE) * _fit_price(listing, buyer)
        + Decimal(W_LOC) * _fit_location(listing, buyer)
        + Decimal(W_BB) * _fit_bed_bath(listing, buyer)
        + Decimal(W_FEAT) * _fit_features(listing, buyer)
    )
    return round_half_up_dec(raw, 2)


def rank_candidates(pairs):
    """Pairs: iterable of (candidate_dict, score Decimal).

    Returns the eligible candidates sorted by (score DESC, created_at ASC, id ASC).
    Eligibility: score >= MATCH_CUTOFF.
    """
    cutoff = Decimal(MATCH_CUTOFF)
    survivors = [(c, s) for c, s in pairs if s >= cutoff]
    survivors.sort(key=lambda x: (-x[1], x[0]["created_at"], x[0]["id"]))
    return survivors


# ─────────────────────────────────────────────────────────────────────────────
# Commission split (scaffold calculations.co_op_commission_split, PRD §3.8)
# ─────────────────────────────────────────────────────────────────────────────


def compute_commission_split(
    sale_price_cents: int,
    total_commission_pct,
    co_op_pct,
    listing_agent_split,
    buyer_agent_split,
) -> dict:
    """Return commission-split component cents per the pinned formula."""
    sale = to_decimal(sale_price_cents)
    total_pct = to_decimal(total_commission_pct)
    co_op = to_decimal(co_op_pct)
    la_split = to_decimal(listing_agent_split)
    ba_split = to_decimal(buyer_agent_split)

    gross_commission_cents = round_half_up_int(sale * total_pct)
    buyer_side_cents = round_half_up_int(sale * co_op)
    listing_side_cents = gross_commission_cents - buyer_side_cents

    listing_agent_cents = round_half_up_int(Decimal(listing_side_cents) * la_split)
    listing_brokerage_cents = listing_side_cents - listing_agent_cents

    buyer_agent_cents = round_half_up_int(Decimal(buyer_side_cents) * ba_split)
    buyer_brokerage_cents = buyer_side_cents - buyer_agent_cents

    return {
        "gross_commission_cents": gross_commission_cents,
        "buyer_side_cents": buyer_side_cents,
        "listing_side_cents": listing_side_cents,
        "listing_agent_cents": listing_agent_cents,
        "listing_brokerage_cents": listing_brokerage_cents,
        "buyer_agent_cents": buyer_agent_cents,
        "buyer_brokerage_cents": buyer_brokerage_cents,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Offer net to seller (scaffold calculations.offer_net_to_seller, PRD §3.8)
# ─────────────────────────────────────────────────────────────────────────────


def provisional_net_to_seller(offer: dict, listing: dict) -> int:
    price = to_decimal(offer["offer_price_cents"])
    concessions = to_decimal(offer.get("estimated_seller_concessions_cents") or 0)
    co_op = to_decimal(listing["co_op_pct"])
    total = to_decimal(listing["total_commission_pct"])
    buyer_side = round_half_up_int(price * co_op)
    listing_side = round_half_up_int(price * (total - co_op))
    return int(price) - int(concessions) - buyer_side - listing_side
