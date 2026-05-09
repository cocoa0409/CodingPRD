"""Work-domain helpers: ownership share validation, rights-chain count."""
from errors import api_error
from db import db


def validate_co_owners_unique(co_owners):
    """Raise ERR_DUPLICATE_CO_OWNER if any rights_holder_id appears twice."""
    if not isinstance(co_owners, list):
        co_owners = []
    seen = set()
    for entry in co_owners:
        if not isinstance(entry, dict):
            raise api_error("ERR_VALIDATION", "co_owners entry must be object")
        rid = entry.get("rights_holder_id")
        if rid in seen:
            raise api_error("ERR_DUPLICATE_CO_OWNER",
                            f"co_owner {rid} appears more than once")
        seen.add(rid)


def validate_ownership_shares(primary_share_bps, co_owners):
    """Raise ERR_OWNERSHIP_SHARES_INVALID if shares don't sum to 10000 or are out of range."""
    if not isinstance(co_owners, list):
        co_owners = []
    try:
        primary = int(primary_share_bps)
    except (TypeError, ValueError):
        raise api_error("ERR_OWNERSHIP_SHARES_INVALID", "primary_share_bps invalid")
    if primary <= 0 or primary > 10000:
        raise api_error("ERR_OWNERSHIP_SHARES_INVALID",
                        "primary_share_bps must be in (0, 10000]")
    total = primary
    for entry in co_owners:
        try:
            s = int(entry.get("share_bps"))
        except (TypeError, ValueError):
            raise api_error("ERR_OWNERSHIP_SHARES_INVALID", "share_bps invalid")
        if s <= 0 or s > 10000:
            raise api_error("ERR_OWNERSHIP_SHARES_INVALID",
                            "every share_bps must be in (0, 10000]")
        total += s
    if total != 10000:
        raise api_error("ERR_OWNERSHIP_SHARES_INVALID",
                        f"ownership shares must sum to 10000, got {total}")


def serialize_work(w: dict) -> dict:
    """Return a copy with the computed rights_chain_event_count populated."""
    if not w:
        return w
    out = dict(w)
    out["rights_chain_event_count"] = sum(
        1 for e in db.rights_chain_events.values() if e.get("work_id") == w.get("id")
    )
    return out


def is_owner_or_co_owner(work: dict, holder_id: str) -> bool:
    if not work:
        return False
    if work.get("primary_owner_id") == holder_id:
        return True
    for entry in (work.get("co_owners") or []):
        if entry.get("rights_holder_id") == holder_id:
            return True
    return False
