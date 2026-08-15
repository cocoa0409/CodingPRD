"""Season-pool state coupling (PRD §2.9): the season's status derives from
its pools, with quota locking/unlocking cascades on the transitions."""
from db import store, touch
from services import quota as quota_service


def season_pools(season_id):
    return [p for p in store.pools.values() if p["season_id"] == season_id]


def maybe_close_season(season):
    """OPEN -> HARVEST_CLOSED when every pool is CLOSED/SETTLED (>= 1 pool).
    Locks every MemberQuota of the season (each lock bumps quota version)."""
    if season["status"] != "OPEN":
        return
    pools = season_pools(season["id"])
    if pools and all(p["status"] in ("CLOSED", "SETTLED") for p in pools):
        season["status"] = "HARVEST_CLOSED"
        touch(season)
        quota_service.lock_season_quotas(season["id"])


def maybe_reopen_season(season):
    """HARVEST_CLOSED -> OPEN when a pool cycles back to OPEN; clears locks."""
    if season["status"] == "HARVEST_CLOSED":
        season["status"] = "OPEN"
        touch(season)
        quota_service.unlock_season_quotas(season["id"])


def maybe_settle_season(season):
    """HARVEST_CLOSED -> SETTLED when every pool of the season is SETTLED."""
    if season["status"] != "HARVEST_CLOSED":
        return
    pools = season_pools(season["id"])
    if pools and all(p["status"] == "SETTLED" for p in pools):
        season["status"] = "SETTLED"
        touch(season)
