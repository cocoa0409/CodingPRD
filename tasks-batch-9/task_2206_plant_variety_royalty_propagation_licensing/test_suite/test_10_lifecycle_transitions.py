"""Declared origins, declared initial states, and the preconditions on them."""

from test_helpers import (
    AUDITOR,
    BREEDER,
    COORDINATOR,
    OFFICER,
    OFFICER_THREE,
    OFFICER_TWO,
    ApiErrorId,
    add_line_item,
    advance_clock,
    assert_decimal_equals,
    assert_instant_equals,
    create_filing,
    create_production_quota_payload,
    create_propagator,
    create_propagator_agreement_payload,
    create_royalty_report_payload,
    create_surveillance_case_payload,
    create_tag_order_payload,
    create_trial_site,
    create_variety,
    create_variety_trial_payload,
    draft_report,
    licensed_quota,
    make_propagator_headers,
    validate_error,
    validate_success,
)


class TestLodgingAFilingLiftsThePosture:
    """DRAFT to FILED, and what it does to the variety that owns the filing."""

    def _drafted_filing(self, api):
        variety = create_variety(
            api, denomination="Quarry Bramble", species="Rubus idaeus",
            breeder_code="QB", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        filing = create_filing(
            api, variety["id"], instrument_type="PLANT_PATENT",
            jurisdiction_code="US", term_years=20, annuity_base_cents=200000,
        )
        advance_clock(api, "2026-08-12T00:00:00Z")
        return variety, filing

    def test_lodging_stamps_the_filing_date_and_leaves_the_grant_open(self, api):
        """The filing takes the present instant as its `filed_on` and nothing
        stamps `granted_on`, because the registry has decided nothing yet.

        PRD 3.1: "Lodging the drafted application with the registry moves it `DRAFT → FILED` and stamps `filed_on` with the logical clock's present instant."

        Design: Corner/state_machines/protection_filing_draft_to_filed_lifts_posture_to_pending
        """
        _variety, filing = self._drafted_filing(api)

        filed = validate_success(api.file_protection_filing(filing["id"], BREEDER))
        assert filed["status"] == "FILED"
        assert_instant_equals(filed["filed_on"], "2026-08-12T00:00:00Z", "filed_on")
        assert filed["granted_on"] is None
        assert filed["version"] == 2

    def test_the_owning_variety_is_re_derived_to_pending(self, api):
        """The lodgement re-derives the parent's posture onto the pending branch
        and bumps the variety's own version, while the jurisdiction list stays
        empty because nothing is granted. The draft had already carried the
        posture from `UNPROTECTED` to `PENDING`, which was itself a mutation of
        the variety, so the lodgement leaves it on its third version.

        PRD 2.4: "A recomputation of a derived field is a mutation. When accepting a royalty report re-derives a propagator's royalty ledger, the propagator's `updated_at` is refreshed and its `version` increments even though no client sent a payload naming that propagator. The same holds for a variety whose protection posture or sublicense count is re-derived, a quota whose tag inventory is re-derived, and a trial site whose occupancy is re-derived."

        Design: Corner/state_machines/protection_filing_draft_to_filed_lifts_posture_to_pending
        """
        variety, filing = self._drafted_filing(api)
        drafted_parent = validate_success(api.get_variety(variety["id"], BREEDER))
        assert drafted_parent["protection_posture"] == "PENDING"
        assert drafted_parent["version"] == 2

        validate_success(api.file_protection_filing(filing["id"], BREEDER))

        refreshed = validate_success(api.get_variety(variety["id"], BREEDER))
        assert refreshed["protection_posture"] == "PENDING"
        assert refreshed["protected_jurisdictions"] == []
        assert refreshed["version"] == 3


class TestPlantingWaitsForTheCalendar:
    """The PLANNED to PLANTED precondition is a clock comparison."""

    def _trial_booked_for_the_fifth(self, api):
        variety = create_variety(
            api, denomination="Rowan Bramble", species="Rubus idaeus",
            breeder_code="RB", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        site = create_trial_site(api, site_name="Rowan Station", region_code="PNW",
                                 plot_capacity=60)
        trial = validate_success(
            api.create_variety_trial(
                create_variety_trial_payload(
                    variety["id"], site["id"], plot_count=10,
                    plant_date="2026-08-05T00:00:00Z",
                    harvest_date="2026-09-20T00:00:00Z",
                ),
                COORDINATOR,
            ),
            201,
        )
        advance_clock(api, "2026-08-04T00:00:00Z", COORDINATOR)
        return variety, site, trial

    def test_planting_a_day_early_is_refused_and_writes_nothing(self, api):
        """At 2026-08-04 the trial's own start has not arrived, so the attempt is
        refused and neither the trial nor the variety's lifecycle moves.

        PRD 3.4: "It is refused before the calendar has caught up: the logical clock's present instant must be at or after `plant_date`, and an earlier attempt is rejected with `ERR_TRIAL_DATE_NOT_REACHED` (HTTP 422)."

        Design: Corner/state_machines/variety_trial_plant_before_the_plant_date_rejected
        """
        variety, _site, trial = self._trial_booked_for_the_fifth(api)

        validate_error(
            api.plant_variety_trial(trial["id"], COORDINATOR),
            ApiErrorId.ERR_TRIAL_DATE_NOT_REACHED.value,
            422,
        )

        unchanged = validate_success(api.get_variety_trial(trial["id"], COORDINATOR))
        assert unchanged["status"] == "PLANNED"
        assert unchanged["version"] == 1
        assert validate_success(api.get_variety(variety["id"], BREEDER))[
            "lifecycle_state"
        ] == "CANDIDATE"

    def test_the_boundary_is_inclusive_at_exactly_the_plant_date(self, api):
        """Advancing to 2026-08-05 satisfies the at-or-after comparison, and the
        same call now plants, moves the candidate into trialing and re-derives the
        site's occupancy.

        PRD 3.4: "It reaches across into the variety's lifecycle dimension: a `CANDIDATE` variety moves to `IN_TRIAL`, and a `TRIAL_COMPLETE` variety whose `released_at` is still null moves back to `IN_TRIAL` — the revision loop by which a variety re-enters trialing for further regions until it is released."

        Design: Corner/state_machines/variety_trial_plant_before_the_plant_date_rejected
        """
        variety, site, trial = self._trial_booked_for_the_fifth(api)
        advance_clock(api, "2026-08-05T00:00:00Z", COORDINATOR)

        planted = validate_success(api.plant_variety_trial(trial["id"], COORDINATOR))
        assert planted["status"] == "PLANTED"

        assert validate_success(api.get_variety(variety["id"], BREEDER))[
            "lifecycle_state"
        ] == "IN_TRIAL"
        assert validate_success(api.get_trial_site(site["id"], COORDINATOR))[
            "occupied_plot_count"
        ] == 10


class TestAcceptingAReportStillInDraft:
    """accept is declared only from SUBMITTED, so DRAFT is the wrong origin."""

    def _draft_report_with_one_line(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_B",
            territory_class="DOMESTIC",
            allocated_units=5000,
            season_code="2026S1",
            basis="PER_PLANT",
            variety_overrides={
                "denomination": "Thistle Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "TB",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Thistle Farms",
        )
        report = draft_report(api, chain)
        add_line_item(api, chain, report["id"], 100)
        chain["report_id"] = report["id"]
        return chain

    def test_accepting_a_draft_report_is_refused_with_no_money_moved(self, api):
        """The report never passed through submission, so acceptance finds it past
        no origin it recognizes and no total is computed onto it.

        PRD 2.8: "Generic transition legality — `ERR_INVALID_STATE_TRANSITION` (HTTP 409), raised when the target's current state is not a declared origin state for the action being attempted."

        Design: Corner/state_machines/royalty_report_accept_from_draft_returns_409
        """
        chain = self._draft_report_with_one_line(api)

        validate_error(
            api.accept_royalty_report(chain["report_id"], OFFICER_TWO),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        report = validate_success(api.get_royalty_report(chain["report_id"], BREEDER))
        assert report["review_status"] == "DRAFT"
        assert report["final_total_cents"] == 0
        assert report["booked_amount_cents"] == 0
        assert report["accepted_at"] is None
        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["royalty_payable_cents"] == 0

    def test_settling_and_disputing_the_same_draft_are_refused_too(self, api):
        """Settlement demands an accepted review status and the dispute transition
        is declared only from ACCEPTED, so both find a draft report at the wrong
        origin as well.

        PRD 3.7: "`review_status` tracks the editorial life of the report — `DRAFT`, `SUBMITTED`, `ACCEPTED`, `DISPUTED` — and cycles."

        Design: Corner/state_machines/royalty_report_accept_from_draft_returns_409
        """
        chain = self._draft_report_with_one_line(api)

        validate_error(
            api.settle_royalty_report(chain["report_id"], OFFICER_TWO),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )
        validate_error(
            api.dispute_royalty_report(chain["report_id"], OFFICER_TWO),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        report = validate_success(api.get_royalty_report(chain["report_id"], BREEDER))
        assert report["review_status"] == "DRAFT"
        assert report["settlement_status"] == "UNSETTLED"


class TestCountersigningIsNotAbsorbing:
    """A second countersign must not overwrite the recorded signatory."""

    def _countersigned_agreement(self, api):
        propagator = create_propagator(
            api, legal_name="Willow Run Nursery", home_territory_code="US-OR"
        )
        agreement = validate_success(
            api.create_propagator_agreement(
                create_propagator_agreement_payload(
                    propagator["id"], quality_tier="TIER_B", territory_codes=["US-OR"],
                    term_start="2026-08-01T00:00:00Z", term_end="2027-08-01T00:00:00Z",
                ),
                OFFICER,
            ),
            201,
        )
        return propagator, validate_success(api.countersign_agreement(agreement["id"], OFFICER))

    def test_a_second_countersign_is_refused(self, api):
        """The agreement is already past PENDING_COUNTERSIGN, which is the only
        declared origin of the transition, so the repeat attempt is rejected.

        PRD 2.8: "It is also what makes every action safe against accidental repetition: a second identical trigger finds the record past its origin state and is rejected."

        Design: Corner/state_machines/second_countersign_on_an_active_agreement_rejected
        """
        _propagator, agreement = self._countersigned_agreement(api)

        validate_error(
            api.countersign_agreement(agreement["id"], OFFICER_THREE),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        refreshed = validate_success(api.get_propagator_agreement(agreement["id"], OFFICER))
        assert refreshed["status"] == "ACTIVE"

    def test_the_recorded_signatory_is_not_overwritten(self, api):
        """The first officer stays recorded, which matters because that field is
        what the segregation-of-duties bar reads later on.

        PRD 3.5: "The transition records the acting `X-User-ID` in `countersigned_by_user_id`, stamps `countersigned_at` with the present instant, and increments the agreement's `version`."

        Design: Corner/state_machines/second_countersign_on_an_active_agreement_rejected
        """
        _propagator, agreement = self._countersigned_agreement(api)

        validate_error(
            api.countersign_agreement(agreement["id"], OFFICER_THREE),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        refreshed = validate_success(api.get_propagator_agreement(agreement["id"], OFFICER))
        assert refreshed["countersigned_by_user_id"] == "officer-1"
        assert_instant_equals(
            refreshed["countersigned_at"], "2026-08-01T00:00:00Z", "countersigned_at"
        )
        assert refreshed["version"] == 2
        assert refreshed["reinstatement_count"] == 0


class TestDeclaredInitialStates:
    """One of every creatable row, read before any action touches it."""

    def _one_of_everything(self, api):
        variety = create_variety(
            api, denomination="Umber Bramble", species="Rubus idaeus",
            breeder_code="UB", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        filing = create_filing(
            api, variety["id"], instrument_type="PLANT_PATENT",
            jurisdiction_code="US", annuity_base_cents=200000,
        )
        site = create_trial_site(api, site_name="Umber Station", region_code="PNW",
                                 plot_capacity=60)
        trial = validate_success(
            api.create_variety_trial(
                create_variety_trial_payload(
                    variety["id"], site["id"], plot_count=10,
                    plant_date="2026-08-05T00:00:00Z",
                    harvest_date="2026-09-20T00:00:00Z",
                ),
                COORDINATOR,
            ),
            201,
        )
        propagator = create_propagator(
            api, legal_name="Umber Growers", home_territory_code="US-WA"
        )
        propagator_headers = make_propagator_headers(propagator["id"])
        drafted_agreement = validate_success(
            api.create_propagator_agreement(
                create_propagator_agreement_payload(
                    propagator["id"], quality_tier="TIER_B", territory_codes=["US-WA"],
                    term_start="2026-08-01T00:00:00Z", term_end="2027-08-01T00:00:00Z",
                ),
                OFFICER,
            ),
            201,
        )
        validate_success(api.countersign_agreement(drafted_agreement["id"], OFFICER))
        quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    drafted_agreement["id"], variety["id"], season_code="2026S1",
                    basis="PER_PLANT", territory_code="US-WA",
                    territory_class="DOMESTIC", allocated_units=5000,
                ),
                OFFICER,
            ),
            201,
        )
        tag_order = validate_success(
            api.create_tag_order(
                create_tag_order_payload(quota["id"], quota["version"],
                                         requested_units=500),
                propagator_headers,
            ),
            201,
        )
        report = validate_success(
            api.create_royalty_report(
                create_royalty_report_payload(
                    drafted_agreement["id"], period_code="2026Q3",
                    period_start="2026-08-01T00:00:00Z",
                    period_end="2026-11-01T00:00:00Z",
                    due_at="2026-11-15T00:00:00Z",
                ),
                propagator_headers,
            ),
            201,
        )
        case = validate_success(
            api.create_surveillance_case(
                create_surveillance_case_payload(
                    variety["id"], suspected_propagator_id=propagator["id"],
                    market_survey_ref="MS-2026-030",
                ),
                AUDITOR,
            ),
            201,
        )
        return {
            "variety": variety, "filing": filing, "site": site, "trial": trial,
            "propagator": propagator, "drafted_agreement": drafted_agreement,
            "quota": quota, "tag_order": tag_order, "report": report, "case": case,
        }

    def test_a_new_surveillance_case_opens_with_a_clean_evidence_slate(self, api):
        """Nothing has been sampled and no laboratory result has landed, so the
        case's two derived evidence fields sit at their declared baselines.

        PRD 3.9: "A new case starts in `OPENED` with `sampled_unit_count` 0, `max_match_confidence` 0.0000, `recovered_damages_cents`, `enforcement_cost_cents`, `enforcement_recovery_cents`, `breeder_pool_cents` and `propagator_credit_cents` all 0, null `concluded_at`, and `version` 1."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        rows = self._one_of_everything(api)
        case = rows["case"]

        assert case["status"] == "OPENED"
        assert case["sampled_unit_count"] == 0
        assert_decimal_equals(case["max_match_confidence"], "0.0000",
                              "max_match_confidence")
        assert case["concluded_at"] is None
        assert case["version"] == 1

    def test_both_parallel_dimensions_of_a_row_start_independently(self, api):
        """The variety carries a lifecycle state and a brand state, and the report
        a review state and a settlement state; each dimension opens at its own
        declared start rather than one governing the other.

        PRD 2.9: "A `RoyaltyReport` likewise has a `review_status` — `DRAFT`, `SUBMITTED`, `ACCEPTED`, `DISPUTED` — and a `settlement_status` — `UNSETTLED`, `SETTLED`, `REVERSED`."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        rows = self._one_of_everything(api)

        variety = validate_success(api.get_variety(rows["variety"]["id"], BREEDER))
        assert variety["lifecycle_state"] == "CANDIDATE"
        assert variety["brand_status"] == "BRAND_NONE"

        report = validate_success(api.get_royalty_report(rows["report"]["id"], BREEDER))
        assert report["review_status"] == "DRAFT"
        assert report["settlement_status"] == "UNSETTLED"

    def test_every_other_creatable_row_opens_where_its_machine_declares(self, api):
        """A filing opens as an unlodged draft, a trial as booked but unplanted, a
        quota live, a tag batch merely requested, and an agreement authorizing
        nothing until it is countersigned.

        PRD 3.5: "A drafted agreement starts in `PENDING_COUNTERSIGN` with `reinstatement_count` 0, `version` 1, and null `countersigned_by_user_id`, `countersigned_at` and `suspension_reason`."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
        """
        rows = self._one_of_everything(api)

        assert rows["drafted_agreement"]["status"] == "PENDING_COUNTERSIGN"
        assert rows["drafted_agreement"]["countersigned_by_user_id"] is None
        assert rows["drafted_agreement"]["reinstatement_count"] == 0

        assert validate_success(
            api.get_protection_filing(rows["filing"]["id"], BREEDER)
        )["status"] == "DRAFT"
        assert validate_success(
            api.get_variety_trial(rows["trial"]["id"], COORDINATOR)
        )["status"] == "PLANNED"
        assert validate_success(
            api.get_production_quota(rows["quota"]["id"], OFFICER)
        )["status"] == "ACTIVE"
        assert validate_success(
            api.get_tag_order(rows["tag_order"]["id"], OFFICER)
        )["status"] == "REQUESTED"
