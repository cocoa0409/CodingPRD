"""Ledger + reminder nested lists, and the flat reverse-reachability read surface (§2.6)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_NOT_FOUND
from middleware import authorized, READ_ROLES
from response import success_object
from services.core import public, serialize_lease, option_assessments, option_notices, assessment_case
from routes.helpers import (
    resolve_lease, resolve_option, resolve_assessment, sorted_items, paged,
)

bp = Blueprint("flat", __name__)


# ---------------------------------------------------------------------------
# Nested ledger / reminder lists
# ---------------------------------------------------------------------------

@bp.get("/portfolios/<pid>/leases/<lid>/ledger")
def list_lease_ledger(pid, lid):
    authorized(READ_ROLES)
    resolve_lease(pid, lid)
    items = sorted_items("ledger", {
        "lease_id": lid,
        "entry_kind": request.args.get("entry_kind"),
    })
    return paged(items, public)


@bp.get("/portfolios/<pid>/leases/<lid>/options/<oid>/reminders")
def list_option_reminders(pid, lid, oid):
    authorized(READ_ROLES)
    resolve_option(pid, lid, oid)
    items = sorted_items("reminders", {
        "option_id": oid,
        "status": request.args.get("status"),
        "tier": request.args.get("tier"),
        "contact_id": request.args.get("contact_id"),
    })
    return paged(items, public)


# ---------------------------------------------------------------------------
# Flat read aliases — same resources, root-level paths; read-only
# ---------------------------------------------------------------------------

@bp.get("/leases/<rid>")
def flat_get_lease(rid):
    authorized(READ_ROLES)
    lease = db["leases"].get(rid)
    if lease is None:
        raise_error(ERR_NOT_FOUND, "lease not found")
    return success_object(serialize_lease(lease))


@bp.get("/leases")
def flat_list_leases():
    authorized(READ_ROLES)
    items = sorted_items("leases", {
        "status": request.args.get("status"),
        "active_amendment_id": request.args.get("active_amendment_id"),
    })
    return paged(items, serialize_lease)


@bp.get("/options/<rid>")
def flat_get_option(rid):
    authorized(READ_ROLES)
    o = db["options"].get(rid)
    if o is None:
        raise_error(ERR_NOT_FOUND, "option not found")
    return success_object(public(o))


@bp.get("/assessments/<rid>")
def flat_get_assessment(rid):
    authorized(READ_ROLES)
    m = db["assessments"].get(rid)
    if m is None:
        raise_error(ERR_NOT_FOUND, "assessment not found")
    return success_object(public(m))


@bp.get("/contacts/<rid>")
def flat_get_contact(rid):
    authorized(READ_ROLES)
    c = db["contacts"].get(rid)
    if c is None:
        raise_error(ERR_NOT_FOUND, "contact not found")
    return success_object(public(c))


@bp.get("/amendments/<rid>")
def flat_get_amendment(rid):
    authorized(READ_ROLES)
    a = db["amendments"].get(rid)
    if a is None:
        raise_error(ERR_NOT_FOUND, "amendment not found")
    return success_object(public(a))


@bp.get("/amendments")
def flat_list_amendments():
    authorized(READ_ROLES)
    items = sorted_items("amendments", {
        "status": request.args.get("status"),
        "kind": request.args.get("kind"),
        "supersedes_amendment_id": request.args.get("supersedes_amendment_id"),
    })
    return paged(items, public)


@bp.get("/leases/<rid>/options")
def flat_lease_options(rid):
    authorized(READ_ROLES)
    if db["leases"].get(rid) is None:
        raise_error(ERR_NOT_FOUND, "lease not found")
    items = sorted_items("options", {
        "lease_id": rid,
        "status": request.args.get("status"),
        "option_type": request.args.get("option_type"),
    })
    return paged(items, public)


@bp.get("/leases/<rid>/amendments")
def flat_lease_amendments(rid):
    authorized(READ_ROLES)
    if db["leases"].get(rid) is None:
        raise_error(ERR_NOT_FOUND, "lease not found")
    items = sorted_items("amendments", {
        "lease_id": rid,
        "status": request.args.get("status"),
        "kind": request.args.get("kind"),
    })
    return paged(items, public)


@bp.get("/leases/<rid>/ledger")
def flat_lease_ledger(rid):
    authorized(READ_ROLES)
    if db["leases"].get(rid) is None:
        raise_error(ERR_NOT_FOUND, "lease not found")
    items = sorted_items("ledger", {
        "lease_id": rid,
        "entry_kind": request.args.get("entry_kind"),
    })
    return paged(items, public)


@bp.get("/options/<rid>/assessments")
def flat_option_assessments(rid):
    authorized(READ_ROLES)
    if db["options"].get(rid) is None:
        raise_error(ERR_NOT_FOUND, "option not found")
    status = request.args.get("status")
    items = option_assessments(rid)
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return paged(items, public)


@bp.get("/options/<rid>/notices")
def flat_option_notices(rid):
    authorized(READ_ROLES)
    if db["options"].get(rid) is None:
        raise_error(ERR_NOT_FOUND, "option not found")
    status = request.args.get("status")
    items = option_notices(rid)
    if status is not None:
        items = [n for n in items if n["status"] == status]
    return paged(items, public)


@bp.get("/options/<rid>/reminders")
def flat_option_reminders(rid):
    authorized(READ_ROLES)
    if db["options"].get(rid) is None:
        raise_error(ERR_NOT_FOUND, "option not found")
    items = sorted_items("reminders", {
        "option_id": rid,
        "status": request.args.get("status"),
        "tier": request.args.get("tier"),
        "contact_id": request.args.get("contact_id"),
    })
    return paged(items, public)


@bp.get("/options/<rid>/ledger")
def flat_option_ledger(rid):
    authorized(READ_ROLES)
    if db["options"].get(rid) is None:
        raise_error(ERR_NOT_FOUND, "option not found")
    items = sorted_items("ledger", {"source_option_id": rid})
    return paged(items, public)


@bp.get("/assessments/<rid>/arbitration")
def flat_assessment_arbitration(rid):
    authorized(READ_ROLES)
    if db["assessments"].get(rid) is None:
        raise_error(ERR_NOT_FOUND, "assessment not found")
    case = assessment_case(rid)
    items = [case] if case is not None else []
    return paged(items, public)


@bp.get("/assessments/<rid>/ledger")
def flat_assessment_ledger(rid):
    authorized(READ_ROLES)
    if db["assessments"].get(rid) is None:
        raise_error(ERR_NOT_FOUND, "assessment not found")
    items = sorted_items("ledger", {"source_assessment_id": rid})
    return paged(items, public)


@bp.get("/contacts/<rid>/reminders")
def flat_contact_reminders(rid):
    authorized(READ_ROLES)
    if db["contacts"].get(rid) is None:
        raise_error(ERR_NOT_FOUND, "contact not found")
    items = sorted_items("reminders", {
        "contact_id": rid,
        "status": request.args.get("status"),
        "tier": request.args.get("tier"),
    })
    return paged(items, public)
