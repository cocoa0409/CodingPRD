"""Corner-case coverage of the two universal rejection gates that sit in front of
every endpoint of the dynamic-discounting contract.

The rejection ladder of PRD §2.7 opens with authentication at position 1 and
request shape at position 3, and both are declared to run before anything else
is examined — before role authorisation, before any path-parameter lookup and
before any body foreign key is resolved. The two tests below prove exactly that
ordering by addressing rows that *do* exist while presenting broken identity
headers, and by submitting a body that is malformed *and* names a foreign key
that resolves to nothing.

The harness restarts the API server before every test, so each test builds all
of its own state from an empty database using the shared builders in
``test_helpers.fixtures``.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import assert_buyer, assert_program
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import (
    PLATFORM_OPS_HEADERS,
    make_buyer_admin_headers,
    make_headers,
    headers_without_role,
    headers_without_user_id,
)


def test_unauthenticated_request_without_valid_identity_headers_is_rejected():
    """A live Buyer row is addressed four times over, so the addressed path
    parameter always resolves and the outcome can only come from the identity
    gate: omitting both headers, omitting ``X-User-ID``, sending an empty
    ``X-User-ID`` and naming a role outside the five recognised names must each
    answer 401 ERR_UNAUTHENTICATED — never the 403 of the role gate and never a
    404 — and the Buyer row must be left untouched.

    PRD §2.1: "Every request to this API carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which that principal is acting."
    PRD §2.1: "If either header is missing, empty, or if `X-User-Role` is not exactly one of the five recognised role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."
    PRD §2.7: "1. **Authentication** — `X-User-Role` is present and is one of `BuyerAdmin`, `BuyerTreasury`, `Supplier`, `Funder`, `PlatformOps`, and `X-User-ID` is present and non-empty."
    Design: Corner/errors/unauthenticated_request_without_valid_identity_headers_is_rejected
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer(
        legal_name="Auth Gate Buyer", credit_limit_cents=100_000_000
    )
    buyer_id = buyer["id"]
    assert buyer["status"] == "ACTIVE", (
        "a freshly registered buyer opens in ACTIVE, got {!r}".format(buyer["status"])
    )
    assert buyer["version"] == 1, (
        "a freshly registered buyer starts at version 1, got {}".format(
            buyer["version"]
        )
    )

    # 1. No identity headers at all.
    validate_error(
        api_client.get_buyer(buyer_id, {"Content-Type": "application/json"}),
        ERR_UNAUTHENTICATED,
        401,
    )

    # 2. X-User-Role present, X-User-ID absent: a present role does not
    #    compensate for a missing subject.
    validate_error(
        api_client.get_buyer(buyer_id, headers_without_user_id("BuyerAdmin")),
        ERR_UNAUTHENTICATED,
        401,
    )

    # 3. X-User-ID present, X-User-Role absent.
    validate_error(
        api_client.get_buyer(buyer_id, headers_without_role(buyer_id)),
        ERR_UNAUTHENTICATED,
        401,
    )

    # 4. X-User-Role present but empty X-User-ID: "missing, empty".
    validate_error(
        api_client.get_buyer(buyer_id, make_headers("BuyerAdmin", "")),
        ERR_UNAUTHENTICATED,
        401,
    )

    # 5. A role outside the five recognised names fails authentication, not
    #    authorisation: 401 ERR_UNAUTHENTICATED, not 403 ERR_UNAUTHORIZED.
    validate_error(
        api_client.get_buyer(buyer_id, make_headers("Auditor", buyer_id)),
        ERR_UNAUTHENTICATED,
        401,
    )

    # The five refusals wrote nothing at all.
    after = validate_success(api_client.get_buyer(buyer_id, PLATFORM_OPS_HEADERS), 200)
    assert_buyer(
        after,
        id=buyer_id,
        status="ACTIVE",
        version=1,
        credit_used_cents=0,
    )
    assert after["updated_at"] == buyer["updated_at"], (
        "a rejected unauthenticated read must not refresh updated_at: {!r} -> {!r}".format(
            buyer["updated_at"], after["updated_at"]
        )
    )


