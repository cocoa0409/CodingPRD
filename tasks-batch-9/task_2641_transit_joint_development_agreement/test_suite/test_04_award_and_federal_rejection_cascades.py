"""Cascades whose links each cause the next: the award that reaches sibling
solicitations through the site, and the grantor's rejection that reaches bus
bay capacity through the agreement's negotiation dimension."""

from test_helpers import (
    assert_money,
    build_assessment,
    build_approved_staging_window,
    build_developer,
    build_encumbered_site_context,
    build_proposal,
    build_shared_facility,
    build_site,
    build_solicitation,
    certify_assessment,
    close_solicitation,
    create_fee_proposal_payload,
    determination_payload,
    get_success_data,
    issue_solicitation,
    make_developer_headers,
    read_agreement,
    read_shared_facility,
    read_site,
    release_site,
    set_logical_clock,
    validate_success,
)

GUM_RIDGE_SITE = {
    "site_code": "TJD-A-007",
    "name": "Gum Ridge Transit Village",
    "address_line": "9 Gum Ridge",
    "parcel_area_sqft": 102000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}

HAZEL_AVENUE_SITE = {
    "site_code": "TJD-A-008",
    "name": "Hazel Avenue Bus Base Surplus",
    "address_line": "410 Hazel Ave",
    "parcel_area_sqft": 96000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


class TestAwardCascade:
    """One parcel, two issued solicitations, and an award on only one of them."""

    @staticmethod
    def _two_issued_solicitations(api):
        set_logical_clock()
        site = build_site(**GUM_RIDGE_SITE)
        certify_assessment(build_assessment(site["id"])["id"])
        release_site(site["id"])
        developer_a = build_developer(legal_name="Alder Transit Partners LLC",
                                     contact_email="dev-a@example.com",
                                     prequalified=True,
                                     debarment_status="CLEAR")
        developer_b = build_developer(legal_name="Birch Union Development Co",
                                     contact_email="dev-b@example.com",
                                     prequalified=True,
                                     debarment_status="CLEAR")
        solicitation_a = issue_solicitation(build_solicitation(
            site["id"], solicitation_type="RFP",
            response_deadline="2026-09-15T00:00:00Z",
            min_proposals_required=1, joint_use_required=False)["id"])
        solicitation_b = issue_solicitation(build_solicitation(
            site["id"], solicitation_type="RFQ",
            response_deadline="2026-09-20T00:00:00Z",
            min_proposals_required=1, joint_use_required=False)["id"])
        proposal_a = build_proposal(solicitation_a["id"], developer_a["id"],
                                    joint_use_committed=False)
        proposal_b = get_success_data(api.create_proposal(
            solicitation_b["id"],
            create_fee_proposal_payload(developer_b["id"],
                                        proposed_purchase_price_cents=42_000_000,
                                        affordable_units=36, total_units=180,
                                        transit_ridership_uplift=1200,
                                        design_compliance_score=70,
                                        joint_use_committed=False),
            make_developer_headers(developer_b["id"])))
        return {
            "site": read_site(site["id"]),
            "solicitation_a": close_solicitation(solicitation_a["id"]),
            "solicitation_b": solicitation_b,
            "proposal_a": proposal_a,
            "proposal_b": proposal_b,
        }

    @staticmethod
    def _award(api, real_estate_officer, ctx):
        return validate_success(api.award_solicitation(
            ctx["solicitation_a"]["id"],
            {"proposal_id": ctx["proposal_a"]["id"],
             "negotiation_start_date": "2026-08-15",
             "negotiation_end_date": "2027-01-15"},
            real_estate_officer))

    def test_award_moves_the_solicitation_and_its_winning_proposal(
            self, api, real_estate_officer):
        """PRD §3.4: "On success the solicitation moves `ISSUED → CLOSED` and
        every responsive proposal is assigned a `rank`." and "Ranks are then
        assigned as contiguous integers starting at 1 with no gaps." The award
        then runs its cascade: "The solicitation moves `CLOSED → AWARDED`. The
        awarded proposal moves `SUBMITTED → SELECTED` or
        `SHORTLISTED → SELECTED` (hop 1)."

        Design: Difficulty/transitive_cascade/award_cascade_site_to_sibling_solicitation_to_its_proposals
        """
        ctx = self._two_issued_solicitations(api)
        assert ctx["solicitation_a"]["status"] == "CLOSED"

        awarded = self._award(api, real_estate_officer, ctx)

        assert awarded["status"] == "AWARDED"
        winner = validate_success(api.get_proposal(ctx["proposal_a"]["id"],
                                                   real_estate_officer))
        assert winner["status"] == "SELECTED"
        assert winner["rank"] == 1

    def test_award_opens_an_active_negotiation_period_over_the_supplied_interval(
            self, api, real_estate_officer):
        """PRD §3.4: "Because that proposal became `SELECTED`, a new exclusive
        negotiation period is created over the supplied interval with `status`
        `ACTIVE`, `extension_count` 0, `start_date` from
        `negotiation_start_date` and `end_date` from `negotiation_end_date`
        (hop 2)."

        Design: Difficulty/transitive_cascade/award_cascade_site_to_sibling_solicitation_to_its_proposals
        """
        ctx = self._two_issued_solicitations(api)

        self._award(api, real_estate_officer, ctx)

        periods = validate_success(api.list_negotiation_periods(
            real_estate_officer, params={"site_id": ctx["site"]["id"]}))
        assert len(periods) == 1
        period = periods[0]
        assert period["status"] == "ACTIVE"
        assert period["extension_count"] == 0
        assert period["proposal_id"] == ctx["proposal_a"]["id"]
        assert period["start_date"] == "2026-08-15"
        assert period["end_date"] == "2027-01-15"

    def test_the_active_period_carries_the_site_under_agreement(
            self, api, real_estate_officer):
        """PRD §3.4: "Because that period became `ACTIVE`, the site moves
        `SOLICITATION_READY → UNDER_AGREEMENT` with its `version` bumped by 1
        (hop 3) — a site already `UNDER_AGREEMENT` stays there, and an
        additional non-overlapping period does not change site status."

        Design: Difficulty/transitive_cascade/award_cascade_site_to_sibling_solicitation_to_its_proposals
        """
        ctx = self._two_issued_solicitations(api)
        assert ctx["site"]["status"] == "SOLICITATION_READY"
        version_before = ctx["site"]["version"]

        self._award(api, real_estate_officer, ctx)

        site = read_site(ctx["site"]["id"])
        assert site["status"] == "UNDER_AGREEMENT"
        assert site["version"] == version_before + 1

    def test_the_site_transition_cancels_the_sibling_and_rejects_its_proposal(
            self, api, real_estate_officer):
        """PRD §3.4: "Because the site became `UNDER_AGREEMENT`, every **other**
        solicitation on the same site that is `DRAFT` or `ISSUED` moves to
        `CANCELLED`, each with its `version` bumped by 1 (hop 4); "other"
        excludes the solicitation being awarded, so an award never cancels
        itself. Because those solicitations became `CANCELLED`, each of their
        proposals whose status was `SUBMITTED` or `SHORTLISTED` moves to
        `REJECTED`, each with its `version` bumped by 1 and its parent's
        `responsive_proposal_count` refreshed (hop 5)." The sibling was never
        closed, and §3.4 assigns a `rank` only when a solicitation closes, so
        the rejected proposal keeps `rank` null.

        Design: Difficulty/transitive_cascade/award_cascade_site_to_sibling_solicitation_to_its_proposals
        """
        ctx = self._two_issued_solicitations(api)
        # Read the sibling immediately before the award: PRD §3.3 already bumped
        # its version when proposal_b's submission incremented its
        # `responsive_proposal_count`, so the snapshot taken at issuance is stale
        # and the hop-4 bump must be measured from the sibling's current version.
        sibling_version_before = validate_success(api.get_solicitation(
            ctx["solicitation_b"]["id"], real_estate_officer))["version"]

        self._award(api, real_estate_officer, ctx)

        sibling = validate_success(api.get_solicitation(
            ctx["solicitation_b"]["id"], real_estate_officer))
        assert sibling["status"] == "CANCELLED"
        assert sibling["version"] == sibling_version_before + 1
        orphan = validate_success(api.get_proposal(ctx["proposal_b"]["id"],
                                                   real_estate_officer))
        assert orphan["status"] == "REJECTED"
        assert orphan["rank"] is None


class TestFederalRejectionCascade:
    """A board-approved deal with a filed disposition and four bays held for
    construction, unwound by the grantor's refusal."""

    @staticmethod
    def _filed_with_approved_window():
        ctx = build_encumbered_site_context(
            narrative="Ground lease of surplus bus base frontage.",
            negotiation_via="award",
            site_overrides=dict(HAZEL_AVENUE_SITE),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False},
            agreement_overrides={"site_area_share_pct": 60,
                                 "joint_use_committed": False},
            resolution_number="R-2026-118")
        ctx["facility"] = build_shared_facility(ctx["site"]["id"],
                                                facility_type="BUS_BAY",
                                                total_bay_capacity=6,
                                                maintenance_responsibility="SHARED",
                                                cost_share_pct_developer=0.35)
        ctx["window"] = build_approved_staging_window(
            ctx["agreement"]["id"], ctx["facility"]["id"], ctx["developer"]["id"],
            start_at="2026-09-01T08:00:00Z", end_at="2026-09-08T08:00:00Z",
            bays_occupied=4, purpose="Excavation laydown")
        ctx["facility"] = read_shared_facility(ctx["facility"]["id"])
        return ctx

    @staticmethod
    def _reject(api, grants_compliance_officer, ctx):
        return validate_success(api.record_disposition_determination(
            ctx["disposition_request"]["id"],
            determination_payload(
                "REJECTED",
                "Grantor withholds concurrence in the below-market transfer."),
            grants_compliance_officer))

    def test_filing_pledges_the_area_share_of_the_basis_and_encumbers_the_site(
            self, api, grants_compliance_officer):
        """PRD §3.8: "The slice this filing pledges is
        `federal_interest_amount_cents`: the site's
        `federal_interest_basis_cents` multiplied by the agreement's
        `site_area_share_pct` and divided by 100, rounded half up to a whole
        cent." The worked case is pinned: "an agreement disposing of sixty
        percent of the parcel pledges 727,500 cents and leaves 485,000 cents
        unencumbered." On filing "the site's
        `federal_interest_encumbered_cents` is increased by the pledged amount,
        its `federal_interest_unencumbered_cents` is decreased by exactly the
        same amount".

        Design: Difficulty/transitive_cascade/federal_rejection_cascade_suspends_staging_and_releases_encumbrance
        """
        ctx = self._filed_with_approved_window()

        assert_money(ctx["disposition_request"]["federal_interest_amount_cents"],
                     727_500, "federal_interest_amount_cents")
        assert ctx["disposition_request"]["determination"] == "PENDING"
        site = ctx["site"]
        assert_money(site["federal_interest_basis_cents"], 1_212_500,
                     "federal_interest_basis_cents")
        assert_money(site["federal_interest_encumbered_cents"], 727_500,
                     "federal_interest_encumbered_cents")
        assert_money(site["federal_interest_unencumbered_cents"], 485_000,
                     "federal_interest_unencumbered_cents")

    def test_rejection_flips_the_request_and_both_agreement_dimensions(
            self, api, grants_compliance_officer):
        """PRD §3.8: "Hop 1: the request moves `PENDING → REJECTED` with
        `determined_at` stamped. Hop 2: because the request was rejected, the
        agreement moves `SUBMITTED → FTA_REJECTED` on its federal dimension,
        and — if its `negotiation_status` was `BOARD_APPROVED` — that dimension
        moves `BOARD_APPROVED → REVISION_REQUESTED` as well." The same hop sets
        `revision_notes` to "the literal prefix `federal disposition rejected: `
        followed by the recorded `condition_notes`", and
        "`board_resolution_number` is cleared back to null".

        Design: Difficulty/transitive_cascade/federal_rejection_cascade_suspends_staging_and_releases_encumbrance
        """
        ctx = self._filed_with_approved_window()
        assert ctx["agreement"]["negotiation_status"] == "BOARD_APPROVED"

        rejected = self._reject(api, grants_compliance_officer, ctx)

        assert rejected["determination"] == "REJECTED"
        assert rejected["determined_at"] is not None
        agreement = read_agreement(ctx["agreement"]["id"])
        assert agreement["federal_approval_status"] == "FTA_REJECTED"
        assert agreement["negotiation_status"] == "REVISION_REQUESTED"
        assert agreement["revision_notes"] == (
            "federal disposition rejected: "
            "Grantor withholds concurrence in the below-market transfer.")
        assert agreement["board_resolution_number"] is None

    def test_revision_requested_supersedes_the_valuation_and_frees_the_bays(
            self, api, grants_compliance_officer):
        """PRD §3.8: "Hop 3a: because `negotiation_status` became
        `REVISION_REQUESTED`, the agreement's referenced valuation determination
        moves `CERTIFIED → SUPERSEDED`, so the corrected agreement will need a
        fresh appraisal certified before it can go back to review. Hop 3b: also
        because `negotiation_status` became `REVISION_REQUESTED`, every staging
        window of this agreement whose status is `APPROVED` moves
        `APPROVED → SUSPENDED`. Hop 4: because those windows left `APPROVED`,
        each one's shared facility has its `available_bay_capacity` increased by
        that window's `bays_occupied`, the window's `capacity_released` is set
        to true, and the facility's `version` is bumped by 1".

        Design: Difficulty/transitive_cascade/federal_rejection_cascade_suspends_staging_and_releases_encumbrance
        """
        ctx = self._filed_with_approved_window()
        assert ctx["window"]["status"] == "APPROVED"
        assert ctx["facility"]["available_bay_capacity"] == 2
        facility_version_before = ctx["facility"]["version"]

        self._reject(api, grants_compliance_officer, ctx)

        valuation = validate_success(api.get_valuation(ctx["valuation"]["id"],
                                                       grants_compliance_officer))
        assert valuation["status"] == "SUPERSEDED"
        window = validate_success(api.get_staging_window(
            ctx["window"]["id"], grants_compliance_officer))
        assert window["status"] == "SUSPENDED"
        assert window["capacity_released"] is True
        facility = read_shared_facility(ctx["facility"]["id"])
        assert facility["available_bay_capacity"] == 6
        assert facility["version"] == facility_version_before + 1

    def test_rejection_releases_the_encumbrance_and_restores_the_ledger(
            self, api, grants_compliance_officer):
        """PRD §3.8: "Hop 5: the site's `federal_interest_encumbered_cents` is
        decreased by this request's `federal_interest_amount_cents` and its
        `federal_interest_unencumbered_cents` is increased by exactly the same
        amount, with the site's `version` bumped by 1, restoring the ledger
        identity of §2.7."

        Design: Difficulty/transitive_cascade/federal_rejection_cascade_suspends_staging_and_releases_encumbrance
        """
        ctx = self._filed_with_approved_window()
        site_version_before = ctx["site"]["version"]

        self._reject(api, grants_compliance_officer, ctx)

        site = read_site(ctx["site"]["id"])
        assert_money(site["federal_interest_encumbered_cents"], 0,
                     "federal_interest_encumbered_cents")
        assert_money(site["federal_interest_unencumbered_cents"], 1_212_500,
                     "federal_interest_unencumbered_cents")
        assert_money(site["federal_interest_basis_cents"], 1_212_500,
                     "federal_interest_basis_cents")
        assert site["version"] == site_version_before + 1
