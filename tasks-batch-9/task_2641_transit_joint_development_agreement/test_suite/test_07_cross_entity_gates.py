"""Transitions one entity cannot make until a different entity moves first."""

from test_helpers import (
    ApiErrorId,
    assert_money,
    build_board_approved_agreement,
    build_context,
    build_facility_replacement,
    build_shared_facility,
    build_staging_window,
    read_shared_facility,
    replacement_status_payload,
    staging_decision_payload,
    validate_error,
    validate_success,
)

MAPLE_JUNCTION_SITE = {
    "site_code": "TJD-C-001",
    "name": "Maple Junction Development Parcel",
    "address_line": "14 Maple Junction",
    "parcel_area_sqft": 83000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}

NUTMEG_STREET_SITE = {
    "site_code": "TJD-C-002",
    "name": "Nutmeg Street Bus Bays",
    "address_line": "8 Nutmeg St",
    "parcel_area_sqft": 71000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": True,
}


class TestSubmissionGatedOnValuationState:
    """The same submission call, refused and then accepted, with only the
    valuation's own status changing in between."""

    @staticmethod
    def _drafting_agreement_on_a_draft_valuation():
        return build_context(
            stage="DRAFTING", negotiation_via="award",
            site_overrides=dict(MAPLE_JUNCTION_SITE),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False},
            certify_valuation_record=False,
            agreement_overrides={"joint_use_committed": False})

    def test_submission_is_refused_while_the_backing_valuation_is_a_draft(
            self, api, real_estate_officer):
        """PRD §3.7: "The referenced valuation determination must be
        `CERTIFIED`, otherwise `ERR_VALUATION_NOT_CERTIFIED`". The consideration
        clears this appraisal's floor — PRD §3.2: "Under
        `TRANSIT_SUPPORTIVE_BELOW_MARKET` the floor is the appraised value less
        the transit-supportive credit, but never below the federal interest
        floor" — so only the valuation's own state can refuse the submission.

        Design: Difficulty/cross_entity_state_dependency/agreement_submit_gated_on_valuation_certified_state
        """
        ctx = self._drafting_agreement_on_a_draft_valuation()
        assert ctx["valuation"]["status"] == "DRAFT"
        assert_money(ctx["valuation"]["permissible_floor_cents"], 36_375_000,
                     "permissible_floor_cents")
        assert_money(ctx["agreement"]["consideration_value_cents"], 46_280_000,
                     "consideration_value_cents")

        response = api.submit_agreement_for_review(ctx["agreement"]["id"],
                                                   real_estate_officer)

        validate_error(response, ApiErrorId.VALUATION_NOT_CERTIFIED)

    def test_certifying_that_valuation_admits_the_identical_submission(
            self, api, real_estate_officer, valuation_officer):
        """PRD §3.2: "On success the determination moves `DRAFT → CERTIFIED`
        with `certified_at` stamped from the logical clock", and "Only a
        `CERTIFIED` determination may back an agreement that goes to review".
        PRD §3.7: "On success the agreement advances
        `DRAFTING → AGENCY_REVIEW`, `submitted_by_user_id` is set to the
        submitting operator's `X-User-ID`, and `revision_notes` is cleared."

        Design: Difficulty/cross_entity_state_dependency/agreement_submit_gated_on_valuation_certified_state
        """
        ctx = self._drafting_agreement_on_a_draft_valuation()
        validate_error(api.submit_agreement_for_review(ctx["agreement"]["id"],
                                                      real_estate_officer),
                       ApiErrorId.VALUATION_NOT_CERTIFIED)

        certified = validate_success(api.certify_valuation(
            ctx["valuation"]["id"], valuation_officer))
        assert certified["status"] == "CERTIFIED"

        submitted = validate_success(api.submit_agreement_for_review(
            ctx["agreement"]["id"], real_estate_officer))
        assert submitted["negotiation_status"] == "AGENCY_REVIEW"
        assert submitted["submitted_by_user_id"] == "reo-001"


