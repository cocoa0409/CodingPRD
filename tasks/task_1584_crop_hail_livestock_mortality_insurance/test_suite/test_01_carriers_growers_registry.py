"""Carrier onboarding, grower registry, and identity-header enforcement
(PRD §2.1, §2.5, §2.6, §3.1)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_carrier,
    assert_grower,
    assert_timestamp_equals,
    create_carrier_payload,
    create_grower_payload,
    make_policyholder_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestCarrierOnboarding:
    def test_carrier_creation_returns_201_and_default_clock(self, api):
        """PRD §2.5: "The clock starts at `2026-08-01T00:00:00Z` when the carrier
        is created and advances only when an `Underwriter` invokes the carrier's
        clock-setting capability with a `to_iso8601` timestamp; it never moves on
        its own."
        PRD §4: "Operations that create a new resource — a carrier, grower,
        adjuster, rate-table row, federal crop policy, policy, coverage unit,
        acreage or head report, claim, field inspection, veterinary report, loss
        determination, indemnity payment, dual coverage link, renewal, or premium
        payment — return `201 Created`."

        Design: Corner/entities/carrier_creation_returns_201_and_default_clock
        """
        res = api.create_carrier(
            create_carrier_payload(
                carrier_code="CHL-Z1", legal_name="C1",
                reinsurance_treaty_attachment_cents=1_000_000,
            ),
            ADMIN,
        )
        carrier = validate_success(res, 201)
        assert_carrier(carrier)
        assert_timestamp_equals(
            carrier["current_utc"], "2026-08-01T00:00:00Z", "current_utc"
        )

    def test_get_carrier_with_nonexistent_id_returns_404(self, api):
        """PRD §2.6: "The server validates these identifiers in a strict
        left-to-right order: the first identifier in the path that does not
        correspond to an existing resource produces a `404 Not Found` rejection
        with `ERR_NOT_FOUND`, and no further validation is attempted."

        Design: Corner/entities/get_carrier_with_nonexistent_id_returns_404
        """
        res = api.get_carrier(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestGrowerRegistry:
    def test_grower_creation_missing_required_email_returns_invalid_request(self, api):
        """PRD §2.9: "Independently of this pipeline, malformed payloads — a
        missing required field, a value of the wrong type, or an enum value
        outside the declared set — are rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."
        PRD §3.1: "An `Underwriter` registers each insured grower with a
        `full_name`, the `tax_id_last4` (the last four digits of the grower's SSN
        or EIN, which serve as the registry's duplicate-guard key), a contact
        `email`, and the grower's primary `county_code` (a five-character FIPS
        code) and two-letter `state_code`."

        Design: Corner/entities/grower_creation_missing_required_email_returns_invalid_request
        """
        carrier = validate_success(
            api.create_carrier(create_carrier_payload(carrier_code="CHL-Z2"), ADMIN), 201
        )
        payload = create_grower_payload()
        del payload["email"]
        res = api.create_grower(carrier["id"], payload, UW)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_grower_default_status_is_active(self, api):
        """PRD §3.1: "A newly registered grower's `status` begins `ACTIVE` and
        its `prior_claims_count` begins at zero; the count tracks the grower's
        claims in `APPROVED` or `PAID` status across all of that grower's
        policies and drives the high-risk surcharge described in §3.4."

        Design: Corner/entities/grower_default_status_is_active
        """
        carrier = validate_success(
            api.create_carrier(create_carrier_payload(carrier_code="CHL-Z3"), ADMIN), 201
        )
        res = api.create_grower(carrier["id"], create_grower_payload(), UW)
        grower = validate_success(res, 201)
        assert_grower(grower)
        assert grower["status"] == "ACTIVE"
        assert grower["prior_claims_count"] == 0

    def test_list_growers_pagination_default_limit(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/entities/list_growers_pagination_default_limit
        """
        carrier = validate_success(
            api.create_carrier(create_carrier_payload(carrier_code="CHL-Z6"), ADMIN), 201
        )
        for i in range(12):
            validate_success(
                api.create_grower(
                    carrier["id"],
                    create_grower_payload(
                        full_name=f"Grower {i:02d}", tax_id_last4=f"{i:04d}",
                        email=f"g{i}@x.com",
                    ),
                    UW,
                ),
                201,
            )
        data, meta = validate_paginated(api.list_growers(carrier["id"], UW))
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert len(data) == 10
        assert meta["total_count"] == 12
        assert meta["has_more"] is True


class TestIdentityHeaders:
    def test_missing_auth_headers_returns_invalid_user_context(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act. A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_invalid_user_context
        """
        carrier = validate_success(
            api.create_carrier(create_carrier_payload(carrier_code="CHL-V1"), ADMIN), 201
        )
        res = api.get_carrier(carrier["id"], headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_invalid_role_returns_insufficient_permissions(self, api):
        """PRD §2.1: "Once the identity headers are accepted, the caller's role
        must appear in the target endpoint's authorized role list; otherwise the
        request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST /carriers/{carrierId}/rate-tables is authorized for
        Underwriter only.

        Design: Corner/errors/invalid_role_returns_insufficient_permissions
        """
        carrier = validate_success(
            api.create_carrier(create_carrier_payload(carrier_code="CHL-ER1"), ADMIN), 201
        )
        grower = validate_success(
            api.create_grower(carrier["id"], create_grower_payload(), UW), 201
        )
        payload = {
            "rating_kind": "CROP_HAIL", "county_code": "06001", "crop_code": "CORN",
            "rate_per_100_cents_of_liability": 333,
            "effective_from": "2026-01-01T00:00:00Z",
        }
        res = api.create_rate_table(
            carrier["id"], payload, make_policyholder_headers(grower["id"])
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
