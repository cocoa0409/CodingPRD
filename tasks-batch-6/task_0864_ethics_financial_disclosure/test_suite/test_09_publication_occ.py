"""Publication optimistic-concurrency control on Statement.version.

Queue B: publish_stale_statement_version_returns_412.
"""
from test_helpers import validate_error, setup_published_statement


def test_publish_stale_version_412(api, registrar_headers):
    """PRD 2.6: "If `expected_statement_version` does not equal the statement's current
    `version`, the publish is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 3.5: "it sets `public_status` to `PUBLISHED`, stamps `published_at` from the logical
    clock, and increments the statement's `version` by 1."

    Design: Corner/endpoints/publish_stale_statement_version_returns_412
    """
    ctx = setup_published_statement(category="SENIOR_STAFF")
    # The first publish already bumped version; re-publishing with the pre-publish
    # version is now stale.
    res = api.publish_statement(
        ctx["statement"]["id"],
        {"expected_statement_version": ctx["pre_publish_version"]},
        registrar_headers)
    validate_error(res, "ERR_STALE_VERSION")
