"""Gates that stand in front of a privileged act: release, sublicensing, recovery."""

from test_helpers import (
    AUDITOR,
    BREEDER,
    OFFICER,
    OFFICER_TWO,
    ApiErrorId,
    add_line_item,
    assert_decimal_equals,
    assert_instant_equals,
    create_filing,
    create_variety,
    draft_report,
    finalize_engagement_payload,
    granted_filing,
    active_agreement,
    licensed_quota,
    opened_audit_engagement,
    proposed_sublicense,
    two_region_passed_trials,
    validate_error,
    validate_success,
)


class TestSublicensingWaitsForCommercialRelease:
    """A protected but unreleased variety, with a grant already proposed over it."""

    def _protected_candidate_with_a_proposed_grant(self, api):
        variety = create_variety(
            api, denomination="Stonemill Bramble", species="Rubus idaeus",
            breeder_code="SM", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        granted_filing(api, variety["id"])
        chain = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA"],
            propagator_name="Stonemill Nursery", home_territory_code="US-WA",
        )
        grant = proposed_sublicense(
            api, chain, variety["id"], sublicensee_name="Stonemill Retail",
            territory_code="US-WA", jurisdiction_code="US",
            exclusivity="NON_EXCLUSIVE",
            effective_date="2026-10-01T00:00:00Z",
            expiry_date="2026-12-31T00:00:00Z",
        )
        chain.update({"variety_id": variety["id"], "grant": grant,
                      "grant_id": grant["id"]})
        return chain

    def test_the_right_is_in_force_while_the_variety_is_still_a_candidate(self, api):
        """The proposal itself is accepted and the enforceable right exists, so the
        only thing standing in the way of activation is the lifecycle dimension.

        PRD 3.8: "A new grant is created in `PROPOSED` with null `activated_at` and null `revocation_reason` and `version` 1, and creating it increments the agreement's `version` by 1."

        Design: Corner/errors/activating_a_grant_on_an_unreleased_variety_rejected
        """
        chain = self._protected_candidate_with_a_proposed_grant(api)

        assert chain["grant"]["status"] == "PROPOSED"
        variety = validate_success(api.get_variety(chain["variety_id"], BREEDER))
        assert variety["protection_posture"] == "PROTECTED"
        assert variety["protected_jurisdictions"] == ["US"]
        assert variety["lifecycle_state"] == "CANDIDATE"

    def test_activation_is_refused_on_the_lifecycle_and_not_on_the_right(self, api):
        """Because the protection check that outranks it is satisfied, the caller is
        told the variety is not released rather than that no right exists.

        PRD 3.8: "The variety's `lifecycle_state` must be `RELEASED`, since a variety still in trialling, or already retired, may not be sublicensed to nurseries or retail programmes; failing this it is rejected with `ERR_VARIETY_NOT_RELEASED` (HTTP 422)."

        Design: Corner/errors/activating_a_grant_on_an_unreleased_variety_rejected
        """
        chain = self._protected_candidate_with_a_proposed_grant(api)

        validate_error(
            api.activate_sublicense_grant(chain["grant_id"], OFFICER),
            ApiErrorId.ERR_VARIETY_NOT_RELEASED.value,
            422,
        )

    def test_the_refused_activation_leaves_the_grant_and_the_variety_alone(self, api):
        """A rejected activation is not a partial one: the grant is still merely
        proposed and the variety counts no live programme over it.

        PRD 3.8: "Activation stamps `activated_at` with the present instant, re-derives the variety's `active_sublicense_count` — the count of that variety's grants whose status is `ACTIVE` — and increments both the grant's `version` and the variety's `version` by 1."

        Design: Corner/errors/activating_a_grant_on_an_unreleased_variety_rejected
        """
        chain = self._protected_candidate_with_a_proposed_grant(api)
        validate_error(
            api.activate_sublicense_grant(chain["grant_id"], OFFICER),
            ApiErrorId.ERR_VARIETY_NOT_RELEASED.value,
            422,
        )

        grant = validate_success(api.get_sublicense_grant(chain["grant_id"], OFFICER))
        assert grant["status"] == "PROPOSED"
        assert grant["activated_at"] is None
        assert validate_success(api.get_variety(chain["variety_id"], BREEDER))[
            "active_sublicense_count"
        ] == 0


