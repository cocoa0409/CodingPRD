"""Cascades down the ownership chain, and the terminal states that stop them."""

from test_helpers import (
    AUDITOR,
    BREEDER,
    COORDINATOR,
    OFFICER,
    ApiErrorId,
    active_agreement,
    advance_clock,
    assert_decimal_equals,
    assert_instant_equals,
    assert_quota_inventory_invariant,
    brand_register_payload,
    create_filing,
    create_genetic_test_payload,
    create_production_quota_payload,
    create_tag_order_payload,
    create_trial_site,
    create_variety,
    create_variety_trial_payload,
    evaluate_trial_payload,
    licensed_quota,
    read_version,
    reconcile_tag_order_payload,
    sampled_case,
    validate_error,
    validate_success,
)

#: Observations that weight to a performance index of exactly 82.00:
#: 85 x 0.40 = 34.00 plus three components of 80 x 0.20 = 16.00 each, at a
#: propagation pass rate of 1.0000.
_EVEN_82 = {
    "yield_index": 85.00,
    "vigor_score": 80.00,
    "uniformity_score": 80.00,
    "disease_resistance_score": 80.00,
    "propagation_pass_rate": 1.0000,
}


def _released_variety(api, denomination, breeder_code, north_site, south_site):
    """A variety released on the strength of two 82.00-index regional trials,
    with its protection application lodged but not yet granted."""
    variety = create_variety(
        api, denomination=denomination, species="Rubus idaeus",
        breeder_code=breeder_code, base_royalty_cents_per_plant=35,
        base_royalty_cents_per_acre=1200,
    )
    filing = create_filing(
        api, variety["id"], instrument_type="PLANT_PATENT",
        jurisdiction_code="US", annuity_base_cents=200000,
    )
    validate_success(api.file_protection_filing(filing["id"], BREEDER))
    sites = [
        create_trial_site(api, site_name=north_site, region_code="PNW", plot_capacity=60),
        create_trial_site(api, site_name=south_site, region_code="CAL", plot_capacity=60),
    ]
    trials = [
        validate_success(
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
        for site in sites
    ]
    advance_clock(api, "2026-08-05T00:00:00Z", COORDINATOR)
    for trial in trials:
        validate_success(api.plant_variety_trial(trial["id"], COORDINATOR))
    advance_clock(api, "2026-09-20T00:00:00Z", COORDINATOR)
    evaluated = [
        validate_success(
            api.evaluate_variety_trial(
                trial["id"], evaluate_trial_payload(**_EVEN_82), COORDINATOR
            )
        )
        for trial in trials
    ]
    certified = [
        validate_success(api.certify_variety_trial(trial["id"], BREEDER))
        for trial in trials
    ]
    released = validate_success(api.release_variety(variety["id"], BREEDER))
    return {"variety": released, "variety_id": variety["id"], "filing": filing,
            "sites": sites, "evaluated": evaluated, "certified": certified}


class TestRetiredIsTheLifecycleTerminal:
    """Once retired, no further lifecycle trigger is accepted at all."""

    def _retired_variety(self, api):
        bundle = _released_variety(api, "Vesper Bramble", "VB", "Vesper North",
                                   "Vesper South")
        bundle["retired"] = validate_success(
            api.retire_variety(bundle["variety_id"], BREEDER)
        )
        return bundle

    def test_two_even_regional_trials_carry_the_variety_to_release(self, api):
        """Each trial indexes at exactly 82.00 and both pass, so the region count
        reaches two and the mean of the two indices is the same 82.00 that clears
        the release floor.

        PRD 3.4: "`regional_performance_index` becomes the mean of `performance_index` over exactly those `PASSED` trials, rounded half up to 2 decimal places — and 0.00 when the variety has no passed trials at all."

        Design: Corner/state_machines/retired_variety_rejects_every_further_lifecycle_trigger
        """
        bundle = _released_variety(api, "Vesper Bramble", "VB", "Vesper North",
                                   "Vesper South")

        first = validate_success(
            api.get_variety_trial(bundle["certified"][0]["id"], COORDINATOR)
        )
        assert first["status"] == "PASSED"
        assert_decimal_equals(first["performance_index"], "82.00", "performance_index")

        variety = validate_success(api.get_variety(bundle["variety_id"], BREEDER))
        assert variety["lifecycle_state"] == "RELEASED"
        assert variety["passed_trial_region_count"] == 2
        assert_decimal_equals(variety["regional_performance_index"], "82.00",
                              "regional_performance_index")

    def test_re_releasing_a_retired_variety_reports_the_terminal_state(self, api):
        """The retired lifecycle is a declared terminal state, so the specific
        terminal code is returned rather than the generic transition code, and the
        rejected call writes nothing.

        PRD 2.8: "Terminal-state rejection — `ERR_TERMINAL_STATE` (HTTP 409). Before the generic transition check, the server asks whether the target is already in a terminal state of the machine this action drives, so that a terminal resource yields the specific terminal code."

        Design: Corner/state_machines/retired_variety_rejects_every_further_lifecycle_trigger
        """
        bundle = self._retired_variety(api)
        assert bundle["retired"]["lifecycle_state"] == "RETIRED"

        validate_error(
            api.release_variety(bundle["variety_id"], BREEDER),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            409,
        )

        unchanged = validate_success(api.get_variety(bundle["variety_id"], BREEDER))
        assert unchanged["lifecycle_state"] == "RETIRED"
        assert unchanged["version"] == bundle["retired"]["version"]

    def test_the_brand_dimension_is_not_locked_down_by_retirement(self, api):
        """Retiring again is refused for the same reason, yet the mark may still be
        registered, because the lockdown belongs to the lifecycle machine alone.

        PRD 2.9: "A variety still in `CANDIDATE` may hold a registered mark, and a `RETIRED` variety may still hold one; abandoning the mark leaves the lifecycle untouched, and retiring the variety leaves the mark untouched."

        Design: Corner/state_machines/retired_variety_rejects_every_further_lifecycle_trigger
        """
        bundle = self._retired_variety(api)

        validate_error(
            api.retire_variety(bundle["variety_id"], BREEDER),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            409,
        )

        registered = validate_success(
            api.brand_register_variety(
                bundle["variety_id"],
                brand_register_payload(brand_mark_text="VESPERCREST",
                                       brand_renewal_due_at="2026-12-01T00:00:00Z"),
                BREEDER,
            )
        )
        assert registered["brand_status"] == "BRAND_REGISTERED"
        assert registered["lifecycle_state"] == "RETIRED"


class TestRetirementCascadesToQuotasThenToRequestedTags:
    """Variety, then its live quotas, then those quotas' pending tag batches."""

    def _released_variety_with_a_mixed_tag_history(self, api):
        bundle = _released_variety(api, "Zephyr Bramble", "ZB", "Zephyr North",
                                   "Zephyr South")
        chain = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA"],
            propagator_name="Zephyr Growers",
        )
        quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], bundle["variety_id"], season_code="2026S1",
                    basis="PER_PLANT", territory_code="US-WA",
                    territory_class="DOMESTIC", allocated_units=5000,
                ),
                OFFICER,
            ),
            201,
        )
        first = validate_success(
            api.create_tag_order(
                create_tag_order_payload(quota["id"], quota["version"],
                                         requested_units=400),
                chain["propagator_headers"],
            ),
            201,
        )
        validate_success(api.issue_tag_order(first["id"], OFFICER))
        validate_success(
            api.reconcile_tag_order(first["id"], reconcile_tag_order_payload(400),
                                    chain["propagator_headers"])
        )
        second = validate_success(
            api.create_tag_order(
                create_tag_order_payload(
                    quota["id"],
                    read_version(api, api.get_production_quota, quota["id"], OFFICER),
                    requested_units=600,
                ),
                chain["propagator_headers"],
            ),
            201,
        )
        bundle.update({"chain": chain, "quota_id": quota["id"],
                       "reconciled_id": first["id"], "requested_id": second["id"]})
        return bundle

    def test_the_chain_stands_live_before_the_retirement(self, api):
        """The quota is live with 400 units committed and activated by the settled
        batch, and the second batch is only requested, so it holds nothing.

        PRD 3.6: "`tags_activated_units` is the sum of `activated_units` over the quota's tag orders whose status is `RECONCILED` alone."

        Design: Corner/state_machines/retiring_a_variety_cascades_to_quotas_then_to_requested_tag_orders
        """
        bundle = self._released_variety_with_a_mixed_tag_history(api)

        quota = validate_success(api.get_production_quota(bundle["quota_id"], OFFICER))
        assert quota["status"] == "ACTIVE"
        assert quota["tags_committed_units"] == 400
        assert quota["units_available"] == 4600
        assert quota["tags_activated_units"] == 400
        assert_quota_inventory_invariant(quota)

        assert validate_success(
            api.get_tag_order(bundle["reconciled_id"], OFFICER)
        )["status"] == "RECONCILED"
        assert validate_success(
            api.get_tag_order(bundle["requested_id"], OFFICER)
        )["status"] == "REQUESTED"

    def test_level_one_closes_the_varietys_live_quota(self, api):
        """Retirement is accepted with no live sublicense standing in its way, and
        the first cascade level closes the quota that authorized production.

        PRD 3.4: "Level one, caused by the retirement, closes every production quota of that variety whose status is `ACTIVE` or `FROZEN`, moving each to `CLOSED`; those quotas are processed by `created_at` ascending, ties broken by `season_code` ascending."

        Design: Corner/state_machines/retiring_a_variety_cascades_to_quotas_then_to_requested_tag_orders
        """
        bundle = self._released_variety_with_a_mixed_tag_history(api)

        retired = validate_success(api.retire_variety(bundle["variety_id"], BREEDER))
        assert retired["lifecycle_state"] == "RETIRED"

        quota = validate_success(api.get_production_quota(bundle["quota_id"], OFFICER))
        assert quota["status"] == "CLOSED"

    def test_level_two_voids_only_the_batch_that_was_still_pending(self, api):
        """Each closure voids the quota's requested batches for their full
        requested quantity, while the already-reconciled batch keeps its terminal
        status and records no voided units.

        PRD 3.4: "Level two, caused by each quota closure, voids every tag order of that quota whose status is `REQUESTED`, setting each one's `voided_units` to its `requested_units`."

        Design: Corner/state_machines/retiring_a_variety_cascades_to_quotas_then_to_requested_tag_orders
        """
        bundle = self._released_variety_with_a_mixed_tag_history(api)
        before = validate_success(api.get_tag_order(bundle["requested_id"], OFFICER))

        validate_success(api.retire_variety(bundle["variety_id"], BREEDER))

        voided = validate_success(api.get_tag_order(bundle["requested_id"], OFFICER))
        assert voided["status"] == "VOIDED"
        assert voided["voided_units"] == 600
        assert voided["version"] == before["version"] + 1

        survivor = validate_success(api.get_tag_order(bundle["reconciled_id"], OFFICER))
        assert survivor["status"] == "RECONCILED"
        assert survivor["voided_units"] == 0


