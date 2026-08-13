"""Taxonomy basics, response envelope, pagination, and top-level uniqueness.

Covers PRD §2.1 (auth headers), §2.3 (pagination), §2.5 (common fields),
§2.7 (period keys), §3.1 (registrants) and §3.2 (jurisdictions).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_event,
    create_jurisdiction,
    create_registrant,
    is_iso8601_timestamp,
    is_valid_uuid,
    new_admin_headers,
    new_analyst_headers,
    setup_active_registration,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRegistrantCreation:
    def test_registrant_create_applies_system_defaults(self, api):
        """PRD §3.1: "A new registrant starts `ACTIVE` with
        `aggregate_open_liability_cents` and `overpayment_balance_cents` both
        at zero."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix." / "`version` (integer): a
        system-managed integer that increments by one on every mutation."
        PRD §2.4: "Before any client interaction the clock reads exactly
        2026-08-01T00:00:00Z."

        Design: Corner/entities/registrant_create_applies_system_defaults
        """
        data = validate_success(api.create_registrant(
            {"legal_name": "Acme Fuels", "fein": "12-3456789"},
            new_admin_headers()), expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["aggregate_open_liability_cents"] == 0
        assert data["overpayment_balance_cents"] == 0
        assert data["version"] == 1
        assert is_valid_uuid(data["id"]), "id must be a UUID with no prefix"
        assert data["created_at"] == "2026-08-01T00:00:00.000Z", (
            "created_at must be stamped from the logical clock default")
        assert is_iso8601_timestamp(data["created_at"])

    def test_registrant_create_missing_fein_returns_invalid_request(self, api):
        """PRD §2.10: "(3) body well-formedness — required fields present, enum
        members valid, integer fields at or above their minimums such as
        `quantity_units` of at least one and amounts of at least one cent" and
        "Body well-formedness covers several domain shapes explicitly and all
        are rejected with `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/registrant_create_missing_required_returns_invalid_request
        """
        resp = api.create_registrant(
            {"legal_name": "No Fein Co"}, new_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_registrant_create_computed_field_input_ignored(self, api):
        """PRD §3.1: "A new registrant starts `ACTIVE` with
        `aggregate_open_liability_cents` and `overpayment_balance_cents` both
        at zero." (client-supplied values for the server-computed balances do
        not change the zeroed start).

        Design: Corner/entities/registrant_create_computed_field_input_ignored
        """
        data = validate_success(api.create_registrant(
            {"legal_name": "Acme Fuels", "fein": "12-3456789",
             "overpayment_balance_cents": 999},
            new_admin_headers()), expected_status=201)
        assert data["overpayment_balance_cents"] == 0, (
            "computed balance must start at zero regardless of client input")


class TestJurisdictionValidation:
    def test_jurisdiction_create_invalid_enum_rejected(self, api):
        """PRD §3.2: "a `level` of `FEDERAL`, `STATE`, or `LOCAL`".
        PRD §2.10: "(3) body well-formedness — required fields present, enum
        members valid, integer fields at or above their minimums" and "all are
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/jurisdiction_create_invalid_enum_rejected
        """
        resp = api.create_jurisdiction(
            {"code": "XX", "name": "Nowhere", "level": "REGIONAL",
             "return_frequency": "MONTHLY", "deposit_frequency": "MONTHLY"},
            new_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFound:
    def test_return_get_missing_id_returns_not_found(self, api):
        """PRD §2.10: "(4) existence — path identifiers validated left to
        right, then foreign-key identifiers referenced in the body, with the
        first missing identifier yielding `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/return_get_missing_id_returns_not_found
        """
        resp = api.get_return(NON_EXISTENT_UUID, new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestListPaginationEnvelope:
    def test_taxable_events_list_pagination_envelope(self, api):
        """PRD §2.3: "`limit` specifies the maximum number of items to return;
        it defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        specifies how many items to skip and defaults to 0." and "Paginated
        list responses include `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/taxable_events_list_pagination_envelope
        """
        ctx = setup_active_registration()
        rgn, jur, pc = (ctx["registration"], ctx["jurisdiction"],
                        ctx["product_class"])
        created = [
            create_event(rgn, jur, pc, event_date=f"2026-08-0{3 + i}T00:00:00Z",
                         quantity_units=i + 1)
            for i in range(3)
        ]
        page1, meta1 = validate_paginated(api.list_taxable_events(
            new_analyst_headers(),
            params={"registration_id": rgn["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_taxable_events(
            new_analyst_headers(),
            params={"registration_id": rgn["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2

        paged_ids = [row["id"] for row in page1 + page2]
        assert sorted(paged_ids) == sorted(e["id"] for e in created), (
            "the two pages must together cover exactly the created events")


class TestQuarterlyPeriodKey:
    def test_quarterly_period_key_derivation(self, api):
        """PRD §2.7: "Return periods are keyed by short strings: `YYYY-MM`
        (for example `2026-08`) for a jurisdiction with `MONTHLY` return
        frequency, and `YYYY-Qn` (for example `2026-Q3`) for a `QUARTERLY`
        one."
        PRD §3.6: "The system computes its `due_date` as the first day of the
        month following the period end, advanced by twenty-four days — the
        twenty-fifth of the following month for a monthly period."

        Design: Corner/entities/quarterly_period_key_derivation
        """
        ctx = setup_active_registration(
            jurisdiction_overrides={"code": "OR-TX", "name": "Oregon",
                                    "return_frequency": "QUARTERLY",
                                    "deposit_frequency": "MONTHLY"})
        ev = create_event(ctx["registration"], ctx["jurisdiction"],
                          ctx["product_class"],
                          event_date="2026-08-15T00:00:00Z", quantity_units=10)
        assert ev["period"] == "2026-Q3", (
            "an August event in a QUARTERLY jurisdiction derives 2026-Q3")

        ret = validate_success(api.create_return(
            {"registration_id": ctx["registration"]["id"],
             "jurisdiction_id": ctx["jurisdiction"]["id"],
             "period": "2026-Q3"},
            new_analyst_headers()), expected_status=201)
        # Q3 ends 2026-09-30; first day of the next month + 24 days = 10-25.
        assert ret["due_date"].startswith("2026-10-25T00:00:00"), (
            f"quarterly due_date must be 2026-10-25, got {ret['due_date']!r}")


class TestAuthHeaders:
    def test_request_with_missing_or_undeclared_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, presenting a malformed
        value, or naming an undeclared role is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/request_with_missing_auth_role_header_returns_invalid_request
        """
        no_auth = {"Content-Type": "application/json"}
        resp_missing = api.create_registrant(
            {"legal_name": "Ghost", "fein": "00-0000000"}, no_auth)
        validate_error(resp_missing,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        undeclared = build_user_headers("ghost-1", "Anonymous")
        resp_anon = api.create_registrant(
            {"legal_name": "Ghost", "fein": "00-0000000"}, undeclared)
        validate_error(resp_anon,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestUniqueness:
    def test_duplicate_fein_rejected(self, api):
        """PRD §3.1: "The `fein` must be unique across registrants; a
        duplicate is rejected with `ERR_DUPLICATE_FEIN`."

        Design: Corner/validations/duplicate_fein_rejected
        """
        create_registrant(legal_name="Acme Fuels", fein="12-3456789")
        resp = api.create_registrant(
            {"legal_name": "Acme Clone", "fein": "12-3456789"},
            new_admin_headers())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FEIN)

    def test_duplicate_jurisdiction_code_rejected(self, api):
        """PRD §3.2: "Duplicate jurisdiction codes are rejected with
        `ERR_DUPLICATE_CODE`."

        Design: Corner/validations/duplicate_jurisdiction_code_rejected
        """
        create_jurisdiction(code="CA-BOE", name="California")
        resp = api.create_jurisdiction(
            {"code": "CA-BOE", "name": "California Again", "level": "STATE",
             "return_frequency": "MONTHLY", "deposit_frequency": "SEMI_MONTHLY"},
            new_admin_headers())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)
