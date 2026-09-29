"""Pre-built role headers for every role named in the PRD.

`Vendor` is the one role whose identity is an actual `Vendor` row: its
`X-User-ID` must be the supplier's `id`, or every ownership comparison rejects
the request with `ERR_VENDOR_SCOPE_VIOLATION`.  Use
`make_vendor_headers(vendor_id)` for anything ownership-gated; the shared
`TEST_USERS["vendor_headers"]` constant is only safe for calls that never
resolve an owning supplier (missing-header and unknown-role probes).

`ComplianceOfficer` has two identities on purpose: the officer who adjudicates a
dispute must not be the operator recorded as the violation's
`detected_by_user_id`, and a violation may be filed by a `DCInspector` whose id
must differ from the adjudicating officer's.
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable operator identifiers for the opaque roles.
OFFICER_USER_ID = "co-1"
SECOND_OFFICER_USER_ID = "co-2"
INSPECTOR_USER_ID = "insp-1"
SECOND_INSPECTOR_USER_ID = "insp-2"
BUYER_USER_ID = "buyer-1"
ACCOUNTANT_USER_ID = "ap-1"

TEST_USERS = {
    "officer_headers": build_user_headers(OFFICER_USER_ID, "ComplianceOfficer"),
    "second_officer_headers": build_user_headers(
        SECOND_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "inspector_headers": build_user_headers(INSPECTOR_USER_ID, "DCInspector"),
    "second_inspector_headers": build_user_headers(
        SECOND_INSPECTOR_USER_ID, "DCInspector"
    ),
    "buyer_headers": build_user_headers(BUYER_USER_ID, "CategoryBuyer"),
    "accountant_headers": build_user_headers(ACCOUNTANT_USER_ID, "APAccountant"),
    # entity_backed role: fallback constant for non-ownership probes only.
    "vendor_headers": build_user_headers("vendor-user-1", "Vendor"),
}


def make_vendor_headers(vendor_id: str) -> dict:
    """Headers for one specific supplier.

    Pass the real `Vendor.id`; the programme resolves the acting supplier from
    `X-User-ID`.
    """
    return build_user_headers(vendor_id, "Vendor")


def make_officer_headers(user_id: str = OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_inspector_headers(user_id: str = INSPECTOR_USER_ID) -> dict:
    return build_user_headers(user_id, "DCInspector")


def make_buyer_headers(user_id: str = BUYER_USER_ID) -> dict:
    return build_user_headers(user_id, "CategoryBuyer")


def make_accountant_headers(user_id: str = ACCOUNTANT_USER_ID) -> dict:
    return build_user_headers(user_id, "APAccountant")
