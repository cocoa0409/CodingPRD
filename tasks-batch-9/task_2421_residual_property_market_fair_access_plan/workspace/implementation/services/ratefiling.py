"""Rate selection and the filing quiet-window (PRD 3.2)."""

from db import db, sorted_records
from util import parse_date


def approved_filings(cat_zone_id, peril_package):
    return [f for f in db.rate_filings.values()
            if f["cat_zone_id"] == cat_zone_id
            and f["peril_package"] == peril_package
            and f["status"] == "APPROVED"]


def _pick_greatest_effective(rows):
    """Greatest effective_date wins; tie-break in favour of earliest created_at."""
    dated = []
    for filing in rows:
        effective = parse_date(filing["effective_date"])
        if effective is not None:
            dated.append((effective, filing))
    if not dated:
        return None
    newest = max(pair[0] for pair in dated)
    tied = [pair[1] for pair in dated if pair[0] == newest]
    return sorted_records(None, tied)[0]


def select_rate_filing(cat_zone_id, peril_package, reference_date):
    """APPROVED, matching territory + package, effective_date on or before the
    reference date; greatest effective_date, tie-break earliest created_at."""
    rows = []
    for filing in approved_filings(cat_zone_id, peril_package):
        effective = parse_date(filing["effective_date"])
        if effective is not None and effective <= reference_date:
            rows.append(filing)
    return _pick_greatest_effective(rows)


def latest_approved_filing(cat_zone_id, peril_package):
    """The incumbent APPROVED filing on the (territory, package) pair."""
    return _pick_greatest_effective(approved_filings(cat_zone_id, peril_package))
