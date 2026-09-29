"""
The error surface: one not-found code per entity, the two distinct 401s that
guard the headers, the three shapes a malformed request can take, the refusal a
hard-closed period returns to a later statement, and the single envelope every
status code is poured into.
"""

import re

import pytest

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import NOT_FOUND_CODES, ApiErrorId
from test_helpers.constants import (
    CLOCK_EPOCH,
    MAX_LIMIT,
    PERIOD_AUG_END,
    PERIOD_HARD_CLOSED,
    PROGRAM_DRAFT,
    UNKNOWN_ID,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_HEADERS,
    EMPTY_ROLE_HEADERS,
    EMPTY_USER_ID_HEADERS,
    MISSING_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    NO_AUTH_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    make_unknown_role_headers,
)
from test_helpers.types import (
    ENVELOPE_META_FIELDS,
    ENVELOPE_TOP_LEVEL_FIELDS,
    ERROR_ENVELOPE_FIELDS,
)

# The eleven single-resource reads, in the order the not-found catalogue lists
# their codes.
_DETAIL_READERS = (
    "get_program",
    "get_state_expiry_rule",
    "get_cohort",
    "get_member",
    "get_period",
    "get_agreement",
    "get_point_lot",
    "get_redemption",
    "get_estimate",
    "get_statement",
    "get_change_order",
)

# An api_request_timestamp is UTC with exactly three fractional digits.
_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(Z|\+00:00)$"
)

_UNKNOWN_ROLE_HEADERS = make_unknown_role_headers()

# The figures the reference August close persists: 1000 points at 1200
# millicents deferring 900, remeasured at 8200 basis points.
DEFERRED_REVENUE_CENTS = 900
REQUIRED_LIABILITY_CENTS = 984
CATCH_UP_ADJUSTMENT_CENTS = 84

DUPLICATE_COHORT_CODE = "C1"


def _auth_probes():
    """
    Every way the two identity headers can fail, paired with the 401 it earns:
    an absent or empty header on either side is a missing-headers failure, while
    a role name outside the five recognised ones is an unknown-role failure.
    """
    return {
        "no_headers_at_all_reading_a_known_programme": (
            lambda api, program_id: api.get_program(program_id, NO_AUTH_HEADERS),
            ApiErrorId.MISSING_AUTH_HEADERS.value,
        ),
        "no_headers_at_all_reading_an_unknown_programme": (
            lambda api, program_id: api.get_program(UNKNOWN_ID, NO_AUTH_HEADERS),
            ApiErrorId.MISSING_AUTH_HEADERS.value,
        ),
        "no_headers_at_all_posting_a_malformed_body": (
            lambda api, program_id: api.create_program({"name": ""}, NO_AUTH_HEADERS),
            ApiErrorId.MISSING_AUTH_HEADERS.value,
        ),
        "role_header_absent": (
            lambda api, program_id: api.get_program(program_id, MISSING_ROLE_HEADERS),
            ApiErrorId.MISSING_AUTH_HEADERS.value,
        ),
        "user_id_header_absent": (
            lambda api, program_id: api.get_program(program_id, MISSING_USER_ID_HEADERS),
            ApiErrorId.MISSING_AUTH_HEADERS.value,
        ),
        "role_header_empty": (
            lambda api, program_id: api.get_program(program_id, EMPTY_ROLE_HEADERS),
            ApiErrorId.MISSING_AUTH_HEADERS.value,
        ),
        "user_id_header_empty": (
            lambda api, program_id: api.get_program(program_id, EMPTY_USER_ID_HEADERS),
            ApiErrorId.MISSING_AUTH_HEADERS.value,
        ),
        "unrecognised_role_reading_a_known_programme": (
            lambda api, program_id: api.get_program(program_id, _UNKNOWN_ROLE_HEADERS),
            ApiErrorId.UNKNOWN_ROLE.value,
        ),
        "unrecognised_role_reading_an_unknown_programme": (
            lambda api, program_id: api.get_program(UNKNOWN_ID, _UNKNOWN_ROLE_HEADERS),
            ApiErrorId.UNKNOWN_ROLE.value,
        ),
        "unrecognised_role_activating_a_programme": (
            lambda api, program_id: api.activate_program(
                program_id, None, _UNKNOWN_ROLE_HEADERS
            ),
            ApiErrorId.UNKNOWN_ROLE.value,
        ),
    }


_AUTH_PROBES = _auth_probes()


