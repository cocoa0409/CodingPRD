"""Row -> JSON projection."""

import calc


def dump(row):
    if row is None:
        return None
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def dump_log_entry(entry):
    """superseded_flag is derived on read."""
    if entry is None:
        return None
    out = dump(entry)
    out["superseded_flag"] = calc.is_superseded_entry(entry)
    return out


def dump_many(rows):
    return [dump(r) for r in rows]


def dump_log_entries(rows):
    return [dump_log_entry(r) for r in rows]
