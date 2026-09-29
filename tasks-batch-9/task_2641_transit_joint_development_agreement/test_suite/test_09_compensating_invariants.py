"""Actions and their compensations, checked by the quantity each conserves: a
money ledger in cents and an integer count of bus bays."""

from test_helpers import (
    ApiErrorId,
    assert_federal_ledger_identity,
    assert_bay_capacity_identity,
    assert_money,
    build_board_approved_agreement,
    build_shared_facility,
    build_staging_window,
    decide_staging_window,
    read_shared_facility,
    read_site,
    validate_error,
    validate_success,
    withdraw_disposition_payload,
)

ELM_LOOP_FEDERAL_SITE = {
    "site_code": "TJD-E-001",
    "name": "Elm Loop Federal Parcel",
    "address_line": "9 Elm Loop",
    "parcel_area_sqft": 82000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}

FIR_STREET_SITE = {
    "site_code": "TJD-E-002",
    "name": "Fir Street Bay Yard",
    "address_line": "18 Fir St",
    "parcel_area_sqft": 97000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}

FILING_NARRATIVE = ("Ground lease of the Elm Loop parcel for transit-oriented "
                    "housing")


class TestFederalLedgerConservedAcrossFilingAndWithdrawal:
    """Three checkpoints on the same parcel: before the filing, after it, and
    after the withdrawal."""

    @staticmethod
    def _board_approved_on_a_certified_basis():
        ctx = build_board_approved_agreement(
            negotiation_via="award",
            site_overrides=dict(ELM_LOOP_FEDERAL_SITE),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False},
            agreement_overrides={"site_area_share_pct": 60,
                                 "joint_use_committed": False},
            resolution_number="R-2026-121")
        ctx["site"] = read_site(ctx["site"]["id"])
        return ctx

    def test_filing_moves_the_pledged_slice_between_the_two_columns(
            self, api, grants_compliance_officer):
        """PRD §3.2: "the site's `federal_interest_basis_cents` and
        `federal_interest_unencumbered_cents` are pinned from this appraisal".
        PRD §3.8: "the site's `federal_interest_encumbered_cents` is increased by
        the pledged amount, its `federal_interest_unencumbered_cents` is
        decreased by exactly the same amount", and the arithmetic is pinned: "an
        agreement disposing of sixty percent of the parcel pledges 727,500 cents
        and leaves 485,000 cents unencumbered."

        Design: Difficulty/compensating_invariant/federal_interest_ledger_conserved_across_filing_and_withdrawal
        """
        ctx = self._board_approved_on_a_certified_basis()
        assert_money(ctx["site"]["federal_interest_basis_cents"], 1_212_500,
                     "federal_interest_basis_cents")
        assert_money(ctx["site"]["federal_interest_encumbered_cents"], 0,
                     "federal_interest_encumbered_cents")
        assert_money(ctx["site"]["federal_interest_unencumbered_cents"],
                     1_212_500, "federal_interest_unencumbered_cents")
        assert_federal_ledger_identity(ctx["site"])

        request = validate_success(api.create_disposition_request(
            ctx["agreement"]["id"], {"narrative": FILING_NARRATIVE},
            grants_compliance_officer), expected_status=201)

        assert_money(request["federal_interest_amount_cents"], 727_500,
                     "federal_interest_amount_cents")
        site = read_site(ctx["site"]["id"])
        assert_money(site["federal_interest_encumbered_cents"], 727_500,
                     "federal_interest_encumbered_cents")
        assert_money(site["federal_interest_unencumbered_cents"], 485_000,
                     "federal_interest_unencumbered_cents")
        assert_federal_ledger_identity(site)

    def test_withdrawal_returns_the_same_slice_and_leaves_no_drift(
            self, api, grants_compliance_officer):
        """PRD §3.8: "The request moves `PENDING → WITHDRAWN` with
        `determined_at` stamped, the agreement moves `SUBMITTED → NOT_SUBMITTED`
        on its federal dimension so a corrected filing can be made, the site's
        `federal_interest_encumbered_cents` is decreased and its
        `federal_interest_unencumbered_cents` increased by this request's
        `federal_interest_amount_cents`". "Filing and withdrawing therefore
        conserve `federal_interest_basis_cents` exactly, leaving the pre-filing
        ledger untouched." And "withdrawal touches only the ledger and the
        federal dimension, and never disturbs the valuation, the staging windows
        or `negotiation_status`."

        Design: Difficulty/compensating_invariant/federal_interest_ledger_conserved_across_filing_and_withdrawal
        """
        ctx = self._board_approved_on_a_certified_basis()
        request = validate_success(api.create_disposition_request(
            ctx["agreement"]["id"], {"narrative": FILING_NARRATIVE},
            grants_compliance_officer), expected_status=201)

        withdrawn = validate_success(api.withdraw_disposition_request(
            request["id"],
            withdraw_disposition_payload(
                "Agency re-scoping the joint use program before FTA review"),
            grants_compliance_officer))

        assert withdrawn["determination"] == "WITHDRAWN"
        site = read_site(ctx["site"]["id"])
        assert_money(site["federal_interest_basis_cents"], 1_212_500,
                     "federal_interest_basis_cents")
        assert_money(site["federal_interest_encumbered_cents"], 0,
                     "federal_interest_encumbered_cents")
        assert_money(site["federal_interest_unencumbered_cents"], 1_212_500,
                     "federal_interest_unencumbered_cents")
        assert_federal_ledger_identity(site)
        agreement = validate_success(api.get_agreement(ctx["agreement"]["id"],
                                                       grants_compliance_officer))
        assert agreement["federal_approval_status"] == "NOT_SUBMITTED"
        assert agreement["negotiation_status"] == "BOARD_APPROVED"