class TestReleaseNeedsAProtectionPostureAsWellAsPerformance:
    """Two passed regional trials, but no application ever made."""

    def _unprotected_trial_complete_variety(self, api):
        variety = create_variety(
            api, denomination="Thornhill Bramble", species="Rubus idaeus",
            breeder_code="TH", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        two_region_passed_trials(api, variety["id"],
                                 first_site_name="Thornhill North",
                                 second_site_name="Thornhill South")
        return variety

    def test_two_of_the_three_criteria_are_already_satisfied(self, api):
        """The performance side of the test is met twice over — two distinct regions
        and an index above the floor — while the posture is the one that is not.

        PRD 3.1: "Otherwise the posture is `UNPROTECTED`."

        Design: Corner/errors/releasing_a_variety_with_no_protection_filing_rejected
        """
        variety = self._unprotected_trial_complete_variety(api)

        current = validate_success(api.get_variety(variety["id"], BREEDER))
        assert current["lifecycle_state"] == "TRIAL_COMPLETE"
        assert current["passed_trial_region_count"] == 2
        assert_decimal_equals(current["regional_performance_index"], "78.50",
                              "regional_performance_index")
        assert current["protection_posture"] == "UNPROTECTED"

    def test_an_unprotected_variety_is_never_released(self, api):
        """All three criteria must hold together, so the missing enforceable right
        blocks the release and the lifecycle does not move.

        PRD 3.1: "A variety whose posture is `UNPROTECTED` or `LAPSED_PROTECTION` is never released, because there would be no enforceable right behind the royalty. Any of the three failing yields `ERR_RELEASE_CRITERIA_NOT_MET` (HTTP 422)."

        Design: Corner/errors/releasing_a_variety_with_no_protection_filing_rejected
        """
        variety = self._unprotected_trial_complete_variety(api)

        validate_error(
            api.release_variety(variety["id"], BREEDER),
            ApiErrorId.ERR_RELEASE_CRITERIA_NOT_MET.value,
            422,
        )

        blocked = validate_success(api.get_variety(variety["id"], BREEDER))
        assert blocked["lifecycle_state"] == "TRIAL_COMPLETE"
        assert blocked["released_at"] is None

    def test_a_pending_application_is_enough_to_unblock_the_release(self, api):
        """The criterion admits `PENDING` as well as `PROTECTED`, so merely lodging
        the application — with no grant at all — carries the same call through, and
        the release is stamped with the clock's present instant.

        PRD 3.1: "Three release criteria must all hold at that moment: `passed_trial_region_count` must be at least 2, so that performance has been demonstrated in at least two distinct growing regions; `regional_performance_index` must be at least 72.00; and `protection_posture` must be either `PENDING` or `PROTECTED`."

        Design: Corner/errors/releasing_a_variety_with_no_protection_filing_rejected
        """
        variety = self._unprotected_trial_complete_variety(api)
        filing = create_filing(api, variety["id"], instrument_type="PLANT_PATENT",
                               jurisdiction_code="US", annuity_base_cents=200000)
        validate_success(api.file_protection_filing(filing["id"], BREEDER))
        assert validate_success(api.get_variety(variety["id"], BREEDER))[
            "protection_posture"
        ] == "PENDING"

        released = validate_success(api.release_variety(variety["id"], BREEDER))
        assert released["lifecycle_state"] == "RELEASED"
        assert_instant_equals(released["released_at"], "2026-09-20T00:00:00Z",
                              "released_at")


class TestAnUnresolvedMaterialFindingBlocksRecoveryOnItsOwn:
    """A single material finding: 25 points, which still clears the score gate."""

    def _suspended_by_a_material_finding(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Umbra Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "UM",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Umbra Nursery",
            home_territory_code="US-WA",
        )
        report = draft_report(
            api, chain, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
            due_at="2026-11-15T00:00:00Z",
        )
        add_line_item(api, chain, report["id"], 100)
        validate_success(
            api.submit_royalty_report(report["id"], chain["propagator_headers"])
        )
        validate_success(api.accept_royalty_report(report["id"], OFFICER_TWO))
        chain["report_id"] = report["id"]
        engagement = opened_audit_engagement(api, chain)
        chain["engagement"] = validate_success(
            api.finalize_audit_engagement(
                engagement["id"],
                finalize_engagement_payload("MATERIAL", underreported_units=50),
                AUDITOR,
            )
        )
        return chain

    def test_the_finding_disputes_the_report_and_unbooks_the_money(self, api):
        """Issuing the finding forces the accepted report back into dispute, which
        zeroes the booked amount and with it the propagator's payable.

        PRD 3.9: "Independently of severity within the findings branch, when the audited report is still `ACCEPTED` and still `UNSETTLED` it moves to `DISPUTED` with `booked_amount_cents` set to 0, and that un-booking in turn causes the propagator's `royalty_payable_cents` to be re-derived; a report already `SETTLED` or `REVERSED` is left alone, though the engagement still reaches `FINDINGS_ISSUED` and the penalty still lands."

        Design: Corner/errors/reinstating_with_an_unresolved_material_finding_rejected
        """
        chain = self._suspended_by_a_material_finding(api)

        assert chain["engagement"]["status"] == "FINDINGS_ISSUED"
        report = validate_success(api.get_royalty_report(chain["report_id"], OFFICER))
        assert report["review_status"] == "DISPUTED"
        assert report["booked_amount_cents"] == 0
        assert validate_success(api.get_propagator(chain["propagator_id"], OFFICER))[
            "royalty_payable_cents"
        ] == 0

    def test_the_score_falls_only_to_seventy_five_which_clears_its_gate(self, api):
        """One material finding costs 25 points and the report was on time, so the
        rolling score lands above the reinstatement threshold while the finding
        itself is counted as outstanding, and the licence is suspended for it.

        PRD 2.11: "An audit engagement that issued a `MATERIAL` finding contributes **25 points**, attributed to the instant the engagement was finalized."

        Design: Corner/errors/reinstating_with_an_unresolved_material_finding_rejected
        """
        chain = self._suspended_by_a_material_finding(api)

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["compliance_score"] == 75
        assert propagator["material_audit_finding_count"] == 1

        agreement = validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )
        assert agreement["status"] == "SUSPENDED"
        assert agreement["suspension_reason"] == "AUDIT_FINDING"
        assert validate_success(api.get_production_quota(chain["quota_id"], OFFICER))[
            "status"
        ] == "FROZEN"

    def test_reinstatement_is_refused_on_the_finding_alone(self, api):
        """The two eligibility gates are independent: the score gate passes at 75 and
        the outstanding finding is what refuses the recovery, leaving the licence
        suspended, its lap counter at zero and the quota still frozen.

        PRD 3.5: "The propagator's `material_audit_finding_count` must be exactly 0, and any outstanding material finding is rejected with `ERR_MATERIAL_FINDING_UNRESOLVED` (HTTP 422) — a propagator carrying an unresolved material finding cannot be reinstated even when its rolling score has fully recovered."

        Design: Corner/errors/reinstating_with_an_unresolved_material_finding_rejected
        """
        chain = self._suspended_by_a_material_finding(api)

        validate_error(
            api.reinstate_agreement(chain["agreement_id"], OFFICER),
            ApiErrorId.ERR_MATERIAL_FINDING_UNRESOLVED.value,
            422,
        )

        agreement = validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )
        assert agreement["status"] == "SUSPENDED"
        assert agreement["reinstatement_count"] == 0
        assert validate_success(api.get_production_quota(chain["quota_id"], OFFICER))[
            "status"
        ] == "FROZEN"
