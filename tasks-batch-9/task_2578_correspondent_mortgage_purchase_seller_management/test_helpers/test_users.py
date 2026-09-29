"""Pre-built request headers for each role.

Five of the six roles are opaque: any non-empty `X-User-ID` identifies them.
`SellerUser` is different — the platform interprets its `X-User-ID` as the
identifier of the Seller the caller belongs to, so seller headers must always
be built from a real seller id with `make_seller_user_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Opaque-identity users ──────────────────────────────────────────────────

PLATFORM_ADMIN_ID = "u-adm-1"
COUNTERPARTY_ANALYST_ID = "u-ca-1"
COUNTERPARTY_ANALYST_ALT_ID = "u-ca-2"
QC_REVIEWER_ID = "u-qc-1"
QC_REVIEWER_ALT_ID = "u-qc-2"
LOCK_DESK_TRADER_ID = "u-ld-1"
PURCHASE_REVIEWER_ID = "u-pr-1"
PURCHASE_REVIEWER_ALT_ID = "u-pr-2"
PURCHASE_REVIEWER_THIRD_ID = "u-pr-3"

TEST_USERS = {
    "platform_admin": build_user_headers(PLATFORM_ADMIN_ID, UserRole.PLATFORM_ADMIN),
    "counterparty_analyst": build_user_headers(
        COUNTERPARTY_ANALYST_ID, UserRole.COUNTERPARTY_ANALYST
    ),
    "counterparty_analyst_alt": build_user_headers(
        COUNTERPARTY_ANALYST_ALT_ID, UserRole.COUNTERPARTY_ANALYST
    ),
    "qc_reviewer": build_user_headers(QC_REVIEWER_ID, UserRole.QC_REVIEWER),
    "qc_reviewer_alt": build_user_headers(QC_REVIEWER_ALT_ID, UserRole.QC_REVIEWER),
    "lock_desk_trader": build_user_headers(
        LOCK_DESK_TRADER_ID, UserRole.LOCK_DESK_TRADER
    ),
    "purchase_reviewer": build_user_headers(
        PURCHASE_REVIEWER_ID, UserRole.PURCHASE_REVIEWER
    ),
    "purchase_reviewer_alt": build_user_headers(
        PURCHASE_REVIEWER_ALT_ID, UserRole.PURCHASE_REVIEWER
    ),
    "purchase_reviewer_third": build_user_headers(
        PURCHASE_REVIEWER_THIRD_ID, UserRole.PURCHASE_REVIEWER
    ),
}

ADMIN = TEST_USERS["platform_admin"]
ANALYST = TEST_USERS["counterparty_analyst"]
ANALYST_ALT = TEST_USERS["counterparty_analyst_alt"]
QC = TEST_USERS["qc_reviewer"]
QC_ALT = TEST_USERS["qc_reviewer_alt"]
TRADER = TEST_USERS["lock_desk_trader"]
REVIEWER = TEST_USERS["purchase_reviewer"]
REVIEWER_ALT = TEST_USERS["purchase_reviewer_alt"]
REVIEWER_THIRD = TEST_USERS["purchase_reviewer_third"]


# ─── Per-role header builders ───────────────────────────────────────────────


def make_seller_user_headers(seller_id: str) -> dict:
    """Headers for a seller employee acting on behalf of `seller_id`."""
    return build_user_headers(seller_id, UserRole.SELLER_USER)


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN)


def make_counterparty_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.COUNTERPARTY_ANALYST)


def make_qc_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.QC_REVIEWER)


def make_lock_desk_trader_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.LOCK_DESK_TRADER)


def make_purchase_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PURCHASE_REVIEWER)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user id / role string pair."""
    return build_user_headers(user_id, role)


# ─── Deliberately malformed identity headers ────────────────────────────────


def headers_without_role(user_id: str) -> dict:
    """Headers carrying a user id but no role header at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> dict:
    """Headers carrying a role but no user id header at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str) -> dict:
    """Headers whose role header is present but an empty string."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_empty_user_id(role: str) -> dict:
    """Headers whose user id header is present but an empty string."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }
