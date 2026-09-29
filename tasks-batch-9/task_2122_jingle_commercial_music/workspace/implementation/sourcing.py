"""Library-versus-custom sourcing comparison (PRD 3.9)."""

import db
import licensing
from errors import ApiError

LIBRARY_FLOOR_CENTS = 25000
LIBRARY_MARGIN_PCT = 15
LIVE_DEAL_STATUSES = ("DRAFT", "PROPOSED", "ACCEPTED", "ACTIVE", "RENEWAL_DUE")


def live_deal(project_id):
    """created_at DESC, tie-break version DESC, first row wins."""
    rows = [d for d in db.license_deals.values()
            if d["project_id"] == project_id and d["status"] in LIVE_DEAL_STATUSES]
    if not rows:
        return None
    rows.sort(key=lambda d: (d["created_at"], d["version"], d["_seq"]), reverse=True)
    return rows[0]


def compare(project):
    brief = licensing.approved_brief(project["id"])
    if brief is None:
        raise ApiError("ERR_NO_ELIGIBLE_LIBRARY_TRACK",
                       "No eligible production-library track for this engagement.")
    n_markets = len(brief["target_markets"])
    shortest_cut = min(brief["required_lengths"])

    deal = live_deal(project["id"])
    deal_quote = deal["license_fee_quoted_cents"] if deal else 0
    custom_total_cents = project["spent_cents"] + project["committed_cents"] + deal_quote

    eligible = [
        t for t in db.library_tracks.values()
        if t["status"] == "ACTIVE"
        and t["max_markets"] >= n_markets
        and t["min_length_seconds"] <= shortest_cut
    ]
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_LIBRARY_TRACK",
                       "No eligible production-library track for this engagement.")

    def quote(track):
        return track["blanket_fee_cents"] + track["per_market_fee_cents"] * n_markets

    selected = sorted(eligible, key=lambda t: (quote(t), t["created_at"], t["_seq"]))[0]
    library_total_cents = max(LIBRARY_FLOOR_CENTS, quote(selected))
    savings_cents = custom_total_cents - library_total_cents
    recommended_mode = (
        "LIBRARY"
        if library_total_cents * 100 <= custom_total_cents * (100 - LIBRARY_MARGIN_PCT)
        else "CUSTOM"
    )
    return {
        "custom_total_cents": custom_total_cents,
        "library_total_cents": library_total_cents,
        "selected_library_track_id": selected["id"],
        "eligible_track_count": len(eligible),
        "savings_cents": savings_cents,
        "recommended_mode": recommended_mode,
    }
