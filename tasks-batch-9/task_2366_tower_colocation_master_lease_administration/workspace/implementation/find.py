"""Resource resolution helpers; each raises the 404 code of its own type."""
from db import db
from errors import ApiError


def _get(collection, identifier, error_id, label):
    if not isinstance(identifier, str):
        raise ApiError(error_id, "%s not found." % label)
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id, "%s not found." % label)
    return record


def tower(identifier):
    return _get(db.towers, identifier, "ERR_TOWER_NOT_FOUND", "Tower")


def landlord(identifier):
    return _get(db.landlords, identifier, "ERR_LANDLORD_NOT_FOUND", "Landlord")


def ground_lease(identifier):
    return _get(db.ground_leases, identifier, "ERR_GROUND_LEASE_NOT_FOUND", "Ground lease")


def tenant(identifier):
    return _get(db.tenants, identifier, "ERR_TENANT_NOT_FOUND", "Tenant")


def mla(identifier):
    return _get(db.mlas, identifier, "ERR_MLA_NOT_FOUND", "Master lease agreement")


def application(identifier):
    return _get(db.applications, identifier, "ERR_APPLICATION_NOT_FOUND",
                "Colocation application")


def equipment_line(identifier):
    return _get(db.equipment_lines, identifier, "ERR_EQUIPMENT_LINE_NOT_FOUND",
                "Equipment line")


def analysis(identifier):
    return _get(db.analyses, identifier, "ERR_ANALYSIS_NOT_FOUND", "Structural analysis")


def amendment(identifier):
    return _get(db.amendments, identifier, "ERR_AMENDMENT_NOT_FOUND", "Site amendment")


def project(identifier):
    return _get(db.projects, identifier, "ERR_PROJECT_NOT_FOUND", "Modification project")


def cost_share(identifier):
    return _get(db.cost_shares, identifier, "ERR_COST_SHARE_NOT_FOUND", "Cost share")


def audit(identifier):
    return _get(db.audits, identifier, "ERR_AUDIT_NOT_FOUND", "Equipment audit")


def finding(identifier):
    return _get(db.findings, identifier, "ERR_FINDING_NOT_FOUND", "Audit finding")
