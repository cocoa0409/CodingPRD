"""Compliance reviews, lease execution, acceptance cascades, and the
square-footage reserve/release invariant (PRD §2.9, §3.1, §3.3, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_commission_invoice,
    assert_site_sf_invariant,
    clear_both_reviews,
    create_accepted_loi,
    create_completed_tour,
    create_requirement,
    create_review,
    create_second_requirement,
    create_site,
    create_submitted_loi,
    setup_toured_pair,
    validate_error,
    validate_success,
)

LM = TEST_USERS["leasing_manager_headers"]
REP_1 = TEST_USERS["tenant_rep_1_headers"]
REP_2 = TEST_USERS["tenant_rep_2_headers"]
AM = TEST_USERS["asset_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestComplianceReviewCycle:
    def test_compliance_rereview_cycle(self, api):
        """PRD §3.4: "A flagged review is not dead — after remediation the
        officer may begin it again, `FLAGGED` → `IN_REVIEW`, and resolve it
        afresh, looping as many times as needed." and "when the resolution
        payload carries `findings`, the stored narrative is replaced by it."

        Design: Difficulty/non_linear_state_machine/compliance_rereview_cycle
        """
        req = create_requirement(REP_1)
        site = create_site()
        review = create_review(site["id"], req["id"], "ZONING_USE")
        assert review["status"] == "PENDING"

        in_review = validate_success(api.begin_compliance_review(review["id"], CO))
        assert in_review["status"] == "IN_REVIEW"

        flagged = validate_success(
            api.resolve_compliance_review(
                review["id"],
                {"outcome": "FLAGGED", "findings": "outdoor storage conditional use"},
                CO,
            )
        )
        assert flagged["status"] == "FLAGGED"
        assert flagged["findings"] == "outdoor storage conditional use"

        re_review = validate_success(api.begin_compliance_review(review["id"], CO))
        assert re_review["status"] == "IN_REVIEW", (
            "A FLAGGED review must re-enter IN_REVIEW (remediation loop)"
        )

        cleared = validate_success(
            api.resolve_compliance_review(
                review["id"], {"outcome": "CLEARED", "findings": "CUP granted"}, CO
            )
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["findings"] == "CUP granted", (
            "The resolution payload's findings replace the stored narrative"
        )

    def test_compliance_cleared_is_terminal(self, api):
        """PRD §3.4: "from `IN_REVIEW`, a `CLEARED` outcome lands in terminal
        `CLEARED`". PRD §2.8: "terminal states accept no further transitions —
        otherwise `ERR_INVALID_STATE` (409)."

        Design: Difficulty/non_linear_state_machine/compliance_rereview_cycle
        """
        req = create_requirement(REP_1)
        site = create_site()
        review = create_review(site["id"], req["id"], "ZONING_USE")
        validate_success(api.begin_compliance_review(review["id"], CO))
        cleared = validate_success(
            api.resolve_compliance_review(
                review["id"], {"outcome": "CLEARED", "findings": "CUP granted"}, CO
            )
        )
        assert cleared["status"] == "CLEARED"
        resp = api.resolve_compliance_review(
            review["id"], {"outcome": "FLAGGED"}, CO
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_duplicate_review_type_returns_409(self, api):
        """PRD §3.4: "Uniqueness is enforced per triple: a second review with
        the same `site_id`, `requirement_id`, and `review_type` is rejected
        with `ERR_DUPLICATE_REVIEW` (409)."

        Design: Corner/validations/duplicate_review_type_returns_409
        """
        req = create_requirement(REP_1)
        site = create_site()
        create_review(site["id"], req["id"], "ZONING_USE")
        resp = api.create_compliance_review(
            {
                "site_id": site["id"],
                "requirement_id": req["id"],
                "review_type": "ZONING_USE",
            },
            CO,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REVIEW)


class TestExecuteComplianceGate:
    def _setup_accepted_with_reviews_in_review(self, api):
        req, site, _tour = setup_toured_pair()
        loi = create_accepted_loi(req["id"], site["id"], REP_1)
        rev_e = create_review(site["id"], req["id"], "ENVIRONMENTAL")
        validate_success(api.begin_compliance_review(rev_e["id"], CO))
        rev_z = create_review(site["id"], req["id"], "ZONING_USE")
        validate_success(api.begin_compliance_review(rev_z["id"], CO))
        return req, site, loi, rev_e, rev_z

    def test_execute_with_reviews_in_review_rejected(self, api):
        """PRD §3.4: "Executing an LOI demands two separate `CLEARED` reviews
        for the LOI's site-and-requirement pair — one `ENVIRONMENTAL` and one
        `ZONING_USE` — and a missing or non-cleared review on either axis
        rejects the execution with `ERR_COMPLIANCE_NOT_CLEARED` (409)."

        Design: Difficulty/cross_entity_state_dependency/execute_requires_compliance_cleared
        """
        _req, _site, loi, _rev_e, _rev_z = (
            self._setup_accepted_with_reviews_in_review(api)
        )
        resp = api.execute_loi(loi["id"], AM)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_NOT_CLEARED)
        after = validate_success(api.get_loi(loi["id"], LM))
        assert after["status"] == "ACCEPTED", (
            "A compliance-rejected execution must leave the LOI ACCEPTED"
        )

    def test_execute_after_both_cleared_succeeds(self, api):
        """PRD §3.5: "A successful execution does five things in one request:
        the LOI moves `ACCEPTED` → `EXECUTED`; the site moves `RESERVED` →
        `COMMITTED` ...; the requirement moves `ACTIVE` → `SATISFIED`".

        Design: Difficulty/cross_entity_state_dependency/execute_requires_compliance_cleared
        """
        req, site, loi, rev_e, rev_z = (
            self._setup_accepted_with_reviews_in_review(api)
        )
        validate_error(api.execute_loi(loi["id"], AM),
                       ApiErrorId.ERR_COMPLIANCE_NOT_CLEARED)
        for rev in (rev_e, rev_z):
            validate_success(
                api.resolve_compliance_review(
                    rev["id"], {"outcome": "CLEARED"}, CO
                )
            )
        executed = validate_success(api.execute_loi(loi["id"], AM))
        assert executed["status"] == "EXECUTED"
        site_after = validate_success(api.get_site(site["id"], LM))
        assert site_after["status"] == "COMMITTED"
        req_after = validate_success(api.get_tenant_requirement(req["id"], REP_1))
        assert req_after["status"] == "SATISFIED"


class TestExecuteImmediateConsistency:
    def test_execute_side_effects_immediately_visible(self, api):
        """PRD §2.9: "State changes propagate across entities within the same
        request, and every side effect is visible in that request's response —
        the consistency model is immediate, with no deferred settlement."
        PRD §3.5: "two commission invoices are auto-created in a fixed order —
        `TENANT_REP` first, `LANDLORD_REP` second — each starting `ACCRUED`".

        Design: Corner/consistency_model/execute_side_effects_immediately_visible
        """
        req, site, _tour = setup_toured_pair()
        loi = create_accepted_loi(req["id"], site["id"], REP_1,
                                  commission_basis="GROSS_AGGREGATE")
        clear_both_reviews(site["id"], req["id"])
        executed = validate_success(api.execute_loi(loi["id"], AM))
        assert executed["status"] == "EXECUTED", (
            "The execute response itself must report EXECUTED"
        )

        plans = validate_success(
            api.list_bts_plans(LM, params={"loi_id": loi["id"]})
        )
        assert len(plans) == 1
        assert plans[0]["status"] == "SCHEMATIC"
        assert plans[0]["loi_id"] == loi["id"]

        invoices = validate_success(
            api.list_commission_invoices(LM, params={"loi_id": loi["id"]})
        )
        assert len(invoices) == 2
        assert invoices[0]["broker_side"] == "TENANT_REP"
        assert invoices[0]["status"] == "ACCRUED"
        assert invoices[1]["broker_side"] == "LANDLORD_REP"
        assert invoices[1]["status"] == "ACCRUED"
        assert_commission_invoice(invoices[0])
        assert_commission_invoice(invoices[1])

        site_after = validate_success(api.get_site(site["id"], LM))
        assert site_after["status"] == "COMMITTED"
        req_after = validate_success(api.get_tenant_requirement(req["id"], REP_1))
        assert req_after["status"] == "SATISFIED"


class TestAcceptanceCascade:
    """Accept -> site RESERVED -> competing LOIs auto-REJECTED (PRD §3.3)."""

    def _setup_two_submitted_lois(self, api):
        req1 = create_requirement(REP_1)
        req2 = create_second_requirement()
        site = create_site()
        create_completed_tour(site["id"], req1["id"], REP_1)
        create_completed_tour(
            site["id"], req2["id"], REP_2,
            start_at="2026-08-10T11:30:00Z", end_at="2026-08-10T12:30:00Z",
        )
        loi_a = create_submitted_loi(req1["id"], site["id"], REP_1)
        loi_b = create_submitted_loi(req2["id"], site["id"], REP_2)
        return req1, req2, site, loi_a, loi_b

    def test_accept_reserves_site_and_drops_available_sf(self, api):
        """PRD §3.3: "On acceptance the cascade fires: the site moves `LISTED`
        → `RESERVED` with `leased_sf` added to `reserved_sf` and
        `available_sf` recomputed — link one".

        Design: Difficulty/transitive_cascade/accept_reservation_rejects_competing_lois
        """
        _r1, _r2, site, loi_a, _loi_b = self._setup_two_submitted_lois(api)
        accepted = validate_success(api.accept_loi(loi_a["id"], LM))
        assert accepted["status"] == "ACCEPTED"
        site_after = validate_success(api.get_site(site["id"], LM))
        assert site_after["status"] == "RESERVED"
        assert site_after["reserved_sf"] == 100000
        assert site_after["available_sf"] == 100000
        assert_site_sf_invariant(site_after)

    def test_accept_auto_rejects_competing_loi(self, api):
        """PRD §3.3: "that site transition rejects every other LOI on the same
        site sitting in `SUBMITTED` or `COUNTERED`, moving them to `REJECTED`
        — link two, caused by the site transition rather than the accept call
        itself."

        Design: Difficulty/transitive_cascade/accept_reservation_rejects_competing_lois
        """
        _r1, _r2, _site, loi_a, loi_b = self._setup_two_submitted_lois(api)
        validate_success(api.accept_loi(loi_a["id"], LM))
        loi_b_after = validate_success(api.get_loi(loi_b["id"], LM))
        assert loi_b_after["status"] == "REJECTED", (
            f"The competing SUBMITTED LOI must be auto-REJECTED by the site "
            f"transition, got {loi_b_after['status']}"
        )
        loi_a_after = validate_success(api.get_loi(loi_a["id"], LM))
        assert loi_a_after["status"] == "ACCEPTED"


class TestSquareFootageConservation:
    """Conserved quantity: available_sf + reserved_sf == total_sf (PRD §3.1)."""

    def test_reserve_consumes_available_sf(self, api):
        """PRD §3.1: "`available_sf` is read-only and always equals `total_sf`
        minus `reserved_sf`, recomputed whenever `reserved_sf` changes."
        PRD §3.3: "the site moves `LISTED` → `RESERVED` with `leased_sf`
        added to `reserved_sf`".

        Design: Difficulty/compensating_invariant/site_sf_reserve_release_conservation
        """
        req, site, _tour = setup_toured_pair()
        loi = create_submitted_loi(req["id"], site["id"], REP_1)
        validate_success(api.accept_loi(loi["id"], LM))
        mid = validate_success(api.get_site(site["id"], LM))
        assert mid["status"] == "RESERVED"
        assert mid["reserved_sf"] == 100000
        assert mid["available_sf"] == 100000
        assert mid["reserved_sf"] + mid["available_sf"] == mid["total_sf"]

    def test_withdraw_from_accepted_releases_reservation(self, api):
        """PRD §3.3: "Withdrawing from `ACCEPTED` — the tenant walking away
        before execution — performs the compensating release: the site moves
        `RESERVED` → `LISTED` with the LOI's `leased_sf` removed from
        `reserved_sf`, and every expansion option still `GRANTED` on that LOI
        moves to `RELEASED`."

        Design: Difficulty/compensating_invariant/site_sf_reserve_release_conservation
        """
        req, site, _tour = setup_toured_pair()
        loi = create_accepted_loi(req["id"], site["id"], REP_1)
        withdrawn = validate_success(api.withdraw_loi(loi["id"], REP_1))
        assert withdrawn["status"] == "WITHDRAWN"
        end = validate_success(api.get_site(site["id"], LM))
        assert end["status"] == "LISTED"
        assert end["reserved_sf"] == 0
        assert end["available_sf"] == end["total_sf"] == 200000, (
            f"The compensating release must restore all 200000 SF, got "
            f"reserved {end['reserved_sf']} / available {end['available_sf']}"
        )
