"""Path-chain resolvers (priority 3, ERR_NOT_FOUND) and body-FK resolvers
(priority 4, ERR_FK_NOT_FOUND), plus list-filter helpers."""

from flask import request

import db
import errors

S = db.STORE


# ---------------------------------------------------------------- path chain

def resolve_company(cid):
    rec = S["installer_companies"].get(cid)
    if rec is None:
        errors.not_found("Installer company not found")
    return rec


def resolve_staff(collection, cid, row_id):
    resolve_company(cid)
    rec = S[collection].get(row_id)
    if rec is None or rec["installer_company_id"] != cid:
        errors.not_found("Staff record not found")
    return rec


def resolve_customer(cid, cuid):
    resolve_company(cid)
    rec = S["customers"].get(cuid)
    if rec is None or rec["installer_company_id"] != cid:
        errors.not_found("Customer not found")
    return rec


def resolve_site(cid, cuid, sid):
    resolve_customer(cid, cuid)
    rec = S["sites"].get(sid)
    if rec is None or rec["customer_id"] != cuid or rec["installer_company_id"] != cid:
        errors.not_found("Site not found")
    return rec


def _child(collection, row_id, **scope):
    rec = S[collection].get(row_id)
    if rec is None:
        errors.not_found("Resource not found")
    for key, val in scope.items():
        if rec.get(key) != val:
            errors.not_found("Resource not found")
    return rec


def resolve_science(collection, site, row_id):
    return _child(collection, row_id, site_id=site["id"])


def resolve_design(site, did):
    return _child("designs", did, site_id=site["id"])


def resolve_permit(site, pid):
    return _child("permits", pid, site_id=site["id"])


def resolve_installation(site, iid):
    return _child("installations", iid, site_id=site["id"])


def resolve_inspection(inst, inspid):
    return _child("inspections", inspid, installation_id=inst["id"])


def resolve_material(inst, mvid):
    return _child("material_verifications", mvid, installation_id=inst["id"])


def resolve_variance(site, vid):
    return _child("variance_requests", vid, site_id=site["id"])


def resolve_contract(site, mcid):
    return _child("maintenance_contracts", mcid, site_id=site["id"])


def resolve_visit(contract, vid):
    return _child("maintenance_visits", vid, contract_id=contract["id"])


def resolve_repair(site, rid):
    return _child("repair_cases", rid, site_id=site["id"])


# ----------------------------------------------------------------- body FKs

def _fk(collection, row_id, **scope):
    rec = S[collection].get(row_id) if row_id is not None else None
    if rec is None:
        errors.fk_not_found()
    for key, val in scope.items():
        if rec.get(key) != val:
            errors.fk_not_found()
    return rec


def fk_company_staff(collection, cid, row_id):
    return _fk(collection, row_id, installer_company_id=cid)


def fk_site_row(collection, site, row_id):
    return _fk(collection, row_id, site_id=site["id"])


# -------------------------------------------------------------- list filters

def _matches(rec, field, raw):
    val = rec.get(field)
    if isinstance(val, bool):
        return raw.lower() in ("true", "false") and val == (raw.lower() == "true")
    if val is None:
        return False
    return str(val) == raw


def apply_filters(rows, mapping):
    """mapping: query-param name -> record field name."""
    out = list(rows)
    for param, field in mapping.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        out = [r for r in out if _matches(r, field, raw)]
    return out


def rows_of(collection):
    return list(S[collection].values())


def children(collection, field, value):
    return [r for r in S[collection].values() if r.get(field) == value]
