"""The two header rules in order, and one envelope shape across five status codes.

Nothing here is about a business rule. The first test proves the header ladder is
separable and ordered, and that the clock setter alone escapes it. The second walks 400,
403, 404, 409 and 422 in one scenario and shows the failure envelope never changes shape
and never leaves a row behind.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_DUPLICATE_MARKET_CODE,
    ERR_HOME_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ROLE,
    ERR_SLOT_IN_PAST,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_page_meta,
    failed,
    ok,
    page,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    CLOCK_AUG_02,
)
from test_helpers.test_users import headers_without_user_id, make_headers

UNKNOWN_ROLE = "PropertyOverlord"
MISSING_HOME_ID = "00000000-0000-0000-0000-000000000000"


def _has_message(error):
    """Every refusal carries a human-readable ``message`` (PRD SS2.2)."""
    assert isinstance(error.get("message"), str) and error["message"].strip(), (
        "expected a non-empty message in the error envelope, got {!r}".format(error)
    )
    return error


def test_a_bad_role_answers_before_a_missing_principal_and_the_clock_answers_neither(api):
    """Role first, principal second, both bad reports the role -- and the dial still turns.

    PRD SS2.1: "If `X-User-Role` is absent, or carries any value outside that list of twelve, the
    request is rejected with `ERR_INVALID_ROLE` (HTTP 400). If `X-User-ID` is absent or is an empty
    string, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the single exception is
    the logical-clock setter, which is exempt from the `X-User-ID` requirement."  The order of the
    two is fixed by PRD SS2.7: "**Rank 20 -- unrecognised role.** `ERR_INVALID_ROLE` (400), on every
    endpoint" precedes "**Rank 30 -- missing principal.** `ERR_UNAUTHENTICATED` (401), on every
    endpoint except the logical-clock setter", and "**Evaluation stops at the first violated rule,
    and only that rule's error is reported.**"  The exemption is PRD SS3.1's: "a `System` caller may
    advance or rewind the logical clock to a supplied `current_utc` instant, and any role may read
    the clock's present value. This is the only operation in the system exempt from the `X-User-ID`
    requirement."  Every refusal carries the PRD SS2.2 envelope: "`response_type`" is "error" and
    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/header_failures_report_invalid_role_before_unauthenticated
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)

    unknown_role = make_headers("admin-1", UNKNOWN_ROLE)
    _has_message(failed(api.get_market(market["id"], unknown_role), ERR_INVALID_ROLE))
    _has_message(
        failed(
            api.get_market(market["id"], headers_without_user_id("PortfolioAdmin")),
            ERR_UNAUTHENTICATED,
        )
    )
    _has_message(
        failed(
            api.get_market(market["id"], headers_without_user_id(UNKNOWN_ROLE)),
            ERR_INVALID_ROLE,
        )
    )

    ok(api.set_clock(f.clock_payload(CLOCK_AUG_02), headers_without_user_id("System")))
    assert ok(api.get_clock(x.ADMIN))["current_utc"] == CLOCK_AUG_02

    readable = ok(api.get_market(market["id"], x.ADMIN))
    assert readable["id"] == market["id"]
    assert_fields(readable, code="ATL")


def test_five_refusals_five_status_codes_one_envelope_and_no_rows_written(api):
    """A missing field, a forbidden role, an unknown id, a duplicate code and a stale window.

    PRD SS2.2 fixes the shape of all five: "All error API responses (4xx status codes) follow this
    standard envelope format", whose `response_type` is "error" and whose `data` carries an
    "`error_id` ... a unique, machine-readable string that identifies the specific error" and a
    "`message` ... human-readable explanation of what went wrong."  The five classes are PRD SS5's
    own rows -- `ERR_INVALID_REQUEST` (400), `ERR_UNAUTHORIZED` (403), `ERR_HOME_NOT_FOUND` (404),
    `ERR_DUPLICATE_MARKET_CODE` (409) and `ERR_SLOT_IN_PAST` (422) -- and their triggers are PRD
    SS2.7's: "**Rank 10 -- malformed payload.** A required input field is absent", "**Rank 40 --
    role not permitted.** `ERR_UNAUTHORIZED` (403), on every endpoint", "**Rank 54 -- unknown
    home.** `ERR_HOME_NOT_FOUND` (404)", "**Rank 452 -- showing window in the past.**
    `ERR_SLOT_IN_PAST` (422) on showing-slot creation" and PRD SS3.1's market rule: "A second
    registration reusing an existing `code` is refused with `ERR_DUPLICATE_MARKET_CODE`."  Only
    `PortfolioAdmin` may register a market at all -- PRD SS2.1: "A `PortfolioAdmin` is the only role
    that may register markets and publish scope templates."  Nothing partial survives, PRD SS2.9:
    "if a guard rejects the operation, nothing at all is written, including the cascade targets",
    and the listing arithmetic is PRD SS2.3's "`total_count` (the number of rows matching the
    filters before pagination)".

    Design: Corner/errors/error_envelope_is_uniform_from_invalid_request_to_unauthorized_and_conflict
    """
    # The design index publishes the past window with an ``access_mode`` of ``SELF_SHOWING``.
    # PRD SS3.7 enumerates that field exhaustively -- "`SMART_LOCK`, `LOCKBOX` or
    # `AGENT_ESCORT`" -- so the window is published as ``SMART_LOCK`` instead; the refusal
    # under test is the past-window rule and the access mode is incidental to it.
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])

    _has_message(
        failed(
            api.create_market(f.dallas_market_payload(millage_bps=None), x.ADMIN),
            ERR_INVALID_REQUEST,
        )
    )
    _has_message(
        failed(api.create_market(f.dallas_market_payload(), x.AGENT), ERR_UNAUTHORIZED)
    )
    _has_message(failed(api.get_home(MISSING_HOME_ID, x.ADMIN), ERR_HOME_NOT_FOUND))
    _has_message(
        failed(
            api.create_market(
                f.dallas_market_payload(code="ATL", name="Atlanta Duplicate"), x.ADMIN
            ),
            ERR_DUPLICATE_MARKET_CODE,
        )
    )
    _has_message(
        failed(
            api.create_showing_slot(
                f.showing_slot_payload(
                    home["id"],
                    starts_at="2026-07-31T15:00:00Z",
                    ends_at="2026-07-31T15:30:00Z",
                ),
                x.AGENT,
            ),
            ERR_SLOT_IN_PAST,
        )
    )

    markets, market_meta = page(api.list_markets(x.ADMIN))
    assert_page_meta(market_meta, total_count=1)
    assert [row["id"] for row in markets] == [market["id"]]

    _, slot_meta = page(api.list_showing_slots(x.AGENT, {"home_id": home["id"]}))
    assert_page_meta(slot_meta, total_count=0)
