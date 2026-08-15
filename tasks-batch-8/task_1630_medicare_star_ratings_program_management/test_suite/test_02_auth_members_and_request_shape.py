"""Auth presence, member enrollment basics, list pagination, request shape, and
uniqueness rules."""
from test_helpers import (
    ApiErrorId,
    assert_member,
    create_cycle,
    create_measure,
    create_measure_payload,
    create_member,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthPresence:
    def test_missing_auth_headers_rejected(self, api, stars_admin_headers):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`."
        PRD §2.1: "Both headers must be present and non-empty; a request missing
        either is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        create_cycle()
        resp = api.list_rating_cycles({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRequestShape:
    def test_request_shape_violations_rejected(self, api, stars_admin_headers,
                                               stars_analyst_headers,
                                               quality_ops_headers):
        """PRD §2.11: "3. **Request shape** — required fields present, types
        correct, enum members valid, and scalar ranges respected: `numerator` at
        least 0, `denominator` at least 0, `numerator` not exceeding `denominator`,
        `sample_size` greater than 0, `response_count` between 0 and `sample_size`
        inclusive, `enrolled_months` between 1 and 12 inclusive,
        `max_concurrent_waves` at least 1, `target_star` between 1 and 5 inclusive,
        `unit_reward_per_gap` greater than 0, `max_pool_amount` at least 0,
        `benchmark_pmpm` greater than 0, and `rating_year` strictly greater than
        `measurement_year`. Violations are `ERR_INVALID_REQUEST` (HTTP 400) on all
        write endpoints."

        Design: Corner/validations/request_shape_violations_rejected
        """
        cycle = create_cycle()
        measure = create_measure(cycle["id"])

        # Bad enum member for measure_type.
        resp = api.create_measure(
            create_measure_payload(cycle["id"], code="XXX", title="Bad Type",
                                   measure_type="INVALID_TYPE"),
            stars_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        # numerator exceeding denominator.
        resp = api.create_measure_performance(
            {"rating_cycle_id": cycle["id"], "measure_id": measure["id"],
             "numerator": 11, "denominator": 10},
            quality_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        # Missing required field member_ref.
        resp = api.create_member({"plan_contract": "H1234", "enrolled_months": 12},
                                 quality_ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestMemberEnrollment:
    def test_member_creation_applies_defaults(self, api, quality_ops_headers):
        """PRD §3.4: "A `QualityOps` specialist enrolls a member by supplying the
        external `member_ref` — unique across the entire system, with duplicates
        rejected as `ERR_DUPLICATE_MEMBER_REF` — the `plan_contract` MA contract
        identifier, and the `enrolled_months` the member accumulates in the
        measurement year (an integer from 1 to 12)."
        PRD §3.4: "A new member is `ENROLLED`."

        Design: Corner/entities/member_creation_applies_defaults
        """
        resp = api.create_member(
            {"member_ref": "MBR-100", "plan_contract": "H1234", "enrolled_months": 6},
            quality_ops_headers,
        )
        member = validate_success(resp, 201)
        assert_member(member)
        assert member["status"] == "ENROLLED", "A new member is ENROLLED"
        assert member["enrolled_months"] == 6
        assert is_valid_uuid(member["id"]), "id is a server-minted UUID"

    def test_member_list_pagination_defaults(self, api, quality_ops_headers):
        """PRD §2.3: "All list endpoints accept `limit` and `offset` query
        parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of
        100. `offset` defaults to 0. Results are sorted by `created_at` ascending.
        The `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more` so the caller can page deterministically
        through the collection."

        Design: Corner/endpoints/member_list_pagination_defaults
        """
        for i in range(12):
            create_member(f"MBR-{i + 1:02d}")

        page, meta = validate_paginated(api.list_members(quality_ops_headers))
        assert len(page) == 10, f"Default page holds 10 items, got {len(page)}"
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True

        page, meta = validate_paginated(
            api.list_members(quality_ops_headers, params={"limit": 5, "offset": 10}))
        assert len(page) == 2, f"Final page holds the remaining 2 items, got {len(page)}"
        assert meta["limit"] == 5 and meta["offset"] == 10
        assert meta["total_count"] == 12
        assert meta["has_more"] is False


class TestUniqueness:
    def test_uniqueness_violations_member_ref_and_measure_code(
            self, api, stars_analyst_headers, quality_ops_headers):
        """PRD §2.10: "Uniqueness and referential rules are enforced at write time,
        each with its own rejection: a cut point row referencing a measure outside
        the set's cycle is rejected with `ERR_CUTPOINT_MEASURE_CYCLE_MISMATCH`; a
        performance whose measure does not belong to the named cycle with
        `ERR_MEASURE_CYCLE_MISMATCH`; a second performance for the same measure
        within one cycle with `ERR_DUPLICATE_PERFORMANCE`; a second `OPEN` or
        `REOPENED` gap for the same member and measure with
        `ERR_DUPLICATE_OPEN_GAP`; a measure `code` reused within one cycle with
        `ERR_DUPLICATE_MEASURE_CODE`; and a `member_ref` already registered anywhere
        in the system with `ERR_DUPLICATE_MEMBER_REF`."

        Design: Corner/validations/uniqueness_violations_member_ref_and_measure_code
        """
        cycle = create_cycle()
        create_measure(cycle["id"], code="BCS")
        create_member("MBR-1")

        resp = api.create_member(
            {"member_ref": "MBR-1", "plan_contract": "H5678", "enrolled_months": 6},
            quality_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBER_REF)

        resp = api.create_measure(
            create_measure_payload(cycle["id"], code="BCS", title="Duplicate Code",
                                   domain="CHRONIC_CARE", measure_type="OUTCOME"),
            stars_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEASURE_CODE)
