"""Pre-built role headers for every role in the PRD.

Six of the seven roles carry an opaque operator identifier that the server records
but never compares to an entity id, so a shared constant is always correct for them.
The exception is `BpoVendor`, whose `X-User-ID` is the id of the vendor record
itself: ownership-gated vendor calls MUST use `make_bpo_vendor_headers(vendor_id)`.
The junior lien holder's identifier is opaque but is compared to the
`holder_user_id` recorded on the lien, so lien fixtures thread it explicitly.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used consistently across the suite.
NEGOTIATOR_ID = "neg-001"
LISTING_AGENT_ID = "la-200"
# Two distinct analysts: sa-100 orders valuations and issues letters, so the
# segregation-of-duties bars make sa-101 the one who adjudicates and decides.
SERVICER_ANALYST_ID = "sa-100"
SECOND_ANALYST_ID = "sa-101"
JUNIOR_LIEN_HOLDER_ID = "jlh-700"
OTHER_LIEN_HOLDER_ID = "jlh-999"
MI_UNDERWRITER_ID = "miu-800"
PLATFORM_ADMIN_ID = "adm-900"

TEST_USERS = {
    "negotiator_headers": build_user_headers(NEGOTIATOR_ID, "Negotiator"),
    "listing_agent_headers": build_user_headers(LISTING_AGENT_ID, "ListingAgent"),
    "servicer_analyst_headers": build_user_headers(SERVICER_ANALYST_ID, "ServicerAnalyst"),
    "second_analyst_headers": build_user_headers(SECOND_ANALYST_ID, "ServicerAnalyst"),
    "junior_lien_holder_headers": build_user_headers(JUNIOR_LIEN_HOLDER_ID, "JuniorLienHolder"),
    "other_lien_holder_headers": build_user_headers(OTHER_LIEN_HOLDER_ID, "JuniorLienHolder"),
    "mi_underwriter_headers": build_user_headers(MI_UNDERWRITER_ID, "MiUnderwriter"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
}


def make_bpo_vendor_headers(vendor_id: str) -> dict:
    """Headers for a BpoVendor. `X-User-ID` must be the vendor record's own id,
    because ownership checks compare it to the valuation's `vendor_id`."""
    return build_user_headers(vendor_id, "BpoVendor")


def make_negotiator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Negotiator")


def make_listing_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ListingAgent")


def make_servicer_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServicerAnalyst")


def make_junior_lien_holder_headers(user_id: str) -> dict:
    """Headers for a JuniorLienHolder. `X-User-ID` must equal the
    `holder_user_id` recorded on the lien being acted upon."""
    return build_user_headers(user_id, "JuniorLienHolder")


def make_mi_underwriter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MiUnderwriter")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
