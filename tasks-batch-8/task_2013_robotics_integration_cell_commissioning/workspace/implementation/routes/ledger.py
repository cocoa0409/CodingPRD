"""RetentionLedgerEntry endpoints (PRD §2.8, §3.9)."""
from flask import Blueprint, request

from db import children, store
from errors import (ApiError, ERR_RETENTION_OVERRELEASE,
                    ERR_STALE_PROJECT_VERSION, bad_request, not_found)
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_SERVICE_MANAGER as SM
from response import success, success_list
from services.domain import maybe_close_project, post_ledger_entry, pub, pubs, touch
from validation import as_enum, as_int, as_str, body, paginate, pagination, req

bp = Blueprint("ledger", __name__)

ENTRY_TYPES = ("WITHHOLD", "RELEASE", "PENALTY", "ADJUST")


@bp.get("/robotics/cell-projects/<project_id>/retention-ledger-entries")
def list_entries(project_id):
    authenticate({FA, SM})
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    limit, offset = pagination()
    items = children("ledger", "cell_project_id", project_id)
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.post("/robotics/cell-projects/<project_id>/retention-ledger-entries")
def post_entry(project_id):
    authenticate({FA})
    project = store.projects.get(project_id)
    if project is None:
        raise not_found("Cell project not found")
    b = body()
    # OCC (priority 5).
    expected = req(b, "expected_project_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("Field 'expected_project_version' must be an integer")
    if expected != project["version"]:
        raise ApiError(ERR_STALE_PROJECT_VERSION, 412,
                       "expected_project_version does not match current project version")
    # Conservation (priority 15) evaluates before generic field checks (18).
    raw_type = b.get("entry_type")
    raw_amount = b.get("amount_cents")
    if (isinstance(raw_type, str) and raw_type in ENTRY_TYPES
            and isinstance(raw_amount, int) and not isinstance(raw_amount, bool)):
        if project["retention_balance_cents"] + raw_amount < 0:
            raise ApiError(ERR_RETENTION_OVERRELEASE, 422,
                           "Posting would drive retention_balance_cents below zero")
    entry_type = as_enum(req(b, "entry_type"), "entry_type", ENTRY_TYPES)
    amount = as_int(req(b, "amount_cents"), "amount_cents")
    milestone_ref = as_str(req(b, "milestone_ref"), "milestone_ref")
    if project["retention_balance_cents"] + amount < 0:
        raise ApiError(ERR_RETENTION_OVERRELEASE, 422,
                       "Posting would drive retention_balance_cents below zero")
    entry = post_ledger_entry(project, entry_type, amount, milestone_ref)
    maybe_close_project(project)
    touch(project)
    return success(pub(entry), 201)
