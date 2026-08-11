"""Pre-built identity headers for every role the PRD declares.

Five of the seven roles present an opaque operator identifier that the server
never compares to any stored row.  Two roles are entity-backed and MUST be
built per instance:

  * ``Technician``       -- ``X-User-ID`` is the acting technician's own ``id``
  * ``CustomerContact``  -- ``X-User-ID`` is the acting account's own ``id``

Falling back to a shared constant for either of those two makes every
ownership check reject every request.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque compliance-officer identifiers.  Two distinct officers are needed so
# the segregation-of-duties rule on a confirmatory result can be satisfied or
# violated on purpose.
OFFICER_ALPHA = "officer-alpha"
OFFICER_BETA = "officer-beta"
OFFICER_BRAVO = "officer-bravo"


TEST_USERS = {
    # Opaque roles: the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("admin-primary", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("dispatcher-primary", "Dispatcher"),
    "estimator_headers": build_user_headers("estimator-primary", "Estimator"),
    "billing_clerk_headers": build_user_headers("billing-primary", "BillingClerk"),
    "compliance_officer_headers": build_user_headers(OFFICER_ALPHA, "ComplianceOfficer"),
    "compliance_officer_beta_headers": build_user_headers(
        OFFICER_BETA, "ComplianceOfficer"
    ),
    "compliance_officer_bravo_headers": build_user_headers(
        OFFICER_BRAVO, "ComplianceOfficer"
    ),
    # Entity-backed roles: these shared constants are only safe on calls that
    # carry no ownership gate (401/403-on-role probes, 404-on-missing-row).
    "technician_headers": build_user_headers("technician-unbound", "Technician"),
    "customer_contact_headers": build_user_headers(
        "customer-unbound", "CustomerContact"
    ),
    # A role name that is not one of the seven declared roles.
    "anonymous_headers": build_user_headers("nobody", "Anonymous"),
}


def make_technician_headers(technician_id: str) -> dict:
    """For the Technician role.  Pass the acting technician row's own id."""
    return build_user_headers(technician_id, "Technician")


def make_customer_headers(account_id: str) -> dict:
    """For the CustomerContact role.  Pass the acting account's own id."""
    return build_user_headers(account_id, "CustomerContact")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For the ComplianceOfficer role.  The id is recorded but never resolved."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str = "admin-primary") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_dispatcher_headers(user_id: str = "dispatcher-primary") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_estimator_headers(user_id: str = "estimator-primary") -> dict:
    return build_user_headers(user_id, "Estimator")


def make_billing_clerk_headers(user_id: str = "billing-primary") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def headers_for(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary role name and identifier."""
    return build_user_headers(user_id, role)


def headers_without(header_name: str, base: dict) -> dict:
    """Copy ``base`` with one header removed."""
    stripped = dict(base)
    stripped.pop(header_name, None)
    return stripped
