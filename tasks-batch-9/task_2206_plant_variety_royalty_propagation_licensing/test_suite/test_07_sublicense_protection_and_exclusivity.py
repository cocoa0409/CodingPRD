"""Activating a sublicense: protection in force, and exclusive occupancy."""

from test_helpers import (
    BREEDER,
    OFFICER,
    ApiErrorId,
    active_agreement,
    active_sublicense,
    assert_instant_equals,
    create_variety,
    filed_filing,
    proposed_sublicense,
    released_variety,
    two_region_passed_trials,
    validate_error,
    validate_success,
)


class TestActivationNeedsProtectionInForce:
    """A grant may not be activated where the variety holds no granted filing."""

    def _released_variety_with_a_filed_only_filing(self, api):
        variety = create_variety(
            api, denomination="Copper Lantern", species="Malus domestica",
            breeder_code="CL", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        filing = filed_filing(
            api, variety["id"], instrument_type="PLANT_VARIETY_CERTIFICATE",
            jurisdiction_code="US", term_years=20, annuity_base_cents=481000,
        )
        two_region_passed_trials(
            api, variety["id"],
            first_site_name="Chelan Station", second_site_name="Lodi Station",
        )
        released = validate_success(api.release_variety(variety["id"], BREEDER))
        chain = active_agreement(
            api, quality_tier="TIER_A", territory_codes=["US-WA"],
            propagator_name="Copperfield Retail Group",
        )
        grant = proposed_sublicense(
            api, chain, variety["id"],
            sublicensee_name="Copperleaf Garden Supply",
            territory_code="US-WA", jurisdiction_code="US",
            exclusivity="NON_EXCLUSIVE",
            effective_date="2026-10-01T00:00:00Z",
            expiry_date="2027-06-01T00:00:00Z",
        )
        return released, filing, chain, grant

    def test_activation_is_refused_while_the_filing_is_only_filed(self, api):
        """A `FILED` application keeps the posture at PENDING with an empty
        jurisdiction list, so the grant's jurisdiction is not covered and no
        royalty-bearing sublicense may stand behind it.

        PRD 3.8: "The grant's `jurisdiction_code` must be a member of the variety's `protected_jurisdictions` — that is, the variety must hold a protection filing in status `GRANTED` or `MAINTENANCE_DUE` for that jurisdiction — because no royalty-bearing sublicense may be activated where the variety carries no enforceable right; failing this it is rejected with `ERR_PROTECTION_NOT_IN_FORCE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/sublicense_activation_requires_a_granted_protection_filing_in_that_jurisdiction
        """
        released, _filing, _chain, grant = self._released_variety_with_a_filed_only_filing(api)
        assert released["lifecycle_state"] == "RELEASED"
        assert released["protection_posture"] == "PENDING"
        assert released["protected_jurisdictions"] == []

        validate_error(
            api.activate_sublicense_grant(grant["id"], OFFICER),
            ApiErrorId.ERR_PROTECTION_NOT_IN_FORCE.value,
            422,
        )

    def test_the_refused_grant_is_left_exactly_as_proposed(self, api):
        """Nothing about the grant moves and the variety's active sublicense count
        stays at zero, because only activation counts a grant into it.

        PRD 3.8: "Activation stamps `activated_at` with the present instant, re-derives the variety's `active_sublicense_count` — the count of that variety's grants whose status is `ACTIVE` — and increments both the grant's `version` and the variety's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/sublicense_activation_requires_a_granted_protection_filing_in_that_jurisdiction
        """
        released, _filing, _chain, grant = self._released_variety_with_a_filed_only_filing(api)

        validate_error(
            api.activate_sublicense_grant(grant["id"], OFFICER),
            ApiErrorId.ERR_PROTECTION_NOT_IN_FORCE.value,
            422,
        )

        unchanged = validate_success(api.get_sublicense_grant(grant["id"], OFFICER))
        assert unchanged["status"] == "PROPOSED"
        assert unchanged["activated_at"] is None
        variety = validate_success(api.get_variety(released["id"], BREEDER))
        assert variety["active_sublicense_count"] == 0

    def test_recording_the_grant_of_protection_unblocks_activation(self, api):
        """Once the registry's decision is recorded the jurisdiction enters
        `protected_jurisdictions`, and the same activation call now succeeds and
        counts the grant.

        PRD 3.1: "Granting it moves the posture to `PROTECTED` and inserts the jurisdiction code into `protected_jurisdictions` at its lexicographic position."

        Design: Difficulty/cross_entity_state_dependency/sublicense_activation_requires_a_granted_protection_filing_in_that_jurisdiction
        """
        released, filing, _chain, grant = self._released_variety_with_a_filed_only_filing(api)

        granted = validate_success(api.grant_protection_filing(filing["id"], BREEDER))
        assert granted["status"] == "GRANTED"
        protected = validate_success(api.get_variety(released["id"], BREEDER))
        assert protected["protection_posture"] == "PROTECTED"
        assert protected["protected_jurisdictions"] == ["US"]

        activated = validate_success(api.activate_sublicense_grant(grant["id"], OFFICER))
        assert activated["status"] == "ACTIVE"
        assert_instant_equals(activated["activated_at"], "2026-09-20T00:00:00Z", "activated_at")

        variety = validate_success(api.get_variety(released["id"], BREEDER))
        assert variety["active_sublicense_count"] == 1


class TestExclusiveOccupancyWithTheThirtyDayBuffer:
    """One exclusive grant per variety and territory, plus a 30-day buffer."""

    def _incumbent_and_two_candidates(self, api):
        bundle = released_variety(
            api, denomination="Sundial Nectarine", species="Prunus persica",
            breeder_code="SN", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        variety_id = bundle["variety"]["id"]
        chain = active_agreement(
            api, quality_tier="TIER_A", territory_codes=["US-WA"],
            propagator_name="Sundial Retail Partners",
        )
        incumbent = active_sublicense(
            api, chain, variety_id,
            sublicensee_name="Meadow Lane Garden Centers",
            territory_code="US-WA", jurisdiction_code="US", exclusivity="EXCLUSIVE",
            effective_date="2026-10-01T00:00:00Z", expiry_date="2026-12-31T00:00:00Z",
        )
        inside_buffer = proposed_sublicense(
            api, chain, variety_id,
            sublicensee_name="Birch Row Nurseries",
            territory_code="US-WA", jurisdiction_code="US", exclusivity="EXCLUSIVE",
            effective_date="2027-01-15T00:00:00Z", expiry_date="2027-03-31T00:00:00Z",
        )
        beyond_buffer = proposed_sublicense(
            api, chain, variety_id,
            sublicensee_name="Stonefield Retail Group",
            territory_code="US-WA", jurisdiction_code="US", exclusivity="EXCLUSIVE",
            effective_date="2027-02-05T00:00:00Z", expiry_date="2027-04-30T00:00:00Z",
        )
        return variety_id, incumbent, inside_buffer, beyond_buffer

    def test_a_candidate_inside_the_incumbents_buffer_conflicts(self, api):
        """The incumbent's window closes on 2026-12-31 and its occupied span runs
        30 days further to 2027-01-30, which the candidate's window entered on
        2027-01-15.

        PRD 3.8: "The already-active grant's interval is then extended by 30 days — the exclusivity buffer — on **both** ends, so its occupied span starts 30 days before its `effective_date` and ends 30 days after its `expiry_date`."

        Design: Difficulty/resource_temporal_overlap/exclusive_sublicense_singleton_occupancy_with_thirty_day_buffer_on_closed_intervals
        """
        _variety_id, _incumbent, inside_buffer, _beyond = self._incumbent_and_two_candidates(api)

        validate_error(
            api.activate_sublicense_grant(inside_buffer["id"], OFFICER),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
            409,
        )

    def test_the_conflicting_candidate_stays_proposed(self, api):
        """The clash leaves the candidate unactivated and the variety still
        carrying exactly the one active grant.

        PRD 3.8: "No other sublicense grant with the same `variety_id` and the same `territory_code`, in status `ACTIVE`, may occupy an overlapping window when either that grant or the candidate has `exclusivity` `EXCLUSIVE`; the clash is rejected with `ERR_EXCLUSIVITY_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/exclusive_sublicense_singleton_occupancy_with_thirty_day_buffer_on_closed_intervals
        """
        variety_id, _incumbent, inside_buffer, _beyond = self._incumbent_and_two_candidates(api)

        validate_error(
            api.activate_sublicense_grant(inside_buffer["id"], OFFICER),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
            409,
        )

        unchanged = validate_success(api.get_sublicense_grant(inside_buffer["id"], OFFICER))
        assert unchanged["status"] == "PROPOSED"
        variety = validate_success(api.get_variety(variety_id, BREEDER))
        assert variety["active_sublicense_count"] == 1

    def test_a_candidate_clear_of_the_buffer_activates(self, api):
        """A window opening on 2027-02-05 clears the incumbent's buffered span
        entirely, and the still-proposed rival is not an occupant, so the second
        exclusive grant activates.

        PRD 3.8: "Overlap is tested between that buffered span and the candidate's **un-extended** closed interval: the buffer is applied once, to the incumbent, and never to the applicant."

        Design: Difficulty/resource_temporal_overlap/exclusive_sublicense_singleton_occupancy_with_thirty_day_buffer_on_closed_intervals
        """
        variety_id, _incumbent, _inside, beyond_buffer = self._incumbent_and_two_candidates(api)

        activated = validate_success(
            api.activate_sublicense_grant(beyond_buffer["id"], OFFICER)
        )
        assert activated["status"] == "ACTIVE"

        variety = validate_success(api.get_variety(variety_id, BREEDER))
        assert variety["active_sublicense_count"] == 2


class TestTwoNonExclusiveGrantsMayShareOneTerritory:
    """The conflict rule is conditional on the exclusivity flag, not on overlap."""

    def _two_overlapping_non_exclusive_grants(self, api):
        released = released_variety(
            api, denomination="Glenmore Bramble", species="Rubus idaeus",
            breeder_code="GM", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        variety_id = released["variety"]["id"]
        chain = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA"],
            propagator_name="Glenmore Nursery",
        )
        first = proposed_sublicense(
            api, chain, variety_id, sublicensee_name="Glenmore Retail A",
            territory_code="US-WA", jurisdiction_code="US",
            exclusivity="NON_EXCLUSIVE",
            effective_date="2026-10-01T00:00:00Z",
            expiry_date="2026-12-31T00:00:00Z",
        )
        second = proposed_sublicense(
            api, chain, variety_id, sublicensee_name="Glenmore Retail B",
            territory_code="US-WA", jurisdiction_code="US",
            exclusivity="NON_EXCLUSIVE",
            effective_date="2026-11-01T00:00:00Z",
            expiry_date="2027-01-31T00:00:00Z",
        )
        activated_first = validate_success(
            api.activate_sublicense_grant(first["id"], OFFICER)
        )
        return variety_id, chain, activated_first, second

    def test_the_second_overlapping_grant_activates_and_the_count_reaches_two(self, api):
        """The windows overlap through November and December, but neither grant is
        exclusive, so both occupy the territory and the variety counts two.

        PRD 3.8: "Two `NON_EXCLUSIVE` grants may overlap freely and never conflict with each other; the check only bites when at least one side of the pair is `EXCLUSIVE`."

        Design: Corner/validations/two_non_exclusive_grants_may_overlap_in_one_territory
        """
        variety_id, _chain, activated_first, second = self._two_overlapping_non_exclusive_grants(api)
        assert activated_first["status"] == "ACTIVE"
        assert validate_success(api.get_variety(variety_id, BREEDER))[
            "active_sublicense_count"
        ] == 1

        activated_second = validate_success(
            api.activate_sublicense_grant(second["id"], OFFICER)
        )
        assert activated_second["status"] == "ACTIVE"
        assert_instant_equals(activated_second["activated_at"], "2026-09-20T00:00:00Z",
                              "activated_at")

        variety = validate_success(api.get_variety(variety_id, BREEDER))
        assert variety["active_sublicense_count"] == 2
        assert variety["lifecycle_state"] == "RELEASED"
        assert variety["protected_jurisdictions"] == ["US"]

    def test_an_exclusive_late_comer_is_still_refused(self, api):
        """One exclusive side is enough to make the rule bite, and the incumbent's
        buffered span reaches beyond January, so the exclusive applicant clashes.

        PRD 3.8: "No other sublicense grant with the same `variety_id` and the same `territory_code`, in status `ACTIVE`, may occupy an overlapping window when either that grant or the candidate has `exclusivity` `EXCLUSIVE`; the clash is rejected with `ERR_EXCLUSIVITY_CONFLICT` (HTTP 409)."

        Design: Corner/validations/two_non_exclusive_grants_may_overlap_in_one_territory
        """
        variety_id, chain, _first, second = self._two_overlapping_non_exclusive_grants(api)
        validate_success(api.activate_sublicense_grant(second["id"], OFFICER))

        exclusive = proposed_sublicense(
            api, chain, variety_id, sublicensee_name="Glenmore Retail C",
            territory_code="US-WA", jurisdiction_code="US",
            exclusivity="EXCLUSIVE",
            effective_date="2027-01-05T00:00:00Z",
            expiry_date="2027-03-31T00:00:00Z",
        )
        validate_error(
            api.activate_sublicense_grant(exclusive["id"], OFFICER),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
            409,
        )

        assert validate_success(api.get_sublicense_grant(exclusive["id"], OFFICER))[
            "status"
        ] == "PROPOSED"
        assert validate_success(api.get_variety(variety_id, BREEDER))[
            "active_sublicense_count"
        ] == 2

    def test_live_grants_block_retirement_of_the_variety(self, api):
        """Two live downstream permissions make the count positive, and retirement
        is conditional on that count being clear.

        PRD 3.4: "It is blocked while the variety's `active_sublicense_count` is greater than 0: live nursery or retail sublicenses must be revoked or allowed to expire first, and an attempt otherwise is rejected with `ERR_ACTIVE_SUBLICENSES_EXIST` (HTTP 409)."

        Design: Corner/validations/two_non_exclusive_grants_may_overlap_in_one_territory
        """
        variety_id, _chain, _first, second = self._two_overlapping_non_exclusive_grants(api)
        validate_success(api.activate_sublicense_grant(second["id"], OFFICER))

        validate_error(
            api.retire_variety(variety_id, BREEDER),
            ApiErrorId.ERR_ACTIVE_SUBLICENSES_EXIST.value,
            409,
        )

        variety = validate_success(api.get_variety(variety_id, BREEDER))
        assert variety["lifecycle_state"] == "RELEASED"
        assert variety["active_sublicense_count"] == 2
