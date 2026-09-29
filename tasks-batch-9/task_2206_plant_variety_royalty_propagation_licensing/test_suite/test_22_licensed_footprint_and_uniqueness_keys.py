"""The licensed footprint, and the two composite keys that stop double allocation."""

from test_helpers import (
    OFFICER,
    ApiErrorId,
    active_agreement,
    create_production_quota_payload,
    create_royalty_report_payload,
    create_sublicense_grant_payload,
    create_variety,
    read_version,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOnlyTheAgreementsOwnTerritoriesMayBeAllocated:
    """A nursery in US-ID holding a licence for US-WA and US-OR only."""

    def _agreement_for_two_territories(self, api):
        variety = create_variety(
            api, denomination="Vantage Bramble", species="Rubus idaeus",
            breeder_code="VG", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        chain = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA", "US-OR"],
            propagator_name="Vantage Nursery", home_territory_code="US-ID",
        )
        chain.update({"variety": variety, "variety_id": variety["id"]})
        return chain

    def test_the_home_territory_counts_for_nothing_if_it_is_not_licensed(self, api):
        """The footprint is the agreement's list and nothing else, so a quota for the
        nursery's own home territory is refused and no quota is written.

        PRD 3.6: "The destination territory must sit inside the agreement's licensed footprint: the supplied `territory_code` must be a member of the agreement's `territory_codes`, and a territory outside that list is rejected with `ERR_TERRITORY_NOT_LICENSED` (HTTP 422)."

        Design: Corner/errors/quota_for_an_unlicensed_territory_rejected
        """
        chain = self._agreement_for_two_territories(api)

        validate_error(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], chain["variety_id"],
                    season_code="2026S1", basis="PER_PLANT",
                    territory_code="US-ID", territory_class="DOMESTIC",
                    allocated_units=5000,
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_TERRITORY_NOT_LICENSED.value,
            422,
        )

        _rows, meta = validate_paginated(api.list_production_quotas(OFFICER))
        assert meta["total_count"] == 0

    def test_a_licensed_territory_allocates_normally(self, api):
        """Either member of the list is acceptable, so the identical allocation for
        the second licensed territory opens an active quota.

        PRD 3.6: "A new quota starts `ACTIVE` with `tags_committed_units` 0, `tags_activated_units` 0, `units_available` equal to `allocated_units`, and `version` 1."

        Design: Corner/errors/quota_for_an_unlicensed_territory_rejected
        """
        chain = self._agreement_for_two_territories(api)

        quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], chain["variety_id"],
                    season_code="2026S1", basis="PER_PLANT",
                    territory_code="US-OR", territory_class="DOMESTIC",
                    allocated_units=5000,
                ),
                OFFICER,
            ),
            201,
        )
        assert quota["status"] == "ACTIVE"
        assert quota["territory_code"] == "US-OR"

    def test_the_same_footprint_rule_guards_sublicensing(self, api):
        """The rule is shared between the two downstream writes, so a grant for the
        unlicensed territory is refused with the very same code.

        PRD 3.8: "The `territory_code` must be a member of the agreement's `territory_codes`, exactly as for production quotas, failing which it is rejected with `ERR_TERRITORY_NOT_LICENSED`."

        Design: Corner/errors/quota_for_an_unlicensed_territory_rejected
        """
        chain = self._agreement_for_two_territories(api)
        agreement_version = read_version(api, api.get_propagator_agreement,
                                         chain["agreement_id"], OFFICER)

        validate_error(
            api.create_sublicense_grant(
                create_sublicense_grant_payload(
                    chain["agreement_id"], chain["variety_id"], agreement_version,
                    sublicensee_name="Vantage Retail", territory_code="US-ID",
                    jurisdiction_code="US", exclusivity="NON_EXCLUSIVE",
                    effective_date="2026-10-01T00:00:00Z",
                    expiry_date="2026-12-31T00:00:00Z",
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_TERRITORY_NOT_LICENSED.value,
            422,
        )


class TestTheTwoCompositeKeysHaveDeliberatelyDifferentScopes:
    """One live quota for 2026S1 / US-WA, and one report for 2026Q3."""

    def _one_quota_and_one_report(self, api):
        variety = create_variety(
            api, denomination="Westmark Bramble", species="Rubus idaeus",
            breeder_code="WM", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        chain = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA", "US-OR"],
            propagator_name="Westmark Nursery", home_territory_code="US-WA",
        )
        chain["variety_id"] = variety["id"]
        chain["quota"] = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], variety["id"], season_code="2026S1",
                    basis="PER_PLANT", territory_code="US-WA",
                    territory_class="DOMESTIC", allocated_units=5000,
                ),
                OFFICER,
            ),
            201,
        )
        chain["report"] = validate_success(
            api.create_royalty_report(
                create_royalty_report_payload(
                    chain["agreement_id"], period_code="2026Q3",
                    period_start="2026-08-01T00:00:00Z",
                    period_end="2026-11-01T00:00:00Z",
                    due_at="2026-11-15T00:00:00Z",
                ),
                chain["propagator_headers"],
            ),
            201,
        )
        return chain

    def test_a_different_basis_and_class_do_not_make_a_new_quota_key(self, api):
        """The key is the four-part tuple only, so changing the pricing basis and the
        territory class leaves the same allocation and it is refused.

        PRD 3.6: "Uniqueness is scoped to live quotas only: at most one quota may exist for a given combination of agreement, variety, season code and territory code while its status is `ACTIVE` or `FROZEN`, and a duplicate is rejected with `ERR_DUPLICATE_QUOTA_SEASON` (HTTP 409)."

        Design: Corner/errors/duplicate_quota_season_and_duplicate_report_period_rejected
        """
        chain = self._one_quota_and_one_report(api)

        validate_error(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], chain["variety_id"], season_code="2026S1",
                    basis="PER_ACRE", territory_code="US-WA",
                    territory_class="EXPORT", allocated_units=900,
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_DUPLICATE_QUOTA_SEASON.value,
            409,
        )

        _rows, meta = validate_paginated(api.list_production_quotas(OFFICER))
        assert meta["total_count"] == 1

    def test_a_different_window_does_not_make_a_new_report_key(self, api):
        """The report key is the agreement and the period code alone, so restating
        the period under different dates is the same period and is refused.

        PRD 3.7: "At most one report may exist for a given combination of agreement and `period_code`, regardless of either state dimension, and a second one is rejected with `ERR_DUPLICATE_REPORT_PERIOD` (HTTP 409): corrections travel the dispute-and-revise loop below, never a duplicate report for the same period."

        Design: Corner/errors/duplicate_quota_season_and_duplicate_report_period_rejected
        """
        chain = self._one_quota_and_one_report(api)

        validate_error(
            api.create_royalty_report(
                create_royalty_report_payload(
                    chain["agreement_id"], period_code="2026Q3",
                    period_start="2026-08-01T00:00:00Z",
                    period_end="2026-09-01T00:00:00Z",
                    due_at="2026-09-15T00:00:00Z",
                ),
                chain["propagator_headers"],
            ),
            ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD.value,
            409,
        )

        _rows, meta = validate_paginated(api.list_royalty_reports(OFFICER))
        assert meta["total_count"] == 1

    def test_the_territory_is_part_of_one_key_and_the_period_code_of_the_other(self, api):
        """Changing a component that genuinely belongs to the key opens a second
        record: the same season in another licensed territory, and another period
        under the same licence, are both accepted.

        PRD 3.6: "A `CLOSED` quota does not block a replacement for the same combination."

        Design: Corner/errors/duplicate_quota_season_and_duplicate_report_period_rejected
        """
        chain = self._one_quota_and_one_report(api)

        second_quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], chain["variety_id"], season_code="2026S1",
                    basis="PER_PLANT", territory_code="US-OR",
                    territory_class="DOMESTIC", allocated_units=5000,
                ),
                OFFICER,
            ),
            201,
        )
        assert second_quota["status"] == "ACTIVE"

        second_report = validate_success(
            api.create_royalty_report(
                create_royalty_report_payload(
                    chain["agreement_id"], period_code="2026Q4",
                    period_start="2026-11-01T00:00:00Z",
                    period_end="2027-02-01T00:00:00Z",
                    due_at="2027-02-15T00:00:00Z",
                ),
                chain["propagator_headers"],
            ),
            201,
        )
        assert second_report["review_status"] == "DRAFT"

        _quotas, quota_meta = validate_paginated(api.list_production_quotas(OFFICER))
        assert quota_meta["total_count"] == 2
        _reports, report_meta = validate_paginated(api.list_royalty_reports(OFFICER))
        assert report_meta["total_count"] == 2
