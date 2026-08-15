"""Contracts: closed-interval term overlap, certification gates, segregation of
duties, referential integrity, capacity guard (PRD §2.8, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    award_posting,
    certify_contract,
    create_contract_payload,
    create_funding_request_line_payload,
    get_posting,
    new_applicant,
    new_applicant_user_with_headers,
    new_contract,
    new_posting,
    new_provider_with_headers,
    new_request,
    new_service,
    publish_posting,
    setup_applicant_base,
    setup_awarded_posting,
    setup_certified_contract,
    setup_request_with_lines,
    validate_error,
    validate_success,
)


def _setup_two_awarded_postings():
    """Certified C1 contract A (term 2027-04-01..2028-03-31) plus a second
    posting awarded to the same provider, ready for a follow-up contract."""
    ctx = setup_applicant_base(with_snapshot=False)
    sp1, _ = new_provider_with_headers()
    p_a = new_posting(ctx, description="Internet access year one")
    publish_posting(ctx, p_a)  # startup-default clock 2026-08-01
    (b_a,) = award_posting(ctx, p_a, [{"provider": sp1, "price": 50000}])
    p_a = get_posting(p_a["id"])
    ct_a = new_contract(ctx, p_a, b_a, sp1, category="CATEGORY_ONE",
                        total_eligible_cents=50000, term=("2027-04-01", "2028-03-31"))
    ct_a = certify_contract(ctx, ct_a)
    # Second procurement: published at the 2026-08-29 clock, bid 2026-09-02,
    # window closed 2026-09-30.
    p_b = new_posting(ctx, description="Internet access renewal")
    publish_posting(ctx, p_b)
    (b_b,) = award_posting(ctx, p_b, [{"provider": sp1, "price": 70000}],
                           bid_clock="2026-09-02T00:00:00Z",
                           close_clock="2026-09-30T00:00:00Z")
    p_b = get_posting(p_b["id"])
    return ctx, sp1, p_b, b_b, ct_a


class TestContractTermOverlap:
    """Queue A: resource_temporal_overlap/contract_term_closed_interval_overlap."""

    def test_shared_endpoint_date_counts_as_overlap(self, api):
        """PRD §3.4: "Finally, the term must not collide — under closed-interval
        semantics, so a shared endpoint date counts as overlap — with the term of
        any other `CERTIFIED` contract for the same (`applicant_id`,
        `service_provider_id`, `category`) triple; a collision is
        `ERR_CONTRACT_TERM_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_term_closed_interval_overlap
        """
        ctx, sp1, p_b, b_b, ct_a = _setup_two_awarded_postings()
        assert ct_a["status"] == "CERTIFIED"
        assert ct_a["service_end_date"] == "2028-03-31"
        # Incoming term starts exactly on the existing contract's end date.
        resp = api.create_contract(
            create_contract_payload(
                applicant_id=ctx["applicant"]["id"], service_provider_id=sp1["id"],
                posting_id=p_b["id"], winning_bid_id=b_b["id"],
                category="CATEGORY_ONE", total_eligible_cents=70000,
                service_start_date="2028-03-31", service_end_date="2029-03-30"),
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_TERM_OVERLAP)

    def test_term_starting_day_after_existing_end_accepted(self, api):
        """PRD §3.4: "Finally, the term must not collide — under closed-interval
        semantics, so a shared endpoint date counts as overlap — with the term of
        any other `CERTIFIED` contract for the same (`applicant_id`,
        `service_provider_id`, `category`) triple; a collision is
        `ERR_CONTRACT_TERM_OVERLAP`."
        PRD §3.4: "A drafted contract starts in `DRAFT` status with
        `certified_date` null."

        Design: Difficulty/resource_temporal_overlap/contract_term_closed_interval_overlap
        """
        ctx, sp1, p_b, b_b, _ = _setup_two_awarded_postings()
        # 2028-04-01 is one day past the existing end 2028-03-31: disjoint.
        data = validate_success(
            api.create_contract(
                create_contract_payload(
                    applicant_id=ctx["applicant"]["id"], service_provider_id=sp1["id"],
                    posting_id=p_b["id"], winning_bid_id=b_b["id"],
                    category="CATEGORY_ONE", total_eligible_cents=70000,
                    service_start_date="2028-04-01", service_end_date="2029-03-31"),
                ctx["coord_headers"],
            ),
            201,
        )
        assert data["status"] == "DRAFT"
        assert data["certified_date"] is None


class TestLineRequiresCertifiedContract:
    """Queue A: cross_entity_state_dependency/line_create_requires_contract_certified."""

    def _awarded_with_draft_contract(self):
        ctx = setup_awarded_posting()  # C1 posting awarded to VendorOne at 50000
        ctx["services"] = {"primary": new_service(ctx["cycle"]["id"])}
        ctx["contract"] = new_contract(ctx, ctx["posting"], ctx["bids"][0],
                                       ctx["provider"])
        return ctx

    def test_line_create_rejected_while_contract_draft(self, api):
        """PRD §3.5: "the referenced contract must be `CERTIFIED` (otherwise
        `ERR_CONTRACT_NOT_CERTIFIED`)"

        Design: Difficulty/cross_entity_state_dependency/line_create_requires_contract_certified
        """
        ctx = self._awarded_with_draft_contract()
        assert ctx["contract"]["status"] == "DRAFT"
        request = new_request(ctx)
        resp = api.create_funding_request_line(
            create_funding_request_line_payload(
                funding_request_id=request["id"], contract_id=ctx["contract"]["id"],
                eligible_service_id=ctx["services"]["primary"]["id"],
                requested_pre_discount_cents=50000),
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_CERTIFIED)

    def test_line_create_succeeds_immediately_after_certification(self, api):
        """PRD §3.5: "the referenced contract must be `CERTIFIED` (otherwise
        `ERR_CONTRACT_NOT_CERTIFIED`)"
        PRD §3.5: "New lines start `PENDING` with `committed_pre_discount_cents`
        and `committed_share_cents` at 0 until decision, `reimbursed_cents` at 0,
        and `denial_reason` null."

        Design: Difficulty/cross_entity_state_dependency/line_create_requires_contract_certified
        """
        ctx = self._awarded_with_draft_contract()
        certify_contract(ctx, ctx["contract"])  # identical contract, now CERTIFIED
        request = new_request(ctx)
        # Identical payload to the blocked case — only the contract state differs.
        data = validate_success(
            api.create_funding_request_line(
                create_funding_request_line_payload(
                    funding_request_id=request["id"], contract_id=ctx["contract"]["id"],
                    eligible_service_id=ctx["services"]["primary"]["id"],
                    requested_pre_discount_cents=50000),
                ctx["coord_headers"],
            ),
            201,
        )
        assert data["status"] == "PENDING"
        assert data["committed_pre_discount_cents"] == 0
        assert data["committed_share_cents"] == 0
        assert data["denial_reason"] is None


class TestContractCertificationGates:
    def test_coordinator_cannot_certify_contract(self, api):
        """PRD §2.1: "When the caller's role is not in the endpoint's authorized
        list, the rejection is `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/erate/contracts/{id}/certify` | Certify a draft
        contract | ApplicantCertifier |".

        Design: Corner/rbac/coordinator_cannot_certify_contract
        """
        ctx = setup_awarded_posting(with_snapshot=False)
        contract = new_contract(ctx, ctx["posting"], ctx["bids"][0], ctx["provider"])
        resp = api.certify_contract(contract["id"], ctx["coord_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_sod_certifier_who_selected_winner_cannot_certify(self, api):
        """PRD §2.8: "When a posting's winner is selected, the caller's
        `X-User-ID` is recorded as the posting's `selected_by_user_id`; the
        contract growing out of that posting must later be certified by a
        different user, and a certifier whose identifier matches
        `selected_by_user_id` is rejected with `ERR_SOD_CONTRACT_CERTIFIER`
        (HTTP 409)."
        PRD §3.4: "A successful certification sets `certified_date` to the clock's
        date, records the caller as `certified_by_user_id`, increments the
        contract's `version`, and creates a `CONTRACT_CERTIFICATION` retained
        document in the same request."

        Design: Corner/rbac/sod_certifier_who_selected_winner_cannot_certify
        """
        ctx = setup_applicant_base(with_snapshot=False)
        sp1, _ = new_provider_with_headers()
        posting = new_posting(ctx)
        publish_posting(ctx, posting)
        # The certifier personally runs winner selection (a shared operation).
        (bid,) = award_posting(ctx, posting, [{"provider": sp1, "price": 50000}],
                               selector="cert")
        posting = get_posting(posting["id"])
        assert posting["selected_by_user_id"] == ctx["u_cert"]["id"]

        contract = new_contract(ctx, posting, bid, sp1)
        resp = api.certify_contract(contract["id"], ctx["cert_headers"])
        validate_error(resp, ApiErrorId.ERR_SOD_CONTRACT_CERTIFIER)

        # A second certifier of the same applicant certifies successfully.
        u_cert2, cert2_headers = new_applicant_user_with_headers(
            ctx["applicant"]["id"], "Cleo Certifier", "CERTIFIER"
        )
        certified = validate_success(
            api.certify_contract(contract["id"], cert2_headers), 200
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == u_cert2["id"]


class TestContractReferentialIntegrity:
    def test_contract_create_with_non_winning_bid_rejected(self, api):
        """PRD §3.4: "The `winning_bid_id` must equal the posting's
        `selected_bid_id`, else `ERR_BID_NOT_AWARDED`."
        PRD §3.3: "The winner is the highest `total_score`; ties break to the
        lower `eligible_price_cents`, and further ties to the earlier bid
        `created_at`."

        Design: Corner/validations/contract_create_with_non_winning_bid_rejected
        """
        ctx = setup_applicant_base(with_snapshot=False)
        sp1, _ = new_provider_with_headers("VendorOne", "SPIN-001")
        sp2, _ = new_provider_with_headers("VendorTwo", "SPIN-002")
        posting = new_posting(ctx)
        publish_posting(ctx, posting)
        # Identical 40000 bids: b1 submitted first wins the created_at tiebreak,
        # so b2 is the non-selected bid at the same price. Equal prices keep the
        # payload's total consistent with the referenced bid under any reading
        # of "the winning bid's price" (PRD §2.10 tier 4), isolating tier 11.
        b1, b2 = award_posting(ctx, posting, [
            {"provider": sp1, "price": 40000},
            {"provider": sp2, "price": 40000},
        ])
        posting = get_posting(posting["id"])
        assert posting["selected_bid_id"] == b1["id"]

        # Only the bid reference is wrong: provider, category, and the eligible
        # total all match the actual winner, isolating the single violation.
        resp = api.create_contract(
            create_contract_payload(
                applicant_id=ctx["applicant"]["id"], service_provider_id=sp1["id"],
                posting_id=posting["id"], winning_bid_id=b2["id"],
                category="CATEGORY_ONE", total_eligible_cents=40000,
                service_start_date="2027-04-01", service_end_date="2028-03-31"),
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BID_NOT_AWARDED)

    def test_cross_applicant_contract_reference_rejected(self, api):
        """PRD §3.5: "the contract's applicant must be the request's applicant,
        the referenced service must belong to the request's cycle inventory, and
        the contract's category must match the service's category — referential
        violations are `ERR_CROSS_ENTITY_MISMATCH`."

        Design: Corner/validations/cross_applicant_contract_reference_rejected
        """
        ctx_a = setup_certified_contract()  # applicant A's certified C1 contract
        app_b = new_applicant(name="District B", entity_type="SCHOOL",
                              urban_rural="RURAL", student_count=500)
        _, coord_b = new_applicant_user_with_headers(app_b["id"], "Coord B",
                                                     "COORDINATOR")
        req_b = validate_success(
            api.create_funding_request(
                {"applicant_id": app_b["id"],
                 "funding_cycle_id": ctx_a["cycle"]["id"]},
                coord_b),
            201,
        )
        resp = api.create_funding_request_line(
            create_funding_request_line_payload(
                funding_request_id=req_b["id"], contract_id=ctx_a["contract"]["id"],
                eligible_service_id=ctx_a["services"]["primary"]["id"],
                requested_pre_discount_cents=10000),
            coord_b,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_MISMATCH)


class TestContractCapacity:
    def test_contract_capacity_exceeded_on_second_line(self, api):
        """PRD §3.5: "A fiscal guard applies at the contract level: the sum of
        `requested_pre_discount_cents` over the contract's non-`CANCELLED` lines,
        including the proposed one, must not exceed the contract's
        `total_eligible_cents`, or the create fails with
        `ERR_CONTRACT_CAPACITY_EXCEEDED`."

        Design: Corner/validations/contract_capacity_exceeded_on_second_line
        """
        ctx = setup_certified_contract()  # C1 contract, total_eligible_cents 50000
        setup_request_with_lines(ctx, line_amounts=(50000,), certify=False)
        # The first line fills the contract exactly (50000 does not exceed 50000).
        assert ctx["lines"][0]["requested_pre_discount_cents"] == 50000

        resp = api.create_funding_request_line(
            create_funding_request_line_payload(
                funding_request_id=ctx["request"]["id"],
                contract_id=ctx["contract"]["id"],
                eligible_service_id=ctx["services"]["primary"]["id"],
                requested_pre_discount_cents=1),
            ctx["coord_headers"],
        )
        # 50000 + 1 = 50001 > 50000
        validate_error(resp, ApiErrorId.ERR_CONTRACT_CAPACITY_EXCEEDED)
