"""Domain constants and shared lookup helpers."""

from db import db
from errors import ApiError

# Domain constants (PRD §3).
MIN_RELEASE_LEAD_DAYS = 7
SUBSCRIPTION_GRACE_DAYS = 30
MAX_DELIVERY_ATTEMPTS = 3
SPLIT_TOTAL_BPS = 10000
STORE_DELIVERY_WINDOW_MINUTES = 60
STORE_DELIVERY_BUFFER_MINUTES = 15
PAYOUT_THRESHOLD_CENTS = 2000
PAYOUT_REVERSAL_WINDOW_DAYS = 90
TAX_1099_THRESHOLD_CENTS = 60000
MIN_COMMISSION_CENTS = 50
COMMISSION_CAP_BPS = 2000
CONTENT_ID_COMMISSION_BPS = 3000
BACKUP_WITHHOLDING_BPS = 2400
US_WITHHOLDING_BPS = 0
TREATY_REDUCED_WITHHOLDING_BPS = 1000
DEFAULT_FOREIGN_WITHHOLDING_BPS = 3000
TREATY_COUNTRIES = ("GB", "DE", "NL", "AU", "JP")
LOYALTY_TIER_1_MIN_GROSS_CENTS = 100000
LOYALTY_TIER_1_DISCOUNT_BPS = 100
LOYALTY_TIER_2_MIN_GROSS_CENTS = 500000
LOYALTY_TIER_2_DISCOUNT_BPS = 250
CONTENT_ID_BONUS_TIER_1_MIN_CENTS = 50000
CONTENT_ID_BONUS_TIER_1_BPS = 200
CONTENT_ID_BONUS_TIER_2_MIN_CENTS = 200000
CONTENT_ID_BONUS_TIER_2_BPS = 500


def not_found():
    raise ApiError("ERR_RESOURCE_NOT_FOUND")


def get_or_404(collection, row_id):
    if not isinstance(row_id, str):
        not_found()
    row = collection.get(row_id)
    if row is None:
        not_found()
    return row


def find_plan(plan_id):
    return get_or_404(db.subscription_plans, plan_id)


def find_store(store_id):
    return get_or_404(db.stores, store_id)


def find_artist(artist_id):
    return get_or_404(db.artists, artist_id)


def find_subscription(sub_id):
    return get_or_404(db.subscriptions, sub_id)


def find_release(release_id):
    return get_or_404(db.releases, release_id)


def find_track(track_id):
    return get_or_404(db.tracks, track_id)


def find_collaborator(collaborator_id):
    return get_or_404(db.collaborators, collaborator_id)


def find_sheet(sheet_id):
    return get_or_404(db.split_sheets, sheet_id)


def find_share(share_id):
    return get_or_404(db.split_shares, share_id)


def find_delivery(delivery_id):
    return get_or_404(db.deliveries, delivery_id)


def find_statement(statement_id):
    return get_or_404(db.royalty_statements, statement_id)


def find_line(line_id):
    return get_or_404(db.royalty_lines, line_id)


def find_payout(payout_id):
    return get_or_404(db.payouts, payout_id)


def find_tax_form(form_id):
    return get_or_404(db.tax_forms, form_id)


# ---- relationship helpers -------------------------------------------------

def tracks_of_release(release_id):
    return [t for t in db.tracks.values() if t["release_id"] == release_id]


def deliveries_of_release(release_id):
    return [d for d in db.deliveries.values() if d["release_id"] == release_id]


def shares_of_sheet(sheet_id):
    return [s for s in db.split_shares.values() if s["split_sheet_id"] == sheet_id]


def sheets_of_track(track_id):
    return [s for s in db.split_sheets.values() if s["track_id"] == track_id]


def lines_of_statement(statement_id):
    return [l for l in db.royalty_lines.values() if l["royalty_statement_id"] == statement_id]


def payouts_of_collaborator(collaborator_id):
    return [p for p in db.payouts.values() if p["collaborator_id"] == collaborator_id]


def payouts_of_statement(statement_id):
    return [p for p in db.payouts.values() if p["royalty_statement_id"] == statement_id]


def releases_of_artist(artist_id):
    return [r for r in db.releases.values() if r["artist_id"] == artist_id]


def artist_of_release(release):
    return db.artists.get(release["artist_id"])


def artist_of_track(track):
    release = db.releases.get(track["release_id"])
    return release["artist_id"] if release else None


def artist_of_sheet(sheet):
    track = db.tracks.get(sheet["track_id"])
    return artist_of_track(track) if track else None


def artist_of_share(share):
    sheet = db.split_sheets.get(share["split_sheet_id"])
    return artist_of_sheet(sheet) if sheet else None


def artist_of_payout(payout):
    collaborator = db.collaborators.get(payout["collaborator_id"])
    return collaborator["artist_id"] if collaborator else None


def artist_of_tax_form(form):
    collaborator = db.collaborators.get(form["collaborator_id"])
    return collaborator["artist_id"] if collaborator else None


def current_subscription(artist_id):
    """PRD §3.7 step three: the most recently created subscription of the artist
    whose status is ACTIVE, PAST_DUE, EXPIRED or CANCELLED."""
    candidates = [
        s for s in db.subscriptions.values()
        if s["artist_id"] == artist_id
        and s["status"] in ("ACTIVE", "PAST_DUE", "EXPIRED", "CANCELLED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return candidates[-1]


def any_subscription(artist_id):
    """The artist's subscription used for entitlement gates: latest created row."""
    candidates = [s for s in db.subscriptions.values() if s["artist_id"] == artist_id]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return candidates[-1]
