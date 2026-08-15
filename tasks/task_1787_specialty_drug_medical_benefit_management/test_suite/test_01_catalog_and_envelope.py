"""Catalog registration, request-shape rules, envelope and pagination (PRD §2.2,
§2.3, §2.8, §2.9, §3.1)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_drug,
    assert_spend_forecast_run,
    assert_timestamp_three_fractional,
    create_drug_payload,
    is_valid_uuid,
    make_provider_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCatalogRegistration:
    def test_drug_create_applies_documented_defaults(self, api, plan_admin_headers):
        """PRD §3.1: "`weight_based_dosing` defaults to false; when it is true, `mg_per_kg`
        must be present, and when false it must be absent".
        PRD §2.5: "Most resources carry four system-managed fields: `id`, a server-minted
        UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created; `updated_at`, in the
        same format, refreshed on every mutation; and `version`, a system-managed integer
        that increments with every mutation".

        Design: Corner/entities/drug_create_success_defaults
        """
        payload = create_drug_payload(j_code="J9000", drug_name="BaseDrug")
        payload.pop("weight_based_dosing", None)  # omitted -> default applies
        resp = api.create_drug(payload, plan_admin_headers)
        drug = validate_success(resp, 201)
        assert_drug(drug)
        assert drug["version"] == 1, f"new drug version must be 1, got {drug['version']}"
        assert drug["weight_based_dosing"] is False
        assert drug.get("mg_per_kg") is None, "mg_per_kg must be absent/null when not weight-based"
        assert_timestamp_three_fractional(drug["created_at"])
        assert_timestamp_three_fractional(drug["updated_at"])

        # The single-drug read returns the same representation (PRD §3.1).
        reread = validate_success(api.get_drug(drug["id"], plan_admin_headers))
        assert reread["id"] == drug["id"]
        assert reread["version"] == 1

    def test_drug_missing_j_code_rejected(self, api, plan_admin_headers):
        """PRD §2.8: "Shape failures surface as `ERR_INVALID_REQUEST` and always precede
        existence checks." PRD §3.1: registration names "the HCPCS `j_code` — unique
        across all drugs, so a duplicate registration is rejected with
        `ERR_JCODE_NOT_UNIQUE`" — the code is a required field of the payload.

        Design: Corner/entities/drug_missing_required_field_rejected
        """
        payload = create_drug_payload(j_code="J9001", drug_name="NoCode")
        payload.pop("j_code")
        resp = api.create_drug(payload, plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_duplicate_j_code_and_bad_vial_ratio_rejected(
        self, api, plan_admin_headers
    ):
        """PRD §3.1: "the HCPCS `j_code` — unique across all drugs, so a duplicate
        registration is rejected with `ERR_JCODE_NOT_UNIQUE`".
        PRD §3.1: "`vial_size_mg`, the single-vial size, which must be a positive whole
        multiple of the billing unit or registration fails with
        `ERR_INVALID_VIAL_UNIT_RATIO`".

        Design: Corner/entities/catalog_registration_guards
        """
        first = validate_success(
            api.create_drug(create_drug_payload(j_code="J8000", drug_name="FirstDrug"), plan_admin_headers),
            201,
        )
        assert_drug(first)

        dup = api.create_drug(
            create_drug_payload(j_code="J8000", drug_name="DupDrug"), plan_admin_headers
        )
        validate_error(dup, ApiErrorId.ERR_JCODE_NOT_UNIQUE, 409)

        bad_vial = api.create_drug(
            create_drug_payload(j_code="J8001", drug_name="BadVial", vial_size_mg=105),
            plan_admin_headers,
        )
        validate_error(bad_vial, ApiErrorId.ERR_INVALID_VIAL_UNIT_RATIO, 422)


class TestRequestShapeAndEnvelope:
    def test_claim_with_unknown_site_enum_rejected_as_shape_error(self, api):
        """PRD §2.8: "required fields present, types correct, enum members valid ... Shape
        failures surface as `ERR_INVALID_REQUEST` and always precede existence checks."

        Design: Corner/entities/claim_invalid_enum_rejected
        """
        payload = {
            "auth_id": NON_EXISTENT_UUID,
            "drug_id": NON_EXISTENT_UUID,
            "service_date": "2026-08-01",
            "site_of_care": "spaceship",
            "sourcing_path": "BUY_AND_BILL",
            "j_code_billed": "J0000",
            "billed_units": 1,
        }
        resp = api.create_claim(payload, make_provider_rep_headers(NON_EXISTENT_UUID))
        # 400 shape failure, not 404: shape precedes existence (PRD §2.8).
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_get_unknown_claim_returns_error_envelope(self, api, plan_admin_headers):
        """PRD §2.9: "the system validates their existence in a strict left-to-right order
        and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier
        that names no existing resource".
        PRD §2.2: error responses carry "response_type": "error" and a data object with
        `error_id` and `message`; meta contains only api_request_id and
        api_request_timestamp.

        Design: Corner/entities/get_nonexistent_claim_returns_not_found
        """
        unknown = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
        resp = api.get_claim(unknown, plan_admin_headers)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert error["error_id"] == "ERR_NOT_FOUND"
        assert error["message"].strip()

    def test_missing_user_context_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or naming a role outside this
        declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/rbac/missing_auth_header_rejected
        """
        resp = api.list_drugs(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

        # A role outside the declared set is rejected the same way.
        resp2 = api.list_drugs(headers={"X-User-ID": "x-1", "X-User-Role": "SuperUser"})
        validate_error(resp2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestPagination:
    def test_drug_list_pagination_contract(
        self, api, plan_admin_headers, pharmacy_analyst_headers
    ):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults
        to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies
        how many items to skip and defaults to 0." List responses carry the pagination
        fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object.

        Design: Corner/endpoints/list_pagination_and_envelope
        """
        for code, name in [("J7001", "PgA"), ("J7002", "PgB"), ("J7003", "PgC")]:
            validate_success(
                api.create_drug(
                    create_drug_payload(j_code=code, drug_name=name), plan_admin_headers
                ),
                201,
            )

        resp1 = api.list_drugs(pharmacy_analyst_headers, params={"limit": 2, "offset": 0})
        assert resp1.json()["response_type"] == "array", "list envelope type (PRD §2.2)"
        page1, meta1 = validate_paginated(resp1)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_drugs(pharmacy_analyst_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        default_page, default_meta = validate_paginated(
            api.list_drugs(pharmacy_analyst_headers)
        )
        assert default_meta["limit"] == 10, "default limit is 10 (PRD §2.3)"
        assert default_meta["offset"] == 0
        assert len(default_page) == 3
        assert default_meta["has_more"] is False
        assert all(is_valid_uuid(d["id"]) for d in default_page)


class TestForecastSnapshotShape:
    def test_forecast_run_is_immutable_snapshot_without_version(
        self, api, pharmacy_analyst_headers
    ):
        """PRD §2.5: "Two resources are immutable records and deliberately carry only `id`
        and `created_at`: the claim adjustment, an append-only repricing event, and the
        spend-forecast run, a computed snapshot. Neither has `updated_at` nor `version`,
        because neither is ever modified after creation."
        PRD §3.8: "Completed runs are readable by all roles."

        Design: Corner/entities/forecast_run_immutable_no_version
        """
        resp = api.create_spend_forecast(
            {"variant": "BASELINE", "horizon_years": 1, "enrollment_projection": 500000},
            pharmacy_analyst_headers,
        )
        run = validate_success(resp, 201)
        assert_spend_forecast_run(run)
        assert "version" not in run, "spend-forecast run must not carry version"
        assert "updated_at" not in run, "spend-forecast run must not carry updated_at"
        # Empty registry and no paid/adjusted claims -> all totals zero (PRD §3.8).
        assert run["pipeline_total_cents"] == 0
        assert run["inline_annualized_cents"] == 0
        assert run["total_projected_cents"] == 0
        assert run["per_drug_projections"] == []

        reread = validate_success(api.get_spend_forecast(run["id"], pharmacy_analyst_headers))
        assert reread == run, "stored snapshot re-reads identically (immutable)"
