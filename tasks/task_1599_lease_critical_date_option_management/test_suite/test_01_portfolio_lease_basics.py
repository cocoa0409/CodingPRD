"""Portfolio and lease basics: creation defaults, required fields, pagination,
and not-found handling."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_lease,
    assert_portfolio,
    create_lease_payload,
    create_portfolio_payload,
    get_success_data,
    is_valid_uuid,
    setup_active_lease,
    setup_portfolio_with_contacts,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestPortfolioCreation:
    def test_create_portfolio_returns_defaults(self, api):
        """PRD §3.1: "A fresh portfolio reports `total_active_square_feet` of zero,
        a `posture` of `LADDER_OK`, and a null `posture_year`."
        PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/create_portfolio_returns_defaults
        """
        resp = api.create_portfolio(
            create_portfolio_payload(name="Corner P1", region="WEST",
                                     laddering_max_pct_per_year=35),
            ADMIN,
        )
        portfolio = validate_success(resp, 201)
        assert_portfolio(portfolio)
        assert portfolio["posture"] == "LADDER_OK"
        assert portfolio["total_active_square_feet"] == 0
        assert portfolio["posture_year"] is None
        assert portfolio["version"] == 1
        assert is_valid_uuid(portfolio["id"]), "id is a bare UUID with no type prefix"

        fetched = validate_success(api.get_portfolio(portfolio["id"], ADMIN))
        assert fetched["posture"] == "LADDER_OK"
        assert fetched["total_active_square_feet"] == 0
        assert fetched["posture_year"] is None


class TestLeaseCreation:
    def test_create_lease_missing_required_field_returns_400(self, api):
        """PRD §2.10: "a malformed body — a missing required field, a wrong-typed
        value, or an enum outside its declared set — is rejected with
        `ERR_VALIDATION` (HTTP 400)."
        PRD §3.2: "the covered `rentable_square_feet`, which must be greater than
        zero"

        Design: Corner/entities/create_lease_missing_required_field_returns_400
        """
        ws = setup_portfolio_with_contacts(name="P2", region="EAST")
        payload = create_lease_payload(
            premises_label="X",
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2027-12-31T00:00:00Z",
            holdover_tier1_pct=150,
            holdover_tier2_pct=200,
        )
        del payload["rentable_square_feet"]
        resp = api.create_lease(ws["pid"], payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        _data, meta = validate_paginated(api.list_leases(ws["pid"], ADMIN))
        assert meta["total_count"] == 0, "No lease may be persisted by the rejected create"

    def test_holdover_tier1_days_default_applies(self, api):
        """PRD §3.2: "`holdover_tier1_days` sets the first tier's length in days,
        defaulting to 90 when omitted."
        PRD §3.2: "A new lease starts in `DRAFT` with `accrued_holdover_rent_cents`
        at zero and `active_amendment_id` null."

        Design: Corner/entities/holdover_tier1_days_default_applies
        """
        ws = setup_portfolio_with_contacts(name="P3", region="WEST")
        payload = create_lease_payload(
            premises_label="D",
            rentable_square_feet=5000,
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2027-12-31T00:00:00Z",
            holdover_tier1_pct=150,
            holdover_tier2_pct=200,
        )
        resp = api.create_lease(ws["pid"], payload, ADMIN)
        lease = validate_success(resp, 201)
        assert_lease(lease)
        assert lease["holdover_tier1_days"] == 90, "holdover_tier1_days defaults to 90"
        assert lease["status"] == "DRAFT"
        assert lease["accrued_holdover_rent_cents"] == 0
        assert lease["active_amendment_id"] is None

    def test_get_lease_with_unknown_id_returns_404(self, api):
        """PRD §2.6: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at
        the first identifier that does not exist or is not nested beneath its
        declared parent"

        Design: Corner/entities/get_lease_with_unknown_id_returns_404
        """
        ws = setup_portfolio_with_contacts(name="P4", region="WEST")
        resp = api.get_lease(ws["pid"], NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestLeaseListing:
    def test_list_leases_pagination_envelope(self, api):
        """PRD §2.2: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §2.3: "`limit` ... defaults to 10 when omitted ... `offset` ...
        defaults to 0."

        Design: Corner/entities/list_leases_pagination_envelope
        """
        ws = setup_portfolio_with_contacts(name="P5", region="WEST")
        payload = create_lease_payload(
            premises_label="L1",
            rentable_square_feet=5000,
            base_rent_cents_per_rsf_year=4000,
            commencement_date="2026-01-01T00:00:00Z",
            expiration_date="2027-12-31T00:00:00Z",
            holdover_tier1_pct=150,
            holdover_tier2_pct=200,
        )
        get_success_data(api.create_lease(ws["pid"], payload, ADMIN))

        resp = api.list_leases(ws["pid"], ADMIN)
        body = resp.json()
        assert "meta" in body and "api_request_id" in body["meta"], (
            "envelope.meta.api_request_id is present"
        )
        assert body.get("response_type") == "array"
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(data) == 1
