"""Underwriting models: NOI variants, WALT combinatorics, input-set
filtering, the cap-rate band, segregation of duties, and version pinning."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_lease,
    add_property,
    add_verified_lease,
    approve_model,
    complete_all_open_milestones,
    create_approved_model,
    create_approved_tenant,
    create_deal,
    create_model,
    create_psa,
    create_tenant,
    execute_psa,
    get_deal,
    get_milestone_by_type,
    make_committee_headers,
    setup_psa_executed,
    submit_model,
    validate_error,
    validate_success,
)


def _two_lease_deal(api, analyst_headers, deal_name="DualVariantDeal"):
    """Deal + property + two APPROVED tenants + two VERIFIED leases with
    rents 1,200,000 and 800,000 (gross rent 2,000,000)."""
    deal = create_deal(deal_name=deal_name, deal_type="MULTI_TENANT",
                       purchase_price_cents=25000000,
                       earnest_money_cents=500000)
    prop = add_property(deal["id"], address="100 Main St",
                        rentable_sqft=20000, year_built=2010)
    t1 = create_approved_tenant(legal_name="Tenant One", credit_score=800)
    t2 = create_approved_tenant(legal_name="Tenant Two", credit_score=790,
                                annual_revenue_cents=90000000)
    lease_a = add_verified_lease(
        deal["id"], prop["id"], t1["id"], annual_base_rent_cents=1200000,
        lease_expiration_date="2036-08-01T00:00:00Z")
    lease_b = add_verified_lease(
        deal["id"], prop["id"], t2["id"], lease_type="NN",
        annual_base_rent_cents=800000,
        lease_commencement_date="2021-01-01T00:00:00Z",
        lease_expiration_date="2032-06-01T00:00:00Z")
    return deal, prop, t1, t2, lease_a, lease_b


class TestNoiDualVariant:
    def test_noi_conservative_variant(self, api, analyst_headers):
        """PRD §3.3: "The operating-expense allowance is that gross rent
        multiplied by the variant's percentage: fifteen percent under
        `CONSERVATIVE`, twelve percent under `MARKET`. The `noi_cents` is the
        gross rent minus the allowance."

        Design: Difficulty/dual_variant_calc/noi_conservative_vs_market_variant_on_underwriting_domain
        """
        deal, _prop, _t1, _t2, _la, _lb = _two_lease_deal(api,
                                                          analyst_headers)
        model = create_model(deal["id"], "CONSERVATIVE")
        # 2,000,000 gross - 15% (300,000) = 1,700,000
        assert model["noi_cents"] == 1700000, (
            f"CONSERVATIVE NOI must be 1700000, got {model['noi_cents']}")
        fetched = validate_success(
            api.get_underwriting_model(deal["id"], model["id"],
                                       analyst_headers))
        assert fetched["noi_cents"] == 1700000

    def test_noi_market_variant_diverges(self, api, analyst_headers):
        """PRD §3.3: "The two variants therefore produce different NOI from
        identical lease data — the market variant's smaller allowance yields
        the higher NOI."

        Design: Difficulty/dual_variant_calc/noi_conservative_vs_market_variant_on_underwriting_domain
        """
        deal, _prop, _t1, _t2, _la, _lb = _two_lease_deal(api,
                                                          analyst_headers)
        model_cons = create_model(deal["id"], "CONSERVATIVE")
        model_mkt = create_model(deal["id"], "MARKET")
        # 2,000,000 gross - 12% (240,000) = 1,760,000
        assert model_mkt["noi_cents"] == 1760000
        assert model_cons["noi_cents"] == 1700000
        divergence = model_mkt["noi_cents"] - model_cons["noi_cents"]
        assert divergence == 60000, (
            f"The variant flag alone drives a 60000-cent divergence, "
            f"got {divergence}")


class TestWaltCombinatorics:
    def _walt_deal(self, api, analyst_headers):
        """Two VERIFIED leases (1.2M / 0.8M) plus one permanently-DRAFT
        lease (0.5M, unrated unguaranteed tenant)."""
        deal = create_deal(deal_name="WaltDeal", deal_type="MULTI_TENANT",
                           target_close_date="2026-12-01T00:00:00Z",
                           purchase_price_cents=25000000,
                           earnest_money_cents=500000)
        prop = add_property(deal["id"], address="200 Oak Ave",
                            property_type="INDUSTRIAL", rentable_sqft=50000,
                            year_built=2015)
        t1 = create_approved_tenant(legal_name="WT1", credit_score=810,
                                    annual_revenue_cents=200000000)
        t2 = create_approved_tenant(legal_name="WT2", credit_score=780,
                                    annual_revenue_cents=150000000)
        t3 = create_tenant(legal_name="WT3", credit_rating="UNRATED",
                           credit_score=500, annual_revenue_cents=10000000,
                           is_guaranteed=False)
        lease_a = add_verified_lease(
            deal["id"], prop["id"], t1["id"], annual_base_rent_cents=1200000,
            lease_commencement_date="2019-01-01T00:00:00Z",
            lease_expiration_date="2036-08-01T00:00:00Z")
        lease_b = add_verified_lease(
            deal["id"], prop["id"], t2["id"], lease_type="NN",
            annual_base_rent_cents=800000,
            lease_expiration_date="2032-06-01T00:00:00Z")
        lease_c = add_lease(
            deal["id"], prop["id"], t3["id"], lease_type="GROSS",
            annual_base_rent_cents=500000,
            lease_commencement_date="2022-01-01T00:00:00Z",
            lease_expiration_date="2030-01-01T00:00:00Z")
        return deal, prop, lease_a, lease_b, lease_c

    def test_walt_rent_weighted_over_verified_leases(self, api,
                                                     analyst_headers):
        """PRD §3.3: "The `walt_months` is the weighted average lease term
        across the same included lease set (statuses `VERIFIED`,
        `ESTOPPEL_PENDING`, `ESTOPPELED`): each lease contributes its
        `annual_base_rent_cents` as the weight and its `remaining_term_months`
        as the term; the WALT is the sum over leases of weight-times-term
        divided by the sum of weights, rounded half up to integer months."

        Design: Difficulty/combinatorial_formula/walt_weighted_scoring_mode_a_nonlinear_interaction
        """
        deal, prop, lease_a, lease_b, _lc = self._walt_deal(api,
                                                            analyst_headers)
        a = validate_success(api.get_lease(deal["id"], prop["id"],
                                           lease_a["id"], analyst_headers))
        b = validate_success(api.get_lease(deal["id"], prop["id"],
                                           lease_b["id"], analyst_headers))
        assert a["remaining_term_months"] == 120
        assert b["remaining_term_months"] == 70

        model = create_model(deal["id"], "CONSERVATIVE")
        # round_half_up((1200000*120 + 800000*70) / 2000000) = 100
        assert model["walt_months"] == 100, (
            f"WALT must be 100 months, got {model['walt_months']}")

    def test_draft_lease_excluded_from_noi_and_walt(self, api,
                                                    analyst_headers):
        """PRD §3.3: "Collect every lease across all of the deal's properties
        whose status is `VERIFIED`, `ESTOPPEL_PENDING`, or `ESTOPPELED` —
        `DRAFT` and `EXPIRED` leases are excluded — and sum their
        `annual_base_rent_cents` into a gross rent figure."

        Design: Difficulty/combinatorial_formula/walt_weighted_scoring_mode_a_nonlinear_interaction
        """
        deal, _prop, _la, _lb, lease_c = self._walt_deal(api,
                                                         analyst_headers)
        assert lease_c["status"] == "DRAFT"
        model = create_model(deal["id"], "CONSERVATIVE")
        # The DRAFT lease's 500,000 rent is excluded from both aggregates.
        assert model["noi_cents"] == 1700000, (
            "DRAFT lease excluded from NOI: 2,000,000 * 0.85 = 1,700,000")
        assert model["walt_months"] == 100, (
            "DRAFT lease excluded from the WALT input set")


class TestNoiInputSetFiltering:
    def test_noi_input_set_filtering_excludes_draft_leases(
            self, api, analyst_headers):
        """PRD §3.3: "`DRAFT` and `EXPIRED` leases are excluded"
        PRD §3.3: "The arithmetic is integer multiplication followed by
        truncation to whole cents; no rounding mode applies."

        Design: Corner/calculations/noi_input_set_filtering_excludes_draft_leases
        """
        deal = create_deal(deal_name="FilterDeal", deal_type="MULTI_TENANT",
                           purchase_price_cents=15000000)
        prop = add_property(deal["id"], address="1 Filter St",
                            rentable_sqft=8000)
        tenant = create_approved_tenant(legal_name="FT")
        lease1 = add_verified_lease(deal["id"], prop["id"], tenant["id"],
                                    annual_base_rent_cents=1000000)
        add_lease(deal["id"], prop["id"], tenant["id"], lease_type="NN",
                  annual_base_rent_cents=500000,
                  lease_commencement_date="2021-01-01T00:00:00Z",
                  lease_expiration_date="2033-01-01T00:00:00Z")

        model = create_model(deal["id"], "CONSERVATIVE")
        assert model["noi_cents"] == 850000, (
            "Only the VERIFIED lease counts: 1,000,000 * 0.85 = 850,000")
        # WALT over the single VERIFIED lease: rtm(2036-01-01) = 113 months
        # per PRD §3.2: (2036-2026)*12 + (1-8) = 113; expiry day 1 is not
        # earlier than clock day 1, so no partial-month decrement.
        assert model["walt_months"] == 113
        assert lease1["remaining_term_months"] == 113


class TestCapRateBand:
    def test_cap_rate_constants_band_enforced(self, api, analyst_headers):
        """PRD §3.3: "Submission is only accepted when the cap rate lands in
        the band from 300 to 1200 basis points inclusive; outside the band the
        submission is rejected with `ERR_CAP_RATE_OUT_OF_BAND` (HTTP 422)."

        Design: Corner/calculations/cap_rate_constants_band_enforced
        """
        deal = create_deal(deal_name="BandDeal",
                           purchase_price_cents=50000000,
                           earnest_money_cents=500000)
        prop = add_property(deal["id"], address="1 Band St")
        tenant = create_approved_tenant(legal_name="BT")
        add_verified_lease(deal["id"], prop["id"], tenant["id"],
                           annual_base_rent_cents=1000000)
        model = create_model(deal["id"], "CONSERVATIVE")
        # NOI 850,000 on a 50,000,000 price -> cap = 170 bps, below the floor.
        assert model["cap_rate_bps"] == 170

        resp = api.submit_underwriting_model(deal["id"], model["id"],
                                             analyst_headers)
        validate_error(resp, ApiErrorId.ERR_CAP_RATE_OUT_OF_BAND)


class TestModelSegregationOfDuties:
    def test_model_approve_sod_violation_same_user(self, api):
        """PRD §2.10: "Approving or rejecting an underwriting model requires
        the `UnderwritingCommittee` actor's `X-User-ID` to differ from the
        analyst identity that submitted the model."
        PRD §2.10: "a match is rejected with `ERR_SOD_VIOLATION` (HTTP 403)"

        Design: Corner/state_machines/model_approve_sod_violation_same_user
        """
        deal = create_deal(deal_name="SODDeal")
        prop = add_property(deal["id"], address="1 SOD St")
        tenant = create_approved_tenant(legal_name="SODT")
        add_verified_lease(deal["id"], prop["id"], tenant["id"])
        model = create_model(deal["id"])
        # Submitted under X-User-ID "analyst-1" (the shared analyst constant).
        submit_model(deal["id"], model["id"],
                     submitter_headers=TEST_USERS["analyst_headers"])

        same_user = make_committee_headers("analyst-1")
        resp = api.approve_underwriting_model(deal["id"], model["id"],
                                              same_user)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        other_member = make_committee_headers("committee-2")
        approved = validate_success(api.approve_underwriting_model(
            deal["id"], model["id"], other_member))
        assert approved["status"] == "APPROVED"


class TestVersionPinning:
    def _setup_pinned_then_superseded(self):
        ctx = setup_psa_executed(deal_name="PinDeal", dd_period_days=30,
                                 financing_contingency_days=0)
        deal_id = ctx["deal"]["id"]
        m1 = ctx["model"]
        m2 = create_model(deal_id, "MARKET")
        submit_model(deal_id, m2["id"])
        m2 = approve_model(deal_id, m2["id"])
        return ctx, m1, m2

    def test_version_pinning_on_approval_layer(self, api, analyst_headers):
        """PRD §2.11: "Approving a newer model afterwards supersedes the
        previously approved one, but the pin does not move once the deal has
        reached `PSA_EXECUTED` — the deal stays pinned to the model the
        committee saw when it executed."
        PRD §3.3: "Approval flips every other `APPROVED` model on the deal to
        `SUPERSEDED`"

        Design: Corner/cross_cutting_layers/version_pinning_on_approval_layer
        """
        ctx, m1, m2 = self._setup_pinned_then_superseded()
        deal = get_deal(ctx["deal"]["id"])
        assert deal["pinned_underwriting_model_id"] == m1["id"], (
            "The pin does not auto-refresh after PSA execution")
        m1_after = validate_success(api.get_underwriting_model(
            ctx["deal"]["id"], m1["id"], analyst_headers))
        assert m1_after["status"] == "SUPERSEDED"
        assert m2["status"] == "APPROVED"

    def test_error_stale_underwriting_model_on_certify(
            self, api, dd_officer_headers):
        """PRD §2.11: "Certification of clear-to-close then checks that the
        pinned model is still the latest approved model; if a newer approval
        has superseded it, certification fails with
        `ERR_STALE_UNDERWRITING_MODEL` until the pin is refreshed."
        PRD §3.10: "every milestone must be `SATISFIED` or `WAIVED` (else
        `ERR_MILESTONES_OUTSTANDING`)"
        PRD §3.5: "starting the first milestone moves the deal itself from
        `PSA_EXECUTED` into `DUE_DILIGENCE`"

        Design: Corner/errors/error_stale_underwriting_model_on_certify
        """
        ctx, m1, m2 = self._setup_pinned_then_superseded()
        deal_id = ctx["deal"]["id"]
        committee = make_committee_headers("committee-early")

        # Move the deal into DUE_DILIGENCE; with the other milestones still
        # PENDING, the milestone gate — listed first among the §3.10 gates —
        # reports first.
        walkthrough = get_milestone_by_type(deal_id, "FINAL_WALKTHROUGH")
        validate_success(api.start_milestone(deal_id, walkthrough["id"],
                                             dd_officer_headers))
        early = api.certify_clear_to_close(deal_id, committee)
        validate_error(early, ApiErrorId.ERR_MILESTONES_OUTSTANDING)

        # Once every milestone is satisfied, the armed staleness gate fires.
        complete_all_open_milestones(deal_id)
        resp = api.certify_clear_to_close(deal_id, committee)
        validate_error(resp, ApiErrorId.ERR_STALE_UNDERWRITING_MODEL)

        deal = get_deal(deal_id)
        assert deal["pinned_underwriting_model_id"] == m1["id"]
        assert m2["status"] == "APPROVED"