class TestTerminationClosesEveryQuotaButVoidsOnlyPendingTags:
    """The level-two cascade is conditional on each child's own state."""

    def _suspended_agreement_with_two_quotas(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_B",
            territory_class="DOMESTIC",
            allocated_units=5000,
            season_code="2026S1",
            basis="PER_PLANT",
            variety_overrides={
                "denomination": "Amberlight Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "AL",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Amberlight Nursery",
        )
        second_quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], chain["variety_id"], season_code="2026S2",
                    basis="PER_PLANT", territory_code="US-WA",
                    territory_class="DOMESTIC", allocated_units=3000,
                ),
                OFFICER,
            ),
            201,
        )
        issued = validate_success(
            api.create_tag_order(
                create_tag_order_payload(
                    chain["quota_id"],
                    read_version(api, api.get_production_quota, chain["quota_id"], OFFICER),
                    requested_units=400,
                ),
                chain["propagator_headers"],
            ),
            201,
        )
        validate_success(api.issue_tag_order(issued["id"], OFFICER))
        requested = validate_success(
            api.create_tag_order(
                create_tag_order_payload(
                    chain["quota_id"],
                    read_version(api, api.get_production_quota, chain["quota_id"], OFFICER),
                    requested_units=600,
                ),
                chain["propagator_headers"],
            ),
            201,
        )
        validate_success(api.suspend_agreement(chain["agreement_id"], OFFICER))
        chain.update({"second_quota_id": second_quota["id"], "issued_id": issued["id"],
                      "requested_id": requested["id"]})
        return chain

    def test_the_manual_suspension_freezes_both_quotas_first(self, api):
        """Suspending by hand records the manual reason and carries its own cascade
        over every live quota of the agreement, whatever season it covers.

        PRD 3.5: "Whichever direction it arrives from, suspension carries the same cascade. Every production quota of that agreement whose status is `ACTIVE` moves to `FROZEN`, processed by `created_at` ascending with ties broken by `season_code` ascending."

        Design: Corner/state_machines/agreement_termination_voids_only_the_requested_tag_orders
        """
        chain = self._suspended_agreement_with_two_quotas(api)

        agreement = validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )
        assert agreement["status"] == "SUSPENDED"
        assert agreement["suspension_reason"] == "MANUAL"

        assert validate_success(
            api.get_production_quota(chain["quota_id"], OFFICER)
        )["status"] == "FROZEN"
        assert validate_success(
            api.get_production_quota(chain["second_quota_id"], OFFICER)
        )["status"] == "FROZEN"

    def test_termination_closes_the_frozen_quotas_on_both_seasons(self, api):
        """Termination is reachable from the suspended state and its quota branch
        closes frozen quotas just as it closes active ones.

        PRD 3.5: "On the quota branch, level one closes every production quota of the agreement whose status is `ACTIVE` or `FROZEN`, moving each to `CLOSED`; level two, caused by each closure, voids every tag order of that quota whose status is `REQUESTED`, setting each one's `voided_units` to its `requested_units`."

        Design: Corner/state_machines/agreement_termination_voids_only_the_requested_tag_orders
        """
        chain = self._suspended_agreement_with_two_quotas(api)

        terminated = validate_success(api.terminate_agreement(chain["agreement_id"], OFFICER))
        assert terminated["status"] == "TERMINATED"

        assert validate_success(
            api.get_production_quota(chain["quota_id"], OFFICER)
        )["status"] == "CLOSED"
        assert validate_success(
            api.get_production_quota(chain["second_quota_id"], OFFICER)
        )["status"] == "CLOSED"

    def test_the_issued_batch_survives_and_keeps_its_commitment(self, api):
        """Only the requested batch is voided; the issued one is left issued, so
        the closed quota's committed figure still reflects the tags that were
        actually printed.

        PRD 3.6: "A `VOIDED` order is excluded from both sums, which is exactly what makes voiding the compensating action for issuing."

        Design: Corner/state_machines/agreement_termination_voids_only_the_requested_tag_orders
        """
        chain = self._suspended_agreement_with_two_quotas(api)

        validate_success(api.terminate_agreement(chain["agreement_id"], OFFICER))

        voided = validate_success(api.get_tag_order(chain["requested_id"], OFFICER))
        assert voided["status"] == "VOIDED"
        assert voided["voided_units"] == 600
        survivor = validate_success(api.get_tag_order(chain["issued_id"], OFFICER))
        assert survivor["status"] == "ISSUED"
        assert survivor["voided_units"] == 0

        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["tags_committed_units"] == 400
        assert quota["units_available"] == 4600
        assert_quota_inventory_invariant(quota)