def test_invalid_request_shape_is_rejected_before_any_lookup():
    """Shape validation sits at position 3 of the rejection ladder and runs
    before any database lookup, so an auction-session request whose window is
    inverted *and* whose ``program_id`` resolves to no row answers 400
    ERR_INVALID_REQUEST rather than the 404 the unresolvable body foreign key at
    position 6 would otherwise produce. The same 400 covers a ``tax_id`` that is
    not exactly nine digits, a ``program_type`` outside its enum and a
    ``max_acceptable_apr_bps`` below its declared 200 floor — and none of the
    four refusals writes a row.

    PRD §2.7: "3. **Request shape** — every required body field is present, types are correct, enum values are within range, integers declared non-negative are non-negative, ISO 8601 timestamps parse, and every declared window has its start strictly before its end. This check runs before any database lookup. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    PRD §3.1: "Registration takes the buyer's registered `legal_name`, between 1 and 200 characters, its `tax_id`, which must be exactly nine digits and must be unique across all buyers — a collision is reported as a malformed request with `ERR_INVALID_REQUEST` — and its `credit_limit_cents`, the ceiling on the total of self-funded early payments the buyer may hold open, which must be zero or greater."
    PRD §3.1: "Every programme also carries `max_acceptable_apr_bps`, between 200 and 5000 basis points, as the upper bound on any rate named, countered or accepted."
    Design: Corner/errors/invalid_request_shape_is_rejected_before_any_lookup
    """
    fx.set_clock(DEFAULT_CLOCK_UTC)
    buyer = fx.new_buyer(
        legal_name="Shape Gate Buyer", credit_limit_cents=100_000_000
    )
    buyer_id = buyer["id"]
    admin = make_buyer_admin_headers(buyer_id)
    program = fx.new_program(buyer_id, name="Shape Gate Programme")
    assert_program(program, status="DRAFT", version=1)

    # 1. Inverted window AND an unresolvable program_id: the shape gate at
    #    position 3 outranks the body foreign-key gate at position 6.
    validate_error(
        api_client.create_session(
            f.session_payload(
                NON_EXISTENT_UUID,
                opens_at="2026-08-20T00:00:00Z",
                closes_at="2026-08-10T00:00:00Z",
            ),
            admin,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    # 2. tax_id of five digits where exactly nine are declared.
    validate_error(
        api_client.create_buyer(
            f.buyer_payload(
                legal_name="Short Tax Id Buyer",
                tax_id="12345",
                credit_limit_cents=100_000,
            ),
            PLATFORM_OPS_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    # 3. program_type outside {SUPPLIER_NAMED, FIXED_RATE}.
    validate_error(
        api_client.create_program(
            f.minimal_program_payload(
                buyer_id, name="Mystery Type Programme", program_type="MYSTERY"
            ),
            admin,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    # 4. max_acceptable_apr_bps of 100, below the declared 200 floor.
    validate_error(
        api_client.create_program(
            f.minimal_program_payload(
                buyer_id,
                name="Too Cheap Programme",
                max_acceptable_apr_bps=100,
            ),
            admin,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    # None of the four refusals persisted anything.
    programs, programs_meta = validate_paginated(
        api_client.list_buyer_programs(buyer_id, admin)
    )
    assert programs_meta["total_count"] == 1, (
        "the two refused programme creates must not have persisted a row; "
        "expected total_count 1, got {}".format(programs_meta["total_count"])
    )
    assert [p["id"] for p in programs] == [program["id"]], (
        "only the one valid DRAFT programme may exist, got {!r}".format(
            [p["id"] for p in programs]
        )
    )

    sessions, sessions_meta = validate_paginated(
        api_client.list_program_sessions(program["id"], admin)
    )
    assert sessions_meta["total_count"] == 0, (
        "the refused auction-session create must not have persisted a row; "
        "expected total_count 0, got {}".format(sessions_meta["total_count"])
    )
    assert sessions == [], "no auction session may exist, got {!r}".format(sessions)
