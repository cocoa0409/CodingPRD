"""Salon onboarding, professional licensing, and the order-creation gate."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_license,
    assert_salon_account,
    create_license_payload,
    create_salon_payload,
    make_brand,
    make_compliance_officer_headers,
    make_consultant,
    make_product,
    make_sales_consultant_headers,
    make_salon,
    make_salon_buyer_headers,
    submit_license,
    validate_error,
    validate_success,
    verify_license,
)

ADMIN = TEST_USERS["admin_headers"]


class TestSalonCreation:
    def test_salon_creation_applies_pending_defaults(self, api):
        """PRD §3.1: "The new account starts in `PENDING_VERIFICATION` with
        tier `SILVER` and all counters — `education_credit_points`,
        `diversion_strike_points`, `diversion_risk_score`,
        `trailing_12m_delivered_volume_cents` — at zero, and
        `tier_override_active` false."

        Design: Corner/entities/salon_create_applies_defaults
        """
        consultant = make_consultant(territory_codes=["WA"])
        resp = api.create_salon_account(
            create_salon_payload(
                legal_name="Salon N", territory_code="WA",
                assigned_consultant_id=consultant["id"]),
            make_sales_consultant_headers(consultant["id"]),
        )
        salon = validate_success(resp, 201)
        assert_salon_account(salon)
        assert salon["status"] == "PENDING_VERIFICATION"
        assert salon["tier"] == "SILVER"
        assert salon["education_credit_points"] == 0
        assert salon["diversion_strike_points"] == 0
        assert salon["diversion_risk_score"] == 0
        assert salon["trailing_12m_delivered_volume_cents"] == 0
        assert salon["tier_override_active"] is False
        assert salon["suspension_reason"] is None
        assert salon["version"] == 1

    def test_salon_creation_missing_legal_name_rejected(self, api):
        """PRD §3.1: "A `SalesConsultant` opens a salon account by supplying
        the salon's `legal_name`, the two-letter `territory_code` it operates
        in, and optionally an `assigned_consultant_id` attributing the account
        to a consultant."
        PRD §2.8: "Schema failures yield `ERR_INVALID_REQUEST`;
        window-ordering failures yield `ERR_INVALID_TIME_WINDOW`."

        Design: Corner/entities/salon_create_missing_required_field
        """
        consultant = make_consultant(territory_codes=["WA"])
        resp = api.create_salon_account(
            {"territory_code": "WA"},
            make_sales_consultant_headers(consultant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLicenseSubmissionAndReview:
    def test_license_submit_with_past_valid_until_rejected(self, api):
        """PRD §3.1: "The `valid_until` must lie strictly after the logical
        clock at submission; otherwise the submission is rejected with
        `ERR_LICENSE_DATE_INVALID` (HTTP 400)."

        Design: Corner/validations/license_submit_with_past_valid_until_returns_400
        """
        consultant = make_consultant()
        salon = make_salon(legal_name="Salon 40", consultant=consultant)
        resp = api.create_license(
            salon["id"],
            create_license_payload(
                license_number="LIC-40", license_type="BARBER",
                valid_until="2026-01-01T00:00:00Z"),
            make_salon_buyer_headers(salon["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_DATE_INVALID)
        salon_after = validate_success(api.get_salon_account(salon["id"], ADMIN))
        assert salon_after["status"] == "PENDING_VERIFICATION"

    def test_license_verify_twice_rejected(self, api):
        """PRD §3.1: "Rejecting a `SUBMITTED` license moves it to `REJECTED`;
        verifying it requires the license still be `SUBMITTED`
        (`ERR_INVALID_LICENSE_STATE` otherwise) and re-checks that
        `valid_until` is still after the logical clock
        (`ERR_LICENSE_DATE_INVALID` otherwise)."

        Design: Corner/state_machines/license_verify_twice_rejected
        """
        consultant = make_consultant()
        salon = make_salon(legal_name="Salon 1", consultant=consultant)
        license_row = submit_license(
            salon["id"], valid_until="2027-06-01T00:00:00Z",
            license_type="BARBER")
        verified = verify_license(license_row["id"])
        assert verified["status"] == "VERIFIED"

        resp = api.verify_license(
            license_row["id"], make_compliance_officer_headers("officer-again"))
        validate_error(resp, ApiErrorId.ERR_INVALID_LICENSE_STATE)
        license_after = validate_success(api.get_license(license_row["id"], ADMIN))
        assert_license(license_after)
        assert license_after["status"] == "VERIFIED"


class TestOrderCreationRequiresActiveSalon:
    def test_order_create_rejected_while_salon_pending_verification(self, api):
        """PRD §3.5: "Order creation requires the salon to be `ACTIVE` —
        otherwise `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409) — and the
        territory-exclusivity rule is evaluated per initial line: for each
        line's brand, if any exclusivity window exists for that brand, the
        salon's `territory_code` must be covered by a window containing the
        logical clock under half-open semantics; failure is
        `ERR_BRAND_TERRITORY_RESTRICTED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/order_create_requires_active_salon
        """
        consultant = make_consultant()
        salon = make_salon(legal_name="Salon W", consultant=consultant)
        submit_license(salon["id"])  # SUBMITTED, not yet verified
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=4000,
                               weight_grams=200)

        resp = api.create_order(
            {"salon_account_id": salon["id"],
             "items": [{"product_id": product["id"], "quantity": 1}]},
            make_salon_buyer_headers(salon["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)

    def test_order_create_succeeds_after_verification_activates_salon(self, api):
        """PRD §3.1: "Verification has a cascade: if the owning salon is still
        `PENDING_VERIFICATION` and the verified license's `valid_until` lies
        after the logical clock, the salon transitions to `ACTIVE` and its
        `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/order_create_requires_active_salon
        """
        consultant = make_consultant()
        salon = make_salon(legal_name="Salon W2", consultant=consultant)
        license_row = submit_license(salon["id"])
        verify_license(license_row["id"])
        salon_after = validate_success(api.get_salon_account(salon["id"], ADMIN))
        assert salon_after["status"] == "ACTIVE"

        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=4000,
                               weight_grams=200)
        resp = api.create_order(
            {"salon_account_id": salon["id"],
             "items": [{"product_id": product["id"], "quantity": 1}]},
            make_salon_buyer_headers(salon["id"]),
        )
        order = validate_success(resp, 201)
        assert order["fulfillment_status"] == "DRAFT"
        assert order["payment_status"] == "UNPAID"

