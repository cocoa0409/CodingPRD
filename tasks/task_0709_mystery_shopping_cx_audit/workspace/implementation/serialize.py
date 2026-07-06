"""Resource serialization — strip internal bookkeeping fields (those prefixed
with '_') from the stored record before returning it in the response body.
"""


def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
