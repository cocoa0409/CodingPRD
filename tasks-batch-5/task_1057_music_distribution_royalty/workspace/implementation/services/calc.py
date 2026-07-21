"""Calculations and derived aggregates — PRD §2.6, §3.2, §3.7, §3.8, §3.9."""

from fractions import Fraction

from db import db, touch
from services import core


def round_half_up(value):
    """Round a non-negative exact rational to a whole number, half away from zero."""
    frac = Fraction(value)
    if frac >= 0:
        return int((frac + Fraction(1, 2)).__floor__())
    return -int((-frac + Fraction(1, 2)).__floor__())


# ---- derived aggregates ---------------------------------------------------

def recompute_releases_used(subscription, bump=True):
    """PRD §3.2 — count of the artist's releases in SUBMITTED/IN_REVIEW/APPROVED/LIVE."""
    if subscription is None:
        return
    count = len([
        r for r in db.releases.values()
        if r["artist_id"] == subscription["artist_id"]
        and r["status"] in ("SUBMITTED", "IN_REVIEW", "APPROVED", "LIVE")
    ])
    if subscription["releases_used"] != count:
        subscription["releases_used"] = count
        if bump:
            touch(subscription)


def recompute_live_track_count(artist, bump=True):
    """PRD §3.5 — tracks in ACTIVE across all of the artist's releases."""
    if artist is None:
        return
    release_ids = {r["id"] for r in db.releases.values() if r["artist_id"] == artist["id"]}
    count = len([
        t for t in db.tracks.values()
        if t["release_id"] in release_ids and t["status"] == "ACTIVE"
    ])
    if artist["live_track_count"] != count:
        artist["live_track_count"] = count
        if bump:
            touch(artist)


def recompute_sheet_totals(sheet):
    shares = core.shares_of_sheet(sheet["id"])
    sheet["total_share_bps"] = sum(s["share_bps"] for s in shares)
    sheet["accepted_share_count"] = len([s for s in shares if s["accepted"]])


def recompute_statement_aggregates(statement):
    lines = core.lines_of_statement(statement["id"])
    statement["line_count"] = len(lines)
    statement["gross_cents"] = sum(l["gross_cents"] for l in lines)
    statement["content_id_gross_cents"] = sum(
        l["gross_cents"] for l in lines if l["source"] == "CONTENT_ID"
    )


def recompute_collaborator_totals(collaborator, bump=True):
    """PRD §3.9 — the three running buckets are aggregates over the payee's payouts."""
    payouts = core.payouts_of_collaborator(collaborator["id"])
    pending = sum(p["net_cents"] for p in payouts if p["status"] in ("PENDING", "APPROVED"))
    paid = sum(p["net_cents"] for p in payouts if p["status"] == "PAID")
    reversed_total = sum(p["net_cents"] for p in payouts if p["status"] == "REVERSED")
    changed = (
        collaborator["pending_payout_cents"] != pending
        or collaborator["lifetime_paid_cents"] != paid
        or collaborator["reversed_payout_cents"] != reversed_total
    )
    collaborator["pending_payout_cents"] = pending
    collaborator["lifetime_paid_cents"] = paid
    collaborator["reversed_payout_cents"] = reversed_total
    if changed and bump:
        touch(collaborator)


def withholding_bps(collaborator):
    """PRD §3.4 — the four-case ladder, in the pinned order."""
    if collaborator["tax_form_status"] in ("MISSING", "EXPIRED"):
        return core.BACKUP_WITHHOLDING_BPS
    if collaborator["country_code"] == "US":
        return core.US_WITHHOLDING_BPS
    if (
        collaborator["country_code"] in core.TREATY_COUNTRIES
        and collaborator["tax_form_status"] == "VERIFIED"
    ):
        return core.TREATY_REDUCED_WITHHOLDING_BPS
    return core.DEFAULT_FOREIGN_WITHHOLDING_BPS


# ---- commission -----------------------------------------------------------

def loyalty_discount_bps(artist):
    g = artist["lifetime_gross_cents"]
    if g >= core.LOYALTY_TIER_2_MIN_GROSS_CENTS:
        return core.LOYALTY_TIER_2_DISCOUNT_BPS
    if g >= core.LOYALTY_TIER_1_MIN_GROSS_CENTS:
        return core.LOYALTY_TIER_1_DISCOUNT_BPS
    return 0


