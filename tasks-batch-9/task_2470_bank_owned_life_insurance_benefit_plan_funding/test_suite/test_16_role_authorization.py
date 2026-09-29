"""Role eligibility, the four-eyes identity rule and the carrier liaison's own scope."""
from test_helpers import validate_error, validate_success
from test_helpers.test_users import (
    make_benefits_analyst_headers,
    make_carrier_liaison_headers,
    make_risk_officer_headers,
)
from test_helpers.fixtures import (
    ADMIN,
    RISK,
    file_capital_position,
    onboard_carrier,
    open_diligence_review,
    register_product_type,
    submit_diligence_review,
)


ELMWOOD = {
    "legal_name": "Elmwood Life",
    "naic_code": "71031",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "IL",
}
FOXGLOVE = {
    "legal_name": "Foxglove Life",
    "naic_code": "71032",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "MN",
}


class TestRoleEligibility:
    def test_an_analyst_is_refused_the_risk_officers_own_operations(self, api):
        """The role gate closes before the resource's state is ever consulted.

        "If both headers are present but the value of `X-User-Role` is not one of
        the seven declared roles, or is a declared role that does not appear on the
        called endpoint's authorized-role list, the request fails with
        `ERR_UNAUTHORIZED` (HTTP 403)." That check runs early: "Header presence is
        checked first, then role eligibility for the endpoint, then — only for
        endpoints that admit `CarrierLiaison` at all — the carrier scoping check."
        The file is in exactly the state the risk officer's own calls need.

        Design: Corner/rbac/benefits_analyst_cannot_perform_risk_officer_exclusive_operations
        """
        file_capital_position(
            api,
            as_of_date="2026-06-30T00:00:00Z",
            tier1_capital_usd=1_000_000_000.00,
            total_assets_usd=12_000_000_000.00,
        )
        carrier = onboard_carrier(api, **ELMWOOD)
        review = open_diligence_review(api, carrier["id"], review_year=2026)
        submit_diligence_review(api, review["id"])

        other_analyst = make_benefits_analyst_headers("analyst-2")
        validate_error(
            api.approve_diligence_review(review["id"], other_analyst),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api.request_diligence_info(review["id"], other_analyst),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api.suspend_carrier(carrier["id"], other_analyst), "ERR_UNAUTHORIZED", 403
        )

        untouched = validate_success(api.get_diligence_review(review["id"], RISK))
        assert untouched["status"] == "UNDER_REVIEW"
        assert untouched["info_request_count"] == 0
        assert untouched["decided_by_user_id"] is None

        carrier_after = validate_success(api.get_carrier(carrier["id"], RISK))
        assert carrier_after["status"] == "PENDING_DILIGENCE"


class TestFourEyesIdentity:
    def test_the_operator_who_prepared_the_file_may_not_decide_it(self, api):
        """The four-eyes rule compares operator identifiers, not roles.

        "Five decision points in this system are guarded by a four-eyes rule: the
        operator taking the decision must not be the operator who prepared the item
        being decided. Approving a diligence review and declining a diligence
        review both require that the acting `X-User-ID` differ from the review's
        `submitted_by_user_id`." A violation "is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)", while a second operator carrying
        the same role passes both that check and "the score threshold, requiring
        `financial_strength_score` to be at least 65".

        Design: Corner/rbac/the_same_user_id_cannot_submit_and_then_decide_the_same_review
        """
        file_capital_position(
            api,
            as_of_date="2026-06-30T00:00:00Z",
            tier1_capital_usd=1_000_000_000.00,
            total_assets_usd=12_000_000_000.00,
        )
        carrier = onboard_carrier(api, **FOXGLOVE)
        review = open_diligence_review(api, carrier["id"], review_year=2026)
        submitted = submit_diligence_review(api, review["id"], submitter="analyst-1")
        assert submitted["submitted_by_user_id"] == "analyst-1"
        assert submitted["financial_strength_score"] == 65

        wearing_the_risk_hat = make_risk_officer_headers("analyst-1")
        validate_error(
            api.approve_diligence_review(review["id"], wearing_the_risk_hat),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        validate_error(
            api.decline_diligence_review(review["id"], wearing_the_risk_hat),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        still_open = validate_success(api.get_diligence_review(review["id"], RISK))
        assert still_open["status"] == "UNDER_REVIEW"
        assert still_open["decided_by_user_id"] is None

        decided = validate_success(
            api.approve_diligence_review(review["id"], make_risk_officer_headers("risk-9"))
        )
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == "risk-9"

        authorized = validate_success(api.get_carrier(carrier["id"], RISK))
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["last_approved_review_year"] == 2026


class TestCarrierLiaisonScope:
    def test_a_liaison_reads_its_own_records_and_nothing_of_its_peers(self, api):
        """The liaison's identifier is the carrier it speaks for.

        "When `X-User-Role` is `CarrierLiaison`, by contrast, `X-User-ID` is the
        `id` of the acting carrier itself; on every endpoint whose authorized-role
        list includes `CarrierLiaison`, the server compares the `carrier_id` of each
        resource named in the path or in the request body against `X-User-ID`, and
        any mismatch is rejected with `ERR_CARRIER_SCOPE_VIOLATION` (HTTP 403). A
        `CarrierLiaison` reading a carrier record other than its own, listing
        product types or purchase requests belonging to another carrier, or reading
        a policy or a statement period issued by another carrier, all fail that
        way."

        Design: Corner/rbac/carrier_liaison_cannot_read_another_carriers_records
        """
        gable = onboard_carrier(
            api,
            legal_name="Gable Life",
            naic_code="71033",
            am_best_rating="A",
            statutory_surplus_usd=500_000_000.00,
            domicile_state="MO",
        )
        harrow = onboard_carrier(
            api,
            legal_name="Harrow Life",
            naic_code="71034",
            am_best_rating="A",
            statutory_surplus_usd=500_000_000.00,
            domicile_state="IA",
        )
        gable_product = register_product_type(
            api, gable["id"], product_name="Gable GA BOLI", account_type="GENERAL"
        )
        harrow_product = register_product_type(
            api, harrow["id"], product_name="Harrow GA BOLI", account_type="GENERAL"
        )

        acting = make_carrier_liaison_headers(gable["id"])

        own_carrier = validate_success(api.get_carrier(gable["id"], acting))
        assert own_carrier["legal_name"] == "Gable Life"

        validate_error(
            api.get_carrier(harrow["id"], acting), "ERR_CARRIER_SCOPE_VIOLATION", 403
        )
        validate_error(
            api.get_product_type(harrow_product["id"], acting),
            "ERR_CARRIER_SCOPE_VIOLATION",
            403,
        )

        own_product = validate_success(api.get_product_type(gable_product["id"], acting))
        assert own_product["product_name"] == "Gable GA BOLI"

        assert validate_success(api.get_carrier(harrow["id"], ADMIN))["version"] == 1
        assert validate_success(api.get_carrier(gable["id"], ADMIN))["version"] == 1
