"""Pre-built role headers for every role the PRD declares (§2.1).

`X-User-ID` semantics differ by role. For the five operator roles it is an opaque
identifier that is never compared against any entity id, so a shared constant is
safe. For `SalesRepresentative` it is the id of the acting representative record,
so ownership-gated calls must use ``make_sales_representative_headers(rep_id)``
with the real representative id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers reused across the suite. The two ComplianceOfficer ids and
# the several ContractAdministrator ids exist because the two segregation-of-duty
# prohibitions compare one operator identifier against another.
USER_IDS = {
    "marketing_manager": "mm-primary",
    "gallery_manager": "gm-primary",
    "officer_alpha": "officer-alpha",
    "officer_bravo": "officer-bravo",
    "admin_intake": "admin-intake",
    "admin_adjudicator": "admin-adjudicator",
    "admin_disburser": "admin-disburser",
    "admin_funder": "admin-funder",
    "admin_underwriter": "admin-underwriter",
    "platform_admin": "platform-ops",
    "representative_placeholder": "rep-any",
}


TEST_USERS = {
    "marketing_manager_headers": build_user_headers(
        USER_IDS["marketing_manager"], "MarketingManager"
    ),
    "gallery_manager_headers": build_user_headers(
        USER_IDS["gallery_manager"], "GalleryManager"
    ),
    # Placeholder only — never use for an ownership-gated representative call.
    "sales_representative_headers": build_user_headers(
        USER_IDS["representative_placeholder"], "SalesRepresentative"
    ),
    "compliance_officer_headers": build_user_headers(
        USER_IDS["officer_alpha"], "ComplianceOfficer"
    ),
    "compliance_officer_bravo_headers": build_user_headers(
        USER_IDS["officer_bravo"], "ComplianceOfficer"
    ),
    "contract_administrator_headers": build_user_headers(
        USER_IDS["admin_intake"], "ContractAdministrator"
    ),
    "contract_admin_adjudicator_headers": build_user_headers(
        USER_IDS["admin_adjudicator"], "ContractAdministrator"
    ),
    "contract_admin_disburser_headers": build_user_headers(
        USER_IDS["admin_disburser"], "ContractAdministrator"
    ),
    "contract_admin_funder_headers": build_user_headers(
        USER_IDS["admin_funder"], "ContractAdministrator"
    ),
    "contract_admin_underwriter_headers": build_user_headers(
        USER_IDS["admin_underwriter"], "ContractAdministrator"
    ),
    "platform_admin_headers": build_user_headers(
        USER_IDS["platform_admin"], "PlatformAdmin"
    ),
}


def make_sales_representative_headers(rep_id: str) -> dict:
    """Headers for the SalesRepresentative role.

    Pass the real `SalesRepresentative.id`: ownership checks compare a booking's
    `assigned_rep_id`, a presentation's `rep_id` and an agreement's `rep_id`
    against `X-User-ID`.
    """
    return build_user_headers(rep_id, "SalesRepresentative")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Headers for a specific ComplianceOfficer operator identifier."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_contract_administrator_headers(user_id: str) -> dict:
    """Headers for a specific ContractAdministrator operator identifier."""
    return build_user_headers(user_id, "ContractAdministrator")


def make_marketing_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MarketingManager")


def make_gallery_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GalleryManager")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
