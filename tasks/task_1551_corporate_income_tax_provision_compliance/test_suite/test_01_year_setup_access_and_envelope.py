"""Year/jurisdiction setup, access control, error envelope, and read surface.

Covers the corner-design claims around resource creation defaults, the auth
context and role gates, the standard error envelope, pagination, date-range
sanity, uniqueness, and FK reverse-reachability of the read surface.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_book_tax_difference,
    assert_tax_year,
    create_audit_record,
    create_draft_allowance,
    create_filing_record,
    create_fy2026_tax_year,
    create_jurisdiction_payload,
    create_locked_difference,
    create_measured_position,
    create_notice_record,
    create_tax_year_payload,
    create_us_ca_jurisdiction,
    create_us_fed_jurisdiction,
    create_us_il_jurisdiction,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestYearCreation:
    def test_year_create_ignores_client_id_and_applies_defaults(
            self, api, tax_manager_headers):
        """PRD §2.6: "Undeclared extra fields in a request body are ignored,
        never rejected."
        PRD §2.4: "Every resource carries an `id` that is a server-minted UUID
        with no type prefix"
        PRD §3.1: "A new year starts in status `OPEN` with every computed money
        field and both ETR fields at 0."
        PRD §3.1: "`prior_year_total_tax_cents`, the prior year's consolidated
        actual tax, is optional and defaults to 0"

        Design: Corner/entities/tax_year_creation_client_id_input_ignored
        """
        client_id = "00000000-0000-0000-0000-0000000000aa"
        payload = create_tax_year_payload()
        del payload["prior_year_total_tax_cents"]  # exercise the default
        payload["id"] = client_id

        res = api.create_tax_year(payload, tax_manager_headers)
        year = validate_success(res, 201)
        assert_tax_year(year)

        assert year["id"] != client_id, "server must mint its own UUID"
        assert is_valid_uuid(year["id"])
        assert year["status"] == "OPEN"
        assert year["prior_year_total_tax_cents"] == 0
        for field in ("current_provision_cents", "deferred_expense_cents",
                      "net_deferred_asset_cents", "valuation_allowance_cents",
                      "utp_liability_cents",
                      "return_to_provision_adjustment_cents",
                      "forecast_etr_bp", "actual_etr_bp"):
            assert year[field] == 0, f"{field} must start at 0"


class TestAuthAndRoles:
    def test_missing_auth_headers_rejected_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        string that is not one of the declared roles, is rejected with
        `ERR_MISSING_AUTH_CONTEXT` (HTTP 401)."

        Design: Corner/validations/tax_year_create_missing_auth_header_returns_401
        """
        res = api.create_tax_year(create_tax_year_payload(), headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH_CONTEXT,
                       expected_status=401)

    def test_auditor_write_forbidden_but_reads_allowed(
            self, api, tax_manager_headers, auditor_headers):
        """PRD §2.1: "An `Auditor` has read-only access to every resource and
        no write operations."
        PRD §2.6: "**Authorization** — the caller's role is listed for the
        endpoint (`ERR_FORBIDDEN_FOR_ROLE`)."

        Design: Corner/rbac/auditor_write_attempt_forbidden
        """
        jur = validate_success(
            api.create_jurisdiction(create_jurisdiction_payload(),
                                    tax_manager_headers), 201)

        res = api.create_jurisdiction(
            create_jurisdiction_payload(code="US-CA", name="California",
                                        level="STATE"), auditor_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE,
                       expected_status=403)

        got = validate_success(api.get_jurisdiction(jur["id"],
                                                    auditor_headers), 200)
        assert got["code"] == "US-FED"


