"""Claims: creation defaults, validation, retrieval, listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, is_valid_uuid,
    ApiErrorId, make_manager_headers, make_compliance_headers,
    create_adjuster, create_claim, create_claim_payload,
    NON_EXISTENT_UUID,
)
from test_helpers.api_client import api_client


class TestClaimCreation:
    def test_claim_creation_defaults(self, api):
        """PRD §3.1: "An adjuster then registers a claim by supplying the insured's
        `policy_number`, the two-letter `state_code` that will govern the claim's
        bureau and delay rules, the owning `adjuster_id`, and the total
        `claimed_amount_cents`. A new claim starts in `PENDING` with
        `paid_amount_cents` at zero and `payment_hold_reason` unset."

        Design: Corner/entities/claim_creation_required_fields_and_defaults
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        resp = api_client.create_claim(
            create_claim_payload(adj["id"], claimed_amount_cents=1_000_000), ah)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING"
        assert data["paid_amount_cents"] == 0
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert data.get("payment_hold_reason") is None

    def test_claim_missing_required_field_returns_400(self, api):
        """PRD §2.6: "Structurally malformed requests — a missing required field,
        a wrong-typed value, or an enum value outside its allowed set — are rejected
        with `ERR_INVALID_REQUEST` (HTTP 400) as part of request parsing, before any
        business-rule evaluation."

        Design: Corner/entities/claim_missing_required_field_returns_invalid_request
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        payload = {"policy_number": "P-X", "state_code": "CA", "adjuster_id": adj["id"]}
        resp = api_client.create_claim(payload, ah)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_claim_state_code_must_be_two_letter(self, api):
        """PRD §3.1: "the two-letter `state_code` that will govern the claim's bureau
        and delay rules"
        PRD §2.6: "a wrong-typed value ... are rejected with `ERR_INVALID_REQUEST`
        (HTTP 400) as part of request parsing"

        Design: Corner/entities/claim_state_code_enum_constraint
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        resp = api_client.create_claim(
            create_claim_payload(adj["id"], state_code="CAL"), ah)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestClaimRetrieval:
    def test_claim_get_by_id_returns_stored_fields(self, api):
        """PRD §4: "GET | `/siu/claims/{claimId}` | Fetch claim"
        PRD §2.2: "operations that create or modify a resource will return the
        created or updated resource object in the data field."

        Design: Corner/entities/claim_get_by_id_returns_stored
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, state_code="NY", claimed_amount_cents=1_234_567)
        resp = api_client.get_claim(claim["id"], mh)
        data = validate_success(resp)
        assert data["policy_number"] == claim["policy_number"]
        assert data["state_code"] == "NY"
        assert data["claimed_amount_cents"] == 1_234_567

    def test_claim_get_non_existent_returns_404(self, api):
        """PRD §2.5: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not resolve."

        Design: Corner/entities/claim_get_non_existent_returns_not_found
        """
        mh = make_manager_headers()
        resp = api_client.get_claim(NON_EXISTENT_UUID, mh)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestClaimListing:
    def test_claim_list_returns_paginated_envelope(self, api):
        """PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."
        PRD §2.2: "The `response_type` is either \"object\" for a single resource
        or \"array\" for a list of resources."

        Design: Corner/entities/claim_list_pagination_envelope
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        create_claim(adj, state_code="CA", claimed_amount_cents=100)
        create_claim(adj, state_code="NY", claimed_amount_cents=200)
        create_claim(adj, state_code="FL", claimed_amount_cents=300)
        resp = api_client.list_claims(mh)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert len(data) == 3
        for f in ("limit", "offset", "total_count", "has_more"):
            assert f in meta, f"missing pagination field {f}"