@pytest.mark.parametrize(
    ("reader_name", "expected_error_id"), list(zip(_DETAIL_READERS, NOT_FOUND_CODES))
)
def test_every_addressable_entity_has_its_own_not_found_code(
    api, reader_name, expected_error_id
):
    """
    Addressing an identifier that resolves to nothing on any of the eleven
    single-resource reads returns that entity's own not-found code at HTTP 404 —
    the codes are per entity, never a shared generic one.

    "Each entity has its own not-found code — `ERR_PROGRAM_NOT_FOUND`, `ERR_STATE_EXPIRY_RULE_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_PARTNER_AGREEMENT_NOT_FOUND`, `ERR_POINT_LOT_NOT_FOUND`, `ERR_REDEMPTION_EVENT_NOT_FOUND`, `ERR_BREAKAGE_ESTIMATE_NOT_FOUND`, `ERR_SETTLEMENT_STATEMENT_NOT_FOUND` and `ERR_CHANGE_ORDER_NOT_FOUND` — and each carries HTTP 404."
    "Where a nested path is addressed, path identifiers are resolved strictly left to right and the first identifier that does not resolve decides the 404."

    Design: Corner/errors/errors_all_eleven_path_id_codes_return_their_own_not_found
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    read = getattr(api, reader_name)
    assertions.assert_error(read(UNKNOWN_ID, ACCOUNTANT_HEADERS), expected_error_id)


@pytest.mark.parametrize("probe_name", sorted(_AUTH_PROBES))
def test_absent_or_unrecognised_identity_headers_both_return_401(api, probe_name):
    """
    The two header failures are distinct codes at the same status: any absent or
    empty identity header is a missing-headers refusal, while a role name outside
    the recognised five is an unknown-role refusal. Both are decided before the
    request body, the path identifier or the role's authority is ever consulted,
    and neither leaves a trace on the programme.

    "Every request — without exception, including reads — must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts."
    "When either header is absent or empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
    "When `X-User-Role` carries a value that is not one of the five recognised role names, the rejection is `ERR_UNKNOWN_ROLE` (HTTP 401)."

    Design: Corner/errors/errors_missing_auth_headers_and_unknown_role_both_return_401
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    probe, expected_error_id = _AUTH_PROBES[probe_name]

    assertions.assert_error(probe(api, program["id"]), expected_error_id)

    after = assertions.assert_ok(api.get_program(program["id"], PROGRAM_ADMIN_HEADERS))
    assertions.assert_fields(after, status=PROGRAM_DRAFT, version=program["version"])
    assertions.assert_page(
        api.list_programs(PROGRAM_ADMIN_HEADERS), expected_ids=[program["id"]], total_count=1
    )


def _program_with_one_cohort(api):
    """A DRAFT programme already carrying one cohort, whose code is therefore taken."""
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    cohort = fixtures.new_cohort(api, program["id"], cohort_code=DUPLICATE_COHORT_CODE)
    return program, cohort