class TestErrorEnvelopeAndNotFound:
    def test_get_filing_unknown_id_returns_not_found(self, api,
                                                     auditor_headers):
        """PRD §2.6: "**Existence** — path identifiers exist, validated left
        to right, and body foreign-key references (`tax_year_id`,
        `jurisdiction_id`, `audit_case_id`) resolve to existing resources
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/filing_get_unknown_id_not_found
        """
        res = api.get_filing(NON_EXISTENT_UUID, auditor_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_jurisdiction_create_missing_code_invalid_request(
            self, api, tax_manager_headers):
        """PRD §2.6: "**Structural well-formedness** — required fields
        present, enum values valid, integer types correct
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/errors/jurisdiction_create_missing_required_field_invalid_request
        """
        payload = create_jurisdiction_payload()
        del payload["code"]
        res = api.create_jurisdiction(payload, tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST,
                       expected_status=400)

    def test_tax_year_equal_period_dates_rejected(self, api,
                                                  tax_manager_headers):
        """PRD §3.1: "The end date must be after the start date, otherwise the
        create is rejected with `ERR_DATE_RANGE_INVALID`."

        Design: Corner/validations/invalid_date_range_rejected
        """
        payload = create_tax_year_payload(
            fiscal_year_label="FY-ZERO", period_start_date="2026-01-01",
            period_end_date="2026-01-01")
        res = api.create_tax_year(payload, tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_DATE_RANGE_INVALID,
                       expected_status=422)


class TestUniqueness:
    def test_duplicate_jurisdiction_code_rejected(self, api,
                                                  tax_manager_headers):
        """PRD §3.1: "Each carries a unique `code` such as `US-FED` or `US-CA`
        (a duplicate code is rejected with
        `ERR_DUPLICATE_JURISDICTION_CODE`)"

        Design: Corner/validations/duplicate_jurisdiction_code_rejected
        """
        validate_success(
            api.create_jurisdiction(create_jurisdiction_payload(),
                                    tax_manager_headers), 201)
        res = api.create_jurisdiction(
            create_jurisdiction_payload(name="Duplicate Federal"),
            tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_JURISDICTION_CODE,
                       expected_status=409)


class TestListPagination:
    def test_filing_list_limit_offset_and_meta(self, api, auditor_headers):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query
        parameters. `limit` defaults to 10, with a minimum of 1 and a maximum
        of 100; `offset` defaults to 0. List responses order by `created_at`
        ascending. The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/filing_list_pagination_and_envelope
        """
        ty = create_fy2026_tax_year()
        jur_fed = create_us_fed_jurisdiction()
        jur_ca = create_us_ca_jurisdiction()
        jur_il = create_us_il_jurisdiction()
        created = [
            create_filing_record(ty["id"], jur_fed["id"]),
            create_filing_record(ty["id"], jur_ca["id"]),
            create_filing_record(ty["id"], jur_il["id"]),
        ]

        page1, meta1 = validate_paginated(api.list_filings(
            auditor_headers,
            params={"tax_year_id": ty["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_filings(
            auditor_headers,
            params={"tax_year_id": ty["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        page_ids = {f["id"] for f in page1} | {f["id"] for f in page2}
        assert page_ids == {f["id"] for f in created}, \
            "the two pages must be disjoint and cover all three filings"


class TestReadSurfaceSweep:
    def test_child_entities_reachable_by_id_and_parent_filters(
            self, api, auditor_headers):
        """PRD §3.2: "Deferred tax items are system-generated and read-only;
        they are listed and fetched, with filters on `tax_year_id`,
        `source_difference_id`, and `item_kind`, but never written directly."
        PRD §4: list endpoints "List differences with optional filters", "List
        valuation allowances with optional filters", "List UTPs with optional
        filters", "List notices with optional filters", "List audits with
        optional filters".

        Design: Corner/entities/read_surface_sweep_and_fk_reverse_reachability
        """
        ty = create_fy2026_tax_year()
        jur = create_us_fed_jurisdiction()

        diff = create_locked_difference(ty["id"], jur["id"])
        va = create_draft_allowance(
            ty["id"], more_likely_than_not=True,
            projected_taxable_income_cents=1000000, reversing_dtl_cents=100000)
        utp = create_measured_position(ty["id"], jur["id"],
                                       position_amount_cents=2000000,
                                       cumulative_probability_bp=6000,
                                       description="R&D credit")
        notice = create_notice_record(jur["id"], received_on="2026-08-01",
                                      response_due_on="2026-12-31")
        audit = create_audit_record(ty["id"], jur["id"])

        diffs, _ = validate_paginated(api.list_book_tax_differences(
            auditor_headers, params={"tax_year_id": ty["id"]}))
        assert [d["id"] for d in diffs] == [diff["id"]]
        assert_book_tax_difference(diffs[0])
        got_diff = validate_success(
            api.get_book_tax_difference(diff["id"], auditor_headers), 200)
        assert got_diff["id"] == diff["id"]

        items, _ = validate_paginated(api.list_deferred_tax_items(
            auditor_headers, params={"source_difference_id": diff["id"]}))
        assert len(items) == 1
        got_item = validate_success(
            api.get_deferred_tax_item(items[0]["id"], auditor_headers), 200)
        assert got_item["id"] == items[0]["id"]

        vas, _ = validate_paginated(api.list_valuation_allowances(
            auditor_headers, params={"tax_year_id": ty["id"]}))
        assert [v["id"] for v in vas] == [va["id"]]

        utps, _ = validate_paginated(api.list_uncertain_tax_positions(
            auditor_headers, params={"jurisdiction_id": jur["id"]}))
        assert [u["id"] for u in utps] == [utp["id"]]

        notices, _ = validate_paginated(api.list_notices(
            auditor_headers, params={"jurisdiction_id": jur["id"]}))
        assert [n["id"] for n in notices] == [notice["id"]]
        got_notice = validate_success(
            api.get_notice(notice["id"], auditor_headers), 200)
        assert got_notice["id"] == notice["id"]

        audits, _ = validate_paginated(api.list_audits(
            auditor_headers, params={"tax_year_id": ty["id"]}))
        assert [a["id"] for a in audits] == [audit["id"]]
        got_audit = validate_success(
            api.get_audit(audit["id"], auditor_headers), 200)
        assert got_audit["id"] == audit["id"]
