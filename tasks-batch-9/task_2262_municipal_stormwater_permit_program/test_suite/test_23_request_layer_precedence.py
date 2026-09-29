"""The first three rungs of the ladder: identity, then role, then shape."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import UNRESOLVABLE_UUID
from test_helpers.test_users import (
    CLERK_HEADERS,
    INSPECTOR_HEADERS,
    MANAGER_HEADERS,
    role_only_headers,
)
from test_helpers.types import UserRole

CLERK_ROLE = UserRole.UTILITY_BILLING_CLERK.value
MANAGER_ROLE = UserRole.STORMWATER_PROGRAM_MANAGER.value

# A body that is short of ``permit_number`` and would fail the shape layer.
INCOMPLETE_TERM_BODY = {"term_start_date": "2026-01-01"}


class TestAnUnidentifiedCallerIsAnsweredFirst:
    """One request breaking identity, role and shape at once answers 401."""

    def test_01_a_missing_user_id_outranks_both_the_role_and_the_body(self):
        """A clerk-roled, permit_number-less create still reports the identity.

        PRD: "Every request — including the clock endpoint — must carry two headers.
        `X-User-ID` identifies the acting individual and `X-User-Role` declares the
        capacity in which they are acting. If `X-User-ID` is absent or does not name a
        known actor, the request is refused with `ERR_MISSING_USER_ID` (HTTP 401)." And:
        "When a request violates more than one rule, exactly one error is returned: the
        one belonging to the highest-precedence violated rule." And: "**Actor
        identification.** A missing or unknown `X-User-ID` yields `ERR_MISSING_USER_ID`
        (401)."

        Design: Corner/validations/a_request_missing_x_user_header_is_rejected_ahead_of_role_and_shape
        """
        response = api_client.create_permit_term(
            INCOMPLETE_TERM_BODY, role_only_headers(CLERK_ROLE)
        )

        validate_error(response, ApiErrorId.ERR_MISSING_USER_ID.value, 401)

    def test_02_the_clock_endpoint_is_no_exception(self):
        """The administrative clock is behind the same two headers.

        PRD: "Every request — including the clock endpoint — must carry two headers."
        And: "If `X-User-ID` is absent or does not name a known actor, the request is
        refused with `ERR_MISSING_USER_ID` (HTTP 401)."

        Design: Corner/validations/a_request_missing_x_user_header_is_rejected_ahead_of_role_and_shape
        """
        response = api_client.set_clock(
            "2026-08-15T00:00:00Z", role_only_headers(MANAGER_ROLE)
        )

        validate_error(response, ApiErrorId.ERR_MISSING_USER_ID.value, 401)

    def test_04_neither_rejection_left_a_trace(self):
        """No term was stored and the clock never moved off its opening instant.

        PRD: "Nothing is persisted when a request is rejected — no partial writes, no
        counter increments, no cascades." And: "Before any request is made the clock
        reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to the host's
        real time." And: "The manager or a `MunicipalOperationsSupervisor` reports
        progress by supplying `measurable_goal_actual`, which requires the measure's
        `status` to be `ACTIVE`; the call stamps `last_progress_reported_at` from the
        logical clock."

        Design: Corner/validations/a_request_missing_x_user_header_is_rejected_ahead_of_role_and_shape
        """
        api_client.create_permit_term(
            INCOMPLETE_TERM_BODY, role_only_headers(CLERK_ROLE)
        )
        api_client.set_clock("2026-08-15T00:00:00Z", role_only_headers(MANAGER_ROLE))

        _, meta = validate_paginated(api_client.list_permit_terms(MANAGER_HEADERS))
        assert meta["total_count"] == 0, (
            f"the rejected create stored nothing, got {meta['total_count']} terms"
        )

        program = fx.setup_active_program()
        progress = fx.report_progress(
            program["measures"]["PUBLIC_EDUCATION"]["id"], 6.00
        )
        assert progress["last_progress_reported_at"] == "2026-08-01T00:00:00Z", (
            "the refused clock call left the logical clock where it started, got "
            f"{progress['last_progress_reported_at']}"
        )


class TestAnUnauthorisedRoleLearnsNothingElse:
    """The 403 hides whether the path resolves and whether the body parses."""

    def test_05_the_role_check_precedes_both_the_body_and_the_path(
        self, active_program
    ):
        """A clerk aiming a nonsense body at a dead outfall id is told only 403.

        PRD: "**Role authorisation.** A role not listed for the endpoint yields
        `ERR_UNAUTHORIZED` (403). Because this precedes every existence and state check,
        an unauthorised caller can never learn whether a resource exists or what state it
        is in."

        Design: Corner/validations/unauthorized_role_outranks_invalid_payload_shape_and_hides_existence
        """
        response = api_client.create_observation(
            UNRESOLVABLE_UUID,
            {"observation_type": "NOT_A_TYPE", "observed_at": "not-a-timestamp"},
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    def test_06_a_real_active_outfall_is_equally_silent(self, active_program):
        """Retirement belongs to the manager, so the inspector is simply refused.

        PRD: "**Role authorisation.** A role not listed for the endpoint yields
        `ERR_UNAUTHORIZED` (403). Because this precedes every existence and state check,
        an unauthorised caller can never learn whether a resource exists or what state it
        is in." And: "Nothing is persisted when a request is rejected — no partial writes,
        no counter increments, no cascades."

        Design: Corner/validations/unauthorized_role_outranks_invalid_payload_shape_and_hides_existence
        """
        outfall = active_program["outfalls"]["OF-01"]
        before = fx.read_outfall(outfall["id"])

        response = api_client.retire_outfall(outfall["id"], INSPECTOR_HEADERS)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        after = fx.read_outfall(outfall["id"])
        assert after["status"] == "ACTIVE", "the outfall was never retired"
        assert after["version"] == before["version"], (
            f"the refused call bumped no version, {before['version']} -> "
            f"{after['version']}"
        )


class TestRequestShapeIsJudgedBeforeThePathResolves:
    """A bad enum and a dead path id in one call answer 400, not 404."""

    def test_07_a_bad_enum_answers_ahead_of_the_missing_inspection(
        self, active_program
    ):
        """The severity is rejected without the inspection id ever being looked up.

        PRD: "**Request shape.** Missing required body fields, wrong types, unknown enum
        members, out-of-range numbers, malformed ISO 8601 values and out-of-range
        pagination all yield `ERR_VALIDATION` (400)." And: "**Path existence.** Every
        identifier in the path must resolve to a stored row, yielding the 404 belonging
        to that entity kind."

        Design: Corner/validations/invalid_enum_outranks_the_path_not_found_check
        """
        response = api_client.add_inspection_finding(
            UNRESOLVABLE_UUID,
            {"severity": "CATASTROPHIC", "description": "Slope failure"},
            INSPECTOR_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        _, meta = validate_paginated(api_client.list_inspections(INSPECTOR_HEADERS))
        assert meta["total_count"] == 0, (
            f"no inspection was conjured up by the attempt, got {meta['total_count']}"
        )

    @pytest.mark.parametrize("limit", [0, 101])
    def test_08_a_limit_outside_one_to_a_hundred_is_a_shape_failure(
        self, active_program, limit
    ):
        """Zero rows and a hundred and one rows are both out of range.

        PRD: "`limit` is the maximum number of rows returned; it defaults to 10, has a
        minimum of 1 and a maximum of 100." And: "A `limit` outside the range 1 to 100
        inclusive, or a negative `offset`, is a request-shape failure and yields
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/invalid_enum_outranks_the_path_not_found_check
        """
        response = api_client.list_term_control_measures(
            active_program["term_id"], MANAGER_HEADERS, {"limit": limit}
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    @pytest.mark.parametrize("limit", [1, 100])
    def test_09_both_ends_of_the_range_are_themselves_allowed(
        self, active_program, limit
    ):
        """The range is inclusive, so 1 and 100 are ordinary page sizes.

        PRD: "A `limit` outside the range 1 to 100 inclusive, or a negative `offset`, is
        a request-shape failure and yields `ERR_VALIDATION` (HTTP 400)." And: "Every list
        response reports `limit`, `offset`, `total_count` and `has_more` in the `meta`
        object of the envelope."

        Design: Corner/validations/invalid_enum_outranks_the_path_not_found_check
        """
        rows, meta = validate_paginated(
            api_client.list_term_control_measures(
                active_program["term_id"], MANAGER_HEADERS, {"limit": limit}
            )
        )

        assert meta["limit"] == limit, f"the page size is echoed back, got {meta['limit']}"
        assert meta["total_count"] == 6, (
            f"the six measures are all counted, got {meta['total_count']}"
        )
        assert len(rows) == min(limit, 6), (
            f"a limit of {limit} returns min(limit, 6) rows, got {len(rows)}"
        )
        assert meta["has_more"] is (limit < 6), (
            "has_more follows whether the page exhausted the collection"
        )


def test_10_a_shape_failure_beats_a_path_failure_on_a_reading_endpoint(
    active_program,
):
    """Even a plain read judges its pagination before resolving the path.

    PRD: "**Request shape.** Missing required body fields, wrong types, unknown enum
    members, out-of-range numbers, malformed ISO 8601 values and out-of-range pagination
    all yield `ERR_VALIDATION` (400)." And: "**Path existence.** Every identifier in the
    path must resolve to a stored row, yielding the 404 belonging to that entity kind."

    Design: Corner/validations/invalid_enum_outranks_the_path_not_found_check
    """
    response = api_client.list_term_control_measures(
        UNRESOLVABLE_UUID, MANAGER_HEADERS, {"limit": 0}
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    # The term that does exist is untouched and still readable.
    term = validate_success(
        api_client.get_permit_term(active_program["term_id"], MANAGER_HEADERS)
    )
    assert term["status"] == "ACTIVE", "the real term is unaffected"
