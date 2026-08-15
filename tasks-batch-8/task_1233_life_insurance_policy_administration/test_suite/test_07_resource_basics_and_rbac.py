"""Resource creation, envelope/pagination contract, nested retrieval, RBAC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_billing_cycle,
    assert_insured_person,
    create_application,
    create_insured,
    create_issued_policy,
    create_template,
    get_success_data,
    is_valid_uuid,
    make_policyholder_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["agent_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


class TestInsuredPersonCreation:
    def test_creation_returns_full_resource(self, api):
        """PRD §4: "Operations that create a new resource — an insured person, a product template,
        an application, an issued policy, a loan, an election, a declaration,
        a reinstatement request, a rider, or a conversion request — return
        `201 Created`."
        PRD §2.5: "The `id` is a server-minted UUID with no type prefix. The `created_at`
        timestamp records creation as an ISO 8601 UTC value with three
        fractional digits."

        Design: Corner/entities/insured_person_creation_required_fields
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_insured_person(
            {"full_name": "Carl C", "date_of_birth": "1990-01-01",
             "tobacco_user": False, "gender": "MALE"}, AGENT)
        data = validate_success(resp, expected_status=201)
        assert_insured_person(data)
        assert is_valid_uuid(data["id"])
        assert data["full_name"] == "Carl C"
        assert data["tobacco_user"] is False
        assert data["gender"] == "MALE"

    def test_missing_date_of_birth_rejected(self, api):
        """PRD §2.12: "**eighth**, field-value constraints (`ERR_INVALID_REQUEST`) on all creating
        and modifying endpoints". PRD §5:
        "ERR_INVALID_REQUEST | 400 Bad Request".

        Design: Corner/entities/insured_person_missing_required_field_returns_invalid_request
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_insured_person(
            {"full_name": "NoDOB", "tobacco_user": False, "gender": "MALE"}, AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFoundAndPagination:
    def test_get_unknown_policy_returns_policy_not_found(self, api):
        """PRD §2.9: "Top-level lookups carry their own existence errors:
        `ERR_APPLICATION_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, and
        `ERR_INSURED_NOT_FOUND`" and the path-identifier check surfaces
        "ERR_POLICY_NOT_FOUND for the policy segment".

        Design: Corner/entities/entity_not_found_returns_404
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.get_policy(NON_EXISTENT_UUID, AGENT)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_FOUND)

    def test_list_policies_applies_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults
        to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "The `offset` parameter sets the number of items skipped and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/pagination_defaults_applied_on_list
        """
        set_clock("2026-05-01T00:00:00Z")
        data, meta = validate_paginated(api.list_policies(AGENT))
        assert isinstance(data, list)
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"
        assert "total_count" in meta and "has_more" in meta

    def test_billing_cycles_reverse_reachable_from_policy(self, api):
        """PRD §3.11: "Flat collection listings exist for reverse reachability from a known foreign
        key: billing cycles, dividend declarations, non-forfeiture elections,
        reinstatement requests, riders, and cash-value ledger entries are each
        filterable by `policy_id`".
        PRD §3.3: "the first billing cycle is established" at issuance.

        Design: Corner/endpoints/fk_reverse_reachability_list_billing_cycles
        """
        bundle = create_issued_policy(premium_mode="MONTHLY")
        policy_id = bundle["policy"]["id"]
        cycles, _meta = validate_paginated(api.list_billing_cycles(policy_id, AGENT))
        assert len(cycles) >= 1, "issuance establishes the first billing cycle"
        for cycle in cycles:
            assert_billing_cycle(cycle)
            assert cycle["policy_id"] == policy_id


class TestAuthenticationAndRbac:
    def test_missing_user_context_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a malformed value, is rejected
        with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.list_policies(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_policyholder_cannot_create_product_template(self, api):
        """PRD §2.1: "Each operation is restricted to a designated set of roles; a request whose
        role is not authorized for the target operation is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4 endpoint table: "| POST | `/product-templates` | Create a product template | PlatformAdmin |".

        Design: Corner/validations/insufficient_permissions_returns_403
        """
        set_clock("2026-05-01T00:00:00Z")
        insured = create_insured()
        resp = api.create_product_template(
            {"product_code": "X-1", "product_type": "WHOLE_LIFE_NON_PARTICIPATING",
             "participating": False, "allows_policy_loans": False,
             "min_face_amount_cents": 1, "max_face_amount_cents": 100,
             "base_monthly_premium_rate_per_thousand_cents": 1,
             "coi_rate_table": [], "surrender_charge_schedule": []},
            make_policyholder_headers(insured["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_underwriter_cannot_create_insured_person(self, api):
        """PRD §2.1: "a request whose role is not authorized for the target operation is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4 endpoint table: "| POST | `/insured-persons` | Create an insured person | Agent |".

        Design: Corner/rbac/underwriter_cannot_create_insured_person
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_insured_person(
            {"full_name": "X", "date_of_birth": "1990-01-01",
             "tobacco_user": False, "gender": "MALE"}, UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_agent_cannot_approve_application(self, api):
        """PRD §2.1: "a request whose role is not authorized for the target operation is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4 endpoint table: "| POST | `/applications/{id}/approve` | Approve with an assigned underwriting
        class | Underwriter |".

        Design: Corner/rbac/agent_cannot_approve_application
        """
        set_clock("2026-05-01T00:00:00Z")
        insured = create_insured()
        template = create_template()
        app = create_application(insured["id"], template["id"])
        get_success_data(api.begin_review(app["id"], UNDERWRITER))
        resp = api.approve_application(app["id"], "STANDARD_NON_TOBACCO", AGENT)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
