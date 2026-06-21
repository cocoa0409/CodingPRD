"""Serialize internal records to the wire format.

Records are stored as plain dicts that already use the field names from the
scaffold. Datetime fields are stored as tz-aware datetimes and serialized to ISO
8601 strings here. The full audit/concurrency triple (created_at, updated_at,
version) is present on Member/Listing/Conversation/Offer/Meetup/Flag/SavedSearch;
Category/Message/SafeTradeSpot/Alert carry only id + created_at (PRD §2.4).
"""
import constants as C
from timeutil import iso_now

# datetime-typed fields per entity (serialized via iso_now).
_DT_FIELDS = {
    "listing": {"expires_at"},
    "offer": {"expires_at"},
    "meetup": {"start_at", "end_at"},
    "alert": {"matched_at"},
}


def _base(rec, dt_fields):
    out = {}
    for k, v in rec.items():
        # Internal-only fields (e.g. _seq, _proposer_side) are never serialized.
        if k.startswith("_"):
            continue
        if k in ("created_at", "updated_at"):
            out[k] = iso_now(v)
        elif k in dt_fields:
            out[k] = iso_now(v)
        else:
            out[k] = v
    return out


def member_out(rec):
    return _base(rec, set())


def category_out(rec):
    return _base(rec, set())


def listing_out(rec, viewer_role=None, viewer_id=None):
    """min_acceptable_price_cents is confidential: returned only to the listing's
    seller (PRD §3.2). Omitted for every other reader."""
    out = _base(rec, _DT_FIELDS["listing"])
    is_seller_owner = (
        viewer_role == C.ROLE_SELLER and viewer_id == rec.get("seller_id")
    )
    if not is_seller_owner:
        out.pop("min_acceptable_price_cents", None)
    return out


def conversation_out(rec):
    return _base(rec, set())


def message_out(rec):
    return _base(rec, set())


def offer_out(rec):
    return _base(rec, _DT_FIELDS["offer"])


def spot_out(rec):
    return _base(rec, set())


def meetup_out(rec):
    return _base(rec, _DT_FIELDS["meetup"])


def flag_out(rec):
    return _base(rec, set())


def saved_search_out(rec):
    return _base(rec, set())


def alert_out(rec):
    return _base(rec, _DT_FIELDS["alert"])
