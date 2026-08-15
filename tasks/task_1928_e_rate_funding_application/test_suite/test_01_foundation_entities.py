"""Foundation entities: creation defaults, computed snapshot share, envelope
shapes, conditional required fields, pagination (PRD §2.2, §2.3, §3.1, §3.2)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    new_applicant,
    new_cycle,
    new_request,
    setup_applicant_base,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPostingCreationDefaults:
    def test_posting_creation_defaults_applied(self, api):
        """PRD §3.3: "New postings start in `DRAFT` status with `posted_at` null
        and `selected_bid_id` unset."
        PRD §3.3: "it must be at least the `weight_pct` of every entry in
        `other_factor_weights` (an optional list of `{ factor_name, weight_pct }`
        records that defaults to an empty list)."

        Design: Corner/entities/posting_creation_defaults_applied
        """
        ctx = setup_applicant_base(with_snapshot=False)
        payload = {
            "applicant_id": ctx["applicant"]["id"],
            "funding_cycle_id": ctx["cycle"]["id"],
            "category": "CATEGORY_ONE",
            "description": "Internet access",
            "price_weight_pct": 100,
            # other_factor_weights deliberately omitted — the default applies
        }
        data = validate_success(
            api.create_procurement_posting(payload, ctx["coord_headers"]), 201
        )
        assert data["status"] == "DRAFT", f"new posting must start DRAFT, got {data['status']}"
        assert data["other_factor_weights"] == [], (
            f"omitted other_factor_weights must default to [], got {data['other_factor_weights']}"
        )
        assert data["posted_at"] is None, "posted_at must be null while DRAFT"
        assert data["selected_bid_id"] is None, "selected_bid_id must be unset while DRAFT"


class TestSnapshotComputedShare:
    def test_snapshot_computed_share_ignores_no_input(self, api, admin_headers):
        """PRD §3.2: "At recording time the server computes the snapshot's
        `effective_share_pct`" and "When `cep_participating` is false, the share is
        100 times `free_lunch_eligible_students` divided by `total_students`,
        rounded half up to two decimal places."
        PRD §2.10: "unknown or missing fields, bad enum members, non-positive
        amounts, malformed dates, and violated conditional-field rules all yield
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/snapshot_computed_share_ignores_no_input
        """
        cycle = new_cycle()
        applicant = new_applicant()

        snap = validate_success(
            api.create_nslp_snapshot(
                {
                    "applicant_id": applicant["id"],
                    "funding_cycle_id": cycle["id"],
                    "total_students": 1000,
                    "free_lunch_eligible_students": 300,
                    "cep_participating": False,
                },
                admin_headers,
            ),
            201,
        )
        assert snap["effective_share_pct"] == pytest.approx(30.0, abs=1e-9), (
            f"300/1000 direct snapshot must compute share 30.00, "
            f"got {snap['effective_share_pct']}"
        )

        # A client-supplied value for the computed field is an unknown field.
        resp = api.create_nslp_snapshot(
            {
                "applicant_id": applicant["id"],
                "funding_cycle_id": cycle["id"],
                "total_students": 1000,
                "free_lunch_eligible_students": 300,
                "cep_participating": False,
                "effective_share_pct": 99.99,
            },
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFoundAndShapeValidation:
    def test_get_funding_request_not_found_returns_404(self, api, admin_headers):
        """PRD §2.10: "**Referenced-id existence** — every identifier in the path
        and body must exist, validated left to right: path parameters first, then
        body fields in their declared order. The first missing identifier yields
        `ERR_NOT_FOUND`."
        PRD §5: `ERR_NOT_FOUND` maps to 404 Not Found.

        Design: Corner/entities/get_funding_request_not_found_returns_404
        """
        resp = api.get_funding_request(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_applicant_invalid_enum_returns_invalid_request(self, api, admin_headers):
        """PRD §3.1: "Applicant registration captures the billed entity's `name`,
        an `entity_type` of `SCHOOL` or `LIBRARY`, and an `urban_rural` designation
        of `URBAN` or `RURAL` — the last of these matters later, because the
        discount matrix keys on it."
        PRD §2.10: "unknown or missing fields, bad enum members, non-positive
        amounts, malformed dates, and violated conditional-field rules all yield
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_applicant_invalid_enum_returns_invalid_request
        """
        resp = api.create_applicant(
            {
                "name": "Charter Academy",
                "entity_type": "CHARTER",
                "urban_rural": "URBAN",
                "student_count": 400,
            },
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_school_missing_student_count_returns_invalid_request(self, api, admin_headers):
        """PRD §3.1: "a `SCHOOL` must supply `student_count` greater than zero,
        while a `LIBRARY` must instead supply `square_feet` greater than zero;
        omitting the required measure is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_school_missing_student_count_returns_invalid_request
        """
        resp = api.create_applicant(
            {"name": "No Count USD", "entity_type": "SCHOOL", "urban_rural": "RURAL"},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPagination:
    def test_funding_cycle_list_pagination(self, api, admin_headers):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter sets the number of items skipped and defaults to 0."
        PRD §2.3: "List responses carry four pagination fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/funding_cycle_list_pagination
        """
        new_cycle(label="FY2026", window_open_date="2025-10-01",
                  window_close_date="2026-03-31", service_delivery_deadline="2026-06-30")
        new_cycle(label="FY2027")
        new_cycle(label="FY2028", window_open_date="2027-10-01",
                  window_close_date="2028-03-31", service_delivery_deadline="2028-06-30")

        page1, meta1 = validate_paginated(
            api.list_funding_cycles(admin_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2, f"limit=2 must return 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_funding_cycles(admin_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1, f"offset=2 over 3 rows must return 1 row, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api, admin_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with `response_type` "error", a `data` object
        carrying `error_id` and `message`, and "The `meta` object for error
        responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_contract(NON_EXISTENT_UUID, admin_headers)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error_data["message"].strip(), "error message must be non-empty"
        body = resp.json()
        request_id = body["meta"]["api_request_id"]
        assert isinstance(request_id, str) and request_id.startswith("req_"), (
            f"meta.api_request_id must be present and start with 'req_', got {request_id!r}"
        )


class TestFundingRequestInitialState:
    def test_request_initial_state_draft(self, api):
        """PRD §3.5: "created with just `applicant_id` and `funding_cycle_id`,
        starting in `DRAFT` status with `services_started` false, an empty
        `pia_reviewer_user_ids` list, and the computed discount fields
        (`nslp_share_pct`, `discount_rate_c1_pct`, `discount_rate_c2_pct`) null."

        Design: Corner/state_machines/request_initial_state_draft
        """
        ctx = setup_applicant_base(with_snapshot=False)
        request = new_request(ctx)
        assert request["status"] == "DRAFT"
        assert request["services_started"] is False
        assert request["pia_reviewer_user_ids"] == []
        assert request["nslp_share_pct"] is None
        assert request["discount_rate_c1_pct"] is None
        assert request["discount_rate_c2_pct"] is None
