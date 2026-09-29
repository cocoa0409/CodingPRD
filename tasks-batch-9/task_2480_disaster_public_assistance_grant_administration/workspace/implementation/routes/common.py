"""Shared route plumbing: prefix, lookups, list rendering."""
from db import db, commit, order_key, serialize
from errors import fail
from response import ok_list
from validate import pagination, qp

PREFIX = "/public-assistance"

NOT_FOUND = {
    "disasters": "ERR_DISASTER_NOT_FOUND",
    "applicants": "ERR_APPLICANT_NOT_FOUND",
    "facilities": "ERR_FACILITY_NOT_FOUND",
    "damage_sites": "ERR_DAMAGE_SITE_NOT_FOUND",
    "projects": "ERR_PROJECT_NOT_FOUND",
    "cost_line_items": "ERR_COST_LINE_ITEM_NOT_FOUND",
    "force_account_resources": "ERR_RESOURCE_NOT_FOUND",
    "contracts": "ERR_CONTRACT_NOT_FOUND",
    "insurance_policies": "ERR_POLICY_NOT_FOUND",
    "drawdowns": "ERR_DRAWDOWN_NOT_FOUND",
    "progress_reports": "ERR_PROGRESS_REPORT_NOT_FOUND",
    "deobligations": "ERR_DEOBLIGATION_NOT_FOUND",
    "appeals": "ERR_APPEAL_NOT_FOUND",
}


def find(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(db, collection).get(row_id)


def require(collection, row_id):
    row = find(collection, row_id)
    if row is None:
        fail(NOT_FOUND[collection], "%s does not resolve" % row_id)
    return row


def render_list(collection, filters):
    """`filters` maps query-parameter name -> row field name."""
    limit, offset = pagination()
    rows = list(getattr(db, collection).values())
    for param, field in filters.items():
        wanted = qp(param)
        if wanted is None:
            continue
        rows = [r for r in rows if str(r.get(field)) == wanted]
    rows.sort(key=order_key)
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, total)


def respond(row, status=200):
    from response import ok
    commit()
    return ok(serialize(row), status)
