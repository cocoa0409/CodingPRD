"""Desk bootstrap: directories, claim intake defaults, and request-shape gates."""
import pytest

from test_helpers import (
    ADJUSTER,
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_claim,
    assert_rental_partner,
    create_claim_payload,
    create_policyholder_payload,
    create_rental_partner_payload,
    create_repair_shop_payload,
    get_claim_view,
    open_claim,
    register_policyholder,
    register_rental_partner,
    register_repair_shop,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPartnerRegistration:
    def test_partner_created_with_active_default(self, api):
        """PRD §3.1: "A newly registered partner starts with `status` set to `ACTIVE`."

        Design: Corner/entities/partner_created_with_active_default
        """
        resp = api.create_rental_partner(create_rental_partner_payload(), ADMIN)
        partner = validate_success(resp, 201)
        assert_rental_partner(partner)
        assert partner["status"] == "ACTIVE", (
            f"Expected new partner status ACTIVE, got {partner['status']}"
        )

    def test_duplicate_policy_number_rejected(self, api):
        """PRD §3.1: "The policy number is unique across all policy holders; a
        duplicate registration is rejected with `ERR_DUPLICATE_POLICY_NUMBER`."

        Design: Corner/validations/duplicate_policy_number_rejected
        """
        register_policyholder(policy_number="POL-100")
        resp = api.create_policyholder(
            create_policyholder_payload(full_name="Patricia Holder",
                                        policy_number="POL-100",
                                        contact_email="patricia@x.com"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POLICY_NUMBER)

    def test_duplicate_shop_code_rejected(self, api):
        """PRD §3.1: "Registering a repair shop records the `shop_name` and a
        `shop_code` that is likewise unique across all repair shops, with
        duplicates rejected as `ERR_DUPLICATE_SHOP_CODE`."

        Design: Corner/errors/duplicate_shop_code_rejected
        """
        register_repair_shop(shop_code="SHOP-1")
        resp = api.create_repair_shop(
            create_repair_shop_payload(shop_name="Ace II", shop_code="SHOP-1"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SHOP_CODE)

    def test_duplicate_partner_code_rejected(self, api):
        """PRD §3.1: "A `SystemAdmin` registers each partner with a `partner_name`
        and a unique `partner_code` (duplicates fail with
        `ERR_DUPLICATE_PARTNER_CODE`)"

        Design: Corner/errors/duplicate_partner_code_rejected
        """
        register_rental_partner(partner_code="RC-1")
        resp = api.create_rental_partner(
            create_rental_partner_payload(partner_name="RentCo Clone", partner_code="RC-1",
                                          economy_capacity=1),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARTNER_CODE)


class TestClaimIntake:
    def test_claim_creation_applies_computed_defaults(self, api):
        """PRD §3.2: "On creation the claim's `rental_reserve_cents` is initialized
        to the daily limit multiplied by the duration cap, `authorized_days_total`
        and `recovery_balance_cents` start at zero, and the claim opens with three
        independent status dimensions: `rental_track_status` begins `OPEN`,
        `loss_of_use_track_status` begins `NONE`, and `overall_status` begins `OPEN`."

        Design: Corner/entities/claim_creation_applies_computed_defaults
        """
        policyholder = register_policyholder()
        resp = api.create_claim(create_claim_payload(policyholder["id"]), ADJUSTER)
        claim = validate_success(resp, 201)
        assert_claim(claim)
        assert claim["rental_reserve_cents"] == 120000, (
            f"Expected reserve 120000 (6000 x 20), got {claim['rental_reserve_cents']}"
        )
        assert claim["authorized_days_total"] == 0
        assert claim["recovery_balance_cents"] == 0
        assert claim["rental_track_status"] == "OPEN"
        assert claim["loss_of_use_track_status"] == "NONE"
        assert claim["overall_status"] == "OPEN"

    def test_claim_missing_required_field_rejected(self, api):
        """PRD §2.7: "a missing required field, a type mismatch, an invalid enum
        value, a decision-specific required field that is absent (a `denial_reason`
        on a denial, a `new_estimated_completion_date` on a delay report), or an
        amount outside its permitted range fails with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/claim_missing_required_field_rejected
        """
        policyholder = register_policyholder()
        payload = create_claim_payload(policyholder["id"])
        del payload["coverage_daily_limit_cents"]
        resp = api.create_claim(payload, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_claim_not_found_returns_404(self, api):
        """PRD §2.8: "Each resource type has its own not-found error:
        `ERR_POLICYHOLDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_COVERAGE_VERIFICATION_NOT_FOUND`, `ERR_REPAIR_SHOP_NOT_FOUND`,
        `ERR_RENTAL_PARTNER_NOT_FOUND`, `ERR_REPAIR_ORDER_NOT_FOUND`,
        `ERR_MILESTONE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
        `ERR_EXTENSION_REQUEST_NOT_FOUND`, `ERR_LOSS_OF_USE_CLAIM_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, and `ERR_RECOVERY_CASE_NOT_FOUND`."

        Design: Corner/entities/get_claim_not_found_returns_404
        """
        resp = api.get_claim(NON_EXISTENT_UUID, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)

    def test_policyholder_claims_list_paginates(self, api):
        """PRD §2.3: "List responses carry four pagination fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10 when omitted, accepts a minimum of 1, and is clamped at a
        maximum of 100."

        Design: Corner/entities/policyholder_claims_list_paginates
        """
        policyholder = register_policyholder()
        for day in ("2026-07-01", "2026-07-02", "2026-07-03"):
            open_claim(policyholder["id"], incident_date=day)

        page1, meta1 = validate_paginated(
            api.list_policyholder_claims(policyholder["id"], ADJUSTER,
                                         params={"limit": 2, "offset": 0}))
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(
            api.list_policyholder_claims(policyholder["id"], ADJUSTER,
                                         params={"limit": 2, "offset": 2}))
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(page2) == 1


class TestAuthenticationGate:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.create_claim(
            create_claim_payload(NON_EXISTENT_UUID), {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
