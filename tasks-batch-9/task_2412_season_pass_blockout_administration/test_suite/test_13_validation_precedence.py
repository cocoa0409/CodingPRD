"""Where the ordered validation bands are visible from outside: role, schema, paging."""

from test_helpers import (
    ApiErrorId,
    create_park_day,
    create_program,
    gate_agent_headers,
    pass_program_payload,
    program_admin_headers,
    validate_error,
    validate_paginated,
)


def _bad_program_body():
    """A body that breaks the schema band twice: unknown field and missing field."""
    payload = pass_program_payload(mascot="Otter")
    payload.pop("season_year")
    return payload


class TestAuthorisationAnswersBeforeSchema:
    """A forbidden role never learns whether its body was well formed."""

    def test_a_gate_agent_posting_a_malformed_programme_gets_the_role_error(self, api):
        """The role band sits above the schema band, so 403 wins over 400.

        PRD: "Validation is strictly ordered, and the **first** rule whose condition holds
        produces the response; later rules are never reached."

        Design: Corner/validations/role_check_at_priority_three_precedes_schema_check_at_priority_four
        """
        response = api.create_pass_program(_bad_program_body(), headers=gate_agent_headers())

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        _, meta = validate_paginated(
            api.list_pass_programs(headers=program_admin_headers())
        )
        assert meta["total_count"] == 0, (
            f"the refused write must not have created a programme, got {meta['total_count']!r}"
        )

    def test_the_same_body_from_the_permitted_role_reaches_the_schema_band(self, api):
        """Once the role passes, the malformed body is answered on its merits.

        PRD: "3. **Schema** — on write endpoints, an unknown field, a missing required
        field, a wrong JSON type, a malformed date or timestamp, a numeric value outside a
        declared range, or a value outside a declared enumeration, all yielding
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/role_check_at_priority_three_precedes_schema_check_at_priority_four
        """
        response = api.create_pass_program(_bad_program_body(), headers=program_admin_headers())

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        _, meta = validate_paginated(
            api.list_pass_programs(headers=program_admin_headers())
        )
        assert meta["total_count"] == 0, (
            f"neither attempt should have stored a programme, got {meta['total_count']!r}"
        )


class TestPaginationBoundsAreEnforcedOnListEndpoints:
    """The paging window and the filter enumerations are schema-band checks."""

    def _one_day(self, api):
        program = create_program(api)
        create_park_day(api, program["id"], "2026-09-01")
        return program

    def test_a_limit_or_offset_outside_its_bounds_is_rejected(self, api, default_clock):
        """101, 0 and a negative offset are each refused.

        PRD: "A `limit` below 1, a `limit` above 100, an `offset` below 0, or a filter query
        parameter carrying a value outside its declared enumeration is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/list_endpoint_limit_above_one_hundred_is_rejected
        """
        self._one_day(api)

        for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}, {"day_class": "SUNNY"}):
            response = api.list_park_days(headers=program_admin_headers(), params=params)
            validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_the_maximum_limit_of_one_hundred_is_itself_accepted(self, api, default_clock):
        """The ceiling is an inclusive bound, so 100 is a legal page size.

        PRD: "`limit` is the maximum number of records to return; when omitted it defaults
        to 10, its minimum accepted value is 1 and its maximum accepted value is 100."

        Design: Corner/validations/list_endpoint_limit_above_one_hundred_is_rejected
        """
        self._one_day(api)

        rows, meta = validate_paginated(
            api.list_park_days(headers=program_admin_headers(), params={"limit": 100})
        )

        assert meta["limit"] == 100, (
            f"the accepted maximum should be echoed back, got {meta['limit']!r}"
        )
        assert meta["total_count"] == 1, (
            f"the single day should be counted, got {meta['total_count']!r}"
        )
        assert len(rows) == 1, f"one day should be returned, got {len(rows)}"
        assert meta["has_more"] is False, "nothing remains beyond a page of one hundred"
