"""Thresholds decided by one hundredth of a point, and by one proposal."""

from test_helpers import (
    ApiErrorId,
    build_assessment,
    build_developer,
    build_proposal,
    build_site,
    build_solicitation,
    certify_assessment,
    create_local_only_site_payload,
    issue_solicitation,
    release_site,
    set_logical_clock,
    validate_error,
    validate_success,
)

READY_SITE = {
    "site_code": "TJD-B-001",
    "name": "Kingfisher Park-and-Ride A",
    "address_line": "1 Kingfisher Way",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}

EDGE_SITE = dict(READY_SITE,
                 site_code="TJD-B-002",
                 name="Kingfisher Park-and-Ride B",
                 address_line="2 Kingfisher Way",
                 federal_interest_pct=2.6)

BOUNDARY_SCORES = {
    "environmental_score": 80,
    "utility_score": 75,
    "access_score": 70,
    "entitlement_score": 60,
    "encumbrance_count": 1,
}


class TestReadinessReleaseBoundary:
    """Identical sub-scores on two parcels whose federal interest differs by one
    tenth of a percent."""

    @staticmethod
    def _certified_site(site_overrides):
        site = build_site(**site_overrides)
        assessment = certify_assessment(
            build_assessment(site["id"], **BOUNDARY_SCORES)["id"])
        return site, assessment

    def test_exactly_seventy_is_ready_and_the_parcel_reaches_the_market(
            self, api, real_estate_officer):
        """PRD §3.1: "A score of at least 70.00 is `READY`; a score of at least
        50.00 but below 70.00 is `CONDITIONAL`; anything below 50.00 is
        `NOT_READY`. The `READY` boundary is inclusive on the lower side, so
        exactly 70.00 qualifies and 69.99 does not." The worked case pins the
        score: "sub-scores of 80, 75, 70 and 60 with one encumbrance on a parcel
        whose federal interest is two and a half percent yield a preliminary
        score of 71.25 and a certified score of 70.00 from identical stored
        inputs." Release then "advances it `ASSESSED → SOLICITATION_READY`".

        Design: Difficulty/boundary_precision_check/release_for_solicitation_readiness_boundary_70_00_versus_69_99
        """
        set_logical_clock()
        site, assessment = self._certified_site(READY_SITE)

        assert assessment["composite_score"] == 70.00
        assert assessment["tier"] == "READY"
        released = validate_success(api.release_site_for_solicitation(
            site["id"], real_estate_officer))
        assert released["status"] == "SOLICITATION_READY"

    def test_one_hundredth_below_the_boundary_is_conditional_and_refused(
            self, api, real_estate_officer):
        """PRD §3.1: "The `READY` boundary is inclusive on the lower side, so
        exactly 70.00 qualifies and 69.99 does not." Release "is refused in two
        ways: a site whose status is not `ASSESSED` reports
        `ERR_INVALID_SITE_STATE`, and a site whose `readiness_tier` is anything
        other than `READY` reports `ERR_SITE_NOT_READY`." The score itself comes
        from "The **federal interest penalty** is one tenth of a point for each
        whole percent of `federal_interest_pct` on the parcel", subtracted on
        unrounded operands.

        Design: Difficulty/boundary_precision_check/release_for_solicitation_readiness_boundary_70_00_versus_69_99
        """
        set_logical_clock()
        site, assessment = self._certified_site(EDGE_SITE)

        assert assessment["composite_score"] == 69.99
        assert assessment["tier"] == "CONDITIONAL"

        response = api.release_site_for_solicitation(site["id"],
                                                    real_estate_officer)

        validate_error(response, ApiErrorId.SITE_NOT_READY)
        unreleased = validate_success(api.get_site(site["id"],
                                                   real_estate_officer))
        assert unreleased["status"] == "ASSESSED"
        assert unreleased["readiness_composite_score"] == 69.99


class TestResponsiveProposalMinimum:
    """A locally funded parcel taken to market, then closed with nothing in
    hand and with exactly the minimum in hand."""

    LARCH_STREET_SITE = {
        "site_code": "TJD-B-003",
        "name": "Larch Street Infill Site",
        "address_line": "60 Larch St",
        "parcel_area_sqft": 47000,
        "transit_facility_present": False,
    }

    @staticmethod
    def _issued_solicitation(api, real_estate_officer):
        set_logical_clock()
        # PRD §4: "Creating a new resource returns HTTP 201 with the created
        # resource in `data`."
        site = validate_success(api.create_site(
            create_local_only_site_payload(
                **TestResponsiveProposalMinimum.LARCH_STREET_SITE),
            real_estate_officer), 201)
        assessment = certify_assessment(
            build_assessment(site["id"], **BOUNDARY_SCORES)["id"])
        release_site(site["id"])
        solicitation = issue_solicitation(build_solicitation(
            site["id"], min_proposals_required=1,
            joint_use_required=False)["id"])
        return site, assessment, solicitation

    def test_closing_with_zero_responsive_proposals_is_refused(
            self, api, real_estate_officer):
        """PRD §3.4: "The system first recomputes `responsive_proposal_count` as
        the number of this solicitation's proposals whose status is `SUBMITTED`
        or `SHORTLISTED`, and if that count is strictly below
        `min_proposals_required` the close is refused with
        `ERR_NO_RESPONSIVE_PROPOSALS`. The empty case is the common one: zero
        responsive proposals against a `min_proposals_required` of 1 fails
        here." The parcel carries no federal interest, so §3.1's certified score
        of 70.25 is the weighted sum less the encumbrance penalty alone.

        Design: Difficulty/boundary_precision_check/solicitation_close_with_zero_responsive_proposals
        """
        site, assessment, solicitation = self._issued_solicitation(
            api, real_estate_officer)
        assert assessment["composite_score"] == 70.25
        assert solicitation["status"] == "ISSUED"

        response = api.close_solicitation(solicitation["id"],
                                          real_estate_officer)

        validate_error(response, ApiErrorId.NO_RESPONSIVE_PROPOSALS)
        unchanged = validate_success(api.get_solicitation(solicitation["id"],
                                                          real_estate_officer))
        assert unchanged["status"] == "ISSUED"
        assert unchanged["responsive_proposal_count"] == 0

    def test_exactly_one_responsive_proposal_meets_the_minimum(
            self, api, real_estate_officer):
        """PRD §3.4: "if that count is strictly below `min_proposals_required`
        the close is refused with `ERR_NO_RESPONSIVE_PROPOSALS`" — one proposal
        against a minimum of one is not below it, and "On success the
        solicitation moves `ISSUED → CLOSED` and every responsive proposal is
        assigned a `rank`."

        Design: Difficulty/boundary_precision_check/solicitation_close_with_zero_responsive_proposals
        """
        site, _assessment, solicitation = self._issued_solicitation(
            api, real_estate_officer)
        developer = build_developer(prequalified=True, debarment_status="CLEAR")
        proposal = build_proposal(solicitation["id"], developer["id"],
                                  joint_use_committed=False)

        closed = validate_success(api.close_solicitation(solicitation["id"],
                                                         real_estate_officer))

        assert closed["status"] == "CLOSED"
        assert closed["responsive_proposal_count"] == 1
        ranked = validate_success(api.get_proposal(proposal["id"],
                                                   real_estate_officer))
        assert ranked["rank"] == 1
