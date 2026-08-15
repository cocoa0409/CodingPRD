"""Flat filtered-list GET endpoints (SCAFFOLD §1.5): cross-portfolio reverse
reachability lists. Default ordering is created_at ASC (PRD §2.3); the
cross-portfolio annuity-obligation list orders by owning application
created_at ASC then period_year ASC.
"""

from flask import Blueprint, request

import db as dbmod
import serialize
from middleware import require_roles, parse_pagination, ALL_ROLES
from response import success_list

bp = Blueprint("lists", __name__)


def _paginate(items, serializer):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


@bp.get("/contacts")
def list_contacts():
    require_roles(ALL_ROLES)
    client_id = request.args.get("client_id")
    items = list(dbmod.DB["contacts"].values())
    if client_id is not None:
        items = [c for c in items if c["client_id"] == client_id]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.contact)


@bp.get("/inventors")
def list_inventors():
    require_roles(ALL_ROLES)
    client_id = request.args.get("client_id")
    items = list(dbmod.DB["inventors"].values())
    if client_id is not None:
        items = [i for i in items if i["client_id"] == client_id]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.inventor)


@bp.get("/families")
def list_families():
    require_roles(ALL_ROLES)
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    items = list(dbmod.DB["families"].values())
    if client_id is not None:
        items = [f for f in items if f["client_id"] == client_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.family)


@bp.get("/applications")
def list_applications():
    require_roles(ALL_ROLES)
    family_id = request.args.get("family_id")
    parent_application_id = request.args.get("parent_application_id")
    status = request.args.get("status")
    items = list(dbmod.DB["applications"].values())
    if family_id is not None:
        items = [a for a in items if a["family_id"] == family_id]
    if parent_application_id is not None:
        items = [a for a in items if a["parent_application_id"] == parent_application_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.application)


@bp.get("/docket-entries")
def list_docket_entries():
    require_roles(ALL_ROLES)
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    entry_type = request.args.get("entry_type")
    items = list(dbmod.DB["docket_entries"].values())
    if application_id is not None:
        items = [e for e in items if e["application_id"] == application_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.docket_entry)


@bp.get("/office-actions")
def list_office_actions():
    require_roles(ALL_ROLES)
    application_id = request.args.get("application_id")
    docket_entry_id = request.args.get("docket_entry_id")
    items = list(dbmod.DB["office_actions"].values())
    if application_id is not None:
        items = [o for o in items if o["application_id"] == application_id]
    if docket_entry_id is not None:
        items = [o for o in items if o.get("docket_entry_id") == docket_entry_id]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.office_action)


@bp.get("/annuity-obligations")
def list_obligations():
    require_roles(ALL_ROLES)
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    items = list(dbmod.DB["obligations"].values())
    if application_id is not None:
        items = [o for o in items if o["application_id"] == application_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    # Cross-portfolio order: owning application created_at ASC, then period_year ASC.
    app_created = {
        a["id"]: a["created_at"] for a in dbmod.DB["applications"].values()
    }
    items.sort(key=lambda o: (app_created.get(o["application_id"], ""), o["period_year"]))
    return _paginate(items, serialize.obligation)


@bp.get("/authorizations")
def list_authorizations():
    require_roles(ALL_ROLES)
    obligation_id = request.args.get("annuity_obligation_id")
    status = request.args.get("status")
    items = list(dbmod.DB["authorizations"].values())
    if obligation_id is not None:
        items = [a for a in items if a["annuity_obligation_id"] == obligation_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.authorization)


@bp.get("/instructions")
def list_instructions():
    require_roles(ALL_ROLES)
    application_id = request.args.get("application_id")
    counsel_firm_id = request.args.get("counsel_firm_id")
    docket_entry_id = request.args.get("docket_entry_id")
    status = request.args.get("status")
    items = list(dbmod.DB["instructions"].values())
    if application_id is not None:
        items = [i for i in items if i["application_id"] == application_id]
    if counsel_firm_id is not None:
        items = [i for i in items if i["counsel_firm_id"] == counsel_firm_id]
    if docket_entry_id is not None:
        items = [i for i in items if i.get("docket_entry_id") == docket_entry_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.instruction)


@bp.get("/abandonment-reviews")
def list_reviews():
    require_roles(ALL_ROLES)
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    items = list(dbmod.DB["reviews"].values())
    if application_id is not None:
        items = [r for r in items if r["application_id"] == application_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.review)


@bp.get("/assignments")
def list_assignments():
    require_roles(ALL_ROLES)
    application_id = request.args.get("application_id")
    inventor_ids = request.args.get("inventor_ids")
    items = list(dbmod.DB["assignments"].values())
    if application_id is not None:
        items = [a for a in items if a["application_id"] == application_id]
    if inventor_ids is not None:
        wanted = {part.strip() for part in inventor_ids.split(",") if part.strip()}
        items = [a for a in items if wanted & set(a["inventor_ids"])]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.assignment)


@bp.get("/audits")
def list_audits():
    require_roles(ALL_ROLES)
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    items = list(dbmod.DB["audits"].values())
    if application_id is not None:
        items = [a for a in items if a["application_id"] == application_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return _paginate(items, serialize.audit)
