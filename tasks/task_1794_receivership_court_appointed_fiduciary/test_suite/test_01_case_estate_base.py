"""Case creation, computed reads, envelope contract, not-found."""
from test_helpers import (
    COURT,
    CREDITOR,
    RECEIVER,
    UNKNOWN_ROLE_HEADERS,
    ApiErrorId,
    assert_case,
    create_case,
    create_case_payload,
    create_claim,
    create_asset,
    determine_claim,
    get_case,
    liquidate_asset,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCaseCreation:
    def test_case_creation_returns_active_with_zeroed_computed_fields(self, api):
        """PRD §3.1: "A newly created case starts in `ACTIVE` status with
        `cash_on_hand_cents`, `marshalled_value_cents`, and
        `allowed_claims_total_cents` all zero, `posture` equal to `NORMAL`,
        and `version` 1."

        Design: Corner/entities/case_creation_returns_active_with_zeroed_computed_fields
        """
        resp = api.create_case(create_case_payload(), COURT)
        data = validate_success(resp, 201)
        assert_case(data)
        assert data["status"] == "ACTIVE"
        assert data["cash_on_hand_cents"] == 0
        assert data["marshalled_value_cents"] == 0
        assert data["allowed_claims_total_cents"] == 0
        assert data["posture"] == "NORMAL"
        assert data["report_overdue"] is False
        assert data["version"] == 1

    def test_case_creation_missing_required_field_returns_400(self, api):
        """PRD §2.10: "Request shape: required fields are present, types are
        valid, enum values are in range, and conditional requirements are
        satisfied"
        PRD §2.10: "Any failure here is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/case_creation_missing_required_field_returns_400
        """
        payload = create_case_payload()
        del payload["debtor_name"]
        resp = api.create_case(payload, COURT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_case_computed_field_input_ignored(self, api):
        """PRD §3.1: "A newly created case starts in `ACTIVE` status with
        `cash_on_hand_cents`, `marshalled_value_cents`, and
        `allowed_claims_total_cents` all zero, `posture` equal to `NORMAL`,
        and `version` 1."

        Design: Corner/entities/case_computed_field_input_ignored
        """
        payload = create_case_payload()
        payload["cash_on_hand_cents"] = 999999
        resp = api.create_case(payload, COURT)
        data = validate_success(resp, 201)
        assert data["cash_on_hand_cents"] == 0, (
            "client-supplied computed field must be ignored; initialized to 0"
        )

    def test_get_case_unknown_id_returns_404(self, api):
        """PRD §2.9: "A path identifier or referenced foreign key that does
        not exist, or that exists outside the implied scope, is rejected with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_case_unknown_id_returns_404
        """
        resp = api.get_case("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", RECEIVER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_duplicate_case_number_rejected(self, api):
        """PRD §3.1: "The `case_number` must be unique within its
        `court_jurisdiction`; a second case filed with the same number in the
        same jurisdiction is rejected with `ERR_DUPLICATE_CASE_NUMBER`."

        Design: Corner/validations/duplicate_case_number_rejected
        """
        create_case(case_number="2026-CV-3023")
        resp = api.create_case(
            create_case_payload(case_number="2026-CV-3023", debtor_name="Other Debtor Inc"),
            COURT,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE_NUMBER)


class TestCaseComputedRead:
    def test_get_case_computed_read_reflects_mutations(self, api):
        """PRD §2.4: "The `allowed_claims_total_cents` is the sum of
        `allowed_amount_cents` over the case's claims currently in `ALLOWED`
        status."
        PRD §2.4: "The `marshalled_value_cents` is the sum, over every asset
        of the case that is not `ABANDONED`, of the asset's
        `liquidation_value_cents` when the asset is `LIQUIDATED` and of its
        `estimated_value_cents` otherwise."

        Design: Corner/endpoints/get_case_computed_read_reflects_mutations
        """
        case = create_case()
        asset = create_asset(case["id"], asset_class="CASH", estimated_value_cents=150000)
        claim = create_claim(case["id"], creditor_name="Trade Supplier",
                             creditor_type="GENERAL_UNSECURED", filed_amount_cents=90000)
        liquidate_asset(asset["id"], 150000)
        determine_claim(claim["id"], "ALLOWED", 90000)

        data = get_case(case["id"])
        assert data["cash_on_hand_cents"] == 150000
        assert data["marshalled_value_cents"] == 150000
        assert data["allowed_claims_total_cents"] == 90000


class TestResponseEnvelope:
    def test_post_case_response_envelope_contract(self, api):
        """PRD §2.2: "The `response_type` is either \"object\" for a single
        resource or \"array\" for a list of resources."
        PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned: it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. The `offset` parameter sets the number of items
        skipped and defaults to 0."

        Design: Corner/endpoints/post_case_response_envelope_contract
        """
        case = create_case()

        obj = api.get_case(case["id"], RECEIVER).json()
        assert "api_request_id" in obj["meta"]
        assert "api_request_timestamp" in obj["meta"]
        assert obj["response_type"] == "object"

        lst = api.list_claims(RECEIVER, {"case_id": case["id"]}).json()
        assert lst["response_type"] == "array"
        assert lst["meta"]["limit"] == 10
        assert lst["meta"]["offset"] == 0
        assert lst["meta"]["total_count"] == 0
        assert lst["meta"]["has_more"] is False


class TestUnknownRole:
    def test_request_with_unknown_role_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does
        not name one of these four roles is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/request_with_unknown_role_returns_unauthenticated
        """
        resp = api.create_case(create_case_payload(), UNKNOWN_ROLE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
