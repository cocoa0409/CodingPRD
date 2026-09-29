"""Pre-built role headers for every role in the PRD.

Four roles carry opaque operator identities: `EditorInChief`, `ManagingEditor`,
`SalesDirector` and `RoyaltyAccountant`. For those, the shared constants below
are the canonical form.

Two roles are entity-backed: when `X-User-Role` is `Creator`, `X-User-ID` is the
`id` of the acting `Creator` record; when it is `Retailer`, `X-User-ID` is the
`id` of the acting `Retailer` record. Ownership-gated calls MUST therefore use
`make_creator_headers(creator["id"])` / `make_retailer_headers(retailer["id"])`
rather than the shared constants.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.
EDITOR_IN_CHIEF_USER_ID = "eic-1"
MANAGING_EDITOR_USER_ID = "med-1"
SALES_DIRECTOR_USER_ID = "sd-1"
ROYALTY_ACCOUNTANT_USER_ID = "acct-1"
ROYALTY_ACCOUNTANT_2_USER_ID = "acct-2"

TEST_USERS = {
    # opaque roles — the shared constant is the canonical form.
    "editor_in_chief_headers": build_user_headers(
        EDITOR_IN_CHIEF_USER_ID, "EditorInChief"
    ),
    "managing_editor_headers": build_user_headers(
        MANAGING_EDITOR_USER_ID, "ManagingEditor"
    ),
    "sales_director_headers": build_user_headers(
        SALES_DIRECTOR_USER_ID, "SalesDirector"
    ),
    "royalty_accountant_headers": build_user_headers(
        ROYALTY_ACCOUNTANT_USER_ID, "RoyaltyAccountant"
    ),
    "royalty_accountant_2_headers": build_user_headers(
        ROYALTY_ACCOUNTANT_2_USER_ID, "RoyaltyAccountant"
    ),
    # entity-backed roles — fallback for tests that never exercise ownership
    # (missing-resource, malformed-payload and role-authorization tests).
    "creator_headers": build_user_headers("test-creator-1", "Creator"),
    "retailer_headers": build_user_headers("test-retailer-1", "Retailer"),
}


def make_creator_headers(user_id: str) -> dict:
    """Headers for the `Creator` role, whose `X-User-ID` is a `Creator.id`.

    Pass the real creator's `id` whenever the call is ownership-gated:
    countering an assignment, accepting an assignment, starting a production
    stage or delivering a production stage.
    """
    return build_user_headers(user_id, "Creator")


def make_retailer_headers(user_id: str) -> dict:
    """Headers for the `Retailer` role, whose `X-User-ID` is a `Retailer.id`.

    Pass the real retailer's `id` whenever the call is ownership-gated:
    drafting, submitting, adjusting or cancelling a retailer order.
    """
    return build_user_headers(user_id, "Retailer")


def make_editor_in_chief_headers(user_id: str) -> dict:
    """Headers for a specific `EditorInChief` operator identifier."""
    return build_user_headers(user_id, "EditorInChief")


def make_managing_editor_headers(user_id: str) -> dict:
    """Headers for a specific `ManagingEditor` operator identifier."""
    return build_user_headers(user_id, "ManagingEditor")


def make_sales_director_headers(user_id: str) -> dict:
    """Headers for a specific `SalesDirector` operator identifier."""
    return build_user_headers(user_id, "SalesDirector")


def make_royalty_accountant_headers(user_id: str) -> dict:
    """Headers for a specific `RoyaltyAccountant` operator identifier.

    Statement payment compares the acting `X-User-ID` against the recorded
    `issued_by_user_id`, so tests that exercise that guard need two distinct
    accountant identifiers.
    """
    return build_user_headers(user_id, "RoyaltyAccountant")


ALL_ROLE_NAMES = (
    "EditorInChief",
    "ManagingEditor",
    "SalesDirector",
    "RoyaltyAccountant",
    "Creator",
    "Retailer",
)
