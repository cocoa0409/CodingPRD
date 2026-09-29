"""Non-linear lifecycles: the agreement's two independent state dimensions
through a revision cycle, and the site's return trip through inventory."""

from test_helpers import (
    assert_money,
    assert_score,
    build_agency_review_agreement,
    build_disposition_request,
    build_site,
    certify_assessment,
    create_assessment_payload,
    determination_payload,
    read_agreement,
    read_site,
    reopen_inventory_payload,
    request_revision_payload,
    set_logical_clock,
    validate_success,
)

ELM_LOOP_SITE = {
    "site_code": "TJD-A-005",
    "name": "Elm Loop Joint Development Site",
    "address_line": "5 Elm Loop",
    "parcel_area_sqft": 78000,
}


class TestAgreementParallelDimensions:
    """A full negotiation cycle beside an independent federal advance."""

    @staticmethod
    def _through_revision_to_board_approval(api, real_estate_officer,
                                            board_secretary):
        ctx = build_agency_review_agreement(
            negotiation_via="award", site_overrides=dict(ELM_LOOP_SITE),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            agreement_overrides={"revenue_share_pct": 0.05,
                                 "joint_use_committed": False},
            submitter_user_id="reo-001")
        validate_success(api.request_agreement_revision(
            ctx["agreement"]["id"],
            request_revision_payload(
                "Board asks for a higher participation rent share."),
            board_secretary))
        ctx["amended"] = validate_success(api.update_agreement(
            ctx["agreement"]["id"], {"revenue_share_pct": 0.06},
            real_estate_officer))
        validate_success(api.submit_agreement_for_review(
            ctx["agreement"]["id"], real_estate_officer))
        ctx["agreement"] = validate_success(api.board_approve_agreement(
            ctx["agreement"]["id"], {"resolution_number": "R-2026-118"},
            board_secretary))
        return ctx

    def test_amendment_after_revision_returns_to_drafting_and_recomputes_money(
            self, api, real_estate_officer, board_secretary):
        """PRD §3.6: "an amendment applied to a `REVISION_REQUESTED` agreement
        advances it `REVISION_REQUESTED → DRAFTING`, closing the negotiation
        cycle `AGENCY_REVIEW → REVISION_REQUESTED → DRAFTING → AGENCY_REVIEW`."
        The amendable fields include `revenue_share_pct`, and "whichever are
        supplied are applied, and `capital_credit_cents`,
        `annual_revenue_to_agency_cents` and `consideration_value_cents` are
        then all recomputed from the resulting stored inputs."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_with_revision_cycle
        """
        ctx = build_agency_review_agreement(
            negotiation_via="award", site_overrides=dict(ELM_LOOP_SITE),
            agreement_overrides={"revenue_share_pct": 0.05,
                                 "joint_use_committed": False})
        validate_success(api.request_agreement_revision(
            ctx["agreement"]["id"],
            request_revision_payload(
                "Board asks for a higher participation rent share."),
            board_secretary))

        amended = validate_success(api.update_agreement(
            ctx["agreement"]["id"], {"revenue_share_pct": 0.06},
            real_estate_officer))

        assert amended["negotiation_status"] == "DRAFTING", (
            "an amendment to a revision-requested agreement returns it to "
            f"DRAFTING, got {amended['negotiation_status']}")
        assert_money(amended["annual_revenue_to_agency_cents"], 2_420_800,
                    "annual_revenue_to_agency_cents")
        assert_money(amended["capital_credit_cents"], 299_200,
                    "capital_credit_cents")

    def test_resubmission_reaches_board_approval_with_the_resolution_recorded(
            self, api, real_estate_officer, board_secretary):
        """PRD §3.7: "a `BoardSecretary` may record approval, supplying the
        `resolution_number` that is stored as `board_resolution_number`; that
        advances the agreement `AGENCY_REVIEW → BOARD_APPROVED`".

        Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_with_revision_cycle
        """
        ctx = self._through_revision_to_board_approval(api, real_estate_officer,
                                                       board_secretary)

        assert ctx["agreement"]["negotiation_status"] == "BOARD_APPROVED"
        assert ctx["agreement"]["board_resolution_number"] == "R-2026-118", (
            "the supplied resolution number is stored verbatim, got "
            f"{ctx['agreement']['board_resolution_number']}")

    def test_grantor_concurrence_advances_only_the_federal_dimension(
            self, api, real_estate_officer, board_secretary,
            grants_compliance_officer):
        """PRD §3.8: "Both `APPROVED` and `APPROVED_WITH_CONDITIONS` move the
        request `PENDING → APPROVED` or `PENDING → APPROVED_WITH_CONDITIONS`
        respectively and move the agreement `SUBMITTED → FTA_APPROVED` on its
        federal dimension." And: "`negotiation_status` is not touched at all:
        the two dimensions of the agreement advance independently, and a board
        that has not yet voted is unaffected by the grantor's concurrence."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_with_revision_cycle
        """
        ctx = self._through_revision_to_board_approval(api, real_estate_officer,
                                                       board_secretary)
        request = build_disposition_request(
            ctx["agreement"]["id"],
            "Air-rights ground lease over a federally assisted park-and-ride.")

        determined = validate_success(api.record_disposition_determination(
            request["id"],
            determination_payload("APPROVED_WITH_CONDITIONS",
                                  "Maintain 20 percent affordable units for "
                                  "55 years."),
            grants_compliance_officer))

        assert determined["determination"] == "APPROVED_WITH_CONDITIONS"
        stored = read_agreement(ctx["agreement"]["id"])
        assert stored["federal_approval_status"] == "FTA_APPROVED"
        assert stored["negotiation_status"] == "BOARD_APPROVED", (
            "the grantor's answer must leave the negotiation dimension where "
            f"the board left it, got {stored['negotiation_status']}")

    def test_amended_money_persists_through_approval_and_concurrence(
            self, api, real_estate_officer, board_secretary,
            grants_compliance_officer):
        """PRD §3.6: "`consideration_value_cents` follows immediately from the
        same inputs and is the figure the fiscal gate of §3.7 tests. For a
        `GROUND_LEASE` it is the `annual_revenue_to_agency_cents` just computed,
        capitalised over twenty years by simple integer multiplication". PRD
        §3.8 adds that on a favourable answer "The site's encumbrance stays
        exactly where it is".

        Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_with_revision_cycle
        """
        ctx = self._through_revision_to_board_approval(api, real_estate_officer,
                                                       board_secretary)
        request = build_disposition_request(
            ctx["agreement"]["id"],
            "Air-rights ground lease over a federally assisted park-and-ride.")
        validate_success(api.record_disposition_determination(
            request["id"],
            determination_payload("APPROVED_WITH_CONDITIONS",
                                  "Maintain 20 percent affordable units for "
                                  "55 years."),
            grants_compliance_officer))

        stored = read_agreement(ctx["agreement"]["id"])
        assert_money(stored["annual_revenue_to_agency_cents"], 2_420_800,
                    "annual_revenue_to_agency_cents")
        assert_money(stored["consideration_value_cents"], 48_416_000,
                    "consideration_value_cents")
        assert_money(stored["capital_credit_cents"], 299_200,
                    "capital_credit_cents")
        assert read_site(ctx["site"]["id"])["status"] == "UNDER_AGREEMENT"


