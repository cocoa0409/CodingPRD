"""Formulas whose evaluation order is pinned: the agency revenue waterfall and
the shared-facility maintenance allocation."""

from test_helpers import (
    assert_maintenance_split_conserved,
    assert_money,
    assert_score,
    build_context,
    build_shared_facility,
    create_agreement_payload,
    create_maintenance_charge_payload,
    maintenance_line_item,
    read_agreement,
    validate_success,
)

THREE_EQUAL_LINES = [
    maintenance_line_item("Plaza sweeping", 41250),
    maintenance_line_item("Elevator service", 41250),
    maintenance_line_item("Lighting", 41250),
]


class TestAgencyRevenueCreditTier:
    """The capital credit rate is keyed on the pre-credit subtotal."""

    @staticmethod
    def _ready_to_draft():
        return build_context(
            stage="VALUATION", negotiation_via="award",
            site_overrides={"site_code": "TJD-A-003",
                            "name": "Cedar Transit Center Air Rights",
                            "address_line": "300 Cedar Ave",
                            "parcel_area_sqft": 91000},
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False})

    def test_capital_credit_keyed_on_the_pre_credit_subtotal(self, api,
                                                             real_estate_officer):
        """PRD §3.6: "a capital credit rate is looked up **from that pre-credit
        subtotal and from nothing else**: a subtotal of at least 5,000,000 cents
        earns twelve hundredths; at least 2,500,000 but below 5,000,000 earns
        eight hundredths". The worked case: "a `GROUND_LEASE` with 2,000,000
        cents of base rent, 12,000,000 cents of projected gross revenue and a
        five-hundredths revenue share yields a participation of 600,000 and a
        subtotal of 2,600,000, which falls in the eight-hundredths tier; with 50
        of 200 units committed as affordable the three-hundredths bonus applies,
        giving eleven hundredths; the capital credit is 286,000 and the annual
        revenue to the agency is 2,314,000."

        Design: Difficulty/combinatorial_formula/agency_revenue_credit_tier_keyed_on_pre_credit_subtotal
        """
        ctx = self._ready_to_draft()

        agreement = validate_success(api.create_agreement(
            create_agreement_payload(
                ctx["site"]["id"], ctx["developer"]["id"], ctx["proposal"]["id"],
                ctx["valuation"]["id"], structure="GROUND_LEASE", term_years=20,
                base_rent_cents=2_000_000, revenue_share_pct=0.05,
                projected_gross_revenue_cents=12_000_000,
                affordable_units_committed=50, total_units=200,
                site_area_share_pct=60, joint_use_committed=False),
            real_estate_officer), 201)

        assert_money(agreement["capital_credit_cents"], 286_000,
                    "capital_credit_cents")
        assert_money(agreement["annual_revenue_to_agency_cents"], 2_314_000,
                    "annual_revenue_to_agency_cents")

    def test_credit_tier_is_not_keyed_on_the_post_credit_figure(
            self, api, real_estate_officer):
        """PRD §3.6: "it is resolved by keying the tier on the subtotal produced
        in step three, never on the post-credit figure produced in step six."
        And: "Keying the tier on the post-credit figure of 2,314,000 instead
        would drop it into the four-hundredths tier and produce 2,438,020 from
        the same inputs — a different and wrong answer."

        Design: Difficulty/combinatorial_formula/agency_revenue_credit_tier_keyed_on_pre_credit_subtotal
        """
        ctx = self._ready_to_draft()

        agreement = validate_success(api.create_agreement(
            create_agreement_payload(
                ctx["site"]["id"], ctx["developer"]["id"], ctx["proposal"]["id"],
                ctx["valuation"]["id"], base_rent_cents=2_000_000,
                revenue_share_pct=0.05,
                projected_gross_revenue_cents=12_000_000,
                affordable_units_committed=50, total_units=200,
                site_area_share_pct=60, joint_use_committed=False),
            real_estate_officer), 201)

        assert agreement["annual_revenue_to_agency_cents"] != 2_438_020, (
            "2438020 is the answer produced by keying the credit tier on the "
            "post-credit figure, which the pinned order forbids")
        assert_money(agreement["annual_revenue_to_agency_cents"], 2_314_000,
                    "annual_revenue_to_agency_cents")

    def test_consideration_capitalises_the_annual_revenue_over_twenty_years(
            self, api, real_estate_officer):
        """PRD §3.6: "For a `GROUND_LEASE` it is the
        `annual_revenue_to_agency_cents` just computed, capitalised over twenty
        years by simple integer multiplication". And: "Continuing the worked
        case, 2,314,000 capitalised over twenty years is 46,280,000 cents".

        Design: Difficulty/combinatorial_formula/agency_revenue_credit_tier_keyed_on_pre_credit_subtotal
        """
        ctx = self._ready_to_draft()

        agreement = validate_success(api.create_agreement(
            create_agreement_payload(
                ctx["site"]["id"], ctx["developer"]["id"], ctx["proposal"]["id"],
                ctx["valuation"]["id"], base_rent_cents=2_000_000,
                revenue_share_pct=0.05,
                projected_gross_revenue_cents=12_000_000,
                affordable_units_committed=50, total_units=200,
                site_area_share_pct=60, joint_use_committed=False),
            real_estate_officer), 201)

        assert_money(agreement["consideration_value_cents"], 46_280_000,
                    "consideration_value_cents")

    def test_drafted_agreement_opens_in_drafting_with_federal_filing_owed(
            self, api, real_estate_officer):
        """PRD §3.6: "A newly drafted agreement opens with `negotiation_status`
        `DRAFTING`. Its federal dimension is initialised from the parcel:
        `federal_approval_status` starts at `NOT_REQUIRED` when the site's
        `federal_interest_pct` is exactly 0, and at `NOT_SUBMITTED` otherwise."
        The stored record must report the same computed money as the create
        response.

        Design: Difficulty/combinatorial_formula/agency_revenue_credit_tier_keyed_on_pre_credit_subtotal
        """
        ctx = self._ready_to_draft()
        agreement = validate_success(api.create_agreement(
            create_agreement_payload(
                ctx["site"]["id"], ctx["developer"]["id"], ctx["proposal"]["id"],
                ctx["valuation"]["id"], base_rent_cents=2_000_000,
                revenue_share_pct=0.05,
                projected_gross_revenue_cents=12_000_000,
                affordable_units_committed=50, total_units=200,
                site_area_share_pct=60, joint_use_committed=False),
            real_estate_officer), 201)

        stored = read_agreement(agreement["id"])

        assert stored["negotiation_status"] == "DRAFTING"
        assert stored["federal_approval_status"] == "NOT_SUBMITTED", (
            "a parcel with a non-zero federal interest owes a filing, so the "
            f"federal dimension opens at NOT_SUBMITTED, got "
            f"{stored['federal_approval_status']}")
        assert_money(stored["capital_credit_cents"], 286_000,
                    "stored capital_credit_cents")
        assert_money(stored["annual_revenue_to_agency_cents"], 2_314_000,
                    "stored annual_revenue_to_agency_cents")
        assert_money(stored["consideration_value_cents"], 46_280_000,
                    "stored consideration_value_cents")


