"""Row lookup helpers that raise the per-entity not-found error (PRD 2.6)."""
from errors import ApiError, NOT_FOUND
from store import db, sort_rows


def _find(table, row_id, entity):
    if row_id is None:
        raise ApiError(NOT_FOUND[entity], "%s not found." % entity)
    row = table.get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND[entity], "%s not found." % entity)
    return row


def get_operator(row_id):
    return _find(db.operators, row_id, "Operator")


def get_well(row_id):
    return _find(db.wells, row_id, "Well")


def get_determination(row_id):
    return _find(db.determinations, row_id, "OrphanDetermination")


def get_site_access(row_id):
    return _find(db.site_accesses, row_id, "SiteAccess")


def get_transfer(row_id):
    return _find(db.transfers, row_id, "WellTransfer")


def get_contractor(row_id):
    return _find(db.contractors, row_id, "Contractor")


def get_solicitation(row_id):
    return _find(db.solicitations, row_id, "Solicitation")


def get_bid(row_id):
    return _find(db.bids, row_id, "Bid")


def get_contract(row_id):
    return _find(db.contracts, row_id, "UnitCostContract")


def get_job(row_id):
    return _find(db.jobs, row_id, "PluggingJob")


def get_task(row_id):
    return _find(db.tasks, row_id, "ReclamationTask")


def get_funding_source(row_id):
    return _find(db.funding_sources, row_id, "FundingSource")


def get_allocation(row_id):
    return _find(db.allocations, row_id, "FundingAllocation")


def get_grant_report(row_id):
    return _find(db.grant_reports, row_id, "GrantReport")


def child_of(row, parent_field, parent_id, entity):
    """A child that exists but hangs off another parent is not found for that
    path (PRD 2.6)."""
    if row.get(parent_field) != parent_id:
        raise ApiError(NOT_FOUND[entity], "%s not found." % entity)
    return row


def collect(table, predicate=None, sort_key=None):
    rows = list(table.values())
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    return sort_rows(rows, sort_key)
