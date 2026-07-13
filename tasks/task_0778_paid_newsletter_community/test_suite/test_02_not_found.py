"""Resource-specific not-found errors (queue B — entities).

Each endpoint whose path names a resource returns that resource's specific
404 error when the identifier does not resolve (PRD §2.10). Written as one
function per corner instance so each carries its own Design tag.
"""
from test_helpers import validate_error, ApiErrorId, NON_EXISTENT_UUID, TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
CREATOR = TEST_USERS["creator_headers"]
MEMBER = TEST_USERS["member_headers"]

_NOT_FOUND_CITATION = (
    'PRD §2.10: "The not-found errors are resource-specific: '
    "ERR_PUBLICATION_NOT_FOUND, ERR_TIER_NOT_FOUND, ERR_MEMBER_NOT_FOUND, "
    "ERR_SUBSCRIPTION_NOT_FOUND, ERR_INVOICE_NOT_FOUND, ERR_POST_NOT_FOUND, "
    "ERR_EVENT_NOT_FOUND, ERR_REGISTRATION_NOT_FOUND, ERR_COMMENT_NOT_FOUND, "
    'and ERR_PAYOUT_NOT_FOUND."'
)


def test_get_member_nonexistent_not_found(api):
    """PRD §2.10: "The not-found errors are resource-specific: ...
    ERR_MEMBER_NOT_FOUND ..."

    Design: Corner/entities/get_member_nonexistent_not_found
    """
    resp = api.get_member(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


def test_get_publication_nonexistent_not_found(api):
    """PRD §2.10: "The not-found errors are resource-specific:
    ERR_PUBLICATION_NOT_FOUND ..."

    Design: Corner/entities/get_publication_nonexistent_not_found
    """
    resp = api.get_publication(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PUBLICATION_NOT_FOUND.value)


def test_get_subscription_nonexistent_not_found(api):
    """PRD §2.10: "The not-found errors are resource-specific: ...
    ERR_SUBSCRIPTION_NOT_FOUND ..."

    Design: Corner/entities/get_subscription_nonexistent_not_found
    """
    resp = api.get_subscription(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value)


def test_settle_payout_nonexistent_not_found(api):
    """PRD §2.10: "The not-found errors are resource-specific: ...
    ERR_PAYOUT_NOT_FOUND."

    Design: Corner/entities/settle_payout_nonexistent_not_found
    """
    resp = api.settle_payout(NON_EXISTENT_UUID, {"outcome": "PAID"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_FOUND.value)


def test_moderate_comment_nonexistent_not_found(api):
    """PRD §2.10: "The not-found errors are resource-specific: ...
    ERR_COMMENT_NOT_FOUND ..."

    Design: Corner/entities/moderate_comment_nonexistent_not_found
    """
    resp = api.moderate_comment(NON_EXISTENT_UUID, {"decision": "APPROVE"}, CREATOR)
    validate_error(resp, ApiErrorId.ERR_COMMENT_NOT_FOUND.value)


def test_get_registration_nonexistent_not_found(api):
    """PRD §2.10: "The not-found errors are resource-specific: ...
    ERR_REGISTRATION_NOT_FOUND ..."

    Design: Corner/entities/get_registration_nonexistent_not_found
    """
    resp = api.get_registration(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value)


def test_register_nonexistent_event_not_found(api):
    """PRD §2.10: "The not-found errors are resource-specific: ...
    ERR_EVENT_NOT_FOUND ..."

    Design: Corner/entities/register_nonexistent_event_not_found
    """
    resp = api.create_registration(NON_EXISTENT_UUID, {}, MEMBER)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND.value)


def test_get_post_content_nonexistent_not_found(api):
    """PRD §2.10: "The not-found errors are resource-specific: ...
    ERR_POST_NOT_FOUND ..."

    Design: Corner/entities/get_post_content_nonexistent_not_found
    """
    resp = api.get_post_content(NON_EXISTENT_UUID, CREATOR)
    validate_error(resp, ApiErrorId.ERR_POST_NOT_FOUND.value)


def test_get_invoice_nonexistent_not_found(api):
    """PRD §2.10: "The not-found errors are resource-specific: ...
    ERR_INVOICE_NOT_FOUND ..."

    Design: Corner/entities/get_invoice_nonexistent_not_found
    """
    resp = api.get_invoice(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND.value)
