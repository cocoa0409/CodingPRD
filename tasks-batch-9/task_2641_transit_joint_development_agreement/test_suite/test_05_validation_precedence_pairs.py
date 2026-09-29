"""Requests that fail two checks at once, where the PRD fixes which failure the
caller is told about."""

from test_helpers import (
    ApiErrorId,
    assert_money,
    build_context,
    build_developer,
    build_valuation,
    certify_valuation,
    create_agreement_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

IVY_COURT_SITE = {
    "site_code": "TJD-A-009",
    "name": "Ivy Court Kiss-and-Ride",
    "address_line": "12 Ivy Ct",
    "parcel_area_sqft": 58000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}

JUNIPER_YARD_SITE = {
    "site_code": "TJD-A-010",
    "name": "Juniper Yard Development Block",
    "address_line": "31 Juniper Yard",
    "parcel_area_sqft": 88000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


class TestSiteStateBeatsDebarment:
    """Drafting against a parcel that was never awarded, naming a debarred
    developer, so the state check and the safety check both fail."""

    @staticmethod
    def _released_site_with_a_debarred_developer():
        ctx = build_context(stage="PROPOSAL",
                            site_overrides=dict(IVY_COURT_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"min_proposals_required": 1,
                                                    "joint_use_required": False},
                            proposal_overrides={"joint_use_committed": False})
        ctx["debarred_developer"] = build_developer(
            legal_name="Juniper Excluded Builders Inc",
            contact_email="dev-bad@example.com",
            prequalified=True, debarment_status="DEBARRED")
        ctx["valuation"] = certify_valuation(
            build_valuation(ctx["site"]["id"])["id"])
        return ctx

    @staticmethod
    def _draft_payload(ctx):
        return create_agreement_payload(ctx["site"]["id"],
                                        ctx["debarred_developer"]["id"],
                                        ctx["proposal"]["id"],
                                        ctx["valuation"]["id"],
                                        joint_use_committed=False)

    def test_site_state_is_reported_and_debarment_is_never_mentioned(
            self, api, real_estate_officer):
        """PRD §3.6: "The site must be `UNDER_AGREEMENT`, otherwise
        `ERR_SITE_NOT_UNDER_AGREEMENT` — and this check outranks every other, so
        a drafting attempt against a site still in `SOLICITATION_READY` reports
        the site problem even when the named developer is simultaneously
        debarred." PRD §2.11 repeats it: "On agreement drafting, a site that is
        not `UNDER_AGREEMENT` reports `ERR_SITE_NOT_UNDER_AGREEMENT` even when
        the named developer is also debarred."

        Design: Difficulty/priority_pair_validation_conflict/agreement_create_site_state_beats_developer_debarment
        """
        ctx = self._released_site_with_a_debarred_developer()
        assert ctx["site"]["status"] == "SOLICITATION_READY"
        assert ctx["debarred_developer"]["debarment_status"] == "DEBARRED"

        response = api.create_agreement(self._draft_payload(ctx),
                                        real_estate_officer)

        error = validate_error(response, ApiErrorId.SITE_NOT_UNDER_AGREEMENT)
        assert error["error_id"] != ApiErrorId.DEVELOPER_DEBARRED

    def test_the_refused_draft_leaves_the_parcel_and_the_developer_untouched(
            self, api, real_estate_officer):
        """PRD §3.6: "Drafting is guarded by six checks in this order. The site
        must be `UNDER_AGREEMENT`, otherwise `ERR_SITE_NOT_UNDER_AGREEMENT`",
        so a refused draft never becomes an agreement. PRD §2.11 fixes which
        guard speaks: "When a request would fail more than one rule, the checks
        are evaluated in a strict, fixed order and the **first** failing check
        decides the response. Nothing later in the order can mask something
        earlier."

        Design: Difficulty/priority_pair_validation_conflict/agreement_create_site_state_beats_developer_debarment
        """
        ctx = self._released_site_with_a_debarred_developer()

        validate_error(api.create_agreement(self._draft_payload(ctx),
                                            real_estate_officer),
                       ApiErrorId.SITE_NOT_UNDER_AGREEMENT)

        agreements, meta = validate_paginated(api.list_agreements(
            real_estate_officer, params={"site_id": ctx["site"]["id"]}))
        assert meta["total_count"] == 0
        assert agreements == []
        site = validate_success(api.get_site(ctx["site"]["id"],
                                             real_estate_officer))
        assert site["status"] == "SOLICITATION_READY"
        developer = validate_success(api.get_developer(
            ctx["debarred_developer"]["id"], real_estate_officer))
        assert developer["debarment_status"] == "DEBARRED"


class TestValuationCertificationBeatsPermissibleFloor:
    """A submission whose backing appraisal is still a draft and whose
    consideration also falls short of that appraisal's floor."""

    @staticmethod
    def _drafting_agreement_on_a_draft_fmv_valuation():
        return build_context(
            stage="DRAFTING", negotiation_via="award",
            site_overrides=dict(JUNIPER_YARD_SITE),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False},
            valuation_overrides={"method": "SALES_COMPARISON",
                                 "transfer_basis": "FMV_STRICT"},
            certify_valuation_record=False,
            agreement_overrides={"joint_use_committed": False})

    def test_uncertified_valuation_is_reported_before_the_floor_shortfall(
            self, api, real_estate_officer):
        """PRD §3.7: "The referenced valuation determination must be
        `CERTIFIED`, otherwise `ERR_VALUATION_NOT_CERTIFIED` — and this
        referential check runs **before** either fiscal check, so an agreement
        backed by a draft appraisal reports the uncertified valuation even if its
        consideration would also fall below the floor." PRD §3.2 pins the floor
        this agreement misses: "Under `FMV_STRICT` the grantor has not concurred
        in any below-market transfer, so `permissible_floor_cents` is the full
        `appraised_value_cents`".

        Design: Difficulty/priority_pair_validation_conflict/submit_for_review_valuation_referential_beats_below_floor_fiscal
        """
        ctx = self._drafting_agreement_on_a_draft_fmv_valuation()
        assert ctx["valuation"]["status"] == "DRAFT"
        assert_money(ctx["valuation"]["permissible_floor_cents"], 48_500_000,
                     "permissible_floor_cents")
        assert_money(ctx["agreement"]["consideration_value_cents"], 46_280_000,
                     "consideration_value_cents")

        response = api.submit_agreement_for_review(ctx["agreement"]["id"],
                                                   real_estate_officer)

        error = validate_error(response, ApiErrorId.VALUATION_NOT_CERTIFIED)
        assert error["error_id"] != ApiErrorId.BELOW_PERMISSIBLE_FLOOR

    def test_the_refused_submission_leaves_both_records_where_they_were(
            self, api, real_estate_officer):
        """PRD §3.7: "On success the agreement advances
        `DRAFTING → AGENCY_REVIEW`, `submitted_by_user_id` is set to the
        submitting operator's `X-User-ID`, and `revision_notes` is cleared." A
        submission refused with `ERR_VALUATION_NOT_CERTIFIED` reaches none of
        that, and PRD §2.11 adds that "Nothing later in the order can mask
        something earlier."

        Design: Difficulty/priority_pair_validation_conflict/submit_for_review_valuation_referential_beats_below_floor_fiscal
        """
        ctx = self._drafting_agreement_on_a_draft_fmv_valuation()

        validate_error(api.submit_agreement_for_review(ctx["agreement"]["id"],
                                                       real_estate_officer),
                       ApiErrorId.VALUATION_NOT_CERTIFIED)

        agreement = validate_success(api.get_agreement(ctx["agreement"]["id"],
                                                       real_estate_officer))
        assert agreement["negotiation_status"] == "DRAFTING"
        assert agreement["submitted_by_user_id"] is None
        valuation = validate_success(api.get_valuation(ctx["valuation"]["id"],
                                                       real_estate_officer))
        assert valuation["status"] == "DRAFT"