class TestBayCountConservedAcrossCloseAndReclose:
    """Four bays taken, given back once, and never given back twice."""

    @staticmethod
    def _approved_window_holding_four_bays():
        ctx = build_board_approved_agreement(
            negotiation_via="award",
            site_overrides=dict(FIR_STREET_SITE),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False},
            agreement_overrides={"joint_use_committed": False},
            resolution_number="R-2026-122")
        ctx["facility"] = build_shared_facility(
            ctx["site"]["id"], facility_type="BUS_BAY", total_bay_capacity=6,
            maintenance_responsibility="SHARED", cost_share_pct_developer=0.35)
        ctx["requested_window"] = build_staging_window(
            ctx["agreement"]["id"], ctx["facility"]["id"], ctx["developer"]["id"],
            expected_facility_version=ctx["facility"]["version"],
            start_at="2026-09-01T08:00:00Z", end_at="2026-09-20T08:00:00Z",
            bays_occupied=4, purpose="Foundation staging")
        ctx["window"] = decide_staging_window(ctx["requested_window"]["id"],
                                              "APPROVE")
        ctx["facility"] = read_shared_facility(ctx["facility"]["id"])
        return ctx

    def test_closing_the_window_returns_exactly_the_bays_it_held(
            self, api, transit_operations_manager):
        """PRD §3.9: "`REQUESTED → APPROVED` decreases the shared facility's
        `available_bay_capacity` by the window's `bays_occupied`, bumps the
        facility's `version` by 1, and leaves `capacity_released` false so the
        bays are known to be still out." Then "Closing an `APPROVED` window moves
        it `APPROVED → CLOSED` and, because its `capacity_released` was still
        false, increases the facility's `available_bay_capacity` by the window's
        `bays_occupied`, sets `capacity_released` to true and bumps the
        facility's `version` by 1."

        Design: Difficulty/compensating_invariant/shared_facility_bay_count_conserved_across_staging_close_and_reclose
        """
        ctx = self._approved_window_holding_four_bays()
        assert ctx["facility"]["total_bay_capacity"] == 6
        assert ctx["requested_window"]["capacity_released"] is False
        assert ctx["window"]["status"] == "APPROVED"
        assert ctx["facility"]["available_bay_capacity"] == 2
        assert_bay_capacity_identity(ctx["facility"], [ctx["window"]])

        closed = validate_success(api.close_staging_window(
            ctx["window"]["id"], transit_operations_manager))

        assert closed["status"] == "CLOSED"
        assert closed["capacity_released"] is True
        facility = read_shared_facility(ctx["facility"]["id"])
        assert facility["available_bay_capacity"] == 6
        assert_bay_capacity_identity(facility, [])

    def test_a_second_close_is_refused_so_the_bays_are_never_credited_twice(
            self, api, transit_operations_manager):
        """PRD §3.9: "It requires the window to be `APPROVED` or `SUSPENDED`, and
        a `REQUESTED`, `REJECTED` or already-`CLOSED` window reports
        `ERR_STAGING_WINDOW_NOT_CLOSABLE`." The guard is what conserves the
        count: "That guard is what makes approval and closure conserve
        `total_bay_capacity` exactly, however the window got to its terminal
        state."

        Design: Difficulty/compensating_invariant/shared_facility_bay_count_conserved_across_staging_close_and_reclose
        """
        ctx = self._approved_window_holding_four_bays()
        validate_success(api.close_staging_window(ctx["window"]["id"],
                                                  transit_operations_manager))

        response = api.close_staging_window(ctx["window"]["id"],
                                            transit_operations_manager)

        validate_error(response, ApiErrorId.STAGING_WINDOW_NOT_CLOSABLE)
        facility = read_shared_facility(ctx["facility"]["id"])
        assert facility["available_bay_capacity"] == 6
        assert_bay_capacity_identity(facility, [])
        window = validate_success(api.get_staging_window(
            ctx["window"]["id"], transit_operations_manager))
        assert window["status"] == "CLOSED"
