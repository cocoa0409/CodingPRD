"""Resource representations.

Rows are stored with exactly the fields their representation carries; internal
bookkeeping keys are prefixed with an underscore and are never emitted.
"""


def serialize(row):
    if row is None:
        return None
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))