class TestMaintenanceAllocationRoundingOrder:
    """Each line is rounded before the shares are summed."""

    @staticmethod
    def _facility_and_agreement():
        ctx = build_context(
            stage="DRAFTING", negotiation_via="award",
            site_overrides={"site_code": "TJD-A-004",
                            "name": "Dogwood Station Plaza",
                            "address_line": "88 Dogwood Way",
                            "parcel_area_sqft": 65000},
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            proposal_overrides={"joint_use_committed": False},
            agreement_overrides={"joint_use_committed": False})
        ctx["facility"] = build_shared_facility(
            ctx["site"]["id"], facility_type="PLAZA", total_bay_capacity=6,
            maintenance_responsibility="SHARED", cost_share_pct_developer=0.35)
        return ctx

    def test_developer_share_rounds_each_line_before_accumulating(
            self, api, transit_operations_manager):
        """PRD §3.9: "each line item's `cost_cents` is multiplied by
        `effective_share_applied` and **rounded half up to a whole cent
        immediately**, and those rounded per-line amounts are accumulated into
        `developer_share_cents`." The worked case: "With
        `maintenance_responsibility` `SHARED`, a `cost_share_pct_developer` of
        thirty-five hundredths and three line items of 41,250 cents each, every
        line rounds from 14,437.5 up to 14,438, giving a `developer_share_cents`
        of 43,314 against a `total_cost_cents` of 123,750 and an
        `agency_share_cents` of 80,436."

        Design: Difficulty/combinatorial_formula/maintenance_allocation_rounds_each_line_then_sums
        """
        ctx = self._facility_and_agreement()

        charge = validate_success(api.create_maintenance_charge(
            ctx["facility"]["id"],
            create_maintenance_charge_payload(
                ctx["agreement"]["id"], THREE_EQUAL_LINES,
                period_start="2026-08-01", period_end="2026-08-31"),
            transit_operations_manager), 201)

        assert_money(charge["total_cost_cents"], 123_750, "total_cost_cents")
        assert_money(charge["developer_share_cents"], 43_314,
                    "developer_share_cents")
        assert_money(charge["agency_share_cents"], 80_436, "agency_share_cents")

    def test_summing_before_rounding_would_be_one_cent_short(
            self, api, transit_operations_manager):
        """PRD §3.9: "Summing the raw costs and rounding once at the end would
        give 43,313 — one cent less — and with five identical lines the gap
        widens to two cents. The per-line figure is the correct one."

        Design: Difficulty/combinatorial_formula/maintenance_allocation_rounds_each_line_then_sums
        """
        ctx = self._facility_and_agreement()

        charge = validate_success(api.create_maintenance_charge(
            ctx["facility"]["id"],
            create_maintenance_charge_payload(ctx["agreement"]["id"],
                                              THREE_EQUAL_LINES),
            transit_operations_manager), 201)

        assert charge["developer_share_cents"] != 43_313, (
            "43313 is the sum-then-round answer the per-line order forbids")
        assert_money(charge["developer_share_cents"], 43_314,
                    "developer_share_cents")

    def test_shared_responsibility_applies_the_facility_cost_share(
            self, api, transit_operations_manager):
        """PRD §3.9: "`effective_share_applied` is one whole when the facility's
        `maintenance_responsibility` is `DEVELOPER`, zero when it is `AGENCY`,
        and the facility's `cost_share_pct_developer` as it stands at request
        time when it is `SHARED`; prior maintenance charges never participate in
        the computation."

        Design: Difficulty/combinatorial_formula/maintenance_allocation_rounds_each_line_then_sums
        """
        ctx = self._facility_and_agreement()

        charge = validate_success(api.create_maintenance_charge(
            ctx["facility"]["id"],
            create_maintenance_charge_payload(ctx["agreement"]["id"],
                                              THREE_EQUAL_LINES),
            transit_operations_manager), 201)

        assert_score(charge["effective_share_applied"], 0.35,
                    "effective_share_applied")

    def test_agency_share_absorbs_the_rounding_residue(
            self, api, transit_operations_manager):
        """PRD §3.9: "`total_cost_cents` is the plain sum of every line item's
        `cost_cents`, and `agency_share_cents` is `total_cost_cents` less
        `developer_share_cents`, so the agency absorbs the rounding residue by
        construction and the two shares always add back to the total exactly."

        Design: Difficulty/combinatorial_formula/maintenance_allocation_rounds_each_line_then_sums
        """
        ctx = self._facility_and_agreement()

        charge = validate_success(api.create_maintenance_charge(
            ctx["facility"]["id"],
            create_maintenance_charge_payload(ctx["agreement"]["id"],
                                              THREE_EQUAL_LINES),
            transit_operations_manager), 201)

        assert_maintenance_split_conserved(charge)
        assert_money(charge["developer_share_cents"]
                     + charge["agency_share_cents"], 123_750,
                     "developer share plus agency share")
