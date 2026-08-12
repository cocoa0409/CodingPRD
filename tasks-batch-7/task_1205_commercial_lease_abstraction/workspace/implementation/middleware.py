"""Auth extraction / RBAC (validation pipeline steps 1-2) and request-body
validation helpers (pipeline step 4)."""

from flask import request

from errors import err

ROLES = {
    "PlatformAdmin",
    "PortfolioManager",
    "PropertyManager",
    "LeaseAccountant",
    "Abstractor",
    "Certifier",
}

ANY_ROLE = sorted(ROLES)

# Every authenticated GET is allowed for all roles; write endpoints name roles.
ENDPOINT_ROLES = {
    ("POST", "/lease-admin/_clock/set_current_utc"): ["PlatformAdmin"],
    ("POST", "/lease-admin/properties"): ["PlatformAdmin"],
    ("GET", "/lease-admin/properties/<property_id>"): ANY_ROLE,
    ("GET", "/lease-admin/properties"): ANY_ROLE,
    ("GET", "/lease-admin/properties/<property_id>/occupancy-report"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("POST", "/lease-admin/properties/<property_id>/leases"): ["PortfolioManager"],
    ("GET", "/lease-admin/leases/<lease_id>"): ANY_ROLE,
    ("GET", "/lease-admin/leases"): ANY_ROLE,
    ("GET", "/lease-admin/properties/<property_id>/leases"): ANY_ROLE,
    ("POST", "/lease-admin/leases/<lease_id>/abstract"): ["Abstractor"],
    ("POST", "/lease-admin/leases/<lease_id>/certify"): ["Certifier"],
    ("POST", "/lease-admin/leases/<lease_id>/reopen-abstraction"): ["PortfolioManager"],
    ("POST", "/lease-admin/leases/<lease_id>/activate"): ["PortfolioManager"],
    ("POST", "/lease-admin/leases/<lease_id>/terminate"): ["PortfolioManager"],
    ("GET", "/lease-admin/leases/<lease_id>/rent-roll"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("POST", "/lease-admin/leases/<lease_id>/rent-schedule-lines"): ["PortfolioManager"],
    ("GET", "/lease-admin/leases/<lease_id>/rent-schedule-lines"): ANY_ROLE,
    ("GET", "/lease-admin/rent-schedule-lines/<line_id>"): ANY_ROLE,
    ("POST", "/lease-admin/leases/<lease_id>/escalation-steps"): ["PortfolioManager"],
    ("GET", "/lease-admin/leases/<lease_id>/escalation-steps"): ANY_ROLE,
    ("GET", "/lease-admin/escalation-steps/<step_id>"): ANY_ROLE,
    ("POST", "/lease-admin/properties/<property_id>/recovery-pools"): ["LeaseAccountant"],
    ("PUT", "/lease-admin/recovery-pools/<pool_id>/actuals"): ["LeaseAccountant"],
    ("GET", "/lease-admin/properties/<property_id>/recovery-pools"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/recovery-pools/<pool_id>"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("POST", "/lease-admin/leases/<lease_id>/recovery-billings"): ["LeaseAccountant"],
    ("GET", "/lease-admin/leases/<lease_id>/recovery-billings"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/recovery-billings/<billing_id>"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("POST", "/lease-admin/recovery-billings/<billing_id>/issue"): ["LeaseAccountant"],
    ("POST", "/lease-admin/recovery-billings/<billing_id>/mark-paid"): ["LeaseAccountant"],
    ("POST", "/lease-admin/recovery-billings/<billing_id>/void"): ["LeaseAccountant"],
    ("POST", "/lease-admin/leases/<lease_id>/reconciliations"): ["LeaseAccountant"],
    ("GET", "/lease-admin/leases/<lease_id>/reconciliations"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/reconciliations/<recon_id>"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("POST", "/lease-admin/reconciliations/<recon_id>/post"): ["LeaseAccountant"],
    ("POST", "/lease-admin/reconciliations/<recon_id>/approve"): ["PortfolioManager"],
    ("POST", "/lease-admin/reconciliations/<recon_id>/close"): ["PortfolioManager"],
    ("POST", "/lease-admin/leases/<lease_id>/critical-dates"): ["PropertyManager"],
    ("GET", "/lease-admin/leases/<lease_id>/critical-dates"): ANY_ROLE,
    ("GET", "/lease-admin/critical-dates/<cd_id>"): ANY_ROLE,
    ("POST", "/lease-admin/critical-dates/<cd_id>/notify"): ["PropertyManager"],
    ("POST", "/lease-admin/critical-dates/<cd_id>/exercise"): ["PropertyManager"],
    ("POST", "/lease-admin/critical-dates/<cd_id>/lapse"): ["PropertyManager"],
    ("POST", "/lease-admin/critical-dates/<cd_id>/waive"): ["PortfolioManager"],
    ("POST", "/lease-admin/leases/<lease_id>/compliance-docs"): ["PropertyManager"],
    ("GET", "/lease-admin/leases/<lease_id>/compliance-docs"): ANY_ROLE,
    ("GET", "/lease-admin/compliance-docs/<doc_id>"): ANY_ROLE,
    ("POST", "/lease-admin/compliance-docs/<doc_id>/start-review"): ["PropertyManager"],
    ("POST", "/lease-admin/compliance-docs/<doc_id>/accept"): ["PropertyManager"],
    ("POST", "/lease-admin/compliance-docs/<doc_id>/reject"): ["PropertyManager"],
    ("POST", "/lease-admin/leases/<lease_id>/amendments"): ["PortfolioManager"],
    ("GET", "/lease-admin/leases/<lease_id>/amendments"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/amendments/<amendment_id>"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("POST", "/lease-admin/amendments/<amendment_id>/approve"): ["PortfolioManager"],
    ("POST", "/lease-admin/amendments/<amendment_id>/apply"): ["PortfolioManager"],
    ("POST", "/lease-admin/amendments/<amendment_id>/reject"): ["PortfolioManager"],
    ("POST", "/lease-admin/leases/<lease_id>/tenant-challenges"): ["PropertyManager"],
    ("GET", "/lease-admin/leases/<lease_id>/tenant-challenges"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/tenant-challenges/<challenge_id>"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("POST", "/lease-admin/tenant-challenges/<challenge_id>/start-review"): ["LeaseAccountant"],
    ("POST", "/lease-admin/tenant-challenges/<challenge_id>/reopen"): ["LeaseAccountant"],
    ("POST", "/lease-admin/tenant-challenges/<challenge_id>/resolve"): ["PortfolioManager"],
    ("POST", "/lease-admin/tenant-challenges/<challenge_id>/escalate"): ["PropertyManager"],
    ("POST", "/lease-admin/tenant-challenges/<challenge_id>/withdraw"): ["PropertyManager"],
    ("POST", "/lease-admin/leases/<lease_id>/audit-rights"): ["PropertyManager"],
    ("GET", "/lease-admin/leases/<lease_id>/audit-rights"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/audit-rights/<audit_id>"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("POST", "/lease-admin/audit-rights/<audit_id>/start-fieldwork"): ["PropertyManager"],
    ("POST", "/lease-admin/audit-rights/<audit_id>/issue-findings"): ["PropertyManager"],
    ("POST", "/lease-admin/audit-rights/<audit_id>/settle"): ["PortfolioManager"],
    ("GET", "/lease-admin/rent-schedule-lines"): ANY_ROLE,
    ("GET", "/lease-admin/escalation-steps"): ANY_ROLE,
    ("GET", "/lease-admin/recovery-pools"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/recovery-billings"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/reconciliations"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/critical-dates"): ANY_ROLE,
    ("GET", "/lease-admin/compliance-docs"): ANY_ROLE,
    ("GET", "/lease-admin/amendments"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/tenant-challenges"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
    ("GET", "/lease-admin/audit-rights"):
        ["PlatformAdmin", "PortfolioManager", "PropertyManager", "LeaseAccountant"],
}


def current_role():
    """Validation pipeline step 1: authentication."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        err("ERR_UNAUTHENTICATED",
            "X-User-Role header missing or not a recognized role")
    return role


def current_user_id():
    return request.headers.get("X-User-ID")


def authorize(rule_path):
    """Validation pipeline step 2: authorization per endpoint role table."""
    role = current_role()
    allowed = ENDPOINT_ROLES.get((request.method, rule_path))
    if allowed is None:
        # Not a declared API endpoint — fall through to routing/404.
        return role
    if role not in allowed:
        err("ERR_FORBIDDEN", f"Role {role} is not permitted for this endpoint")
    return role
