"""AnnualStatistic endpoints (PRD 3.8): live view, publish, amend."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_STATISTICS_YEAR_INVALID, ERR_DUPLICATE_RESOURCE
from middleware import authorized, STAFF_READ_ROLES
from response import success_object
from services.calculations import compute_annual_statistics
from services.core import new_record, touch, public
from util import clock_iso

bp = Blueprint("statistics", __name__)

YEAR_MIN, YEAR_MAX = 2000, 2100


def _check_year(year):
    if year < YEAR_MIN or year > YEAR_MAX:
        raise_error(ERR_STATISTICS_YEAR_INVALID,
                    f"year must be within {YEAR_MIN}..{YEAR_MAX}")


def _row_for(year):
    for s in db["annual_statistics"].values():
        if s["year"] == year:
            return s
    return None


@bp.get("/annual-statistics/<int:year>")
def get_statistics(year):
    authorized(STAFF_READ_ROLES)
    _check_year(year)
    row = _row_for(year)
    # `counts` is always the LIVE recomputation as of the current logical clock;
    # snapshot_counts/amended_counts are the frozen artifacts (PRD 3.8 variants).
    live = compute_annual_statistics(year)
    if row is None:
        return success_object({
            "year": year,
            "status": "LIVE",
            "counts": live,
            "snapshot_counts": None,
            "amended_counts": None,
            "published_at": None,
            "amended_at": None,
        })
    data = public(row)
    data["counts"] = live
    return success_object(data)


@bp.post("/annual-statistics/<int:year>/publish")
def publish_statistics(year):
    caller = authorized(["TitleIXCoordinator"])
    # Tier 7: year uniqueness.
    if _row_for(year) is not None:
        raise_error(ERR_DUPLICATE_RESOURCE, f"statistics for year {year} already exist")
    # Tier 9: year validity.
    _check_year(year)
    snapshot = compute_annual_statistics(year)
    rec = new_record("annual_statistics", {
        "year": year,
        "status": "PUBLISHED",
        "snapshot_counts": snapshot,
        "amended_counts": None,
        "published_at": clock_iso(),
        "amended_at": None,
    })
    return success_object(public(rec), 201)


@bp.post("/annual-statistics/<int:year>/amend")
def amend_statistics(year):
    caller = authorized(["TitleIXCoordinator"])
    _check_year(year)
    row = _row_for(year)
    if row is None or row["status"] not in ("PUBLISHED", "AMENDED"):
        raise_error(ERR_STATISTICS_YEAR_INVALID,
                    f"no published statistics row exists for year {year}")
    row["amended_counts"] = compute_annual_statistics(year)
    row["amended_at"] = clock_iso()
    row["status"] = "AMENDED"
    touch(row)
    return success_object(public(row))
