"""Serializer instances, wired with live-compute hooks where needed."""
from serializers import make_serializer, _coerce, _COMMON, _FIELDS
import queries

ser_title = make_serializer("title")
ser_format = make_serializer("format")
ser_asset = make_serializer("asset")
ser_isbn = make_serializer("isbn")
ser_channel = make_serializer("channel")
ser_price = make_serializer("price")
ser_proof = make_serializer("proof")
ser_drequest = make_serializer("drequest")
ser_salesline = make_serializer("salesline")
ser_statement = make_serializer("statement", provisional_fn=queries.provisional_net)


def ser_publisher(rec):
    """Publisher reserve_held_cents and lifetime_paid_cents are derived rollups,
    computed live so reads always reflect current sales/statements."""
    out = {k: _coerce(rec.get(k)) for k in _COMMON}
    for f in _FIELDS["publisher"]:
        out[f] = _coerce(rec.get(f))
    out["reserve_held_cents"] = queries.compute_reserve_held(rec["id"])
    out["lifetime_paid_cents"] = queries.compute_lifetime_paid(rec["id"])
    return out
