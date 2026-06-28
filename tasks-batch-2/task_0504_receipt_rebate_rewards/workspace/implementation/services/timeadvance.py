"""Logical-clock advancement (PRD §2.10).

Setting the clock fires every due time-based transition:
  - PENDING claims whose matures_at has been reached -> AVAILABLE
  - AVAILABLE claims whose expires_at has been reached -> EXPIRED
  - INVITED referrals past their expiry deadline -> EXPIRED
  - Offers past expires_at -> EXPIRED
Each maturation recomputes the affected member's bonus streak.
"""
from datetime import timedelta

from clock import parse_iso
from constants import REFERRAL_EXPIRY_DAYS
from db import touch
from services.claims import mature_claim, expire_claim


def fire_due_transitions(store):
    now = store.clock.get()

    # Offers: ACTIVE -> EXPIRED past expires_at.
    for o in store.offers.values():
        if o["status"] == "ACTIVE":
            exp = parse_iso(o["expires_at"])
            if exp is not None and now >= exp:
                o["status"] = "EXPIRED"
                touch(store, o)

    # Reward claims: process maturation first (PENDING -> AVAILABLE), oldest first,
    # then expiry (AVAILABLE -> EXPIRED). A claim can mature then expire in one jump
    # if the clock leaps far enough.
    claims_by_age = sorted(
        store.reward_claims.values(), key=lambda c: (c["created_at"], c["_seq"])
    )
    for c in claims_by_age:
        if c["status"] == "PENDING":
            matures = parse_iso(c["matures_at"])
            if matures is not None and now >= matures:
                mature_claim(store, c)
    for c in claims_by_age:
        if c["status"] == "AVAILABLE":
            expires = parse_iso(c["expires_at"])
            if expires is not None and now >= expires:
                expire_claim(store, c)

    # Referrals: INVITED -> EXPIRED past created_at + REFERRAL_EXPIRY_DAYS.
    for r in store.referrals.values():
        if r["status"] == "INVITED":
            created = parse_iso(r["created_at"])
            if created is not None:
                deadline = created + timedelta(days=REFERRAL_EXPIRY_DAYS)
                if now >= deadline:
                    r["status"] = "EXPIRED"
                    touch(store, r)