class TestSiteInventoryCycle:
    """A parcel goes ASSESSED, back to INVENTORIED, and out to ASSESSED again."""

    @staticmethod
    def _assessed_site(api, real_estate_officer):
        set_logical_clock("2026-08-01T00:00:00Z")
        site = build_site(site_code="TJD-A-006",
                          name="Fir Street Layover Lot",
                          address_line="77 Fir St",
                          parcel_area_sqft=52000,
                          acquisition_funding_source="FEDERAL_GRANT",
                          federal_interest_pct=2.5,
                          transit_facility_present=False)
        first = validate_success(api.create_assessment(
            site["id"],
            create_assessment_payload(environmental_score=80, utility_score=75,
                                      access_score=70, entitlement_score=60,
                                      encumbrance_count=1),
            real_estate_officer), 201)
        certify_assessment(first["id"])
        return site, first

    def test_reopening_inventory_clears_the_copied_readiness_fields(
            self, api, real_estate_officer):
        """PRD §3.1: "Reopening inventory takes a site whose status is
        `ASSESSED` or `SOLICITATION_READY` back to `INVENTORIED`, and the request
        must carry a `reason`." And: "On success the site's
        `readiness_composite_score` and `readiness_tier` are cleared back to
        null, every `CERTIFIED` assessment on the site moves `CERTIFIED →
        SUPERSEDED`, every `DRAFT` solicitation on the site moves `DRAFT →
        CANCELLED`, and the site's `version` is bumped by 1."

        Design: Difficulty/non_linear_state_machine/site_status_cycles_assessed_inventoried_assessed
        """
        site, _first = self._assessed_site(api, real_estate_officer)

        reopened = validate_success(api.reopen_site_inventory(
            site["id"],
            reopen_inventory_payload(
                "Encumbrance cleared; retake the readiness screen."),
            real_estate_officer))

        assert reopened["status"] == "INVENTORIED"
        assert reopened["readiness_composite_score"] is None, (
            "the copied score is cleared, got "
            f"{reopened['readiness_composite_score']}")
        assert reopened["readiness_tier"] is None

    def test_reopening_supersedes_the_certified_assessment_without_rescoring_it(
            self, api, real_estate_officer):
        """PRD §3.1: "every `CERTIFIED` assessment on the site moves `CERTIFIED
        → SUPERSEDED`". The superseded row keeps the number it was certified
        with, because the certified variant "is recomputed" only when a
        `RealEstateOfficer` certifies a draft assessment.

        Design: Difficulty/non_linear_state_machine/site_status_cycles_assessed_inventoried_assessed
        """
        site, first = self._assessed_site(api, real_estate_officer)

        validate_success(api.reopen_site_inventory(
            site["id"],
            reopen_inventory_payload(
                "Encumbrance cleared; retake the readiness screen."),
            real_estate_officer))

        stored = validate_success(api.get_assessment(first["id"],
                                                     real_estate_officer))
        assert stored["status"] == "SUPERSEDED"
        assert_score(stored["composite_score"], 70.00,
                    "superseded composite_score")

    def test_a_fresh_certification_closes_the_cycle_back_to_assessed(
            self, api, real_estate_officer):
        """PRD §3.1: "Because the copied readiness fields are gone, leaving
        `INVENTORIED` a second time requires a fresh assessment to be recorded
        and certified — the cycle `INVENTORIED → ASSESSED → INVENTORIED` closes
        cleanly and no shortcut exists." The certified variant charges "three
        points for each recorded encumbrance", so an unencumbered retake scores
        higher.

        Design: Difficulty/non_linear_state_machine/site_status_cycles_assessed_inventoried_assessed
        """
        site, _first = self._assessed_site(api, real_estate_officer)
        validate_success(api.reopen_site_inventory(
            site["id"],
            reopen_inventory_payload(
                "Encumbrance cleared; retake the readiness screen."),
            real_estate_officer))

        second = validate_success(api.create_assessment(
            site["id"],
            create_assessment_payload(environmental_score=80, utility_score=75,
                                      access_score=70, entitlement_score=60,
                                      encumbrance_count=0),
            real_estate_officer), 201)
        certified = validate_success(
            api.certify_assessment(second["id"], real_estate_officer))

        assert_score(certified["composite_score"], 73.00, "composite_score")
        assert certified["tier"] == "READY"
        assert certified["variant_applied"] == "CERTIFIED"

    def test_the_site_re_adopts_the_second_certified_score_and_tier(
            self, api, real_estate_officer):
        """PRD §3.1: "The site's `readiness_composite_score` and
        `readiness_tier` are refreshed to the certifying assessment's
        `composite_score` and `tier` — those two site fields are always a copy of
        the most recently certified assessment, and are null whenever no
        certified assessment exists." And: "A site sitting in `INVENTORIED` moves
        `INVENTORIED → ASSESSED`".

        Design: Difficulty/non_linear_state_machine/site_status_cycles_assessed_inventoried_assessed
        """
        site, _first = self._assessed_site(api, real_estate_officer)
        validate_success(api.reopen_site_inventory(
            site["id"],
            reopen_inventory_payload(
                "Encumbrance cleared; retake the readiness screen."),
            real_estate_officer))
        second = validate_success(api.create_assessment(
            site["id"],
            create_assessment_payload(environmental_score=80, utility_score=75,
                                      access_score=70, entitlement_score=60,
                                      encumbrance_count=0),
            real_estate_officer), 201)
        certify_assessment(second["id"])

        stored = read_site(site["id"])
        assert stored["status"] == "ASSESSED"
        assert_score(stored["readiness_composite_score"], 73.00,
                    "site.readiness_composite_score")
        assert stored["readiness_tier"] == "READY"
