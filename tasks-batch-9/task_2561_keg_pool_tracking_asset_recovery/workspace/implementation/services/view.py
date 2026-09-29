"""Row projection and list paging."""
import db
from services import calc


def keg_out(keg):
    """A keg read recomputes its scrap value against the currently effective
    commodity index row."""
    row = dict(keg)
    row["stainless_scrap_value_cents"] = calc.keg_scrap_value(keg)
    return row


def kegs_out(kegs):
    index_row = calc.effective_index()
    out = []
    for keg in kegs:
        row = dict(keg)
        row["stainless_scrap_value_cents"] = calc.keg_scrap_value(keg,
                                                                  index_row)
        out.append(row)
    return out


def ordered(rows):
    """List results are ordered by created_at ascending; a stable sort keeps
    creation order for rows minted at the same logical instant."""
    return sorted(rows, key=lambda row: row["created_at"])


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def match(row, field, value):
    if value is None:
        return True
    return row.get(field) == value
