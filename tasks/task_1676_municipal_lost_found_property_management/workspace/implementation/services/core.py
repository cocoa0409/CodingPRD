"""Core services: record lifecycle, computed fields, and the PRD Section 3
calculations (value tier, retention deadline, proof score, lot minimum bid,
storage occupancy, inquiry SLA, auction settlement, unsold escalation)."""
from datetime import datetime, timedelta, timezone

from db import db
from util import new_id, now_ms, parse_dt, fmt_sec, round_half_up_cents

# ---------------------------------------------------------------------------
# Declared vocabularies
# ---------------------------------------------------------------------------

PROGRAM_TYPES = ["TRANSIT", "FACILITY"]
CATEGORIES = [
    "ELECTRONICS", "JEWELRY", "ID_DOCUMENT", "KEYS", "CLOTHING",
    "BAG", "WALLET", "BICYCLE", "CASH", "OTHER",
]
VALUE_TIERS = ["LOW", "MID", "HIGH"]
DISPOSAL_METHODS = ["AUCTION", "DESTRUCTION", "DONATION"]
HANDOVER_METHODS = ["IN_PERSON", "MAIL"]
PROOF_DETAILS = ["BRIEF", "DETAILED"]
ITEM_STATUSES = [
    "STORED", "LISTED", "RELEASE_PENDING", "RELEASED", "REFERRED_TO_LE",
    "IN_LE_CUSTODY", "EVIDENCE", "AUCTION_ELIGIBLE", "LOTTED", "SOLD",
    "DISPOSAL_PENDING", "DISPOSED", "DONATED",
]
CLAIM_STATUSES = [
    "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "STAYED",
    "APPROVED", "REJECTED", "WITHDRAWN", "RELEASED",
]
INQUIRY_STATUSES = ["OPEN", "ANSWERED", "CLOSED"]
EVENT_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED"]
LOT_STATUSES = ["DRAFT", "PUBLISHED", "SOLD", "CLOSED_UNSOLD", "CANCELLED"]
REFERRAL_STATUSES = ["REFERRED", "IN_CUSTODY", "RETURNED", "CONVERTED_TO_EVIDENCE"]

# Statuses that occupy a storage slot (PRD 2.9).
OCCUPYING_STATUSES = {
    "STORED", "LISTED", "RELEASE_PENDING", "REFERRED_TO_LE",
    "AUCTION_ELIGIBLE", "LOTTED", "DISPOSAL_PENDING",
}

FLOOR_RATES = {"LOW": "0.10", "MID": "0.20", "HIGH": "0.30"}

PROOF_THRESHOLDS = {"LOW": 40, "MID": 60, "HIGH": 80}

COMMISSION_TIER1_MAX = 1_000_000
COMMISSION_TIER2_MAX = 5_000_000

MAX_UNSOLD_CYCLES = 2


# ---------------------------------------------------------------------------
# Record lifecycle (PRD 2.4)
# ---------------------------------------------------------------------------

def new_record(collection, fields, with_version=True):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ms()
    rec["created_at"] = ts
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and increment version by exactly one (PRD 2.4)."""
    rec["updated_at"] = now_ms()
    rec["version"] = rec.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Item calculations
# ---------------------------------------------------------------------------

def value_tier_of(declared_value_cents: int) -> str:
    """LOW < 10000 <= MID < 100000 <= HIGH; boundaries inclusive upward (3.2)."""
    if declared_value_cents < 10000:
        return "LOW"
    if declared_value_cents < 100000:
        return "MID"
    return "HIGH"


def active_policy_for(program_id, category, value_tier):
    for p in db["retention_policies"].values():
        if (
            p["program_id"] == program_id
            and p["item_category"] == category
            and p["value_tier"] == value_tier
            and p["active"]
        ):
            return p
    return None


def compute_retention_deadline(found_at_iso, retention_days, program_type) -> str:
    """TRANSIT: found_at + retention_days * 24h (hour-precise).
    FACILITY: midnight UTC following (calendar date of found_at + retention_days)."""
    found = parse_dt(found_at_iso)
    if program_type == "TRANSIT":
        return fmt_sec(found + timedelta(days=retention_days))
    deadline_date = found.date() + timedelta(days=retention_days + 1)
    return fmt_sec(
        datetime(deadline_date.year, deadline_date.month, deadline_date.day,
                 tzinfo=timezone.utc)
    )


# ---------------------------------------------------------------------------
# Storage occupancy (PRD 2.9) — computed live
# ---------------------------------------------------------------------------

def occupied_slots(location_id) -> int:
    return sum(
        1
        for it in db["items"].values()
        if it["storage_location_id"] == location_id and it["status"] in OCCUPYING_STATUSES
    )


def serialize_location(loc):
    out = dict(loc)
    out["occupied_slots"] = occupied_slots(loc["id"])
    return out


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def compute_proof_score(proofs, claimant) -> int:
    """Weighted score (3.4): id_verified 30, serial 30, photo 15, DETAILED 15,
    receipt 10."""
    score = 0
    if claimant["id_verified"]:
        score += 30
    if proofs.get("proof_serial"):
        score += 30
    if proofs.get("proof_photo"):
        score += 15
    if proofs.get("proof_description_detail") == "DETAILED":
        score += 15
    if proofs.get("proof_receipt"):
        score += 10
    return score


def recompute_claim_scores_for_claimant(claimant):
    """On id verification: recompute proof_score of the claimant's claims in
    {SUBMITTED, UNDER_REVIEW, INFO_REQUESTED} (Claim.version += 1 each)."""
    for claim in db["claims"].values():
        if claim["claimant_id"] != claimant["id"]:
            continue
        if claim["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"):
            claim["proof_score"] = compute_proof_score(claim, claimant)
            touch(claim)


# ---------------------------------------------------------------------------
# Auctions
# ---------------------------------------------------------------------------

def floor_price_of(item) -> int:
    """Per-item floor: round_half_up(declared_value_cents * tier rate) (3.8)."""
    return round_half_up_cents(item["declared_value_cents"], FLOOR_RATES[item["value_tier"]])


def lot_items_of(lot_id):
    return [li for li in db["lot_items"].values() if li["lot_id"] == lot_id]


def recompute_lot_minimum(lot):
    """Sum of already-rounded per-item floors; empty lot -> 0 (pinned rounding
    order: round each item's floor FIRST, then sum)."""
    lot["minimum_bid_cents"] = sum(li["floor_price_cents"] for li in lot_items_of(lot["id"]))


def commission_rate_for_gross(gross_cents: int) -> str:
    if gross_cents < COMMISSION_TIER1_MAX:
        return "0.10"
    if gross_cents < COMMISSION_TIER2_MAX:
        return "0.08"
    return "0.06"


def settle_event_figures(event):
    """Pinned order (3.8): gross over SOLD lots; commission rate keyed on gross;
    per-lot commission rounded HALF_UP then summed; net = gross - commission."""
    sold = [
        l for l in db["auction_lots"].values()
        if l["event_id"] == event["id"] and l["status"] == "SOLD"
    ]
    gross = sum(l["hammer_price_cents"] for l in sold)
    rate = commission_rate_for_gross(gross)
    commission = sum(round_half_up_cents(l["hammer_price_cents"], rate) for l in sold)
    return gross, commission, gross - commission
