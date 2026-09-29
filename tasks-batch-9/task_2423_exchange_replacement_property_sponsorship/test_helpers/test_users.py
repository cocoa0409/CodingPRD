"""Pre-built role headers for every role in the PRD.

Six of the seven roles are opaque operator identities, so the shared constant
below is their canonical form. `Investor` is different: the PRD states that an
investor's `X-User-ID` equals `Investor.id`, so ownership-gated investor calls
MUST use `make_investor_headers(investor["id"])` with a real investor id.
"""

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. Safe for the six opaque roles, and for investor-role tests
# that do not depend on the caller owning the subject row.
TEST_USERS = {
    "sponsor_headers": build_user_headers("sponsor-1", "SponsorPrincipal"),
    "compliance_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    "trustee_headers": build_user_headers("trustee-1", "Trustee"),
    # entity_backed role: the shared constant never equals a real Investor.id,
    # so use it only for non-ownership tests.
    "investor_headers": build_user_headers("investor-1", "Investor"),
    "master_tenant_headers": build_user_headers("tenant-1", "MasterTenant"),
    "qi_headers": build_user_headers("qi-1", "QualifiedIntermediary"),
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


# A second distinct operator per opaque role, for the two segregation-of-duties
# rules: the officer who submits a memorandum may not declare it effective, and
# the sponsor who closes a subscription may not be the officer who approved the
# investor's suitability.
SECOND_USERS = {
    "sponsor_headers": build_user_headers("sponsor-2", "SponsorPrincipal"),
    "compliance_headers": build_user_headers("compliance-2", "ComplianceOfficer"),
    "trustee_headers": build_user_headers("trustee-2", "Trustee"),
    "master_tenant_headers": build_user_headers("tenant-2", "MasterTenant"),
    "qi_headers": build_user_headers("qi-2", "QualifiedIntermediary"),
    "admin_headers": build_user_headers("admin-2", "PlatformAdmin"),
}


def make_investor_headers(user_id: str) -> dict:
    """For the Investor role, whose `X-User-ID` equals `Investor.id`.

    Pass the actual investor's `id` whenever the call is ownership-gated
    (rescinding a subscription, recording an exit consent).
    """
    return build_user_headers(user_id, "Investor")


def make_sponsor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SponsorPrincipal")


def make_compliance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_trustee_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Trustee")


def make_master_tenant_headers(user_id: str) -> dict:
    """For the MasterTenant role. Rent postings and master-tenant funding
    require this `X-User-ID` to equal the executed lease's
    `master_tenant_user_id`.
    """
    return build_user_headers(user_id, "MasterTenant")


def make_qi_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualifiedIntermediary")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


ROLE_HEADER_BUILDERS = {
    "SponsorPrincipal": make_sponsor_headers,
    "ComplianceOfficer": make_compliance_headers,
    "Trustee": make_trustee_headers,
    "Investor": make_investor_headers,
    "MasterTenant": make_master_tenant_headers,
    "QualifiedIntermediary": make_qi_headers,
    "PlatformAdmin": make_admin_headers,
}
