"""Waitlist promotion (PRD 3.3): when a confirmed slot frees on a distance and
at least one entry is QUEUED, promote the head (lowest created_at) to OFFERED,
stamp offer_expires_utc = now + OFFER_TTL_HOURS, bump its version."""
import datetime

from db import db
from middleware import fmt_iso, now_dt
from services.calculations import OFFER_TTL_HOURS
from services.store import touch, confirmed_count


def promote_head(distance_id):
    """Promote the head QUEUED entry on the distance to OFFERED, provided the
    distance now has room. Returns the promoted entry or None."""
    dist = db.distances.get(distance_id)
    if dist is None:
        return None
    if confirmed_count(distance_id) >= dist["capacity_total"]:
        return None
    queued = [e for e in db.waitlist_entries.values()
              if e["distance_id"] == distance_id and e["status"] == "QUEUED"]
    if not queued:
        return None
    queued.sort(key=lambda e: (e["_created_dt"], e["_seq"]))
    head = queued[0]
    head["status"] = "OFFERED"
    expires = now_dt() + datetime.timedelta(hours=OFFER_TTL_HOURS)
    head["offer_expires_utc"] = fmt_iso(expires)
    head["_offer_expires_dt"] = expires
    touch(head)
    return head
