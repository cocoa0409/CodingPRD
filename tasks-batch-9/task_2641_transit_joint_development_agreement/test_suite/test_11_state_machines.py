"""Lifecycle checks: the legal hops, the refused hops, the initial state a record
opens in, and the side effects a hop drags behind it."""

from test_helpers import (
    ApiErrorId,
    assert_money,
    assert_score,
    board_approve_payload,
    build_assessment,
    build_context,
    build_site,
    build_solicitation,
    certify_assessment,
    create_solicitation_payload,
    execute_agreement_payload,
    extend_negotiation_period_payload,
    read_site,
    set_logical_clock,
    terminate_negotiation_period_payload,
    validate_error,
    validate_success,
)

FEDERAL_SITE = {
    "site_code": "TJD-C-012",
    "name": "Cedar Point Parcel",
    "address_line": "12 Cedar Point",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}

LOCAL_ONLY_SITE = {
    "site_code": "TJD-C-013",
    "name": "Cedar Mill Parcel",
    "address_line": "13 Cedar Mill",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "LOCAL_ONLY",
    "federal_interest_pct": 0,
    "transit_facility_present": False,
}


class TestAssessmentCertification:
    """The one hop that replaces the number the officer has been looking at."""

    def test_certifying_swaps_the_preliminary_mean_for_the_weighted_score(
            self, api, real_estate_officer):
        """PRD §3.1: "The certified variant weights the four sub-scores rather
        than averaging them: the environmental score counts for thirty-five
        hundredths of a point per point scored, the utility score and the access
        score each for twenty-five hundredths, and the entitlement score for
        fifteen hundredths", less an encumbrance penalty of "three points for each
        recorded encumbrance" and a federal interest penalty of "one tenth of a
        point for each whole percent of `federal_interest_pct` on the parcel". The
        PRD works this very case: "sub-scores of 80, 75, 70 and 60 with one
        encumbrance on a parcel whose federal interest is two and a half percent
        yield a preliminary score of 71.25 and a certified score of 70.00 from
        identical stored inputs." At 70.00, "A score of at least 70.00 is
        `READY`", and "The site's `readiness_composite_score` and
        `readiness_tier` are refreshed to the certifying assessment's
        `composite_score` and `tier`" while "a site already in `ASSESSED` stays
        there".

        Design: Corner/state_machines/corner_assessment_draft_to_certified_valid_transition
        """
        set_logical_clock()
        site = build_site(**FEDERAL_SITE)
        certify_assessment(build_assessment(site["id"])["id"])
        assert read_site(site["id"])["status"] == "ASSESSED"
        draft = build_assessment(site["id"])
        assert_score(draft["composite_score"], 71.25, "composite_score")
        assert draft["variant_applied"] == "PRELIMINARY"

        certified = validate_success(api.certify_assessment(draft["id"],
                                                           real_estate_officer))

        assert certified["status"] == "CERTIFIED"
        assert_score(certified["composite_score"], 70.00, "composite_score")
        assert certified["variant_applied"] == "CERTIFIED"
        assert certified["tier"] == "READY"
        assert certified["certified_at"].startswith("2026-08-01T00:00:00")
        site_after = read_site(site["id"])
        assert_score(site_after["readiness_composite_score"], 70.00,
                     "readiness_composite_score")
        assert site_after["readiness_tier"] == "READY"
        assert site_after["status"] == "ASSESSED"

    def test_certifying_the_same_assessment_again_is_refused_and_keeps_the_stamp(
            self, api, real_estate_officer):
        """PRD §3.1: "Certification is refused unless the assessment is in
        `DRAFT` — an already certified or superseded assessment reports
        `ERR_ASSESSMENT_NOT_DRAFT`". The first certification already stamped the
        instant — "`certified_at` is stamped with the current logical clock
        instant" — so a refused second attempt after PRD §2.5's clock has moved
        cannot re-stamp it.

        Design: Corner/state_machines/corner_certify_assessment_twice_rejected
        """
        set_logical_clock()
        site = build_site(**FEDERAL_SITE)
        certified = certify_assessment(build_assessment(site["id"])["id"])
        assert certified["certified_at"].startswith("2026-08-01T00:00:00")
        set_logical_clock("2026-08-05T00:00:00Z")

        response = api.certify_assessment(certified["id"], real_estate_officer)

        validate_error(response, ApiErrorId.ASSESSMENT_NOT_DRAFT)
        after = validate_success(api.get_assessment(certified["id"],
                                                    real_estate_officer))
        assert after["status"] == "CERTIFIED"
        assert after["certified_at"] == certified["certified_at"]