class TestConfirmingAMatchReachesAcrossToThePropagator:
    """A case transition writes compliance fields on a different entity."""

    def _case_ready_to_conclude(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_B",
            territory_class="DOMESTIC",
            allocated_units=5000,
            season_code="2026S1",
            basis="PER_PLANT",
            variety_overrides={
                "denomination": "Bluecrest Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "BC",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Bluecrest Nursery",
        )
        case = sampled_case(
            api, chain["variety_id"], sampled_unit_count=40,
            suspected_propagator_id=chain["propagator_id"],
            market_survey_ref="MS-2026-041",
        )
        validate_success(
            api.create_genetic_test(
                case["id"], create_genetic_test_payload(0.9600), AUDITOR
            ),
            201,
        )
        chain["case_id"] = case["id"]
        return chain

    def test_the_server_chooses_the_confirmed_branch_and_stamps_the_instant(self, api):
        """A single result at 0.9600 puts the case's highest confidence above the
        0.9000 threshold, so the fork lands on the confirmed side without the
        caller naming a branch.

        PRD 3.9: "When `max_match_confidence` is 0.9000 or higher, the case moves `TESTING → MATCH_CONFIRMED`; when it is strictly below 0.9000, the case moves `TESTING → NO_MATCH`."

        Design: Corner/state_machines/confirming_a_genetic_match_updates_the_propagator_compliance_fields
        """
        chain = self._case_ready_to_conclude(api)
        before = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert before["compliance_score"] == 100
        assert before["lifetime_compliance_score"] == 100

        concluded = validate_success(api.conclude_testing(chain["case_id"], AUDITOR))
        assert concluded["status"] == "MATCH_CONFIRMED"
        assert_instant_equals(concluded["concluded_at"], "2026-08-01T00:00:00Z",
                              "concluded_at")
        assert_decimal_equals(concluded["max_match_confidence"], "0.9600",
                              "max_match_confidence")

    def test_the_named_suspect_takes_the_thirty_point_penalty(self, api):
        """The confirmed match materializes one thirty-point event against the
        named propagator, taking both scores from the clean baseline down to 70.

        PRD 2.11: "A surveillance case whose testing concluded in a confirmed genetic match against a named suspect contributes **30 points**, attributed to the instant testing was concluded."

        Design: Corner/state_machines/confirming_a_genetic_match_updates_the_propagator_compliance_fields
        """
        chain = self._case_ready_to_conclude(api)
        before = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))

        validate_success(api.conclude_testing(chain["case_id"], AUDITOR))

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["compliance_score"] == 70
        assert propagator["lifetime_compliance_score"] == 70
        assert propagator["version"] == before["version"] + 1

    def test_a_score_of_exactly_seventy_does_not_suspend_anything(self, api):
        """The suspension trigger is a strict comparison, so landing exactly on 70
        stops the cascade at level one: the licence stays live and its quota stays
        unfrozen.

        PRD 2.11: "Whenever `compliance_score` is recomputed and lands **strictly below 70**, every `ACTIVE` agreement of that propagator is suspended with `suspension_reason` set to `COMPLIANCE_SCORE_BREACH`, and each suspension in turn freezes that agreement's `ACTIVE` quotas."

        Design: Corner/state_machines/confirming_a_genetic_match_updates_the_propagator_compliance_fields
        """
        chain = self._case_ready_to_conclude(api)

        validate_success(api.conclude_testing(chain["case_id"], AUDITOR))

        agreement = validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )
        assert agreement["status"] == "ACTIVE"
        assert agreement["suspension_reason"] is None
        assert validate_success(
            api.get_production_quota(chain["quota_id"], OFFICER)
        )["status"] == "ACTIVE"