class TestStagingApprovalGatedOnReplacement:
    """Bus bays cannot be handed to construction while the facility they
    displace has no interim arrangement in service."""

    @staticmethod
    def _requested_window_with_a_planned_replacement():
        ctx = build_board_approved_agreement(
            negotiation_via="award",
            site_overrides=dict(NUTMEG_STREET_SITE),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False},
            agreement_overrides={"joint_use_committed": False},
            resolution_number="R-2026-119")
        ctx["replacement"] = build_facility_replacement(
            ctx["agreement"]["id"], facility_type="BUS_BAY",
            original_capacity=12, replacement_capacity=12, interim_capacity=8,
            milestone_date="2027-03-01")
        ctx["facility"] = build_shared_facility(ctx["site"]["id"],
                                                facility_type="BUS_BAY",
                                                total_bay_capacity=6,
                                                maintenance_responsibility="SHARED",
                                                cost_share_pct_developer=0.35)
        ctx["window"] = build_staging_window(
            ctx["agreement"]["id"], ctx["facility"]["id"], ctx["developer"]["id"],
            start_at="2026-09-01T08:00:00Z", end_at="2026-09-08T08:00:00Z",
            bays_occupied=4, purpose="Bus bay demolition laydown")
        return ctx

    def test_approval_is_refused_while_the_replacement_is_still_planned(
            self, api, transit_operations_manager):
        """PRD §3.9: "The approve branch carries three further gates: the parent
        agreement's `negotiation_status` must be `BOARD_APPROVED`, otherwise
        `ERR_AGREEMENT_NOT_BOARD_APPROVED`; if the site's
        `transit_facility_present` is true, a transit facility replacement of the
        same agreement must have reached `INTERIM_IN_PLACE` or `COMPLETE`,
        otherwise `ERR_FACILITY_REPLACEMENT_INCOMPLETE`". A fresh commitment
        cannot satisfy that: "A new commitment opens in `PLANNED`", and its
        `capacity_deficit` is "the amount by which `original_capacity` exceeds
        `replacement_capacity`, or 0 when the replacement is at least as large".

        Design: Difficulty/cross_entity_state_dependency/staging_approval_gated_on_facility_replacement_in_place
        """
        ctx = self._requested_window_with_a_planned_replacement()
        assert ctx["replacement"]["status"] == "PLANNED"
        assert ctx["replacement"]["capacity_deficit"] == 0
        assert ctx["window"]["status"] == "REQUESTED"

        response = api.decide_staging_window(ctx["window"]["id"],
                                            staging_decision_payload("APPROVE"),
                                            transit_operations_manager)

        validate_error(response, ApiErrorId.FACILITY_REPLACEMENT_INCOMPLETE)

    def test_the_interim_report_admits_the_identical_approval_and_takes_the_bays(
            self, api, transit_operations_manager):
        """PRD §3.9: "Only three transitions are legal: `PLANNED →
        INTERIM_IN_PLACE`, `INTERIM_IN_PLACE →` either completion outcome, and
        `DEFICIENT → COMPLETE`." Once the interim stage is reported the approve
        branch's replacement gate is satisfied, and "The facility's
        `available_bay_capacity` is a denormalised ledger of the same
        arithmetic, refreshed on every status write: it is the
        `total_bay_capacity` less the sum of `bays_occupied` across that
        facility's `APPROVED` windows".

        Design: Difficulty/cross_entity_state_dependency/staging_approval_gated_on_facility_replacement_in_place
        """
        ctx = self._requested_window_with_a_planned_replacement()
        validate_error(
            api.decide_staging_window(ctx["window"]["id"],
                                      staging_decision_payload("APPROVE"),
                                      transit_operations_manager),
            ApiErrorId.FACILITY_REPLACEMENT_INCOMPLETE)

        reported = validate_success(api.report_facility_replacement_status(
            ctx["replacement"]["id"],
            replacement_status_payload("INTERIM_IN_PLACE", interim_capacity=8),
            transit_operations_manager))
        assert reported["status"] == "INTERIM_IN_PLACE"

        approved = validate_success(api.decide_staging_window(
            ctx["window"]["id"], staging_decision_payload("APPROVE"),
            transit_operations_manager))
        assert approved["status"] == "APPROVED"
        facility = read_shared_facility(ctx["facility"]["id"])
        assert facility["available_bay_capacity"] == 2