class TestSolicitationLifecycle:
    """Where a solicitation opens, and the hop that is not on its map."""

    def test_a_drafted_solicitation_is_not_yet_on_the_market(
            self, api, real_estate_officer):
        """PRD §3.3: "A drafted solicitation lands in `DRAFT` with `issued_at`
        null and `responsive_proposal_count` at 0", and "`min_proposals_required`,
        at least 1 and defaulting to 1, is the count of live proposals needed
        before the solicitation may close". Only issuance changes that — PRD §3.3:
        "On success the solicitation moves `DRAFT → ISSUED` and `issued_at` is
        stamped from the logical clock."

        Design: Corner/state_machines/corner_new_solicitation_starts_in_draft_initial_state
        """
        ctx = build_context(stage="RELEASED", site_overrides=dict(FEDERAL_SITE))

        response = api.create_solicitation(ctx["site"]["id"],
                                           create_solicitation_payload(
                                               solicitation_type="RFQ",
                                               min_proposals_required=1,
                                               joint_use_required=False),
                                           real_estate_officer)

        solicitation = validate_success(response, expected_status=201)
        assert solicitation["status"] == "DRAFT"
        assert solicitation["issued_at"] is None
        assert solicitation["responsive_proposal_count"] == 0
        assert solicitation["min_proposals_required"] == 1

    def test_closing_a_solicitation_that_was_never_issued_is_refused(
            self, api, real_estate_officer):
        """PRD §3.4: "Closing a solicitation stops the clock on responses and
        produces the ranking the award will be judged against. It requires the
        solicitation to be `ISSUED`, any other status reporting
        `ERR_SOLICITATION_NOT_ISSUED`." A refused close cannot stamp the record
        either, since PRD §3.3 gives `issued_at` only to issuance: "On success the
        solicitation moves `DRAFT → ISSUED` and `issued_at` is stamped from the
        logical clock."

        Design: Corner/state_machines/corner_close_solicitation_from_draft_rejected
        """
        ctx = build_context(stage="RELEASED", site_overrides=dict(FEDERAL_SITE))
        solicitation = build_solicitation(ctx["site"]["id"])
        assert solicitation["status"] == "DRAFT"

        response = api.close_solicitation(solicitation["id"],
                                          real_estate_officer)

        validate_error(response, ApiErrorId.SOLICITATION_NOT_ISSUED)
        after = validate_success(api.get_solicitation(solicitation["id"],
                                                      real_estate_officer))
        assert after["status"] == "DRAFT"
        assert after["issued_at"] is None


