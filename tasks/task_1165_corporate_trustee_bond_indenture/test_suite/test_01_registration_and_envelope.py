"""Registration surface: creation defaults, envelope shape, field discipline,
principal cap, pagination (PRD §2.2–§2.4, §3.1–§3.2)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_valid_uuid, ApiErrorId, NON_EXISTENT_UUID,
    assert_indenture, assert_tranche, assert_noteholder_account,
    assert_iso8601_ms_utc,
    create_indenture_payload, create_tranche_payload,
    create_noteholder_account_payload, create_position_payload,
    create_active_indenture_with_tranche, register_account, register_position,
    make_platform_admin_headers, make_trust_officer_headers,
)

ADMIN = make_platform_admin_headers("admin-1")


class TestIndentureCreation:
    def test_indenture_creation_initializes_computed_fields(self, api):
        """PRD §3.1: "A new indenture is `DRAFT`, with
        `outstanding_principal_cents` initialized to zero, `covenant_posture`
        initialized to `CURRENT`, and `active_default_count` initialized to
        zero."

        Design: Corner/entities/indenture_creation_defaults_and_computed_initialization
        """
        resp = api.create_indenture(create_indenture_payload(name="I1"), ADMIN)
        data = validate_success(resp, 201)
        assert_indenture(data)
        assert data["status"] == "DRAFT"
        assert data["outstanding_principal_cents"] == 0
        assert data["covenant_posture"] == "CURRENT"
        assert data["active_default_count"] == 0

        fetched = validate_success(api.get_indenture(data["id"], ADMIN))
        assert fetched["status"] == "DRAFT"
        assert fetched["outstanding_principal_cents"] == 0
        assert fetched["covenant_posture"] == "CURRENT"
        assert fetched["active_default_count"] == 0

    def test_client_supplied_computed_fields_are_ignored(self, api):
        """PRD §2.10: "Derived fields — `outstanding_principal_cents`,
        `covenant_posture`, `active_default_count`, `total_unpaid_cents`,
        `total_received_cents`, `eligible_principal_cents`,
        `supporting_principal_cents`, `consenting_principal_cents` — are never
        written by clients; they are recomputed by the server at the moments
        §3 specifies"
        PRD §2.4: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix."

        Design: Corner/entities/computed_and_system_fields_input_ignored
        """
        payload = create_indenture_payload(name="I1")
        payload["status"] = "ACTIVE"
        payload["outstanding_principal_cents"] = 999999999
        payload["covenant_posture"] = "BREACH"
        payload["active_default_count"] = 7
        resp = api.create_indenture(payload, ADMIN)
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT", "server-computed status governs"
        assert data["outstanding_principal_cents"] == 0
        assert data["covenant_posture"] == "CURRENT"
        assert data["active_default_count"] == 0
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
        assert_iso8601_ms_utc(data["created_at"], "created_at")

    def test_create_indenture_missing_required_field_rejected(self, api):
        """PRD §2.8: "Request shape: required fields present, enum values
        valid, dates well-formed ISO — `ERR_INVALID_REQUEST`."
        PRD §3.1 lists `annual_admin_fee_cents` among the creation parameters.

        Design: Corner/entities/missing_required_field_returns_invalid_request
        """
        payload = create_indenture_payload(name="I1")
        del payload["annual_admin_fee_cents"]
        resp = api.create_indenture(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestTrancheCreation:
    def test_tranche_and_obligation_defaults_applied_when_omitted(self, api):
        """PRD §3.1: "optionally `notice_period_days`, which defaults to 30
        when omitted and later governs redemption notice."
        PRD §3.3: "an optional `grace_period_days` defaulting to 10."

        Design: Corner/entities/field_defaults_applied_when_omitted
        """
        indenture, tranche = create_active_indenture_with_tranche(
            indenture_overrides={"name": "I1"},
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
        )
        assert tranche["notice_period_days"] == 30, "default notice period"
        assert_tranche(tranche)

        officer = make_trust_officer_headers("officer-1")
        resp = api.create_covenant_obligation(
            {
                "indenture_id": indenture["id"],
                "covenant_type": "FINANCIAL_REPORT",
                "frequency": "QUARTERLY",
                "period_anchor_date": "2026-06-30",
            },
            officer,
        )
        obligation = validate_success(resp, 201)
        assert obligation["grace_period_days"] == 10, "default grace period"

    def test_tranche_invalid_day_count_enum_rejected(self, api):
        """PRD §3.1: "the `day_count_convention` — one of `ACT_360`,
        `ACT_365`, or `THIRTY_360`"
        PRD §2.8: "Request shape: required fields present, enum values valid,
        dates well-formed ISO — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/invalid_enum_value_returns_invalid_request
        """
        resp = api.create_indenture(create_indenture_payload(name="I1"), ADMIN)
        ind = validate_success(resp, 201)
        payload = create_tranche_payload(ind["id"], day_count_convention="ACT_ACT")
        resp = api.create_tranche(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_unknown_tranche_returns_not_found(self, api):
        """PRD §2.9: "rejects the request with `ERR_NOT_FOUND` (HTTP 404) at
        the **first** identifier that does not resolve to an existing resource"

        Design: Corner/entities/get_nonexistent_tranche_returns_not_found
        """
        resp = api.get_tranche(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPositionsAndCap:
    def test_position_aggregate_principal_cap_boundary(self, api):
        """PRD §3.2: "the sum of `original_principal_cents` across all
        positions of a tranche must not exceed the tranche's
        `original_principal_cents`, and a registration that would breach the
        cap is rejected with `ERR_PRINCIPAL_EXCEEDS_POSITION` (HTTP 422)."

        Design: Corner/validations/aggregate_position_principal_cap_boundary
        """
        indenture, tranche = create_active_indenture_with_tranche(
            indenture_overrides={"name": "I1"},
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
        )
        account = register_account("H-A", "Holder A", "a@x.com")
        first = validate_success(api.create_position(
            create_position_payload(tranche["id"], account["id"], 399999999), ADMIN), 201)
        # Exactly at the cap: 399999999 + 1 == 400000000 — allowed.
        second = validate_success(api.create_position(
            create_position_payload(tranche["id"], account["id"], 1), ADMIN), 201)
        assert second["principal_amount_cents"] == 1
        # One cent beyond the cap: rejected.
        resp = api.create_position(
            create_position_payload(tranche["id"], account["id"], 1), ADMIN)
        validate_error(resp, ApiErrorId.ERR_PRINCIPAL_EXCEEDS_POSITION)


class TestListingAndEnvelope:
    def test_noteholder_account_list_pagination(self, api):
        """PRD §2.3: "The `meta` object of a list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned: it defaults to 10, with a minimum of 1 and a maximum of 100."

        Design: Corner/entities/noteholder_account_list_pagination
        """
        for i in range(1, 13):
            register_account(f"H-{i:02d}", f"H{i}", f"h{i}@x.com")

        page1, meta1 = validate_paginated(
            api.list_noteholder_accounts(ADMIN, params={"limit": 10, "offset": 0}))
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert len(page1) == 10
        for account in page1:
            assert_noteholder_account(account)

        page2, meta2 = validate_paginated(
            api.list_noteholder_accounts(ADMIN, params={"limit": 10, "offset": 10}))
        assert meta2["has_more"] is False
        assert len(page2) == 2

    def test_indenture_computed_read_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §3.1: "its creation recomputes the parent indenture's
        `outstanding_principal_cents`, which is always the sum of the
        outstanding principal of its tranches."

        Design: Corner/endpoints/indenture_computed_read_and_envelope_shape
        """
        indenture, tranche = create_active_indenture_with_tranche(
            indenture_overrides={"name": "I1"},
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
        )
        account = register_account("H-A", "Holder A", "a@x.com")
        register_position(tranche["id"], account["id"], 400000000)

        resp = api.get_indenture(indenture["id"], ADMIN)
        body = resp.json()
        assert resp.status_code == 200
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["response_type"] == "object"
        data = body["data"]
        assert_indenture(data)
        assert data["outstanding_principal_cents"] == 400000000
        assert data["covenant_posture"] == "CURRENT"
        assert data["active_default_count"] == 0
        assert data["current_trustee_ref"] == "trustee-alpha"
