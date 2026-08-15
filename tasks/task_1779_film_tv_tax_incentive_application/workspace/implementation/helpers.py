"""Shared route helpers: serialization, list pagination, ownership chains."""
from db import db
from errors import raise_error, ERR_NOT_OWNER
from middleware import authorized, ALL_READ_ROLES
from response import success_list, success_object
from validate import get_pagination, require_path_resource


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_one(collection, rid):
    """GET one resource: auth (1), role (2 — all roles), existence (3)."""
    authorized(ALL_READ_ROLES)
    rec = require_path_resource(collection, rid)
    return success_object(public(rec))


def list_query(collection, filters=None):
    """List with filters, created_at-ascending sort, and limit/offset pagination."""
    authorized(ALL_READ_ROLES)
    items = list(db[collection].values())
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Ownership chains (PRD 2.1): Producer identity is the ProductionCompany id;
# CreditBuyer identity is the CreditBuyer id; CPA ownership compares the audit
# package's stored cpa_user_id.
# ---------------------------------------------------------------------------

def company_id_of_production(production):
    return production["production_company_id"] if production else None


def company_id_of_application(app):
    prod = db["productions"].get(app["production_id"]) if app else None
    return company_id_of_production(prod)


def company_id_of_certificate(cert):
    app = db["applications"].get(cert["application_id"]) if cert else None
    return company_id_of_application(app)


def company_id_of_case(case):
    app = db["applications"].get(case["application_id"]) if case else None
    return company_id_of_application(app)


def check_producer_owns(caller, company_id):
    """Priority 4: entity-backed Producer ownership of the resource chain."""
    if caller.user_id != company_id:
        raise_error(ERR_NOT_OWNER, "caller does not own the target resource chain")


def certificate_for_application(application_id):
    for cert in db["certificates"].values():
        if cert["application_id"] == application_id:
            return cert
    return None


def audit_package_for_application(application_id, statuses=None):
    """The live (or matching) audit package for an application; at most one
    non-REJECTED package exists per application."""
    matches = [
        p for p in db["audit_packages"].values()
        if p["application_id"] == application_id
        and (statuses is None or p["status"] in statuses)
    ]
    if not matches:
        return None
    matches.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return matches[-1]


def program_of_application(app):
    return db["jurisdiction_programs"].get(app["jurisdiction_program_id"])