def weighted_surcharge_bps(statement):
    """PRD §3.7 step two — rounded half up to whole basis points here, once."""
    gross = statement["gross_cents"]
    if gross == 0:
        return 0
    total = 0
    for line in core.lines_of_statement(statement["id"]):
        store = db.stores.get(line["store_id"])
        surcharge = store["surcharge_bps"] if store else 0
        total += line["gross_cents"] * surcharge
    return round_half_up(Fraction(total, gross))


def effective_bps(statement, artist):
    subscription = core.current_subscription(artist["id"])
    plan_bps = 0
    if subscription is not None:
        plan = db.subscription_plans.get(subscription["plan_id"])
        if plan is not None:
            plan_bps = plan["commission_bps"]
    raw = plan_bps - loyalty_discount_bps(artist) + weighted_surcharge_bps(statement)
    return max(0, min(10000, raw))


def commission_cents(statement, artist, variant):
    """PRD §3.7 steps four/five and §3.8 final commission."""
    gross = statement["gross_cents"]
    if gross == 0:
        return 0
    rate = effective_bps(statement, artist)
    if variant == "PROVISIONAL":
        raw = round_half_up(Fraction(gross * rate, 10000))
    else:
        non_cid = gross - statement["content_id_gross_cents"]
        raw = round_half_up(Fraction(non_cid * rate, 10000)) + round_half_up(
            Fraction(statement["content_id_gross_cents"] * core.CONTENT_ID_COMMISSION_BPS, 10000)
        )
    cap = round_half_up(Fraction(gross * core.COMMISSION_CAP_BPS, 10000))
    return max(core.MIN_COMMISSION_CENTS, min(raw, cap))


def content_id_bonus_cents(statement):
    """PRD §3.8 — tier selected from the pre-bonus Content-ID gross."""
    c = statement["content_id_gross_cents"]
    if c >= core.CONTENT_ID_BONUS_TIER_2_MIN_CENTS:
        rate = core.CONTENT_ID_BONUS_TIER_2_BPS
    elif c >= core.CONTENT_ID_BONUS_TIER_1_MIN_CENTS:
        rate = core.CONTENT_ID_BONUS_TIER_1_BPS
    else:
        rate = 0
    return round_half_up(Fraction(c * rate, 10000))


# ---- two-level waterfall allocation --------------------------------------

def allocate_payout_shares(statement):
    """PRD §3.8 — returns an ordered list of (collaborator_id, cents) contributions.

    Floor-then-largest-remainder at each of the two levels.
    """
    lines = core.lines_of_statement(statement["id"])
    net = statement["net_cents"]
    gross = statement["gross_cents"]

    track_gross = {}
    for line in lines:
        track_gross[line["track_id"]] = track_gross.get(line["track_id"], 0) + line["gross_cents"]

    participating = []
    for track_id in track_gross:
        track = db.tracks.get(track_id)
        if track is not None:
            participating.append(track)
    participating.sort(key=lambda t: (t["created_at"], t["_seq"]))

    track_net = {}
    if gross == 0:
        for track in participating:
            track_net[track["id"]] = 0
    else:
        fracs = {}
        for track in participating:
            raw = Fraction(net * track_gross[track["id"]], gross)
            floored = int(raw.__floor__())
            track_net[track["id"]] = floored
            fracs[track["id"]] = raw - floored
        residual = net - sum(track_net.values())
        order = sorted(
            participating,
            key=lambda t: (-fracs[t["id"]], t["created_at"], t["_seq"]),
        )
        for track in order[:max(0, residual)]:
            track_net[track["id"]] += 1

    contributions = []
    for track in participating:
        allocated = track_net[track["id"]]
        sheet_id = track.get("locked_split_sheet_id")
        if not sheet_id:
            continue
        shares = core.shares_of_sheet(sheet_id)
        shares.sort(key=lambda s: (s["created_at"], s["_seq"]))
        if not shares:
            continue
        cents = {}
        fracs = {}
        for share in shares:
            raw = Fraction(allocated * share["share_bps"], 10000)
            floored = int(raw.__floor__())
            cents[share["id"]] = floored
            fracs[share["id"]] = raw - floored
        residual = allocated - sum(cents.values())
        order = sorted(
            shares,
            key=lambda s: (-fracs[s["id"]], -s["share_bps"], s["created_at"], s["_seq"]),
        )
        for share in order[:max(0, residual)]:
            cents[share["id"]] += 1
        for share in shares:
            contributions.append((share["collaborator_id"], cents[share["id"]]))
    return contributions
