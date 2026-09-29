"""Record serialisation.

Records are stored holding exactly the fields the API exposes, so rendering a
record is a shallow copy (with list fields copied so callers cannot mutate the
store through the response body).
"""


def out(record):
    if record is None:
        return None
    return {
        key: (list(value) if isinstance(value, list) else value)
        for key, value in record.items()
    }
