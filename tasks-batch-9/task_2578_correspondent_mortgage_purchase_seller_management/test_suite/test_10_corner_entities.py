"""Entity creation, retrieval, listing and the shape of a rejected request."""

import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    QC,
    REVIEWER,
    REVIEWER_ALT,
    TRADER,
    ApiErrorId,
    api_client,
    assert_defect,
    assert_loan,
    assert_product,
    assert_seller,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_PRODUCT_ID = "22222222-2222-4222-8222-222222222222"


class TestSellerRegistration:
    """A brand new applicant carries nothing but what it was told."""

    def test_a_new_seller_starts_applied_not_eligible_and_wholly_zeroed(self):
        """Registration writes three inputs and derives everything else as empty.

        The applicant comes back on both state dimensions at their opening values,
        with no tier, no decision maker, no servicing privilege, an ungraded
        scorecard position and every money roll-up at zero — nothing has been
        underwritten yet, so nothing may be presumed.

        PRD: "Its derived fields all start empty: `approval_tier` and
        `suspension_reason` and `approval_decided_by_user_id` are null,
        `servicing_retained_eligible` is false, `current_scorecard_grade` is
        `UNRATED`, and `approved_tangible_net_worth_cents`,
        `mandatory_exposure_limit_cents`, `open_mandatory_exposure_cents`,
        `net_funded_cents`, `fee_receivable_cents` and `current_defect_rate_bps`
        are all zero."

        Design: Corner/entities/seller_creation_starts_applied_and_not_eligible_with_rollups_zeroed
        """
        fixtures.setup_clock("2026-08-01T00:00:00Z")

        seller = validate_success(
            api_client.create_seller(factories.seller_payload(), ANALYST), 201
        )

        assert_seller(seller)
        assert seller["legal_name"] == "Harbor Point Mortgage LLC"
        assert seller["tin"] == "823391045"
        assert seller["seller_type"] == "NON_BANK_IMB"
        assert seller["approval_status"] == "APPLIED"
        assert seller["delivery_standing"] == "NOT_ELIGIBLE"
        assert seller["approval_tier"] is None
        assert seller["suspension_reason"] is None
        assert seller["approval_decided_by_user_id"] is None
        assert seller["servicing_retained_eligible"] is False
        assert seller["current_scorecard_grade"] == "UNRATED"
        assert seller["approved_tangible_net_worth_cents"] == 0
        assert seller["mandatory_exposure_limit_cents"] == 0
        assert seller["open_mandatory_exposure_cents"] == 0
        assert seller["net_funded_cents"] == 0
        assert seller["fee_receivable_cents"] == 0
        assert seller["current_defect_rate_bps"] == 0
        assert seller["created_at"] == "2026-08-01T00:00:00.000Z"
        assert seller["version"] == 1

    def test_registration_without_a_tin_is_rejected_and_creates_nothing(self):
        """The taxpayer number is a required input, not an optional one.

        A body carrying only the legal name and the seller type is refused on
        schema grounds, and because the refusal happens before anything is
        written, the seller collection is still empty afterwards.

        PRD: "A `CounterpartyAnalyst` brings a new counterparty onto the platform
        by registering it as a **Seller**, supplying the applicant's `legal_name`
        (a non-empty string of between 1 and 200 characters), its `tin` (a
        taxpayer identification number of exactly nine digits), and its
        `seller_type`, which is one of `BANK`, `CREDIT_UNION` or `NON_BANK_IMB`."

        Design: Corner/entities/seller_creation_without_tin_returns_invalid_request
        """
        fixtures.setup_clock("2026-08-01T00:00:00Z")

        response = api_client.create_seller(
            factories.seller_payload(tin=factories.OMIT), ANALYST
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        sellers, meta = validate_paginated(api_client.list_sellers(ANALYST))
        assert meta["total_count"] == 0
        assert sellers == []


class TestApprovedSellerRetrieval:
    """Reading an approved seller shows the frozen underwriting result."""

    def test_the_approved_seller_carries_the_frozen_net_worth_and_its_decider(self):
        """Approval copies the statement's net worth onto the seller and holds it.

        The governing statement reported 300,000,000 and passed review, and the
        governing review returned no findings of consequence, so the seller reads
        back at the standard tier with servicing privileges, ten times leverage on
        the frozen figure, and the deciding analyst recorded by id.

        PRD: "`approved_tangible_net_worth_cents` copies the governing statement's
        `tangible_net_worth_cents`, freezing the net worth the approval was granted
        against."

        Design: Corner/entities/approved_seller_retrieval_returns_frozen_underwriting_rollups
        """
        fixtures.setup_clock("2026-08-01T00:00:00Z")
        staged = fixtures.setup_approved_seller()

        seller = fixtures.read_seller(staged["seller_id"])

        assert_seller(seller)
        assert seller["approval_status"] == "APPROVED"
        assert seller["delivery_standing"] == "GOOD_STANDING"
        assert seller["approval_tier"] == "STANDARD"
        assert seller["servicing_retained_eligible"] is True
        assert seller["approved_tangible_net_worth_cents"] == 300000000
        assert seller["mandatory_exposure_limit_cents"] == 3000000000
        assert seller["open_mandatory_exposure_cents"] == 0
        assert seller["approval_decided_by_user_id"] == "u-ca-1"

        assert staged["qc_review"]["outcome"] == "PASS"
        assert staged["qc_review"]["completed_by_user_id"] == "u-qc-1"
        assert staged["statement"]["status"] == "ACCEPTED"


class TestSellerListing:
    """The approval filter narrows the population before the page is cut."""

    @staticmethod
    def _three_sellers_two_of_them_still_applied() -> dict:
        fixtures.setup_clock("2026-08-01T00:00:00Z")
        first = fixtures.setup_seller()
        fixtures.setup_qc_review(first["id"], "PRE_APPROVAL")
        second = fixtures.setup_seller(
            legal_name="Cascade Funding Inc", tin="770112238", seller_type="BANK"
        )
        third = fixtures.setup_seller(
            legal_name="Ironwood Lending CU", tin="641903377", seller_type="CREDIT_UNION"
        )
        return {"first": first, "second": second, "third": third}

    def test_the_filter_counts_only_matching_rows_and_paging_walks_them_in_order(self):
        """Two applicants match, so total_count reads 2 and not 3.

        Opening a review on the first seller moved it off the applied state, so a
        one-row page over the applied population reports a total of two and more to
        come, and the second page finishes the set in creation order without ever
        showing the seller under review.

        PRD: "Collection endpoints also accept domain filters, which are applied
        before pagination."

        Design: Corner/entities/seller_listing_filters_by_approval_status_with_pagination_envelope
        """
        staged = self._three_sellers_two_of_them_still_applied()

        page1, meta1 = validate_paginated(
            api_client.list_sellers(
                ANALYST, {"approval_status": "APPLIED", "limit": 1, "offset": 0}
            )
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        assert page1[0]["id"] == staged["second"]["id"]

        page2, meta2 = validate_paginated(
            api_client.list_sellers(
                ADMIN, {"approval_status": "APPLIED", "limit": 1, "offset": 1}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert meta2["offset"] == 1
        assert page2[0]["id"] == staged["third"]["id"]

        returned_ids = {page1[0]["id"], page2[0]["id"]}
        assert staged["first"]["id"] not in returned_ids


class TestUnknownPathIdentifiers:
    """Each of the twelve entity paths answers with its own not-found id."""

    @pytest.mark.parametrize(
        "call, expected_error_id",
        [
            (
                lambda: api_client.get_seller(UNKNOWN_ID, ANALYST),
                ApiErrorId.ERR_SELLER_NOT_FOUND,
            ),
            (
                lambda: api_client.get_product(UNKNOWN_ID, ADMIN),
                ApiErrorId.ERR_PRODUCT_NOT_FOUND,
            ),
            (
                lambda: api_client.review_financial_statement(
                    UNKNOWN_ID, {"decision": "ACCEPT"}, ANALYST
                ),
                ApiErrorId.ERR_STATEMENT_NOT_FOUND,
            ),
            (
                lambda: api_client.complete_qc_review(
                    UNKNOWN_ID, {"findings_count": 0, "critical_findings_count": 0}, QC
                ),
                ApiErrorId.ERR_QC_REVIEW_NOT_FOUND,
            ),
            (
                lambda: api_client.get_commitment(UNKNOWN_ID, TRADER),
                ApiErrorId.ERR_COMMITMENT_NOT_FOUND,
            ),
            (
                lambda: api_client.get_loan(UNKNOWN_ID, REVIEWER),
                ApiErrorId.ERR_LOAN_NOT_FOUND,
            ),
            (
                lambda: api_client.waive_defect(
                    UNKNOWN_ID, {"price_adjustment_bps": -25}, REVIEWER
                ),
                ApiErrorId.ERR_DEFECT_NOT_FOUND,
            ),
            (
                lambda: api_client.clear_suspense_condition(
                    UNKNOWN_ID, {"document_reference": "DOC-404"}, REVIEWER
                ),
                ApiErrorId.ERR_CONDITION_NOT_FOUND,
            ),
            (
                lambda: api_client.settle_purchase_advice(
                    UNKNOWN_ID, {"funding_reference": "WIRE-404"}, REVIEWER_ALT
                ),
                ApiErrorId.ERR_ADVICE_NOT_FOUND,
            ),
            (
                lambda: api_client.get_repurchase_demand(UNKNOWN_ID, REVIEWER),
                ApiErrorId.ERR_DEMAND_NOT_FOUND,
            ),
            (
                lambda: api_client.complete_escrow_transfer(
                    UNKNOWN_ID, {"goodbye_letter_reference": "GB-404"}, REVIEWER
                ),
                ApiErrorId.ERR_TRANSFER_NOT_FOUND,
            ),
            (
                lambda: api_client.close_scorecard(UNKNOWN_ID, ANALYST),
                ApiErrorId.ERR_SCORECARD_NOT_FOUND,
            ),
        ],
    )
    def test_an_unknown_path_id_names_the_entity_it_failed_to_resolve(
        self, call, expected_error_id
    ):
        """No path falls back on a generic not-found or on a schema complaint.

        Against an empty database the same unknown identifier is aimed at each of
        the twelve entity paths in turn, and every one of them names the entity
        type it could not resolve, at the same status.

        PRD: "A missing seller yields `ERR_SELLER_NOT_FOUND`; a missing product
        `ERR_PRODUCT_NOT_FOUND`; a missing financial statement
        `ERR_STATEMENT_NOT_FOUND`; a missing quality-control review
        `ERR_QC_REVIEW_NOT_FOUND`; a missing commitment `ERR_COMMITMENT_NOT_FOUND`;
        a missing loan `ERR_LOAN_NOT_FOUND`; a missing defect
        `ERR_DEFECT_NOT_FOUND`; a missing suspense condition
        `ERR_CONDITION_NOT_FOUND`; a missing purchase advice `ERR_ADVICE_NOT_FOUND`;
        a missing repurchase demand `ERR_DEMAND_NOT_FOUND`; a missing escrow
        transfer `ERR_TRANSFER_NOT_FOUND`; and a missing scorecard
        `ERR_SCORECARD_NOT_FOUND`."

        Design: Corner/entities/unknown_path_ids_across_all_twelve_entities_return_not_found
        """
        fixtures.setup_clock("2026-08-01T00:00:00Z")

        error = validate_error(call(), expected_error_id, 404)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value


class TestProductDefaults:
    """An omitted optional field takes its declared default, or stays null."""

    def test_status_falls_back_to_active_while_a_supplied_status_survives(self):
        """One optional field has a default; the other simply has none.

        The first product omits both optional inputs and comes back available for
        new business with no description at all, proving the fallback applies only
        where one was declared. The second supplies both, and the supplied retired
        status is kept rather than overwritten by the default.

        PRD: "A `status` may be supplied and defaults to `ACTIVE`; the only other
        accepted value is `RETIRED`, which withdraws the row from new business."

        Design: Corner/entities/product_creation_omitting_description_and_status_applies_declared_defaults
        """
        fixtures.setup_clock("2026-08-01T00:00:00Z")

        defaulted = validate_success(
            api_client.create_product(factories.product_payload(), ADMIN), 201
        )
        retired = validate_success(
            api_client.create_product(
                factories.product_payload(
                    product_code="JUMBO30F",
                    base_price_pct=100.500,
                    min_fico=700,
                    max_ltv_pct=80.0,
                    max_loan_amount_cents=200000000,
                    allowed_commitment_types=["MANDATORY"],
                    allowed_occupancies=["PRIMARY"],
                    srp_pct=0.750,
                    description="retired jumbo grid",
                    status="RETIRED",
                ),
                ADMIN,
            ),
            201,
        )

        assert_product(defaulted)
        assert defaulted["status"] == "ACTIVE"
        assert defaulted["description"] is None
        assert defaulted["base_price_pct"] == 101.250
        assert defaulted["srp_pct"] == 1.250

        assert_product(retired)
        assert retired["status"] == "RETIRED"
        assert retired["description"] == "retired jumbo grid"


class TestDefectDerivedFields:
    """The reviewer supplies the finding; the platform decides its nature."""

    def test_classification_and_deadline_come_from_the_finding_not_the_body(self):
        """Both bodies carry a classification, and both are thrown away.

        A low documentation finding is stored curable with a fifteen-day rope even
        though the body claimed it was non-curable, and a critical credit finding
        is stored non-curable with no rope at all even though the body claimed it
        was curable — the derivation reads only the severity and the category.

        PRD: "The defect's `classification` is **derived, and any value supplied in
        the body is ignored**."

        Design: Corner/entities/defect_classification_is_computed_from_severity_and_category_extra_field_input_ignored
        """
        staged = fixtures.setup_loan_in_review()

        low = validate_success(
            api_client.create_defect(
                staged["loan_id"],
                factories.defect_payload(
                    "DOC-MISSING-1008",
                    "DOCUMENTATION",
                    "LOW",
                    classification="NON_CURABLE",
                ),
                REVIEWER,
            ),
            201,
        )
        critical = validate_success(
            api_client.create_defect(
                staged["loan_id"],
                factories.defect_payload(
                    "CRED-FRAUD-2001", "CREDIT", "CRITICAL", classification="CURABLE"
                ),
                REVIEWER,
            ),
            201,
        )

        assert_defect(low)
        assert low["classification"] == "CURABLE"
        assert low["cure_deadline_at"] == "2026-08-16T00:00:00.000Z"
        assert low["status"] == "OPEN"

        assert_defect(critical)
        assert critical["classification"] == "NON_CURABLE"
        assert critical["cure_deadline_at"] is None
        assert critical["status"] == "OPEN"

        loan = fixtures.read_loan(staged["loan_id"])
        assert loan["open_defect_count"] == 2
        assert loan["non_curable_defect_count"] == 1
        assert loan["purchase_status"] == "SUSPENDED"
        assert loan["review_cycle_count"] == 0


class TestLoanDeliverySystemFields:
    """Scope ids come down from the parent line, never up from the payload."""

    def test_the_delivered_loan_inherits_its_scope_and_is_stamped_from_the_clock(self):
        """The payload names no seller and no product, yet the loan carries both.

        Delivery copies the owning seller and the priced product off the
        commitment, stamps the delivery instant from the logical clock, leaves the
        purchase instant empty, and takes 40,000,000 out of the line's residual
        without closing it or disturbing the frozen lock price.

        PRD: "Its `commitment_id` names the line it was delivered against, while
        its `seller_id` and `product_id` are copied down from that commitment
        rather than supplied by the client — the loan can never disagree with its
        commitment about who sold it or under which product it was priced."

        Design: Corner/entities/loan_delivery_stamps_system_fields_and_copies_parent_scope_ids
        """
        staged = fixtures.setup_locked_commitment()
        assert staged["commitment"]["commitment_price_pct"] == 100.880

        loan = fixtures.deliver_loan(staged["commitment_id"], staged["seller_id"])

        assert_loan(loan)
        assert loan["commitment_id"] == staged["commitment_id"]
        assert loan["seller_id"] == staged["seller_id"]
        assert loan["product_id"] == staged["product_id"]
        assert loan["delivered_at"] == "2026-08-01T00:00:00.000Z"
        assert loan["purchased_at"] is None
        assert loan["purchase_status"] == "DELIVERED"
        assert loan["first_payment_status"] == "PENDING"
        assert loan["review_cycle_count"] == 0
        assert loan["open_defect_count"] == 0
        assert loan["open_suspense_count"] == 0
        assert loan["advice_count"] == 0
        assert loan["escrow_balance_cents"] == 0

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert commitment["allocated_amount_cents"] == 40000000
        assert commitment["fulfilled_amount_cents"] == 0
        assert commitment["available_amount_cents"] == 60000000
        assert commitment["status"] == "LOCKED"
        assert commitment["commitment_price_pct"] == 100.880


class TestCommitmentRequestSchema:
    """Malformed values are refused on shape, before any domain rule runs."""

    def test_an_undeclared_type_and_a_fractional_cents_value_are_both_refused(self):
        """Neither an unknown enum member nor a non-integer cents value survives.

        A commitment type outside the declared pair is a schema failure and not the
        product's allowed-type complaint, and a notional carrying a fraction of a
        cent is a schema failure too; neither attempt leaves a line behind or moves
        the seller's exposure.

        PRD: "Every request that carries a body is checked for required fields,
        declared enum membership, scalar shape (any field whose name ends in
        `_cents`, `_count` or `_bps` must be an integer; any field whose name ends
        in `_pct` must be a number), ISO 8601 date formatting, and resolvability of
        body-referenced identifiers such as `product_id`, `commitment_id`,
        `seller_id` and `source_defect_id`."

        Design: Corner/entities/commitment_creation_with_undeclared_enum_or_fractional_cents_is_rejected
        """
        staged = fixtures.setup_lock_ready_seller(with_adjustment=False)

        bad_enum = validate_error(
            api_client.create_commitment(
                factories.commitment_payload(
                    staged["seller_id"],
                    staged["product_id"],
                    commitment_type="FORWARD_TBA",
                ),
                TRADER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )
        assert bad_enum["error_id"] != ApiErrorId.ERR_COMMITMENT_TYPE_NOT_ALLOWED.value

        validate_error(
            api_client.create_commitment(
                factories.commitment_payload(
                    staged["seller_id"],
                    staged["product_id"],
                    notional_amount_cents=100000000.75,
                ),
                TRADER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        _, meta = validate_paginated(
            api_client.list_commitments(TRADER, {"seller_id": staged["seller_id"]})
        )
        assert meta["total_count"] == 0
        assert fixtures.read_seller(staged["seller_id"])["open_mandatory_exposure_cents"] == 0

    def test_a_dangling_product_reference_reads_differently_in_body_and_path(self):
        """The same unknown id is a schema fault in a body and a miss in a path.

        Carried inside the lock request the unresolvable product reference is a
        malformed body, while the very same identifier addressed as a path segment
        reports the product it could not find — and no line is created either way.

        PRD: "Each identifier embedded in the URL must resolve to a live row of the
        expected type before anything to its right is examined."

        Design: Corner/entities/commitment_creation_with_unknown_body_product_id_returns_invalid_request
        """
        staged = fixtures.setup_lock_ready_seller(with_adjustment=False)

        validate_error(
            api_client.create_commitment(
                factories.commitment_payload(
                    staged["seller_id"], UNKNOWN_PRODUCT_ID
                ),
                TRADER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        validate_error(
            api_client.get_product(UNKNOWN_PRODUCT_ID, TRADER),
            ApiErrorId.ERR_PRODUCT_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(
            api_client.list_commitments(TRADER, {"seller_id": staged["seller_id"]})
        )
        assert meta["total_count"] == 0
