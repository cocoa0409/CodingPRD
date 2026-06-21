"""Serialize internal records to API output, stripping private keys."""


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# Field order is not significant for JSON; we just strip private (underscore) keys.
def serialize(rec):
    return _public(rec)


def serialize_list(recs):
    return [_public(r) for r in recs]
