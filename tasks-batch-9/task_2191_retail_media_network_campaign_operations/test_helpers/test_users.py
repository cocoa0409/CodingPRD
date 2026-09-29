"""Header builders for the eight roles of the retail media network API.

Every request must carry `X-User-ID` and `X-User-Role`. Seven of the eight roles use
an opaque operator identifier that the server never compares to any row's `id`, so a
fixed constant is safe for them.

`AdvertiserUser` is the one exception: its `X-User-ID` *is* the `id` of the acting
advertiser, and ownership checks compare the target resource's advertiser reference to
that header. There is therefore no usable constant for an advertiser seat — call
`make_advertiser_user_headers()` with the id of the advertiser created by the fixture
under test.

Five approval chains forbid one operator from standing on both sides, so the operator
constants below are deliberately all distinct. Where a single role must act twice on
opposite sides of a chain, use the numbered alternates (for example
`SECOND_NETWORK_ADMIN`).
"""

from prd_bench_local_runner.testing import build_user_headers

# --- Role names ------------------------------------------------------------

ROLE_NETWORK_ADMIN = "NetworkAdmin"
ROLE_ACCOUNT_MANAGER = "AccountManager"
ROLE_ADVERTISER_USER = "AdvertiserUser"
ROLE_CREDIT_ANALYST = "CreditAnalyst"
ROLE_MEASUREMENT_ANALYST = "MeasurementAnalyst"
ROLE_BILLING_OPS = "BillingOps"
ROLE_CATALOG_OPS = "CatalogOps"
ROLE_AUCTION_SERVICE = "AuctionService"

ALL_ROLES = (
    ROLE_NETWORK_ADMIN,
    ROLE_ACCOUNT_MANAGER,
    ROLE_ADVERTISER_USER,
    ROLE_CREDIT_ANALYST,
    ROLE_MEASUREMENT_ANALYST,
    ROLE_BILLING_OPS,
    ROLE_CATALOG_OPS,
    ROLE_AUCTION_SERVICE,
)


# --- Opaque operator identifiers ------------------------------------------

NETWORK_ADMIN_USER_ID = "na_001"
SECOND_NETWORK_ADMIN_USER_ID = "na_002"
ACCOUNT_MANAGER_USER_ID = "am_001"
SECOND_ACCOUNT_MANAGER_USER_ID = "am_002"
CREDIT_ANALYST_USER_ID = "ca_001"
SECOND_CREDIT_ANALYST_USER_ID = "ca_002"
MEASUREMENT_ANALYST_USER_ID = "ma_001"
SECOND_MEASUREMENT_ANALYST_USER_ID = "ma_002"
BILLING_OPS_USER_ID = "bo_001"
SECOND_BILLING_OPS_USER_ID = "bo_002"
CATALOG_OPS_USER_ID = "co_001"
SECOND_CATALOG_OPS_USER_ID = "co_002"
AUCTION_SERVICE_USER_ID = "auc_001"


# --- Ready-made header dicts ---------------------------------------------

NETWORK_ADMIN = build_user_headers(NETWORK_ADMIN_USER_ID, ROLE_NETWORK_ADMIN)
SECOND_NETWORK_ADMIN = build_user_headers(
    SECOND_NETWORK_ADMIN_USER_ID, ROLE_NETWORK_ADMIN
)
ACCOUNT_MANAGER = build_user_headers(ACCOUNT_MANAGER_USER_ID, ROLE_ACCOUNT_MANAGER)
SECOND_ACCOUNT_MANAGER = build_user_headers(
    SECOND_ACCOUNT_MANAGER_USER_ID, ROLE_ACCOUNT_MANAGER
)
CREDIT_ANALYST = build_user_headers(CREDIT_ANALYST_USER_ID, ROLE_CREDIT_ANALYST)
SECOND_CREDIT_ANALYST = build_user_headers(
    SECOND_CREDIT_ANALYST_USER_ID, ROLE_CREDIT_ANALYST
)
MEASUREMENT_ANALYST = build_user_headers(
    MEASUREMENT_ANALYST_USER_ID, ROLE_MEASUREMENT_ANALYST
)
SECOND_MEASUREMENT_ANALYST = build_user_headers(
    SECOND_MEASUREMENT_ANALYST_USER_ID, ROLE_MEASUREMENT_ANALYST
)
BILLING_OPS = build_user_headers(BILLING_OPS_USER_ID, ROLE_BILLING_OPS)
SECOND_BILLING_OPS = build_user_headers(SECOND_BILLING_OPS_USER_ID, ROLE_BILLING_OPS)
CATALOG_OPS = build_user_headers(CATALOG_OPS_USER_ID, ROLE_CATALOG_OPS)
SECOND_CATALOG_OPS = build_user_headers(SECOND_CATALOG_OPS_USER_ID, ROLE_CATALOG_OPS)
AUCTION_SERVICE = build_user_headers(AUCTION_SERVICE_USER_ID, ROLE_AUCTION_SERVICE)

TEST_USERS = {
    ROLE_NETWORK_ADMIN: NETWORK_ADMIN,
    ROLE_ACCOUNT_MANAGER: ACCOUNT_MANAGER,
    ROLE_CREDIT_ANALYST: CREDIT_ANALYST,
    ROLE_MEASUREMENT_ANALYST: MEASUREMENT_ANALYST,
    ROLE_BILLING_OPS: BILLING_OPS,
    ROLE_CATALOG_OPS: CATALOG_OPS,
    ROLE_AUCTION_SERVICE: AUCTION_SERVICE,
}

# Opaque operator id per role, for tests that need to assert a stamped
# *_by_user_id field or to pick a colliding / non-colliding actor.
OPERATOR_USER_IDS = {
    ROLE_NETWORK_ADMIN: NETWORK_ADMIN_USER_ID,
    ROLE_ACCOUNT_MANAGER: ACCOUNT_MANAGER_USER_ID,
    ROLE_CREDIT_ANALYST: CREDIT_ANALYST_USER_ID,
    ROLE_MEASUREMENT_ANALYST: MEASUREMENT_ANALYST_USER_ID,
    ROLE_BILLING_OPS: BILLING_OPS_USER_ID,
    ROLE_CATALOG_OPS: CATALOG_OPS_USER_ID,
    ROLE_AUCTION_SERVICE: AUCTION_SERVICE_USER_ID,
}


def make_advertiser_user_headers(advertiser_id: str) -> dict:
    """Build AdvertiserUser headers for the seat that owns `advertiser_id`.

    `X-User-ID` for an AdvertiserUser is the acting advertiser's own `id`, so this
    must be called with the id of the advertiser the test created. Passing any other
    id makes the call a non-owner and earns ERR_NOT_RESOURCE_OWNER.
    """
    return build_user_headers(advertiser_id, ROLE_ADVERTISER_USER)


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary user id and role name."""
    return build_user_headers(user_id, role)