def _malformed_probes():
    """
    The three shapes of a malformed request: an absent required input, a value
    outside its declared enumeration, and a pagination argument outside its
    accepted range. The last case is malformed *and* a duplicate code, which the
    request-shape rung must decide first.
    """
    return {
        "required_input_absent": lambda api, program_id: api.create_cohort(
            factories.cohort_payload(program_id, observed_redemption_rate_bp=None),
            PROGRAM_ADMIN_HEADERS,
        ),
        "value_outside_its_enumeration": lambda api, program_id: api.create_program(
            factories.program_payload(breakage_method="FIFO_WEIGHTED"),
            PROGRAM_ADMIN_HEADERS,
        ),
        "limit_above_the_maximum": lambda api, program_id: api.list_cohorts(
            PROGRAM_ADMIN_HEADERS, program_id=program_id, limit=MAX_LIMIT + 1
        ),
        "limit_below_the_minimum": lambda api, program_id: api.list_cohorts(
            PROGRAM_ADMIN_HEADERS, program_id=program_id, limit=0
        ),
        "negative_offset": lambda api, program_id: api.list_cohorts(
            PROGRAM_ADMIN_HEADERS, program_id=program_id, offset=-1
        ),
        "absent_input_outranks_a_duplicate_code": lambda api, program_id: api.create_cohort(
            factories.cohort_payload(
                program_id,
                cohort_code=DUPLICATE_COHORT_CODE,
                observed_redemption_rate_bp=None,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
    }


_MALFORMED_PROBES = _malformed_probes()


@pytest.mark.parametrize("probe_name", sorted(_MALFORMED_PROBES))
def test_invalid_request_covers_absent_inputs_bad_enums_and_pagination(api, probe_name):
    """
    One code carries all three request-shape failures: an omitted required input,
    a value the enumeration does not declare, and a pagination argument out of
    range. A body that is malformed and also carries an already-taken code is
    reported as malformed, because request shape is decided before uniqueness,
    and no rejected request persists anything.

    "**Request shape** — the body parses, every required input the endpoint declares is present, every value satisfies its declared type, enumeration and range constraint, and pagination parameters are in range. Otherwise `ERR_INVALID_REQUEST` (400), on every endpoint."
    "Behaviourally, a cohort carries `observed_redemption_rate_bp` — the redemption rate historically observed for that vintage before any programme-change effect, from 0 through 10000 inclusive — and `sample_size`, the number of members underlying that observation, at least 1."
    "`breakage_method` is either `COHORT_WEIGHTED` or `PROGRAM_HISTORICAL` and defaults to `COHORT_WEIGHTED`."
    "A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    "Enrolment vintages are **Cohort** rows, each attached to a programme through a `program_id` and labelled by a `cohort_code` of at most 32 non-empty characters that must be unique within the programme, again on pain of `ERR_DUPLICATE_CODE`."

    Design: Corner/errors/errors_invalid_request_covers_missing_field_bad_enum_and_pagination
    """
    program, cohort = _program_with_one_cohort(api)

    assertions.assert_error(
        _MALFORMED_PROBES[probe_name](api, program["id"]),
        ApiErrorId.INVALID_REQUEST.value,
    )

    assertions.assert_page(
        api.list_cohorts(PROGRAM_ADMIN_HEADERS, program_id=program["id"]),
        expected_ids=[cohort["id"]],
        total_count=1,
    )
    assertions.assert_page(
        api.list_programs(PROGRAM_ADMIN_HEADERS),
        expected_ids=[program["id"]],
        total_count=1,
    )


def test_pagination_bounds_are_inclusive_at_both_ends(api):
    """
    The pagination range that rejects 0 and 101 accepts its own endpoints: a limit
    of 1 and a limit of 100 are both honoured and echoed back in the list window
    alongside the unfiltered total.

    "`limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."
    "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope."

    Design: Corner/errors/errors_invalid_request_covers_missing_field_bad_enum_and_pagination
    """
    program, cohort = _program_with_one_cohort(api)

    assertions.assert_page(
        api.list_cohorts(PROGRAM_ADMIN_HEADERS, program_id=program["id"], limit=MAX_LIMIT),
        expected_ids=[cohort["id"]],
        total_count=1,
        has_more=False,
        limit=MAX_LIMIT,
        offset=0,
    )
    assertions.assert_page(
        api.list_cohorts(PROGRAM_ADMIN_HEADERS, program_id=program["id"], limit=1),
        expected_ids=[cohort["id"]],
        total_count=1,
        has_more=False,
        limit=1,
    )


def test_hard_closed_period_refuses_a_statement_measured_afterwards(api):
    """
    Sealing the books is final: once the period is hard-closed, a settlement
    statement measured against it afterwards is refused even though the agreement
    is active and its expected version is exactly right, and the sealed figures
    are left untouched.

    "A `Controller` hard-closes a soft-closed period, `SOFT_CLOSED → HARD_CLOSED`, which is terminal."
    "Finally, a hard-closed accounting period is immutable, and so is everything beneath it."
    "Once a period reaches `HARD_CLOSED`, no mutation of that period or of any statement belonging to it is permitted, and the attempt is rejected with `ERR_PERIOD_HARD_CLOSED`."
    "Separately, and at a lower rung of the ladder, no child of a `HARD_CLOSED` period may be mutated at all: reopening the period, or creating, issuing, paying or writing off one of its statements, is rejected with `ERR_PERIOD_HARD_CLOSED`."

    Design: Corner/errors/errors_hard_closed_period_rejects_a_later_settlement_statement
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(api, program["id"])
    cohort = fixtures.new_cohort(api, program["id"])
    fixtures.activate(api, program["id"])
    member = fixtures.new_member(api, program["id"], cohort["id"])
    period = fixtures.new_period(api, program["id"])
    fixtures.issue_lot(api, member["id"], period["id"], 1000)
    fixtures.approved_estimate(api, program["id"], period["id"])

    fixtures.set_clock(api, PERIOD_AUG_END)
    assertions.assert_ok(api.soft_close_period(period["id"], None, CONTROLLER_HEADERS))
    sealed = assertions.assert_ok(
        api.hard_close_period(period["id"], None, CONTROLLER_HEADERS)
    )
    assertions.assert_fields(
        sealed,
        state=PERIOD_HARD_CLOSED,
        pre_catchup_liability_cents=DEFERRED_REVENUE_CENTS,
        required_liability_cents=REQUIRED_LIABILITY_CENTS,
        catch_up_adjustment_cents=CATCH_UP_ADJUSTMENT_CENTS,
        closing_liability_cents=REQUIRED_LIABILITY_CENTS,
        breakage_recognized_cents=-CATCH_UP_ADJUSTMENT_CENTS,
    )

    agreement = fixtures.new_agreement(api, program["id"], min_invoice_cents=1000)
    assertions.assert_error(
        api.create_statement(
            factories.statement_payload(
                agreement["id"], period["id"], agreement["version"]
            ),
            ACCOUNTANT_HEADERS,
        ),
        ApiErrorId.PERIOD_HARD_CLOSED.value,
    )

    assertions.assert_page(
        api.list_statements(ACCOUNTANT_HEADERS, period_id=period["id"]), total_count=0
    )
    after = assertions.assert_ok(api.get_period(period["id"], CONTROLLER_HEADERS))
    assertions.assert_fields(
        after, state=PERIOD_HARD_CLOSED, version=sealed["version"]
    )


def _assert_error_envelope(response, expected_error_id, expected_status):
    """
    One error envelope, checked as a shape rather than as a code: three top-level
    fields, an error response_type, a data object of exactly the two error fields
    with a non-empty message, and a meta object of exactly the two request fields.
    """
    assertions.assert_error(response, expected_error_id)
    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status} for {expected_error_id}, "
        f"got {response.status_code}"
    )
    body = response.json()

    assert set(body) == set(ENVELOPE_TOP_LEVEL_FIELDS), (
        f"Expected exactly {sorted(ENVELOPE_TOP_LEVEL_FIELDS)} at the top level, "
        f"got {sorted(body)}"
    )
    assert body["response_type"] == "error", (
        f"Expected response_type 'error', got {body['response_type']!r}"
    )
    assert set(body["data"]) == set(ERROR_ENVELOPE_FIELDS), (
        f"Expected exactly {sorted(ERROR_ENVELOPE_FIELDS)} in data, "
        f"got {sorted(body['data'])}"
    )
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip(), (
        f"An error message must be human-readable text, got {body['data']['message']!r}"
    )
    assert set(body["meta"]) == set(ENVELOPE_META_FIELDS), (
        f"An error's meta carries only {sorted(ENVELOPE_META_FIELDS)}, "
        f"got {sorted(body['meta'])}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert _TIMESTAMP_PATTERN.match(body["meta"]["api_request_timestamp"]), (
        "api_request_timestamp must be a UTC instant with three fractional digits, "
        f"got {body['meta']['api_request_timestamp']!r}"
    )
    return body


def test_error_envelope_is_identical_across_every_status_code(api):
    """
    A 400, a 403, a 404 and a 409 are poured into one and the same envelope: three
    top-level fields, response_type 'error', a data object of exactly error_id and
    message, and a meta object of exactly the request identifier and its
    timestamp — no pagination keys leak in, every request identifier is distinct,
    and the successful read alongside them shares the same two meta keys while
    carrying an object in data.

    "All error API responses (4xx status codes) follow this standard envelope format:"
    "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    "The `error_id` is a unique, machine-readable string that identifies the specific error."
    "The `message` provides a human-readable explanation of what went wrong."
    "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."
    "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."
    "The first activation moves the programme `DRAFT → ACTIVE`, and it is permitted only when the programme already has at least one state expiry rule and at least one cohort; a programme missing either is rejected with `ERR_PROGRAM_CONFIG_INCOMPLETE`."

    Design: Corner/errors/errors_envelope_shape_is_identical_across_every_status_code
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)

    malformed = _assert_error_envelope(
        api.list_programs(PROGRAM_ADMIN_HEADERS, limit=MAX_LIMIT + 1),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )
    forbidden = _assert_error_envelope(
        api.create_program(factories.program_payload(), ACCOUNTANT_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        403,
    )
    missing = _assert_error_envelope(
        api.get_program(UNKNOWN_ID, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.PROGRAM_NOT_FOUND.value,
        404,
    )
    conflicted = _assert_error_envelope(
        api.activate_program(program["id"], None, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.PROGRAM_CONFIG_INCOMPLETE.value,
        409,
    )

    request_ids = [
        body["meta"]["api_request_id"]
        for body in (malformed, forbidden, missing, conflicted)
    ]
    assert len(set(request_ids)) == len(request_ids), (
        f"Every response must carry its own api_request_id, got {request_ids}"
    )

    success_response = api.get_program(program["id"], PROGRAM_ADMIN_HEADERS)
    entity = assertions.assert_envelope_object(success_response)
    success_body = success_response.json()
    assert set(success_body) == set(ENVELOPE_TOP_LEVEL_FIELDS)
    assert set(success_body["meta"]) == set(ENVELOPE_META_FIELDS), (
        "A single-object read carries no pagination keys in meta, got "
        f"{sorted(success_body['meta'])}"
    )
    assert success_body["meta"]["api_request_id"].startswith("req_")
    assert _TIMESTAMP_PATTERN.match(success_body["meta"]["api_request_timestamp"])
    assertions.assert_fields(entity, status=PROGRAM_DRAFT, version=program["version"])

    assertions.assert_page(
        api.list_programs(PROGRAM_ADMIN_HEADERS),
        expected_ids=[program["id"]],
        total_count=1,
    )