class TestAgreementBoardApproval:
    """Board approval is only reachable from the review state."""

    def test_the_board_cannot_approve_an_agreement_still_being_drafted(
            self, api, board_secretary):
        """PRD §3.7: "Or a `BoardSecretary` may record approval, supplying the
        `resolution_number` that is stored as `board_resolution_number`; that
        advances the agreement `AGENCY_REVIEW → BOARD_APPROVED` and is likewise
        refused with `ERR_AGREEMENT_NOT_IN_REVIEW` outside `AGENCY_REVIEW`." PRD
        §3.6 fixes where a fresh agreement sits and what is still null: "A newly
        drafted agreement opens with `negotiation_status` `DRAFTING`" and "Nothing
        is recorded yet in `submitted_by_user_id`, `board_resolution_number`,
        `execution_date` or `revision_notes`, all of which begin null."

        Design: Corner/state_machines/corner_board_approve_on_drafting_agreement_precondition_enforced
        """
        ctx = build_context(stage="DRAFTING", negotiation_via="award",
                            site_overrides=dict(FEDERAL_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"})
        assert ctx["agreement"]["negotiation_status"] == "DRAFTING"

        response = api.board_approve_agreement(
            ctx["agreement"]["id"], board_approve_payload("R-2026-130"),
            board_secretary)

        validate_error(response, ApiErrorId.AGREEMENT_NOT_IN_REVIEW)
        after = validate_success(api.get_agreement(ctx["agreement"]["id"],
                                                   board_secretary))
        assert after["negotiation_status"] == "DRAFTING"
        assert after["board_resolution_number"] is None


class TestNegotiationPeriodTerminalStates:
    """A terminated dealing window is closed for good."""

    def test_a_terminated_period_refuses_an_extension_and_keeps_its_dates(
            self, api, real_estate_officer):
        """PRD §3.5: "The period `status` values are `ACTIVE`, `EXTENDED`,
        `EXPIRED`, `TERMINATED` and `CONVERTED`, the last three terminal", and an
        extension "is refused four ways: a period whose status is not `ACTIVE` or
        `EXTENDED` reports `ERR_NEGOTIATION_PERIOD_NOT_ACTIVE`". Only success
        touches the dates — "On success `end_date` is replaced by `new_end_date`
        and `extension_count` is increased by 1." Termination itself already ran
        its own two hops: "the held proposal drops `SELECTED → REJECTED` (hop 1),
        and **conditionally** — only when no `ACTIVE` or `EXTENDED` period remains
        on the site and no agreement on the site is `EXECUTED` — the site moves
        `UNDER_AGREEMENT → SOLICITATION_READY`".

        Design: Corner/state_machines/corner_terminated_negotiation_period_cannot_be_extended
        """
        # The period is opened through the §3.4 award path because only that path
        # derives `SUBMITTED → SELECTED` on the held proposal; §3.5's direct grant
        # "never selects the proposal", so termination's hop 1 —
        # "the held proposal drops `SELECTED → REJECTED`" — would have no premise.
        ctx = build_context(stage="NEGOTIATION", negotiation_via="award",
                            period_start_date="2026-08-15",
                            period_end_date="2026-10-15",
                            site_overrides=dict(FEDERAL_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"})
        assert ctx["period"]["status"] == "ACTIVE"
        terminated = validate_success(api.terminate_negotiation_period(
            ctx["period"]["id"],
            terminate_negotiation_period_payload(
                "Developer withdrew from the sole-source discussion."),
            real_estate_officer))
        assert terminated["status"] == "TERMINATED"

        response = api.extend_negotiation_period(
            ctx["period"]["id"], extend_negotiation_period_payload("2026-12-15"),
            real_estate_officer)

        validate_error(response, ApiErrorId.NEGOTIATION_PERIOD_NOT_ACTIVE)
        period = validate_success(api.get_negotiation_period(
            ctx["period"]["id"], real_estate_officer))
        assert period["end_date"] == "2026-10-15"
        assert period["extension_count"] == 0
        proposal = validate_success(api.get_proposal(ctx["proposal"]["id"],
                                                     real_estate_officer))
        assert proposal["status"] == "REJECTED"
        assert read_site(ctx["site"]["id"])["status"] == "SOLICITATION_READY"


class TestAgreementExecution:
    """Signing a fee disposition fires three side effects in one call."""

    def test_executing_a_fee_disposition_conveys_the_parcel_and_converts_the_period(
            self, api, real_estate_officer):
        """PRD §3.7: "On success the agreement moves `BOARD_APPROVED → EXECUTED`
        and the exclusive negotiation period holding its proposal moves `ACTIVE →
        CONVERTED` or `EXTENDED → CONVERTED`. What happens to the parcel depends
        entirely on the `structure`. Under `FEE_DISPOSITION` the land actually
        changes hands, so the site moves `UNDER_AGREEMENT → CONVEYED`, its
        terminal state". The federal gate is inert here because PRD §3.6 says
        "`federal_approval_status` starts at `NOT_REQUIRED` when the site's
        `federal_interest_pct` is exactly 0". The money is the pinned order of PRD
        §3.6: the base component for a fee disposition is "the
        `purchase_price_cents` divided by `term_years`, rounded half up to a whole
        cent", 42,000,000 over 20 years giving 2,100,000; the participation
        component is "the `projected_gross_revenue_cents` multiplied by
        `revenue_share_pct`", giving 600,000; the pre-credit subtotal of 2,700,000
        earns "at least 2,500,000 but below 5,000,000 earns eight hundredths" plus
        the three hundredths for a committed affordable share "at least twenty
        hundredths", so the credit is 297,000 and
        `annual_revenue_to_agency_cents` is 2,403,000. PRD §3.6 adds that "for a
        `FEE_DISPOSITION` it is the `purchase_price_cents` outright", so the
        consideration is 42,000,000 — exactly the strict floor, since PRD §3.2
        says "Under `FMV_STRICT` the grantor has not concurred in any below-market
        transfer, so `permissible_floor_cents` is the full
        `appraised_value_cents`".

        Design: Corner/state_machines/corner_execute_fee_disposition_conveys_site_and_converts_period
        """
        ctx = build_context(
            stage="BOARD_APPROVED", negotiation_via="award",
            site_overrides=dict(LOCAL_ONLY_SITE),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            proposal_overrides={"proposed_structure": "FEE_DISPOSITION",
                                "proposed_purchase_price_cents": 42_000_000,
                                "proposed_annual_rent_cents": None},
            valuation_overrides={"appraised_value_cents": 42_000_000,
                                 "transfer_basis": "FMV_STRICT"},
            agreement_overrides={"structure": "FEE_DISPOSITION",
                                 "purchase_price_cents": 42_000_000,
                                 "base_rent_cents": None},
            resolution_number="R-2026-140")
        site_before = read_site(ctx["site"]["id"])
        assert_score(site_before["readiness_composite_score"], 70.25,
                     "readiness_composite_score")
        assert site_before["readiness_tier"] == "READY"
        assert_money(ctx["valuation"]["permissible_floor_cents"], 42_000_000,
                     "permissible_floor_cents")
        assert ctx["agreement"]["federal_approval_status"] == "NOT_REQUIRED"
        assert_money(ctx["agreement"]["capital_credit_cents"], 297_000,
                     "capital_credit_cents")
        assert_money(ctx["agreement"]["annual_revenue_to_agency_cents"],
                     2_403_000, "annual_revenue_to_agency_cents")
        assert_money(ctx["agreement"]["consideration_value_cents"], 42_000_000,
                     "consideration_value_cents")
        assert ctx["period"]["status"] == "ACTIVE"

        executed = validate_success(api.execute_agreement(
            ctx["agreement"]["id"], execute_agreement_payload("2026-08-25"),
            real_estate_officer))

        assert executed["negotiation_status"] == "EXECUTED"
        assert executed["execution_date"] == "2026-08-25"
        assert read_site(ctx["site"]["id"])["status"] == "CONVEYED"
        period = validate_success(api.get_negotiation_period(
            ctx["period"]["id"], real_estate_officer))
        assert period["status"] == "CONVERTED"
        proposal = validate_success(api.get_proposal(ctx["proposal"]["id"],
                                                     real_estate_officer))
        assert proposal["status"] == "SELECTED"
